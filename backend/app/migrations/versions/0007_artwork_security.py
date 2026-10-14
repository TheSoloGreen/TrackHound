"""Remove embedded Plex credentials from historical artwork URLs."""
from alembic import op
import sqlalchemy as sa

from app.core.artwork import artwork_reference, public_avatar_url

revision = "0007_artwork_security"
down_revision = "0006_instance_auth"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for table, column, sanitize in (("shows", "thumb_url", artwork_reference),
                                    ("users", "plex_thumb_url", public_avatar_url)):
        rows = connection.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).all()
        for row_id, value in rows:
            cleaned = sanitize(value)
            if cleaned != value:
                connection.execute(sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                                   {"id": row_id, "value": cleaned})


def downgrade():
    # Credential-bearing URLs must never be restored. A scan can refresh artwork.
    pass
