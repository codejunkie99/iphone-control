"""iphonectl: the bounded CLI for Grok Bot's approved Mac commands.

Agent commands (controller "grok-bot"); each prints one JSON object:
  iphonectl status
  iphonectl observe [--inline] [--text]   (--text: screen text with pixel boxes, read on this Mac)
  iphonectl scroll --session S --observation O --request R --direction up|down [--distance short|medium]
  iphonectl tap  --session S --observation O --request R --x PX --y PX   (pixels in the latest screenshot)
  iphonectl type --session S --observation O --request R --text TEXT
  iphonectl key  --session S --observation O --request R --name home|app_switcher|spotlight|return|...
  iphonectl batch --session S --observation O --request R --steps JSON [--text]
      JSON: [{"action": "key", "key": "spotlight"}, {"action": "type", "text": "Spotify"},
             {"action": "tap_text", "text": "Spotify"}, {"action": "tap", "x": 10, "y": 20, "wait": 1}]
  iphonectl release [--session S]

Owner commands (not for agents):
  iphonectl doctor      read-only setup and compatibility check

Exit codes: 0 done, 2 refused or failed (see "code"), 3 engine not running, 64 usage.
The CLI accepts no other commands and runs nothing else.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

from .privacy import apply_telemetry_opt_out

apply_telemetry_opt_out()

from . import client  # noqa: E402
from .backend import KEYS  # noqa: E402

CONTROLLER = "grok-bot"


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "code": "usage", "message": message}))
        sys.exit(64)


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="iphonectl", description="iPhone control (status, observe, scroll, tap, type, key, batch, release).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    o = sub.add_parser("observe")
    o.add_argument("--inline", action="store_true", help="include the PNG as base64 in the JSON")
    o.add_argument("--text", action="store_true", help="include screen text with pixel boxes (OCR on this Mac)")
    b = sub.add_parser("batch")
    b.add_argument("--session", required=True)
    b.add_argument("--observation", required=True)
    b.add_argument("--request", required=True)
    b.add_argument("--steps", required=True, help="JSON list of steps")
    b.add_argument("--text", action="store_true", help="return the final screen's text")
    s = sub.add_parser("scroll")
    s.add_argument("--session", required=True)
    s.add_argument("--observation", required=True)
    s.add_argument("--request", required=True)
    s.add_argument("--direction", required=True, choices=["up", "down"])
    s.add_argument("--distance", default="short", choices=["short", "medium"])
    for name in ("tap", "type", "key"):
        c = sub.add_parser(name)
        c.add_argument("--session", required=True)
        c.add_argument("--observation", required=True)
        c.add_argument("--request", required=True)
        if name == "tap":
            c.add_argument("--x", required=True, type=float, help="pixels in the latest screenshot")
            c.add_argument("--y", required=True, type=float)
        elif name == "type":
            c.add_argument("--text", required=True)
        else:
            c.add_argument("--name", required=True, choices=list(KEYS))
    r = sub.add_parser("release")
    r.add_argument("--session")
    sub.add_parser("doctor")
    return p


def main(argv=None, socket_path=None) -> int:
    a = parser().parse_args(argv)
    if a.cmd == "doctor":
        from . import doctor
        return doctor.main()
    args = {}
    if a.cmd == "scroll":
        args = {"session_id": a.session, "observation_id": a.observation, "request_id": a.request,
                "direction": a.direction, "distance": a.distance}
    elif a.cmd in ("tap", "type", "key"):
        args = {"session_id": a.session, "observation_id": a.observation, "request_id": a.request}
        if a.cmd == "tap":
            args.update(x=a.x, y=a.y)
        elif a.cmd == "type":
            args["text"] = a.text
        else:
            args["key"] = a.name
    elif a.cmd == "observe" and a.text:
        args = {"text": True}
    elif a.cmd == "batch":
        try:
            steps = json.loads(a.steps)
        except ValueError:
            print(json.dumps({"ok": False, "code": "usage", "message": "--steps must be JSON"}))
            return 64
        args = {"session_id": a.session, "observation_id": a.observation, "request_id": a.request,
                "steps": steps, "text": a.text}
    elif a.cmd == "release" and a.session:
        args = {"session_id": a.session}
    try:
        result = client.call(a.cmd, CONTROLLER, path=socket_path, **args)
    except client.EngineNotRunning as e:
        print(json.dumps({"ok": False, "code": "engine_not_running", "message": str(e)}))
        return 3
    if a.cmd == "observe" and getattr(a, "inline", False) and result.get("image_path"):
        try:
            with open(result["image_path"], "rb") as f:
                result["image_png_base64"] = base64.b64encode(f.read()).decode()
        except OSError:
            pass
    print(json.dumps(result, indent=1))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
