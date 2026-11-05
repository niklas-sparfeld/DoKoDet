# 0107 M3: accepted uses and copies

`PipelineNodeUses` durably records each accepted run and its exact input revisions under a shared
transaction lock. Acceptance rejects a stale working head. The record remains authoritative if the
run later fails or is cancelled. Direct node saves share the lock and reject content changes after
accepted use. An unchanged save remains a no-op.

`PipelineNodeEdits` creates an independent node when an accepted input changes. It applies the edit
and its item provenance before the new node becomes visible. It returns the selected node and revision
and the copy reason. Later edits stay in that copy until it has an accepted downstream use. The
service also supports explicit copies of historical revisions and restores into the current head.
Copies record the exact source, actor, time, and reason when known. Restores record the historical
source. Names include the full unique copy ID.

A shared interprocess lock serializes acceptance, edits, and idempotency handling. An edit journal
binds each key to a request digest. The output revision carries the same operation identity, so a
retry can recover after publication but before the journal result is written. A retry also removes its
own unpublished revision if a head update failed. Validation occurs before copy publication. A
failed accepted run does not release its inputs. Different content under the same key is rejected.
The atomic node publication or head replacement commits the result; a journal entry by itself is not
a visible copy. This protocol is for the local filesystem and relies on the existing fsync and atomic
rename primitives.

The foundation is not connected to the existing processor coordinator or workspace. Integration must
use accepted-use registration before a worker reads inputs and route content edits through this
service. Item-tracked content requires explicit pointers and operations. M4–M10 still own review,
graph, migration, and integration verification.

Verification: 33 focused and existing pipeline-store tests passed. They cover accepted-use and edit
races, failed-run protection, provenance-preserving copies, repeated edits, concurrent retries,
invalid edits, historical copies and restores, and interruptions before and after publication. Ruff
check and format passed for the changed Python files.
