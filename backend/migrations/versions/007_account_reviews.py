"""LLM verdicts on how related each Instagram account is to the brand."""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"


def upgrade():
    op.create_table("account_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("relevance", sa.String(20), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("effort", sa.String(20), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("profile_digest", sa.String(64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("brand_id", "username", name="uq_brand_account_review"))
    op.create_index("ix_account_reviews_brand_id", "account_reviews", ["brand_id"])


def downgrade():
    op.drop_table("account_reviews")
