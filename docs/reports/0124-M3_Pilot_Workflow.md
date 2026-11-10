# 0124 M3 pilot workflow

Status: In progress

## Outcome

Use the normal recordings app with the retained `cardeventnet-IMG_0662` pilot. Play the video,
inspect and correct an event set, launch visible-card detection from the selected event set, and
reopen the saved result and exact input after restart.

## Finding and change

The normal browser route reached the event-set editor and saved a corrected alternative. Detector
launch then failed because `VisibleCardPipelineService._accepted_source()` called the retired
recording catalog and read the old bundle video path. The folder-backed workflow already stores its
source media in the recording root. The service now resolves media, byte length, and digest from
that root through the existing `EventSetStore.recordings` store. This adds no authority or storage
contract.

## Browser workflow

`web/tests/recording-folder/recordings.spec.ts` now covers the normal list, workspace playback,
event-set review and correction, generated selection, unselected-set browse, detector launch,
result inspection, selection change, restart, and exact event input reopen. The backend server
uses a disposable recording folder with persisted event sets and a deterministic detector. The test
also forbids old recording catalog reads and old event selection reads.

The retained pilot conversion was rehearsed in disposable storage. The saved source digest and both
event content digests matched their frozen inputs after restart. The pilot was then activated at
`data/recordings/cardeventnet-IMG_0662`. The original source bundle, event nodes, and selector files
remain unchanged. Existing reviews for the exact selected event revisions number zero. Recovery
inputs and the removal-only rollback instruction are at
`data/operations-recovery/0124-m3-20261110/snapshot.json`.

## Verification

- `pytest backend/tests/test_recording_folder_store.py backend/tests/test_event_set_store.py backend/tests/test_visible_card_pipeline_api.py backend/tests/test_pipeline_api.py backend/tests/test_recording_catalog_growth_contract.py -q` — passed.
- `npx playwright test --config playwright.recording-folder.config.ts --reporter=line` — passed, 3 tests.
- `npm run check` — passed: typecheck, lint, format, generated API verification, and 244 tests.
- `npm run build` — passed.
- Ruff check and format check for the changed backend service and browser server — passed.
- Pilot conversion rehearsal and source/event digest comparison — passed.

## Remaining acceptance

The required real-provider smoke through the normal local app is not complete. The backend on port
8000 owns the main operations job lock. Its active and all-job lists were empty, but it still runs
the main-worktree code and does not serve this fix. After the fixed commit reaches `main`, restart
that backend with its existing command and configuration. Then use the normal app to play the
activated pilot, edit and select an alternative, run the already configured local detector, inspect
the saved output, change event selection, restart, and reopen the exact event input. Record the
provider, result ID, and any limit here before marking M3 complete.
