"""One question in, one schema-valid response out.

    input guard -> G2 false premise -> retrieve per version -> G1 weak retrieval
    -> generate -> validate citations and support -> G3 nothing supported -> answer

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
from rag.generator import build_messages, parse_reply
from rag.llm import LLMError
from rag.refusal import (
    Refusal,
    check_false_premise,
    check_input,
    check_retrieval,
    clean_question,
)
from rag.retriever import Hit, Retrieval, Retriever, tokenize
from rag.validator import NliFn, VerifiedSentence, validate_with_report

LlmFn = Callable[[list[dict[str, str]]], str]
Trace = dict[str, Any]
MAX_TOP_K = 10
COUNTERPARTS_PER_VERSION = 2
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
    nli: NliFn
    known_terms: set[str]
    vocabulary: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.vocabulary:
            self.vocabulary = {
                t for c in self.retriever.chunks.values() for t in tokenize(c.embed_text())
            }

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

        def done(
            answer: str, refused: bool, cites: list[Citation], ids: list[str]
        ) -> tuple[AskResponse, Trace]:
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
        messages = build_messages(
            question, context, len(max(context.values(), key=len)), settings.context_chars
        )
        try:
            draft = parse_reply(self.llm(messages))
        except LLMError as err:
            trace["llm_error"] = str(err)[:300]
            return refuse(
                Refusal(
                    "llm_error",
                    "The language model could not be reached, so no answer was produced.",
                ),
                ids,
            )
        trace["draft"] = {
            "answerable": draft.answerable,
            "sentences": [
                {"text": d.text, "citations": [(c.chunk_id, c.quote) for c in d.citations]}
                for d in draft.sentences
            ],
            "gaps": draft.gaps,
            "missing": draft.missing,
        }

        retrieved = {h.chunk.chunk_id: h.chunk for hs in context.values() for h in hs}
        retrieved.update({h.chunk.chunk_id: h.chunk for h in result.all_hits()})
        kept, verdicts = (
            validate_with_report(
                draft.sentences, retrieved, self.nli, settings.nli_entail_threshold
            )
            if draft.answerable
            else ([], [])
        )
        trace["verdicts"] = verdicts
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
        answer, citations = assemble(kept, allowed_gaps(draft.gaps, self.retriever.versions))
        return done(answer, False, citations, ids)


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
    from rag.models import nli_scores
    from rag.retriever import load_default_retriever

    retriever = load_default_retriever(settings.index_dir)
    return Pipeline(retriever, chat_json, nli_scores, load_known_terms(settings.index_dir))


def main() -> None:
    """Ask one question from the command line and print the JSON response."""
    import sys  # pylint: disable=import-outside-toplevel

    question = " ".join(sys.argv[1:]) or "How many minor versions may the kubelet lag behind?"
    print(load_default_pipeline().ask(question).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
