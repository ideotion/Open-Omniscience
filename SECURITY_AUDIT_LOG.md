# Security audit log — Open Omniscience

Append-only proof trail for the application-security audit. Defensive review of the
operator's own, non-production instance. **Read-only / assessment** (no source changed by
this audit). Network treated **OFF** — ingestion evaluated statically and with local,
benign fixtures; **no live external target was ever contacted**; only benign markers used.

- **Date:** 2026-06-08 · **Commit:** `5780172` (0.06 line) · **Stack:** Python 3.13 /
  FastAPI / SQLite (SQLAlchemy ORM + FTS5) / `requests` fetcher / feedparser + trafilatura
  parsers / Ollama (local LLM) / dependency-free vanilla-JS GUI bound to `127.0.0.1`.
- **Defaults adopted:** non-destructive, isolated, benign inputs only, no live external
  access, no production data, report in English.

| # | Action (command / file) | Purpose | Salient observation |
|---|---|---|---|
| 1 | `grep -rE '\.execute\|text(\|\.raw\|f"SELECT\|+ \"…WHERE"' src/` | Find SQL sinks | Only `fts.py` builds SQL from a literal; ORM elsewhere; `async_db.py` uses `select()` (and is unwired). |
| 2 | Read `src/database/fts.py` | Verify the search sink | `search_ids` uses `text("… MATCH :q … LIMIT :lim")` with **bound params**; `build_match` quotes every term + escapes `"`→`""`. No string-built SQL. → **S-009 (positive)**. |
| 3 | PoC: `build_match('oil prices DROP')`, `build_match('a") OR 1=1 --')` | Prove injection-safety | `'oil prices DROP'` → `("oil" AND "prices" AND "DROP")` (SQL keyword = literal data); `a") OR 1=1 --` → **raises `SearchQueryError`** (API → HTTP 400). Injection rejected, never executed → **S-009 Verified**. |
| 4 | `grep -rE 'subprocess\|os.system\|shell=True\|eval(\|exec(\|pickle.\|yaml.load(\|marshal'` | Code/cmd/deser sinks | **None** in live src; all hits are `re.compile` or `yaml.safe_load` → **S-010 (positive)**. |
| 5 | Read `src/ingest/__init__.py` (`EthicalFetcher.fetch`) | Ingestion / SSRF / DoS | Only the **scheme** is validated (`http(s)`); **no IP/host allow/deny** (loopback, private, `169.254.169.254` reachable). `allow_redirects=True` with **no re-validation** of the redirect target; robots checked on the *original* URL only → **S-001 SSRF**. `max_bytes` checked **after** `response.content` (whole body already in memory); gzip auto-decompressed → **S-002 DoS**. Timeout present (30 s). |
| 6 | Read `src/api/ingestion.py` | CSRF reachability | `/api/ingest` requires a JSON body (preflight-gated; CORS allowlist = localhost → cross-origin blocked). But `POST /api/sources/{id}/ingest` and other **no-body POSTs** are *simple requests* → executable cross-origin → **S-003 CSRF**. |
| 7 | `grep CORS/CSP/headers src/api/main.py` | Header posture | `allow_credentials=True` (origins = localhost only) → **S-007**. **No** `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options` anywhere → **S-006**. |
| 8 | `grep innerHTML src/static/index.html` (192 hits); read search-results render (`:3146`) + `cardHtml` | Stored XSS | Ingested fields are escaped via `esc()` (`esc(a.title/content/source/url)`) and the server `view_article` uses `html.escape` → main paths safe (**S-010 positive**). **But** `href="${esc(a.url)}"` (+ server view) has **no scheme allowlist** — a feed `<link>javascript:…` survives `esc()` → **S-005**. `esc()` does not encode `'`. |
| 9 | `grep feedparser/lxml/etree/defusedxml` | XXE | Feeds via `feedparser.parse` (sanitising, entity-safe by default); no raw `etree.fromstring`/lxml with `resolve_entities` in live code → **S-008 (low/residual)**. |
| 10 | Read `export_articles` (`main.py:583`) + PoC | CSV formula injection | `writer.writerow([…, a.title, …, a.content, …])` with **no neutralization**. PoC: a title `=OOAUDIT_MARKER()` is written verbatim (lead `=` preserved) → **S-004 Verified**. |
| 11 | `git check-ignore` (prior audit) + `grep secrets src/` | Secrets / at-rest | No hardcoded secrets in live src; `data/`,`*.key`,`*.db` git-ignored; signing keys `chmod 0600` (`custody/signing.py`). DB/cache files rely on umask + disk/VM encryption → **S-011 (low)**. |
| 12 | Read `src/llm/ollama.py` usage + producers | Indirect prompt injection | Ingested text is summarised/translated by a **local** model; output is **stored + displayed (escaped)**; the model has **no tools/actions** wired → impact bounded → **S-012 (low/info)**. |

**Not performed (scope):** no live external fetch (network off) — SSRF/redirect bypass and
the decompression bomb are reasoned from the code + library behaviour, not fired against a
real host (marked by their static confidence); no active CSRF page run against the live
server (the simple-request reachability is read from the route signatures + CORS config);
no full read of all 236 modules (prioritised the ingest→store→process→present data path,
the query/render/export sinks, and the fetcher).

---

## Hardening log (operator approved applying fixes, on PR #34)

Gated protocol: one root cause per change, verified by re-running its safe PoC, reversible.
Full suite green afterwards (**722 passed, 6 skipped**); new helper files ruff-clean.

| # | Action | Finding | Verification |
|---|---|---|---|
| H1 | `security.py`: add `csv_safe_cell()`; apply in `main.py export_articles` + `catalog/csv_io.write_csv` | S-004 | PoC + `test_security_hardening` parametrized: `= + - @`/TAB/CR neutralized, benign untouched. |
| H2 | `security.py`: add `safe_href()` (http/https allowlist); use in `view_article`; add JS `safeUrl()` + apply to 5 ingested-URL hrefs | S-005 | `safe_href('javascript:…')==''`; `safeUrl` keeps relative + http(s), drops other schemes; JS `node --check` OK. |
| H3 | `main.py`: `csrf_and_security_headers` middleware — refuse cross-origin state-changing requests; add CSP/`X-Frame-Options: DENY`/`nosniff`/`Referrer-Policy` (swagger exempt from strict CSP) | S-003, S-006 | Live: cross-origin POST → **403**; same/no-origin → 200; headers present on `/`; `/docs` CSP-exempt. |
| H4 | `main.py`: CORS `allow_credentials=False` | S-007 | suite green (no flow used credentials). |
| H5 | `ingest/__init__.py`: SSRF guard `_guard_target` (literal-IP block + DNS-resolve check for the real session), manual bounded redirects re-validated per hop, streamed size cap (`_read_body`) with Content-Length precheck | S-001, S-002 | PoC: real `EthicalFetcher().fetch('http://127.0.0.1\|169.254.169.254\|10.x\|[::1]')` → **BlockedTarget**; stub-session tests unaffected (guard gated to the real `requests.Session`). |
| H6 | `paths.py`: `chmod 0700` the data dir (best-effort, POSIX) | S-011 | data dir owner-only; keys already 0600. |
| H7 | `test_repo_invariants.py`: assert no `eval/exec/os.system/shell=True/pickle/marshal/yaml.load` in live src; `test_security_hardening.py`: CSV/href/SSRF/CSRF/headers + search-injection→non-500 | S-009, S-010 | new tests pass; injection-style `/api/articles?query=…` returns 400/200, never 500. |

**Left open (documented residuals):** S-008 (feedparser entity-safe by default — recommend `defusedxml`
for any future first-party XML), S-012 (indirect prompt injection — bounded by the no-tools posture;
recommend explicit data/instruction delimiting + UI labelling of model output).

**Honesty note on confidence:** S-001/S-002 fixes were verified by their safe PoCs against the
*operator's own* fetcher with benign internal targets and stub bodies; no live external host was
contacted. The CSP uses `'unsafe-inline'` for script/style because the UI is inline-heavy — a
nonce-based CSP is a deferred follow-up; the current header still blocks remote script/object/frame
loads and clickjacking.
