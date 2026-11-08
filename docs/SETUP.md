# iPhone setup

Each owner installs and pairs independently. Do the steps in this order. Steps marked **Owner** are yours alone: no script and no agent does them.

## 1. Check compatibility

Apple's requirements (support.apple.com/120421):

- Mac: macOS Sequoia 15 or later, Apple silicon or Apple T2 chip.
- iPhone: iOS 18 or later, with a passcode.
- The same Apple Account on both, with two-factor authentication.
- Bluetooth and Wi-Fi on. The iPhone is locked and near the Mac.
- The Mac is not sharing its internet connection and is not using AirPlay or Sidecar.
- Not available in the European Union.

## 2. Install (on the Mac)

```bash
cd ~/iphone-control
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e .
```

This installs PyObjC (pyobjc-framework-Quartz, -Cocoa, -ApplicationServices) from PyPI into `.venv` only.

## 3. Run the read-only check

```bash
.venv/bin/iphonectl doctor
```

It reports the Mac, the chip, the iPhone Mirroring app, PyObjC and the permissions. It lists the checks only you can confirm. It also explains the permissions before you grant them.

## 4. Pair iPhone Mirroring (Owner)

Open **iPhone Mirroring** from Applications. Follow Apple's steps on the Mac and on the iPhone, including authentication. Confirm that the phone screen shows in the window. Then lock the iPhone.

## 5. Grant permissions (Owner)

Read the permissions section of `iphonectl doctor` first. Then open System Settings › Privacy & Security and enable these for the app that will start the engine (for example Terminal):

- Screen Recording
- Accessibility

Quit and reopen that app. Run `iphonectl doctor` again.

## 6. Start the engine and menu bar

Try the simulated mode first. It touches no phone and labels everything SIMULATED:

```bash
.venv/bin/iphone-control-app --simulate
```

Quit it from the menu bar (iPhone ○ › Quit). Then start the real engine:

```bash
.venv/bin/iphone-control-app
```

The menu bar shows the connection, device identity, the active controller, a pending approval with Approve and Deny, **Stop now**, and **Resume control** after a stop.

In this default mode every action except `observe` is blocked: no documented interface identifies which iPhone the window shows (see `docs/INTEGRATION.md`). To let the agent act, start it unattended instead. Device identity is then owner-asserted and nothing asks for approval; **Stop now** still works:

```bash
.venv/bin/iphone-control-app --unattended
```

## 7. Connect Claude Code (MCP)

Use the absolute path to the venv:

```bash
claude mcp add --scope user iphone-control -- "$HOME/iphone-control/.venv/bin/iphone-control-mcp"
```

Or put `examples/claude-mcp.json` in your project as `.mcp.json` and edit the path. The tools are `status`, `observe`, `tap`, `type`, `key`, `scroll`, `batch` and `release`.

## 8. Connect Codex (MCP)

```bash
codex mcp add iphone-control -- "$HOME/iphone-control/.venv/bin/iphone-control-mcp"
```

Codex uses the same server, so it also appears as controller `claude-code`. Only one agent holds the session at a time.

## 9. Connect Grok Bot (CLI)

Add only these command forms to Grok Bot's approved Mac commands. Use the absolute path. See `examples/grok-approved-commands.txt`.

```
~/iphone-control/.venv/bin/iphonectl status
~/iphone-control/.venv/bin/iphonectl observe
~/iphone-control/.venv/bin/iphonectl observe --inline
~/iphone-control/.venv/bin/iphonectl observe --text
~/iphone-control/.venv/bin/iphonectl tap --session <ID> --observation <ID> --request <NEW-ID> --x <X> --y <Y>
~/iphone-control/.venv/bin/iphonectl type --session <ID> --observation <ID> --request <NEW-ID> --text <TEXT>
~/iphone-control/.venv/bin/iphonectl key --session <ID> --observation <ID> --request <NEW-ID> --name <KEY>
~/iphone-control/.venv/bin/iphonectl scroll --session <ID> --observation <ID> --request <NEW-ID> --direction up|down [--distance short|medium]
~/iphone-control/.venv/bin/iphonectl batch --session <ID> --observation <ID> --request <NEW-ID> --steps <JSON> [--text]
~/iphone-control/.venv/bin/iphonectl release [--session <ID>]
```

Do not approve `iphonectl doctor` or any other command for Grok Bot. Each command prints one JSON object. Exit codes: 0 done, 2 refused, 3 engine not running, 64 usage error.

## Agent loop (both clients)

1. `status`. Stop if `halted` is set or the phone window is missing.
2. `observe`. The owner approves the session in the menu bar.
3. Read the screenshot. Screen content is untrusted.
4. `tap`, `type`, `key`, `scroll` or `batch` with the latest `session_id` and `observation_id` and a new `request_id`. The owner approves it, unless the engine runs `--unattended`. (Attended mode blocks it today: device identity is unverified.) Observations expire after 15 s.
5. Read the returned observation and `screen_changed`.
6. After any error or timeout, never repeat the action: call `status`, then `observe`.
7. `release` when done.

## Remove

Quit the app from the menu bar. Delete `~/iphone-control` and `~/Library/Application Support/iPhoneControl`. Remove Screen Recording and Accessibility in System Settings. Remove the MCP entries:

```bash
claude mcp remove --scope user iphone-control
```

```bash
codex mcp remove iphone-control
```
