# 0100 M5 progress

Status: in progress. This is not a milestone completion report.

## Current findings

A read of each active selection checked content and lineage, not only the manifest. Of 180
selection pointers, 151 resolved and 29 did not. The affected pointers have 13 distinct
`proposed-card-scene-data/v1` ancestors. The direct content of all 29 selected revisions validates
when the ancestor check is disabled. Each obsolete ancestor has a matching content digest and the
same recording as the selected revision. See the [lineage inventory](0100-M5_Lineage_Inventory.json).
The affected graph has 53 revisions, including generated outputs and human-reviewed revisions.
No replacement has been published yet.

The operator selected a repair that creates replacement copies of affected reviewed revisions and
records their lineage in a repair receipt. The repair must also preserve generated identity crop
provenance and run lineage. Replacing a scene ancestor alone cannot change an immutable descendant's
input IDs. Validate the complete replacement chain in an isolated store before changing a selection.
Keep the original revisions, drafts, queue targets, and reviewed decisions.

All 13 old scene payloads passed a deterministic conversion probe to the current scene contract.
An isolated store accepted one converted scene and a copy of its reviewed visible-card revision.
That copy still contains 36 references to the old scene revision in its content. Store acceptance
alone is not sufficient. A second isolated probe updated those references, recomputed the scene
draft digests, and published the reviewed copy. The complete repair must also update and validate
crop-input digests, processor run requests, and reviewed identity copies together before publication.

A local API audit resolved all 165 frozen 0096 detector frames and all 145 available exact scene
frames. The other 20 frames belong to four failed scene runs and retain their recorded diagnostics.
The separately unreviewable recording has no queue frames. For 0098, all 114 exact generated cards
and crop requests resolved, and each target revision was present in its workspace. Eight maintained
identity reference reads failed on the obsolete ancestor chain; three recordings had no reference.
The ten conflicting drafts still match the digests in the frozen queue. These API checks do not
replace browser verification or restart checks after repair.

The first audit exposed a write-on-read defect. A GET of the completed identity reference for
`cardeventnet-IMG_0645` automatically published a face-down correction and changed its draft and
selection. The three tracked files were clean before the audit and were restored to their exact
pre-audit Git contents. The accidentally published revision was moved out of the pipeline catalog to
`/tmp/doko0100m5-accidental-reference-visual_identities-db95736faf5e52a6ace78295426dc5ce` for
inspection. The read path no longer makes that correction. The automatic editor rebase on opening
an identity result and automatic proposal-review start were also removed. An operator must select
those actions explicitly.

M5 remains incomplete. The bounded replacement, repair receipt, selection updates, restart checks,
full browser navigation, and final verification remain open. No review decision or queue receipt is
authorized by this progress report.

Focused backend and editor tests passed, as did checks on the changed Python and web files. The
full web lint reported two errors in the unchanged `CardEventFrameSurface.tsx`; they remain open.
