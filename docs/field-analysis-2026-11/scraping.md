# Goal 3: the scraping engine

## 3.1 Extraction method

**Not measurable.** There is one extractor, trafilatura (`src/ingest/extract.py:190-223`), with its internal
fallbacks enabled (`no_fallback=False`). Which path produced an article is not recorded (`ExtractedDoc` has no
method field, `src/ingest/extract.py:31-40`). There is no feed-summary fallback. "Success by extraction method"
cannot be answered. OPEN-QUESTIONS.md Q2 proposes the diagnostic.

Extraction success **by site type**, measured indirectly from the hand-labelled sample (quality.md §1.1):
- **Non-article pages** come from discovered institution, religious, stock-exchange and journal sources.
- **Clean articles** come mostly from news, broadcaster and wire sources.
- One catalogue news source in the disqualified set stored the raw HTML of its page as text (a Korean site; cause not
  determined). That one case is not enough to give a rate.

## 3.2 Fetch errors by class (article pages reached through a working feed)

`ff:*` classes are shares of `fetch_failed` summed over the kept passes (`scripts/ingest_runs.py`). The
classifier is `src/ingest/fetch_verdict.py:397-442`: TLS errors and timeouts both land in `connect`, and too many
redirects in `bad_url`.

| instance | fetch_failed | http_403 | dns | http_4xx | bad_url | http_429 | http_5xx | connect | not_html | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Windows | 2,930 | 70% | 2% | 7% | 7% | 4% | 4% | 1% | 2% | 3% |
| Linux A | 758 | 48% | 38% | 10% | 0% | 0% | 0% | 2% | 0% | 3% |
| Linux B | 1,086 | 59% | 17% | 8% | 12% | 0% | 0% | 3% | 0% | 1% |
| Linux C | 6,250 | 68% | 18% | 4% | 3% | 2% | 0% | 2% | 3% | 1% |
| H3–H8 | 901–4,412 | 36–69% | 18–48% | 4–7% | 2–8% | 0–1% | 0–1% | 2–7% | 0–3% | 1–2% |

- **All instances: HTTP 403 is the largest class (36–70%).** The fetcher sends an honest bot user agent and never
  evades blocks (CLAUDE.md non-negotiables), so a 403 is a publisher's refusal. These failures are spread over many
  hosts. The data has no per-host split.
- **Linux: DNS is the second class (17–48%). It is 2% on Windows.** The Linux VMs resolve through their own
  network setup, so this is likely **local** (resolver or VM networking), not the sources.
  Not verified per host: the data has no per-host failure log.
- **Windows-only:** more `bad_url` (redirect loops), 429 and 5xx. That fits Windows' larger request volume
  (79,638 items over 60 passes against 10–12k on Linux A and B). It is likely load and rate limiting from
  publishers, not an OS effect.
- **Not measurable:** feed-level errors (§2 of ingest.md), TLS separately from timeouts, redirects followed, and
  retries.

## 3.3 Robots

- **In collection (measured):** `blocked_robots` 0.2–0.6% and `robots_unavailable` 0.2–2.1% of items. Linux A is
  highest at 2.1%, which is local.
- **In discovery (measured, older kit):** the 2026-09-11 Stage A verification of 37,079 Wikidata-discovered
  institution candidates (`scripts/stage_a.py`). robots.txt failures were the largest single loss:

| outcome | first pass (37,079) | retry pass (23,237 of the failures) |
|---|---:|---:|
| verified feed | 2,373 (6.4%) | 267 (1.1%) |
| robots.txt could not be read (unavailable / unreachable) | 15,875 (42.8%) | 10,145 (43.7%) |
| robots.txt refused (401/403) | (in "unavailable") | 1,956 (8.4%) |
| robots server error | | 361 (1.6%) |
| homepage unreachable | 7,357 (19.8%) | 9,734 (41.9%) |
| no feed found | 7,381 (19.9%) | 474 (2.0%) |
| feed unparseable | 3,139 (8.5%) | 200 (0.9%) |
| feed stale (> 120 d) / too few entries / undated | 692 (1.9%) | 64 (0.3%) |
| robots.txt disallows | 255 (0.7%) | 32 (0.1%) |

Robots is fail-closed by ruling (CLAUDE.md non-negotiables), so this is the price of that rule, and it is correct
behaviour. The retry recovered only 1.1%, so most of these hosts are unreachable or refuse every request. This
kit predates the current fetcher. **Could not determine** whether main's numbers differ, because main's
`robots_cache.json` is not exported.

## 3.4 Feed versus page discovery

- Regular passes read **feeds only**. A source without `rss_url` returns at once (`src/scheduler/runner.py:857-858`).
- Feed-less sources are reached only by the housekeeping crawl supplement (`_lane_step_crawl`,
  `src/scheduler/runner.py:1620`). It rotates feed-less sources first (`:545-547`), one source per outlet per pass.
- **Measured:** of the 830 feed-less catalogue rows on each Linux instance, **122 / 152 / 110 (13–18%) ever stored
  an article.** Across all 13 snapshots, 649 feed-less catalogue keys never stored one.
- **Could not determine** how far the crawl rotation has reached, because `last_crawled_at` is exported only for
  sources that have an article.

## 3.5 Politeness and back-off

All verified in code:
- Minimum 1 s between requests per host, raised to the robots crawl-delay. One request at a time per host. A wait
  over 180 s defers the item (`src/ingest/__init__.py:605-628`, `:1214-1245`, `:2530-2636`).
- `Source.rate_limit_ms` (catalogue default 2000 ms) is **not read by the fetcher**. It is used only in a plan
  estimate (`src/scheduler/runner.py:761`). The catalogue's per-source rate limits are therefore inert. This is
  stated, not a defect: the effective spacing is the host's crawl-delay or 1 s.
- Robots back-off: 1 h·2^(n−1), capped at 24 h (`src/ingest/__init__.py:197`, `:216-236`).
- Feed back-off does not apply to failing feeds (ingest.md §2.3).

The data has no per-host spacing log, so the politeness actually applied is **not measured**.
