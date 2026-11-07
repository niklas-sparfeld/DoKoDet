"""Build and validate visual identity crop provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from table_evidence_analyzer.pipeline_data import VisualIdentityCropInputProvenance
from table_evidence_analyzer.visual_identity_crop_input import (
    VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION,
    VisualIdentityCropInput,
    VisualIdentityCropInputItem,
)

from dokodetector_backend.pipeline_store import StoredPipelineRevision


@dataclass(frozen=True)
class ValidatedCropContext:
    revision: StoredPipelineRevision
    crop_input: VisualIdentityCropInput
    roots: tuple[Path, ...]
    fingerprint: tuple[tuple[str, int, int, int, int, int, str], ...]


def crop_dependency_fingerprint(
    roots: tuple[Path, ...],
) -> tuple[tuple[str, int, int, int, int, int, str], ...]:
    """Detect edits, replacements, removals, and added members."""
    entries = []
    for root in roots:
        for path in (root, *sorted(root.rglob("*"))):
            stat = path.lstat()
            if path.is_symlink():
                raise OSError("crop validation dependency must not be a symlink")
            entries.append(
                (
                    str(path),
                    stat.st_ino,
                    stat.st_mode,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file() and root.parent.name == "revisions"
                    else "",
                )
            )
    return tuple(entries)


def crop_input_provenance(
    crop_input: VisualIdentityCropInput,
    item: VisualIdentityCropInputItem | None,
) -> VisualIdentityCropInputProvenance | None:
    """Create provenance for one item from the frozen M1 crop input."""
    if item is None:
        return None
    return VisualIdentityCropInputProvenance(
        input_kind=crop_input.input_kind,
        manifest_digest=crop_input.computed_manifest_digest,
        source_revision_id=crop_input.source_revision_id,
        source_revision_digest=crop_input.source_revision_digest,
        source_view_digest=crop_input.source_view_digest,
        source_node_id=crop_input.source_node_id,
        source_node_revision_id=crop_input.source_node_revision_id,
        schema_version=(
            "visual-identity-crop-input-provenance/v3"
            if crop_input.schema_version == VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION
            else "visual-identity-crop-input-provenance/v2"
        ),
    )


def validate_crop_outcome(
    crop_input: VisualIdentityCropInput,
    item: VisualIdentityCropInputItem | None,
    outcome,
) -> None:
    """Reject stale item identity, geometry, or provenance."""
    expected = crop_input_provenance(crop_input, item)
    if expected is None or outcome.crop_input_provenance != expected:
        from doko_operations.derived_view import DerivedViewError

        raise DerivedViewError("the identity crop input lineage changed")
    if item.geometry.to_mapping() != outcome.geometry.to_mapping():
        from doko_operations.derived_view import DerivedViewError

        raise DerivedViewError("the identity crop geometry changed")


def validate_run_crop_provenance(
    output_revision: StoredPipelineRevision,
    outcome,
    *,
    run_store,
    selection_store,
    accepted_source: Callable[[str], tuple[Any, Any]],
    canonical_input_revision: Callable[[Any], StoredPipelineRevision],
    freeze_crop_input: Callable[..., VisualIdentityCropInput],
    validate_frozen_outcome: Callable[[VisualIdentityCropInput, Any], None],
    revision_cache: dict[str, StoredPipelineRevision] | None = None,
) -> VisualIdentityCropInput:
    """Validate persisted run, exact input revision, and frozen crop provenance."""
    from doko_operations.derived_view import DerivedViewError
    from table_evidence_analyzer.visual_identity_crop_input import (
        VisualIdentityCropInputError,
        validate_crop_policy_compatibility,
    )

    provenance = outcome.crop_input_provenance
    run_id = getattr(output_revision.manifest.producer, "run_id", None)
    if provenance is None or not isinstance(run_id, str):
        raise DerivedViewError("the identity crop input provenance is unavailable")
    revision_cache = {} if revision_cache is None else revision_cache
    revision_cache[output_revision.manifest.revision_id] = output_revision
    run = run_store.require(run_id, revision_cache=revision_cache)
    if run.request.crop_input is None or len(run.request.input_revision_ids) != 1:
        raise DerivedViewError("the identity crop input manifest is unavailable")
    accepted, source = accepted_source(run.request.source.recording_id)
    del accepted
    if source != run.request.source:
        raise DerivedViewError("the identity crop input source changed")
    input_revision = canonical_input_revision(run.request)
    input_refs = run.request.input_node_refs or ()
    if len(input_refs) == 1:
        input_ref = input_refs[0]
        revision_cache[input_ref["revision_id"]] = selection_store.read_node_revision(
            input_ref["node_id"], input_ref["revision_id"]
        )
    frozen_input = freeze_crop_input(
        run.request.source.recording_id,
        input_revision,
        source=source,
        requested=run.request.crop_input,
        revision_cache=revision_cache,
        input_node_ref=(run.request.input_node_refs or [None])[0],
    )
    validate_frozen_outcome(frozen_input, outcome)
    try:
        validate_crop_policy_compatibility(
            frozen_input, str((run.request.crop_policy or {}).get("policy_id", ""))
        )
    except VisualIdentityCropInputError as error:
        raise DerivedViewError("the identity crop policy is incompatible") from error
    return frozen_input


__all__ = [
    "ValidatedCropContext",
    "crop_dependency_fingerprint",
    "crop_input_provenance",
    "validate_crop_outcome",
    "validate_run_crop_provenance",
]
