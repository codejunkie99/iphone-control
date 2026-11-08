"""The real backend: the iPhone Mirroring window on macOS 15+.

Documented interfaces only:
  - Window: Quartz CGWindowListCopyWindowInfo, matched to the app with bundle ID
    com.apple.ScreenContinuity through AppKit NSRunningApplication.
  - Capture: /usr/sbin/screencapture -l WINDOW_ID (Apple's tool; captures that
    one window). There is no full-screen fallback: if the window capture fails
    or its size doesn't match the window, the capture is deleted and refused.
  - Input: Quartz CGEvent scroll-wheel events with trackpad phase fields
    (kCGScrollWheelEventScrollPhase, IsContinuous, PointDeltaAxis1), posted at
    kCGHIDEventTap. iPhone Mirroring ignores events posted to its PID and bare
    wheel events; it needs HID-level trackpad gestures routed by the cursor
    position. This finding comes from mirroir-mcp (Apache-2.0, see NOTICE).
  - Permissions: CGPreflightScreenCaptureAccess and AXIsProcessTrusted (checks
    only; this module never requests a permission).

Requires PyObjC (pyobjc-framework-Quartz, pyobjc-framework-Cocoa,
pyobjc-framework-ApplicationServices).
"""
from __future__ import annotations

import math
import os
import subprocess
import time
from typing import Optional

from .backend import (MIRRORING_BUNDLE_ID, THUMB_H, THUMB_W, Backend, BackendError, Capture,  # noqa: F401
                      DeliveryUncertain, OwnerTakeover, Probe, WindowRef)

SCREENCAPTURE = "/usr/sbin/screencapture"

# CGEventField numbers from CGEventTypes.h
F_SCROLL_PHASE = 99  # kCGScrollWheelEventScrollPhase
F_MOMENTUM_PHASE = 123  # kCGScrollWheelEventMomentumPhase
F_IS_CONTINUOUS = 88  # kCGScrollWheelEventIsContinuous
F_POINT_DELTA_1 = 96  # kCGScrollWheelEventPointDeltaAxis1 (vertical)
PHASE_MAY_BEGIN, PHASE_BEGAN, PHASE_CHANGED, PHASE_ENDED = 128, 1, 2, 4

def _us_keys() -> dict:
    """Character -> (macOS virtual key code, needs shift) for a US keyboard layout."""
    plain = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
             "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
             "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
             "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
             ".": 47, " ": 49, "`": 50, "\n": 36, "\t": 48}
    shifted = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
               "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
               "~": "`"}
    out = {ch: (code, False) for ch, code in plain.items()}
    out.update({ch.upper(): (code, True) for ch, code in plain.items() if ch.isalpha()})
    out.update({ch: (plain[base], True) for ch, base in shifted.items()})
    return out


_US_KEYS = _us_keys()

GESTURE_STEPS = 12
GESTURE_SECONDS = 0.30
POINTER_TOLERANCE = 4.0  # points the cursor may drift before it counts as owner input


class MacBackend(Backend):
    simulated = False

    def __init__(self):
        try:
            import AppKit
            import Quartz
        except ImportError as e:
            raise BackendError("PyObjC is not installed. Run the iPhone setup steps in docs/SETUP.md.") from e
        self.Q = Quartz
        self.AppKit = AppKit

    # ---------- window ----------

    def _mirroring_pid(self) -> Optional[int]:
        apps = self.AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(MIRRORING_BUNDLE_ID)
        for app in apps or []:
            if not app.isTerminated():
                return int(app.processIdentifier())
        return None

    def _windows(self):
        Q = self.Q
        opts = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
        return Q.CGWindowListCopyWindowInfo(opts, Q.kCGNullWindowID) or []

    def probe(self) -> Probe:
        pid = self._mirroring_pid()
        if pid is None:
            return Probe(False, None, False, None, notes=["iPhone Mirroring is not running"])
        best = None
        front_pid = None
        for w in self._windows():  # front to back
            layer = int(w.get("kCGWindowLayer", 0))
            if layer != 0:
                continue
            owner = int(w.get("kCGWindowOwnerPID", -1))
            if front_pid is None:
                front_pid = owner
            if owner != pid or float(w.get("kCGWindowAlpha", 1.0)) <= 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            bounds = (float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0)))
            if bounds[2] < 150 or bounds[3] < 300:  # not a phone screen (menus, sheets)
                continue
            if best is None or bounds[2] * bounds[3] > best.bounds[2] * best.bounds[3]:
                best = WindowRef(int(w["kCGWindowNumber"]), pid, bounds)
        # Window-list order is live; NSWorkspace.frontmostApplication goes stale in the engine's socket threads.
        frontmost = bool(best and front_pid == pid)
        # No documented signal tells whether the window shows a live phone
        # stream or a "connecting"/"iPhone in use" screen: report unknown.
        return Probe(True, best, frontmost, None)

    # ---------- capture ----------

    def capture(self, window: WindowRef, path: str) -> Capture:
        try:
            os.unlink(path)
        except OSError:
            pass
        old = os.umask(0o077)  # screencapture creates the file: make it 0600
        try:
            r = subprocess.run([SCREENCAPTURE, "-x", "-o", "-t", "png", "-l", str(window.window_id), path],
                               capture_output=True, timeout=10)
        finally:
            os.umask(old)
        if r.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
            self._remove(path)
            raise BackendError("screencapture could not capture the iPhone Mirroring window "
                               "(check Screen Recording permission).")
        os.chmod(path, 0o600)
        width, height, thumb = self._read(path)
        # The file must be this window and nothing larger: 1x-3x its size in points.
        ww, wh = window.bounds[2], window.bounds[3]
        if not (0.9 * ww <= width <= 3.1 * ww and 0.9 * wh <= height <= 3.1 * wh):
            self._remove(path)
            raise BackendError("The capture's size does not match the phone window. It was deleted.")
        blank = max(thumb) - min(thumb) < 8
        return Capture(path, width, height, thumb, blank)

    def _remove(self, path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _read(self, path: str):
        """Image size and a 32 x 64 grey thumbnail, with Core Graphics."""
        Q = self.Q
        url = self.AppKit.NSURL.fileURLWithPath_(path)
        src = Q.CGImageSourceCreateWithURL(url, None)
        img = Q.CGImageSourceCreateImageAtIndex(src, 0, None) if src else None
        if img is None:
            self._remove(path)
            raise BackendError("The capture could not be read.")
        width, height = int(Q.CGImageGetWidth(img)), int(Q.CGImageGetHeight(img))
        ctx = Q.CGBitmapContextCreate(None, THUMB_W, THUMB_H, 8, THUMB_W, Q.CGColorSpaceCreateDeviceGray(),
                                      Q.kCGImageAlphaNone)
        Q.CGContextSetInterpolationQuality(ctx, Q.kCGInterpolationMedium)
        Q.CGContextDrawImage(ctx, Q.CGRectMake(0, 0, THUMB_W, THUMB_H), img)
        small = Q.CGBitmapContextCreateImage(ctx)
        data = bytes(Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(small)))
        row = int(Q.CGImageGetBytesPerRow(small))
        thumb = [data[y * row + x] for y in range(THUMB_H) for x in range(THUMB_W)]
        return width, height, thumb

    # ---------- input ----------

    def _cursor(self):
        loc = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
        return float(loc.x), float(loc.y)

    def _scroll_event(self, dy: int, phase: int, at):
        Q = self.Q
        try:
            ev = Q.CGEventCreateScrollWheelEvent2(None, Q.kCGScrollEventUnitPixel, 2, dy, 0, 0)
        except AttributeError:
            ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 2, dy, 0)
        if ev is None:
            raise BackendError("Could not create a scroll event.")
        Q.CGEventSetLocation(ev, at)
        Q.CGEventSetIntegerValueField(ev, F_IS_CONTINUOUS, 1)
        Q.CGEventSetIntegerValueField(ev, F_POINT_DELTA_1, dy)
        Q.CGEventSetIntegerValueField(ev, F_SCROLL_PHASE, phase)
        Q.CGEventSetIntegerValueField(ev, F_MOMENTUM_PHASE, 0)
        return ev

    def scroll(self, window, direction, distance_pt, should_stop=lambda: False) -> None:
        Q = self.Q
        x, y, w, h = window.bounds
        mid = Q.CGPointMake(x + w / 2, y + h / 2)  # window centre: far from the status bar and Dynamic Island
        home = self._cursor()
        # "down" shows content further down: the content moves up, so the delta is negative.
        sign = -1 if direction == "down" else 1
        step = int(round(distance_pt / GESTURE_STEPS))
        sent = 0
        began = False

        def owner_moved() -> bool:
            cx, cy = self._cursor()
            return math.hypot(cx - mid.x, cy - mid.y) > POINTER_TOLERANCE

        def post(ev):
            nonlocal sent
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            sent += 1

        try:
            Q.CGWarpMouseCursorPosition(mid)  # scroll events go to the window under the cursor
            time.sleep(0.05)
            move = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, mid, Q.kCGMouseButtonLeft)
            post(move)
            time.sleep(0.05)
            post(self._scroll_event(0, PHASE_MAY_BEGIN, mid))  # wake the window's scroll handler
            time.sleep(0.1)
            for i in range(GESTURE_STEPS):
                if should_stop():
                    raise DeliveryUncertain("stopped during the gesture")
                if owner_moved():
                    raise OwnerTakeover()
                post(self._scroll_event(sign * step, PHASE_BEGAN if i == 0 else PHASE_CHANGED, mid))
                began = True
                time.sleep(GESTURE_SECONDS / GESTURE_STEPS)
            post(self._scroll_event(0, PHASE_ENDED, mid))  # finger lift; no momentum: a bounded drag
            began = False
        except (OwnerTakeover, DeliveryUncertain):
            raise
        except Exception as e:
            raise (DeliveryUncertain(f"error after {sent} events") if sent else BackendError(str(e))) from e
        finally:
            if began:  # never leave a touch down on the phone
                try:
                    Q.CGEventPost(Q.kCGHIDEventTap, self._scroll_event(0, PHASE_ENDED, mid))
                except Exception:
                    pass
            try:
                if not owner_moved():
                    Q.CGWarpMouseCursorPosition(Q.CGPointMake(*home))  # give the owner the pointer back
            except Exception:
                pass

    def activate(self) -> None:
        # `open -b` brings the app and its window to this desktop; NSRunningApplication.activate is refused
        # under macOS cooperative activation when the caller is not frontmost.
        subprocess.run(["/usr/bin/open", "-b", MIRRORING_BUNDLE_ID], capture_output=True, timeout=10)
        time.sleep(0.5)

    def _post(self, ev) -> None:
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def _mouse(self, kind, at, src=None):
        Q = self.Q
        ev = Q.CGEventCreateMouseEvent(src, kind, at, Q.kCGMouseButtonLeft)
        if kind in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, 1)
        Q.CGEventSetFlags(ev, 0)
        self._post(ev)

    def tap(self, window, x_pt, y_pt) -> None:
        Q = self.Q
        at = Q.CGPointMake(x_pt, y_pt)
        home = self._cursor()
        src = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
        sent = 0
        try:
            # Hover in like a real pointer: Mirroring forwards clicks only after the pointer has entered the phone.
            for dx in (12, 6, 2, 0):
                p = Q.CGPointMake(x_pt + dx, y_pt + dx)
                Q.CGWarpMouseCursorPosition(p)
                self._mouse(Q.kCGEventMouseMoved, p, src)
                time.sleep(0.03)
            time.sleep(0.05)
            self._mouse(Q.kCGEventLeftMouseDown, at, src)
            sent += 1
            time.sleep(0.08)
            self._mouse(Q.kCGEventLeftMouseUp, at, src)
            time.sleep(0.05)
        except Exception as e:
            raise (DeliveryUncertain(f"error after {sent} events") if sent else BackendError(str(e))) from e
        finally:
            try:
                Q.CGWarpMouseCursorPosition(Q.CGPointMake(*home))
            except Exception:
                pass

    def _keystroke(self, code: int, flags: int = 0, char: Optional[str] = None) -> None:
        Q = self.Q
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, code, down)
            Q.CGEventSetFlags(ev, flags)
            if char is not None:  # receivers that read the character, not the key code, get it too
                Q.CGEventKeyboardSetUnicodeString(ev, len(char.encode("utf-16-le")) // 2, char)
            self._post(ev)
            time.sleep(0.015)

    def type_text(self, window, text) -> None:
        shift = self.Q.kCGEventFlagMaskShift
        sent = 0
        try:
            for ch in text:
                if ch in _US_KEYS:
                    code, shifted = _US_KEYS[ch]
                    self._keystroke(code, shift if shifted else 0, ch)
                else:  # shortcut: non-US-keyboard characters rely on the unicode string, untested on Mirroring
                    self._keystroke(0, 0, ch)
                sent += 1
                time.sleep(0.02)
        except Exception as e:
            raise (DeliveryUncertain(f"error after {sent} characters") if sent else BackendError(str(e))) from e

    def key(self, window, name) -> None:
        cmd = self.Q.kCGEventFlagMaskCommand
        code, flags = {"home": (18, cmd), "app_switcher": (19, cmd), "spotlight": (20, cmd),
                       "return": (36, 0), "delete": (51, 0), "escape": (53, 0), "tab": (48, 0), "space": (49, 0),
                       "left": (123, 0), "right": (124, 0), "down": (125, 0), "up": (126, 0)}[name]
        try:
            self._keystroke(code, flags)
        except Exception as e:
            raise DeliveryUncertain(str(e)) from e

    # ---------- text (Apple Vision OCR, on this Mac) ----------

    def read_text(self, path: str) -> list:
        import Vision
        from Foundation import NSURL
        src = self.Q.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
        img = src and self.Q.CGImageSourceCreateImageAtIndex(src, 0, None)
        if not img:
            raise BackendError("Could not read the screenshot for text recognition.")
        w, h = self.Q.CGImageGetWidth(img), self.Q.CGImageGetHeight(img)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            raise BackendError(f"Text recognition failed ({err}).")
        out = []
        for r in req.results() or []:
            cand = r.topCandidates_(1)
            if not cand:
                continue
            (bx, by), (bw, bh) = r.boundingBox()  # normalized, bottom-left origin
            out.append({"text": str(cand[0].string()), "x": round(bx * w), "y": round((1 - by - bh) * h),
                        "w": round(bw * w), "h": round(bh * h)})
        out.sort(key=lambda e: (e["y"], e["x"]))
        return out

    # ---------- permissions ----------

    def permissions(self) -> dict:
        out = {}
        try:
            out["screen_recording"] = bool(self.Q.CGPreflightScreenCaptureAccess())
        except AttributeError:
            out["screen_recording"] = None
        try:
            from ApplicationServices import AXIsProcessTrusted
            out["accessibility"] = bool(AXIsProcessTrusted())
        except ImportError:
            out["accessibility"] = None
        return out
