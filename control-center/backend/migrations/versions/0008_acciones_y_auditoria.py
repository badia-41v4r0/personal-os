"""acciones, políticas, revocaciones y auditoría encadenada

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("actions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False), sa.Column("actor_type", sa.String(12), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("tainted", sa.Boolean(), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(500), nullable=False), sa.Column("decided_by", sa.String(80), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True), sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key"))
    for c in ("capability", "status", "run_id", "created_at"):
        op.create_index(f"ix_actions_{c}", "actions", [c])
    op.create_table("policies",
        sa.Column("capability", sa.String(80), primary_key=True), sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("limits", sa.JSON(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(80), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("revocations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("agent", sa.String(80), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False), sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_by", sa.String(80), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("system_flags",
        sa.Column("key", sa.String(48), primary_key=True), sa.Column("value", sa.String(200), nullable=False),
        sa.Column("updated_by", sa.String(80), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    with op.batch_alter_table("audit_logs") as b:
        b.add_column(sa.Column("actor_type", sa.String(12), nullable=False, server_default="user"))
        b.add_column(sa.Column("run_id", sa.String(64), nullable=False, server_default=""))
        b.add_column(sa.Column("action_id", sa.String(36), nullable=False, server_default=""))
        b.add_column(sa.Column("prev_hash", sa.String(64), nullable=False, server_default=""))
        b.add_column(sa.Column("hash", sa.String(64), nullable=False, server_default=""))
        b.create_index("ix_audit_logs_run_id", ["run_id"])
        b.create_index("ix_audit_logs_action_id", ["action_id"])


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as b:
        b.drop_index("ix_audit_logs_action_id")
        b.drop_index("ix_audit_logs_run_id")
        for c in ("hash", "prev_hash", "action_id", "run_id", "actor_type"):
            b.drop_column(c)
    op.drop_table("system_flags")
    op.drop_table("revocations")
    op.drop_table("policies")
    for c in ("created_at", "run_id", "status", "capability"):
        op.drop_index(f"ix_actions_{c}", table_name="actions")
    op.drop_table("actions")
