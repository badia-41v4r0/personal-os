"""uso de proveedores alternativos

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("provider_usage",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("key", sa.String(48), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False), sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("model", sa.String(96), nullable=False), sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("windows", sa.JSON(), nullable=False), sa.Column("error", sa.String(500), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_provider_usage_key", "provider_usage", ["key"])
    op.create_index("ix_provider_usage_ts", "provider_usage", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_provider_usage_ts", table_name="provider_usage")
    op.drop_index("ix_provider_usage_key", table_name="provider_usage")
    op.drop_table("provider_usage")
