"""Keep user language-review notes separate from measured track metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0004_language_review"
down_revision = "0003_classification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_files", sa.Column("language_review_note", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("media_files", "language_review_note")
