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

## 0. Deployment context (RESOLVED — drives everything below)

This build targets **one specific environment and one user**. These answers are now fixed and resolve
several of the former `⚠️ DECIDE` points.

- **Host:** Qubes OS, running inside a **Debian AppVM** (template-based).
- **Python:** **3.13 as the default interpreter.**
- **User:** a **single primary user (the project owner)** — no multi-tenant accounts, no RBAC.
- **Surface:** **web UI + REST API bound to `127.0.0.1` only** (loopback). No external listeners.
- **Network posture:** local-first; outbound only during scraping/LLM-pull; **no inbound** anything.

### 0.1 What Qubes changes about the design

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

### 0.2 Python 3.13 implications (resolves the dependency-version conflicts)

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

### 0.3 Security model for a single local user (simplifies the P0s)

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
- ✅ RESOLVED (§0): **web UI served by FastAPI at `127.0.0.1:8000`; Tkinter desktop app is dropped**
  (remove `python3-tk`). Open in the AppVM's browser.
- ✅ RESOLVED (§0): front-end is **vanilla JS + vendored libraries (served from `/static`)** — no CDN.
  ⚠️ DECIDE (minor): keep charts lightweight (e.g. a small vendored charting lib) vs none in v1.

### 5.13 Reporting & Defensible Output (P1)
- Generate investigation reports that bundle findings **with their provenance** (sources, timestamps,
  hashes, methods, uncertainty).
- **Chain-of-custody / integrity:** cryptographic signing + tamper-evidence on exported evidence
  (the crypto modules exist but aren't wired in). This is what makes the "legal admissibility" claim
  real rather than decorative.

---

## 6. Non-functional requirements

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

## 9. Decisions (consolidated)

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
