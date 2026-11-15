"""último análisis general del agente de finanzas

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("finance_analyses", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("author", sa.String(80), nullable=False))
    op.create_index("ix_finance_analyses_created_at", "finance_analyses", ["created_at"])


def downgrade() -> None:
    op.drop_table("finance_analyses")
