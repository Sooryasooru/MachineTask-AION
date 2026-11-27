"""Checks every proposed sentence against the chunks it cites. Nothing is repaired.

A citation survives only if:
  1. its chunk_id is one of the chunks that were actually retrieved, and
  2. its quote occurs in that chunk. Matching ignores whitespace, curly quotes and
     markdown backticks/asterisks, but the quote returned to the caller is always
     the chunk's own original text, so it is an exact substring by construction.

A sentence survives only if it keeps at least one citation, and every number it
states and every maturity word (alpha, beta, stable...) appears in the cited text.
Those two are the claims that matter most here ("two" vs "three", "beta" vs
"stable"), and plain string checks catch them reliably. An NLI support check was
tried and removed; see docs/evaluation.md.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from rag.chunker import Chunk
from rag.generator import DraftSentence

MIN_QUOTE_WORDS = 3
ALIGN_MIN_RATIO = 0.9  # how close a near-verbatim quote must be to snap to the real text
CONTEXT_WINDOW = 500  # characters kept either side of the quote
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
    """A sentence that kept at least one verified citation and passed the checks."""

    text: str
    citations: tuple[VerifiedCitation, ...]


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


def _exact_span(chunk_text: str, quote: str) -> tuple[int, int] | None:
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


def _aligned_span(chunk_text: str, quote: str) -> tuple[int, int] | None:
    """Closest real span to a near-verbatim quote, or None if nothing is close enough.

    The model sometimes drops a word or joins two lines inside a quote. Rather than
    throwing the sentence away, find the span of the chunk that the quote was clearly
    copied from. It must be at least ALIGN_MIN_RATIO similar, and it must state the
    same numbers and maturity words, so a quote can never be "aligned" onto a
    different fact. The returned quote is always the chunk's own text.
    """
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", chunk_text)]
    target = " ".join(quote.lower().split())
    n = len(quote.split())
    best_ratio, best_start, best_end = 0.0, -1, -1
    for size in range(max(MIN_QUOTE_WORDS, n - 3), n + 4):
        for i in range(0, max(len(words) - size + 1, 0)):
            start, end = words[i][0], words[i + size - 1][1]
            candidate = " ".join(chunk_text[start:end].lower().split())
            ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
            if ratio > best_ratio:
                best_ratio, best_start, best_end = ratio, start, end
    if best_ratio < ALIGN_MIN_RATIO:
        return None
    span_text = chunk_text[best_start:best_end]
    if numbers_in(quote) != numbers_in(span_text) or stages_in(quote) != stages_in(span_text):
        return None
    return best_start, best_end


def locate_quote(chunk_text: str, quote: str) -> tuple[int, int] | None:
    """Find the quote in the chunk; return the (start, end) span in the original text.

    Exact match first, then whitespace/markdown-insensitive, then near-verbatim
    alignment. Whatever matches, the caller gets a span of the chunk's own text.
    """
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return None
    return _exact_span(chunk_text, quote) or _aligned_span(chunk_text, quote)


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
    """'On 1.31, the kubelet...' -> 'the kubelet...', so the release is not read as a number."""
    return _VERSION_PREFIX_RE.sub("", sentence).strip()


def _cited_context(cite: VerifiedCitation) -> str:
    """The quote plus nearby text, page title and heading: what a sentence may rely on."""
    text = cite.chunk.text
    lo, hi = max(0, cite.start - CONTEXT_WINDOW), min(len(text), cite.end + CONTEXT_WINDOW)
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
    sentences: Sequence[DraftSentence], retrieved: dict[str, Chunk]
) -> tuple[list[VerifiedSentence], list[dict[str, object]]]:
    """Like `validate`, plus one verdict per proposed sentence saying why it stayed or went."""
    verdicts: list[dict[str, object]] = []
    kept: list[VerifiedSentence] = []
    for sentence in sentences:
        if not sentence.text:
            continue
        cites = verify_citations(sentence, retrieved)
        if not cites:
            verdicts.append(
                {
                    "text": sentence.text,
                    "kept": False,
                    "reason": "no verifiable citation",
                    "proposed": [(c.chunk_id, c.quote[:80]) for c in sentence.citations],
                }
            )
            continue
        cited_text = " ".join(_cited_context(c) for c in cites)
        claim = strip_version_prefix(sentence.text)
        if not numbers_in(claim) <= numbers_in(cited_text):
            reason = "number not in cited text"
        elif not stages_in(claim) <= stages_in(cited_text):
            reason = "maturity not in cited text"
        else:
            reason = "supported"
            kept.append(VerifiedSentence(sentence.text, tuple(cites)))
        verdicts.append({"text": sentence.text, "kept": reason == "supported", "reason": reason})
    return kept, verdicts


def validate(
    sentences: Sequence[DraftSentence], retrieved: dict[str, Chunk]
) -> list[VerifiedSentence]:
    """Return the sentences that keep a verified citation and pass the checks."""
    return validate_with_report(sentences, retrieved)[0]
