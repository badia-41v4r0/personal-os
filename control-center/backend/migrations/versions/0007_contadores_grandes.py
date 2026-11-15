"""contadores de red en 64 bits (superan el entero de 32 bits de PostgreSQL)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("metric_samples") as b:
        b.alter_column("net_sent", type_=sa.BigInteger(), existing_type=sa.Integer())
        b.alter_column("net_recv", type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    with op.batch_alter_table("metric_samples") as b:
        b.alter_column("net_recv", type_=sa.Integer(), existing_type=sa.BigInteger())
        b.alter_column("net_sent", type_=sa.Integer(), existing_type=sa.BigInteger())
