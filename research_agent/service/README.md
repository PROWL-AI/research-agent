# Adapter modules

- `store.py`: durable jobs, single-use decisions, config revisions, events and usage receipts.
- `runtime.py`: observed clients, bounded service execution, existing Orchestrator reuse, synthetic tutorial.
- `protocol.py`: MCP tools and Fabric job/result translation.
- `app.py`: loopback HTTP/authentication and dashboard API.
- `cli.py`: exclusive process lock, token file checks, foreground supervised entry and doctor.
- `static/`: service-owned operator interface, local OFL font assets; no third-party runtime scripts.

The implementation is independent of the AGPL Fabric reference kit. The normative contract is an external test input, not copied into this MIT package. See `docs/FABRIC.md` for operating boundaries.
