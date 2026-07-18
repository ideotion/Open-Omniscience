# Autonomous session brief — the LAW vertical: verify, surface, then scale to every country (2026-07-17)

**Status:** plan of record, ready for execution. **Executor:** one autonomous Claude Code CLI
session on the maintainer's machine (OPEN EGRESS — live source verification is a core task).
**Mission (maintainer, 2026-07-17):** *"a proper, intelligent, adapted and performant strategy to
scrape each country's legal articles, law articles (all types of laws), ingested the same way
articles are, with the possibility to track their changes. Currently I don't see anything working
despite my previous attempts."*

**The honest headline this brief is built on:** the vertical is NOT missing — it is 6 days old,
substantially built, and was BROKEN-INVISIBLE for exactly the window of the maintainer's attempts
(§1). So the session's order is: **(A) prove the built vertical works end-to-end and make that
visible, (B) fix the real UX/honesty gaps that made working code look dead, (C) scale coverage
from ~17 curated documents toward per-country corpora via verified adapters.** Building C on top
of an unverified A would repeat the exact failure the maintainer just experienced.

---

## §0 Working mode (binding)

- **Base:** `git fetch origin main` immediately before `git checkout -B <branch> origin/main`.
  Branch: `claude/law-vertical-<suffix>`. ONE draft PR onto `main`, one commit per slice.
  Nothing self-merges.
- **STALENESS GUARD — emphatic here:** the law vertical changed FOUR times in the 6 days before
  this brief (schema #625 → corpus body `fc75aa0` → the #691/#696 session-poisoning pair → the
  `38c0502` cross-driver fix, landed the SAME DAY as this brief). Re-verify every §1 claim
  against the tree before acting; a found-already-fixed item is verify-and-marked, never rebuilt.
- **Gates per slice:** full suite in the py3.13 venv (or the documented CI-only subset),
  ruff (project config) + per-file mypy, `node --check` on any JS edit, i18n `--min 100` if
  locales are touched, invariant guards extended with each shipped behavior.
- **Skeptics-before-push** with the NEGATIVE-SPACE lens on every parser/adapter slice (a law
  parser that fabricates or mangles text is worse than none — enumerate should-be-empty inputs).
- **NEVER fabricate a source or endpoint** (the project was burned before): every adapter
  endpoint, feed URL, or bulk-data path is LIVE-FETCHED by this session before it is committed,
  and carries a verification status (✅ fetched-and-parsed here · 🔎 search-verified only ·
  ❓ unverified lead — the V1_PATHWAY §4 convention). A ❓ row ships DISABLED.
- **Law-specific honesty (binding, from GOVERNANCE + the catalog header):** a research mirror,
  NEVER the authoritative source and never legal advice — every record links to the official
  gazette; robots fail-closed applies to government sites exactly like everyone else (no
  gov-site bypass, ever); licenses respected ("public ≠ freely redistributable"); provenance
  stored; degrade loudly. Caveats visible ×12 on every new surface.
- **Ledger closeout:** shipped.csv row per slice; lessons harvested; carry-overs stated.

---

## §1 GROUND TRUTH (investigated 2026-07-17 against `main` @ `af30b39` — re-verify, then trust)

### What EXISTS and is wired end-to-end

| Piece | Where | State |
|---|---|---|
| Models | `LawDocument` (+`latest_text`/`latest_text_revid`) · `LawRevision` (+`full_text`, capped diff, flags) — `models.py:1862-1941` | ✅ |
| Catalog | `configs/legal_sources.yml`: ~47 official portal `sources:` (all real domains, worldwide) + ~17 tracked `documents:` (HRA, GDPR, AI Act, Grundgesetz, US Constitution, …) | ✅ boot-seeded, idempotent (`main.py:164-179`, `OO_AUTOSEED` gated) |
| Tracker | `src/law/track.py`: baseline → unchanged → revert → change; PDF-vs-HTML autodetect; `_MIN_TEXT=200`; diff capped 4000 lines; flags via the wiki flagging engine | ✅ |
| **Auto-tracking** | `auto_track_due` — 5 docs/pass, 24 h freshness gate, round-robin, on EVERY online collect pass (`runner.py:1245-1254`, opt-out `auto_track_law`); plus the manual full pass (`mode=="law"`) | ✅ wired since the 2026-06-22 field test |
| Corpus ingest | `src/law/corpus.py`: tracked laws are first-class `Article`s under `law.<jur>.local` (`source_type="legal"`) through THE `index_article` hook — keywords, When×Where×Who, FTS | ✅ landed `fc75aa0` (2026-07-14) |
| API | `/api/law/{status,documents,changes,track,seed,documents/{id},documents/{id}/view}` — incl. a standalone reader page with an amendment timeline | ✅ |
| Surfaces | Governments tab → **Law** subtab; omnibar "World law" group (title match); `law_change` + `model_legislation` briefing cards | ✅ |
| Tests | `test_law.py`, `test_law_corpus.py`, `test_law_reader.py`, `test_law_text_columns.py` — heavily pinned | ✅ |

### Why the maintainer saw NOTHING (ranked; the first is the big one)

1. **A cross-driver IntegrityError silently poisoned the tracking pass on the ENCRYPTED default
   store** — `track.py`/`corpus.py` caught only `sqlalchemy.exc.IntegrityError`, missing
   sqlcipher3's unwrapped class, so the first benign duplicate revision aborted the whole pass.
   **Fixed `38c0502` (2026-07-17)** — the 4th recurrence of the family that also produced #691
   (2026-07-15, session poisoning) and the #696 savepoint fix-forward (2026-07-17). The
   maintainer's attempts fell EXACTLY inside this broken window.
2. **Discoverability:** the sidebar tab is labelled **"Governments"** (renamed 2026-06-22; the
   `data-tab` stays `law`), and it always opens on the Countries subtab — the Law tracker is two
   clicks deep and never default.
3. **The changes panel is empty BY DESIGN:** `/api/law/changes` defaults `flagged_only=True` +
   `delta_bytes != 0` — consolidated statutes rarely produce large flagged amendments, so a
   perfectly working tracker renders "no changes yet" indefinitely.
4. **Baselines need sustained ONLINE passes** (5 docs/pass, 24 h gate): a mostly-airplane
   install or a fresh store shows few/zero baselines.
5. **Robots fail-closed on some gov hosts** → those docs sit at `last_status="fetch error…"`,
   visible only in a table column nobody reads.
6. **PDF is an optional extra** (`[pdf]`/pypdf): PDF gazettes store no body without it
   (defaults are mostly HTML, so secondary).

### The REAL gaps vs the mission

- ~17 hand-curated documents ≠ "each country's laws, all types" — no per-country enumeration.
- **No add-a-document-by-URL** endpoint or UI (editing YAML + re-seed is the only way).
- `law` is NOT in `PROVENANCE_CLASSES` (`provenance.py:36` — law articles bucket as `web`),
  despite `corpus.py`'s "filterable provenance class forever" docstring.
- No per-vertical freshness/coverage diagnostic (the vertical pattern mandates one).
- Fetch verdicts per document are not surfaced honestly in the UI.

---

## §2 The strategy in one paragraph

Keep the proven shape — **curated tracked documents + change tracking + laws-as-Articles** — and
scale it with **per-jurisdiction ADAPTERS that prefer official STRUCTURED/bulk endpoints over
HTML scraping** (the stats-vertical "SDMX before scraping" precedent): most serious jurisdictions
publish their consolidated law as open data (XML/API/bulk), which is *better* than scraping —
stable IDs, revision metadata, whole-corpus enumeration, and far kinder to the host. HTML
tracking stays the fallback for jurisdictions without structured publishing. Gazettes (daily
official journals) are a THIRD stream: many have RSS and flow through the EXISTING news pipeline
as `source_type: legal` sources. Coverage grows catalog-first (a dated, registry-tracked file),
floor = the 12-UI-language countries (the elections coverage-floor precedent), then outward.

**THE COMPLETENESS PRINCIPLE (maintainer clarified 2026-07-17 — this is the coverage bar):**
a portal entry is an ENTRY POINT, never a coverage claim. "Covering a country" means covering
the jurisdiction's OWN official enumeration of its corpus — **France alone has 76 codes en
vigueur** (Légifrance's code list, maintainer-verified live 2026-07-17; the sandbox 403s the
page — the executing session re-verifies the count at
`https://www.legifrance.gouv.fr/liste/code?etatTexte=VIGUEUR`) plus the non-codified
consolidated statutes behind them; Germany's gesetze-im-internet indexes thousands of
laws/regulations; the UK's legislation.gov.uk holds every ukpga/uksi. The ~47 catalog portals
and ~17 tracked documents are seeds, not the destination. Consequences threaded through the
slices below: an adapter's `list_documents()` must enumerate the official collection COMPLETELY
(never a hand-picked sample presented as coverage); the S5 diagnostic measures coverage AGAINST
the official enumeration (the denominator comes from the source's own list — "France: 76/76
codes tracked", never "we track what we track"); and at that scale a whole-country legal corpus
takes the MANAGED-DATASET posture (the wiki-dump/PubMed architectural-separation precedent:
bulk ingest as task-manager download jobs, own storage accounting, own freshness diagnostics —
never 76,000 individual page fetches).

**SOURCE ACQUISITION AT WORLD SCALE (maintainer-ruled 2026-07-17):** the catalog grows through
PARALLEL INTERNET-CONNECTED research sessions producing a digestible enrichment file — the
contract, region-batch session prompt, offline validator, and the curated-wins intake seam are
in [`LAW_SOURCES_ACQUISITION_2026-07-17.md`](LAW_SOURCES_ACQUISITION_2026-07-17.md) (**intake +
validator ALREADY SHIPPED**: `load_legal_catalog` merges `configs/legal_sources_generated.yml`
when present; `scripts/validate_legal_catalog.py` lints it). The executing session CONSUMES that
file's metadata: `enumeration_url`/`official_count` → the S5 coverage denominators;
`structured:` (api/bulk/formats) → the S6 adapter-priority worklist; `languages` → S4b below
(legal language ≠ the country's majority language — Cambodian codes have official French
versions).

---

## §3 The slices (ordered; commit per slice)

### S1 — PROVE the vertical end-to-end, live (P0, the trust-reset) — size S
On the maintainer's networked machine: fresh store (or the live one), go online, let
`auto_track_due` run (or press "Track changes now"), then EVIDENCE in the PR body: N baselines
captured · the corpus Articles exist under `law.*.local` sources with keyword mentions · a law
found via omnibar AND via FTS body search · the reader page renders · per-doc `last_status`
values (incl. any robots-blocked hosts, listed honestly). If ANY step fails on the current tree,
root-cause and fix FIRST — this brief's §1 says it should work post-`38c0502`; verify, don't
assume. **Acceptance: a written, reproduced it-works trail — the thing the maintainer has never
seen.**

### S2 — Truth-in-UI: make working tracking LOOK like working tracking (P0) — size M
(a) The changes panel defaults to ALL real changes (`flagged_only=False`, `delta_bytes!=0`
kept), with the flagged filter as the toggle-on option; empty state says WHAT was checked ("17
documents tracked · 14 baselined · last pass 2 h ago"), never a bare "no changes". (b) Per-doc
status column surfaces the transport-aware verdict loudly (robots-blocked / fetch-error /
baselined / changed, with the honest hover per invariant #17). (c) A small "Law" pointer from
the Governments tab's default view (badge or stat chip: "Law: 17 tracked · 2 changes") so the
subtab is discoverable; do NOT change the default subtab without a click-through (fork-3
conservative). (d) Key new strings ×12. **Acceptance: a user landing on Governments can see the
vertical is alive without knowing where to click.**

### S3 — Add-a-document-by-URL (P1, the missing workflow) — size M
`POST /api/law/documents` (jurisdiction, title, url, official_url, category; validated,
deduped on `(jurisdiction,url)`, fetched through the ethical fetcher on first track — a
robots-blocked add is stored but reports its verdict honestly) + a small form in the Law subtab
(ensureOnline-gated for the immediate first fetch, or defer to the next pass) + DELETE/unwatch.
Tests incl. the negative space (bad URL, duplicate, robots-blocked). **Acceptance: the
maintainer can paste any statute URL and see it tracked without touching YAML.**

### S4 — `law` as a first-class provenance class (P1) — size S — **SHIPPED 2026-07-17**
**Shipped early in the same PR as this brief (verify + strike, never rebuild — the staleness
guard):** `LAW` joined `PROVENANCE_CLASSES`; `provenance_of` maps `source_type legal/ip` AND the
synthetic `law.*.local` domains → `LAW`; **plus the channel-implied TAGS system** (maintainer
same-day ask): `CLASS_IMPLIED_TAGS` + pure `implied_tags()` + the idempotent append-only
`ensure_channel_tags()` boot heal (wired into both seed sites) materialize channel tags onto
sources — `law` (+`ip`), `wikipedia,encyclopedia`, `statistics`, `newsletter`, `cited` — so
tag-based filters find those articles; `ensure_law_source`/`ensure_wiki_source` set tags at
creation. Tests extended (`test_provenance_class.py`, 17 green). REMAINING for this session:
verify the reading-diet/facet/Articles-toggle surfaces render the new class correctly in the
browser (fork-3) — the backend filter validates against the extended set already.

### S4b — Thread the legal LANGUAGE through to the corpus (P1, the Cambodia fix) — size S
The catalog carries per-source/per-document `language`, but registration DROPS it —
`LawDocument` has no language/country columns and `upsert_law_corpus_article` ingests law
Articles with `language=None`, so a French-language Cambodian code gets no French stoplist,
wrong keyword treatment, and no language facet. Fix: additive `language` + `country` columns on
`LawDocument` (migration + boot self-heal, the established pattern), populated from the catalog
at registration; `upsert_law_corpus_article` sets `Article.language` from the document; the next
track pass updates existing law Articles in place (idempotent re-ingest). Negative space: a
document with NO stated language stays `None` honestly — never guessed from the country.
**Acceptance: a tracked French-language document produces a corpus Article with
`language="fr"` and French keyword extraction; existing docs heal on their next track.**

### S5 — The law coverage/freshness diagnostic (P1) — size S
`GET /api/diagnostics/law-coverage`: per-jurisdiction doc counts, baseline coverage %,
last-checked ages, per-doc verdict tallies (robots-blocked named), adapter/catalog `*_AS_OF`
freshness — counts + method, no score. **Denominators come from the official enumeration**
(the completeness principle, §2): where an adapter exists, report tracked-vs-enumerated
("France: 12/76 codes"), and where none exists yet, say so honestly ("no enumeration adapter —
coverage unknown") rather than presenting the tracked count as coverage. Bundle member + the membership-ratchet classification
(the 2026-07-17 ratchet WILL redden the build until this is classified — that is by design).
**Acceptance: the maintainer's next "is law working?" is answered by one JSON.**

### S6 — The adapter seam + the first verified adapters (P2, the scale core) — size L
A `LawAdapter` seam per jurisdiction: `list_documents()` (enumerate a collection with stable
IDs) + `fetch_text(doc)` (+ revision metadata where the source provides it), catalog-driven from
a new `collections:` block in `legal_sources.yml` (dated `LEGAL_CATALOG_AS_OF`, registry entry
per the external-artifact rule). Adapters go through the ONE ethical fetcher; bulk downloads
become task-manager jobs (the wiki-dump pattern) — never unbounded crawls. **Build 2–3 adapters
maximum this session, each LIVE-VERIFIED here (fetch + parse a real document end-to-end before
committing).** Leads to verify, in recommended order (ALL ❓ unverified leads until this session
fetches them — never commit a ❓ as enabled):
- 🇬🇧 `legislation.gov.uk` — documented open XML/API (`/ukpga/2018/12/data.xml` pattern);
  point-in-time versions = revision metadata for free.
- 🇩🇪 `gesetze-im-internet.de` — per-act XML downloads (the Gesamtausgabe precedent is already
  in the catalog notes).
- 🇪🇺 EUR-Lex — ELI URIs / Cellar; consolidated versions carry CELEX-dated revisions.
- 🇫🇷 Légifrance — the PISTE API is KEY-GATED (defer; operator decision); the DILA **bulk
  open-data dumps** (LEGI) are the honest no-key path but are LARGE → a task-manager download
  job, gated like wiki dumps. Do not attempt both in one session. NOTE the architectural
  symmetry: LEGI publishes a full base + INCREMENTAL DELTAS — this is the law-world instance of
  the ruled Wikipedia "dump-as-baseline + delta" plan of record, and the ONLY honest way to the
  completeness bar (76 codes ≈ on the order of 10⁵ legal articles in force; scraping that
  page-by-page is neither polite nor performant). Verify the current DILA distribution
  point/format live before designing the job.
- 🇪🇸 BOE — documented open API (`boe.es/datosabiertos`); 🇺🇸 `uscode.house.gov` XML releases +
  govinfo bulk — later sessions.
Granularity inside an adapter: **the tracked/corpus unit stays the ACT (consolidated document)**;
per-legal-article splitting (Code civil ≈ 2,800 articles) is DEFERRED to a maintainer ruling
(§4 Q2) — an act-level Article already makes every legal article's text searchable, and diffs
name the changed articles. **Acceptance per adapter: enumerate a real collection, ingest ≥3 real
acts as corpus Articles, a re-fetch is idempotent, a changed consolidated version produces a
revision; negative-space tests (malformed XML, empty act, robots-blocked) pinned.**

### S7 — Gazettes as streams (P2) — size S
Verify (live) which seeded legal portals expose real RSS/Atom (BOE, Dziennik Ustaw, Federal
Register, EUR-Lex OJ daily…), fix their `Source` rows to carry the working feed URL, and confirm
they flow through the NORMAL news pipeline as `source_type: legal` articles (provenance class
LAW after S4). Feeds that don't exist are marked honestly (no feed → crawler-only or disabled).
**Acceptance: at least 3 verified gazette feeds producing law-stream articles in a normal pass.**

### S8 — Docs + closeout (P2) — size S
USER_MANUAL law chapter updated to the real flow (Governments → Law, auto-tracking cadence,
add-by-URL, the research-mirror/no-legal-advice framing); QUICKSTART one-liner; ledger rows;
carry-over list (untouched: per-article granularity ruling, Légifrance bulk job, more adapters,
`[pdf]` in the default install set — §4).

---

## §4 Maintainer decisions (collect, don't block — conservative defaults stated)

1. **`[pdf]` extra in the default install set?** Gazette PDFs need pypdf. *Recommend YES* (it is
   pure-Python); until ruled, S7 prefers HTML/XML feeds.
2. **Per-legal-article granularity** (one corpus Article per article of a code) vs act-level
   (current): storage/count implications (~2,800 rows for the Code civil alone; ~10⁵ legal
   articles in force across France's 76 codes, so a COMPLETE France at per-article granularity
   rivals a mid-size news corpus by row count) vs finer tracking and more precise change
   attribution. This ruling becomes SCALE-CRITICAL once the completeness principle (§2) is
   pursued — the answer likely differs per tier (act-level for HTML-tracked documents;
   per-article where a structured source gives stable per-article IDs like LEGIARTI).
   *Default: act-level; rule before the first whole-country bulk ingest, not after.*
3. **Coverage priority beyond the floor** (which countries next) + whether the Légifrance
   key-gated API is worth an operator key vs the DILA bulk path.
4. **Cadence** per category (gazette daily / consolidated weekly?) — current: 24 h gate,
   5 docs/pass. Fine at 17 docs; S6 must make the batch size scale with the watched count
   (still bounded per pass, politeness untouched).

## §5 Definition of done

S1's evidence trail exists; a fresh install shows a visibly-alive law vertical within one online
session; a pasted URL becomes a tracked, searchable, change-tracked corpus Article; ≥2 country
adapters + ≥3 gazette feeds are live-verified and shipped; law is a provenance class; the
coverage diagnostic rides the bundle; every source committed this session was actually fetched
by this session; all gates green; ledger closed out with carry-overs explicit.
