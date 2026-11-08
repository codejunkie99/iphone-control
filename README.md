# iPhone Control

Lets Claude Code, Codex (MCP) and Grok Bot (CLI) operate the owner's own iPhone through Apple's iPhone Mirroring on the owner's Mac. By default the owner approves every session and every action in the menu bar, and **Stop now** halts everything immediately.

> **Status: prototype.** Tested on a physical iPhone from a Mac on macOS 27, with `--unattended`: opened apps through Spotlight, read Weather, played a song in Spotify, wrote a note in Notes. Also 49 tests against a SIMULATED backend. In the default (attended) mode, actions stay blocked because no documented interface identifies which iPhone the iPhone Mirroring window shows (see `docs/INTEGRATION.md`). `--unattended` makes device identity owner-asserted.

## Operations

| Operation | MCP tool | CLI | Changes the phone |
|---|---|---|---|
| Connection, device, session, capabilities | `status` | `iphonectl status` | No |
| Fresh screenshot (or OCR text with `text=true`) + observation ID | `observe` | `iphonectl observe [--text]` | No |
| Tap at pixel x, y of the latest screenshot | `tap` | `iphonectl tap ...` | Yes |
| Type text into the focused field | `type` | `iphonectl type ...` | Yes |
| Press a key: home, app_switcher, spotlight, return, delete, escape, tab, space, arrows | `key` | `iphonectl key ...` | Yes |
| One bounded scroll | `scroll` | `iphonectl scroll ...` | Yes |
| Up to 20 tap / tap_text / type / key / scroll steps, one observation back | `batch` | `iphonectl batch ...` | Yes |
| Stop pending work and release control | `release` | `iphonectl release` | No |

There is no tool for shell commands, Python or general desktop automation. Input goes only to the iPhone Mirroring window.

## Layout

```
src/iphone_control/
  engine.py         session, observations, policy, approvals, Stop (no UI)
  backend.py        backend interface, screen-change measure
  macos_backend.py  iPhone Mirroring window: capture, tap, type, keys, scroll, OCR (PyObjC)
  fake_backend.py   SIMULATED backend for tests
  identity.py       device identity gate (default: unverified -> mutations blocked)
  server.py         user-only Unix socket (agent operations only)
  client.py         socket client
  mcp_server.py     stdio MCP server for Claude Code and Codex (controller "claude-code")
  cli.py            iphonectl for Grok Bot (controller "grok-bot")
  app.py            persistent process: engine + socket + menu bar
  doctor.py         read-only iPhone setup check
  privacy.py        telemetry opt-out, content-free event log
tests/              simulated tests (unittest)
docs/               INTEGRATION, SETUP, LOCAL-TEST-PLAN, TEMPLATE-ONBOARDING
examples/           Claude Code MCP config, Grok Bot approved commands
```

## Start

Read `docs/SETUP.md`. Run the tests:

```bash
cd tests && python3 -m unittest -v
```

## License

Apache-2.0. See `LICENSE` and `NOTICE` (attribution for mirroir-mcp and phoneuse).
