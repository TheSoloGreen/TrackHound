"""Track successful metadata analysis separately from rule evaluation."""

from alembic import op
import sqlalchemy as sa

revision = "0010_cached_evaluation"
down_revision = "0009_durable_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_files", sa.Column("analysis_version", sa.Integer(), nullable=True))
    op.add_column("media_files", sa.Column("issue_policy_revision", sa.String(64), nullable=True))
    # Existing tracks are usable cached evidence. Historical empty analyses
    # cannot reliably distinguish no-audio from a failed/skipped old probe.
    op.execute(sa.text("UPDATE media_files SET analysis_version = 1 WHERE EXISTS "
                       "(SELECT 1 FROM audio_tracks WHERE audio_tracks.media_file_id = media_files.id)"))


def downgrade():
    op.drop_column("media_files", "issue_policy_revision")
    op.drop_column("media_files", "analysis_version")
