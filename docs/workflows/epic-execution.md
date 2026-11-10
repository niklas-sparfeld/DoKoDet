# Optional epic execution workflows

Read this file before starting a persistent milestone run or a Luna loop. The root
[AGENTS.md](../../AGENTS.md) defines the shared development, Git, milestone completion, and
verification requirements. This file adds the rules for each optional execution mode.

## Re-planning limits

For a persistent milestone run or Luna loop, allow at most five re-plannings for each
milestone and at most ten re-plannings for the whole run. A re-planning is a revision of the
remaining milestone scope, acceptance criteria, or approach in response to new evidence. Count
each revision once against both limits, including revisions made after worker advice, review,
or a blocked report. Clarifications that do not revise the plan do not count.

Keep the current milestone and run counts in the execution handoff. A new milestone resets its
milestone count for genuinely independent work; a new user-authorized run resets the run count.
Splitting, renaming, or moving the same unfinished work does not reset its milestone counts.
Resuming an interrupted run keeps its existing counts. If another re-planning is needed after
either limit is reached, stop and report the evidence and remaining work. These limits do not
change the trigger to revisit the plan after two successive attempts that discover prerequisites
or do not reduce the scope.

## Goal and progress record

Before an implementing loop starts, check the plan against
[Plans for implementing agents](../../AGENTS.md#plans-for-implementing-agents). Repair an oversized
or weakly justified plan within existing authorization before assigning a worker. Do not begin a
long infrastructure chain merely because the milestones are already written. This preflight and
the scope review below are the current agent's work; they do not require another supervisor agent.

Keep these compact fields in the epic's execution handoff, across runs and compaction:

- Original user outcome, non-goals and final closure check.
- First complete workflow, its scheduled proof milestone, and latest evidence or exact gap.
- Initial and current remaining milestone counts; newly added source owners/contracts and why.
- Current run counts and cumulative re-planning/correction history for unfinished work. Give split
  milestones their original milestone as a shared family; keep its counts when names change.
- Last scope decision, what remaining work it removed, next proof/check and stop condition.

Record a plan-baseline count once; do not overwrite it on every restart. Preserve earlier counts
in a compact history when the user selects a different scope. Completed infrastructure is useful
evidence, but does not substitute for the promised workflow or closeout. Do not advance the first
workflow checkpoint or move qualification outside the run merely to fit newly discovered work.
A user-selected short run may end before an already-scheduled workflow or qualification milestone;
that is not a scope failure.

## Scope review

Perform this review before the next implementation assignment when any of these occurs:

- Two successive submissions or attempts discover prerequisites or fail to reduce the work needed
  for the selected workflow. Count attempts across workers, runs, and split milestone names.
- A new persistent authority/transaction contract or subsystem is proposed outside the frozen plan.
- The first complete workflow is still unproved at its checkpoint, or new work would displace the
  promised workflow/qualification beyond the authorized run.
- A milestone family exhausts its two correction turns, including corrections in earlier runs.

Read the original outcome and the small set of source/contract evidence needed to assess the
dependency. Compare remaining work with the initial plan. Answer: what user behavior has improved,
what exact requirement fails, and why must the new work precede delivery? Distinguish a local bug
from an invalid implementation boundary or an independently useful improvement. A review finding
does not automatically justify a stronger contract or more infrastructure.

Choose and record one concrete disposition: keep the approach with a bounded local fix; simplify
using existing authority; split an independent defect into a separate epic; remove/revert an
unsuccessful approach with dependency and retained-data checks; or supersede the plan. Name the
next observable proof, finite remaining assignments, checks, and stop condition. A smaller label,
another run, a longer prerequisite list, or a fresh worker is not a new approach. Do not drop a
valid correctness criterion to pass this gate. Do not mark removed scope complete; record it as
deferred, cancelled or superseded with an owner where needed.

The current agent owns this decision. Continue autonomously when the disposition is clear, within
the requested outcome and existing run/re-planning limits. Ask the user only for a concrete scope
choice outside that authorization or unresolved competing requirements. If no bounded disposition
is supported by evidence, stop implementation and report the decision needed. The scope gate may
end a run before its numeric limit; it is not permission to exceed an exhausted limit.

The two-correction limit follows unfinished work across user-authorized run restarts. A normal
`continue` or a fresh run does not grant two more attempts at the same failing approach. After
exhaustion, continue only with an explicitly user-authorized additional correction, or a materially
different/smaller approach recorded by this review within otherwise available authorization.
For a changed approach, record its new finite correction allowance (at most two), the old exhausted
counts, and why the change breaks the failure pattern. Adding the next missed edge case does not
qualify. Keep all other run and re-planning limits.

If two consecutive scope reviews produce neither workflow proof nor a concrete reduction in the
remaining work, end the current loop with an exit proposal. Do not use another review or run reset
as permission to repeat the unchanged approach. The next plan must resolve that recorded scope gate.

## Persistent milestone execution

Use this mode only when the user says `run epic 1234 for N milestones` or
`continue epic 1234 for N milestones`, where `N` is a positive integer. Both commands start at
the next incomplete milestone. The count includes that milestone. These commands authorize one
agent in the current chat to complete at most `N` milestones in sequence. The existing
`start epic 1234` and `next phase` commands keep their single-milestone behavior.

Follow the milestone completion requirements in [AGENTS.md](../../AGENTS.md#planning-workflow).
For each milestone, also maintain an `Execution handoff` section in the active epic. Record the
completed milestone, changes, checks and results, decisions, known limits, next milestone, and
this run's requested, completed, and remaining counts, and the re-planning counts. Keep one current
handoff and replace stale next steps and counts. Put detailed history in a milestone report. Keep
continuation facts here rather than only in chat history. Commit the handoff with the milestone
implementation and plan updates.

Maintain the goal/progress record above. After each milestone compare the promised workflow and
remaining work with the initial plan. Apply the scope-review triggers before continuing. This mode
has the same two-correction scope-review trigger as the Luna loop, even without a separate reviewer.

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
Git state. Complete the plan preflight and goal/progress record above before assignment. The
orchestrator owns the overall outcome and architecture/dependency decisions; Luna owns the bounded
implementation and its verification. A worker should not discover the epic's architecture by
successively expanding its assignment.

For an unbounded-count invocation, record the number of remaining planned milestones as this
run's limit. Do not add milestones to extend the run. Use this loop:

1. Assign one milestone to one fresh Luna worker. Use `fork_turns="none"` where supported.
   Supply a compact assignment with the repository path, milestone, authoritative file paths,
   acceptance criteria, original user outcome/non-goals, reason this milestone is needed, first
   workflow checkpoint, relevant handoff, family/run counts, and the worker rules below. Do not copy
   the parent conversation. Only one worker can be active. Workers must not spawn agents.
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
3. For each milestone submission, spawn a fresh review agent after the implementing worker
   completes. The reviewer is read-only. Give it the milestone acceptance criteria, relevant plan
   and handoff sections, original outcome/non-goals, dependency rationale, workflow checkpoint,
   cumulative family history, the worker receipt, and the changed-path summary. It checks whether
   the work follows the plan, appears obviously wrong or incomplete, or exposes a mistaken plan.
   It must also check whether added contracts/guarantees are necessary for the original outcome,
   the first workflow remains on schedule, and a correction retains earlier regression boundaries.
   This is a sanity check, not a test run, broad code review, or second implementation. Ask for a
   compact result: `PASS`, `IMPLEMENTATION_FIX`, or `PLAN_FIX`, with specific evidence, a one-line
   goal/scope assessment and a short handover note. Use `PLAN_FIX` for an unjustified prerequisite
   or missed scope checkpoint even when the local implementation is correct. The reviewer must not
   run tests, change files, or commit. This scope check does not authorize a broad source audit.
4. Read only the compact worker and reviewer receipts. Confirm that the worker's commit exists on
   `main`, its changed paths fit the assignment, and the epic and handoff record completion and
   checks. The receipts alone do not prove completion. A reviewer `PASS` proceeds through the
   normal completion gate; it does not replace required checks or the orchestrator's scope review.
   Compare remaining work and workflow evidence with the goal/progress record before assigning more.
5. For `IMPLEMENTATION_FIX`, send the milestone back to an implementing subagent with the
   reviewer's handover note. Prefer the same worker; if it is unavailable, use a fresh worker and
   include the original assignment and note. The worker makes only the needed correction and
   returns a new compact receipt. Run the sanity review again for that submission. Allow at most
   two correction turns per milestone family under the cross-run rules above. If a scope-review
   trigger is reached sooner, perform it before sending another correction. Stop implementation of
   the exhausted approach; a new worker or run does not reset it.
6. For `PLAN_FIX`, revise the milestone plan within the existing run authorization when the
   evidence shows that its acceptance criteria or approach is wrong. Apply the dependency check
   and scope review before accepting new prerequisites or stronger guarantees. Hand the revised
   assignment and reviewer's note to an implementing subagent, then review its next submission as above. If
   the correct plan remains unclear or exceeds the authorization, stop and report the decision
   needed. Ordinary remaining work is not a correction; if it exceeds the assignment, revise the
   milestone scope under the run limits.

When a worker asks for advice, resolve the escalation within the existing authorization. Clarify
its assignment, remove unnecessary work, split an independent defect, or give a concrete next step.
Apply any scope-review trigger before splitting work or accepting new prerequisites. Keep the run
and correction limits. A scope escalation is not a completed milestone or a correction turn. Record any revised
scope in the epic before resuming implementation. Ask the user only when a decision exceeds the
existing authorization or the intended behavior remains unclear.

When a worker reports `BLOCKED` or `NEEDS_USER`, do not stop the loop based on the receipt alone.
Inspect the specific evidence needed to decide whether human input is required or an external
dependency prevents progress. If the issue can be resolved within the existing authorization,
replan the remaining work, record any scope change in the epic, and continue with an implementing
worker only after any required scope review. Preserve the run limit and do not count an incomplete
milestone as complete. Do not repeat an unchanged failed action; give the worker a concrete revised
step. Stop only when the evidence
shows that a required human decision, unavailable dependency, exhausted limit, or unresolved scope
gate prevents progress within the authorization. Explain the precise blocker and remaining work.

Keep the orchestrator's context small. Do not read worker transcripts, raw logs, ongoing
implementation, or full diffs by default. Do not repeat source exploration or successful checks. Luna owns
implementation and verification. Compact context must still include the original outcome and
cumulative scope history. After the initial read, read the goal/progress record, relevant epic
sections and handoff changes. Inspect additional source or evidence only for a specific missing field,
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
- Do not introduce new authorities, transaction contracts, unrelated subsystem fixes or stronger
  guarantees without reporting the failing requirement and the actual dependency. Propose the
  smallest way to prove the requested workflow. Do not solve the epic's architecture in the worker.
- Use the existing checkout and follow the checkout and integration rules in `AGENTS.md`. Do not
  create a branch or worktree. Inspect Git state first. Preserve unrelated changes. Stop for
  integration problems only after following the conflict resolution and coordination rules in
  `AGENTS.md`. Do not stage unrelated paths.
- Run the milestone's relevant tests and required lint, format, type, generated API, link, and
  browser checks. Resolve failures within scope. Record baseline failures separately; they do
  not waive acceptance criteria. Preserve distinct earlier regression boundaries when adding a
  correction; do not replace the prior crash test with the next case. Do not mark incomplete
  acceptance criteria complete.
- Update the epic and board. Maintain an `Execution handoff` with changes, checks and outcomes,
  decisions, limits, next milestone, this run's requested, completed, and remaining counts, and
  the milestone and run re-planning counts. Preserve the original outcome, workflow checkpoint,
  initial plan count and shared family history. Report added source owners/contracts explicitly.
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
GOAL_PROGRESS: workflow evidence or remaining gap, not just infrastructure completed
SCOPE_CHANGE: none, or added owners/contracts and dependency evidence
HANDOFF: path and heading
NEXT:
DECISION_NEEDED: none, or one precise question
```

Use the persistent mode's handoff, interruption, and stop rules and the root compaction rule.
In this mode, the current chat orchestrates the authorized workers; do not create another supervisor, chat, harness,
or external continuation loop. After compaction, reconcile the handoff and actual Git state.
Stop at the run limit, epic completion, a user stop request, or a blocker that cannot be resolved
within the current authorization. Do not repeat an action
with an unknown outcome. End with completed milestones, commits, verification, all milestone
statuses, remaining work, and any blocker. Another run requires a new user instruction.
