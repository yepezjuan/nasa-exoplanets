"""Create planets and ingest_runs tables, with query and cone search indexes.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS q3c")

    op.create_table(
        "planets",
        sa.Column("pl_name", sa.Text, primary_key=True),
        sa.Column("hostname", sa.Text, nullable=False),
        sa.Column("discovery_method", sa.Text, nullable=False),
        sa.Column("disc_year", sa.Integer, nullable=False),
        sa.Column("disc_facility", sa.Text),
        sa.Column("orbital_period_days", sa.Double),
        sa.Column("radius_earth", sa.Double),
        sa.Column("mass_earth", sa.Double),
        sa.Column("eq_temp_k", sa.Double),
        sa.Column("distance_pc", sa.Double),
        sa.Column("stellar_teff_k", sa.Double),
        sa.Column("ra_deg", sa.Double, nullable=False),
        sa.Column("dec_deg", sa.Double, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # Filters match these two case-insensitively, so the indexes are on lower().
    op.execute("CREATE INDEX ix_planets_hostname ON planets (lower(hostname))")
    op.execute("CREATE INDEX ix_planets_discovery_method ON planets (lower(discovery_method))")
    for column in ("disc_year", "orbital_period_days", "radius_earth", "mass_earth", "eq_temp_k"):
        op.create_index(f"ix_planets_{column}", "planets", [column])
    op.create_index("ix_planets_distance_pc", "planets", ["distance_pc"])
    op.execute("CREATE INDEX ix_planets_q3c ON planets (q3c_ang2ipix(ra_deg, dec_deg))")

    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deleted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("detail", sa.Text),
    )
    op.create_index("ix_ingest_runs_status_finished", "ingest_runs", ["status", "finished_at"])


def downgrade() -> None:
    op.drop_table("ingest_runs")
    op.drop_table("planets")
    op.execute("DROP EXTENSION IF EXISTS q3c")
