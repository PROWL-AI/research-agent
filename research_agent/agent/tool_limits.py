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
    #: The same fact for a person or a caller: a direct result's envelope and the reports.
    statement: str = ""
    #: The statement in the dashboard's language (B-078); the API keeps `statement`.
    statement_ru: str = ""


#: SearchApi "TikTok Ads Library Countries" (docs/parameters/tiktok-ads-library/country,
#: read 2026-10-22; the refusal on 2026-10-21 lists the same values in the same order).
#: The library holds ads shown in these European markets only.
_TIKTOK_ADS_COUNTRIES = frozenset({
    "all", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IS", "IE", "IT",
    "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "TR", "GB",
})

#: SearchApi's Bing News `time_period` (the refusal of 2026-11-13 lists these; the engine's schema enumerates the same
#: ten). There is no month or year window: a pulse over months reads Bing News for its last 30 days at most.
_BING_NEWS_PERIODS = frozenset({
    "last_minute", "last_5_minutes", "last_15_minutes", "last_30_minutes", "last_hour", "last_4_hours",
    "last_6_hours", "last_24_hours", "last_7_days", "last_30_days",
})

LIMITS: dict[str, dict[str, ArgumentLimit]] = {
    "bing_news": {
        "time_period": ArgumentLimit(
            allowed=_BING_NEWS_PERIODS,
            note=("Bing News `time_period` takes only last_minute, last_5_minutes, last_15_minutes, last_30_minutes, "
                  "last_hour, last_4_hours, last_6_hours, last_24_hours, last_7_days or last_30_days; `month`, `year` "
                  "and longer windows are refused. For a window of months pass last_30_days or leave it out."),
            source=("B-126: both acceptance runs of 2026-11-13 (pr-4970f08d4eb0383bf89e, pr-71cff1b75b7cad5a0999) "
                    "sent `month` and got HTTP 400 \"Unsupported value `month` in time_period parameter\""),
            coverage=("`bing_news` results cover at most the last 30 days: never read them as a count over a longer "
                      "window, and say so where the pulse window is longer."),
            statement="Bing News: at most the last 30 days; a longer window is not available from this source.",
            statement_ru="Bing News: не больше последних 30 дней; более длинного окна у этого источника нет.",
        ),
    },
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
            statement_ru=("TikTok Ads Library: только реклама, показанная в Европе (ЕС/ЕЭЗ, Великобритания, "
                          "Швейцария, Турция); пустой результат ничего не говорит о других рынках."),
        ),
    },
}


@dataclass(frozen=True)
class FlagDependency:
    """A boolean argument the provider takes only when other booleans are true as well (B-134)."""
    requires: tuple[str, ...]
    note: str
    source: str


#: A true flag whose requirements are not all true is taken out before the step is sent: the provider refuses the
#: whole task otherwise, and switching the requirements on would buy paid options nobody asked for.
FLAG_DEPENDENCIES: dict[str, dict[str, FlagDependency]] = {
    "dataforseo_onpage_task_post": {
        "enable_browser_rendering": FlagDependency(
            requires=("enable_javascript", "load_resources"),
            note=("`enable_browser_rendering` is accepted only with `enable_javascript` and `load_resources` both "
                  "true; leave it out unless both are set."),
            source=("B-134: acceptance pr-ccc142f3e62bfb674bbb (2026-11-14) sent it with enable_javascript only: "
                    "DataForSEO 40501 \"Invalid Field: 'enable_browser_rendering', 'enable_javascript' and "
                    "'load_resources' must be enabled\", and the three on-page reads after it were not sent"),
        ),
    },
}


def planner_notes(tools: Iterable[str]) -> str:
    """One line per limit of the given tools, for the planner's prompt ('' when none)."""
    tools = list(tools)
    lines = [f"- `{tool}` `{argument}`: {limit.note}"
             for tool in tools for argument, limit in LIMITS.get(tool, {}).items()]
    lines += [f"- `{tool}` `{flag}`: {dep.note}"
              for tool in tools for flag, dep in FLAG_DEPENDENCIES.get(tool, {}).items()]
    return "\n".join(lines)


def unmet_flags(tool: str, arguments: Any) -> list[str]:
    """The true flags of `arguments` whose required flags are not all true (B-134)."""
    if not isinstance(arguments, dict):
        return []
    return [flag for flag, dep in FLAG_DEPENDENCIES.get(tool, {}).items()
            if arguments.get(flag) is True and not all(arguments.get(r) is True for r in dep.requires)]


def coverage_notes(tools: Iterable[str]) -> list[str]:
    """What the results of the given (sent) tools cover, once per tool, for the writer."""
    notes: list[str] = []
    for tool in dict.fromkeys(tools):
        notes.extend(limit.coverage for limit in LIMITS.get(tool, {}).values() if limit.coverage)
    return notes


def canonical(tool: str, arguments: Any) -> Any:
    """`arguments` with each limited value in the spelling the provider lists ("fr" ->
    "FR"): only the value was measured, so it is sent as the provider's list writes it."""
    if not isinstance(arguments, dict) or (tool not in LIMITS and tool not in FLAG_DEPENDENCIES):
        return arguments
    out = {k: v for k, v in arguments.items() if k not in unmet_flags(tool, arguments)}
    for argument, limit in LIMITS.get(tool, {}).items():
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


def statements_ru(tools: Iterable[str]) -> list[str]:
    """The same facts as `statements`, in the dashboard's language."""
    out: list[str] = []
    for tool in dict.fromkeys(tools):
        out.extend(limit.statement_ru for limit in LIMITS.get(tool, {}).values() if limit.statement_ru)
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
