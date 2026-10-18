"""Canonical topics per run and production traits of reels."""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"


def upgrade():
    op.create_table("post_content_analyses",
        sa.Column("shortcode", sa.String(64), sa.ForeignKey("instagram_posts.shortcode", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("run_topic_maps",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("labels_digest", sa.String(64), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("run_topic_maps")
    op.drop_table("post_content_analyses")
