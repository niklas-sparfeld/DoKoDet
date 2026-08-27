"""Add immutable training-recording intake metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0003_training_recordings"
down_revision = "0002_table_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_recordings",
        sa.Column("recording_id", sa.String(length=256), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("video_id", sa.String(length=256), nullable=False),
        sa.Column("started_at_utc", sa.String(length=64), nullable=False),
        sa.Column("ended_at_utc", sa.String(length=64), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("video_byte_length", sa.Integer(), nullable=False),
        sa.Column("video_sha256", sa.String(length=64), nullable=False),
        sa.Column("video_relative_path", sa.String(length=512), nullable=False),
        sa.Column("predictions_byte_length", sa.Integer(), nullable=False),
        sa.Column("predictions_sha256", sa.String(length=64), nullable=False),
        sa.Column("predictions_relative_path", sa.String(length=512), nullable=False),
        sa.Column("recording_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("derived_state", sa.String(length=32), nullable=False),
        sa.Column("dataset_record_byte_length", sa.Integer(), nullable=False),
        sa.Column("dataset_record_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_record_relative_path", sa.String(length=512), nullable=False),
        sa.Column("candidate_queue_byte_length", sa.Integer(), nullable=True),
        sa.Column("candidate_queue_sha256", sa.String(length=64), nullable=True),
        sa.Column("candidate_queue_relative_path", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("recording_id"),
    )


def downgrade() -> None:
    op.drop_table("training_recordings")
