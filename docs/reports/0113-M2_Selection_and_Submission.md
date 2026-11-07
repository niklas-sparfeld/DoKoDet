# 0113 M2 exact selection and submission

M2 adds reusable exact revision and model fields, dependency-keyed choice loading, and one shared
job submission owner. Revision choices expose both the data node and immutable revision. The field
requires an explicit choice and excludes incompatible revisions. Model choices expose unavailable
options and reasons but only allow an available model to be selected.

`useJobStartChoices` aborts requests when the caller's dependency key changes and ignores late
responses. Callers must include the recording and selected prerequisite identity in that key. The
field and hook do not build an action request; every action retains its own request construction.

`useJobSubmission` prevents concurrent clicks. It sends one idempotency key for the exact payload and
keeps that key after an uncertain response so a retry reconciles the same request. A definite 4xx
rejection clears the key. `useManagedJobSubmission` delegates acceptance to the existing jobs API,
refreshes the app-owned Jobs state once, and returns a shared `/jobs/<id>` receipt. It adds no polling
owner. Existing `POST /api/jobs` acceptance validates registered job inputs and frozen revisions, so
M2 required no server or generated API change.

## Verification

- `npm test -- --run src/jobs/JobStartInfrastructure.test.tsx` — passed, 7 tests. Covers ambiguous
  exact revision selection, multiple exact input roles, unavailable models, stale responses after
  recording change, double-click exclusion, one accepted job link, definite rejection, and retry
  after a lost acceptance response with the same key and payload.
- `npm run typecheck` — passed.
- Focused ESLint and Prettier checks for the four changed source/test files — passed.
- `git diff --check` — passed.

M2 did not edit `RunControls` or any feature launch path. 0112 M8 remains unstarted. M3 owns the
first feature integration and request construction remains with each feature caller.
