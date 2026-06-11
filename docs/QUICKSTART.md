# Quickstart — running the prototype

This is the **trustworthy core** (the `0.0.x` pre-alpha; the running app reports
its exact version): add a source → ethically scrape it → store with provenance →
Boolean full-text search → export. Local-first, loopback only, no accounts.

---

## 0. The easy way — one command, then double-click to run

If you just want to use the app (no command-line knowledge needed afterwards):

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

> **Inspect before you trust.** Piping a script into your shell runs code on your
> machine. The bootstrap is deliberately tiny — read it first if you like
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh)); all it does is check for
> git + Python 3.13, clone this repo into `~/open-omniscience`, and hand off to
> the in-repo `./install.sh`. You can equally clone yourself and run `./install.sh`.

`install.sh` then shows a small menu (a boxed TUI if `whiptail` is present,
otherwise plain prompts) where you choose:

| Component | What you get |
|-----------|--------------|
| **Core** *(always)* | scrape · store with provenance · Boolean search · export |
| **Analysis tools** | keywords · framing comparison · sentiment |
| **Local LLM tools** | summarize & translate via **Ollama** (optionally installs Ollama + a small model for you) |

You can re-run `./install.sh` any time to **add the LLM tools later** — it's
idempotent and only installs what's missing.

**Then just double-click to launch.** The installer offers to create an
**Open Omniscience** launcher. To start the app afterwards:

- open your applications menu and search **Open Omniscience**, **or**
- double-click the **Open Omniscience** icon on your **Desktop**.

A small terminal window appears, the app starts, and your browser opens to
**http://127.0.0.1:8000**. **Close that window to stop the app.** (On macOS the
launcher is `Open Omniscience.command` on your Desktop.)

Prefer the terminal? `cd ~/open-omniscience && ./scripts/launch.sh` does the same.

**Check or remove it later:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. On a Qubes OS Debian AppVM (the target)

Qubes resets an AppVM's root filesystem on every boot; only `/home` (and
`/usr/local`, `/rw`) persist. So system packages go in the **TemplateVM**, and the
app + virtualenv + database live under `/home` in the **AppVM**.

**1. In the TemplateVM (once):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Shut the TemplateVM down, then **reboot the AppVM** so the packages are visible.

**2. In the AppVM (as your user, no sudo):**
```bash
./install.sh                      # interactive menu: pick components, optional launcher
# or non-interactively (Core + Analysis, creates the launcher):
./install.sh --appvm
```

**3. Run it (binds to 127.0.0.1 only):**
Double-click the **Open Omniscience** launcher (apps menu / Desktop), or:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Open **http://127.0.0.1:8000** in the AppVM browser.

The server never listens off-loopback. To go fully offline after a run, detach the
AppVM's NetVM — the UI has no external dependencies and keeps working on stored data.

---

## B. Local dev run (any Linux with Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Useful env vars: `OO_DATA_DIR` (where the SQLite DB + data live), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (per-host politeness delay, seconds).

### Upgrading an existing database

Fresh installs build the schema automatically (`init_db()`), and the database is
stamped at the current migration baseline. When a future release changes the
schema, upgrade an existing database with:
```bash
alembic upgrade head
```
`alembic check` reports whether the models and migrations are in sync (CI guards this).

---

## C. The end-to-end loop (UI or API)

> **Sources are preconfigured.** On first launch (or during `install.sh --appvm`)
> the curated catalogs (`configs/sources.yml` ~3,200 public-interest outlets, plus
> the markets, political-spectrum and law/IP catalogs — ~3,180 unique domains in
> all) are seeded automatically — so you can start ingesting immediately.
> Re-seeding is idempotent. Disable auto-seed with `OO_AUTOSEED=0`; re-seed
> manually with `python scripts/seed_sources.py` or `POST /api/sources/seed-defaults`.
> Feed URLs/robots policies change over time; the ethical fetcher refuses anything
> it can't confirm, so prune/extend the list to suit your investigation.

**In the UI:** pick (or add) a source → *Ingest* a feed or a single URL → *Search*
with Boolean operators → *Export* CSV/JSON.

**Via the API:**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

Interactive API docs: **http://127.0.0.1:8000/docs**.

---

## D. Analysis capabilities (Phases 2–5)

All are local-first and degrade loudly (never fabricate). Full schemas at `/docs`.

**Local LLM (Ollama) — Phase 2.** Easiest: choose **Local LLM tools** in
`./install.sh` (it can install Ollama and pull a small model for you). Manually:
install Ollama, then `ollama pull llama3.2:3b`. The UI header shows LLM status;
each search result has **Summarize** and **Translate** buttons. API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
If Ollama isn't running, these return HTTP 503 with a clear message — not a fake summary.

**Commodity prices + honest correlation — Phase 3.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
Correlation returns a real coefficient + p-value + n from scipy (Pearson/Spearman),
with a "correlation ≠ causation" caveat; too little overlap → `insufficient_data`.

**Monitoring — Phase 4.** `GET /api/monitoring/health` performs real reachability
checks (through the ethical fetcher); `GET /api/monitoring/anomalies` flags
article-volume spikes by z-score. **Email:** `POST /api/sources/{id}/ingest-email`
(IMAP) folds messages into the same searchable corpus.

**Image metadata verification — Phase 4.** `POST /api/verify/image-metadata`
(upload an image) returns its format, dimensions, EXIF and GPS with plain factual
observations (e.g. editing-software tag present, no capture timestamp). Scoped
honestly as *metadata checks* — **not** deepfake/manipulation detection (that was
fabricated and is quarantined).

**Signed evidence bundles — Phase 5.** The search panel's **Export signed
evidence** button (or `POST /api/reports/evidence`) produces a Merkle-rooted,
Ed25519-signed bundle. Anyone can verify it offline, without this app:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Chain of custody — Phase 5.** The **Chain of custody** UI panel tracks signed,
tamper-evident provenance and lets you toggle its behaviour at runtime:
post-quantum signatures, anchoring mode (offline `local` vs Bitcoin-anchored
**OpenTimestamps**), and auto-logging on ingest. Toggles are *preferences* — the
panel shows the **effective** state, so nothing claims to be on when its extra
isn't installed. API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Full model, threat model, and privacy caveats: [USER_MANUAL.md](USER_MANUAL.md).

---

## What "ethical ingest" guarantees

- robots.txt is fetched, cached per host, and **fail-closed**: if it can't be
  confirmed (network error, timeout, 5xx, or a restricted 401/403), the URL is
  **not** fetched.
- A per-host minimum interval is enforced (honouring `Crawl-delay`).
- One fetch path, an identifying User-Agent, HTML only for articles — no raw bypass.
- Extraction uses trafilatura; if no real article body is found, nothing is stored
  (no fabricated "No Title / No Content" rows).
- Every stored article carries provenance: source, original URL, canonical URL,
  content hash (used for dedup), fetch time.
