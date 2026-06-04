# Open-Omniscience — Product Synthesis (What the App Should Do)

> **Status:** Draft for review. This document consolidates the *intended* design from across the
> repository's documentation into one coherent, de-duplicated specification. It deliberately removes
> version drift, marketing hype, and unverifiable QA claims. It describes the **target product**, not
> the current (largely non-functional) code.
>
> Markers used:
> - `⚠️ DECIDE:` a point where the source docs were ambiguous or contradicted each other — your call.
> - `(P0/P1/P2)` a *suggested* priority for that capability (P0 = MVP core, P1 = important, P2 = later).

---

## 1. One-sentence definition

Open-Omniscience is a **local-first, open-source intelligence platform for investigative journalists**
that ethically aggregates many worldwide data sources into a **single, searchable, cross-referenceable,
and provenance-tracked corpus**, with optional **local AI** for analysis — and where every output is
designed to be **scientifically and legally defensible**.

## 2. Who it's for, and the jobs they hire it to do

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

## 3. Guiding principles (the non-negotiables)

These are the heart of the intent and must constrain every feature. Where today's code violates one,
that is a defect, not a tradeoff.

1. **Local-first & offline-capable.** Runs entirely on the user's machine/server. Must function with
   no internet except during scraping itself. Suitable for air-gapped use (with pre-staged data/models).
2. **Privacy-preserving.** No telemetry. **No user data ever leaves the machine** — especially LLM
   processing (local via Ollama only). ⚠️ DECIDE: the current GUI pulls Google Fonts + React/Recharts
   from CDNs, which violates this. Confirm we vendor all front-end assets locally.
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

## 4. The core mental model

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

## 5. Functional scope, by capability area

### 5.1 Data Ingestion (P0)
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

### 5.2 Unified Data Store (P0)
- **Single database** holding all entity types, with explicit **link tables** connecting them
  (article ↔ financial instrument, article ↔ commodity, article ↔ email, article ↔ named entity).
- **Provenance fields on every record:** source, fetch timestamp, original URL, content hash,
  raw-vs-processed separation.
- **Backends:** SQLite for single-user/desktop; PostgreSQL for server/concurrent use.
  ⚠️ DECIDE: confirm SQLite-default + optional Postgres (docs mention both; also Redis for caching —
  in or out?).
- **Audit log:** append-only, **tamper-evident** record of every ingestion and mutation.

### 5.3 Search & Retrieval (P0)
- **Full-text search** across the entire corpus.
- **Boolean operators** (`AND`/`OR`/`NOT`), **quoted phrases**, and **parentheses with correct
  precedence** — implemented with a real grammar or the DB's native FTS, not string hacks.
- **Structured filters:** source, date range, language, tags/category, entity, data type.
- **Pagination**, result ranking, snippet/highlight.
- **Export:** CSV and JSON (and ⚠️ DECIDE: PDF/report formats?), faithful to the filtered result set.

### 5.4 Cross-referencing & Correlation (P1 — the differentiator)
- Pivot from any record to related records across types (article → companies mentioned → price moves
  near the publish date → related emails).
- **Correlation engines** (financial/commodity ↔ news) that surface *candidate* relationships with an
  **honest, defined measure** (and clearly label correlation ≠ causation). No fabricated p-values.
- Entity-centric view: everything the corpus knows about a person/org/place/instrument.

### 5.5 Local LLM Analysis (P1)
- **Runtime:** Ollama, fully local. Models are pluggable; ship a small sensible default that *actually
  exists*. ⚠️ DECIDE: current default `gemma4:e2b` and most listed models (Gemma 4, Llama 4, Qwen 3.5)
  are hallucinated — replace the catalog with real tags (e.g. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Capabilities:** generate, chat (with context), extract (entities/keywords/summaries/quotes/links),
  translate (multi-language), analyze (sentiment/tone/readability; bias only if honestly bounded),
  synthesize (summaries, comparisons, timelines, reports), batch.
- **Degrade loudly:** if Ollama or the model is absent, say so — never return fake analysis.

### 5.6 Verification & Deception Defense — *Pillar 3* (P2, scope TBD)
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

### 5.7 Scientific Rigor — *Pillar 2* (P1)
- **Intent:** make the platform's quantitative claims defensible — real statistical tests, confidence
  intervals, reproducibility/lineage scoring, and "peer review" via multiple local LLMs cross-checking.
- This pillar is the most genuinely-implemented (real scipy/statsmodels). Keep, harden, and make it the
  **gatekeeper**: any number the app shows the user should pass through honest-uncertainty reporting.

### 5.8 Real-Time Monitoring & Alerting — *Pillar 4* (P2)
- **Intent:** continuous source surveillance; anomaly/trend/pattern detection; threat-intel enrichment;
  multi-channel alerts (email/webhook/chat) with rules and escalation.
- ⚠️ DECIDE: current health checks are simulated (`sleep; return HEALTHY`) and threat-intel/STIX-TAXII
  don't exist. Confirm scope: real source-uptime monitoring + anomaly alerts on the corpus is
  achievable and valuable; STIX/TAXII, SMS/Twilio, Slack/Teams are heavy — in or out?

### 5.9 Financial Intelligence — *Pillar 5* (P2, marked 0% in docs)
- **Intent:** scrape global exchanges (OHLC + fundamentals) from open web sources (no APIs/paywalls),
  detect fluctuations/patterns/anomalies, and **correlate price movements with news** in the shared DB.
- ⚠️ DECIDE: This is **design-only (0% built)** despite committed scaffold code. Confirm it's a real
  target and, if so, its realistic first scope (e.g. a handful of exchanges, daily OHLC, correlation to
  articles) rather than "50+ exchanges / 10,000+ companies" day one. Note: robust multi-exchange
  scraping without APIs is a large, brittle undertaking.

### 5.10 Rare-Earth / Commodity Intelligence — *Pillar 6* (P2, marked 0% in docs)
- **Intent:** same pattern as Pillar 5 for the 17 rare-earth elements — prices, production, inventory,
  correlated to geopolitical/news events; with forecasting.
- ⚠️ DECIDE: Also **design-only (0% built)**. Confirm scope and priority vs Pillar 5. (Fix needed: the
  price-normalization unit math is currently wrong by ~1000×, and currency isn't converted.)
  ⚠️ DECIDE: Is "forecasting" in scope? Honest forecasting with uncertainty is hard; recommend deferring.

### 5.11 Email & Newsletter Intelligence (P1/P2)
- **Intent:** retrieve from IMAP/POP3 and newsletter sources (Substack/Mailchimp/RSS-to-email), parse +
  clean, handle attachments (PDF/Office/images w/ OCR), extract entities and communication networks,
  and **fold into the same searchable corpus**.
- **Privacy/consent is paramount here** (private communications): explicit authorization, encrypted
  credential storage, data-minimization, retention/right-to-be-forgotten.
- ⚠️ DECIDE: Newsletter-API integrations (Substack/Mailchimp/etc.) vs. just IMAP + RSS-to-email for v1?

### 5.12 GUI / UX (P0 for core, P1+ for pillar dashboards)
- **Core GUI:** search interface, results browsing, source management, export, basic dashboards.
- **Pillar dashboards (later):** financial heatmaps/charts, commodity views, monitoring/alerts, email
  inbox, correlation explorer.
- ⚠️ DECIDE: **Web UI vs desktop app.** Docs simultaneously describe a browser app at `localhost:8000`
  **and** a Tkinter desktop app (installer pulls `python3-tk`, QA mentions "GUI/Tkinter testing"). Pick
  one primary surface. (Recommendation: web UI served by FastAPI; drop Tkinter.)
- ⚠️ DECIDE: Front-end stack — current mix is vanilla JS + React/Recharts via CDN. Pick one and vendor
  it locally (offline/privacy requirement).

### 5.13 Reporting & Defensible Output (P1)
- Generate investigation reports that bundle findings **with their provenance** (sources, timestamps,
  hashes, methods, uncertainty).
- **Chain-of-custody / integrity:** cryptographic signing + tamper-evidence on exported evidence
  (the crypto modules exist but aren't wired in). This is what makes the "legal admissibility" claim
  real rather than decorative.

---

## 6. Non-functional requirements

- **Platform:** Debian 13 primary. ⚠️ DECIDE: other Linux / cross-platform support level.
- **Python:** single target version, consistently configured everywhere. ⚠️ DECIDE: 3.12 (what CI/
  tooling actually targets) vs 3.13 (what `.python-version` claims but dependencies can't satisfy).
- **Install footprint:** a true **minimal core** (web + DB + search, lightweight) separable from heavy
  optional extras (ML/LLM). One coherent dependency strategy — not six disagreeing manifests.
- **Security:** parameterized DB access only (no blocklist "sanitizers"); real auth on any networked
  deployment; no secrets in code; metrics endpoint protected; safe installer (no unconfirmed `rm -rf`,
  no unverified `curl|sh`).
  ⚠️ DECIDE: **Deployment/threat model** — single-user localhost desktop (minimal auth needed) vs
  self-hosted multi-user server (full auth + RBAC needed) vs both. This decision drives the whole
  security model.
- **Performance:** non-blocking I/O for network/LLM work; bounded concurrency; the app stays responsive
  while scraping/inferring. Targets (throughput/latency) defined per realistic hardware, not aspirational.
- **Offline:** all assets, models, and fonts local; documented air-gap procedure.
- **Observability:** structured logs, honest health checks, Prometheus metrics — reflecting real state.

## 7. Explicit non-goals / out of scope (proposed — adjust)

- Not a general-purpose web crawler/mirror (the HTTrack lineage is vestigial; drop the framing).
- Not a paywall bypass, credential-stuffing, or ToS-violating scraper.
- Not a cloud/SaaS product; no external AI APIs.
- ⚠️ DECIDE: Are forecasting (5.10), social-media ingestion (5.8), and media-forensics (5.6) in or out
  for the first real release?

## 8. Data, provenance & legal-defensibility model (cross-cutting)

- Every stored item: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Every derived/analytic result: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **confidence is never a hardcoded constant.**
- Exported evidence: optionally **signed**, with a verifiable manifest (hashes + Merkle/GPG) so a third
  party can confirm integrity. This is the concrete meaning of "Pillar 4: Legal Admissibility."

## 9. Decisions I need from you (consolidated `⚠️ DECIDE` list)

1. **MVP scope:** core spine only first, or core + which pillar(s)?
2. **Rebuild strategy:** greenfield rewrite of a small core vs. salvage/repair the existing scaffold.
3. **Deployment & threat model:** single-user localhost vs multi-user server vs both (drives auth).
4. **Media forensics (Pillar 3):** cut / rebuild-real / keep-but-label-experimental.
5. **Financial (5) & commodity (6):** real targets now, later, or cut? Realistic first scope?
6. **Email:** IMAP+RSS only, or full newsletter-API integrations?
7. **GUI:** web vs desktop (Tkinter); front-end stack; vendor assets locally.
8. **Platform/Python/DB/Redis:** confirm targets.
9. **License:** GPLv3 vs AGPL-3.0, project-wide.
10. **Out-of-scope confirmation:** forecasting, social ingestion, etc.

## 10. Suggested phasing (proposal, not a commitment)

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

*This synthesis is intended to be edited. Strike, reprioritize, or expand any section — especially the
`⚠️ DECIDE` points — and I'll fold your changes into a finalized product spec and a matching build plan.*
