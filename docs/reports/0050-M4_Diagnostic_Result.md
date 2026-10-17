# Epic 0050 M4 diagnostic result

## Decision

M4 completed as a bounded local diagnostic. Corrected scene processing and identity processing
reached terminal results for all three recordings. Observation assembly rejected all three identity
revisions before it created an observation run. It reported that identity candidate probabilities
must sum to one within the contract tolerance. No observation output or reconstruction result exists.

The next limiting boundary is the identity-to-observation probability contract. M6 emits 24 card
identity candidates from a 25-class distribution that includes `FACE_DOWN`. The output does not
preserve the omitted probability mass. This makes the candidate probabilities invalid for observed
cards. M6 remains unqualified. M4 does not change the model, its output, or the observation contract.

## Preflight and scope

The M0 freeze included the correct real-round path and hash in the retained event request. Its local
preflight inventory used a different basename. M4 corrected that inventory entry and verified the
file at `data/intake/recordings/game-2026-08-20-01-001/videos/game-2026-08-20-01-001-video.mov`.
Its SHA-256 is
`2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa`. All 66 source, reference,
run, revision, and model checks passed before execution. No substitute source was used.

M4 reused all nine frozen event, detector, and original scene requests, states, and outputs. It ran
no event or detector inference. It used local providers only, made zero cloud requests, and did not
use sealed data, create labels, or change a model. The execution used implementation revision
`58ba9488c1f18cbe41461a8410e45e86ec788549`. The main checkout was clean before execution and no
source code changed during the batch. The source-file digests were captured after the runs and are
bound to their exact requests, states, and output hashes in the JSON report. A separate pre-run
implementation-digest record was not saved.

## Results

Event scores below are the retained 0090 scores. M4 did not rerun event inference. Card and pile
counts are separate. Detector counts are proposals, not quality scores.

| Recording | Reused events (matched / reviewed; F1) | Cards (detected / reviewed) | Piles (detected / reviewed) | New scene frames | New identity outcomes | Exact reviewed-crop pairs | Observation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | 48 / 51; 0.932 | 113 / 117 | 1 / 0 | 43 supported, 9 `no_cards_detected`, 0 failed; 113 poses | 112 classified, 1 face-down | 0 / 117 | Rejected with HTTP 422 |
| `cardeventnet-IMG_0662` | 42 / 50; 0.824 | 104 / 109 | 85 / 70 | 44 supported, 8 `no_cards_detected`, 0 failed; 104 poses | 104 classified | 0 / 109 | Rejected with HTTP 422 |
| `game-2026-08-20-01-001` | 39 / 49; 0.848 | 105 / 226 | 21 / 0 | 41 supported, 2 `no_cards_detected`, 0 failed; 105 poses | 100 classified, 5 face-down | Not available; no reviewed identity reference | Rejected with HTTP 422 |

The 19 frames that had zero individual-card candidates in the retained detector outputs now have
explicit `no_cards_detected` scene outcomes. Their pile evidence remains separate. No candidate-
bearing frame failed scene processing. Identity output counts match the detector card-candidate
counts; zero-card frames produced no identity outcomes.

The two shared `IMG_0662` decoded frames are frames 300 and 375. Seven predicted and seven reviewed
card geometries match at polygon IoU `>= 0.5`, as reported by M1. None of the predicted crop image
hashes match a reviewed oracle crop hash. `IMG_0657` has no shared identity frame; the real round
has no reviewed identity revision. M6 predictions need human review, so these inputs support no
identity-quality claim.

The three observation requests each supplied the exact retained event and detector revisions and
the new identity revision. Each was rejected before a processor run or output revision was created.
The validation tolerance is `1e-6`. Candidate probability sums outside that tolerance were 66 of
112 classified outcomes for `IMG_0657`, 61 of 104 for `IMG_0662`, and 60 of 100 for the real round.
The failure is consistent across all recordings. M4 did not normalize the scores or retry the
requests.

Reconstruction was skipped for the real round. Its frozen source record has no explicit active
players, dealer, or first-trick leader. No context was inferred. The other recordings are staged
trick sequences and have no reconstruction run.

## Budget and stored outputs

The batch ran from `2026-10-17T07:47:50Z` to `2026-10-17T07:59:13Z`, about 11 minutes 23 seconds.
It used 6 of at most 9 new processor executions: three scene and three identity runs. The three
observation requests were rejected before processor creation. There were no event, detector, or
reconstruction executions. The maximum sampled backend RSS was 1.03 GiB against the 32 GiB limit.
RSS was sampled at progress checkpoints about every 30 seconds, so this is the maximum observed
sample, not continuous peak capture. The zero-cloud-request limit held.

The six new processor runs and their output revisions are retained under
`data/operations/pipeline/runs/` and `data/operations/pipeline/revisions/`. The JSON companion
lists every path, request and state digest, exact input revision, output revision, and output hash.
The API temporarily changed the three generated identity selection pointers. After stopping the
backend, M4 restored each pointer byte-for-byte to its prior tracked value. The original 0090
artifacts remain unchanged.

## Handoff

The next bounded question is: how should the 25-class identity output preserve `FACE_DOWN`
probability while it supplies a valid 24-card identity distribution to observation assembly, without
treating `FACE_DOWN` as a card identity? Any implementation needs a new epic with its own contract,
measurements, and budget. M4 selects no model or additional capability.

The machine-readable report is [0050 M4 diagnostic result JSON](0050-M4_Diagnostic_Result.json).
