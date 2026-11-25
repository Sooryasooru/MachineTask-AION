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

MODES: tuple[Mode, ...] = ("bm25", "dense", "hybrid", "hybrid_rerank")
EVAL_DIR = Path(__file__).parent
TOP_K = 5
CONTEXT_K = 3  # chunks per version the LLM actually sees


def first_k(result: Retrieval, k: int) -> Retrieval:
    """Same result, cut to the top k per version."""
    return Retrieval(by_version={v: hits[:k] for v, hits in result.by_version.items()})


def run_split(retriever: Any, questions: list[dict[str, Any]], mode: Mode) -> dict[str, Any]:
    """recall@5, both-version recall on conflicts, misses and latency for one split."""
    hits, hits3, both, latencies, misses = [], [], [], [], []
    for q in questions:
        if not q["gold_docs"]:
            continue
        start = time.perf_counter()
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

    out = EVAL_DIR / "retrieval_ablation.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"{'mode':<15}{'test recall@5':>15}{'test both-ver':>15}{'dev recall@5':>14}{'p95 ms':>9}"
    )
    for mode, res in report["modes"].items():
        t, d = res["test"], res["dev"]
        print(
            f"{mode:<15}{t['recall_at_5']:>15}{t['conflict_both_versions_at_5']:>15}"
            f"{d['recall_at_5']:>14}{t['p95_retrieval_ms']:>9}"
        )
    print("\ntest misses (hybrid_rerank):", report["modes"]["hybrid_rerank"]["test"]["misses"])
    print("\ndev top reranker scores (for the refusal threshold):")
    for row in sorted(report["dev_top_scores"], key=lambda r: -r["top_score"]):
        print(f"  {row['top_score']:.3f}  {row['qid']}  {row['type']}")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
