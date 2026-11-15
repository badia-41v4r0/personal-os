"""Gym: periodos sin entrenar (enfermedad, lesión, vacaciones).

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gym_pauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("start", sa.String(10), nullable=False, index=True),
        sa.Column("end", sa.String(10), nullable=True),
        sa.Column("reason", sa.String(16), nullable=False, server_default="enfermedad"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gym_pauses")
