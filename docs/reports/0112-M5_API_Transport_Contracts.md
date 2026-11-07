# 0112 M5 API transport and contracts

## Result

`web/src/api/transport.ts` now owns `ApiError`, JSON request handling, HTTP error-body decoding,
JSON headers, timeout conversion, caller abort forwarding, and cleanup of abort listeners and
timers. Blob response errors use the same response-body decoder.

Retained hand-written contracts moved out of `client.ts` into:

- `recordingContracts.ts` for recording list and detail responses.
- `pipelineContracts.ts` for pipeline workspace, run, selection, comparison, result, and frame
  review contracts.
- `calibrationContracts.ts` for calibration refinement and calibration response contracts.
- `analysisContracts.ts` for round analysis and counterfactual contracts.
- `jobsContracts.ts` for job names backed by the existing generated OpenAPI schemas.

`client.ts` continues to expose the existing types and methods. M6 owns movement of API methods and
paths. The transport keeps its optional timeout argument for direct transport use and tests. No
client call configures a timeout.

The migration-only legacy processor-run reader has two consumers: runtime inventory code in
`lineage_migration_inventory.py` and the offline `backend/scripts/repair_0100_m5.py` repair tool.
The active epic handoff now records both. Neither consumer is a runtime store.

## Verification

- `npm test -- --run src/api/client.test.ts src/api/transport.test.ts` — passed, 17 tests.
- `npm run typecheck` — passed.
- `npx eslint src/api/client.ts src/api/transport.ts src/api/transport.test.ts src/api/analysisContracts.ts src/api/calibrationContracts.ts src/api/jobsContracts.ts src/api/pipelineContracts.ts src/api/recordingContracts.ts` — passed.
- `npx prettier --check src/api/client.ts src/api/transport.ts src/api/transport.test.ts src/api/analysisContracts.ts src/api/calibrationContracts.ts src/api/jobsContracts.ts src/api/pipelineContracts.ts src/api/recordingContracts.ts` — passed.
- `npm run verify:api` — passed. Export logged that its temporary processor-run catalog resource root was unavailable; generated API diff passed.
- Changed contract modules and transport are below the 700-line production-module budget. The transport test is below the 800-line focused-test budget.

Transport tests cover successful JSON, JSON/text/empty HTTP error bodies, timeout conversion,
caller abort reason propagation, listener cleanup, timer cleanup after timeout and success, JSON
headers, and `ApiError` fields.
