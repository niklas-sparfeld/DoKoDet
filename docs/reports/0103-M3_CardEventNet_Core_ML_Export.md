# 0103 M3: CardEventNet Core ML export

## Result

M3 is complete. The exact frozen CardEventNet checkpoint exported to Core ML and matched the
frozen M0 Python result on its fixed eight-frame causal input. The Core ML logit differed by
`0.000030041` and the probability differed by `0.0000000234`; both are within the frozen
`atol=1e-4`, `rtol=1e-4` limits. The score stayed below the operating threshold and both decoders
returned no event. This is an execution result, not an event-quality claim.

## Frozen model and input

The checkpoint is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt`,
SHA-256 `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4`. The exporter loads the
checkpoint with the existing CardEventNet loader and checks the frozen M0 manifest and Python
reference digests before conversion.

The model uses MobileNetV3-Small frame features and the `full_clip_v2` temporal head. Its fixed
input shape is `[1,8,3,224,224]`. The eight RGB cache frames use `full_frame_letterbox_v1` and
ImageNet normalization. Their selected cache indices are 66, 68, 70, 72, 74, 76, 78, and 79. Their
decoded timestamps span 6.6064–7.9077 seconds and provide the causal context for the 8.0-second
decision. The script verifies each frozen JPEG digest and the selected indices before inference.
It does not replace the temporal input with separate still-frame inference.

## Export and parity

The attempt used macOS 27.2 arm64, Python 3.13.18, Core ML Tools 9.0, PyTorch 2.7.0, torchvision
0.22.0, NumPy 2.5.4, and OpenCV 5.0.0.93. Conversion used the existing fixed-shape ML Program
exporter, float32 precision, and an iOS 15 minimum deployment target. The model package is kept
outside Git at `.runtime/0103-m3/cardeventnet.mlpackage`. Its SHA-256 package digest is
`b3f41726c2029e6047bd9ea04ab742fc55868e815f2601410dc266a8ca736bfd`; its size is 4,282,574 bytes.

| Output | Python | Core ML | Difference | Within tolerance |
| --- | ---: | ---: | ---: | --- |
| Logit | -7.1549272537 | -7.1549572945 | 0.0000300407 | Yes |
| Probability | 0.000780396862 | 0.000780373449 | 0.0000000234 | Yes |
| At threshold `0.4271905720` | Below | Below | No decision change | Yes |
| Decoded event proposal | None | None | None | Yes |

The frozen Python reference reproduced exactly before export. No event was emitted, so this single
decision point cannot show an event timing offset. The converter's separate random-input parity
check was skipped; the exported package was instead compared with the exact M0 temporal input.

## Reproduction and limits

Run from the repository root:

```sh
PYTHONWARNINGS=ignore PYTHONPATH=card_event_net/src:table_evidence_analyzer/src \
  backend/.venv/bin/python scripts/0103_m3_export_cardeventnet.py
```

The script writes `.runtime/0103-m3/export-report.json`, including package, dependency, input,
parity, or failure details. The package and report are local runtime outputs and are not committed.
The fixed development sample does not measure event accuracy or timing quality. Device execution,
latency, memory, and iPhone availability remain for M4.
