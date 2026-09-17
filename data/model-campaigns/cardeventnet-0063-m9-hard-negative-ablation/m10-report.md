# CardEventNet M10 timing-review handoff

- Campaign: `cardeventnet-0063-m9-hard-negative-ablation`
- Packet: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-timing-review.json`
- Packet digest: `eb47261ca4236c59c9dbab4565c77a4f8cec66804b9413e8c956a54f8444bc12`
- Selected checkpoint: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt`
- Checkpoint SHA-256: `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4`
- Validation threshold: `0.4271905720233917`
- Decoder: `{"min_event_gap_s": 0.625, "peak_confirmation_s": 0.125}`
- Raw review items: `70`
- Grouped review regions: `47`

M10 is a read-only handoff. Do not change a maintained reference from this report. If the reference is wrong, create and complete a new draft in the recording workspace.

## M7 and validation lineage

- Dataset: `cardeventnet-interval-dataset-2e00fe87f08e25c51aa4` (`2e00fe87f08e25c51aa40d68ec2a212001bdff9a4586f86affd72703d04813ca`)
- Split: `cardeventnet-interval-split-99ff7cb84e5484c7b4a1` (`99ff7cb84e5484c7b4a16fda24e2b1d4812f598b0dc876c52b8e0bd25298ad24`)
- Materialized view: `.runtime/cardevent/datasets/cardeventnet-interval-dataset-2e00fe87f08e25c51aa4`
- Validation stream: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/validation-streams/evaluation.json.gz` (`aa58a2ef7843dfc923486dd5a4191567768d18ad9a2238050924826631acd8aa`)

## Ordered operator checklist

1. **Review `cardeventnet-IMG_0090`.** false triggers, merged or near misses, and repeated decoder triggers.
   - Miss anchors: `29.743, 32.103, 50.044, 110.871` seconds.
   - Predictions: `36.750, 48.500, 54.625, 61.000, 62.375, 64.125, 64.875, 71.125` seconds.
   - In-progress predictions: `9.750, 91.500, 110.000` seconds.
   - Treat 61.000–64.875 seconds as one review region.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0090/pipeline/events
2. **Review `cardeventnet-IMG_0644`.** the dominant false-trigger cluster and one missed card-state change.
   - Miss anchors: `17.510` seconds.
   - Predictions: `19.375, 20.375, 21.250, 54.125, 68.500, 77.250, 88.000, 90.000, 97.500` seconds.
   - In-progress predictions: `7.625, 16.625, 78.000` seconds.
   - Treat 17.510–21.250 seconds as one review region.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0644/pipeline/events
3. **Review `cardeventnet-IMG_0635`.** possible missing or shifted point events.
   - Miss anchors: `46.529, 49.781, 56.286, 58.037, 67.292` seconds.
   - Predictions: `65.750, 94.125` seconds.
   - Compare the 65.750-second prediction with the 67.292-second miss.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0635/pipeline/events
4. **Review `cardeventnet-IMG_0652`.** the only reviewed trick-clear interval without a decoded trigger.
   - Miss anchors: `9.509, 12.262, 23.021, 34.283, 69.066, 73.819` seconds.
   - In-progress predictions: `72.750` seconds.
   - Reviewed interval: `21.021–23.021` seconds.
   - Inspect the reviewed interval from 21.021 to 23.021 seconds.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0652/pipeline/events
5. **Review `cardeventnet-IMG_0091`.** timing-only review; no confirmed false triggers.
   - Miss anchors: `9.217, 22.269, 60.139, 90.442, 99.526` seconds.
   - In-progress predictions: `8.000, 20.750, 39.125, 59.125, 68.625, 78.500, 79.375, 89.000, 98.500` seconds.
   - Re-annotate only when the current interval start or stable end is wrong.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0091/pipeline/events
6. **Review `cardeventnet-IMG_0661`.** merged and timing-sensitive events.
   - Miss anchors: `15.013, 25.775, 37.537, 61.308, 66.315, 74.573, 84.833` seconds.
   - Predictions: `89.250` seconds.
   - In-progress predictions: `14.250, 30.875, 39.375, 49.375, 60.000, 68.750` seconds.
   - Keep valid close events instead of moving them to satisfy the decoder gap.
   - Workspace: http://127.0.0.1:5173/recordings/cardeventnet-IMG_0661/pipeline/events

## Review regions

The grouping policy joins adjacent focus times within `2.000` seconds. Each raw item remains in the packet.

| Region | Recording | Focus range (s) | Items |
| --- | --- | ---: | ---: |
| `m10-region-001` | `cardeventnet-IMG_0090` | `9.750000–9.750000` | 1 (in_progress_detection) |
| `m10-region-002` | `cardeventnet-IMG_0090` | `29.742867–29.742867` | 1 (missed_event) |
| `m10-region-003` | `cardeventnet-IMG_0090` | `32.103412–32.103412` | 1 (missed_event) |
| `m10-region-004` | `cardeventnet-IMG_0090` | `36.750000–36.750000` | 1 (confirmed_false_trigger) |
| `m10-region-005` | `cardeventnet-IMG_0090` | `48.500000–50.043555` | 2 (confirmed_false_trigger, missed_event) |
| `m10-region-006` | `cardeventnet-IMG_0090` | `54.625000–54.625000` | 1 (confirmed_false_trigger) |
| `m10-region-007` | `cardeventnet-IMG_0090` | `61.000000–64.875000` | 4 (confirmed_false_trigger, confirmed_false_trigger, confirmed_false_trigger, confirmed_false_trigger) |
| `m10-region-008` | `cardeventnet-IMG_0090` | `71.125000–71.125000` | 1 (confirmed_false_trigger) |
| `m10-region-009` | `cardeventnet-IMG_0090` | `91.500000–91.500000` | 1 (in_progress_detection) |
| `m10-region-010` | `cardeventnet-IMG_0090` | `110.000000–110.871133` | 2 (in_progress_detection, missed_event) |
| `m10-region-011` | `cardeventnet-IMG_0091` | `8.000000–9.217407` | 2 (in_progress_detection, missed_event) |
| `m10-region-012` | `cardeventnet-IMG_0091` | `20.750000–22.268726` | 2 (in_progress_detection, missed_event) |
| `m10-region-013` | `cardeventnet-IMG_0091` | `39.125000–39.125000` | 1 (in_progress_detection) |
| `m10-region-014` | `cardeventnet-IMG_0091` | `59.125000–60.139049` | 2 (in_progress_detection, missed_event) |
| `m10-region-015` | `cardeventnet-IMG_0091` | `68.625000–68.625000` | 1 (in_progress_detection) |
| `m10-region-016` | `cardeventnet-IMG_0091` | `78.500000–79.375000` | 2 (in_progress_detection, in_progress_detection) |
| `m10-region-017` | `cardeventnet-IMG_0091` | `89.000000–90.442104` | 2 (in_progress_detection, missed_event) |
| `m10-region-018` | `cardeventnet-IMG_0091` | `98.500000–99.526363` | 2 (in_progress_detection, missed_event) |
| `m10-region-019` | `cardeventnet-IMG_0635` | `46.529347–46.529347` | 1 (missed_event) |
| `m10-region-020` | `cardeventnet-IMG_0635` | `49.781398–49.781398` | 1 (missed_event) |
| `m10-region-021` | `cardeventnet-IMG_0635` | `56.285501–58.036605` | 2 (missed_event, missed_event) |
| `m10-region-022` | `cardeventnet-IMG_0635` | `65.750000–67.292443` | 2 (confirmed_false_trigger, missed_event) |
| `m10-region-023` | `cardeventnet-IMG_0635` | `94.125000–94.125000` | 1 (confirmed_false_trigger) |
| `m10-region-024` | `cardeventnet-IMG_0644` | `7.625000–7.625000` | 1 (in_progress_detection) |
| `m10-region-025` | `cardeventnet-IMG_0644` | `16.625000–21.250000` | 5 (in_progress_detection, missed_event, confirmed_false_trigger, confirmed_false_trigger, confirmed_false_trigger) |
| `m10-region-026` | `cardeventnet-IMG_0644` | `54.125000–54.125000` | 1 (confirmed_false_trigger) |
| `m10-region-027` | `cardeventnet-IMG_0644` | `68.500000–68.500000` | 1 (confirmed_false_trigger) |
| `m10-region-028` | `cardeventnet-IMG_0644` | `77.250000–78.000000` | 2 (confirmed_false_trigger, in_progress_detection) |
| `m10-region-029` | `cardeventnet-IMG_0644` | `88.000000–90.000000` | 2 (confirmed_false_trigger, confirmed_false_trigger) |
| `m10-region-030` | `cardeventnet-IMG_0644` | `97.500000–97.500000` | 1 (confirmed_false_trigger) |
| `m10-region-031` | `cardeventnet-IMG_0652` | `9.509140–9.509140` | 1 (missed_event) |
| `m10-region-032` | `cardeventnet-IMG_0652` | `12.261786–12.261786` | 1 (missed_event) |
| `m10-region-033` | `cardeventnet-IMG_0652` | `23.020927–23.020927` | 1 (missed_event) |
| `m10-region-034` | `cardeventnet-IMG_0652` | `34.282954–34.282954` | 1 (missed_event) |
| `m10-region-035` | `cardeventnet-IMG_0652` | `69.066389–69.066389` | 1 (missed_event) |
| `m10-region-036` | `cardeventnet-IMG_0652` | `72.750000–73.819275` | 2 (in_progress_detection, missed_event) |
| `m10-region-037` | `cardeventnet-IMG_0661` | `14.250000–15.012675` | 2 (in_progress_detection, missed_event) |
| `m10-region-038` | `cardeventnet-IMG_0661` | `25.775097–25.775097` | 1 (missed_event) |
| `m10-region-039` | `cardeventnet-IMG_0661` | `30.875000–30.875000` | 1 (in_progress_detection) |
| `m10-region-040` | `cardeventnet-IMG_0661` | `37.536548–39.375000` | 2 (missed_event, in_progress_detection) |
| `m10-region-041` | `cardeventnet-IMG_0661` | `49.375000–49.375000` | 1 (in_progress_detection) |
| `m10-region-042` | `cardeventnet-IMG_0661` | `60.000000–61.307990` | 2 (in_progress_detection, missed_event) |
| `m10-region-043` | `cardeventnet-IMG_0661` | `66.314569–66.314569` | 1 (missed_event) |
| `m10-region-044` | `cardeventnet-IMG_0661` | `68.750000–68.750000` | 1 (in_progress_detection) |
| `m10-region-045` | `cardeventnet-IMG_0661` | `74.572609–74.572609` | 1 (missed_event) |
| `m10-region-046` | `cardeventnet-IMG_0661` | `84.832599–84.832599` | 1 (missed_event) |
| `m10-region-047` | `cardeventnet-IMG_0661` | `89.250000–89.250000` | 1 (confirmed_false_trigger) |

## Local review commands

From the repository root, start the local backend in one terminal:

```bash
mise exec -- uv run --project backend dokodetector-backend
```

Start the web workspace in a second terminal:

```bash
cd web
mise exec -- npm run dev
```

Open the workspace routes in the printed checklist order:

1. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0090/pipeline/events
2. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0644/pipeline/events
3. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0635/pipeline/events
4. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0652/pipeline/events
5. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0091/pipeline/events
6. http://127.0.0.1:5173/recordings/cardeventnet-IMG_0661/pipeline/events

Complete the operator review in the recording workspace. The exact handoff artifact to complete is `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-operator-review.json`. Keep correct point and interval references unchanged; publish a new completed revision only when the reference is wrong and full-source coverage is recorded.

M10 stops here. It does not create a dataset, tune the decoder, start training, read the sealed test partition, or read the system holdout.
