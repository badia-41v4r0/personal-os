"""avisos: bandeja y suscripciones Web Push

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("notifications",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(12), nullable=False), sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("url", sa.String(255), nullable=False),
        sa.Column("source", sa.String(48), nullable=False), sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("pushed", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_notifications_ts", "notifications", ["ts"])
    op.create_index("ix_notifications_source", "notifications", ["source"])
    op.create_index("ix_notifications_read_at", "notifications", ["read_at"])
    op.create_table("push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("endpoint", sa.String(1024), nullable=False),
        sa.Column("p256dh", sa.String(200), nullable=False), sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("label", sa.String(120), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True), sa.Column("last_error", sa.String(300), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("endpoint"))


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_source", table_name="notifications")
    op.drop_index("ix_notifications_ts", table_name="notifications")
    op.drop_table("notifications")
