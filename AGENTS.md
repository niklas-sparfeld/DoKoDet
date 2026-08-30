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

## Planning workflow

Use the [epic board](docs/plans/README.md) for project plans. Each numbered Markdown file is one
epic. The file can contain both the specification and its work items.

Structure each epic into small implementation milestones named `M0`, `M1`, and so on. Each
milestone must be small enough for Luna to implement in one phase.

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
