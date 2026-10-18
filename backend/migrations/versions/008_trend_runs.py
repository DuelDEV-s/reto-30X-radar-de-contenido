"""Runs of the LinkedIn + YouTube trend engine and their reports."""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade():
    op.create_table("trend_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("cost", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_trend_runs_brand_id", "trend_runs", ["brand_id"])


def downgrade():
    op.drop_table("trend_runs")
