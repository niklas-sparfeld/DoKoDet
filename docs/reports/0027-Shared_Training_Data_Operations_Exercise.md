# Plan 0027 M11 clean-room exercise

## Automated clean-room gate

Status: passed on 2026-08-28.

The headless test `test_saved_video_clean_room_reaches_commit_ready_independent_tasks` runs one
saved video through the local recording client, backend, and repository-operations command. It
uses temporary roots and needs no phone, camera, display, external service, GPU, or cloud
resource.

Command:

```text
mise exec -- uv run pytest tests/test_local_pipeline.py -k clean_room -q
```

The test performs this sequence:

```text
saved video
  -> Swift collection-profile simulator
  -> complete repository bundle
  -> stopped-backend retryable upload
  -> accepted repository intake
  -> SQLite deletion and rebuild from canonical bundle files
  -> doko data review --task all
  -> CardEventNet task publication
  -> resumed TableEvidenceAnalyzer task publication
  -> doko data validate
```

The first review invocation creates resumable work. The second invocation supplies decisions only
for CardEventNet and approves its split. The third invocation supplies the remaining table-evidence
decisions and publishes the second task. This proves that one task can complete while the other
remains resumable.

The test checks:

- both task branches use the same source asset and source SHA-256;
- the backend rebuilds searchable metadata from the accepted bundle after SQLite deletion;
- the CardEventNet and TableEvidenceAnalyzer outputs publish in separate directories;
- every published JSON source digest equals the accepted source digest;
- no published task output contains a video copy;
- `doko data validate` succeeds;
- the review report lists existing state, log, report, and published files as commit-ready.

The decision objects are fixture-only `{"outcome": "reviewed"}` values. They are test input and do
not create ground truth for non-fixture data.

## Required human exercise

Status: not run by the headless automated gate.

The human exercise must be run with the local app or simulator and the interactive review
interfaces. Use one saved video and one collection profile. Record the operator, app build, command
versions, source digest, and the final `doko data validate` result below after execution.

Required actions:

1. Reuse one collection profile for two recordings.
2. Change one recording task override and confirm the field-level validation before upload.
3. Stop the local backend, retry one failed recording upload, and confirm one accepted repository
   bundle.
4. Rebuild the local intake index from the accepted bundle.
5. Select, defer, resume, and complete the two task reviews independently.
6. Approve both split proposals and confirm that the final report contains only commit-ready
   artifacts.

Human result: pending local interactive execution.

