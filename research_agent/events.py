"""Structured lifecycle events: one log line per transition, `event=<name> k=v …`.

Every lifecycle transition is logged through `emit` so a log reader (human or
grep) sees one stable shape. Values are scalars; strings are truncated to 200
characters and repr-quoted when they contain whitespace or '=' (so the line
stays splittable). A field whose key looks like a credential is never logged:
it raises under RESEARCH_EVENTS_STRICT=1 (the test suite) and is dropped with
a WARNING otherwise — a production log line must not fail a run.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

MAX_VALUE_CHARS = 200

_CREDENTIAL_KEY = re.compile(r"(?i)key|token|secret|authorization|password|cookie")
_NEEDS_QUOTES = re.compile(r"[\s=]")


def _strict() -> bool:
    return os.environ.get("RESEARCH_EVENTS_STRICT") == "1"


def _format_value(value: Any) -> str:
    if value is None or isinstance(value, (bool, int, float)):
        return str(value)
    text = str(value)[:MAX_VALUE_CHARS]
    if not text or _NEEDS_QUOTES.search(text):
        return repr(text)
    return text


def emit(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> str:
    """Log one `event=<name> k=v …` line and return it."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        if _CREDENTIAL_KEY.search(key):
            if _strict():
                raise ValueError(
                    f"event {event!r}: field {key!r} looks like a credential and is never logged"
                )
            logger.warning("event %s: dropped credential-like field %r", event, key)
            continue
        parts.append(f"{key}={_format_value(value)}")
    line = " ".join(parts)
    logger.log(level, "%s", line)
    return line
