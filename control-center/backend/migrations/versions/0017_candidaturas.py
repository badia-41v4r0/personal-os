"""Candidaturas con agente: documentos (CV), perfil del candidato y solicitudes preparadas.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "career_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="cv"),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="es"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "applicant_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "application_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("document_sha", sa.String(64), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("screenshots", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(1000), nullable=False, server_default=""),
        sa.Column("action_id", sa.String(36), nullable=True),
        sa.Column("vc_id", sa.String(36), nullable=True),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("application_runs")
    op.drop_table("applicant_profile")
    op.drop_table("career_documents")
