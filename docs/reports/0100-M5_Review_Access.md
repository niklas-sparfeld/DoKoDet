# 0100 M5 revision and review access

Status: complete. No human review decision or saved-review receipt was created.

The [repair receipt](0100-M5_Repair_Receipt.json) maps 53 original revisions to 53 replacement
revisions. It records 26 copy runs, 26 maintained-reference draft updates, 18 selection updates,
source and replacement digests, and the verification results. The
[original reference snapshots](0100-M5_Original_Reference_Snapshots.tar.gz) retain the exact
pre-repair draft, state, command, and selection bytes. The repair copied the existing outputs. It
ran no model and made no cloud request. It kept the original revisions and frozen queues.

The repair moved obsolete scene ancestry to the current contract. It retained card geometry,
classification outcomes, review states, and coverage decisions. It updated only the lineage fields
that name copied revisions. Each changed draft advanced its revision so stale edits are rejected.
The original source files, annotations, and sealed evaluation reports were not changed.

All 165 frozen 0096 detector targets resolved their exact stored result and frame identity. All 145
available scene targets resolved. Four failed scene runs cover the other 20 selected frames and
keep their recorded diagnostics. The separate unreviewable recording has no queue frames. All 114
frozen 0098 identity targets resolved their exact recording, revision, card, frame, and crop identity;
the pre-repair API audit also resolved all 114 crops. The queue manifests and target IDs did not
change. The ten conflicting identity drafts retain their decisions. Seven now point to copies of
the same original draft source; none was switched to the frozen queue target.

One older identity result for `game-2026-08-20-01-001` did not save a crop-input descriptor. Its
copy preserves that absence. The original video exists, but for card `pose-visible_cards-run-7b52fe8b-f4a-event-000000-card-0000` the current exact-frame
decode produced JPEG digest `323eefb3365ad9db83f3a6af95a75140d7f8bc916564e76f145aacb47551e138`, rather than the recorded `aab0caea14fe0a3b5170744bfc5d1f1d58e2ab9d93551e468dccb216779f201e`. The retained cache did not contain
the original JPEG. The result and decisions remain readable; the exact crop is unavailable. This
is not a claim that the video or every frame in that recording is missing.

The repair checks rejected stale selection revisions, changed source bytes, changed review decisions,
wrong recording lineage, and write failures. A separate copied-data application and restart check
passed before the active repair. The final fresh-store checks, focused backend tests, Ruff checks,
frontend component tests, type check, generated API check, and local Markdown link check passed.
Full web lint still reports two existing errors in the unchanged `CardEventFrameSurface.tsx`; the
changed web files passed their focused lint check. M6 remains responsible for the full trial
readiness checks.
