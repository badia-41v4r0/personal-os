"""objetivos, hábitos, salud, candidaturas y estilo de vida

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("goals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("area", sa.String(32), nullable=False, index=True), sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, index=True), sa.Column("target_date", sa.String(10), nullable=True),
        sa.Column("why", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("milestones", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("done_at", sa.DateTime(), nullable=True))
    op.create_table("habits", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("habit_logs", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("habit_id", sa.Integer(), sa.ForeignKey("habits.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("day", sa.String(10), nullable=False, index=True), sa.UniqueConstraint("habit_id", "day"))
    op.create_table("health_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("day", sa.String(10), nullable=False, index=True),
        sa.Column("metric", sa.String(32), nullable=False, index=True), sa.Column("value", sa.Float(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("job_applications", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company", sa.String(160), nullable=False),
        sa.Column("role", sa.String(200), nullable=False), sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("link", sa.String(500), nullable=False), sa.Column("next_step", sa.String(300), nullable=False),
        sa.Column("follow_up", sa.String(10), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("lifestyle_items", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("kind", sa.String(16), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("day", sa.String(10), nullable=True, index=True),
        sa.Column("note", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    for t in ("lifestyle_items", "job_applications", "health_logs", "habit_logs", "habits", "milestones", "goals"):
        op.drop_table(t)
