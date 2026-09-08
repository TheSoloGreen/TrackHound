"""Remember the non-anime category and normalize inconsistent historical flags."""

from alembic import op
import sqlalchemy as sa

revision = "0003_classification"
down_revision = "0002_ownership_constraints"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shows", sa.Column("base_media_type", sa.String(20), nullable=True))
    op.execute("UPDATE shows SET base_media_type = CASE WHEN media_type = 'movie' THEN 'movie' ELSE 'tv' END")
    # The old unmark action changed only is_anime and left its prior source/type.
    op.execute("UPDATE shows SET anime_source = 'manual' WHERE NOT is_anime AND (media_type = 'anime' OR anime_source IS NOT NULL)")
    op.execute("UPDATE shows SET media_type = CASE WHEN is_anime THEN 'anime' ELSE base_media_type END")
    op.execute("UPDATE shows SET anime_source = NULL WHERE NOT is_anime AND anime_source <> 'manual'")
    with op.batch_alter_table("shows") as batch:
        batch.alter_column("base_media_type", existing_type=sa.String(20), nullable=False)


def downgrade():
    raise RuntimeError("Restore the matching database backup to roll back classification changes.")
