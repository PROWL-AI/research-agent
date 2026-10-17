#!/usr/bin/env python3
"""Compare research_agent/pricing.PRICES with the live OpenRouter catalog.

Exit 0 when every listed model's input/output price matches the catalog
(to 4 decimals per 1M tokens), 1 with a line per mismatch or missing model,
2 when the catalog cannot be read. Needs network; no key.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_agent.pricing import PRICES  # noqa: E402

CATALOG = "https://openrouter.ai/api/v1/models"


def main() -> int:
    try:
        with urllib.request.urlopen(CATALOG, timeout=30) as response:  # noqa: S310 — fixed https URL
            models = {m["id"]: m for m in json.load(response)["data"]}
    except Exception as exc:  # noqa: BLE001
        print(f"error: catalog unreadable: {exc}", file=sys.stderr)
        return 2
    problems = 0
    for model, (p_in, p_out) in PRICES.items():
        entry = models.get(model)
        if entry is None:
            print(f"MISSING {model}: not in the catalog")
            problems += 1
            continue
        live = (round(float(entry["pricing"]["prompt"]) * 1e6, 4), round(float(entry["pricing"]["completion"]) * 1e6, 4))
        if live != (round(p_in, 4), round(p_out, 4)):
            print(f"STALE   {model}: table {p_in}/{p_out}, catalog {live[0]}/{live[1]}")
            problems += 1
    print("prices match the catalog" if not problems else f"{problems} price row(s) to update")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
