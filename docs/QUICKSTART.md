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

`install.sh` is **promptless** — there is **no component menu**. One command installs
the sensible default set:

| Installed by default | What you get |
|----------------------|--------------|
| **Core** *(always)* | scrape · store with provenance · Boolean search · export |
| **Analysis** | keywords · framing comparison · sentiment |
| **Compression** | faster on-disk storage of the corpus |

Local-LLM / Ollama setup is **not** part of the installer — it lives entirely in the
app's **Settings → AI** tab (see §D). Override the installed set with the
`OO_COMPONENTS="…"` env var (e.g. `OO_COMPONENTS="analysis,nlp"`); re-running
`./install.sh` is idempotent and only installs what's missing.

**It then auto-launches.** The installer creates an **Open Omniscience** launcher (apps
menu + Desktop) and opens the app in your browser. To start it again later:

- open your applications menu and search **Open Omniscience**, **or**
- double-click the **Open Omniscience** icon on your **Desktop**.

A small terminal window appears, the app starts, and your browser opens to
**http://127.0.0.1:8000**. **Close that window (or use the top-bar power / shutdown
button) to stop the app.** (On macOS the launcher is `Open Omniscience.command` on your
Desktop.)

**First launch.** On a fresh install the app walks you through a short one-time setup
*before* the main UI: **choose your language → read and accept the legal terms**
(declining **uninstalls** the app, via typed confirmation) **→ create your corpus
passphrase**. The corpus is **encrypted at rest by default** (SQLCipher 4) and there is
**no recovery** for a lost passphrase (a lost passphrase costs re-collection time — the
corpus is rebuilt from the web). The app then boots **offline (airplane mode)**;
switching online passes **one consent popup** that names the action and shows your local
interface IPs before any request goes out.

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
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
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

### On Tails

Debian/Ubuntu/Tails ship the stdlib `venv`/`ensurepip` in a **separate apt package**, so
`python3 -m venv` fails until it is installed. `install.sh` now installs it
**automatically** — on Tails that needs an **administration password** (set it at the
Welcome Screen; it is off by default) and a working **Tor connection** (apt downloads over
Tor). Opt out with `OO_NO_APT=1` if you prefer to run apt yourself.

Two honest caveats specific to Tails:

- **Python version.** Tails is Debian 12 → **Python 3.11**, but the app targets **3.13**.
  You must have a 3.13 interpreter available and point the installer at it
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 and its `python3.13-venv` package are **not**
  in Tails' default repositories.
- **Amnesia.** Anything apt-installed — and the whole `.venv` — is **lost on reboot** unless
  it lives on Persistent Storage: add the venv package via **Persistent Storage → Additional
  Software**, and keep the checkout + `OO_DATA_DIR` on the persistent volume.

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
> the markets, political-spectrum and law/IP catalogs — **~3,395 unique domains in
> all**) are seeded automatically — so you can start ingesting immediately.
> (These counts **drift** as the catalogs grow; the live figure is whatever
> `configs/*.yml` currently holds.) Re-seeding is idempotent. Disable auto-seed with
> `OO_AUTOSEED=0`; re-seed manually with `python scripts/seed_sources.py` or
> `POST /api/sources/seed-defaults`. Feed URLs/robots policies change over time; the
> ethical fetcher refuses anything it can't confirm, so prune/extend the list to suit
> your investigation.

**In the UI:** **go online** once (the airplane-mode toggle → one consent popup) and
**collection runs itself** in the background — stratified across languages and source
tags, robots-respecting and rate-limited. Then **search from the omnibar** (top bar or
Ctrl/⌘-K) — pressing Enter spawns an **analysis window** where you filter, read,
run Boolean queries and **export** (CSV/JSON, methods appendix, signed evidence). You
can still add a source and *Ingest* a single feed or URL manually from **Settings →
Collect / Sources**.

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

## D. Analysis capabilities

All are local-first and degrade loudly (never fabricate). Full schemas at `/docs`.

**Local LLM (Ollama) — Phase 2.** Set it up from **Settings → AI**: an in-app,
**checksum-verified** Ollama installer (Linux) plus a **model download queue** (real
byte progress, cancel), an active-model picker and an editable-prompts panel. Or install
Ollama yourself from **ollama.com** and `ollama pull llama3.2:3b`. Model pulls egress
over **clearnet via the Ollama process** (not the app's Tor path) — disclosed at
consent. The top-bar LLM pill shows live status (click it to open Settings → AI); each
search result has **Summarize** and **Translate** buttons. API:
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
fabricated and was quarantined off the working tree; see
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Signed evidence bundles — Phase 5.** The analysis window's **Export signed
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
