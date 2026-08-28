# DokoDetector

DokoDetector reconstructs **Doppelkopf games from video**.

The target setup is simple. An iPhone records a normal game from an imperfect angle. Room lighting
can change. Players can play naturally without interacting with the system.

The project combines on-device event proposals, bounded evidence capture, deployment-neutral table
evidence analysis, deterministic game reconstruction, and human correction.

## Architecture

```text
┌────────────────────────┐
│ iOS evidence capture   │
│                        │
│ CardEventNet proposes  │
│ possible visual events │
└────────────┬───────────┘
             │ selected frames and bounded video snippet
             ▼
┌────────────────────────┐
│ Evidence transport     │
│ and storage            │
│                        │
│ preserves source bytes │
└────────────┬───────────┘
             │ supplied evidence package
             ▼
┌────────────────────────┐
│ TableEvidenceAnalyzer  │
│                        │
│ inspects evidence and  │
│ emits observations     │
└────────────┬───────────┘
             │ ordered TableObservation stream
             ▼
┌────────────────────────┐
│ Game reconstruction    │
│                        │
│ applies rules and      │
│ retains alternatives   │
└────────────┬───────────┘
             │ resolved result or focused questions
             ▼
┌────────────────────────┐
│ Human review           │
│                        │
│ applies traceable      │
│ correction constraints │
└────────────────────────┘
```

The central rule is to keep uncertainty until a component has enough context to resolve it:

```text
CardEventNet          → something probably changed
TableEvidenceAnalyzer → these visible-card observations fit the supplied evidence
game reconstruction   → these card plays and tricks form the retained games
human review          → this correction resolves or replaces the machine result
```

The logical boundaries do not select a deployment. The TableEvidenceAnalyzer can run in a local
service first and move partly or fully on-device later without changing its input and output
contracts.

The detailed target is in
[Table Observation and Game Reconstruction](docs/TableObservationReconstruction.md).

### iOS evidence capture

The iPhone captures evidence. A small local model, **CardEventNet**, reports event proposals. An
event proposal is not proof of a card play.

The app stores selected frames and a bounded video snippet around a proposal. It uploads an evidence
package instead of continuously streaming video.

### Evidence transport and storage

The Python backend receives and validates evidence packages. It stores each accepted package as one
immutable repository intake bundle. The searchable index and analyzer output are disposable state.
The backend preserves source bytes and hands a requested package to downstream processing.

The backend contains little table analysis or game logic. This keeps stored evidence replayable as
analyzer components and reconstruction methods change.

### TableEvidenceAnalyzer

The TableEvidenceAnalyzer is handed an evidence package to inspect. It does not capture evidence
actively and does not apply game rules.

It can combine several vision models with classical image processing, matching, geometry, and
short-term object tracking. Its internal components can change independently. Its boundary stays
stable:

```text
EvidencePackage → TableEvidenceAnalyzer → TableObservation
```

A table observation contains anonymous observed cards and ranked visual card identity candidates.
Optional capabilities can add presence, newly-visible, active-area, association, and card-tracklet
evidence. The analyzer preserves ambiguity instead of forcing one played-card decision.

### Game reconstruction

Game reconstruction combines ordered table observations with the known round setup and Doppelkopf
rules. It infers persistent cards, card plays, trick boundaries, active players, and missing plays.

It can retain several reconstruction hypotheses. It reports the smallest gameplay decisions that
differ between them.

### Human review

A reviewer can answer focused questions or edit the complete round. Each edit becomes an immutable
correction constraint. Reconstruction runs again without changing the source evidence or earlier
results.

## Repository

The repository contains several mostly independent projects:

```text
doko_detector/
├── card_event_net/          # on-device event-proposal model and data tools
├── ios/                     # iOS capture and evidence upload
├── backend/                 # evidence ingestion and local orchestration
├── table_evidence_analyzer/ # analyzer contracts and model-training foundation
├── fixtures/                # shared contract and scenario fixtures
├── docs/                    # architecture, reports, and plans
├── mise.toml
├── AGENTS.md
└── README.md
```

The `table_evidence_analyzer/` package contains the analyzer contracts and model-training
foundation. It contains model-based and classical analyzer components and is not tied to backend
deployment.

## Git LFS

The raw videos in `card_event_net/data/raw/` use Git LFS. Install Git LFS once before you work with
the videos:

```bash
brew install git-lfs
git lfs install
```

After a fresh clone, download the video content from the repository root:

```bash
git lfs pull
```

Run `git lfs pull` in an existing clone if the raw videos contain only LFS pointer files. Use
`git lfs ls-files` to check which files Git LFS manages.

## Development

The project is developed primarily on macOS.

- `mise.toml` defines shared development tools and versions.
- Language-native tooling runs on top. Python projects use `uv`; the iOS project uses Xcode.
- Prefer reproducible local tests to repeated cloud or physical-device deployment.
- Use a lightweight test-driven loop where practical: **test → implement → verify**.
- Use trunk-based Git development.

## Delivery

The near-term work proceeds in independent layers:

1. establish shared source, annotation, review, and lineage data;
2. freeze the table-observation and reconstruction contracts with synthetic fixtures;
3. add bounded video snippets to iOS and backend evidence transport;
4. build reusable model training for TableEvidenceAnalyzer capabilities;
5. add analyzer capabilities one at a time with reconstruction ablations;
6. scale game reconstruction;
7. add focused human review and complete correction;
8. select production work from measured requirements.

The [epic board](docs/plans/README.md) contains the exact order, dependencies, and acceptance gates.
Epic numbers record creation order. Status folders record workflow state.

## Storage boundaries

Shared source bytes use these repository-root paths:

```text
data/incoming/videos/<upload-id>/             pending upload; not yet intake
data/intake/recordings/<recording-id>/        complete recording bundle
data/intake/evidence-packages/<package-id>/   accepted evidence package
data/operations/                              review and lifecycle artifacts
backend/.runtime/                             disposable index, cache, and outputs
```

A pending upload is not visible to review or dataset assembly. An operator completes it with
metadata and both task enrollments before it becomes a recording bundle:

```bash
mise exec -- uv run --project operations doko data status --repository-root .
mise exec -- uv run --project operations doko data complete-video \
  --repository-root . --upload-id <upload-id> --metadata completion.json
```

Accepted evidence packages are available to both data tasks when their independent task
enrollments select the task. Review reads the shared package in place; it does not copy source
media into a component data directory. Inspect or validate the shared intake with:

```bash
mise exec -- uv run --project operations doko data validate --repository-root .
mise exec -- uv run --project operations doko data adopt-evidence \
  --repository-root . --runtime-root backend/.runtime \
  --package-id <package-id> --metadata package-metadata.json
```

The adoption command is for packages from the old runtime path. It keeps the old package until the
operator verifies the new intake bundle. Deleting `backend/.runtime` cannot delete an accepted
source package.
