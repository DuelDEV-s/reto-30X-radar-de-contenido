"""Shared Instagram profile cache; related accounts keep only the relation; run profile enrichment."""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"

PROFILE_COLUMNS = ["full_name", "biography", "followers", "following", "posts_count", "is_verified", "is_private",
                   "category", "external_urls", "avatar", "avatar_type", "raw"]


def profile_columns():
    return [
        sa.Column("full_name", sa.String(300), nullable=True),
        sa.Column("biography", sa.Text(), nullable=True),
        sa.Column("followers", sa.Integer(), nullable=True),
        sa.Column("following", sa.Integer(), nullable=True),
        sa.Column("posts_count", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("external_urls", sa.JSON(), nullable=False),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("avatar_type", sa.String(50), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
    ]


def typed(*extra):
    """Columnas con tipo para copiar filas: el driver necesita saber qué es JSON y qué son bytes."""
    return [*extra, *[sa.column(c.name, c.type) for c in profile_columns()]]


def upgrade():
    op.create_table("instagram_accounts",
        sa.Column("username", sa.String(30), primary_key=True),
        *profile_columns(),
        sa.Column("fetch_status", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))

    # Los perfiles ya pagados pasan a la tabla compartida; si una cuenta está en varias marcas, gana la más reciente.
    related = sa.table("related_accounts", *typed(sa.column("username"), sa.column("collected_at", sa.DateTime(timezone=True))))
    accounts = sa.table("instagram_accounts", *typed(sa.column("username"), sa.column("fetch_status"), sa.column("fetched_at", sa.DateTime(timezone=True))))
    bind = op.get_bind()
    latest = {}
    for row in bind.execute(sa.select(related).where(related.c.raw.is_not(None)).order_by(related.c.collected_at)).mappings():
        latest[row["username"]] = row
    for name, row in latest.items():
        values = {c: row[c] for c in PROFILE_COLUMNS}
        values["external_urls"] = values["external_urls"] or []
        bind.execute(accounts.insert().values(username=name, fetch_status="private" if row["is_private"] else "ok", fetched_at=row["collected_at"], **values))

    with op.batch_alter_table("related_accounts") as batch:
        for column in PROFILE_COLUMNS:
            batch.drop_column(column)

    with op.batch_alter_table("discovery_runs") as batch:
        batch.add_column(sa.Column("profiles_state", sa.String(30), nullable=False, server_default="not_started"))
        batch.add_column(sa.Column("profiles_generation", sa.String(36), nullable=True))
        batch.add_column(sa.Column("profiles_snapshot_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("profiles_requested", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("profiles_message", sa.String(500), nullable=False, server_default=""))
        batch.add_column(sa.Column("profiles_updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("discovery_runs") as batch:
        for column in ("profiles_state", "profiles_requested", "profiles_message"):
            batch.alter_column(column, server_default=None)


def downgrade():
    with op.batch_alter_table("discovery_runs") as batch:
        for column in ("profiles_state", "profiles_generation", "profiles_snapshot_id", "profiles_requested", "profiles_message", "profiles_updated_at"):
            batch.drop_column(column)
    with op.batch_alter_table("related_accounts") as batch:
        for column in profile_columns():
            if column.name == "external_urls":
                column = sa.Column("external_urls", sa.JSON(), nullable=False, server_default="[]")
            batch.add_column(column)
    bind = op.get_bind()
    accounts = sa.table("instagram_accounts", *typed(sa.column("username")))
    related = sa.table("related_accounts", *typed(sa.column("username")))
    for row in bind.execute(sa.select(accounts)).mappings():
        bind.execute(related.update().where(related.c.username == row["username"]).values(**{c: row[c] for c in PROFILE_COLUMNS}))
    op.drop_table("instagram_accounts")
