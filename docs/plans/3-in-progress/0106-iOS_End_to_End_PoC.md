# iOS end-to-end proof of concept

## Plan status

- **Summary:** Record video and detect card-state changes live on iOS, then run the remaining
  recording pipeline on the resulting event proposals and collect diagnostics.
- **Status:** In Progress
- **Depends on:** Epic 0105 M0–M2 execution contract and stage graph; the model artifacts and
  limitations from Epics 0103 and 0104. Compare against the completed 0105 local workflow when
  0105 M4 is available; this comparison is required for M6.
- **Outcome:** M0 and M1 complete. M2–M6 remain. Live capture retains event proposals, frame timing,
  frozen model lineage, and interruption evidence. No device result or model-quality claim exists.

## Purpose and scope

Use an iPhone to record a table and run CardEventNet during capture. After recording stops, use
its event proposals and the recorded video to run the remaining applicable stages through round
analysis on the device. Provide only the controls and status needed to run and inspect the PoC.
Keep intermediate results, diagnostics, and readable debugging log lines for each run.

Follow the stage semantics and input requirements of [Epic 0105](../5-closed/0105-One_Click_Recording_Pipeline.md)
without assuming its backend worker or Python services already run on iOS. M0 must identify the
on-device implementation or port for every stage, including calibration, proposed card scenes,
crops, table observations, and reconstruction. Use local fixtures for routine development. A real
iPhone is required for the final capture and device measurements.

The 0104 RF-DETR package has a full-parity gap that the user accepted for a bounded PoC; DINOv3
passed only the specified frozen-crop comparisons. CardEventNet has prior iOS support. None of
these facts establishes end-to-end accuracy or device performance. Keep model packages out of Git
and record the exact artifact identities and limitations used in each trial.

## Execution and evidence

- Collect required round facts and settings before processing. Do not infer missing gameplay facts.
  Recording and processing may have separate start actions. Report missing inputs clearly.
- Capture one continuous recording and run the existing causal event detector live. Preserve source
  timestamps, event proposal intervals and anchors, and the mapping to recorded video frames.
  Define sampling, orientation, dropped-frame, interruption, and timestamp behavior in M0.
- After capture, process every eligible event proposal through the applicable 0105 stages in order.
  Define valid empty outputs, calibration failure, and stop conditions in M0. Never silently skip a
  required stage or report a partial run as complete. Do not rerun event detection offline as a
  substitute for the live event stream.
- Retain the recording, frozen inputs, model identities, event proposals, stage outputs and failures,
  final analysis when available, and timing and resource observations. Make a run's diagnostics
  accessible from the app for local inspection or export. Keep diagnostic storage bounded and
  describe retention and cleanup. Generated results remain proposals, not reviewed ground truth.
- Emit readable timestamped log lines with run and stage identifiers, start and finish, event counts,
  timings, warnings, and actionable errors. Avoid per-frame log floods and keep logs free of
  unnecessary personal data. Show recording and processing state, progress, failure, and a way to
  inspect or export diagnostics in a minimal UI.
- This is a development PoC, not production readiness, model promotion, training, or an accuracy
  campaign. Do not require a server for the device pipeline.

## Milestones

### M0 — Freeze the device execution contract — Complete

The [device execution contract](../../reports/0106-M0_Device_Execution_Contract.md) records the
model identities, stage ports, time mapping, failure rules, diagnostics, and fixture obligations.

Inventory the existing iOS capture, event decoder, recording and diagnostics, the 0105 stage graph,
and exact Core ML artifacts. Map each stage to an iOS implementation or a bounded port, including
model preprocessing and postprocessing, data contracts, required round facts, frame extraction,
and the event-to-frame time mapping. Specify resource limits, empty and failure behavior,
interruption, diagnostic bundle contents, log format, and fixture and device acceptance. Identify
concrete blockers before implementation; do not claim that exports alone make the pipeline runnable.

Acceptance: a reproducible contract maps live event proposals to every downstream input and output,
identifies artifact locations and digests or actionable missing prerequisites, and names the
implementation and tests for each remaining milestone.

### M1 — Capture live events and retain a recording — Complete

Connect recording and causal event detection to one run. Persist event proposals and the timing and
frame mapping defined in M0 with the recording and model lineage. Record capture and inference
errors and bounded diagnostic logs.

Acceptance: deterministic capture and decoder fixtures cover event timestamps, frame selection,
dropped frames, empty events, stop, and interruption. A saved run can be reopened without changing
its event proposals.

The [M1 result](../../reports/0106-M1_Live_Capture.md) records the frozen model input, retained
timeline, error and interruption evidence, and verification results.

### M2 — Run visible-card and geometry stages

Implement the bounded on-device event-frame extraction, RF-DETR inference and postprocessing, and
the 0105 automatic calibration and geometry path. Save inputs, outputs, timings, and failures for
each stage, including empty outputs.

Acceptance: local fixtures exercise frame mapping, preprocessing, detection and geometry handoffs,
empty events and detections, and a blocking calibration or processing failure. Compare supported
fixed inputs with the frozen reference and record mismatches and the known RF-DETR parity limit.

### M3 — Run visual identity and assemble observations

Run the selected DINOv3 model on the defined crops and assemble table observations using the 0105
contracts. Preserve all candidates, abstentions, face-down evidence, and per-item errors under the
selected policy. Save lineage and diagnostics.

Acceptance: fixtures cover crop transforms, identity outputs, empty and unusable crops, partial
probabilities, and observation handoff. Compare the frozen DINOv3 crops with their reference and
report differences.

### M4 — Reconstruct and retain the round analysis

Run the remaining reconstruction and analysis on device from the saved observations and explicit
round facts. Retain intermediate state, terminal output, stage timings, and errors; preserve partial
results when a stage fails.

Acceptance: deterministic fixtures cover a complete path, valid empty inputs where applicable,
missing facts, and a reconstruction failure. The saved output can be inspected after app restart.

### M5 — Add minimal controls and diagnostic export

Provide the required input, recording and processing controls, progress, final status, error detail,
and access to the saved diagnostic bundle and log. Make the run lifecycle and storage limits clear.

Acceptance: automated app or component tests cover a complete fixture run, missing input, failure,
and reopening or exporting diagnostics. Log lines identify the run and failing stage.

### M6 — Verify the end-to-end iPhone trial

Run relevant automated checks and a bounded real-device recording with staged activity. Record the
device and OS, setup, artifact digests, inputs, event and stage counts, frame mapping, latency,
resource observations, output, logs, and failures. Compare downstream behavior on the same saved
inputs with the completed 0105 local workflow and explain differences and known parity gaps.
Document exact reproduction and diagnostic retrieval steps.

Acceptance: the report links a retained run from live capture through round analysis, or identifies
the exact stage and reproducible blocker with all partial diagnostics. A successful execution is
not an accuracy or production qualification. A blocker does not count as a successful end-to-end
trial.
