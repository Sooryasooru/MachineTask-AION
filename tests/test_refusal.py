"""Gates that refuse before generation."""

from rag.refusal import check_false_premise, check_input, check_retrieval, clean_question

VOCAB = {"kubelet", "minor", "versions", "lag", "behind", "default", "max-pods", "swap", "node"}
TERMS = {"--max-pods", "nodeswap", "statefulset"}


def test_empty_and_whitespace_are_refused() -> None:
    assert check_input(clean_question("   ", 1000), VOCAB) is not None
    assert check_input(clean_question(None, 1000), VOCAB) is not None


def test_long_question_is_capped_not_rejected() -> None:
    assert len(clean_question("kubelet " * 1000, 1000)) <= 1000


def test_english_technical_question_passes() -> None:
    assert check_input("How far can the kubelet lag behind?", VOCAB) is None
    assert check_input("kubelet --max-pods default?", VOCAB) is None


def test_other_languages_are_refused() -> None:
    assert check_input("¿Cuántas versiones menores puede retrasarse el kubelet?", VOCAB) is not None
    assert check_input("kubelet 可以落后多少个版本？", VOCAB) is not None


def test_invented_flag_and_gate_are_false_premises() -> None:
    assert check_false_premise("How do I set --max-pod-lag?", TERMS) is not None
    assert check_false_premise("What does PodAutoRepair do?", TERMS) is not None


def test_real_terms_pass() -> None:
    assert check_false_premise("What is the default --max-pods?", TERMS) is None
    assert check_false_premise("How does a StatefulSet scale?", TERMS) is None


def test_weak_retrieval() -> None:
    assert check_retrieval(0.01, 0.05) is not None
    assert check_retrieval(0.9, 0.05) is None
