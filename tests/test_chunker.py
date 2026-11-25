"""Chunking rules that the rest of the system depends on."""

from rag.chunker import MAX_CHARS, chunk_page, gate_state, render_shortcodes
from rag.terms import extract_terms

PAGE = """---
title: Version Skew Policy
---
Intro text that is long enough to stand as its own chunk of documentation here.

## kubelet

`kubelet` may be up to three minor versions older than `kube-apiserver`.
Supported: {{< skew currentVersionAddMinor -1 >}} and {{< skew currentVersion >}}.

```shell
## not a heading, this sits inside a code fence
kubelet --max-pods=110
```

### Details

{{< note >}}
Drain pods first. See {{< glossary_tooltip text="node" term_id="node" >}}.
{{< /note >}}
"""


def test_chunk_ids_are_stable_and_versioned() -> None:
    first = chunk_page(PAGE, "releases/version-skew-policy", "1.31")
    second = chunk_page(PAGE, "releases/version-skew-policy", "1.31")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert first[0].chunk_id == "v1.31:releases/version-skew-policy#c1"
    assert all(c.version == "1.31" for c in first)


def test_skew_renders_per_version() -> None:
    old = " ".join(c.text for c in chunk_page(PAGE, "d", "1.27"))
    new = " ".join(c.text for c in chunk_page(PAGE, "d", "1.31"))
    assert "1.26 and 1.27" in old
    assert "1.30 and 1.31" in new


def test_no_shortcodes_survive() -> None:
    text = " ".join(c.text for c in chunk_page(PAGE, "d", "1.31"))
    assert "{{" not in text
    assert "Note:" in text and "node" in text


def test_heading_inside_code_fence_is_not_a_split() -> None:
    chunks = chunk_page(PAGE, "d", "1.31")
    assert not any(c.section.startswith("not a heading") for c in chunks)


def test_long_sections_are_split() -> None:
    body = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(20))
    chunks = chunk_page(f"---\ntitle: Long\n---\n## Big\n{body}", "d", "1.31")
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS + 1 for c in chunks)


def test_feature_state_from_gate_metadata() -> None:
    stages = [
        {"stage": "alpha", "fromVersion": "1.28", "toVersion": "1.28"},
        {"stage": "beta", "fromVersion": "1.29"},
    ]
    gates = {"SidecarContainers": stages}
    text = render_shortcodes(
        '{{< feature-state feature_gate_name="SidecarContainers" >}}', "1.31", gates
    )
    assert text.startswith("FEATURE STATE: Kubernetes v1.29 [beta]")
    assert gate_state(stages, "1.28") == ("1.28", "alpha")
    assert gate_state(stages, "1.27") is None


def test_terms_catch_flags_and_gates() -> None:
    terms = extract_terms("Use `--max-pods=110` and enable SidecarContainers or `restartPolicy`.")
    assert {"--max-pods", "sidecarcontainers", "restartpolicy"} <= terms
