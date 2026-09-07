# Prompt 10 — Throughput: the C-slice remainder

> **Scope:** the collector, the housekeeping lane, sitemaps, segmented downloads.
> **Gated on:** the C-brief's own evidence gates (C16 in particular). Rulings a/b/c/d/e were adopted as
> revertible spec defaults.
> **Sequencing:** independent, but its C16 slice touches the write path — not concurrent with prompt 09.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md` and its companion
`AUTONOMOUS_SESSION_BRIEF_2026-07-24_C_THROUGHPUT_SCALING.md` (seventeen ordered slices, C1–C17).

## 1. What the field measured, so the levers are ranked honestly

Two diagnostics exports from machines at opposite ends of the fleet, launched together, produced three
stacked causes and they are **not** equally addressable:

- **Supply** dominates. Roughly 90% duplicate rate on both machines; 2,766 of 3,599 enabled sources have an
  `rss_url` and yield about two new articles per day per feed. Ten times the throughput needs more qualified
  and enabled sources plus crawl mode — not more workers. That makes **prompt 04** the real throughput work.
- **Duty cycle** is the top code lever: inter-pass gaps of 3–8 minutes on both machines, and the *faster* box
  was worse (48% fetching, 52% gap), because the gap work is single-core analytics and **serial Tor fetches**
  in the ride-alongs, so it barely scales with CPU.
- **Memory** parks the governor's permits at a median of 2 on a 3.3 GB box. Hardware-dependent; zero mem-low
  samples on the larger machine.

The 2026-07-23 duty-cycle fix (moving `refresh_briefing` off the pass-blocking path) shipped and the
mechanism is confirmed; no percentage is claimed, and the operator's 8-core/20 GB machine is the before/after
bench.

## 2. Slices

### S1 — S-B: overlap the network ride-alongs with the next pass

The remaining half of the duty-cycle cause. Roughly seven serial Tor fetches (calendar, wiki, law, discovery,
qualification) run in the gap. Moving live network I/O across a pass boundary is materially bigger than the
read-mostly briefing move that shipped, which is why it was deferred — it needs the `KindLadder`, which is
built and **unwired**, and wiring it finally implements the 2026-06-13 bandwidth-priority-ladder ruling
(markets/weather first, interactive DDG next, RSS, then recursive crawl only with headroom).

### S2 — S-E: sitemap support

There is **none**: `Source.sitemap_url` is a dormant column and the crawler skips `.xml`. This matters twice
— for new-URL discovery, and because `trial_fetch` is **RSS-only**, so the feedless majority of the candidate
backlog is structurally unqualifiable without it. That second point is what makes this a supply lever rather
than a nicety.

Sitemap-preferred, crawl as the fallback. Under ruling (d), sitemap trial evidence counts toward
qualification.

### S3 — C16 / S-D: extraction out of the write gate (evidence-gated)

`_flush_batched` holds the one gate window **across** per-article `index_article` CPU extraction — the
mechanism behind the fast box's `writer-bound` pass verdicts. The fix shape is stage-then-gate plus the
proven `reindex_parallel` process-pool precompute.

It is evidence-gated **and the evidence now exists** (the writer-bound verdicts at the current offer), but it
is the riskiest hot-path change on the board and the brief mandates the full skeptic matrix with a
negative-space lens. If the session is short, do S1 and S2 and park this whole.

### S4 — Transport parallelism (small slices)

Skip the per-fetch **local** `getaddrinfo` when proxied — it also closes a DNS-metadata exposure, since a
local resolve hands the resolver the list of sources the operator reads. Hardware-aware `w_max`. Wire
`rank_mirrors` and `plan_segments`/`reassemble` for segmented multi-circuit bulk downloads (the cores are
built; the live GET is operator-gated). An opt-in operator-run SOCKS endpoint pool sharded per host, per
ruling (b).

Per-host politeness is never traded for speed: parallel across hosts and circuits, bounded per host.

### S5 — Crawl by default

Ruled ON by default as a **hybrid budgeted rung**, explicitly not a mode flip — flipping `mode` to `crawl`
would abandon conditional-GET feed economics and blow up pass time. Additive `crawl_supplement: bool = True`
plus a `crawl_per_pass` budget mirroring the `world_discovery_per_pass` ride-along, a bounded crawl sub-pass
after RSS over least-recently-crawled and feedless-first sources, a new `Source.last_crawled_at` marker, the
lowest ladder rung so it never starves RSS, through the one fetcher so robots and politeness are unchanged by
construction.

### S6 — The second-tier accelerators worth doing now

An in-memory dedup front (~90% duplicate rate ⇒ skip the codec read; the negative-space property is "never a
false negative"). Bulk mention insert (the per-term ORM path is ~93% SQLAlchemy overhead: 235 µs versus
25 µs raw) — the write gate already covers bulk `session.execute(insert())` via its `do_orm_execute`
listener, which the module's own docstring records, so no new gate wiring. Persist the robots and DNS caches
across restarts. Shrink the per-worker memory footprint (the small-box floor).

### S7 — PERF-09: per-job rate, ETA and bandwidth cap

Deliberately omitted so far, for a good reason worth preserving: the download owners report **bytes and
percent, not a rate**, so an honest rate needs owner-measured bytes-over-time in the manager — never a
client-side guess across an adaptive poll — and the cap needs a backend that supports throttling, which does
not exist. Build the owner-side measurement first; the display follows.

## 3. Scope fence

The non-options are hard fences: robots, per-host politeness and the honest UA are untouchable; no evasion of
blocks or CAPTCHAs; no third-party proxy meshes or scraping APIs; no headless browser fleet; and **no
fabricated multiplier** — every projection is an estimate until the 8-core bench measures it.
