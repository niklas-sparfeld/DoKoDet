# Plan 0025 M0 media selection

## Source and method

The comparison used the checked-in recorded source `card_event_net/data/raw/IMG_0090.mov`.
The source is 1920×1080 H.264 at 30 fps. Each candidate encoded a two-second, video-only segment
with FFmpeg 8.0 on macOS. Decode time used the same local FFmpeg build with a null output.

The event point was 11.000 s in the source. The selected frame targets are -800, -400, -100,
150, 400, and 700 ms. The selected segment starts at -1,000 ms and ends at +1,133 ms after
encoding. It therefore covers all selected frame targets.

## Comparison

| Profile | Container | Codec | Size | Dimensions | Rate | Encode | Decode |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| compact | MP4 | H.264 | 137,663 B | 640×360 | 15 fps | 0.23 s | 0.02 s |
| larger | MP4 | H.264 | 336,167 B | 960×540 | 15 fps | 0.27 s | 0.04 s |

Both profiles produced 32 decodable video frames. The compact profile is 59% smaller and keeps
the required event-relative coverage. It is the M0 selection.

## Versioned bounds

The V2 `video_capture` object records these PoC values:

```text
container: mp4
video_codec: h264
content_type: video/mp4
requested_start_offset_ms: -1000
requested_end_offset_ms: 1000
max_duration_ms: 2500
max_width: 640
max_height: 360
max_nominal_frame_rate: 15.0
max_byte_length: 250000
queued_byte_capacity: 10485760
```

The queue capacity allows 41 maximum-size snippets before the next package would exceed the
configured bound. These are local PoC values. They are not production limits.

The canonical fixture is in
[`fixtures/evidence/v2/example-complete`](../../fixtures/evidence/v2/example-complete). Its
`probe.json` records the expected technical values. The MP4 is probed with FFmpeg and decoded in
the Swift AVFoundation contract test.
