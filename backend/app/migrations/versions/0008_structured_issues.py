"""Preserve legacy findings as structured, filterable issue records."""

from alembic import op
import sqlalchemy as sa

from app.core.issue_catalog import legacy_issues

revision = "0008_structured_issues"
down_revision = "0007_artwork_security"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_files", sa.Column("issue_evaluation_version", sa.Integer(), nullable=True))
    issues = op.create_table("media_issues",
        sa.Column("media_file_id", sa.Integer(), sa.ForeignKey("media_files.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False))
    op.create_index("ix_media_issues_code_file", "media_issues", ["code", "media_file_id"])
    connection = op.get_bind()
    cursor = 0
    while True:
        rows = connection.execute(sa.text("SELECT id, issue_details, has_issues FROM media_files WHERE id > :id ORDER BY id LIMIT 500"), {"id": cursor}).all()
        if not rows:
            break
        records = [{"media_file_id": row.id, **issue.to_dict()}
                   for row in rows for issue in legacy_issues(row.issue_details, row.has_issues)]
        if records:
            connection.execute(issues.insert(), records)
        ids = [row.id for row in rows]
        files = sa.table("media_files", sa.column("id"), sa.column("issue_evaluation_version"))
        connection.execute(files.update().where(files.c.id.in_(ids)).values(issue_evaluation_version=0))
        cursor = rows[-1].id


def downgrade():
    op.drop_table("media_issues")
    op.drop_column("media_files", "issue_evaluation_version")
