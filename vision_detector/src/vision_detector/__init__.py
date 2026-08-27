"""Shared domain types for the DokoDetector vision boundary."""

from vision_detector.cards import (
    CARD_IDENTITIES,
    CARD_SET_ID,
    CardIdentity,
    CardSetManifest,
    DeckCard,
    DeckManifest,
    load_card_set,
    load_deck_manifest,
)
from vision_detector.contract import (
    CALIBRATION_STATES,
    VISION_SCHEMA_VERSION,
    VisionCandidate,
    VisionContractError,
    VisionDetectionResult,
    VisionDetectorMetadata,
    VisionDiagnostics,
    VisionEvidence,
    VisionFrame,
    VisionSession,
    VisionStatus,
    canonical_json_bytes,
    parse_result_bytes,
    validate_result,
)
from vision_detector.detector import VisionDetector
from vision_detector.scripted import (
    SCRIPTED_DETECTOR_NAME,
    SCRIPTED_DETECTOR_VERSION,
    ScriptedDetector,
    ScriptedDetectorConfigurationError,
    ScriptedVisionDetector,
    default_mapping_path,
)
from vision_detector.table_observation import (
    ANALYZER_CAPABILITIES,
    OBSERVATION_SCHEMA_VERSION,
    IdentityCandidate,
    ObservationSession,
    ObservationSource,
    ObservedCard,
    TableObservation,
    parse_observation_bytes,
    validate_observation,
)
from vision_detector.table_observation import (
    CALIBRATION_STATES as TABLE_OBSERVATION_CALIBRATION_STATES,
)
from vision_detector.table_observation import (
    ContractError as TableObservationContractError,
)
from vision_detector.table_observation import (
    canonical_json_bytes as canonical_table_observation_json_bytes,
)

__all__ = [
    "CALIBRATION_STATES",
    "ANALYZER_CAPABILITIES",
    "CARD_IDENTITIES",
    "CARD_SET_ID",
    "CardIdentity",
    "CardSetManifest",
    "DeckCard",
    "DeckManifest",
    "VISION_SCHEMA_VERSION",
    "VisionCandidate",
    "VisionContractError",
    "VisionDetectionResult",
    "VisionDetector",
    "VisionDetectorMetadata",
    "VisionDiagnostics",
    "VisionEvidence",
    "VisionFrame",
    "VisionSession",
    "VisionStatus",
    "TABLE_OBSERVATION_CALIBRATION_STATES",
    "TableObservationContractError",
    "IdentityCandidate",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationSession",
    "ObservationSource",
    "ObservedCard",
    "TableObservation",
    "SCRIPTED_DETECTOR_NAME",
    "SCRIPTED_DETECTOR_VERSION",
    "ScriptedDetector",
    "ScriptedDetectorConfigurationError",
    "ScriptedVisionDetector",
    "canonical_json_bytes",
    "canonical_table_observation_json_bytes",
    "default_mapping_path",
    "load_card_set",
    "load_deck_manifest",
    "parse_result_bytes",
    "parse_observation_bytes",
    "validate_result",
    "validate_observation",
]
