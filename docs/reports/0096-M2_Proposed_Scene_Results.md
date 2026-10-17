# 0096 M2 proposed scene results

Date: 2026-10-17

## Outcome

M2 is complete. It ran scene processing for 33 corrected M1 recordings. 29 runs completed and 4 stopped at calibration gates. The completed runs cover 1513 input frames. The four failures leave 194 frames without scene output. The separate terminal M1 dependency failure leaves 49 more frames unprocessed.

The completed runs use the exact corrected M1 detector revisions. Request records match the M1 revision IDs and content digests. Scene frame identities match the M1 input identities for every completed run. All stored scene content digests match their manifests. No scene frame is marked unsupported; 142 frames have explicit empty-card outcomes.

M2 processor logs account for 7508.539 active seconds. Together with M1, the recorded total is 8611.217 seconds of the 86,400-second limit. RSS evidence contains 1450 samples at 10-second intervals and peaks at 2,190,163,968 bytes, below 32 GiB. No cloud requests or identity data were used.

All generated selection pointers are unchanged. The completed reference pointers remain unchanged.

Two early M2 requests used generated run IDs instead of the M0-frozen IDs. Their terminal results remain in the report and were not retried. All later requests used the frozen IDs. The M2 request for `game-2026-08-20-01-005` explicitly selected the frozen corrected M1 revision even though its current generated selection pointer differed.

## Recording outcomes

| Recording | M2 run | Outcome | Frames | Scene revision / failure | Calibration |
|---|---|---:|---:|---|---|
| `5a1f4037-d8ad-48da-9950-2ed2272811a5` | `card-scene-proposal-b3e29a21-b34a-4e3a-8290-d96396713267` | Complete | 85/85 | `card-scene-proposals-card-scene-proposal-b3e29a21-b34a-4e3a-8290-d96396713267-attempt-1` | `calibration-ddcfc8ab8c33a646e25c02dd` |
| `cardeventnet-IMG_0090` | `card-scene-proposal-26458f5b-c76c-46fd-a5cd-c28d02a79a59` | Failed | 0/50 | `inconsistent_card_geometry` | Not published |
| `cardeventnet-IMG_0091` | `card-scene-proposal-0363ca81-7651-597d-ba18-69fd2b7d2770` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-0363ca81-7651-597d-ba18-69fd2b7d2770-attempt-1` | `calibration-02e518b6fe929cd8d275a8e9` |
| `cardeventnet-IMG_0095` | `card-scene-proposal-438d8fc1-a077-576a-90b8-b2a03fca55f2` | Complete | 53/53 | `card-scene-proposals-card-scene-proposal-438d8fc1-a077-576a-90b8-b2a03fca55f2-attempt-1` | `calibration-d7d852a94cb88ec05f0364eb` |
| `cardeventnet-IMG_0096` | `card-scene-proposal-48a6d711-997a-5963-8e11-57f9c209295d` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-48a6d711-997a-5963-8e11-57f9c209295d-attempt-1` | `calibration-94d1302cf610b8eb667b17fa` |
| `cardeventnet-IMG_0097` | `card-scene-proposal-29d16690-f23c-52c5-be36-2f7dd663ae42` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-29d16690-f23c-52c5-be36-2f7dd663ae42-attempt-1` | `calibration-d30984ce7022758e2b576f0d` |
| `cardeventnet-IMG_0635` | `card-scene-proposal-b9c5b740-53e7-5c90-b6cd-5e9173a53d91` | Failed | 0/51 | `inconsistent_card_geometry` | Not published |
| `cardeventnet-IMG_0636` | `card-scene-proposal-e78ad4d9-7816-5517-9871-28485cd5034f` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-e78ad4d9-7816-5517-9871-28485cd5034f-attempt-1` | `calibration-ef69e1f516522882dae50a32` |
| `cardeventnet-IMG_0637` | `card-scene-proposal-c101190e-3a99-50ad-892f-e93f5ff52237` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-c101190e-3a99-50ad-892f-e93f5ff52237-attempt-1` | `calibration-85a37b910dcd2ad33d237d5c` |
| `cardeventnet-IMG_0638` | `card-scene-proposal-80836c53-d4ac-57df-b56d-6a0f7e7b65dc` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-80836c53-d4ac-57df-b56d-6a0f7e7b65dc-attempt-1` | `calibration-59a779812b99ef41e9f98649` |
| `cardeventnet-IMG_0639` | `card-scene-proposal-1c332f90-9e03-567d-a724-53d4d30c21a0` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-1c332f90-9e03-567d-a724-53d4d30c21a0-attempt-1` | `calibration-c1ea1d7e63d9c2a9e22bd6bd` |
| `cardeventnet-IMG_0640` | `card-scene-proposal-3d0e6222-23be-5501-a696-a1202ec69826` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-3d0e6222-23be-5501-a696-a1202ec69826-attempt-1` | `calibration-0defe3382350484d5ceb5f14` |
| `cardeventnet-IMG_0641` | `card-scene-proposal-bc0d0aba-751b-54fb-976d-c1549c8dd09d` | Failed | 0/53 | `unstable_table_transform` | Not published |
| `cardeventnet-IMG_0642` | `card-scene-proposal-b75633cc-b7b8-57d0-b718-5548cec7f351` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-b75633cc-b7b8-57d0-b718-5548cec7f351-attempt-1` | `calibration-bae17f0d5b215c6aa95ca950` |
| `cardeventnet-IMG_0643` | `card-scene-proposal-5de2e404-4f70-5181-a161-d9f58168fd5e` | Complete | 52/52 | `card-scene-proposals-card-scene-proposal-5de2e404-4f70-5181-a161-d9f58168fd5e-attempt-1` | `calibration-0ddeceb8e0f6bd1970b0024c` |
| `cardeventnet-IMG_0644` | `card-scene-proposal-a4c1f35b-4b82-5fc3-90bb-bb679da0e701` | Complete | 54/54 | `card-scene-proposals-card-scene-proposal-a4c1f35b-4b82-5fc3-90bb-bb679da0e701-attempt-1` | `calibration-d0dd45a361418a22b5f5a9a1` |
| `cardeventnet-IMG_0645` | `card-scene-proposal-1688f803-21b0-5be5-832d-3dc06d7928d3` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-1688f803-21b0-5be5-832d-3dc06d7928d3-attempt-1` | `calibration-c14f57e63ba233d35fe96039` |
| `cardeventnet-IMG_0646` | `card-scene-proposal-042e69ed-a1ca-5197-9875-eab2cb6971d6` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-042e69ed-a1ca-5197-9875-eab2cb6971d6-attempt-1` | `calibration-2088722e77eb3720495bc8e3` |
| `cardeventnet-IMG_0648` | `card-scene-proposal-74097974-8c87-5067-840a-aed7a277f2df` | Complete | 52/52 | `card-scene-proposals-card-scene-proposal-74097974-8c87-5067-840a-aed7a277f2df-attempt-1` | `calibration-20ce3aee66ff50b7fccb7706` |
| `cardeventnet-IMG_0649` | `card-scene-proposal-eb81c511-58f7-5448-ac51-30fd54ab057f` | Complete | 54/54 | `card-scene-proposals-card-scene-proposal-eb81c511-58f7-5448-ac51-30fd54ab057f-attempt-1` | `calibration-65619936a317e27f0759fe7c` |
| `cardeventnet-IMG_0650` | `card-scene-proposal-f7279496-73da-5b82-aa26-9ffab766f953` | Complete | 36/36 | `card-scene-proposals-card-scene-proposal-f7279496-73da-5b82-aa26-9ffab766f953-attempt-1` | `calibration-0e03112044bf5973a04cb08b` |
| `cardeventnet-IMG_0651` | `card-scene-proposal-3ec9bf3c-329a-56f4-9b26-4654ab64836b` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-3ec9bf3c-329a-56f4-9b26-4654ab64836b-attempt-1` | `calibration-dc7e274a705bff12d72a54f9` |
| `cardeventnet-IMG_0652` | `card-scene-proposal-1e8ef8a3-346e-5c56-a949-52dcb94b75db` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-1e8ef8a3-346e-5c56-a949-52dcb94b75db-attempt-1` | `calibration-8c2fb98268a9437344677d85` |
| `cardeventnet-IMG_0653` | `card-scene-proposal-109132b0-9e63-5c11-9d44-0200869a912d` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-109132b0-9e63-5c11-9d44-0200869a912d-attempt-1` | `calibration-f5d62a23c69175a64992e781` |
| `cardeventnet-IMG_0655` | `card-scene-proposal-e4b4a225-814b-5915-b58c-4dfb8eeab5d2` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-e4b4a225-814b-5915-b58c-4dfb8eeab5d2-attempt-1` | `calibration-daab4aeabc38f6054c177e7a` |
| `cardeventnet-IMG_0657` | `card-scene-proposal-2a59861a-1d5a-54ab-8bc6-2598ad744caa` | Complete | 51/51 | `card-scene-proposals-card-scene-proposal-2a59861a-1d5a-54ab-8bc6-2598ad744caa-attempt-1` | `calibration-200dd37219606d7f949d13bf` |
| `cardeventnet-IMG_0658` | `card-scene-proposal-6f32cd34-ebd9-541f-8948-8531a8370c98` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-6f32cd34-ebd9-541f-8948-8531a8370c98-attempt-1` | `calibration-385b696a0476f8a41045db50` |
| `cardeventnet-IMG_0661` | `card-scene-proposal-8a9d75d2-f068-56aa-9a73-b5502641eafd` | Complete | 54/54 | `card-scene-proposals-card-scene-proposal-8a9d75d2-f068-56aa-9a73-b5502641eafd-attempt-1` | `calibration-fe569668c600f64bad64e34d` |
| `cardeventnet-IMG_0662` | `card-scene-proposal-86811f40-afff-5cf9-bd8f-fbe1f1c4d90b` | Complete | 50/50 | `card-scene-proposals-card-scene-proposal-86811f40-afff-5cf9-bd8f-fbe1f1c4d90b-attempt-1` | `calibration-ead6d98f6a665d22d926b9dd` |
| `game-2026-08-20-01-005` | `card-scene-proposal-a0aefa4e-caa8-567e-96b0-eba312dabbce` | Failed | 0/40 | `insufficient_validation_population` | Not published |
| `game-2026-09-18-01-001` | `card-scene-proposal-b0ebc0eb-e701-55c3-88da-79c3bbf5f5d1` | Complete | 57/57 | `card-scene-proposals-card-scene-proposal-b0ebc0eb-e701-55c3-88da-79c3bbf5f5d1-attempt-1` | `calibration-8b45dcc90ce09123421b98ab` |
| `game-2026-09-18-01-002` | `card-scene-proposal-7fdb15cb-0fc3-585f-9c15-85ea78ac6726` | Complete | 52/52 | `card-scene-proposals-card-scene-proposal-7fdb15cb-0fc3-585f-9c15-85ea78ac6726-attempt-1` | `calibration-274aaacc98963b18ef50067e` |
| `game-2026-09-18-01-003` | `card-scene-proposal-5c7b1ff7-33ab-5028-854b-53091836f672` | Complete | 57/57 | `card-scene-proposals-card-scene-proposal-5c7b1ff7-33ab-5028-854b-53091836f672-attempt-1` | `calibration-048cd4d1f730611212cb9b3a` |

The M1 dependency failure is `game-2026-08-20-01-001` (49 frames). Calibration failures are `cardeventnet-IMG_0090` and `cardeventnet-IMG_0635` (`inconsistent_card_geometry`), `cardeventnet-IMG_0641` (`unstable_table_transform`), and `game-2026-08-20-01-005` (`insufficient_validation_population`). No terminal failure was retried.

The machine-readable lineage, input hashes, run IDs, frame accounting, calibration IDs, pointer checks, and processing evidence are in [`0096-M2_Proposed_Scene_Results.json`](0096-M2_Proposed_Scene_Results.json). M0 run IDs, frame inputs, and M1 results remain linked from the epic.
