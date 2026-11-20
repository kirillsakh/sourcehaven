from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_MARKER: str = "replace-me"


class Settings(BaseSettings):
    """Application settings read from `SOURCEHAVEN_*` variables and an optional `.env` file.

    `OPENAI_API_KEY` is also accepted without the prefix. Production deployments are
    rejected unless every safety-relevant provider and cookie setting is real and no credential
    that is set still holds the placeholder.
    """

    model_config = SettingsConfigDict(
        env_prefix="SOURCEHAVEN_",
        env_file=".env",
        # Compose passes unset optional variables as empty strings; treat them as unset.
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    # Connects as the non-owner `sourcehaven_app` role; row-level security applies.
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://sourcehaven_app:replace-me@postgres:5432/sourcehaven"
    )
    # The credentials below belong to single commands and are unset elsewhere, so a compromised
    # api or worker container does not hold the owner or BYPASSRLS credentials.
    # Connects as `sourcehaven_maintenance` (BYPASSRLS); never used for request handling.
    maintenance_database_url: SecretStr | None = None
    # Owner connection, used only by `sourcehaven migrate`.
    admin_database_url: SecretStr | None = None
    # Applied to the database roles by `sourcehaven migrate`.
    app_role_password: SecretStr | None = None
    maintenance_role_password: SecretStr | None = None

    # Address of the reverse proxy whose X-Forwarded-* headers uvicorn trusts.
    trusted_proxy: str = "127.0.0.1"

    uploads_dir: Path = Path("/var/lib/sourcehaven/uploads")

    embedding_provider: Literal["tei", "hash"] = "tei"
    tei_url: str = "http://embeddings:80"
    embedding_model_id: str = "Snowflake/snowflake-arctic-embed-m-v2.0"
    embedding_model_revision: str | None = None
    embedding_dimensions: int = 768
    embedding_query_prefix: str = "query: "
    embedding_document_prefix: str = ""
    embedding_max_input_tokens: int = 2048
    tokenizer_file: Path | None = None

    chunk_tokens: int = 400
    chunk_overlap: int = 60
    evidence_threshold: float = 0.0

    generation_provider: Literal["openai", "fake"] = "openai"
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "SOURCEHAVEN_OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-6-luna"
    # Unset by default: reasoning models such as gpt-6-luna reject any temperature other than
    # their default, and an unset value is omitted from the request.
    generation_temperature: float | None = None
    max_output_tokens: int = 800

    human_verification: Literal["turnstile", "disabled"] = "turnstile"
    cookie_secure: bool = True

    max_upload_bytes: int = 20 * 1024 * 1024
    max_pages_per_document: int = 300
    max_documents_per_session: int = 10
    max_question_chars: int = 2000
    max_documents_per_question: int = 10
    session_idle_hours: int = 24
    session_absolute_days: int = 7

    @model_validator(mode="after")
    def reject_unsafe_combinations(self) -> Self:
        if self.embedding_provider == "tei" and not self.embedding_model_revision:
            raise ValueError("embedding_model_revision is required when embedding_provider is tei")
        if self.environment == "production":
            self._reject_unsafe_production_settings()
        return self

    def _reject_unsafe_production_settings(self) -> None:
        if self.embedding_provider == "hash":
            raise ValueError("embedding_provider must not be hash in production")
        if self.generation_provider == "fake":
            raise ValueError("generation_provider must not be fake in production")
        if self.human_verification == "disabled":
            raise ValueError("human_verification must not be disabled in production")
        if not self.cookie_secure:
            raise ValueError("cookie_secure must be true in production")
        if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
            raise ValueError("openai_api_key is required in production")
        credentials: dict[str, SecretStr | None] = {
            "database_url": self.database_url,
            "maintenance_database_url": self.maintenance_database_url,
            "admin_database_url": self.admin_database_url,
            "app_role_password": self.app_role_password,
            "maintenance_role_password": self.maintenance_role_password,
        }
        for name, secret in credentials.items():
            if secret is not None and PLACEHOLDER_MARKER in secret.get_secret_value():
                raise ValueError(f"{name} still contains the placeholder credential in production")
