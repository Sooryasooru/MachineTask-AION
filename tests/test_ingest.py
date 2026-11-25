"""Ingestion must be deterministic: same corpus in, same files out."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from rag.ingest import build_index

PAGE_A = (
    "---\ntitle: Pods\n---\n## Lifecycle\nA Pod moves through Pending, Running and Succeeded.\n"
)
PAGE_B = "---\ntitle: Jobs\n---\n## Retries\nThe backoffLimit field sets how many retries happen.\n"


def fake_embed(texts: Sequence[str]) -> np.ndarray:
    """Deterministic stand-in for the real model, so tests need no download."""
    rows = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        vec = np.random.default_rng(seed).normal(size=8)
        rows.append(vec / np.linalg.norm(vec))
    return np.asarray(rows, dtype="float32")


@pytest.fixture(name="corpus")
def corpus_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for version in ("1.27", "1.31"):
        (root / version / "concepts").mkdir(parents=True)
        (root / version / "concepts" / "pods.md").write_text(PAGE_A)
        (root / version / "concepts" / "jobs.md").write_text(PAGE_B)
    return root


def _digest(index_dir: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(index_dir.iterdir())
        if p.is_file()
    }


def test_rebuild_is_byte_identical(corpus: Path, tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    build_index(corpus, index_dir, fake_embed)
    first = _digest(index_dir)
    build_index(corpus, index_dir, fake_embed)
    assert _digest(index_dir) == first


def test_no_duplicate_chunks(corpus: Path, tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    build_index(corpus, index_dir, fake_embed)
    build_index(corpus, index_dir, fake_embed)
    lines = (index_dir / "chunks.jsonl").read_text().splitlines()
    ids = [json.loads(line)["chunk_id"] for line in lines]
    assert len(ids) == len(set(ids)) == 4


def test_moved_page_gets_an_alias(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / "1.27" / "old").mkdir(parents=True)
    (root / "1.31" / "new").mkdir(parents=True)
    body = "## Scaling\n" + " ".join(f"term{i}" for i in range(60)) + "\n"
    (root / "1.27" / "old" / "manage.md").write_text("---\ntitle: Managing Resources\n---\n" + body)
    (root / "1.31" / "new" / "manage.md").write_text("---\ntitle: Managing Workloads\n---\n" + body)
    build_index(root, tmp_path / "index", fake_embed)
    aliases = json.loads((tmp_path / "index" / "doc_aliases.json").read_text())
    assert aliases == {"old/manage": "new/manage"}
