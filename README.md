# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.0.7 (pre-alpha — the `0.0.x` series; see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md))
**License:** [GNU GPLv3](LICENSE)

---

> **On the version number.** This is deliberately versioned **`0.0.7`**, not `0.7`. The
> software is young and still being proven; we **under-state** maturity on purpose
> (honesty over hype). The `0.0.x` series is pre-alpha; only after it consolidates do we
> move to a `0.1` **alpha**, then **beta**, then a `1.0` release. Development cycles are
> named after the version they produce: branch `0.05 → 0.06 → 0.07` ⇒ `0.0.5 → 0.0.6 →
> 0.0.7`. See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Status — v0.0.7: building on the trustworthy core (visual & technical refinements)

> **`0.0.7` is the active cycle.** It builds directly on the `0.0.6` core described
> below — which works and is tested — and focuses on **visual updates and technical
> adjustments** rather than new pillars. Feature notes still tagged `0.06` describe what
> shipped in that cycle and remain accurate; `0.07` refinements land on top of them.

This release rebuilds the project around a small, **genuinely working and tested**
spine. See **[docs/QUICKSTART.md](docs/QUICKSTART.md)** to run it.

**What works now (tested end-to-end):**
- ✅ Add sources; **ethically ingest** an RSS feed or a single URL — robots.txt
  respected **fail-closed**, per-host rate limiting, one fetch path, no raw bypass.
- ✅ Robust article extraction (trafilatura); nothing stored if there's no real body.
- ✅ Unified SQLite store with **provenance** (source, URL, canonical, content hash,
  fetch time) and content-hash / canonical-URL **deduplication**.
- ✅ **Boolean full-text search** (SQLite FTS5): real `AND`/`OR`/`NOT`, `"phrases"`,
  parentheses with correct precedence — fully parameterized.
- ✅ CSV/JSON export; a dependency-free, offline web UI at `127.0.0.1:8000`.
- ✅ **Honest chain of custody**: append-only, hash-chained, **signed** custody log
  (hybrid Ed25519 + post-quantum ML-DSA), timestamping (self-asserted local, or
  Bitcoin-anchored **OpenTimestamps**), and offline verification — all toggleable
  from a **Chain of custody** UI panel, with the effective state always shown
  honestly (see [docs/USER_MANUAL.md](docs/USER_MANUAL.md)).
- ✅ Single `pyproject.toml`, Python 3.13, clean install, full test suite green.
- ✅ **Web UI** — a sidebar grouped by intention (*Investigate · Collect · Trust ·
  System*) covering Home, Search, Insights, Temporal map, Wikipedia, Markets, Collect,
  Sources, Library, Evidence &amp; custody, Settings and an in-app Help/docs reader. Includes a
  command palette (Ctrl/⌘-K), appearance customization in **Settings → Appearance** (themes,
  accent, density, text size, layout, which tools show), a **Library** panel (real row counts + on-disk size),
  inline **source management** (enable/disable, priority, delete), and a
  **World coverage** view (countries covered vs not, sources + topic keywords per
  country). *(The interface described here is the current **default** (`0.05`); see
  [`docs/DESIGN.md`](docs/DESIGN.md) and the Console/Desk
  comparison in [`docs/DESIGN.md`](docs/DESIGN.md).)*
- ✅ **Settings**: theme (system/dark/light) and a SQLite **backup/restore**
  — consistent online-backup download, and a *validated*, snapshotted restore
  (refuses anything that isn't a genuine Open Omniscience database).
- ✅ **Background scheduler**: start/stop + "scrape now", on an interval, in
  `rss`, `crawl`, or `markets` mode — all through the same ethical fetch path.
- ✅ **Bounded recursive crawler**: same-domain article *discovery* (not
  mirroring) with robots fail-closed, rate limiting, and hard depth/page caps.
- ✅ **Markets** (financial / stock / rare-earth): per-source **price-extraction
  rules** turn structured pages into a real `CommodityPrice` series (a number is
  stored only where a CSS selector lands on one — never guessed), with inline
  charts and honest price↔news **correlation** (real coefficient + p-value + n).
- ✅ **Packaged worldwide markets catalog** (~110 sources): stock & securities
  exchanges across every region, commodity/metals/energy/derivatives exchanges
  (incl. GFEX rare-earth futures), commodity & rare-earth price/data sources
  (SMM, USGS, World Bank, Fastmarkets, …) and financial publishers — seeded on
  first run so the app is ready to ingest market coverage. (Live *price* numbers
  still come only from a verified extraction rule or a CSV import — see
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md) — never a guessed selector.)
- ✅ **Official CSV price feeds**: a one-click catalog (FRED, which carries the
  **World Bank "Pink Sheet"** and **EIA** series) plus a **custom-URL importer**
  to pull any CSV series into the commodity store — idempotent, missing values
  skipped, failures reported (never fabricated).
- ✅ **CSV import/export of the source list** (`/api/catalog`) with a documented
  column format + downloadable template; import upserts by domain, bad rows are
  reported, not dropped.
- ✅ **Data-derived worldwide catalog generator** (Wikidata CC0 + optional
  GDELT/Media Cloud merge) for news media **and** official institutions per
  country, with a coverage report driving gaps — see
  [docs/ROADMAP.md](docs/ROADMAP.md).
- ✅ **Keyword & entity analytics** (the **Insights** tab): keywords/entities are
  extracted from ingested article text (people/orgs/places as single units; opt-in
  spaCy `[nlp]` for real NER), stored as mentions with context, and surfaced as
  **trends**, PMI **associations** ("mind-map"), in-context snippets, and an
  **interactive map** (zoomable SVG with city pins by real lat/lon + per-country/
  city tables) — every figure a real aggregate with method + caveat. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).
- ✅ **Temporal map** (the **Temporal map** tab): every locatable, datable signal on one
  zoomable world map under a **time slider** from antiquity to the near future — curated
  historical/scheduled anchors, your **geocoded corpus** (publication date), **dates
  mentioned in article text** (extracted, human-confirmable per-article **date tags**), and
  opt-in live **hazards**. Pins need *both* a coordinate and a date (no coordinate → no pin);
  country-level pins are flagged approximate; "near in space & time" is co-occurrence, never
  cause. Offline coastlines via `scripts/build_world_outline.py` (graticule fallback).
- ✅ **Home briefing** (the **Home** tab, `0.06` Phase A): a **triage feed of honest
  "cards"** — the app gathers and measures in the background, then surfaces candidate
  stories as cards grouped into editorial buckets (*rising · overtold · undertold ·
  investigate · check-the-framing · watch · context · data-integrity*). Each card is
  **one measured signal + evidence links + a caveat**, never a verdict — and there is
  **no composite trust score** (forbidden *in code*, not just docs). Cards compose the
  existing real analytics (trending, per-source VADER framing, Wikipedia flagging,
  honest commodity correlation, market-rule freshness) plus a new pure
  **concentration** primitive (Gini + top-share) powering a *reading-diet self-audit*.
  Pin cards into a **newsletter draft** and **export Markdown** in which every claim
  carries its source links, method and caveat — reproducible journalism. The feed is
  precomputed/cached (instant Home) and refreshed after each scrape. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).
- ✅ **Wikipedia change-tracking** (the **Wikipedia** tab): each language edition is
  a tracked source whose *edits* are the data — one baseline snapshot then
  diffs/deltas (not re-copies), with honest large-edit/revisionism flagging (size
  delta, revert/blank tags, anon/burst, optional **ORES** scores), a flagged-edit
  feed and diff viewer, plus an optional **offline baseline downloader**
  (per-language, resumable, size-probed) kept separate from live tracking. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

- ✅ **Source integrity & anti-amplification** (the **Source integrity** tab, `0.06`
  Phases B–D): the pure `src/signals/` substrate — **concentration** (Gini), **near-dup /
  coordination** (MinHash + LSH → actor graph), **novelty / surprisal** — powers a
  **no-composite-score** source profile and **user-guided anti-amplification**: the app
  *proposes* collapsing a coordinated near-duplicate flood into one actor (with its
  evidence); the user *disposes* — never silent, always flagged, one click to expand,
  reverting reproduces the raw equal counts exactly (a 40-puppet flood is a passing
  acceptance test). Plus **crowdsourced, signed, portable annotation bundles** with an
  opt-in **web of trust** and transparent (dissent-shown, never averaged) aggregation.
  See [docs/USER_MANUAL.md](docs/USER_MANUAL.md) and [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

- ✅ **World law — change-tracking** (the **World law** tab, `0.06` §5): a worldwide
  catalog of **real official primary sources** (national legislation databases, gazettes,
  IP offices — `legislation.gov.uk`, EUR-Lex, Légifrance, govinfo/congress, WIPO Lex,
  USPTO, EPO, …) **seeded by default** and ingestible through the same ethical pipeline.
  A curated set of consolidated-law documents is tracked for change over time (baseline →
  normalised-text diff → honest large-change flag, reusing the Wikipedia engine), and the
  shared near-dup engine surfaces **model legislation** copied across jurisdictions. A
  research mirror, never legal advice — every record links to its official gazette. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

**In progress / next:**
- 🚧 Structured per-edit legal diffs (Akoma Ntoso / ELI) and patent/docket parsing into a
  price-feed-style series, on top of the seeded IP/legal primary sources.
- 🚧 Local LLM analysis via Ollama; email + monitoring; cross-linking Wikipedia
  diffs into the Insights keyword analytics.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full phasing.

**Honesty note:** several previously-advertised "analysis" components (deepfake,
propaganda, cognitive-bias, bot detection) were **fabricated** — returning
hardcoded or heuristic scores while claiming real detection — and have been
**quarantined** (`quarantine/`, see [docs/HISTORY.md](docs/HISTORY.md))
rather than shipped as if they worked.

---

## 🌟 Mission

Open Omniscience is an **ethically oriented**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.
- **NEW:** Analyze, translate, and synthesize content using **local LLM capabilities**

This project is a **Debian-based Linux application** built on Python, leveraging robust crawling capabilities for **ethical scraping**, **duplicate detection**, **data management**, and now **AI-powered analysis**.

---

## 🚀 Getting Started

This is a **local-first, single-user** app for a **Qubes OS Debian AppVM** on
**Python 3.13**, bound to loopback only. Full instructions: **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

**One command (then double-click to run):**
```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```
It clones the repo and runs `./install.sh`, a small menu where you pick **Core**
(scrape/store/search/export), optional **Analysis tools**, and optional **Local LLM
tools** (Ollama + a model) — re-run it any time to add more. It then creates an
**Open Omniscience** launcher in your apps menu and on the Desktop; double-click it
to start the app and open the browser. *(Inspect the tiny
[bootstrap](scripts/bootstrap.sh) before piping any script to a shell, or clone and
run `./install.sh` yourself.)*

```bash
# Local dev (any Linux with Python 3.13):
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q
open-omniscience          # serves http://127.0.0.1:8000 (auto-seeds ~2,100+ sources)
```

On Qubes: `sudo ./install.sh --template` (in the TemplateVM, then reboot the AppVM)
→ `./install.sh`.

The loop: pick/add a source → **ingest** an RSS feed or URL (ethical: robots.txt
fail-closed, rate-limited) → **search** with Boolean operators (`AND`/`OR`/`NOT`,
phrases, parentheses) → **export** CSV/JSON → optionally **summarize** locally via
Ollama and export a **signed, verifiable evidence bundle**.

## 📚 Documentation

The docs are consolidated into a small set of complete guides
([docs/README.md](docs/README.md) is the index):

- **[USER_MANUAL](docs/USER_MANUAL.md)** — the friendly, complete guide: every tab,
  control, setting, workflow, env var and API area, plus per-feature deep-dives
  (briefing, source integrity, annotations, insights, Wikipedia, world-law, markets,
  chain of custody).
- **[QUICKSTART](docs/QUICKSTART.md)** — install + the end-to-end loop.
- **[DESIGN](docs/DESIGN.md)** — what the app is and isn't, the pillar map, GUI reasoning.
- **[ROADMAP](docs/ROADMAP.md)** — design memory (north star), phased plan + status, open questions.
- **[ARCHITECTURE](docs/ARCHITECTURE.md)** — database/config, the HTTP API map, and i18n.
- **[ETHICS](docs/ETHICS.md)** — principles, compliance (GPLv3), third-party notices.
- **[SECURITY](docs/SECURITY.md)** — threat model, local-first posture, the security audit.
- **[CONTRIBUTING](docs/CONTRIBUTING.md)** — how to contribute + the versioning policy.
- **[CHANGES](docs/CHANGES.md)** — changelog · **[HISTORY](docs/HISTORY.md)** — audits & quality archive.

## 🔒 Security model

Single local user, loopback-only (`127.0.0.1`), no accounts/RBAC. No telemetry; no
data leaves the machine (LLM is local via Ollama). Outbound only during scraping,
and only through the ethical, robots-respecting fetcher.

## 📜 License

[GNU GPLv3](LICENSE).

---

*© 2026 Ideotion — built for investigative journalism, honestly.*
