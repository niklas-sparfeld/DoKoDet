# AGENTS.md

## Development

Keep changes small and easy to verify.

Use a lightweight test-driven workflow when it makes sense:

1. Write or update a test.
2. Implement the change.
3. Run the relevant tests and checks.

Prefer automated verification over repeated manual testing.

## Backward compatibility

Do not preserve backward compatibility unless the user explicitly requests it.

Move fast and accept breaking changes to models, data contracts, APIs, file formats, and other
revisions that are not deployed or in active use. Remove obsolete revisions instead of adding
compatibility layers or migrations. The user will explicitly state when compatibility or
preservation requirements begin.

## Git

Use trunk-based development.

* Work directly on `main`.
* Do not create branches unless explicitly requested.
* Keep commits focused.
* Do not modify or discard unrelated changes.

### Integrate worktree commits

When you finish work in a secondary worktree, integrate its completed commits into the main
worktree:

1. Commit the work on the secondary worktree's detached `HEAD`.
2. Use `git worktree list` to find the worktree that has `main` checked out.
3. Inspect the main worktree status and the paths changed by the incoming commits. Confirm that no
   other Git operation is in progress. Tracked and untracked changes may remain when their paths do
   not overlap with the incoming commits and the integration cannot overwrite, move, or otherwise
   affect them.
4. Run `git -C <main-worktree-path> cherry-pick <commit>` for each completed commit, in order.
5. If a cherry-pick conflicts, inspect the base, current, and incoming versions. Resolve the
   conflict when the intended combined behavior is clear. Preserve valid changes from both sides.
   For example, keep new logging around updated logic instead of choosing one side wholesale.
6. Run checks that cover the resolved paths and combined behavior. Continue the cherry-pick after
   the checks pass.
7. Confirm that `main` contains the commits and that all pre-existing tracked and untracked changes
   remain intact.

Do not use push and pull to move commits between local worktrees. Do not update the `main` ref
directly. Only one agent can run a Git integration operation in the main worktree at a time. Work
by another agent does not by itself block integration. Proceed when its changes are unrelated or
when a conflict has a small, clear resolution. Before integration, record the existing worktree
status and compare all changed paths with every path changed by the incoming commits. Do not
modify, add, move, stage, or discard unrelated worktree changes.

Stop and report the problem only when safe integration is unclear. Examples include overlapping
uncommitted changes, ambiguous differences in intended behavior, incompatible API or data model
changes, large rewrites of the same code, conflicts in generated or binary files, failing checks
whose correct fix is unclear, or an in-progress Git operation owned by another agent. If a
cherry-pick reaches such a conflict, preserve the evidence and describe the competing changes and
the decision that needs human input.

### Worktree naming

Codex-managed worktree directories are created before the agent reads this file. `AGENTS.md`
cannot rename that directory. When you create or name a worktree yourself, use a short,
task-based name in lower-case kebab case, such as `mapping-corner-diagnostics` or
`proposal-status-fix`. If the task uses a branch, use the same task-based wording after the
`codex/` prefix. Do not use the repository directory name as a task identifier.

## Planning workflow

Use the [epic board](docs/plans/README.md) for project plans. Each numbered Markdown file is one
epic. The file can contain both the specification and its work items.

Structure each epic into small implementation milestones named `M0`, `M1`, and so on. Each
milestone must be small enough for Luna to implement in one phase.

Before starting a milestone, name its observable result, required checks, and commit boundary.
Split oversized milestones before assignment. New storage, transaction, or processor contracts are
implementation work; give them explicit milestones instead of hiding them in migration or cleanup.
If two successive attempts discover new prerequisites or do not reduce the remaining scope,
revise the plan before another attempt. Keep the existing authorization and run limits.

Implement an epic one milestone at a time. When the user says `start epic 1234`, begin with `M0`
of epic 1234. When the user says `next phase`, implement the next incomplete milestone. Do not
require the user to repeat the commit rules, request a status overview, or specify a milestone
number.

After each completed milestone:

* commit the milestone directly to `main`,
* update the epic and the epic board to show the current state,
* give the user a summary, and
* include a current status overview with one line for each milestone.

After the summary, compact the working context before the next milestone.

### Architecture replacements and migrations

Apply these checks when replacing an existing runtime path or migrating retained data. Record the
results in the existing epic or report; no separate process document is required.

* Inspect representative persisted resource kinds and schema versions before implementation.
  List active readers and writers with their replacement and verification check. Keep this list
  current until removal is complete.
* Establish one complete replacement workflow through real APIs/services and persistence before
  converting the remaining paths. Disable the old path in that check. Use deterministic processor
  stubs where practical.
* Rehearse migration in disposable storage before activation. Verify usable content, review
  decisions, exact dependencies, editing, and restart. File copies and counts alone do not prove
  runtime cutover. Freeze and verify the activation snapshot and retain recovery evidence.
* Sequence concurrent epics that change the same API, data contract, or runtime composition.
  Stabilize that boundary before converting its consumers. Separate worktrees do not resolve
  conflicting contract changes; unrelated work can continue.

### Optional persistent milestone execution

Use this mode only when the user says `run epic 1234 for N milestones` or
`continue epic 1234 for N milestones`, where `N` is a positive integer. Both commands start at
the next incomplete milestone. The count includes that milestone. These commands authorize one
agent in the current chat to complete at most `N` milestones in sequence. The existing
`start epic 1234` and `next phase` commands keep their single-milestone behavior.

Keep each milestone as a separate work package. For each milestone:

1. Read the current epic, dependencies, and Git state. Implement only that milestone.
2. Run its required tests and checks. Resolve failures before marking it complete.
3. Update the epic and board. Add or update an `Execution handoff` section in the active epic.
   Record the completed milestone, changes, checks and results, decisions, known limits, next
   milestone, and the requested count with the completed and remaining counts for this run.
   Keep one current handoff and replace stale next steps and counts. Put detailed history in a
   milestone report. Keep continuation facts here rather than only in chat history.
4. Commit the milestone's implementation, plan updates, and handoff together directly to `main`.
   Preserve unrelated changes. Do not combine several milestones into one commit.
5. Give a concise progress summary in commentary. Include the commit ID and one status line for
   each milestone. Then continue to the next milestone without waiting for another prompt.

In this mode, the commentary summary and committed handoff replace the end-of-turn handoff
between milestones. Use native context compaction when available. If no explicit compaction
operation is available, continue in the same chat and let the harness manage the context. Do not
claim that compaction occurred without evidence. After compaction, read the handoff and verify
the actual epic and Git state before continuing. Do not create a supervising agent, a new chat,
or an external continuation loop for this mode.

Stop when the count is reached, the epic is complete, the user asks to stop, or the next milestone
cannot proceed safely. A blocked dependency, required user decision or approval, unresolved check
failure, or ambiguous overlapping Git change ends the run early. Record the reason and remaining
count in the handoff when possible. Do not skip a blocked milestone, expand the epic, or repeat a
commit or action whose outcome is unknown. An interruption does not authorize an automatic restart;
on an explicit resume, reconcile saved progress before doing more work.

At the end of the run, give a final summary with completed milestones, commit IDs, verification,
all milestone statuses, and any blocker. The count limit ends this authorization; another run
requires a new user instruction.

### Optional Luna loop

Invoke this mode with `luna loop epic 1234` to complete the remaining milestones, or
`luna loop epic 1234 for N milestones` to complete at most `N` milestones. Start at the next
incomplete milestone. These commands authorize sequential Luna subagents in the current chat.
They do not change the behavior of `start epic`, `next phase`, or the persistent commands above.

The current chat is the orchestrator, regardless of its model or reasoning level. Use
`gpt-6-luna` at High reasoning for workers. Check the available worker model controls. If that
configuration is unavailable, stop and explain. Do not silently substitute another worker model.

The orchestrator reads this file and the current epic, dependencies, handoff, and Git state.
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

Keep the orchestrator's context small. Do not read worker transcripts, raw logs, ongoing implementation, or
full diffs by default. Do not repeat source exploration or successful checks. Luna owns
implementation and verification. After the initial read, read only relevant epic sections and
handoff changes. Inspect additional source or evidence only for a specific missing field,
contradiction, failure, or acceptance gap. Request bounded excerpts. Record token usage only
when tools expose it. Do not claim measured savings without comparable measurements.

Include these worker rules in every assignment:

- Read applicable `AGENTS.md` files, the assigned milestone, relevant contracts and handoff, and
  the glossary before changing domain terminology. Implement only the assigned milestone.
- Work directly on `main` in the existing checkout. Do not create a branch or worktree. Inspect
  Git state first. Preserve unrelated changes. Stop for ambiguous overlap or an existing Git
  operation. Do not stage unrelated paths.
- Run the milestone's relevant tests and required lint, format, type, generated API, link, and
  browser checks. Resolve failures within scope. Record baseline failures separately; they do
  not waive acceptance criteria. Do not mark incomplete acceptance criteria complete.
- Update the epic and board. Maintain an `Execution handoff` with changes, checks and outcomes,
  decisions, limits, next milestone, and this run's requested, completed, and remaining counts.
  Replace stale handoff facts; keep detailed history and evidence in a milestone report.
- Commit implementation, documentation, and plan updates together as one focused milestone
  commit on `main`. For the final milestone, verify closure criteria, move the epic to the correct
  folder, and repair links. Use `INCOMPLETE` for ordinary unfinished work. Use `BLOCKED` only when
  a concrete dependency, failed check, or unsafe overlap prevents further work. Return only this
  receipt, at most 180 words:

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

Use the persistent mode's handoff, compaction, interruption, and stop rules. In this mode, the
current chat orchestrates the authorized workers; do not create another supervisor, chat, harness,
or external continuation loop. After compaction, reconcile the handoff and actual Git state.
Stop at the run limit, epic completion, a user stop request, or a blocker. Do not repeat an action
with an unknown outcome. End with completed milestones, commits, verification, all milestone
statuses, remaining work, and any blocker. Another run requires a new user instruction.

### Epic maintenance

When you add or edit an epic:

* use the next unused four-digit epic number for a new file,
* use only the statuses defined on the epic board,
* store the file in the folder that matches its `Status` field,
* record prerequisites in a separate `Depends on` field,
* use `Blocked` when an unmet dependency prevents work,
* update the board entry when the epic title, status, dependency, outcome, or closure changes.

When an epic changes status, update its `Status` field and move the file to the matching folder in
the same change. A closed epic must have a `Closure reason`. Keep all links to and from the moved
file valid. Check local Markdown links after adding, moving, or renaming an epic.

Treat closed epic files as immutable historical records. Do not update them to match current
terminology, architecture, or planning policy. Change a closed epic only when:

* the user explicitly requests a correction to that closed epic,
* secrets, personal data, or legally restricted content must be removed, or
* a strictly mechanical link repair is required after an authorized file move or rename.

Keep each exception as small as possible. Do not reopen or rewrite the plan through an exception.
Record new work and changed decisions in an active epic or a new epic.

## Language

Use [ASD-STE100](https://github.com/danyuchn/asd-ste100-skill) principles for documentation and technical prose.

Use simple English, short sentences, active voice, and consistent terminology.

Use the canonical domain terms in the [project glossary](docs/glossary.md). Read the glossary before
you add or change domain terminology. Do not use a glossary term with a different meaning. Define a
new term in the glossary before you use it when its meaning could overlap with an existing term.

## Local development

Prefer fast, reproducible development on a MacBook.

Do not require cloud infrastructure, phones, or other real hardware for the normal development loop when a practical local substitute exists.

Prefer fixtures, recorded inputs, mocks, simulators, and local implementations where appropriate.

## Tooling

Use `mise` to declare the project's development toolchain in `mise.toml`.

* Keep `mise.toml` in git.
* Add required runtimes and development tools to it where practical.
* Respect the versions declared there.
* Run `mise install` after setup changes.
* Use the normal tooling of each language for dependencies, tests, builds, and formatting.

Do not add `mise` tasks merely to wrap existing project commands.

## Verification

Before considering a change complete:

* run the relevant automated tests,
* run applicable linting, formatting, type, or static checks,
* verify that the change is reproducible locally,
* add a regression test for a fixed bug when practical.

Match evidence to the completion claim. Mocked browser APIs verify UI behavior. For changes across
the UI and persistence, include one real-backend workflow with disposable persisted data; processor
stubs are allowed. Verify durable effects and restart when those behaviors change. For coordinated
writes or concurrency changes, test concurrent readers/writers separately from crash recovery.

Record check results against the relevant code revision and data snapshot. Repeat affected checks
after changes, then run the combined completion checks. Do not repeat successful broad audits
without a new change, failure, or unresolved concern. Give each remaining baseline failure a named
owner or follow-up and evidence for its origin; it does not waive an acceptance criterion.
