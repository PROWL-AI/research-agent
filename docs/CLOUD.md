# Prowl Research in the cloud: operator runbook

The cloud instance `prowl-research.cloud` is the team's research gateway: runbooks and every Prowl tool, reached from a
teammate's Claude Code with a personal client key. The provider keys (Prowl, OpenRouter) live only on the server. The
local instance `prowl-research.default` does not change. Design and decisions: [spec B-099](specs/2026-11-04-cloud-gateway.md).
Teammates read [TEAM-ONBOARDING.md](TEAM-ONBOARDING.md).

## Shape

| | Local (`default`) | Cloud (`cloud`) |
|---|---|---|
| Where | the operator's Mac, `127.0.0.1:18764`, launchd | Heroku, app `prowl-research`, `$PORT` behind Heroku's TLS router |
| Code | this repository | the team copy `appvillis-com/prowl-research-agent`, built from a named commit of this one |
| Provider keys | the operator's Observatory | config vars of the app only |
| Who calls `/mcp` | the operator's agents (agent token, delegation) | clients with a `prc_` key, one per person or agent |
| Page | Fabric Dashboards, one-time code | Fabric Dashboards, one-time code; cookie `__Host-prowl_operator`, `Secure` |
| State | the data folder on disk | the data folder, snapshotted into Postgres |

Cloud mode is `prowl-research-service cloud-run` (the `Procfile`). Without its variables the service is the local one
byte for byte (`tests/test_service.py`).

## Configuration

| Variable | What |
|---|---|
| `PUBLIC_ORIGIN` | `https://<host>`, no path. Only requests for this host, forwarded as https, are answered (`research_agent/service/app.py`, `guard`) |
| `FABRIC_SERVICE_TOKEN` | the service token, at least 32 characters. It opens the well-known document, events, usage and the one-time code; it is refused on `/mcp` |
| `DATABASE_URL` | Heroku Postgres. Client keys (`prowl_research_clients`) and state snapshots (`prowl_research_snapshot`) |
| `PROWL_API_KEY` | the Prowl key of the cloud instance |
| `OPENROUTER_API_KEY` or `RESEARCH_LLM_API_KEY` | the model key of the cloud instance |
| `PROWL_RESEARCH_ROOT` | data folder on the dyno, default `/tmp/prowl-research` |

## Client keys

```sh
heroku run -a prowl-research -- prowl-research-service client add anna --scopes read,research.run,tools.call
heroku run -a prowl-research -- prowl-research-service client list
heroku run -a prowl-research -- prowl-research-service client rotate anna
heroku run -a prowl-research -- prowl-research-service client revoke anna
```

`add` and `rotate` print the key once; only its SHA-256 is stored (`research_agent/service/clients.py`). Scopes:

| Scope | Capabilities |
|---|---|
| `read` | `research.list_runbooks`, `research.artifact.get`, `research.tutorial` (free, contacts no provider) |
| `research.run` | `research.run` |
| `tools.call` | `research.tools.call` (one Prowl tool) |

`fabric.job.get` and `fabric.job.cancel` act on the caller's own jobs only. A key's jobs carry `client:<name>` as
their principal, so one client never reads, resumes or replays another's (`tests/test_cloud_service.py`). Every paid
job waits for the operator's approval on the cloud page (spec R-6); a per-key allowance without a person is B-100.

## Deploy

Heroku key and provider keys never enter argv or chat: run under Observatory.

```sh
# Once: the app, its database and its buildpack (team telegramcrew, spec R-3).
heroku apps:create prowl-research --team telegramcrew --buildpack heroku/python
heroku addons:create heroku-postgresql:essential-0 -a prowl-research

# Config vars by name (values from the environment use_secret.py builds; printed: names only).
python "$(project-observatory full-path)/tools/use_secret.py" run --env prod <project> HEROKU_API_KEY \
  PROWL_API_KEY OPENROUTER_API_KEY FABRIC_SERVICE_TOKEN -- \
  python scripts/cloud.py config --app prowl-research PROWL_API_KEY OPENROUTER_API_KEY FABRIC_SERVICE_TOKEN

# A build of one commit: its own suite runs first, a red suite refuses the deploy.
python "$(project-observatory full-path)/tools/use_secret.py" run --env prod <project> HEROKU_API_KEY -- \
  python scripts/cloud.py deploy --app prowl-research --ref <sha>
```

The team copy deploys from the copy: the same `scripts/cloud.py deploy` in its checkout.

## Team copy

```sh
scripts/build_team_copy.py --ref <sha> --copy <clone of appvillis-com/prowl-research-agent> \
  --audit <org-transfer-audit>
git -C <copy> push origin sync/<sha12>:main     # after the branch's checks; fast-forward only
```

The builder refuses a copy commit after the last build that the original has not taken back (`Backports: <sha>` in
an original commit, D15 S3). What stays with the original: `docs/evidence/`, `docs/reports/`, `docs/HANDOFF.md`,
`runs/`, `.task-pipeline/` (`scripts/build_team_copy.py`, `FORBIDDEN`). The LICENSE is the original's (MIT).

## Fabric Dashboards

```sh
python scripts/cloud.py register --origin https://<host> --token-file <0600 file holding FABRIC_SERVICE_TOKEN>
```

writes `prowl-research.cloud.json` (placement `remote`, `lifecycle.manager: none`, `peer.custody:
organization-managed`). Dashboards shows `default` and `cloud` as one product.

## State

`research_agent/service/snapshot.py` restores the newest intact snapshot before the store opens, saves when the data
folder changed (checked every 30 s) and at shutdown, keeps three, and skips a snapshot whose SHA-256 does not match.
