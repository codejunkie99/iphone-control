# Integration, identity, permissions and privacy

## Components

```
Claude Code ──stdio──▶ iphone-control-mcp ─┐
                                             ├─ Unix socket (0600, same user only) ─▶ engine ─▶ macOS ─▶ iPhone Mirroring window
Grok Bot ────exec────▶ iphonectl ───────────┘                                          ▲
                                                               menu bar (in-process): approve / deny / Stop / resume
```

- **Engine** (`engine.py`): the only owner of the session, the observations and the policy. It has no UI code.
- **Host process** (`app.py`, `iphone-control-app`): runs the engine, the socket server and the menu bar. It is the only persistent process.
- **Socket** (`server.py`): `AF_UNIX`, in `~/Library/Application Support/iPhoneControl/run/`. The directory is 0700 and the socket is 0600. The server rejects a peer whose UID is not the owner's UID. It accepts only `status`, `observe`, `scroll`, `tap`, `type`, `key`, `batch`, `release`. Approve, deny, Stop and Resume are not on the socket.
- **MCP server** (`mcp_server.py`): stdio, eight tools, controller `claude-code` (also used by Codex). It has no dependencies. It implements MCP over JSON-RPC 2.0 for protocol versions 2025-06-18, 2025-03-26 and 2024-11-05.
- **CLI** (`cli.py`, `iphonectl`): the same operations, controller `grok-bot`, JSON output. `iphonectl doctor` is the owner's read-only setup check.

There is no TCP listener, no relay, no Tailscale and no hosted service. The CLI does not need Claude Code.

## macOS interfaces used

| Need | Interface | Documented by |
|---|---|---|
| Find the app | `NSRunningApplication` by bundle ID `com.apple.ScreenContinuity` | AppKit |
| Find the window | `CGWindowListCopyWindowInfo` (owner PID, layer, bounds, front-to-back order) | Quartz Window Services |
| Capture one window | `/usr/sbin/screencapture -x -o -l WINDOW_ID` | `man screencapture` |
| Read the capture | `CGImageSource`, `CGBitmapContext` (32 x 64 grey thumbnail) | Core Graphics |
| Scroll | `CGEventCreateScrollWheelEvent2`, scroll phase fields, `CGEventPost(kCGHIDEventTap)`, `CGWarpMouseCursorPosition` | Quartz Event Services |
| Tap | Left mouse down/up `CGEvent` at the mapped window point, `CGEventPost(kCGHIDEventTap)`, cursor restored after | Quartz Event Services |
| Type, keys | One `CGEventKeyboardSetUnicodeString` event per character; Cmd+1 home, Cmd+2 app switcher, Cmd+3 Spotlight | Quartz Event Services |
| Screen text | `VNRecognizeTextRequest` on the captured window, on this Mac | Vision |
| Permission checks | `CGPreflightScreenCaptureAccess`, `AXIsProcessTrusted` | Core Graphics, Accessibility |

Apple publishes no automation interface for iPhone Mirroring itself. The engine uses only generic macOS window and event interfaces, and limits every use to the iPhone Mirroring window:

- It captures by window ID. It never captures the full screen. If the file size does not match the window, the engine deletes the file and refuses.
- It posts input only inside the window, only while iPhone Mirroring is the frontmost app and its window is the front window. With `--unattended` it brings iPhone Mirroring to the front itself first.

### Dependencies evaluated

| Candidate | Decision | Reason |
|---|---|---|
| mirroir-mcp (Apache-2.0) | Not a runtime dependency; knowledge adapted (NOTICE) | More than 30 tools (taps, typing, app launch, skill generation). A daily npm update check. Its own permission model. Not shareable with a CLI under one session and one Stop. Its source documents the scroll-event recipe that iPhone Mirroring accepts. |
| phoneuse (MIT) | Logic adapted (NOTICE) | Screen-change measure, settle-before-verify, stop-until-resume. Its AirPlay and Bluetooth paths do not apply. |
| Official MCP Python SDK | Used only in tests | 8 tools on stdio do not need its dependency tree. The test suite runs the official SDK client against this server. |
| PyObjC | Runtime dependency (macOS only) | Maintained bridge to AppKit and Quartz. No telemetry. |
| Appium / WebDriverAgent | Not used | Needs a developer-signed app on the phone. It controls the phone over USB or Wi-Fi, not through iPhone Mirroring. |

## Device identity (unresolved gate)

A window ID, a PID, a window title or a "connected" state identifies the Mac window, not the phone. No documented interface reports which iPhone an iPhone Mirroring session shows:

- iPhone Mirroring has no scripting dictionary, URL scheme or public framework.
- `xcrun devicectl list devices` lists CoreDevice devices. It does not say which one is mirroring.
- The phone name in the window content is screen content. It is untrusted, and anyone can set a phone's name.

**Result:** `identity.NoDocumentedIdentity` reports "unverified", and the engine blocks every mutation (`tap`, `type`, `key`, `scroll` and `batch` return `identity_unverified` before asking the owner). Starting the engine with `--unattended` is the owner's explicit opt-in: identity becomes owner-asserted, not technically verified. `observe` still works after the owner approves the session. To unblock scroll, add a provider in `identity.py` that uses a documented, tamper-resistant mechanism. Do not add a name match or an owner checkbox.

A second gap: no documented signal tells whether the window shows a live phone stream or a "connecting" or "iPhone in use" screen. `Probe.stream_live` is `None`. `status` reports this as a blocked reason.

## Permissions

| Permission | Why | Scope that macOS actually grants |
|---|---|---|
| Screen Recording | Capture the iPhone Mirroring window | Any window of any app |
| Accessibility | Post the scroll gesture | Input to any app |

macOS grants both to the *responsible* app: the app that started the engine. If you start `iphone-control-app` from Terminal, Terminal and every program started from it get both permissions. The engine only checks permissions (`CGPreflightScreenCaptureAccess`, `AXIsProcessTrusted`). It never requests them and never clicks through a dialog. The owner grants them in System Settings › Privacy & Security.

The MCP server and the CLI need no permission: they only talk to the socket.

## Action policy

`observe`: the controller must be one of `claude-code` or `grok-bot`, and no other controller may hold the session. The phone window must be present. A new session needs owner approval in the menu bar. A blank capture is refused and deleted.

`scroll`, in order:

1. The controller holds the session; `session_id` matches.
2. `request_id` was never used before (a repeat is rejected, never re-run).
3. `observation_id` is the latest observation, unused, and at most 15 s old. The engine marks it used now, whatever the outcome.
4. The window is present and has the same window ID, PID and size as at the observation. A change halts the engine.
5. Device identity is verified (currently impossible: blocked).
6. The owner approves this one scroll (60 s timeout).
7. The engine checks the device again, requires the phone window to be frontmost, captures again, and rejects the request if more than 20 % of the content changed.
8. One gesture (12 steps, 120 or 240 pt, no momentum). Owner pointer movement during the gesture halts the engine (`owner_takeover`). An error after the first event halts it (`uncertain_delivery`). Stop during the gesture halts it. There is never an automatic retry.
9. The engine waits for the screen to settle, observes again and compares. No visible change also halts it (`uncertain_delivery`).

A halt cancels a pending approval, ends the session, deletes the session's screenshots, and refuses every operation except `status` and `release` until the owner selects **Resume control**. After Resume, a new session needs a new approval.

`tap`, `type`, `key` and `batch` follow the same rules as `scroll`. With `--unattended`, rules 5 and 6 are skipped: no identity check and no approval. Stop and every other rule still apply.

Taps and typing can do anything a person can do on the unlocked phone, including sending messages. The engine does not classify screens, so the agent's own rules (and attended mode) are the guard against purchases, deletion, and account or security changes.

## Privacy

- **Telemetry:** none in this code or in PyObjC. The process sets `DO_NOT_TRACK=1` and similar opt-out variables before it imports anything else.
- **Capture scope:** the iPhone Mirroring window only. There is no full-desktop fallback.
- **Files:** screenshots are in `~/Library/Application Support/iPhoneControl/shots` (0700). Each file is 0600. A session keeps at most 6. Release, Stop, a halt, idle expiry (5 min) or quitting the app deletes them.
- **Logs:** `logs/engine.log` (0600) records event names, IDs, controller names and result codes only. A field allow-list removes paths, image data and screen text.
- **Screen text:** the engine reads no text. Every observation tells the agent that screen content is untrusted. Approval summaries come from the engine, never from the screen.
- **Credentials:** the engine never collects, stores or types a passcode, and never grants permissions.
