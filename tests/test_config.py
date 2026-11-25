"""Settings must come from the environment, with sensible defaults."""

from app.config import Settings


def test_default_port() -> None:
    assert Settings().port == 8080
