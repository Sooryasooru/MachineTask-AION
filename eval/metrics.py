"""Metric helpers shared by the retrieval and full evaluations."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rag.retriever import Retrieval, canonical_doc


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL question file."""
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def retrieved_docs(
    result: Retrieval, aliases: dict[str, str], version: str | None = None
) -> set[str]:
    """Canonical doc ids in the result, optionally for one version only."""
    return {
        canonical_doc(h.chunk.doc_id, aliases)
        for v, hits in result.by_version.items()
        if version in (None, v)
        for h in hits
    }


def gold_hit(gold: Sequence[str], result: Retrieval, aliases: dict[str, str]) -> bool:
    """recall@k: at least one gold page appears in the top-k of any version."""
    wanted = {canonical_doc(g, aliases) for g in gold}
    return bool(wanted & retrieved_docs(result, aliases))


def gold_hit_every_version(gold: Sequence[str], result: Retrieval, aliases: dict[str, str]) -> bool:
    """For version conflicts: a gold page must show up in the top-k of each version."""
    wanted = {canonical_doc(g, aliases) for g in gold}
    return all(wanted & retrieved_docs(result, aliases, v) for v in result.by_version)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile, so p95 of 20 values is the 19th, not an interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def rate(flags: Sequence[bool]) -> float:
    """Share of True values, rounded for reports."""
    return round(sum(flags) / len(flags), 3) if flags else 0.0
