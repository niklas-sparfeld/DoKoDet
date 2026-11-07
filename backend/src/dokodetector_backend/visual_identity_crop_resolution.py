"""Resolve crop bytes from validated, frozen visual identity geometry."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from doko_operations.derived_view import (
    DerivedViewError,
    FrameResolver,
    ResolvedCrop,
    ResolvedCropJpegPreview,
    parse_geometry,
    resolve_crop_jpeg_preview,
    resolve_crop_jpeg_preview_from_cache,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import ProcessorProducer, RecordingVideoSource
from table_evidence_analyzer.visual_identity_crop_input import VisualIdentityCropInput

from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.visual_identity_crop_provenance import (
    ValidatedCropContext,
    crop_dependency_fingerprint,
)


def crop_identity_mapping(crop: ResolvedCrop) -> dict[str, Any]:
    """Return the persisted crop identity fields."""
    mapping = crop.identity_mapping()
    for field in ("exclusion_inputs", "exclusion_decisions", "exclusion_policy"):
        mapping.pop(field, None)
    return mapping


def resolve_geometry_crop(
    *,
    video_path: Path,
    source: RecordingVideoSource,
    frame_identity: Mapping[str, Any],
    geometry: Mapping[str, Any],
    crop_policy: str,
    output_encoding: str,
    resolver: FrameResolver,
    cache: Path,
    lock: RLock,
) -> ResolvedCrop:
    """Resolve a crop using its exact frame identity and validated geometry."""
    with lock:
        frame = resolve_exact_event(
            video_path,
            source=source,
            requested_time_us=int(frame_identity["requested_time_us"]),
            cache=cache,
            resolver=resolver,
            output_encoding=str(frame_identity["output_encoding"]),
        )
        if frame.identity_mapping() != dict(frame_identity):
            raise DerivedViewError("the resolved identity frame changed")
        crop = resolve_visible_region_crop(
            frame,
            parse_geometry(dict(geometry)),
            crop_policy=crop_policy,
            output_encoding=output_encoding,
            cache=cache,
        )
    return crop


def resolve_identity_crop(
    *,
    video_path: Path,
    source: RecordingVideoSource,
    outcome,
    crop_identity,
    resolver: FrameResolver,
    cache: Path,
    lock: RLock,
) -> ResolvedCrop:
    crop = resolve_geometry_crop(
        video_path=video_path,
        source=source,
        frame_identity=outcome.frame_identity.to_mapping(),
        geometry=outcome.geometry.to_mapping(),
        crop_policy=crop_identity.crop_policy,
        output_encoding=crop_identity.output_encoding,
        resolver=resolver,
        cache=cache,
        lock=lock,
    )
    if crop_identity_mapping(crop) != crop_identity.to_mapping():
        raise DerivedViewError("the resolved identity crop changed")
    return crop


def resolve_reviewed_annotation_crop(
    *,
    crop_input: VisualIdentityCropInput,
    item_id: str,
    outcome: Mapping[str, Any],
    source: RecordingVideoSource,
    video_path: Path,
    resolver: FrameResolver,
    cache: Path,
    lock: RLock,
) -> ResolvedCrop:
    """Resolve one annotation crop against exact frozen M1 geometry and identity."""
    item = next((value for value in crop_input.items if value.card_id == item_id), None)
    if item is None or outcome.get("card_id") != item_id:
        raise DerivedViewError("the reviewed identity item is unavailable")
    if (
        outcome.get("frame_identity") != item.frame_identity.to_mapping()
        or outcome.get("geometry") != item.geometry.to_mapping()
    ):
        raise DerivedViewError("the reviewed identity geometry changed")
    crop_identity = outcome.get("crop_identity")
    if not isinstance(crop_identity, Mapping) or crop_identity.get("status") != "usable":
        raise DerivedViewError("the reviewed identity crop is unavailable")
    crop = resolve_geometry_crop(
        video_path=video_path,
        source=source,
        frame_identity=item.frame_identity.to_mapping(),
        geometry=item.geometry.to_mapping(),
        crop_policy=str(crop_identity["crop_policy"]),
        output_encoding=str(crop_identity["output_encoding"]),
        resolver=resolver,
        cache=cache,
        lock=lock,
    )
    if crop_identity_mapping(crop) != crop_identity:
        raise DerivedViewError("the reviewed identity crop changed")
    return crop


def validated_identity_crop_outcome(
    recording_id: str,
    revision_id: str,
    item_id: str,
    *,
    contexts: OrderedDict[str, ValidatedCropContext],
    context_lock: RLock,
    require_revision,
    require_outcome,
    validate_outcome,
    validate_provenance,
    recording_store,
    node_store,
    run_store,
    repository_storage,
) -> tuple[StoredPipelineRevision, Any]:
    """Validate a crop against its exact M1 input and all mutable dependencies."""
    with context_lock:
        context = contexts.get(revision_id)
        if context is not None:
            try:
                current_revision = require_revision(recording_id, revision_id)
                unchanged = crop_dependency_fingerprint(context.roots) == context.fingerprint
            except (OSError, ValueError):
                unchanged = False
                current_revision = None
            if (
                unchanged
                and current_revision is not None
                and current_revision.manifest.content_sha256
                == context.revision.manifest.content_sha256
                and context.revision.manifest.source.recording_id == recording_id
            ):
                outcome = require_outcome(context.revision, item_id)
                validate_outcome(context.crop_input, outcome)
                contexts.move_to_end(revision_id)
                return context.revision, outcome
            contexts.pop(revision_id)

        validation_started_ns = time.time_ns()
        bundle = recording_store.get_metadata(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        revision_cache: dict[str, StoredPipelineRevision] = {}
        revision = require_revision(recording_id, revision_id, revision_cache=revision_cache)
        source = revision.manifest.source
        if (
            source.recording_id != recording_id
            or source.video_sha256 != bundle.source_sha256
            or source.byte_length != bundle.video_byte_length
        ):
            raise DerivedViewError(
                "The selected visual identity revision does not match the accepted recording video."
            )
        outcome = require_outcome(revision, item_id)
        frozen_input = validate_provenance(revision, outcome, revision_cache=revision_cache)
        roots = {repository_storage.bundle_path(recording_id)}
        for dependency_id, dependency in revision_cache.items():
            try:
                dependency_node, dependency_revision = node_store.find_revision(dependency_id)
            except FileNotFoundError as error:
                raise DerivedViewError("a canonical crop dependency is unavailable") from error
            roots.add(
                node_store.revision_path(dependency_node.node_id, dependency_revision.revision_id)
            )
            if isinstance(dependency.manifest.producer, ProcessorProducer):
                roots.add(run_store.run_path(dependency.manifest.producer.run_id))
        dependency_roots = tuple(sorted(roots))
        try:
            fingerprint = crop_dependency_fingerprint(dependency_roots)
        except OSError:
            fingerprint = ()
        if fingerprint and all(entry[5] < validation_started_ns for entry in fingerprint):
            contexts[revision_id] = ValidatedCropContext(
                revision, frozen_input, dependency_roots, fingerprint
            )
            while len(contexts) > 8:
                contexts.popitem(last=False)
        return revision, outcome


def resolve_browser_preview(
    *, crop_identity, crop_resolver, cache: Path
) -> ResolvedCropJpegPreview | None:
    """Use the validated crop digest for both cached and cold previews."""
    if crop_identity.content_type != "image/x-portable-pixmap":
        return None
    cached = resolve_crop_jpeg_preview_from_cache(crop_identity.image_sha256, cache=cache)
    if cached is not None:
        return cached
    crop = crop_resolver()
    if crop.image_sha256 != crop_identity.image_sha256:
        raise DerivedViewError("the resolved identity crop changed")
    return resolve_crop_jpeg_preview(crop, cache=cache)


__all__ = [
    "crop_identity_mapping",
    "resolve_browser_preview",
    "resolve_geometry_crop",
    "resolve_identity_crop",
    "resolve_reviewed_annotation_crop",
    "validated_identity_crop_outcome",
]
