# Evidence upload V1 contract

This document defines the local evidence package contract. The canonical manifest examples are:

```text
fixtures/evidence/v1/example-complete/manifest.json
fixtures/evidence/v1/example-incomplete/manifest.json
```

The backend and iOS tests must load these files directly.

## Manifest

The manifest is UTF-8 JSON. Its top-level fields are:

```text
schema_version
package_id
session
event
model
event_decoder
evidence_capture
camera
frames
missing_frame_targets_ms
score_trace
client
```

`schema_version` is `cardevent-evidence/v1`. `package_id` and `session.session_id` are UUIDs.
`session.event_sequence` is a positive integer. These two session fields identify one logical
event.

The `event` object contains `event_time_ms`, `emitted_at_ms`, and `evidence_complete`. Both times
are session-relative milliseconds. The emitted time must not be before the event time.

The `model`, `event_decoder`, `evidence_capture`, and `camera` objects contain the client
configuration used to produce the package. The backend stores this metadata. It does not interpret
the model or detector result.

Each `frames` item contains:

```text
part_name
target_offset_ms
actual_offset_ms
session_elapsed_ms
captured_at_utc
width
height
byte_length
content_type
sha256
```

`part_name` is a safe multipart name. It has no path separator. `content_type` is `image/jpeg`.
`captured_at_utc` includes the UTC offset. `sha256` is a lower-case SHA-256 hex string.

The `evidence_capture.target_offsets_ms` list is the configured target set. The target offsets in
`frames` plus `missing_frame_targets_ms` must equal that set. No target may occur twice.
`event.evidence_complete` is true only when `missing_frame_targets_ms` is empty. A metadata-only
package is valid when all configured targets are in the missing list and `frames` is empty.

The client object contains `app_version`, `build`, `device_model_identifier`, and `os_version`.
The device value is a model class. It is not a stable device identifier. The manifest has no player
or turn context.

## Fingerprint

The package fingerprint is the SHA-256 of canonical JSON with this shape:

```json
{
  "manifest_sha256": "...",
  "frames": [
    {"byte_length": 123, "part_name": "frame_00", "sha256": "..."}
  ]
}
```

The manifest digest is the SHA-256 of the received manifest bytes. Frame entries are sorted by
`part_name`. Multipart boundaries, filenames, and received part order are not included.

## HTTP errors

Validation errors use this stable shape. The server does not return stack traces or local paths.

```json
{
  "error": {
    "code": "invalid_manifest",
    "message": "The manifest failed validation.",
    "details": [
      {"field": "frames", "message": "..."}
    ]
  }
}
```

`details` is an array and may be empty. A malformed request uses `invalid_request`. A malformed
package ID uses `invalid_package_id`. A path and manifest ID mismatch uses
`package_id_mismatch`. The upload endpoint and its status mapping are implemented in later
milestones.
