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

### S1 — Whole-edition ingest (storage-gated; the honest answer may be "not yet")

Build the seam and the *bounded* version: a dump becomes a baseline, `recentchanges` becomes the delta, and
the tiered-depth proposal decides how much of an edition a given install carries. Auto-tracking after a dump
download is by design and by default per the ruling — which means it needs **visible consent and a visible
job**, because it is the largest thing the app would ever start on its own.

If the storage plan's Phase C is not in place, say so and stop at the seam. A half-built whole-edition ingest
on an unprepared store is the failure mode this was gated to avoid.

### S2 — The tracked-changes tab

The maintainer asked for it twice and the ledger records it twice as REMAINING: a dedicated tab in the wiki
article surface for scrolling, discovering and analysing edits through time. Intuitive, interactive, and
carrying the same disclosures the tracker already makes (newest version by default, revid recorded, full text
per revision stored locally with its storage cost stated, stripped-wikitext honesty).

### S3 — Wikitext rendering

Today the stored text is a bounded wikitext→plain strip, stated as such. A renderer is what makes the reader's
wiki articles readable rather than merely searchable.

### S4 — Per-mention revid anchoring

So an analytic result over a wiki article can say *which version* it was computed against. This is the piece
that makes the audit trail meaningful rather than decorative.

### S5 — One consented "refresh exact sizes"

Replace the per-edition "Estimate size" probe button (a live per-edition HEAD) with a **single** consented
call: the dump date's `dumpstatus.json` lists every edition at once. The bundled dated size table and its
freshness test already ship, so the probe is the only remaining live per-edition fetch.

### S6 — G10, the five questions

Answer them where they are recorded, and let the answers shape S1's tiering rather than the other way round.

## 3. Scope fence

Zero-network boot is untouched. No auto-fetch at boot, ever. The per-edition source domain stays filterable
so wiki content never blends silently into trust-sensitive views. Do not start whole-edition ingest against a
store the storage plan has not prepared.
