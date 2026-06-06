# Wikipedia change-tracking

## Intent

Wikipedia is contested ground: articles are continuously edited, and in the LLM
era removing or rewriting history is easier than ever. This tool treats each
Wikipedia **language edition** as a tracked source whose *edits* are the data, so
a journalist can **detect and document** large-scale or revisionist changes —
e.g. prove that a sentence existed on a given date and was removed by a given
account.

> Editions are per-**language** (`en`, `fr`, `ar`, `ru`, `zh`, …), not
> per-country (there is no national Wikipedia); the UI maps languages to countries.

## Why this is not "regular article" ingestion

Articles change over time, so they cannot be stored as one-shot `Article` rows.
Two design choices follow:

1. **Use the MediaWiki Action API, not page scraping** — `revisions`,
   `recentchanges` (with byte deltas), and `compare` (server-computed diffs). This
   is the efficient, ToS-friendly, change-oriented path.
2. **Store deltas, not re-copies** — keep **one** compressed full-text baseline
   per page (`wiki_pages.baseline_text`); every edit after is a `wiki_revisions`
   row holding the **diff + signed byte delta + flags**, never the whole new
   article. Any historical version is reconstructable by replaying diffs.

**This answers the redundancy/disk question:** a cosmetic edit is a tiny diff
carrying MediaWiki's `minor` flag and is filtered by a size/minor threshold, so it
costs almost nothing. Storage scales with **edit activity on watched pages**, not
with the multi-GB article corpus — you never need the full dump for tracking.

## Detecting large-scale / suspicious edits (honest)

`src/wiki/flagging.py` flags an edit and records **reason codes** — it surfaces
*candidates*, it does not pronounce "disinformation":

- `large_removal` / `large_addition` — byte delta beyond a threshold
- `revert` / `blank` — MediaWiki change tags (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — a medium+ edit from an anonymous IP
- `burst` — many edits to one page in a short window
- `ores_damaging` — optional **Wikimedia ORES** "damaging" probability, presented
  as a *labelled-by-ORES* assertion (like our entity provenance)

Minor cosmetic edits are never flagged. Each flagged edit is documented with its
diff + provenance (revid, editor, timestamp), which plugs into the existing
**chain-of-custody** for signed/timestamped evidence.

## Two clearly-separated subsystems (UX)

1. **Watch & track** (lightweight, instant, the default): a watchlist of pages /
   categories per language edition; poll revisions on the in-app scheduler; store
   revisions + diffs + flags; a diff viewer + per-page timeline. No bulk download.
2. **Offline baseline** (heavy, optional): a **per-language menu** — each edition
   shows an estimated **size + time** before you commit, with download / pause /
   resume / delete, kept entirely separate from article scraping. (Size reality:
   current-text enwiki ≈ 22 GB compressed; full history is terabytes — only needed
   for offline historical diffs.)

## Status

- **Done (Phase 1):** schema (`wiki_pages`, `wiki_revisions`; migration
  `d4e5f6a7b8c9`), the MediaWiki API parser (`src/wiki/mediawiki.py`), and the
  edit-flagging logic (`src/wiki/flagging.py`) — pure, unit-tested with fixtures.
- **Next:** live polling client + scheduler `wiki` mode + ORES client; the
  Wikipedia tab (watchlist, flagged-edit feed, diff viewer, evidence export;
  diffs feed the Insights analytics); then the offline baseline downloader.

## Ethics

All fetching honours the MediaWiki API usage policy (identifying User-Agent,
`maxlag`, rate limits) — more considerate than scraping. We store only public
revision data; nothing is fetched until tracking runs.
