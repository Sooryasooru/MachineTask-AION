"""One question in, one schema-valid response out.

    input guard -> G2 false premise -> retrieve per version -> G1 weak retrieval
    -> generate -> validate citations -> (one retry if checking lost sentences)
    -> G3 nothing supported -> answer

Every exit path returns an AskResponse with all fields set, refusals included.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas import AskResponse, Citation
from rag.chunker import Chunk
from rag.generator import Draft, build_messages, parse_reply
from rag.llm import LLMError
from rag.refusal import (
    Refusal,
    check_false_premise,
    check_input,
    check_retrieval,
    clean_question,
)
from rag.retriever import Hit, Retrieval, Retriever, tokenize
from rag.validator import (
    VerifiedCitation,
    VerifiedSentence,
    stages_in,
    validate_with_report,
)

LlmFn = Callable[[list[dict[str, str]]], str]
Trace = dict[str, Any]

FULL_PASSAGE_CHARS = 4000  # chunks are at most ~1800 characters, so this means "untrimmed"
RETRY_BUDGET_S = 15.0  # no retry if the first attempt already took this long
MAX_TOP_K = 10
COUNTERPARTS_PER_VERSION = 2
FEATURE_STATE_RE = re.compile(
    r"FEATURE STATE: Kubernetes v[\d.]+ \[\w+\](?: \(feature gate `[^`]+`\))?"
)
MATURITY_QUESTION_RE = re.compile(
    r"\b(feature state|maturity|alpha|beta|stable|ga|generally available|deprecated|still use)\b",
    re.I,
)
_GAP_RE = re.compile(
    r"\b1\.\d+\b.*\b(?:do(?:es)? not|don't|doesn't)\b.*\b(?:cover|mention|document|describe)", re.I
)


_GAP_EXTRA_RE = re.compile(r"\b(?:but|should|instead|use|recommend\w*|however)\b", re.I)


def allowed_gaps(gaps: list[str], versions: list[str]) -> list[str]:
    """Gaps carry no citation, so only plain "release X doesn't cover this" lines pass."""
    kept = []
    for gap in gaps[:2]:
        plain = _GAP_RE.search(gap) and not _GAP_EXTRA_RE.search(gap)
        if plain and any(v in gap for v in versions) and len(gap) <= 160:
            kept.append(gap)
    return kept


def load_known_terms(index_dir: Path) -> set[str]:
    """Union of every release's term index."""
    per_version: dict[str, list[str]] = json.loads((index_dir / "term_index.json").read_text())
    return {t for terms in per_version.values() for t in terms}


@dataclass
class Pipeline:
    """Holds the loaded index and model callables; `ask` is safe to call concurrently."""

    retriever: Retriever
    llm: LlmFn
    known_terms: set[str]
    vocabulary: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.vocabulary:
            self.vocabulary = {
                t for c in self.retriever.chunks.values() for t in tokenize(c.embed_text())
            }

    def draft_and_check(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        question: str,
        context: dict[str, list[Hit]],
        retrieved: dict[str, Chunk],
        per_version: int,
        max_chars: int,
        note: str = "",
    ) -> tuple[Draft, list[VerifiedSentence], list[dict[str, object]]]:
        """One model call plus citation checking. Raises LLMError if the model fails."""
        messages = build_messages(question, context, per_version, max_chars)
        if note:
            messages[-1]["content"] += f"\n\nNote: {note}"
        draft = parse_reply(self.llm(messages))
        if not draft.answerable:
            return draft, [], []
        kept, verdicts = validate_with_report(draft.sentences, retrieved)
        return draft, kept, verdicts

    def retry_if_needed(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        question: str,
        context: dict[str, list[Hit]],
        retrieved: dict[str, Chunk],
        draft: Draft,
        kept: list[VerifiedSentence],
        trace: Trace,
    ) -> tuple[Draft, list[VerifiedSentence]]:
        """One more model call when checking threw away sentences that may be right.

        The retry shows the excerpts untrimmed and says which quotes were not found.
        Its result is merged in, never swapped in: everything the first attempt kept
        stays, and the retry can only add sentences for releases that were missing.
        """
        reason = retry_reason(draft, kept, context, settings.context_chars)
        if not reason:
            return draft, kept
        trace["retry"] = {"reason": reason}
        per = len(max(context.values(), key=len))
        try:
            draft2, kept2, verdicts2 = self.draft_and_check(
                question, context, retrieved, per, FULL_PASSAGE_CHARS, feedback(trace["verdicts"])
            )
        except LLMError as err:
            trace["retry"]["llm_error"] = str(err)[:300]
            return draft, kept
        trace["retry"]["verdicts"] = verdicts2
        if not kept:
            trace["retry"]["added"] = len(kept2)
            return draft2, kept2
        lost = drafted_releases(draft) - kept_releases(kept)
        extra = [k for k in kept2 if kept_releases([k]) <= lost]
        trace["retry"]["added"] = len(extra)
        return draft, kept + extra

    def ask(self, raw_question: object, top_k: object = 5, version: object = None) -> AskResponse:
        """Answer, or refuse with a reason. Never raises."""
        return self.ask_traced(raw_question, top_k, version)[0]

    def build_context(self, result: Retrieval, pinned: str | None) -> dict[str, list[Hit]]:
        """Top chunks per release, plus each one's counterpart in the other release.

        Retrieval ranks each release on its own, so the 1.27 and 1.31 versions of the
        same section often land at different ranks and one gets cut. Pulling in the
        same page and section from the other release puts both side by side for the
        model, which is what lets it notice that they disagree.
        """
        per = settings.context_per_version
        context = {v: list(hits[:per]) for v, hits in result.by_version.items()}
        if pinned:
            return context
        for version, hits in list(context.items()):
            for hit in hits[:per]:
                for other in self.retriever.versions:
                    if other == version or other not in context:
                        continue
                    have = {h.chunk.chunk_id for h in context[other]}
                    if len(context[other]) >= per + COUNTERPARTS_PER_VERSION:
                        continue
                    twin = self.retriever.counterpart(hit.chunk, other)
                    if twin and twin.chunk_id not in have:
                        context[other].append(Hit(twin, hit.score))
        return context

    def complete_versions(
        self, question: str, kept: list[VerifiedSentence]
    ) -> list[VerifiedSentence]:
        """Add the other release's feature state when an answer covers only one release.

        The model sometimes answers for one release and its sentence for the other
        doesn't survive checking (T-06, T-07 in run 2), which leaves exactly the
        one-sided answer the brief warns about. When the other release's twin of a
        cited section states a different feature state, code adds that line, quoted
        verbatim and cited. Nothing here is generated, so it can't be made up.
        """
        cited_versions = {c.chunk.version for s in kept for c in s.citations}
        if len(cited_versions) != 1 or len(self.retriever.versions) < 2:
            return []
        (version,) = cited_versions
        answer_text = " ".join(s.text for s in kept)
        added: list[VerifiedSentence] = []
        seen: set[str] = set()
        for sentence in kept:
            for cite in sentence.citations:
                own = FEATURE_STATE_RE.findall(cite.chunk.text)
                if not own and not MATURITY_QUESTION_RE.search(question):
                    continue
                own_stages = stages_in(" ".join(own) + " " + answer_text)
                for other in self.retriever.versions:
                    if other == version:
                        continue
                    twin = self.retriever.counterpart(cite.chunk, other)
                    if twin is None or twin.chunk_id in seen:
                        continue
                    for match in FEATURE_STATE_RE.finditer(twin.text):
                        if stages_in(match.group(0)) <= own_stages:
                            continue
                        seen.add(twin.chunk_id)
                        quote = match.group(0)
                        added.append(
                            VerifiedSentence(
                                f"On {other}, the same section states {quote}",
                                (VerifiedCitation(twin, quote, match.start(), match.end()),),
                            )
                        )
                        break
        return added

    def ask_traced(
        self, raw_question: object, top_k: object = 5, version: object = None
    ) -> tuple[AskResponse, Trace]:
        """`ask`, plus a trace of what happened at each step (used by the eval)."""
        start = time.perf_counter()
        question = clean_question(raw_question, settings.max_question_chars)
        k = top_k if isinstance(top_k, int) and not isinstance(top_k, bool) else 5
        k = min(max(k, 1), MAX_TOP_K)
        pinned = version if version in self.retriever.versions else None
        trace: Trace = {"question": question}
        timing: dict[str, int] = {}
        trace["timing_ms"] = timing

        def done(
            answer: str, refused: bool, cites: list[Citation], ids: list[str]
        ) -> tuple[AskResponse, Trace]:
            timing["total"] = ms_since(start)
            resp = AskResponse(
                answer=answer,
                refused=refused,
                citations=[] if refused else cites,
                retrieved_chunk_ids=ids,
                latency_ms=round((time.perf_counter() - start) * 1000),
            )
            return resp, trace

        def refuse(refusal: Refusal, ids: list[str] | None = None) -> tuple[AskResponse, Trace]:
            trace["refusal"] = refusal.reason
            return done(refusal.message, True, [], ids or [])

        early = check_input(question, self.vocabulary) or check_false_premise(
            question, self.known_terms
        )
        if early:
            return refuse(early)

        result = self.retriever.retrieve(question, top_k=k, version=pinned)
        trace["top_score"] = round(result.top_score(), 4)
        weak = check_retrieval(result.top_score(), settings.refusal_threshold)
        if weak:
            return refuse(weak, result.chunk_ids())

        context = self.build_context(result, pinned)
        ids = list(
            dict.fromkeys(
                result.chunk_ids() + [h.chunk.chunk_id for hs in context.values() for h in hs]
            )
        )
        trace["context"] = {v: [h.chunk.chunk_id for h in hs] for v, hs in context.items()}
        retrieved = {h.chunk.chunk_id: h.chunk for hs in context.values() for h in hs}
        retrieved.update({h.chunk.chunk_id: h.chunk for h in result.all_hits()})
        timing["retrieve"] = ms_since(start)

        try:
            draft, kept, verdicts = self.draft_and_check(
                question,
                context,
                retrieved,
                len(max(context.values(), key=len)),
                settings.context_chars,
            )
        except LLMError as err:
            trace["llm_error"] = str(err)[:300]
            return refuse(
                Refusal(
                    "llm_error",
                    "The language model could not be reached, so no answer was produced.",
                ),
                ids,
            )
        trace["draft"] = draft_summary(draft)
        trace["verdicts"] = verdicts
        timing["first_attempt"] = ms_since(start) - timing["retrieve"]
        first_releases = kept_releases(kept)
        if time.perf_counter() - start < RETRY_BUDGET_S:
            draft, kept = self.retry_if_needed(question, context, retrieved, draft, kept, trace)
        timing["retry"] = ms_since(start) - timing["retrieve"] - timing["first_attempt"]

        if not kept:  # G3
            missing = draft.missing or "none of the drafted sentences survived citation checking"
            return refuse(
                Refusal(
                    "unsupported",
                    "I can't answer this from the 1.27 or 1.31 documentation: "
                    f"{missing.rstrip('.')}.",
                ),
                ids,
            )
        completed = self.complete_versions(question, kept)
        trace["completed"] = [c.text for c in completed]
        gaps = allowed_gaps(draft.gaps, self.retriever.versions)
        # A release covered by the retry or by completion no longer "doesn't cover this".
        covered = kept_releases(completed)
        if first_releases:
            covered |= kept_releases(kept) - first_releases
        if covered:
            gaps = [g for g in gaps if not any(v in g for v in covered)]
        answer, citations = assemble(kept + completed, gaps)
        return done(answer, False, citations, ids)


def ms_since(start: float) -> int:
    """Milliseconds since a perf_counter() start."""
    return round((time.perf_counter() - start) * 1000)


def draft_summary(draft: Draft) -> dict[str, object]:
    """What the model proposed, for the trace."""
    return {
        "answerable": draft.answerable,
        "sentences": [
            {"text": d.text, "citations": [(c.chunk_id, c.quote) for c in d.citations]}
            for d in draft.sentences
        ],
        "gaps": draft.gaps,
        "missing": draft.missing,
    }


def drafted_releases(draft: Draft) -> set[str]:
    """Releases the model wrote about, read from the chunk ids it cited ("v1.31:..")."""
    return {c.chunk_id.split(":", 1)[0].lstrip("v") for s in draft.sentences for c in s.citations}


def kept_releases(kept: list[VerifiedSentence]) -> set[str]:
    """Releases covered by sentences that passed checking."""
    return {c.chunk.version for s in kept for c in s.citations}


def retry_reason(
    draft: Draft, kept: list[VerifiedSentence], context: dict[str, list[Hit]], max_chars: int
) -> str:
    """Why a second attempt is worth one more model call, or "" if it isn't.

    - checking dropped every sentence about a release the model did write about
      (this covers "nothing survived" and one-sided version answers), or
    - the model said the excerpts don't answer it while some were trimmed for length.
    """
    if draft.answerable and drafted_releases(draft) - kept_releases(kept):
        return "a release lost all its sentences in checking"
    trimmed = any(len(h.chunk.text) > max_chars for hs in context.values() for h in hs)
    if not kept and trimmed:
        return "nothing answered while some excerpts were trimmed"
    return ""


def feedback(verdicts: list[dict[str, object]]) -> str:
    """Retry note: excerpts are now complete, and which quotes could not be found."""
    lost = [str(v["text"])[:160] for v in verdicts if v["reason"] == "no verifiable citation"]
    note = (
        "the excerpts are now shown in full. Every quote must be copied word for word "
        "from one excerpt, as one continuous passage, without '...'."
    )
    if lost:
        note += " These sentences were dropped because their quotes were not found: " + " | ".join(
            lost
        )
    return note


def assemble(kept: list[VerifiedSentence], gaps: list[str]) -> tuple[str, list[Citation]]:
    """Answer text with [chunk_id] markers, and a citation entry for every marker."""
    parts: list[str] = []
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for sentence in kept:
        markers = []
        for cite in sentence.citations:
            markers.append(f"[{cite.chunk.chunk_id}]")
            key = (cite.chunk.chunk_id, cite.quote)
            if key not in seen:
                seen.add(key)
                citations.append(
                    Citation(
                        doc_id=cite.chunk.doc_id,
                        chunk_id=cite.chunk.chunk_id,
                        version=cite.chunk.version,
                        quote=cite.quote,
                    )
                )
        text = sentence.text.rstrip()
        body, end = (text[:-1], text[-1]) if text[-1:] in ".!?" else (text, ".")
        parts.append(f"{body} {' '.join(dict.fromkeys(markers))}{end}")
    parts.extend(g if g.endswith((".", "!", "?")) else g + "." for g in gaps)
    return " ".join(parts), citations


def load_default_pipeline() -> Pipeline:
    """Real models and the configured LLM."""
    # pylint: disable=import-outside-toplevel
    from rag.llm import chat_json
    from rag.retriever import load_default_retriever

    retriever = load_default_retriever(settings.index_dir)
    return Pipeline(retriever, chat_json, load_known_terms(settings.index_dir))


def main() -> None:
    """Ask one question from the command line and print the JSON response."""
    import sys  # pylint: disable=import-outside-toplevel

    question = " ".join(sys.argv[1:]) or "How many minor versions may the kubelet lag behind?"
    print(load_default_pipeline().ask(question).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
