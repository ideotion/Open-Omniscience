# Security

## Model

Open Omniscience targets a **single local user** on a **Qubes OS Debian AppVM**:

- Binds to **127.0.0.1 only** (loopback). It must never be exposed on a network
  interface; there is intentionally no authentication/RBAC for this deployment.
- **No telemetry. No data leaves the machine.** LLM inference is local (Ollama, HTTP).
- Outbound traffic happens **only during ingestion**, and only through the single
  ethical fetcher: robots.txt is honoured and **fail-closed** (if it can't be
  confirmed, the URL is not fetched), per-host rate-limited, identifying User-Agent.
  As of the v0.0.7 audit (finding ETH-01) this includes RSS-feed **discovery** —
  it fetches through the same ethical fetcher, with the same guards.
- **One documented exception, now opt-in** (audit finding ETH-02, gated in 0.0.8 per
  RM-03): *Discover by topic* sends your topic query to **DuckDuckGo** (an external
  service) to find candidate outlets. It is **disabled by default** — the endpoint
  refuses with an honest message until you knowingly enable it in **Settings → Advanced → Safety →
  External topic discovery**, which states plainly that the query leaves your machine
  (`OO_DISCOVERY_EXTERNAL=1` for headless use). It is strictly user-triggered — never
  part of ingestion, the scheduler, or any default path. (The browser-rendered `/docs` Swagger page also
  references a CDN for its own assets; the app itself never fetches it.)
- **Every other outbound call is user-consented and off the default/boot path.** For
  completeness, the full set of endpoints the app can reach beyond article ingestion,
  each by explicit user action:
  - **DuckDuckGo** — the opt-in *Discover by topic* channel above.
  - **Open-Meteo** (`src/weather/openmeteo.py`, `archive-api.open-meteo.com`) —
    weather-context reanalysis, fetched only when you click "fetch" on a corroboration
    Lead. CC BY 4.0, disclosed at the point of use.
  - **Official-statistics endpoints** (`src/stats/fetch.py`: World Bank
    `api.worldbank.org`, Eurostat) — official figures, fetched on click; a tracked
    figure can auto-refresh on the scheduler's markets pass only if you subscribed it.
  - **GitHub releases API** (`src/llm/installer.py`, `api.github.com/repos/ollama/…`) —
    to fetch the official Ollama installer and its attested `sha256` digest when you run
    the in-app installer.
  - **Ollama's own model pulls** — when you pull a model, Ollama downloads it over
    **clearnet via its own process** (not our fetcher, not Tor); this is disclosed at the
    consent step.

  All of the above are gated behind the airplane kill switch: while offline is engaged
  the request is refused before any socket is opened (see *Data at rest & airplane mode*).

## Data at rest & airplane mode

- **Encrypted by default (SQLCipher 4).** A new corpus is created encrypted, opened with
  a passphrase the user chooses at first launch and re-enters at every start. Running a
  **plaintext** store is an explicit opt-out that requires typed confirmation of the risk.
- **No recovery.** There is no recovery and no decryption alternative for the passphrase.
  A lost passphrase costs re-collection time — the corpus is rebuilt from the web, not
  from us — so no recovery key (a second decryption surface) is added.
- **Threat model.** At-rest encryption protects a **seized or copied file** (a machine
  that is off, or a stolen disk image). It **cannot** protect a **compromised, running
  session** — once the store is unlocked the key is in memory. There is deliberately no
  wrong-passphrase rate-limiting: an attacker who can brute-force already has the file and
  works offline, so backoff would only punish the honest fat-finger user; the honest lever
  is passphrase length, which the create flow guides.
- **Airplane mode is a socket-level kill switch, not just a per-call convention.** When
  offline is engaged, `src/ingest/airplane.py` installs a process-wide guard over
  `socket.getaddrinfo` / `create_connection` / `socket.connect(_ex)` — and, since
  2026-07-25, over `http.client.HTTPConnection._tunnel` and PySocks' `socksocket.connect`
  as well, because a proxied connection negotiates its REAL destination at an
  application-protocol layer the first three never see. Any **non-loopback** target raises
  `AirplaneModeError` **before** a real socket is opened, so no missed call
  site, third-party library, or DNS prefetch can egress. Loopback (127/8, ::1, `localhost`)
  and AF_UNIX always pass through (the app's own server, a loopback Ollama, the file DB).
  It is transparent while online. `OO_AIRPLANE_SOCKET_GUARD=0` disables the backstop; the
  per-call refusals remain as the friendly layer above it. App boot makes zero network calls.
- **The same patch layer carries a second, independent gate: the connect-time SSRF check**
  (`src/ingest/ssrf_guard.py`, 2026-09-07). It is inert except inside an `EthicalFetcher`
  request on the thread making it, where it refuses any non-public address the request
  resolves to or connects to — closing the window between the pre-fetch check's `getaddrinfo`
  and the one `requests` performs at connect time. One patch layer, two gates, so a call site
  cannot meet one and miss the other; each has its own opt-out
  (`OO_SSRF_CONNECT_GUARD=0` here), and neither flag disables the other.

## Data integrity / chain of custody

- Stored items carry provenance (source, original URL, canonical URL, content hash,
  fetch time).
- Evidence bundles are **Merkle-rooted (domain-separated) + Ed25519-signed**. Verify
  with `scripts/verify_evidence.py <bundle.json> [signer_public_key]` — pass the
  signer's key to prove *provenance*, not just integrity. Verification needs nothing
  but the bundle + key (no DB, no trust in this tool).
- An append-only, hash-chained, **signed custody log** (`src/custody/`) records
  ongoing actions on an item; verify offline with `scripts/verify_custody.py`.
  Signatures are **hybrid Ed25519 + post-quantum ML-DSA** when the `pqc` extra is
  installed (honestly labelled `ed25519` otherwise; hybrid verification requires
  *both* components — never a silent downgrade). Independent time comes from
  **OpenTimestamps** (Bitcoin-anchored); a self-asserted local time is the offline
  default. See `docs/USER_MANUAL.md` for the full model and its limits.
- **Configurable from the UI:** post-quantum signing, anchoring mode
  (local vs OpenTimestamps), and auto-logging on ingest are operator-controlled at
  runtime from the **Chain of custody** panel (or `GET/PUT /api/custody/settings`),
  persisted to `custody_settings.json`. A toggle is a *request*: the UI and API always
  surface the **effective** state, so post-quantum / OpenTimestamps can never appear
  "on" when the supporting extra is not installed.
- **Privacy caveat:** anchoring to a public blockchain is permanent publication and
  can deanonymise; it is opt-in, defaults to the offline local provider, and is
  documented with a warning. Custody auto-logging on ingest is off by default
  (defaulting to the legacy `OO_CUSTODY_ON_INGEST=1` flag until a UI preference is saved).

## Hardening already in place

*(Current state, re-derived from the tree on 2026-09-07 — the 2026-06 audit report further
down is a RECORD of that date and carries its own disposition table.)*

- **Injection sinks.** Parameterized DB access only (no string-built SQL on the live path);
  FTS5 `MATCH` is fully bound, and an injection-style search returns 400 or an empty match,
  never a 500. `bleach` allowlist for any HTML; `bcrypt` required for hashing (no silent
  fallback). No `eval`/`exec`/`pickle`/`yaml.load` sinks, asserted by a repo invariant.
  Untrusted XML (Wikipedia dumps, sitemaps) parses through `defusedxml`.
- **Ingested URLs.** `sanitize_url` strips whitespace before the scheme check, and
  `safe_href` allowlists http(s) before any ingested URL is rendered as a link, so a
  `javascript:` URL in a feed is inert text. Both catch `ValueError` only — an unexpected
  exception reaches the caller instead of becoming an empty string that reads as "unsafe".
- **The fetch path.** Robots fail-closed, per-host rate limits, an honest bot User-Agent,
  bounded redirects re-validated per hop on the page *and* robots fetches, a declared
  `Content-Length` refused up front, and the streamed body aborted mid-read once it exceeds
  the cap (so a gzip bomb never materialises). SSRF is checked twice: the target is resolved
  and validated before the fetch, and — since 2026-09-07 — every address the request actually
  resolves or connects to is validated as it happens, closing the DNS-rebinding window
  between the two (`src/ingest/ssrf_guard.py`).
- **The local API.** A cross-origin state-changing request is refused (403) on `Origin`/
  `Referer`; a `Host` header that does not name this loopback API is refused (421, a
  DNS-rebinding guard); every non-Swagger response carries `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `default-src 'self'` CSP with
  `frame-ancestors 'none'`. CORS ships `allow_credentials=False`.
- **At rest.** The data dir is created `0700` (best-effort, POSIX-only) so another local user
  cannot read the corpus, signing keys or custody log; signing keys are `0600`. Full at-rest
  encryption remains the host's job (Qubes/LUKS) — this bounds a shared host, not a seized one.
- **Exported data.** CSV cells beginning `= + - @` or a control character are neutralised
  before export (spreadsheet formula injection).

## At-risk-user safety (Settings → Advanced → Safety, and → Uninstall & wipe)

For journalists working under pressure. Each tool states its honest limit — we never
imply a protection we cannot deliver.

- **Encrypted backup/restore** (`src/safety/crypto.py`, `backup.py`): a passphrase-derived
  AES-256-GCM key (scrypt KDF, per-file salt + nonce) over a live SQLite snapshot. The same
  audited primitives used elsewhere — no bespoke crypto. A wrong passphrase or any tampering
  fails *loudly* (`EncryptionError`); a correctly-decrypted but non-Open-Omniscience payload
  is refused before it can overwrite the corpus.
- **Panic wipe** (`src/safety/panic.py`, under **Advanced → Uninstall & wipe** — kept in a
  section of its own, apart from the tools above, because it cannot be undone):
  best-effort overwrite-then-delete of the whole data dir, requiring an explicit confirmation. **Honest limit:** overwrite-in-place does *not*
  guarantee unrecoverability on SSD/flash or copy-on-write filesystems — only full-disk
  encryption (LUKS/Qubes/Tails) plus key destruction does. Also exposed as a `panic` CLI and
  an `--ephemeral` mode (RAM-only data dir, wiped on process exit).
- **Protected fetch mode** (`src/safety/settings.py`, `fetcher.py`): routes every fetch
  through a proxy you run and sends a generic User-Agent that does not name the tool. **Honest
  limit:** this cannot guarantee anonymity — you must run and trust the proxy (e.g. Tor)
  yourself. Refuses to enable without a proxy URL. HTTP/HTTPS proxies work out of the box;
  **SOCKS** proxies (e.g. `socks5://127.0.0.1:9050` for Tor) additionally need **PySocks**
  (`pip install pysocks`) — there is no packaged extra for it.

These are local and loopback-only; the destructive/state-changing routes are protected by the
same cross-origin refusal middleware as the rest of the API.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** Report it
privately by email to **open-omniscience@ideotion.com** with steps to reproduce;
we aim to acknowledge within a few days. A public GitHub issue is appropriate only
for non-sensitive, already-public security-hardening discussion.

Because the app is loopback/single-user, the main risk surface is the
ethical-fetch path and the evidence-verification guarantees above.

---

# Application-security audit (2026-06)

> ## ⚠ Disposition — this report is a RECORD of 2026-06-08, not a list of open findings
>
> **Every Medium and Low finding below has since been closed in code**, and the report
> was never updated, so it has been reading as a live to-do list for over a year. It is
> kept in full because its threat model, data-flow map and reasoning are still the best
> description of this app's attack surface — but the table below, not the sections after
> it, is the current state. Each verdict was re-derived from the tree on **2026-09-07**
> (`main`, the anchors are what proves it), never taken from a status line.
>
> | # | 2026-06 finding | State on 2026-09-07 | Anchor |
> |---|---|---|---|
> | S-001 | SSRF (CWE-918) | **Closed, including the residual.** Resolve-then-validate on the target, manual bounded redirects re-validated per hop on the page *and* robots paths. The `OO-D2-003` DNS-rebinding TOCTOU the report left open — the one thing "pin to the validated IP" was for — was live-reproduced and closed on 2026-09-07 by validating the address the connection *actually reaches*, not by pinning. | `src/ingest/__init__.py::_guard_target`, `::_guarded_redirect_get`, `src/ingest/ssrf_guard.py`, `tests/test_ssrf_connect_guard.py` |
> | S-002 | Decompression-bomb / size DoS | **Closed.** `Content-Length` refused up front; the real (streamed) body is read in chunks against a running ceiling, so a gzip bomb is aborted mid-read rather than after materialising. | `src/ingest/__init__.py::_read_body` |
> | S-003 | CSRF on no-body POSTs | **Closed.** A middleware refuses any state-changing method whose `Origin`/`Referer` is not loopback (403). A separate `Host`-header guard refuses a DNS-rebinding host with 421. | `src/api/main.py::csrf_and_security_headers` |
> | S-004 | CSV formula injection | **Closed.** Exported cells beginning `= + - @` or a control char are prefixed with `'`. | `src/utils/security.py::csv_safe_cell`, `tests/test_security_hardening.py` |
> | S-005 | `javascript:` URI in an `href` | **Closed.** A strict http(s) scheme allowlist runs on every ingested URL rendered as a link, server-side and in the reader. | `src/utils/security.py::safe_href` (call sites: `src/api/main.py`, `src/api/law.py`, `src/services/duckduckgo.py`) |
> | S-006 | No CSP / security headers | **Closed except one clause.** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `default-src 'self'` CSP with `frame-ancestors 'none'` ship on every non-Swagger response. **Residual, tracked as NET-04:** `script-src` still carries `'unsafe-inline'`, because the UI still has roughly 590 inline `on*=` handlers; landing a nonce-based CSP before they are retired would break the app. | `src/api/main.py::_CSP` |
> | S-007 | CORS `allow_credentials=True` | **Closed.** The app passes `allow_credentials=False`. (`src/config/settings.py` still declares a `cors_allow_credentials` default of `True`; nothing reads it — recorded here rather than changed, because removing a config field is a surface change, not a security fix.) | `src/api/main.py` CORS middleware |
> | S-008 | XXE (residual) | **Posture asserted.** Both untrusted-XML readers parse through `defusedxml`. | `src/wiki/dumpread.py`, `src/ingest/sitemap.py` |
> | S-011 | At-rest file permissions | **Closed at the level that bounds access.** The whole data dir is `chmod 0700` on creation, which is what stops another local user reading the corpus, keys and custody log; individual files keep their umask mode inside it. Best-effort and POSIX-only by design — full at-rest encryption remains the host's job (Qubes/LUKS), as the report itself says. | `src/paths.py::_ensure` |
> | S-009 | SQL/FTS injection — SAFE | **Still safe, and now guarded.** An injection-style search returns 400 or an empty match, never a 500. | `tests/test_security_hardening.py::test_injection_style_search_returns_400_not_500` |
> | S-010 | No eval/exec/pickle sinks | **Still true, and now guarded.** | `tests/test_repo_invariants.py::test_no_dangerous_eval_or_deserialization_sinks` |
> | S-012 | Indirect prompt injection — bounded | **Unchanged posture** (local model, no tools, output escaped and labelled as AI-derived). | — |
>
> The remediation roadmap in §5 is therefore **spent**: items 1–8 are done, apart from the
> `script-src 'unsafe-inline'` clause of item 5.

The defensive security review of the ingest→store→process→present data path, its findings, and the hardening applied.

**In this part:**
- [Security report — Open Omniscience](#security-report-open-omniscience)


---

## Security report — Open Omniscience

**Target:** `/home/user/Open-Omniscience` @ `5780172` · **Date:** 2026-06-08 ·
**Mode:** defensive, read-only assessment (no code changed) · **Network:** OFF (no live
external target contacted; benign markers only) · **Proof trail:** [`HISTORY.md`](HISTORY.md) ·
**Machine-readable:** [`security_findings.json`](archive/security_findings.json) / [`security_findings.csv`](archive/security_findings.csv)

---

### 1. Executive summary & risk posture

Open Omniscience ingests **untrusted web content** (pages, RSS/Atom feeds, emails, market
pages, legal documents) into a local SQLite corpus, analyses it, and renders it in a
loopback-bound browser UI — a classic *hostile-input → store → process → present* pipeline.

**Overall posture: solid core, with defense-in-depth gaps at the edges.** The two highest-risk
classic sinks are correctly handled: **SQL/FTS injection is parameterized and proven safe**
(S-009, Verified PoC — SQL keywords become literal data and injection-style queries are
rejected with HTTP 400), and there are **no command/code-injection or insecure-deserialization
sinks** (S-010 — no shell/eval/exec/pickle/`yaml.load`). The GUI escapes ingested fields, the
ethical fetcher fails **closed** on robots uncertainty, signing keys are `0600`, and no secrets
live in code. **No Critical or High findings.**

The weaknesses that matter are **edge controls around hostile input**, all Medium:

1. **SSRF (S-001) — substantially closed; one residual.** The fetcher resolves and
   validates every target against private / loopback / link-local / `169.254.169.254`
   (cloud metadata), and follows redirects **manually with a per-hop re-validation on
   BOTH the page fetch and the robots.txt fetch** (the robots redirect chain was the
   last gap — it used `allow_redirects=True` and is closed by OO-D2-001).
   **Residual (OO-D2-003, Low/Rare):** a DNS-rebinding TOCTOU window between the
   guard's `getaddrinfo` check and `requests`' connect-time re-resolution. Closing it
   needs connect-time IP pinning (a custom `requests` adapter) and is tracked as
   hardening; it is mitigated by the public-IP-literal block and the curated catalog.
2. **Decompression-bomb / size DoS (S-002):** the 10 MiB cap is checked **after** the whole
   (auto-gunzipped) body is in memory.
3. **CSRF on no-body POST endpoints (S-003):** no token/Origin check; a visited web page can
   trigger scrapes (amplifying S-001), reseeds, or an actor-collapse on the local instance.
4. **CSV/spreadsheet formula injection (S-004, Verified PoC):** ingested titles/content are
   exported unneutralized.
5. **No CSP / security headers (S-006):** no backstop if any escape is missed, and the UI is
   frameable.

Plus Lows: a `javascript:`-URI link vector (S-005), permissive `allow_credentials` CORS (S-007),
at-rest file permissions (S-011), and bounded indirect prompt injection (S-012).

**Coverage statement.** I traced the ingest→store→process→present data path and every query,
render, and export sink, with safe local PoCs for the FTS and CSV paths. I did **not** perform
any **live external fetch** (network off) — so the SSRF redirect-bypass and the decompression
bomb are reasoned from the code + library behaviour and marked by their static confidence
(Inferred), not fired against a real host; I did not run a live cross-origin CSRF page against
the server (reachability is read from route signatures + the CORS config); and I did not read
all 236 modules (prioritised the data path and sinks).

---

### 2. Threat model & data-flow

**Assets:** the corpus + its provenance/integrity (a poisoned corpus → poisoned intelligence);
signing keys & the custody chain; the operator's host & privacy; the GUI session.

**Adversaries:** a malicious website/feed author serving hostile pages; a disinfo actor poisoning
the corpus; a web page the operator merely visits (CSRF); a crafted document/media file; a local
user on a shared host.

**Trust boundaries & STRIDE focus:**

```
 internet ──(B1)──> EthicalFetcher ──(B2)──> parsers ──(B3)──> SQLite corpus
   hostile           [S-001 SSRF,             feedparser/        [S-009 SQL: SAFE;
   pages/feeds        S-002 DoS]              trafilatura         S-004 CSV export]
                                              S-008 XXE(resid)]        │
                                                                       ▼
        browser <──(B5)── FastAPI render ◀──(B4)── analytics + local LLM
        [S-005 js: URI,    [S-006 no CSP,            [S-012 prompt-injection,
         S-003 CSRF]        S-007 CORS]               bounded — no tools]
```
- **B1 internet↔ingestion:** Tampering/DoS/SSRF — **S-001, S-002**.
- **B2/B3 parse↔store:** Injection — **S-009 (safe)**, **S-008 (residual)**; export **S-004**.
- **B4 process/model:** **S-012** (indirect prompt injection, bounded).
- **B5 present↔user:** XSS/CSRF/clickjacking — **S-005, S-006, S-003, S-007**.
- **at rest:** **S-011**.

---

### 3. Findings by severity

> Full schema (attack_vector, impact, evidence, fix, effort/risk) in `security_findings.json`.

#### Critical — none. · High — none.

#### Medium

- **S-001 · Ingestion · SSRF · CWE-918 · Inferred/Likely.** Fetcher checks only the scheme;
  `allow_redirects=True` with no re-validation; robots checked on the original URL only →
  redirect to loopback/RFC1918/`169.254.169.254`. *Fix:* resolve-then-validate (deny internal
  ranges + non-HTTP), manual bounded redirects re-validated per hop, pin to the validated IP.
- **S-002 · Ingestion · Decompression-bomb/DoS · CWE-400/776 · Inferred.** `max_bytes` checked
  after the full (gunzipped) body is materialised. *Fix:* `stream=True` + chunked read with a
  running ceiling; Content-Length precheck; bounded decompression.
- **S-003 · Presentation · CSRF · CWE-352 · Inferred/Likely.** No token/Origin check;
  no-body POSTs (`/api/sources/{id}/ingest`, scheduler, `/api/briefing/refresh`,
  `/api/law/track|seed`, `/api/integrity/collapse/apply_all`) are simple requests executable
  cross-origin. *Fix:* require a custom header (forces preflight) or validate Origin/Referer =
  loopback on all state-changing methods.
- **S-004 · Storage(export) · CSV formula injection · CWE-1236 · Verified (PoC).** Exported
  article cells not neutralized (`=OOAUDIT_MARKER()` survives). *Fix:* prefix cells starting with
  `= + - @`/control chars with `'` in both CSV exporters.
- **S-006 · Presentation · Missing CSP/headers · CWE-16/1021 · Verified (absent).** No CSP,
  `X-Frame-Options`, or `X-Content-Type-Options`. *Fix:* a header middleware with a strict
  `default-src 'self'` CSP (feasible — the UI is dependency-free), `nosniff`, `frame-ancestors
  'none'`, `Referrer-Policy: no-referrer`.

#### Low

- **S-005 · Presentation · `javascript:` URI in href · CWE-79/80 · Inferred/Likely.** Stored
  article URL rendered as `href` without a scheme allowlist (client + server `view_article`);
  `esc()` doesn't block the scheme. *Fix:* allowlist http/https before rendering; else inert text.
- **S-007 · Cross-cutting · CORS `allow_credentials=True` · CWE-942 · Verified.** Unnecessary
  (no cookies/auth); latent if origins widen. *Fix:* set `allow_credentials=False`.
- **S-011 · Storage · At-rest perms · CWE-311/732 · Inferred.** DB/cache/custody files use umask
  (often `0644`); only keys are `0600`. *Fix:* `0700` data dir, `0600` DB/custody/annotations;
  keep documenting host-level (Qubes/LUKS) encryption.
- **S-008 · Ingestion · XXE (residual) · CWE-611 · Hypothesis.** feedparser is entity-safe by
  default; no raw XML parser found. *Fix:* assert the posture; use `defusedxml` for any future XML.

#### Info (positive controls to preserve)

- **S-009 · SQL/FTS injection — SAFE (Verified PoC).** Parameterized `MATCH :q`; terms quoted;
  malformed → 400; ORM filters parameterized; no identifier/ORDER BY interpolation; no
  second-order query building found. *Keep* + add a 400-not-500 regression test.
- **S-010 · No injection/deser sinks; robots fail-closed; output encoding; keys 0600; no secrets.**
  *Keep as invariants* (extend `test_repo_invariants.py` to assert no `eval/exec/pickle/yaml.load`).
- **S-012 · Indirect prompt injection — bounded** (local model, no tools, output displayed escaped).
  *Keep the no-tools posture*; delimit data vs instructions; label model output as derived.

---

### 4. Data-flow / taint summary (source → sink verdict)

| Untrusted source | Sink | Neutralized? |
|---|---|---|
| GUI search/filter text | SQLite FTS5 `MATCH` / ORM filters | **Yes** — bound param + quoted terms (S-009, PoC) |
| GUI sort/identifier | — | n/a — no dynamic identifier/ORDER BY interpolation found |
| ingested URL / redirect target | `requests.get` (fetcher) | **No** — scheme-only check, redirects unvalidated (S-001) |
| ingested response body | memory (size cap) | **Partial** — cap applied post-download (S-002) |
| ingested feed XML | feedparser | **Yes (default)** — entity-safe library (S-008 residual) |
| ingested title/content | CSV export cell | **No** — formula injection (S-004, PoC) |
| ingested title/content/source | GUI `innerHTML` | **Yes** — `esc()` / `html.escape` on the rendered paths (S-010) |
| ingested URL | GUI/server `href` | **No** — scheme not allowlisted; `javascript:` survives (S-005) |
| ingested text | local LLM prompt | **Partial** — bounded (no tools); output displayed escaped (S-012) |
| cross-origin web page | state-changing POST | **Partial** — JSON endpoints preflight-gated; no-body POSTs are not (S-003) |
| stored data re-read | new query | **Yes** — no second-order query construction found |

---

### 5. Remediation roadmap (by exploitability × impact)

1. **S-004** (S/Low) — neutralize CSV export cells. *Verified, trivial, real operator impact.*
2. **S-003** (M/Low) — Origin/custom-header check on state-changing requests. *Closes CSRF; blunts S-001 amplification.*
3. **S-001** (M/Med) — resolve-then-validate + manual bounded redirects in the fetcher. *Closes SSRF; centralised in one path.*
4. **S-002** (M/Low) — streamed, bounded, decompression-capped fetch.
5. **S-006** (M/Med) — security-header middleware with a strict CSP. *Backstops any future XSS + clickjacking.*
6. **S-005** (S/Low) — http/https scheme allowlist on rendered links.
7. **S-007** (S/Low) — `allow_credentials=False`. · **S-011** (S/Low) — `0600`/`0700` file perms.
8. **S-009/S-010** (S/Low) — regression tests: search injection → 400 (not 500); no eval/exec/pickle in `src/`.

**Quick wins:** S-004, S-005, S-007 are each a few lines and low-risk; S-009/S-010 regression
tests turn the positive controls into guardrails.

---

### 6. Residual risk & assumptions

- **Host/isolation is load-bearing.** The design assumes a **single-user, loopback-only Qubes
  AppVM**. SSRF (S-001) and at-rest exposure (S-011) are substantially mitigated by that boundary;
  the risk rises sharply if the app is run on a multi-user host, a cloud VM with an IMDS, or
  bound beyond loopback.
- **No auth by design.** CSRF (S-003) is the price of a no-auth local API; the right control is an
  Origin/header check, not adding accounts.
- **Untested live behaviour.** SSRF redirect-bypass, the decompression bomb, and cross-origin CSRF
  were reasoned from code/library behaviour, not fired against a live host (network off). They are
  marked Inferred; a follow-up with a controlled local fixture server (operator-confirmed) would
  promote them to Verified.
- **Corpus integrity ≠ truth.** The product is intelligence; a determined actor can still *poison*
  the corpus (flood/echo) within the rules. The 0.06 source-integrity layer surfaces this; it is a
  mitigation of impact, not a barrier to ingestion (by deliberate design).

*Read-only assessment: no source was modified. Every claim traces to a line in
`HISTORY.md`. No weaponized payloads or secrets are included.*

