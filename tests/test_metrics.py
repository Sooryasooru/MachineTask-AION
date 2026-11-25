"""Small, exact checks on the metric helpers."""

from eval.metrics import percentile, rate


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 21))
    assert percentile(values, 95) == 19
    assert percentile([], 95) == 0.0


def test_rate() -> None:
    assert rate([True, False, True, True]) == 0.75
    assert rate([]) == 0.0
