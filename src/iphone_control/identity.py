"""Which iPhone is on the other end of the iPhone Mirroring window?

This is an unresolved gate. Apple documents no interface that reports which
iPhone an iPhone Mirroring session shows:

- The window server reports a window ID, an owner PID and a title
  ("iPhone Mirroring"). These identify the Mac window, not the phone.
- The iPhone Mirroring app has no public scripting dictionary, URL scheme or
  framework API.
- `xcrun devicectl list devices` (Xcode) lists devices that CoreDevice knows,
  but does not say which of them, if any, is mirroring.
- The phone name sometimes appears in the window's content or accessibility
  tree. That is screen content (untrusted, and settable by anyone who names
  a phone), not verification.

So the default provider reports "unverified" and the engine blocks every
mutation. Read-only observation is still possible with owner approval.

To unblock mutations, add a provider whose evidence comes from a documented,
tamper-resistant mechanism, and register it in `make_provider`. Do not
replace this with a name match or an owner checkbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .backend import Probe


@dataclass
class IdentityResult:
    verified: bool
    method: str
    device_label: Optional[str]
    reason: str


class IdentityProvider:
    def verify(self, probe: Probe) -> IdentityResult:
        raise NotImplementedError


class NoDocumentedIdentity(IdentityProvider):
    """The production default: no documented identity mechanism exists."""

    def verify(self, probe: Probe) -> IdentityResult:
        return IdentityResult(
            verified=False, method="none", device_label=None,
            reason=("No documented interface reports which iPhone the iPhone Mirroring window shows. "
                    "Mutations stay blocked. See docs/INTEGRATION.md, 'Device identity'."))


class SimulatedIdentity(IdentityProvider):
    """Tests only. Reports a fixed, clearly simulated identity."""

    def __init__(self, verified: bool = True, label: str = "SIMULATED-PHONE"):
        self.verified = verified
        self.label = label

    def verify(self, probe: Probe) -> IdentityResult:
        if not probe.simulated:
            return IdentityResult(False, "simulated", None, "simulated identity refuses a real backend")
        return IdentityResult(self.verified, "simulated", self.label if self.verified else None,
                              "SIMULATED: test identity, not a real device check")


class OwnerAsserted(IdentityProvider):
    """The owner started the engine with --unattended and states the mirrored phone is theirs.
    This is the owner's word, not a technical check; status reports it as such."""

    def verify(self, probe: Probe) -> IdentityResult:
        if probe.simulated:
            return IdentityResult(False, "owner_asserted", None, "owner assertion applies to a real phone only")
        return IdentityResult(True, "owner_asserted", None,
                              "Owner-asserted (--unattended): not a technical device check.")


def make_provider(name: str = "none") -> IdentityProvider:
    if name == "none":
        return NoDocumentedIdentity()
    if name == "owner":
        return OwnerAsserted()
    raise ValueError(f"unknown identity provider {name!r}; use 'none' or 'owner'")
