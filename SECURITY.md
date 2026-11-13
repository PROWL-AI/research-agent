
## Local Fabric service

The HTTP service binds 127.0.0.1 only, checks Host/Origin/Fetch-Site, separates host and agent bearer tokens, uses single-use expiring login codes and HttpOnly SameSite=Strict operator cookies. Browser mutations require a custom same-origin header. CSP disallows inline scripts; provider output is escaped as text. MCP caller credentials cannot approve paid jobs: a paid job starts without a person only when it fits the caller's daily allowance (`research_agent/service/allowance.py`, B-100), and every other one waits for the operator. Tokens are regular owned 0600 files; no token enters URLs, argv or logs (the host's one-use login code is consumed without request logging).

The boundary protects against remote pages and accidental cross-service access, not hostile processes running as the same OS user, which can read local files. Caller-provided chain attribution is unverified. This is a single-operator service, not a multi-tenant authorization server. Do not expose the local instance on a LAN or Internet origin. Provider credentials must be managed by the operator's secret consumer, not copied into the repository or dashboard.

## Cloud instance (B-099)

`prowl-research-service cloud-run` is the one mode meant for an Internet origin, behind a TLS-terminating router. It answers only requests whose `Host` is its `PUBLIC_ORIGIN` and whose `X-Forwarded-Proto` is `https`; the well-known document answers `401` with no body without the service token. `/mcp` accepts only client keys (`prc_`, stored as HMAC-SHA256 under a pepper held in the platform's config vars (`CLIENT_KEY_PEPPER`, B-104), scoped, revocable one by one; a refused key's reason is logged, the caller sees 401); the service token is refused there. Each client's jobs carry its principal and are invisible to other clients. A paid job starts on its own only within its key's daily ceiling (at least 10 USD per UTC day); above it, it waits for the operator's approval. Provider keys live only in the platform's config vars; operator scripts set them by name and print names only. Details: [docs/CLOUD.md](docs/CLOUD.md).

## Untrusted text in prompts (B-102)

Pages and tool results are data. Every prompt that quotes one wraps it in a fence whose token is drawn per call and
never occurs in the text (the agents database pattern `untrusted-fence` 1.2.1, vendored in
`research_agent/agent/untrusted_fence.py`); forged fence lines are neutralised and hidden characters removed first. A
suspected injection is logged as `untrusted.suspected` and changes no decision except one: a value that only a raw
flagged as an injection states is never bound into a later tool call. Nothing here makes a model immune; the boundary is
that claims still need a quote found in the stored raw.
