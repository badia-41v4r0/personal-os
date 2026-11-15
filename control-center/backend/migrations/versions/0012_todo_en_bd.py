"""todo en la base de datos: tareas, entrenos, uni, ofertas y diario

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("area", sa.String(32), nullable=False),
        sa.Column("due", sa.String(10), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("done_on", sa.String(10), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("external_id"))
    op.create_index("ix_tasks_done", "tasks", ["done"])
    op.create_index("ix_tasks_area", "tasks", ["area"])
    op.create_index("ix_tasks_due", "tasks", ["due"])
    op.create_table("workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("hevy_title", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("external_id"))
    op.create_index("ix_workouts_day", "workouts", ["day"])
    op.create_table("workout_exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workout_id", sa.Integer(), sa.ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("exercise_key", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False))
    op.create_index("ix_workout_exercises_name", "workout_exercises", ["name"])
    op.create_index("ix_workout_exercises_exercise_key", "workout_exercises", ["exercise_key"])
    op.create_index("ix_workout_exercises_workout_id", "workout_exercises", ["workout_id"])
    op.create_table("workout_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("workout_exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("warmup", sa.Boolean(), nullable=False),
        sa.Column("failure", sa.Boolean(), nullable=False),
        sa.Column("drop_set", sa.Boolean(), nullable=False),
        sa.Column("rpe", sa.Float(), nullable=True))
    op.create_index("ix_workout_sets_exercise_id", "workout_sets", ["exercise_id"])
    op.create_table("subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("formula", sa.String(300), nullable=False),
        sa.Column("minimums", sa.String(300), nullable=False),
        sa.Column("current_grade", sa.String(32), nullable=False),
        sa.Column("status", sa.String(300), nullable=False),
        sa.UniqueConstraint("code"))
    op.create_table("grade_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(32), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("weight", sa.String(120), nullable=False),
        sa.Column("due", sa.String(40), nullable=False),
        sa.Column("grade", sa.String(32), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("external_id"))
    op.create_index("ix_grade_items_subject", "grade_items", ["subject"])
    op.create_table("assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("due", sa.String(10), nullable=False),
        sa.Column("due_time", sa.String(5), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("external_id"))
    op.create_index("ix_assessments_due", "assessments", ["due"])
    op.create_table("study_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("day", "slot"))
    op.create_index("ix_study_blocks_day", "study_blocks", ["day"])
    op.create_table("job_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("place", sa.String(200), nullable=False),
        sa.Column("link", sa.String(500), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("seen_on", sa.String(10), nullable=False),
        sa.UniqueConstraint("external_id"))
    op.create_index("ix_job_leads_seen_on", "job_leads", ["seen_on"])
    op.create_index("ix_job_leads_score", "job_leads", ["score"])
    op.create_table("journal_days",
        sa.Column("path", sa.String(500), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False))
    op.create_index("ix_journal_days_day", "journal_days", ["day"])
    op.create_table("vault_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("kind", "external_id"))
    op.create_index("ix_vault_records_kind", "vault_records", ["kind"])


def downgrade() -> None:
    op.drop_table("vault_records")
    op.drop_table("journal_days")
    op.drop_table("job_leads")
    op.drop_table("study_blocks")
    op.drop_table("assessments")
    op.drop_table("grade_items")
    op.drop_table("subjects")
    op.drop_table("workout_sets")
    op.drop_table("workout_exercises")
    op.drop_table("workouts")
    op.drop_table("tasks")
