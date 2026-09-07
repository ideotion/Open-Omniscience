# Prompt 17 — Super-groups, the concept map, and the analysis surfaces

> **EXECUTED 2026-09-07 — read this before building anything below.** The staleness guard
> (`_WORKING_MODE.md` §2) found **S1–S7 already shipped**, almost all of it in PR #721 on
> 2026-07-19; the Open-queue entry this prompt was written from still said *"execution delegated,
> PENDING"*, which is what made the whole prompt read as unbuilt. Nothing here was rebuilt.
> Per-slice evidence, with the tree anchor that proves it, is in the CLOSING NOTE appended to the
> **SUPER-GROUPS** entry in [`docs/ledger/OPEN_QUEUE.md`](../../ledger/OPEN_QUEUE.md).
>
> Two items in §S7 were not gaps at all and are now corrected in `INVENTORY.md`: **KW-17** is
> shipped (`/api/insights/keyword-stats` + the reader/SPA hovers), and **AI-19** was *deliberately
> removed* by maintainer ruling 22 as an absorption into the reader — building it would undo a
> ruling. The Trends third window and its per-window top-5 charts shipped 2026-06-16; only the
> wider Trends redesign (retiring the Insights search bar, B11a) is still open, and it stays
> browser-gated.
>
> **The one genuine defect the sweep found has been fixed in this PR:** `ring_country_split` capped
> its country list at 40 while the shipped catalog carries 189 distinct source countries, so §D's
> clickable *"not mapped"* bucket could be truncated out of the payload and the count announced
> beside the map was the cap. Reproduced live, fixed, mutation-checked.
>
> **Scope:** `src/analytics/supergroups.py` and the group layer, the analysis window, the concept map.
> **Gated on:** nothing blocking; the naming and circle-grammar rulings are already given.
> **Sequencing:** its S1 is a prerequisite for prompt 16 (the Observatory consumes it) — S1 is
> shipped (`src/analytics/supergroup_stats.py`), so prompt 16 is **unblocked**.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md entries **"SUPER-GROUPS: HONEST STATS, A LEADS FAMILY, AND
NAVIGATION"** and its same-day **"GROUPS LAYER AMENDMENT"**, then
`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md`.

Two rulings are already given and shape everything here. **Naming:** keyword → **GROUP** → **SUPER-GROUP**,
user-facing and ×12; "ring" leaves the UI entirely and stays internal (the Lead-rename precedent). Today's
"Groups" subtab shows super-groups, which is the collision to fix. Families stay invisible variant-collapsing
and never become a fourth tier. **The circle grammar:** a plain chip is a keyword, one circle is a group, two
circles a super-group — the count encodes the level — with colour reinforcing only, through two
theme-**derived** variables (never hardcoded hues: a hardcoded caveat colour failed 8 of 17 themes), and a
clickable breadcrumb wherever any level appears.

## 1. Slices

### S1 — Honest super-group statistics

There are none today, and the export exposed why the naive version would lie:

- **Generic contamination.** "data" is 36,507 of the AI group's 43,067 mentions — 85%. `universe` at 16,393
  is a probable homograph member inflating in one language. So every statistic carries a mandatory
  top-member **dominance** disclosure plus the shared DF-ubiquity gate.
- **Within-group double counting.** The AI group mixes legacy plain families with rings covering the same
  concepts (plain "ai" at 12 beside the `ai` ring at 1,555). Member keyword ids must be **deduped** before any
  sum, and the residue migrated as a data fix with user-edit-wins honoured.
- **Cross-group overlap** is legitimate (`data` in two groups; `logic` in Mathematics and Philosophy) and
  must be **disclosed**, not resolved.

Build the resolution primitive once and reuse it one level down for GROUP-level statistics, where the
disclosure adapts to top-**language** dominance ("ru carries 61% of this group").

### S2 — A `supergroup_rising` producer, born scale-aware

Across ~77 groups: FDR correction, count floors, share-normalised, one-member-driven rises **disclosed**, and
a generic-driven rise is **not** a Lead at all. The rising-card family stays super-group-only — 540 groups is
not a reviewable card population.

### S3 — Navigation: keyword → super-group

The reverse lookup, with chips in the analysis Keywords subtab and in search. Plural membership means several
chips, not a chosen one.

### S4 — The concept map upgrade

This is the surface the maintainer singled out as working. `ring_country_split` and `/ring-countries` are
built. Four changes:

- The 540-item dropdown becomes a two-tier circled browse (super-group chips → group chips) with type-ahead.
- **Countries become clickable:** member keyword ids intersected with source country give an exact article set
  → `openAnalysisForIds`. The "not mapped" bucket is clickable too — it was the largest bucket in the export.
- Every circled chip app-wide deep-links to the map.
- The located-share honesty line states that map coverage grows as source countries are filled, which points
  at the standing Wikidata source-country generator lever rather than reading as a defect.

### S5 — Scaffold cleanup (hand-verified, never swept)

`deficiency` in the Money group (a `deficit` conflation?), `copyrighted` → `copyright`, the `diaspora*`
asterisk, zero-mention clutter. Per-case fixes plus a config lint — a sweep here would delete real concepts.

### S6 — Curation lives in Settings, once

Entity-family and super-group curation both belong in the **same** Settings home, beside the Keywords
explorer (invariant #8: the UI shows data, acquisition and configuration live in Settings). Show only rows
with a real decision — post-acronym-ruling, entity families are single-member by construction, so a "you
decide" list that offers nothing to decide is worse than no list.

### S7 — The analysis-window residue

- **KW-17:** the clickable-keyword stats hover (slice 2 of that design) — mention n, article spread, trend
  rate, ring translation, top co-occurrences. Counts only, no score, method and caveat visible. Which stats
  is a soft ruling; the perf constraint is not: read through the `article_id`-indexed mention tables, never
  the keyword→articles join that drags whole article rows through the SQLCipher codec.
- **AI-19:** per-article Summarize and Translate on the analysis Articles list.
- The Trends redesign's third window and the per-window top-5 charts, where they are not already shipped —
  check before building.

## 2. Scope fence

No composite score. No fabricated merge — a keyword joins a ring only when its effective language matches.
Do not touch the user's own `KeywordFamilyOverride` splits. Keep per-language counts visible on every merged
row.
