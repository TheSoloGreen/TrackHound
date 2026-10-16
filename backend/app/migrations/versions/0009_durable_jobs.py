"""Persist bounded work and outcomes independently of HTTP requests."""

from alembic import op
import sqlalchemy as sa

revision = "0009_durable_jobs"
down_revision = "0008_structured_issues"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_key", sa.String(64), unique=True, nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.create_index("ix_jobs_user_status_id", "jobs", ["user_id", "status", "id"])


def downgrade():
    op.drop_table("jobs")
