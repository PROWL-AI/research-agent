
## Local Fabric service

The HTTP service binds 127.0.0.1 only, checks Host/Origin/Fetch-Site, separates host and agent bearer tokens, uses single-use expiring login codes and HttpOnly SameSite=Strict operator cookies. Browser mutations require a custom same-origin header. CSP disallows inline scripts; provider output is escaped as text. MCP caller credentials cannot approve paid jobs. Tokens are regular owned 0600 files; no token enters URLs, argv or logs (the host's one-use login code is consumed without request logging).

The boundary protects against remote pages and accidental cross-service access, not hostile processes running as the same OS user, which can read local files. Caller-provided chain attribution is unverified. This is a single-operator service, not a multi-tenant authorization server. Do not expose it on a LAN or Internet origin. Provider credentials must be managed by the operator's secret consumer, not copied into the repository or dashboard.
