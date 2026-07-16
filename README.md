# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.2.0 (alpha — the data-safety-at-scale cycle; the tagged release awaits the live-corpus scale validation, see [docs/product/SCALE_ROADMAP.md](docs/product/SCALE_ROADMAP.md))
**License:** [GNU GPLv3](LICENSE)

---

> **On the version number.** The `0.0.x` series deliberately **under-stated** maturity
> (honesty over hype) while the software was being proven. The `0.09` cycle consolidated
> the alpha — at-rest encryption, the additive-only + volumes+parity backup story, the
> analysis-window/corpora system — and shipped as **`0.1.0`, the first alpha**. The
> project now opens the **`0.2`** cycle: **data safety at scale** — "the version that
> survives a 100 GB field run" (streaming, bounded-RAM backup/restore, the collector
> out-of-memory fix, unlock-at-scale). `0.2.0` is honest about every limit, not finished;
> beta and `1.0` still have to be earned, and the `v0.2.0` **tag awaits the live-corpus
> scale validation**. Development cycles are named after the version they produce (branch
> `0.06 → … → 0.09 → 0.1 → 0.2` ⇒ `0.0.6 → … → 0.0.9 → 0.1.0 → 0.2.0`; the `0.09` cycle
> culminated in `0.1.0`, and the cycle branch is renamed `0.1 → 0.2` — as `0.09 → 0.1`
> before it). See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Status — v0.2.0: data safety at scale

> **`0.2.0` is the current version** (the cycle branch renames `0.1 → 0.2`, as `0.09 → 0.1`
> before it). The `0.2` cycle hardens the app for **large corpora** — a live multi-day run
> reached ~100–130 GB — with streaming, bounded-RAM backup/restore, the collector
> out-of-memory fix, and unlock-at-scale instrumentation
> ([`docs/product/SCALE_ROADMAP.md`](docs/product/SCALE_ROADMAP.md)); the **tagged release
> awaits the maintainer's live-corpus validation** of the P0 scale set.

> **`0.1.0` — the deeper sense-making alpha, shipped 2026-07-02.** The `0.0.8` cycle shipped in full —
> the whole product-roadmap push (trust hardening, the investigation-recipe cards and
> `/investigate` dashboards, the typed ORM, all 29 audit findings closed — the `0.07`
> audit fixed 20 and deferred 9 with rationale; the 9 were closed in `0.0.8`
> ([`findings.csv`](docs/archive/audits/findings.csv) reads 29/29 FIXED) — the methods
> appendix and provenance-preserving exports, corpus LLM synthesis, offline source
> discovery), then the live-test hardening batches (temporal map + agenda, themes and
> bundled fonts, entity/location/date extractors, network-mode switch, field-test
> instrumentation). `0.0.9` **built out** the parked sense-making layer: space-time
> convergence detection and the **watch-rule attention engine** shipped, the source
> catalog was de-US-centred, **SQLCipher at-rest encryption** and the **unified
> volumes+parity backup** landed, the **corpora / analysis-window** system and the
> **omnibar global-search** rework replaced the old Search tab, and the map became the
> **ooMap choropleth**. Local **AI** (Settings → AI), **newsletter import**, **official
> statistics**, **offline OSM maps** and the **task-manager window** all shipped this
> cycle (see [`docs/FUTURE_DEVELOPMENTS.md`](docs/FUTURE_DEVELOPMENTS.md) for what
> remains). Feature notes tagged `0.06`/`0.07`/`0.0.8` describe what shipped in those
> cycles and remain accurate.

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
  (Ed25519 by default; hybrid Ed25519 + post-quantum ML-DSA when the optional `[pqc]`
  extra is installed and enabled), timestamping (self-asserted local, or
  Bitcoin-anchored **OpenTimestamps**), and offline verification — all toggleable
  from a **Chain of custody** UI panel, with the effective state always shown
  honestly (see [docs/USER_MANUAL.md](docs/USER_MANUAL.md)).
- ✅ Single `pyproject.toml`, Python 3.13; clean install, with the full pytest suite
  green on Linux CI, a type-check ratchet, and advisory cross-OS/style lanes — all
  tracked in CI (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
- ✅ **Web UI** — a **flat sidebar** of data tabs: Home · Insights · World map ·
  Governments · Agenda · Indices · Commodities · Library. There is no **Analysis**
  sidebar tab: an analysis **spawns as its own window** from the omnibar (or the
  command palette), one per query. A **minimal top bar** carries the always-on
  **search** omnibar (also the Ctrl/⌘-K command palette), live status, a
  **task-manager** button, the **airplane-mode** network toggle, a **language
  switcher**, an in-app **Help/docs** reader (the top-bar `?`) and a **power /
  shutdown** button (stops the server; your data is untouched). **Settings** opens
  from the **gear at the bottom of the sidebar**. (Search is the top-bar omnibar —
  there is no separate Search sidebar tab; the full Boolean search opens from it.)
  *Content-first reorg:* the acquisition + management surfaces — **Collect**,
  **Sources**, **Wikipedia**, **Newsletters**, **Statistics**, **Offline map** and
  **AI** — live as **Settings** sections (the sidebar shows the *data*); Source
  integrity's and Evidence & custody's tools moved into **Settings → Safety**.
  Appearance customization in **Settings → Appearance** (themes, accent, density, text
  size, layout; the experimental **Alternative interfaces** gallery), a **Library**
  panel (real row counts + on-disk size), inline **source management** (enable/disable,
  priority, delete), and the **World map** tab's **World coverage** choropleth (sources
  / articles / keywords / tone per country). *(See [`docs/DESIGN.md`](docs/DESIGN.md)
  for the interface's design history.)*
- ✅ **Settings → Data &amp; backup**: one unified **Export / Back up** and **Import**
  flow that handles a corpus of **any size**. Pick a destination folder or drive and it
  **streams** everything into it — the encrypted corpus as independently-authenticated
  **volumes + Reed-Solomon parity** (a corrupt or lost volume can be rebuilt), and the
  large public re-downloadable blobs (models / maps / Wikipedia dumps) copied as-is (no
  2 GiB cap, never the whole archive in RAM). **Restore is additive-only**: it
  **complements** your corpus and **never replaces** it (preview-then-merge: nothing
  deleted, bit-for-bit dedup, conflicts keep your local value and report both). The old
  single-file `oo-backup-2` download and the destructive "replace your corpus" restore
  are **legacy** (the replace path was removed, so no flow can overwrite your data).
- ✅ **Background scheduler**: after you go online (one consent), collection runs
  **continuously** in the background — stratified by language and source tag, one
  source at a time per host, politeness untouched — through `rss`, `crawl`, `markets`,
  `wiki` and `law` passes, all on the same ethical fetch path. Start/stop + "scrape
  now" stay available; airplane mode is the one thing that stops it.
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
  [docs/archive/roadmaps/DESIGN_MEMORY_pre-0.2.md](docs/archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- ✅ **Keyword & entity analytics** (the **Insights** tab): keywords/entities are
  extracted from ingested article text (people/orgs/places as single units; opt-in
  spaCy `[nlp]` for real NER), stored as mentions with context, and surfaced as
  **trends**, PMI **associations** ("mind-map"), in-context snippets, and an
  **interactive map** (zoomable SVG with city pins by real lat/lon + per-country/
  city tables) — every figure a real aggregate with method + caveat. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).
- ✅ **World map** (the **World map** tab): a **World coverage choropleth** of your
  corpus (`ooMap`, no map deps). An **in-map measure picker** colours each country by a
  real dimension — **sources · articles · keyword mentions · mean tone** (tone on a
  diverging scale with the VADER English-only caveat + `n`); no data ≠ zero (a
  distinct **no-data hatch**, never a guessed colour). **In-map controls** switch
  **granularity** (country ↔ continent aggregate) and toggle overlay **layers**: a
  **places** layer (mentioned places, "deduced, never confirmed") and a **signals**
  layer of locatable/datable events under a **time slider** from antiquity to the
  near-future (curated anchors + your geocoded corpus + extracted date tags; "near in
  space & time" is co-occurrence, never cause). Country borders from
  `scripts/build_country_polygons.py`; offline coastlines via
  `scripts/build_world_outline.py` (graticule fallback).
- ✅ **Home briefing** (the **Home** tab, `0.06` Phase A): a **triage feed of honest
  Leads** (investigative starting points, rendered as "cards") — the app gathers and
  measures in the background, then surfaces candidate stories grouped into editorial
  buckets (*rising · overtold · undertold ·
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
- ✅ **Wikipedia change-tracking** (**Settings → Wikipedia**): each language edition is
  a tracked source whose *edits* are the data — one baseline snapshot then
  diffs/deltas (not re-copies), with honest large-edit/revisionism flagging (size
  delta, revert/blank tags, anon/burst, optional **ORES** scores), a flagged-edit
  feed and diff viewer, plus an optional **offline baseline downloader**
  (per-language, resumable, size-probed) kept separate from live tracking. (The
  richer **per-article tracked-changes *timeline* tab** — the living-source view —
  is in progress; see below.) See [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

- ✅ **Source integrity & anti-amplification** (`0.06` Phases B–D; the desk's tools
  now open from **Settings → Safety**): the pure `src/signals/` substrate — **concentration** (Gini), **near-dup /
  coordination** (MinHash + LSH → actor graph), **novelty / surprisal** — powers a
  **no-composite-score** source profile and **user-guided anti-amplification**: the app
  *proposes* collapsing a coordinated near-duplicate flood into one actor (with its
  evidence); the user *disposes* — never silent, always flagged, one click to expand,
  reverting reproduces the raw equal counts exactly (a 40-puppet flood is a passing
  acceptance test). Plus **crowdsourced, signed, portable annotation bundles** with an
  opt-in **web of trust** and transparent (dissent-shown, never averaged) aggregation.
  See [docs/USER_MANUAL.md](docs/USER_MANUAL.md) and [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

- ✅ **World law — change-tracking** (the **Governments** tab, Law section, `0.06` §5): a worldwide
  catalog of **real official primary sources** (national legislation databases, gazettes,
  IP offices — `legislation.gov.uk`, EUR-Lex, Légifrance, govinfo/congress, WIPO Lex,
  USPTO, EPO, …) **seeded by default** and ingestible through the same ethical pipeline.
  A curated set of consolidated-law documents is tracked for change over time (baseline →
  normalised-text diff → honest large-change flag, reusing the Wikipedia engine), and the
  shared near-dup engine surfaces **model legislation** copied across jurisdictions. A
  research mirror, never legal advice — every record links to its official gazette. See
  [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

- ✅ **Governments — official statistics** (the **Governments** tab, Countries subtab;
  fetched from **Settings → Statistics**): a directory of government + international
  statistical producers, ingested through documented machine endpoints (World Bank,
  Eurostat/SDMX). Every figure carries **producer + agency + publication date +
  methodology reference**, and re-fetches are stored as **vintages** (a revision is a
  new row, never an overwrite). Producers are shown **side by side, never averaged**;
  comparability guards flag incomparable units / SA-NSA / base years; a published gap
  is stored as a gap, never a fabricated zero. Optional scheduled vintage auto-refresh.
- ✅ **Local AI** (**Settings → AI**): an in-app, **checksum-verified** Ollama
  **installer** (Linux; verifies the official installer's attested `sha256` before it
  runs, with a visible elevation step) and a **model download queue** (one pull at a
  time, real byte progress, cancel), an **active-model** picker, a **Behaviour &
  prompts** editor (the built-in summary/translate/synthesis prompts are editable) and
  **custom extractors** (user-defined prompts that write labelled *"AI-derived —
  unreliable"* metadata, **never** the trusted keyword index). Summarize / translate /
  synthesize run **locally** over Ollama, cited and refusing when the source is absent —
  a header pill shows live LLM status. Model pulls egress over **clearnet via the Ollama
  process** (disclosed at consent, not the Tor path).
- ✅ **Newsletter import** (**Settings → Newsletters**): fold newsletters into the same
  searchable corpus — a small **.eml upload**, a **whole-folder import job** (a pausable,
  resumable, task-manager-visible background job that scales to a 20 GB+ tree), and an
  opt-in **mailbox pull** (IMAP/POP3, consented, airplane-gated). **Anonymize-at-ingest**
  by construction: no recipient identity, no raw `.eml`, tracking links detoxed, **zero
  sockets** on a file import.
- ✅ **Offline maps** (**Settings → Offline map**): a per-region **OSM download manager**
  (its own task-manager job, resumable, reorderable queue, with a dated inline size
  table) so map data can be held locally, managed like the Wikipedia dumps.
- ✅ **Watches** (the **Insights → Watches** subtab): saved local "if-this-then-watch"
  conditions that surface a **Lead** when your corpus gains enough new matching articles.
  Local-only, **no notifications / network / telemetry** and no escalation beyond the
  Lead card; a Watches panel shows history + per-watch enable / edit / delete.
- ✅ **Task-manager window** (the top-bar **Tasks & system** button opens it in a new
  tab): live views of the collection pass, the wiki-dump / OSM / model-pull download
  queues (reorder / pause / resume / cancel, honest byte progress — no fabricated ETA
  or rate), the schedule, and a **System** tab with hardware vitals. The **Stop** control
  trips the network kill switch (stated up front).
- ✅ **Alternative interfaces** (**Settings → Appearance**, *experimental*): an opt-in
  gallery of eight alternative UI skins over the one render engine — the ethical
  guarantees (caveats visible, the one network-consent popup, no scores) are preserved
  by construction (same DOM), and no functionality is lost.

**In progress / next:**
- 🚧 Structured per-edit legal diffs (Akoma Ntoso / ELI) and patent/docket parsing into a
  price-feed-style series, on top of the seeded IP/legal primary sources.
- 🚧 The **task-manager window** ships today (see above); the remaining spec is
  per-country scrape priority, richer download arbitration and pass-time estimates.
- 🚧 The **Wikipedia per-article tracked-changes timeline tab** (the living-source view
  that lets you scroll and analyse a page's edits over time) — the existing flagged-edit
  feed and diff viewer ship today.
- 🚧 Volume/anomaly **monitoring** dashboards, and cross-linking Wikipedia diffs into the
  Insights keyword analytics.

See [docs/FUTURE_DEVELOPMENTS.md](docs/FUTURE_DEVELOPMENTS.md) for the full phasing.

**Honesty note:** several previously-advertised "analysis" components (deepfake,
propaganda, cognitive-bias, bot detection) were **fabricated** — returning
hardcoded or heuristic scores while claiming real detection — and were
**quarantined** (never imported, never shipped) rather than presented as if they
worked. That legacy `quarantine/` tree has since been moved off the working tree to
the `quarantine-archive` branch; the honesty record and retrieval steps are in
[docs/QUARANTINE_ARCHIVE.md](docs/QUARANTINE_ARCHIVE.md) (history in
[docs/HISTORY.md](docs/HISTORY.md)).

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
It clones the repo and runs `./install.sh`, which is **promptless**: **one command
installs Core (scrape/store/search/export) + Analysis + Compression**, creates an
**Open Omniscience** launcher (apps menu + Desktop) and **auto-launches** the app into
your browser. (Override the set with `OO_COMPONENTS="…"`; Local-LLM/Ollama setup is
**not** offered here — it lives in the app's **Settings → AI** tab.) On **first
launch** the app walks you through **language → legal terms** (declining uninstalls) **→
a create-passphrase step** (encrypted at rest by default, **no recovery**), then boots
**offline (airplane mode)** — going online passes **one consent popup**. *(Inspect the
tiny [bootstrap](scripts/bootstrap.sh) before piping any script to a shell, or clone
and run `./install.sh` yourself.)*

```bash
# Local dev (any Linux with Python 3.13):
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q
open-omniscience          # serves http://127.0.0.1:8000 (auto-seeds ~3,400 sources)
```

On Qubes: `sudo ./install.sh --template` (in the TemplateVM, then reboot the AppVM)
→ `./install.sh`.

The loop: **go online** (one consent) → **collection runs itself** in the background
(ethical: robots.txt fail-closed, rate-limited) → **search** from the omnibar with
Boolean operators (`AND`/`OR`/`NOT`, phrases, parentheses) → **analyse / export**
(CSV/JSON) from the spawned analysis window → optionally **summarize** locally via
Ollama and export a **signed, verifiable evidence bundle**. (You can still add a source
and ingest a single feed/URL manually.)

## 📚 Documentation

The docs are consolidated into a small set of complete guides
([docs/README.md](docs/README.md) is the index):

- **[USER_MANUAL](docs/USER_MANUAL.md)** — the friendly, complete guide: every tab,
  control, setting, workflow, env var and API area, plus per-feature deep-dives
  (briefing, source integrity, annotations, insights, Wikipedia, world-law, markets,
  chain of custody).
- **[QUICKSTART](docs/QUICKSTART.md)** — install + the end-to-end loop.
- **[DESIGN](docs/DESIGN.md)** — what the app is and isn't, the pillar map, GUI reasoning.
- **[ROADMAP](docs/ROADMAP.md)** — the forward-looking board (DB limitations, performance & scale, known bugs, feature backlog + status).
- **[FUTURE_DEVELOPMENTS](docs/FUTURE_DEVELOPMENTS.md)** — persistent design memory (north star): design intent + open questions.
- **[ARCHITECTURE](docs/ARCHITECTURE.md)** — database/config, the HTTP API map, and i18n.
- **[ETHICS](docs/ETHICS.md)** — principles, compliance (GPLv3), third-party notices.
- **[SECURITY](docs/SECURITY.md)** — threat model, local-first posture, the security audit.
- **[CONTRIBUTING](docs/CONTRIBUTING.md)** — how to contribute + the versioning policy.
- **[CODE OF CONDUCT](docs/CODE_OF_CONDUCT.md)** — Contributor Covenant 2.1.
- **[Legal & governance](docs/legal/README.md)** — legal notice, CGU, privacy (RGPD) and acceptable-use charter (French-authoritative working drafts, permanently not reviewed by a lawyer).
- **[CHANGES](docs/CHANGES.md)** — changelog · **[HISTORY](docs/HISTORY.md)** — audits & quality archive.

## 🔒 Security model

Single local user, loopback-only (`127.0.0.1`), no accounts/RBAC. No telemetry; your
corpus never leaves the machine, and LLM inference is local (loopback Ollama). **All
scraping** goes through the ethical, robots-respecting fetcher. The only outbound
traffic beyond that is a small set of **consented, disclosed exceptions**: **Ollama
model pulls** (they egress over **clearnet via the Ollama process**, not the app's Tor
path — stated at consent), and the **opt-in DuckDuckGo** topic-discovery/ingest channel.
App boot makes **zero** network calls, and a top-bar **airplane-mode** kill switch is a
socket-level guarantee that trips all non-loopback traffic instantly.

**At-rest encryption is on by default for new corpora** (SQLCipher 4): the app asks
for one stable passphrase at every start. The honest limit is stated wherever it
shows — it protects a *seized or copied file*, **not** a compromised running session
(the key is in memory while the app runs) — and there is **no recovery** for a lost
passphrase (the corpus is rebuilt from the web). Plaintext operation stays an explicit
choice; the app never shows a lock screen over a plaintext file (that would be
fabricated security). See [docs/USER_MANUAL.md](docs/USER_MANUAL.md) and
[docs/SECURITY.md](docs/SECURITY.md).

## 📜 License & legal

[GNU GPLv3](LICENSE) — you may **use, study, modify and redistribute** the code,
**including commercially**. Ethical use is a **charter / moral commitment**
(see [docs/legal/CHARTE_USAGE.md](docs/legal/CHARTE_USAGE.md) and
[docs/ETHICS.md](docs/ETHICS.md)), **not** a restriction on the GPLv3 grant.

A layered set of **legal & governance documents** (in French) covers the *use* of the
running software and its AI-derived outputs — areas the GPLv3 does not address. On the
**code** license, the **GPLv3 prevails** over these terms in case of conflict:

- [Mentions légales](docs/legal/MENTIONS_LEGALES.md) — legal notice
- [CGU](docs/legal/CGU.md) — terms of use (incl. the AI-output disclaimer)
- [Politique de confidentialité](docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md) — privacy (RGPD)
- [Charte d'usage](docs/legal/CHARTE_USAGE.md) — acceptable-use charter
- [Index](docs/legal/README.md)

> These documents are **working drafts written without professional legal review,
> permanently** (a free, unfunded hobby project — no lawyer will ever review them),
> not legal advice.

---

*© 2026 Ideotion — distributed under the [GNU GPL v3](LICENSE); built for investigative journalism, honestly.*
