"""Educación: repaso espaciado, tiempo real de estudio, estado de entregas y cambios de Canvas.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edu_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.String(32), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="concepto"),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("source", sa.String(300), nullable=False, server_default=""),
        sa.Column("author", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("due", sa.String(10), nullable=False, index=True),
        sa.Column("ease", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_review", sa.String(10), nullable=False, server_default=""),
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "edu_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("edu_cards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="repaso"),
    )
    op.create_table(
        "edu_study_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False, index=True),
        sa.Column("subject", sa.String(32), nullable=False, server_default="", index=True),
        sa.Column("label", sa.String(300), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "edu_delivery_states",
        sa.Column("key", sa.String(800), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="sin_empezar"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "edu_canvas_items",
        sa.Column("uid", sa.String(200), primary_key=True),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("start", sa.String(40), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "edu_canvas_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("old", sa.String(40), nullable=False, server_default=""),
        sa.Column("new", sa.String(40), nullable=False, server_default=""),
        sa.Column("seen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "edu_calendar_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False, index=True),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.UniqueConstraint("day", "slot"),
    )
    op.add_column("subjects", sa.Column("credits", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("subjects", "credits")
    for t in ("edu_calendar_blocks", "edu_canvas_changes", "edu_canvas_items", "edu_delivery_states", "edu_study_sessions", "edu_reviews", "edu_cards"):
        op.drop_table(t)
