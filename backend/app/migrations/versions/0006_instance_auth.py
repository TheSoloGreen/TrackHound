"""Persist the chosen login mode and shared library owner."""
from alembic import op
import sqlalchemy as sa

revision = "0006_instance_auth"
down_revision = "0005_local_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("instance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("auth_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("id = 1", name="ck_instance_singleton"))


def downgrade():
    op.drop_table("instance_settings")
