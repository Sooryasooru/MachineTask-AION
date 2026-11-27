"""Citation checks: verbatim quotes, no repairs, numbers and maturity words enforced."""

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
    )
    assert len(kept) == 1
    assert kept[0].citations[0].quote in CHUNK.text


def test_wrong_number_is_dropped() -> None:
    kept = validate(
        [
            sentence(
                "The kubelet may be up to four minor versions older.",
                "may be up to three minor versions older",
            )
        ],
        RETRIEVED,
    )
    assert not kept


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
    kept = validate([draft], {FS_CHUNK.chunk_id: FS_CHUNK})
    assert len(kept) == 1


def test_wrong_maturity_is_dropped_even_with_page_context() -> None:
    draft = sentence(
        "On 1.31, user namespaces are stable.",
        "FEATURE STATE: Kubernetes v1.30 [beta]",
        FS_CHUNK.chunk_id,
    )
    assert not validate([draft], {FS_CHUNK.chunk_id: FS_CHUNK})


def test_near_verbatim_quote_snaps_to_real_text() -> None:
    draft = sentence(
        "The kubelet may be three minor versions older.",
        "kubelet may be up to three minor version older than the kube-apiserver",
    )
    kept = validate([draft], RETRIEVED)
    assert len(kept) == 1
    assert kept[0].citations[0].quote in CHUNK.text


def test_good_sentence_kept_and_wrong_number_dropped() -> None:
    good = sentence(
        "The kubelet may be three minor versions older.", "may be up to three minor versions older"
    )
    wrong_number = sentence(
        "The kubelet may be five minor versions older.", "may be up to three minor versions older"
    )
    kept = validate([good, wrong_number], RETRIEVED)
    assert [k.text for k in kept] == [good.text]


KMS_TEXT = (
    "You should use KMS v2 if feasible because KMS v1 is deprecated (since Kubernetes v1.28) "
    "and disabled by default (since Kubernetes v1.29). KMS v2 offers better performance."
)


def test_reordered_quote_keeps_its_longest_verbatim_piece() -> None:
    quote = (
        "KMS v1 is deprecated (since Kubernetes v1.28) and disabled by default "
        "(since Kubernetes v1.29). You should use KMS v2 if feasible"
    )
    span = locate_quote(KMS_TEXT, quote)
    assert span is not None
    assert KMS_TEXT[span[0] : span[1]].startswith("KMS v1 is deprecated (since Kubernetes v1.28)")


def test_quote_spliced_with_ellipsis_keeps_a_real_piece() -> None:
    quote = "You should use KMS v2 if feasible ... KMS v2 offers better performance."
    span = locate_quote(KMS_TEXT, quote)
    assert span is not None and KMS_TEXT[span[0] : span[1]] in KMS_TEXT


def test_spliced_quote_with_no_real_piece_is_rejected() -> None:
    quote = "KMS v1 is fully supported forever ... KMS v3 replaces everything soon enough."
    assert locate_quote(KMS_TEXT, quote) is None


def test_markdown_italics_are_ignored_when_matching() -> None:
    text = "Components select a leader via _coordinated leader election_ during upgrades."
    assert locate_quote(text, "select a leader via coordinated leader election") is not None
