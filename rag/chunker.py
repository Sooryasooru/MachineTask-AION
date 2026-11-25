"""Turns Hugo markdown pages into clean, heading-scoped chunks.

The Kubernetes docs are Hugo pages: YAML front matter, a lot of shortcodes, and
sections marked with ## and ### headings. Several shortcodes render differently
per release (`skew`, `param "version"`, `feature-state`), so they are rendered
here with the branch's own version. Otherwise 1.27 and 1.31 would read the same
in exactly the places where they differ.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_CHARS = 1800  # roughly 400 tokens
MIN_CHARS = 300  # smaller sections get merged with their neighbour
MIN_CONTENT_CHARS = 40  # below this a chunk carries no real information

HEADING_LABELS = {
    "prerequisites": "Before you begin",
    "whatsnext": "What's next",
    "objectives": "Objectives",
    "cleanup": "Clean up",
    "seealso": "See also",
}
ADMONITIONS = {"note": "Note:", "caution": "Caution:", "warning": "Warning:"}
DROP_BLOCKS = ("comment", "mermaid")
DROP_TAGS = (
    "include",
    "version-check",
    "glossary_definition",
    "thirdparty-content",
    "legacy-repos-deprecation",
    "figure",
)

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
SHORTCODE_RE = re.compile(r"\{\{[<%]\s*(/?)\s*([\w-]+)(.*?)\s*[>%]\}\}", re.S)
ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
POS_ARG_RE = re.compile(r'"([^"]*)"|(-?\d+)|([A-Za-z]\w*)')
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit. `text` is what citations quote from."""

    chunk_id: str
    doc_id: str
    version: str
    title: str
    section: str
    text: str

    def embed_text(self) -> str:
        """Text sent to the embedder: title and heading path give context."""
        return f"{self.title} > {self.section}\n{self.text}"

    def to_dict(self) -> dict[str, str]:
        """Plain dict for JSONL."""
        return asdict(self)


# --------------------------------------------------------------------------- versions


def _minor(version: str) -> int:
    return int(version.split(".")[1])


def _vtuple(value: str) -> tuple[int, int]:
    major, minor = value.strip().lstrip("v").split(".")[:2]
    return int(major), int(minor)


def gate_state(stages: list[dict[str, Any]], version: str) -> tuple[str, str] | None:
    """Pick the stage a feature gate is in at `version`: (from_version, stage)."""
    current = _vtuple(version)
    for stage in stages:
        start = _vtuple(str(stage.get("fromVersion", "0.0")))
        end = _vtuple(str(stage["toVersion"])) if stage.get("toVersion") else (99, 99)
        if start <= current <= end:
            return f"{start[0]}.{start[1]}", str(stage.get("stage", "")).strip()
    return None


def load_feature_gates(gate_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read feature gate stages from the per-gate metadata files (1.31 layout)."""
    gates: dict[str, list[dict[str, Any]]] = {}
    if not gate_dir.is_dir():
        return gates
    for path in sorted(gate_dir.glob("*.md")):
        meta, _ = split_front_matter(path.read_text(encoding="utf-8"))
        if meta.get("title") and isinstance(meta.get("stages"), list):
            gates[str(meta["title"])] = meta["stages"]
    return gates


# --------------------------------------------------------------------------- cleaning


def split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Return (front matter dict, body). Bad YAML falls back to an empty dict."""
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), raw[match.end() :]


def _render_skew(args: str, version: str) -> str:
    parts = [m.group(1) or m.group(2) or m.group(3) for m in POS_ARG_RE.finditer(args)]
    if not parts:
        return version
    kind = parts[0]
    if kind == "currentVersion":
        return version
    if kind == "currentPatchVersion":
        return f"{version}.x"
    if kind == "currentVersionAddMinor" and len(parts) >= 2:
        sep = parts[2] if len(parts) >= 3 else "."
        return f"1{sep}{_minor(version) + int(parts[1])}"
    return version


def _render_feature_state(
    attrs: dict[str, str], version: str, gates: dict[str, list[dict[str, Any]]]
) -> str:
    gate = attrs.get("feature_gate_name")
    if gate:
        state = gate_state(gates.get(gate, []), version)
        if state:
            return f"FEATURE STATE: Kubernetes v{state[0]} [{state[1]}] (feature gate `{gate}`)"
        return f"FEATURE STATE: feature gate `{gate}`"
    since = attrs.get("for_k8s_version", f"v{version}")
    return f"FEATURE STATE: Kubernetes {since} [{attrs.get('state', '')}]"


def render_shortcodes(
    body: str, version: str, gates: dict[str, list[dict[str, Any]]] | None = None
) -> str:
    """Replace Hugo shortcodes with the text a reader would see."""
    gates = gates or {}
    for block in DROP_BLOCKS:
        body = re.sub(
            r"\{\{[<%]\s*" + block + r"\b.*?[>%]\}\}.*?\{\{[<%]\s*/\s*" + block + r"\s*[>%]\}\}",
            "",
            body,
            flags=re.S,
        )

    # One branch per shortcode reads better here than a dispatch table.
    def replace(match: re.Match[str]) -> str:  # pylint: disable=too-many-return-statements
        closing, name, rest = match.group(1), match.group(2), match.group(3)
        attrs = dict(ATTR_RE.findall(rest))
        if closing:
            return ""
        if name in ADMONITIONS:
            return ADMONITIONS[name] + " "
        if name == "skew":
            return _render_skew(rest, version)
        if name == "param" and "version" in rest:
            return f"v{version}"
        if name == "glossary_tooltip":
            return attrs.get("text", "")
        if name == "feature-state":
            return _render_feature_state(attrs, version, gates)
        if name == "heading":
            key = rest.strip().strip('"')
            return HEADING_LABELS.get(key, key.capitalize())
        if name in ("code_sample", "codenew", "code"):
            return f"(example file: {attrs['file']})" if "file" in attrs else ""
        if name == "tab":
            return f"{attrs['name']}:" if "name" in attrs else ""
        return ""  # DROP_TAGS and anything unknown: keep inner text, drop the tag

    return SHORTCODE_RE.sub(replace, body)


def clean_markdown(body: str) -> str:
    """Strip HTML comments, images and link targets; keep text and code."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# --------------------------------------------------------------------------- splitting


def split_sections(body: str, title: str) -> list[tuple[str, str]]:
    """Split on ## and ### outside code fences. Returns (heading path, text)."""
    sections: list[tuple[str, str]] = []
    h2, h3 = "", ""
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            path = " > ".join(p for p in (h2, h3) if p) or title
            sections.append((path, text))

    for line in body.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            flush()
            lines = [match.group(2)]
            if len(match.group(1)) == 2:
                h2, h3 = match.group(2), ""
            else:
                h3 = match.group(2)
            continue
        lines.append(line)
    flush()
    return sections


def _paragraphs(text: str) -> list[str]:
    """Blank-line paragraphs, never cutting through a code fence."""
    paras: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if current:
                paras.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paras.append("\n".join(current))
    return paras


def _pack_units(units: list[str], joiner: str) -> list[str]:
    """Greedily join units into pieces of at most MAX_CHARS."""
    pieces: list[str] = []
    buf = ""
    for unit in units:
        if buf and len(buf) + len(unit) + len(joiner) > MAX_CHARS:
            pieces.append(buf)
            buf = unit
        else:
            buf = f"{buf}{joiner}{unit}" if buf else unit
    if buf:
        pieces.append(buf)
    return pieces


def _pack(text: str) -> list[str]:
    """Split an oversized section on paragraphs, and huge paragraphs on lines."""
    if len(text) <= MAX_CHARS:
        return [text]
    units: list[str] = []
    for para in _paragraphs(text):
        units.extend([para] if len(para) <= MAX_CHARS else _pack_units(para.splitlines(), "\n"))
    return _pack_units(units, "\n\n")


def chunk_page(
    raw: str,
    doc_id: str,
    version: str,
    gates: dict[str, list[dict[str, Any]]] | None = None,
) -> list[Chunk]:
    """Full pipeline for one page: front matter, shortcodes, sections, packing."""
    meta, body = split_front_matter(raw)
    title = str(meta.get("title") or doc_id.rsplit("/", 1)[-1]).strip()
    body = clean_markdown(render_shortcodes(body, version, gates))

    pieces: list[tuple[str, str]] = []
    for path, text in split_sections(body, title):
        pieces.extend((path, piece) for piece in _pack(text))

    merged: list[tuple[str, str]] = []
    for path, text in pieces:
        if (
            merged
            and len(merged[-1][1]) < MIN_CHARS
            and len(merged[-1][1]) + len(text) <= MAX_CHARS
        ):
            merged[-1] = (merged[-1][0], f"{merged[-1][1]}\n\n{text}")
        else:
            merged.append((path, text))

    chunks: list[Chunk] = []
    for path, text in merged:
        if len(re.sub(r"\s", "", text)) < MIN_CONTENT_CHARS:
            continue
        n = len(chunks) + 1
        chunks.append(
            Chunk(
                chunk_id=f"v{version}:{doc_id}#c{n}",
                doc_id=doc_id,
                version=version,
                title=title,
                section=path,
                text=text,
            )
        )
    return chunks
