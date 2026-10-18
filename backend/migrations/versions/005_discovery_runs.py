"""Persist every topic discovery run: queries, Google results and candidates."""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def upgrade():
    op.create_table("discovery_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("topic", sa.String(100), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("hl", sa.String(10), nullable=False),
        sa.Column("countries", sa.JSON(), nullable=False),
        sa.Column("max_queries", sa.Integer(), nullable=False),
        sa.Column("profiles_only", sa.Boolean(), nullable=False),
        sa.Column("resolve_posts", sa.Boolean(), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("query_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("discarded_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_discovery_runs_brand_id", "discovery_runs", ["brand_id"])
    op.create_table("discovery_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("planned_query", sa.String(500), nullable=False),
        sa.Column("angle", sa.String(20), nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("gl", sa.String(10), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("results_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(500), nullable=True))
    op.create_index("ix_discovery_queries_run_id", "discovery_queries", ["run_id"])
    op.create_table("discovery_hits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_id", sa.String(36), sa.ForeignKey("discovery_queries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("link", sa.String(1000), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("username", sa.String(30), nullable=True),
        sa.Column("author_source", sa.String(20), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True))
    op.create_index("ix_discovery_hits_run_id", "discovery_hits", ["run_id"])
    op.create_index("ix_discovery_hits_query_id", "discovery_hits", ["query_id"])
    op.create_index("ix_discovery_hits_username", "discovery_hits", ["username"])
    op.create_table("discovery_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(30), nullable=False),
        sa.Column("query_hits", sa.Integer(), nullable=False),
        sa.Column("best_rank", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "username", name="uq_run_candidate"))
    op.create_index("ix_discovery_candidates_run_id", "discovery_candidates", ["run_id"])
    op.create_index("ix_discovery_candidates_username", "discovery_candidates", ["username"])


def downgrade():
    op.drop_table("discovery_candidates")
    op.drop_table("discovery_hits")
    op.drop_table("discovery_queries")
    op.drop_table("discovery_runs")
