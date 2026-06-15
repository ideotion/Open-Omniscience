# Design & product synthesis

What the app is and isn't, where each original 'pillar' now lives, the GUI's design reasoning, and the content-analysis strategy. The single design reference.

## Contents
- [Open-Omniscience — Product Synthesis (What the App Should Do)](#open-omniscience-product-synthesis-what-the-app-should-do)
- [Pillar Intent Map — where each pillar's purpose now lives](#pillar-intent-map-where-each-pillars-purpose-now-lives)
- [GUI Redesign — "0.05"](#gui-redesign-005)
- [Two interfaces, one argument — "Console" vs "Desk"](#two-interfaces-one-argument-console-vs-desk)
- [Content-analysis strategy — links, uniformity, and the original source](#content-analysis-strategy-links-uniformity-and-the-original-source)


---

## Open-Omniscience — Product Synthesis (What the App Should Do)

> **Status:** Draft for review. This document consolidates the *intended* design from across the
> repository's documentation into one coherent, de-duplicated specification. It deliberately removes
> version drift, marketing hype, and unverifiable QA claims. It describes the **target product**, not
> the current (largely non-functional) code.
>
> Markers used:
> - `⚠️ DECIDE:` a point where the source docs were ambiguous or contradicted each other — your call.
> - `(P0/P1/P2)` a *suggested* priority for that capability (P0 = MVP core, P1 = important, P2 = later).

---

### 0. Deployment context (RESOLVED — drives everything below)

This build targets **one specific environment and one user**. These answers are now fixed and resolve
several of the former `⚠️ DECIDE` points.

- **Host:** Qubes OS, running inside a **Debian AppVM** (template-based).
- **Python:** **3.13 as the default interpreter.**
- **User:** a **single primary user (the project owner)** — no multi-tenant accounts, no RBAC.
- **Surface:** **web UI + REST API bound to `127.0.0.1` only** (loopback). No external listeners.
- **Network posture:** local-first; outbound only during scraping/LLM-pull; **no inbound** anything.

#### 0.1 What Qubes changes about the design

Qubes is not "just Debian." Its security model and AppVM lifecycle impose hard constraints that the
installer and runtime **must** respect:

1. **Filesystem persistence is selective.** In an AppVM, only **`/home`, `/usr/local`, and `/rw`**
   survive a reboot; the root filesystem is **reset from the TemplateVM every boot**. Therefore:
   - The app, its virtualenv, the database, scraped data, logs, audit trail, and any downloaded LLM
     models **must live under `/home/user/...`** (recommended: `/home/user/open-omniscience`).
   - **`apt`/system packages do *not* persist** if installed in the AppVM. System dependencies must be
     installed **in the TemplateVM** (and the AppVM rebooted), or pulled in via Qubes `bind-dirs`.
     The installer must **split**: "system deps → TemplateVM" vs "Python venv + app → AppVM `/home`."
2. **No assumption of persistent root.** Root changes in the AppVM vanish on reboot. Treat the AppVM as:
   persistent `/home`, ephemeral root.
3. **Networking via a NetVM.** The AppVM reaches the internet only through its assigned net/firewall
   qube. The app must **degrade cleanly when offline** and never assume connectivity.
4. **No GPU.** GPU passthrough is impractical in typical Qubes setups → **LLM inference is CPU-only**.
   Default to **small models** (e.g. `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`); large models opt-in.
5. **Air-gap / split-VM is a first-class *future* option (not v1).** Qubes makes the "ethical scrape in a
   networked qube, analyze/store in an offline vault qube" pattern natural via **qrexec/qubes-rpc**. v1
   runs in **one AppVM**; the architecture must keep the *fetch* boundary clean so a later split is a
   deployment change, not a rewrite. (The repo already contains vestigial `src/qubes/rpc/` and
   `docs/QUBES_*` material — to be reviewed/replaced, not trusted.)

#### 0.2 Python 3.13 implications (resolves the dependency-version conflicts)

- **Core stack is 3.13-clean:** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — all ship 3.13 wheels.
- **Local LLM does NOT require heavy Python ML.** Ollama is a **separate native binary**; the app talks
  to it over **HTTP only**. Full LLM capability works on 3.13 with just `httpx`/`requests` — no
  `torch`/`transformers` in the app at all.
- **Heavy ML libraries are dropped from the core.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis`, and the deepfake stack are **removed** for v1 because they are (a) currently
  **fabricated** (the "deepfake CNN" never runs inference), (b) heavy and **CPU-only here**, and
  (c) a per-package 3.13-wheel risk (`pyAudioAnalysis` is unmaintained; `igraph`/`leidenalg`/`gensim`
  must each be verified before use). Any future ML feature must justify its weight and prove a 3.13 wheel.
- **One dependency manifest, 3.13-pinned.** Replace the six disagreeing requirements files with a single
  root `pyproject.toml` (`requires-python = ">=3.13"`) + optional extras (`[llm]`, `[analysis]`, `[dev]`).
  Delete the AI-"corrective" comments and impossible pins.

#### 0.3 Security model for a single local user (simplifies the P0s)

Because the only listener is loopback and the only user is you:
- **Auth:** none required for v1 *provided* the server binds strictly to `127.0.0.1` and is never exposed
  by a Qubes firewall rule. (A single optional API token can be added later if proxied.) This **resolves**
  the "no auth on endpoints" finding *for this deployment* — by removing network exposure rather than
  adding RBAC.
- **`/metrics`:** loopback-only like everything else.
- **Installer safety still mandatory:** no unconfirmed `rm -rf`, no unverified `curl | sh`, never discard
  package-manager stderr — correctness/safety issues regardless of single-user.
- **Front-end assets vendored locally** (no Google Fonts / CDN React) — required for offline/Qubes and
  for the privacy principle.

---

### 1. One-sentence definition

Open-Omniscience is a **local-first, open-source intelligence platform for investigative journalists**
that ethically aggregates many worldwide data sources into a **single, searchable, cross-referenceable,
and provenance-tracked corpus**, with optional **local AI** for analysis — and where every output is
designed to be **scientifically and legally defensible**.

### 2. Who it's for, and the jobs they hire it to do

**Primary user:** an investigative journalist, researcher, or analyst — likely working alone or in a
small newsroom, often privacy-sensitive (sources to protect), sometimes in restricted/air-gapped
environments.

**Core jobs-to-be-done:**
1. *"Collect everything relevant to my investigation from many sources, in one place, automatically."*
2. *"Search and cross-reference it all together — articles, markets, emails — to find connections."*
3. *"Help me understand large volumes of text"* (summarize, translate, extract entities) — **without
   sending my data to anyone.**
4. *"Tell me when something I can trust — or distrust"* (verify media, flag manipulation).
5. *"Prove where this came from and that I didn't tamper with it"* (provenance for publication/legal).
6. *"Alert me when something changes"* (a source goes dark, a price spikes, a narrative emerges).

### 3. Guiding principles (the non-negotiables)

These are the heart of the intent and must constrain every feature. Where today's code violates one,
that is a defect, not a tradeoff.

1. **Local-first & offline-capable.** Runs entirely on the user's machine/server. Must function with
   no internet except during scraping itself. Suitable for air-gapped use (with pre-staged data/models).
2. **Privacy-preserving.** No telemetry. **No user data ever leaves the machine** — especially LLM
   processing (local via Ollama only). ✅ RESOLVED (§0): all front-end assets (fonts, JS libs) are
   **vendored locally** — no CDN calls — required for the Qubes/offline posture.
3. **100% FOSS.** All code and models open-source. ⚠️ DECIDE: License is **GPLv3** at the root but
   **AGPL-3.0** in Pillar 3 — pick one project-wide (AGPL is stricter for network use).
4. **Ethical by construction.** Respect `robots.txt`, rate limits, identify the bot, public data only,
   never bypass paywalls or use credentials to scrape. **Fail *closed*** — if compliance can't be
   verified, don't scrape.
5. **Defensible outputs (scientific + legal).** Every analytical result carries honest uncertainty and
   traceable provenance. **No fabricated numbers.** A confidence score must come from a real method, or
   not exist. Chain-of-custody must be real (signed, tamper-evident), not a plain log file.
6. **Unified corpus.** Everything ingested — news, financial data, commodities, email — lives in **one
   database** and is **cross-referenceable in one query**. This is the product's reason to exist.
7. **Transparency over graceful failure.** The system must never silently degrade into invalid output.
   Missing model, blocked source, unavailable dependency → **visible, explicit status**, never a
   silent placeholder.

### 4. The core mental model

```
        ┌─────────────────────────── INGESTION ───────────────────────────┐
        │  Web articles · RSS · Financial · Commodities · Email/Newsletters │
        │            (all ethically scraped / retrieved)                    │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
        ┌──────────────────── ONE UNIFIED, PROVENANCE-TRACKED STORE ────────┐
        │  articles · financial_data · commodity_data · emails · entities    │
        │  + links between them (article ↔ price move ↔ email ↔ entity)      │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
   ┌──────────── RETRIEVAL ────────────┐   ┌──────────── ANALYSIS (opt-in) ───────────┐
   │ Boolean / full-text search        │   │ Local LLM · verification · stats ·        │
   │ filters · cross-source correlation│   │ monitoring/alerts · correlation engines   │
   │ export (CSV/JSON) · reports       │   │ (every result: method + uncertainty)      │
   └───────────────────────────────────┘   └───────────────────────────────────────────┘
                                         ▼
                         GUI (search, dashboards, source mgmt, reports)
                         + REST API (everything available programmatically)
```

**The spine (ingest → unified store → search → export) must be rock-solid before any pillar.**
Pillars are *enrichers* that read from and write back to the shared store.

---

### 5. Functional scope, by capability area

#### 5.1 Data Ingestion (P0)
- **Source types:** news websites (HTML), RSS/Atom feeds. Later: APIs, social platforms, file drops.
  ⚠️ DECIDE: Pillar 4 lists Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — confirm which (if any)
  are in real scope vs aspirational.
- **Ethical scraper (single, shared implementation):** robots.txt check (cached, http+https aware,
  **fail-closed** on uncertainty), per-source rate limiting, identifying User-Agent, retry/backoff.
  **One fetch per URL** — no double-fetch, no raw bypass path.
- **Deduplication:** content-hash + canonical-URL based; never store the same article twice.
- **Normalization:** extract title, author, publish date, language, canonical URL, body text reliably.
  ⚠️ DECIDE: real news extraction needs per-site rules or a library (e.g. trafilatura-style); the
  current generic-CSS approach silently yields "No Title/No Content." Confirm we adopt robust extraction.
- **Scheduling & incremental updates:** periodic re-scrape, only fetch new/changed content, resume
  interrupted runs.

#### 5.2 Unified Data Store (P0)
- **Single database** holding all entity types, with explicit **link tables** connecting them
  (article ↔ financial instrument, article ↔ commodity, article ↔ email, article ↔ named entity).
- **Provenance fields on every record:** source, fetch timestamp, original URL, content hash,
  raw-vs-processed separation.
- **Backends:** SQLite for single-user/desktop; PostgreSQL for server/concurrent use.
  ⚠️ DECIDE: confirm SQLite-default + optional Postgres (docs mention both; also Redis for caching —
  in or out?).
- **Audit log:** append-only, **tamper-evident** record of every ingestion and mutation.

#### 5.3 Search & Retrieval (P0)
- **Full-text search** across the entire corpus.
- **Boolean operators** (`AND`/`OR`/`NOT`), **quoted phrases**, and **parentheses with correct
  precedence** — implemented with a real grammar or the DB's native FTS, not string hacks.
- **Structured filters:** source, date range, language, tags/category, entity, data type.
- **Pagination**, result ranking, snippet/highlight.
- **Export:** CSV and JSON (and ⚠️ DECIDE: PDF/report formats?), faithful to the filtered result set.

#### 5.4 Cross-referencing & Correlation (P1 — the differentiator)
- Pivot from any record to related records across types (article → companies mentioned → price moves
  near the publish date → related emails).
- **Correlation engines** (financial/commodity ↔ news) that surface *candidate* relationships with an
  **honest, defined measure** (and clearly label correlation ≠ causation). No fabricated p-values.
- Entity-centric view: everything the corpus knows about a person/org/place/instrument.

#### 5.5 Local LLM Analysis (P1)
- **Runtime:** Ollama, fully local. Models are pluggable; ship a small sensible default that *actually
  exists*. ⚠️ DECIDE: current default `gemma4:e2b` and most listed models (Gemma 4, Llama 4, Qwen 3.5)
  are hallucinated — replace the catalog with real tags (e.g. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Capabilities:** generate, chat (with context), extract (entities/keywords/summaries/quotes/links),
  translate (multi-language), analyze (sentiment/tone/readability; bias only if honestly bounded),
  synthesize (summaries, comparisons, timelines, reports), batch.
- **Degrade loudly:** if Ollama or the model is absent, say so — never return fake analysis.

#### 5.6 Verification & Deception Defense — *Pillar 3* (P2, scope TBD)
- **Intent:** detect manipulated media (image/video/audio deepfakes), propaganda techniques, cognitive
  biases, bots, and coordinated campaigns; validate metadata (EXIF/ID3) and cross-modal consistency.
- ⚠️ DECIDE (important): Today this is **fabricated** — the "deepfake CNN" never runs inference; scores
  are blur heuristics; bias/propaganda coverage is mostly unreachable; "accuracy >95%" is aspirational.
  Choose one:
  - **(a) Cut** media-forensics for now and ship only what's honest (metadata/EXIF validation is real
    and useful); **(b) Rebuild** with genuine, evaluated FOSS models and published accuracy; or
    **(c) Keep** but **clearly label "experimental heuristic, not evidence."**
  My recommendation: (a) now, (b) later. Fabricated forensics is the single biggest liability for a
  journalism/legal tool.

#### 5.7 Scientific Rigor — *Pillar 2* (P1)
- **Intent:** make the platform's quantitative claims defensible — real statistical tests, confidence
  intervals, reproducibility/lineage scoring, and "peer review" via multiple local LLMs cross-checking.
- This pillar is the most genuinely-implemented (real scipy/statsmodels). Keep, harden, and make it the
  **gatekeeper**: any number the app shows the user should pass through honest-uncertainty reporting.

#### 5.8 Real-Time Monitoring & Alerting — *Pillar 4* (P2)
- **Intent:** continuous source surveillance; anomaly/trend/pattern detection; threat-intel enrichment;
  multi-channel alerts (email/webhook/chat) with rules and escalation.
- ⚠️ DECIDE: current health checks are simulated (`sleep; return HEALTHY`) and threat-intel/STIX-TAXII
  don't exist. Confirm scope: real source-uptime monitoring + anomaly alerts on the corpus is
  achievable and valuable; STIX/TAXII, SMS/Twilio, Slack/Teams are heavy — in or out?

#### 5.9 Financial Intelligence — *Pillar 5* (P2, marked 0% in docs)
- **Intent:** scrape global exchanges (OHLC + fundamentals) from open web sources (no APIs/paywalls),
  detect fluctuations/patterns/anomalies, and **correlate price movements with news** in the shared DB.
- ⚠️ DECIDE: This is **design-only (0% built)** despite committed scaffold code. Confirm it's a real
  target and, if so, its realistic first scope (e.g. a handful of exchanges, daily OHLC, correlation to
  articles) rather than "50+ exchanges / 10,000+ companies" day one. Note: robust multi-exchange
  scraping without APIs is a large, brittle undertaking.

#### 5.10 Rare-Earth / Commodity Intelligence — *Pillar 6* (P2, marked 0% in docs)
- **Intent:** same pattern as Pillar 5 for the 17 rare-earth elements — prices, production, inventory,
  correlated to geopolitical/news events; with forecasting.
- ⚠️ DECIDE: Also **design-only (0% built)**. Confirm scope and priority vs Pillar 5. (Fix needed: the
  price-normalization unit math is currently wrong by ~1000×, and currency isn't converted.)
  ⚠️ DECIDE: Is "forecasting" in scope? Honest forecasting with uncertainty is hard; recommend deferring.

#### 5.11 Email & Newsletter Intelligence (P1/P2)
- **Intent:** retrieve from IMAP/POP3 and newsletter sources (Substack/Mailchimp/RSS-to-email), parse +
  clean, handle attachments (PDF/Office/images w/ OCR), extract entities and communication networks,
  and **fold into the same searchable corpus**.
- **Privacy/consent is paramount here** (private communications): explicit authorization, encrypted
  credential storage, data-minimization, retention/right-to-be-forgotten.
- ⚠️ DECIDE: Newsletter-API integrations (Substack/Mailchimp/etc.) vs. just IMAP + RSS-to-email for v1?

#### 5.12 GUI / UX (P0 for core, P1+ for pillar dashboards)
- **Core GUI:** search interface, results browsing, source management, export, basic dashboards.
- **Pillar dashboards (later):** financial heatmaps/charts, commodity views, monitoring/alerts, email
  inbox, correlation explorer.
- ✅ RESOLVED (§0): **web UI served by FastAPI at `127.0.0.1:8000`; Tkinter desktop app is dropped**
  (remove `python3-tk`). Open in the AppVM's browser.
- ✅ RESOLVED (§0): front-end is **vanilla JS + vendored libraries (served from `/static`)** — no CDN.
  ⚠️ DECIDE (minor): keep charts lightweight (e.g. a small vendored charting lib) vs none in v1.

#### 5.13 Reporting & Defensible Output (P1)
- Generate investigation reports that bundle findings **with their provenance** (sources, timestamps,
  hashes, methods, uncertainty).
- **Chain-of-custody / integrity:** cryptographic signing + tamper-evidence on exported evidence
  (the crypto modules exist but aren't wired in). This is what makes the "legal admissibility" claim
  real rather than decorative.

---

### 6. Non-functional requirements

- **Platform:** ✅ RESOLVED (§0) — **Qubes OS Debian AppVM** is the *only* supported target for v1
  (built and tested there). Plain Debian 13 may work but is not a goal; no cross-platform commitment.
- **Python:** ✅ RESOLVED (§0) — **3.13**, consistently across `pyproject.toml`, `.python-version`, and
  any CI. Drop dependencies that lack 3.13 wheels (see §0.2).
- **Install footprint:** a true **minimal core** (web + DB + search, lightweight) separable from optional
  extras (`[llm]`, `[analysis]`). **One** `pyproject.toml` — not six disagreeing manifests. Installer
  respects Qubes persistence (§0.1): system deps in TemplateVM, venv+data in `/home`.
- **Security:** ✅ RESOLVED (§0) — single local user, **loopback-only**, so no RBAC. Still mandatory:
  parameterized DB access only (delete the blocklist "sanitizer"), no secrets in code, loopback `/metrics`,
  and a **safe installer** (no unconfirmed `rm -rf`, no unverified `curl | sh`, never discard pkg stderr).
- **Performance:** non-blocking I/O for network/LLM work; bounded concurrency; app stays responsive while
  scraping/inferring. **CPU-only** assumptions (no GPU in Qubes). Targets defined per realistic AppVM
  resources, not aspirational.
- **Offline:** all assets, fonts, and (pre-pulled) models local; documented procedure to operate with the
  NetVM detached after data/models are fetched.
- **Observability:** structured logs (under `/home`), honest health checks, loopback Prometheus metrics —
  reflecting real state.

### 7. Explicit non-goals / out of scope (proposed — adjust)

- Not a general-purpose web crawler/mirror (the HTTrack lineage is vestigial; drop the framing).
- Not a paywall bypass, credential-stuffing, or ToS-violating scraper.
- Not a cloud/SaaS product; no external AI APIs.
- ⚠️ DECIDE: Are forecasting (5.10), social-media ingestion (5.8), and media-forensics (5.6) in or out
  for the first real release?

### 8. Data, provenance & legal-defensibility model (cross-cutting)

- Every stored item: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Every derived/analytic result: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **confidence is never a hardcoded constant.**
- Exported evidence: optionally **signed**, with a verifiable manifest (hashes + Merkle/GPG) so a third
  party can confirm integrity. This is the concrete meaning of "Pillar 4: Legal Admissibility."

### 9. Decisions (consolidated)

**✅ Resolved by the deployment context (§0):**
- **3. Deployment & threat model** → single local user, Qubes Debian AppVM, loopback-only, no RBAC.
- **7. GUI** → web UI at `127.0.0.1:8000`, vanilla JS, assets vendored locally; Tkinter dropped.
- **8. Platform/Python** → Qubes Debian AppVM, Python 3.13, SQLite default (Postgres/Redis **out** for v1).

**⚠️ Still open (your call — sensible defaults proposed):**
1. **MVP scope:** *proposed* — Trustworthy Core only first (Phase 1), then LLM. Confirm.
2. **Rebuild strategy:** *proposed* — salvage the thin good parts (DB models, `ethical_scraper`,
   `async_db`, FastAPI skeleton), delete the fabricated pillars, rebuild the core around them. Confirm vs.
   full greenfield.
4. **Media forensics (Pillar 3):** *proposed* — **(a) cut** deepfake/propaganda/bias for v1 (also
   3.13/CPU-hostile), **keep** real metadata/EXIF validation. Confirm.
5. **Financial (5) & commodity (6):** *proposed* — defer to Phase 3, then build **one** thin vertical.
   Which first?
6. **Email:** *proposed* — IMAP + RSS-to-email only for v1; defer newsletter-API integrations. Confirm.
9. **License:** GPLv3 vs AGPL-3.0 project-wide — still needs a decision.
10. **Out-of-scope confirmation:** forecasting, social-media ingestion, STIX/TAXII, SMS/chat alerts —
    *proposed* out for v1.

### 10. Suggested phasing (proposal, not a commitment)

- **Phase 1 — Trustworthy Core:** ethical ingest → unified store (with provenance) → correct Boolean/
  full-text search → export → minimal web GUI → real tests. *Everything else off until this is green.*
- **Phase 2 — Local LLM + Scientific Rigor:** wire Ollama (real models, loud degradation); make Pillar 2
  the honesty gate for any number shown.
- **Phase 3 — One vertical + correlation:** pick **either** financial **or** commodity, build a thin but
  real slice, prove the article↔data correlation experience end-to-end.
- **Phase 4 — Monitoring/alerts, email, verification (metadata first):** add enrichers one at a time,
  each genuinely working and tested.
- **Phase 5 — Defensible reporting:** wire real signing/chain-of-custody into exports.

---

### 11. Implementation status (current)

What is built and tested today, mapped to the scope above (intent unchanged; these
note where reality now stands). See the linked feature docs for detail.

- **Trustworthy core (5.1–5.3, 5.13):** ✅ ethical ingest, unified provenance store,
  Boolean FTS5 search, CSV/JSON export, signed chain-of-custody.
- **Ingestion at scale (5.1):** ✅ in-app **scheduler** (start/stop, interval, modes
  rss/crawl/markets) and a **bounded recursive crawler** (same-domain *discovery*,
  robots fail-closed, depth/page caps) — not a general-purpose mirror (§7 honoured).
- **GUI (5.12):** ✅ tabbed web UI — Search · Ingest · **Sources & Database** (stats,
  source management, **world coverage**) · **Markets** · **Insights** · Chain of
  custody · **Settings** (theme + SQLite backup/restore). Dependency-free, offline.
- **Financial & commodity (5.9, 5.10):** ✅ thin real vertical — per-source price
  **extraction rules**, **official CSV feeds** (FRED→World Bank/EIA), charts, and
  honest price↔news correlation. Unit math fixed; numbers only from a verified rule
  or imported CSV. See [USER_MANUAL.md](USER_MANUAL.md).
- **Worldwide source coverage:** ✅ packaged markets catalog + a **data-derived
  generator** (Wikidata CC0) for news media **and** institutions per country, with a
  coverage report. CSV import/export of the source list. See
  [ROADMAP.md](ROADMAP.md).
- **Cross-referencing & correlation (5.4):** ✅ **keyword & entity analytics** —
  extraction at ingest, mention store with context, trends, PMI associations
  ("mind-map"), and a per-country/city map. See [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia as a tracked source (new):** 🚧 change-tracking foundation (per-language
  editions, delta storage, large-edit/revisionism flagging incl. ORES) — schema +
  parser + flagging done; live polling, tab and offline downloader next. See
  [USER_MANUAL.md](USER_MANUAL.md).
- **Verification (5.6):** ✅ honest image EXIF/metadata only (fabricated forensics
  remain quarantined). **LLM (5.5)**, **monitoring/alerts (5.8)**, **email (5.11)**:
  partial/queued.

---


---

## Pillar Intent Map — where each pillar's purpose now lives

The original design organised the platform into six "pillars". Those pillar trees
were ~50k lines that the running app never imported — mostly design-only or
fabricated. **Their *intent* has been preserved**: each pillar's genuine purpose
is now a small, honest, tested module inside `src/` (or is explicitly deferred).
The original pillar trees are kept under `quarantine/pillars/` for reference and
history; nothing is deleted.

| Pillar (intent) | Where the intent lives now | Status |
|---|---|---|
| **1 — Data ingestion** (ethical scrape → unified store) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Real, tested |
| **2 — Scientific rigor** (honest statistics, uncertainty) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Salvaged the genuine scipy/statsmodels code** + its 60 tests |
| **3 — Deception defense** (verify media) | `src/verification/metadata.py` (honest EXIF/metadata) + `POST /api/verify/image-metadata` | ✅ Honest scope. Deepfake/propaganda/bias detectors were fabricated → `quarantine/pillar3_analysis/` |
| **4 — Monitoring + legal admissibility** | `src/monitoring/` (real uptime + anomalies) and `src/reporting/` + `src/crypto/` (Merkle + Ed25519 signed evidence) | ✅ Real, tested |
| **5 — Financial intelligence** | *Deferred.* The pattern is proven by Pillar 6's reimplementation; a financial vertical can reuse `src/commodity` + `src/analysis`. | ⏸ Design-only originally (0%); not yet built |
| **6 — Rare-earth / commodity** | `src/commodity/` (prices, correct unit conversion, **real** scipy correlation, CSV import) + `POST /api/commodities/*` | ✅ Real, tested |

### What was salvaged in this step (Pillar 2)
- `src/analysis/statistical_tests.py` — t-tests, ANOVA, chi-square, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, regression, Tukey HSD (scipy/statsmodels). Every result
  carries statistic, p-value, dof, effect size, sample size.
- `src/analysis/confidence_intervals.py` — means and proportions (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Exposed at `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  so a journalist can check whether a pattern in their data is actually significant.
- The genuine Pillar-2 test suites moved with the code (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### What was NOT salvaged (and why)
- Pillar 2 `peer_review` / `consensus` / `reproducibility` — speculative or shallow
  (e.g. reproducibility was a boolean-average rubric). Parked; revive with real
  methods if needed.
- Pillar 3 forensic detectors, Pillar 4 simulated monitoring/threat-intel, Pillar
  5/6 scaffolds — fabricated or design-only; the honest pieces are already in `src/`.

### Net effect
The repository now reflects what actually runs: a ~16k-line live core (plus the
salvaged statistics), with the aspirational/fabricated ~50k pillar lines parked in
`quarantine/pillars/` rather than masquerading as working features.


---

## GUI Redesign — "0.05"

> A ground-up redesign of the Open Omniscience interface, reasoned from the user
> outward. This document is the *why*; `src/static/index.html` is the *what*.
> Read this first if you want to understand (or argue with) the decisions.

---

### 0. The brief, restated

Redesign the entire GUI for a specific person: **a truth-seeking operative — an
investigator/journalist who is *not* fond of computers**, who wants to understand
the world as it really is and to communicate findings credibly. The result must be
slick, beautiful, adaptable, highly customizable, simple *and* deep, and good
enough that a colleague glancing over a shoulder says *"what is this — can I have
it?"* It must respect what the project already is: **single-user, loopback-only,
offline-first, dependency-free, no telemetry**, governed by the **Munich Charter**
(truth, source verification, privacy, no propaganda).

#### Engineering stance (and the honest tradeoff)

The previous UI is a single 2,200-line `index.html` wiring ~110 functions to ~150
API endpoints. Those functions *work and are tested*. A from-scratch rewrite would
have produced a prettier shell with a high chance of silently broken buttons — the
exact opposite of a tool whose entire selling point is **honesty**. So this is a
**total redesign of everything the user sees and touches** — visual language,
layout, navigation model, information architecture, naming, onboarding,
customization, and two brand-new surfaces (a Home dashboard and an in-app Docs
reader) — built *on top of the proven data layer*, with every original element ID
preserved so nothing regresses. Dependency-free remains absolute: **no CDN, no web
fonts, no framework** — one self-contained file that runs with the NetVM detached.

---

### 1. Personas (who we are actually serving)

**Amara — investigative journalist, 44. Primary persona.**
Covers procurement corruption. Brilliant reporter, reluctant computer user. Works
on sensitive stories and is (rightly) paranoid about surveillance and data loss.
*Needs:* find things fast across her own corpus; prove a document is authentic and
unaltered; export something she can hand an editor or a court; never feel stupid.
*Fears:* losing work, being tracked, jargon, looking amateur next to a "tech" colleague.
*Win condition:* she opens the app and immediately knows what to do, and what she
produces looks and *is* trustworthy.

**Daniel — freelance OSINT researcher, 29. Power persona.**
Semi-technical, fast, keyboard-driven, runs many sources. *Needs:* density, batch
operations, trends/associations, market correlations, keyboard shortcuts, a command
palette. *Fears:* hand-holding that slows him down; hidden features.
*Win condition:* he never has to touch the mouse and finds advanced power on tap.

**Sister-of-the-cause — the "operative", 50s. Values persona.**
Distrusts Big Tech; wants sovereignty. *Needs:* proof nothing phones home; offline
operation; plain explanations of what each action does to her network exposure.
*Win condition:* she can read, in the app, exactly what it will and won't do.

**Elliot — the editor, 38. Recipient persona.**
Never opens the app; *receives* its outputs. *Needs:* exports that are legible and
verifiable on their own. The UI serves him indirectly: evidence bundles, signed
custody, clean CSV/JSON.

**Design implication:** lead for Amara (clarity, guidance, trust), layer in Daniel's
depth so it never gets in her way (progressive disclosure + command palette),
honour the operative's sovereignty in copy and behaviour, and make Elliot's
artifacts first-class.

---

### 2. Design principles (derived, not borrowed)

1. **Clarity over cleverness.** Plain verbs, human labels, one obvious primary
   action per screen. Jargon ("ingest", "corpus", "Merkle root") is translated or
   explained inline, never assumed.
2. **Trust is the product.** Verifiability, provenance and "this number is real,
   not estimated" are surfaced, not buried. The aesthetic should *feel* like an
   instrument, not a toy.
3. **Progressive disclosure.** Simple by default; depth one click away. Advanced
   panels collapse; rarely-used modules can be hidden entirely.
4. **Customizable, because trust is personal.** Themes, accent, density, font size,
   layout, and *which tools even appear* are the user's to set — and persist
   locally only.
5. **Honesty in the interface.** If a capability depends on an optional extra, the
   UI says so instead of pretending. Nothing fakes success.
6. **Sovereign by construction.** No external requests of any kind. The look is
   achieved with system fonts and hand-built SVG icons.
7. **Keyboard-first is also accessibility-first.** A command palette and shortcuts
   serve Daniel *and* make the whole app reachable without precise mousing.

---

### 3. Per-tool analysis — pros, cons, decision

The old top-tab set: *Search · Ingest · Sources · Database · Markets · Insights ·
Wikipedia · Chain of custody · Settings.* Evaluated one by one for our personas.

| Old tab | Pros | Cons | **Decision** |
|---|---|---|---|
| **Search** | The core act. Everyone needs it. | Buried as one tab among nine; no orientation for a new user. | **Keep & elevate.** Becomes the heart, reachable instantly; a new **Home** gives orientation around it. |
| **Ingest** | Necessary to pull data in. | "Ingest" is engineer jargon; intimidating; conflated scheduler + manual fetch. | **Keep, rename → "Collect."** Lead with the simple manual action; the scheduler is "Automatic collection," framed as set-and-forget. |
| **Sources** | Credibility lives here; provenance starts with *where*. | Dense tables; felt like admin, not journalism. | **Keep, reframe as "Sources" (your newsroom's beat list).** Restyled to read like a library, not a database console. |
| **Database** | Honest live counts; backup/restore. | "Database" means nothing to Amara; she has a *library/archive*, not a DB. | **Keep, rename → "Library."** Same real counts and world-coverage, framed as "what you've gathered." |
| **Markets** | Powerful for "follow the money" investigations. | Irrelevant to most stories; heavy, niche; clutter for Amara. | **Keep, mark Advanced, hideable.** Off the critical path; one toggle removes it for users who don't do financial work. |
| **Insights** | The visual showpiece — trends, associations, map. The "wow." | Was a quiet middle tab; under-sold. | **Keep & promote.** This is a headline feature; given prominence and polish. |
| **Wikipedia** | Strong fit: "the world as it really is," offline knowledge, edit-war detection. | Two different things (live tracking vs heavy offline dumps) split across tabs confusingly. | **Keep.** Tracking stays here; heavy dumps stay in Settings, clearly cross-linked (already done in prior work). |
| **Chain of custody** | The trust differentiator. This is what makes Elliot trust the output and Amara look professional. | Named in legalese; felt like a vault few would open. | **Keep, rename → "Evidence & custody," promote.** Part of the "what is this?!" moment. |
| **Settings** | Needed. | Was a junk drawer (prefs + keyword filter + dumps + backup). | **Keep, restructure** into sections (Appearance · General · Wikipedia · Data & backup · Safety). *(0.07: the standalone Customize drawer was folded in as the **Appearance** section — one home for look-and-feel, less floating chrome.)* |

#### New surfaces added

- **Home (dashboard).** *Rationale:* Amara needs orientation, not a blank search box.
  Status at a glance (corpus size, sources, scheduler, last activity), big quick
  actions ("Search," "Collect now," "Verify a document"), and an empty-state that
  teaches. This is the single biggest usability win for the primary persona.
- **Help / Docs reader.** The user explicitly asked for direct access to the detailed
  manual. A first-class **Help** surface renders the User Manual (and other docs)
  *inside* the app — searchable, offline, no leaving the tool. Also reachable from
  the top bar (`?`) and the command palette.

#### Resulting information architecture

The flat 9-tab strip becomes a **grouped sidebar** (collapsible to icons), ordered
by how the work actually flows:

- **Investigate** — Home · Search · Insights · Temporal map · Wikipedia · *Markets (advanced)*
- **Collect** — Collect · Sources · Library
- **Trust** — Evidence & custody
- **System** — Settings · Help

Grouping turns "nine equal strangers" into "four intentions," which is how Amara
thinks ("I want to *find* something" / "I want to *gather*" / "I want to *prove*").

---

### 4. The "wow" — what makes a journalist lean in

- **A coherent visual system.** Deep "ink" dark theme by default with a confident
  single accent, generous spacing rhythm, real typographic hierarchy, monospace for
  data/hashes, soft depth, and restrained motion. It reads as *instrument*, not
  *dashboard template*.
- **Command palette (Ctrl/⌘-K).** Type to jump anywhere or run any action or open
  any doc. Power for Daniel; a "what can I even do here?" map for Amara.
- **Appearance controls** (Settings → Appearance; a live drawer through 0.06, folded
  into Settings in 0.07). Theme presets (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), accent swatches, density, font size, sidebar collapse,
  and **module visibility** — all instant, all local, all persistent.
- **A Home that orients**, an onboarding that teaches, and empty states that guide.
- **Trust, made visible.** Custody/verification and "measured, not estimated"
  framing are part of the aesthetic, not fine print.
- **Total offline integrity.** No network calls for the chrome — which is itself a
  feature you can *show* a security-conscious colleague.

---

### 5. Customization model

Look-and-feel is stored in `localStorage` (`oo.ui`) — never sent anywhere — so it
is instant and survives offline. Functional preferences (default result limit, base
theme) continue to persist server-side via `/api/settings`. Customizable: theme
preset, accent colour, density, font scale, sidebar state, and the set of visible
modules. Sensible defaults mean a first-run user touches none of it.

---

### 6. What I deliberately did **not** do (honesty)

- **No framework / build step / CDN.** Would break the offline, auditable, sovereign
  ethos for cosmetic gain. Vanilla, single file, system fonts, hand-drawn SVG.
- **No fabricated features.** Every button maps to a real, working endpoint. Capability
  that depends on an optional extra still says so.
- **No silent backend changes** beyond an additive, read-only, allow-listed docs
  endpoint (`/api/docs`) to power the Help reader.
- **The free-text language inputs stayed free-text** (already noted in OPEN_QUESTIONS);
  redesign doesn't invent dropdowns that the backend can't back.

---

### 7. Status

`0.05` is now the repository's **default branch** (mainline); earlier lines (0.04
and before) remain in git history. Functional parity is preserved (same element
IDs, same wiring); the change is everything *around* that engine. The default ships
**two** interfaces — Console (`/`) and Desk (`/desk`) — compared in
[`DESIGN.md`](DESIGN.md).


---

## Two interfaces, one argument — "Console" vs "Desk"

> You asked for a *contradictory* argument: not a defense of the 0.05 redesign, but
> an honest case that it might be the **wrong** interface for this app — and a
> concrete alternative to test it against. This document is that argument. The two
> interfaces ship side by side so you can run both on the same data and judge for
> yourself.

---

### 0. First, re-ground in what this app actually is

Before arguing about chrome, the non-negotiables (from `ETHICS.md`,
`DESIGN.md`, the Munich Charter):

- **One user, one machine, loopback only, offline-first.** No accounts, no cloud,
  no telemetry. Often run in a Qubes AppVM with the network qube *detached*.
- **A truth-seeking operative who is not fond of computers.** An investigator /
  journalist whose job is to *understand reality and communicate it credibly*.
- **The product is trust.** Provenance, source verification, "measured not
  estimated," tamper-evidence. The Munich Charter (truth, verify sources, protect
  sources, resist propaganda) is the spine.
- **Sovereignty as aesthetic.** The tool should *feel* like it belongs to the user,
  not to a platform.

Any interface must be judged against *those*, not against "does it look like a
2025 SaaS product."

---

### 1. The charge sheet against "Console" (the 0.05 redesign)

Steelmanning the case that 0.05 is the wrong direction:

1. **It dresses a sovereign tool in surveillance-capitalism clothes.** Persistent
   left sidebar, status pills, command palette, a customization drawer with eight
   themes — this is the visual grammar of Slack, Linear, Notion: *cloud SaaS*. For
   a user who distrusts Big Tech and works on sensitive stories, that grammar can
   read as "another app that watches me," undermining the one thing that matters
   most here: trust. The look fights the values.

2. **It optimizes for the demo, not the work.** The brief included "make a
   journalist say *can I have it?*" — a five-second over-the-shoulder reaction.
   Designing for that pulls toward dashboard flash (gradients, animated counts,
   theme zoo) and away from the quiet, reading-heavy, document-centric reality of
   investigation. The best tools for deep work (a text editor, a notebook) are
   *plain*. Console may be impressive and shallow.

3. **Customization is a tax disguised as a gift.** Eight themes, accent swatches,
   density, font scale, per-module hiding. For *Amara* (not fond of computers) every
   one of these is a decision she didn't want and a way to misconfigure her tool.
   "Highly customizable" served the brief's wording and the *designer's* idea of
   generosity — but a genuinely simple tool is **opinionated**: it makes the right
   call so the user doesn't have to. Choice is cognitive load.

4. **The information architecture is still the software's, not the user's.** Console
   renamed and regrouped the tabs, but the menu is still a list of *modules*
   (Search, Sources, Insights, Markets, Custody…). Amara doesn't think in modules;
   she thinks in a **case**: "I'm chasing this story — gather, read, connect, prove,
   publish." Both 0.04 and 0.05 make the user translate their *job* into the app's
   *features*. A persistent nav of nine destinations is a map of the codebase.

5. **Chrome competes with content.** A fixed sidebar + top bar permanently spend
   ~250px and a horizontal band on *navigation the user uses for two seconds per
   session*. The thing they actually do — read articles, scan results, compare
   diffs — gets the leftovers. Investigation is reading; Console under-serves
   reading.

6. **The "wow" is borrowed, not earned.** A palette and themes are *table stakes*
   in modern apps — impressive precisely because they're familiar. The genuinely
   differentiating, "I've never seen that" features here are the *substance*:
   offline Wikipedia edit-war detection, tamper-evident custody, "every number is a
   real COUNT(\*)". Console decorates; it doesn't dramatize what's actually unique.

That is a serious indictment. It deserves a real alternative, not a rebuttal.

---

### 2. In Console's defense (so the argument is fair)

- A persistent nav is **discoverable**: nothing is hidden, which matters for a
  novice who doesn't yet know what the tool can do. Hub-and-spoke models hide
  power behind a click and a guess.
- Customization is **opt-out**: defaults are sane; a user who ignores the drawer
  loses nothing. And theming genuinely helps the eye-strain/late-night reality of
  the work, and the accessibility (high-contrast, text size) of *real* users.
- The "SaaS grammar" is also just **current usability convention** — people know how
  to use it on day one. Novelty for its own sake has its own tax.
- It is still **100% offline and dependency-free**. The grammar is borrowed; the
  substance (no network, no telemetry) is not.

Both positions are legitimate. The way to resolve it is not more arguing — it's to
**build the antithesis and use both**.

---

### 3. The antithesis: "Desk"

If Console is a **broad operations console** (everything always one click away,
maximally flexible, modern-app grammar), **Desk** is the opposite thesis:

> **An investigator's desk: calm, opinionated, content-first, and task-framed.
> Almost no chrome. One job at a time. The interface gets out of the way of reading
> and thinking.**

Concrete commitments where Desk deliberately *disagrees* with Console:

| Dimension | Console (thesis) | Desk (antithesis) |
|---|---|---|
| Navigation | Persistent left sidebar (always visible) | **No persistent nav.** Navigation is *on demand* — a calm home, a "Go to…" overlay, and ⌘K. Chrome appears only when summoned. |
| Entry point | A status dashboard | **A job-framed home:** "What are you working on?" → Gather · Find & read · Connect · Verify & share. Framed by the user's task, not the app's modules. |
| Customization | 8 themes, accent, density, font, module toggles | **Two themes only** (Paper / Ink), no knobs. Opinionated. The tool decides so you don't. |
| Aesthetic | Modern app console (sans, pills, gradients) | **Editorial / print:** serif headings, paper warmth, generous margins, reading measure. Feels like a newsroom, not a SaaS. |
| What gets the space | Navigation + status, then content | **Content.** A single centered reading column; tables and the article reader get the room. |
| Trust signal | A status pill | A persistent, quiet **"Local · Offline · Nothing leaves this machine"** line — sovereignty stated, not implied. |
| Demo reaction | "Slick!" | "…oh, this is *calm*. And it's all mine." A slower, deeper kind of wow. |

What Desk **keeps** (because it's the point of the app, not chrome): every feature
and every working endpoint. Desk and Console share the exact same engine and the
same content panels — they differ *only* in shell, navigation model, IA framing,
and aesthetic. That's deliberate: it keeps the experiment controlled, so what you're
comparing is **the philosophy**, not which one I happened to wire up more carefully.

---

### 4. How to judge them (rubric)

Score each against the values — not against your gut "which looks nicer":

1. **Trust** — which one *feels* like it belongs to you and won't betray you?
2. **Calm vs capability** — which lets you think? which makes power findable?
3. **Novice path** — drop *Amara* in cold: which gets her to a result faster, with
   less fear?
4. **Power path** — *Daniel* on the keyboard: which gets out of his way?
5. **Reading** — open a long article / a Wikipedia diff in each. Which is the better
   place to *read*?
6. **The 5-second test** — show a colleague each. Which provokes "can I have it?" —
   and is that the reaction you actually want to optimize for?
7. **Fit to ethos** — which one would you trust to run with the network detached in
   a Qubes vault?

---

### 5. Predicted pros / cons (my honest bet, to be tested)

**Console** — *Pros:* discoverable, conventional, flexible, accessible knobs, demo
shine. *Cons:* chrome-heavy, decision load, generic-SaaS feel that may erode trust,
IA still module-centric.

**Desk** — *Pros:* calm, content/reading-first, opinionated (no config tax),
task-framed entry, an aesthetic that *reinforces* sovereignty and trust. *Cons:*
power is one summon away (a click/keystroke), fewer accessibility knobs, less
immediately "impressive," novelty has a small learning cost.

---

### 6. My recommendation (synthesis — provisional, pending your test)

I expect the right answer is **neither pure Console nor pure Desk**, but a synthesis
that leans on Desk's *values fit* and Console's *discoverability*:

- **Adopt Desk's task-framed home and editorial calm** as the default mood. The job
  framing ("gather / read / connect / verify") is the single biggest fix to the
  "IA is the codebase" critique.
- **Adopt Desk's restraint on customization:** ship two excellent themes
  (Paper/Ink) + a text-size control for accessibility, and **cut** the accent /
  density / module-hiding sprawl. Opinionated beats configurable here.
- **Keep a *quiet, collapsible* nav from Console** for discoverability — but
  collapsed by default, so content leads and the nav is there when wanted.
- **Keep ⌘K** (it serves both novice and power user and is genuinely useful).
- **Dramatize the substance, not the chrome:** make custody, offline Wikipedia, and
  "real counts" the visual heroes — that's the earned wow.
- **Lead the trust line everywhere** ("nothing leaves this machine"). It is the
  brand.

But that's a hypothesis. Run both, score them against §4, and tell me where reality
diverges from my bet — then I'll fold the verdict into a single 0.06.

> **FINAL VERDICT (maintainer, 2026-06-10, after live use):** the dialectic is
> resolved — **Desk is retired entirely. One interface: the Console** (`/`).
> Two icons confused more than they helped; Desk's reduced toolset made
> shipped features (Temporal map, Agenda) look lost; and the Console already
> adapts smoothly to window size (the sidebar retracts to an icon rail). The
> `desk.html` file was removed (it lives in git history); `/desk` now
> redirects to `/`. Desk's best ideas — the task-framed home, ⌘K, editorial
> calm — should be folded into the Console over time, per §6 above.

---

### 7. Running both at once

Both interfaces are served by the same local backend on the same data:

- **Console** → `http://127.0.0.1:8000/`  (the default)
- **Desk** → `http://127.0.0.1:8000/desk`

The installer creates **two desktop icons** — *Open Omniscience* (Console) and
*Open Omniscience — Desk* — so you can launch either, or open both windows together
and compare them tab-for-tab on identical data. Pick a winner (or ask for the
synthesis) and we collapse back to one in 0.06.


---

## Content-analysis strategy — links, uniformity, and the original source

> Concrete, staged strategies for the vision in [`ROADMAP.md`](ROADMAP.md):
> use article **links** to assemble what's talking about the same thing, surface
> media **uniformity**, and trace information back to its **original source** — while
> keeping the **user in power**, the analysis **transparent and local**, and never
> letting the tool become an arbiter of truth (Munich Charter). Open-source and
> offline throughout.

---

### 0. Where we are (honest status)

Article-link detection is **scaffolded but not wired**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extracts links
  from HTML, normalises URLs, tracks anchor text + position, classifies link *type*
  (internal/external/image/…), and produces link statistics. ~500 lines, unit-shaped.
- ✅ **DB schema** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource`, and `LinkClassificationRule`. Relationships are in place
  (`Article.links`, `ExternalSource.links`).
- ✅ **Invoked on ingest** *(done — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  populates `article_links` with outbound **external** links (best-effort, fail-open;
  internal/image/ad/social/tracker excluded per `ROADMAP.md`; de-duped + capped).
- ✅ **API** *(done — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (by url|domain, windowed), `articles-by-link` (by url|domain). Counts
  only; nothing scored or judged.
- ❌ **No UI yet** — no Insights view over the link graph (P2, below).

So P0/P1 are wired; the remaining work is the UI and the deeper analyses (P3/P4).

---

### 1. The core idea: links are a citation graph

Treat each article as a node and each outbound link as a directed edge to a URL (and
to its domain). That graph answers exactly what you asked:

- **"Assemble all articles talking about the same link."** = group articles by the
  external URL they cite → the URL's **in-degree** is "how many of my articles point
  here." High in-degree = a **hub**: often a primary document, a wire story, or a
  much-discussed reference.
- **"Discover trends through internal links."** = watch in-degree over time; a URL or
  domain whose citations spike is a *trend* grounded in what reporters actually cite,
  not just keyword frequency.
- **"Trace the original / primal source."** = within a cluster of articles about one
  story, the original is the node others **link to**, and/or the earliest, and/or the
  one citing a **primary document** (court/gov/dataset). Links + timestamps + wire
  attribution triangulate it.

This is *co-citation analysis* — cheap, transparent, and explainable. No black box.

---

### 2. Staged strategies (each shippable on its own)

#### P0 — Wire the extractor into ingest (make the graph exist)
- Call `LinkExtractor` during ingestion on the fetched HTML; persist outbound
  **external** links to `article_links` (skip internal nav, ads, and — per
  `ROADMAP.md` — image/binary links). Store normalized_url + anchor text + type.
- Map each external link's domain to a known `Source`/`ExternalSource` where
  possible (so "who cites whom" can roll up to outlets and **owners**).
- Cheap, deterministic, offline. Nothing fetched beyond what ingest already fetched.

#### P1 — Aggregation + API (answer the user's question)
Read-only endpoints over the graph:
- **`top-cited`** — most-cited URLs/domains in a window (the trend signal).
- **`articles-by-link`** — given a URL/domain, every article in the corpus citing it
  ("assemble all articles talking about the same link").
- **`link-graph`** — nodes/edges for a topic or window, for visualisation.
- **`co-citation`** — articles that cite the *same* external sources (candidate
  "same story" clusters), with overlap counts.

#### P2 — UI: a "Links & sources" view in Insights
- A ranked list of **most-cited links/domains** (click → all citing articles).
- A small, zoomable **citation graph** (reuse the SVG approach already used for the
  Insights map — no new dependency).
- Always shows **sample sizes** ("cited by 14 of your articles") — measured, not
  guessed. The user clicks, explores, decides.

#### P3 — Original-source lineage
For a cluster of articles about one story, present a **lineage**, ranked by signals
(each shown, none decisive):
- in-degree (who is linked to by the others),
- earliest publication timestamp,
- wire attribution (AFP/Reuters/AP — we already tag `wire-agency`),
- presence of a **primary document** link (gov/court/dataset/preprint).
Output: "primary doc → first report → echoes," as a chain the user reads.

#### P4 — Uniformity & echo (ties to media concentration)
- **Near-duplicate detection** (cheap MinHash/SimHash) to flag syndicated/copied text
  across outlets — builds on `src/ingestor/duplicate_detector.py`.
- **Echo score**: a cluster where many outlets cite **one** source (or each other in a
  tight loop) and add little original linking = high echo. Diverse primary-source
  citations = independent reporting.
- **Concentration overlay**: weight echo by **ownership** — if the echoing cluster maps
  to one owner/bloc (the "~7 billionaires own ~90%" case), surface that. Needs the
  ownership graph (Wikidata P127/P749 + manual), per `ROADMAP.md`.

---

### 3. Keeping the user in power (non-negotiable)

- **Surface, never suppress.** Echo/lineage scores are *shown and sortable*; the tool
  never hides or auto-demotes a source. Any down-weighting is an explicit, reversible
  user control, **off by default**.
- **No truth labels.** "Earliest we saw" / "most cited" ≠ "true." We show structure
  (who said it first, who cites whom, who owns whom) and stop.
- **Everything explainable & local.** Every number traces to rows the user can inspect;
  no external calls, no ML black box (hashing + counting + graph degree).
- **Open-source & auditable.** Pure functions, unit-testable, classification rules in
  data (`LinkClassificationRule`) the user can edit.

---

### 4. Risks & honest limits

- Link extraction is only as good as the fetched HTML (paywalls/JS limit it).
- Anchor/citation conventions vary; "according to X" without a link is missed (a
  later NLP pass could help, but starts simple).
- Ownership data is patchy and dated — must be attributable, not guessed.
- Near-dup at corpus scale needs care to stay cheap on one machine (hashing, windowed
  comparison), not O(n²) full-text compares.

### 5. Suggested first commit

Wire **P0** (populate `article_links` on ingest) behind a setting, add the **P1
`articles-by-link`** and **`top-cited`** endpoints, and a minimal Insights list. That
alone delivers "assemble all articles citing the same link" and a citation-based
trend — the smallest slice of real value, fully in keeping with the ethos.

