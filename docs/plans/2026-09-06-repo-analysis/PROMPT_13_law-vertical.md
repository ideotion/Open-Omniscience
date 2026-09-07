# Prompt 13 — The law vertical: enumeration, gazettes, and honest coverage

> **Scope:** `src/law/`, `configs/legal_sources_generated.yml`, the law surfaces.
> **Gated on:** F1 ⛔ (the egress allowlist — S1 cannot start without it), A3-law granularity (already
> ruled), L6.
> **Sequencing:** independent. S2, S3, S4 and S5 are buildable **without** egress.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md` and the
CLAUDE.md law rulings 34–37 with their 2026-08-20 status amendment.

**The staleness guard is emphatic here.** This vertical changed four times in its first six days, and rulings
36 and 37 turned out to be already shipped when a session went to build them. Ruling 35's literal form is
*impossible* — `baseline_text` and `full_text` hold normalised text and `raw_html` is never persisted, so a
retroactive re-extraction over stored copies has no subject — and its structural intent is already met by
`check_document`, which re-reads a tracked document's own baseline through the strip stage on its next
successful poll and deliberately records **no revision** (a fabricated flagged amendment on a legal audit
trail is worse than the chrome).

## 1. What exists

225 sources plus 7 documents across 162 jurisdictions in the generated catalog, world-swept and validator-clean.
The CLML adapter's **offline** half is built (`src/law/adapters/`), reading a statute into addressable
provisions with three non-collapsing dates. The strip stage, the coverage diagnostic, add-by-URL, the LAW
provenance class and channel-implied tags all shipped. Laws are first-class corpus Articles through
`index_article`.

What is missing is enumeration — and therefore coverage.

## 2. Slices

### S1 — ⛔ F1: the live enumeration adapters

`legislation.gov.uk`, `eur-lex.europa.eu` and `gesetze-im-internet.de` all answer `CONNECT` 403 through the
agent proxy, re-verified 2026-08-20. So no endpoint shape could be confirmed and **none was invented** — the
fixtures are hand-authored and labelled as such in `tests/fixtures/law/PROVENANCE.md`.

The adapter was built to survive being wrong (local-name matching, unknown elements reported with their text
kept, an unrecognised root refused rather than half-parsed, and a text-recovery floor that refuses when too
little of the body was understood — the one check that holds if every schema assumption is wrong). That is
insurance, not evidence.

**The one operator step that unblocks everything:** fetch one CLML `…/data.xml` on a networked machine and run
`parse_clml`. If it parses at or above the recovery floor with an empty `unknown_elements`, the schema
assumptions hold and the enumeration is worth building. If not, the report **names** what it did not
understand, which is why it was built that way.

Ruling A4 sequences this adapter-first over breadth-first. Ruling A3 sets granularity: act/code-level
`LawDocument` by default, per-legal-article rows **only** for structured bulk sources that pre-split (the
LEGI class).

### S2 — S7: gazettes as streams (no egress needed for the wiring)

Four verified RSS feeds sit in `configs/legal_sources_generated.yml` and never become an `rss_url`, so they
never reach the normal pipeline. Vietnam and St Vincent's `legal.gov.vc` (a working Joomla gazette feed) are
the two confirmed. Wire them as `source_type legal` through the ordinary ingest path — this is the cheapest
real coverage in the vertical.

**BUILT 2026-09-07, and the count above is off in both directions.** Reading each row's *evidence*
rather than its `verification.status` gives THREE feeds whose own record says somebody fetched them
(Georgia's `matsne.gov.ge` as well as the two named) and ONE — Uruguay's `impo.com.uy` — whose feed
was never fetched at all and whose own notes call it the site's generic WordPress news feed. All
four rows are `verification.status: fetched`, because that field is about the PORTAL, not the feed.
A feed now carries its own tier (`gazette_feed_verification`) and only `fetched` is promoted.

### S3 — S4b: the catalog's language never reaches the document

**STALE — VERIFIED-PRESENT at `main` @ `690920e2` (checked 2026-09-07, not rebuilt).** The claim
below was already false when this prompt was written: `LawDocument.language` / `.country` are
declared at `src/database/models.py:2187-2188`, `register_documents` populates them from the
catalog and heals both the row and its already-ingested Article, and `upsert_law_corpus_article`
passes `language=doc.language` into the Article (`src/law/corpus.py:119`). Shipped 2026-07-17 as
S4b. The original text is kept below as the problem statement it was.

> `LawDocument` has no language or country column, and law corpus Articles ingest with `language=None`. So
> **Cambodian law, which is in French**, gets the wrong keyword treatment — the catalog knows and the document
> does not. Thread catalog → `LawDocument` → `Article.language`. The catalog carries languages-of-the-law
> deliberately distinct from the country's spoken languages, which is exactly why this is worth threading
> rather than inferring.

### S4 — Coverage denominators from the source's own enumeration

The completeness principle is the coverage bar: a portal is an entry point, never a coverage claim. Covering a
jurisdiction means covering its **own official enumeration** — France's 76 codes en vigueur plus
non-codified statutes, Germany's thousands, every `ukpga`/`uksi`.

27 dated official counts already landed in the catalog and are real denominators (Armenia 208,987 acts;
Colombia 87,392 normas; Cabo Verde 76,947; Madagascar 40,000; Belarus and Georgia 26 codes each; Uruguay 13).
The diagnostic must report tracked-versus-enumerated using **those**, and where no enumeration adapter exists
say "coverage unknown" rather than printing a ratio against a number it invented. Two counts are self-disclosed
as not read off the official page (Council of Europe via Wikipedia; the African Union manual tally) — keep the
disclosure attached to the figure.

**BUILT 2026-09-07; the count is 39, not 27, across 32 countries** (measured: `official_count` on a
source row). No ratio is printed anywhere — the join runs only through the country a document
itself states, and nothing declares the enumerated units commensurable with an act/code-level
tracked document. See the open question this raises for the maintainer.

### S5 — A5: AI change summaries

**STALE — VERIFIED-PRESENT at `main` @ `690920e2` (checked 2026-09-07, nothing extended).** The
instruction to verify the wiring first was the right one and it answers the whole slice:
`advance_law_summaries` runs as a scheduler ride-along (`src/scheduler/runner.py:1263`),
`summarize_revision` is the on-demand path (`src/api/law.py:378`), the language floor is
`UI_LOCALE_CODES` (`pending_ai_summaries`), and each summary stores model + prompt_version + the
verbatim prompt text. Ruling A5 is met as written; there was nothing to extend.

> Auto at track time for UI-language-floor jurisdictions, on demand elsewhere, always labelled
> "AI-derived · unreliable". `src/law/summarize.py` exists; verify what it is wired to before extending it.

### S6 — The vetting board (operator, but prepare it)

Nine leads to decide; roughly 25 domains the acquisition sessions flagged as robots-blocked or bot-walled —
they cannot be scraped fail-closed, so each is an adapter/API path or an honest gap, and saying which is a
per-domain judgement. Grenada's `laws.gov.gd` is down; North Korea is a confirmed documented gap with its
evidence preserved verbatim in the catalog. Present these as a table the maintainer can answer in one pass.

### S7 — L6: `[pdf]` in the default install

A default install cannot read a PDF statute because `[pdf]` is optional and the code degrades loudly. Either
promote it or say so in the coverage report — the current state is that the report is silently narrower than
the catalog.

## 3. Scope fence

Never fabricate a source or an endpoint: every committed endpoint is fetched by the session that commits it,
tiered `fetched` / `search-verified` / `lead`, and a `lead` ships disabled. Never scrape around a robots
refusal. Do not build breadth-first coverage ahead of the adapters (ruling A4).
