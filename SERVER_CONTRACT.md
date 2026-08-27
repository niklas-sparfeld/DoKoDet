# Evidence upload V2 contract

This document freezes the client-to-server contract for one evidence package. The canonical
manifest examples are:

```text
fixtures/evidence/v2/example-complete/manifest.json
fixtures/evidence/v2/example-incomplete/manifest.json
```

The backend and iOS tests must load these files directly. Do not copy them into another fixture
format.

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
video_capture
camera
frames
video_snippet
missing_frame_targets_ms
score_trace
client
```

`schema_version` is `cardevent-evidence/v2`. `package_id` and `session.session_id` are UUIDs.
`session.event_sequence` is a positive integer. These two session fields identify one logical
event. The manifest has no player or turn context.

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

`part_name` is a safe multipart name. It has no path separator and matches
`^[A-Za-z0-9][A-Za-z0-9._-]*$` with a maximum length of 64 characters. `content_type` is
`image/jpeg`. `captured_at_utc` is an ISO-8601 timestamp with a zero UTC offset (`Z` or
`+00:00`). `sha256` is a lower-case SHA-256 hex string.

The `evidence_capture.target_offsets_ms` list is the configured target set. The target offsets in
`frames` plus `missing_frame_targets_ms` must equal that set. No target may occur twice.
`event.evidence_complete` is true only when `missing_frame_targets_ms` is empty. A metadata-only
package is valid when all configured targets are in the missing list and `frames` is empty.

The `video_capture` object freezes the requested event-relative range and the PoC bounds:

```text
requested_start_offset_ms, requested_end_offset_ms
max_duration_ms, max_width, max_height, max_nominal_frame_rate
max_byte_length, queued_byte_capacity
container, video_codec, content_type
```

The selected closed media values are `mp4`, `h264`, and `video/mp4`. The requested range covers all
configured frame targets.

`video_snippet` is nullable. `null` means that optional snippet evidence is absent. A non-null
complete value declares exactly one multipart part and contains its actual event-relative start and
end, duration, media values, byte length, and SHA-256. An incomplete value contains only
`capture_complete: false` and a `failure_reason`; it has no media part. A corrupt declared snippet
is different: it is complete and has a declared part, but its bytes fail hash or media validation.

The client object contains `app_version`, `build`, `device_model_identifier`, and `os_version`.
The device value is a model class. It is not a stable device identifier.

All required fields are present in both fixtures. Unknown fields are not part of V2. Clients must
send the fields shown in the fixtures and servers must reject unknown fields rather than silently
assigning them a meaning.

## Upload endpoint

The client sends one immutable package with:

```http
PUT /v1/evidence-packages/{package_id}
Content-Type: multipart/form-data; boundary=<boundary>
```

`{package_id}` must be a UUID and must equal `manifest.package_id`. The request has exactly one
`manifest` part with content type `application/json`. It has one `image/jpeg` part for each
manifest frame, using that frame's `part_name` as the multipart field name. A missing target has no
multipart part. A metadata-only package therefore contains the manifest part only. Undeclared
frame parts, duplicate parts, and duplicate manifest parts are invalid.

When `video_snippet` is complete, the request also contains one `video/mp4` part using its
`part_name`. A null or incomplete snippet has no video part.

For the complete fixture, the parts are:

```text
manifest  application/json
frame_00  image/jpeg
frame_01  image/jpeg
frame_02  image/jpeg
frame_03  image/jpeg
frame_04  image/jpeg
frame_05  image/jpeg
snippet_00 video/mp4
```

Multipart filenames are not trusted and are not part of the contract fingerprint. The server stores
each accepted frame as `<part_name>.jpg` and a complete snippet as `<part_name>.mp4` below the
package directory.

The server validates the complete package before it stores or exposes it:

- each declared frame has one matching part and no extra frame part exists;
- each frame byte length and SHA-256 match the manifest;
- each frame content type is `image/jpeg`;
- the present and missing target lists equal the configured target set, without duplicates;
- `event.evidence_complete` is true only when the missing list is empty;
- the package ID in the path and manifest match.

Incomplete packages are valid. A metadata-only package is valid when every configured target is in
`missing_frame_targets_ms` and `frames` is empty. The server must retain the manifest for an
incomplete package.

### Size limits

These are the V2 default limits. A deployment may lower them, but it must not raise them without a
new contract version:

```text
manifest bytes:             1,000,000
one JPEG frame:            10,000,000
manifest plus JPEG frames: 100,000,000
one video snippet:             250,000
```

The limits apply to received bytes, before any image decoding. A request over a limit is rejected
and does not create a package directory or database row.

### Successful responses

For a new package, return `201 Created`:

```json
{
  "package_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "stored",
  "created": true,
  "received_at": "2026-08-26T18:11:29.000Z"
}
```

For an identical replay, return `200 OK` with the same shape, `created: false`, and the original
`received_at`. Idempotency compares the package fingerprint below. A package ID with different
content returns `409 Conflict` and is not overwritten.

`state` is `stored` for every successful V2 response. `received_at` is an RFC 3339 UTC timestamp.

## Stored package reads

Read package metadata with:

```http
GET /v1/evidence-packages/{package_id}
```

The response includes the validated manifest, selected-frame metadata, and the optional
`video_snippet` metadata. For a complete snippet, `video_relative_path` reports its local relative
storage path. Clients must use the safe read endpoint instead of constructing a filesystem path:

```http
GET /v1/evidence-packages/{package_id}/video-snippet
```

The endpoint returns the original `video/mp4` bytes with an ETag equal to the declared SHA-256.
It returns `404` when the package has no complete snippet. The endpoint never accepts a path or
part name from the client.

## Fingerprint

The package fingerprint is the SHA-256 of canonical JSON with this shape:

```json
{
  "manifest_sha256": "...",
  "frames": [
    {"byte_length": 123, "part_name": "frame_00", "sha256": "..."}
  ],
  "video_snippet": null
}
```

The manifest digest is the SHA-256 of the received manifest bytes. Frame entries are sorted by
`part_name`. A present video entry contains its `part_name`, `byte_length`, and `sha256`.
Multipart boundaries, filenames, and received part order are not included. The server
must persist the received manifest bytes without reformatting them. Encode the fingerprint JSON as
UTF-8 with lexicographically sorted object keys, compact separators (`,` and `:`), and no additional
whitespace before hashing.

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

`details` is an array and may be empty. Use these status and error-code mappings:

| Status | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | The multipart envelope or required part is malformed. |
| 409 | `package_conflict` | The package ID exists with different content. |
| 409 | `logical_event_conflict` | The session ID and event sequence already identify another package. |
| 413 | `manifest_too_large`, `frame_too_large`, `video_too_large`, or `package_too_large` | A configured byte limit is exceeded. |
| 415 | `unsupported_media_type` | The request or a part has an unsupported content type. |
| 422 | `invalid_package_id`, `package_id_mismatch`, `invalid_manifest`, `hash_mismatch`, or `invalid_video` | A declared identity, manifest, byte digest, or video stream is invalid. |
| 500 | `internal_error` | The server failed after receiving a valid request. |

Every error uses the JSON shape above. The server does not return stack traces, local paths, or
uploaded bytes. A rejected request must not be visible as a stored package.
