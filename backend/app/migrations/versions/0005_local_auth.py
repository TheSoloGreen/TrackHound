"""Add local credentials without replacing existing Plex accounts or ownership."""
from alembic import op
import sqlalchemy as sa

revision = "0005_local_auth"
down_revision = "0004_language_review"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.alter_column("plex_user_id", existing_type=sa.String(255), nullable=True)
        batch.alter_column("plex_token", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("username", sa.String(64), nullable=True))
        batch.add_column(sa.Column("password_hash", sa.Text(), nullable=True))
        batch.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_users_username", ["username"])


def downgrade():
    raise RuntimeError("Local accounts cannot safely be removed by downgrade. Restore the pre-upgrade backup.")
