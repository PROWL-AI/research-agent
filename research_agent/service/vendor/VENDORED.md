# Vendored files

| File | Source | sha256 | Why |
|---|---|---|---|
| `spend_ledger.py` | agents database pattern `spend-ledger` 1.3.0, `patterns/spend-ledger/code/spend_ledger.py` at `a154ae2` | `6fb43d882d45ef1f70a6ff12052cdabf1eb81ee7f77e155b970ead7b7df05457` | B-103: the month ceiling across jobs and its hash-chained journal (jsonl store in the data root, which the cloud's snapshot keeps). Copied unchanged: update by replacing the file from a newer pattern version and recording its digest here. |
| `fabric_delegation.py` | fabric-agent-adapter plugin 0.34.0 (byte-identical in 0.23.0–0.35.0), `skills/building-fabric-services/scripts/fabric_delegation.py` | `e1dd63f4343b64d867d39d69d106bc1b5e4a65b6c0b08928eb0c75114b474e15` | The contract's DL-13 verifier (DEC-0039) in Python, standard library only. Copied unchanged: update by replacing the file from a newer adapter release and recording its digest here. |
| `costs_panel.py` | agents database pattern `costs-panel` 1.0.0, `patterns/costs-panel/code/costs_panel.py` at `a2019216` | `c96b2643d0b623b248c6e56b797838f7fc89aca0e508572b25848b72f75a14b6` | B-155 (rule R33 O16, D-74): the Costs section's windows, the check before a paid call, the limit book with its one edit `spend.limits.set`, chart series. Copied unchanged; `tests/test_costs_section.py` checks the hash |
