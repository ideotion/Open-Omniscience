# Prompt 18 — Wikipedia as a living source

> **Scope:** `src/wiki/`, the reader's tracked-changes surface, the dump path.
> **Gated on:** G10 (five questions), and — for the whole-edition half — the storage milestones.
> **Sequencing:** last among the vertical prompts. Its S1 is explicitly P0-scale-gated by a standing ruling.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md **"VERSIONED SOURCES AS FIRST-CLASS ARTICLES"** entry and the
FUTURE_DEVELOPMENTS sections §1 and §22 — **both**, because §22 carries the superseding auto-track ruling and
prompt 02 deliberately cross-links rather than merges them.

## 1. Where this actually stands

Watched pages already become corpus Articles through the one `index_article` hook, per edition, with a
filterable source domain; full text is stored per revision; the tracker refreshes on every change with the
revid anchored.

Downloaded **dumps** are files. `ingest_dump_pages` reads a title list and a `fetch_recentchanges` client
exists, but nothing turns a dump into a corpus, and the superseding ruling — that downloading a language
dataset auto-tracks that entire edition and retires per-page tracking — is unbuilt.

The scale honesty that gates it has not changed: enwiki is roughly 100k edits per day against a two-core
reference VM, tens of millions of articles, and the standing ruling says **do not start before the P0 scale
set lands**. The architecture is dump-as-baseline plus a `recentchanges` delta, never per-article scraping.

## 2. Slices

> **OUTCOME 2026-09-07.** S1 stopped at the seam (the gate is MEASURED below, not cited) · S2 was
> **already built and recorded as UNBUILT** — the view shipped in wave 5; what was missing is the READER,
> now closed · S3 designed, deliberately not half-built · S4 shipped as a per-ARTICLE anchor with the
> deviation recorded · S5 shipped, its single-request mechanism parked with evidence · S6 answered: three
> of G10's five questions were already ruled. A fourth thing was found that no slice asked for: the wiki
> strip carries the recorded K·N `OPEN.*?CLOSE` bomb in three patterns, on the ingest path — 13.4 s per
> 400 KB of unclosed-`<ref>` spam against 0.014 s well-formed, fixed through a shared linear scanner.

### S1 — Whole-edition ingest (storage-gated; the honest answer may be "not yet")

Build the seam and the *bounded* version: a dump becomes a baseline, `recentchanges` becomes the delta, and
the tiered-depth proposal decides how much of an edition a given install carries. Auto-tracking after a dump
download is by design and by default per the ruling — which means it needs **visible consent and a visible
job**, because it is the largest thing the app would ever start on its own.

If the storage plan's Phase C is not in place, say so and stop at the seam. A half-built whole-edition ingest
on an unprepared store is the failure mode this was gated to avoid.

> **STOPPED AT THE SEAM 2026-09-07, and the gate was checked against the tree rather than a status line.**
> `STORAGE_5TB_PLAN.md` §9 sequencing: step 1 (Phase-A deltas) DONE; step 2 (CREATE-time
> `auto_vacuum`/`page_size` seams) DONE — `src/database/connect.py` carries both, so that plan's own
> 2026-07-22 banner calling them "still unwired" is itself stale; step 3 (the FTS split-out to a
> contentless-delete `fts.db`) NOT built; step 4 (the sharding prototype at 50–100M synthetic documents,
> which the plan requires BEFORE any sharding code) NOT run; step 5 (the Phase C packed keyed text store)
> NOT built — a tree-wide grep finds no text-offload store, no pack format and no sharding. Four of the
> six §8 rulings are unruled (blob dedup · OOENC2-vs-`age` · keyed HMAC addressing · the `sqlite3mc`
> trial). **Nothing was built.** Wiring the existing `fetch_recentchanges` client into an ingest would be
> starting whole-edition ingest against a store the plan has not prepared, which this slice's own scope
> fence forbids; and auto-tracking is "the largest thing the app would ever start on its own", so its
> consent surface and visible job should be designed once the store's shape is ruled, not twice.
> **What exists today:** the BOUNDED version already ships — `ingest_dump_pages(session, wiki, titles,
> limit=1000)` over an operator-chosen title list, offline, through the one `index_article` hook
> (`POST /api/wiki/dumps/corpus-ingest`). The DELTA half has a client (`WikiClient.fetch_recentchanges`)
> and **no consumer**. Nothing enumerates a whole edition and nothing auto-tracks after a download.

### S2 — The tracked-changes tab

The maintainer asked for it twice and the ledger records it twice as REMAINING: a dedicated tab in the wiki
article surface for scrolling, discovering and analysing edits through time. Intuitive, interactive, and
carrying the same disclosures the tracker already makes (newest version by default, revid recorded, full text
per revision stored locally with its storage cost stated, stripped-wikitext honesty).

> **CORRECTED 2026-09-07 — the VIEW was already SHIPPED, and the ledger's "REMAINING" is half right.**
> `app-map.js` carries `openWikiTC` / `_wikiRevRow` / `loadWikiTC` ("wave 5"), `index.html` carries
> `#wiki-tc`, and `GET /api/wiki/pages/{id}/revisions` serves it with the window, the per-revision diff,
> the `has_full_text` marker and the visible caveat. `INVENTORY.md` WIKI-02 recorded it UNBUILT with
> evidence "no hits", which is simply wrong and is fixed in the same PR. **What WAS missing is the half
> this slice names: "in the wiki article surface".** The view was reachable only from the Settings
> watched-pages table, and the reader is a standalone page served by `/api/articles/{id}/view` — so a wiki
> article opened from search or analytics showed no version, no history and no way to either. The reader
> now states the version, links the revision as published, and offers the local history ONLY when this
> machine holds tracked revisions for that page (a link into an empty room looks like a capability and
> answers nothing); a `?wikitc=` deep link hydrates the view through the subtab component. The view is
> now DRIVEN by a node suite rather than asserted from source.

### S3 — Wikitext rendering

Today the stored text is a bounded wikitext→plain strip, stated as such. A renderer is what makes the reader's
wiki articles readable rather than merely searchable.

> **DESIGNED 2026-09-07, DELIBERATELY NOT BUILT.** The constraint that decides its shape was verified:
> the raw wikitext is NOT in `Article.content` and must not be put there — `content` is what the keyword
> engine indexes, what FTS holds and what `hash` is computed over, so changing it re-indexes the corpus
> and changes every wiki article's identity. So the renderer must work from where the wikitext already
> lives: `WikiPage.latest_text` for a watched page, and NOWHERE in the database for a dump-ingested one
> (`dumpread.find_page` could read it back, at an index seek plus a bz2 block decompress per page view,
> from a file that may no longer be on disk). The honest shape is therefore **render on read, degrade to
> the stripped text with the reason stated** — not a stored second artifact. Full design (safety
> argument, tag allowlist, the link rules under invariants #6/#7, what is counted as dropped) in the
> session scratchpad and summarised in the PR body. It is a new HTML-emitting surface over untrusted
> markup whose safety argument IS the slice, so it gets its own review and its own browser pass rather
> than the tail of a session that has already changed this subsystem three times. The design is written
> up in [`WIKI_S3_RENDERER_DESIGN.md`](WIKI_S3_RENDERER_DESIGN.md).

### S4 — Per-mention revid anchoring

So an analytic result over a wiki article can say *which version* it was computed against. This is the piece
that makes the audit trail meaningful rather than decorative.

> **SHIPPED 2026-09-07 as a per-ARTICLE anchor, and the deviation is deliberate.** The defect was exactly
> as recorded: `upsert_wiki_corpus_article` has always RECEIVED the revid — from the tracker's latest text
> or from the dump a page was read out of — and had nowhere to put it, so it returned the number to its
> caller and dropped it. But every mention of an article is produced by ONE indexing pass over ONE text,
> so a per-mention column would store a per-article constant once per mention: millions of copies at field
> scale, on the largest table in the store, of a fact with one distinct reading per article. That is the
> recorded "a term whose count equals the article count is a fact about the channel" tell applied to a
> schema. `Article.source_revision` is written in the SAME transaction as `content`/`hash` so the pair
> cannot drift, and the mentions inherit it through their article. A `String`, not an `int`, because a law
> revision and a statistics vintage are not integers and this is the one seam every versioned source will
> write into — FUTURE_DEVELOPMENTS §1's unifying principle as a column rather than a table.

### S5 — One consented "refresh exact sizes"

Replace the per-edition "Estimate size" probe button (a live per-edition HEAD) with a **single** consented
call: the dump date's `dumpstatus.json` lists every edition at once. The bundled dated size table and its
freshness test already ship, so the probe is the only remaining live per-edition fetch.

> **SHIPPED 2026-09-07, with the mechanism half CORRECTED.** The ruled requirement — retire the
> per-edition probe button and replace it with ONE consented refresh — is built. The sentence above about
> `dumpstatus.json` is **an unverified premise, not a fact**: it originates in an assistant-written
> docstring (`src/wiki/dump_sizes.py`, 2026-06-16), was copied into the Open queue and then into this
> prompt, and nobody read the endpoint. Every `dumps.wikimedia.org` path this repository builds is
> per-edition, and the host is egress-blocked here (`curl` → 000, against 200 for pypi.org), so it could
> not be checked. The shipped action is therefore ONE consented, bounded, politeness-spaced read over the
> operator's actual selection; folding it into a single request is parked with that evidence. Building it
> on the premise would have shipped a fabricated endpoint.
>
> Three further defects were found in the button being retired and are fixed in the same slice: it
> egressed with **no `ensureOnline` consent** though every sibling action on that surface has one
> (invariant #14); it read only `dumpSelected()[0]` from a MULTI-select picker, silently defaulting to
> `en` when nothing was selected; and every failure — airplane mode included — printed one
> "size check failed", so a refusal by this machine read as a dump host that would not answer.

### S6 — G10, the five questions

Answer them where they are recorded, and let the answers shape S1's tiering rather than the other way round.

> **ANSWERED WHERE RECORDED 2026-09-07, AND THERE ARE TWO OF THEM, NOT FIVE.** Read against the section
> that filed them, Q2 (analytics mixing — same pools), Q3 (version storage depth — per-revision FULL TEXT)
> and Q4 (change feed — the watched-pages tracker IS the feed) were all answered by the maintainer's own
> 2026-06-12 ruling recorded a few paragraphs below them in FUTURE_DEVELOPMENTS §22, and Q3 SHIPPED the
> same day. Q1 (scope of dump ingestion) and Q5 (backups) remain open and are sharpened in that section's
> new status block and in the Open queue entry. No ruling is invented: the recommended defaults in
> `QUESTIONS_FOR_THE_MAINTAINER.md` are NOT taken.

## 3. Scope fence

Zero-network boot is untouched. No auto-fetch at boot, ever. The per-edition source domain stays filterable
so wiki content never blends silently into trust-sensitive views. Do not start whole-edition ingest against a
store the storage plan has not prepared.
