# Recording data storage

Decision date: 2026-11-10. This is the target for new storage work. It does not claim that the
current runtime or retained data already uses this format. The [epic board](plans/README.md)
records delivery. Closed epics remain historical evidence.

## Problem and goals

The current recordings list reconstructs processing status from nodes, revision history, runs,
analyses, and packages. Generic persistence concepts also obscure the recording's domain data.
The user requests simple local files, explicit relationships, and fast reads of current metadata.

- A recording folder is understandable without executing the application.
- Store authoritative source facts, annotations, predictions, and review decisions. Preserve the
  distinction between a prediction and a human-confirmed statement.
- Use concrete resources and one content contract for each resource type. Human and model content
  use that same contract. Origin and review are metadata.
- Follow consistent conventions. Do not implement a universal resource envelope, base store,
  adapter registry, dependency engine, or generic graph to enforce them.
- Keep current selection explicit. Read current metadata directly. Open content and history only
  when a caller requests them.
- Preserve retained human work and the exact inputs of retained results during conversion.

## Domain resources

- **Recording:** source media, source identity, session, measured media facts, and current selection.
  Retain existing permission, allowed-use, acquisition, and retention facts. A recording is not a
  round. Display a source name or recording ID when no round name is known.
- **Event set:** an alternative collection of events for one recording. Events have identity,
  type, and start/end times. Several sets can coexist.
- **Source frame:** exact recording/frame identity and image coordinates, including a transform
  when applicable. Several frames can support an event. A frame can also be annotated directly.
- **Visual detection set:** an alternative collection of visible objects for named events/frames.
  A detection has a local object ID and a visible region with one or more segments. Multiple
  segments can describe one occluded object. Keep pile regions and ignore regions explicit.
- **Table-plane calibration:** image-to-table mapping, card dimensions, and the interval where the
  camera and table are stable. Detection segmentation does not require calibration.
- **Virtual scene:** card poses and stacking order for one frame under an exact calibration, with
  links to supporting detections. Keep pile footprints without inventing their component cards.
  A virtual-scene set collects alternative scenes. Do not require new pile-fitting algorithms.
- **Classification set:** visual classifications of exact detected or virtual objects. Preserve
  candidate scores, unknown/unusable evidence, and the exact visible geometry used as input.
  A visual card identity does not establish a unique physical card.
- **Table observation stream:** ordered uncertain reports with exact source intervals and inputs.
  Preserve cards, piles, candidate identities, and supported uncertain temporal associations.
  Gameplay reconstruction consumes a selected stream; it does not define these resources.
- **Review decision:** who inspected which saved content, item, question, and coverage, and the
  decision. Geometry and identity review are separate. Preserve independent unfinished reviews.

## Folder convention

Use the configured worktree storage root. The target authoritative root is `data/recordings/`.
Use existing recording IDs; do not rename them just to add a prefix. For example:

```text
recordings/<recording-id>/
  recording.json
  source/
    video.mov
  event-sets/<set-id>/versions/<version>/
    event-set.json
    events/<event-id>/event.json
  detection-sets/<set-id>/versions/<version>/
    detection-set.json
    frames/<frame-id>/detections/<detection-id>/
      detection.json
      segments/<segment-id>.json
  calibrations/<calibration-id>/versions/<version>/calibration.json
  virtual-scene-sets/<set-id>/versions/<version>/
    scene-set.json
    scenes/<scene-id>.json
  classification-sets/<set-id>/versions/<version>/
    classification-set.json
    classifications/<classification-id>.json
  observation-streams/<stream-id>/versions/<version>/
    observation-stream.json
    observations/<observation-id>.json
```

These are concrete layouts, not inputs to a configurable storage framework. Set metadata records
membership, exact inputs, coverage, and provenance once. It does not duplicate each item's content.
Keep small review decisions and resumable review work beside the content they concern; specify
their exact typed layout in the owning resource epic. Do not add a generic review-state migration.

The recording owns these collections. Event, frame, and object references express relationships
between them. Detections are not physically nested under an event-set version: two event sets can
use the same frame evidence without copying it. Detection segments remain with their detection.
This small departure from the user's rough sketch avoids duplicate ownership.

Frame identity is data in the relevant resource. A separate frame database or authoritative JPEG
collection is unnecessary. Sampled images, crops, thumbnails, and rendered visible regions are
derived views. Existing cache policies remain outside this work.

## Saving and selection convention

`recording.json` owns recording metadata and an inline `head` object with exact current references.
HEAD is a selection, not a pipeline progress record. Keep generated and selected completed-reference
choices distinct where the existing workflow needs both. Do not select content by newest timestamp.

This deliberately replaces the current separate aggregate snapshot/HEAD store when the relevant
resource consumers convert. Update the glossary's existing recording HEAD/snapshot descriptions at
that cutover; do not silently use their old meanings for the new representation.

- A reference names a concrete resource, saved version, and item where needed. It never means
  "whatever is latest". Use explicit fields in each type, not a polymorphic reference framework.
- A saved version is immutable. Autosave can create another version of the same set. A user copy
  has its own set identity. Immutable versions protect retained inputs without checking whether
  another resource already used them. Do not carry automatic copy-on-edit detection or an
  accepted-use database into the target model.
- Write a complete saved version in a temporary directory and rename it into place. Then replace
  `recording.json` atomically under a recording-local lock and expected-version check if selection
  changes. A save need not select its output.
- A crash before selection leaves the previous HEAD usable. A fully saved, unselected version is
  valid data, not an orphan that needs a publication certificate. No multi-store commit is needed.
- Two edits with the same expected recording version cannot silently overwrite each other.
- Changing an input preserves existing results and their exact inputs. Compute incompatibility
  when that result is opened. Do not persist propagated stale flags across the whole recording.
- Store provenance and review as facts. Keep job progress, cancellation, retries, and execution
  failure in existing operational records. Distinguish examined-and-empty from unexamined or failed.

During conversion, move one resource type's selection readers and writers together. That type has
one authority. Untouched resource types keep their existing authority until their own cutover.
Temporary, explicit call-site conversions are allowed; dual writes and a permanent legacy resolver
are not. No resource epic must migrate the scheduler, training campaigns, or unrelated data types.

## Recordings list contract

Deliver the fast list before any storage conversion. Initially use existing authoritative recording
metadata and exact selection files. Do not adopt the experimental aggregate HEAD just for listing.

The planned row contains recording/source identity, display name, received date, session, thumbnail
URL, and separate generated/reference selection indicators. Indicators mean **selected**, **no
explicit selection**, or **unavailable metadata**. They do not mean reviewed, runnable, processing
complete, or that no historical data exists. The list does not certify referenced content.

Move live progress, historical counts, latest analysis, package aggregation, and analysis readiness
to explicit recording/detail or job operations. This is an intentional list-contract change. Keep
those operations available and validate their exact inputs when used. It removes the requirement
that led 0120 to propose publication ledgers for multiple independent writers.

The initial read budget is three known intake metadata files and at most six exact selection files
per recording, plus one existing pending-transaction locator for the request. Read only the root
fields needed by the row; never parse proposal payloads embedded or referenced in the manifest.
The final layout needs only `recording.json` for a row. Do not read video bytes, invoke ffprobe,
recurse through recording contents, follow input dependencies, or enumerate histories.

Use a narrow metadata-only selection parser. The existing `get_exact()` also validates referenced
resources and can recover transactions; it is not the list reader. If an existing transaction is
pending, show unavailable selection metadata while preserving recording identity. Do not recover
writes on the list route. Independent selection-file reads do not promise a cross-type snapshot.

Corrupt recording metadata remains visible as an error row with the directory recording ID. Do
not silently omit it or invent usable metadata. Bound malformed-file reads with a documented size
limit. Missing selection means no explicit selection; invalid selection metadata means unavailable.

With recording count fixed, retained event/detection/scene/classification versions, runs, analyses,
and packages must not increase list file reads, decoded bytes, or directory visits. A normal list
request performs no writes. Root enumeration can grow with recording count.

Target request medians below one second for both fresh-process and warm reads of the frozen local
corpus. Measure after backend startup; report startup and thumbnail work separately. Use three
uncontended process sessions. Do not call a fresh process a cold disk-cache measurement. Timing is
a qualification gate, not a claim based on this planning inspection.

## Delivery and non-goals

[0123](plans/3-in-progress/0123-Simple_Recording_List.md) delivers the list in three milestones without
new persistent state. [0124](plans/4-blocked/0124-Recording_Folders_and_Events.md) proves recording
folders and event editing. [0125](plans/4-blocked/0125-Recording_Visual_Detections.md),
[0126](plans/4-blocked/0126-Recording_Virtual_Scenes.md),
[0127](plans/4-blocked/0127-Recording_Classifications.md), and
[0128](plans/4-blocked/0128-Recording_Table_Observations.md) convert one downstream resource workflow
at a time. Each epic includes its own retained-data check and removal of replaced code.

Do not implement a generic resource framework, catalog index, projection ledger, source outbox,
publication certificates, or new scheduler. Do not redesign detection, fitting, classification,
reconstruction, training, cache retention, or backup policy. Reuse existing algorithms and preserve
their evidence semantics. Faster listing does not require bounded writes or global consistency.

Use one-time offline conversion of named retained resources, with a disposable rehearsal, frozen
input manifest, exact-reference mapping, verified human work, and a recovery copy. Preserve source
media bytes. No automatic in-request migration, speculative global migration, or permanent format
compatibility layer. A missing original dependency must remain explicit.

## Execution bounds

This planning change authorizes no implementation loop. Each later loop selects one epic; it does
not automatically continue into the next. 0123 has three milestones. Each resource epic has four.
No nested milestone suffixes or new prerequisite milestones may extend those baselines.

Prove an API/service save/open or list workflow by M1, and an actual browser workflow by M2 at the
latest. Qualify and close within the stated final milestone. Each worker receives one observable
result, named source owners, required checks, and one focused commit boundary. Later milestone
details are frozen after the preceding proof, before assignment. Workers do not choose a framework.

Apply the [execution scope review](workflows/epic-execution.md#scope-review) after two attempts
without reduced scope or at the two-correction limit. Preserve old exhausted correction counts.
Record a smaller approach or stop; new epic numbers do not renew the old ledger approach. New
cross-resource transactions, an unbounded consumer conversion, or displaced workflow/qualification
proof require a scope decision before more implementation. Do not treat local complexity as a
reason to build more infrastructure.
