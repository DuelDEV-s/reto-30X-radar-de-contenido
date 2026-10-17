"""Persist Bright Data job claims and normalized results."""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade():
    op.create_table("profile_collection_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("snapshot_id", sa.String(100), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_profile_collection_jobs_brand_id", "profile_collection_jobs", ["brand_id"])


def downgrade():
    op.drop_table("profile_collection_jobs")
