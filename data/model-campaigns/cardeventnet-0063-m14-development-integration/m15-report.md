# CardEventNet M15 integration closeout

- Campaign: cardeventnet-0063-m14-development-integration
- Outcome: m9_retained_as_development_integration_baseline
- Integration model: data/model-campaigns/cardeventnet-0063-m14-development-integration/integration-model/CardEventNet.mlpackage
- Checkpoint: data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt
- Production promotion eligible: False

The M9 hard-negative checkpoint remains the development baseline. The sealed test is an
informational integration measurement, not a tuning or promotion decision.

## Sealed-test result

- Recordings: 5
- Real events: 233
- Detected true events: 193
- Missed events: 40
- False events: 364
- Recall: 82.83%
- Precision: 34.65%
- F1: 48.86%
- False events per hour: 762.30

The existing production gates remain recorded in the M14 lock for information only.
The sealed-test result does not alter the locked threshold, decoder, candidate, or registry.

## Runtime contract

- Runtime load: passed
- Input: clips [1, 8, 3, 224, 224]
- Output: logit
- Preprocessing: full_frame_letterbox_v1
- Parity maximum absolute error: 1.33514e-05

## Downstream measurement questions

- Does an event produce a correct stable table observation?
- Can a later proposal recover an early proposal?
- Does a miss cause a persistent reconstruction error?
- Do duplicate or false proposals corrupt state, or only add computation?

The five old-phone recordings remain a separate legacy_device_diagnostic population.
No diagnostic command was run or merged into this campaign.

Epic 0063 is closed. Defer more CardEventNet training until downstream evidence identifies
a concrete, non-recoverable failure class.
