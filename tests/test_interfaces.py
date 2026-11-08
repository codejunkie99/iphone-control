"""Socket, MCP and CLI tests against a SIMULATED engine (no phone involved)."""
import contextlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import unittest

from helpers import Owner, make_engine

from iphone_control import cli, client, mcp_server
from iphone_control.server import SocketServer

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


class WithServer(unittest.TestCase):
    def setUp(self):
        self.eng, self.be, self.home = make_engine()
        self.path = os.path.join(self.home, "run", "engine.sock")
        os.makedirs(os.path.dirname(self.path), mode=0o700)
        self.server = SocketServer(self.eng, self.path)
        self.server.start()
        self.owner = Owner(self.eng)

    def tearDown(self):
        self.owner.close()
        self.server.close()


class TestSocket(WithServer):
    def test_permissions(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode), 0o700)

    def test_owner_operations_not_reachable(self):
        for op in ("approve", "deny", "stop", "resume", "owner_snapshot", "shell"):
            r = client.call(op, "claude-code", path=self.path)
            self.assertEqual(r["code"], "unknown_operation", op)

    def test_bad_json(self):
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.path)
        s.sendall(b"not json\n")
        self.assertEqual(json.loads(s.makefile().readline())["code"], "bad_request")
        s.close()

    def test_second_engine_refused(self):
        with self.assertRaises(RuntimeError):
            SocketServer(self.eng, self.path).start()

    def test_round_trip(self):
        obs = client.call("observe", "grok-bot", path=self.path)
        self.assertTrue(obs["ok"] and obs["simulated"])
        r = client.call("scroll", "grok-bot", path=self.path, session_id=obs["session_id"],
                        observation_id=obs["observation_id"], request_id="q1", direction="down")
        self.assertTrue(r["ok"] and r["screen_changed"])
        busy = client.call("observe", "claude-code", path=self.path)
        self.assertEqual(busy["code"], "controller_busy")

    def test_not_running(self):
        with self.assertRaises(client.EngineNotRunning):
            client.call("status", "grok-bot", path=os.path.join(self.home, "nope.sock"))


class TestMcp(WithServer):
    def rpc(self, method, params=None, mid=1):
        return mcp_server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
                                 socket_path=self.path)

    def test_initialize_and_tools(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "0"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["status", "observe", "scroll", "tap", "type", "key", "batch", "release"])
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_observe_returns_image_and_scroll(self):
        r = self.rpc("tools/call", {"name": "observe", "arguments": {}})["result"]
        self.assertFalse(r["isError"])
        self.assertEqual(r["content"][1]["type"], "image")
        obs = json.loads(r["content"][0]["text"])
        s = self.rpc("tools/call", {"name": "scroll", "arguments": {
            "session_id": obs["session_id"], "observation_id": obs["observation_id"],
            "request_id": "m1", "direction": "down"}})["result"]
        self.assertFalse(s["isError"])
        self.assertTrue(json.loads(s["content"][0]["text"])["simulated"])

    def test_rejects_unknown_tool_and_arguments(self):
        r = self.rpc("tools/call", {"name": "shell", "arguments": {"cmd": "ls"}})["result"]
        self.assertTrue(r["isError"])
        r = self.rpc("tools/call", {"name": "status", "arguments": {"cmd": "ls"}})["result"]
        self.assertTrue(r["isError"])

    def test_official_sdk_client(self):
        """Talk to the real stdio process with the official MCP Python SDK, if installed here."""
        try:
            import anyio
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.skipTest("official MCP SDK not installed")
        env = dict(os.environ, PYTHONPATH=SRC, IPHONE_CONTROL_HOME=self.home)

        async def go():
            params = StdioServerParameters(command=sys.executable, args=["-m", "iphone_control.mcp_server"], env=env)
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    tools = await s.list_tools()
                    st = await s.call_tool("status", {})
                    return [t.name for t in tools.tools], json.loads(st.content[0].text)
        names, st = anyio.run(go)
        self.assertEqual(names, ["status", "observe", "scroll", "tap", "type", "key", "batch", "release"])
        self.assertTrue(st["ok"] and st["simulated"])


class TestCli(WithServer):
    def run_cli(self, argv):
        out = io.StringIO()
        code = None
        with contextlib.redirect_stdout(out):
            try:
                code = cli.main(argv, socket_path=self.path)
            except SystemExit as e:
                code = e.code
        return code, json.loads(out.getvalue())

    def test_flow(self):
        code, st = self.run_cli(["status"])
        self.assertEqual(code, 0)
        code, obs = self.run_cli(["observe", "--inline"])
        self.assertEqual(code, 0)
        self.assertIn("image_png_base64", obs)
        code, r = self.run_cli(["scroll", "--session", obs["session_id"], "--observation", obs["observation_id"],
                                "--request", "c1", "--direction", "down"])
        self.assertEqual(code, 0)
        code, r = self.run_cli(["scroll", "--session", obs["session_id"], "--observation", obs["observation_id"],
                                "--request", "c1", "--direction", "down"])
        self.assertEqual((code, r["code"]), (2, "duplicate_request"))
        code, r = self.run_cli(["release"])
        self.assertEqual((code, r["code"]), (0, "released"))

    def test_usage_errors(self):
        self.assertEqual(self.run_cli(["scroll", "--direction", "left"])[0], 64)
        self.assertEqual(self.run_cli(["exec", "ls"])[0], 64)

    def test_engine_not_running_exit_code(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["status"], socket_path=os.path.join(self.home, "nope.sock"))
        self.assertEqual(code, 3)


class TestApp(unittest.TestCase):
    def test_headless_simulated_process(self):
        """The real app process (headless, SIMULATED) serves the CLI and stops cleanly."""
        _eng, _be, home = make_engine()
        env = dict(os.environ, PYTHONPATH=SRC, IPHONE_CONTROL_HOME=home)
        p = subprocess.Popen([sys.executable, "-m", "iphone_control.app", "--simulate", "--headless"],
                             env=env, stdout=subprocess.PIPE, text=True)
        try:
            self.assertIn("SIMULATED", p.stdout.readline())
            out = subprocess.run([sys.executable, "-m", "iphone_control", "status"], env=env,
                                 capture_output=True, text=True, timeout=20)
            st = json.loads(out.stdout)
            self.assertTrue(st["ok"] and st["simulated"])
        finally:
            p.terminate()
            p.wait(5)
            p.stdout.close()
        self.assertFalse(os.path.exists(os.path.join(home, "run", "engine.sock")))


if __name__ == "__main__":
    unittest.main()
