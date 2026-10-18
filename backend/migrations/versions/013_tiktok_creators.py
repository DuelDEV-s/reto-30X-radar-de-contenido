"""TikTok creators: profiles, videos and observations; platform on the shared review tables;
asynchronous keyword search on discovery runs."""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    op.create_table("tiktok_accounts",
        sa.Column("username", sa.String(30), primary_key=True),
        sa.Column("nickname", sa.String(300), nullable=True),
        sa.Column("biography", sa.Text(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True),
        sa.Column("following", sa.Integer(), nullable=True),
        sa.Column("likes_total", sa.BigInteger(), nullable=True),
        sa.Column("videos_count", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.Column("region", sa.String(10), nullable=True),
        sa.Column("external_urls", sa.JSON(), nullable=False),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("avatar_type", sa.String(50), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("fetch_status", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posts_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("tiktok_posts",
        sa.Column("video_id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("author", sa.String(30), nullable=True),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("saves", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True),
        sa.Column("audio", sa.String(300), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(20), nullable=True),
        sa.Column("transcript_seconds", sa.Float(), nullable=True),
        sa.Column("transcript_model", sa.String(100), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tiktok_posts_username", "tiktok_posts", ["username"])
    op.create_table("tiktok_post_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.String(64), sa.ForeignKey("tiktok_posts.video_id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("saves", sa.Integer(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True))
    op.create_index("ix_tiktok_post_observations_video_id", "tiktok_post_observations", ["video_id"])

    op.add_column("discovery_runs", sa.Column("search_state", sa.String(30), nullable=False, server_default="not_started"))
    op.add_column("discovery_runs", sa.Column("search_generation", sa.String(36), nullable=True))
    op.add_column("discovery_runs", sa.Column("search_snapshot_id", sa.String(100), nullable=True))
    op.add_column("discovery_runs", sa.Column("search_message", sa.String(500), nullable=False, server_default=""))
    op.add_column("discovery_runs", sa.Column("search_updated_at", sa.DateTime(timezone=True), nullable=True))

    # Las filas existentes son de Instagram.
    for table in ("account_reviews", "post_topic_reviews", "post_content_analyses"):
        op.add_column(table, sa.Column("platform", sa.String(20), nullable=False, server_default="instagram"))
    if not postgres:
        # SQLite (desarrollo local) no altera restricciones sin reconstruir la tabla y no aplica FKs por defecto.
        return
    op.drop_constraint("uq_brand_account_review", "account_reviews", type_="unique")
    op.create_unique_constraint("uq_brand_account_review", "account_reviews", ["brand_id", "platform", "username"])
    # Revisiones y análisis valen para posts de Instagram y videos de TikTok: ya no apuntan a instagram_posts.
    op.drop_constraint("post_topic_reviews_shortcode_fkey", "post_topic_reviews", type_="foreignkey")
    op.drop_constraint("uq_post_topic_review", "post_topic_reviews", type_="unique")
    op.create_unique_constraint("uq_post_topic_review", "post_topic_reviews", ["platform", "shortcode", "topic_key"])
    op.drop_constraint("post_content_analyses_shortcode_fkey", "post_content_analyses", type_="foreignkey")
    op.drop_constraint("post_content_analyses_pkey", "post_content_analyses", type_="primary")
    op.create_primary_key("post_content_analyses_pkey", "post_content_analyses", ["platform", "shortcode"])


def downgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("DELETE FROM post_content_analyses WHERE platform <> 'instagram'")
        op.execute("DELETE FROM post_topic_reviews WHERE platform <> 'instagram'")
        op.execute("DELETE FROM account_reviews WHERE platform <> 'instagram'")
        op.drop_constraint("post_content_analyses_pkey", "post_content_analyses", type_="primary")
        op.create_primary_key("post_content_analyses_pkey", "post_content_analyses", ["shortcode"])
        op.create_foreign_key("post_content_analyses_shortcode_fkey", "post_content_analyses", "instagram_posts", ["shortcode"], ["shortcode"], ondelete="CASCADE")
        op.drop_constraint("uq_post_topic_review", "post_topic_reviews", type_="unique")
        op.create_unique_constraint("uq_post_topic_review", "post_topic_reviews", ["shortcode", "topic_key"])
        op.create_foreign_key("post_topic_reviews_shortcode_fkey", "post_topic_reviews", "instagram_posts", ["shortcode"], ["shortcode"], ondelete="CASCADE")
        op.drop_constraint("uq_brand_account_review", "account_reviews", type_="unique")
        op.create_unique_constraint("uq_brand_account_review", "account_reviews", ["brand_id", "username"])
    for table in ("post_content_analyses", "post_topic_reviews", "account_reviews"):
        op.drop_column(table, "platform")
    for column in ("search_updated_at", "search_message", "search_snapshot_id", "search_generation", "search_state"):
        op.drop_column("discovery_runs", column)
    op.drop_table("tiktok_post_observations")
    op.drop_table("tiktok_posts")
    op.drop_table("tiktok_accounts")
