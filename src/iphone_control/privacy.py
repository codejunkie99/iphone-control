"""Privacy defaults, applied before any dependency is imported, and a log that
records event codes only.

No dependency used at runtime (PyObjC, the Python standard library) sends
telemetry. These variables are set anyway, so a dependency added later that
honours the common opt-out conventions stays quiet.
"""
from __future__ import annotations

import os
import time

TELEMETRY_OPT_OUT = {
    "DO_NOT_TRACK": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DISABLE_TELEMETRY": "1",
    "NO_UPDATE_NOTIFIER": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def apply_telemetry_opt_out() -> None:
    for key, value in TELEMETRY_OPT_OUT.items():
        os.environ.setdefault(key, value)


# Only these fields may reach the log. Screen content, image paths, image
# hashes and anything an agent typed are never logged.
_ALLOWED_FIELDS = {"event", "controller", "session", "observation", "request", "approval",
                   "code", "direction", "distance", "reason", "changed"}


class EventLog:
    def __init__(self, path: str | None):
        self.path = path

    def write(self, event: str, **fields) -> None:
        if not self.path:
            return
        safe = {k: v for k, v in fields.items() if k in _ALLOWED_FIELDS and isinstance(v, (str, int, bool, type(None)))}
        line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + event + "".join(f" {k}={v}" for k, v in sorted(safe.items()))
        from .paths import open_private
        exists = os.path.exists(self.path)
        if not exists:
            with open_private(self.path, "w"):
                pass
        with open(self.path, "a") as f:
            f.write(line + "\n")
