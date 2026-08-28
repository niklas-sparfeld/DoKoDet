from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_epic.py"
SPEC = importlib.util.spec_from_file_location("run_epic", SCRIPT)
assert SPEC and SPEC.loader
run_epic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_epic)


FAKE_CODEX = r"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.argv[1:3] == ["app-server", "--stdio"]:
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        if method == "initialized":
            continue
        if method == "initialize":
            result = {"userAgent": "fake"}
        elif method == "thread/resume":
            result = {"thread": {"id": request["params"]["threadId"]}}
        elif method == "thread/compact/start":
            result = {}
        else:
            raise SystemExit(f"unexpected method: {method}")
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
        if method == "thread/compact/start":
            print(json.dumps({
                "method": "item/completed",
                "params": {
                    "completedAtMs": 1,
                    "threadId": request["params"]["threadId"],
                    "turnId": "turn-1",
                    "item": {"id": "compact-1", "type": "contextCompaction"},
                },
            }), flush=True)
else:
    output = Path(sys.argv[sys.argv.index("-o") + 1])
    output.write_text(json.dumps({
        "status": "epic_closed",
        "summary": "already closed",
        "commit": "",
        "next_action": "none",
    }))
    print(json.dumps({"type": "thread.started", "thread_id": "thread-1"}), flush=True)
    print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
"""


class EpicRunnerTest(unittest.TestCase):
    def make_fake_codex(self, directory: Path) -> Path:
        executable = directory / "codex"
        executable.write_text(FAKE_CODEX)
        executable.chmod(0o755)
        return executable

    def test_checkpoint_reads_thread_and_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            codex = self.make_fake_codex(directory)
            schema = directory / "schema.json"
            schema.write_text(json.dumps(run_epic.RESULT_SCHEMA))
            result_path = directory / "result.json"

            session, result = run_epic.run_checkpoint(
                codex=str(codex),
                cwd=directory,
                epic="0021",
                model="gpt-5.6-luna",
                reasoning="medium",
                sandbox=None,
                approve_for_me=False,
                session_id=None,
                schema_path=schema,
                result_path=result_path,
                raw_events=False,
            )

            self.assertEqual(session, "thread-1")
            self.assertEqual(result["status"], "epic_closed")

    def test_compact_session_waits_for_completion_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            codex = self.make_fake_codex(directory)

            run_epic.compact_session(
                codex=str(codex),
                cwd=directory,
                session_id="thread-1",
                timeout=5,
            )

    def test_compaction_completion_matches_thread(self) -> None:
        message = {
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "item": {"type": "contextCompaction"},
            },
        }

        self.assertTrue(run_epic.is_compaction_complete(message, "thread-1"))
        self.assertFalse(run_epic.is_compaction_complete(message, "thread-2"))


if __name__ == "__main__":
    unittest.main()
