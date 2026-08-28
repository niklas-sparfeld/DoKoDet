"""Read-only repository data operations for DokoDetector."""

from .cardevent import CARD_EVENT_TASK, CardEventNetReviewAdapter
from .config import ConfigurationError, RepositoryConfig, discover_repository_root
from .intake import (
    BundleInspection,
    Failure,
    InspectionResult,
    ReviewWork,
    TaskState,
    discover_bundle_paths,
    inspect_repository,
)
from .review import (
    GenericReviewAdapter,
    ReviewInput,
    ReviewItem,
    ReviewResult,
    ReviewRunError,
    TaskArtifacts,
    load_review_report,
    load_review_run,
    render_review_human,
    render_review_json,
    run_review,
    validate_review_report,
    validate_review_run,
)
from .status import render_human, render_json, status_mapping
from .table_evidence import (
    COVERAGE_SCHEMA_VERSION,
    SELECTION_SCHEMA_VERSION,
    TABLE_EVIDENCE_TASK,
    VALID_SELECTION_SOURCES,
    TableEvidenceReviewAdapter,
)

__all__ = [
    "BundleInspection",
    "CARD_EVENT_TASK",
    "CardEventNetReviewAdapter",
    "COVERAGE_SCHEMA_VERSION",
    "ConfigurationError",
    "Failure",
    "InspectionResult",
    "RepositoryConfig",
    "ReviewWork",
    "TaskState",
    "discover_bundle_paths",
    "discover_repository_root",
    "inspect_repository",
    "render_human",
    "render_json",
    "GenericReviewAdapter",
    "ReviewInput",
    "ReviewItem",
    "ReviewResult",
    "ReviewRunError",
    "SELECTION_SCHEMA_VERSION",
    "TABLE_EVIDENCE_TASK",
    "TableEvidenceReviewAdapter",
    "TaskArtifacts",
    "load_review_report",
    "load_review_run",
    "render_review_human",
    "render_review_json",
    "run_review",
    "status_mapping",
    "validate_review_report",
    "validate_review_run",
    "VALID_SELECTION_SOURCES",
]
