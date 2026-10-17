"""Initial brand and versioned batch storage."""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table("brands", sa.Column("id", sa.String(36), primary_key=True), sa.Column("brief", sa.JSON(), nullable=False), sa.Column("identity", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("trend_batches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("data", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("brand_id", "fingerprint", name="uq_brand_batch"))
    op.create_index("ix_trend_batches_brand_id", "trend_batches", ["brand_id"])


def downgrade():
    op.drop_table("trend_batches")
    op.drop_table("brands")
