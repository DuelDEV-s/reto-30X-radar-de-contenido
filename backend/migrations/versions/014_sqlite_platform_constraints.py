"""Complete the platform-scoped review constraints skipped by 013 on SQLite.

PostgreSQL already has these constraints. Rebuild only SQLite tables, preserving rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}


def upgrade():
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("account_reviews", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("uq_brand_account_review", type_="unique")
        batch.create_unique_constraint("uq_brand_account_review", ["brand_id", "platform", "username"])
    with op.batch_alter_table("post_topic_reviews", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("fk_post_topic_reviews_shortcode_instagram_posts", type_="foreignkey")
        batch.drop_constraint("uq_post_topic_review", type_="unique")
        batch.create_unique_constraint("uq_post_topic_review", ["platform", "shortcode", "topic_key"])
    with op.batch_alter_table("post_content_analyses", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("fk_post_content_analyses_shortcode_instagram_posts", type_="foreignkey")
        batch.drop_constraint("pk_post_content_analyses", type_="primary")
        batch.create_primary_key("pk_post_content_analyses", ["platform", "shortcode"])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    # Old SQLite constraints cannot represent TikTok rows. Never silently delete them.
    for table in ("account_reviews", "post_topic_reviews", "post_content_analyses"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE platform <> 'instagram'")).scalar():
            raise RuntimeError("El downgrade requiere una base sin revisiones de TikTok. Conserva una copia antes de migrar a 013.")
    with op.batch_alter_table("account_reviews", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("uq_brand_account_review", type_="unique")
        batch.create_unique_constraint("uq_brand_account_review", ["brand_id", "username"])
    with op.batch_alter_table("post_topic_reviews", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("uq_post_topic_review", type_="unique")
        batch.create_unique_constraint("uq_post_topic_review", ["shortcode", "topic_key"])
        batch.create_foreign_key("fk_post_topic_reviews_shortcode_instagram_posts", "instagram_posts", ["shortcode"], ["shortcode"], ondelete="CASCADE")
    with op.batch_alter_table("post_content_analyses", naming_convention=NAMING, recreate="always") as batch:
        batch.drop_constraint("pk_post_content_analyses", type_="primary")
        batch.create_primary_key("pk_post_content_analyses", ["shortcode"])
        batch.create_foreign_key("fk_post_content_analyses_shortcode_instagram_posts", "instagram_posts", ["shortcode"], ["shortcode"], ondelete="CASCADE")
