"""Test helpers. Everything here is SIMULATED: no phone, no macOS API."""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from iphone_control.engine import Engine, Policy  # noqa: E402
from iphone_control.fake_backend import SimulatedBackend  # noqa: E402
from iphone_control.identity import SimulatedIdentity  # noqa: E402
from iphone_control.privacy import EventLog  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def fast_policy(**kw):
    p = Policy(approval_timeout=2.0, settle_timeout=0.0, settle_step=0.0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def make_engine(identity=None, policy=None, clock=None):
    home = tempfile.mkdtemp(prefix="iphonectl-test-")
    os.environ["IPHONE_CONTROL_HOME"] = home
    shots = os.path.join(home, "shots")
    os.makedirs(shots, mode=0o700)
    backend = SimulatedBackend()
    eng = Engine(backend, identity or SimulatedIdentity(), shots, policy=policy or fast_policy(),
                 log=EventLog(os.path.join(home, "engine.log")), clock=clock or time.monotonic,
                 sleep=lambda s: None)
    return eng, backend, home


class Owner:
    """A simulated owner who answers every approval request the same way."""

    def __init__(self, engine, answer="approve", delay=0.0, before=None):
        self.engine, self.answer, self.delay, self.before = engine, answer, delay, before
        self.seen = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            p = self.engine.owner_snapshot()["pending_approval"]
            if p and p["approval_id"] not in [s["approval_id"] for s in self.seen]:
                self.seen.append(p)
                time.sleep(self.delay)
                if self.before:
                    self.before(p)
                if self.answer == "approve":
                    self.engine.approve(p["approval_id"])
                elif self.answer == "deny":
                    self.engine.deny(p["approval_id"])
                elif self.answer == "stop":
                    self.engine.stop("owner_stop")
            time.sleep(0.005)

    def close(self):
        self.stop.set()
        self.thread.join(1)
