from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from sourcehaven.config import Settings


class EnvironmentOnlySettings(Settings):
    """Settings that ignore any local `.env` file so tests see only the process environment."""

    model_config = SettingsConfigDict(env_file=None)


def build_settings(**overrides: Any) -> Settings:  # noqa: ANN401
    """Build settings, passing raw overrides that pydantic validates at runtime."""
    return EnvironmentOnlySettings(**overrides)


SECRET_FIELDS: tuple[str, ...] = (
    "database_url",
    "maintenance_database_url",
    "admin_database_url",
    "app_role_password",
    "maintenance_role_password",
)


def set_production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCEHAVEN_ENVIRONMENT", "production")
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_MODEL_REVISION", "abc123")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for field in SECRET_FIELDS:
        monkeypatch.setenv(f"SOURCEHAVEN_{field.upper()}", "postgresql+psycopg://u:s3cret@db/x")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "SOURCEHAVEN_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_spec_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_MODEL_REVISION", "abc123")
    settings: Settings = build_settings()
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_pages_per_document == 300
    assert settings.max_documents_per_session == 10
    assert settings.chunk_tokens == 400 and settings.chunk_overlap == 60
    assert settings.openai_model == "gpt-6-luna"


def test_openai_key_read_from_unprefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "hash")
    settings: Settings = build_settings()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("EMBEDDING_PROVIDER", "hash"),
        ("GENERATION_PROVIDER", "fake"),
        ("HUMAN_VERIFICATION", "disabled"),
        ("COOKIE_SECURE", "false"),
    ],
)
def test_production_rejects_unsafe_settings(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv(f"SOURCEHAVEN_{field}", value)
    with pytest.raises(ValidationError, match=field.lower()):
        build_settings()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_production_requires_openai_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    set_production_environment(monkeypatch)
    if key is None:
        monkeypatch.delenv("OPENAI_API_KEY")
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    with pytest.raises(ValidationError, match="openai_api_key"):
        build_settings()


@pytest.mark.parametrize("field", SECRET_FIELDS)
def test_production_rejects_placeholder_credentials(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv(f"SOURCEHAVEN_{field.upper()}", "postgresql+psycopg://u:replace-me@db/x")
    with pytest.raises(ValidationError, match=field):
        build_settings()


@pytest.mark.parametrize("field", SECRET_FIELDS[1:])
def test_command_specific_credentials_are_optional(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.delenv(f"SOURCEHAVEN_{field.upper()}")
    assert getattr(build_settings(), field) is None


def test_development_keeps_placeholder_credentials() -> None:
    settings: Settings = build_settings(embedding_provider="hash")
    assert "replace-me" in settings.database_url.get_secret_value()


def test_production_accepts_safe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_production_environment(monkeypatch)
    settings: Settings = build_settings()
    assert settings.human_verification == "turnstile"
    assert settings.cookie_secure is True


def test_tei_requires_pinned_revision() -> None:
    with pytest.raises(ValidationError, match="embedding_model_revision"):
        build_settings(embedding_provider="tei")


def test_trusted_proxy_defaults_to_loopback() -> None:
    assert build_settings(embedding_provider="hash").trusted_proxy == "127.0.0.1"
