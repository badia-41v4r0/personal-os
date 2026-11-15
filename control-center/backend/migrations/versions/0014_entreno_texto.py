"""Cada entreno guarda su texto exacto: la base puede rehacer Gym.md sin depender del archivo.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("source_text", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("workouts", "source_text")
