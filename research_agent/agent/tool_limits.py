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
    #: What a result of this tool covers, as an instruction to the writer (it never sees step arguments).
    coverage: str = ""
    #: The same fact for a person or a caller: the dashboard and a direct result's envelope.
    statement: str = ""


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
                  "CH TR GB. US and any other market are refused; for them pass `all` (the writer is told "
                  "the result covers Europe only)."),
            source="live run accept-subscription-20261021 (HTTP 400) and SearchApi's country list, 2026-10-22",
            coverage=("`tiktok_ads_library` results cover ads shown in European markets only (EU/EEA, UK, CH, TR): "
                      "say so wherever they are used, and never read an empty result as \"does not advertise on "
                      "TikTok\" for any other market."),
            statement=("TikTok Ads Library: ads shown in European markets only (EU/EEA, UK, CH, TR); "
                       "an empty result says nothing about any other market."),
        ),
    },
}


def planner_notes(tools: Iterable[str]) -> str:
    """One line per limit of the given tools, for the planner's prompt ('' when none)."""
    lines = [f"- `{tool}` `{argument}`: {limit.note}"
             for tool in tools for argument, limit in LIMITS.get(tool, {}).items()]
    return "\n".join(lines)


def coverage_notes(tools: Iterable[str]) -> list[str]:
    """What the results of the given (sent) tools cover, once per tool, for the writer."""
    notes: list[str] = []
    for tool in dict.fromkeys(tools):
        notes.extend(limit.coverage for limit in LIMITS.get(tool, {}).values() if limit.coverage)
    return notes


def canonical(tool: str, arguments: Any) -> Any:
    """`arguments` with each limited value in the spelling the provider lists ("fr" ->
    "FR"): only the value was measured, so it is sent as the provider's list writes it."""
    if not isinstance(arguments, dict) or tool not in LIMITS:
        return arguments
    out = dict(arguments)
    for argument, limit in LIMITS[tool].items():
        value = out.get(argument)
        if isinstance(value, str):
            match = next((a for a in limit.allowed if a.upper() == value.upper()), None)
            if match is not None:
                out[argument] = match
    return out


def statements(tools: Iterable[str]) -> list[str]:
    """What the results of the given tools cover, once per tool, for a person or a caller."""
    out: list[str] = []
    for tool in dict.fromkeys(tools):
        out.extend(limit.statement for limit in LIMITS.get(tool, {}).values() if limit.statement)
    return out


def refused(tool: str, arguments: Any) -> list[str]:
    """Each argument of `arguments` that breaks a known limit of `tool`, as
    "name='value'"; an empty list when the step may be sent. Case is not compared
    here; `canonical` sends the provider's spelling."""
    if not isinstance(arguments, dict):
        return []
    out = []
    for argument, limit in LIMITS.get(tool, {}).items():
        value = arguments.get(argument)
        if isinstance(value, str) and value.upper() not in {a.upper() for a in limit.allowed}:
            out.append(f"{argument}={value!r}")
    return out
