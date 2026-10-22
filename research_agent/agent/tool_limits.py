"""Argument values a provider refuses that the tool's published schema does not say (B-071).

The planner writes arguments from the live catalog's schemas. When a schema is
silent or wrong about what a provider takes, the planner writes a value the
provider refuses, and each refusal is a billed attempt. Live run
accept-subscription-20261021: `tiktok_ads_library` documents `country` as
"Country code (e.g. 'US')", the provider answers HTTP 400 "Unsupported value
`US`", and five calls across two runs were paid for that answer.

A limit here is measured, never guessed: each one names the run or the provider
page it came from. The planner is told the limits of its runbook's tools, and a
step whose argument breaks one is not sent (the same path as an unresolved
placeholder: no attempt, not a refusal).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ArgumentLimit:
    allowed: frozenset[str]
    note: str
    source: str


#: SearchApi "TikTok Ads Library Countries" (docs/parameters/tiktok-ads-library/country,
#: read 2026-10-22; the refusal on 2026-10-21 lists the same values in the same order).
#: The library holds ads shown in these European markets only.
_TIKTOK_ADS_COUNTRIES = frozenset({
    "all", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IS", "IE", "IT",
    "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "TR", "GB",
})

LIMITS: dict[str, dict[str, ArgumentLimit]] = {
    "tiktok_ads_library": {
        "country": ArgumentLimit(
            allowed=_TIKTOK_ADS_COUNTRIES,
            note=("the TikTok Ads Library holds ads shown in European markets only: pass `all` or one of "
                  "AT BE BG HR CY CZ DK EE FI FR DE GR HU IS IE IT LV LI LT LU MT NL NO PL PT RO SK SI ES SE "
                  "CH TR GB (upper case). US and any other market are refused; for them pass `all` and say "
                  "in the report that the result covers Europe only."),
            source="live run accept-subscription-20261021 (HTTP 400) and SearchApi's country list, 2026-10-22",
        ),
    },
}


def planner_notes(tools: Iterable[str]) -> str:
    """One line per limit of the given tools, for the planner's prompt ('' when none)."""
    lines = [f"- `{tool}` `{argument}`: {limit.note}"
             for tool in tools for argument, limit in LIMITS.get(tool, {}).items()]
    return "\n".join(lines)


def refused(tool: str, arguments: Any) -> list[str]:
    """Each argument of `arguments` that breaks a known limit of `tool`, as
    "name='value'"; an empty list when the step may be sent."""
    if not isinstance(arguments, dict):
        return []
    out = []
    for argument, limit in LIMITS.get(tool, {}).items():
        value = arguments.get(argument)
        if isinstance(value, str) and value not in limit.allowed:
            out.append(f"{argument}={value!r}")
    return out
