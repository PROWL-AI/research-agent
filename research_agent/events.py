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

#: A key is credential-like when one of its `_`-separated segments is a credential
#: word (optionally plural): `api_key`, `access_token`, `secret` are refused;
#: `keyword`, `input_tokens`, `tokens_in` are ordinary usage fields and pass.
_CREDENTIAL_KEY = re.compile(
    r"(?i)(?:^|_)(?:api_?key|key|token|secret|authorization|auth|password|passwd|cookie|credential)s?(?:_|$)"
)
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "tokens_in", "tokens_out", "total_tokens"})
#: Credential-shaped substrings scrubbed from free-text values (exception text can
#: carry a provider response or a header).
_CREDENTIAL_VALUE = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+|\bsk-[A-Za-z0-9_-]{6,}|\bprowl_[A-Za-z0-9_-]{6,}"
)
_NEEDS_QUOTES = re.compile(r"[\s=]")


def _strict() -> bool:
    return os.environ.get("RESEARCH_EVENTS_STRICT") == "1"


def _format_value(value: Any) -> str:
    if value is None or isinstance(value, (bool, int, float)):
        return str(value)
    text = _CREDENTIAL_VALUE.sub("[redacted]", str(value))[:MAX_VALUE_CHARS]
    if not text or _NEEDS_QUOTES.search(text):
        return repr(text)
    return text


def emit(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> str:
    """Log one `event=<name> k=v …` line and return it."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        if key not in _USAGE_KEYS and _CREDENTIAL_KEY.search(key):
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
