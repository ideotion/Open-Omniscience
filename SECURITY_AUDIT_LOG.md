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
