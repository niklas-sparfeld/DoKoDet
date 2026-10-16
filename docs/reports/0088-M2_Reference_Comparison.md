# 0088 M2 Gemini and PoC references

## Result

Gemini classified 209 exact reviewed development crops. It returned 203/208 face-up identities correctly (97.6% top-1). The full 21-class view returned 204/209 reviewed identities correctly (97.6% top-1). It returned 0 provider failures. All results came from exact request-cache matches, so this milestone made no new Gemini requests and incurred no new provider spend.

The retained 0043 PoC result covers 301 crops, with 283/301 top-1 correct (94.0%). This is a different historical validation set. The retained bundle is now rejected by the current loader as an obsolete uncalibrated smoke format, so M2 does not claim a new same-crop PoC run. The report keeps the two reference conditions separate and lists their input differences.

The Gemini score is a development reference against human labels, not ground truth for future training. The paired rows contain crop digests, reviewed labels, Gemini outputs, and source groups. The held-out final test remains unopened.

## Gemini coverage

- Exact cache hits: 209/209.
- New requests: 0 (limit 250).
- New spend: USD 0.00 (cap USD 10.00).
- Reused receipts record USD 0.1936 in provider cost.
- FACE_DOWN support: 1; report this as exploratory evidence only. It does not support precision, recall, calibration, or generalization claims.

## Retained PoC limits

- Historical evaluation schema: `dinov3-identity-bundle-evaluation/v1`.
- Historical status: `unusable_smoke_artifact`.
- Unsupported positive classes: CLUBS_NINE, DIAMONDS_NINE, FACE_DOWN, HEARTS_NINE, SPADES_NINE.
- FACE_DOWN measured: False.
- The Gemini and PoC sample IDs do not form a same-crop pair. Their metrics must not be read as a direct model ranking.

## Error examples

| Sample | Source group | Reviewed label | Gemini result | Crop SHA-256 |
| --- | --- | --- | --- | --- |
| `cardeventnet-IMG_0657:pose-visible-cards-0086-91x59-IMG_0657-74451f0a-cardeventnet-event-img_0657-037-card-0001` | `source-group-9d6d4824b53bc4a9` | `SPADES_QUEEN` | `CLUBS_QUEEN` | `798fd61405fe1e99e0579888ec971fde20c7285080fc8b60de1bc44efac97ca6` |
| `cardeventnet-IMG_0657:pose-visible-cards-0086-91x59-IMG_0657-74451f0a-cardeventnet-event-img_0657-038-card-0002` | `source-group-9d6d4824b53bc4a9` | `SPADES_QUEEN` | `CLUBS_QUEEN` | `89f500ede8a322d44fdfc4f96e04435cb64f7b530554e28f12d683a1a341a83f` |
| `cardeventnet-IMG_0662:pose-visible_cards-run-58a11cf2-2d0-cardeventnet-event-img_0662-002-card-0000` | `source-group-d4543cb23cc73b35` | `CLUBS_JACK` | `CLUBS_KING` | `89ff67638e0559fa54b82f5e4750d0a4a313d7d05b9c21662d2543239d4b7398` |
| `cardeventnet-IMG_0662:pose-visible_cards-run-58a11cf2-2d0-cardeventnet-event-img_0662-036-card-0012` | `source-group-d4543cb23cc73b35` | `SPADES_ACE` | `UNKNOWN` | `5c30751ade1cb421b765e4e776bbf9199d6fe86d1e64ee97f85320a03b5f1bc2` |
| `cardeventnet-IMG_0662:pose-visible_cards-run-58a11cf2-2d0-cardeventnet-event-img_0662-037-card-0002` | `source-group-d4543cb23cc73b35` | `SPADES_ACE` | `UNKNOWN` | `5b763b5cde8cf489e34aba0a91349f4bcff9004b943717101d348821581e5e8c` |

## Reproduction

Run `operations/scripts/run_0088_m2_reference_comparison.py` with the M1 campaign directory and exact Gemini request cache. The script disables live requests and fails if any crop lacks an exact cached request receipt.

The full class confusion matrices and all paired rows are in [the machine-readable report](0088-M2_Reference_Comparison.json).
