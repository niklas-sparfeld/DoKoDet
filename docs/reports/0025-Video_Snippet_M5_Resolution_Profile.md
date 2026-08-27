# Plan 0025 M5 exploratory resolution profile

## Source and method

The comparison used the checked-in recorded source
`card_event_net/data/raw/IMG_0090.mov`. The source is 1920×1080 H.264 with a 30 fps source rate.
Both derivatives use the same source interval from 10.000 s to 12.133 s, the same 15 fps target,
the same H.264 encoder, and the same 1,200,000 bit/s average bitrate target. The derivatives have
no audio. FFmpeg 8.1.2 ran on the local Mac.

## Comparison

| Profile | Size | Dimensions | Rate | Frames | Duration | Encode wall time | Decode wall time |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| derived review proxy | 333,777 B | 640×360 | 15 fps | 32 | 2,133 ms | 0.28 s | 0.06 s |
| accepted source profile | 286,511 B | 960×540 | 15 fps | 32 | 2,133 ms | 0.32 s | 0.06 s |

The 960×540 output is smaller for this interval because the encoder produced fewer coded bits at
the same target bitrate. Size alone is not a quality result. Both outputs are below the 750,000
byte bound and have the same timing coverage.

## Temporary memory check

At 960×540, one BGRA rolling-buffer sample uses 2,073,600 bytes. The requested two-second range
needs 31 samples at 15 fps. The bounded conversion queue reserves four more samples:

```text
(31 + 4) × 2,073,600 = 72,576,000 bytes
```

This is below the 83,886,080-byte temporary capacity. The live provider checks this relation when
it starts. It reports a configuration error when the relation cannot hold.

## Detail check

The midpoint frames came from the same source time. The 960×540 frame kept more card-edge and
corner detail than the 640×360 derivative in this interval. This is a visual comparison only. It
does not measure recognition or tracking quality.

## Decision

Keep 960×540 as the accepted exploratory source profile. Use 640×360 only as a derived comparison
or review proxy. Supported-iPhone memory, encode, upload, and visible-detail measurements remain
part of M6.
