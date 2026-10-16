# 0088 M9 synthetic identity fit

Date: 2026-10-16

## Result

The one fixed 1:1 synthetic candidate completed. It reached 208/209 top-1 correct on the unchanged
real model-selection crops, equal to M6. Every crop received the same prediction as M6: no crop was
corrected and none regressed. M9 therefore gives no annotation-assistance gain on this selection
view. Follow the frozen M10 rule and compare M3 with M6, not M9 with M6.

The best checkpoint is epoch 7. Epoch 8 tied its 208/209 selection accuracy, so the first best
checkpoint remains selected. Top-3 accuracy is 209/209. The one error is `SPADES_ACE` predicted as
`CLUBS_ACE` in `cardeventnet-IMG_0657`. Both candidates score 116/117 on source group
`source-group-9d6d4824b53bc4a9` (`IMG_0657`) and 92/92 on source group
`source-group-d4543cb23cc73b35` (`IMG_0662`). The only `FACE_DOWN` crop is correct for both
candidates. This is one example and does not support a face-down generalization claim. The seven
synthetic crops cover five face-up identities in one training source group and do not increase class
or group support.

## Fit and resources

- Recipe: 224 pixels, CLS plus mean-patch features, frozen DINOv3 encoder, seed 17, eight epochs,
  batch size 1, AdamW at 0.001, zero weight decay, MPS fp32.
- Each epoch used 599 real draws and one deterministic synthetic draw paired with each real draw.
  This preserved 4,792 real draws and added 4,792 synthetic draws over the fit.
- The run completed 9,584 optimizer steps in 863.86 seconds (14.4 minutes).
- Process maximum RSS was 1,114.734 MB.
- A matched crop-to-prediction timing check used the same 209 selection crops, ten warm-up crops per
  candidate, preprocessing, model forward, probability ranking, and MPS synchronization. M6 mean
  and p95 were 39.877 ms and 44.775 ms. M9 mean and p95 were 40.564 ms and 44.684 ms. M9 did not
  regress the p95 limit of 100 ms. The small mean difference did not change any prediction.

The initial launch stopped before its first optimizer step because M8 stores masks in full-scene
coordinates while the DINO crops use tight card bounds. The M9 runner now crops each mask to its
support bounds and resizes by nearest-neighbor only when a crop dimension differs by one pixel. The
immutable M8 pool was unchanged. The failed launch is retained under the ignored runtime directory;
the single completed fit is the result reported here.

## Lineage and artifacts

- M6 campaign manifest digest: `d6d9a672ede8cbd05a70e26a2b059c67265250c4467bc050b1d6e5ff732a1d7d`.
- M8 pool manifest digest: `dfed94bf10949a71c850cb8059a489e02b20f014175bf4d38f8e3d434af7ca31`.
- Best checkpoint SHA-256: `f168e9440790ebf16ded8427be54e0180bf17ece62ce083a8cd700515d83c774`.
- Selection predictions SHA-256: `f6d0414eb927b5a48813b1196444092a7e608151e51dfa235dd76f78f24f7b4d`.
- Run output: `.runtime/dinov3-identity-0088/m9-synthetic-candidate/run/`.
- Runner: `operations/scripts/run_0088_m9_synthetic_fit.py`.

The run used only the seven M8 synthetic crops and the unchanged M6 real training and selection
views. It did not read final-test material. Synthetic crops do not add support or qualification
evidence. The final test remains sealed.
