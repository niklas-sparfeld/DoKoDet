# Documentation authority and first hops

## Plan status

- **Summary:** Make the shortest current path from repository rules to architecture, component
  ownership, and local verification explicit.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** Agents can select one current authority and one component-local verification path
  without comparing stale transition guidance.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent specifies the authority map and Luna-sized
  delivery milestones.

## Problem and candidate paths

The root repository map omits active components. The target architecture still describes completed
0048 and 0049 work as future work. Current root and component documents duplicate commands and
retain transition guidance.

Candidate paths include `README.md`, component README files, current root contract files,
`docs/TableObservationReconstruction.md`, `docs/Data_Lifecycle.md`,
`docs/Pipeline_Data_Ownership.md`, and `docs/Pipeline_Data_Cutover_Handoff.md`.

## Exclusions and overlap

Do not change runtime behavior, canonical glossary meanings, accepted assets, or closed epic
history. Do not rewrite requirements owned by 0051, 0052, 0043, 0044, or 0050. A historical handoff
can be removed or clearly classified only after M0 proves that no current document needs it as an
authority.

## M0 specification questions

- Which document owns each shared fact, component contract, command, and work-state decision?
- Which current documents are durable authorities, operator guides, generated references, or
  completed handoffs?
- Which commands still work and which named consumer needs each command?
- What is the minimum first-hop README content for every top-level component?
- Which links and local checks prove the reduced documentation path?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused link and command checks. Close this epic without delivery when
the detailed evidence does not justify a change.
