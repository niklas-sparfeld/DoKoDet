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

## Live provider smoke and gap

After commit `0080631a` reached `main`, the backend on port 8000 had no active or queued jobs. I
restarted it with the existing command and configuration. The normal recordings list and event-set
editor opened the activated pilot. The video played in the browser at 2.2 seconds. The editor opened
`retained-reference@1`, saved and selected the edited alternative
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`, then opened the unselected `retained-generated@1`.

The first detector launch returned HTTP 422 because the existing environment lacked `rfdetr==1.9.4`.
I installed the project's existing `inference` dependency group with `mise exec -- uv sync --project
backend --group dev --group inference`. The bundle and checkpoint were already present at
`.runtime/rfdetr-segmentation-0092-m4/bundle`; no model weights were acquired. I restarted the same
backend command and launched once through the normal app with the configured local provider.

The provider was `local-rfdetr-fine-frame` v8 on MPS, using bundle digest
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c` and checkpoint digest
`80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. Job
`7111edd7-9f72-4fdc-9c10-a90d94db172f` froze the exact input event set digest
`a3c284533668d7b316f65142718262424f62769e85bd19d0f67e177fb6b84c78` and source video digest
`2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7`. Its processor run recorded
50 of 50 event outputs and a 1,177,157-byte visible-card revision with digest
`905ecbb65fc9137a15187f9bd0465e8f7923d120bbaff1b7840411250c582e23`.

The normal app initially showed the completed processor run and revision, while its job stayed in
`Publish visible-card revision`. For 7 minutes 18 seconds after the processor state became complete,
`publication.json` remained `prepared`, `job.json` remained `running`, and the backend did not answer
Job Manager requests. At 5:19 elapsed, PID 50672 used 98.4% CPU and 18.7% memory; the read-only
sample `/tmp/python_2026-11-10_210747_3Cs5.sample.txt` showed CPython's JSON encoder serializing
nested lists and floats. The process held the existing `.transactions.lock` and node lock. I did not
restart or interrupt the active write. It committed at 21:11:51 local time, about 8 minutes after
launch. The backend then answered again. This is a long local publication delay; no new transaction
or authority was added.

The normal app opened the saved exact node revision and showed 50 event outcomes, including its
first frame. Its exact event parent remained `manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1` with
the frozen content digest above. The detector result digest is
`905ecbb65fc9137a15187f9bd0465e8f7923d120bbaff1b7840411250c582e23`.

A later attempt to select an unedited retained set in the editor returned HTTP 422. The editor kept
the complete list entry in state and sent its `events`, `source`, and `provenance` fields where the
API requires only `set_id` and `version`. The M3 editor now projects the exact reference on open and
on selection. The browser regression checks the PUT returns 200 and the UI confirms the new choice.
The recording-folder E2E passed (3 tests), `npm run check` passed (244 tests plus type, lint,
format, and generated API checks), and `npm run build` passed after this change.

The local provider run and normal-app result inspection passed, but M3 remains incomplete until the
selection fix is integrated into the active app, direct selection of the unedited alternative
passes there, and the backend restarts with the exact input and unselected alternative reopened.
This smoke is not production qualification.
