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
from .cardevent_m10 import (
    CardEventM10Error,
    publish_cardeventnet_m10_timing_review,
    render_cardeventnet_m10_human,
)
from .cardevent_m11 import (
    CardEventM11Error,
    publish_cardeventnet_m11_timing_review,
    render_cardeventnet_m11_human,
)
from .cardevent_m12 import (
    CardEventM12Error,
    prepare_cardeventnet_m12_timing_response,
    render_cardeventnet_m12_human,
)
from .cardevent_m13 import (
    CardEventM13Error,
    compare_cardeventnet_m13_timing_candidate,
    render_cardeventnet_m13_human,
)
from .cardevent_m14 import (
    CardEventM14Error,
    prepare_cardeventnet_m14_integration_handoff,
    render_cardeventnet_m14_human,
)
from .cardevent_m15 import (
    CardEventM15Error,
    render_cardeventnet_m15_human,
    validate_cardeventnet_m15_integration,
)
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
from .dinov3_identity_campaign import (
    DinoV3IdentityCampaignError,
    DinoV3IdentityPreflightError,
    build_dinov3_identity_preflight,
    prepare_dinov3_identity_campaign,
    render_dinov3_identity_campaign_human,
    render_dinov3_identity_preflight_human,
    render_dinov3_identity_training_handoff_human,
    validate_dinov3_identity_training_handoff,
)
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
from .manual_proposed_card_scene_preflight import (
    ManualProposedCardScenePreflightError,
    preflight_manual_proposed_card_scene_runs,
    read_recording_ids,
    render_manual_proposed_card_scene_preflight,
)
from .manual_visible_card_detection import (
    ManualVisibleCardDetectionError,
    render_manual_visible_card_detection,
    run_manual_visible_card_detection,
)
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
from .reviewed_rfdetr_detector_campaign import (
    ReviewedRfdetrDetectorCampaignError,
    build_reviewed_rfdetr_detector_manifest,
    render_reviewed_rfdetr_detector_human,
    write_reviewed_rfdetr_detector_manifest,
)
from .rfdetr_cluster_crop_materialization import (
    RfdetrClusterCropMaterializationError,
    materialize_rfdetr_cluster_crop_dataset,
)
from .rfdetr_pose_derived_campaign import (
    RfdetrPoseDerivedCampaignError,
    build_rfdetr_pose_derived_manifest,
    render_rfdetr_pose_derived_manifest,
    write_rfdetr_pose_derived_manifest,
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
from .round_split import (
    RoundSplitError,
    RoundSplitMetadata,
    materialize_rounds,
    probe_videos,
    select_rounds,
    suggest_identifiers,
)
from .status import render_human, render_json
from .synthetic_visible_region_annotation_effort import (
    M4_REPORT_DEFAULT as SYNTHETIC_VISIBLE_REGION_M6_M4_REPORT_DEFAULT,
)
from .synthetic_visible_region_annotation_effort import (
    M5_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_M6_M5_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_annotation_effort import (
    M6_REPORT_DEFAULT as SYNTHETIC_VISIBLE_REGION_M6_REPORT_DEFAULT,
)
from .synthetic_visible_region_annotation_effort import (
    SOURCE_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_M6_SOURCE_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_annotation_effort import (
    SyntheticVisibleRegionAnnotationEffortError,
    build_synthetic_visible_region_m6_report,
    render_synthetic_visible_region_m6_human,
    write_synthetic_visible_region_m6_report,
)
from .synthetic_visible_region_campaign import (
    SyntheticVisibleRegionCampaignError,
    build_synthetic_visible_region_manifest,
    render_synthetic_visible_region_human,
    write_synthetic_visible_region_manifest,
)
from .synthetic_visible_region_empty_table_synthesis import (
    M1_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_M1_DEFAULT,
)
from .synthetic_visible_region_empty_table_synthesis import (
    MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_empty_table_synthesis import (
    MATERIALIZATION_DEFAULT as SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_MATERIALIZATION_DEFAULT,
)
from .synthetic_visible_region_empty_table_synthesis import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_empty_table_synthesis import (
    SCENE_LIMIT_DEFAULT as SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCENE_LIMIT_DEFAULT,
)
from .synthetic_visible_region_empty_table_synthesis import (
    SyntheticVisibleRegionEmptyTableError,
    build_synthetic_visible_region_empty_table_samples,
    render_synthetic_visible_region_empty_table_human,
    write_synthetic_visible_region_empty_table_manifest,
)
from .synthetic_visible_region_materialization import (
    M0_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_INPUTS_M0_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_INPUTS_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    MATERIALIZATION_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_MATERIALIZATION_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_INPUTS_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    SOURCE_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_INPUTS_SOURCE_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    TABLE_INPUT_SPEC_DEFAULT as SYNTHETIC_VISIBLE_REGION_TABLE_INPUT_SPEC_DEFAULT,
)
from .synthetic_visible_region_materialization import (
    SyntheticVisibleRegionMaterializationError,
    build_synthetic_visible_region_inputs,
    render_synthetic_visible_region_inputs_human,
    write_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_planar_geometry import (
    M1_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_M1_DEFAULT,
)
from .synthetic_visible_region_planar_geometry import (
    MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_planar_geometry import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_planar_geometry import (
    SAMPLE_COUNT_DEFAULT as SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SAMPLE_COUNT_DEFAULT,
)
from .synthetic_visible_region_planar_geometry import (
    SCANNED_DECK_SOURCE_DEFAULT as SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CARD_SOURCE_DEFAULT,
)
from .synthetic_visible_region_planar_geometry import (
    SyntheticVisibleRegionPlanarGeometryError,
    build_synthetic_visible_region_planar_geometry_samples,
    render_synthetic_visible_region_planar_geometry_human,
    write_synthetic_visible_region_planar_geometry_manifest,
)
from .synthetic_visible_region_recording_synthesis import (
    GEOMETRY_REFERENCE_FRAME_COUNT_DEFAULT,
    MAX_CARD_COUNT_DEFAULT,
    SYNTHESIS_CANDIDATE_POLICIES,
    SYNTHESIS_CANDIDATE_POLICY_DEFAULT,
    SYNTHESIS_VARIANTS_PER_CANDIDATE_DEFAULT,
    SyntheticVisibleRegionAllRecordingsError,
    build_synthetic_visible_region_all_recordings,
    render_synthetic_visible_region_all_recordings_human,
    write_synthetic_visible_region_all_recordings_manifest,
)
from .synthetic_visible_region_recording_synthesis import (
    M1_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_M1_DEFAULT,
)
from .synthetic_visible_region_recording_synthesis import (
    MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_recording_synthesis import (
    MATERIALIZATION_DEFAULT as SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_MATERIALIZATION_DEFAULT,
)
from .synthetic_visible_region_recording_synthesis import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_recording_synthesis import (
    SOURCE_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SOURCE_DEFAULT,
)
from .synthetic_visible_region_rendering import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_SCENES_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_rendering import (
    SCENE_COUNT_DEFAULT as SYNTHETIC_VISIBLE_REGION_SCENE_COUNT_DEFAULT,
)
from .synthetic_visible_region_rendering import (
    SyntheticVisibleRegionRenderingError,
    build_synthetic_visible_region_scenes,
    render_synthetic_visible_region_scenes_human,
    write_synthetic_visible_region_scenes,
)
from .synthetic_visible_region_training_comparison import (
    M0_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_M0_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    M4_OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    M4_REPORT_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_REPORT_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    PRETRAINED_CHECKPOINT_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_CHECKPOINT_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    REAL_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_REAL_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    REAL_MATERIALIZATION_DEFAULT as SYNTHETIC_VISIBLE_REGION_M4_REAL_MATERIALIZATION_DEFAULT,
)
from .synthetic_visible_region_training_comparison import (
    SyntheticVisibleRegionTrainingComparisonError,
    build_synthetic_visible_region_m4_view,
    render_synthetic_visible_region_m4_human,
    run_synthetic_visible_region_m4_comparison,
)
from .synthetic_visible_region_training_view import (
    M3_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_training_view import (
    OUTPUT_DIRECTORY_DEFAULT as SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_OUTPUT_DEFAULT,
)
from .synthetic_visible_region_training_view import (
    REAL_MATERIALIZATION_DEFAULT as SYNTHETIC_VISIBLE_REGION_REAL_MATERIALIZATION_DEFAULT,
)
from .synthetic_visible_region_training_view import (
    SCENE_MANIFEST_DEFAULT as SYNTHETIC_VISIBLE_REGION_SCENE_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_training_view import (
    SyntheticVisibleRegionTrainingViewError,
    build_synthetic_visible_region_training_view,
    render_synthetic_visible_region_training_view_human,
    write_synthetic_visible_region_training_view,
)
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
    dinov3 = data_commands.add_parser(
        "dinov3-identity-preflight",
        aliases=("identity-preflight",),
        help="Run the read-only M0 preflight for the first local DINOv3 identity campaign.",
        description=(
            "Discover current completed visual-card references, validate the selected split and "
            "local prerequisites, and report exact revisions without publishing campaign data."
        ),
    )
    _add_path_options(dinov3, suppress_defaults=True)
    dinov3.add_argument(
        "--operations-root", type=Path, default=None, help="Shared operations root."
    )
    dinov3.add_argument(
        "--split", type=Path, default=None, help="Selected visual-identity split or active pointer."
    )
    dinov3.add_argument(
        "--holdout-registry", type=Path, default=None, help="Shared system holdout registry."
    )
    dinov3.add_argument(
        "--identity-config", type=Path, default=None, help="Resolved local DINOv3 identity config."
    )
    dinov3.add_argument(
        "--license-record", type=Path, default=None, help="Pinned DINOv3 license record JSON."
    )
    dinov3.add_argument(
        "--weights-root", type=Path, default=None, help="Already-materialized local DINOv3 files."
    )
    dinov3.add_argument(
        "--verify-source-bytes",
        action="store_true",
        help="Hash selected source videos in addition to checking declared digests.",
    )
    dinov3.add_argument("--format", choices=("human", "json"), default="human")
    dinov3.add_argument("--json", action="store_true", help="Alias for --format json.")
    dinov3_prepare = data_commands.add_parser(
        "dinov3-identity-prepare",
        aliases=("identity-prepare",),
        help="Freeze and materialize the M1 local DINOv3 identity campaign.",
        description=(
            "Repeat the DINOv3 M0 preflight, freeze eligible reviewed references, reproduce "
            "verified PPM crops, and publish one immutable campaign directory."
        ),
    )
    _add_path_options(dinov3_prepare, suppress_defaults=True)
    dinov3_prepare.add_argument(
        "--operations-root", type=Path, default=None, help="Shared operations root."
    )
    dinov3_prepare.add_argument(
        "--split", type=Path, default=None, help="Selected visual-identity split or active pointer."
    )
    dinov3_prepare.add_argument(
        "--holdout-registry", type=Path, default=None, help="Shared system holdout registry."
    )
    dinov3_prepare.add_argument(
        "--identity-config", type=Path, default=None, help="Resolved local DINOv3 identity config."
    )
    dinov3_prepare.add_argument(
        "--license-record", type=Path, default=None, help="Pinned DINOv3 license record JSON."
    )
    dinov3_prepare.add_argument(
        "--weights-root", type=Path, default=None, help="Already-materialized local DINOv3 files."
    )
    dinov3_prepare.add_argument(
        "--verify-source-bytes",
        action="store_true",
        help="Hash selected source videos during the repeated M0 preflight.",
    )
    dinov3_prepare.add_argument("--format", choices=("human", "json"), default="human")
    dinov3_prepare.add_argument("--json", action="store_true", help="Alias for --format json.")
    dinov3_training = data_commands.add_parser(
        "dinov3-identity-train-preflight",
        aliases=("identity-train-preflight",),
        help="Run the short M2 DINOv3 training handoff check.",
        description=(
            "Verify one frozen M1 DINOv3 campaign and print the exact local operator command; "
            "this command never starts training."
        ),
    )
    _add_path_options(dinov3_training, suppress_defaults=True)
    dinov3_training.add_argument(
        "--campaign-manifest", type=Path, required=True, help="Frozen M1 campaign manifest."
    )
    dinov3_training.add_argument("--format", choices=("human", "json"), default="human")
    dinov3_training.add_argument("--json", action="store_true", help="Alias for --format json.")
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
    pose_derived = data_commands.add_parser(
        "rfdetr-pose-derived",
        help="Audit and freeze eligible proposed card scenes for epic 0084.",
        description=(
            "Audit exact 0083 proposal runs against the frozen 0068 split and write an immutable "
            "M0 campaign manifest. This command is read-only with respect to source data."
        ),
    )
    _add_path_options(pose_derived, suppress_defaults=True)
    pose_derived.add_argument(
        "--operations-root", type=Path, default=None, help="Shared operations root."
    )
    pose_derived.add_argument(
        "--source-manifest",
        type=Path,
        required=True,
        help="Frozen 0068 reviewed detector manifest.",
    )
    pose_derived.add_argument(
        "--run-inventory",
        type=Path,
        required=True,
        help="JSON object with the exact 0083 proposal_run_ids list.",
    )
    pose_derived.add_argument(
        "--output",
        type=Path,
        default=Path("data/operations/rfdetr-pose-derived-0084-m0-manifest.json"),
        help="Immutable M0 manifest path.",
    )
    pose_derived.add_argument("--format", choices=("human", "json"), default="human")
    pose_derived.add_argument("--json", action="store_true", help="Alias for --format json.")
    reviewed_rfdetr = data_commands.add_parser(
        "rfdetr-visible-card-detector",
        aliases=("rfdetr-detector", "rfdetr-segmentation-0068"),
        help="Audit and freeze the reviewed RF-DETR local visible-card detector input.",
        description="Audit and freeze the reviewed RF-DETR local visible-card detector input.",
    )
    _add_path_options(reviewed_rfdetr, suppress_defaults=True)
    reviewed_rfdetr.add_argument(
        "--operations-root",
        type=Path,
        default=None,
        help="Shared operations root (default: data/operations).",
    )
    reviewed_rfdetr.add_argument(
        "--holdout-registry",
        type=Path,
        default=None,
        help="Path to the shared system holdout registry.",
    )
    reviewed_rfdetr.add_argument(
        "--pretrained-checkpoint",
        type=Path,
        default=None,
        help="Explicit RF-DETR segmentation checkpoint to digest and pin.",
    )
    reviewed_rfdetr.add_argument("--device", choices=("mps", "cuda", "cpu"), default="mps")
    reviewed_rfdetr.add_argument(
        "--verify-source-bytes",
        action="store_true",
        help="Hash every selected source video in addition to checking declared digests.",
    )
    reviewed_rfdetr.add_argument(
        "--output",
        type=Path,
        default=Path("data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"),
        help=(
            "Immutable manifest path (default: "
            "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json)."
        ),
    )
    reviewed_rfdetr.add_argument("--format", choices=("human", "json"), default="human")
    reviewed_rfdetr.add_argument("--json", action="store_true", help="Alias for --format json.")
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
    reviewed_rfdetr_materialize = data_commands.add_parser(
        "rfdetr-visible-card-detector-materialize",
        aliases=("rfdetr-visible-card-detector-view",),
        help="Materialize a frozen reviewed RF-DETR visible-card COCO view.",
        description="Materialize a frozen reviewed RF-DETR visible-card COCO view.",
    )
    _add_path_options(reviewed_rfdetr_materialize, suppress_defaults=True)
    reviewed_rfdetr_materialize.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Frozen M0 reviewed RF-DETR detector manifest.",
    )
    reviewed_rfdetr_materialize.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/rfdetr-segmentation-0068"),
        help="Disposable train, validation, and sealed-test view directory.",
    )
    reviewed_rfdetr_materialize.add_argument("--format", choices=("human", "json"), default="human")
    reviewed_rfdetr_materialize.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    cluster_crop_materialize = data_commands.add_parser(
        "rfdetr-cluster-crop-materialize",
        aliases=("rfdetr-cluster-crop-view",),
        help="Materialize the validated M4 cluster-crop segmentation view.",
        description="Materialize the epic 0071 cluster-crop segmentation view.",
    )
    _add_path_options(cluster_crop_materialize, suppress_defaults=True)
    cluster_crop_materialize.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Frozen 0068 M0 manifest with 0072 card_scene envelopes.",
    )
    cluster_crop_materialize.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/rfdetr-cluster-crop-0071-m4"),
        help="Disposable train and validation COCO crop view directory.",
    )
    cluster_crop_materialize.add_argument(
        "--synthetic-view",
        type=Path,
        default=Path(".runtime/synthetic-visible-region-0070-m4-50-50/synthetic-candidate-view"),
        help="Frozen 0070 synthetic candidate view used for train rows.",
    )
    cluster_crop_materialize.add_argument(
        "--synthetic-manifest",
        type=Path,
        default=Path("data/operations/synthetic-visible-region-0070-m5-50-50-training-view.json"),
        help="Frozen 0070 training-view manifest used for scene receipts.",
    )
    cluster_crop_materialize.add_argument(
        "--without-synthetic",
        action="store_true",
        help="Materialize real reviewed rows only; intended for focused local fixtures.",
    )
    cluster_crop_materialize.add_argument("--format", choices=("human", "json"), default="human")
    cluster_crop_materialize.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region = data_commands.add_parser(
        "synthetic-visible-region",
        aliases=("synthetic-rfdetr",),
        help="Audit and freeze the epic 0070 synthetic visible-region experiment input.",
        description="Audit and freeze the epic 0070 synthetic visible-region experiment input.",
    )
    _add_path_options(synthetic_visible_region, suppress_defaults=True)
    synthetic_visible_region.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Frozen 0068 reviewed-detector M0 manifest.",
    )
    synthetic_visible_region.add_argument(
        "--materialization",
        type=Path,
        default=None,
        help="0068 materialization directory or materialization.json path.",
    )
    synthetic_visible_region.add_argument(
        "--detector-bundle",
        type=Path,
        default=None,
        help="0068 local RF-DETR detector bundle directory.",
    )
    synthetic_visible_region.add_argument(
        "--validation-report",
        type=Path,
        default=None,
        help="0068 locked validation report.",
    )
    synthetic_visible_region.add_argument(
        "--output",
        type=Path,
        default=Path("data/operations/synthetic-visible-region-0070-m0-manifest.json"),
        help=(
            "Immutable manifest path (default: "
            "data/operations/synthetic-visible-region-0070-m0-manifest.json)."
        ),
    )
    synthetic_visible_region.add_argument("--format", choices=("human", "json"), default="human")
    synthetic_visible_region.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_materialize = data_commands.add_parser(
        "synthetic-visible-region-materialize",
        aliases=("synthetic-rfdetr-materialize",),
        help="Materialize training-only card cutouts for epic 0070 M1.",
        description="Materialize training-only card cutouts for epic 0070 M1.",
    )
    _add_path_options(synthetic_visible_region_materialize, suppress_defaults=True)
    synthetic_visible_region_materialize.add_argument(
        "--source-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_SOURCE_DEFAULT),
        help="Directory containing operator-supplied JPEG grids and individual HEIC cards.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_OUTPUT_DEFAULT),
        help="Disposable directory for canonical cutouts and alpha masks.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--m0-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_M0_MANIFEST_DEFAULT),
        help="Existing epic 0070 M0 manifest to link as the base experiment receipt.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--materialization-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_MATERIALIZATION_DEFAULT),
        help="0068 materialization directory containing reviewed training frames.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--table-input-spec",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_TABLE_INPUT_SPEC_DEFAULT),
        help="Operator-reviewed card and empty-background link manifest.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_MANIFEST_DEFAULT),
        help="Immutable M1 input manifest path.",
    )
    synthetic_visible_region_materialize.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_materialize.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_render = data_commands.add_parser(
        "synthetic-visible-region-render",
        aliases=("synthetic-rfdetr-render",),
        help="Render deterministic training-only scenes for epic 0070 M2.",
        description="Render deterministic training-only scenes for epic 0070 M2.",
    )
    _add_path_options(synthetic_visible_region_render, suppress_defaults=True)
    synthetic_visible_region_render.add_argument(
        "--m1-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_MANIFEST_DEFAULT),
        help="M1 input manifest containing training-only cutouts and backgrounds.",
    )
    synthetic_visible_region_render.add_argument(
        "--m0-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_M0_MANIFEST_DEFAULT),
        help="Frozen epic 0070 M0 recipe manifest.",
    )
    synthetic_visible_region_render.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_SCENES_OUTPUT_DEFAULT),
        help="Disposable directory for rendered scenes, masks, COCO, and receipts.",
    )
    synthetic_visible_region_render.add_argument(
        "--scene-count",
        type=int,
        default=SYNTHETIC_VISIBLE_REGION_SCENE_COUNT_DEFAULT,
        help="Number of available scene buckets to render.",
    )
    synthetic_visible_region_render.add_argument(
        "--output",
        type=Path,
        default=Path("data/operations/synthetic-visible-region-0070-m2-scenes.json"),
        help="Immutable M2 scene manifest path.",
    )
    synthetic_visible_region_render.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_render.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_training_view = data_commands.add_parser(
        "synthetic-visible-region-training-view",
        aliases=("synthetic-rfdetr-training-view",),
        help="Materialize and inspect the disposable epic 0070 M3 training view.",
        description="Materialize and inspect the disposable epic 0070 M3 training view.",
    )
    _add_path_options(synthetic_visible_region_training_view, suppress_defaults=True)
    synthetic_visible_region_training_view.add_argument(
        "--m0-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_M0_MANIFEST_DEFAULT),
        help="Frozen epic 0070 M0 recipe manifest.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--m1-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_INPUTS_MANIFEST_DEFAULT),
        help="M1 input manifest containing training-only cutouts and backgrounds.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--scene-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_SCENE_MANIFEST_DEFAULT),
        help="M2 scene manifest. The view is regenerated when this file is absent.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--materialization-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_REAL_MATERIALIZATION_DEFAULT),
        help="0068 materialization directory containing the real trainer view.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_OUTPUT_DEFAULT),
        help="Disposable merged COCO training view and inspection artifacts.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--operator-decision",
        choices=("approved", "rejected"),
        default="approved",
        help="Record the operator inspection decision before any later training run.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--operator-name",
        default="codex-visual-inspection",
        help="Operator name retained in the inspection receipt.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_MANIFEST_DEFAULT),
        help="Immutable M3 training-view manifest path.",
    )
    synthetic_visible_region_training_view.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_training_view.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_all_recordings = data_commands.add_parser(
        "synthetic-visible-region-all-recordings",
        aliases=("synthetic-rfdetr-all-recordings",),
        help="Find 1/2/3-card table geometry in all recordings and synthesize train scenes.",
        description=(
            "Audit human-reference 1/2/3-card table geometry across all recordings, "
            "then synthesize train-only scenes."
        ),
    )
    _add_path_options(synthetic_visible_region_all_recordings, suppress_defaults=True)
    synthetic_visible_region_all_recordings.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SOURCE_DEFAULT),
        help="Frozen 0068 reviewed-detector M0 manifest.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--m1-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_M1_DEFAULT),
        help="Training-only 0070 M1 cutout manifest.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--materialization-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_MATERIALIZATION_DEFAULT),
        help="0068 materialized source frames.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_OUTPUT_DEFAULT),
        help="Disposable train-only synthetic scene directory.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_MANIFEST_DEFAULT),
        help="Immutable discovery and synthesis manifest.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--discover-only",
        action="store_true",
        help="Audit all recordings without writing synthetic images.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--candidate-policy",
        choices=SYNTHESIS_CANDIDATE_POLICIES,
        default=SYNTHESIS_CANDIDATE_POLICY_DEFAULT,
        help="Choose one selected geometry per recording or every train geometry candidate.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--variants-per-candidate",
        type=int,
        default=SYNTHESIS_VARIANTS_PER_CANDIDATE_DEFAULT,
        help="Render this many deterministic card-asset and photometric variants per candidate.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--max-card-count",
        type=int,
        default=MAX_CARD_COUNT_DEFAULT,
        help="Include corrected geometry frames with up to this many cards (maximum: 4).",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--geometry-reference-frame-count",
        type=int,
        default=GEOMETRY_REFERENCE_FRAME_COUNT_DEFAULT,
        help="Use this many train-only frames to estimate each table setup's card geometry.",
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_all_recordings.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_empty_table = data_commands.add_parser(
        "synthetic-visible-region-empty-table",
        aliases=("synthetic-rfdetr-empty-table",),
        help="Render bounded samples on explicitly reviewed empty training tables.",
        description=(
            "White-balance training card cutouts, transfer shared lighting from known cards, "
            "and render a bounded sample set on reviewed empty tables only."
        ),
    )
    _add_path_options(synthetic_visible_region_empty_table, suppress_defaults=True)
    synthetic_visible_region_empty_table.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SOURCE_DEFAULT),
        help="Frozen 0068 reviewed-detector M0 manifest.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--m1-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_M1_DEFAULT),
        help="Training-only 0070 M1 cutout and reviewed-empty-table manifest.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--materialization-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_MATERIALIZATION_DEFAULT),
        help="0068 materialized source frames used for lighting references.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_OUTPUT_DEFAULT),
        help="Disposable sample output directory.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_MANIFEST_DEFAULT),
        help="Immutable sample manifest path.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--scene-limit",
        type=int,
        default=SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCENE_LIMIT_DEFAULT,
        help="Maximum sample scenes; use 0 only after operator approval for the full pool.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--variants-per-candidate",
        type=int,
        default=1,
        help="Number of deterministic scene-level lighting variants per geometry candidate.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--max-card-count",
        type=int,
        default=MAX_CARD_COUNT_DEFAULT,
        help="Include corrected geometry frames with up to this many cards (maximum: 4).",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--seed-start",
        type=int,
        default=7001,
        help="Seed for the first scene-level lighting condition.",
    )
    synthetic_visible_region_empty_table.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_empty_table.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_planar_geometry = data_commands.add_parser(
        "synthetic-visible-region-planar-geometry",
        aliases=("synthetic-rfdetr-planar-geometry",),
        help="Calibrate reviewed table planes and render deterministic appearance-review samples.",
        description=(
            "Fit a stable table-plane homography from several reviewed card rectangles in each "
            "selected recording, then render deterministic appearance-review layouts into an "
            "explicit reviewed empty table frame."
        ),
    )
    _add_path_options(synthetic_visible_region_planar_geometry, suppress_defaults=True)
    synthetic_visible_region_planar_geometry.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SOURCE_DEFAULT),
        help="Frozen 0068 reviewed-detector M0 manifest.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--m1-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_M1_DEFAULT),
        help="Training-only M1 cutout and reviewed-empty-table manifest.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--card-source-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CARD_SOURCE_DEFAULT),
        help="Upright scanned card faces used in every rendered geometry sample.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_OUTPUT_DEFAULT),
        help="Disposable geometry-review sample directory.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_MANIFEST_DEFAULT),
        help="Immutable geometry-review manifest path.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--recording-id",
        action="append",
        default=None,
        help="Use one explicitly reviewed empty-table recording. Repeat to select several.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--sample-count",
        type=int,
        default=SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SAMPLE_COUNT_DEFAULT,
        help="Render one to 2000 deterministic geometry scenes.",
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    synthetic_visible_region_planar_geometry.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_m4 = data_commands.add_parser(
        "synthetic-visible-region-training-comparison",
        aliases=("synthetic-rfdetr-training-comparison",),
        help="Run the bounded epic 0070 M4 RF-DETR comparison.",
        description="Train the frozen real-only and real-plus-synthetic RF-DETR candidates.",
    )
    _add_path_options(synthetic_visible_region_m4, suppress_defaults=True)
    synthetic_visible_region_m4.add_argument(
        "--m0-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_M0_MANIFEST_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--real-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_REAL_MANIFEST_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--m3-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_MANIFEST_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--real-materialization",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_REAL_MATERIALIZATION_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--m3-output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_OUTPUT_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--pretrained-checkpoint",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_CHECKPOINT_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--output-directory",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_OUTPUT_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M4_REPORT_DEFAULT),
    )
    synthetic_visible_region_m4.add_argument(
        "--runner", choices=("rfdetr", "fixture"), default="rfdetr"
    )
    synthetic_visible_region_m4.add_argument(
        "--device", choices=("mps", "cuda", "cpu"), default="mps"
    )
    synthetic_visible_region_m4.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate and materialize the paired view without starting model training.",
    )
    synthetic_visible_region_m4.add_argument("--format", choices=("human", "json"), default="human")
    synthetic_visible_region_m4.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
    synthetic_visible_region_m6 = data_commands.add_parser(
        "synthetic-visible-region-annotation-effort",
        aliases=("synthetic-rfdetr-annotation-effort",),
        help="Audit the epic 0070 M6 annotation-effort pilot boundary.",
        description=(
            "Freeze legal development source groups for the annotation-effort pilot and "
            "publish the M6 decision without reusing held-out frames."
        ),
    )
    _add_path_options(synthetic_visible_region_m6, suppress_defaults=True)
    synthetic_visible_region_m6.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M6_SOURCE_MANIFEST_DEFAULT),
        help="Frozen 0068 reviewed-detector M0 manifest.",
    )
    synthetic_visible_region_m6.add_argument(
        "--m5-manifest",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M6_M5_MANIFEST_DEFAULT),
        help="M5 all-recordings audit manifest.",
    )
    synthetic_visible_region_m6.add_argument(
        "--m4-report",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M6_M4_REPORT_DEFAULT),
        help="Completed M4 paired comparison report.",
    )
    synthetic_visible_region_m6.add_argument(
        "--output",
        type=Path,
        default=Path(SYNTHETIC_VISIBLE_REGION_M6_REPORT_DEFAULT),
        help="Immutable M6 annotation-effort report.",
    )
    synthetic_visible_region_m6.add_argument("--format", choices=("human", "json"), default="human")
    synthetic_visible_region_m6.add_argument(
        "--json", action="store_true", help="Alias for --format json."
    )
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
    split_rounds = data_commands.add_parser(
        "split-rounds",
        help="Review long videos and publish one recording bundle per round.",
        description="Review long videos and publish one recording bundle per round.",
    )
    _add_path_options(split_rounds, suppress_defaults=True)
    split_rounds.add_argument("--operator", required=True)
    split_rounds.add_argument(
        "--session-id",
        default=None,
        help="Override the date-based session ID suggested from the first video.",
    )
    split_rounds.add_argument(
        "--game-id",
        default=None,
        help="Override the date-based game ID suggested from the first video.",
    )
    split_rounds.add_argument("--recording-prefix", default=None)
    split_rounds.add_argument("--round-id-prefix", default="round")
    split_rounds.add_argument("--table-setup", default=None)
    split_rounds.add_argument("--notes", default=None)
    split_rounds.add_argument(
        "--ffmpeg", default="ffmpeg", help="ffmpeg executable (default: ffmpeg)."
    )
    split_rounds.add_argument(
        "--window-name", default="DokoDetector round splitter", help="OpenCV window title."
    )
    split_rounds.add_argument(
        "videos", nargs="+", type=Path, help="Input videos in timeline order."
    )
    split_rounds.add_argument("--format", choices=("human", "json"), default="human")
    split_rounds.add_argument("--json", action="store_true", help="Alias for --format json.")
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
    timing_review = model_commands.add_parser(
        "review-card-event-net-timing",
        help="Publish the read-only CardEventNet M10 timing-review handoff.",
    )
    _add_path_options(timing_review, suppress_defaults=True)
    _add_model_options(timing_review)
    timing_review.add_argument("campaign_id")
    m11_review = model_commands.add_parser(
        "review-card-event-net-m11",
        help="Reconcile the M10 review and replay the CardEventNet decoder on validation.",
    )
    _add_path_options(m11_review, suppress_defaults=True)
    _add_model_options(m11_review)
    m11_review.add_argument("campaign_id")
    m12_prepare = model_commands.add_parser(
        "prepare-card-event-net-m12",
        help="Prepare the CardEventNet M12 timing-response handoff without training.",
    )
    _add_path_options(m12_prepare, suppress_defaults=True)
    _add_model_options(m12_prepare)
    m12_prepare.add_argument("campaign_id")
    m13_compare = model_commands.add_parser(
        "compare-card-event-net-m13",
        help="Compare and lock the completed CardEventNet M12 timing candidate.",
    )
    _add_path_options(m13_compare, suppress_defaults=True)
    _add_model_options(m13_compare)
    m13_compare.add_argument("campaign_id")
    m14_prepare = model_commands.add_parser(
        "prepare-card-event-net-m14",
        help="Lock the M9 development baseline and prepare M14 operator handoffs.",
    )
    _add_path_options(m14_prepare, suppress_defaults=True)
    _add_model_options(m14_prepare)
    m14_prepare.add_argument("campaign_id")
    m15_close = model_commands.add_parser(
        "close-card-event-net-m15",
        help="Validate M14 outputs and close the CardEventNet campaign.",
    )
    _add_path_options(m15_close, suppress_defaults=True)
    _add_model_options(m15_close)
    m15_close.add_argument("campaign_id")
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
    pipeline = commands.add_parser(
        "pipeline",
        help="Run backend pipeline operations.",
        description="Run backend pipeline operations.",
    )
    pipeline_commands = pipeline.add_subparsers(dest="pipeline_command", metavar="COMMAND")
    proposal_preflight = pipeline_commands.add_parser(
        "proposed-card-scenes-preflight",
        help="Check prerequisites for a manual RF-DETR proposed-card-scene batch.",
        description=(
            "Check the complete recording list, selected event revisions, backend readiness, "
            "and local RF-DETR provider without starting processor runs."
        ),
    )
    proposal_preflight.add_argument("--recordings", type=Path, required=True)
    proposal_preflight.add_argument(
        "--backend-url", default="http://127.0.0.1:8000", help="Local backend base URL."
    )
    proposal_preflight.add_argument("--timeout", type=float, default=15.0)
    proposal_preflight.add_argument("--format", choices=("human", "json"), default="human")
    visible_cards = pipeline_commands.add_parser(
        "proposed-card-scenes-visible-cards",
        help="Run local RF-DETR visible-card detection for a recording batch.",
        description=(
            "Preflight the complete recording list, then start and poll one durable "
            "local RF-DETR visible-card run for each recording."
        ),
    )
    visible_cards.add_argument("--recordings", type=Path, required=True)
    visible_cards.add_argument(
        "--backend-url", default="http://127.0.0.1:8000", help="Local backend base URL."
    )
    visible_cards.add_argument("--timeout", type=float, default=30.0)
    visible_cards.add_argument("--run-timeout", type=float, default=3600.0)
    visible_cards.add_argument("--poll-interval", type=float, default=2.0)
    visible_cards.add_argument("--format", choices=("human", "json"), default="human")
    scene_proposals = pipeline_commands.add_parser(
        "proposed-card-scenes-generate",
        help="Run proposed-card-scene generation for selected RF-DETR results.",
        description=(
            "Check every selected generated local RF-DETR result, then start and poll one "
            "proposed-card-scene run per recording."
        ),
    )
    scene_proposals.add_argument("--recordings", type=Path, required=True)
    scene_proposals.add_argument(
        "--backend-url", default="http://127.0.0.1:8000", help="Local backend base URL."
    )
    scene_proposals.add_argument("--timeout", type=float, default=30.0)
    scene_proposals.add_argument("--run-timeout", type=float, default=3600.0)
    scene_proposals.add_argument("--poll-interval", type=float, default=2.0)
    scene_proposals.add_argument("--format", choices=("human", "json"), default="human")
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


def _format_seconds(value: float) -> str:
    return f"{value:.3f}s"


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
    if args.command == "pipeline":
        if args.pipeline_command is None:
            pipeline_parser = next(
                action for action in parser._subparsers._group_actions if action.dest == "command"
            ).choices["pipeline"]
            pipeline_parser.print_help()
            return 0
        try:
            recording_ids = read_recording_ids(args.recordings)
            if args.pipeline_command == "proposed-card-scenes-preflight":
                report = preflight_manual_proposed_card_scene_runs(
                    recording_ids,
                    base_url=args.backend_url,
                    timeout_seconds=args.timeout,
                )
                renderer = render_manual_proposed_card_scene_preflight
            elif args.pipeline_command == "proposed-card-scenes-visible-cards":
                report = run_manual_visible_card_detection(
                    recording_ids,
                    base_url=args.backend_url,
                    request_timeout_seconds=args.timeout,
                    run_timeout_seconds=args.run_timeout,
                    poll_interval_seconds=args.poll_interval,
                )
                renderer = render_manual_visible_card_detection
            else:
                from .manual_proposed_card_scene_generation import (
                    render_manual_proposed_card_scene_generation,
                    run_manual_proposed_card_scene_generation,
                )

                report = run_manual_proposed_card_scene_generation(
                    recording_ids,
                    base_url=args.backend_url,
                    request_timeout_seconds=args.timeout,
                    run_timeout_seconds=args.run_timeout,
                    poll_interval_seconds=args.poll_interval,
                )
                renderer = render_manual_proposed_card_scene_generation
        except ManualProposedCardScenePreflightError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        except ManualVisibleCardDetectionError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.format == "json":
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(renderer(report) + "\n")
        return 0 if report["ready"] else 1
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
        "dinov3-identity-preflight",
        "identity-preflight",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                artifacts_root=args.artifacts_root,
            )
            report = build_dinov3_identity_preflight(
                config.repository_root,
                operations_root=args.operations_root or config.derived_artifact_root,
                intake_root=config.bundle_root,
                split_path=args.split,
                holdout_registry_path=args.holdout_registry,
                identity_config_path=args.identity_config,
                license_record_path=args.license_record,
                weights_root=args.weights_root,
                verify_source_bytes=args.verify_source_bytes,
            )
        except (ConfigurationError, OSError, DinoV3IdentityPreflightError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            sys.stdout.write(render_dinov3_identity_preflight_human(report))
        return 0 if report["preflight_state"] == "ready" else 1
    if args.command == "data" and args.data_command in {
        "dinov3-identity-prepare",
        "identity-prepare",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                artifacts_root=args.artifacts_root,
            )
            result = prepare_dinov3_identity_campaign(
                config.repository_root,
                operations_root=args.operations_root or config.derived_artifact_root,
                intake_root=config.bundle_root,
                split_path=args.split,
                holdout_registry_path=args.holdout_registry,
                identity_config_path=args.identity_config,
                license_record_path=args.license_record,
                weights_root=args.weights_root,
                verify_source_bytes=args.verify_source_bytes,
            )
        except (
            ConfigurationError,
            OSError,
            DinoV3IdentityPreflightError,
            DinoV3IdentityCampaignError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            sys.stdout.write(render_dinov3_identity_campaign_human(result))
        return 0 if result["state"] == "completed" else 1
    if args.command == "data" and args.data_command in {
        "dinov3-identity-train-preflight",
        "identity-train-preflight",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                artifacts_root=args.artifacts_root,
            )
            result = validate_dinov3_identity_training_handoff(
                config.repository_root, args.campaign_manifest
            )
        except (
            DinoV3IdentityCampaignError,
            DinoV3IdentityPreflightError,
            OSError,
            ValueError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            sys.stdout.write(render_dinov3_identity_training_handoff_human(result))
        return 0 if result["state"] in {"ready", "completed"} else 1
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
        "rfdetr-visible-card-detector",
        "rfdetr-detector",
        "rfdetr-segmentation-0068",
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
            manifest = build_reviewed_rfdetr_detector_manifest(
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
                write_reviewed_rfdetr_detector_manifest(output_path, manifest)
        except (ConfigurationError, OSError, ReviewedRfdetrDetectorCampaignError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_reviewed_rfdetr_detector_human(manifest))
        return 0 if manifest["freeze_state"] == "frozen" else 1
    if args.command == "data" and args.data_command == "rfdetr-pose-derived":
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            inventory_path = args.run_inventory
            if not inventory_path.is_absolute():
                inventory_path = config.repository_root / inventory_path
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            if not isinstance(inventory, dict) or not isinstance(
                inventory.get("proposal_run_ids"), list
            ):
                raise RfdetrPoseDerivedCampaignError(
                    "run inventory must contain a proposal_run_ids list"
                )
            source_manifest_path = args.source_manifest
            if not source_manifest_path.is_absolute():
                source_manifest_path = config.repository_root / source_manifest_path
            operations_root = args.operations_root or config.derived_artifact_root
            manifest = build_rfdetr_pose_derived_manifest(
                config.repository_root,
                source_manifest_path=source_manifest_path,
                operations_root=operations_root,
                proposal_run_ids=inventory["proposal_run_ids"],
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_rfdetr_pose_derived_manifest(output_path, manifest)
        except (
            ConfigurationError,
            OSError,
            json.JSONDecodeError,
            RfdetrPoseDerivedCampaignError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_rfdetr_pose_derived_manifest(manifest) + "\n")
        return 0 if manifest["freeze_state"] == "frozen" else 1
    if args.command == "data" and args.data_command in {
        "rfdetr-segmentation-materialize",
        "rfdetr-segmentation-view",
        "rfdetr-visible-card-detector-materialize",
        "rfdetr-visible-card-detector-view",
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
    if args.command == "data" and args.data_command in {
        "rfdetr-cluster-crop-materialize",
        "rfdetr-cluster-crop-view",
    }:
        try:
            config = RepositoryConfig.from_environment(getattr(args, "repository_root", None))
            manifest_path = args.manifest
            if not manifest_path.is_absolute():
                manifest_path = config.repository_root / manifest_path
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            synthetic_view = args.synthetic_view
            if not synthetic_view.is_absolute():
                synthetic_view = config.repository_root / synthetic_view
            synthetic_manifest = args.synthetic_manifest
            if not synthetic_manifest.is_absolute():
                synthetic_manifest = config.repository_root / synthetic_manifest
            result = materialize_rfdetr_cluster_crop_dataset(
                manifest_path,
                repository_root=config.repository_root,
                output_root=output_path,
                synthetic_view_root=synthetic_view,
                synthetic_manifest_path=synthetic_manifest,
                include_synthetic=not args.without_synthetic,
            )
        except (ConfigurationError, OSError, RfdetrClusterCropMaterializationError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                "RF-DETR cluster-crop segmentation view materialized\n"
                f"view: {result.view_root}\n"
                f"real crops: {result.real_crop_count}\n"
                f"synthetic crops: {result.synthetic_crop_count}\n"
                f"annotations: {result.annotation_count}\n"
                f"manifest: {result.materialization_digest}\n"
            )
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region",
        "synthetic-rfdetr",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_manifest(
                config.repository_root,
                source_manifest_path=args.source_manifest,
                materialization_path=args.materialization,
                detector_bundle_path=args.detector_bundle,
                validation_report_path=args.validation_report,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_manifest(output_path, manifest)
        except (ConfigurationError, OSError, SyntheticVisibleRegionCampaignError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_human(manifest))
        return 0 if manifest["freeze_state"] == "frozen" else 1
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-materialize",
        "synthetic-rfdetr-materialize",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_inputs(
                config.repository_root,
                source_directory=args.source_directory,
                output_directory=args.output_directory,
                m0_manifest_path=args.m0_manifest,
                materialization_directory=args.materialization_directory,
                table_input_spec=args.table_input_spec,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_inputs(output_path, manifest)
        except (ConfigurationError, OSError, SyntheticVisibleRegionMaterializationError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_inputs_human(manifest))
        return 0 if manifest["freeze_state"] == "ready" else 1
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-render",
        "synthetic-rfdetr-render",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_scenes(
                config.repository_root,
                m1_manifest_path=args.m1_manifest,
                m0_manifest_path=args.m0_manifest,
                output_directory=args.output_directory,
                scene_count=args.scene_count,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_scenes(output_path, manifest)
        except (ConfigurationError, OSError, SyntheticVisibleRegionRenderingError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_scenes_human(manifest))
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-training-view",
        "synthetic-rfdetr-training-view",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_training_view(
                config.repository_root,
                m0_manifest_path=args.m0_manifest,
                m1_manifest_path=args.m1_manifest,
                scene_manifest_path=args.scene_manifest,
                materialization_root=args.materialization_directory,
                output_directory=args.output_directory,
                operator_decision=args.operator_decision,
                operator_name=args.operator_name,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_training_view(output_path, manifest)
        except (ConfigurationError, OSError, SyntheticVisibleRegionTrainingViewError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_training_view_human(manifest))
        return 0 if manifest["operator_approval"]["status"] == "approved" else 1
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-all-recordings",
        "synthetic-rfdetr-all-recordings",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_all_recordings(
                config.repository_root,
                source_manifest_path=args.source_manifest,
                m1_manifest_path=args.m1_manifest,
                materialization_directory=args.materialization_directory,
                output_directory=args.output_directory,
                discover_only=args.discover_only,
                candidate_policy=args.candidate_policy,
                variants_per_candidate=args.variants_per_candidate,
                max_card_count=args.max_card_count,
                geometry_reference_frame_count=args.geometry_reference_frame_count,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_all_recordings_manifest(output_path, manifest)
        except (
            ConfigurationError,
            OSError,
            SyntheticVisibleRegionAllRecordingsError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_all_recordings_human(manifest))
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-empty-table",
        "synthetic-rfdetr-empty-table",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_empty_table_samples(
                config.repository_root,
                source_manifest_path=args.source_manifest,
                m1_manifest_path=args.m1_manifest,
                materialization_directory=args.materialization_directory,
                output_directory=args.output_directory,
                scene_limit=args.scene_limit,
                variants_per_candidate=args.variants_per_candidate,
                max_card_count=args.max_card_count,
                seed_start=args.seed_start,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_empty_table_manifest(output_path, manifest)
        except (
            ConfigurationError,
            OSError,
            SyntheticVisibleRegionEmptyTableError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_empty_table_human(manifest))
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-planar-geometry",
        "synthetic-rfdetr-planar-geometry",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            manifest = build_synthetic_visible_region_planar_geometry_samples(
                config.repository_root,
                source_manifest_path=args.source_manifest,
                m1_manifest_path=args.m1_manifest,
                card_source_directory=args.card_source_directory,
                output_directory=args.output_directory,
                sample_count=args.sample_count,
                recording_ids=args.recording_id,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_planar_geometry_manifest(output_path, manifest)
        except (
            ConfigurationError,
            OSError,
            SyntheticVisibleRegionPlanarGeometryError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_planar_geometry_human(manifest))
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-training-comparison",
        "synthetic-rfdetr-training-comparison",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            if args.preflight_only:
                view = build_synthetic_visible_region_m4_view(
                    config.repository_root,
                    m0_manifest_path=args.m0_manifest,
                    real_manifest_path=args.real_manifest,
                    m3_manifest_path=args.m3_manifest,
                    real_materialization=args.real_materialization,
                    m3_output_directory=args.m3_output_directory,
                    pretrained_checkpoint=args.pretrained_checkpoint,
                    output_directory=args.output_directory,
                )
                report = {
                    "schema_version": "synthetic-visible-region-training-comparison-preflight/v1",
                    "status": "preflight_ready",
                    "candidate_view": str(view["root"]),
                    "materialization_digest": view["materialization"]["materialization_digest"],
                    "facts": view["facts"],
                }
            else:
                report = run_synthetic_visible_region_m4_comparison(
                    config.repository_root,
                    m0_manifest_path=args.m0_manifest,
                    real_manifest_path=args.real_manifest,
                    m3_manifest_path=args.m3_manifest,
                    real_materialization=args.real_materialization,
                    m3_output_directory=args.m3_output_directory,
                    pretrained_checkpoint=args.pretrained_checkpoint,
                    output_directory=args.output_directory,
                    report_path=args.output,
                    runner=args.runner,
                    device=args.device,
                )
        except (
            ConfigurationError,
            OSError,
            SyntheticVisibleRegionTrainingComparisonError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        elif args.preflight_only:
            sys.stdout.write(
                "M4 preflight ready\n"
                f"candidate view: {report['candidate_view']}\n"
                f"materialization digest: {report['materialization_digest']}\n"
            )
        else:
            sys.stdout.write(render_synthetic_visible_region_m4_human(report))
        return 0
    if args.command == "data" and args.data_command in {
        "synthetic-visible-region-annotation-effort",
        "synthetic-rfdetr-annotation-effort",
    }:
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            report = build_synthetic_visible_region_m6_report(
                config.repository_root,
                source_manifest_path=args.source_manifest,
                m5_manifest_path=args.m5_manifest,
                m4_report_path=args.m4_report,
            )
            output_path = args.output
            if not output_path.is_absolute():
                output_path = config.repository_root / output_path
            write_synthetic_visible_region_m6_report(output_path, report)
        except (
            ConfigurationError,
            OSError,
            SyntheticVisibleRegionAnnotationEffortError,
        ) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json or args.format == "json":
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_synthetic_visible_region_m6_human(report))
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
    if args.command == "data" and args.data_command == "split-rounds":
        try:
            config = RepositoryConfig.from_environment(
                args.repository_root,
                intake_root=args.intake_root,
                evidence_package_root=args.evidence_package_root,
                pending_video_root=args.pending_video_root,
                artifacts_root=args.artifacts_root,
            )
            videos = probe_videos(args.videos)
            suggested_session_id, suggested_game_id = suggest_identifiers(args.videos)
            metadata = RoundSplitMetadata(
                operator=args.operator,
                session_id=args.session_id or suggested_session_id,
                game_id=args.game_id or suggested_game_id,
                recording_prefix=args.recording_prefix,
                round_id_prefix=args.round_id_prefix,
                table_setup=args.table_setup,
                notes=args.notes,
            )
            boundaries = select_rounds(videos, window_name=args.window_name)
            result = materialize_rounds(
                config.repository_root,
                videos,
                boundaries,
                metadata,
                intake_root=config.intake_root,
                ffmpeg_binary=args.ffmpeg,
            )
        except (ConfigurationError, OSError, RoundSplitError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        output = {
            "state": "complete",
            "session_id": metadata.session_id,
            "game_id": metadata.game_id,
            "rounds": [item.to_mapping(config.repository_root) for item in result],
        }
        if args.json or args.format == "json":
            sys.stdout.write(
                json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        else:
            sys.stdout.write(
                f"Published {len(result)} recording bundle(s)\n"
                f"session: {metadata.session_id}\n"
                f"game: {metadata.game_id}\n"
            )
            for item in result:
                mapping = item.to_mapping(config.repository_root)
                sys.stdout.write(
                    f"{item.round_id}: {mapping['bundle_path']} "
                    f"({_format_seconds(item.start_seconds)} - "
                    f"{_format_seconds(item.end_seconds)})\n"
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
            if args.model_command == "review-card-event-net-timing":
                packet = publish_cardeventnet_m10_timing_review(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(packet, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m10_human(packet))
                return 0
            if args.model_command == "review-card-event-net-m11":
                result = publish_cardeventnet_m11_timing_review(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m11_human(result))
                return 0
            if args.model_command == "prepare-card-event-net-m12":
                result = prepare_cardeventnet_m12_timing_response(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m12_human(result))
                return 0
            if args.model_command == "compare-card-event-net-m13":
                result = compare_cardeventnet_m13_timing_candidate(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m13_human(result))
                return 0
            if args.model_command == "prepare-card-event-net-m14":
                result = prepare_cardeventnet_m14_integration_handoff(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m14_human(result))
                return 0
            if args.model_command == "close-card-event-net-m15":
                result = validate_cardeventnet_m15_integration(
                    args.campaign_id,
                    repository_root=config.repository_root,
                    campaign_root=args.campaign_root,
                )
                if args.json or args.format == "json":
                    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
                else:
                    sys.stdout.write(render_cardeventnet_m15_human(result))
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
            CardEventM10Error,
            CardEventM11Error,
            CardEventM12Error,
            CardEventM13Error,
            CardEventM14Error,
            CardEventM15Error,
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
