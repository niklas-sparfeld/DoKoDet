# 0100 M4: Local model recipe

This is a development recipe for the existing local models. It does not promote a model or
qualify its quality. The [0090 freeze](0090-M0_Composed_Pilot_Freeze.json) records the model
identities and their limits. The 0088 M6 predictions require human review.

## Setup and preflight

Install the backend and its local inference dependencies with the declared toolchain:

```sh
mise exec -- uv sync --project backend --group inference
```

The files under `.runtime` are ignored local artifacts. A fresh clone does not contain them. Restore
these complete directories from the retained artifact backup of this checkout, preserving every
file and its bytes:

- `.runtime/rfdetr-segmentation-0092-m4/bundle` (manifest and checkpoint).
- `.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle` (manifest, encoder, head,
  configuration, calibration, target map, and bundled pretrained files).

Also restore the 0063 integration contract and checkpoint at the paths in the 0090 freeze if they
are missing. The [0092 M4 report](0092-M4_Final_Refit.md) and
[0088 M12 lock](0088-M12_Final_Evaluation_Lock.md) record their retained lineage. If no retained
copy exists, this recipe cannot restore the weights from Git; locate the artifact backup before the
trial. Do not train a replacement or run the sealed evaluator.

From `backend/`, export the example in the same shell that starts the service:

```sh
set -a
source local-pipeline.env.example
set +a
.venv/bin/python -m dokodetector_backend.local_pipeline_preflight
.venv/bin/dokodetector-backend
```

The example selects CPU for all three processors. To use MPS, set all three device variables to
`mps` after sourcing the example. The preflight validates device availability and the model bundle
schemas, file hashes, frozen bundle digests, event checkpoint, and decoder settings. It makes no
cloud call and runs no inference. It reports mismatched or missing files and stale effective
settings. Remove a conflicting `CARD_EVENT_CHECKPOINT_PATH` from `backend/.env` or the environment.
The preflight must pass before the service starts. Use the direct `.venv/bin` commands shown here:
the backend `mise.toml` loads `backend/.env`, and a `mise` shim can reapply its stale values after
the example is sourced. The normal default remains Gemini when this recipe is not selected.

## Processor requests

In the recording workspace, run events first. For visible cards, choose **Local · RF-DETR
segmentation** and use the generated event revision. For visual identities, choose **Local** and
select the generated **RF-DETR** crop input from that detector revision. The UI sends the
`predicted_visible_region` PPM crop policy. Inspect the saved request to confirm its provider,
bundle identity, device, input revision, and crop policy. The event request records the checkpoint
hash, threshold, merge window, and device. The local full-frame detector records both visible-card
and pile proposals. Fine-frame refinement remains an explicit alternate and is not this recipe.

For the coordinator, copy [the staged request example](../../backend/local-pipeline.requests.example.json)
and pass it to `dokodetector-pipeline-coordinator` through the same environment and backend. It
selects the full-frame detector, local identity classifier, RF-DETR crop input, and predicted region
crop. It explicitly skips reconstruction because a staged sequence has no round context. For a
real round, replace the skip with the actual required context; never invent it. See the
[coordinator guide](0090-M1_Retained_Pipeline_Coordinator.md) for the command and request fields.
The backend saves the concrete provider and model lineage in the processor requests. Explicit
provider selections in browser or coordinator requests take precedence over settings; do not select
Cloud for this recipe. There is no Gemini fallback after a local failure.

The 0063 development checkpoint uses threshold `0.4271905720233917`, causal peak confirmation
`0.125 s`, and minimum event gap `0.625 s`. Its checkpoint SHA-256 is
`258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4`. The detector bundle digest is
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`; the identity bundle digest is
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`. A completed processor run
produces proposals, not reviewed ground truth. M4 makes no claim about real-round accuracy.

## Verification

On 2026-10-30, the preflight validated the exact retained bundles and checkpoint on CPU. With
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, the installed backend constructed both local
providers with those bundle digests. This check did not run inference or make a cloud request.
The focused backend tests cover provider selection, device forwarding, saved bundle identity,
compatible crop inputs, rejected stale bundle or device settings, and the coordinator. The browser
component test selects the local classifier and an RF-DETR crop input. The M6 milestone owns the
bounded real-input inference probes and the combined workflow.

Three broader backend tests fail on the unchanged `HEAD` backend source as well: the pipeline route
inventory expects 36 stage routes but finds 38; a crop-preview test expects one canonical resolution
but finds none; and an identity result test expects `state.items` where the response omits it.
They are not evidence of a completed M5 review-target check. M5 must assess the preview and result
contracts when it verifies current editor access; the route inventory assertion also needs an
owner. The focused M4 tests pass.
The web typecheck and focused component lint and format checks pass. The full web lint reports two
pre-existing `react-hooks/set-state-in-effect` errors in `CardEventFrameSurface.tsx` and one hook
dependency warning in `VisibleCardReviewWorkbenchView.tsx`; M4 does not change those files.
