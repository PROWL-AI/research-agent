# Prowl Research in the cloud: operator runbook

The cloud instance `prowl-research.cloud` is the team's research gateway: runbooks and every Prowl tool, reached from a
teammate's Claude Code with a personal client key. The provider keys (Prowl, OpenRouter) live only on the server. The
local instance `prowl-research.default` does not change. Design and decisions: [spec B-099](specs/2026-11-04-cloud-gateway.md).
Teammates read [TEAM-ONBOARDING.md](TEAM-ONBOARDING.md).

## Shape

| | Local (`default`) | Cloud (`cloud`) |
|---|---|---|
| Where | the operator's Mac, `127.0.0.1:18764`, launchd | Heroku, app `appvillis-prowl-research`, `$PORT` behind Heroku's TLS router |
| Code | this repository | the team copy `appvillis-com/appvillis-prowl-research`, built from a named commit of this one |
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
heroku run -a appvillis-prowl-research -- prowl-research-service client add anna --scopes read,research.run,tools.call
heroku run -a appvillis-prowl-research -- prowl-research-service client list
heroku run -a appvillis-prowl-research -- prowl-research-service client rotate anna
heroku run -a appvillis-prowl-research -- prowl-research-service client revoke anna
```

`add` and `rotate` print the key once; only its HMAC-SHA256 under the pepper `CLIENT_KEY_PEPPER` is stored
(`research_agent/service/clients.py`, B-104): the app refuses to open its key store without a pepper of at least 16
bytes, a key stored as a plain SHA-256 before 0.6.9 is rewritten under the pepper on its next use, and the names
`owner`, `root`, `operator`, `system`, `admin`, `service` and `host` are refused. The pepper lives in Observatory
(`<folder>/prod/CLIENT_KEY_PEPPER`) and reaches the app with `scripts/cloud.py config --app <app> CLIENT_KEY_PEPPER`. Scopes:

| Scope | Capabilities |
|---|---|
| `read` | `research.list_runbooks`, `research.artifact.get`, `research.tutorial` (free, contacts no provider) |
| `research.run` | `research.run` |
| `tools.call` | `research.tools.call` (one Prowl tool) |

`fabric.job.get` and `fabric.job.cancel` act on the caller's own jobs only. A key's jobs carry `client:<name>` as
their principal, so one client never reads, resumes or replays another's (`tests/test_cloud_service.py`). Every paid
job starts on its own when its worst case fits what is left of the key's daily ceiling, and waits for the operator's
approval on the cloud page otherwise (B-100, `research_agent/service/allowance.py`). Every key carries a ceiling of at
least 10 USD per UTC day, 10 by default (the operator's word recorded in the agents database, intake
in-20261112-996c34): `client add <name> --daily-usd 25`, `client limit <name> --daily-usd 25`. `--raw` prints only
the key, for a pipe straight into the holder's vault slot.

Key classes (K1, the operator's word of 2026-11-13, DEC-0074 of the Appvillis keys plan): a key for a person, or for an
agent a person calls in that moment, is `--class interactive` and has no ceiling: its paid jobs start at once, whatever
they cost, and each decision keeps who spent (`client:<name>`) and the class. A pipeline's or a schedule's key is
`--class automated` (the default) and keeps its ceiling as above. A key issued before classes reads as automated
until it is reissued. A missing ceiling reads as `null` in `client list` and the desk's `client.list`, never 0;
`client limit` on an interactive key is refused.

## Issuing desk

A team's key steward (for the Appvillis copy, the organization agent Аня) holds a desk key and issues the team's keys
itself (B-121, research template 1.6.0). The operator's tool creates it and says what it may give:

```sh
heroku run -a appvillis-prowl-research --no-tty -- prowl-research-service client add-desk ania \
  --grants read,research.run,tools.call --max-daily-usd 10 --raw | <vault.py put ... the steward's slot>
```

The desk key (scope `keys.issue`) sees only the desk tools on `/mcp`: `client.issue` (`name`, `scopes` within the
grants, `dailyUsd` from 10 up to the desk's maximum; the key is in the answer once, for a pipe into the holder's
slot), `client.rotate`, `client.revoke` and `client.list`, each on the keys this desk issued only. A desk key reads no
data and calls no data tool; an ordinary key has no desk tools. Without `--grants` a desk gives read keys only, at the
floor.

## Deploy

Heroku key and provider keys never enter argv or chat: run under Observatory.

```sh
# Once: the app, its database and its buildpack (team telegramcrew, spec R-3).
heroku apps:create appvillis-prowl-research --team telegramcrew --buildpack heroku/python
heroku addons:create heroku-postgresql:essential-0 -a prowl-research

# Config vars by name (values from the environment use_secret.py builds; printed: names only).
python "$(project-observatory full-path)/tools/use_secret.py" run --env prod <project> HEROKU_API_KEY \
  PROWL_API_KEY OPENROUTER_API_KEY FABRIC_SERVICE_TOKEN -- \
  python scripts/cloud.py config --app appvillis-prowl-research PROWL_API_KEY OPENROUTER_API_KEY FABRIC_SERVICE_TOKEN

# A build of one commit: its own suite runs first, a red suite refuses the deploy.
python "$(project-observatory full-path)/tools/use_secret.py" run --env prod <project> HEROKU_API_KEY -- \
  python scripts/cloud.py deploy --app appvillis-prowl-research --ref <sha>
```

The team copy deploys from the copy: the same `scripts/cloud.py deploy` in its checkout.

## Team copy

```sh
scripts/build_team_copy.py --ref <sha> --copy <clone of appvillis-com/appvillis-prowl-research> \
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
