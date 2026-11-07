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

* In the main worktree, work directly on `main`.
* In an existing secondary worktree, commit on its detached `HEAD`, then integrate into `main`
  with the procedure below. Do not switch that checkout to `main`.
* Do not create branches unless explicitly requested.
* Keep commits focused.
* Do not modify or discard unrelated changes.

### Integrate worktree commits

After each work commit in a secondary worktree, integrate it into the main worktree, then merge
the latest `main` back into the secondary worktree before starting more work:

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
8. Inspect the secondary worktree status and confirm that no Git operation is in progress there.
   Compare its uncommitted paths with the paths that the merge will change. Preserve unrelated
   changes and stop if they overlap or safe integration is unclear.
9. Run `git -C <secondary-worktree-path> merge main` to include the latest local `main`. Resolve
   conflicts with the same rules as above and run checks for the combined behavior. Confirm that
   the secondary worktree contains the merged `main` revision and all pre-existing local changes.

This synchronization includes completed parallel work from `main` in the next work package.
A merge commit created only to synchronize `main` does not trigger another integration cycle.

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

Before implementation, read the current epic, dependencies, and Git state. Implement only the
assigned milestone. After each milestone:

* run its required tests and checks; resolve failures before marking it complete,
* update the epic and board to show the current state,
* commit the implementation and plan updates together as one focused milestone commit, following
  the checkout and integration rules above; do not combine milestones in one commit, and
* give the user a summary with the commit ID and one status line for each milestone.

Use native context compaction before the next milestone when available. If no explicit compaction
operation is available, continue in the same chat and let the harness manage the context. Do not
claim that compaction occurred without evidence. After compaction, read the current epic and any
execution handoff, then verify the actual Git state before continuing.

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

### Optional execution modes

`run epic 1234 for N milestones` and `continue epic 1234 for N milestones` authorize the current
agent to complete at most `N` milestones, starting at the next incomplete milestone. `N` must be
a positive integer.

`luna loop epic 1234` authorizes sequential Luna workers for the remaining planned milestones.
`luna loop epic 1234 for N milestones` limits that run to at most `N` milestones. Both start at
the next incomplete milestone. Do not add milestones to extend a run.

Before using either mode, read and follow the [execution workflow](docs/workflows/epic-execution.md).
Stop at the run limit, epic completion, a user stop request, or a blocker. These modes do not change
the single-milestone behavior of `start epic` and `next phase`.

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
