"""Add immutable vision result storage."""

import sqlalchemy as sa

from alembic import op

revision = "0002_vision_results"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vision_results",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("detector_name", sa.String(length=128), nullable=False),
        sa.Column("detector_version", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selected_card", sa.String(length=32), nullable=True),
        sa.Column("calibration", sa.String(length=32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["evidence_packages.package_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint(
            "package_id",
            "detector_name",
            "detector_version",
            name="uq_vision_results_package_detector",
        ),
    )


def downgrade() -> None:
    op.drop_table("vision_results")
