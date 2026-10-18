"""Recent Instagram posts of discovered creators, their metric history and the run's posts stage."""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade():
    op.create_table("instagram_posts",
        sa.Column("shortcode", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("author", sa.String(30), nullable=True),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True),
        sa.Column("is_paid_partnership", sa.Boolean(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=True),
        sa.Column("coauthors", sa.JSON(), nullable=False),
        sa.Column("tagged_users", sa.JSON(), nullable=False),
        sa.Column("audio", sa.String(300), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_instagram_posts_username", "instagram_posts", ["username"])
    op.create_table("instagram_post_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shortcode", sa.String(64), sa.ForeignKey("instagram_posts.shortcode", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True))
    op.create_index("ix_instagram_post_observations_shortcode", "instagram_post_observations", ["shortcode"])

    with op.batch_alter_table("instagram_accounts") as batch:
        batch.add_column(sa.Column("posts_fetched_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("discovery_runs") as batch:
        batch.add_column(sa.Column("posts_state", sa.String(30), nullable=False, server_default="not_started"))
        batch.add_column(sa.Column("posts_generation", sa.String(36), nullable=True))
        batch.add_column(sa.Column("posts_snapshot_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("posts_requested", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("posts_message", sa.String(500), nullable=False, server_default=""))
        batch.add_column(sa.Column("posts_updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("discovery_runs") as batch:
        for column in ("posts_state", "posts_requested", "posts_message"):
            batch.alter_column(column, server_default=None)


def downgrade():
    with op.batch_alter_table("discovery_runs") as batch:
        for column in ("posts_state", "posts_generation", "posts_snapshot_id", "posts_requested", "posts_message", "posts_updated_at"):
            batch.drop_column(column)
    with op.batch_alter_table("instagram_accounts") as batch:
        batch.drop_column("posts_fetched_at")
    op.drop_table("instagram_post_observations")
    op.drop_table("instagram_posts")
