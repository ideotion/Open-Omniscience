## 2026-10-15 — redirect bypass: host lists on the wiki, ORES and DuckDuckGo sessions (PR #1393)

The parked LOW from the sink sweep (`/mnt/project-files/rc-diagnostics/sink-sweep-2026-10-13/LOW-redirect-bypass.md`): the Wikipedia/Wikimedia client, the ORES client and the DuckDuckGo search followed any redirect from their fixed
endpoints with no host check and no connect-time SSRF guard. requests calls `Session.send` for the first request and again for every redirect hop, and `GuardedSession` only overrode `request`, so the kill switch and the transport
choice ran once and nothing ran on a hop. `GuardedSession.allowed_hosts` (optional, default none) is now checked in `send`, before every request: `EthicalFetcher._refuse_parser_mismatch`, then https only, no userinfo, port 443 only,
and a listed host (an exact host, or a leading-dot suffix meaning any host under it and never the bare domain or an empty label). A refusal is `RedirectRefused`, a `RequestException` that is not a `ConnectionError`, raised before the
request is sent, naming the clause and never the address. Lists: wiki client `wikimedia.org`, `.wikimedia.org`, `.wikipedia.org` (its one shared session also serves pageviews on the bare apex and EventStreams); ORES
`.wikimedia.org`; DuckDuckGo `duckduckgo.com`, `.duckduckgo.com`. `following_session` keys its cache on the list. The sessions that redirect between CDNs by design (dumps, OSM, segmented download, the model installer, statistics,
catalog and entity loaders) stay unlisted and are pinned in `UNLISTED_SESSIONS` with zero slack. Tests: `tests/test_session_host_list.py`, each refusal clause with a test only it can fail, and a mutation matrix over the check
with a green-baseline gate and no survivor. Docs: `docs/SECURITY.md`. Not covered, and said so: the unlisted sessions; no connect-time SSRF scope for these three (the hosts are fixed public ones and the list is the gate).
