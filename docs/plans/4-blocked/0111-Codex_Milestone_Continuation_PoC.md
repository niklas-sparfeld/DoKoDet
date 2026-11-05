# Codex milestone continuation proof of concept

## Plan status

- **Status:** Blocked
- **Depends on:** A verified supported connection to the desktop app-owned server and a connected iOS Remote client for the live trial.
- **Outcome:** A local script can continue a selected app chat through a bounded sequence of
  milestones, with compaction and no supervising agent. The trial records whether desktop and
  iOS Remote show and can steer the same work.

## Scope

Replace the manual sequence of finishing one milestone, compacting the chat, and requesting the
next milestone. Keep the existing epic, board, checks, and focused Git commits as the source of
project state. Use one existing app chat and the current checkout. Do not use an agent to watch
another agent. Do not introduce Beads, change the planning policy, or start an unattended epic as
part of the protocol trial.

The installed Codex app-server protocol exposes `turn/completed`, `thread/compact/start`, and
`turn/start`. This does not establish that a separate client can safely attach to the desktop app's
server or control an app chat visible in iOS Remote. M0 must test this before implementation
depends on it. Record the Codex and app versions and the supported connection mechanism. Do not
assume that a separate server sharing local files shares live chat state.

## Milestone status

- **M0:** Blocked — no supported connection to the desktop app-owned server was identified. See the [investigation](../../reports/0111-M0_App_Connection.md).
- **M1:** Not started — implement and test the bounded controller.
- **M2:** Not started — run a controlled end-to-end trial and report the result.

## M0 — Verify the app connection

Inspect the installed protocol and prior local experiments when available. Identify how to connect
to the server that owns a desktop app chat. Use a disposable app chat and trivial prompts. Verify
that the controller can observe completion, request compaction, wait for its completion, and send
a second prompt to the same chat. Check desktop visibility and live iOS Remote visibility and
steering with the user. Record what was actually observed, including failures and token usage.

Acceptance:

- The report identifies the connection, protocol version, event sequence, and exact test steps.
- Desktop and iOS results are separate. Do not claim remote support without an observed iOS test.
- Confirm whether concurrent clients, queued input, interruption, and reconnection are supported.
  If this is unclear, do not use that behavior in the controller.
- If no safe app-owned connection exists, stop the epic with a documented blocker and alternatives.
  Do not substitute a CLI-created chat without demonstrating desktop and iOS visibility.

## M1 — Build the controller

Implement a small local script with a documented invocation. Take an explicit chat ID, epic
number, and maximum milestone count. Require an explicit start. Use the connection verified in M0.
Use events rather than an agent or periodic model calls to wait for completion. Keep the chat's
existing model and settings. Record local progress and concise errors without storing credentials.

Define a small, explicit completion result for each milestone: completed, blocked, needs user, or
epic complete. A completed result identifies the epic, milestone, and commit. Before continuing,
check the actual Git commit and epic state. A successful transport event alone is not evidence that
the milestone passed. Preserve unrelated changes. If state is ambiguous, stop.

Only after a successful milestone, request compaction and wait for its completion before sending
the next prompt. Do not continue if a user message, interruption, approval request, or other work is
pending. Stop on failure, disconnect, timeout, unexpected events, missing or invalid results,
inconsistent Git state, or the configured limit. Do not automatically retry an uncertain send,
compaction, or commit. Provide a clear stop command and a safe restart procedure that does not
repeat an action with an unknown outcome. Do not bypass approval or sandbox settings.

Use a fake protocol server and temporary Git repositories for automated checks. Cover event ordering,
compaction failure, incorrect or missing commit, queued input, interruption, disconnect, duplicate
events, timeout, and restart after an uncertain send. Document local setup and cleanup.

Acceptance: the focused tests pass; no model calls are used by the controller; and the script
stops safely for every tested uncertainty. The script is not enabled automatically.

## M2 — Run a bounded trial

Use a disposable app chat and a temporary fixture repository first. Exercise two small scripted
milestones, including one deliberate failure that must stop continuation. Verify the commit and
compaction sequence and observe the chat in desktop and iOS Remote. Confirm that a user can steer
or stop the controller without a duplicate continuation. Record elapsed time, token usage where
available, and the limits of the comparison with the manual workflow.

Then, only if the user selects an appropriate existing epic, run at most two of its milestones.
Otherwise leave the real-epic trial pending and report the fixture result. Do not claim token savings
without a comparable measurement. Document the exact commands, result, known limitations, and
whether the proof of concept is suitable for further use.

Acceptance: the report separates automated fixture evidence, desktop observation, iOS observation,
and any real-epic result. It records failures and the stop behavior as well as successful steps.
