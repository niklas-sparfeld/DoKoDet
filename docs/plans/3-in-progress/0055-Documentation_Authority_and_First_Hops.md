# Documentation authority and first hops

## Plan status

- **Summary:** Make the shortest current path from repository rules to architecture, component
  ownership, and local verification explicit.
- **Status:** In Progress
- **Depends on:** 0053 discovery complete
- **Outcome:** Agents can select one current authority and one component-local verification path
  without comparing stale transition guidance.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Complete — classified the current authorities and first-hop gaps from the 0053 report
  and the tracked documentation inventory.
- **M1:** Complete — published the shared authority route and removed current-state claims that
  contradicted the closed 0048 and 0049 epics.
- **M2:** Complete — gave the Python component guides one consistent ownership and verification
  hop.
- **M3:** Not started — complete the client and rules first hops and prove that navigation links
  and documented commands resolve locally.

## M0 evidence and decision

The 0053 report found that the root repository map omits `operations/`, `web/`, `game_engine/`,
and `schemas/`. It also found no iOS README or game-engine README. The current target architecture
states that 0048 and 0049 remain future work, but the epic board records both as closed. The two
pipeline cutover documents state that 0049 will remove paths that are already removed.

The target architecture is the authority for intended component boundaries. The epic board is the
authority for work state. `AGENTS.md` is the authority for repository rules, and the glossary is the
authority for domain terms. The root contracts and `schemas/` define shared serialized contracts.
Component README files are operator guides: each must point to its owned source and tests, then name
only its component-local checks. `Data_Lifecycle.md` and `Repository_Intake_Contract.md` are durable
operator guides. The two pipeline cutover documents are completed handoffs, not current authority.
Reports and closed epics are historical records.

No generated Markdown reference needs a new authority route. Generated API artifacts remain owned
by the backend export and web verification commands.

## M1 evidence

The root README now maps every top-level executable component and routes repository rules, domain
terms, target architecture, work state, shared contracts, and component operation to one authority.
The target architecture records 0048 and 0049 as completed foundations and sends current work to the
epic board. The two pipeline documents are marked as completed handoff records and retain their
implementation evidence without acting as current navigation.

Changed Markdown links resolve locally. A search of non-historical documentation found no remaining
claim that 0048 or 0049 must perform their completed cutover.

## M2 evidence

The CardEventNet, backend, operations, and TableEvidenceAnalyzer guides now identify their owned
source and test directories, public command or service entry point, component boundary, and exact
local pytest and Ruff checks. Shared architecture, work state, contracts, and repository intake
route through the root documentation route and durable lifecycle and intake guides. The analyzer
guide no longer duplicates the obsolete shared `doko data review` path.

The four public entry points and 50 documented subcommand help surfaces resolve locally. The
analyzer test suite passes with 149 tests. CardEventNet, backend, and operations full-suite or
format checks still report unrelated concurrent implementation changes in the shared worktree;
the documentation checks and all command help checks pass.

## Delivery milestones

### M1 — Publish the shared authority route

Update the root README with the complete top-level component map and a short authority table. It
must route rules to `AGENTS.md`, terms to the glossary, architecture to the target architecture,
work state to the board, and shared wire contracts to the root contract files and `schemas/`.

Update `docs/TableObservationReconstruction.md` to describe 0048 and 0049 as completed
foundations and to route future work through the board. Mark
`docs/Pipeline_Data_Ownership.md` and `docs/Pipeline_Data_Cutover_Handoff.md` as completed
handoffs. Remove them from current-navigation routes, but retain their implementation evidence.

Verify local Markdown links in the changed root and `docs/` files. Search the non-historical
documentation for claims that 0048 or 0049 still need to perform their completed cutover work.

### M2 — Normalize Python component first hops

Update the README files for `card_event_net/`, `backend/`, `operations/`, and
`table_evidence_analyzer/`. Each guide must have a compact first-hop section that names its owned
source and test directories, its public command or service entry point, and the exact local test
and Ruff commands. Move shared architecture, lifecycle, and cross-component command detail to the
authority route instead of duplicating it.

Keep commands that have a current named consumer. Do not remove a training, evaluation, recovery,
or active-epic command. Do not change command behavior, Python imports, package contracts, or
fixtures.

Verify every retained command shown in the changed guides with its documented help or focused local
check. Run the documented component test and Ruff boundary for each changed guide.

### M3 — Complete client and rules first hops

Add concise README files for `ios/` and `game_engine/`, and update `web/README.md`. Each guide
must name its owned code and test locations, upstream boundary, and supported local verification
command. The iOS guide must distinguish Swift Package checks from the Xcode app build. The game
engine guide must route rules terminology to `GAME_RECONSTRUCTION_CONTRACT.md` and the glossary.
The web guide must route generated OpenAPI ownership to backend export and retain its current
`npm run check` and viewport coverage path.

Add a lightweight repository documentation check or focused test only if existing link checking
cannot prove that the authority and first-hop links resolve. Verify all changed Markdown links,
run the documented Swift Package and game-engine checks, and run `npm run check`; run the focused
web browser coverage that touches any changed operator workflow.

## Exclusions and overlap

M1–M3 are documentation-only. They must not alter runtime behavior, canonical glossary meanings,
accepted assets, generated API output, or closed epic history. Do not rewrite requirements owned by
0051, 0052, 0043, 0044, or 0050. A historical handoff can be reclassified only after its current
links route to a durable authority.

## Completion criteria

- One root route identifies the authority for rules, terms, architecture, work state, contracts,
  and component-local operation.
- Every top-level executable component has a README that names owned source, tests, upstream or
  downstream boundary, and local verification.
- No current authority describes the completed 0048/0049 cutover as pending.
- All changed documentation links resolve, and each retained documented command has a passing
  local proof in its owning component.
