# Local test plan (on the owner's Mac)

Run this on the Mac, not in a cloud session. Record the exact command, output and result of each step in `docs/TEST-RESULTS.md`. Never record screenshots, screen text or device names in that file.

**Ask the owner before each step marked [ASK].** Do not install, change permissions, capture the phone or send input without a "yes" for that step.

## Phase 0 — simulated suite (no phone)

```bash
cd ~/iphone-control/tests && python3 -m unittest -v
```

Expected: 42 tests, OK (one test skips if the MCP SDK is not installed). These tests are SIMULATED.

## Phase 1 — install and check [ASK]

1. [ASK] Create `.venv` and run `pip install -e .` (installs PyObjC from PyPI).
2. Run `.venv/bin/iphonectl doctor`. Record every line marked FAIL or `??`.
3. Read the permissions explanation to the owner. The owner pairs iPhone Mirroring and grants Screen Recording and Accessibility personally. Do not open or click System Settings for them.

## Phase 2 — simulated app (no phone)

1. Start `.venv/bin/iphone-control-app --simulate` in the background.
2. `iphonectl status`: expect `"simulated": true`.
3. `iphonectl observe`: the owner clicks Approve in the menu bar (title "iPhone ⚠ approve?").
4. Owner presses **Stop now**. `iphonectl status`: expect `"halted": "owner_stop"`.
5. Quit the simulated app from the menu bar.

## Phase 3 — one screenshot from the physical iPhone [ASK]

1. Start `.venv/bin/iphone-control-app` (real backend).
2. `iphonectl status`: record `window_present`, `permissions`, `device.identity_verified` (expected false).
3. [ASK] "May I take one screenshot of your iPhone screen through iPhone Mirroring?"
4. `iphonectl observe`. The owner approves the session in the menu bar.
5. Check: `"simulated": false`, the image file exists, mode 0600, and its size matches the phone window (not the desktop). Show the image to the owner only. Do not copy it elsewhere.
6. `iphonectl release`. Check that the shots directory is empty.

## Phase 4 — scroll gate (no scroll expected)

Device identity has no documented mechanism, so the scroll must be refused before the owner is asked.

1. `iphonectl observe` (owner approves).
2. `iphonectl scroll --session S --observation O --request gate-1 --direction down`.
3. Expect exit 2, `"code": "identity_unverified"`, no approval prompt, no movement on the phone.

Do not change `identity.py` to pass this gate. A physical scroll needs a documented identity mechanism first, and then a separate owner approval for one short scroll on a harmless screen (for example a Settings list), verified by a new screenshot.

## Phase 5 — failure paths

| Test | Steps | Expected |
|---|---|---|
| Denial | `observe`; owner clicks Deny | exit 2, `denied`; no file in shots |
| Timeout | `observe`; owner does nothing for 60 s | `approval_timeout` |
| Stale evidence | `observe`; wait 16 s; `scroll` | `stale_observation` |
| Duplicate | `scroll` twice with the same `--request` | second one: `duplicate_request` |
| Competing controller | `observe` with the CLI; then the MCP `observe` tool in Claude Code | MCP gets `controller_busy` |
| Disconnect | `observe`; owner closes the iPhone Mirroring window; `observe` | `not_connected`; `halted: disconnect` |
| Takeover / Stop | `observe`; owner presses Stop now; `observe` | `halted`; nothing works until Resume |
| No auto-reconnect | after Stop, reopen iPhone Mirroring; `observe` | still `halted` until the owner selects Resume |
| Cleanup | `observe` twice; `release` | `released`; shots directory empty |
| Engine down | quit the app; `iphonectl status` | exit 3, `engine_not_running` |
| Socket privacy | `ls -l ~/Library/Application\ Support/iPhoneControl/run/` | `srw-------` |
| Log privacy | read `logs/engine.log` | event codes and IDs only; no paths, no text |

## Phase 6 — Claude Code MCP

1. [ASK] `claude mcp add --scope user iphone-control -- "$HOME/iphone-control/.venv/bin/iphone-control-mcp"`
2. In a new Claude Code session, call `status`, then `observe` (owner approves), then `release`.
