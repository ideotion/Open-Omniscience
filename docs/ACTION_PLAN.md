# Open-Omniscience — Action Plan

**Target environment:** Qubes OS · Debian AppVM · Python 3.13 · single primary user · loopback-only.
**Working branch:** `0.05` (direct, per owner's instruction).
**Companion doc:** [`PRODUCT_SYNTHESIS.md`](PRODUCT_SYNTHESIS.md) (what we're building & why).

> ## Implementation status (v0.4)
> **Phases 0–5 implemented and tested** on the `claude/kind-lovelace-ulpTc` branch
> (full suite green; see [`QUICKSTART.md`](QUICKSTART.md)):
> - **Phase 0/1 — Trustworthy core ✅:** single 3.13 manifest; clean DB session
>   layer (no import-time side effects); one ethical fetch path (robots fail-closed)
>   → trafilatura extraction → dedup/provenance; FTS5 Boolean search with correct
>   precedence; CSV/JSON export; offline vanilla UI; safe Qubes installer; honest
>   docs; security blocklist & silent fallbacks removed; fabricated detectors quarantined.
> - **Phase 2 — Local LLM ✅:** Ollama HTTP client (real model catalog, loud 503
>   degradation); summarize persists with provenance.
> - **Phase 3 — Commodity vertical ✅:** price time-series; correct unit conversion;
>   REAL scipy correlation (coefficient + p-value + n), no fabricated stats.
> - **Phase 4 — Enrichers ✅ (partial):** real source-uptime monitoring + z-score
>   anomalies; email (IMAP) into the unified corpus. Metadata/EXIF still deferred.
> - **Phase 5 — Defensible reporting ✅:** Merkle + Ed25519 signed evidence bundles;
>   standalone offline verifier (`scripts/verify_evidence.py`).
>
> Live integration of the whole flow verified against a running server. Remaining:
> live runs needing the operator's machine (real Ollama model, real scrape targets,
> real IMAP), metadata/EXIF revival, and burning down legacy lint debt.

## Operating rules for this plan

- **Trustworthy core first.** No pillar work until the spine (ingest → store → search → export) is
  genuinely working and tested. A small thing that works beats six that pretend to.
- **Delete before you build.** Fabricated/placeholder code is a liability; quarantine or remove it so it
  can't be mistaken for working functionality.
- **Every task has an acceptance check.** "Done" means the check passes, demonstrably, in the AppVM.
- **No silent failure.** Missing dep/model/source → explicit, visible status. Ever.
- **Commit in small, honest increments** on `0.05`. Commit messages describe *what changed and why*, not
  "fixed everything." Run tests before each commit.
- **Provenance everywhere.** If data enters the store, it carries source + timestamp + hash.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Audit refs like `(P0-1)` map to the audit report.

---

## Phase 0 — Environment & ground truth

Goal: a clean, reproducible 3.13 environment in the AppVM, a single dependency manifest, and the
fabricated code quarantined so the core can be built on solid ground.

### 0.1 Qubes / TemplateVM system preparation
> Qubes reminder: packages installed in the **AppVM** vanish on reboot. Install system deps in the
> **TemplateVM**, then reboot the AppVM. App + venv + data live in the AppVM's `/home` (persistent).

- [ ] In the **TemplateVM** (e.g. `debian-12`/`debian-13`-based), install system deps:
  ```bash
  sudo apt update
  sudo apt install -y python3.13 python3.13-venv python3.13-dev \
      build-essential git sqlite3 ca-certificates curl
  # (Optional, for LLM later) install Ollama in the TEMPLATE so the binary persists:
  #   verify checksum, then install — NOT a blind curl|sh (see 2.1)
  ```
  - [ ] Confirm `python3.13 --version` is available. If the Debian release lacks 3.13, document the
        source (deadsnakes-equivalent / backport) used.
- [ ] Shut down the TemplateVM; **reboot the AppVM** so new system packages are visible.
- [ ] **Acceptance:** in the AppVM, `python3.13 --version` works and survives an AppVM reboot.

### 0.2 App location & virtualenv (persistent)
- [ ] Clone/locate the repo under `/home/user/` (persists). Recommended app/data root:
      `/home/user/open-omniscience` with data in `/home/user/open-omniscience/data`.
- [ ] Create the venv **inside `/home`**: `python3.13 -m venv .venv && . .venv/bin/activate`.
- [ ] **Acceptance:** venv activates; `python -V` shows 3.13; venv path is under `/home`.

### 0.3 Repo inventory & branch
- [ ] Confirm on branch `0.05`. Snapshot current state (`git status`, `git log -1`).
- [ ] Produce a one-page module map: what's real vs fabricated (use the audit's P1-8 table).
- [ ] **Acceptance:** a checked-in `docs/SALVAGE_MAP.md` listing keep / fix / delete per module.

### 0.4 Quarantine fabricated subsystems (don't ship lies)
- [ ] Move out of the import/runtime path (a `quarantine/` dir or clearly-marked `experimental/`):
  - `pillar3/src/analysis/deepfake_detector.py`, `propaganda.py`, `cognitive_bias.py`, `bot_detector.py`
    (fabricated detection) — **keep** `metadata_validator.py` (real EXIF work) for later.
  - `pillar4/` simulated monitoring + nonexistent threat-intel (P1-8) — keep only genuinely-real bits.
  - `pillar5/`, `pillar6/` — design-only (0% per their READMEs); park until Phase 3.
- [ ] Remove the `src/main_pipeline.py` raw `requests.get` double-fetch + fallback (P1-1, P1-2).
- [ ] **Acceptance:** `python -c "import src.api.main"` succeeds with the quarantined code absent; no
      endpoint references a fabricated analyzer.

### 0.5 Dependency reset → one 3.13 manifest
- [ ] Delete the six conflicting manifests (`requirements*.txt`, `pillar*/requirements.txt`,
      `configs/python/requirements.txt`) and the misplaced `configs/python/pyproject.toml` (P2-6).
- [ ] Author a **single root `pyproject.toml`**:
  - `requires-python = ">=3.13"`.
  - Core deps only: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `pydantic>=2`, `pydantic-settings`,
    `requests`, `httpx`, `beautifulsoup4`, `feedparser`, `python-dateutil`, `structlog`, `slowapi`.
  - Robust extraction lib (verify 3.13 wheel): `trafilatura` **or** `readability-lxml` (pick in 1.3).
  - Optional extras: `[llm]` (just `httpx` — Ollama is external), `[analysis]` (`numpy`,`pandas`,`scipy`,
    `scikit-learn`,`statsmodels` — all 3.13-OK), `[dev]` (`pytest`,`pytest-cov`,`ruff`,`mypy`,`hypothesis`).
  - **Remove entirely:** `torch`, `onnx`, `onnxruntime`, `tensorflow`, `pyAudioAnalysis`, `transformers`,
    `librosa`, `opencv-python`, the `jose` (keep only `python-jose` *if* auth is ever needed), `dbpool`,
    `requests-rotating-proxy`, and all the AI-"corrective" comment pins (P2-5, P2-7, P2-8).
- [ ] `pip install -e ".[analysis,dev]"` in the AppVM venv.
- [ ] **Acceptance:** clean install on 3.13 with **no resolver errors**; `pytest` collects (even if 0
      tests yet); `ruff check` runs.

### 0.6 `.python-version` & config truth
- [ ] Set `.python-version` to `3.13`. Make a single source of truth for the app version string (one
      value used by README, API `version=`, `/api/health`) (P2-2).
- [ ] **Acceptance:** `grep -r` shows one consistent version; `.python-version` == 3.13.

---

## Phase 1 — Trustworthy Core (the spine)

Goal: add a source → ethically scrape → dedup/normalize → store with provenance → search (correct
Boolean) → export. Running in the AppVM at `127.0.0.1:8000`, covered by behavioral tests.

### 1.1 Database layer
- [ ] Remove the **duplicate** `get_session()` in `src/database/models.py` (keep one) (P1-11).
- [ ] Remove **import-time side effects**: no `create_all`, no monitor thread on import; move to an
      explicit `init_db()` called from the app lifespan (P0-11, B8).
- [ ] Provide a FastAPI **`Depends`-based session** (`yield`), used by every endpoint; delete manual
      `get_session()/try/finally` patterns (P1-11, B4).
- [ ] SQLite: enable **WAL**, sane timeouts; DB file under `/home/.../data/`. Drop
      `check_same_thread=False` global-session pattern (P0-10).
- [ ] **Acceptance:** unit test opens a session via the dependency, writes & reads a row, closes cleanly;
      importing `models` starts **no** threads and creates **no** tables.

### 1.2 One ethical fetch path
- [ ] Make `src/compliance/ethical_scraper.py` the **only** fetch path; wire it into the pipeline (P1-3).
- [ ] Delete the double-fetch and the blocked-URL raw fallback in `main_pipeline._ingest` (P1-1, P1-2).
- [ ] robots.txt: **cache** per host, handle http+https, **fail-closed** on fetch error (don't scrape)
      (P0-… ethics; A6, A7). Per-source rate limiting actually enforced (A4).
- [ ] Remove the dead robots methods / false "respects robots" claims in
      `link_analyzer/source_scraper.py` or route it through the ethical scraper (P1-4).
- [ ] **Acceptance:** test with a stub robots.txt disallowing a path → that URL is **never** fetched
      (assert no HTTP call); a 2nd fetch of the same host reuses cached robots; rate-limit sleep invoked.

### 1.3 Robust content extraction
- [ ] Replace generic CSS selectors with a real extractor (`trafilatura`/`readability`) producing
      title/body/date/lang; **no silent "No Title/No Content"** — failed extraction is recorded as an
      explicit error, not stored as junk (P1-10).
- [ ] **Acceptance:** test against 3 saved HTML fixtures (real article, paywalled stub, empty page):
      correct extraction for the article; explicit failure status for the others.

### 1.4 Dedup, normalization, provenance
- [ ] Content-hash + canonical-URL dedup; never insert duplicates.
- [ ] Every stored record carries `{source, original_url, fetched_at, content_hash, raw_ref}` (§8 of
      synthesis).
- [ ] **Acceptance:** ingesting the same URL twice yields one row; provenance fields populated; test proves it.

### 1.5 Search rewrite (the headline bug area)
- [ ] Delete `sanitize_sql_input` and its use in the query path (P0-8) — it corrupts queries and is fake
      security.
- [ ] Remove the `bindparam` string-concat hacks and the parenthesis-stripping parser (P1-5, P1-6, P1-7).
- [ ] Implement search via **SQLite FTS5 `MATCH`** (preferred: native Boolean + ranking) **or** a real
      parser (e.g. `pyparsing`) → SQLAlchemy AST. Must honor `AND/OR/NOT`, quoted phrases, and
      **parenthesised precedence**. All values parameterized by SQLAlchemy/FTS.
- [ ] **Acceptance (property/behavioral tests):**
  - `a OR b` returns the **union**; `a AND b` the intersection; `a NOT b` excludes b.
  - `(a OR b) AND c` ≠ `a OR (b AND c)` on a crafted fixture.
  - searching `"AT&T"` and `"oil prices DROP"` returns the right rows (no keyword stripping).

### 1.6 API hardening
- [ ] Replace `@app.on_event("startup")` with a **lifespan** context manager; add graceful shutdown
      (dispose engine) (P3-11, D1).
- [ ] Bind to `127.0.0.1` only; mount `/metrics` on loopback (P0-5).
- [ ] Fix deprecated `datetime.utcnow()`; consistent timezone-aware timestamps.
- [ ] **Acceptance:** app starts/stops cleanly via lifespan; `ss -ltnp` shows listener only on 127.0.0.1.

### 1.7 Installer rewrite for Qubes
- [ ] New installer with **two clearly-separated steps**: (a) *TemplateVM* system deps (printed
      instructions or a `--template` mode), (b) *AppVM* venv + app under `/home` (`--appvm` mode).
- [ ] Safety: **no unconfirmed `rm -rf`** (back up to timestamped dir, confirm interactively) (P0-1);
      **no unverified `curl | sh`** (download → checksum → run) (P0-2); **never** discard pkg stderr
      (P0-3). Check OS **before** touching anything.
- [ ] Real model tag for any LLM hint (no `gemma4:e2b`) (P2-4).
- [ ] **Acceptance:** dry-run on a fresh AppVM: app installs to `/home`, survives AppVM reboot; re-running
      the installer does **not** destroy existing data without an explicit confirm.

### 1.8 Front-end cleanup
- [ ] Vendor all assets (fonts, any JS libs) under `/static`; remove **all** CDN references (P2-10).
- [ ] Remove Tkinter/desktop remnants and `python3-tk` (web UI only).
- [ ] Single canonical `index.html`; service worker only caches existing local files.
- [ ] **Acceptance:** load the UI with the NetVM detached → no failed external requests in devtools.

### 1.9 Tests + honest CI/local runner
- [ ] Behavioral test suite for 1.1–1.8 (pytest); coverage threshold that's *real* (start modest, e.g.
      60% of `src/`, and meaningful).
- [ ] Replace the dead CI (missing `requirements-all.txt`, `.pre-commit-config.yaml`, `mkdocs.yml`,
      `main`/`master` split) with either a working GH Actions workflow **or** a documented local
      `make test` / `make lint` that actually runs on 3.13 (P3-10).
- [ ] Delete/replace the fictional QA reports so they can't mislead (the README already says
      "not functional" — make docs tell one true story).
- [ ] **Acceptance:** `pytest` green locally in the AppVM; `ruff`/`mypy` run; no test references
      quarantined code.

### ✅ Phase 1 Definition of Done
Demonstrate end-to-end in the AppVM: add a source via the UI/API → trigger scrape → see deduped,
provenance-tagged articles → run a Boolean search with parentheses → export CSV+JSON matching the
filter — with the whole flow covered by passing tests and the server bound to loopback.

---

## Phase 2 — Local LLM + Scientific Rigor

Goal: local, honest AI analysis over the stored corpus; numeric outputs carry real uncertainty.

### 2.1 Ollama integration (HTTP only, CPU-first)
- [ ] App talks to Ollama over HTTP (`httpx`); **no** `torch`/`transformers` in the app.
- [ ] Real, existing model catalog; default a **small CPU model** (`gemma2:2b` / `llama3.2:3b` /
      `qwen2.5:1.5b`); large models opt-in.
- [ ] Installer/setup pulls the default model **into `/home`** (persistent) with progress + checksum.
- [ ] **Loud degradation:** if Ollama unreachable or model missing → explicit `503` with a clear message,
      never a fake result.
- [ ] Endpoints are **non-blocking**: plain `def` (Starlette threadpool) or true async `httpx`; remove
      fake-async/`get_event_loop`/per-request executors (P3-1..5).
- [ ] **Acceptance:** with a pulled model, `generate`/`summarize`/`translate`/`extract` work on a stored
      article; with Ollama stopped, the API returns an explicit unavailable status (tested).

### 2.2 LLM wired to the corpus
- [ ] LLM operations run on selected stored articles (summarize, translate, extract entities) and write
      results back **with provenance** (model, prompt version, timestamp).
- [ ] **Acceptance:** summarize a stored article; result persisted and linked to the source record.

### 2.3 Pillar 2 — Scientific Rigor as the "honesty gate"
- [ ] Harden the real stats (scipy/statsmodels); every number surfaced to the user passes through
      uncertainty reporting (CI / n / method).
- [ ] Remove hardcoded confidences anywhere they remain (`confidence=0.8` etc.) (P1-8).
- [ ] **Acceptance:** any analytic value in an API response includes its method + uncertainty basis;
      tests assert no constant-confidence outputs.

---

## Phase 3 — One vertical + correlation (pick ONE)

Goal: prove the cross-reference experience on a *thin but real* slice. **⚠️ DECIDE: financial (Pillar 5)
or commodity (Pillar 6) first.**

- [ ] Minimal real scraper for the chosen vertical (a *few* sources, daily values), ethical path reused.
- [ ] Store time-series alongside articles in the unified DB with link table.
- [ ] Correlation surfaced as a **candidate** relationship with an honest, defined measure; clearly label
      "correlation ≠ causation"; **no fabricated p-values** (P1-8).
- [ ] If commodity: fix the unit-normalization bug (oz→kg factor) and add currency conversion (P1-9).
- [ ] **Acceptance:** for one instrument/element, the UI shows price moves with temporally-nearby
      articles and a stated, reproducible correlation measure.

---

## Phase 4 — Enrichers (one at a time, each real)

- [ ] **Email (P1):** IMAP + RSS-to-email only for v1; parse/clean → into the corpus; encrypted
      credential storage; consent/retention documented (defer Substack/Mailchimp APIs).
- [ ] **Monitoring (P2):** *real* source-uptime checks (actual HTTP, not `sleep; HEALTHY`) (P1-8) +
      anomaly alerts on corpus volume. Defer STIX/TAXII, SMS, chat.
- [ ] **Verification (P2):** ship only the genuine `metadata_validator` (EXIF/ID3) — clearly scoped as
      "metadata checks," not "deepfake detection."
- [ ] **Acceptance (each):** the feature works against a real fixture and is tested; absent deps degrade
      loudly.

---

## Phase 5 — Defensible reporting

- [ ] Wire the existing crypto modules into a **real** chain-of-custody: signed, tamper-evident export
      manifest (hashes + Merkle/GPG) for evidence bundles (P1-14).
- [ ] Reports bundle findings **with** provenance + method + uncertainty.
- [ ] **Acceptance:** export an evidence bundle; an independent script verifies its signature/hashes.

---

## Cross-cutting (apply throughout)

- **Concurrency hygiene:** `get_running_loop()` not `get_event_loop()`; shared, shut-down executors; no
  per-item pools; bounded `gather` with semaphores; fix the broken manual batching (P3-1..7).
- **Logging:** structured logs under `/home`; no `except: pass`; specific exceptions; visible warnings.
- **Docs discipline:** one true README; kill version drift; retire the fictional QA/debug reports.
- **License:** decide GPLv3 vs AGPL-3.0 and apply consistently (synthesis §9.9).

## First session checklist (start here)

1. [ ] Phase 0.1–0.2 — TemplateVM deps + AppVM venv on 3.13.
2. [ ] Phase 0.4 — quarantine fabricated pillars; remove double-fetch.
3. [ ] Phase 0.5 — single `pyproject.toml`; clean install on 3.13.
4. [ ] Phase 1.1 — DB session DI + no import-time side effects.
5. [ ] Phase 1.5 — search rewrite with Boolean tests (the highest-value correctness fix).

> After each numbered item: run tests, commit on `0.05` with a precise message, move on.

---

# Phase 6 — Path to Functional v1.0 (post-merge upgrade)

Phases 0–5 delivered a *working prototype*. Phase 6 makes the **repository** (not
just the running app) genuinely functional and trustworthy. See
[`QUALITY_CHECKUP.md`](QUALITY_CHECKUP.md) for the findings that drive this.

Operating rule unchanged: every item ends green and tested; delete-before-build;
no silent failure; honest provenance.

### 6.1 Purge the dead/fabricated bulk (biggest quality lever)
> ~64% of `src/` is never loaded by the app. Removing it makes the repo readable
> and removes latent footguns. Verify each module is referenced by *no* other
> `src/` or `tests/` file before moving it to `quarantine/` (kept in history).
- [ ] Remove fabricated/over-engineered orphans: `scraper/distributed.py`,
      `llm/optimizer.py`, `database/query_optimizer.py` (also kills its **latent
      SQL injection**), `api/performance.py`, `utils/performance.py`,
      `database/optimization.py`, the superseded `compliance/ethical_scraper.py`.
- [ ] **Keep** legitimately-deferred infra: `database/async_db.py` (future Postgres),
      `database/migrations/*` (Alembic), `main_pipeline.py` (still test-referenced).
- [ ] Decide the fate of the legacy LLM module (`llm/config.py` etc. with the
      hallucinated catalog) — it survives only to satisfy `test_llm.py`. Either
      rewrite those tests against the new `llm/ollama.py` and delete the legacy
      module, or quarantine both together.
- [ ] **Acceptance:** full suite green after each batch; `src/` live-LOC ratio
      rises well above 50%; `ruff check src/` findings drop sharply.

### 6.2 Immediate utility — seed real, ethical sources
- [ ] Ship a small curated list of **real, robots-friendly RSS feeds** (e.g. major
      wire services / public-interest outlets) as `configs/default_sources.yaml`.
- [ ] `scripts/seed_sources.py` (and an installer `--seed` step) to load them.
- [ ] **Acceptance:** a fresh install can ingest and search real news with zero
      manual setup; tested with a fixture feed.

### 6.3 Real migration path
- [ ] Wire Alembic to the live models; generate the baseline + a migration for the
      new tables (`article_analyses`, `commodity_prices`). `init_db()` stays for
      fresh installs; existing DBs upgrade via `alembic upgrade head`.
- [ ] **Acceptance:** an old DB (pre-v0.4 schema) upgrades cleanly; tested.

### 6.4 Harden the live legacy routers
- [ ] Add behavioural tests for the source/keyword/link routers actually wired in
      (`source_management`, `keyword_management`, `keyword_analysis`, `link_analysis`):
      create/list/update/delete a source; extract keywords; classify a link.
- [ ] Fix anything they get wrong (route each through the ethical fetcher; ensure
      parameterized DB access). Replace any remaining `datetime.utcnow()` in *live*
      code with timezone-aware now.
- [ ] **Acceptance:** each live router has at least one happy-path + one error test.

### 6.5 Pillar 2 as the honesty gate
- [ ] Surface the genuine scientific-rigor utilities (real scipy/statsmodels) so any
      numeric the app returns carries method + uncertainty (extend what the
      commodity correlation already does to other computed values).
- [ ] **Acceptance:** tests assert no constant/hardcoded confidence in live outputs.

### 6.6 Lint debt burn-down (safe + incremental)
- [ ] Run `ruff --fix` **per-module on live files only**, never repo-wide (a blanket
      fix once removed intentional back-compat re-exports). Add `ruff format`.
- [ ] Flip CI ruff from advisory to blocking once live modules are clean.
- [ ] **Acceptance:** `ruff check src/<live tree>` clean; CI lint blocking.

### 6.7 Verticals & remaining enrichers (lower priority)
- [ ] One real, thin commodity scraper from an open source (e.g. USGS) feeding the
      existing price/correlation machinery — ethical path reused, fixture-tested.
- [ ] Currency conversion with an explicit, dated FX rate (never a hardcoded guess).
- [ ] Newsletter-API email sources (Substack/Mailchimp) beyond IMAP, if wanted.

## Definition of "Functional v1.0"
A fresh Qubes AppVM install seeds real sources, ingests and searches live news,
summarizes locally via Ollama, exports a verifiable evidence bundle — and the
repository a maintainer opens contains *only code that runs*, is lint-clean on the
live tree, migrates cleanly, and has a test for every exposed endpoint.
