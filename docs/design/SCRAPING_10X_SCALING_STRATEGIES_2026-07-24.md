# Scraping & download throughput — five tactical strategies toward ≥10× (plan of record, 2026-07-24)

**Status: PLANNING-ONLY.** No engine code changes ride this document. It is the design-of-record for
the maintainer's 2026-07-24 ask: *"elaborate several scaling strategies to increase article/scraping
download speeds at least 10 times … while keeping the project's ethics and open-source aspects."*

**Method.** Every claim about the engine below was re-derived from the live tree this session
(`main` @ `df8a9b0`) via a four-agent code-verified recon (fetch/transport · scheduler/pass
lifecycle · ingest/write path · download managers + shipped cores), with the load-bearing findings
hand-re-verified by direct file reads (the 06-audit false-positive discipline). Measured field
numbers come from the two 2026-07-23 all-diagnostics exports (2-core/3.2 GB AMD 3020e and
4-vCPU/9.7 GB i7-13620H, both over Tor) already analyzed in the ledger. **Projected multipliers in
this document are labelled estimates to be validated on the maintainer's designated 8-core/20 GB
before/after bench machine — never claimed as measured.**

Composes with (never duplicates): the 2026-07-23 field-feedback workflow brief (S4 series),
`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md`, the SCRAPING_AUTOMATION_PLAN
step ladder, and the standing bandwidth-priority-ladder / no-source-cap / continuous-collection
rulings.

---

## §1 The engine as built (code-verified, 2026-07-24)

One fetch path, one write gate, one pass loop:

| Layer | Mechanics (anchors) |
|---|---|
| **Fetch** | `EthicalFetcher.fetch()` (`src/ingest/__init__.py:366`): kill-switch check per call (`:390`), SSRF guard, robots.txt per host cached 3600 s fail-closed (`:110,:741,:766`), **per-host lock = at most ONE in-flight request per host** (`:411`, `_host_lock :258`), **≥1.0 s min interval per host, raised to robots `Crawl-delay`** (`:783-798`), honest bot UA, manual bounded redirects, retries only on transient statuses. |
| **Tor** | Per-HOST circuit isolation via `IsolateSOCKSAuth` username stamping (`src/safety/fetcher.py:52-69`, `_isolated_proxies` `src/ingest/__init__.py:587`) — same host reuses one circuit, different hosts get different circuits. One shared `requests.Session`, keep-alive pool 64 (`:218-221`). |
| **Concurrency** | `ThreadPoolExecutor(max_workers=w_max)` over the whole due-source list (`src/scheduler/runner.py:804-807`); `collect_parallelism` default/max **50** (`settings.py:26,65`); `BandwidthGovernor` permits ∈ [1, w_max] (`bandwidth.py:49-90`), default mode now `"maximum"` (seed = ceiling, ramp +2/tick); mem-low backs off −2/tick floored at 1; writer/CPU saturation −1/tick. |
| **Pass loop** | `_default_run_once` (`runner.py:1213-1455`): qualification-gated source selection → stratified interleave → parallel fetch stage → then a **serial post-pass tail** of ride-alongs, ~7 of which do network fetches one at a time on the pass thread (calendar auto-import, market CSVs, law auto-track, world-discovery, qualification trials, hazards, first-run preflights). Only the briefing refresh is async so far (S4.1, `runner.py:1166-1211`). Continuous mode still sleeps 5 s between passes (`:38,:1006`) + pass hygiene (WAL checkpoint). |
| **Write path** | Collector write-batching **is live** (`ArticleBatch`, `OO_COLLECT_COMMIT_BATCH` default 8, `batch.py:59-64`, wired via `ingest_source`/`crawl_source`). The single-writer gate opens at the batch flush and **stays held across each article's `index_article` CPU extraction** (keywords + sentiment + when/where/who) until the batch commit (`batch.py:239-249` — the comment says so explicitly). FTS writes ride the article-INSERT trigger inside the same window (`fts.py:225-229`). `reindex_parallel.precompute_batch` (ProcessPoolExecutor, cross-core, DB-free extraction) exists but is **re-index-only** (`reindex_parallel.py:167-211`). |
| **Bulk downloads** | Wiki dumps: concurrency 3 (profile-ranged 1–6), HTTP-Range resume, per-URL circuit isolation (`wiki/dumps.py:288-298,:414-419`). OSM: same, concurrency 2. The shipped `tor_throughput.py` cores (`KindLadder` stride scheduler, `plan_segments`/`reassemble` integrity-mandatory segmented downloads, `rank_mirrors`) are **unwired** — only the selftest registry references them. |
| **Supply funnel** | Source selection admits only `status == qualified` (`runner.py:325-348`). Qualification trials are **RSS-only, ≤5 article fetches per candidate** (`qualification.py:74,:153-165` — a candidate with no `rss_url` yields zero evidence). Ride-along budget 5/pass; the bulk job (batch 20) shipped 2026-07-23. **No sitemap support exists anywhere**: `Source.sitemap_url` is a dormant display-only column (`models.py:344`), the crawler even skips `.xml` links (`crawl.py:64`), and `non_article.py:55` lists "sitemap" as a skip slug. Crawl mode exists (BFS, depth ≤6, pages ≤500, same-host, robots-gated) but the scheduler mode defaults `"rss"`. |

**New analytical findings from this session's recon** (worth recording regardless of which strategy
builds first):

1. **Staleness catch — collector write-batching already shipped.** The ledger's "S4.2 outstanding"
   framing is partially stale: batched commits are live (default 8). The *remaining* write-path
   lever is different and sharper — CPU extraction runs **inside** the held gate window
   (`batch.py:246-248`), so under load every other worker's flush waits on one worker's pure-Python
   extraction. This is the precise mechanism behind the fast box's `writer-bound` verdicts.
2. **Per-fetch local DNS resolution even when proxied.** `_guard_target` calls
   `socket.getaddrinfo(host)` on every real fetch and every redirect hop
   (`src/ingest/__init__.py:579,:662`) regardless of the SOCKS proxy. Over Tor this is both a
   per-fetch latency overhead and a DNS-metadata exposure to the local resolver (the fetch itself
   egresses via the proxy; the guard lookup does not). Throughput fix and honesty fix coincide
   (see S-C).
3. **The qualification funnel is structurally RSS-bound.** `trial_fetch` returns `{}` for a
   feedless candidate — and the Wikidata-generated world catalog's ~42–67 k candidates carry no
   `rss_url` (grep-confirmed in the 2026-07-23 S1 session). Without a second evidence channel,
   most of the backlog can *never* qualify. S-E's sitemap support is that channel.
4. **The bandwidth priority ladder (ruled 2026-06-13) has a shipped, unwired implementation.**
   `KindLadder` is exactly the starvation-free weighted-fair scheduler that ruling asked for;
   nothing calls it.

---

## §2 The measured bottleneck stack and the 10× arithmetic

From the two 2026-07-23 field exports (both instances over Tor, both then still in `target` mode):

| Fact | Slow box (2c/3.2 GB) | Fast box (4c/9.7 GB) |
|---|---|---|
| Stored articles/hour | ~193 | ~331 |
| Duty cycle (fetching vs inter-pass gap) | 65 % / 35 % | 48 % / 52 % |
| Inter-pass gap | 3–8 min every cycle | 3–8 min every cycle |
| Duplicate rate (feed entries already held) | ~92 % | ~90 % |
| Governor permits | median 2 (mem-low floor) | median 11 / max 27 |
| Burst download rate during pass | avg 1402 KiB/s | healthy |
| Bottleneck verdicts | memory-bound | writer-bound at high permits |

The decomposition that governs everything:

```
stored/day ≈ OFFER (new articles the qualified set publishes or holds)
           × DRAIN CAPACITY (what transport + write path can ingest)
           × DUTY CYCLE (share of wall-clock actually collecting)
```

Today the binding constraint is **OFFER**: ~2,766 feed-carrying qualified sources yielding a ~90 %+
duplicate rate means the engine already drains nearly everything its sources publish. Fetching
*faster* without widening supply asymptotes at ~1.5–2× (duty cycle + burst efficiency). A reliable
10× therefore requires supply-side scaling (S-A, S-E) **and** removal of the three measured
ceilings that would otherwise cap the drain at the new volume: duty cycle (S-B), transport (S-C),
write path (S-D). The five strategies are one multiplication, not five alternatives.

Per-host ethics make this arithmetic clean: because politeness is enforced *per host* (one
in-flight + ≥1 s + Crawl-delay), scaling by **breadth** (more hosts) multiplies throughput while
leaving the load on any individual publisher **unchanged by construction**.

---

## §3 The five tactical strategies

### S-A — "Widen the funnel": supply-side scaling through the qualification membrane

**Thesis.** The offer is the dominant term. Grow the *qualified* source base from ~3.6 k enabled
(~2.8 k with feeds) toward 25–35 k, using machinery that already exists, without ever weakening
review-before-collect: qualification (extraction-validity only) stays the membrane every entrant
passes through.

**Current state.** 42.6–66.7 k discovered candidates sit disabled (world-discovery added_total
66,697 on the fast box; 245/249 countries walked). The bulk qualification job shipped 2026-07-23
(batch 20; honest-stop; livelock-fixed selection). `build_world_news_catalog.py` has never been run
to produce a committed `world_news_sources.yml`. Newsletter links produce no `ArticleLink` rows yet
(ruled + briefed in the 2026-07-24 Session A brief). Citation promotion (`promote_cited_sources`,
≥2 distinct citers, noise-filtered) exists.

**Build slices.**
1. **Digest the backlog**: run the bulk qualification job to completion as a standing background
   task; make `qualification_per_pass` and the bulk batch size hardware-aware (profile-ranged, the
   dump-concurrency precedent) so capable boxes digest at 50–100/pass instead of 5.
2. **Second evidence channel for feedless candidates** (depends on S-E slice 1): a sitemap- or
   homepage-crawl-based trial (≤5 pages, same politeness) so the Wikidata-discovered majority can
   produce evidence at all. Without this, the backlog is mostly unqualifiable by construction
   (finding 3 above).
3. **Operator networked runs** (the established parallel-session pattern): generate + commit the
   world news catalog; further regional acquisition batches (the law-batches precedent) for
   under-represented languages — supply growth that also serves the de-US-centring mandate.
4. **Newsletter links → `ArticleLink`** (already ruled; Session A brief): fully-recovered
   destinations only, never tracker-wrapped stubs — feeds both discovery funnels for free.
5. **Trial-cost budgeting**: ~40 k candidates × ≤5 fetches ≈ 200 k politeness-paced fetches — weeks
   of background work at today's cadence; schedule it under the ladder (S-B) so it never competes
   with live collection, and surface progress in the Library qualification graph (shipped).

**Expected gain (estimate).** Offer ×5–10 as the qualified set grows — the only lever that can
carry 10× on its own. Measured by: Library graphs (qualified-source count · articles/hour), the
per-pass `entries/duplicate/stored` tally trending away from 90 % duplicates.

**Ethics/open-source.** The membrane judges extraction validity, never editorial merit
(cover-everything: ordering ≠ exclusion). Candidates stay disabled until qualified; disqualified
domains are never re-proposed (only the time-ladder re-checks them). Per-host load is unchanged;
total network activity grows only inside the consented online envelope. All catalog data stays
committed, reviewable YAML in the repo.

**Risks / kill-criteria.** Wikidata-spec breadth admits non-news institutions — the membrane +
`source_type` provenance handle this; watch the calibration diagnostic. If qualified-but-low-yield
sources bloat pass time, the feed-backoff ladder already rotates them out (cap guarantees
re-check, never exclusion).

---

### S-B — "Never idle": continuous pipelined collection

**Thesis.** 35–52 % of wall-clock is inter-pass gap on both field machines, and the gap barely
shrinks with hardware (Amdahl at the pass boundary). Overlap the serial tail with fetching and the
duty cycle alone is a measured ~1.5–2×, hardware-independent.

**Current state.** S4.1 made only the briefing refresh async. The remaining tail — calendar
auto-import, market CSVs, law auto-track, world-discovery, qualification trials, hazards, stats —
runs serially on the pass thread, each a sequential Tor fetch (~5–15 s each). Continuous mode still
sleeps 5 s/pass; hygiene (WAL checkpoint) runs between passes.

**Build slices.**
1. **The housekeeping lane**: move the network ride-alongs onto one dedicated background lane
   thread with its own fetcher/session (the S4.1 pattern generalized: non-overlapping via a lane
   lock, own `session_scope`, task-manager-visible, airplane-pausable). The pass tail becomes: kick
   the lane, return.
2. **Wire `KindLadder` as the lane scheduler** — the shipped stride scheduler allocates the lane's
   fetch slots across kinds (calendar/law/markets/discovery/qualification/hazards) by the ruled
   bandwidth priority ladder, starvation-free, under one governor budget shared with collection
   (collection keeps priority; the lane consumes headroom). This finally implements the 2026-06-13
   priority-ladder ruling with the 2026-07-13 §5 core.
3. **Pass overlap**: begin pass N+1's due-selection + fetch dispatch immediately after pass N's
   fetch stage drains (the tail no longer blocks it). Later, dissolve the pass boundary entirely
   into a continuous due-queue (each source scheduled at its own `next_due`; "pass" survives as a
   reporting window). Keep the 5 s breather only for the all-304 idle case.
4. **Respect existing arbitration**: DB-writer kinds keep their collision rules; "never two writers
   on one cursor" (world-discovery/qualification) is preserved by keeping those on the lane, never
   duplicated.

**Expected gain (measured basis, not estimate).** Duty cycle 48 % → 90 %+ ≈ ×1.9 on the fast box,
×1.4 on the slow box. The 8-core/20 GB bench machine is the designated before/after instrument
(collect_perf already logs the fetching-vs-gap share).

**Ethics/open-source.** No new network classes — the same ride-alongs, same consent envelope, same
politeness; only *when* they run changes. The lane is task-manager-visible (every network task a
visible job).

**Risks.** Session lifecycle across threads (each lane task opens its own session — the S4.1
shape); memguard interplay (lane pauses under memory pressure first, per the ladder); the
qualification ride-along currently shares the pass session/fetcher — must get its own (small,
verified change).

---

### S-C — "More lanes, same courtesy": transport parallelism + per-fetch overhead removal over Tor

**Thesis.** Parallelism across *hosts* is ethically free; the ceilings are per-fetch fixed
overheads, the governor's hardware floors, and ultimately the single Tor client. Remove overheads,
scale lanes with hardware, and give bulk downloads the multi-circuit treatment the cores were built
for.

**Current state.** w_max 50 with keep-alive pool 64; per-host circuit reuse already amortizes
circuit builds; robots cached 1 h; **but** every fetch and every redirect hop pays a local
`getaddrinfo` (finding 2), and everything rides ONE tor client process. Dump concurrency 3, OSM 2;
`plan_segments`/`reassemble`/`rank_mirrors` unwired.

**Build slices.**
1. **Kill the per-fetch local DNS when proxied**: when a SOCKS proxy is engaged, skip
   `_guard_target`'s local resolution (the SSRF concern it defends is structurally absent — the
   connection egresses via the proxy and the *exit* resolves; a rebind attack would hit the exit's
   network, not the user's LAN) and ensure the proxy URL uses hostname-proxying (`socks5h`) so
   resolution happens at the exit. One change = latency saved per fetch **and** a DNS-metadata leak
   closed. Verify-at-build: what scheme `settings.http_proxy` actually carries in the field; keep
   the local guard for non-proxied fetches unchanged.
2. **Hardware-aware lane ceilings**: raise `w_max`/pool size on capable profiles (the
   power-profiles knob table; suggest-never-silently-switch), keep the mem-low floor exactly as-is
   on small boxes (S4.3's honesty note already tells the operator what RAM capped).
3. **SOCKS proxy pool (opt-in)**: accept a *list* of SOCKS endpoints in settings (N tor instances
   or one daemon with several SocksPorts, operator-run — the app never silently spawns network
   daemons) and shard hosts across them by stable hash. Rationale (verify-at-build, stated as
   hypothesis): a single tor client's circuit crypto is effectively serialized per instance and
   becomes the aggregate ceiling well below NIC capacity; N instances scale it. Per-host isolation
   semantics are preserved (a host maps to one endpoint + one circuit). Never a transport
   downgrade — every endpoint in the pool is Tor or the pool is refused.
4. **Wire the shipped bulk-download cores**: `rank_mirrors` for dump/OSM/LEGI mirror choice
   (measured-latency ranked, unreachable mirrors listed never deleted) + `plan_segments`/
   `reassemble` for segmented multi-circuit HTTP-Range downloads of large artifacts (per-segment
   isolation tokens = parallel circuits; mandatory checksum reassembly is already the core's
   contract). This is SCRAPING_AUTOMATION_PLAN Step 3/4, cores shipped 2026-07-13.
5. **Dump/OSM concurrency onto profiles** (1–6 already ranged; raise ceilings only on measured
   headroom).

**Expected gain (estimate).** Fetch-phase ×2–5 on capable boxes (dominated by slice 3 at high
w_max); bulk artifact downloads ×3–8 (segmentation across circuits); slice 1 shaves a fixed cost
off *every* fetch on all hardware.

**Ethics/open-source.** Per-host courtesy is untouched at every slice — one in-flight, ≥1 s,
Crawl-delay, robots fail-closed, honest UA. Segmented downloads apply only to bulk artifacts
explicitly published for mass download (dumps, extracts, bulk legal bases) against their own
mirrors. No third-party proxy/scraping services — the pool is the operator's own Tor. Everything
stays stdlib/requests/PySocks; no closed dependencies.

**Risks.** Multi-instance Tor raises resource use on small boxes (profile-gated, opt-in); exit
diversity means more exit-operator exposure surface — document honestly; the SSRF-guard change
needs a careful negative-space test (non-proxied path must keep the full guard byte-identical).

---

### S-D — "Write without waiting": extraction out of the gate, indexing across cores

**Thesis.** The write path is not writer-bound because SQLite is slow — it is writer-bound because
the one gate window contains pure-Python CPU work. Move extraction *before* the gate and the gate
holds only DML; precompute extraction across cores with the already-proven process-pool shape, and
the ceiling moves from "one core's Python" to "SQLite's actual write throughput."

**Current state (verified this session).** `_flush_batched`: flush opens the gate → per-article
`index_article(commit=False)` (keyword extraction — the dominant CPU cost — plus sentiment +
when/where/who) runs inside the held window → commit closes it (`batch.py:239-249`). The fast box
already throws `writer-bound` verdicts at permits ~27. `reindex_parallel.precompute_batch` runs the
DB-free extraction steps across cores via `ProcessPoolExecutor` — for re-index only. The S2.1
rider decline (F13 "GIL-marginal") judged a *thread* split; a process pool sidesteps the GIL and
the re-index path has already proven the shape.

**Build slices.**
1. **Stage-then-gate**: restructure `ArticleBatch` so the extraction phase runs per staged entry
   *before* `flush()` (single-threaded first — correctness step), leaving inside the gate only:
   INSERTs (+FTS trigger), mention DML, counter deltas, WWW row DML, commit.
2. **Cross-core precompute**: feed the staged batch through `precompute_batch`'s pattern
   (serialize-safe inputs, DB-free outputs) so a 4–8-core box extracts 4–8 articles concurrently
   while the previous batch commits. Measure-first: wire the collect_perf writer block
   (`wait_rate`, `max_wait_s`) as the acceptance metric.
3. **Batch-size + FTS cadence tuning**: `OO_COLLECT_COMMIT_BATCH` onto the power-profile table;
   `optimize_after_bulk` cadence for sustained high-volume ingest.
4. Keep every existing safety shape byte-identical: the SAVEPOINT-per-article isolation
   (`_index_one`), the rollback-and-redo-per-article fallback, dedup re-check at flush.

**Expected gain (estimate).** ×1.5–3 on the *drain ceiling* for ≥4-core boxes at high offer. At
today's offer it changes little — this strategy is a ceiling-raiser whose value appears exactly
when S-A/S-E land (stated honestly so it is sequenced by evidence, not enthusiasm).

**Ethics/open-source.** No network behaviour change at all. Pure-Python + stdlib
`ProcessPoolExecutor`; no new dependencies.

**Risks.** This is the hot path — the ledger's "riskiest change" label and the full-skeptic-matrix
mandate stand: the delete-then-reinsert epoch trap, savepoint/commit ownership lessons, and the
autoflush-gate lesson all live exactly here. Precompute must never see a Session object
(serialization boundary = the safety boundary). Gate on `writer-bound` verdicts actually appearing
at the new offer before building slice 2.

---

### S-E — "Fetch the firehose, not the page": bulk + structured acquisition channels

**Thesis.** The cheapest fetch is the one you don't make. Publishers already declare their content
in machine-readable bulk forms — sitemaps (an explicit, robots-declared crawler contract),
full-content feeds, official bulk/API endpoints. Prefer those over page-by-page polling: fewer
requests per article, complete enumeration instead of feed-window sampling, and a one-time
historical backfill per newly qualified source that dwarfs its daily trickle.

**Current state.** Zero sitemap support (finding: dormant `sitemap_url` column, `.xml` links
skipped by the crawler). Feeds are polled with conditional GET + backoff (good), but a feed
typically windows the latest 10–50 items — anything older or missed between polls is invisible.
The wiki dump-as-baseline + recentchanges-delta model and the LEGI bulk design are the house
precedents for bulk-first acquisition; per-article fetch is the fallback, not the default, in every
mature vertical.

**Build slices.**
1. **Sitemap reader in the ONE fetch path**: parse `robots.txt`-declared sitemaps + `sitemap.xml`/
   sitemap-index + Google News sitemaps (plain XML; stdlib parseable) through `EthicalFetcher`
   (robots-gated, politeness-paced, size-bounded). Populate/refresh the dormant `Source.sitemap_url`.
   Three consumers, in value order:
   a. **new-URL discovery** for qualified sources — catches what the feed window misses;
   b. **the qualification trial channel for feedless candidates** (unblocks S-A slice 2 — this is
      what makes the 42–67 k backlog digestible at all);
   c. **historical archive backfill** (slice 2).
2. **Archive backfill as a first-class managed job**: when a source qualifies, offer a bounded
   backfill of its sitemap-enumerated history — resumable, politeness-paced (the per-host floor
   makes it self-limiting: ~1 req/s/host ceiling regardless of depth), task-manager-visible with a
   persisted cursor (the dump-manager pattern), scheduled under the ladder's lowest rung (crawl
   class). A single new source contributes its archive once — thousands of articles at zero extra
   per-host burden. This is the largest single stored-articles/day lever during the S-A rollout.
3. **Full-content feed use**: when a feed entry carries the complete body (`content:encoded`),
   store the publisher-provided text without fetching the article page — one request per N
   articles instead of N+1. Verify-at-build: current `ingest_source` behaviour; disclosure that
   `server_ip`/outbound-link capture is reduced for feed-only items (two-class metadata already
   covers "how obtained").
4. **Bulk/API-first per vertical** (the standing pattern, reaffirmed): official bulk endpoints
   before scraping wherever they exist (SDMX, dumps, LEGI, gazette RSS); key-gated firehoses stay
   opt-in per ruling V1-2.

**Expected gain (estimate).** Per-article request cost ↓ (sitemap lists hundreds of URLs per
fetch); qualification coverage of the feedless backlog goes from ~0 to full; backfill produces a
step-change in stored/day for every wave of newly qualified sources. Combined with S-A this is
what makes 10× *stored articles* arithmetically available.

**Ethics/open-source.** Sitemaps are the publisher's own declared crawl guidance — the front door,
not a workaround; robots stays fail-closed above them; Crawl-delay honoured during backfill; no
paywall circumvention (a paywalled URL fails extraction honestly); provenance stays honest
(`created_at` vs `published_at` already distinguishes backfilled history from live collection).
XML parsing via stdlib/defusedxml — no new closed dependencies.

**Risks.** Sitemap quality varies wildly (stale, huge, malformed) — size-bound + per-source caps +
the non-article gate protect the corpus; backfill volume can dominate the pipeline — the ladder
rung + a per-source backfill budget keep live collection first; huge sitemap indexes on CDN-backed
hosts still respect one-in-flight per host by construction.

---

## §4 Composition and sequencing

```
                 OFFER                ×      DRAIN CAPACITY        ×   DUTY CYCLE
        ┌───────────────────────┐        ┌────────────────────┐       ┌─────────┐
        │ S-A qualified breadth │        │ S-C transport lanes│       │   S-B   │
        │ S-E sitemaps+backfill │        │ S-D write ceiling  │       │ overlap │
        └───────────────────────┘        └────────────────────┘       └─────────┘
   est. ×5–10 (the dominant term)      est. ×2–5 where ceilings bind   ×1.5–2 measured
```

Recommended build order (each independently shippable; evidence-gated where marked):

1. **S-B slice 1–2** (housekeeping lane + KindLadder) — hardware-independent, measured ~2× on
   modern boxes, and it un-blocks S-A's trial throughput immediately.
2. **S-A slice 1 + 3** (bulk-qualification digestion at hardware-aware budgets; operator catalog
   runs) — starts the offer growing while everything else builds.
3. **S-E slice 1** (sitemap core) — multiplies S-A (trial channel for the feedless majority), then
   **S-E slice 2** (backfill job) behind a maintainer ruling on default posture (§6a).
4. **S-C slices 1–2** (DNS-when-proxied + hardware-aware ceilings) — small, safe, universal; then
   slice 3–4 (proxy pool, segmented bulk) as opt-in profile features.
5. **S-D** — *evidence-gated*: build when `writer-bound` verdicts appear at the new offer
   (collect_perf is the tripwire), under the full skeptic matrix.

Measurement protocol: the 8-core/20 GB machine is the before/after bench; instruments are already
shipped — collect_perf (rate, permits, duty share, writer block, verdicts), the Library
articles-per-hour + qualification graphs, and the per-pass `entries/duplicate/stored/not_modified`
tally. Each strategy lands with its named metric; **no multiplier is ever reported as achieved
without the corresponding before/after measurement** (the no-fabricated-pass rule applied to
performance claims).

---

## §5 Explicit non-options (ethics/open-source lines that outrank speed)

- **No per-host politeness relaxation** — the one-in-flight + ≥1 s + Crawl-delay floor is not a
  tuning knob at any scale. Scaling is breadth-only.
- **No robots fail-open, ever** — including for sitemaps and backfill.
- **No anti-bot evasion**: no CAPTCHA solving, no browser-fingerprint spoofing, no UA
  masquerading, no header camouflage. A host that blocks the honest bot stays blocked, surfaced
  with the transport-aware verdict.
- **No silent transport downgrade** — Tor-hostile hosts never fall back to clearnet without the
  explicit per-source consented opt-in already designed; a proxy pool is all-Tor or refused.
- **No third-party scraping APIs or residential-proxy meshes** — closed services, and residential
  proxies are consent-laundering; both incompatible with the project's ethics and offline
  auditability.
- **No headless-browser rendering fleet** (for now): JS-only sites are an honest coverage gap,
  stated, not an arms race to join; revisit only as its own ruled design.
- **No default key-gated firehoses** (GDELT-class, paid assessors) — user-supplied keys stay
  opt-in per open ruling V1-2.
- **No capped or fabricated numbers** — throughput reporting stays measured (collect_perf), and
  every projected multiplier above remains an estimate until the bench says otherwise.

---

## §6 Open maintainer rulings

| # | Question | Recommendation |
|---|---|---|
| a | **Archive backfill default posture** (S-E-2): auto-backfill N pages for every newly qualified source, with full-history backfill consented per source? | Bounded auto (~100–500 pages) + explicit consent for full history; both under the ladder's lowest rung. |
| b | **Proxy-pool surface** (S-C-3): accept an operator-run list of SOCKS endpoints, or wait for the designed in-app Stem-managed Tor? | Accept the list now (zero new trust surface); Stem integration stays its own future design. |
| c | **Full-content feed storage** (S-E-3): store publisher-provided feed bodies without a page fetch, with the reduced-capture disclosure? | Yes, disclosed; the page fetch remains the path when the feed body is partial. |
| d | **Sitemap-derived trial evidence** counts toward qualification exactly like feed-derived? | Yes — same extraction-validity judgment, channel recorded in provenance. |
| e | **Hardware-aware budgets** (w_max, qualification batch, dump concurrency) ride the power-profile knob table with suggest-never-silently-switch? | Yes — consistent with the 2026-07-12 profiles ruling. |

---

*Prepared 2026-07-24. Planning-only; the executing sessions take their slices from §3–§4 with the
usual gates (skeptics-before-push with the negative-space lens on S-D and the sitemap parser;
staleness guard against this document itself before building — the engine moved four times in the
week before it was written).*
