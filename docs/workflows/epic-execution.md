# Optional epic execution workflows

Read this file before starting a persistent milestone run or a Luna loop. The root
[AGENTS.md](../../AGENTS.md) defines the shared development, Git, milestone completion, and
verification requirements. This file adds the rules for each optional execution mode.

## Persistent milestone execution

Use this mode only when the user says `run epic 1234 for N milestones` or
`continue epic 1234 for N milestones`, where `N` is a positive integer. Both commands start at
the next incomplete milestone. The count includes that milestone. These commands authorize one
agent in the current chat to complete at most `N` milestones in sequence. The existing
`start epic 1234` and `next phase` commands keep their single-milestone behavior.

Follow the milestone completion requirements in [AGENTS.md](../../AGENTS.md#planning-workflow).
For each milestone, also maintain an `Execution handoff` section in the active epic. Record the
completed milestone, changes, checks and results, decisions, known limits, next milestone, and
this run's requested, completed, and remaining counts. Keep one current handoff and replace stale
next steps and counts. Put detailed history in a milestone report. Keep continuation facts here
rather than only in chat history. Commit the handoff with the milestone implementation and plan updates.

Give the milestone summary in commentary, then continue without waiting for another prompt.

In this mode, the commentary summary and committed handoff replace the end-of-turn handoff
between milestones. Follow the compaction rule in `AGENTS.md`. After compaction, read the handoff
and verify the actual epic and Git state before continuing. Do not create a supervising agent, a new chat,
or an external continuation loop for this mode.

Stop when the count is reached, the epic is complete, the user asks to stop, or the next milestone
cannot proceed safely. A blocked dependency, required user decision or approval, unresolved check
failure, or a Git integration problem that remains unsafe after following `AGENTS.md` ends the run
early. Record the reason and remaining count in the handoff when possible. Do not skip a blocked milestone, expand the epic, or repeat a
commit or action whose outcome is unknown. An interruption does not authorize an automatic restart;
on an explicit resume, reconcile saved progress before doing more work.

At the end of the run, give a final summary with completed milestones, commit IDs, verification,
all milestone statuses, and any blocker. The count limit ends this authorization; another run
requires a new user instruction.

## Luna loop

Invoke this mode with `luna loop epic 1234` to complete the remaining milestones, or
`luna loop epic 1234 for N milestones` to complete at most `N` milestones. Start at the next
incomplete milestone. These commands authorize sequential Luna subagents in the current chat.
They do not change the behavior of `start epic`, `next phase`, or the persistent commands above.

The current chat is the orchestrator, regardless of its model or reasoning level. Use
`gpt-6-luna` at High reasoning for workers. Check the available worker model controls. If that
configuration is unavailable, stop and explain. Do not silently substitute another worker model.

The orchestrator reads `AGENTS.md`, this file, and the current epic, dependencies, handoff, and
Git state.
For an unbounded-count invocation, record the number of remaining planned milestones as this
run's limit. Do not add milestones to extend the run. Use this loop:

1. Assign one milestone to one fresh Luna worker. Use `fork_turns="none"` where supported.
   Supply a compact assignment with the repository path, milestone, authoritative file paths,
   acceptance criteria, relevant handoff, run count, and the worker rules below. Do not copy the
   parent conversation. Only one worker can be active. Workers must not spawn agents.
2. After assigning the milestone, wait for the worker's completion notification. Use a blocking
   agent wait with the longest timeout allowed by the active instructions. If the wait times out,
   wait again; a timeout is not a reason to check on the worker. After 10 minutes without a worker
   message or completion, make one status check using the agent listing. If it is still running,
   resume waiting and allow at least 10 more minutes before another check. Elapsed time alone does
   not prove a stall. Do not interrupt or message the worker based only on elapsed time. If the
   status shows a failure or another concrete problem, inspect only the evidence needed to decide
   the next step. Do not use short waits, status requests, messages, transcript reads, or worktree
   inspection for routine monitoring. A user update does not require a worker check. Respond to user
   instructions and genuine worker messages when they arrive. Workers must not send routine progress
   messages to the orchestrator.
3. Read only the compact completion receipt. Confirm that its commit exists on `main`, its
   changed-path summary fits the assignment, and the epic and handoff record completion and
   checks. The receipt alone does not prove completion.
4. If the completion gate passes, give a brief commentary summary with the commit and milestone
   statuses. Completed earlier milestones can be grouped. Continue without asking the user.
5. If a correction is clear, send it to the same worker. Allow at most two correction turns per
   milestone. Stop for a persistent failure, required human decision, or unclear safe next step.
   Corrections fix defects in the assigned result. Ordinary remaining work is not a blocker or
   a correction; if it exceeds the assignment, revise the milestone scope under the run limits.

When a worker asks for advice, resolve the escalation within the existing authorization. Clarify
its assignment, split the remaining work, or give a concrete next step. Keep the run and correction
limits. A scope escalation is not a completed milestone or a correction turn. Record any revised
scope in the epic before resuming implementation. Ask the user only when a decision exceeds the
existing authorization or the intended behavior remains unclear.

Keep the orchestrator's context small. Do not read worker transcripts, raw logs, ongoing
implementation, or full diffs by default. Do not repeat source exploration or successful checks. Luna owns
implementation and verification. After the initial read, read only relevant epic sections and
handoff changes. Inspect additional source or evidence only for a specific missing field,
contradiction, failure, or acceptance gap. Request bounded excerpts. Record token usage only
when tools expose it. Do not claim measured savings without comparable measurements.

Include these worker rules in every assignment:

- Read applicable `AGENTS.md` files, the assigned milestone, relevant contracts and handoff, and
  the glossary before changing domain terminology. Implement only the assigned milestone.
- If new prerequisites substantially expand the assigned scope, the acceptance criteria require
  work outside it, or two successive attempts do not reduce the remaining work, pause and ask the
  orchestrator for advice. Report what is complete, what remains, the evidence, and a proposed
  smaller next step. Preserve current work and identify any active operation. Ordinary complexity,
  elapsed time, and resolvable integration conflicts alone are not reasons to pause. This advice
  request is an allowed message before the final receipt; do not mark the milestone complete.
- Use the existing checkout and follow the checkout and integration rules in `AGENTS.md`. Do not
  create a branch or worktree. Inspect Git state first. Preserve unrelated changes. Stop for
  integration problems only after following the conflict resolution and coordination rules in
  `AGENTS.md`. Do not stage unrelated paths.
- Run the milestone's relevant tests and required lint, format, type, generated API, link, and
  browser checks. Resolve failures within scope. Record baseline failures separately; they do
  not waive acceptance criteria. Do not mark incomplete acceptance criteria complete.
- Update the epic and board. Maintain an `Execution handoff` with changes, checks and outcomes,
  decisions, limits, next milestone, and this run's requested, completed, and remaining counts.
  Replace stale handoff facts; keep detailed history and evidence in a milestone report.
- Commit implementation, documentation, and plan updates together as one focused milestone
  commit. Integrate it into `main` before reporting completion. For the final milestone, verify
  closure criteria, move the epic to the correct folder, and repair links. Use `INCOMPLETE` for
  ordinary unfinished work. Use `BLOCKED` only when a concrete dependency, failed check, or unresolved
  integration problem prevents further work. Return only this receipt, at most 180 words:

```text
RESULT: COMPLETE | INCOMPLETE | BLOCKED | NEEDS_USER
MILESTONE:
COMMIT: hash, or none
CHANGES: at most three short bullets
CHECKS: commands/check names and pass/fail; evidence path
ACCEPTANCE_GAPS: none, or exact gaps
HANDOFF: path and heading
NEXT:
DECISION_NEEDED: none, or one precise question
```

Use the persistent mode's handoff, interruption, and stop rules and the root compaction rule.
In this mode, the current chat orchestrates the authorized workers; do not create another supervisor, chat, harness,
or external continuation loop. After compaction, reconcile the handoff and actual Git state.
Stop at the run limit, epic completion, a user stop request, or a blocker. Do not repeat an action
with an unknown outcome. End with completed milestones, commits, verification, all milestone
statuses, remaining work, and any blocker. Another run requires a new user instruction.
