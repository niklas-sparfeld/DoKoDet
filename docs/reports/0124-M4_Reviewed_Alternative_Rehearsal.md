# 0124 M4 reviewed-alternative rehearsal

## Result

The M4 conversion and browser workflow passed in disposable storage for:

- `cardeventnet-IMG_0662`
- `cardeventnet-IMG_0648`
- `game-2026-08-20-01-001`

This was a rehearsal. It did not activate the three recordings or change retained source data.
The pilot's existing recording HEAD, edits, and selection were preserved in the rehearsal copy.
No saved output was changed.

## Scope and method

The offline adapter is
`backend/src/dokodetector_backend/event_conversion_rehearsal.py`. It reads the named recordings'
`pipeline-node/v1`, `pipeline-node-revision/v1`, `pipeline-node-selection/v1`, legacy event
selectors, and `pipeline-review/v1` records. It saves event versions and reviews through the
existing `RecordingFolderStore` and `EventSetStore`. It does not convert other resource types or
write to a source store.

Each old event node and revision maps to one event set and version with the same IDs. The adapter
checks canonical content digests, origin, and provenance. It compares all review IDs, kinds,
questions, decisions, reviewer identity, review time, item digest, coverage, policy and evidence.
It preserves source provenance in the existing review evidence object. The normal review listing
requires published revisions; some retained reviews belong to unpublished revisions. The offline
adapter reads only those exact review records by node and revision identity. It does not publish
those source revisions.

The node selector resolves each selected pair by exact node ID and revision ID. The legacy selector
must name that revision's retained legacy revision ID. The adapter fails if they disagree, if an
exact source revision is missing, or if a referenced saved version differs. It uses no time-based
selection rule. The 0662 copy already has a HEAD from M3, so the rehearsal preserves that HEAD and
records the old selector mapping without replacing it.

## Frozen inputs

Snapshot manifest:
`/var/folders/gv/yr_91p3x2_vctbq99586hjm80000gn/T/0124-m4-final-39juxq3w/frozen-input-manifest.json`

Manifest SHA-256:
`a806ca35d95f2424adfa9c14a063f0d33aeadaff2dcc41af25b9ef32b014f03f`

It records 14 source event nodes, 314 review records, both event selector files for each recording,
source bundles, and the retained M3 output parent. All 373 compared input files matched their
frozen copies. The three source media digests were:

| Recording | Source media SHA-256 | Bytes |
| --- | --- | ---: |
| `cardeventnet-IMG_0662` | `2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7` | 158,680,194 |
| `cardeventnet-IMG_0648` | `6ae4bba4c7901ec016d9684661c01ac5fa18932f3da1e79502b43ba2ff2fb33c` | 172,686,963 |
| `game-2026-08-20-01-001` | `2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa` | 557,067,308 |

The 0648 and game repository bundles were copied into the temporary root before use. The source
recordings, node revisions, reviews, selector files, and output remain in the primary checkout's
data roots. The adapter and browser ran against a separate temporary root.

## Conversion comparison

| Recording | Event versions | Reviews | Item reviews | Coverage reviews | Overall reviews | Selected generated | Selected reference |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `cardeventnet-IMG_0662` | 6 | 104 | 100 | 2 | 2 | `1e61d676-fc13-505c-98fb-7b7880460d55@e95b1cda-e6b8-5fa2-ab4d-7eb30fb1105e` | `1dca5a93-4a87-59f6-ab83-d5c72154916b@d41f92f9-7fd1-52db-a065-7c94f963713a` |
| `cardeventnet-IMG_0648` | 5 | 108 | 104 | 2 | 2 | none | `fb902b8a-4704-524e-a2b5-57af8c7aa96f@01fd1db5-5719-52e4-af4b-e1e838924f4b` |
| `game-2026-08-20-01-001` | 6 | 102 | 98 | 2 | 2 | `357dea73-fc78-5840-a05b-231663530dbf@401625b9-4e89-5700-8d1a-9489dc9a2c7a` | `7956102f-392c-5a25-bcae-02040808c38c@d616e0a1-808f-5c1b-87ee-302ea20ba099` |

All 17 canonical event content digests matched. The adapter compared pending item IDs per exact
revision. The conversion receipt has each version's event count, review kinds, reviewed item IDs,
and pending item IDs. It can replay the same frozen input without replacing an event version or
review. Review timestamps use the exact retained value in the existing `event-review/v1` field.

## Browser workflow

The normal browser opened one reviewed, unselected version from each recording. It showed 52
decisions for 0662, 54 for 0648, and 51 for the game recording. The first version was one exact
reviewed revision of the review records on each source. The remaining records attach to their other
source revisions and remain available in the version list.

On disposable 0662 data, the browser edited and saved an event alternative, selected it, and then
restarted the backend against the same files. After restart, it reopened the reviewed alternative
and opened the exact earlier event parent in the event-set workspace.

The retained output is run
`7111edd7-9f72-4fdc-9c10-a90d94db172f`. Its output content digest is
`905ecbb65fc9137a15187f9bd0465e8f7923d120bbaff1b7840411250c582e23`. Its exact event parent is
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1` with content digest
`a3c284533668d7b316f65142718262424f62769e85bd19d0f67e177fb6b84c78`. The output API returned
HTTP 200 after restart. The browser reopened that parent with its original first event start time
of `2001934` microseconds. The source output file digest remained
`5a4bf4dd0a0c4797e4226649c6d94afe5ee4b337e2678e08eb67c5893fa14fc7`.

## Correction 1/2: pre-M3 retained output parent

The first report used output `7111edd7-9f72-4fdc-9c10-a90d94db172f`, created in M3 after the
event-set cutover. Its parent was already folder-backed. That did not prove an actual retained
legacy output's direct event-node parent.

The corrected rehearsal freezes pre-M3 output run
`6e2f3f6f-b5c3-5bb0-8056-47a34bf54327` for `cardeventnet-IMG_0662`. Its exact output is node
`8bfa825d-94af-5ac6-877d-a1381e662d65`, revision
`d9c461ee-c7f9-5a2c-be60-36da3ea9a169`, content digest
`e7d585be69996a440c7c56d6e3fb3a2cd582288327b82555561a38c49191a1ad`. The output's retained
request and revision both name old event revision `reference-events-fd5c08dc4f7540053b3ed1c04606b909`.
The exact source event node/revision is
`1dca5a93-4a87-59f6-ab83-d5c72154916b@d41f92f9-7fd1-52db-a065-7c94f963713a`, with content
digest `00ce1f56caf862db76601d6e82cd36587d56f2c9fd23de208364559b910832f5`. The offline adapter
matched the output's event revision to that unique legacy revision metadata, then emitted the exact
converted parent `1dca5a93-4a87-59f6-ab83-d5c72154916b@d41f92f9-7fd1-52db-a065-7c94f963713a`
with the same digest. It fails if the run, output, or parent is missing, ambiguous, inconsistent, or
has changed content. This is a named offline rehearsal input; it adds no runtime resolver or output
format conversion.

The copied output node (3 files) and run (52 files) had matching tree digests against their retained
sources before and after browser use: `e9ea891414e4b5cc6c1c0b81e3081f6a72dfc94e940df81346228ebabc7f3107`
and `ae8b6c73466836f72f846bbe0c0f1de851c6e25e0e2bed57d72b1bb4e08b6c92`. The normal browser
opened the mapped parent in the event-set workspace, changed generated
selection to `manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`, restarted the backend, and reopened
the mapped parent. Its first event remained at `2001934` microseconds. The exact parent digest was
unchanged before and after restart, and the changed selection remained selected. The output node,
revision, request, state, and items were not modified. The browser uses the emitted exact mapping to
open the parent; no automatic output-to-parent link is added to the runtime UI.

Correction snapshot:
`/var/folders/gv/yr_91p3x2_vctbq99586hjm80000gn/T/0124-m4-final-39juxq3w/pre-m3-output-correction-manifest.json`.
Its SHA-256 is `9724baeecc33a31112f43b31c9506a8020e408b9f417396662ef61331a1f4034`. The source output
revision file, request, state, source event revision, and converted event-set document are frozen
in that manifest.

The previous M4 review, edit, selection, replay, conflict-rejection, and restart checks remain part
of the evidence. M4 correction count is now 1/2; this run remains 1 requested, 1 completed, 0
remaining. M5 qualification and M6 runtime removal remain unchanged.

## Checks

- The named backend regressions passed: 53 tests. One existing Starlette deprecation warning was
  emitted by the test client.
- Ruff check and format passed for the changed backend files.
- `npm run check` passed: 244 tests, type, lint, format, and generated API checks.
- The recording-folder Playwright suite passed: 3 tests.
- The retained-data browser rehearsal opened reviews on all three recordings, edited and selected
  an alternative, restarted the backend, and reopened the reviewed alternative and exact parent.
- A second adapter run against the same disposable data passed with the same 17 versions and 314
  reviews.
- A replay with a changed saved provenance record failed closed. The temporary record was restored
  byte-for-byte after the check.
- Correction 1/2: the named pre-M3 output mapping replay passed, and the normal browser reopened its
  converted exact parent after a selection change and backend restart. Output input copies matched
  retained hashes before and after browser use.
- Correction checks: 66 focused backend tests passed; Ruff check and format passed; `npm run check`
  passed with 244 tests and type, lint, format, and generated API checks; the recording-folder
  Playwright suite passed with 3 tests.

There was no activation or qualification in M4. M5 owns the finite rollout and representative
normal-app qualification. M6 owns removal of replaced event runtime paths and final closure.
