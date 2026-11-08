# Template onboarding (for sharing this project)

This repository is a template. It contains no owner-specific identifiers, pairing records, credentials, screenshots or sessions. Keep it that way.

## Before you share it

Run this from the repository root. It must print nothing:

```bash
git ls-files | grep -Ei '\.(png|jpg|jpeg|heic|log|sock|sqlite)$|\.venv|Application Support'
```

Also check that no file names a real person, Mac, iPhone, Apple Account, Wi-Fi network or serial number.

Runtime state never lives in the repository. It lives in `~/Library/Application Support/iPhoneControl/` on each Mac (socket, screenshots, log) and is not shared.

## What each new owner does

1. Gets a copy of the template.
2. Follows `docs/SETUP.md`: compatibility check, install, `iphonectl doctor`.
3. Pairs iPhone Mirroring personally, with their own Apple Account.
4. Grants Screen Recording and Accessibility personally, after reading what they allow.
5. Starts `iphone-control-app` and approves every session and every action personally.
6. Connects their own Claude Code (MCP) and/or Grok Bot (CLI allow-list).

No owner may reuse another owner's pairing, permissions, approvals or files. There is no shared server.

## Known limits that every owner inherits

- Device identity: no documented mechanism. Scroll is blocked. See `docs/INTEGRATION.md`.
- Live-stream state: no documented signal. Reported as unknown.
- Permissions attach to the app that starts the engine (often Terminal) and cover all apps.
