---
name: implement-epic
description: Implement or resume one already-specified DokoDetector epic through verified completion. Use when the user asks to implement, continue, or complete a numbered epic. Do not use for plan drafting or review; the epic must already be Ready or In Progress.
---

# Implement Epic

Implement the selected epic one milestone at a time. Keep the plan, board, code, tests, and commits
synchronized.

Plan review is outside this skill. Treat a `Ready` or `In Progress` epic as authoritative. Do not
reassess its outcome, dependencies, milestone design, or acceptance criteria unless implementation
finds a direct contradiction that prevents work. Use a separate plan-review task to change those
decisions.

## Execution model

Use one agent for the full workflow. Do not create subagents or switch models. The user chooses the
model and reasoning level before invoking the skill.

There are two execution modes:

- In an ordinary task, run the loop below through completion.
- In an unattended runner checkpoint, perform exactly one milestone or closure action and return
  the runner's required structured result. The runner starts the next turn after compaction.

The user can run the unattended mode from the repository root:

```sh
mise exec -- ./.agents/skills/implement-epic/scripts/run_epic.py run 0021
```

The runner uses `gpt-5.6-luna` with medium reasoning by default. It resumes one Codex thread and
calls app-server compaction after each successful milestone commit. Use `--resume THREAD_ID` after
an interruption. It respects the user's configured sandbox and approval policy. The script also
exposes the missing CLI primitive as `compact THREAD_ID`.

Do not invoke the runner recursively from an active Codex implementation task unless the user
explicitly asks you to launch it.

Run this loop until the epic closes or needs a human:

```text
while not done:
    derive the next action from the epic status and recorded progress
    start the epic, implement one milestone, or close the epic
    verify the work
    update the epic
    commit the owned paths
```

Route by committed epic state:

| State | Next action |
| --- | --- |
| `Ready` | Start the epic. |
| `In Progress` | Implement the earliest milestone not recorded complete. |
| `In Progress` with all milestones complete | Close the epic. |
| `Closed` | Finish without changes. |
| `Backlog`, `To Specify`, or `Blocked` | Use the human handoff. |

The root selects the next milestone only from recorded epic progress. It does not inspect code to
skip ahead. If implementation exists but the epic does not record the milestone as complete,
verify it and commit the missing progress evidence without reimplementing it.

## Repository invariants

Before any change, read `AGENTS.md`, `docs/plans/README.md`, `docs/glossary.md`, and the complete
epic. Follow narrower `AGENTS.md` files for files below their directory.

- Work directly on `main`. Do not create a branch unless the user asks for one.
- Preserve all unrelated changes. Inspect `git status` before every milestone.
- If a file that the milestone must edit already has uncommitted changes, stop and ask the user how
  to handle that overlap. Do not include it in a commit by assumption.
- Exception: when the user explicitly says this resumes an interrupted `implement-epic` run,
  inspect the dirty paths and continue only changes that clearly belong to the current milestone.
  Preserve every other change. Use the human handoff when ownership is mixed or uncertain.
- Stage explicit paths. Never use `git add -A`, `git add .`, or an equivalent broad command.
- Inspect the staged diff before every commit. Commit only files owned by the current action.
- Keep commits focused. Do not amend, squash, rebase, push, or discard user changes unless the user
  asks.
- Treat closed epic files as immutable, except for the narrow exceptions in `AGENTS.md`.
- Use the board's exact statuses, folder mapping, dependency rules, and closure fields.
- Use glossary terms consistently. Define an overlapping new domain term before using it.
- Do not add compatibility code unless the user explicitly requests compatibility.
- Keep milestones sequential unless the epic explicitly makes later work independent of the
  unverified result.
- Never switch to or advance a different epic during the run.

## Start a Ready epic

1. Change its `Status` to `In Progress`.
2. Move the file to `docs/plans/3-in-progress/`.
3. Move its board row to `In Progress` and preserve its outcome and dependencies.
4. Repair links to and from the moved file and check affected local Markdown links.
5. Stage only these plan files, inspect the staged diff, and commit with a message such as
   `docs(epic): start 0021`.

If the epic is already `In Progress`, verify the board and path and do not create an empty start
commit.

## Implement one milestone

Choose the earliest milestone in document order that the epic does not record as complete.

1. Read the milestone and the code it owns. Recheck the worktree for overlapping changes.
2. Determine actual completion from the code, progress evidence, acceptance criteria, and
   definition of done. Do not trust a heading or checkbox alone.
3. Implement only that milestone. Use a lightweight test-first workflow when practical.
4. Run the relevant automated tests plus applicable formatting, lint, type, static, build, or link
   checks. Use `mise` and the versions declared by the repository.
5. Update the epic's existing checklist or progress structure and add concise evidence. Mark only
   work that implementation and verification prove. Record remaining manual evidence explicitly.
6. Review the full diff for scope. Stage explicit owned paths and inspect the staged diff.
7. Commit the implementation and epic progress together. Mention the milestone in the message when
   useful.

If the repository already implements the milestone, verify it and commit only the plan progress
that records the evidence.

After the commit, confirm the new `HEAD` and preserve unrelated worktree changes. In an ordinary
task, continue with the next recorded-incomplete milestone. In a runner checkpoint, return after
this commit.

An agent following the skill in an ordinary task cannot issue the interactive `/compact` command.
The external runner calls `thread/compact/start` and waits for its completion notification. If the
user requests manual milestone checkpoints without the runner, stop after the commit and ask them
to run `/compact`, then resume the same epic. Do not claim that compaction occurred unless the
runtime reports it.

## Human handoff

Continue all safe agent-doable work first. Pause only when the next result needs a person, real
hardware, credentials, unavailable infrastructure, or a user decision. Do not mark that work
complete and do not close the epic.

Leave the epic `In Progress` when a person can perform the next step as part of active delivery.
Use `Blocked` only when a named unmet dependency prevents further work; update the status, folder,
board, links, and `Depends on` field in one focused commit.

Give the user:

1. the last completed milestone and commit;
2. the exact remaining manual actions, in order;
3. required commands, UI path, hardware, or credentials;
4. the expected observation and pass criteria;
5. the artifact or epic section where evidence must be recorded; and
6. a resume prompt such as
   `Use $implement-epic to resume epic 0021 after the required accelerator verification.`

State which checks ran and which did not run. Do not use a generic request such as "please test it."

## Close the epic

Close only when every milestone, acceptance criterion, verification item, and definition-of-done
item is satisfied, and no human work remains.

1. Run the final relevant automated verification and inspect the accumulated milestone evidence.
2. Set `Status` to `Closed` and `Closure reason` to `Complete`.
3. Add a short closure note only when it adds useful evidence or context.
4. Move the epic to `docs/plans/5-closed/`.
5. Move its board row to `Closed`, update the outcome if necessary, and repair affected links.
6. Check affected local Markdown links.
7. Stage only the closure files, inspect the staged diff, and commit with a message such as
   `docs(epic): close 0021`.

Do not choose `Won't Do`, `Superseded`, `Duplicate`, or `Invalid` without an explicit user decision
or clear prior plan authority. If a required check cannot run, use the human handoff instead of
closing.

Finish with the epic outcome, milestone and closure commits, verification results, and remaining
manual steps. A completed epic must say that no manual steps remain.
