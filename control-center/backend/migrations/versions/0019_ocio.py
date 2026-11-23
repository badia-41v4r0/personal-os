"""Ocio: pelis y series.

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False, index=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("original_title", sa.String(300), nullable=False, server_default=""),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=False, server_default=""),
        sa.Column("genres", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("seasons", sa.Integer(), nullable=True),
        sa.Column("episodes", sa.Integer(), nullable=True),
        sa.Column("show_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("poster", sa.String(80), nullable=False, server_default=""),
        sa.Column("tmdb_rating", sa.Float(), nullable=True),
        sa.Column("providers", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("season_episodes", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False, server_default="pendiente", index=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("started_on", sa.String(10), nullable=True),
        sa.Column("finished_on", sa.String(10), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kind", "tmdb_id"),
    )


def downgrade() -> None:
    op.drop_table("media_items")
