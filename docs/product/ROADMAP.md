# Product roadmap — Open Omniscience

> Strategic backlog synthesised from the [use-case scenarios](USE_CASES.md) and the v0.0.7
> audit (`docs/audit/`, `PARKED.md`). Every item cites the gap or finding that motivates it,
> respects the §0.5 invariants (local-first, ethical-by-construction, FOSS-only, auditable,
> provenance, operator-privacy), and carries an explicit invariant check. This is the
> product-strategy companion to the engineering planning in
> [`docs/ROADMAP.md`](../ROADMAP.md).

## 1. Backlog

| ID | Category | Item | User value | Depends on | Effort | Invariant note |
|----|----------|------|-----------|-----------|--------|----------------|
| RM-01 | quality | Pay down audit debt: `Mapped[]` ORM migration (MAINT-03) → flip mypy to blocking; convert remaining `print()`→logger (MAINT-04) | Fewer latent bugs; CI catches type regressions | — | L | none |
| RM-02 | quality | Endpoint test coverage for keyword_management / reporting / framing / LLM HTTP (TEST-05); rate-limit timing test (TEST-04) | Confidence that mutating endpoints don't silently break | — | M | none |
| RM-03 | ethics-trust | Make the DuckDuckGo topic-discovery (ETH-02) a clearly-gated, off-by-default setting with an in-UI "this leaves your machine" notice | Honors operator-privacy for at-risk users | — | S | Keeps the one external call explicit & opt-in |
| RM-04 | performance | Vectorise MinHash (PERF-01 parked); stream large exports instead of buffering | Faster near-dup on big corpora; bounded memory on export | — | M | Local-only; no new deps beyond numpy (already an extra) |
| RM-05 | capability | Local semantic / embedding search + NER entity index (offline model, e.g. via the existing optional spaCy `[nlp]` extra) | "Find this entity across spellings/languages"; the #1 cross-scenario gap (1,3) | RM-01 | XL | Model runs locally; no cloud; results labelled as assistance |
| RM-06 | capability | Incremental-crawl scheduler polish + push/folder-drop export (newsroom integration) | Hands-off corpus upkeep (4) | — | M | No inbound network service; loopback only |
| RM-07 | UX | Report/methods-appendix generator (verdict template for fact-checkers; query+params+versions for reproducibility) | Faster defensible output (3,7) | — | M | Cites stored hashed objects only; no fabricated claims |
| RM-08 | packaging | Offline wheelhouse installer + `.deb` / reproducible build for air-gapped & Qubes | Air-gapped classrooms and at-risk installs (5) | — | M | Strengthens local-first; reproducible = auditable |
| RM-09 | UX | "Lite mode" UI that hides tabs whose extra isn't installed | Cleaner low-spec experience (6) | — | S | Honest: reflects real capability, never fakes it |
| RM-10 | ethics-trust | Standing security/dependency-audit cadence in CI (bandit+pip-audit already added; add scheduled run + advisory dashboard) | Trust is the product; catch CVEs early | — | S | No telemetry; runs in CI only |
| RM-11 | capability | Semantic-network visualization (who-cites-whom graph export + in-UI view) | Disinfo spread artifact (2,8) | RM-05 | L | Counts/links only; no inferred "bot" verdicts |
| RM-12 | capability | First-class corpus-wide LLM synthesis (multi-article summary, honest, provenance-tracked, bounded fan-out) | Cross-source sense-making (8) | — | M | Local Ollama; bounded batch (no OOM); assistance not verdict |
| RM-13 | quality | Postgres parity *or* formal SQLite-only commitment (ARCH-06): if pursued, add a `tsvector` FTS path + a Postgres CI matrix | Removes the capability ambiguity | RM-01 | L | Whichever path, docs stay honest about what's tested |
| RM-14 | capability | Real, *measured* coordination/stylometry models (the honest successor to quarantined "propaganda/bot detection") — published methods, reported accuracy, or labelled experimental | Rebuilds a flagship use case without fabrication (2) | RM-05 | XL | HARD LINE: a score must come from a real method or not exist |
| RM-15 | capability | Richer, provenance-preserving exports (graph formats, multi-series chart export, versioned schema) | Interop with researchers' own tooling (2,4,8) | RM-07 | M | Exports carry provenance; FOSS formats only |
| RM-16 | capability | Multi-LLM cross-validation (run N local models, surface agreement/divergence, never a single "truth") | Higher-trust LLM assistance | RM-12 | L | All local; surfaces divergence, asserts nothing |
| RM-17 | capability | Pluggable source/analysis connector architecture | Community-extensible without forking | RM-01 | XL | Plugins must declare network use; sandbox review |
| RM-18 | UX | UI internationalisation completion (i18n scaffold exists) | Reach non-English newsrooms | — | M | Bundled locales, no web fonts/CDN |
| RM-19 | capability | Automated background source identification & aggregation: a discovery agent (corpus citation-promotion + Wikidata catalog refresh offline; DuckDuckGo channel behind the RM-03 gate) feeding a visible **candidates** staging state, with a full activity log and a user-set resource budget in Settings (see `docs/FUTURE_DEVELOPMENTS.md`) | Coverage grows without operator plumbing effort — focus on content, not source wrangling (all personas; esp. 1,2,4) | RM-03 | L | **Transparency non-negotiable:** background ≠ hidden — every query/candidate visible & logged; external channel opt-in and individually toggleable; candidates verified real (the `fabricated_sources.md` lesson) before promotion; budgeted, never resource-greedy |
| RM-20 | capability | **Investigation recipes + the `/investigate` dashboard** (committed for 0.0.8, WP8/WP9 of `RELEASE_0.0.8_PLAN.md`): the ten space-time scenarios become Home-screen cards (a producer per scenario; `recipe` field on `Card`) whose "Open investigation ↗" button opens a **dedicated, card-adjusted dashboard in a new browser tab** — all related information auto-assembled (map window, article set, diffs, charts via existing APIs) plus a suggestions strip for deeper analyses. Main UI stays free; several investigations can run in parallel tabs. Active recipes are a Settings choice | One-click investigations: the app does the legwork and presents it coherently, the user keeps the judgement (all personas) | — | M+L | Reuses the producer/registry/`Card` engine incl. the `CardSchemaError` no-composite-score guard; dashboards are URL-parameterised views over existing tested APIs (no CDN/framework, same as `/` and `/desk`); suggestions are pre-filled actions the user could do manually, invoking only real methods with method+caveat+n — automates gathering, never the verdict |

## 2. Prioritisation (RICE)

`RICE = Reach × Impact × Confidence ÷ Effort`. Reach 1–5 (fraction of personas served),
Impact 1–3, Confidence 0.5–1.0, Effort in person-weeks (S=1, M=3, L=6, XL=12).

| ID | Reach | Impact | Conf | Effort | **RICE** | Tier |
|----|------|--------|------|--------|---------|------|
| RM-03 | 3 | 2 | 1.0 | 1 | **6.0** | Now |
| RM-10 | 5 | 1 | 1.0 | 1 | **5.0** | Now |
| RM-02 | 4 | 2 | 0.9 | 3 | **2.4** | Now |
| RM-09 | 2 | 1 | 1.0 | 1 | **2.0** | Now |
| RM-07 | 3 | 2 | 0.8 | 3 | **1.6** | Next |
| RM-06 | 3 | 2 | 0.8 | 3 | **1.6** | Next |
| RM-01 | 5 | 2 | 0.9 | 6 | **1.5** | Now/Next |
| RM-05 | 5 | 3 | 0.7 | 12 | **0.9** | Next |
| RM-15 | 3 | 2 | 0.8 | 3 | **1.6** | Next |
| RM-04 | 2 | 1 | 0.9 | 3 | **0.6** | Next |
| RM-12 | 3 | 2 | 0.7 | 3 | **1.4** | Next |
| RM-08 | 2 | 2 | 0.8 | 3 | **1.1** | Next |
| RM-11 | 3 | 2 | 0.6 | 6 | **0.6** | Later |
| RM-13 | 2 | 1 | 0.7 | 6 | **0.23** | Later |
| RM-18 | 3 | 1 | 0.8 | 3 | **0.8** | Later |
| RM-16 | 2 | 2 | 0.6 | 6 | **0.4** | Later |
| RM-14 | 3 | 3 | 0.5 | 12 | **0.4** | Later |
| RM-19 | 4 | 3 | 0.6 | 6 | **1.2** | Next |
| RM-20 | 5 | 3 | 0.7 | 3 | **3.5** | Now/Next |
| RM-17 | 2 | 2 | 0.5 | 12 | **0.17** | Later |

## 3. Horizons

### Now — next release (0.0.8): "trustworthy MVP, hardened"
*(Executable work-package plan: [RELEASE_0.0.8_PLAN.md](RELEASE_0.0.8_PLAN.md).)*
Ship the honestly-scoped functional MVP (ingest → dedup → store → search → export, reliably)
with the trust surface tightened. **RM-03** (gate the DuckDuckGo call), **RM-10** (standing
audit cadence — builds on the bandit/pip-audit CI gates this audit added), **RM-02** (close the
endpoint test gaps), **RM-09** (lite mode), and start **RM-01** (begin the `Mapped[]` migration).
**RM-20** (investigation-recipe cards) scores highest of the new items (RICE 3.5) and is a
strong early candidate — it reuses the existing card engine and is the most visible payoff of
the space-time substrate for end users. Exit: the audit's 5 deferred findings closed or
formally accepted; CI fully blocking on lint+types.

### Next — 1–2 releases (0.0.9–0.1.0): "deeper sense-making"
The capabilities the scenarios most want: **RM-05** (semantic/NER search — the #1 cross-scenario
gap), **RM-07** + **RM-15** (report generator + richer provenance-preserving exports),
**RM-06** (scheduler/integration polish), **RM-12** (corpus-wide LLM synthesis), **RM-08**
(offline/Qubes packaging), **RM-04** (perf), and **RM-19** (automated background source
discovery — offline channels first, the gated DuckDuckGo channel once RM-03 ships). This is
the jump from "searchable archive" to "sense-making workbench" and is the natural gate to a
**0.1 public alpha**.

### Later — vision (post-0.1): "intelligence platform, still local-first"
The ambitions that need the foundation above: **RM-11** (semantic-network visualization),
**RM-16** (multi-LLM cross-validation), **RM-14** (real, measured coordination/stylometry —
the honest rebuild of the quarantined deception-defense pillar), **RM-13** (Postgres parity if
scale demands it), **RM-17** (plugin architecture), **RM-18** (full i18n). Each must clear the
same bar that quarantined the originals: *a score comes from a real method or it does not exist.*

## 4. Cross-cutting tracks (every horizon)

- **Test-coverage targets:** core paths ≥ 80%; no release lowers overall coverage. The
  core-only CI job (audit TEST-06) and the full suite stay green every release.
- **Security/dependency cadence:** the blocking bandit + pip-audit gates added in v0.0.7 run on
  every push; add a scheduled weekly run so a newly-published CVE surfaces without a push.
- **Performance budgets:** the v0.0.7 benchmarks (`scripts/benchmark_audit.py`) are regression
  gates — recency-browse p50 < 5 ms on 50k rows; near-dup linear; DB size watched (the −63%
  index win must not regress).
- **Ethics/trust track:** every new surface states its limit; a transparency note per release of
  exactly what (if anything) leaves the machine; robots/ToS posture re-affirmed; provenance UX
  kept first-class. Trust is the product's core value proposition, so it gets a standing track,
  not ad-hoc attention.

## 5. Broadening reach (with trade-offs)

- **Export/interop formats** (RM-15): graph (GraphML/JSON), versioned CSV/JSON schema, chart
  export. *Trade-off:* schema stability vs. flexibility — pin a versioned contract.
- **Optional local API/SDK** for journalists' own tooling (read-only, loopback). *Trade-off:*
  surface area vs. safety — keep it loopback, no inbound service, document clearly.
- **UI i18n** (RM-18): bundled locales only (no web fonts/CDN — preserves offline/no-leak).
- **Distribution** (RM-08): `.deb` + reproducible build + Qubes/Tails packaging. *Trade-off:*
  packaging maintenance cost vs. reach for at-risk users — high value, worth it.
- **Plugin architecture** (RM-17): community connectors. *Trade-off:* extensibility vs. the
  FOSS/local-first/auditable guarantees — plugins must declare network use and pass review; no
  proprietary or telemetry plugins. **Non-negotiable: every broadening stays FOSS, local-first,
  and auditable.**
