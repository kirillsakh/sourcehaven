# Markers (integration, live) are declared in pyproject.toml.
import pytest

from sourcehaven.config import Settings

pytest_plugins: list[str] = ["tests.support.app", "tests.support.visitors"]


@pytest.fixture(autouse=True)
def ignore_local_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's `.env` out of every test, so results depend only on the test itself."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
