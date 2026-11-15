"""Check-ins de la mañana y de la noche.

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False, index=True),
        sa.Column("slot", sa.String(8), nullable=False),
        sa.Column("mood", sa.Integer(), nullable=True),
        sa.Column("energy", sa.Integer(), nullable=True),
        sa.Column("sleep_h", sa.Float(), nullable=True),
        sa.Column("intention", sa.String(300), nullable=False, server_default=""),
        sa.Column("note", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("day", "slot"),
    )


def downgrade() -> None:
    op.drop_table("checkins")
