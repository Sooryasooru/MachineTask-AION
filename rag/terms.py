"""Exact-term index used by the false-premise gate.

Embeddings are bad at telling `--max-pods` from `--max-pod`. A plain set of every
flag, feature gate and backticked identifier in the corpus is not, so the gate
checks named terms against this set instead of against retrieved chunks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*[a-z0-9]")
BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")
CAMEL_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b")


def extract_terms(text: str) -> set[str]:
    """Flags, CamelCase identifiers (feature gates, kinds) and backticked tokens."""
    terms = set(FLAG_RE.findall(text)) | set(CAMEL_RE.findall(text))
    for token in BACKTICK_RE.findall(text):
        token = token.strip()
        if " " not in token:
            terms.add(token)
            terms.update(FLAG_RE.findall(token))
            if "=" in token:
                terms.add(token.split("=", 1)[0])
    return {t.lower() for t in terms}


def build_term_index(texts: Iterable[str]) -> list[str]:
    """Sorted list so the file is identical on every rebuild."""
    found: set[str] = set()
    for text in texts:
        found |= extract_terms(text)
    return sorted(found)
