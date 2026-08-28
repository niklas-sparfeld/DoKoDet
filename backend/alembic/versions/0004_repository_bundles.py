"""Add shared repository bundle index metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0004_repository_bundles"
down_revision = "0003_training_recordings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_bundles",
        sa.Column("recording_id", sa.String(length=256), nullable=False),
        sa.Column("source_asset_id", sa.String(length=256), nullable=False),
        sa.Column("video_id", sa.String(length=256), nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_record_sha256", sa.String(length=64), nullable=False),
        sa.Column("task_enrollment_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposal_run_ids_json", sa.Text(), nullable=False),
        sa.Column("bundle_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("recording_id"),
    )


def downgrade() -> None:
    op.drop_table("repository_bundles")
