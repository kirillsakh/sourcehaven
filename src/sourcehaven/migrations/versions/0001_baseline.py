"""Baseline schema, database roles, row-level security and cross-owner functions.

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_SCOPED_TABLES: tuple[str, ...] = (
    "owners",
    "anonymous_sessions",
    "documents",
    "document_versions",
    "ingestion_jobs",
    "chunks",
    "conversations",
    "turns",
    "turn_sources",
)
# PostgreSQL reports a custom setting as '' (not NULL) once the transaction that set it locally
# has ended, so on a reused pooled connection an empty value must also mean "no owner"; a bare
# ''::uuid cast would raise instead of hiding every row.
OWNER_SETTING: str = "NULLIF(current_setting('app.owner_id', true), '')::uuid"

CREATE_ROLES: str = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sourcehaven_app') THEN
    CREATE ROLE sourcehaven_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sourcehaven_maintenance') THEN
    CREATE ROLE sourcehaven_maintenance NOLOGIN BYPASSRLS; END IF;
END $$
"""

# Table names are schema-qualified so that a temporary table, which a caller could create to
# shadow a table under `search_path = public`, is never read by these SECURITY DEFINER functions.
CREATE_RESOLVE_SESSION: str = """
CREATE FUNCTION sourcehaven_resolve_session(p_token_hash bytea, p_now timestamptz)
RETURNS TABLE(session_id uuid, owner_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
  SELECT s.id, s.owner_id
  FROM public.anonymous_sessions AS s
  WHERE s.token_hash = p_token_hash
    AND s.ended_at IS NULL
    AND s.idle_expires_at > p_now
    AND s.absolute_expires_at > p_now
$$
"""

CREATE_CLAIM_INGESTION_JOB: str = """
CREATE FUNCTION sourcehaven_claim_ingestion_job(p_lease_seconds int, p_now timestamptz)
RETURNS TABLE(job_id uuid, owner_id uuid, version_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public
AS $$
  UPDATE public.ingestion_jobs AS j
  SET status = 'running',
      lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
      attempts = j.attempts + 1
  WHERE j.id = (
    SELECT c.id
    FROM public.ingestion_jobs AS c
    WHERE (c.status IN ('queued', 'retry') AND c.next_attempt_at <= p_now)
       OR (c.status = 'running' AND c.lease_expires_at < p_now)
    ORDER BY c.created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING j.id, j.owner_id, j.version_id
$$
"""

FUNCTION_SIGNATURES: tuple[str, ...] = (
    "sourcehaven_resolve_session(bytea, timestamptz)",
    "sourcehaven_claim_ingestion_job(int, timestamptz)",
)


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _owner_id() -> sa.Column[object]:
    return sa.Column("owner_id", sa.Uuid(), nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _timestamp(name: str, *, nullable: bool) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _owner_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["owner_id"], ["owners.id"], name=f"fk_{table}_owner_id_owners", ondelete="CASCADE"
    )


def _owned_fk(table: str, column: str, parent: str, *, ondelete: str) -> sa.ForeignKeyConstraint:
    # Foreign-key checks bypass row-level security, so the key includes owner_id: a reference to
    # another owner's parent then fails exactly like a reference to a nonexistent id.
    return sa.ForeignKeyConstraint(
        ["owner_id", column],
        [f"{parent}.owner_id", f"{parent}.id"],
        name=f"fk_{table}_owner_id_{column}_{parent}",
        ondelete=ondelete,
    )


def _owner_and_id_unique(table: str) -> sa.UniqueConstraint:
    # Target of the owner-scoped foreign keys; also serves as the owner_id index.
    return sa.UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id_id")


def _owner_index(table: str) -> None:
    op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])


def upgrade() -> None:
    op.execute(CREATE_ROLES)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _create_tables()
    _protect_owner_scoped_tables()
    op.execute("GRANT SELECT, INSERT ON embedding_configs TO sourcehaven_app")
    # Lets the readiness check compare the applied revision with the packaged head.
    op.execute("GRANT SELECT ON alembic_version TO sourcehaven_app")
    _create_functions()


def _create_tables() -> None:
    op.create_table(
        "owners",
        _id(),
        sa.Column("kind", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_owners"),
        sa.CheckConstraint("kind IN ('anonymous_session', 'account')", name="ck_owners_kind"),
    )
    op.create_table(
        "anonymous_sessions",
        _id(),
        _owner_id(),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        _created_at(),
        _timestamp("last_active_at", nullable=False),
        _timestamp("idle_expires_at", nullable=False),
        _timestamp("absolute_expires_at", nullable=False),
        _timestamp("ended_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_anonymous_sessions"),
        _owner_fk("anonymous_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_anonymous_sessions_token_hash"),
    )
    _owner_index("anonymous_sessions")
    op.create_table(
        "embedding_configs",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("query_prefix", sa.Text(), nullable=False),
        sa.Column("document_prefix", sa.Text(), nullable=False),
        sa.Column("normalize", sa.Boolean(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("distance", sa.Text(), nullable=False),
        sa.Column("chunk_tokens", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_configs"),
        sa.UniqueConstraint("fingerprint", name="uq_embedding_configs_fingerprint"),
    )
    op.create_table(
        "documents",
        _id(),
        _owner_id(),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        _owner_fk("documents"),
        # Also serves as the owner_id index.
        sa.UniqueConstraint(
            "owner_id", "content_sha256", name="uq_documents_owner_id_content_sha256"
        ),
        _owner_and_id_unique("documents"),
    )
    op.create_table(
        "document_versions",
        _id(),
        _owner_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("detected_language", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("parser_name", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("chunker_fingerprint", sa.Text(), nullable=True),
        sa.Column("embedding_config_id", sa.Integer(), nullable=True),
        sa.Column("ingestion_fingerprint", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "skipped_pages",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        _created_at(),
        _timestamp("ready_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        _owner_fk("document_versions"),
        _owned_fk("document_versions", "document_id", "documents", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["embedding_config_id"],
            ["embedding_configs.id"],
            name="fk_document_versions_embedding_config_id_embedding_configs",
        ),
        # Keys holding a reference column start with owner_id: unique indexes are checked as each
        # row is inserted, before the foreign keys, so a global key would report a collision with
        # another owner's row instead of the foreign-key violation a nonexistent parent gives.
        sa.UniqueConstraint(
            "owner_id",
            "document_id",
            "version_no",
            name="uq_document_versions_owner_id_document_id_version_no",
        ),
        _owner_and_id_unique("document_versions"),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'ready', 'failed', 'superseded')",
            name="ck_document_versions_state",
        ),
    )
    # Only current_version_id is cleared on delete; owner_id stays (PostgreSQL 15+ column list).
    op.create_foreign_key(
        "fk_documents_owner_id_current_version_id_document_versions",
        "documents",
        "document_versions",
        ["owner_id", "current_version_id"],
        ["owner_id", "id"],
        ondelete="SET NULL (current_version_id)",
    )
    op.create_table(
        "ingestion_jobs",
        _id(),
        _owner_id(),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("progress_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _timestamp("lease_expires_at", nullable=True),
        _timestamp("next_attempt_at", nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        _owner_fk("ingestion_jobs"),
        _owned_fk("ingestion_jobs", "version_id", "document_versions", ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "version_id", name="uq_ingestion_jobs_owner_id_version_id"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'succeeded', 'failed')",
            name="ck_ingestion_jobs_status",
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_status_next_attempt_at", "ingestion_jobs", ["status", "next_attempt_at"]
    )
    op.create_table(
        "chunks",
        _id(),
        _owner_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_config_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        _owner_fk("chunks"),
        _owned_fk("chunks", "document_id", "documents", ondelete="CASCADE"),
        _owned_fk("chunks", "version_id", "document_versions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["embedding_config_id"],
            ["embedding_configs.id"],
            name="fk_chunks_embedding_config_id_embedding_configs",
        ),
        sa.UniqueConstraint(
            "owner_id", "version_id", "ordinal", name="uq_chunks_owner_id_version_id_ordinal"
        ),
    )
    # Also serves as the owner_id index.
    op.create_index("ix_chunks_owner_id_document_id", "chunks", ["owner_id", "document_id"])
    op.create_table(
        "conversations",
        _id(),
        _owner_id(),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        _owner_fk("conversations"),
        _owner_and_id_unique("conversations"),
    )
    op.create_table(
        "turns",
        _id(),
        _owner_id(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column(
            "selected_document_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=True),
        _created_at(),
        _timestamp("completed_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_turns"),
        _owner_fk("turns"),
        _owned_fk("turns", "conversation_id", "conversations", ondelete="CASCADE"),
        _owner_and_id_unique("turns"),
        sa.UniqueConstraint(
            "owner_id",
            "conversation_id",
            "client_request_id",
            name="uq_turns_owner_id_conversation_id_client_request_id",
        ),
        sa.CheckConstraint("kind IN ('question', 'summary')", name="ck_turns_kind"),
        sa.CheckConstraint(
            "status IN ('generating', 'complete', 'interrupted', 'failed')",
            name="ck_turns_status",
        ),
    )
    op.create_index(
        "uq_turns_owner_id_conversation_id_generating",
        "turns",
        ["owner_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'generating'"),
    )
    op.create_table(
        "turn_sources",
        _owner_id(),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("cited", sa.Boolean(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("document_name_snapshot", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("quote_snapshot", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", "turn_id", "label", name="pk_turn_sources"),
        _owner_fk("turn_sources"),
        _owned_fk("turn_sources", "turn_id", "turns", ondelete="CASCADE"),
        _owned_fk("turn_sources", "document_id", "documents", ondelete="SET NULL (document_id)"),
        _owned_fk(
            "turn_sources", "version_id", "document_versions", ondelete="SET NULL (version_id)"
        ),
    )


def _protect_owner_scoped_tables() -> None:
    for table in OWNER_SCOPED_TABLES:
        owner_column: str = "id" if table == "owners" else "owner_id"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_isolation ON {table}"
            f" USING ({owner_column} = {OWNER_SETTING})"
            f" WITH CHECK ({owner_column} = {OWNER_SETTING})"
        )
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table}"
            " TO sourcehaven_app, sourcehaven_maintenance"
        )


def _create_functions() -> None:
    op.execute(CREATE_RESOLVE_SESSION)
    op.execute(CREATE_CLAIM_INGESTION_JOB)
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sourcehaven_maintenance")
        # Functions are executable by PUBLIC by default.
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sourcehaven_app")


def downgrade() -> None:
    # Roles are cluster-wide and the extension may be shared, so both are left in place.
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"DROP FUNCTION {signature}")
    op.drop_constraint(
        "fk_documents_owner_id_current_version_id_document_versions",
        "documents",
        type_="foreignkey",
    )
    for table in (
        "turn_sources",
        "turns",
        "conversations",
        "chunks",
        "ingestion_jobs",
        "document_versions",
        "documents",
        "embedding_configs",
        "anonymous_sessions",
        "owners",
    ):
        op.drop_table(table)
