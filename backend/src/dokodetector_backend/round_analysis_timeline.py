"""Immutable timeline projection and frame delivery for round analyses."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from doko_operations.round_reconstruction import (
    FocusedDecisionRecord,
    GameplayResultRecord,
    IgnoredActionRecord,
    InferredActionRecord,
    ReconstructionActionRecord,
    RoundReconstructionContractError,
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
    ScoreBreakdownRecord,
    SelectedActionRecord,
    canonical_request_sha256,
    parse_round_reconstruction_result_bytes,
)
from game_engine import ReconstructionInput, parse_reconstruction_input_bytes
from pydantic import Field, field_validator, model_validator
from table_evidence_analyzer import TableObservation, canonical_json_bytes, parse_observation_bytes

from dokodetector_backend.analyzer_adapter import EvidenceIntegrityError, load_analyzer_evidence
from dokodetector_backend.contract import ContractModel, Sha256, parse_manifest_bytes
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.repository import (
    EvidenceRepository,
    StoredPackage,
    StoredRoundAnalysis,
    StoredTableObservation,
)
from dokodetector_backend.round_analysis_contract import (
    RoundAnalysisCreateRequest,
    parse_round_analysis_create_request_bytes,
)
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.storage import EvidenceStorage

ROUND_ANALYSIS_TIMELINE_SCHEMA_VERSION = "round-analysis-timeline/v1"
FRAME_PART_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


class RoundAnalysisTimelineError(RuntimeError):
    """Stored analysis or source bytes do not form a valid timeline."""


class RoundAnalysisNotCompleteError(RuntimeError):
    """A timeline was requested before its analysis reached a terminal result."""


class TimelineFrameNotFound(LookupError):
    """The requested frame is not part of the analysis."""


class TimelineSearchLimits(ContractModel):
    """Search limits copied from the immutable reconstruction result."""

    max_missing_plays: int = Field(ge=0)
    max_hypotheses: int = Field(gt=0)
    max_search_nodes: int = Field(gt=0)


class TimelineArtifactHashes(ContractModel):
    """Artifact identities recorded with one timeline projection."""

    input_artifact_id: str = Field(min_length=1, max_length=512)
    input_sha256: Sha256
    result_artifact_id: str = Field(min_length=1, max_length=512)
    result_sha256: Sha256


class TimelineFrame(ContractModel):
    """The validated central frame descriptor for one evidence row."""

    package_id: UUID
    part_name: str = Field(min_length=1, max_length=64, pattern=FRAME_PART_PATTERN)
    url: str = Field(min_length=1, max_length=1024)
    actual_offset_ms: int
    captured_at_utc: datetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_length: int = Field(gt=0)
    content_type: Literal["image/jpeg"]
    sha256: Sha256


class TimelineEvidenceRow(ContractModel):
    """One ordered evidence and table-observation row."""

    observation_id: str = Field(min_length=1, max_length=128)
    package_id: UUID
    event_sequence: int = Field(ge=1)
    event_time_ms: int = Field(ge=0)
    observed_at_ms: int = Field(ge=0)
    central_frame: TimelineFrame | None
    table_observation: TableObservation


class TimelineInferredPlay(ContractModel):
    """An inferred play anchored to neighboring evidence rows."""

    play_index: int = Field(gt=0)
    player: str = Field(min_length=1, max_length=128)
    card: str = Field(min_length=1, max_length=64)
    position: Literal["before", "between", "after"]
    before_observation_id: str | None = Field(default=None, min_length=1, max_length=128)
    after_observation_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_anchor(self) -> TimelineInferredPlay:
        if self.position == "before" and self.before_observation_id is not None:
            raise ValueError("a before inferred play cannot have a preceding observation.")
        if self.position == "after" and self.after_observation_id is not None:
            raise ValueError("an after inferred play cannot have a following observation.")
        if self.position == "between" and (
            self.before_observation_id is None or self.after_observation_id is None
        ):
            raise ValueError("a between inferred play needs both neighboring observations.")
        return self


class TimelineWarning(ContractModel):
    """A non-fatal condition that the timeline must show to an operator."""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=512)


class TimelineHypothesis(ContractModel):
    """One ranked reconstruction interpretation with its action mapping."""

    rank: int = Field(gt=0)
    gameplay: dict[str, Any]
    source_observation_ids: list[str]
    source_observed_card_ids: list[str]
    ignored_observed_card_ids: list[str]
    missing_play_indices: list[int]
    actions: list[dict[str, Any]]
    total_score: float
    score_breakdown: dict[str, Any]
    inferred_plays: list[TimelineInferredPlay]

    @field_validator("gameplay")
    @classmethod
    def validate_gameplay(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return GameplayResultRecord.from_mapping(
                value, "timeline.hypothesis.gameplay"
            ).to_mapping()
        except (TypeError, ValueError) as error:
            raise ValueError("hypothesis gameplay is invalid.") from error

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            return [_timeline_action(action, index) for index, action in enumerate(value)]
        except (TypeError, ValueError) as error:
            raise ValueError("hypothesis actions are invalid.") from error

    @field_validator("score_breakdown")
    @classmethod
    def validate_score_breakdown(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return ScoreBreakdownRecord.from_mapping(
                value, "timeline.hypothesis.score_breakdown"
            ).to_mapping()
        except (TypeError, ValueError) as error:
            raise ValueError("hypothesis score breakdown is invalid.") from error

    @field_validator("total_score")
    @classmethod
    def require_finite_score(cls, value: float) -> float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("hypothesis score must be finite.")
        return value


class RoundAnalysisTimeline(ContractModel):
    """Strict backend-owned projection for one immutable completed analysis."""

    schema_version: Literal["round-analysis-timeline/v1"] = ROUND_ANALYSIS_TIMELINE_SCHEMA_VERSION
    analysis_id: UUID
    recording_id: str = Field(min_length=1, max_length=256)
    round_id: str = Field(min_length=1, max_length=128)
    session_id: UUID
    reconstruction_status: Literal["resolved", "ambiguous", "incomplete", "impossible"]
    search: TimelineSearchLimits
    diagnostics: dict[str, Any]
    artifact_hashes: TimelineArtifactHashes
    rows: list[TimelineEvidenceRow]
    hypotheses: list[TimelineHypothesis]
    focused_decisions: list[dict[str, Any]]
    inferred_plays: list[TimelineInferredPlay]
    warnings: list[TimelineWarning]

    @field_validator("focused_decisions")
    @classmethod
    def validate_focused_decisions(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            return [
                FocusedDecisionRecord.from_mapping(
                    decision, f"timeline.focused_decisions[{index}]"
                ).to_mapping()
                for index, decision in enumerate(value)
            ]
        except (TypeError, ValueError) as error:
            raise ValueError("focused decisions are invalid.") from error


@dataclass(frozen=True, slots=True)
class VerifiedRoundAnalysis:
    """Parsed artifacts and validated source values for one completed analysis."""

    analysis: StoredRoundAnalysis
    request: RoundAnalysisCreateRequest
    input: ReconstructionInput
    result: RoundReconstructionRunResult
    packages: dict[UUID, StoredPackage]


@dataclass(frozen=True, slots=True)
class TimelineFrameFile:
    """A validated frame file ready for an HTTP response."""

    path: Path
    sha256: str


class RoundAnalysisTimelineProjector:
    """Verify immutable analysis inputs and build its presentation projection."""

    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        evidence_package_storage: EvidencePackageStorage,
        evidence_storage: EvidenceStorage,
        artifact_storage: RoundAnalysisArtifactStorage,
    ) -> None:
        self.evidence_repository = evidence_repository
        self.evidence_package_storage = evidence_package_storage
        self.evidence_storage = evidence_storage
        self.artifact_storage = artifact_storage

    def project(self, analysis: StoredRoundAnalysis) -> RoundAnalysisTimeline:
        """Verify one complete analysis and project its immutable timeline data."""

        verified = self.load_verified(analysis)
        rows: list[TimelineEvidenceRow] = []
        warnings: list[TimelineWarning] = []
        for observation in verified.input.observations:
            package_id = _package_uuid(observation.source.package_id)
            package = verified.packages[package_id]
            central_frame = self._central_frame(analysis.analysis_id, package)
            rows.append(
                TimelineEvidenceRow(
                    observation_id=observation.observation_id,
                    package_id=package_id,
                    event_sequence=package.event_sequence,
                    event_time_ms=package.event_time_ms,
                    observed_at_ms=observation.observed_at_ms,
                    central_frame=central_frame,
                    table_observation=TableObservation.model_validate(
                        observation.model_dump(mode="python", exclude_none=True)
                    ),
                )
            )
            if central_frame is None:
                warnings.append(
                    TimelineWarning(
                        code="missing_media",
                        message=f"Evidence package {package_id} has no stored frame.",
                    )
                )

        if any(
            observation.status == "insufficient_evidence"
            for observation in verified.input.observations
        ):
            warnings.append(
                TimelineWarning(
                    code="insufficient_evidence",
                    message="One or more table observations contain insufficient evidence.",
                )
            )
        if verified.result.diagnostics.truncated:
            warnings.append(
                TimelineWarning(
                    code="search_truncated",
                    message="The reconstruction search reached one of its configured limits.",
                )
            )
        if verified.result.diagnostics.ignored_observations:
            warnings.append(
                TimelineWarning(
                    code="ignored_observations",
                    message="The reconstruction ignored one or more table observations.",
                )
            )

        hypotheses: list[TimelineHypothesis] = []
        for rank, hypothesis in enumerate(verified.result.hypotheses, start=1):
            mapping = hypothesis.to_mapping()
            mapping["rank"] = rank
            mapping["inferred_plays"] = self._inferred_plays(hypothesis.actions, verified.input)
            hypotheses.append(TimelineHypothesis.model_validate(mapping))

        inferred_plays = hypotheses[0].inferred_plays if hypotheses else []
        return RoundAnalysisTimeline(
            analysis_id=analysis.analysis_id,
            recording_id=analysis.recording_id,
            round_id=analysis.round_id,
            session_id=analysis.session_id,
            reconstruction_status=verified.result.status,
            search=TimelineSearchLimits.model_validate(verified.result.search.to_mapping()),
            diagnostics=verified.result.diagnostics.to_mapping(),
            artifact_hashes=TimelineArtifactHashes(
                input_artifact_id=analysis.input_artifact_id or "",
                input_sha256=analysis.input_artifact_sha256 or "",
                result_artifact_id=analysis.result_artifact_id or "",
                result_sha256=analysis.result_artifact_sha256 or "",
            ),
            rows=rows,
            hypotheses=hypotheses,
            focused_decisions=[
                decision.to_mapping() for decision in verified.result.focused_decisions
            ],
            inferred_plays=inferred_plays,
            warnings=warnings,
        )

    def load_verified(self, analysis: StoredRoundAnalysis) -> VerifiedRoundAnalysis:
        """Read and verify the exact input, result, and source observations."""

        if analysis.state != "complete":
            raise RoundAnalysisNotCompleteError("The round analysis is not complete.")
        if (
            analysis.input_artifact_id is None
            or analysis.input_artifact_sha256 is None
            or analysis.result_artifact_id is None
            or analysis.result_artifact_sha256 is None
            or analysis.result_json is None
            or analysis.result_status is None
        ):
            raise RoundAnalysisTimelineError("The stored round analysis result is incomplete.")

        expected_input_id = f"round-analyses/{analysis.analysis_id}/input.json"
        expected_result_id = f"round-analyses/{analysis.analysis_id}/result.json"
        if (
            analysis.input_artifact_id != expected_input_id
            or analysis.result_artifact_id != expected_result_id
        ):
            raise RoundAnalysisTimelineError("The stored analysis artifact identity is invalid.")

        directory = self.artifact_storage.analysis_path(analysis.analysis_id)
        if not directory.is_dir() or directory.is_symlink():
            raise RoundAnalysisTimelineError(
                "The stored analysis artifact directory is unavailable."
            )
        input_bytes = self._read_artifact(directory / "input.json", analysis.input_artifact_sha256)
        result_bytes = self._read_artifact(
            directory / "result.json", analysis.result_artifact_sha256
        )
        if result_bytes.decode("utf-8") != analysis.result_json:
            raise RoundAnalysisTimelineError(
                "The stored result database row differs from result.json."
            )

        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
            reconstruction_input = parse_reconstruction_input_bytes(input_bytes)
            result = parse_round_reconstruction_result_bytes(result_bytes)
        except (UnicodeError, ValueError, RoundReconstructionContractError) as error:
            raise RoundAnalysisTimelineError(
                "The stored analysis artifacts failed validation."
            ) from error

        if request.analysis_id != analysis.analysis_id or result.run_id != str(
            analysis.analysis_id
        ):
            raise RoundAnalysisTimelineError(
                "The stored analysis artifacts do not match the analysis ID."
            )
        if result.status != analysis.result_status:
            raise RoundAnalysisTimelineError(
                "The stored result status does not match the analysis row."
            )
        self._validate_input_identity(request, reconstruction_input)
        self._validate_result_request(request, result)
        packages = self._validate_sources(reconstruction_input, result)
        self._validate_result_links(reconstruction_input, result)
        return VerifiedRoundAnalysis(
            analysis=analysis,
            request=request,
            input=reconstruction_input,
            result=result,
            packages=packages,
        )

    def load_verified_artifacts(self, analysis: StoredRoundAnalysis) -> VerifiedRoundAnalysis:
        """Read analysis artifacts without requiring the rebuildable source index."""

        if analysis.state != "complete":
            raise RoundAnalysisNotCompleteError("The round analysis is not complete.")
        if (
            analysis.input_artifact_id is None
            or analysis.input_artifact_sha256 is None
            or analysis.result_artifact_id is None
            or analysis.result_artifact_sha256 is None
            or analysis.result_json is None
            or analysis.result_status is None
        ):
            raise RoundAnalysisTimelineError("The stored round analysis result is incomplete.")

        expected_input_id = f"round-analyses/{analysis.analysis_id}/input.json"
        expected_result_id = f"round-analyses/{analysis.analysis_id}/result.json"
        if (
            analysis.input_artifact_id != expected_input_id
            or analysis.result_artifact_id != expected_result_id
        ):
            raise RoundAnalysisTimelineError("The stored analysis artifact identity is invalid.")
        directory = self.artifact_storage.analysis_path(analysis.analysis_id)
        if not directory.is_dir() or directory.is_symlink():
            raise RoundAnalysisTimelineError(
                "The stored analysis artifact directory is unavailable."
            )
        input_bytes = self._read_artifact(directory / "input.json", analysis.input_artifact_sha256)
        result_bytes = self._read_artifact(
            directory / "result.json", analysis.result_artifact_sha256
        )
        if result_bytes.decode("utf-8") != analysis.result_json:
            raise RoundAnalysisTimelineError(
                "The stored result database row differs from result.json."
            )
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
            reconstruction_input = parse_reconstruction_input_bytes(input_bytes)
            result = parse_round_reconstruction_result_bytes(result_bytes)
        except (UnicodeError, ValueError, RoundReconstructionContractError) as error:
            raise RoundAnalysisTimelineError(
                "The stored analysis artifacts failed validation."
            ) from error
        if request.analysis_id != analysis.analysis_id or result.run_id != str(
            analysis.analysis_id
        ):
            raise RoundAnalysisTimelineError(
                "The stored analysis artifacts do not match the analysis ID."
            )
        if result.status != analysis.result_status:
            raise RoundAnalysisTimelineError(
                "The stored result status does not match the analysis row."
            )
        self._validate_input_identity(request, reconstruction_input)
        self._validate_result_request(request, result)
        self._validate_result_links(reconstruction_input, result)
        return VerifiedRoundAnalysis(
            analysis=analysis,
            request=request,
            input=reconstruction_input,
            result=result,
            packages={},
        )

    def frame(
        self,
        analysis: StoredRoundAnalysis,
        package_id: UUID,
        part_name: str,
    ) -> TimelineFrameFile:
        """Verify and return one analysis-owned frame file."""

        verified = self.load_verified(analysis)
        if package_id not in verified.packages:
            raise TimelineFrameNotFound("The frame is not part of this analysis.")
        if not _safe_frame_part_name(part_name):
            raise TimelineFrameNotFound("The frame is not part of this analysis.")
        package = verified.packages[package_id]
        manifest = self._read_package_manifest(package)
        manifest_frame = next(
            (frame for frame in manifest.frames if frame.part_name == part_name), None
        )
        if manifest_frame is None:
            raise TimelineFrameNotFound("The frame is not part of this analysis.")
        stored_frame = next(
            (frame for frame in package.frames if frame.part_name == part_name), None
        )
        if stored_frame is None:
            raise RoundAnalysisTimelineError("The stored frame metadata is incomplete.")
        path = self._frame_path(package, stored_frame.relative_path)
        return TimelineFrameFile(path=path, sha256=manifest_frame.sha256)

    def _central_frame(self, analysis_id: UUID, package: StoredPackage) -> TimelineFrame | None:
        if not package.frames:
            return None
        manifest = self._read_package_manifest(package)
        manifest_frames = {frame.part_name: frame for frame in manifest.frames}
        stored_frame = min(
            package.frames,
            key=lambda frame: (
                abs(frame.actual_offset_ms),
                frame.actual_offset_ms,
                frame.part_name,
            ),
        )
        manifest_frame = manifest_frames.get(stored_frame.part_name)
        if manifest_frame is None:
            raise RoundAnalysisTimelineError("The stored frame metadata is incomplete.")
        return TimelineFrame(
            package_id=package.package_id,
            part_name=stored_frame.part_name,
            url=(
                f"/v1/round-analyses/{analysis_id}/evidence-packages/"
                f"{package.package_id}/frames/{stored_frame.part_name}"
            ),
            actual_offset_ms=stored_frame.actual_offset_ms,
            captured_at_utc=stored_frame.captured_at_utc,
            width=manifest_frame.width,
            height=manifest_frame.height,
            byte_length=stored_frame.byte_length,
            content_type="image/jpeg",
            sha256=stored_frame.sha256,
        )

    def _validate_sources(
        self,
        reconstruction_input: ReconstructionInput,
        result: RoundReconstructionRunResult,
    ) -> dict[UUID, StoredPackage]:
        packages: dict[UUID, StoredPackage] = {}
        if len(reconstruction_input.observations) != len(result.sources):
            raise RoundAnalysisTimelineError(
                "The result sources do not match the input observations."
            )
        for observation, source in zip(
            reconstruction_input.observations, result.sources, strict=True
        ):
            observation_bytes = canonical_json_bytes(observation)
            if (
                source.observation_id != observation.observation_id
                or source.byte_length != len(observation_bytes)
                or source.sha256 != _sha256(observation_bytes)
            ):
                raise RoundAnalysisTimelineError(
                    "The result source record does not match the input."
                )
            stored_observation = self.evidence_repository.get_table_observation(
                source.observation_id
            )
            if stored_observation is None:
                raise RoundAnalysisTimelineError("A source table observation is unavailable.")
            self._validate_stored_observation(
                stored_observation,
                observation,
                source.observation_id,
                source.observation_path,
            )
            package_id = _package_uuid(observation.source.package_id)
            package = self.evidence_repository.get_package(package_id)
            if package is None:
                raise RoundAnalysisTimelineError("A source evidence package is unavailable.")
            try:
                observation_session_id = UUID(observation.session.session_id)
            except (AttributeError, TypeError, ValueError) as error:
                raise RoundAnalysisTimelineError(
                    "A source observation has an invalid session."
                ) from error
            if (
                package.session_id != observation_session_id
                or package.event_sequence != observation.session.event_sequence
            ):
                raise RoundAnalysisTimelineError(
                    "A source evidence package has the wrong session event."
                )
            packages[package_id] = package
        for _package_id, package in packages.items():
            try:
                load_analyzer_evidence(package, self.evidence_package_storage)
            except EvidenceIntegrityError as error:
                raise RoundAnalysisTimelineError(
                    "A source evidence package failed integrity validation."
                ) from error
        return packages

    def _validate_stored_observation(
        self,
        stored: StoredTableObservation,
        input_observation: TableObservation,
        observation_id: str,
        observation_path: str,
    ) -> None:
        expected_bytes = canonical_json_bytes(input_observation)
        if (
            stored.package_id != _package_uuid(input_observation.source.package_id)
            or stored.relative_path != observation_path
            or stored.relative_path != f"table-observations/{observation_id}/observation.json"
            or stored.observation_sha256 != _sha256(expected_bytes)
            or stored.observation_json.encode("utf-8") != expected_bytes
        ):
            raise RoundAnalysisTimelineError(
                "A stored source observation differs from the analysis input."
            )
        path = self.evidence_storage.table_observation_path(observation_id) / "observation.json"
        try:
            observation_file_bytes = path.read_bytes()
            if observation_file_bytes != expected_bytes:
                raise RoundAnalysisTimelineError(
                    "A stored source observation file differs from the analysis input."
                )
            parse_observation_bytes(observation_file_bytes)
        except (OSError, ValueError) as error:
            raise RoundAnalysisTimelineError(
                "A stored source observation is unavailable."
            ) from error

    def _validate_input_identity(
        self,
        request: RoundAnalysisCreateRequest,
        reconstruction_input: ReconstructionInput,
    ) -> None:
        setup = request.round_setup
        if (
            reconstruction_input.game_id != setup.game_id
            or reconstruction_input.round_id != setup.round_id
            or reconstruction_input.ruleset.name != setup.ruleset.name
            or reconstruction_input.ruleset.version != setup.ruleset.version
            or reconstruction_input.deck_variant != setup.deck_variant
            or reconstruction_input.active_players != setup.active_players
            or reconstruction_input.dealer != setup.dealer
            or reconstruction_input.first_trick_leader != setup.first_trick_leader
            or any(
                observation.session.session_id != str(request.session_id)
                for observation in reconstruction_input.observations
            )
            or tuple(
                observation.source.package_id for observation in reconstruction_input.observations
            )
            != tuple(str(package_id) for package_id in request.evidence_package_ids)
        ):
            raise RoundAnalysisTimelineError(
                "The reconstruction input does not match the analysis request."
            )

    def _validate_result_request(
        self,
        request: RoundAnalysisCreateRequest,
        result: RoundReconstructionRunResult,
    ) -> None:
        reconstruction_request = RoundReconstructionRunRequest(
            run_id=str(request.analysis_id),
            round_setup=request.round_setup.to_shared(),
            observation_paths=tuple(source.observation_path for source in result.sources),
            search=request.search.to_shared(),
            output_root=".",
        )
        if (
            result.search != reconstruction_request.search
            or result.request_sha256 != canonical_request_sha256(reconstruction_request)
        ):
            raise RoundAnalysisTimelineError(
                "The reconstruction result does not match its analysis request."
            )

    def _validate_result_links(
        self,
        reconstruction_input: ReconstructionInput,
        result: RoundReconstructionRunResult,
    ) -> None:
        observed_cards = {
            (observation.observation_id, card.observed_card_id)
            for observation in reconstruction_input.observations
            for card in observation.cards
        }
        observation_ids = {
            observation.observation_id for observation in reconstruction_input.observations
        }
        for hypothesis in result.hypotheses:
            for action in hypothesis.actions:
                if (
                    isinstance(action, (SelectedActionRecord, IgnoredActionRecord))
                    and (
                        action.observation_id,
                        action.observed_card_id,
                    )
                    not in observed_cards
                ):
                    raise RoundAnalysisTimelineError(
                        "A reconstruction action refers to an unavailable observed card."
                    )
        for decision in result.focused_decisions:
            if any(
                source_id not in observation_ids for source_id in decision.source_observation_ids
            ):
                raise RoundAnalysisTimelineError(
                    "A focused decision refers to an unavailable observation."
                )

    def _inferred_plays(
        self,
        actions: tuple[ReconstructionActionRecord, ...],
        reconstruction_input: ReconstructionInput,
    ) -> list[TimelineInferredPlay]:
        selected_by_play = {
            action.play_index: action.observation_id
            for action in actions
            if isinstance(action, SelectedActionRecord)
        }
        inferred = [action for action in actions if isinstance(action, InferredActionRecord)]
        result: list[TimelineInferredPlay] = []
        observation_ids = [
            observation.observation_id for observation in reconstruction_input.observations
        ]
        for action in inferred:
            preceding = [play for play in selected_by_play if play < action.play_index]
            following = [play for play in selected_by_play if play > action.play_index]
            before = selected_by_play[max(preceding)] if preceding else None
            after = selected_by_play[min(following)] if following else None
            if before is None:
                position: Literal["before", "between", "after"] = "before"
                after = after or (observation_ids[0] if observation_ids else None)
            elif after is None:
                position = "after"
                before = before or (observation_ids[-1] if observation_ids else None)
            else:
                position = "between"
            result.append(
                TimelineInferredPlay(
                    play_index=action.play_index,
                    player=action.player,
                    card=action.card,
                    position=position,
                    before_observation_id=before,
                    after_observation_id=after,
                )
            )
        return result

    def _read_package_manifest(self, package: StoredPackage):
        try:
            manifest_bytes = (
                self.evidence_package_storage.package_path(package.package_id)
                / "evidence-manifest.json"
            ).read_bytes()
            if manifest_bytes != package.manifest_json.encode("utf-8"):
                raise RoundAnalysisTimelineError(
                    "The stored package manifest differs from its metadata."
                )
            if _sha256(manifest_bytes) != package.manifest_sha256:
                raise RoundAnalysisTimelineError("The stored package manifest hash is invalid.")
            return parse_manifest_bytes(manifest_bytes)
        except (OSError, ValueError) as error:
            if isinstance(error, RoundAnalysisTimelineError):
                raise
            raise RoundAnalysisTimelineError("The stored package manifest is invalid.") from error

    def _frame_path(self, package: StoredPackage, relative_path: str) -> Path:
        if relative_path != f"frames/{Path(relative_path).name}" or not relative_path.endswith(
            ".jpg"
        ):
            raise RoundAnalysisTimelineError("The stored frame path is invalid.")
        root = self.evidence_package_storage.package_path(package.package_id).resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file():
            raise RoundAnalysisTimelineError("The stored frame is unavailable.")
        return path

    @staticmethod
    def _read_artifact(path: Path, expected_sha256: str) -> bytes:
        try:
            value = path.read_bytes()
        except OSError as error:
            raise RoundAnalysisTimelineError(
                "A stored analysis artifact is unavailable."
            ) from error
        if _sha256(value) != expected_sha256:
            raise RoundAnalysisTimelineError("A stored analysis artifact failed hash validation.")
        return value


def _package_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise RoundAnalysisTimelineError(
            "The analysis references an invalid evidence package ID."
        ) from error


def _timeline_action(action: dict[str, Any], index: int) -> dict[str, Any]:
    kind = action.get("kind")
    context = f"timeline.hypothesis.actions[{index}]"
    if kind == "selected":
        return SelectedActionRecord.from_mapping(action, context).to_mapping()
    if kind == "ignored":
        return IgnoredActionRecord.from_mapping(action, context).to_mapping()
    if kind == "inferred":
        return InferredActionRecord.from_mapping(action, context).to_mapping()
    raise RoundReconstructionContractError(
        f"{context}.kind must be selected, ignored, or inferred."
    )


def _safe_frame_part_name(value: str) -> bool:
    import re

    return bool(re.fullmatch(FRAME_PART_PATTERN, value)) and len(value) <= 64


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "ROUND_ANALYSIS_TIMELINE_SCHEMA_VERSION",
    "RoundAnalysisNotCompleteError",
    "RoundAnalysisTimeline",
    "RoundAnalysisTimelineError",
    "RoundAnalysisTimelineProjector",
    "TimelineFrameFile",
    "TimelineFrameNotFound",
    "TimelineInferredPlay",
]
