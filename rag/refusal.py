"""Checks that can refuse a question before any generation happens.

Input guard: empty, oversized or non-English questions.
G1 (retrieval): nothing retrieved is even close to the question.
G2 (false premise): the question names a flag, feature gate or identifier that
    appears nowhere in either release. Checked against the full term index, not
    the retrieved chunks, because "not retrieved" and "does not exist" differ.
G3 (support) runs after generation, in the pipeline: if no sentence survives
    citation checking, the answer is a refusal.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

from rag.retriever import STOPWORDS, tokenize
from rag.terms import BACKTICK_RE, CAMEL_RE, FLAG_RE

MIN_ENGLISH_RATIO = 0.5
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


@dataclass(frozen=True)
class Refusal:
    """Why a question was refused, in words a user can act on."""

    reason: str
    message: str


def clean_question(raw: object, max_chars: int) -> str:
    """Coerce to text, trim whitespace and cap the length."""
    text = raw if isinstance(raw, str) else ""
    return " ".join(text.split())[:max_chars]


def check_input(question: str, vocabulary: Collection[str]) -> Refusal | None:
    """Refuse empty questions and questions that aren't in English.

    Language is judged by vocabulary, not a language detector: if fewer than half
    the words are English stopwords or words that occur in the corpus, the question
    is not something these English docs can answer. Short technical questions
    ("kubelet --max-pods default?") pass because their words are corpus words.
    """
    if not question:
        return Refusal("empty", "The question is empty, so there is nothing to look up.")
    words = [w.lower() for w in LATIN_WORD_RE.findall(question)]
    non_space = len(re.sub(r"\s", "", question))
    latin_share = sum(len(w) for w in words) / max(non_space, 1)
    known = [w for w in words if w in STOPWORDS or any(t in vocabulary for t in tokenize(w))]
    if not words or latin_share < 0.5 or len(known) / len(words) < MIN_ENGLISH_RATIO:
        return Refusal(
            "language",
            "This assistant only covers the English Kubernetes documentation, and the "
            "question doesn't look like English. Please ask it in English.",
        )
    return None


def named_terms(question: str) -> set[str]:
    """Flags, CamelCase identifiers and backticked tokens the question names."""
    terms = set(FLAG_RE.findall(question)) | set(CAMEL_RE.findall(question))
    terms |= {t.strip() for t in BACKTICK_RE.findall(question) if " " not in t.strip()}
    return {t.lower() for t in terms if t}


def check_false_premise(question: str, known_terms: Collection[str]) -> Refusal | None:
    """G2: refuse when the question relies on a term neither release mentions."""
    missing = sorted(t for t in named_terms(question) if t not in known_terms)
    if not missing:
        return None
    listed = ", ".join(f"`{t}`" for t in missing)
    return Refusal(
        "false_premise",
        f"Neither the 1.27 nor the 1.31 documentation mentions {listed}, so I can't "
        "confirm it exists or say how it behaves.",
    )


def check_retrieval(top_score: float, threshold: float) -> Refusal | None:
    """G1: refuse when even the best retrieved chunk is unrelated to the question."""
    if top_score >= threshold:
        return None
    return Refusal(
        "weak_retrieval",
        "Nothing in the 1.27 or 1.31 documentation I indexed is relevant to this "
        "question, so I can't answer it from the docs.",
    )
