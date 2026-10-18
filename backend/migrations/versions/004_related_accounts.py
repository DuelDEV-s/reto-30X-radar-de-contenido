"""Instagram accounts related to a brand through its reels."""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade():
    op.create_table("related_account_runs",
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("brand_account", sa.String(30), nullable=False),
        sa.Column("reels_snapshot_id", sa.String(100), nullable=True),
        sa.Column("profiles_snapshot_id", sa.String(100), nullable=True),
        sa.Column("relations", sa.JSON(), nullable=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("related_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("full_name", sa.String(300), nullable=True),
        sa.Column("biography", sa.Text(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True),
        sa.Column("following", sa.Integer(), nullable=True),
        sa.Column("posts_count", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("external_urls", sa.JSON(), nullable=False),
        sa.Column("relations", sa.JSON(), nullable=False),
        sa.Column("reel_urls", sa.JSON(), nullable=False),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("avatar_type", sa.String(50), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("brand_id", "username", name="uq_brand_related_account"))
    op.create_index("ix_related_accounts_brand_id", "related_accounts", ["brand_id"])


def downgrade():
    op.drop_table("related_accounts")
    op.drop_table("related_account_runs")
