"""memoria: hechos, eventos, decisiones, procedencia, índice y credenciales de ejecución

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("uri", sa.String(500), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("trust", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_sources_external_id", "sources", ["external_id"])
    op.create_table("facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.String(80), nullable=False),
        sa.Column("predicate", sa.String(80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("verification", sa.String(12), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True))
    op.create_index("ix_facts_valid_to", "facts", ["valid_to"])
    op.create_index("ix_facts_predicate", "facts", ["predicate"])
    op.create_index("ix_facts_subject", "facts", ["subject"])
    op.create_table("life_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("corrects_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False))
    op.create_index("ix_life_events_type", "life_events", ["type"])
    op.create_index("ix_life_events_occurred_at", "life_events", ["occurred_at"])
    op.create_index("ix_life_events_domain", "life_events", ["domain"])
    op.create_table("entity_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_type", sa.String(40), nullable=False),
        sa.Column("from_id", sa.String(64), nullable=False),
        sa.Column("to_type", sa.String(40), nullable=False),
        sa.Column("to_id", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("from_type", "from_id", "to_type", "to_id", "relation"))
    op.create_index("ix_entity_links_to_type", "entity_links", ["to_type"])
    op.create_index("ix_entity_links_from_type", "entity_links", ["from_type"])
    op.create_index("ix_entity_links_from_id", "entity_links", ["from_id"])
    op.create_index("ix_entity_links_to_id", "entity_links", ["to_id"])
    op.create_table("decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decided_on", sa.String(10), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("choice", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_on", sa.String(10), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_decisions_decided_on", "decisions", ["decided_on"])
    op.create_index("ix_decisions_domain", "decisions", ["domain"])
    op.create_table("knowledge_docs",
        sa.Column("path", sa.String(500), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=False))
    op.create_table("run_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(80), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("tainted", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    op.create_index("ix_run_tokens_run_id", "run_tokens", ["run_id"])
    # Solo PostgreSQL: en SQLite la búsqueda sigue siendo la de la vault
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("""CREATE TABLE knowledge_chunks (
            id bigserial PRIMARY KEY, path varchar(500) NOT NULL REFERENCES knowledge_docs(path) ON DELETE CASCADE,
            position integer NOT NULL, heading varchar(300) NOT NULL DEFAULT '', content text NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', heading || ' ' || content)) STORED,
            embedding vector(1024))""")
        op.execute("CREATE INDEX ix_chunks_tsv ON knowledge_chunks USING gin (tsv)")
        op.execute("CREATE INDEX ix_chunks_path ON knowledge_chunks (path)")
        op.execute("CREATE INDEX ix_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE knowledge_chunks")
    op.drop_index("ix_run_tokens_run_id", table_name="run_tokens")
    op.drop_index("ix_decisions_domain", table_name="decisions")
    op.drop_index("ix_decisions_decided_on", table_name="decisions")
    op.drop_index("ix_entity_links_to_id", table_name="entity_links")
    op.drop_index("ix_entity_links_from_id", table_name="entity_links")
    op.drop_index("ix_entity_links_from_type", table_name="entity_links")
    op.drop_index("ix_entity_links_to_type", table_name="entity_links")
    op.drop_index("ix_life_events_domain", table_name="life_events")
    op.drop_index("ix_life_events_occurred_at", table_name="life_events")
    op.drop_index("ix_life_events_type", table_name="life_events")
    op.drop_index("ix_facts_subject", table_name="facts")
    op.drop_index("ix_facts_predicate", table_name="facts")
    op.drop_index("ix_facts_valid_to", table_name="facts")
    op.drop_index("ix_sources_external_id", table_name="sources")
    op.drop_table("run_tokens")
    op.drop_table("knowledge_docs")
    op.drop_table("decisions")
    op.drop_table("entity_links")
    op.drop_table("life_events")
    op.drop_table("facts")
    op.drop_table("sources")
