"""The engine's local socket: one JSON request per line, one JSON reply per line.

- AF_UNIX only. No TCP listener, no relay.
- The socket's directory is 0700 and the socket is 0600.
- Each connection's peer UID must equal this process's UID (LOCAL_PEERCRED on
  macOS, SO_PEERCRED on Linux).
- Only agent operations are reachable: status, observe, scroll, tap, type, key, batch, release.
  Approve, deny, stop and resume exist only in-process for the menu-bar app.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading

from .engine import Engine, EngineError

AGENT_OPS = ("status", "observe", "scroll", "tap", "type", "key", "batch", "release")
MAX_REQUEST = 32768


def peer_uid(conn: socket.socket) -> int:
    if sys.platform == "darwin":
        SOL_LOCAL, LOCAL_PEERCRED = 0, 0x001
        raw = conn.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, struct.calcsize("IiH16I") + 8)
        _version, uid = struct.unpack_from("Ii", raw)
        return uid
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def dispatch(engine: Engine, req: dict) -> dict:
    op = req.get("op")
    if op not in AGENT_OPS:
        return {"ok": False, "code": "unknown_operation", "message": f"operation must be one of {', '.join(AGENT_OPS)}"}
    controller = req.get("controller")
    try:
        if op == "status":
            return engine.status(controller)
        if op == "observe":
            return engine.observe(controller, bool(req.get("text")))
        if op == "scroll":
            return engine.scroll(controller, str(req.get("session_id") or ""), str(req.get("observation_id") or ""),
                                 str(req.get("request_id") or ""), str(req.get("direction") or ""),
                                 str(req.get("distance") or "short"))
        if op == "batch":
            return engine.batch(controller, str(req.get("session_id") or ""), str(req.get("observation_id") or ""),
                                str(req.get("request_id") or ""), req.get("steps"), bool(req.get("text")))
        if op in ("tap", "type", "key"):
            return engine.act(controller, str(req.get("session_id") or ""), str(req.get("observation_id") or ""),
                              str(req.get("request_id") or ""), op, x=req.get("x"), y=req.get("y"),
                              text=req.get("text"), key=req.get("key"))
        return engine.release(controller, req.get("session_id"))
    except EngineError as e:
        return e.as_dict()
    except Exception as e:  # never leak details of internal errors (they may hold paths or content)
        return {"ok": False, "code": "internal_error", "message": f"internal error ({type(e).__name__}); nothing was retried"}


class SocketServer:
    def __init__(self, engine: Engine, path: str):
        self.engine = engine
        self.path = path
        self.sock = None
        self.closed = threading.Event()

    def start(self) -> None:
        if os.path.exists(self.path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(self.path)
                probe.close()
                raise RuntimeError("Another iPhone Control engine is already running.")
            except (ConnectionRefusedError, FileNotFoundError):
                os.unlink(self.path)  # stale socket from a crashed run
            finally:
                probe.close()
        os.chmod(os.path.dirname(self.path), 0o700)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(self.path)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        s.listen(8)
        self.sock = s
        threading.Thread(target=self._accept, daemon=True, name="engine-socket").start()

    def _accept(self) -> None:
        while not self.closed.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            try:
                if peer_uid(conn) != os.getuid():
                    conn.sendall(b'{"ok": false, "code": "forbidden", "message": "wrong user"}\n')
                    return
            except OSError:
                return
            f = conn.makefile("rb")
            line = f.readline(MAX_REQUEST + 1)
            if not line or len(line) > MAX_REQUEST:
                return
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError
            except ValueError:
                reply = {"ok": False, "code": "bad_request", "message": "one JSON object per line"}
            else:
                reply = dispatch(self.engine, req)
            try:
                conn.sendall(json.dumps(reply).encode() + b"\n")
            except OSError:
                # The client left (cancelled). The engine already finished or rejected the request.
                pass

    def close(self) -> None:
        self.closed.set()
        if self.sock:
            self.sock.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass
