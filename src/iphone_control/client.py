"""Client for the engine socket, shared by the MCP server and the CLI."""
from __future__ import annotations

import json
import socket
from typing import Optional

from . import paths

# Observe and scroll may wait for the owner (60 s) plus capture and settling.
TIMEOUT = 100.0


class EngineNotRunning(Exception):
    pass


def call(op: str, controller: str, path: Optional[str] = None, timeout: float = TIMEOUT, **args) -> dict:
    path = path or paths.socket_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        s.close()
        raise EngineNotRunning("The iPhone Control app is not running. The owner must start it "
                               "(see docs/SETUP.md).") from e
    with s:
        s.sendall(json.dumps({"op": op, "controller": controller, **args}).encode() + b"\n")
        f = s.makefile("rb")
        try:
            line = f.readline()
        except socket.timeout:
            # The request may still complete inside the engine: report it as uncertain, never retry.
            return {"ok": False, "code": "client_timeout", "message": "No answer in time. The outcome is unknown; "
                    "do not repeat the action. Call status, then observe."}
        if not line:
            return {"ok": False, "code": "no_reply", "message": "The engine closed the connection. Call status."}
        return json.loads(line)
