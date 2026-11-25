"""Builds the prompt and parses the model's JSON reply.

The model never writes the final answer text directly. It returns sentences, each
with the chunk ids and quotes it relies on. The validator then decides what
survives, and the pipeline assembles the answer and the [chunk_id] markers itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rag.retriever import Hit

SYSTEM_PROMPT = """You answer questions about Kubernetes using ONLY the documentation \
excerpts provided. The excerpts come from two releases, 1.27 and 1.31, grouped by release.

Return a JSON object with exactly these keys:
{
  "answerable": true or false,
  "sentences": [
    {"text": "one factual sentence, no brackets or ids",
     "citations": [{"chunk_id": "an id from the excerpts", "quote": "exact words from it"}]}
  ],
  "gaps": ["sentence saying a release's excerpts do not cover the topic"],
  "missing": "if not answerable: what the excerpts do not say"
}

Rules:
1. Use only facts stated in the excerpts. Never use outside knowledge.
2. Every sentence needs at least one citation. The quote must be copied character \
for character from the cited excerpt (5 to 30 words) and must contain the fact.
3. A sentence is about one release and cites only that release's excerpts.
4. Both releases are usually shown the same page and section. Compare them. If they \
differ (a number, a default, or a feature state such as alpha, beta, stable or \
deprecated), write one sentence per release, starting "On 1.27," or "On 1.31,".
5. A line like "FEATURE STATE: Kubernetes v1.30 [beta]" states the maturity of the \
feature its page and section describe. Quote that line when the question is about maturity.
6. If the releases agree, one sentence is enough.
7. Only if none of a release's excerpts mention the topic, add a gap such as \
"The 1.27 documentation excerpts do not cover this."
8. If the excerpts do not answer the question, or the question assumes a flag, field, \
feature or behaviour the excerpts do not describe, set "answerable" to false, leave \
"sentences" empty and explain in "missing".
9. A value that only appears inside an example command is not a documented default."""


@dataclass
class DraftCitation:
    """A citation exactly as the model proposed it."""

    chunk_id: str
    quote: str


@dataclass
class DraftSentence:
    """A sentence exactly as the model proposed it."""

    text: str
    citations: list[DraftCitation] = field(default_factory=list)


@dataclass
class Draft:
    """The parsed model reply, before any validation."""

    answerable: bool
    sentences: list[DraftSentence]
    gaps: list[str]
    missing: str


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[: cut.rfind(" ")] if " " in cut else cut


def build_messages(
    question: str, hits_by_version: Mapping[str, Sequence[Hit]], per_version: int, max_chars: int
) -> list[dict[str, str]]:
    """System prompt plus the context, grouped by release, each chunk labelled by id.

    Chunks are trimmed to max_chars. Quotes are checked against the full chunk text
    later, so trimming only limits what the model sees, never what can be verified.
    """
    blocks = []
    for version in sorted(hits_by_version):
        hits = list(hits_by_version[version])[:per_version]
        if not hits:
            blocks.append(f"### Release {version}\n(no excerpts retrieved)")
            continue
        parts = [
            f"[{h.chunk.chunk_id}] ({h.chunk.title} > {h.chunk.section})\n"
            f"{_trim(h.chunk.text, max_chars)}"
            for h in hits
        ]
        blocks.append(f"### Release {version}\n\n" + "\n\n".join(parts))
    user = "Documentation excerpts:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_reply(raw: str) -> Draft:
    """Parse the JSON reply defensively. Anything malformed becomes 'not answerable'."""
    match = re.search(r"\{.*\}", raw, flags=re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    sentences = []
    for item in data.get("sentences") or []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        cites = [
            DraftCitation(str(c.get("chunk_id", "")), str(c.get("quote", "")))
            for c in item.get("citations") or []
            if isinstance(c, dict)
        ]
        text = re.sub(r"\s*\[[^\]]*#c\d+\]", "", item["text"]).strip()  # drop stray markers
        sentences.append(DraftSentence(text, cites))

    gaps = [g.strip() for g in data.get("gaps") or [] if isinstance(g, str) and g.strip()]
    return Draft(
        answerable=bool(data.get("answerable", False)),
        sentences=sentences,
        gaps=gaps,
        missing=str(data.get("missing") or "").strip(),
    )
