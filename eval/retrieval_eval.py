"""Retrieval-only evaluation and ablation. Run with `make recall`.

For every answerable question it checks whether a gold page lands in the top 5,
under each retrieval mode. Version-conflict questions also need the gold page in
the top 5 of *both* releases. No LLM is involved, so a miss here is a retrieval
miss, not a generation one.

Writes eval/retrieval_ablation.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.config import settings
from eval.metrics import gold_hit, gold_hit_every_version, load_questions, percentile, rate
from rag.retriever import Mode, Retrieval, load_default_retriever
from rag.rewrite import RewriteFn, retrieve_with_rewrite, rewrite_query

MODES: tuple[Mode, ...] = ("bm25", "dense", "hybrid", "hybrid_rerank")
EVAL_DIR = Path(__file__).parent
TOP_K = 5
CONTEXT_K = 3  # chunks per version the LLM actually sees


def first_k(result: Retrieval, k: int) -> Retrieval:
    """Same result, cut to the top k per version."""
    return Retrieval(by_version={v: hits[:k] for v, hits in result.by_version.items()})


def run_split(
    retriever: Any, questions: list[dict[str, Any]], mode: Mode, rewrite: RewriteFn | None = None
) -> dict[str, Any]:
    """recall@5, both-version recall on conflicts, misses and latency for one split.

    With `rewrite`, weak searches (hybrid_rerank only) also try a rewritten query.
    """
    hits, hits3, both, latencies, misses, rewritten = [], [], [], [], [], []
    for q in questions:
        if not q["gold_docs"]:
            continue
        start = time.perf_counter()
        if rewrite is not None:
            result, query = retrieve_with_rewrite(
                retriever, q["question"], TOP_K, None, rewrite, settings.rewrite_below
            )
            if query:
                rewritten.append(q["qid"])
        else:
            result = retriever.retrieve(q["question"], top_k=TOP_K, mode=mode)
        latencies.append((time.perf_counter() - start) * 1000)
        hit = gold_hit(q["gold_docs"], result, retriever.aliases)
        hits.append(hit)
        hits3.append(gold_hit(q["gold_docs"], first_k(result, CONTEXT_K), retriever.aliases))
        if not hit:
            misses.append(q["qid"])
        if q["type"] == "version_conflict":
            both.append(gold_hit_every_version(q["gold_docs"], result, retriever.aliases))
    return {
        "recall_at_5": rate(hits),
        "recall_at_3": rate(hits3),
        "conflict_both_versions_at_5": rate(both),
        "answerable_questions": len(hits),
        "misses": misses,
        "rewritten": rewritten,
        "p95_retrieval_ms": round(percentile(latencies, 95)),
    }


def top_scores(retriever: Any, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best reranker score per question. Used to see where a refusal threshold could sit."""
    rows = []
    for q in questions:
        result = retriever.retrieve(q["question"], top_k=TOP_K, mode="hybrid_rerank")
        rows.append(
            {
                "qid": q["qid"],
                "type": q["type"],
                "answerable": bool(q["gold_docs"]),
                "top_score": round(result.top_score(), 4),
            }
        )
    return rows


def main() -> None:
    """Run every mode on both splits and save the table."""
    retriever = load_default_retriever(settings.index_dir)
    splits = {
        "test": load_questions(EVAL_DIR / "questions_test.jsonl"),
        "dev": load_questions(EVAL_DIR / "questions_dev.jsonl"),
    }
    report: dict[str, Any] = {"top_k": TOP_K, "modes": {}}
    for mode in MODES:
        report["modes"][mode] = {
            name: run_split(retriever, qs, mode) for name, qs in splits.items()
        }
    report["dev_top_scores"] = top_scores(retriever, splits["dev"])

    # Real-user rewrites vs the questions they rewrite: same answers, vaguer wording.
    # paraphrase was used to build the query-rewrite step; paraphrase2 was frozen first.
    by_qid = {
        q["qid"]: q
        for path in sorted(EVAL_DIR.glob("questions_*.jsonl"))
        if "paraphrase" not in path.name
        for q in load_questions(path)
    }
    rewrite = rewrite_query if settings.rewrite_model else None
    for name in ("paraphrase", "paraphrase2"):
        rewrites = load_questions(EVAL_DIR / f"questions_{name}.jsonl")
        if not rewrites:
            continue
        originals = [by_qid[q["paraphrase_of"]] for q in rewrites]
        modes: dict[str, Any] = {
            mode: {
                "original_wording": run_split(retriever, originals, mode),
                "user_wording": run_split(retriever, rewrites, mode),
            }
            for mode in MODES
        }
        if rewrite is not None:
            modes["hybrid_rerank+rewrite"] = {
                "original_wording": run_split(retriever, originals, "hybrid_rerank", rewrite),
                "user_wording": run_split(retriever, rewrites, "hybrid_rerank", rewrite),
            }
        report[name] = modes
        report[f"{name}_top_scores"] = top_scores(retriever, rewrites)

    out = EVAL_DIR / "retrieval_ablation.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"{'mode':<15}{'test r@5':>10}{'test r@3':>10}{'both-ver':>10}{'dev r@5':>9}{'p95 ms':>8}"
    )
    for mode, res in report["modes"].items():
        t, d = res["test"], res["dev"]
        print(
            f"{mode:<15}{t['recall_at_5']:>10}{t['recall_at_3']:>10}"
            f"{t['conflict_both_versions_at_5']:>10}{d['recall_at_5']:>9}{t['p95_retrieval_ms']:>8}"
        )
    print("\ntest misses (hybrid_rerank):", report["modes"]["hybrid_rerank"]["test"]["misses"])
    print("\ndev top reranker scores (for the refusal threshold):")
    for row in sorted(report["dev_top_scores"], key=lambda r: -r["top_score"]):
        print(f"  {row['top_score']:.3f}  {row['qid']}  {row['type']}")
    for name in ("paraphrase", "paraphrase2"):
        if name not in report:
            continue
        print(f"\n{name}: recall@5 / recall@3, original wording -> user wording")
        for mode, res in report[name].items():
            o, u = res["original_wording"], res["user_wording"]
            print(
                f"  {mode:<22}{o['recall_at_5']:>6} / {o['recall_at_3']:<6} -> "
                f"{u['recall_at_5']:>6} / {u['recall_at_3']}"
            )
        low = [
            r for r in report[f"{name}_top_scores"] if r["top_score"] < settings.refusal_threshold
        ]
        print(f"  below the refusal threshold without rewrite: {len(low)}")
        if "hybrid_rerank+rewrite" in report[name]:
            rw = report[name]["hybrid_rerank+rewrite"]
            print(f"  rewrites triggered: user wording {rw['user_wording']['rewritten']}")
            print(f"                      original wording {rw['original_wording']['rewritten']}")
        print(
            "  misses (best mode):", report[name][list(report[name])[-1]]["user_wording"]["misses"]
        )
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
