"""Enforce ownership, per-user paths, and foreign keys after orphan cleanup."""

from alembic import op
import sqlalchemy as sa

revision = "0002_ownership_constraints"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None

NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
          "uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    bind = op.get_bind()
    # Remove rows that should have cascaded with their deleted parent.
    for table in ("user_preferences", "media_files", "shows", "scan_locations"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE user_id NOT IN (SELECT id FROM users)"))
    bind.execute(sa.text("DELETE FROM seasons WHERE show_id NOT IN (SELECT id FROM shows)"))
    bind.execute(sa.text("DELETE FROM audio_tracks WHERE media_file_id NOT IN (SELECT id FROM media_files)"))
    bind.execute(sa.text("UPDATE media_files SET season_id = NULL WHERE season_id NOT IN (SELECT id FROM seasons)"))
    bind.execute(sa.text("UPDATE media_files SET show_id = NULL WHERE show_id NOT IN (SELECT id FROM shows)"))

    for table in ("shows", "media_files", "scan_locations"):
        inspector = sa.inspect(bind)
        foreign_keys = inspector.get_foreign_keys(table)
        constraints = inspector.get_unique_constraints(table)
        columns = {col["name"]: col for col in inspector.get_columns(table)}
        with op.batch_alter_table(table, naming_convention=NAMING) as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            if "media_type" in columns:
                batch.alter_column("media_type", existing_type=sa.String(20), nullable=False)
            expected_fks = [("user_id", "users", "CASCADE")]
            if table == "media_files":
                expected_fks.append(("show_id", "shows", "SET NULL"))
            for column, parent, ondelete in expected_fks:
                matches = [fk for fk in foreign_keys if fk["constrained_columns"] == [column]]
                if matches and matches[0]["referred_table"] == parent and matches[0].get("options", {}).get("ondelete") == ondelete:
                    continue
                for fk in matches:
                    name = fk["name"] or f"fk_{table}_{column}_{fk['referred_table']}"
                    batch.drop_constraint(name, type_="foreignkey")
                batch.create_foreign_key(f"fk_{table}_{column}_{parent}", parent, [column], ["id"], ondelete=ondelete)

            old_path = "file_path" if table == "media_files" else "path" if table == "scan_locations" else None
            for constraint in constraints:
                if old_path and constraint["column_names"] == [old_path]:
                    batch.drop_constraint(constraint["name"] or f"uq_{table}_{old_path}", type_="unique")
            if table == "media_files":
                batch.create_unique_constraint("uq_media_files_user_path", ["user_id", "file_path"])
            if table == "scan_locations" and "is_anime_folder" in columns:
                batch.drop_column("is_anime_folder")

        index_names = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if f"ix_{table}_user_id" not in index_names:
            op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        if table == "scan_locations" and "uq_scan_locations_user_path" not in index_names:
            op.create_index("uq_scan_locations_user_path", table, ["user_id", "path"], unique=True)


def downgrade():
    raise RuntimeError("Per-user paths cannot safely become globally unique. Restore the pre-upgrade backup.")
