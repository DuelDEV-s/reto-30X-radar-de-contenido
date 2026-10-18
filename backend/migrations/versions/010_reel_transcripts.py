"""Transcripts of the first seconds of each reel's audio."""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
COLUMNS = ("transcript", "transcript_status", "transcript_seconds", "transcript_model", "transcribed_at")


def upgrade():
    with op.batch_alter_table("instagram_posts") as batch:
        batch.add_column(sa.Column("transcript", sa.Text(), nullable=True))
        batch.add_column(sa.Column("transcript_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("transcript_seconds", sa.Float(), nullable=True))
        batch.add_column(sa.Column("transcript_model", sa.String(100), nullable=True))
        batch.add_column(sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("instagram_posts") as batch:
        for column in COLUMNS:
            batch.drop_column(column)
