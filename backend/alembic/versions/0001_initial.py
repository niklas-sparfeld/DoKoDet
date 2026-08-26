"""Create the evidence package and frame tables."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_packages",
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("event_time_ms", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("package_id"),
        sa.UniqueConstraint(
            "session_id",
            "event_sequence",
            name="uq_evidence_packages_session_event",
        ),
    )
    op.create_table(
        "evidence_frames",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("part_name", sa.String(length=64), nullable=False),
        sa.Column("target_offset_ms", sa.Integer(), nullable=False),
        sa.Column("actual_offset_ms", sa.Integer(), nullable=False),
        sa.Column("session_elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("captured_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["evidence_packages.package_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            "part_name",
            name="uq_evidence_frames_package_part",
        ),
    )


def downgrade() -> None:
    op.drop_table("evidence_frames")
    op.drop_table("evidence_packages")
