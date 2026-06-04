# Quickstart — running the prototype

This is the **trustworthy core** (v0.4): add a source → ethically scrape it →
store with provenance → Boolean full-text search → export. Local-first, loopback
only, no accounts. Local LLM and the vertical pillars come in later phases.

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
./install.sh --appvm              # creates .venv + installs the app under $HOME
```

**3. Run it (binds to 127.0.0.1 only):**
```bash
cd ~/open-omniscience && . .venv/bin/activate && open-omniscience
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

---

## C. The end-to-end loop (UI or API)

**In the UI:** add a source (name + domain, optionally an RSS URL) → *Ingest* a
feed or a single URL → *Search* with Boolean operators → *Export* CSV/JSON.

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
