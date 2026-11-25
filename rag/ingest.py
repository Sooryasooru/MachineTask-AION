"""Rebuilds the index from corpus/. Run with `make ingest`.

Every run wipes index/ and writes it again from scratch. File order is sorted and
no timestamps are written, so the same corpus always gives the same chunk ids and
the same files.

Output in index/:
    chunks.jsonl        every chunk, sorted by version, then page, then position
    <version>.faiss     one dense index per version (inner product on unit vectors)
    <version>.ids.json  row -> chunk_id for that version's FAISS index
    term_index.json     every flag / gate / identifier, per version
    doc_aliases.json    pages that moved between releases, matched by title
    meta.json           models, chunk settings, counts and corpus commits
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

import faiss
import numpy as np

from app.config import settings
from rag.chunker import MAX_CHARS, MIN_CHARS, Chunk, chunk_page, load_feature_gates
from rag.terms import build_term_index

EmbedFn = Callable[[Sequence[str]], np.ndarray]


def discover_versions(corpus_dir: Path) -> list[str]:
    """Version folders are the ones named like 1.27; _feature_gates is metadata."""
    return sorted(p.name for p in corpus_dir.iterdir() if p.is_dir() and p.name[0].isdigit())


def load_chunks(corpus_dir: Path) -> list[Chunk]:
    """Chunk every page of every version, in a fixed order."""
    chunks: list[Chunk] = []
    for version in discover_versions(corpus_dir):
        gates = load_feature_gates(corpus_dir / "_feature_gates" / version)
        root = corpus_dir / version
        for path in sorted(root.rglob("*.md")):
            doc_id = path.relative_to(root).with_suffix("").as_posix()
            chunks.extend(chunk_page(path.read_text(encoding="utf-8"), doc_id, version, gates))
    return chunks


ALIAS_MIN_JACCARD = 0.5
ALIAS_MIN_MARGIN = 2.0
_WORD_RE = re.compile(r"[a-z][a-z0-9-]{2,}")


def build_aliases(chunks: Sequence[Chunk], versions: Sequence[str]) -> dict[str, str]:
    """Map a page that exists in only one release to its moved twin in the other.

    Pairing by doc_id breaks when a page is moved or renamed. Pages present in only
    the older release are matched to pages present only in the newer one, first by
    exact title, then by word overlap (Jaccard). A content match needs at least
    ALIAS_MIN_JACCARD and must beat the runner-up by ALIAS_MIN_MARGIN; anything
    closer is left unmatched on purpose, because a wrong pairing is worse than none.
    """
    if len(versions) != 2:
        return {}
    old, new = versions
    pages: dict[tuple[str, str], list[Chunk]] = {}
    for c in chunks:
        pages.setdefault((c.version, c.doc_id), []).append(c)
    only_old = sorted(d for v, d in pages if v == old and (new, d) not in pages)
    only_new = sorted(d for v, d in pages if v == new and (old, d) not in pages)

    def title(version: str, doc: str) -> str:
        return pages[(version, doc)][0].title.strip().lower()

    def words(version: str, doc: str) -> set[str]:
        return set(_WORD_RE.findall(" ".join(c.text for c in pages[(version, doc)]).lower()))

    new_words = {d: words(new, d) for d in only_new}
    aliases: dict[str, str] = {}
    for doc in only_old:
        same_title = [d for d in only_new if title(new, d) == title(old, doc)]
        if len(same_title) == 1:
            aliases[doc] = same_title[0]
            continue
        mine = words(old, doc)
        scored = sorted(
            ((len(mine & w) / max(len(mine | w), 1), d) for d, w in new_words.items()),
            reverse=True,
        )
        if not scored:
            continue
        best, runner_up = scored[0][0], scored[1][0] if len(scored) > 1 else 0.0
        if best >= ALIAS_MIN_JACCARD and best >= ALIAS_MIN_MARGIN * runner_up:
            aliases[doc] = scored[0][1]
    return aliases


def _reset_dir(index_dir: Path) -> None:
    if index_dir.exists():
        shutil.rmtree(index_dir)
    index_dir.mkdir(parents=True)
    (index_dir / ".gitkeep").touch()


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_index(corpus_dir: Path, index_dir: Path, embed: EmbedFn) -> dict[str, object]:
    """Build every index file. `embed` is injected so tests can skip the model."""
    chunks = load_chunks(corpus_dir)
    versions = discover_versions(corpus_dir)
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate chunk ids, refusing to write the index")

    _reset_dir(index_dir)
    with (index_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    counts: dict[str, dict[str, int]] = {}
    terms: dict[str, list[str]] = {}
    for version in versions:
        vchunks = [c for c in chunks if c.version == version]
        vectors = np.asarray(embed([c.embed_text() for c in vchunks]), dtype="float32")
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)  # pylint: disable=no-value-for-parameter  # faiss SWIG signature
        faiss.write_index(index, str(index_dir / f"{version}.faiss"))
        _write_json(index_dir / f"{version}.ids.json", [c.chunk_id for c in vchunks])
        terms[version] = build_term_index(c.text for c in vchunks)
        counts[version] = {"pages": len({c.doc_id for c in vchunks}), "chunks": len(vchunks)}

    _write_json(index_dir / "term_index.json", terms)
    aliases = build_aliases(chunks, versions)
    _write_json(index_dir / "doc_aliases.json", aliases)

    manifest_path = corpus_dir / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    meta: dict[str, object] = {
        "embed_model": settings.embed_model,
        "max_chars": MAX_CHARS,
        "min_chars": MIN_CHARS,
        "counts": counts,
        "aliases": len(aliases),
        "corpus_commits": {v["version"]: v["commit"] for v in manifest.get("versions", [])},
    }
    _write_json(index_dir / "meta.json", meta)
    return meta


def main() -> None:
    """CLI entry point used by `make ingest` and the Dockerfile."""
    # Imported here so tests and tooling don't load torch just to import this module.
    from rag.models import get_embedder  # pylint: disable=import-outside-toplevel

    model = get_embedder()

    def embed(texts: Sequence[str]) -> np.ndarray:
        return model.encode(
            list(texts), batch_size=32, normalize_embeddings=True, show_progress_bar=True
        )

    meta = build_index(settings.corpus_dir, settings.index_dir, embed)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
