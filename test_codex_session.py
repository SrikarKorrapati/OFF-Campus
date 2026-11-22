import asyncio
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tracker.codex_session import run_codex_session


class CodexSessionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        executable = self.root / "codex"
        executable.write_text("#!/usr/bin/env python3\n" + textwrap.dedent("""
            import json, os, sys, time
            from pathlib import Path

            args = sys.argv[1:]
            task = json.load(sys.stdin)
            result = Path(args[args.index("--output-last-message") + 1])
            schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text())
            settings = dict(args[i + 1].split("=", 1) for i, arg in enumerate(args) if arg == "-c")
            instructions = json.loads(settings["developer_instructions"])
            assert settings["mcp_servers.job_tracker.enabled"] == "false"
            assert args[0] == "exec" and args[-1] == "-"
            assert args[args.index("--sandbox") + 1] == "workspace-write"
            assert args[args.index("--enable") + 1] == "multi_agent"
            assert args[args.index("--disable") + 1] == "multi_agent_v2"
            assert "--ephemeral" in args and "--json" in args and schema == {"type": "object"}
            assert "untrusted" not in instructions and task["listing"] not in args
            assert os.environ["BROWSER_USE_ACCESS_EXECUTOR_ID"] == "fixture"

            def emit(kind, **data):
                print(json.dumps({"type": kind, **data}), flush=True)

            emit("thread.started", thread_id="source")
            emit("turn.started")
            spawn = dict(type="collab_tool_call", tool="spawn_agent", sender_thread_id="source",
                         status="completed", receiver_thread_ids=["real-child"])
            emit("item.started", item={**spawn, "receiver_thread_ids": ["started"]})
            emit("item.completed", item={**spawn, "status": "failed", "receiver_thread_ids": ["failed"]})
            emit("item.completed", item={**spawn, "sender_thread_id": "outsider", "receiver_thread_ids": ["nested"]})
            emit("item.completed", item={"type": "agent_message", "text": str(spawn) * 10000})
            emit("item.completed", item=spawn)
            state = {"status": "completed", "message": "actual child final text"}
            if task.get("case") != "early":
                emit("item.completed", item={**spawn, "tool": "wait", "agents_states": {"real-child": state}})
            browser = dict(type="mcp_tool_call", server="cua_repl", tool="js", status="completed", error=None)
            emit("item.completed", item={**browser, "status": "failed", "error": {"message": "failure"}})
            if task.get("case") != "no_browser":
                emit("item.completed", item=browser)
            if task.get("case") == "sleep":
                Path("started").write_text(str(os.getpid()))
                time.sleep(30)
            if task.get("case") == "fail":
                print("private form field", file=sys.stderr)
                sys.exit(2)
            emit("turn.completed")
            if task.get("case") == "malformed":
                result.write_text("[]")
            elif task.get("case") == "oversized":
                result.write_text("x" * (1024 * 1024 + 1))
            else:
                result.write_text(json.dumps({"task": task, "pid": os.getpid(), "cwd": os.getcwd(),
                                              "result_path": str(result)}))
        """), encoding="utf-8")
        executable.chmod(0o700)
        environment = patch.dict(os.environ, {
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "BROWSER_USE_ACCESS_EXECUTOR_ID": "fixture",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def launch(self, listing="untrusted listing", **options):
        return run_codex_session(
            'Read the source.\nReturn its "jobs".', {"listing": listing, **options},
            cwd=self.root, output_schema={"type": "object"},
        )

    async def test_independent_sessions_collect_only_native_successful_spawns(self):
        first, second = await asyncio.gather(self.launch(), self.launch("untrusted other", case="no_browser"))
        self.assertNotEqual(first.report["pid"], second.report["pid"])
        self.assertTrue(first.browser_used)
        self.assertFalse(second.browser_used)
        self.assertEqual(first.report["task"]["listing"], "untrusted listing")
        self.assertEqual(second.report["task"]["listing"], "untrusted other")
        for result in (first, second):
            self.assertEqual(result.children, {"real-child": "actual child final text"})
            self.assertEqual(Path(result.report["cwd"]), self.root)
            self.assertFalse(Path(result.report["result_path"]).parent.exists())

    async def test_rejects_invalid_results_and_keeps_cli_errors_private(self):
        for case, message in (("malformed", "JSON object"), ("oversized", "size limit"),
                              ("fail", "Codex exited with status 2"), ("early", "every spawned child")):
            with self.subTest(case=case), self.assertRaisesRegex((ValueError, RuntimeError), message) as error:
                await self.launch(case=case)
            self.assertNotIn("private form field", str(error.exception))

    async def test_cancelling_reaps_the_process(self):
        async def wait_for_start():
            while not (self.root / "started").exists():
                await asyncio.sleep(0.01)

        session = asyncio.create_task(self.launch(case="sleep"))
        try:
            await asyncio.wait_for(wait_for_start(), timeout=5)
        finally:
            session.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await session
        pid = int((self.root / "started").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
