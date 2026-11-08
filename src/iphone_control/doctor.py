"""iPhone setup check (`iphonectl doctor`): read-only.

Discovers this Mac and checks Apple's current iPhone Mirroring requirements
(support.apple.com/120421, checked 2026-11-08). It never installs anything,
never opens a permission dialog and never captures the screen. Requirements
that only the owner can confirm are listed as owner checks.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys

MIRRORING_APP = "/System/Applications/iPhone Mirroring.app"

PERMISSIONS_EXPLAINED = """\
Permissions this app needs, and why (grant them yourself in System Settings > Privacy & Security):

  Screen Recording  macOS grants this per app, and it allows capture of ANY window, not only
                    the phone. This app captures only the iPhone Mirroring window
                    (screencapture -l WINDOW) and never the whole desktop.
  Accessibility     macOS grants this per app, and it allows input to ANY app. This app posts
                    one scroll gesture over the phone window, and only after you approve it
                    in the menu bar.

macOS gives both permissions to the app that starts the engine. If you start it from
Terminal, Terminal gets them, and so does everything else you run in Terminal. Remove
them in System Settings when you stop using this app.
"""

OWNER_CHECKS = [
    "iPhone runs iOS 18 or later and has a passcode",
    "iPhone and Mac use the same Apple Account with two-factor authentication",
    "Bluetooth and Wi-Fi are on, on both devices",
    "iPhone is locked and near the Mac (it may be charging / in StandBy)",
    "The Mac is not sharing its internet connection and is not using AirPlay or Sidecar",
    "You are not in the European Union (iPhone Mirroring is unavailable there)",
    "You completed iPhone Mirroring pairing yourself in the iPhone Mirroring app",
]


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def checks() -> dict:
    out = {"platform": sys.platform, "results": [], "owner_checks": OWNER_CHECKS}

    def add(name, ok, detail):
        out["results"].append({"check": name, "ok": ok, "detail": detail})

    if sys.platform != "darwin":
        add("macOS", False, "This is not a Mac. iPhone Mirroring needs macOS.")
        return out
    ver = platform.mac_ver()[0]
    major = int(ver.split(".")[0]) if ver else 0
    add("macOS 15 or later", major >= 15, f"macOS {ver}")
    arm = _run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"]).strip() == "1"
    t2 = False if arm else "T2" in _run(["/usr/sbin/system_profiler", "SPiBridgeDataType"])
    add("Apple silicon or T2 chip", arm or t2, "Apple silicon" if arm else ("Apple T2" if t2 else "neither found"))
    add("iPhone Mirroring app present", os.path.isdir(MIRRORING_APP), MIRRORING_APP)
    add("Python 3.9 or later", sys.version_info >= (3, 9), platform.python_version())
    try:
        import AppKit  # noqa: F401
        import Quartz  # noqa: F401
        pyobjc = True
    except ImportError:
        pyobjc = False
    add("PyObjC installed", pyobjc, "pyobjc-framework-Quartz / Cocoa / ApplicationServices")
    if pyobjc:
        from .macos_backend import MacBackend
        b = MacBackend()
        perms = b.permissions()
        add("Screen Recording permission (this process)", perms.get("screen_recording"),
            "granted" if perms.get("screen_recording") else "not granted: grant it in System Settings")
        add("Accessibility permission (this process)", perms.get("accessibility"),
            "granted" if perms.get("accessibility") else "not granted: grant it in System Settings")
        p = b.probe()
        add("iPhone Mirroring running", p.app_running, "open the iPhone Mirroring app" if not p.app_running else "running")
        add("Phone window on screen", p.window_present,
            f"window {p.window.window_id}, {int(p.window.bounds[2])}x{int(p.window.bounds[3])} pt" if p.window else "none")
    add("Device identity verification", False,
        "No documented mechanism. Mutations (scroll) stay blocked; observe works with owner approval.")
    return out


def main() -> int:
    r = checks()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=1))
    else:
        print("iPhone setup check (read-only)\n")
        for c in r["results"]:
            mark = "ok  " if c["ok"] else ("??  " if c["ok"] is None else "FAIL")
            print(f"  [{mark}] {c['check']}: {c['detail']}")
        print("\nOwner checks (only you can confirm these):")
        for c in r["owner_checks"]:
            print(f"  [ ] {c}")
        print("\n" + PERMISSIONS_EXPLAINED)
    hard = [c for c in r["results"] if c["ok"] is False and c["check"] != "Device identity verification"]
    return 1 if hard else 0
