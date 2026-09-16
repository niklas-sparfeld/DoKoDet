"""The ``doko`` repository operations command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .cardevent_campaign import (
    FixtureCommandRunner,
    preflight_card_event_campaign,
    promote_card_event_campaign,
    run_card_event_campaign,
)
from .cardevent_dataset import (
    CardEventNetDatasetFreezeError,
    freeze_cardeventnet_dataset,
    render_cardeventnet_freeze_human,
)
from .cardevent_interval_dataset import (
    CardEventNetIntervalDatasetError,
    build_cardeventnet_interval_dataset_report,
    build_cardeventnet_interval_sampling_report,
    freeze_cardeventnet_interval_dataset,
    write_cardeventnet_interval_report,
)
from .cardevent_interval_pilot import (
    CardEventNetIntervalPilotError,
    render_cardeventnet_interval_pilot_human,
    run_cardeventnet_interval_pilot,
)
from .cardevent_interval_readiness import (
    CardEventNetIntervalReadinessError,
    build_cardeventnet_interval_readiness,
    render_cardeventnet_interval_readiness_human,
    write_cardeventnet_interval_readiness_report,
    write_cardeventnet_zero_interval_attestation,
    write_legacy_device_exclusion_receipt,
)
from .cardevent_inventory import (
    CardEventNetInventoryError,
    audit_cardeventnet,
    render_cardevent_inventory_human,
    render_cardevent_inventory_json,
)
from .cardevent_m9 import review_cardeventnet_m9
from .cardevent_materialization import (
    CardEventNetMaterializationError,
    materialize_cardeventnet_dataset,
)
from .cardevent_migration import (
    CardEventNetMigrationError,
    migrate_cardeventnet,
    render_cardevent_migration_human,
)
from .cardevent_readiness import (
    CardEventNetReadinessError,
    build_cardeventnet_readiness,
    render_cardeventnet_readiness_human,
    write_cardeventnet_readiness_receipt,
)
from .config import ConfigurationError, RepositoryConfig
from .evidence_adoption import EvidencePackageAdoptionError, adopt_runtime_evidence_package
from .holdout import SystemHoldoutError, seal_system_holdout_group
from .impact import (
    RETIREMENT_STATES,
    SourceImpactError,
    analyze_repository_impacts,
    analyze_source_impact,
    retire_source,
)
from .intake import inspect_repository
from .model_improvement import (
    ModelImprovementError,
    load_campaign,
    load_campaign_comparison,
    load_model_registry,
    model_status,
    render_comparison_human,
    render_comparison_json,
    render_model_status_human,
    render_model_status_json,
    validate_campaign_against_registry,
)
from .pending_video import PendingVideoCompletionError, complete_pending_video
from .resilience_baseline import (
    DEFAULT_CLASSIFIER_MODEL,
    DEFAULT_CLASSIFIER_PROVIDER,
    ResilienceBaselineError,
    build_resilience_baseline_manifest,
    render_resilience_baseline_human,
    write_resilience_baseline_manifest,
)
from .resilience_comparison import (
    ResilienceComparisonBlocked,
    ResilienceComparisonError,
    render_resilience_comparison_human,
    run_resilience_comparison,
    write_resilience_comparison,
)
from .resilience_execution import (
    build_resilience_work_plan,
    execute_resilience_work,
    materialize_resilience_work,
)
from .rfdetr_segmentation_campaign import (
    RfdetrSegmentationCampaignError,
    build_rfdetr_segmentation_manifest,
    render_rfdetr_segmentation_human,
    write_rfdetr_segmentation_manifest,
)
from .rfdetr_segmentation_materialization import (
    RfdetrSegmentationMaterializationError,
    materialize_rfdetr_segmentation_dataset,
)
from .round_reconstruction_contract import RoundReconstructionContractError
from .round_reconstruction_execution import run_round_reconstruction
from .status import render_human, render_json
from .system_holdout import (
    FAILURE_BOUNDARIES,
    SystemHoldoutEvaluationError,
    SystemHoldoutFixtureRunner,
    evaluate_system_holdout,
)
from .table_evidence_campaign import (
    TableEvidenceFixtureCommandRunner,
    promote_table_evidence_campaign,
    run_table_evidence_campaign,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doko", description="DokoDetector data operations.")
    _add_path_options(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    data = commands.add_parser("data", help="Inspect and process repository data.")
    data_commands = data.add_subparsers(dest="data_command", metavar="COMMAND")
    for name, help_text in (
        ("status", "Show read-only intake and derived-data status."),
        ("validate", "Validate read-only intake and derived-data state."),
    ):
        command = data_commands.add_parser(name, help=help_text, description=help_text)
        _add_path_options(command, suppress_defaults=True)
        command.add_argument(
            "--format",
            choices=("human", "json"),
            default="human",
            help="Output format (default: human).",
        )
        command.add_argument(
            "--json",
            action="store_true",
            help="Alias for --format json.",
        )
    cardevent = data_commands.add_parser(
        "cardevent", help="Inspect the legacy CardEventNet corpus."
    )
    cardevent_commands = cardevent.add_subparsers(dest="cardevent_command", metavar="COMMAND")
    audit = cardevent_commands.add_parser(
        "audit",
        help="Audit legacy CardEventNet artifacts without changing data.",
        description="Audit legacy CardEventNet artifacts without changing data.",
    )
    _add_path_options(audit, suppress_defaults=True)
    audit.add_argument(
        "--legacy-root",
        type=Path,
        default=None,
        help="Legacy CardEventNet data root (default: card_event_net/data).",
    )
    audit.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    audit.add_argument(
        "--campaign-root",
        type=Path,
        default=None,
        help="Model campaign root (default: data/model-campaigns).",
    )
    audit.add_argument("--holdout-registry", type=Path, default=None)
    audit.add_argument("--format", choices=("human", "json"), default="human")
    audit.add_argument("--json", action="store_true", help="Alias for --format json.")
    migrate = cardevent_commands.add_parser(
        "migrate",
        help="Migrate the legacy CardEventNet corpus into shared data.",
        description="Migrate the legacy CardEventNet corpus into shared data.",
    )
    _add_path_options(migrate, suppress_defaults=True)
    migrate.add_argument(
        "--legacy-root",
        type=Path,
        default=None,
        help="Legacy CardEventNet data root (default: card_event_net/data).",
    )
    migrate.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    migrate.add_argument("--operator", required=True)
    migrate.add_argument(
        "--video-id",
        dest="video_ids",
        action="append",
        default=None,
        help="Migrate only this source recording; repeat as needed for a resumable repair.",
    )
    migrate.add_argument("--format", choices=("human", "json"), default="human")
    migrate.add_argument("--json", action="store_true", help="Alias for --format json.")
    readiness = cardevent_commands.add_parser(
        "readiness",
        help="Report CardEventNet human-review gaps without changing data.",
        description="Report CardEventNet human-review gaps without changing data.",
    )
    _add_path_options(readiness, suppress_defaults=True)
    readiness.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    readiness.add_argument(
        "--operator",
        default=None,
        help="Write a digest-backed receipt for this report using the operator ID.",
    )
    readiness.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Receipt path; requires --operator. Without this option, no file is written.",
    )
    readiness.add_argument("--format", choices=("human", "json"), default="human")
    readiness.add_argument("--json", action="store_true", help="Alias for --format json.")
    freeze = cardevent_commands.add_parser(
        "freeze",
        help="Freeze an immutable CardEventNet dataset and sealed split.",
        description="Freeze an immutable CardEventNet dataset and sealed split.",
    )
    _add_path_options(freeze, suppress_defaults=True)
    freeze.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    freeze.add_argument("--operator", required=True)
    freeze.add_argument("--format", choices=("human", "json"), default="human")
    freeze.add_argument("--json", action="store_true", help="Alias for --format json.")
    materialize = cardevent_commands.add_parser(
        "materialize",
        help="Build a disposable CardEventNet trainer view from a frozen dataset.",
        description="Build a disposable CardEventNet trainer view from a frozen dataset.",
    )
    _add_path_options(materialize, suppress_defaults=True)
    materialize.add_argument("--dataset", type=Path, required=True)
    materialize.add_argument("--output", type=Path, default=None)
    materialize.add_argument("--format", choices=("human", "json"), default="human")
    materialize.add_argument("--json", action="store_true", help="Alias for --format json.")
    interval_pilot = cardevent_commands.add_parser(
        "interval-pilot",
        help="Publish and compare one bounded trick-clear interval-review pilot.",
        description="Publish and compare one bounded trick-clear interval-review pilot.",
    )
    _add_path_options(interval_pilot, suppress_defaults=True)
    interval_pilot.add_argument("--baseline-dataset", type=Path, required=True)
    interval_pilot.add_argument("--review", type=Path, required=True)
    interval_pilot.add_argument("--output", type=Path, required=True)
    interval_pilot.add_argument("--baseline-sampling", type=Path, required=True)
    interval_pilot.add_argument("--pilot-sampling", type=Path, required=True)
    interval_pilot.add_argument("--tolerance-s", type=float, default=0.5)
    interval_pilot.add_argument("--format", choices=("human", "json"), default="human")
    interval_pilot.add_argument("--json", action="store_true", help="Alias for --format json.")
    interval_readiness = cardevent_commands.add_parser(
        "interval-readiness",
        help="Report CardEventNet interval-review readiness and diagnostic exclusions.",
        description="Report CardEventNet interval-review readiness and diagnostic exclusions.",
    )
    _add_path_options(interval_readiness, suppress_defaults=True)
    interval_readiness.add_argument(
        "--dataset", type=Path, default=None, help="Frozen dataset directory or dataset.json."
    )
    interval_readiness.add_argument(
        "--operations-root", type=Path, default=None, help="Shared operations root."
    )
    interval_readiness.add_argument(
        "--exclusion-receipt", type=Path, default=None, help="Diagnostic-only receipt path."
    )
    interval_readiness.add_argument(
        "--report", type=Path, default=None, help="Optional immutable JSON report output path."
    )
    interval_readiness.add_argument(
        "--attest-no-interval",
        dest="attest_no_intervals",
        action="append",
        default=[],
        metavar="RECORDING_ID",
        help="Record an explicit no-interval decision; requires --operator.",
    )
    interval_readiness.add_argument(
        "--operator", default=None, help="Operator ID for attestations or receipt publication."
    )
    interval_readiness.add_argument(
        "--publish-exclusion",
        action="store_true",
        help="Publish the immutable five-recording diagnostic-only exclusion receipt.",
    )
    interval_readiness.add_argument("--format", choices=("human", "json"), default="human")
    interval_readiness.add_argument("--json", action="store_true", help="Alias for --format json.")
    interval_freeze = cardevent_commands.add_parser(
        "interval-freeze",
        help="Freeze and audit the interval-aware CardEventNet dataset.",
        description="Freeze and audit the interval-aware CardEventNet dataset.",
    )
    _add_path_options(interval_freeze, suppress_defaults=True)
    interval_freeze.add_argument(
        "--baseline-dataset",
        type=Path,
        default=None,
        help="M3 frozen dataset directory or dataset.json.",
    )
    interval_freeze.add_argument(
        "--interval-readiness", type=Path, default=None, help="M6 interval-readiness report."
    )
    interval_freeze.add_argument(
        "--exclusion-receipt", type=Path, default=None, help="M6 diagnostic-only exclusion receipt."
    )
    interval_freeze.add_argument(
        "--operations-root", type=Path, default=None, help="Shared operations root."
    )
    interval_freeze.add_argument(
        "--baseline-view",
        type=Path,
        default=None,
        help="M3 disposable trainer view for cache reuse.",
    )
    interval_freeze.add_argument(
        "--cache-source",
        type=Path,
        default=None,
        help="Disposable cache view to link into the new view.",
    )
    interval_freeze.add_argument(
        "--view-output", type=Path, default=None, help="Disposable interval-aware trainer view."
    )
    interval_freeze.add_argument(
        "--sampling-report", type=Path, default=None, help="Immutable sampling report output path."
    )
    interval_freeze.add_argument(
        "--report", type=Path, default=None, help="Immutable combined M7 report output path."
    )
    interval_freeze.add_argument("--operator", required=True)
    interval_freeze.add_argument("--format", choices=("human", "json"), default="human")
    interval_freeze.add_argument("--json", action="store_true", help="Alias for --format json.")
    baseline = data_commands.add_parser(
        "resilience-baseline",
        help="Freeze the visible-region identity resilience contract and report coverage.",
        description="Freeze the visible-region identity resilience contract and report coverage.",
    )
    _add_path_options(baseline, suppress_defaults=True)
    baseline.add_argument(
        "--runtime-root",
        type=Path,
        default=None,
        help="Pipeline revision root (default: data/operations).",
    )
    baseline.add_argument(
        "--holdout-registry",
        type=Path,
        default=None,
        help="Path to the shared system holdout registry.",
    )
    baseline.add_argument("--classifier-provider", default=DEFAULT_CLASSIFIER_PROVIDER)
    baseline.add_argument("--classifier-model", default=DEFAULT_CLASSIFIER_MODEL)
    baseline.add_argument(
        "--output", type=Path, default=None, help="Optional manifest output path."
    )
    baseline.add_argument("--format", choices=("human", "json"), default="human")
    baseline.add_argument("--json", action="store_true", help="Alias for --format json.")
    rfdetr = data_commands.add_parser(
        "rfdetr-segmentation",
        aliases=("rfdetr-segmentation-audit",),
        help="Audit and freeze the RF-DETR visible-region segmentation input.",
        description="Audit and freeze the RF-DETR visible-region segmentation input.",
    )
    _add_path_options(rfdetr, suppress_defaults=True)
    rfdetr.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    rfdetr.add_argument(
        "--holdout-registry",
        type=Path,
        default=None,
        help="Path to the shared system holdout registry.",
    )
    rfdetr.add_argument(
        "--pretrained-checkpoint",
        type=Path,
        default=None,
        help="Explicit RF-DETR segmentation checkpoint to digest and pin.",
    )
    rfdetr.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    rfdetr.add_argument(
        "--verify-source-bytes",
        action="store_true",
        help="Hash every selected source video in addition to checking declared digests.",
    )
    rfdetr.add_argument(
        "--output",
        type=Path,
        default=Path("data/operations/rfdetr-segmentation-0067-m0-manifest.json"),
        help=(
            "Immutable manifest path (default: "
            "data/operations/rfdetr-segmentation-0067-m0-manifest.json)."
        ),
    )
    rfdetr.add_argument("--format", choices=("human", "json"), default="human")
    rfdetr.add_argument("--json", action="store_true", help="Alias for --format json.")
    rfdetr_materialize = data_commands.add_parser(
        "rfdetr-segmentation-materialize",
        aliases=("rfdetr-segmentation-view",),
        help="Materialize a frozen RF-DETR visible-region COCO trainer view.",
        description="Materialize a frozen RF-DETR visible-region COCO trainer view.",
    )
    _add_path_options(rfdetr_materialize, suppress_defaults=True)
    rfdetr_materialize.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Frozen M0 RF-DETR segmentation manifest.",
    )
    rfdetr_materialize.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/rfdetr-segmentation-0067"),
        help="Disposable trainer-view directory.",
    )
    rfdetr_materialize.add_argument("--format", choices=("human", "json"), default="human")
    rfdetr_materialize.add_argument("--json", action="store_true", help="Alias for --format json.")
    comparison = data_commands.add_parser(
        "resilience-comparison",
        help="Run the frozen paired visible-region resilience comparison.",
        description="Run the frozen paired visible-region resilience comparison.",
    )
    _add_path_options(comparison, suppress_defaults=True)
    comparison.add_argument("--manifest", type=Path, required=True)
    comparison.add_argument(
        "--rows", type=Path, required=True, help="JSON list of retained M3 comparison rows."
    )
    comparison.add_argument(
        "--output", type=Path, required=True, help="Directory for comparison and row artifacts."
    )
    comparison.add_argument("--elapsed-wall-clock-seconds", type=float, default=0)
    comparison.add_argument("--format", choices=("human", "json"), default="human")
    comparison.add_argument("--json", action="store_true", help="Alias for --format json.")
    resilience_materialize = data_commands.add_parser(
        "resilience-materialize",
        help="Plan or materialize the frozen visible-region resilience work matrix.",
        description="Plan or materialize the frozen visible-region resilience work matrix.",
    )
    _add_path_options(resilience_materialize, suppress_defaults=True)
    resilience_materialize.add_argument("--manifest", type=Path, required=True)
    resilience_materialize.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/visible-region-identity-resilience-m3"),
        help="Resumable M3 work directory.",
    )
    resilience_materialize.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the complete matrix and cache reuse without extracting frames.",
    )
    resilience_materialize.add_argument("--format", choices=("human", "json"), default="human")
    resilience_materialize.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    resilience_execute = data_commands.add_parser(
        "resilience-execute",
        help="Execute the pinned classifier over retained M3 crops.",
        description="Execute the pinned classifier over retained M3 crops.",
    )
    _add_path_options(resilience_execute, suppress_defaults=True)
    resilience_execute.add_argument("--work", type=Path, required=True)
    resilience_execute.add_argument("--format", choices=("human", "json"), default="human")
    resilience_execute.add_argument("--json", action="store_true", help="Alias for --format json.")
    complete = data_commands.add_parser(
        "complete-video",
        help="Complete one pending video and publish a recording bundle.",
        description="Complete one pending video and publish a recording bundle.",
    )
    _add_path_options(complete, suppress_defaults=True)
    complete.add_argument("--upload-id", required=True)
    complete.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="Strict pending-video-completion/v1 JSON metadata file.",
    )
    complete.add_argument("--format", choices=("human", "json"), default="human")
    complete.add_argument("--json", action="store_true", help="Alias for --format json.")
    adopt = data_commands.add_parser(
        "adopt-evidence",
        aliases=("adopt-evidence-package",),
        help="Adopt one legacy runtime evidence package into repository intake.",
        description="Adopt one legacy runtime evidence package into repository intake.",
    )
    _add_path_options(adopt, suppress_defaults=True)
    adopt.add_argument(
        "--runtime-root",
        type=Path,
        required=True,
        help="Legacy backend runtime root containing evidence/<package-id>.",
    )
    adopt.add_argument("--package-id", required=True)
    adopt.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="JSON metadata object or directory with the package record, enrollment, and lineage.",
    )
    adopt.add_argument("--format", choices=("human", "json"), default="human")
    adopt.add_argument("--json", action="store_true", help="Alias for --format json.")
    holdout = data_commands.add_parser("holdout", help="Manage the shared system holdout registry.")
    holdout_commands = holdout.add_subparsers(dest="holdout_command", metavar="COMMAND")
    seal = holdout_commands.add_parser(
        "seal", help="Seal one reviewed group for end-to-end system evaluation."
    )
    _add_path_options(seal, suppress_defaults=True)
    seal.add_argument(
        "--group-name",
        choices=("session_id", "game_id", "table_setup", "source_lineage"),
        required=True,
    )
    seal.add_argument("--group-value", required=True)
    seal.add_argument("--reviewer", required=True, help="Reviewer who approved the seal.")
    seal.add_argument("--review-id", default=None, help="Existing review identifier, if any.")
    seal.add_argument("--reason", required=True)
    seal.add_argument("--holdout-registry", type=Path, default=None)
    seal.add_argument("--format", choices=("human", "json"), default="human")
    seal.add_argument("--json", action="store_true", help="Alias for --format json.")
    impact = data_commands.add_parser(
        "impact",
        help="Report source permission and retirement impact.",
        description="Report source permission and retirement impact.",
    )
    _add_path_options(impact, suppress_defaults=True)
    impact.add_argument("--source-asset-id", default=None)
    impact.add_argument("--retention-state", choices=tuple(sorted(RETIREMENT_STATES | {"active"})))
    impact.add_argument("--format", choices=("human", "json"), default="human")
    impact.add_argument("--json", action="store_true", help="Alias for --format json.")
    source = data_commands.add_parser("source", help="Write versioned source lifecycle state.")
    source_commands = source.add_subparsers(dest="source_command", metavar="COMMAND")
    retire = source_commands.add_parser(
        "retire", help="Withdraw permission or retire one source asset."
    )
    _add_path_options(retire, suppress_defaults=True)
    retire.add_argument("--source-asset-id", required=True)
    retire.add_argument(
        "--retention-state", choices=tuple(sorted(RETIREMENT_STATES)), required=True
    )
    retire.add_argument("--operator", required=True)
    retire.add_argument("--reason", required=True)
    retire.add_argument("--format", choices=("human", "json"), default="human")
    retire.add_argument("--json", action="store_true", help="Alias for --format json.")
    model = commands.add_parser("model", help="Inspect model champions and campaigns.")
    model_commands = model.add_subparsers(dest="model_command", metavar="COMMAND")
    status = model_commands.add_parser(
        "status", help="Show read-only model registry and campaign status."
    )
    _add_path_options(status, suppress_defaults=True)
    _add_model_options(status)
    compare = model_commands.add_parser(
        "compare", help="Show one read-only model campaign comparison."
    )
    _add_path_options(compare, suppress_defaults=True)
    _add_model_options(compare)
    compare.add_argument("campaign_id")
    review = model_commands.add_parser(
        "review-card-event-net",
        help="Validate one completed CardEventNet campaign and publish its M9 review artifacts.",
    )
    _add_path_options(review, suppress_defaults=True)
    _add_model_options(review)
    review.add_argument("campaign_id")
    improve = model_commands.add_parser(
        "improve", help="Run or resume a bounded component improvement campaign."
    )
    _add_path_options(improve, suppress_defaults=True)
    _add_model_options(improve)
    improve.add_argument("component", choices=("card-event-net", "table-evidence-analyzer"))
    improve.add_argument("--recipe", type=Path, required=True)
    improve.add_argument("--campaign-id", default=None)
    improve.add_argument(
        "--preflight",
        action="store_true",
        help="Validate inputs and write an operator handoff without starting the campaign.",
    )
    improve.add_argument(
        "--handoff",
        type=Path,
        default=None,
        help="Handoff JSON path for --preflight (default: campaign directory/handoff.json).",
    )
    improve.add_argument(
        "--runner",
        choices=("cardevent", "table-evidence-analyzer", "fixture"),
        default="cardevent",
        help="Execution backend; fixture is for local clean-room checks.",
    )
    improve.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="CardEventNet project root (default: card_event_net).",
    )
    improve.add_argument("--config", type=Path, default=None, help="Default CardEventNet config.")
    improve.add_argument("--split", type=Path, default=None, help="Default CardEventNet split.")
    improve.add_argument("--cache-dir", type=Path, default=None)
    improve.add_argument("--annotations-dir", type=Path, default=None)
    improve.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Explicit frozen dataset path for the selected model component.",
    )
    improve.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help="Explicit plan 0020 sample-artifact index for TableEvidenceAnalyzer.",
    )
    improve.add_argument(
        "--champion-run",
        type=Path,
        default=None,
        help="Explicit analyzer champion run or capability bundle.",
    )
    improve.add_argument("--max-samples", type=int, default=None)
    improve.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default=None)
    improve.add_argument("--precision", choices=("fp32", "bf16"), default=None)
    promote = model_commands.add_parser(
        "promote", help="Test and promote one explicitly confirmed locked candidate."
    )
    _add_path_options(promote, suppress_defaults=True)
    _add_model_options(promote)
    promote.add_argument("campaign_id")
    promote.add_argument("--candidate", dest="candidate_id", default=None)
    promote.add_argument(
        "--runner",
        choices=("cardevent", "table-evidence-analyzer", "fixture"),
        default="cardevent",
        help=("Execution backend (default: cardevent; fixture is for local clean-room checks)."),
    )
    promote.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the one-time sealed test and promotion operation.",
    )
    promote.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="CardEventNet project root (default: card_event_net).",
    )
    promote.add_argument("--split", type=Path, default=None)
    promote.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Explicit plan 0020 dataset manifest for TableEvidenceAnalyzer.",
    )
    promote.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help="Explicit plan 0020 sample-artifact index for TableEvidenceAnalyzer.",
    )
    promote.add_argument("--cache-dir", type=Path, default=None)
    promote.add_argument("--annotations-dir", type=Path, default=None)
    promote.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default=None)
    promote.add_argument(
        "--app-bundle",
        type=Path,
        default=None,
        help=(
            "Checked-in app bundle path (default: "
            "ios/CardEventProbe/CardEventNetTransitionV2.mlpackage)."
        ),
    )
    system = model_commands.add_parser(
        "evaluate-system", help="Run the locked composed pipeline on the shared system holdout."
    )
    _add_path_options(system, suppress_defaults=True)
    _add_model_options(system)
    system.add_argument("cardevent_campaign_id")
    system.add_argument("table_campaign_id")
    system.add_argument("--holdout-registry", type=Path, default=None)
    system.add_argument("--cardevent-dataset", type=Path, required=True)
    system.add_argument("--cardevent-split", type=Path, required=True)
    system.add_argument("--table-dataset", type=Path, required=True)
    system.add_argument("--table-split", type=Path, required=True)
    system.add_argument("--reconstruction-config", type=Path, default=None)
    system.add_argument("--fixture", type=Path, default=None)
    system.add_argument("--evaluation-root", type=Path, default=None)
    system.add_argument(
        "--runner",
        choices=("fixture",),
        default="fixture",
        help="Execution backend (the local fixture is the supported M5 backend).",
    )
    system.add_argument(
        "--fail-boundary",
        choices=FAILURE_BOUNDARIES,
        default=None,
        help="Inject one local fixture failure for attribution tests.",
    )
    reconstruct = commands.add_parser(
        "reconstruct",
        help="Run local game reconstruction.",
        description="Run local game reconstruction.",
    )
    reconstruct_commands = reconstruct.add_subparsers(dest="reconstruct_command", metavar="COMMAND")
    round_command = reconstruct_commands.add_parser(
        "round",
        help="Reconstruct one round from a strict local request file.",
        description="Reconstruct one round from a strict local request file.",
    )
    round_command.add_argument(
        "--request",
        type=Path,
        required=True,
        help="Path to a round-reconstruction-run/v1 JSON request.",
    )
    return parser


def _add_path_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--repository-root",
        "--root",
        dest="repository_root",
        type=Path,
        default=default,
        help="Repository checkout to inspect (default: discover from mise.toml).",
    )
    parser.add_argument(
        "--intake-root",
        dest="intake_root",
        type=Path,
        default=default,
        help="Override the repository intake root; useful for a fixture or temporary root.",
    )
    parser.add_argument(
        "--pending-video-root",
        dest="pending_video_root",
        type=Path,
        default=default,
        help="Override the raw pending-video root.",
    )
    parser.add_argument(
        "--evidence-package-root",
        dest="evidence_package_root",
        type=Path,
        default=default,
        help="Override the canonical accepted evidence-package root.",
    )
    parser.add_argument(
        "--artifacts-root",
        dest="artifacts_root",
        type=Path,
        default=default,
        help="Override the read-only derived-artifact root.",
    )


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model-registry",
        type=Path,
        default=None,
        help="Override the champion registry path (default: data/model-registry.json).",
    )
    parser.add_argument(
        "--campaign-root",
        type=Path,
        default=None,
        help="Override the campaign root (default: data/model-campaigns).",
    )
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="Output format (default: human).",
    )
    parser.add_argument("--json", action="store_true", help="Alias for --format json.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one repository operation and return its process status."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "data" and args.data_command is None:
        data_parser = next(
            action for action in parser._subparsers._group_actions if action.dest == "command"
        )
        data_parser.choices["data"].print_help()
        return 0
    if args.command == "data" and args.data_command == "cardevent":
        if args.cardevent_command not in {
            "audit",
            "migrate",
            "readiness",
            "freeze",
            "materialize",
            "interval-pilot",
            "interval-readiness",
            "interval-freeze",
        }:
            data_parser = next(
                action for action in parser._subparsers._group_actions if action.dest == "command"
            )
            data_parser.choices["data"].choices["cardevent"].print_help()
            return 0
        if args.cardevent_command == "migrate":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                result = migrate_cardeventnet(
                    config.repository_root,
                    legacy_root=args.legacy_root,
                    intake_root=config.intake_root,
                    operations_root=args.operations_root or config.derived_artifact_root,
                    operator=args.operator,
                    video_ids=args.video_ids,
                )
            except (ConfigurationError, OSError, CardEventNetMigrationError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                sys.stdout.write(json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write(render_cardevent_migration_human(result))
            return 0
        if args.cardevent_command == "readiness":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                operations_root = args.operations_root or config.derived_artifact_root
                report = build_cardeventnet_readiness(
                    config.repository_root,
                    intake_root=config.bundle_root,
                    operations_root=operations_root,
                )
                receipt = None
                if args.receipt is not None and args.operator is None:
                    raise CardEventNetReadinessError("--receipt requires --operator")
                if args.operator is not None:
                    receipt_path = args.receipt
                    if receipt_path is None:
                        receipt_path = (
                            Path(operations_root).expanduser()
                            / "cardeventnet-readiness"
                            / "receipts"
                            / f"readiness-{report.to_mapping()['report_digest']}.json"
                        )
                    if not receipt_path.is_absolute():
                        receipt_path = config.repository_root / receipt_path
                    receipt = write_cardeventnet_readiness_receipt(
                        report,
                        receipt_path,
                        operator=args.operator,
                    )
            except (ConfigurationError, OSError, CardEventNetReadinessError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                output = report.to_mapping()
                if receipt is not None:
                    output["receipt"] = receipt
                sys.stdout.write(
                    json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )
            else:
                sys.stdout.write(
                    render_cardeventnet_readiness_human(
                        report,
                        receipt_path=receipt["path"] if receipt is not None else None,
                    )
                )
            return 0
        if args.cardevent_command == "freeze":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                result = freeze_cardeventnet_dataset(
                    config.repository_root,
                    intake_root=config.bundle_root,
                    operations_root=args.operations_root or config.derived_artifact_root,
                    operator=args.operator,
                )
            except CardEventNetDatasetFreezeError as error:
                result = error.report
                if result is None:
                    print(f"error: {error}", file=sys.stderr)
                    return 2
                if args.json or args.format == "json":
                    sys.stdout.write(
                        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                    )
                else:
                    sys.stdout.write(render_cardeventnet_freeze_human(result))
                return 2
            except (ConfigurationError, OSError, ValueError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                sys.stdout.write(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )
            else:
                sys.stdout.write(render_cardeventnet_freeze_human(result))
            return 0
        if args.cardevent_command == "materialize":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                result = materialize_cardeventnet_dataset(
                    args.dataset,
                    repository_root=config.repository_root,
                    output_root=args.output,
                )
            except (ConfigurationError, OSError, CardEventNetMaterializationError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                sys.stdout.write(json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write(
                    "CardEventNet trainer view materialized\n"
                    f"dataset: {result.dataset_version_id}\n"
                    f"split: {result.split_version_id}\n"
                    f"view: {result.view_root}\n"
                    f"manifest: {result.manifest_digest}\n"
                )
            return 0
        if args.cardevent_command == "interval-pilot":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                result = run_cardeventnet_interval_pilot(
                    config.repository_root,
                    baseline_dataset_path=args.baseline_dataset,
                    review_path=args.review,
                    output_root=args.output,
                    baseline_sampling_report_path=args.baseline_sampling,
                    pilot_sampling_report_path=args.pilot_sampling,
                    tolerance_s=args.tolerance_s,
                )
            except (ConfigurationError, OSError, CardEventNetIntervalPilotError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write(render_cardeventnet_interval_pilot_human(result))
            return 0
        if args.cardevent_command == "interval-readiness":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                if (args.attest_no_intervals or args.publish_exclusion) and args.operator is None:
                    raise CardEventNetIntervalReadinessError(
                        "--operator is required for attestations or --publish-exclusion"
                    )
                operations_root = args.operations_root or config.derived_artifact_root
                written: list[dict[str, object]] = []
                for recording_id in args.attest_no_intervals:
                    written.append(
                        write_cardeventnet_zero_interval_attestation(
                            config.repository_root,
                            recording_id,
                            operator=args.operator,
                            dataset_path=args.dataset,
                            operations_root=operations_root,
                        )
                    )
                if args.publish_exclusion:
                    written.append(
                        write_legacy_device_exclusion_receipt(
                            config.repository_root,
                            operator=args.operator,
                            dataset_path=args.dataset,
                            output_path=args.exclusion_receipt,
                        )
                    )
                report = build_cardeventnet_interval_readiness(
                    config.repository_root,
                    dataset_path=args.dataset,
                    operations_root=operations_root,
                    exclusion_receipt_path=args.exclusion_receipt,
                )
                report_receipt = None
                if args.report is not None:
                    report_receipt = write_cardeventnet_interval_readiness_report(
                        config.repository_root, report, args.report
                    )
            except (ConfigurationError, OSError, CardEventNetIntervalReadinessError) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            if args.json or args.format == "json":
                output = dict(report)
                if written:
                    output["written"] = written
                if report_receipt is not None:
                    output["report_artifact"] = report_receipt
                sys.stdout.write(
                    json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )
            else:
                sys.stdout.write(render_cardeventnet_interval_readiness_human(report))
                for item in written:
                    sys.stdout.write(f"written: {item['path']}\n")
            return 0 if report["state"] == "ready" else 1
        if args.cardevent_command == "interval-freeze":
            try:
                config = RepositoryConfig.from_environment(
                    getattr(args, "repository_root", None),
                    intake_root=getattr(args, "intake_root", None),
                    artifacts_root=getattr(args, "artifacts_root", None),
                )
                operations_root = args.operations_root or config.derived_artifact_root
                freeze_result = freeze_cardeventnet_interval_dataset(
                    config.repository_root,
                    operator=args.operator,
                    baseline_dataset_path=args.baseline_dataset,
                    interval_readiness_path=args.interval_readiness,
                    exclusion_receipt_path=args.exclusion_receipt,
                    operations_root=operations_root,
                )
                dataset_path = config.repository_root / freeze_result["path"]
                baseline_view = args.baseline_view
                if baseline_view is None:
                    baseline_view = (
                        config.repository_root
                        / ".runtime"
                        / "cardevent"
                        / "datasets"
                        / str(freeze_result["baseline_dataset"]["id"])
                    )
                cache_source = args.cache_source or baseline_view
                materialization = materialize_cardeventnet_dataset(
                    dataset_path,
                    repository_root=config.repository_root,
                    output_root=args.view_output,
                    cache_source_root=cache_source,
                )
                sampling = build_cardeventnet_interval_sampling_report(
                    config.repository_root,
                    dataset_path=dataset_path,
                    materialized_view_path=materialization.view_root,
                    baseline_dataset_path=args.baseline_dataset,
                    baseline_view_path=baseline_view,
                )
                sampling_path = args.sampling_report or (
                    config.repository_root
                    / "data"
                    / "operations"
                    / "cardeventnet-interval-readiness"
                    / "reports"
                    / f"{freeze_result['dataset_version_id']}-sampling.json"
                )
                sampling_artifact = write_cardeventnet_interval_report(
                    config.repository_root, sampling, sampling_path
                )
                combined = build_cardeventnet_interval_dataset_report(
                    freeze_result, materialization, sampling
                )
                report_path = args.report or (
                    config.repository_root
                    / "data"
                    / "operations"
                    / "cardeventnet-interval-readiness"
                    / "reports"
                    / f"{freeze_result['dataset_version_id']}.json"
                )
                report_artifact = write_cardeventnet_interval_report(
                    config.repository_root, combined, report_path
                )
            except (
                ConfigurationError,
                OSError,
                CardEventNetIntervalDatasetError,
                CardEventNetMaterializationError,
            ) as error:
                print(f"error: {error}", file=sys.stderr)
                return 2
            output = {
                **freeze_result,
                "materialization": materialization.to_mapping(),
                "sampling_report": sampling_artifact,
                "report": report_artifact,
            }
            if args.json or args.format == "json":
                sys.stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write(
                    "CardEventNet interval-aware dataset\n"
                    f"state: {output['state']}\n"
                    f"dataset: {output['dataset_version_id']}\n"
                    f"train recordings: {output['partition_counts']['train']}\n"
                    f"validation recordings: {output['partition_counts']['validation']}\n"
                    f"sealed test recordings: {output['partition_counts']['test']}\n"
                    f"excluded diagnostic recordings: {len(output['excluded_recordings'])}\n"
                    f"view: {output['materialization']['view_root']}\n"
                    f"sampling report: {output['sampling_report']['path']}\n"
                    f"report: {output['report']['path']}\n"
                )
            return 0
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            report = audit_cardeventnet(
                config.repository_root,
                legacy_root=args.legacy_root,
                intake_root=getattr(args, "intake_root", None),
                operations_root=args.operations_root or getattr(args, "artifacts_root", None),
                campaign_root=args.campaign_root,
                holdout_registry=args.holdout_registry,
            )
        except (ConfigurationError, OSError, CardEventNetInventoryError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(render_cardevent_inventory_json(report))
        else:
            sys.stdout.write(render_cardevent_inventory_human(report))
        return 0
    if args.command == "data" and args.data_command == "impact":
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            if args.source_asset_id:
                result = analyze_source_impact(
                    config.repository_root,
                    args.source_asset_id,
                    bundle_root=config.bundle_root,
                    artifacts_root=config.derived_artifact_root,
                    requested_retention_state=args.retention_state,
                )
            else:
                if args.retention_state is not None:
                    raise SourceImpactError(
                        "--retention-state requires --source-asset-id for an impact preview."
                    )
                result = {
                    "schema_version": "source-impact-index/v1",
                    "reports": list(
                        analyze_repository_impacts(
                            config.repository_root,
                            bundle_root=config.bundle_root,
                            artifacts_root=config.derived_artifact_root,
                        )
                    ),
                }
        except (ConfigurationError, OSError, SourceImpactError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            sys.stdout.write(_render_impact_human(result))
        return 0
    if args.command == "data" and args.data_command == "resilience-baseline":
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_resilience_baseline_manifest(
                config.repository_root,
                runtime_root=args.runtime_root,
                operations_root=config.derived_artifact_root,
                intake_root=config.bundle_root,
                holdout_registry_path=args.holdout_registry,
                classifier_provider=args.classifier_provider,
                classifier_model=args.classifier_model,
            )
            if args.output is not None:
                output_path = args.output
                if not output_path.is_absolute():
                    output_path = config.repository_root / output_path
                write_resilience_baseline_manifest(output_path, manifest)
            if args.json or args.format == "json":
                sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write(render_resilience_baseline_human(manifest))
        except (ConfigurationError, OSError, ResilienceBaselineError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        return 0 if manifest["validation_classification_allowed"] else 1
    if args.command == "data" and args.data_command in {
        "rfdetr-segmentation",
        "rfdetr-segmentation-audit",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            operations_root = args.operations_root or config.derived_artifact_root
            manifest = build_rfdetr_segmentation_manifest(
                config.repository_root,
                intake_root=config.bundle_root,
                operations_root=operations_root,
                holdout_registry_path=args.holdout_registry,
                pretrained_checkpoint=args.pretrained_checkpoint,
                device=args.device,
                verify_source_bytes=args.verify_source_bytes,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            if manifest["freeze_state"] == "frozen":
                write_rfdetr_segmentation_manifest(output_path, manifest)
        except (ConfigurationError, OSError, RfdetrSegmentationCampaignError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_rfdetr_segmentation_human(manifest))
        return 0 if manifest["freeze_state"] == "frozen" else 1
    if args.command == "data" and args.data_command in {
        "rfdetr-segmentation-materialize",
        "rfdetr-segmentation-view",
    }:
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            manifest_path = args.manifest
            if not manifest_path.is_absolute():
                manifest_path = config.repository_root / manifest_path
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            result = materialize_rfdetr_segmentation_dataset(
                manifest_path,
                repository_root=config.repository_root,
                output_root=output_path,
            )
        except (ConfigurationError, OSError, RfdetrSegmentationMaterializationError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                "RF-DETR segmentation trainer view materialized\n"
                f"view: {result.view_root}\n"
                f"images: {result.image_count}\n"
                f"annotations: {result.annotation_count}\n"
                f"excluded frames: {result.excluded_frame_count}\n"
                f"ineligible outcomes: {result.ineligible_outcome_count}\n"
                f"manifest: {result.materialization_digest}\n"
            )
        return 0
    if args.command == "data" and args.data_command == "resilience-materialize":
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            manifest_path = args.manifest.expanduser()
            if not manifest_path.is_absolute():
                manifest_path = config.repository_root / manifest_path
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            output_path = args.output.expanduser()
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            result = (
                build_resilience_work_plan(manifest, output_root=output_path)
                if args.dry_run
                else materialize_resilience_work(
                    manifest,
                    repository_root=config.repository_root,
                    output_root=output_path,
                )
            )
        except (
            ConfigurationError,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        elif args.dry_run:
            sys.stdout.write(
                "Visible-region identity resilience M3 work plan\n"
                f"work items: {result['planned_classifier_request_count']}\n"
                f"reusable crops: {result['cache_reusable_crop_count']}\n"
                f"estimated cost: ${result['estimated_cost_usd']:.4f}\n"
                "classifier execution: not started\n"
            )
        else:
            counts = result["counts"]
            sys.stdout.write(
                "Visible-region identity resilience M3 crops materialized\n"
                f"work items: {counts['planned_work_count']}\n"
                f"new crops: {counts['materialized_crop_count']}\n"
                f"reused crops: {counts['reused_crop_count']}\n"
                f"unusable crops: {counts['unusable_crop_count']}\n"
                f"failed crops: {counts['failed_crop_count']}\n"
                f"work manifest: {output_path / 'work.json'}\n"
            )
        return 0
    if args.command == "data" and args.data_command == "resilience-execute":
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            work_path = args.work.expanduser()
            if not work_path.is_absolute():
                work_path = config.repository_root / work_path
            from table_evidence_analyzer.card_classification import (
                CachedCardClassifier,
                GeminiCardClassifier,
            )

            classifier = CachedCardClassifier(
                GeminiCardClassifier.from_environment(), work_path.parent / "classifier-cache"
            )
            result = execute_resilience_work(work_path, classifier=classifier)
        except (
            ConfigurationError,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            summary = result["summary"]
            sys.stdout.write(
                "Visible-region identity resilience M3 comparison complete\n"
                f"rows: {summary['retained_row_count']}\n"
                f"classifier requests: {summary['classifier_request_count']}\n"
                f"cached results: {summary['classifier_cache_reused_count']}\n"
                f"comparison: {result['comparison_path']}\n"
            )
        return 0
    if args.command == "data" and args.data_command == "resilience-comparison":
        try:
            manifest_path = args.manifest.expanduser()
            rows_path = args.rows.expanduser()
            output_path = args.output.expanduser()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows_value = json.loads(rows_path.read_text(encoding="utf-8"))
            if isinstance(rows_value, dict):
                rows_value = rows_value.get("rows")
            if not isinstance(rows_value, list):
                raise ResilienceComparisonError("retained rows file must contain a JSON list")
            comparison_result = run_resilience_comparison(
                manifest,
                rows_value,
                elapsed_wall_clock_seconds=args.elapsed_wall_clock_seconds,
            )
            write_resilience_comparison(output_path, comparison_result)
        except ResilienceComparisonBlocked as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(comparison_result, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_resilience_comparison_human(comparison_result))
        return 0
    if args.command == "data" and args.data_command == "source":
        if args.source_command != "retire":
            parser.parse_args(["data", "source", "--help"])
            return 0
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            result = retire_source(
                config.repository_root,
                args.source_asset_id,
                bundle_root=config.bundle_root,
                artifacts_root=config.derived_artifact_root,
                retention_state=args.retention_state,
                operator=args.operator,
                reason=args.reason,
            )
        except (ConfigurationError, OSError, SourceImpactError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            state = result["source_state"]
            receipt = result["stale_receipt"]
            sys.stdout.write(
                "Source lifecycle state recorded\n"
                f"source: {state['source_asset_id']}\n"
                f"retention state: {state['retention_state']}\n"
                f"state version: {state['version']}\n"
                f"stale receipt: {receipt['receipt_id']}\n"
            )
        return 0
    if args.command == "data" and args.data_command == "holdout":
        if args.holdout_command != "seal":
            parser.parse_args(["data", "holdout", "--help"])
            return 0
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            registry_path = args.holdout_registry or (
                config.derived_artifact_root / "system-holdout-registry.json"
            )
            if not registry_path.is_absolute():
                registry_path = config.repository_root / registry_path
            result = seal_system_holdout_group(
                registry_path,
                group_name=args.group_name,
                group_value=args.group_value,
                reviewer=args.reviewer,
                review_id=args.review_id,
                reason=args.reason,
            )
        except (ConfigurationError, OSError, SystemHoldoutError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            seal = result["seals"][-1]
            sys.stdout.write(
                "System holdout group sealed\n"
                f"registry: {registry_path}\n"
                f"version: {result['registry_version']}\n"
                f"group: {seal['group_key']['name']}:{seal['group_key']['value']}\n"
                f"seal: {seal['seal_id']}\n"
            )
        return 0
    if args.command == "data" and args.data_command == "complete-video":
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            result = complete_pending_video(
                config.repository_root,
                args.upload_id,
                args.metadata,
                pending_video_root=config.pending_root,
                intake_root=config.intake_root,
            )
        except (ConfigurationError, OSError, PendingVideoCompletionError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(
                    result.to_mapping(config.repository_root),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            sys.stdout.write(
                "Pending video completed\n"
                f"upload: {result.upload_id}\n"
                f"recording: {result.recording_id}\n"
                f"bundle: {result.to_mapping(config.repository_root)['bundle_path']}\n"
                f"source SHA-256: {result.source_sha256}\n"
            )
        return 0
    if args.command == "data" and args.data_command in {
        "adopt-evidence",
        "adopt-evidence-package",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            result = adopt_runtime_evidence_package(
                args.runtime_root,
                args.package_id,
                args.metadata,
                evidence_package_root=config.evidence_package_intake_root,
            )
        except (ConfigurationError, OSError, EvidencePackageAdoptionError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                "Evidence package adopted\n"
                f"package: {result['package_id']}\n"
                f"state: {result['state']}\n"
                f"path: {result['path']}\n"
            )
        return 0
    if args.command == "model":
        if args.model_command is None:
            model_parser = next(
                action for action in parser._subparsers._group_actions if action.dest == "command"
            )
            model_parser.choices["model"].print_help()
            return 0
        try:
            config = RepositoryConfig.from_environment(args.repository_root)
            if args.model_command == "improve":
                if args.preflight:
                    if args.component != "card-event-net":
                        raise ValueError("--preflight is supported only for card-event-net")
                    handoff = preflight_card_event_campaign(
                        args.recipe,
                        repository_root=config.repository_root,
                        registry_path=args.model_registry,
                        campaign_root=args.campaign_root,
                        campaign_id=args.campaign_id,
                        project_root=args.project_root,
                        dataset_path=args.dataset,
                        device=args.device,
                        precision=args.precision,
                        handoff_path=args.handoff,
                    )
                    if args.json or args.format == "json":
                        sys.stdout.write(json.dumps(handoff, indent=2, sort_keys=True) + "\n")
                    else:
                        sys.stdout.write(
                            "CardEventNet campaign preflight\n"
                            f"campaign: {handoff['campaign_id']}\n"
                            f"state: {handoff['status']}\n"
                            f"handoff: {handoff['handoff_path']}\n"
                            f"manual command: {handoff['commands']['manual']}\n"
                        )
                    return 0
                if args.component == "table-evidence-analyzer":
                    command_runner = (
                        TableEvidenceFixtureCommandRunner() if args.runner == "fixture" else None
                    )
                    campaign = run_table_evidence_campaign(
                        args.recipe,
                        repository_root=config.repository_root,
                        registry_path=args.model_registry,
                        campaign_root=args.campaign_root,
                        campaign_id=args.campaign_id,
                        project_root=args.project_root,
                        dataset_path=args.dataset,
                        split_path=args.split,
                        artifacts_path=args.artifacts,
                        champion_run_path=args.champion_run,
                        device=args.device,
                        precision=args.precision,
                        runner=command_runner,
                    )
                    label = "TableEvidenceAnalyzer"
                else:
                    command_runner = FixtureCommandRunner() if args.runner == "fixture" else None
                    campaign = run_card_event_campaign(
                        args.recipe,
                        repository_root=config.repository_root,
                        registry_path=args.model_registry,
                        campaign_root=args.campaign_root,
                        campaign_id=args.campaign_id,
                        project_root=args.project_root,
                        config_path=args.config,
                        split_path=args.split,
                        cache_dir=args.cache_dir,
                        annotations_dir=args.annotations_dir,
                        dataset_path=args.dataset,
                        max_samples=args.max_samples,
                        device=args.device,
                        precision=args.precision,
                        runner=command_runner,
                    )
                    label = "CardEventNet"
                campaign_root = (
                    args.campaign_root or config.repository_root / "data" / "model-campaigns"
                )
                if not campaign_root.is_absolute():
                    campaign_root = config.repository_root / campaign_root
                result = {
                    "campaign": campaign.to_mapping(),
                    "campaign_path": str(campaign_root / campaign.campaign_id),
                }
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(
                        f"{label} campaign\n"
                        f"campaign: {campaign.campaign_id}\n"
                        f"state: {campaign.state}\n"
                        f"recommendation: {campaign.recommendation or 'pending'}\n"
                        f"artifacts: {result['campaign_path']}\n"
                    )
                return 1 if campaign.state == "failed" else 0
            if args.model_command == "review-card-event-net":
                review = review_cardeventnet_m9(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(review, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(
                        "CardEventNet M9 review\n"
                        f"campaign: {review['campaign_id']}\n"
                        f"decision: {review['decision']['recommendation']}\n"
                        f"hard-negative candidates: "
                        f"{review['hard_negative_manifest']['candidate_count']}\n"
                        f"report: {review['report_path']}\n"
                    )
                return 0
            if args.model_command == "promote":
                campaign_root = (
                    args.campaign_root or config.repository_root / "data" / "model-campaigns"
                )
                if not campaign_root.is_absolute():
                    campaign_root = config.repository_root / campaign_root
                existing_campaign = load_campaign(campaign_root, args.campaign_id)
                if existing_campaign.component == "table-evidence-analyzer":
                    command_runner = (
                        TableEvidenceFixtureCommandRunner(test_quality=0.96)
                        if args.runner == "fixture"
                        else None
                    )
                    campaign = promote_table_evidence_campaign(
                        args.campaign_id,
                        repository_root=config.repository_root,
                        registry_path=args.model_registry,
                        campaign_root=args.campaign_root,
                        candidate_id=args.candidate_id,
                        project_root=args.project_root,
                        dataset_path=args.dataset,
                        split_path=args.split,
                        artifacts_path=args.artifacts,
                        runner=command_runner,
                        confirm=args.confirm,
                    )
                    label = "TableEvidenceAnalyzer promotion"
                else:
                    command_runner = FixtureCommandRunner() if args.runner == "fixture" else None
                    campaign = promote_card_event_campaign(
                        args.campaign_id,
                        repository_root=config.repository_root,
                        registry_path=args.model_registry,
                        campaign_root=args.campaign_root,
                        candidate_id=args.candidate_id,
                        project_root=args.project_root,
                        split_path=args.split,
                        cache_dir=args.cache_dir,
                        annotations_dir=args.annotations_dir,
                        device=args.device,
                        app_bundle_path=args.app_bundle,
                        runner=command_runner,
                        confirm=args.confirm,
                    )
                    label = "CardEventNet promotion"
                result = {
                    "campaign": campaign.to_mapping(),
                    "campaign_path": str(campaign_root / campaign.campaign_id),
                }
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(
                        f"{label}\n"
                        f"campaign: {campaign.campaign_id}\n"
                        f"state: {campaign.state}\n"
                        f"artifacts: {result['campaign_path']}\n"
                    )
                return 1 if campaign.state == "failed" else 0
            if args.model_command == "evaluate-system":
                runner = (
                    SystemHoldoutFixtureRunner(fail_boundary=args.fail_boundary)
                    if args.runner == "fixture"
                    else None
                )
                report = evaluate_system_holdout(
                    args.cardevent_campaign_id,
                    args.table_campaign_id,
                    repository_root=config.repository_root,
                    cardevent_dataset_path=args.cardevent_dataset,
                    cardevent_split_path=args.cardevent_split,
                    table_dataset_path=args.table_dataset,
                    table_split_path=args.table_split,
                    reconstruction_config_path=args.reconstruction_config,
                    holdout_registry_path=args.holdout_registry,
                    model_registry_path=args.model_registry,
                    campaign_root=args.campaign_root,
                    fixture_path=args.fixture,
                    evaluation_root=args.evaluation_root,
                    runner=runner,
                )
                result = {"report": report.to_mapping()}
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(
                        "System holdout evaluation\n"
                        f"evaluation: {report.evaluation_id}\n"
                        f"status: {report.status}\n"
                        f"recommendation: {report.recommendation}\n"
                    )
                return 1 if report.status == "failed" else 0
            if args.model_command == "status":
                result = model_status(
                    config.repository_root,
                    registry_path=args.model_registry,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(render_model_status_json(result))
                else:
                    sys.stdout.write(render_model_status_human(result))
                return 0 if result["valid"] else 1
            if args.model_command == "compare":
                campaign_root = (
                    args.campaign_root or config.repository_root / "data" / "model-campaigns"
                )
                if not campaign_root.is_absolute():
                    campaign_root = config.repository_root / campaign_root
                campaign = load_campaign(campaign_root, args.campaign_id)
                registry_path = (
                    args.model_registry or config.repository_root / "data" / "model-registry.json"
                )
                if not registry_path.is_absolute():
                    registry_path = config.repository_root / registry_path
                if registry_path.exists():
                    validate_campaign_against_registry(campaign, load_model_registry(registry_path))
                comparison = load_campaign_comparison(campaign_root, campaign)
                if args.json or args.format == "json":
                    sys.stdout.write(render_comparison_json(comparison))
                else:
                    sys.stdout.write(render_comparison_human(comparison))
                return 0
        except (
            ConfigurationError,
            OSError,
            ModelImprovementError,
            SystemHoldoutError,
            SystemHoldoutEvaluationError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    if args.command == "reconstruct":
        if args.reconstruct_command != "round":
            reconstruct_parser = next(
                action for action in parser._subparsers._group_actions if action.dest == "command"
            )
            reconstruct_parser.choices["reconstruct"].print_help()
            return 0
        try:
            artifacts = run_round_reconstruction(args.request)
        except (OSError, RoundReconstructionContractError, ValueError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        sys.stdout.write(
            f"artifact directory: {artifacts.directory}\nstatus: {artifacts.result.status}\n"
        )
        return 0
    try:
        config = RepositoryConfig.from_environment(
            args.repository_root,
            intake_root=args.intake_root,
            evidence_package_root=args.evidence_package_root,
            pending_video_root=args.pending_video_root,
            artifacts_root=args.artifacts_root,
        )
        result = inspect_repository(
            config.repository_root,
            bundle_root=config.bundle_root,
            evidence_package_root=config.evidence_package_intake_root,
            pending_video_root=config.pending_root,
            artifacts_root=config.derived_artifact_root,
        )
    except (ConfigurationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output_json = args.json or args.format == "json"
    if output_json:
        sys.stdout.write(
            render_json(
                result,
                repository_root=config.repository_root,
                bundle_root=config.bundle_root,
            )
        )
    else:
        sys.stdout.write(
            render_human(
                result,
                repository_root=config.repository_root,
                bundle_root=config.bundle_root,
            )
        )
    return 1 if args.data_command == "validate" and not result.valid else 0


def _render_impact_human(result: dict) -> str:
    reports = result.get("reports") if "reports" in result else [result]
    lines = ["DokoDetector source impact"]
    for report in reports:
        lines.append(
            f"source: {report['source_asset_id']} ({report['retention_state']}), "
            f"{sum(report['artifact_counts'].values())} affected artifacts"
        )
        for task in report["task_impacts"]:
            lines.append(f"  - {task['task']}: {task['impact_state']}")
        for artifact in report["affected_artifacts"]:
            lines.append(f"    - {artifact['kind']}: {artifact['path']}")
    return "\n".join(lines) + "\n"


__all__ = ["build_parser", "main"]
