# 0088 M8 synthetic identity-crop pool

Date: 2026-10-16

## Result

M8 built and visually reviewed one immutable synthetic crop for each exact 0070-to-0088 training
join. Seven of the 165 0070 cutouts had an eligible reviewed 0088 training identity. The seven
examples come from `cardeventnet-IMG_0655`, one frozen training source group. They cover five
face-up identities: `DIAMONDS_TEN` (1), `HEARTS_KING` (2), `SPADES_ACE` (1), `SPADES_KING` (2),
and `SPADES_QUEEN` (1). The pool has no synthetic `FACE_DOWN` example because 0070 has no matching
reviewed face-down cutout. The one real `FACE_DOWN` training crop stays in the 0088 training set.
This does not block the exploratory M9 fit and does not change support claims.

The join checked 0088 training membership and reviewed eligibility, source recording digest,
decoded frame digest, event item, frame lineage, and uniqueness of the reviewed identity. The
adapter did not use the generic `visible_card` segmentation label to assign identity. It reused
0070's deterministic cutout warp, shadow, and appearance effects on a fixed neutral canvas. No
source background pixels or validation/final-test material entered the pool. Each entry retains its
real PPM crop and adds the rendered appearance, visible mask, synthetic PPM crop, label, source
lineage, and file digests.

The contact sheet shows each real crop, synthetic DINO crop, and rendered appearance with the mask
overlay. Visual review confirmed that labels match the exact joined crops and that the masks cover
the rendered cards. The pool manifest digest was identical across two builds:
`dfed94bf10949a71c850cb8059a489e02b20f014175bf4d38f8e3d434af7ca31`.

The machine-readable pool and images are in
`.runtime/dinov3-identity-0088/m8-synthetic-pool/`. They use 0070 M1 manifest digest
`c26159be1ead824f96bf49ccbd4172bba7dfba164940541effa2af772b94113f`, 0088 dataset digest
`c206c665f22fbe30b7343961d8555dad4bbec25b4420da836478a04f15e817ab`, split digest
`753eb5c2d39eec031109fec59bdc2d66a028be2e5a50969ad441826fcaec8d87`, and crop-cache digest
`4eba776d0aeb9d0a8df112edb1e32ded36c0a790d0ee210958d1a231a260b091`.

## Reproduction

From the primary repository checkout, run:

```sh
mise exec -- uv run --project operations python \
  operations/scripts/build_0088_m8_synthetic_identity_pool.py
```

The command writes the pool to `.runtime/dinov3-identity-0088/m8-synthetic-pool/`. M9 can use
the stored synthetic crops with the unchanged real training set. No model fit was started in M8.
