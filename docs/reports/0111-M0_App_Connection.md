# 0111 M0: App connection investigation

Date: 2026-11-05

## Result

Blocked. This investigation did not identify a supported way for a separate controller to attach
to the server that owns the current desktop app chat. It did not prove that no such mechanism
exists. Do not build the controller against an unverified connection. Resume M0 when a supported
connection is available and complete the desktop and iOS tests.

## Local evidence and steps

1. `codex --version` returned `codex-cli 0.166.0`. The desktop app bundle is ChatGPT
   `26.1027.61615`; its bundled Codex binary reports `0.166.0-alpha.5.1`. These are build versions;
   no independent protocol version number was identified.
2. `codex app-server --help`, `codex app-server daemon --help`, and
   `codex app-server proxy --help` describe stdio, Unix socket and WebSocket transports and a
   proxy to a running app-server control socket. `codex app-server daemon version` reported a
   running managed daemon at `~/.codex/app-server-control/app-server-control.sock`, version
   `0.166.0`.
3. `ps -ax -o pid=,command=` showed that managed daemon and a separate desktop-bundled
   `codex ... app-server` process. `lsof -n -p <desktop-server-pid> -a -d 0,1,2 -F nTt` showed
   Unix streams for its standard descriptors. The process command did not expose a listening
   socket. These observations do not establish a supported second-client endpoint.
4. The bundled binary generated experimental TypeScript bindings with
   `codex app-server generate-ts --experimental --out /tmp/codex-0111-protocol`. They contain
   `turn/start`, `turn/completed`, `thread/compact/start`, `thread/compacted`,
   `thread/tokenUsage/updated`, `turn/steer`, and `turn/interrupt`. Their presence does not prove
   event ordering, delivery, or concurrent-client safety for the desktop chat.
5. The [official app-server guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
   describes starting a child server and using its stdio, initialization and turn events. It does
   not establish an attachment mechanism for an already running desktop-owned server.

## Tests not run

No disposable chat or model turn was created. No compaction, second prompt, desktop visibility,
iOS Remote visibility, or steering was observed. No trial tokens were used. Concurrent clients,
queued input, interruption, and reconnection remain unverified. The required event sequence and
compaction completion signal must be measured in the eventual trial; the generated names alone do
not establish their order or sufficiency.

A separate managed daemon or a new stdio server is a possible experiment, but shared files or a
shared thread ID do not prove live desktop and iOS visibility. An app-supported attachment API,
or a documented mechanism that connects the desktop app to a shared server, would permit M0 to
continue. The manual milestone workflow remains available in the meantime. No controller was
implemented or enabled.

## Follow-up: shared-daemon route

A second investigation found a concrete candidate. Inspection of the installed app's
`Contents/Resources/app.asar` found a local connection path gated by
`CODEX_APP_SERVER_USE_LOCAL_DAEMON=1`. It uses `ws://localhost/rpc` over the Unix socket
`~/.codex/app-server-control/app-server-control.sock`. Other conditions include a local host,
no explicit CLI command or path override, no force-CLI flag, and an internal availability check.
This is installed implementation evidence, not a documented public interface or support guarantee.

Two earlier `codex app-server proxy` probes sent newline-delimited JSON and received no
initialization response within eight and five seconds. A direct Unix socket probe then sent an
HTTP WebSocket upgrade for `/rpc`, received `101 Switching Protocols`, and sent masked WebSocket
JSON frames. `initialize` succeeded and returned server version `0.166.0` in its user agent.
`thread/loaded/list` succeeded and returned an empty list. No chat was resumed, created, compacted,
or prompted. The probe connection was closed. No model call was made by these probes.

This proves that a second client can initialize against the running managed daemon. It does not
prove concurrent control of a shared chat: the daemon had no loaded threads during this probe.
The app tool separately listed the current desktop chat as active. Together with the separate
processes, this supports investigating the app's opt-in daemon path as the next experiment.

The app tools expose chat status, waits and follow-up prompts, but no compaction operation. Using
those tools from a supervising agent would also miss the controller's no-supervising-agent goal.

### Next bounded experiment

1. Arrange a desktop restart with no running work that could be interrupted. Start the desktop
   executable with `CODEX_APP_SERVER_USE_LOCAL_DAEMON=1` in its environment. Do not persist the
   flag or change remote-control, sandbox, or approval settings. This requires user coordination:
   other desktop chats were active during the investigation.
2. Verify that the app actually selected the daemon. Check process ownership and the daemon's
   loaded-thread list; the flag alone is insufficient evidence.
3. Create one disposable chat through the desktop UI. Connect the read-only WebSocket probe and
   confirm that its ID is loaded by that same daemon. Then run the M0 trivial-turn, compaction,
   second-turn and user-steering tests against that disposable chat.
4. Observe desktop and iOS Remote separately. Measure token usage and event ordering. Stop on any
   owner/follower restriction, missing event, queued input, disconnect, or unknown outcome.
5. Quit the trial app and reopen normally without the environment flag to restore normal launch.

The shared-daemon route is now a tested transport candidate. M0 remains blocked on the coordinated
app launch and visibility trial. M1 and M2 remain unstarted.
