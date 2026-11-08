"""Private, per-user locations for the socket, screenshots and logs.

Every directory is created with mode 0700 and every file with mode 0600, so
other users on the Mac cannot read screen content or connect to the engine.
The paths are fixed (not taken from $TMPDIR), so an MCP client started with a
minimal environment finds the same socket as the menu-bar app.
"""
from __future__ import annotations

import os
import sys

APP_DIR_NAME = "iPhoneControl"


def base_dir() -> str:
    override = os.environ.get("IPHONE_CONTROL_HOME")  # tests and owner-chosen location
    if override:
        return override
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_DIR_NAME}")
    return os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), APP_DIR_NAME)


def private_dir(*parts: str) -> str:
    path = os.path.join(base_dir(), *parts)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)  # makedirs ignores the mode for directories that already exist
    return path


def socket_path() -> str:
    return os.path.join(private_dir("run"), "engine.sock")


def shots_dir() -> str:
    return private_dir("shots")


def log_path() -> str:
    return os.path.join(private_dir("logs"), "engine.log")


def open_private(path: str, mode: str = "wb"):
    """Open a new file that only this user can read (0600)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode)
