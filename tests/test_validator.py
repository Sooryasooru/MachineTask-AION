"""Citation checks: verbatim quotes, no repairs, numbers and support enforced."""

from collections.abc import Sequence

from rag.chunker import Chunk
from rag.generator import DraftCitation, DraftSentence, parse_reply
from rag.validator import locate_quote, numbers_in, validate

CHUNK = Chunk(
    chunk_id="v1.31:releases/skew#c2",
    doc_id="releases/skew",
    version="1.31",
    title="Skew",
    section="kubelet",
    text="* `kubelet` may be up to three minor versions older than `kube-apiserver`.",
)
RETRIEVED = {CHUNK.chunk_id: CHUNK}


def entail_all(pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float, float]]:
    return [(0.01, 0.98, 0.01) for _ in pairs]


def neutral_all(pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float, float]]:
    return [(0.05, 0.10, 0.85) for _ in pairs]


def contradict_all(pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float, float]]:
    return [(0.90, 0.05, 0.05) for _ in pairs]


def sentence(text: str, quote: str, chunk_id: str = CHUNK.chunk_id) -> DraftSentence:
    return DraftSentence(text, [DraftCitation(chunk_id, quote)])


def test_exact_quote_is_found() -> None:
    span = locate_quote(CHUNK.text, "may be up to three minor versions older")
    assert span is not None
    assert CHUNK.text[span[0] : span[1]] == "may be up to three minor versions older"


def test_quote_without_backticks_maps_back_to_original_text() -> None:
    span = locate_quote(CHUNK.text, "kubelet may be up to three minor versions")
    assert span is not None
    original = CHUNK.text[span[0] : span[1]]
    assert original == "kubelet` may be up to three minor versions"
    assert original in CHUNK.text


def test_invented_quote_is_rejected() -> None:
    assert locate_quote(CHUNK.text, "may be up to four minor versions older") is None
    assert locate_quote(CHUNK.text, "kubelet") is None  # too short to mean anything


def test_supported_sentence_survives_with_verbatim_quote() -> None:
    kept = validate(
        [
            sentence(
                "On 1.31, the kubelet may be up to three minor versions older than the API server.",
                "kubelet may be up to three minor versions older",
            )
        ],
        RETRIEVED,
        entail_all,
        0.5,
    )
    assert len(kept) == 1
    assert kept[0].citations[0].quote in CHUNK.text


def test_wrong_number_is_dropped_even_if_nli_agrees() -> None:
    kept = validate(
        [
            sentence(
                "The kubelet may be up to four minor versions older.",
                "may be up to three minor versions older",
            )
        ],
        RETRIEVED,
        entail_all,
        0.5,
    )
    assert not kept


def test_contradiction_is_dropped() -> None:
    kept = validate(
        [
            sentence(
                "The kubelet must match the API server version.",
                "may be up to three minor versions older",
            )
        ],
        RETRIEVED,
        contradict_all,
        0.5,
    )
    assert not kept


def test_neutral_kept_only_when_words_come_from_the_quote() -> None:
    close = sentence(
        "The kubelet may be three minor versions older.",
        "kubelet may be up to three minor versions older",
    )
    far = sentence(
        "Upgrading the kubelet first avoids downtime for workloads.",
        "kubelet may be up to three minor versions older",
    )
    kept = validate([close, far], RETRIEVED, neutral_all, 0.5)
    assert [k.text for k in kept] == [close.text]


def test_citation_to_unretrieved_chunk_is_dropped() -> None:
    kept = validate(
        [
            sentence(
                "The kubelet may be three minor versions older.",
                "may be up to three minor versions older",
                "v1.27:other#c1",
            )
        ],
        RETRIEVED,
        entail_all,
        0.5,
    )
    assert not kept


def test_numbers_ignore_release_versions() -> None:
    assert numbers_in("On 1.31, up to three versions, 40 seconds") == {"3", "40"}


def test_parse_reply_survives_garbage() -> None:
    assert parse_reply("not json at all").answerable is False
    draft = parse_reply(
        '{"answerable": true, "sentences": [{"text": "A [v1.31:x#c1].", "citations": []}]}'
    )
    assert draft.sentences[0].text == "A."


FS_CHUNK = Chunk(
    chunk_id="v1.31:concepts/user-namespaces#c1",
    doc_id="concepts/user-namespaces",
    version="1.31",
    title="User Namespaces",
    section="User Namespaces",
    text=(
        "FEATURE STATE: Kubernetes v1.30 [beta] (feature gate `UserNamespacesSupport`)\n\n"
        "This page explains user namespaces."
    ),
)


def test_feature_state_line_supports_claim_about_page_subject() -> None:
    draft = sentence(
        "On 1.31, user namespaces are beta.",
        "FEATURE STATE: Kubernetes v1.30 [beta]",
        FS_CHUNK.chunk_id,
    )
    kept = validate([draft], {FS_CHUNK.chunk_id: FS_CHUNK}, neutral_all, 0.5)
    assert len(kept) == 1


def test_wrong_maturity_is_dropped_even_with_page_context() -> None:
    draft = sentence(
        "On 1.31, user namespaces are stable.",
        "FEATURE STATE: Kubernetes v1.30 [beta]",
        FS_CHUNK.chunk_id,
    )
    assert not validate([draft], {FS_CHUNK.chunk_id: FS_CHUNK}, entail_all, 0.5)


def test_near_verbatim_quote_snaps_to_real_text() -> None:
    draft = sentence(
        "The kubelet may be three minor versions older.",
        "kubelet may be up to three minor version older than the kube-apiserver",
    )
    kept = validate([draft], RETRIEVED, entail_all, 0.5)
    assert len(kept) == 1
    assert kept[0].citations[0].quote in CHUNK.text


def test_without_nli_the_other_checks_still_apply() -> None:
    good = sentence(
        "The kubelet may be three minor versions older.", "may be up to three minor versions older"
    )
    wrong_number = sentence(
        "The kubelet may be five minor versions older.", "may be up to three minor versions older"
    )
    kept = validate([good, wrong_number], RETRIEVED, None, 0.5)
    assert [k.text for k in kept] == [good.text]
