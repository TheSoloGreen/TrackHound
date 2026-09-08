"""Adopt the initial, media-type, and pre-constraint ownership schemas."""

from alembic import op
import sqlalchemy as sa

from app.core.encryption import encrypt_value, is_encrypted
from app.migrations.schema_v1 import metadata

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Frozen schema: future model changes must get a new revision.
    metadata.create_all(bind)

    def columns(table):
        return {column["name"] for column in sa.inspect(bind).get_columns(table)}

    for table in ("shows", "media_files", "scan_locations"):
        if "user_id" not in columns(table):
            op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))

    if "media_type" not in columns("shows"):
        op.add_column("shows", sa.Column("media_type", sa.String(20), nullable=True))
    bind.execute(sa.text("UPDATE shows SET media_type = CASE WHEN is_anime THEN 'anime' ELSE 'tv' END WHERE media_type IS NULL"))

    if "media_type" not in columns("scan_locations"):
        op.add_column("scan_locations", sa.Column("media_type", sa.String(20), nullable=True))
    expression = "CASE WHEN is_anime_folder THEN 'anime' ELSE 'tv' END" if "is_anime_folder" in columns("scan_locations") else "'tv'"
    bind.execute(sa.text(f"UPDATE scan_locations SET media_type = {expression} WHERE media_type IS NULL"))

    if "show_id" not in columns("media_files"):
        op.add_column("media_files", sa.Column("show_id", sa.Integer(), nullable=True))
    bind.execute(sa.text("""
        UPDATE media_files SET show_id = (SELECT show_id FROM seasons WHERE seasons.id = media_files.season_id)
        WHERE show_id IS NULL AND season_id IS NOT NULL
    """))

    needs_owner = any(bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"))
                      for table in ("shows", "media_files", "scan_locations"))
    if needs_owner:
        owner_id = bind.scalar(sa.text("SELECT MIN(id) FROM users"))
        if owner_id is None:
            users = metadata.tables["users"]
            owner_id = bind.scalar(users.insert().values(
                plex_user_id="bootstrap-owner", plex_username="bootstrap-owner",
                plex_token=encrypt_value("bootstrap-owner-token"),
                created_at=sa.func.current_timestamp(), last_login=sa.func.current_timestamp(),
            ).returning(users.c.id))
        bind.execute(sa.text("UPDATE shows SET user_id = :owner WHERE user_id IS NULL"), {"owner": owner_id})
        # Prefer the file's show owner if an earlier partial migration assigned it.
        bind.execute(sa.text("""
            UPDATE media_files SET user_id = COALESCE(
                (SELECT user_id FROM shows WHERE shows.id = media_files.show_id), :owner)
            WHERE user_id IS NULL
        """), {"owner": owner_id})
        bind.execute(sa.text("UPDATE scan_locations SET user_id = :owner WHERE user_id IS NULL"), {"owner": owner_id})

    for user_id, token in bind.execute(sa.text("SELECT id, plex_token FROM users")):
        if token and not is_encrypted(token):
            bind.execute(sa.text("UPDATE users SET plex_token = :token WHERE id = :id"),
                         {"id": user_id, "token": encrypt_value(token)})


def downgrade():
    raise RuntimeError("Restore the pre-upgrade database backup to roll back this adoption migration.")
