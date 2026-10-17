---
name: calibration-teardown
description: judge calibration fixture runbook (evals/fixtures/planted); never run against providers
version: "1.0"
inputs:
  - { name: competitors, type: "list[domain]", required: true, max: 1 }
tools:
  - spyfu_get_domain_stats
  - dataforseo_bl_summary
budget: { max_tool_calls: 4, max_usd: 0.50, max_minutes: 10 }
outputs: { report_template: calibration, formats: [markdown] }
---

# Calibration Teardown

Fixture runbook for `evals/calibrate.py`: the judge reads its required sections.

## Sequence

1. **Baseline** — `spyfu_get_domain_stats` and `dataforseo_bl_summary` for the competitor.

## Verification (hard rules)

- none

## Output instructions

Template `calibration`. Required sections:

1. **Executive summary** — key findings, one line each.
2. **Source log** — every figure with tool + retrieval date.
