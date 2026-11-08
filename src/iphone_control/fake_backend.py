"""SIMULATED backend for tests and dry runs. It touches no phone and no macOS API.

Every Probe it returns has simulated=True, and the engine copies that flag into
every result, so a simulated run can never be mistaken for a physical-phone run.
"""
from __future__ import annotations

import struct
import zlib
from typing import Callable, List, Optional

from .backend import THUMB_H, THUMB_W, Backend, Capture, DeliveryUncertain, OwnerTakeover, Probe, WindowRef
from .paths import open_private


def _png(width: int, height: int, grey: List[int]) -> bytes:
    """A small greyscale PNG (no dependencies)."""
    raw = b"".join(b"\x00" + bytes(grey[y * width:(y + 1) * width]) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class SimulatedBackend(Backend):
    simulated = True

    def __init__(self):
        self.window: Optional[WindowRef] = WindowRef(4242, 999, (100.0, 100.0, 330.0, 720.0))
        self.app_running = True
        self.frontmost = True
        self.stream_live: Optional[bool] = None  # like the real backend: unknown
        self.offset = 0  # scroll position of the simulated page
        self.blank = False
        self.scroll_effect = True  # False: the scroll "goes nowhere"
        self.fail_scroll: Optional[str] = None  # "uncertain" or "takeover"
        self.scrolls = 0
        self.captures = 0
        self.ambient = 0  # increase to simulate content changing by itself
        self.on_scroll: Optional[Callable[[], None]] = None
        self.inputs: list = []  # taps, typing and keys, in order

    def probe(self) -> Probe:
        return Probe(self.app_running, self.window if self.app_running else None, self.frontmost,
                     self.stream_live, simulated=True, notes=["SIMULATED"])

    def _thumb(self) -> List[int]:
        if self.blank:
            return [0] * (THUMB_W * THUMB_H)
        out = []
        for y in range(THUMB_H):
            row = (y + self.offset + self.ambient) % 8
            for x in range(THUMB_W):
                out.append(230 if row < 4 or x < 3 else 20)  # striped "list" with a margin
        return out

    def capture(self, window: WindowRef, path: str) -> Capture:
        self.captures += 1
        thumb = self._thumb()
        with open_private(path, "wb") as f:
            f.write(_png(THUMB_W, THUMB_H, thumb))
        return Capture(path, THUMB_W, THUMB_H, thumb, blank=self.blank)

    def scroll(self, window, direction, distance_pt, should_stop=lambda: False) -> None:
        if self.on_scroll:
            self.on_scroll()
        self.scrolls += 1
        if should_stop():
            raise DeliveryUncertain("stopped mid-gesture")
        if self.fail_scroll == "uncertain":
            raise DeliveryUncertain("simulated partial delivery")
        if self.fail_scroll == "takeover":
            raise OwnerTakeover()
        if self.scroll_effect:
            self.offset += 3 if direction == "down" else -3

    def activate(self) -> None:
        self.frontmost = True

    def tap(self, window, x_pt, y_pt) -> None:
        self.inputs.append(("tap", round(x_pt), round(y_pt)))
        self.offset += 3  # the simulated screen changes

    def type_text(self, window, text) -> None:
        self.inputs.append(("type", text))
        self.offset += 3

    def key(self, window, name) -> None:
        self.inputs.append(("key", name))
        self.offset += 3

    def permissions(self) -> dict:
        return {"screen_recording": True, "accessibility": True}
