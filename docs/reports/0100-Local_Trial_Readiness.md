# 0100 local trial readiness

## Result

M6 is complete. The fixture service checks pass across event proposals, visible-card and pile
proposals, proposed scenes, visual identities, table observations, and round analysis persistence.
The focused browser checks can inspect a saved round analysis. The local model probes below also
completed with the frozen bundles on CPU. These checks establish that the current code can execute
the workflow. They do not establish that a reconstruction is correct.

The next task is one operator trial with a real round. Use
`game-2026-09-18-01-003` as the suggested source. Its source record identifies game
`game-2026-09-18-01`, round `round-003`, and session `session-2026-09-18`. It is a real-game manual
round split from `IMG_0724.MOV` at 00:14:24–00:18:08.702. The source record does not contain the
players, dealer, first-trick leader, or rules version.

## Local setup

From the repository root, install the declared tools and backend packages:

```sh
mise install
mise exec -- uv sync --project backend --group inference
```

Restore the ignored local model artifacts from the retained artifact backup. Keep every file byte
unchanged. The required paths and exact model identities are listed in the
[M4 recipe](0100-M4_Local_Model_Recipe.md):

- `.runtime/rfdetr-segmentation-0092-m4/bundle`;
- `.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle`;
- the 0063 CardEventNet checkpoint and integration contract named in the M4 recipe.

These files are not in Git. A fresh clone does not contain them. Do not train replacement models.

Install web dependencies from `web/`:

```sh
cd web
npm ci
```

## Start the local workflow

In one terminal, start the backend with the explicit local recipe:

```sh
cd backend
set -a
source local-pipeline.env.example
set +a
.venv/bin/python -m dokodetector_backend.local_pipeline_preflight
.venv/bin/dokodetector-backend
```

The preflight must pass before the service starts. The example selects CPU for CardEventNet,
RF-DETR, and DINOv3. The direct `.venv/bin` commands keep `backend/.env` from overriding the
selected recipe through a `mise` shim. The local recipe makes no cloud calls and does not fall back
to Gemini.

In another terminal, start the web app:

```sh
cd web
npm run dev
```

Open `http://localhost:5173/recordings`, select `game-2026-09-18-01-003`, and open its pipeline
workspace. Run the stages in order: events, visible cards and piles, proposed card scenes, visual
identity proposals, table observations, then round analysis. Wait for each processor to finish
before starting a dependent stage. Inspect the run requests and results to confirm the selected
provider, bundle digest, device, input revisions, and predicted-region crop policy. Preserve partial
and failed outcomes as diagnostics; do not treat a request acceptance as a completed run.

For round analysis, enter the confirmed game and round context. Then inspect the saved analysis in
the workspace. Reload the page and confirm that the result and its timeline still open. Identity
outputs are proposals that need human review. Do not mark a proposal reviewed unless a person has
checked it.

## Operator input

The source record already supplies the game, round, session, and video identity. Before round
analysis, the operator must supply or confirm:

- four active players in seat order;
- the dealer, who can sit out the round;
- the first-trick leader, who must be an active player;
- the supported rules version.

Do not infer these facts from video or use seat examples as confirmed values. The first real trial
must record the values that the operator confirms.

## Bounded model probes

The probes ran on 2026-10-31 in the refreshed main checkout. They used CPU and the local models only.
The M4 preflight validated all three frozen model identities before inference.

| Processor | Input | Result | Lineage |
| --- | --- | --- | --- |
| CardEventNet | Two seconds from the suggested recording at 30 s | 16 probability rows, zero event proposals; completed in 3.86 s | Checkpoint SHA-256 `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4` |
| RF-DETR | One decoded frame from the suggested recording at 30 s | 2 card proposals and 4 pile proposals; completed in 3.23 s | Bundle digest `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c` |
| DINOv3 | One PPM crop from an RF-DETR card proposal | One identity result with 24 candidates; completed in 0.36 s | Bundle digest `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79` |

The zero event proposals are a terminal result for this two-second probe, not a model failure or a
quality score. The card and pile counts are raw proposals. The identity candidates are not verified
labels. These probes do not support accuracy, latency, calibration, or production claims.

## Reconstruction limits

Round analysis requires explicit search limits for missing plays, hypotheses, and search nodes. The
engine can return an unresolved result when evidence conflicts or a limit stops the search. An
execution that stores a result proves that the processor completed its contract. It does not prove
that the result matches the real round. The current workflow has no reviewed reconstruction target
for this source and no measured end-to-end reconstruction accuracy.

Piles remain separate evidence. They do not become card plays. Zero-card frames remain observations
with no card plays. Identity predictions remain review-required proposals.

## Verification

The following checks passed in both the task checkout and the refreshed main checkout at the same
source revision:

- backend API suites for events, visible cards and piles, proposed scenes, identities, observations,
  coordinator flow, and round-analysis persistence;
- the API suites above after excluding two baseline assertions that expect the removed
  `state.items` field;
- focused browser checks for explicit round context and saved round-analysis inspection;
- web type check and generated API verification;
- M4 local-model preflight and the three bounded CPU probes above.

The clean Python environment sync and `npm ci` from `web/` both completed. Backend Ruff passes after
the one-line formatting correction to `pipeline_reference_handlers.py`.

Known baseline checks still fail in untouched paths. Two identity API tests expect `state.items`,
which the current result contract does not return. The full recording-workspace browser suite has an
outdated URL-state expectation and Vitest Blob cleanup errors. Full web lint reports two existing
errors in `CardEventFrameSurface.tsx` and one warning in `VisibleCardReviewWorkbenchView.tsx`. The
full web format check reports seven existing files. The full backend Ruff format check reports 19
other existing files; the changed backend file passes its focused check. These checks are not
evidence of a model or workflow contract failure. The focused M6 browser tests pass.

The M5 original identity crop for one old result remains unavailable, as recorded in the
[M5 handoff](0100-M5_Review_Access.md). This does not block the suggested recording or the bounded
probes.
