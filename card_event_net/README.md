# CardEventNet

CardEventNet detects the moment when a card has just landed in the trick area.

Run the commands below from `card_event_net/`.

## Current state

This repo now has the phase-2 annotator:

- project metadata
- config loading
- device selection
- annotation schema and validation
- video metadata reading
- OpenCV annotation tool
- test and lint setup

The annotator stores one JSON file per source video in `data/annotations/`.
It remembers the ROI and the saved events.

Startup controls:

```text
SPACE   mark a card_played event
P       pause or play
A / D   seek backward or forward about 250 ms
J / L   seek backward or forward about 2 s
BACKSPACE or X  remove the latest event
R       redefine the ROI
Q       save and exit
```

## Setup

If `uv` is not available yet, run `mise install` first so the toolchain from `mise.toml` is ready.

```bash
uv sync
uv run cardevent --help
uv run pytest
uv run ruff check .
```

## Annotation

Run the annotator from `card_event_net/`:

```bash
uv run cardevent annotate data/raw/IMG_0090.mov
```

The tool shows the event definition at startup. On first use, select the ROI in the OpenCV
window, then save. You can quit and reopen the same video later. Existing events stay in the
JSON file.
