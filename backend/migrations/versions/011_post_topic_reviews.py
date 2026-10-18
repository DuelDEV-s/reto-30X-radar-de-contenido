"""LLM verdicts on whether each post talks about the run's topic."""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"


def upgrade():
    op.create_table("post_topic_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shortcode", sa.String(64), sa.ForeignKey("instagram_posts.shortcode", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_key", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("relevance", sa.String(20), nullable=False),
        sa.Column("content_kind", sa.String(30), nullable=False),
        sa.Column("subtopics", sa.JSON(), nullable=False),
        sa.Column("needs_transcript", sa.Boolean(), nullable=False),
        sa.Column("used_transcript", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("effort", sa.String(20), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("shortcode", "topic_key", name="uq_post_topic_review"))
    op.create_index("ix_post_topic_reviews_shortcode", "post_topic_reviews", ["shortcode"])


def downgrade():
    op.drop_table("post_topic_reviews")
