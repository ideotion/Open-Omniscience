# Content-analysis strategy — links, uniformity, and the original source

> Concrete, staged strategies for the vision in [`FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md):
> use article **links** to assemble what's talking about the same thing, surface
> media **uniformity**, and trace information back to its **original source** — while
> keeping the **user in power**, the analysis **transparent and local**, and never
> letting the tool become an arbiter of truth (Munich Charter). Open-source and
> offline throughout.

---

## 0. Where we are (honest status)

Article-link detection is **scaffolded but not wired**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extracts links
  from HTML, normalises URLs, tracks anchor text + position, classifies link *type*
  (internal/external/image/…), and produces link statistics. ~500 lines, unit-shaped.
- ✅ **DB schema** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource`, and `LinkClassificationRule`. Relationships are in place
  (`Article.links`, `ExternalSource.links`).
- ✅ **Invoked on ingest** *(done — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  populates `article_links` with outbound **external** links (best-effort, fail-open;
  internal/image/ad/social/tracker excluded per `KNOWN_GAPS.md`; de-duped + capped).
- ✅ **API** *(done — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (by url|domain, windowed), `articles-by-link` (by url|domain). Counts
  only; nothing scored or judged.
- ❌ **No UI yet** — no Insights view over the link graph (P2, below).

So P0/P1 are wired; the remaining work is the UI and the deeper analyses (P3/P4).

---

## 1. The core idea: links are a citation graph

Treat each article as a node and each outbound link as a directed edge to a URL (and
to its domain). That graph answers exactly what you asked:

- **"Assemble all articles talking about the same link."** = group articles by the
  external URL they cite → the URL's **in-degree** is "how many of my articles point
  here." High in-degree = a **hub**: often a primary document, a wire story, or a
  much-discussed reference.
- **"Discover trends through internal links."** = watch in-degree over time; a URL or
  domain whose citations spike is a *trend* grounded in what reporters actually cite,
  not just keyword frequency.
- **"Trace the original / primal source."** = within a cluster of articles about one
  story, the original is the node others **link to**, and/or the earliest, and/or the
  one citing a **primary document** (court/gov/dataset). Links + timestamps + wire
  attribution triangulate it.

This is *co-citation analysis* — cheap, transparent, and explainable. No black box.

---

## 2. Staged strategies (each shippable on its own)

### P0 — Wire the extractor into ingest (make the graph exist)
- Call `LinkExtractor` during ingestion on the fetched HTML; persist outbound
  **external** links to `article_links` (skip internal nav, ads, and — per
  `KNOWN_GAPS.md` — image/binary links). Store normalized_url + anchor text + type.
- Map each external link's domain to a known `Source`/`ExternalSource` where
  possible (so "who cites whom" can roll up to outlets and **owners**).
- Cheap, deterministic, offline. Nothing fetched beyond what ingest already fetched.

### P1 — Aggregation + API (answer the user's question)
Read-only endpoints over the graph:
- **`top-cited`** — most-cited URLs/domains in a window (the trend signal).
- **`articles-by-link`** — given a URL/domain, every article in the corpus citing it
  ("assemble all articles talking about the same link").
- **`link-graph`** — nodes/edges for a topic or window, for visualisation.
- **`co-citation`** — articles that cite the *same* external sources (candidate
  "same story" clusters), with overlap counts.

### P2 — UI: a "Links & sources" view in Insights
- A ranked list of **most-cited links/domains** (click → all citing articles).
- A small, zoomable **citation graph** (reuse the SVG approach already used for the
  Insights map — no new dependency).
- Always shows **sample sizes** ("cited by 14 of your articles") — measured, not
  guessed. The user clicks, explores, decides.

### P3 — Original-source lineage
For a cluster of articles about one story, present a **lineage**, ranked by signals
(each shown, none decisive):
- in-degree (who is linked to by the others),
- earliest publication timestamp,
- wire attribution (AFP/Reuters/AP — we already tag `wire-agency`),
- presence of a **primary document** link (gov/court/dataset/preprint).
Output: "primary doc → first report → echoes," as a chain the user reads.

### P4 — Uniformity & echo (ties to media concentration)
- **Near-duplicate detection** (cheap MinHash/SimHash) to flag syndicated/copied text
  across outlets — builds on `src/ingestor/duplicate_detector.py`.
- **Echo score**: a cluster where many outlets cite **one** source (or each other in a
  tight loop) and add little original linking = high echo. Diverse primary-source
  citations = independent reporting.
- **Concentration overlay**: weight echo by **ownership** — if the echoing cluster maps
  to one owner/bloc (the "~7 billionaires own ~90%" case), surface that. Needs the
  ownership graph (Wikidata P127/P749 + manual), per `FUTURE_DEVELOPMENTS.md`.

---

## 3. Keeping the user in power (non-negotiable)

- **Surface, never suppress.** Echo/lineage scores are *shown and sortable*; the tool
  never hides or auto-demotes a source. Any down-weighting is an explicit, reversible
  user control, **off by default**.
- **No truth labels.** "Earliest we saw" / "most cited" ≠ "true." We show structure
  (who said it first, who cites whom, who owns whom) and stop.
- **Everything explainable & local.** Every number traces to rows the user can inspect;
  no external calls, no ML black box (hashing + counting + graph degree).
- **Open-source & auditable.** Pure functions, unit-testable, classification rules in
  data (`LinkClassificationRule`) the user can edit.

---

## 4. Risks & honest limits

- Link extraction is only as good as the fetched HTML (paywalls/JS limit it).
- Anchor/citation conventions vary; "according to X" without a link is missed (a
  later NLP pass could help, but starts simple).
- Ownership data is patchy and dated — must be attributable, not guessed.
- Near-dup at corpus scale needs care to stay cheap on one machine (hashing, windowed
  comparison), not O(n²) full-text compares.

## 5. Suggested first commit

Wire **P0** (populate `article_links` on ingest) behind a setting, add the **P1
`articles-by-link`** and **`top-cited`** endpoints, and a minimal Insights list. That
alone delivers "assemble all articles citing the same link" and a citation-based
trend — the smallest slice of real value, fully in keeping with the ethos.
