"""The persistent process: engine + local socket + menu-bar UI.

    iphone-control-app              real phone (macOS, PyObjC), with the menu bar
    iphone-control-app --simulate   SIMULATED backend, for trying the flow without a phone

The menu bar shows connection status, the active controller, a pending
approval (Approve / Deny) and a Stop button. Stop is always enabled and acts
at once: it cancels pending work, ends the session and keeps control stopped
until you choose Resume. The engine never reconnects or resumes by itself.
"""
from __future__ import annotations

import argparse
import signal
import sys

from .privacy import apply_telemetry_opt_out

apply_telemetry_opt_out()

from . import paths  # noqa: E402
from .engine import Engine, Policy  # noqa: E402
from .identity import SimulatedIdentity, make_provider  # noqa: E402
from .privacy import EventLog  # noqa: E402
from .server import SocketServer  # noqa: E402


def build(simulate: bool, unattended: bool = False) -> Engine:
    if simulate:
        from .fake_backend import SimulatedBackend
        backend, identity = SimulatedBackend(), SimulatedIdentity()
    else:
        from .macos_backend import MacBackend
        backend, identity = MacBackend(), make_provider("owner" if unattended else "none")
    return Engine(backend, identity, paths.shots_dir(), policy=Policy(unattended=unattended, settle_step=0.15 if unattended else 0.25),
                  log=EventLog(paths.log_path()))


def run_menu_bar(engine: Engine, server: SocketServer, simulate: bool) -> None:
    import AppKit
    import objc
    from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

    class Controller(NSObject):
        def init(self):
            self = objc.super(Controller, self).init()
            self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            self.approval_id = None
            self.last_pending = None
            self.refresh_(None)
            timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(0.5, self, "refresh:", None, True)
            NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
            return self

        @objc.python_method  # helper, not an Objective-C selector (PyObjC rejects it otherwise)
        def _add(self, menu, title, action=None, enabled=True):
            it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            it.setTarget_(self)
            it.setEnabled_(enabled and action is not None)
            menu.addItem_(it)
            return it

        def refresh_(self, _timer):
            st = engine.owner_snapshot()
            conn = st["connection"]
            pending = st["pending_approval"]
            halted = st["halted"]
            sim = " (SIMULATED)" if simulate else ""
            if halted:
                title = "iPhone ■ stopped"
            elif pending:
                title = "iPhone ⚠ approve?"
            elif st["active_controller"]:
                title = f"iPhone ● {st['active_controller']}"
            else:
                title = "iPhone ○"
            self.item.button().setTitle_(title + sim)
            if pending and pending["approval_id"] != self.last_pending:
                AppKit.NSBeep()
            self.last_pending = pending["approval_id"] if pending else None
            self.approval_id = self.last_pending

            menu = AppKit.NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            window = "phone window on screen" if conn["window_present"] else "no phone window"
            self._add(menu, f"Connection: {window}{sim}")
            ident = st["device"]
            self._add(menu, "Device identity: " + ("verified" if ident["identity_verified"] else "NOT verified (scroll blocked)"))
            self._add(menu, f"Active controller: {st['active_controller'] or 'none'}")
            if pending:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
                self._add(menu, "Pending: " + pending["summary"])
                self._add(menu, "Approve", "approve:")
                self._add(menu, "Deny", "deny:")
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            self._add(menu, "Stop now", "stop:")
            if halted:
                self._add(menu, f"Stopped: {halted}")
                self._add(menu, "Resume control", "resume:")
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            self._add(menu, "Quit iPhone Control", "quit:")
            self.item.setMenu_(menu)

        def approve_(self, _s):
            if self.approval_id:
                engine.approve(self.approval_id)
            self.refresh_(None)

        def deny_(self, _s):
            if self.approval_id:
                engine.deny(self.approval_id)
            self.refresh_(None)

        def stop_(self, _s):
            engine.stop("owner_stop")
            self.refresh_(None)

        def resume_(self, _s):
            engine.resume()
            self.refresh_(None)

        def quit_(self, _s):
            engine.stop("app_quit")
            server.close()
            AppKit.NSApp.terminate_(None)

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # menu bar only, no Dock icon
    controller = Controller.alloc().init()  # noqa: F841 (kept alive by the run loop)
    app.run()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="iphone-control-app")
    p.add_argument("--simulate", action="store_true", help="SIMULATED backend; touches no phone")
    p.add_argument("--headless", action="store_true", help="no menu bar (approvals impossible; for diagnostics)")
    p.add_argument("--unattended", action="store_true",
                   help="owner opt-in: no approval clicks and owner-asserted device identity; Stop still works")
    a = p.parse_args(argv)
    engine = build(a.simulate, a.unattended)
    server = SocketServer(engine, paths.socket_path())
    server.start()

    def shutdown(*_):
        engine.stop("app_quit")
        server.close()
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"iPhone Control engine on {paths.socket_path()}" + (" (SIMULATED)" if a.simulate else "")
          + (" (UNATTENDED: no approvals; Stop in the menu bar still works)" if a.unattended else ""), flush=True)
    if a.headless or sys.platform != "darwin":
        signal.pause()
        return 0
    run_menu_bar(engine, server, a.simulate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
