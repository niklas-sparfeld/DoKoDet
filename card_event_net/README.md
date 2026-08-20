# CardEventNet

CardEventNet detects the moment when a card has just landed in the trick area.

Run the commands below from `card_event_net/`.

## Current state

This repo now has the phase-1 scaffold:

- project metadata
- config loading
- device selection
- CLI shell
- test and lint setup

## Setup

If `uv` is not available yet, run `mise install` first so the toolchain from `mise.toml` is ready.

```bash
uv sync
uv run cardevent --help
uv run pytest
uv run ruff check .
```
