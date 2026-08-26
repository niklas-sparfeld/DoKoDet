# DokoDetector

DokoDetector reconstructs **Doppelkopf games from video**.

The target setup is deliberately simple: an iPhone observes a normal game from an imperfect angle, under changing room lighting, while players play naturally and without interacting with the system.

The project combines lightweight on-device detection, server-side computer vision, and deterministic game logic.

## Architecture

```text
┌──────────────────────┐
│      iOS App         │
│                      │
│ CardEventNet         │
│ detects likely       │
│ card-play events     │
└──────────┬───────────┘
           │ evidence packages
           ▼
┌──────────────────────┐
│   Python Backend     │
│                      │
│ ingest + persistence │
│ orchestration        │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   VisionDetector     │
│                      │
│ identifies candidate │
│ played cards         │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│    Game Engine       │
│                      │
│ applies rules and    │
│ reconstructs game    │
└──────────────────────┘
```

The central idea is to keep uncertainty until the layer with enough context can resolve it:

```text
phone       → something probably happened
vision      → these cards may have been played
game engine → this is the coherent game
```

### iOS app

The iPhone is the capture device.

A small local model, **CardEventNet**, detects likely card-play events. The app records a small evidence package around those events and uploads it instead of continuously streaming video.

### Backend

A Python service receives and stores evidence packages and hands them to downstream processing.

It intentionally contains little vision or game logic so that recorded evidence can be replayed while those components evolve.

### VisionDetector

The VisionDetector turns evidence into candidate card events.

It may use multiple frames and larger models than are practical on the phone. Its output should preserve ambiguity and confidence rather than forcing every observation into one answer.

### Game engine

The game engine combines the observations with the known game setup and Doppelkopf rules.

It reconstructs tricks, rejects impossible interpretations, and can resolve earlier ambiguity retrospectively as more of the game becomes known.

## Repository

The repository contains several mostly independent sub-projects:

```text
doko-detector/
├── ios/           # iOS capture app
├── backend/       # Python backend
├── vision/        # VisionDetector and ML tooling
├── game-engine/   # Doppelkopf rules and reconstruction
├── fixtures/      # reusable test/evaluation data
├── docs/          # plans and architecture notes
├── mise.toml
├── AGENTS.md
└── README.md
```

The exact structure may evolve during implementation.

## Git LFS

The raw videos in `card_event_net/data/raw/` use Git LFS. Install Git LFS once before you
work with the videos:

```bash
brew install git-lfs
git lfs install
```

After a fresh clone, download the video content from the repository root:

```bash
git lfs pull
```

Run `git lfs pull` in an existing clone as well if the raw videos contain only LFS pointer
files. Use `git lfs ls-files` to check which files are managed by Git LFS.

## Development

The project is developed primarily on macOS.

* `mise.toml` defines shared development tools and versions.
* Language-native tooling is used on top, e.g. `uv` for Python and Xcode for Swift.
* Prefer reproducible local testing over repeatedly deploying to cloud GPUs or physical devices.
* Use a lightweight test-driven loop where practical: **test → implement → verify**.
* Git development is trunk-based.

## Implementation

The project is being built incrementally:

1. CardEventNet
2. iOS proof of concept
3. production capture app
4. Python backend
5. VisionDetector
6. game engine
7. end-to-end integration

Detailed decisions and component-specific architecture belong in the respective implementation plans rather than this README.

The Kanban epic board is in [`docs/plans/README.md`](docs/plans/README.md). Epic numbers record
creation order. Status folders record workflow state.

## Layout

- `card_event_net` will hold the iPhone-local detection model.
- `ios/` will hold the iOS client.
- `backend/` will hold backend services.
- `vision_detector/` will hold the later vision detector project.
- `docs/plans/` will hold repo-level plans.
