#!/usr/bin/env python3
"""Run one DokoDetector epic as compacted, single-agent Codex checkpoints."""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Self

RESULT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "milestone_committed",
                "epic_closed",
                "human_handoff",
                "failed",
            ],
        },
        "summary": {"type": "string"},
        "commit": {"type": "string"},
        "next_action": {"type": "string"},
    },
    "required": ["status", "summary", "commit", "next_action"],
    "additionalProperties": False,
}

CHECKPOINT_PROMPT = """\
Use $implement-epic to advance epic {epic}. This is one unattended runner checkpoint.

Use the committed epic state as the source of truth. Do not review or redesign the plan. Do not
spawn subagents. If the epic is Ready, start it first and then continue this same turn. Implement
and commit exactly one earliest recorded-incomplete milestone. If all milestones are already
complete, close the epic and commit the closure instead. Then stop.

Return `milestone_committed` only after the milestone commit succeeds. Return `epic_closed` when
the epic was already closed or after the closure commit succeeds. Return `human_handoff` when the
next required work needs a person or a decision. Return `failed` for any other condition that
prevents a reliable checkpoint. Put the commit hash in `commit`, or an empty string if this turn
made no commit. Keep `next_action` concrete.
"""


class RunnerError(RuntimeError):
    """A deterministic runner operation failed."""


def log(message: str) -> None:
    print(message, flush=True)


def git_head(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerError(
            f"Codex did not return a valid checkpoint result: {error}"
        ) from error
    if not isinstance(value, dict):
        raise RunnerError("Codex checkpoint result is not a JSON object")
    return value


def render_exec_event(event: dict[str, Any], raw: bool) -> str | None:
    if raw:
        return json.dumps(event, separators=(",", ":"))

    event_type = event.get("type")
    if event_type == "thread.started":
        return f"thread {event.get('thread_id')}"
    if event_type == "turn.started":
        return "turn started"
    if event_type == "turn.completed":
        usage = event.get("usage", {})
        return (
            "turn completed"
            f" (input {usage.get('input_tokens', '?')},"
            f" output {usage.get('output_tokens', '?')})"
        )
    if event_type in {"turn.failed", "error"}:
        return json.dumps(event, ensure_ascii=False)

    item = event.get("item")
    if event_type == "item.started" and isinstance(item, dict):
        item_type = item.get("type")
        if item_type == "command_execution":
            return f"command: {item.get('command', '')}"
        if item_type == "mcp_tool_call":
            return f"tool: {item.get('server', '')}/{item.get('tool', '')}"
    return None


def run_checkpoint(
    *,
    codex: str,
    cwd: Path,
    epic: str,
    model: str,
    reasoning: str,
    sandbox: str | None,
    approve_for_me: bool,
    session_id: str | None,
    schema_path: Path,
    result_path: Path,
    raw_events: bool,
) -> tuple[str, dict[str, Any]]:
    prompt = CHECKPOINT_PROMPT.format(epic=epic)
    common = [
        "--json",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "--output-schema",
        str(schema_path),
        "-o",
        str(result_path),
    ]
    if approve_for_me:
        common.insert(1, "--approve-for-me")
    if session_id is None:
        command = [
            codex,
            "exec",
            "-C",
            str(cwd),
        ]
        if sandbox:
            command.extend(["--sandbox", sandbox])
        command.extend([*common, prompt])
    else:
        command = [codex, "exec", "resume", *common, session_id, prompt]

    result_path.unlink(missing_ok=True)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    discovered_session = session_id
    assert process.stdout is not None
    for line in process.stdout:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log(f"codex: {line.rstrip()}")
            continue
        if event.get("type") == "thread.started":
            discovered_session = event.get("thread_id") or discovered_session
        rendered = render_exec_event(event, raw_events)
        if rendered:
            log(f"codex: {rendered}")

    process.stdout.close()
    return_code = process.wait()
    if return_code != 0:
        raise RunnerError(f"codex exec exited with status {return_code}")
    if not discovered_session:
        raise RunnerError("codex exec did not report a thread id")
    return discovered_session, read_json(result_path)


class AppServer:
    def __init__(self, codex: str, cwd: Path) -> None:
        self.process = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.messages: queue.Queue[dict[str, Any] | Exception | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()
        self.next_id = 1

    def _read_stdout(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (OSError, json.JSONDecodeError) as error:
            self.messages.put(error)
        finally:
            self.messages.put(None)

    def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RunnerError("app-server stdin is unavailable")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def receive(self, deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunnerError("timed out while waiting for app-server")
        try:
            message = self.messages.get(timeout=remaining)
        except queue.Empty as error:
            raise RunnerError("timed out while waiting for app-server") from error
        if message is None:
            raise RunnerError(
                f"app-server exited before completing the request ({self.process.poll()})"
            )
        if isinstance(message, Exception):
            raise RunnerError(f"invalid app-server output: {message}") from message
        return message

    def request(
        self, method: str, params: dict[str, Any], deadline: float
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": request_id, "params": params})
        notifications = []
        while True:
            message = self.receive(deadline)
            if message.get("id") != request_id:
                notifications.append(message)
                continue
            if "error" in message:
                raise RunnerError(f"{method} failed: {json.dumps(message['error'])}")
            result = message.get("result", {})
            return result if isinstance(result, dict) else {}, notifications

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.reader.join(timeout=1)
        if self.process.stdout:
            self.process.stdout.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def is_compaction_complete(message: dict[str, Any], session_id: str) -> bool:
    if message.get("method") != "item/completed":
        return False
    params = message.get("params", {})
    item = params.get("item", {}) if isinstance(params, dict) else {}
    return (
        params.get("threadId") == session_id and item.get("type") == "contextCompaction"
    )


def compact_session(*, codex: str, cwd: Path, session_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with AppServer(codex, cwd) as server:
        server.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "doko_epic_runner",
                    "title": "DokoDetector Epic Runner",
                    "version": "1.0.0",
                }
            },
            deadline,
        )
        server.send({"method": "initialized", "params": {}})
        server.request(
            "thread/resume",
            {"threadId": session_id},
            deadline,
        )
        _, notifications = server.request(
            "thread/compact/start", {"threadId": session_id}, deadline
        )
        if any(
            is_compaction_complete(message, session_id) for message in notifications
        ):
            return
        while True:
            if is_compaction_complete(server.receive(deadline), session_id):
                return


def run_epic(args: argparse.Namespace) -> int:
    cwd = args.cwd.resolve()
    if not (cwd / ".git").exists():
        raise RunnerError(f"not a Git worktree: {cwd}")

    session_id = args.resume
    with tempfile.TemporaryDirectory(prefix="doko-epic-runner-") as temporary:
        temporary_path = Path(temporary)
        schema_path = temporary_path / "checkpoint-schema.json"
        result_path = temporary_path / "checkpoint-result.json"
        schema_path.write_text(json.dumps(RESULT_SCHEMA))

        for checkpoint in range(1, args.max_checkpoints + 1):
            before = git_head(cwd)
            log(f"checkpoint {checkpoint}/{args.max_checkpoints}")
            session_id, result = run_checkpoint(
                codex=args.codex,
                cwd=cwd,
                epic=args.epic,
                model=args.model,
                reasoning=args.reasoning,
                sandbox=args.sandbox,
                approve_for_me=args.approve_for_me,
                session_id=session_id,
                schema_path=schema_path,
                result_path=result_path,
                raw_events=args.json_events,
            )
            after = git_head(cwd)
            log(f"session: {session_id}")
            log(json.dumps(result, indent=2, ensure_ascii=False))

            status = result.get("status")
            if status == "milestone_committed":
                if before == after:
                    raise RunnerError(
                        "agent reported milestone_committed but HEAD did not change"
                    )
                log("compacting thread")
                compact_session(
                    codex=args.codex,
                    cwd=cwd,
                    session_id=session_id,
                    timeout=args.compact_timeout,
                )
                log("compaction completed")
                continue
            if status == "epic_closed":
                log("epic complete")
                return 0
            if status == "human_handoff":
                log(f"human handoff required; resume with --resume {session_id}")
                return 3
            raise RunnerError(f"checkpoint stopped with status {status!r}")

    raise RunnerError(
        f"reached {args.max_checkpoints} checkpoints; resume with --resume {session_id}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a DokoDetector epic one committed milestone per compacted Codex turn."
    )
    parser.add_argument(
        "--codex", default=shutil.which("codex") or "codex", help="Codex CLI executable"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="implement or resume an epic")
    run.add_argument("epic", help="four-digit epic number")
    run.add_argument("--cwd", type=Path, default=Path.cwd(), help="repository root")
    run.add_argument("--model", default="gpt-5.6-luna")
    run.add_argument(
        "--reasoning",
        choices=("low", "medium", "high", "xhigh"),
        default="medium",
    )
    run.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        help="override the configured sandbox for the new thread",
    )
    run.add_argument(
        "--approve-for-me",
        action="store_true",
        help="automatically review eligible approval requests",
    )
    run.add_argument(
        "--resume", metavar="THREAD_ID", help="resume an interrupted runner thread"
    )
    run.add_argument("--max-checkpoints", type=int, default=32)
    run.add_argument("--compact-timeout", type=float, default=600)
    run.add_argument(
        "--json-events", action="store_true", help="print raw codex exec JSONL"
    )

    compact = subparsers.add_parser("compact", help="compact one saved Codex thread")
    compact.add_argument("thread_id")
    compact.add_argument("--cwd", type=Path, default=Path.cwd())
    compact.add_argument("--timeout", type=float, default=600)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "compact":
            compact_session(
                codex=args.codex,
                cwd=args.cwd.resolve(),
                session_id=args.thread_id,
                timeout=args.timeout,
            )
            log("compaction completed")
            return 0
        return run_epic(args)
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except (RunnerError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
