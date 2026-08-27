# Plan 0025 M6 local end-to-end measurement

## Inputs

This measurement uses the self-recorded source asset
`backend/.runtime/training-recordings/caf8a161-a850-4dfb-a1e5-8f044bd06e61`.
The source recording has these values:

| Value | Result |
| --- | --- |
| device | iPhone |
| operating system | 26.6 |
| app build | 1.0 (build 1) |
| source media | 1920×1080 H.264, 30 fps |
| source duration | 25.129 s |
| source bytes | 42,290,115 B |
| source SHA-256 | `6c468402ed9fef91882e34a7ef8be2bb66527d4fe87fc48cf99b6219d4050a39` |
| session | `9e5397c7-8f95-432f-bdb6-0a8750ba3682` |
| backend revision | `8f7f042148f8b019f30d893dbb0260e38c31fa3a` |

The operator reviewed the source recording and the associated evidence-package JPEGs and video
snippets. This review is a media and motion review. It does not turn an event proposal into a
reviewed event, and it does not measure recognition or tracking quality.

## Package set

The backend database contains 20 packages for this session. All 20 are `stored`. All 20 contain a
complete 960×540 video snippet. The three packages below are the M6 sample. They are far apart in
the evidence session and cover different visible card and occlusion states.

| Event sequence | Package | Event time | Snippet bytes | Frames | Coverage | SHA-256 |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | `c2b33e1e-4578-45be-8b8f-0bd99a5a73aa` | 3,299 ms | 265,460 B | 31 | -1,000…+1,067 ms | `cb5755c34ef332f0786fd1374cc49c5615ec2fb75bc23d39d1a160a178e8a677` |
| 6 | `53c57e02-bd0f-46f8-800e-2ddf805cac31` | 12,765 ms | 329,662 B | 31 | -1,000…+1,067 ms | `701101fcbf430d4cbd7a151908deda044111eb4905141de84d43fe7eb13d2b66` |
| 15 | `d942bf06-8b98-4284-a737-42cf986c5beb` | 44,226 ms | 329,814 B | 31 | -1,000…+1,067 ms | `c4fcae7e0ed3690795d79f0340edaa27ee37f0f0770ab1783628f7331242da68` |

The three selected packages use the same capture configuration:

```text
960×540, H.264/MP4, 15 fps target, 1,200,000 bit/s target
maximum snippet bytes: 750,000
requested coverage: -1,000 ms to +1,000 ms
temporary capacity: 83,886,080 B
queued video capacity: 10,485,760 B
```

## Backend read-back

The stored bytes passed these checks:

- all 20 video files match the SHA-256 and byte length in their manifests;
- all 20 pass the backend `probe_video_bytes` implementation;
- all 20 probe as H.264, 960×540, 15 fps, 31 decoded frames, and 2,067 ms;
- each selected package has six JPEG frames with matching byte lengths and SHA-256 values;
- each selected package has no missing frame target;
- the backend metadata and `/video-snippet` read routes return the selected package data;
- the backend database contains the 20 package rows with state `stored`.

The successful-upload queue normally removes the original iOS spool copy. The available local
evidence is therefore an independent verification of the immutable backend copy against the
manifest hash, not a second-file comparison with an iOS spool copy.

## 640×360 derivatives

The 640×360 files were created from the three accepted 960×540 snippets. The command scaled the
video, kept the 15 fps target, used H.264 at the same 1,200,000 bit/s target, and removed audio.
The derivative files are temporary comparison files. They are not accepted source evidence.

| Package | 960×540 source | 640×360 derivative | Frames | Duration |
| --- | ---: | ---: | ---: | ---: |
| `c2b33e1e…` | 265,460 B | 287,761 B | 31 | 2,067 ms |
| `53c57e02…` | 329,662 B | 265,658 B | 31 | 2,067 ms |
| `d942bf06…` | 329,814 B | 281,196 B | 31 | 2,067 ms |

The reviewed 960×540 views retain more card-edge and corner detail. The 640×360 derivatives remain
useful for a small review proxy and broad motion. Keep 960×540 as the source profile.

## Measurements

Across the 20 packages:

| Measurement | Result |
| --- | --- |
| video snippets | 20 complete |
| snippet size | 207,115–361,941 B; mean 298,047 B |
| encoded stream | 960×540 H.264 |
| decoded frames | 31 in every package |
| encoded rate | 15 fps in every package |
| encoded duration | 2,067 ms in every package |
| timing coverage | -1,000…+1,067 ms in every package |
| video bytes | 5,960,940 B total |
| stored package bytes | 53,221,908 B total for 20 packages, excluding Finder metadata |

The profile stays below the 750,000-byte snippet bound. The 20 snippets use about 5.96 MiB, below
the 10 MiB queued video capacity. The six JPEG frames make the complete package larger than the
video queue budget. Package storage must remain a separate limit.

The reviewed package manifests do not contain observed peak temporary bytes, encode latency, or
upload latency. The bounded profile calculation remains:

```text
one 960×540 BGRA sample: 2,073,600 B
required coverage: 31 samples + 4 pending conversions = 72,576,000 B
maximum bounded use: 36 buffered samples + 4 pending conversions = 82,944,000 B
configured capacity: 83,886,080 B
```

Do not use backend receipt timestamps as upload latency. They do not contain the client upload
start time. The device performance part of M6 remains open until a build records these three
values per package:

- peak raw temporary bytes;
- encode start and end time;
- upload start and successful backend receipt time.

## Result

The corrected live path produced more than the required three complete 960×540 packages. The
backend preserved and decoded the snippets, and the selected JPEG path remained intact. The
available evidence supports the 960×540 exploratory source profile and does not revise the M5
bounds.

M6 is not fully closed. Device latency and observed peak-memory telemetry are still required. M4
also retains its separate camera source-rate and backend disagreement work items.
