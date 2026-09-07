# Epic 0053 agent navigation cleanup discovery

Date: 2026-09-07

## Scope

This report is a broad and shallow review of tracked repository evidence. It excludes dependency
trees, build products, caches, local runtime data, accepted source assets, generated API code, and
closed epic history from cleanup counts. It does not propose implementation designs.

## First-hop navigation map

| Need | First authority | Owning code and local verification |
| --- | --- | --- |
| Repository rules and terms | [`AGENTS.md`](../../AGENTS.md), then the [glossary](../glossary.md) | Use the component entry below. |
| Current direction and work | [Target architecture](../TableObservationReconstruction.md), then the [epic board](../plans/README.md) | The active epic owns change-specific checks. |
| Event model and data tools | [`card_event_net/README.md`](../../card_event_net/README.md) | `card_event_net/src/cardevent/`, `card_event_net/tests/`; run `uv run pytest` and Ruff from `card_event_net/`. |
| iOS capture and upload | Root README and `ios/Package.swift`; there is no iOS README | `ios/CardEventProbe/`, `ios/CardEventProbeTests/`; Swift Package and Xcode boundaries both need confirmation. |
| Local HTTP and orchestration | [`backend/README.md`](../../backend/README.md) | `backend/src/dokodetector_backend/`, `backend/tests/`; run pytest and Ruff from `backend/`. |
| Repository data and model operations | [`operations/README.md`](../../operations/README.md) | `operations/src/doko_operations/`, `operations/tests/`; use the `doko` entry point. |
| Analyzer contracts and model tools | [`table_evidence_analyzer/README.md`](../../table_evidence_analyzer/README.md) | `table_evidence_analyzer/src/table_evidence_analyzer/`, `table_evidence_analyzer/tests/`; use the `table-analyzer` entry point. |
| Reconstruction rules | [`GAME_RECONSTRUCTION_CONTRACT.md`](../../GAME_RECONSTRUCTION_CONTRACT.md) and the target architecture | `game_engine/src/game_engine/`, `game_engine/tests/`. |
| Operator web UI | [`web/README.md`](../../web/README.md) | `web/src/`, `web/tests/`; run `npm run check` and `npm run test:e2e`. |
| Shared contracts and scenarios | Root contract files, `schemas/`, and `fixtures/` | Consumers span Python, Swift, and TypeScript. Verify the affected consumers. |

The dependency direction visible in package manifests is:

```text
web -> backend OpenAPI
backend -> operations, CardEventNet, TableEvidenceAnalyzer
operations -> game engine, TableEvidenceAnalyzer
iOS -> backend contracts through shared fixtures
schemas and fixtures -> several component tests
```

Keep these top-level component boundaries. The current problem is the quality of the first hop and
the size of some component-local surfaces, not the existence of the boundaries.

## Repeatable baseline

The baseline is the pre-M0 tree at commit `5bb4fa7eb`. The scan found 714 tracked paths and
19,807,502 tracked bytes. The 45 tracked Markdown files outside closed epic history contain 7,703
lines. Root, component, contract, and durable `docs/*.md` guidance contains 4,674 lines. The three
Python command parsers contain 3,859 lines and 73 `add_parser` calls.

| Area | Source baseline | Navigation signal |
| --- | --- | --- |
| Operations | 33 Python modules, 37,151 lines | 14 source files have at least 1,000 lines; 10 have at least 1,500. `__init__.py` exports 449 names. |
| Backend | 44 Python modules, 19,680 lines | Five source files have at least 1,000 lines. Eight `*pipeline*.py` files contain 7,450 lines. |
| Web | 37 source files, 31,074 lines | Generated `api/openapi.ts` is 4,643 lines and is excluded as generated output. Nine other files have at least 1,000 lines. |
| iOS app | 48 Swift files, 18,236 lines | Six source files have at least 1,000 lines. |
| CardEventNet | 39 Python modules, 20,269 lines | Four source files have at least 1,000 lines. |
| TableEvidenceAnalyzer | 30 Python modules, 18,241 lines | Seven source files have at least 1,000 lines. |

Repeat the path and size baseline with `git ls-files`, `wc -c`, and `wc -l`. Repeat command-surface
counts with `rg 'add_parser\('` over the three `cli.py` files. Do not count `uv.lock`,
`package-lock.json`, model weights, media fixtures, generated OpenAPI code, or closed epics as
cleanup targets.

## Retained candidates

### 1. Current documentation authority and first hops — epic 0055

- **Ratings:** navigation benefit `high`; implementation risk `low`; confidence `high`.
- **Problem and example:** An agent cannot trust one short path from repository purpose to current
  work. The root repository tree omits `operations/`, `web/`, `game_engine/`, and `schemas/`.
  `docs/TableObservationReconstruction.md` still says that 0048 and 0049 have not completed and
  tells agents to start them, although both are closed.
- **Paths and owner:** root and component README files, current root contract files, and durable
  documents under `docs/`. Architecture facts belong to the target architecture; work state belongs
  to the epic board; commands belong to their owning component.
- **Evidence:** Current non-closed Markdown contains 7,703 lines. Transitional documents
  `Pipeline_Data_Ownership.md` and `Pipeline_Data_Cutover_Handoff.md` still describe work for 0049
  to perform. Component READMEs range from 41 to 419 lines and do not use one consistent route to
  local checks. There is no iOS README.
- **Expected simplification:** One dependable first hop per task. Remove the need to compare stale
  transition plans with the board and implementation.
- **Verification boundary:** local Markdown links plus every retained command in its owning
  component documentation.
- **Missing Terra evidence:** Classify each durable document as authority, operator guide,
  generated reference, or historical handoff. Confirm every current command before removal.
- **Active overlap:** 0051 owns resilience requirements. 0043, 0044, 0050, and 0052 own their
  future scopes. Do not rewrite their plans.

### 2. Superseded review and data interfaces — epic 0056

- **Ratings:** navigation benefit `high`; implementation risk `medium`; confidence `high`.
- **Problem and example:** Agents still find package-backed and review-batch commands and modules
  after the recording workspace removed their backend routes. This makes obsolete and supported
  workflows appear equal.
- **Paths and owner:** legacy review/data surfaces in `card_event_net/`, `operations/`, and
  `table_evidence_analyzer/`, with their tests and current documentation. The recording pipeline is
  the current owner of review and processing entry points.
- **Evidence:** The former backend route modules for event, visible-card, and visual identity review
  are absent. Four retained legacy review modules contain 8,053 lines. Current component and data
  guides still advertise old queue, review, dataset, import, and retirement commands. The three
  command parsers together expose 73 parser declarations.
- **Expected simplification:** Make supported commands and reusable validators clear. Remove
  obsolete orchestration, tests, exports, and guidance after consumer proof.
- **Verification boundary:** all affected Python component tests and Ruff checks; retained commands
  must have named agent, test, automation, runtime, operations, or recovery consumers.
- **Missing Terra evidence:** Build a command-by-command consumer table. Separate reusable contract
  validation from obsolete orchestration. Check untracked operational instructions before removal.
- **Active overlap:** Preserve all 0051 paths and any training or evaluation entry point required by
  0043 or 0050. Preserve the device evidence-package showcase and recovery paths.

### 3. Operations module and public API boundaries — epic 0057

- **Ratings:** navigation benefit `high`; implementation risk `medium`; confidence `high`.
- **Problem and example:** Common operations changes cross large files and an eager package export
  surface. Importing an operations submodule executes an `__init__.py` that re-exports 449 names
  from most of the package.
- **Paths and owner:** `operations/src/doko_operations/`, its tests, and backend imports of
  operations contracts. The operations package owns shared data, comparison, model, and
  reconstruction orchestration.
- **Evidence:** The package has 37,151 source lines. Fourteen of 33 modules exceed 1,000 lines.
  `pipeline_comparison.py`, `round_reconstruction.py`, model campaigns, derived views, and review
  stores each combine contract types, parsing, validation, execution, and publication concerns.
  Backend code already uses direct submodule imports in most places.
- **Expected simplification:** Smaller stable contract and execution modules, explicit imports, and
  tests beside the responsibility they verify.
- **Verification boundary:** operations pytest and Ruff, plus backend tests for every moved public
  contract.
- **Missing Terra evidence:** Measure the real import graph, select two or three high-frequency
  change paths, and define safe seams. Confirm which exports are external API.
- **Active overlap:** Epic 0056 owns removal decisions for superseded interfaces. Epic 0051 owns
  resilience behavior. This candidate must not redesign either.

### 4. Backend pipeline service boundaries — epic 0058

- **Ratings:** navigation benefit `high`; implementation risk `medium`; confidence `high`.
- **Problem and example:** `pipeline_service.py` combines event execution, comparison, and complete
  recording-workspace assembly. `pipeline_reference_service.py` combines commands, content-specific
  edits, coverage, correction impact, and publication. `pipeline_api.py` combines all pipeline HTTP
  models and routes.
- **Paths and owner:** backend pipeline service, store, API, and focused tests. The backend owns HTTP
  translation and local orchestration, not analyzer or game rules.
- **Evidence:** Eight pipeline-named source files contain 7,450 lines. Five backend source files
  exceed 1,000 lines. The largest two services contain several distinct class families and many
  content-specific branches.
- **Expected simplification:** Let an agent open one service and one focused test area for a stage,
  reference operation, or workspace summary.
- **Verification boundary:** backend pytest and Ruff, web OpenAPI verification, and affected local
  pipeline tests.
- **Missing Terra evidence:** Trace constructor wiring and state ownership. Identify seams that do
  not duplicate validation or create circular imports.
- **Active overlap:** 0051 uses visual identity pipeline and derived-view behavior. Do not change its
  contracts or current data.

### 5. Web workspace module boundaries — epic 0059

- **Ratings:** navigation benefit `high`; implementation risk `medium`; confidence `high`.
- **Problem and example:** A stage edit often requires loading a 1,700–2,100-line component and
  searching a 5,846-line shared CSS module. Routing, data loading, source surfaces, inspectors,
  command state, formatting, and guards often share one file.
- **Paths and owner:** `web/src/pipeline/`, the three stage editors, analysis workbenches,
  `App.module.css`, and their tests. The web package owns the operator presentation.
- **Evidence:** Excluding the generated 4,643-line OpenAPI file, web source has 26,431 lines and
  nine files of at least 1,000 lines. The recording workspace and three editors each contain
  multiple UI surfaces and helpers.
- **Expected simplification:** Stage-local components, styles, state helpers, and focused tests that
  reduce unrelated UI context for one change.
- **Verification boundary:** `npm run check` and `npm run test:e2e` at the supported viewport set.
- **Missing Terra evidence:** Find the most frequent co-change paths, shared state seams, and style
  ownership. Select moves that reduce context without adding wrapper files.
- **Active overlap:** Preserve the completed 0054 layout and Timeline Rail. Do not add 0051 quality
  behavior during this cleanup.

### 6. iOS capture module boundaries — epic 0060

- **Ratings:** navigation benefit `medium`; implementation risk `medium`; confidence `medium`.
- **Problem and example:** `EvidencePackage.swift` is 2,089 lines and `AppState.swift` is 1,792
  lines. Evidence contract models, validation, encoding, and package assembly sit close together;
  app-wide capture, upload, analysis, and presentation state share one controller.
- **Paths and owner:** `ios/CardEventProbe/Core/`, `App/AppState.swift`, networking collaborators,
  Swift Package declarations, and tests. The iOS app owns capture and upload behavior.
- **Evidence:** The app has 18,236 Swift source lines and six files over 1,000 lines. The Package
  manifest enumerates many individual core sources, but no component README gives the first source
  and verification hop.
- **Expected simplification:** Smaller contract, validation, state, and coordination boundaries so
  one capture or upload change does not require the complete app state.
- **Verification boundary:** Swift Package tests plus the affected Xcode app build and fixture
  contract tests.
- **Missing Terra evidence:** Map Xcode and Swift Package membership, actor and main-thread
  constraints, persistence compatibility, and the minimum stable seams.
- **Active overlap:** Preserve the device showcase, durable upload and retry behavior, model bundle,
  evidence bytes, and backend contract.

## Rejected ideas

- **Move top-level components for uniformity:** Rejected. The package manifests show useful
  component and dependency boundaries. A move would create import, build, test, fixture, and
  documentation churn without a demonstrated multi-task ownership gain.
- **Move `operations/` into `backend/`:** Rejected. Operations has its own `doko` entry point and is
  also a dependency boundary for shared data and reconstruction work. Backend is one consumer.
- **Move `schemas/` or `fixtures/` into one component:** Rejected. Python, Swift, backend, and web
  verification share these contracts and scenarios.
- **Merge the game engine with TableEvidenceAnalyzer:** Rejected. The target architecture requires
  uncertain visual evidence to remain separate from deterministic game rules.
- **Delete all command-line interfaces:** Rejected. The backend service entry point is a runtime
  consumer. `doko` supports agent development, operations, recovery, and active evaluation work.
  Training and export commands also have test and automation consumers. Epic 0056 must prove
  removal command by command.
- **Delete models, reviewed data, media fixtures, generated OpenAPI, or lock files because they are
  large:** Rejected. They are accepted assets, reproducibility inputs, shared fixtures, generated
  boundaries, or dependency locks. Their byte size is not navigation evidence.
- **Rewrite closed epics and old reports:** Rejected. They are immutable history and were excluded
  from cleanup counts.
- **Clean active resilience or model-quality work now:** Rejected. Epics 0051, 0052, 0043, 0044,
  and 0050 already own those outcomes.

## Recommended order

1. Specify 0055. Fix the authority path before other cleanup changes need documentation updates.
2. Specify 0056. Prove and retire superseded interfaces before splitting code that might disappear.
3. Specify 0057. Refine the remaining operations package after obsolete-surface decisions are clear.
4. Specify 0058. Reduce backend pipeline context while preserving its generated web contract.
5. Specify 0059. Split the stable 0054 presentation without changing its behavior.
6. Specify 0060. Improve the higher-risk iOS boundary after the shared contract and command guidance
   is clear.

Each follow-up remains independently closable if its Terra evidence does not justify delivery.
