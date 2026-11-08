"""The interface between the engine and the phone window.

The engine never talks to macOS directly. A backend finds the iPhone
Mirroring window, captures only that window, and posts one scroll gesture.
`macos_backend.MacBackend` is the real one; `fake_backend.SimulatedBackend`
is a simulation for tests and is labeled as such in every result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

MIRRORING_BUNDLE_ID = "com.apple.ScreenContinuity"  # the iPhone Mirroring app


@dataclass(frozen=True)
class WindowRef:
    """One iPhone Mirroring window, as the window server describes it."""
    window_id: int
    pid: int
    bounds: Tuple[float, float, float, float]  # x, y, width, height in screen points

    def key(self) -> tuple:
        # Position may change when the owner drags the window; size and identity must not.
        return (self.window_id, self.pid, round(self.bounds[2]), round(self.bounds[3]))


@dataclass
class Probe:
    """The connection state immediately before an operation."""
    app_running: bool
    window: Optional[WindowRef]
    frontmost: bool
    # None: no documented signal says whether the phone stream is live.
    stream_live: Optional[bool]
    simulated: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def window_present(self) -> bool:
        return self.window is not None


@dataclass
class Capture:
    """One screenshot of the phone window only."""
    path: str  # PNG, mode 0600, in the private shots directory
    width: int
    height: int
    fingerprint: List[int]  # coarse grey thumbnail (32 x 64), for change checks only
    blank: bool  # True when the picture has no content (e.g. missing Screen Recording permission)


class BackendError(Exception):
    """The operation did not start. Safe to report; nothing reached the phone."""


class DeliveryUncertain(Exception):
    """An input event may or may not have reached the phone. Never retry."""


class OwnerTakeover(Exception):
    """The owner used the pointer during the gesture."""


class Backend:
    simulated = False

    def probe(self) -> Probe:
        raise NotImplementedError

    def capture(self, window: WindowRef, path: str) -> Capture:
        """Capture exactly this window. Must never fall back to the full screen."""
        raise NotImplementedError

    def scroll(self, window: WindowRef, direction: str, distance_pt: int,
               should_stop: Callable[[], bool] = lambda: False) -> None:
        """Post one bounded scroll gesture over the window. `should_stop` is
        checked between events (the owner's Stop). Raises
        DeliveryUncertain if the events may have been only partly delivered,
        OwnerTakeover if the owner moved the pointer during the gesture."""
        raise NotImplementedError

    def activate(self) -> None:
        """Bring the phone window to the front (unattended mode only)."""
        raise NotImplementedError

    def tap(self, window: WindowRef, x_pt: float, y_pt: float) -> None:
        """One click (a tap on the phone) at screen point x_pt, y_pt inside the window."""
        raise NotImplementedError

    def type_text(self, window: WindowRef, text: str) -> None:
        """Type text into the phone's focused field."""
        raise NotImplementedError

    def key(self, window: WindowRef, name: str) -> None:
        """Press one key from KEYS."""
        raise NotImplementedError

    def read_text(self, path: str) -> list:
        """Text on a screenshot: [{"text", "x", "y", "w", "h"}], pixel box with a top-left origin, top to bottom."""
        return []

    def permissions(self) -> dict:
        return {}


# home / app_switcher / spotlight are iPhone Mirroring's own View-menu shortcuts (Cmd-1/2/3).
KEYS = ("home", "app_switcher", "spotlight", "return", "delete", "escape", "tab", "space",
        "up", "down", "left", "right")


THUMB_W, THUMB_H = 32, 64  # fingerprint size: grey values, row by row


def changed_fraction(a: List[int], b: List[int], top_skip: float = 0.06, threshold: int = 24) -> float:
    """How much of the screen's content changed between two thumbnails, 0..1.

    Adapted from phoneuse (cli.moved_since_look; MIT, Copyright (c) 2026 Aleksey Smolenchuk; see NOTICE):
    measure changed pixels against content ("ink") pixels, not against the whole
    picture, so a mostly plain page still registers a moved list. The status
    bar (top 6 %) is ignored, so the clock and battery don't count as change.
    Different sizes count as fully changed.
    """
    if not a or not b or len(a) != len(b) or len(a) != THUMB_W * THUMB_H:
        return 1.0
    start = int(THUMB_H * top_skip) * THUMB_W
    a, b = a[start:], b[start:]
    med_a, med_b = sorted(a)[len(a) // 2], sorted(b)[len(b) // 2]
    ink = changed = 0
    for x, y in zip(a, b):
        if abs(x - med_a) > threshold or abs(y - med_b) > threshold:
            ink += 1
            if abs(x - y) > threshold:
                changed += 1
    if ink < 20:  # an empty screen: compare everything instead
        return sum(1 for x, y in zip(a, b) if abs(x - y) > threshold) / len(a)
    return changed / ink
