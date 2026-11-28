"""Full evaluation. Run with `make eval`; writes eval_report.json.

Each question goes through the same pipeline the API uses. Retrieval is also run
on its own, so a wrong answer can be traced to retrieval (gold page never
retrieved) or to generation and the gates (gold page retrieved, answer still wrong).

Scoring is deterministic, with no LLM judge:
  - should refuse (unanswerable, false_premise): correct when refused with no citations
  - should answer: correct when not refused and every `must_include` string is in the
    answer text (citation markers stripped first, so "1.27" inside a chunk id
    doesn't count)
  - version_conflict additionally needs both releases named and cited

Hallucination, as defined in the README: a response that is not a refusal and is
wrong, i.e. it answers a question that should have been refused, or it misses a
fact the docs state. A refusal is never a hallucination; it is scored as a false
refusal instead.
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
from pathlib import Path
from typing import Any

import psutil

from app.config import settings
from eval.metrics import gold_hit, gold_hit_every_version, load_questions, percentile, rate
from rag import llm
from rag.pipeline import Pipeline, load_default_pipeline

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
SPLITS = ("test", "dev", "holdout", "holdout2", "holdout3")
SHOULD_REFUSE = {"unanswerable", "false_premise"}
MARKER_RE = re.compile(r"\[[^\]]*#c\d+\]")


def answer_text(answer: str) -> str:
    """Answer without [chunk_id] markers, with any Unicode space turned into a plain one."""
    return " ".join(MARKER_RE.sub("", answer).split())


def score(q: dict[str, Any], resp: dict[str, Any]) -> bool:
    """Is this response correct for this question?"""
    if q["type"] in SHOULD_REFUSE:
        return bool(resp["refused"]) and not resp["citations"]
    if resp["refused"]:
        return False
    text = answer_text(resp["answer"]).lower()
    if not all(" ".join(m.lower().split()) in text for m in q.get("must_include", [])):
        return False
    if q["type"] == "version_conflict":
        cited = {c["version"] for c in resp["citations"]}
        return {"1.27", "1.31"} <= cited and "1.27" in text and "1.31" in text
    return True


def citation_checks(resp: dict[str, Any], chunks: dict[str, str]) -> tuple[list[bool], bool]:
    """Per citation: quote is an exact substring of its chunk. Plus marker integrity."""
    valid = [
        c["chunk_id"] in chunks and c["quote"] in chunks[c["chunk_id"]] for c in resp["citations"]
    ]
    markers = {m[1:-1] for m in MARKER_RE.findall(resp["answer"])}
    integrity = markers == {c["chunk_id"] for c in resp["citations"]}
    return valid, integrity


def run_split(
    pipeline: Pipeline, questions: list[dict[str, Any]], chunks: dict[str, str], name: str = ""
) -> dict[str, Any]:
    """Run one question file and compute every metric for it."""
    rows = []
    traces = []
    for q in questions:
        result = pipeline.retriever.retrieve(q["question"], top_k=5)
        response, trace = pipeline.ask_traced(q["question"], top_k=5)
        resp = response.model_dump()
        traces.append({"qid": q["qid"], **trace})
        valid, integrity = citation_checks(resp, chunks)
        gold = q["gold_docs"]
        retrieved = gold_hit(gold, result, pipeline.retriever.aliases) if gold else None
        rows.append(
            {
                "qid": q["qid"],
                "type": q["type"],
                "question": q["question"],
                "expected": q["expected"],
                "correct": score(q, resp),
                "refused": resp["refused"],
                "confidence": round(result.top_score(), 4),
                "gold_retrieved": retrieved,
                "both_versions_retrieved": (
                    gold_hit_every_version(gold, result, pipeline.retriever.aliases)
                    if q["type"] == "version_conflict"
                    else None
                ),
                "citations_valid": valid,
                "marker_integrity": integrity,
                "latency_ms": resp["latency_ms"],
                "timing_ms": trace.get("timing_ms", {}),
                "retry_added": trace["retry"].get("added", 0) if "retry" in trace else None,
                "answer": resp["answer"],
                "citations": resp["citations"],
            }
        )
        verdict = "ok " if rows[-1]["correct"] else "BAD"
        print(f"  {q['qid']:<6} {q['type']:<17} {verdict} refused={resp['refused']}")
    if name:
        with (EVAL_DIR / f"traces_{name}.jsonl").open("w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in traces)
    return summarise(rows)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn per-question rows into the headline numbers."""
    if not rows:
        return {"questions": 0}
    refuse = [r for r in rows if r["type"] in SHOULD_REFUSE]
    answer = [r for r in rows if r["type"] not in SHOULD_REFUSE]
    conflicts = [r for r in rows if r["type"] == "version_conflict"]
    all_cites = [v for r in rows for v in r["citations_valid"]]

    wrong_answerable = [r for r in answer if not r["correct"]]
    attribution = {
        "retrieval": sum(1 for r in wrong_answerable if r["gold_retrieved"] is False),
        "generation_or_gates": sum(1 for r in wrong_answerable if r["gold_retrieved"]),
    }
    confidently_wrong = sorted(
        (r for r in rows if not r["correct"]),
        key=lambda r: (r["refused"], -r["confidence"]),  # answered-and-wrong first
    )[:3]

    by_type: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by_type.setdefault(r["type"], {"n": 0, "correct": 0})
        entry["n"] += 1
        entry["correct"] += int(r["correct"])

    return {
        "questions": len(rows),
        "accuracy": rate([r["correct"] for r in rows]),
        "accuracy_by_type": {
            t: {**v, "accuracy": round(v["correct"] / v["n"], 3)}
            for t, v in sorted(by_type.items())
        },
        "refusal_rate_on_unanswerable": rate([r["refused"] for r in refuse]),
        "false_refusal_rate": rate([r["refused"] for r in answer]),
        "hallucination_rate": rate([not r["refused"] and not r["correct"] for r in rows]),
        # The two parts of the hallucination rate, kept apart so they can be read separately.
        "answered_but_should_refuse_rate": rate(
            [not r["refused"] for r in refuse] + [False] * len(answer)
        ),
        "answered_but_incomplete_rate": rate(
            [not r["refused"] and not r["correct"] for r in answer] + [False] * len(refuse)
        ),
        "version_conflict_pass": f"{sum(r['correct'] for r in conflicts)}/{len(conflicts)}",
        "citation_validity": rate(all_cites) if all_cites else None,
        "citations_checked": len(all_cites),
        "marker_integrity": rate([r["marker_integrity"] for r in rows]),
        "retrieval_recall_at_5": rate([bool(r["gold_retrieved"]) for r in answer]),
        "conflict_both_versions_at_5": rate(
            [bool(r["both_versions_retrieved"]) for r in conflicts]
        ),
        "wrong_answer_attribution": attribution,
        "p95_latency_ms": round(percentile([r["latency_ms"] for r in rows], 95)),
        "median_latency_ms": round(percentile([r["latency_ms"] for r in rows], 50)),
        "median_step_ms": {
            step: round(
                percentile([r["timing_ms"][step] for r in rows if step in r["timing_ms"]], 50)
            )
            for step in ("retrieve", "first_attempt", "retry")
            if any(step in r["timing_ms"] for r in rows)
        },
        "retries": f"{sum(r['retry_added'] is not None for r in rows)} tried, "
        f"{sum(bool(r['retry_added']) for r in rows)} added sentences",
        "most_confidently_wrong": [
            {
                k: r[k]
                for k in ("qid", "type", "question", "expected", "confidence", "refused", "answer")
            }
            for r in confidently_wrong
        ],
        "rows": rows,
    }


def machine() -> dict[str, Any]:
    """What the numbers were measured on."""
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "python": platform.python_version(),
        "device": settings.device,
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "llm": f"{settings.llm_model} @ {settings.llm_base_url}",
        "refusal_threshold": settings.refusal_threshold,
    }


def main() -> None:
    """Run every split that has questions and write eval_report.json."""
    started = time.time()
    pipeline = load_default_pipeline()
    chunks = {cid: c.text for cid, c in pipeline.retriever.chunks.items()}

    report: dict[str, Any] = {"command": "make eval", "hardware": machine(), "splits": {}}
    for split in SPLITS:
        path = EVAL_DIR / f"questions_{split}.jsonl"
        questions = load_questions(path) if path.exists() else []
        if not questions:
            continue
        print(f"\n== {split} ({len(questions)} questions)")
        report["splits"][split] = run_split(pipeline, questions, chunks, split)
    report["runtime_s"] = round(time.time() - started)
    live, hits = llm.STATS["live_calls"], llm.STATS["cache_hits"]
    report["llm_replies"] = {
        "live_calls": live,
        "replayed_from_cache": hits,
        "mode": "replay" if hits and not live else "live" if live and not hits else "mixed",
        "note": "in a replay, latency excludes the model call; see the README for live latency",
    }

    out = ROOT / "eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    keys = (
        "accuracy",
        "refusal_rate_on_unanswerable",
        "false_refusal_rate",
        "hallucination_rate",
        "version_conflict_pass",
        "citation_validity",
        "retrieval_recall_at_5",
        "p95_latency_ms",
        "median_step_ms",
        "retries",
    )
    for split, res in report["splits"].items():
        print(f"\n== {split}")
        for k in keys:
            print(f"  {k:<30} {res.get(k)}")
        print("  most confidently wrong:", [r["qid"] for r in res["most_confidently_wrong"]])
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
