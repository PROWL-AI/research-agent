"""Callee side of Fabric delegation (DEC-0039, FD-12), by trust tier (DL-25, DL-26).

The service binds loopback. A caller holding the service's own agent token from
loopback is T0: it is never required to present a delegation token. A token it
does present is verified offline and refused when invalid, and the verified
principal, caller and actor chain are recorded on the job it starts. A caller
presenting only a delegation token, or calling from off the machine, is T2: a
valid token is required. With no trusted issuer configured a presented token
is refused — fail closed, never skipped.

Configuration (environment, read at start):
  RESEARCH_DELEGATION_ISSUER   the issuer this service trusts, `urn:fabric:estate:<id>`
  RESEARCH_DELEGATION_JWKS     where the estate's key set is read: https, loopback http, or a file
  RESEARCH_DELEGATION_AUDIENCE this service's agent id (default `prowl-research.default`)

The verifier is the adapter kit's (vendor/fabric_delegation.py, unchanged).
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any, Mapping

from .vendor import fabric_delegation as fd

DEFAULT_AUDIENCE = "prowl-research.default"


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DelegationPolicy:
    def __init__(self, *, issuer: str | None, jwks: Any, audience: str, effects: Mapping[str, str]) -> None:
        self.issuer = issuer or None
        self.jwks_source = jwks if isinstance(jwks, str) else None
        self.audience = audience
        self.effects = dict(effects)
        self._gate = None
        if self.issuer:
            if jwks is None:
                raise ValueError("RESEARCH_DELEGATION_ISSUER is set without RESEARCH_DELEGATION_JWKS")
            keys = fd.JwksCache(jwks) if isinstance(jwks, str) else jwks
            self._gate = fd.delegation_gate(audience=audience, jwks=keys, issuer=self.issuer, effects=self.effects)

    @classmethod
    def from_env(cls, effects: Mapping[str, str], environ: Mapping[str, str] | None = None) -> "DelegationPolicy":
        env = os.environ if environ is None else environ
        return cls(issuer=env.get("RESEARCH_DELEGATION_ISSUER", "").strip() or None,
                   jwks=env.get("RESEARCH_DELEGATION_JWKS", "").strip() or None,
                   audience=env.get("RESEARCH_DELEGATION_AUDIENCE", "").strip() or DEFAULT_AUDIENCE,
                   effects=effects)

    @property
    def configured(self) -> bool:
        return self._gate is not None

    def declaration(self) -> dict[str, str] | None:
        """`auth.delegation` for the well-known document (DL-16), when configured."""
        if not self.configured:
            return None
        return {"issuer": self.issuer, "jwks": self.jwks_source or "inline"}

    @staticmethod
    def carries_token(headers: Any) -> bool:
        return fd.read_delegation_token(headers) is not None

    def check(self, tool: str, headers: Any, *, own_token: bool, loopback: bool) -> dict[str, Any]:
        """The verdict for one tools/call: `{ok: True, tier, principal, caller, chain, ...}` or a DL-19
        refusal `{ok: False, code, detail}`."""
        tier = "T0" if own_token and loopback else "T2"
        if self._gate is None:
            if self.carries_token(headers):
                return {"ok": False, "code": "issuer-unavailable", "detail": "no-trusted-issuer"}
            if tier == "T0":
                return {"ok": True, "tier": tier, "principal": None, "caller": None, "chain": [], "claims": None, "kid": None}
            return {"ok": False, "code": "unauthenticated", "detail": "no-token"}
        return self._gate(tool, headers, tier=tier)


def refusal_tool_result(verdict: dict[str, Any]) -> dict[str, Any]:
    return fd.refusal_tool_result(verdict)


def recorded(verdict: dict[str, Any]) -> dict[str, Any] | None:
    """What a job keeps of a verified delegation: who acts for whom. Never the token."""
    if not verdict.get("principal"):
        return None
    return {"principal": verdict["principal"], "caller": verdict.get("caller"), "chain": verdict.get("chain") or [],
            "kid": verdict.get("kid"), "tier": verdict.get("tier")}
