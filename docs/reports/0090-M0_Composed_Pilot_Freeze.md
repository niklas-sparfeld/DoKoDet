# 0090 M0 composed pilot freeze

Date: 2026-10-16

## Decision

Freeze three recordings for a local development pilot: two staged trick sequences and one real
round. This batch contains clean and overlapping card scenes, reviewed event and card geometry
references, and a known visible-card detector failure. Identity references exist for the staged
sequences. No reviewed reconstruction reference is available in this batch. Report that coverage
gap; do not make a reconstruction quality claim without a reviewed target.

The batch is for development measurement. It does not qualify a model, change a default, or support
production use. No pipeline stage ran during this freeze.

## Frozen recordings and references

The source and reference digests below come from the intake and pipeline stores at commit
`41532a756` (`Close epic 0089 after fresh replay`). The
[machine-readable freeze](0090-M0_Composed_Pilot_Freeze.json) gives the same inputs to M1 preflight.
All three sources permit evaluation use.
The reviewed references are comparison targets only. They are not execution inputs.

| Recording | Type and role | Source SHA-256 | Event reference | Card geometry reference | Identity reference |
| --- | --- | --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | Staged sequence; clean and overlapping scenes | `23df5b4dbf0d0d80c79161ba32c1f4c4db8473f053fdd9b63508c66e38d3658b` | `reference-events-17e0b4ea8fc84cec099e237467798fdd` / `b7b928f5e1738af2343dba68e83a4edee10c2e7dcd7141d03282b9d4971fa4f3` | `reference-visible_cards-9825ffb099bab16c735b114ec4c4050a` / `cd87d26bddae0677f7646b5084d8832bdf668d7a9277ee144715db236b31b058` | `reference-visual_identities-cd3866d5633c58efaff44bf46ef7637f` / `186aa09f1599990395f800a17e18ad81ed970909a65726f4779d69fe9aa341ad` |
| `cardeventnet-IMG_0662` | Staged sequence; known detector no-match case | `2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7` | `reference-events-fd5c08dc4f7540053b3ed1c04606b909` / `00ce1f56caf862db76601d6e82cd36587d56f2c9fd23de208364559b910832f5` | `reference-visible_cards-bf287d3bff82dec774f16be1ccc736f0` / `d098847ee1ee68d6a3e9a3977d7b254bfff762008f9ffccf0ad0ae90625f147d` | `reference-visual_identities-4026272dca1192019417b0b8ad200eeb` / `f782a4c5b9aac7e59be952a7e3f3254a0d472f71787aeff45f0242d6cf1aef99` |
| `game-2026-08-20-01-001` | Real round; reviewed event and card geometry coverage | `2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa` | `reference-events-e22b24bde3ef35a56ab930873b2200cc` / `685cc65c97b7ec4b6e4ebe7db645e451ecb9d46ad2b2e42a64bec742b78bd088` | `reference-visible_cards-25c56fb38af9a5604283bbc57789e690` / `6710ff5ce7758561ea2d1c1c5278cb90974162bbebbd01af37b75e70fd9a4a3a` | None. Treat identity as unreviewed. |

The selected geometry references contain 22 single-card scenes and 66 multi-card scenes in the
staged sequences, plus two single-card and 47 multi-card scenes in the real round. The 0089 replay
found zero reviewed-card polygon matches at IoU 0.5 for the automatic outputs from `IMG_0657` and
`IMG_0662`. Keep `IMG_0662` as the frozen known-failure case. This failure is expected diagnostic
evidence, not a reason to remove the recording.

The frozen source groups are `source-group-9d6d4824b53bc4a9` (`IMG_0657`),
`source-group-d4543cb23cc73b35` (`IMG_0662`), and `session-2026-08-20` (the real round).

Do not use `cardeventnet-IMG_0095`; its source record permits training use only. Exclude protected
test sources `cardeventnet-IMG_0654` (0087), `cardeventnet-IMG_0659` (0088), and
`cardeventnet-IMG_0656` and `cardeventnet-IMG_0660` (0092). Do not use any sealed test data or
predictions.

## Frozen stage recipe

Run each recording from its original video, in this order:

1. Event proposals from video.
2. Visible-card and pile proposals from the event frames.
3. Card-scene and calibration processing from automatic detector geometry.
4. Visual identity proposals from crops made from automatic predicted geometry.
5. Table observations, then reconstruction from the automatic outputs.

Use the M14 accepted CardEventNet development baseline: checkpoint
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt`,
SHA-256 `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4`. Use threshold
`0.4271905720233917` and the locked causal-peak decoder (`peak_confirmation_s=0.125`,
`min_event_gap_s=0.625`, `event_match_tolerance_s=0.75`). This is a development baseline, not a
production champion.

Use the 0092 M4 RF-DETR bundle at
`.runtime/rfdetr-segmentation-0092-m4/bundle`, bundle digest
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`, checkpoint SHA-256
`80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. Verify the manifest digest
`826ccba533531c62a2059be5889b9c48aa44800df5d216997575a238c37f5816` before execution. This
two-class bundle supersedes the 0087 candidate for this pilot. It supports `visible_card` and
`card_pile`; report both classes separately. Pile evidence remains separate from individual cards
and must not create identity, card pose, plays, or winners.

Use 0088 M6 seed 17 for identity diagnostics: bundle digest
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`, checkpoint SHA-256
`ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a`. Use the locked 224-pixel
RGB P6 PPM preprocessing. Treat every identity result as a proposal for human review. The model is
unqualified. Do not use the 0.90 confidence value for auto-accept or abstention. A paired M3 run is
outside this fixed batch.

Use the automatic `predicted_visible_region` crop policy. Do not substitute reviewed geometry for
execution crops, call Gemini, change model defaults, tune a threshold, train, or promote a model.
Use exact-event frame extraction with `ffmpeg/8.1.2`. Pin the application source to the M0 parent
revision `41532a756`; the M1 preflight must record the exact coordinator and processor code digests.

## Gates and budgets

Preflight must finish before any stage starts. It must verify the exact three source digests, source
permissions, reference revision digests, model bundle and checkpoint digests, software versions,
and stage order. It must reject any missing or changed input. It must confirm the protected-source
exclusions and show the lack of reviewed reconstruction targets. Missing identity coverage for the
real round is explicit and does not block the pilot.

The report must include, for every recording and stage, the exact input and output revision, source
and model lineage, reviewed comparison coverage, runtime, terminal outcome, and operator action.
Report event matches with the locked 0.75-second event tolerance; report visible-card and pile
matches at polygon IoU 0.5; report identity metrics only for exact reviewed-crop matches. Report
observation and reconstruction results separately. A stage with no reviewed comparison coverage
has no quality claim. Do not combine stage scores into one quality score.

Limit the pilot to one initial execution per stage and recording, no cloud requests, six hours of
total wall time, and 32 GiB peak process memory. Resume may reuse unchanged completed stages. A
failed preflight starts no stages. A stage failure stops dependent stages for that recording;
other recordings may continue. Any rerun requires an explicit recorded decision and remains inside
the same budget.

## Handoff

M0 is complete. M1 can implement the coordinator and deterministic preflight around this frozen
contract. The pilot remains diagnostic. The sealed system holdout remains unused.
