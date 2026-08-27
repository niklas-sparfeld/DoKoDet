"""Add immutable table-observation storage."""

import sqlalchemy as sa

from alembic import op

revision = "0002_table_observations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_observations",
        sa.Column("observation_id", sa.String(length=128), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("analyzer_name", sa.String(length=128), nullable=False),
        sa.Column("analyzer_version", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("calibration", sa.String(length=32), nullable=False),
        sa.Column("observation_json", sa.Text(), nullable=False),
        sa.Column("observation_sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["evidence_packages.package_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "package_id",
            "analyzer_name",
            "analyzer_version",
            name="uq_table_observations_package_analyzer",
        ),
    )


def downgrade() -> None:
    op.drop_table("table_observations")
