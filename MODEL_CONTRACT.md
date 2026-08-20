# CardEventNet model contract

This document records the contract of the supplied `CardEventNet.mlpackage`.
The values below come from the Core ML package and the export code in
`card_event_net/src/cardevent/export_coreml.py`.

## Model

- Package: `card_event_net/CardEventNet.mlpackage`
- Format: Core ML ML Program
- Source dialect: TorchScript
- Core ML tools version in package metadata: `9.0`
- Conversion source version: `torch==2.7.0`
- Compute units: the iOS app requests `.all`

## Input

The model has one input:

- Name: `clips`
- Type: `MLMultiArray`
- Shape: `[1, 8, 3, 224, 224]`
- Element type: `float32`
- Layout: batch, time, RGB channel, height, width

The model accepts a fixed eight-frame temporal clip. It is not an image-input
model. The Core ML package does not encode the source-video crop or a frame
sampling policy.

The training and export pipeline supplies these values before Core ML:

1. Crop the annotated table ROI from the source frame.
2. Resize the crop to fit inside a `224 x 224` square.
3. Place the resized RGB image on a black `224 x 224` canvas.
4. Convert pixel values from `[0, 255]` to `[0, 1]`.
5. Apply ImageNet normalization per RGB channel:
   - mean: `[0.485, 0.456, 0.406]`
   - standard deviation: `[0.229, 0.224, 0.225]`

The resize uses OpenCV `INTER_AREA` in the Python cache builder. The iOS
preprocessor uses area resampling for downscaling and linear resampling for
upscaling, which matches OpenCV's `INTER_AREA` behavior. The crop ROI is
external annotation data and is not part of the model. The iOS runner requires
an explicit normalized ROI in the oriented frame coordinate space. It does not
silently substitute a center crop or a full-frame crop.

The training clip offsets are:

```text
[-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0] seconds
```

The configured inference decision stride is `0.125` seconds (8 Hz). These
values are adjacent training and inference configuration. They are not
encoded as Core ML input metadata.

## Output

The model has one output:

- Name: `logit`
- Type: `MLMultiArray`
- Shape: `[1]`
- Element type: `float32`
- Meaning: raw binary classification logit

The package has no predicted-label feature and no probability dictionary.
The application must calculate the canonical card-event probability as:

```text
p = 1 / (1 + exp(-logit))
```

The app boundary exposes this probability as `cardEventProbability` and keeps
the raw `logit` in `rawOutputs`.

## Known limits

- The model package does not state the semantic meaning of the positive class.
  The training labels and project documentation define it as a likely new
  `card_played` event.
- The package does not contain a live-camera ROI or calibration.
- The package does not contain temporal timestamps or frame sampling metadata.
- The app has no default live-camera ROI yet. Inference reports a clear error
  until the host supplies the table ROI.

The live camera path requests 32-bit BGRA frames, rotates the capture output
to portrait when the connection supports it, and samples at 8 Hz. The camera
stream and model queue are separate. Busy inference drops a frame instead of
adding it to an unbounded queue.
