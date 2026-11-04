# Prowl Research locally and in the cloud: a team gateway (B-099)

Status: brief, spec and plan, 2026-11-04. Route: `task-pipeline`, full path (public network surface, client keys,
deploy, spend). Each module below lands as its own commit with tests.

## Brief

Operator, 2026-11-04, this project's session (recognised speech, verbatim):

> «Я хочу, чтобы этот агент стал облачным агентом, так же как CMO Creative и Mobile Publisher агент, и давать токены,
> чтобы команда могла использовать этого агента, вот копию этого агента, который будет в Апилисе, мы задеплоим. и с
> токеном она будет работать у ребят будет доступ к ресерчам и всем подключенным апи инстурментам Короче, это должен
> стать такой gateway, вот как у нас approval chat, это наш gateway типа для всех опишек и ресерчер, а этот ресерчер,
> это типа для клауд-кода проекта, он все равно же коннектится с облаком, и это должен быть gateway клауд-кода для всех
> инструментов, которые вот у нас есть доступны, и также типа он будет облачный агент»

One code, two instances. The local instance (`prowl-research.default`, loopback, launchd, keys from the operator's
Observatory) does not change. A cloud instance (`prowl-research.cloud`) runs from a team copy in `appvillis-com` on
Heroku. The provider keys (Prowl, OpenRouter) live only on that server. A teammate's Claude Code reaches the research
runbooks and every Prowl tool through `POST /mcp` with a personal client key; the page opens only from Fabric
Dashboards with a one-time code. The shape is the estate's rule for shared agents: D15 (copies) and D16 (share the
agent, not the keys) of the agent-transport plan, reference implementation CMO (`cmo-creative-agent`
`docs/specs/2026-11-04-cloud-instance.md`, branch `feat/cloud-instance-2026-11-04`).

This changes two earlier records:

- The agent-transport plan (Data Room, 2026-10-28) listed `prowl-research` as "not an addressee, public PROWL-AI".
  The operator's words above make it an "operator's agent with a copy" (D15 S1).
- `SECURITY.md` said "not a multi-tenant authorization server; do not expose it on a LAN or Internet origin". That
  stays true of the local instance; the cloud instance is the one exposed, and only with client keys.

### Decisions taken without questions (source, why)

| # | Decision | Why |
|---|---|---|
| R-1 | Class D15 "operator's agent with a copy": the original stays `PROWL-AI/research-agent` (public); the copy is `appvillis-com/appvillis-prowl-research` (private), built only by `scripts/build_team_copy.py` from a named original commit, with `Source-Revision: prowl-research@<sha>` and `.copy/upstream.json`. The name avoids the operator's private `research-agent`, which has its own copy plan (its BL-335) | operator «копию этого агента, который будет в Апилисе»; D15 S1, S2 |
| R-2 | The copy carries the original's `LICENSE` byte for byte (MIT, PROWL AI). D14 asks for one LICENSE in original and copy; the original is public under MIT, which already grants Appvillis internal use, and relicensing a public repository is not this task's to do | D14 "one LICENSE in both"; operator kept this repository public (2026-10-28) |
| R-3 | Heroku team `telegramcrew` (Data Room and CMO cloud live there), app `appvillis-prowl-research`, one Basic web dyno, Postgres essential-0: about 12 USD a month, inside the estate's USD 1 000 a month | D13; CMO C-2 precedent; spend record below |
| R-4 | Cloud provider keys are issued for the cloud only: a dedicated OpenRouter key with its own limit (`tools/openrouter.py issue`) and the existing Prowl key `0xDEV/prod/PROWL_API_KEY` until a dedicated prowl.chat key with a spend limit is issued. Both go into config vars from Observatory through stdin, recorded with `vault.py moved` | D16 K1; Prowl key policy carries per-key spend limits (`prowl-app` `mcp_server/key_policy.py`) |
| R-5 | Client keys: `prc_` + 32 random bytes, stored as SHA-256 only, printed once, scopes `read`, `research.run`, `tools.call`, revoked and rotated one by one, in Postgres so a one-off dyno and the web dyno share one table; a 0600 file without `DATABASE_URL` | D16 K2; CMO M4; `fabric-heroku-template` `src/auth.mjs` |
| R-6 | Every paid job a client creates waits for the operator's approval in the cloud page, exactly as today. A per-key daily allowance that approves without a person is a money decision and is filed as its own row (B-100), not shipped here | standing rule: never approve a paid job for the operator; safest reversible default |
| R-7 | A client key is recorded on the job as its principal (`client:<name>`), so jobs, resumes and idempotency keys are each client's own (the B-039 owner rule already does this for delegations) | B-039 `require_owner`; one key per person |
| R-8 | The Fabric service token is refused on `/mcp`; the local agent token does not exist in the cloud. Only client keys reach `/mcp` there | DEC-0024; D16 K2 |
| R-9 | State: the data root (SQLite store, `runs/`) is snapshotted into Postgres (restore at start, save after a job changes state, at most every 30 s, and at SIGTERM), keeping three snapshots | CMO C-6; one dyno, no concurrent writer |
| R-10 | Deploy: `scripts/cloud_deploy.py` sends a tarball of a checked commit through the Heroku Build API with the key from Observatory and refuses without a green-gate receipt for that commit | CMO C-7; operator «мы задеплоим»: the team's main redeploys after gates |

### Spend record

Heroku about 12 USD a month (Basic plus essential-0) on the operator's team account, inside the estate limit of
USD 1 000 a month (global rules). Research and tool calls from the cloud are paid by the Prowl wallet and the cloud
OpenRouter key, and every paid job waits for the operator's approval (R-6), so no call spends without a person.

## REQ

| REQ | Requirement | Check |
|---|---|---|
| REQ-1 | The local instance works as before: without cloud variables no path changes | full suite unchanged; loopback guard tests |
| REQ-2 | Cloud mode answers only https requests for its own origin; the well-known document answers 401 with no body without the service token | tests of the guard and of `/.well-known/fabric-service` in cloud mode |
| REQ-3 | `/mcp` in the cloud takes only a client key; a missing, wrong, revoked or out-of-scope key is refused; the service token is refused | tests per case |
| REQ-4 | A client's jobs carry `client:<name>`; another client cannot read, resume or replay them | tests |
| REQ-5 | Client keys: add prints once, only SHA-256 stored, rotate replaces, revoke refuses at once, list shows no key | tests on the file store and the Postgres store (fake driver) |
| REQ-6 | The page opens only from a Dashboards one-time code; the cloud cookie is `__Host-`, `Secure` | tests |
| REQ-7 | State survives a restart: snapshot and restore, hash checked, a damaged snapshot is refused | tests; live `heroku ps:restart` |
| REQ-8 | No provider key in logs, answers or the page; provider keys only in config vars | tests of degraded and errors; reading Heroku logs |
| REQ-9 | Deploy refuses a commit without a green receipt | test of `cloud_deploy.py` |
| REQ-10 | The team copy is built from a named commit, carries `Source-Revision`, `.copy/upstream.json`, the same LICENSE, no forbidden path, and refuses an unported copy commit | tests of the builder |
| REQ-11 | A teammate knows how to get a key and connect Claude Code, without any provider key in the text | onboarding doc; em-dash check 0 |
| REQ-12 | The cloud instance shows in Fabric Dashboards as an online service | `register_cloud.py` writes a valid remote descriptor; live `list_services` after deploy |

## Design by module

**M1. Cloud mode.** `prowl-research-service cloud-run` (or `PROWL_RESEARCH_CLOUD=1`) reads `PUBLIC_ORIGIN`, `PORT`,
`FABRIC_SERVICE_TOKEN`, `DATABASE_URL`, `PROWL_RESEARCH_ROOT`. It binds `0.0.0.0:$PORT`, has no launchd and no 0600
token files, and keeps the instance lock. `create_app` takes a `CloudSettings` (origin, cookie name, secure cookie,
client store); without it everything is the local service byte for byte.

**M2. Guard.** In cloud mode the allowed `Host` is the host of `PUBLIC_ORIGIN`, `X-Forwarded-Proto` must be `https`,
an `Origin` header must equal `PUBLIC_ORIGIN`; the well-known document without the service token answers `401` with
no body; the identity is `instance: cloud`.

**M3. Client keys.** `research_agent/service/clients.py`: `FileClients` (0600 JSON) and `PostgresClients` behind one
interface (`add`, `rotate`, `revoke`, `list`, `verify`). CLI `prowl-research-service client add|rotate|revoke|list`.
On `/mcp` the bearer is verified; the verdict carries `{tier: "client", principal: "client:<name>", caller:
"client:<name>"}` and each `tools/call` checks the scope of its capability: `research.list_runbooks`,
`research.artifact.get`, `research.tutorial` need `read`; `research.run` needs `research.run`; `research.tools.call`
needs `tools.call`.

**M4. State snapshot.** `research_agent/service/snapshot.py`: a tar of the data root (the SQLite file through the
backup API) into table `prowl_research_snapshot(id, taken_at, sha256, size, body)`; restore before the store opens;
save after job events, debounced 30 s, and at shutdown; three kept. `psycopg` is an optional extra `[cloud]`.

**M5. Deploy.** `Procfile` (`web: prowl-research-service cloud-run`), `.python-version`, `requirements.txt`
(`.[cloud]`). `scripts/cloud_deploy.py`: a tarball of `git archive <sha>` through Heroku's sources and builds API,
refused without `.task-pipeline/receipts/<sha>.json` naming a green suite. `scripts/cloud_config.py` sets config vars
from Observatory through `use_secret.py run`, printing only names.

**M6. Fabric.** `scripts/register_cloud.py` writes `prowl-research.cloud.json` (placement `remote`, origin without
path, `lifecycle.manager: none`, token file 0600, `peer.custody: organization-managed`).

**M7. Team copy.** `scripts/build_team_copy.py <sha> <dir>`: `git archive` of the commit, forbidden paths removed
(`docs/reports/`, `runs/`, `evals/` raw data, `.task-pipeline/`), `.copy/upstream.json`, the original's LICENSE, and
a refusal when the copy has a non-service commit after its last build.

**M8. Documents.** `docs/CLOUD.md` (architecture, operator runbook), `docs/TEAM-ONBOARDING.md` (Russian: key, Claude
Code, what the team can call), `SECURITY.md`, `docs/FABRIC.md`, README, CHANGELOG, scenarios CORE-20…CORE-23,
backlog B-099, B-100, HANDOFF.

## Plan

| Task | Module | Depends on | Done when |
|---|---|---|---|
| T1 | M3 | | client store tests green (file and fake Postgres) |
| T2 | M1, M2 | | cloud settings and guard tests green; local suite unchanged |
| T3 | M3 on `/mcp` | T1, T2 | `/mcp` refusal and scope tests green; jobs carry the client principal |
| T4 | M4 | | snapshot round trip, hash check, damaged snapshot refused |
| T5 | M5 | T2, T4 | Procfile and requirements; `cloud_deploy.py` refuses without a receipt |
| T6 | M6, M7 | | descriptor writer and copy builder tests green |
| T7 | M8 | T1–T6 | docs, scenarios, backlog, em-dash check 0 |
| T8 | release | T7 | PR merged, tag, local install updated (local instance unchanged) |
| T9 | copy and deploy | T8 | copy repository created and built; Heroku app, config vars, first client key, live `tools/list`, restart keeps state, Dashboards shows the service |

Human gates: none for T1–T8. T9 creates a private repository in `appvillis-com` and a paid Heroku app (record above);
the operator said «мы задеплоим», so T9 runs on that word. A dedicated prowl.chat key with a spend limit is issued
from the operator's Prowl account; until then the existing key is used and the gap is named in `degraded`.
