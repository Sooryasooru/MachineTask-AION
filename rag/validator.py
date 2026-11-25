"""Checks every proposed sentence against the chunks it cites. Nothing is repaired.

A citation survives only if:
  1. its chunk_id is one of the chunks that were actually retrieved, and
  2. its quote occurs in that chunk. Matching ignores whitespace, curly quotes and
     markdown backticks/asterisks, but the quote returned to the caller is always
     the chunk's own original text, so it is an exact substring by construction.

A sentence survives only if it keeps at least one citation, every number it states
and every maturity word (alpha, beta, stable...) appears in the cited text, and the
cited text supports it. Support is judged by an NLI model: a contradiction always
drops the sentence; entailment keeps it; "neutral" keeps it only when most of the
sentence's content words come from the verified quotes or the cited page's title and
heading. NLI tends to call faithful paraphrases neutral, and this keeps those without
letting new numbers or maturity claims through.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rag.chunker import Chunk
from rag.generator import DraftSentence
from rag.retriever import tokenize

# (premise, hypothesis) pairs -> (contradiction, entailment, neutral) probabilities
NliFn = Callable[[Sequence[tuple[str, str]]], Sequence[tuple[float, float, float]]]

MIN_QUOTE_WORDS = 3
NEUTRAL_COVERAGE = 0.6
PREMISE_WINDOW = 500  # characters kept either side of the quote
_SKIP_CHARS = {"`", "*"}
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_VERSION_PREFIX_RE = re.compile(r"^(on|in|for)\s+(kubernetes\s+)?v?1\.\d+\s*,?\s*", re.I)
_VERSION_WORD_RE = re.compile(r"^v?1\.\d+$")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_NUMBER_WORDS = {
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


@dataclass(frozen=True)
class VerifiedCitation:
    """A citation whose quote is an exact substring of its chunk."""

    chunk: Chunk
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class VerifiedSentence:
    """A sentence that passed both checks, with the scores that let it through."""

    text: str
    citations: tuple[VerifiedCitation, ...]
    entailment: float
    coverage: float


def _normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalised text plus, for each normalised char, its index in the original."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text.translate(_TRANSLATE)):
        if ch in _SKIP_CHARS:
            continue
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            index.append(i)
            prev_space = True
            continue
        out.append(ch.lower())
        index.append(i)
        prev_space = False
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def locate_quote(chunk_text: str, quote: str) -> tuple[int, int] | None:
    """Find the quote in the chunk; return the (start, end) span in the original text."""
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return None
    start = chunk_text.find(quote)
    if start >= 0:
        return start, start + len(quote)
    norm_text, mapping = _normalise_with_map(chunk_text)
    norm_quote, _ = _normalise_with_map(quote.strip())
    if not norm_quote:
        return None
    pos = norm_text.find(norm_quote)
    if pos < 0:
        return None
    return mapping[pos], mapping[pos + len(norm_quote) - 1] + 1


def _content_words(text: str) -> set[str]:
    return {t for t in tokenize(text) if not _VERSION_WORD_RE.match(t)}


def numbers_in(text: str) -> set[str]:
    """Numbers stated in the text, digits or words, ignoring release versions like 1.31."""
    found = {n for n in _NUMBER_RE.findall(text) if not _VERSION_WORD_RE.match(n)}
    found |= {_NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in _NUMBER_WORDS}
    return found


_STAGE_RE = re.compile(r"\b(alpha|beta|stable|deprecated|ga|generally available)\b", re.I)


def stages_in(text: str) -> set[str]:
    """Maturity words stated in the text; 'GA' and 'generally available' count as stable."""
    found = {m.lower() for m in _STAGE_RE.findall(text)}
    return {"stable" if f in ("ga", "generally available") else f for f in found}


def strip_version_prefix(sentence: str) -> str:
    """'On 1.31, the kubelet...' -> 'the kubelet...', so NLI judges the claim itself."""
    return _VERSION_PREFIX_RE.sub("", sentence).strip()


def _premise(cite: VerifiedCitation) -> str:
    text = cite.chunk.text
    lo, hi = max(0, cite.start - PREMISE_WINDOW), min(len(text), cite.end + PREMISE_WINDOW)
    return (
        f"Kubernetes {cite.chunk.version} documentation, page "
        f'"{cite.chunk.title} > {cite.chunk.section}": {text[lo:hi]}'
    )


def verify_citations(
    sentence: DraftSentence, retrieved: dict[str, Chunk]
) -> list[VerifiedCitation]:
    """Keep only citations to retrieved chunks whose quote is really in the chunk."""
    kept: list[VerifiedCitation] = []
    seen: set[tuple[str, int]] = set()
    for cite in sentence.citations:
        chunk = retrieved.get(cite.chunk_id)
        if chunk is None:
            continue
        span = locate_quote(chunk.text, cite.quote)
        if span is None or (chunk.chunk_id, span[0]) in seen:
            continue
        seen.add((chunk.chunk_id, span[0]))
        kept.append(VerifiedCitation(chunk, chunk.text[span[0] : span[1]], span[0], span[1]))
    return kept


def validate_with_report(
    sentences: Sequence[DraftSentence],
    retrieved: dict[str, Chunk],
    nli: NliFn,
    entail_threshold: float,
) -> tuple[list[VerifiedSentence], list[dict[str, object]]]:
    """Like `validate`, plus one verdict per proposed sentence saying why it stayed or went."""
    verdicts: list[dict[str, object]] = []
    candidates = []
    for s in sentences:
        if not s.text:
            continue
        cites = verify_citations(s, retrieved)
        if cites:
            candidates.append((s, cites))
        else:
            verdicts.append(
                {
                    "text": s.text,
                    "kept": False,
                    "reason": "no verifiable citation",
                    "proposed": [(c.chunk_id, c.quote[:80]) for c in s.citations],
                }
            )
    if not candidates:
        return [], verdicts

    pairs = [
        (" ".join(_premise(c) for c in cites), strip_version_prefix(s.text))
        for s, cites in candidates
    ]
    scores = nli(pairs)

    kept: list[VerifiedSentence] = []
    for (sentence, cites), (contradiction, entailment, neutral) in zip(
        candidates, scores, strict=True
    ):
        # The subject of a terse line like "FEATURE STATE: v1.30 [beta]" lives in the
        # page title and heading, so those words count as cited context too.
        words = _content_words(sentence.text)
        context = set().union(
            *(_content_words(f"{c.quote} {c.chunk.title} {c.chunk.section}") for c in cites)
        )
        coverage = len(words & context) / len(words) if words else 0.0
        cited_text = " ".join(_premise(c) for c in cites)
        verdict: dict[str, object] = {
            "text": sentence.text,
            "entailment": round(entailment, 3),
            "contradiction": round(contradiction, 3),
            "coverage": round(coverage, 3),
        }
        claim = strip_version_prefix(sentence.text)
        if not numbers_in(claim) <= numbers_in(cited_text):
            verdicts.append({**verdict, "kept": False, "reason": "number not in cited text"})
        elif not stages_in(claim) <= stages_in(cited_text):
            verdicts.append({**verdict, "kept": False, "reason": "maturity not in cited text"})
        elif contradiction >= max(entailment, neutral):
            verdicts.append({**verdict, "kept": False, "reason": "contradicted by cited text"})
        elif entailment >= entail_threshold or coverage >= NEUTRAL_COVERAGE:
            verdicts.append({**verdict, "kept": True, "reason": "supported"})
            kept.append(VerifiedSentence(sentence.text, tuple(cites), entailment, coverage))
        else:
            verdicts.append({**verdict, "kept": False, "reason": "not supported enough"})
    return kept, verdicts


def validate(
    sentences: Sequence[DraftSentence],
    retrieved: dict[str, Chunk],
    nli: NliFn,
    entail_threshold: float,
) -> list[VerifiedSentence]:
    """Return the sentences that keep a verified citation and are supported by it."""
    return validate_with_report(sentences, retrieved, nli, entail_threshold)[0]
