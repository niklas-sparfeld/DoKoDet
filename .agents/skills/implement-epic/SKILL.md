---
name: implement-epic
description: Review and implement one DokoDetector epic from its current board state through verified completion. Use when the user asks to implement or complete a numbered epic end to end. Do not use for plan drafting, plan review only, or one explicitly named milestone only.
---

# Implement Epic

Review the selected epic against the current repository, then implement it one milestone at a time.
Keep the plan, board, code, tests, and commits synchronized.

## Model roles and context boundaries

Use sequential delegation when the runtime supports model-specific subagents:

1. Use `gpt-5.6-sol` with `high` reasoning for the plan review.
2. Use a fresh `gpt-5.6-luna` agent with `xhigh` reasoning to start the epic.
3. Use a fresh `gpt-5.6-luna` agent with `xhigh` reasoning for each implementation milestone.

Run only one delegate at a time because all delegates share the worktree. Invoking this skill
authorizes this repo-local delegation, but it does not expand the user's requested scope or permit
external changes. Do not silently substitute another model or reasoning level. If the runtime
cannot create the requested delegate, stop before that phase and give the user the exact model,
reasoning level, epic path, and next phase to run in a new task.

Discard each delegate after its phase commit. For every review-to-start, start-to-milestone,
milestone-to-milestone, and milestone-to-closure handoff, give the next agent:

- the phase and milestone ID, when applicable;
- the skill path and current epic path;
- the current `HEAD` and last verification result; and
- all still-applicable user constraints and decisions, or the committed plan section that records
  them.

The repository, epic progress, and commits are the durable handoff. Do not carry a long
implementation narrative. The coordinator must inspect every delegate's commit, verification
result, and post-phase worktree before starting the next delegate.

Tell the user when this skill starts a review, starts a milestone, creates a commit, or pauses for
human work.

## Repository invariants

Before any change, read `AGENTS.md`, `docs/plans/README.md`, `docs/glossary.md`, and the complete
epic. Follow narrower `AGENTS.md` files for files below their directory.

- Work directly on `main`. Do not create a branch unless the user asks for one.
- Preserve all unrelated changes. Inspect `git status` before every phase.
- If a file that the phase must edit already has uncommitted changes, stop and ask the user how to
  handle that overlap. Do not include it in a commit by assumption.
- Stage explicit paths. Never use `git add -A`, `git add .`, or an equivalent broad command.
- Inspect the staged diff before every commit. Commit only files owned by the current phase.
- Keep commits focused. Do not amend, squash, rebase, push, or discard user changes unless the user
  asks.
- Treat closed epic files as immutable, except for the narrow exceptions in `AGENTS.md`.
- Use the board's exact statuses, folder mapping, dependency rules, and closure fields.
- Use glossary terms consistently. Define an overlapping new domain term before using it.
- Do not add compatibility code unless the user explicitly requests compatibility.
- Keep milestones sequential unless the epic explicitly makes later work independent of the
  unverified result.

## Phase 1: Review the epic

The Sol review agent must:

1. Resolve the epic from the user-supplied number or path. Confirm that the board entry, epic path,
   and `Status` field agree.
2. Inspect the implementation, tests, contracts, reports, relevant active epics, dependencies, and
   recent history that can change the plan's assumptions.
3. Check that the outcome is still useful, dependencies are correct, milestones are small and in a
   valid order, acceptance criteria are testable, and verification distinguishes automated work
   from required human work. Resolve contradictions between acceptance criteria and verification.
   Split an oversized milestone before implementation so each milestone remains a focused,
   verifiable change.
4. Update the active epic to match current reality. Remove obsolete work instead of adding a
   compatibility layer. Record a dated `Reviewed` entry that names the baseline reviewed.
5. Update the board when the epic title, status, dependency, outcome, or closure data changes. Move
   the epic and repair relative links in the same change when its status changes.
6. Check local Markdown links affected by the edit.
7. Stage only the review files, inspect the staged diff, and commit with a focused message such as
   `docs(epic): review 0021 plan`.

The initial review must produce a commit. If the plan needs no substantive correction, update its
dated review record with the current baseline. Do not create an empty commit. On a resume request,
reuse the existing review when no intervening change affects the epic's assumptions. Re-run the Sol
review when relevant external code, plans, dependencies, or user decisions changed. Ignore
unrelated intervening commits. Do not create a baseline-only review commit on every resume.

Do not begin implementation when the review shows an unmet dependency, an unresolved product
decision, or insufficient evidence. Put the epic in the correct board state, commit that review,
and use the human handoff format below.

## Phase 2: Start the epic

The first Luna agent starts implementation only when the reviewed epic is `Ready` or already
`In Progress`.

For a `Ready` epic:

1. Change its `Status` to `In Progress`.
2. Move the file to `docs/plans/3-in-progress/`.
3. Move its board row to `In Progress` and preserve its current outcome and dependencies.
4. Repair links to and from the moved file and check affected local Markdown links.
5. Stage only these plan files, inspect the staged diff, and commit with a message such as
   `docs(epic): start 0021`.

If the epic is already `In Progress`, verify the board and path and do not create an empty start
commit. A `Backlog`, `To Specify`, `Blocked`, or `Closed` epic must not enter the milestone loop
until its state is resolved according to the board policy.

## Phase 3: Implement one milestone per fresh context

Choose the earliest incomplete milestone in document order. Determine completion from the current
code, checked items, progress evidence, acceptance criteria, and definition of done. Do not trust a
heading or checkbox alone.

For each milestone, the fresh Luna agent must:

1. Read the milestone and the code it owns. Recheck the current worktree for overlapping changes.
2. Implement only that milestone. Use a lightweight test-first workflow when practical.
3. Run the relevant automated tests plus applicable formatting, lint, type, static, build, or link
   checks. Use `mise` and the versions declared by the repository.
4. Update the epic's existing checklist or progress structure and add concise progress evidence.
   Do not mechanically convert numbered requirements into checkboxes. Mark only work that the
   implementation and verification actually prove. Record remaining manual evidence explicitly.
5. Review the full diff for scope, then stage explicit owned paths and inspect the staged diff.
6. Commit the implementation and its epic progress in one focused commit. Mention the milestone in
   the message when useful.

If the repository already implements a milestone, verify it and commit the plan progress that
records the evidence. Do not reimplement it merely to create a code diff.

After the commit, the coordinator verifies the new `HEAD`, confirms the worktree still preserves
unrelated changes, records the commands and results, and starts a fresh Luna agent for the next
milestone.

## Human handoff

Continue all safe agent-doable work first. Pause only when the next required result needs a person,
real hardware, credentials, unavailable infrastructure, or a user decision. Do not mark that work
complete and do not close the epic.

Leave the epic `In Progress` when a person can perform the next step as part of active delivery. Use
`Blocked` only when a named unmet dependency prevents further work; update the status, folder,
board, links, and `Depends on` field in one focused commit.

Give the user a self-contained handoff with:

1. the last completed milestone and commit;
2. the exact remaining manual actions, in order;
3. commands, UI path, hardware, or credentials required;
4. the expected observation and pass criteria;
5. the artifact or epic section where the evidence must be recorded; and
6. a resume prompt such as
   `Use $implement-epic to resume epic 0021 after the required accelerator verification.`

State which checks ran and which did not run. Do not use a generic request such as "please test it."

## Phase 4: Close the epic

Close the epic only when every required milestone, acceptance criterion, verification item, and
definition-of-done item is satisfied, and no human work or verification remains.

The final Luna agent must:

1. Run the final relevant automated verification and inspect the accumulated milestone evidence.
2. Set `Status` to `Closed` and `Closure reason` to `Complete`.
3. Add a short closure note only when it adds useful evidence or context.
4. Move the epic to `docs/plans/5-closed/`.
5. Move its board row to `Closed`, update the outcome if necessary, and repair affected links.
6. Check affected local Markdown links.
7. Stage only the closure files, inspect the staged diff, and commit with a message such as
   `docs(epic): close 0021`.

Do not choose `Won't Do`, `Superseded`, `Duplicate`, or `Invalid` without an explicit user decision
or clear prior plan authority. If any required check cannot run, use the human handoff instead of
closing the epic.

Finish with the epic outcome, the review/start/milestone/closure commits, verification results, and
any remaining manual steps. A completed epic must say that no manual steps remain.
