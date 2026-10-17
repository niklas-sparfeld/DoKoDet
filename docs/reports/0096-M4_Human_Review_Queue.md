# 0096 M4 human review queue

Date: 2026-10-17

## Review status

The bounded review queue is frozen and awaits human review. It contains 165 frames across 33 recordings, with five frames per reviewable recording. This is below the 195-frame maximum. One included recording has no corrected detector output and is marked as unreviewable: `game-2026-08-20-01-001`, with 49 unprocessed frames. The queue does not substitute the wrong-anchor M1 output.

The selection digest is `fd54ee11448bb35fa26461538c7e58b15422d215ab0ee433ff8914aaa318126f`. The full frame, reason, source revision, scene run, reference, and WebUI link for each item are in [`0096-M4_Human_Review_Queue.json`](0096-M4_Human_Review_Queue.json). Rebuild it with [`build_0096_m4_review_queue.py`](../../operations/scripts/build_0096_m4_review_queue.py).

## Start here

This is the frame you called near-perfect. M3 pairs it with the exact reviewed image. The generated detector result has one card candidate; one reviewed card matches at IoU 0.913. One additional reviewed card remains unmatched, and the reference has an ignored region. Please inspect the card, pile, calibration, and stack order in the workspace.

[Open IMG_0645 frame 15 in the WebUI](http://localhost:5173/recordings/cardeventnet-IMG_0645/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-22f665b9-2c77-5c8a-9cc1-eed1d90a168e-attempt-1&item=cardeventnet-event-img_0645-015)

## Review focus

The queue prioritizes M2 calibration failures, M3 misses and extras, pose confidence and stack-order diagnostics, pile regions, overlaps, small cards, frame edges, and one successful control when available. The four calibration-failure recordings are `cardeventnet-IMG_0090`, `cardeventnet-IMG_0635`, `cardeventnet-IMG_0641`, and `game-2026-08-20-01-005`. They have no published scene revision, so the queue links to their exact corrected M1 detector outputs and includes the terminal calibration failure.

Review each selected item in the WebUI. Correct card geometry, calibration, and stacking order where the editor permits it. Save completed review receipts through the existing workflow. Do not count a viewed frame as reviewed until the review is saved. The queue contains no accepted review decisions.

## Recording coverage

| Recording | Review | Frames |
|---|---|---:|
| `game-2026-08-20-01-001` | Not reviewable: terminal M1 dependency failure; no corrected detector revision is available | 0 |
| `game-2026-08-20-01-005` | [Open first item](http://localhost:5173/recordings/game-2026-08-20-01-005/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-fe894c5e-b4ab-55bc-ab22-b476de1f84d8-attempt-1&item=event-000003) | 5 |
| `game-2026-09-18-01-001` | [Open first item](http://localhost:5173/recordings/game-2026-09-18-01-001/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-920c891d-1c86-577c-8094-55abd0989bf8-attempt-1&item=event-000043) | 5 |
| `game-2026-09-18-01-002` | [Open first item](http://localhost:5173/recordings/game-2026-09-18-01-002/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-847f395f-dfd0-56c7-b3b0-fd9725cdf2a9-attempt-1&item=event-000040) | 5 |
| `game-2026-09-18-01-003` | [Open first item](http://localhost:5173/recordings/game-2026-09-18-01-003/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-15c12eef-4ce8-5568-8af7-761d2d553b66-attempt-1&item=event-000003) | 5 |
| `cardeventnet-IMG_0635` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0635/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-5858cc78-219d-58c7-991b-d8d9e55d6be0-attempt-1&item=cardeventnet-event-img_0635-002) | 5 |
| `cardeventnet-IMG_0636` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0636/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-4e943e69-0cd3-5841-bbac-a89906613f30-attempt-1&item=cardeventnet-event-img_0636-003) | 5 |
| `cardeventnet-IMG_0637` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0637/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-c017b765-b14e-5b31-a7c2-b4716d5adc61-attempt-1&item=cardeventnet-event-img_0637-018) | 5 |
| `cardeventnet-IMG_0638` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0638/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-2369cabe-007b-50c9-b2a0-25f7b2752091-attempt-1&item=cardeventnet-event-img_0638-008) | 5 |
| `cardeventnet-IMG_0639` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0639/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-8afe8966-3696-5a59-bfb3-34271d063183-attempt-1&item=cardeventnet-event-img_0639-043) | 5 |
| `cardeventnet-IMG_0640` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0640/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-673070df-fc36-5404-a5ec-7d4305131002-attempt-1&item=cardeventnet-event-img_0640-033) | 5 |
| `cardeventnet-IMG_0641` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0641/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-d2b8317b-aacb-5d0b-b3e0-d5ab3a4c2089-attempt-1&item=cardeventnet-event-img_0641-009) | 5 |
| `cardeventnet-IMG_0642` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0642/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-93489b3b-9078-5b53-a779-b9f8aa609c19-attempt-1&item=cardeventnet-event-img_0642-028) | 5 |
| `cardeventnet-IMG_0643` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0643/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-4e9dd1fd-86a9-5f1f-a846-24611110cf44-attempt-1&item=cardeventnet-event-img_0643-004) | 5 |
| `cardeventnet-IMG_0644` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0644/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-61cac67a-56c9-5141-9278-82f0f8e7abe1-attempt-1&item=cardeventnet-event-img_0644-042) | 5 |
| `cardeventnet-IMG_0645` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0645/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-22f665b9-2c77-5c8a-9cc1-eed1d90a168e-attempt-1&item=cardeventnet-event-img_0645-015) | 5 |
| `cardeventnet-IMG_0646` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0646/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-bace182a-e2aa-5c9c-8a28-d0174188219e-attempt-1&item=cardeventnet-event-img_0646-038) | 5 |
| `cardeventnet-IMG_0648` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0648/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-3c77f687-664d-5539-b547-5e085691430f-attempt-1&item=cardeventnet-event-img_0648-003) | 5 |
| `cardeventnet-IMG_0649` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0649/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-42a72ab8-4833-556b-8701-bf15a4f5e697-attempt-1&item=cardeventnet-event-img_0649-015) | 5 |
| `cardeventnet-IMG_0650` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0650/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-6e0c5fdf-9438-56d1-8253-e9912b25d5bf-attempt-1&item=cardeventnet-event-img_0650-029) | 5 |
| `cardeventnet-IMG_0651` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0651/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-2a2ac876-25ab-51ac-bf51-39ff20caffdf-attempt-1&item=cardeventnet-event-img_0651-024) | 5 |
| `cardeventnet-IMG_0652` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0652/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-8a7d7ce8-e811-5dd5-a483-699ca6fc2445-attempt-1&item=cardeventnet-event-img_0652-023) | 5 |
| `cardeventnet-IMG_0653` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0653/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-338183e7-1eb9-56e9-b4ab-18dd8ac02ad8-attempt-1&item=cardeventnet-event-img_0653-027) | 5 |
| `cardeventnet-IMG_0655` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0655/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-6850a399-0c9a-5949-add6-41d5cc77cbcb-attempt-1&item=cardeventnet-event-img_0655-021) | 5 |
| `cardeventnet-IMG_0657` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0657/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-7f18ab0c-4019-5557-a004-b5d10070d6b4-attempt-1&item=cardeventnet-event-img_0657-029) | 5 |
| `cardeventnet-IMG_0658` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0658/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-ef78d951-2932-57a9-b9cd-16914a8d15af-attempt-1&item=cardeventnet-event-img_0658-037) | 5 |
| `cardeventnet-IMG_0662` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0662/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-6e2f3f6f-b5c3-5bb0-8056-47a34bf54327-attempt-1&item=cardeventnet-event-img_0662-007) | 5 |
| `cardeventnet-IMG_0090` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0090/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-a9c887ce-ebcf-5684-8cb9-07ef0e85ccfb-attempt-1&item=cardeventnet-event-img_0090-008) | 5 |
| `cardeventnet-IMG_0091` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0091/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-1897c4e9-12b5-5918-9021-ac59f84e63ce-attempt-1&item=cardeventnet-event-img_0091-013) | 5 |
| `cardeventnet-IMG_0095` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0095/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-7e6dc749-4c85-5352-9dde-23825547228a-attempt-1&item=cardeventnet-event-img_0095-031) | 5 |
| `cardeventnet-IMG_0096` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0096/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-e9f4a529-3edd-56d8-9a76-99594eb011a7-attempt-1&item=cardeventnet-event-img_0096-038) | 5 |
| `cardeventnet-IMG_0097` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0097/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-07c4a94f-3820-52ea-8435-29dd0a9ff2d7-attempt-1&item=cardeventnet-event-img_0097-043) | 5 |
| `cardeventnet-IMG_0661` | [Open first item](http://localhost:5173/recordings/cardeventnet-IMG_0661/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-bc980ec3-a5df-53ab-9726-c5057101c7bd-attempt-1&item=cardeventnet-event-img_0661-025) | 5 |
| `5a1f4037-d8ad-48da-9950-2ed2272811a5` | [Open first item](http://localhost:5173/recordings/5a1f4037-d8ad-48da-9950-2ed2272811a5/pipeline/visible_cards?view=generated&start_review=proposal&revision=visible-cards-291ad680-2792-5695-a710-4f5bd6685347-attempt-1&item=event-000078) | 5 |
