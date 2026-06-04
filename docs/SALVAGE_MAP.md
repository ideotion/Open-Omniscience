# Salvage Map — what's real, what's broken, what's fabricated

> Companion to `docs/ACTION_PLAN.md` (Phase 0.3). Verdict per module:
> **KEEP** (sound, minor cleanup) · **FIX** (right idea, broken implementation) ·
> **REWRITE** (concept ok, code unsalvageable) · **QUARANTINE/DELETE** (fabricated or dead).
> Audit refs like `(P1-1)` map to the audit report.

## The spine (`src/`) — this is what Phase 1 makes trustworthy

| Module | Verdict | Notes |
|--------|---------|-------|
| `src/api/main.py` | **FIX** | Deprecated `@app.on_event` (→ lifespan); broken search parser & `bindparam` misuse (P1-5/6/7); `datetime.utcnow()`; CORS `*`+credentials; unauth `/metrics`; version string `0.02`. The endpoints/shape are salvageable. |
| `src/database/models.py` | **FIX** | `get_session()` defined twice (P1-11); `create_all` + monitor thread run **at import** (P0-11); `check_same_thread=False` global session (P0-10). Models themselves are fine. |
| `src/database/async_db.py` | **KEEP** | Correct async session; currently unused by the API — wire it or fold its pattern into the sync `Depends` session. |
| `src/compliance/ethical_scraper.py` | **KEEP** | Correct robots/rate-limit/UA implementation. The bug is that it's **never called** — make it the only fetch path (P1-3). |
| `src/main_pipeline.py` | **FIX** | `_ingest` does robots-checked `download_page` then **throws the result away and raw-`requests.get`s** (P1-1), plus a raw fallback on blocked URLs (P1-2). Route exclusively through `ethical_scraper`. |
| `src/scraper/scraper.py` | **FIX** | robots check **fails open** on error (A6); hardcoded https-only (A7). |
| `src/utils/security.py` | **REWRITE** | `sanitize_sql_input` is a regex keyword blocklist that silently corrupts queries (P0-8) — delete it; rely on parameterized queries. `hash_password` silently falls back to single-round SHA-256 (P0-9) — remove or make bcrypt mandatory. |
| `src/database/query_optimizer.py` | **FIX** | f-string SQL with `table_name`/`index_name` (P0-7). Parameterize or whitelist identifiers. |
| `src/database/search.py` | **REWRITE** | Replace string-hack Boolean parsing with SQLite **FTS5 `MATCH`** (P1-5/6/7). |
| `src/api/performance.py` | **FIX** | `session.execute("SELECT 1")` raw string (B9); concurrency anti-patterns. |
| `src/ingestor/*` | **KEEP/FIX** | `deduplicator`, `normalizer`, `url_utils` look usable; consolidate the two duplicate-detector implementations (`ingestor/duplicate_detector.py` vs `deduplicator.py`). |
| `src/crypto/*` (`merkle_tree`, `provenance`, `signatures`) | **KEEP** | Real crypto; `provenance.py` has an f-string `LIMIT` injection (C5) to fix. Wire into reporting in Phase 5. |
| `src/audit/chain_of_custody.py` | **KEEP** | For Phase 5 defensible reporting. |
| `src/llm/*` (`ollama_integration`, `llm_service`, `model_manager`) | **FIX** | HTTP-to-Ollama is the right design; remove fake-async / `get_event_loop` patterns; fix hallucinated default model tag (`gemma4:e2b`). Phase 2. |
| `src/services/keyword_extractor`, `link_analyzer/*` | **FIX (later)** | Enrichers; needs `[analysis]` extra. `link_analyzer/source_scraper.py` has dead/false "respects robots" claims (P1-4) — route through `ethical_scraper`. |
| `src/email_intelligence/*` | **KEEP (Phase 4)** | IMAP + parsing scaffold; `attachment_handler` lazily imports `pytesseract` (only heavy import left in `src/`). |
| `src/config/settings.py` | **FIX** | Make one source of truth for the app version (P2-2). |

## Pillars (standalone trees, not imported by the core)

| Pillar | Verdict | Notes |
|--------|---------|-------|
| **Pillar 2** (scientific rigor) | **KEEP/HARDEN** | Most genuinely-implemented (real scipy/statsmodels). Becomes the "honesty gate" in Phase 2.3. |
| **Pillar 3** (deception defense) | **QUARANTINED (partial)** | deepfake/propaganda/cognitive-bias/bot detectors → `quarantine/pillar3_analysis/` (fabricated). `metadata_validator.py` (real EXIF) is the piece to revive first; `multimodal`/`network_analyzer` remain experimental + heavy-dep. |
| **Pillar 4** (monitoring/alerts) | **REWRITE** | Health checks are simulated (`await asyncio.sleep(0.1); status = HEALTHY`, P1-8); threat-intel/STIX-TAXII don't exist. Real source-uptime + corpus anomaly alerts are achievable in Phase 4. |
| **Pillar 5** (financial) | **DESIGN-ONLY (0%)** | Per its own README. Park until Phase 3; pick one vertical. |
| **Pillar 6** (rare-earth) | **DESIGN-ONLY (0%)** | Per its own README. Unit-normalization math wrong by ~1000× (oz/kg) and no currency conversion (P1-9). Park until Phase 3. |

## Docs / infra

| Item | Verdict |
|------|---------|
| `requirements*.txt` ×3, `pillar*/requirements.txt`, `configs/python/pyproject.toml` | **DELETED** — replaced by root `pyproject.toml` (Phase 0.5). |
| `install.sh` | **REWRITE** (Phase 1.7) — unconfirmed `rm -rf` (P0-1), unverified `curl\|sh` (P0-2), `2>/dev/null` swallows pip errors (P0-3), hallucinated model, hardcoded `REPO_BRANCH=0.03`. |
| `docs/qa/FINAL_QA_REPORT.md` and sibling QA/debug reports | **DELETE/REPLACE** — self-contradicting, fictional ("Vibe Code, World-Class QA Engineer"). |
| `.github/workflows/*` | **REWRITE** — reference nonexistent `requirements-all.txt`; `main`/`master` split; `uvicorn --daemon` (no such flag). |
| `src/static/` front-end | **FIX** (Phase 1.8) — vendor all assets, drop CDN/Tkinter remnants. |

## One-line summary
The **core spine is salvageable**: real DB models, a correct (but unwired) ethical
scraper, real crypto, a sane FastAPI skeleton. The damage is in the **glue** (double
fetch, fake sanitizer, string-hack search, import-time side effects) and in the
**fabricated pillar analytics**. Phase 1 fixes the glue; the pillars are rebuilt
honestly, one at a time, later.
