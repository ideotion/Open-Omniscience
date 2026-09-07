# S3 — wikitext rendering: the design, and what it turns on

> **Written 2026-09-07 during the prompt-18 pass, DELIBERATELY NOT BUILT.** Everything below the
> "constraint" heading was verified against the tree, not assumed. Referenced from
> [`PROMPT_18_wikipedia-living-source.md`](PROMPT_18_wikipedia-living-source.md) S3.

## The gap, verified

`Article.content` for a wiki article is `plain_from_wikitext()` output: a bounded lexical strip
that drops templates, refs, tables and files and keeps link LABELS. The reader renders it as one
`<p>` per line. So a Wikipedia article in the reader today has no headings, no lists, no emphasis,
no links and no sections — searchable, not readable, which is exactly the slice's own framing.

## The constraint that decides the shape

**The raw wikitext is not in `Article.content`, and must not be put there.** `content` is what the
keyword engine indexes, what FTS holds and what `hash` is computed over; changing it would
re-index the corpus and change every wiki article's identity. So the renderer cannot work from the
stored article body — it has to read the raw wikitext from where it already lives:

* watched pages → `WikiPage.latest_text` (falling back to `baseline_text`), which the tracker
  already refreshes on every change and which `sync_page_to_corpus` already reads;
* dump-ingested pages → nowhere in the database. `dumpread.find_page` can read it back out of the
  local multistream dump, but that is an index seek plus a bz2 block decompress **per page view**,
  on a file that may no longer be on disk.

So: **render on read, from `WikiPage.latest_text` when we have it, and degrade honestly when we do
not** — the reader keeps showing the stripped text and says why. Reaching for the dump on the
reader path is DEFERRED with that reason, not forgotten.

## Module shape

`src/wiki/render.py`

```
render_wikitext(text, *, wiki, resolve_local=None, max_chars=...) -> RenderedWikitext
    .html        str   -- only tags this function constructs
    .dropped     dict  -- {"templates": n, "tables": n, "refs": n, "files": n, "comments": n}
    .truncated   bool
    .scanned_chars int
```

`dropped` is COUNTED and published rather than silently discarded: the reader states what the
rendering left out, so the page never implies it is the whole article.

## Safety: the property the whole slice rests on

The input is untrusted markup from Wikipedia, and the output goes into an HTML page. So:

* every text run is escaped;
* the function emits ONLY tags it constructs itself, from a fixed set
  (`p h2 h3 h4 ul ol li blockquote b i a br hr code`);
* raw HTML in the wikitext is **escaped, never passed through** — no allowlist of "safe" inline
  HTML, because that is a second parser with a second set of holes;
* `href` goes through `safe_href` (the reader's existing guard) and an external anchor carries
  `class="ext"`, so it inherits the reader page's existing confirm (invariant #7).

Negative-space tests are the load-bearing half: `<script>`, `<img onerror=…>`, `javascript:` and
`data:` hrefs, an event handler smuggled through a link label, an unclosed tag, and a `[[…]]`
target shaped like a path.

## Links

* `[[Target]]` / `[[Target|label]]` → when the corpus holds
  `wiki_article_url(wiki, Target)`, a LOCAL link to `/api/articles/{id}/view` (invariant #6: the
  local reader first). Otherwise the label as plain text, marked "not in your corpus".
  **Deliberately NOT an outbound wikipedia.org link:** a wiki article carries hundreds of them, and
  minting hundreds of new external click targets on a reader page is the "no bare external
  shortcuts" shape invariant #6 forbids. The target is named, so nothing is hidden.
* `[url label]` → `<a class="ext" href=…>` — these are links the source text already carries, and
  the page's confirm covers them.

## Cost

Bound the input and report truncation. The block strips must use the shared linear scanner (see
the K·N finding), never `OPEN.*?CLOSE`, because this now runs on a read path as well as at ingest.

## Why it is not in this PR

Written down rather than half-built. It is a new HTML-emitting surface over untrusted input, and
its safety argument is the whole slice — it deserves its own review and its own browser pass, not
the tail of a session that has already shipped three changes to the same subsystem.
