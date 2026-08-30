"""Add durable round-analysis status and result metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0005_round_analyses"
down_revision = "0004_repository_bundles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "round_analyses",
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("recording_id", sa.String(length=256), nullable=False),
        sa.Column("round_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("total_evidence_packages", sa.Integer(), nullable=False),
        sa.Column("completed_evidence_packages", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=32), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("input_artifact_id", sa.String(length=512), nullable=True),
        sa.Column("input_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_artifact_id", sa.String(length=512), nullable=True),
        sa.Column("result_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("analysis_id"),
    )


def downgrade() -> None:
    op.drop_table("round_analyses")
