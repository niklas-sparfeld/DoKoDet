# Web workspace module boundaries

## Plan status

- **Summary:** Give recording workspace stages, inspectors, source surfaces, state helpers, styles,
  and tests clear local ownership.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** One operator UI change needs a small stage-local code and test surface while the
  completed workspace layout stays unchanged.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent measures co-change and state boundaries and
  specifies Luna-sized delivery milestones.

## Problem and candidate paths

Excluding generated OpenAPI code, web source contains 26,431 lines and nine files over 1,000 lines.
The recording workspace, three stage editors, analysis workbenches, and 5,846-line shared CSS module
mix several UI responsibilities. Candidate paths include `web/src/pipeline/`, `cardEvents/`,
`visibleCards/`, `visualIdentities/`, `analysis/`, `App.module.css`, and their tests.

## Exclusions and overlap

Preserve the completed 0054 viewport shell, central source surface, inspector, and Timeline Rail.
Do not change operator behavior, URLs, accessibility, API contracts, or persistence. Generated
`web/src/api/openapi.ts` is not a cleanup target. Do not add 0051 quality behavior.

## M0 specification questions

- Which files and symbols change together for common stage work?
- Which state is stage-local and which state must remain in the recording workspace?
- How can styles gain ownership without duplication or selector-order changes?
- Which existing tests can move beside the responsibility they verify?
- Which desktop and narrow viewport checks prove behavior and layout preservation?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused unit, check, and browser verification. Close this epic without
delivery when splitting would add wrappers or duplicate state without reducing navigation cost.
