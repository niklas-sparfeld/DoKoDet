"""Deterministic candidate selection for the TableEvidenceAnalyzer data task.

The adapter reads accepted recording bundles, proposal-generator output, reviewed CardEventNet
events, and optional accepted evidence packages.  It writes references to those inputs.  It never
copies or edits source media.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .review import ReviewInput, ReviewItem, ReviewRunError, TaskArtifacts

TABLE_EVIDENCE_TASK = "table_evidence_analysis"
SELECTION_SCHEMA_VERSION = "table-evidence-candidate-selection/v1"
COVERAGE_SCHEMA_VERSION = "table-evidence-selection-coverage/v1"
TABLE_OBSERVATION_ANNOTATION_SCHEMA_VERSION = "table-observation-annotation/v1"
TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION = "table-observation-review/v1"
DATASET_VERSION_SCHEMA_VERSION = "dataset-version/v1"
TABLE_DATASET_TASK = "table_evidence_analyzer_identity_crop"
TABLE_DATASET_TRANSFORM_VERSION = "identity-crop-v1"
TABLE_DATASET_SPLIT_SCHEMA_VERSION = "table-dataset-split/v1"
TABLE_DATASET_COVERAGE_SCHEMA_VERSION = "table-dataset-coverage/v1"
TABLE_DATASET_VALIDATION_SCHEMA_VERSION = "table-dataset-validation/v1"
REVIEW_REPORT_SCHEMA_VERSION = "table-observation-review-report/v1"
VALID_SELECTION_SOURCES = (
    "device_event_proposal",
    "mac_event_proposal",
    "reviewed_event",
    "coverage_sample",
    "negative_sample",
    "operator_selected",
    "evidence_package",
    "other_event_proposal",
)
_SOURCE_ORDER = {value: index for index, value in enumerate(VALID_SELECTION_SOURCES)}
_PLATFORM_SOURCES = {
    "ios": "device_event_proposal",
    "macos": "mac_event_proposal",
}
_REVIEWED_STATES = frozenset({"reviewed", "eligible", "complete", "applied"})
_SHA256 = frozenset("0123456789abcdef")
_CARD_IDENTITIES = frozenset(
    f"{suit}_{rank}"
    for suit in ("CLUBS", "SPADES", "HEARTS", "DIAMONDS")
    for rank in ("NINE", "JACK", "QUEEN", "KING", "TEN", "ACE")
)
_VISIBILITY_STATES = frozenset(
    {"identifiable", "card_not_visible", "visible_but_not_identifiable", "ambiguous_card"}
)
_ACTIVE_AREA_CLASSES = frozenset({"inside", "outside", "uncertain", "not_applicable"})
_MOVEMENT_STATES = frozenset({"stationary", "moving", "reappeared", "unknown"})
_OCCLUSION_STATES = frozenset({"none", "short", "complete", "unknown"})
_ACCEPTED_OUTCOMES = frozenset(
    {"accepted", "confirmed", "confirmed_positive", "include", "confirm_card_play"}
)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ReviewRunError("Table-evidence selection values must be finite JSON values.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, context: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewRunError(f"Could not read {context} {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"{context} must contain an object: {path}")
    return value


def _finite_number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReviewRunError(f"{field} must be a finite number.")
    result = float(value)
    if result < minimum:
        raise ReviewRunError(f"{field} must be at least {minimum}.")
    return result


def _rounded(value: float) -> float:
    return round(value, 6)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.name not in {"", "."}


def _safe_part_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 64
        and all(character.isalnum() or character in "._-" for character in value)
        and value[0].isalnum()
    )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReviewRunError(f"Could not read evidence bytes {path}: {exc}") from exc
    return digest.hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_relative(root: Path, relative_path: str, context: str) -> Path:
    if not _safe_relative_path(relative_path):
        raise ReviewRunError(f"{context} has an unsafe relative path.")
    resolved = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ReviewRunError(f"{context} points outside its package.") from exc
    return resolved


def _verify_declared_file(path: Path, descriptor: Mapping[str, Any], context: str) -> None:
    if not path.is_file():
        raise ReviewRunError(f"{context} is missing: {path}")
    byte_length = descriptor.get("byte_length")
    digest = descriptor.get("sha256")
    if (
        not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length <= 0
        or not _valid_digest(digest)
    ):
        raise ReviewRunError(f"{context} has invalid byte metadata.")
    if path.stat().st_size != byte_length or _sha256_file(path) != digest:
        raise ReviewRunError(f"{context} bytes do not match their declared digest.")


@dataclass(frozen=True, slots=True)
class _BundleData:
    item: ReviewInput
    manifest: Mapping[str, Any]
    source: Mapping[str, Any]
    video_path: Path
    video_id: str
    proposals: tuple[Mapping[str, Any], ...]
    proposal_descriptors: tuple[Mapping[str, Any], ...]
    packages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    item: ReviewItem
    selection: dict[str, Any]
    digest_selection: dict[str, Any]


class TableEvidenceReviewAdapter:
    """Select proposal-independent table-evidence review candidates.

    ``evidence_roots`` and ``reviewed_event_roots`` are optional read-only roots.  When they are
    omitted, the adapter checks the conventional repository locations relative to each bundle.
    ``operator_intervals`` accepts either a mapping keyed by source asset ID or a list of records
    with a ``source_asset_id`` field.  Each interval has ``start_s`` and ``end_s``.
    """

    def __init__(
        self,
        *,
        evidence_roots: Sequence[str | Path] = (),
        reviewed_event_roots: Sequence[str | Path] = (),
        operator_intervals: Mapping[str, Sequence[Mapping[str, Any]]]
        | Sequence[Mapping[str, Any]] = (),
        operator_selection_file: str | Path | None = None,
        coverage_interval_s: float = 10.0,
        candidate_window_s: float = 1.0,
    ) -> None:
        self.evidence_roots = tuple(Path(path).expanduser().resolve() for path in evidence_roots)
        self.reviewed_event_roots = tuple(
            Path(path).expanduser().resolve() for path in reviewed_event_roots
        )
        self.coverage_interval_s = _finite_number(
            coverage_interval_s, "coverage_interval_s", minimum=0.001
        )
        self.candidate_window_s = _finite_number(
            candidate_window_s, "candidate_window_s", minimum=0.001
        )
        self._reviewer = "review-run"
        intervals: Any = operator_intervals
        if operator_selection_file is not None:
            intervals = _read_json(
                Path(operator_selection_file).expanduser().resolve(),
                "operator selection intervals",
            )
        self.operator_intervals = _normalize_operator_intervals(intervals)

    def set_reviewer(self, reviewer: str) -> None:
        """Set the operator name used by immutable table-observation review artifacts."""

        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ReviewRunError("Table-observation reviewer must be a non-empty string.")
        self._reviewer = reviewer

    def discover(self, task: str, inputs: Sequence[ReviewInput]) -> Sequence[ReviewItem]:
        if task != TABLE_EVIDENCE_TASK:
            raise ReviewRunError(f"Table-evidence adapter cannot process {task}")
        candidates = self._candidates(inputs)
        return [candidate.item for candidate in candidates]

    def apply_decision(
        self,
        task: str,
        item: ReviewItem,
        decision: Mapping[str, Any],
        staging_dir: Path,
    ) -> None:
        if task != TABLE_EVIDENCE_TASK:
            raise ReviewRunError(f"Table-evidence adapter cannot process {task}")
        if not decision:
            raise ReviewRunError(f"Decision for {item.item_id} must not be empty.")
        log_path = staging_dir / "table-evidence" / "decision-log.json"
        current: dict[str, Any] = {}
        if log_path.is_file():
            current = dict(_read_json(log_path, "table-evidence decision log"))
        current[item.item_id] = dict(decision)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def finalize(
        self,
        task: str,
        inputs: Sequence[ReviewInput],
        items: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> TaskArtifacts:
        if task != TABLE_EVIDENCE_TASK:
            raise ReviewRunError(f"Table-evidence adapter cannot process {task}")
        candidates = self._candidates(inputs)
        expected_ids = {candidate.item.item_id for candidate in candidates}
        actual_ids = {item.get("item_id") for item in items if isinstance(item.get("item_id"), str)}
        if actual_ids != expected_ids:
            raise ReviewRunError("Table-evidence review items changed before finalization.")
        if any(item.get("state") != "complete" for item in items):
            raise ReviewRunError(
                "All table-evidence candidates must be reviewed before finalization."
            )

        output_root = staging_dir / "table-evidence"
        output_root.mkdir(parents=True, exist_ok=True)
        selection_core = self._selection_core(inputs, candidates)
        selection_digest = _digest(_without_locators(selection_core))
        selection_payload = dict(selection_core)
        selection_payload["selection_digest"] = selection_digest
        selection_path = output_root / "candidate-selection.json"
        _write_json(selection_path, selection_payload)

        coverage_payload = _coverage_payload(selection_core, candidates, selection_digest)
        coverage_path = output_root / "selection-coverage.json"
        _write_json(coverage_path, coverage_payload)
        coverage_markdown_path = output_root / "selection-coverage.md"
        coverage_markdown_path.write_text(_coverage_markdown(coverage_payload), encoding="utf-8")

        validation_payload = {
            "schema_version": "table-evidence-selection-validation/v1",
            "task": TABLE_EVIDENCE_TASK,
            "valid": True,
            "selection_digest": selection_digest,
            "candidate_count": len(candidates),
            "source_assets": [item.source_asset_id for item in inputs],
        }
        validation_path = output_root / "selection-validation.json"
        _write_json(validation_path, validation_payload)

        annotation_records = self._reviewed_annotations(candidates, items)
        self._write_review_artifacts(annotation_records, output_root)
        dataset_payload, dataset_entries, unassigned = _dataset_payload(
            annotation_records,
            inputs=inputs,
            selection_digest=selection_digest,
        )
        dataset_path = output_root / "dataset" / "table-evidence-dataset-version.json"
        _write_json(dataset_path, dataset_payload)

        coverage = _dataset_coverage(
            annotation_records,
            inputs=inputs,
            dataset_payload=dataset_payload,
            unassigned=unassigned,
        )
        dataset_coverage_path = output_root / "dataset" / "coverage.json"
        _write_json(dataset_coverage_path, coverage)
        dataset_coverage_markdown_path = output_root / "dataset" / "coverage.md"
        dataset_coverage_markdown_path.write_text(
            _dataset_coverage_markdown(coverage), encoding="utf-8"
        )

        split_payload = _split_payload(dataset_payload, dataset_entries, selection_digest)
        split_path = output_root / "split-proposal" / "table-evidence-split-proposal.json"
        _write_json(split_path, split_payload)

        validation = _dataset_validation(
            annotation_records,
            dataset_payload=dataset_payload,
            dataset_entries=dataset_entries,
            unassigned=unassigned,
        )
        dataset_validation_path = output_root / "validation" / "table-evidence-validation.json"
        _write_json(dataset_validation_path, validation)

        receipt = _lifecycle_receipt(
            annotation_records,
            inputs=inputs,
            dataset_payload=dataset_payload,
            split_payload=split_payload,
            selection_digest=selection_digest,
        )
        receipt_path = output_root / "lifecycle-receipt.json"
        _write_json(receipt_path, receipt)

        review_report = _review_report(
            annotation_records,
            selection_digest=selection_digest,
            dataset_payload=dataset_payload,
            unassigned=unassigned,
        )
        review_report_path = output_root / "review-report.json"
        _write_json(review_report_path, review_report)
        review_report_markdown_path = output_root / "review-report.md"
        review_report_markdown_path.write_text(
            _review_report_markdown(review_report), encoding="utf-8"
        )

        files = tuple(sorted(path for path in staging_dir.rglob("*") if path.is_file()))
        return TaskArtifacts(files)

    def validate(self, task: str, staging_dir: Path) -> Sequence[str]:
        if task != TABLE_EVIDENCE_TASK:
            return (f"Table-evidence adapter cannot process {task}",)
        required = (
            staging_dir / "table-evidence" / "candidate-selection.json",
            staging_dir / "table-evidence" / "selection-coverage.json",
            staging_dir / "table-evidence" / "selection-coverage.md",
            staging_dir / "table-evidence" / "selection-validation.json",
            staging_dir / "table-evidence" / "dataset" / "table-evidence-dataset-version.json",
            staging_dir / "table-evidence" / "dataset" / "coverage.json",
            staging_dir / "table-evidence" / "dataset" / "coverage.md",
            staging_dir
            / "table-evidence"
            / "split-proposal"
            / "table-evidence-split-proposal.json",
            staging_dir / "table-evidence" / "validation" / "table-evidence-validation.json",
            staging_dir / "table-evidence" / "lifecycle-receipt.json",
            staging_dir / "table-evidence" / "review-report.json",
            staging_dir / "table-evidence" / "review-report.md",
        )
        return tuple(
            f"missing staged table-evidence output: {path}"
            for path in required
            if not path.is_file()
        )

    def _reviewed_annotations(
        self, candidates: Sequence[_Candidate], items: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates_by_id = {candidate.item.item_id: candidate for candidate in candidates}
        records: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda value: str(value.get("item_id", ""))):
            item_id = item.get("item_id")
            if not isinstance(item_id, str) or item_id not in candidates_by_id:
                raise ReviewRunError("Table-evidence review item is not a discovered candidate.")
            decision = item.get("decision")
            if not isinstance(decision, Mapping):
                raise ReviewRunError(f"Table-evidence decision is missing for {item_id}.")
            candidate = candidates_by_id[item_id]
            records.append(_annotation_record(candidate, decision, self._reviewer))
        return records

    def _write_review_artifacts(
        self, records: Sequence[Mapping[str, Any]], output_root: Path
    ) -> tuple[list[Path], list[Path]]:
        annotation_paths: list[Path] = []
        review_paths: list[Path] = []
        for record in records:
            annotation = record["reviewed_annotation"]
            review = record["review"]
            annotation_path = (
                output_root / "annotations" / f"{annotation['annotation_set_id']}.json"
            )
            review_path = output_root / "reviews" / f"{review['review_id']}.json"
            _write_json(annotation_path, annotation)
            _write_json(review_path, review)
            annotation_paths.append(annotation_path)
            review_paths.append(review_path)
        return annotation_paths, review_paths

    def _candidates(self, inputs: Sequence[ReviewInput]) -> list[_Candidate]:
        result: list[_Candidate] = []
        for bundle in sorted(
            (self._load_bundle(item) for item in inputs),
            key=lambda value: (value.item.source_asset_id, value.item.recording_id),
        ):
            package_data = list(bundle.packages)
            proposal_times: list[float] = []
            for proposal, descriptor in zip(
                bundle.proposals, bundle.proposal_descriptors, strict=True
            ):
                source = _PLATFORM_SOURCES.get(
                    (proposal.get("execution_environment") or {}).get("platform")
                    if isinstance(proposal.get("execution_environment"), Mapping)
                    else None,
                    "other_event_proposal",
                )
                run_id = proposal.get("proposal_generator_run_id")
                if not isinstance(run_id, str) or not run_id:
                    raise ReviewRunError(
                        "Proposal generator run is missing its ID for "
                        f"{bundle.item.source_asset_id}."
                    )
                events = proposal.get("event_proposals")
                if not isinstance(events, list):
                    raise ReviewRunError(
                        f"Proposal generator run is incomplete for {bundle.item.source_asset_id}."
                    )
                run_reference = _proposal_run_reference(proposal, descriptor, bundle.item)
                for index, event in enumerate(events):
                    if not isinstance(event, Mapping):
                        raise ReviewRunError(
                            f"Proposal event {index} is invalid for {bundle.item.source_asset_id}."
                        )
                    time_s = _finite_number(
                        event.get("time_s"),
                        f"proposal {run_id} event {index} time_s",
                    )
                    proposal_times.append(time_s)
                    result.append(
                        self._make_candidate(
                            bundle,
                            selection_source=source,
                            time_s=time_s,
                            proposal_generator_run=run_reference,
                            evidence=_nearest_package(
                                package_data, time_s, self.candidate_window_s
                            ),
                            ordinal=index,
                        )
                    )

                low_probability = _lowest_negative(proposal)
                if low_probability is not None:
                    time_s, probability = low_probability
                    result.append(
                        self._make_candidate(
                            bundle,
                            selection_source="negative_sample",
                            time_s=time_s,
                            proposal_generator_run=run_reference,
                            evidence=_nearest_package(
                                package_data, time_s, self.candidate_window_s
                            ),
                            ordinal=0,
                            extra={"probability": probability},
                        )
                    )

            reviewed_events = self._reviewed_events(bundle)
            reviewed_times = []
            for index, event in enumerate(reviewed_events):
                time_s = _finite_number(
                    event.get("time_s"),
                    f"reviewed event {index} time_s for {bundle.item.source_asset_id}",
                )
                reviewed_times.append(time_s)
                result.append(
                    self._make_candidate(
                        bundle,
                        selection_source="reviewed_event",
                        time_s=time_s,
                        evidence=_nearest_package(package_data, time_s, self.candidate_window_s),
                        ordinal=index,
                        extra={"reviewed_event_source": {"canonical_path": event["source_path"]}},
                    )
                )

            duration_s = _duration_s(bundle, package_data)
            coverage_times = _coverage_times(
                duration_s,
                self.coverage_interval_s,
                (*proposal_times, *reviewed_times),
            )
            for index, time_s in enumerate(coverage_times):
                result.append(
                    self._make_candidate(
                        bundle,
                        selection_source="coverage_sample",
                        time_s=time_s,
                        evidence=_nearest_package(package_data, time_s, self.candidate_window_s),
                        ordinal=index,
                    )
                )

            for index, interval in enumerate(
                self.operator_intervals.get(bundle.item.source_asset_id, ())
            ):
                start_s = _finite_number(
                    interval["start_s"],
                    f"operator interval {index} start_s for {bundle.item.source_asset_id}",
                )
                end_s = _finite_number(
                    interval["end_s"],
                    f"operator interval {index} end_s for {bundle.item.source_asset_id}",
                )
                if end_s <= start_s:
                    raise ReviewRunError(
                        f"Operator interval {index} end_s must be after start_s for "
                        f"{bundle.item.source_asset_id}."
                    )
                midpoint = (start_s + end_s) / 2
                extra = {
                    key: interval[key]
                    for key in ("label", "reason")
                    if key in interval and isinstance(interval[key], str) and interval[key]
                }
                result.append(
                    self._make_candidate(
                        bundle,
                        selection_source="operator_selected",
                        time_s=midpoint,
                        recording_range=(start_s, end_s),
                        evidence=_nearest_package(package_data, midpoint, self.candidate_window_s),
                        ordinal=index,
                        extra=extra,
                    )
                )

            for package in package_data:
                if not any(
                    candidate.selection.get("evidence_package_id") == package["package_id"]
                    for candidate in result
                    if candidate.selection["source_asset_id"] == bundle.item.source_asset_id
                ):
                    result.append(
                        self._make_candidate(
                            bundle,
                            selection_source="evidence_package",
                            time_s=package["event_time_s"],
                            recording_range=tuple(package["recording_range"]),
                            evidence=package,
                            ordinal=0,
                        )
                    )

        result.sort(
            key=lambda candidate: (
                candidate.selection["source_asset_id"],
                _SOURCE_ORDER.get(candidate.selection["selection_source"], 999),
                candidate.selection["recording_range"]["start_s"],
                candidate.selection["recording_range"]["end_s"],
                candidate.item.item_id,
            )
        )
        return result

    def _load_bundle(self, item: ReviewInput) -> _BundleData:
        bundle = Path(item.bundle_path).resolve()
        manifest = _read_json(bundle / "manifest.json", "repository bundle manifest")
        source = _read_json(bundle / "source-record.json", "source record")
        if (
            manifest.get("source_asset_id") != item.source_asset_id
            or source.get("source_asset_id") != item.source_asset_id
        ):
            raise ReviewRunError(
                f"Table-evidence source identity differs for {item.source_asset_id}."
            )
        if (
            manifest.get("source_sha256") != item.source_sha256
            or source.get("sha256") != item.source_sha256
        ):
            raise ReviewRunError(
                f"Table-evidence source digest differs for {item.source_asset_id}."
            )
        files = manifest.get("files")
        if not isinstance(files, Mapping) or not isinstance(files.get("video"), Mapping):
            raise ReviewRunError(f"Table-evidence bundle has no video descriptor: {bundle}")
        video_descriptor = files["video"]
        relative_video = video_descriptor.get("relative_path")
        if not isinstance(relative_video, str):
            raise ReviewRunError(f"Table-evidence video descriptor is invalid: {bundle}")
        video_path = _resolve_relative(bundle, relative_video, "Table-evidence video descriptor")
        if not video_path.is_file():
            raise ReviewRunError(f"Table-evidence source video is missing: {video_path}")
        descriptors = files.get("proposal_generator_runs", [])
        if not isinstance(descriptors, list):
            raise ReviewRunError(f"Table-evidence proposal descriptors are invalid: {bundle}")
        proposals: list[Mapping[str, Any]] = []
        proposal_descriptors: list[Mapping[str, Any]] = []
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping) or not isinstance(
                descriptor.get("relative_path"), str
            ):
                raise ReviewRunError(f"Table-evidence proposal descriptor is invalid: {bundle}")
            proposal_path = _resolve_relative(
                bundle, descriptor["relative_path"], "proposal descriptor"
            )
            proposals.append(_read_json(proposal_path, "proposal generator run"))
            proposal_descriptors.append(descriptor)
        packages = self._discover_packages(bundle, source, item)
        return _BundleData(
            item=item,
            manifest=manifest,
            source=source,
            video_path=video_path,
            video_id=str(manifest.get("video_id", source.get("video_id", item.recording_id))),
            proposals=tuple(proposals),
            proposal_descriptors=tuple(proposal_descriptors),
            packages=tuple(packages),
        )

    def _discover_packages(
        self, bundle: Path, source: Mapping[str, Any], item: ReviewInput
    ) -> list[Mapping[str, Any]]:
        roots = list(self.evidence_roots)
        explicit_package_paths = {
            root.parent if root.is_file() and root.name == "manifest.json" else root
            for root in roots
            if (root.is_file() and root.name == "manifest.json")
            or (root.is_dir() and (root / "manifest.json").is_file())
        }
        for ancestor in (bundle, *bundle.parents):
            roots.extend(
                (
                    ancestor / "evidence",
                    ancestor / "evidence-packages",
                    ancestor / ".runtime" / "evidence",
                    ancestor / "data" / "evidence",
                )
            )
        paths: set[Path] = set()
        for root in roots:
            if root.is_file() and root.name == "manifest.json":
                paths.add(root.parent)
                continue
            if not root.is_dir():
                continue
            try:
                for manifest_path in root.rglob("manifest.json"):
                    if manifest_path.is_file():
                        paths.add(manifest_path.parent)
            except OSError as exc:
                raise ReviewRunError(
                    f"Could not discover evidence packages below {root}: {exc}"
                ) from exc
        packages: list[Mapping[str, Any]] = []
        for path in sorted(paths, key=lambda value: value.as_posix()):
            manifest_path = path / "manifest.json"
            try:
                manifest = _read_json(manifest_path, "evidence package manifest")
            except ReviewRunError:
                continue
            if manifest.get("schema_version") != "cardevent-evidence/v2":
                continue
            explicit = path in explicit_package_paths
            if not explicit and not _package_matches(manifest, path, source, item):
                continue
            packages.append(_materialize_package(path, manifest, item))
        return sorted(packages, key=lambda value: (value["event_time_s"], value["package_id"]))

    def _reviewed_events(self, bundle: _BundleData) -> list[Mapping[str, Any]]:
        roots = list(self.reviewed_event_roots)
        for ancestor in (
            Path(bundle.item.bundle_path).resolve(),
            *Path(bundle.item.bundle_path).resolve().parents,
        ):
            roots.extend(
                (
                    ancestor / "reviewed-events.json",
                    ancestor / "annotations",
                    ancestor / "data" / "annotations",
                    ancestor / "card_event_net" / "data" / "annotations",
                )
            )
        paths: set[Path] = set()
        for root in roots:
            if root.is_file() and root.suffix == ".json":
                paths.add(root)
            elif root.is_dir():
                try:
                    paths.update(path for path in root.rglob("*.json") if path.is_file())
                except OSError as exc:
                    raise ReviewRunError(
                        f"Could not discover reviewed events below {root}: {exc}"
                    ) from exc
        events: list[Mapping[str, Any]] = []
        for path in sorted(paths, key=lambda value: value.as_posix()):
            try:
                payload = _read_json(path, "reviewed event document")
            except ReviewRunError:
                continue
            if not _reviewed_document_matches(payload, path, bundle):
                continue
            values = payload.get("events", payload.get("reviewed_events", []))
            if not isinstance(values, list):
                continue
            for event in values:
                if isinstance(event, Mapping) and isinstance(event.get("time_s"), (int, float)):
                    events.append({"time_s": event["time_s"], "source_path": str(path)})
        return sorted(events, key=lambda value: (float(value["time_s"]), str(value["source_path"])))

    def _make_candidate(
        self,
        bundle: _BundleData,
        *,
        selection_source: str,
        time_s: float,
        evidence: Mapping[str, Any] | None = None,
        proposal_generator_run: Mapping[str, Any] | None = None,
        recording_range: tuple[float, float] | None = None,
        ordinal: int,
        extra: Mapping[str, Any] | None = None,
    ) -> _Candidate:
        if selection_source not in VALID_SELECTION_SOURCES:
            raise ReviewRunError(f"Unknown table-evidence selection source: {selection_source}")
        if recording_range is None:
            package_range = evidence.get("recording_range") if evidence else None
            if (
                isinstance(package_range, Sequence)
                and not isinstance(package_range, (str, bytes))
                and len(package_range) == 2
            ):
                recording_range = (float(package_range[0]), float(package_range[1]))
            else:
                recording_range = (
                    max(0.0, time_s - self.candidate_window_s),
                    time_s + self.candidate_window_s,
                )
        start_s, end_s = recording_range
        evidence_package_id = evidence.get("package_id") if evidence else None
        selection: dict[str, Any] = {
            "selection_id": "",
            "source_asset_id": bundle.item.source_asset_id,
            "recording_id": bundle.item.recording_id,
            "selection_source": selection_source,
            "time_s": _rounded(time_s),
            "recording_range": {"start_s": _rounded(start_s), "end_s": _rounded(end_s)},
            "recording": {
                "video_id": bundle.video_id,
                "canonical_video_path": str(bundle.video_path),
            },
            "evidence_package_id": evidence_package_id,
            "evidence": _evidence_reference(evidence),
            "proposal_generator_run": dict(proposal_generator_run)
            if proposal_generator_run is not None
            else None,
        }
        if extra:
            selection.update(dict(extra))
        digest_selection = _without_locators(selection)
        digest_selection["ordinal"] = ordinal
        item_id = "table-evidence-" + _digest(digest_selection)[:24]
        selection["selection_id"] = item_id
        item = ReviewItem(
            item_id=item_id,
            source_asset_id=bundle.item.source_asset_id,
            kind=selection_source,
            prompt=(
                f"Review table evidence selected by {selection_source} for "
                f"{bundle.item.source_asset_id} at {time_s:.3f}s."
            ),
        )
        digest_selection["selection_id"] = item_id
        return _Candidate(item, selection, digest_selection)

    def _selection_core(
        self, inputs: Sequence[ReviewInput], candidates: Sequence[_Candidate]
    ) -> dict[str, Any]:
        runs: dict[str, Mapping[str, Any]] = {}
        for candidate in candidates:
            run = candidate.selection.get("proposal_generator_run")
            if isinstance(run, Mapping):
                runs[str(run["proposal_generator_run_id"])] = run
        return {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "task": TABLE_EVIDENCE_TASK,
            "inputs": [
                {
                    "source_asset_id": item.source_asset_id,
                    "recording_id": item.recording_id,
                    "source_sha256": item.source_sha256,
                    "task_enrollment_id": item.task_enrollment_id,
                }
                for item in sorted(
                    inputs, key=lambda value: (value.source_asset_id, value.recording_id)
                )
            ],
            "proposal_generator_runs": [runs[key] for key in sorted(runs)],
            "selections": [candidate.selection for candidate in candidates],
        }


class TableObservationReviewAdapter(TableEvidenceReviewAdapter):
    """Review adapter that promotes selected evidence to table-observation artifacts."""

    def finalize(
        self,
        task: str,
        inputs: Sequence[ReviewInput],
        items: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> TaskArtifacts:
        artifacts = super().finalize(task, inputs, items, staging_dir)
        return TaskArtifacts(artifacts.staged_files, split_approval_required=True)


def _annotation_record(
    candidate: _Candidate, decision: Mapping[str, Any], reviewer: str
) -> dict[str, Any]:
    selection = candidate.selection
    evidence = selection["evidence"]
    annotation_set_id = (
        "annotation-set-"
        + _digest(
            {"selection_id": selection["selection_id"], "source": selection["source_asset_id"]}
        )[:24]
    )
    frame_references = evidence.get("frame_references", [])
    if not isinstance(frame_references, list):
        raise ReviewRunError(f"Evidence frame references are invalid for {candidate.item.item_id}.")
    observed_cards = _observed_cards(
        decision.get("observed_cards", decision.get("cards", [])),
        frame_references=frame_references,
        selection_id=selection["selection_id"],
    )
    package_id = evidence.get("package_id")
    source = (
        {"package_id": package_id}
        if isinstance(package_id, str) and package_id
        else {"recording_id": selection["recording_id"]}
    )
    draft: dict[str, Any] = {
        "schema_version": TABLE_OBSERVATION_ANNOTATION_SCHEMA_VERSION,
        "annotation_set_id": annotation_set_id,
        "source": source,
        "observed_cards": observed_cards,
        "event_review": "unreviewed",
        "review_state": "draft",
    }
    snippet = evidence.get("video_snippet")
    if isinstance(snippet, Mapping):
        start_s = float(selection["recording_range"]["start_s"])
        end_s = float(selection["recording_range"]["end_s"])
        start_ms = max(0, int(round(start_s * 1000)))
        end_ms = max(start_ms + 1, int(round(end_s * 1000)))
        draft["video_snippet"] = {
            "video_snippet_id": snippet["video_snippet_id"],
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
    event_decision = _event_decision(decision)
    reviewed = dict(draft)
    reviewed["event_review"] = (
        "confirmed_card_play" if event_decision == "confirm_card_play" else "false_event_proposal"
    )
    reviewed["review_state"] = "reviewed"
    source_annotation_sha256 = _digest(draft)
    review_id = (
        "review-"
        + _digest(
            {
                "annotation_set_id": annotation_set_id,
                "source_annotation_sha256": source_annotation_sha256,
                "event_decision": event_decision,
                "reviewer": reviewer,
            }
        )[:24]
    )
    notes = decision.get("notes")
    review = {
        "schema_version": TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION,
        "review_id": review_id,
        "annotation_set_id": annotation_set_id,
        "source_annotation_sha256": source_annotation_sha256,
        "event_decision": event_decision,
        "reviewer": reviewer,
        "reviewed_at": _now(),
        "reviewed_annotation": reviewed,
        "notes": notes if isinstance(notes, str) else None,
    }
    return {
        "selection": selection,
        "selection_id": selection["selection_id"],
        "annotation": draft,
        "reviewed_annotation": reviewed,
        "review": review,
        "event_decision": event_decision,
    }


def _event_decision(decision: Mapping[str, Any]) -> str:
    explicit = decision.get("event_decision")
    if explicit in {"confirm_card_play", "reject_event"}:
        return str(explicit)
    event_review = decision.get("event_review")
    if event_review == "confirmed_card_play":
        return "confirm_card_play"
    if event_review in {
        "false_event_proposal",
        "no_visible_cards",
        "card_not_visible",
        "visible_but_not_identifiable",
        "ambiguous_card",
        "insufficient_visual_evidence",
    }:
        return "reject_event"
    return "confirm_card_play" if decision.get("outcome") in _ACCEPTED_OUTCOMES else "reject_event"


def _observed_cards(
    value: Any,
    *,
    frame_references: Sequence[Mapping[str, Any]],
    selection_id: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReviewRunError(f"Observed cards for {selection_id} must be a list.")
    aliases = {
        str(reference.get("frame_id")): str(reference.get("frame_id"))
        for reference in frame_references
        if isinstance(reference.get("frame_id"), str)
    }
    aliases.update(
        {
            str(reference.get("part_name")): str(reference.get("frame_id"))
            for reference in frame_references
            if isinstance(reference.get("part_name"), str)
            and isinstance(reference.get("frame_id"), str)
        }
    )
    result: list[dict[str, Any]] = []
    for index, raw_card in enumerate(value):
        if not isinstance(raw_card, Mapping):
            raise ReviewRunError(f"Observed card {index} for {selection_id} must be an object.")
        identity = raw_card.get("visual_card_identity")
        if identity is not None and (
            not isinstance(identity, str) or identity not in _CARD_IDENTITIES
        ):
            raise ReviewRunError(f"Observed card {index} has an invalid visual card identity.")
        raw_frames = raw_card.get("frame_observations", raw_card.get("frames"))
        if raw_frames is None:
            raw_frames = list(frame_references)
        if not isinstance(raw_frames, list) or not raw_frames:
            raise ReviewRunError(
                f"Observed card {index} for {selection_id} needs frame observations."
            )
        card_bbox = raw_card.get("bbox")
        frame_observations: list[dict[str, Any]] = []
        seen_frame_ids: set[str] = set()
        for frame_index, raw_frame in enumerate(raw_frames):
            if isinstance(raw_frame, str):
                raw_frame = {"frame_id": raw_frame}
            if not isinstance(raw_frame, Mapping):
                raise ReviewRunError(
                    f"Frame observation {frame_index} for card {index} must be an object."
                )
            frame_id = raw_frame.get("frame_id", raw_frame.get("part_name"))
            if not isinstance(frame_id, str) or not frame_id:
                raise ReviewRunError(
                    f"Frame observation {frame_index} for card {index} needs a frame_id."
                )
            frame_id = aliases.get(frame_id, frame_id)
            if frame_id in seen_frame_ids:
                raise ReviewRunError(f"Observed card {index} repeats frame {frame_id}.")
            seen_frame_ids.add(frame_id)
            bbox_value = raw_frame.get("bbox", card_bbox)
            bbox = _bbox(bbox_value, f"frame observation {frame_index} for card {index}")
            usable = raw_frame.get("usable_for_identity", identity is not None and bbox is not None)
            if not isinstance(usable, bool):
                raise ReviewRunError("usable_for_identity must be a boolean.")
            tags = raw_frame.get("tags", raw_card.get("tags", raw_card.get("quality_tags", [])))
            if not isinstance(tags, list) or any(
                not isinstance(tag, str) or not tag for tag in tags
            ):
                raise ReviewRunError("Frame observation tags must be a list of non-empty strings.")
            frame: dict[str, Any] = {
                "frame_id": frame_id,
                "bbox": bbox,
                "usable_for_identity": usable,
                "tags": sorted(set(tags)),
            }
            if raw_frame.get("observation_id") is not None:
                observation_id = raw_frame["observation_id"]
                if not isinstance(observation_id, str) or not observation_id:
                    raise ReviewRunError("observation_id must be a non-empty identifier.")
                frame["observation_id"] = observation_id
            frame_observations.append(frame)
        visibility = raw_card.get("visibility")
        if visibility is None:
            visibility = (
                "identifiable"
                if identity is not None
                else (
                    "visible_but_not_identifiable"
                    if any(frame["bbox"] is not None for frame in frame_observations)
                    else "card_not_visible"
                )
            )
        if visibility not in _VISIBILITY_STATES:
            raise ReviewRunError(f"Observed card {index} has an invalid visibility.")
        if visibility == "identifiable" and identity is None:
            raise ReviewRunError(f"Identifiable observed card {index} needs a card identity.")
        if visibility != "identifiable" and identity is not None:
            raise ReviewRunError(f"Non-identifiable observed card {index} cannot have an identity.")
        if visibility != "identifiable" and any(
            frame["usable_for_identity"] for frame in frame_observations
        ):
            raise ReviewRunError(
                f"Non-identifiable observed card {index} cannot have identity-usable frames."
            )
        if visibility == "identifiable" and not any(
            frame["usable_for_identity"] for frame in frame_observations
        ):
            raise ReviewRunError(
                f"Identifiable observed card {index} needs an identity-usable frame."
            )
        observed_card_id = raw_card.get("observed_card_id")
        if observed_card_id is None:
            observed_card_id = (
                "observed-card-" + _digest({"selection_id": selection_id, "index": index})[:24]
            )
        if (
            not isinstance(observed_card_id, str)
            or not observed_card_id
            or any(character in observed_card_id for character in "/\\\x00")
        ):
            raise ReviewRunError(f"Observed card {index} has an invalid observed_card_id.")
        became_newly_visible = raw_card.get("became_newly_visible", False)
        if not isinstance(became_newly_visible, bool):
            raise ReviewRunError("became_newly_visible must be a boolean.")
        active_area = raw_card.get("active_area_class", "not_applicable")
        if active_area not in _ACTIVE_AREA_CLASSES:
            raise ReviewRunError(f"Observed card {index} has an invalid active_area_class.")
        card: dict[str, Any] = {
            "observed_card_id": observed_card_id,
            "visual_card_identity": identity,
            "visibility": visibility,
            "frame_observations": frame_observations,
            "became_newly_visible": became_newly_visible,
            "active_area_class": active_area,
            "card_tracklet_id": _optional_identifier_value(raw_card.get("card_tracklet_id")),
            "movement": _optional_enum_value(raw_card.get("movement"), _MOVEMENT_STATES),
            "occlusion": _optional_enum_value(raw_card.get("occlusion"), _OCCLUSION_STATES),
        }
        result.append(card)
    ids = [card["observed_card_id"] for card in result]
    if len(ids) != len(set(ids)):
        raise ReviewRunError(f"Observed cards for {selection_id} contain duplicate IDs.")
    return result


def _bbox(value: Any, field: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ReviewRunError(f"{field} bbox must be null or four coordinates.")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ReviewRunError(f"{field} bbox coordinates must be integers.")
    result = list(value)
    if result[0] < 0 or result[1] < 0 or result[2] <= result[0] or result[3] <= result[1]:
        raise ReviewRunError(f"{field} bbox must be a positive rectangle.")
    return result


def _optional_identifier_value(value: Any) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "/\\\x00")
    ):
        raise ReviewRunError("Optional identifier is invalid.")
    return value


def _optional_enum_value(value: Any, choices: frozenset[str]) -> str | None:
    if value is None:
        return None
    if value not in choices:
        raise ReviewRunError(f"Value must be one of: {', '.join(sorted(choices))}.")
    return str(value)


def _dataset_payload(
    records: Sequence[Mapping[str, Any]],
    *,
    inputs: Sequence[ReviewInput],
    selection_digest: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    sources = {
        item.source_asset_id: _read_json(
            Path(item.bundle_path) / "source-record.json", "source record"
        )
        for item in inputs
    }
    entries: list[dict[str, Any]] = []
    unassigned: list[dict[str, Any]] = []
    for record in records:
        annotation = record["reviewed_annotation"]
        source_id = record["selection"]["source_asset_id"]
        source = sources[source_id]
        record_entries = 0
        for card in annotation["observed_cards"]:
            if card["visibility"] != "identifiable" or card["visual_card_identity"] is None:
                continue
            for frame in card["frame_observations"]:
                if not frame["usable_for_identity"] or frame["bbox"] is None:
                    continue
                entry_id = ":".join(
                    (annotation["annotation_set_id"], card["observed_card_id"], frame["frame_id"])
                )
                entries.append(
                    {
                        "dataset_item_id": entry_id,
                        "source_asset_id": source_id,
                        "source_sha256": source["sha256"],
                        "annotation_set_id": annotation["annotation_set_id"],
                        "review_id": record["review"]["review_id"],
                        "eligibility": {
                            "schema_version": "eligibility/v1",
                            "source_asset_id": source_id,
                            "state": "eligible",
                            "source_permission": source["source_permission"],
                            "allowed_uses": list(source["allowed_uses"]),
                            "review_state": "reviewed",
                            "annotation_set_id": annotation["annotation_set_id"],
                            "review_id": record["review"]["review_id"],
                            "intended_use": _intended_use(source["allowed_uses"]),
                            "reason": None,
                        },
                        "target_schema": TABLE_OBSERVATION_ANNOTATION_SCHEMA_VERSION,
                        "group_keys": _group_keys(source),
                        "inclusion_reason": (
                            f"Reviewed {annotation['event_review']} table observation with an "
                            "identity-usable frame."
                        ),
                        "transform_version": TABLE_DATASET_TRANSFORM_VERSION,
                        "source_frame_id": frame["frame_id"],
                        "observed_card_id": card["observed_card_id"],
                        "bbox": frame["bbox"],
                        "visual_card_identity": card["visual_card_identity"],
                        "quality_tags": frame["tags"],
                    }
                )
                record_entries += 1
        if record_entries == 0:
            unassigned.append(
                {
                    "annotation_set_id": annotation["annotation_set_id"],
                    "reason": "no_identity_usable_observed_card",
                }
            )
    entries.sort(key=lambda value: value["dataset_item_id"])
    unassigned.sort(key=lambda value: (value["annotation_set_id"], value["reason"]))
    group_key_names = sorted({key for entry in entries for key, _ in entry["group_keys"]})
    allowed_use_filter = sorted(
        {use for source in sources.values() for use in source.get("allowed_uses", [])}
    )
    dataset_version_id = "table-evidence-" + selection_digest[:20]
    digest_core = {
        "schema_version": DATASET_VERSION_SCHEMA_VERSION,
        "task": TABLE_DATASET_TASK,
        "target_schema": TABLE_OBSERVATION_ANNOTATION_SCHEMA_VERSION,
        "entries": [
            _dataset_entry_digest_mapping(entry)
            for entry in sorted(entries, key=lambda value: value["dataset_item_id"])
        ],
        "allowed_use_filter": allowed_use_filter,
        "group_key_names": group_key_names,
        "derived_artifact_transform_version": TABLE_DATASET_TRANSFORM_VERSION,
        "creation_code_revision": "doko-operations-m8",
        "dirty_state": True,
        "deck_design_version": None,
        "card_set_version": None,
    }
    payload = {
        **digest_core,
        "dataset_version_id": dataset_version_id,
        "created_at": None,
        "dataset_version_digest": _digest(digest_core),
    }
    return payload, entries, unassigned


def _dataset_entry_digest_mapping(entry: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(entry)
    value["group_keys"] = sorted(value["group_keys"])
    eligibility = dict(value["eligibility"])
    eligibility["allowed_uses"] = sorted(eligibility["allowed_uses"])
    value["eligibility"] = eligibility
    return value


def _intended_use(allowed_uses: Sequence[str]) -> str:
    for use in ("train", "validation", "test", "evaluation"):
        if use in allowed_uses:
            return use
    raise ReviewRunError("A reviewed source has no allowed intended use.")


def _group_keys(source: Mapping[str, Any]) -> list[list[str]]:
    values = [("source_lineage", str(source["source_asset_id"]))]
    for field in ("session_id", "game_id", "table_setup"):
        value = source.get(field)
        if isinstance(value, str) and value:
            values.append((field, value))
    return [list(value) for value in sorted(values)]


def _split_payload(
    dataset: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], selection_digest: str
) -> dict[str, Any]:
    core = {
        "schema_version": TABLE_DATASET_SPLIT_SCHEMA_VERSION,
        "dataset_version_id": dataset["dataset_version_id"],
        "dataset_version_digest": dataset["dataset_version_digest"],
        "group_key_names": sorted(dataset["group_key_names"]),
        "seed": 42,
        "train": [],
        "validation": [],
        "test": [],
        "unassigned": sorted(entry["dataset_item_id"] for entry in entries),
    }
    return {
        **core,
        "split_version_id": "table-evidence-split-" + selection_digest[:20],
        "split_version_digest": _digest(core),
    }


def _dataset_coverage(
    records: Sequence[Mapping[str, Any]],
    *,
    inputs: Sequence[ReviewInput],
    dataset_payload: Mapping[str, Any],
    unassigned: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    sources = {
        item.source_asset_id: _read_json(
            Path(item.bundle_path) / "source-record.json", "source record"
        )
        for item in inputs
    }
    event_reviews = [record["reviewed_annotation"]["event_review"] for record in records]
    identities: list[str] = []
    visibilities: list[str] = []
    active_areas: list[str] = []
    movements: list[str] = []
    occlusions: list[str] = []
    newly_visible: list[str] = []
    quality_tags: list[str] = []
    crop_sizes: list[str] = []
    visible_card_counts: list[str] = []
    selected_frame_count = 0
    snippet_count = 0
    evidence_complete = {
        record["reviewed_annotation"]["source"]["package_id"]: True
        for record in records
        if record["reviewed_annotation"]["source"].get("package_id")
    }
    for record in records:
        annotation = record["reviewed_annotation"]
        selected_frame_count += len(
            {
                frame["frame_id"]
                for card in annotation["observed_cards"]
                for frame in card["frame_observations"]
            }
        )
        snippet_count += annotation.get("video_snippet") is not None
        visible_card_counts.append(str(len(annotation["observed_cards"])))
        for card in annotation["observed_cards"]:
            visibilities.append(card["visibility"])
            if card["visual_card_identity"] is not None:
                identities.append(card["visual_card_identity"])
            active_areas.append(card["active_area_class"])
            if card["movement"] is not None:
                movements.append(card["movement"])
            if card["occlusion"] is not None:
                occlusions.append(card["occlusion"])
            newly_visible.append(str(card["became_newly_visible"]).lower())
            for frame in card["frame_observations"]:
                quality_tags.extend(frame["tags"])
                if frame["bbox"] is not None:
                    crop_sizes.append(
                        f"{frame['bbox'][2] - frame['bbox'][0]}x"
                        f"{frame['bbox'][3] - frame['bbox'][1]}"
                    )
    source_values: dict[str, list[str]] = {
        "session_id": [],
        "game_id": [],
        "round_id": [],
        "table_setup": [],
        "content_type": [],
        "device_class": [],
        "deck_design": [],
        "physical_card_id": [],
    }
    for source in sources.values():
        metadata = source.get("collection_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        values = {
            "session_id": source.get("session_id"),
            "game_id": source.get("game_id"),
            "round_id": source.get("round_id"),
            "table_setup": source.get("table_setup"),
            "content_type": source.get("content_type"),
            "device_class": metadata.get("device_class", source.get("device_class")),
            "deck_design": metadata.get("deck_design", source.get("deck_design")),
            "physical_card_id": metadata.get("physical_card_id", source.get("physical_card_id")),
        }
        for field, value in values.items():
            if value is not None:
                source_values[field].append(str(value))
    complete = {"complete": 0, "incomplete": 0, "unknown": 0}
    for value in evidence_complete.values():
        complete["complete" if value else "incomplete"] += 1
    complete["unknown"] = len(
        {
            record["reviewed_annotation"]["source"].get("recording_id")
            for record in records
            if record["reviewed_annotation"]["source"].get("package_id") is None
        }
        - {None}
    )
    return {
        "schema_version": TABLE_DATASET_COVERAGE_SCHEMA_VERSION,
        "dataset_version_id": dataset_payload["dataset_version_id"],
        "dataset_version_digest": dataset_payload["dataset_version_digest"],
        "counts": {
            "dataset_entries": len(dataset_payload["entries"]),
            "annotation_sets": len(records),
            "source_assets": len(sources),
            "selected_frames": selected_frame_count,
            "video_snippets": snippet_count,
            "reviewed_card_tracklets": 0,
            "unassigned": len(unassigned),
            "excluded": 0,
        },
        "event_review": _counter(event_reviews),
        "visual_card_identity": _counter(identities),
        "visibility": _counter(visibilities),
        "quality": {
            "tags": _counter(quality_tags),
            "crop_sizes": _counter(crop_sizes),
            "newly_visible": _counter(newly_visible),
            "active_area": _counter(active_areas),
            "movement": _counter(movements),
            "occlusion": _counter(occlusions),
        },
        "visible_card_count": _counter(visible_card_counts),
        "evidence_completeness": complete,
        "source_coverage": {field: _counter(values) for field, values in source_values.items()},
        "unassigned": [dict(item) for item in unassigned],
        "excluded": [],
    }


def _counter(values: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _dataset_coverage_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# TableEvidenceAnalyzer dataset coverage",
        "",
        f"- Dataset version: `{payload['dataset_version_id']}`",
        f"- Dataset digest: `{payload['dataset_version_digest']}`",
        "",
        "## Counts",
        "",
    ]
    lines.extend(f"- {name}: {value}" for name, value in sorted(payload["counts"].items()))
    lines.extend(["", "## Event review", ""])
    lines.extend(f"- {name}: {value}" for name, value in payload["event_review"].items())
    lines.extend(["", "## Evidence completeness", ""])
    lines.extend(f"- {name}: {value}" for name, value in payload["evidence_completeness"].items())
    lines.extend(["", "## Unassigned", ""])
    if payload["unassigned"]:
        lines.extend(f"- {item}" for item in payload["unassigned"])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _dataset_validation(
    records: Sequence[Mapping[str, Any]],
    *,
    dataset_payload: Mapping[str, Any],
    dataset_entries: Sequence[Mapping[str, Any]],
    unassigned: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    for record in records:
        annotation = record["reviewed_annotation"]
        review = record["review"]
        if annotation["review_state"] != "reviewed":
            errors.append(f"Annotation {annotation['annotation_set_id']} is not reviewed.")
        if review["annotation_set_id"] != annotation["annotation_set_id"]:
            errors.append(f"Review {review['review_id']} does not match its annotation.")
        if review["source_annotation_sha256"] != _digest(record["annotation"]):
            errors.append(f"Review {review['review_id']} has a changed source annotation.")
    warnings = []
    if not dataset_entries:
        warnings.append(
            "No eligible identity samples were assembled; reviewed evidence is retained."
        )
    if unassigned:
        warnings.append(f"{len(unassigned)} reviewed annotation set has no identity-usable sample.")
    return {
        "schema_version": TABLE_DATASET_VALIDATION_SCHEMA_VERSION,
        "dataset_version_id": dataset_payload["dataset_version_id"],
        "dataset_version_digest": dataset_payload["dataset_version_digest"],
        "checked_entry_count": len(dataset_entries),
        "valid": not errors,
        "errors": sorted(errors),
        "warnings": sorted(warnings),
    }


def _lifecycle_receipt(
    records: Sequence[Mapping[str, Any]],
    *,
    inputs: Sequence[ReviewInput],
    dataset_payload: Mapping[str, Any],
    split_payload: Mapping[str, Any],
    selection_digest: str,
) -> dict[str, Any]:
    source_refs = [
        {"kind": "source_asset", "id": item.source_asset_id, "digest": item.source_sha256}
        for item in inputs
    ]
    package_refs = [
        {
            "kind": "evidence_package",
            "id": record["selection"]["evidence_package_id"],
            "digest": None,
        }
        for record in records
        if record["selection"].get("evidence_package_id")
    ]
    run_refs = {
        run["proposal_generator_run_id"]: run
        for record in records
        for run in [record["selection"].get("proposal_generator_run")]
        if isinstance(run, Mapping)
    }
    annotation_refs = [
        {
            "kind": "annotation_set",
            "id": record["reviewed_annotation"]["annotation_set_id"],
            "digest": _digest(record["reviewed_annotation"]),
        }
        for record in records
    ]
    review_refs = [
        {
            "kind": "review",
            "id": record["review"]["review_id"],
            "digest": _digest(record["review"]),
        }
        for record in records
    ]
    inputs_refs = _unique_refs((*source_refs, *package_refs))
    dependencies = _unique_refs(
        (
            *source_refs,
            *package_refs,
            *[
                {"kind": "derived_artifact", "id": run_id, "digest": run["run_digest"]}
                for run_id, run in sorted(run_refs.items())
            ],
        )
    )
    outputs = _unique_refs(
        (
            *annotation_refs,
            *review_refs,
            {
                "kind": "dataset_version",
                "id": dataset_payload["dataset_version_id"],
                "digest": dataset_payload["dataset_version_digest"],
            },
            {
                "kind": "split_version",
                "id": split_payload["split_version_id"],
                "digest": split_payload["split_version_digest"],
            },
        )
    )
    metadata = {
        "task": TABLE_EVIDENCE_TASK,
        "selection_digest": selection_digest,
        "reviewed_item_count": len(records),
        "eligible_dataset_entry_count": len(dataset_payload["entries"]),
        "lifecycle_state": "eligible" if dataset_payload["entries"] else "reviewed",
        "proposal_generator_run_ids": sorted(run_refs),
    }
    core = {
        "schema_version": "lifecycle-receipt/v1",
        "receipt_type": "annotation_application",
        "operator": records[0]["review"]["reviewer"] if records else "review-run",
        "inputs": inputs_refs,
        "outputs": outputs,
        "dependencies": dependencies,
        "metadata": metadata,
    }
    return {
        **core,
        "receipt_id": "receipt-table-evidence-" + selection_digest[:20],
        "occurred_at": _now(),
        "receipt_digest": _digest(core),
    }


def _unique_refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        key = (str(value["kind"]), str(value["id"]))
        existing = result.get(key)
        if existing is not None and existing.get("digest") != value.get("digest"):
            raise ReviewRunError(f"Lifecycle reference {key[0]}:{key[1]} has conflicting digests.")
        result[key] = dict(value)
    return [result[key] for key in sorted(result)]


def _review_report(
    records: Sequence[Mapping[str, Any]],
    *,
    selection_digest: str,
    dataset_payload: Mapping[str, Any],
    unassigned: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": REVIEW_REPORT_SCHEMA_VERSION,
        "task": TABLE_EVIDENCE_TASK,
        "selection_digest": selection_digest,
        "review_state": "reviewed",
        "lifecycle_state": "eligible" if dataset_payload["entries"] else "reviewed",
        "annotation_sets": [
            {
                "selection_id": record["selection_id"],
                "selection_source": record["selection"]["selection_source"],
                "annotation_set_id": record["reviewed_annotation"]["annotation_set_id"],
                "review_id": record["review"]["review_id"],
                "event_decision": record["event_decision"],
                "event_review": record["reviewed_annotation"]["event_review"],
                "observed_card_count": len(record["reviewed_annotation"]["observed_cards"]),
                "selected_frame_count": len(
                    {
                        frame["frame_id"]
                        for card in record["reviewed_annotation"]["observed_cards"]
                        for frame in card["frame_observations"]
                    }
                ),
                "video_snippet_available": record["reviewed_annotation"].get("video_snippet")
                is not None,
            }
            for record in records
        ],
        "dataset_version_id": dataset_payload["dataset_version_id"],
        "dataset_version_digest": dataset_payload["dataset_version_digest"],
        "eligible_dataset_entry_count": len(dataset_payload["entries"]),
        "unassigned_annotation_count": len(unassigned),
    }


def _review_report_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Table-observation review report",
        "",
        f"- Task: `{payload['task']}`",
        f"- Review state: `{payload['review_state']}`",
        f"- Lifecycle state: `{payload['lifecycle_state']}`",
        f"- Dataset entries: `{payload['eligible_dataset_entry_count']}`",
        "",
        "## Annotation sets",
        "",
    ]
    for item in payload["annotation_sets"]:
        lines.append(
            f"- `{item['annotation_set_id']}`: `{item['event_review']}`, "
            f"{item['observed_card_count']} observed cards, "
            f"{item['selected_frame_count']} selected frames"
        )
    lines.extend(
        ["", f"- Unassigned annotation sets: `{payload['unassigned_annotation_count']}`", ""]
    )
    return "\n".join(lines)


def _normalize_operator_intervals(
    value: Mapping[str, Sequence[Mapping[str, Any]]] | Sequence[Mapping[str, Any]] | Any,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    if value in (None, ()):
        return {}
    result: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(value, Mapping):
        if isinstance(value.get("intervals"), list):
            value = value["intervals"]
        else:
            for source_id, intervals in value.items():
                if (
                    not isinstance(source_id, str)
                    or not isinstance(intervals, Sequence)
                    or isinstance(intervals, (str, bytes))
                ):
                    raise ReviewRunError("Operator intervals must map source asset IDs to lists.")
                result[source_id] = [
                    _validate_interval(interval, source_id) for interval in intervals
                ]
            return {key: tuple(values) for key, values in sorted(result.items())}
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReviewRunError("Operator intervals must be a list or mapping.")
    for interval in value:
        if not isinstance(interval, Mapping) or not isinstance(
            interval.get("source_asset_id"), str
        ):
            raise ReviewRunError("Each operator interval needs a source_asset_id.")
        source_id = interval["source_asset_id"]
        result.setdefault(source_id, []).append(_validate_interval(interval, source_id))
    return {key: tuple(values) for key, values in sorted(result.items())}


def _validate_interval(interval: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    if "start_s" not in interval or "end_s" not in interval:
        raise ReviewRunError(f"Operator interval for {source_id} needs start_s and end_s.")
    return dict(interval)


def _proposal_run_reference(
    proposal: Mapping[str, Any], descriptor: Mapping[str, Any], item: ReviewInput
) -> dict[str, Any]:
    required = ("proposal_generator_run_id", "output_sha256", "model_bundle_id", "weights_sha256")
    if any(not isinstance(proposal.get(field), str) for field in required):
        raise ReviewRunError(
            "Proposal generator run is incomplete for "
            f"{item.source_asset_id}; full lineage is required."
        )
    return {
        "proposal_generator_run_id": proposal["proposal_generator_run_id"],
        "source_asset_id": item.source_asset_id,
        "source_sha256": item.source_sha256,
        "output_sha256": proposal["output_sha256"],
        "model_bundle_id": proposal["model_bundle_id"],
        "weights_sha256": proposal["weights_sha256"],
        "platform": (
            proposal.get("execution_environment", {}).get("platform")
            if isinstance(proposal.get("execution_environment"), Mapping)
            else None
        ),
        "run_digest": _digest(proposal),
        "member_sha256": descriptor.get("sha256"),
    }


def _lowest_negative(proposal: Mapping[str, Any]) -> tuple[float, float] | None:
    probabilities = proposal.get("probabilities")
    decoder = proposal.get("decoder")
    threshold = decoder.get("threshold") if isinstance(decoder, Mapping) else None
    if not isinstance(probabilities, list) or not isinstance(threshold, (int, float)):
        return None
    values: list[tuple[float, float]] = []
    for sample in probabilities:
        if not isinstance(sample, Mapping):
            continue
        time_s = sample.get("time_s")
        probability = sample.get("probability")
        if (
            isinstance(time_s, (int, float))
            and not isinstance(time_s, bool)
            and isinstance(probability, (int, float))
            and not isinstance(probability, bool)
            and math.isfinite(time_s)
            and math.isfinite(probability)
            and time_s >= 0
            and 0 <= probability < threshold
        ):
            values.append((float(time_s), float(probability)))
    if not values:
        return None
    return min(values, key=lambda value: (value[1], value[0]))


def _duration_s(bundle: _BundleData, packages: Sequence[Mapping[str, Any]]) -> float:
    for field in ("duration_s", "duration_seconds"):
        value = bundle.source.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return max(float(value), 0.001)
    value = bundle.source.get("duration_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return max(float(value) / 1000, 0.001)
    times: list[float] = []
    for proposal in bundle.proposals:
        for field in ("probabilities", "event_proposals"):
            values = proposal.get(field)
            if isinstance(values, list):
                times.extend(
                    float(item["time_s"])
                    for item in values
                    if isinstance(item, Mapping)
                    and isinstance(item.get("time_s"), (int, float))
                    and not isinstance(item.get("time_s"), bool)
                    and math.isfinite(item["time_s"])
                )
    times.extend(float(package["event_time_s"]) for package in packages)
    return max((*times, 0.0)) + 1.0


def _coverage_times(
    duration_s: float, interval_s: float, proposal_times: Sequence[float]
) -> list[float]:
    count = max(1, math.ceil(duration_s / interval_s))
    grid = [min(index * interval_s, max(0.0, duration_s - 0.001)) for index in range(count)]
    absent = [
        time_s
        for time_s in grid
        if all(abs(time_s - proposal_time) > 0.25 for proposal_time in proposal_times)
    ]
    if absent:
        return absent
    for denominator in range(2, 102):
        candidate = duration_s / denominator
        if all(abs(candidate - proposal_time) > 0.25 for proposal_time in proposal_times):
            return [candidate]
    return grid[:1]


def _package_matches(
    manifest: Mapping[str, Any], path: Path, source: Mapping[str, Any], item: ReviewInput
) -> bool:
    for field in ("source_asset_id", "recording_id"):
        value = manifest.get(field)
        if value is not None and value not in {item.source_asset_id, item.recording_id}:
            return False
    package_session = (
        (manifest.get("session") or {}).get("session_id")
        if isinstance(manifest.get("session"), Mapping)
        else None
    )
    source_session = source.get("session_id")
    if (
        package_session is not None
        and source_session is not None
        and package_session != source_session
    ):
        return False
    return bool(
        package_session
        or manifest.get("source_asset_id")
        or path.parent.name in {item.source_asset_id, item.recording_id}
    )


def _materialize_package(
    package_path: Path, manifest: Mapping[str, Any], item: ReviewInput
) -> dict[str, Any]:
    package_id = manifest.get("package_id")
    event = manifest.get("event")
    frames = manifest.get("frames")
    if (
        not isinstance(package_id, str)
        or not package_id
        or not isinstance(event, Mapping)
        or not isinstance(frames, list)
    ):
        raise ReviewRunError(
            f"Evidence package is incomplete for {item.source_asset_id}: {package_path}"
        )
    event_time_ms = _finite_number(event.get("event_time_ms"), "evidence package event_time_ms")
    frame_refs: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping) or not _safe_part_name(frame.get("part_name")):
            raise ReviewRunError(f"Evidence frame {index} is invalid in {package_path}")
        frame_path = package_path / "frames" / f"{frame['part_name']}.jpg"
        _verify_declared_file(frame_path, frame, f"Evidence frame {frame['part_name']}")
        frame_core = {
            "package_id": package_id,
            "part_name": frame["part_name"],
            "sha256": frame.get("sha256"),
        }
        frame_refs.append(
            {
                "frame_id": "frame-" + _digest(frame_core)[:24],
                "part_name": frame["part_name"],
                "canonical_path": str(frame_path),
                "target_offset_ms": frame.get("target_offset_ms"),
                "actual_offset_ms": frame.get("actual_offset_ms"),
                "session_elapsed_ms": frame.get("session_elapsed_ms"),
                "byte_length": frame["byte_length"],
                "sha256": frame["sha256"],
            }
        )
    snippet = manifest.get("video_snippet")
    snippet_ref: dict[str, Any] | None = None
    if isinstance(snippet, Mapping) and snippet.get("capture_complete"):
        part_name = snippet.get("part_name")
        if not _safe_part_name(part_name):
            raise ReviewRunError(f"Evidence video snippet is invalid in {package_path}")
        snippet_path = package_path / "video" / f"{part_name}.mp4"
        if not snippet_path.is_file():
            snippet_path = package_path / "snippet.mp4"
        _verify_declared_file(snippet_path, snippet, "Evidence video snippet")
        snippet_ref = {
            "video_snippet_id": "snippet-"
            + _digest({"package_id": package_id, "part_name": part_name})[:24],
            "part_name": part_name,
            "canonical_path": str(snippet_path),
            "start_offset_ms": snippet.get("start_offset_ms"),
            "end_offset_ms": snippet.get("end_offset_ms"),
            "duration_ms": snippet.get("duration_ms"),
            "byte_length": snippet["byte_length"],
            "sha256": snippet["sha256"],
        }
    offsets = [
        float(frame.get("actual_offset_ms", 0)) / 1000
        for frame in frames
        if isinstance(frame.get("actual_offset_ms"), (int, float))
    ]
    if snippet_ref is not None:
        start_s = event_time_ms / 1000 + float(snippet_ref["start_offset_ms"]) / 1000
        end_s = event_time_ms / 1000 + float(snippet_ref["end_offset_ms"]) / 1000
    elif offsets:
        start_s = event_time_ms / 1000 + min(offsets)
        end_s = event_time_ms / 1000 + max(offsets)
    else:
        start_s = max(0.0, event_time_ms / 1000 - 1.0)
        end_s = event_time_ms / 1000 + 1.0
    return {
        "package_id": package_id,
        "manifest_path": str(package_path / "manifest.json"),
        "event_time_s": _rounded(event_time_ms / 1000),
        "recording_range": [_rounded(max(0.0, start_s)), _rounded(max(end_s, start_s + 0.001))],
        "frame_references": sorted(frame_refs, key=lambda value: value["part_name"]),
        "video_snippet": snippet_ref,
    }


def _nearest_package(
    packages: Sequence[Mapping[str, Any]], time_s: float, window_s: float
) -> Mapping[str, Any] | None:
    matches = [
        package for package in packages if abs(float(package["event_time_s"]) - time_s) <= window_s
    ]
    return (
        min(
            matches,
            key=lambda package: (
                abs(float(package["event_time_s"]) - time_s),
                package["package_id"],
            ),
        )
        if matches
        else None
    )


def _evidence_reference(package: Mapping[str, Any] | None) -> dict[str, Any]:
    if package is None:
        return {"package_id": None, "frame_references": [], "video_snippet": None}
    return {
        "package_id": package["package_id"],
        "manifest_path": package["manifest_path"],
        "frame_references": package["frame_references"],
        "video_snippet": package["video_snippet"],
    }


def _without_locators(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_locators(item)
            for key, item in value.items()
            if key not in {"canonical_video_path", "canonical_path", "manifest_path"}
        }
    if isinstance(value, list):
        return [_without_locators(item) for item in value]
    return value


def _reviewed_document_matches(payload: Mapping[str, Any], path: Path, bundle: _BundleData) -> bool:
    state = payload.get("review_state", payload.get("state", payload.get("status")))
    if state is not None and state not in _REVIEWED_STATES:
        return False
    expected = {
        "source_asset_id": {bundle.item.source_asset_id},
        "recording_id": {bundle.item.recording_id},
        "video_id": {bundle.video_id},
        "video": {bundle.source.get("original_filename")},
    }
    declared = [(field, payload.get(field)) for field in expected if payload.get(field) is not None]
    if any(value not in expected[field] for field, value in declared):
        return False
    return bool(
        declared
        or path.stem
        in {
            bundle.item.source_asset_id,
            bundle.item.recording_id,
            bundle.video_id,
            Path(str(bundle.source.get("original_filename", ""))).stem,
        }
    )


def _coverage_payload(
    selection_core: Mapping[str, Any], candidates: Sequence[_Candidate], selection_digest: str
) -> dict[str, Any]:
    by_source: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate.selection["selection_source"], []).append(candidate)
    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "task": TABLE_EVIDENCE_TASK,
        "selection_digest": selection_digest,
        "total_candidates": len(candidates),
        "selection_sources": [
            {
                "selection_source": source,
                "count": len(by_source[source]),
                "item_ids": [candidate.item.item_id for candidate in by_source[source]],
                "source_asset_ids": sorted(
                    {candidate.selection["source_asset_id"] for candidate in by_source[source]}
                ),
            }
            for source in sorted(by_source, key=lambda value: _SOURCE_ORDER.get(value, 999))
        ],
        "evidence": {
            "packages": len(
                {
                    candidate.selection["evidence_package_id"]
                    for candidate in candidates
                    if candidate.selection["evidence_package_id"]
                }
            ),
            "frame_references": sum(
                len(candidate.selection["evidence"]["frame_references"]) for candidate in candidates
            ),
            "video_snippet_references": sum(
                candidate.selection["evidence"]["video_snippet"] is not None
                for candidate in candidates
            ),
        },
        "proposal_generator_run_ids": [
            run["proposal_generator_run_id"] for run in selection_core["proposal_generator_runs"]
        ],
    }


def _coverage_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Table-evidence selection coverage",
        "",
        f"- Task: `{payload['task']}`",
        f"- Selection digest: `{payload['selection_digest']}`",
        f"- Total candidates: `{payload['total_candidates']}`",
        "",
        "## Selection sources",
        "",
    ]
    for source in payload["selection_sources"]:
        lines.append(f"- `{source['selection_source']}`: {source['count']}")
    lines.extend(
        [
            "",
            "## Evidence references",
            "",
            f"- Packages: {payload['evidence']['packages']}",
            f"- Frame references: {payload['evidence']['frame_references']}",
            f"- Video snippet references: {payload['evidence']['video_snippet_references']}",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "COVERAGE_SCHEMA_VERSION",
    "DATASET_VERSION_SCHEMA_VERSION",
    "SELECTION_SCHEMA_VERSION",
    "TABLE_DATASET_COVERAGE_SCHEMA_VERSION",
    "TABLE_DATASET_SPLIT_SCHEMA_VERSION",
    "TABLE_DATASET_TASK",
    "TABLE_DATASET_VALIDATION_SCHEMA_VERSION",
    "TABLE_EVIDENCE_TASK",
    "TABLE_OBSERVATION_ANNOTATION_SCHEMA_VERSION",
    "TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION",
    "TableEvidenceReviewAdapter",
    "TableObservationReviewAdapter",
    "VALID_SELECTION_SOURCES",
]
