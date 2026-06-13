# Scraping automation & the download subsystem — action plan

> **Status:** maintainer-commissioned 2026-06-13; awaiting review.
> This is THE retrievable home of the plan triggered by the 2026-06-13
> field session (slow-over-Tor downloads, "the task manager is absent",
> "move Collect into Settings", "the app should focus on content, not
> scraping mechanics"). It folds together five maintainer messages that
> are really one subsystem. Ledger pointer: CLAUDE.md queue; design
> neighbours: FUTURE_DEVELOPMENTS §"Continuous collection & fair ordering"
> and §"Network switch".

## The maintainer principle (verbatim, for recall)

> "I'd like the UI to focus more on the content, less on the technical
> aspects of the database ingestion and so forth. The entire 'collect'
> tab should be moved in the 'settings'. We want the app to, after user
> consent, automatically scrap the web. The user should be able to
> organize, prioritize, and so forth, but in my honest opinion, having to
> setup everything is just cumbersome. The app should focus on data and
> content analysis, not the scrapping mechanics."
> — maintainer, 2026-06-13

The north star: **after one informed consent, the corpus fills itself.**
The user spends attention on *what the data means*, never on *making the
data arrive*. Power and transparency are preserved — moved, not removed
(the Desk lesson: never silently lose a tool) — into one Settings home and
one task-manager window for those who want the controls.

---

## Why downloads are 56K-modem slow today (root cause, code-verified)

The user is on Tor and sees ~56 Kbit/s. Two compounding causes, both ours
to fix; Tor is only half the story:

1. **The app serialises every network operation.** Dump downloads run
   `max_concurrent = 1` (`src/wiki/dumps.py:92`); the collect pass is a
   sequential `for … in sources` loop (`src/scheduler/runner.py:217`). At
   any instant there is exactly **one** connection doing work.
2. **Tor's bottleneck is per-circuit, not per-machine.** Every stream
   rides one 3-hop circuit bounded by its slowest relay and a congested,
   bandwidth-shared exit. Tens of KB/s on a single circuit is normal Tor
   behaviour, not a bug. Because we run exactly one stream at a time, we
   get the *worst* case of Tor: one slow circuit, never parallelised.

**Corollary — the maintainer's instinct is exactly right, and Tor makes
parallelism MORE valuable, not less.** N concurrent downloads ⇒ N circuits
⇒ aggregate throughput multiplies even while each individual stream stays
slow. Parallelism is the single biggest lever for a Tor user.

**Latent transport bug found in the same code (RC-relevant):** the dump /
wiki downloaders use raw `requests.get` with no `proxies=`
(`src/wiki/dumps.py:311`), so they ride Tor **only** via OS/env-level
proxying. A user who set Tor *only* in the app's proxy setting (not the
environment) would have dump downloads silently go **clearnet** — a
violation of the non-negotiable "never silently downgrade transport". For
this user (downloads are slow ⇒ traffic IS on Tor) the VM almost certainly
routes everything through a Tor gateway (Qubes/Whonix), so env catches it;
the leak is latent for others. Fixed in Step 1 below.

---

## Step 1 — Route every fetch through ONE guarded socket factory (foundation)

Everything else depends on this. Today six modules import `requests`/`httpx`
directly (pinned by `tests/test_network_consent.py`); four of them
(`wiki/dumps`, `wiki/client`, `wiki/ores`, `services/duckduckgo`) bypass
the `EthicalFetcher`, so they bypass the **kill switch, the proxy, and the
honest UA** all at once.

- Build the single guarded socket factory already queued as RC §1 SHOULD —
  **elevate to RC-BLOCKING (ethics-facing).** Every outbound byte passes:
  kill-switch check, proxy (incl. SOCKS5 to Tor), robots fail-closed,
  per-host politeness, true versioned UA.
- This closes, in one move: the kill-switch gap (audit T-A #1), the stale
  `OpenOmniscienceBot/0.4` UA (T-A #2), and the proxy-bypass transport leak
  above. The socket-importer ratchet shrinks from 6 allowed modules toward
  2 (the factory + loopback Ollama).
- **Acceptance:** with airplane-mode engaged mid-dump, the download stops;
  with Tor set only in app settings, a dump download provably egresses via
  SOCKS (test asserts `proxies` present on the dump session).

## Step 2 — Parallel downloads (the headline win)

- **Dumps:** raise the queue's `max_concurrent` from 1 to a user setting
  (default 2–3; the reorderable single-queue invariant from T9 generalises
  to a bounded pool). Each download = its own connection = its own Tor
  circuit. Dumps write **files, not the DB**, so this has zero single-writer
  contention (the T9 ruling already blesses dumps-parallel-with-collect) —
  the only arbitration is bandwidth, surfaced in the task manager.
- **Collect pass:** replace the sequential loop with a **bounded fetch
  worker pool** that fetches *different hosts* concurrently while a single
  consumer drains results into the one SQLite writer. Fetch is parallel;
  the DB write stays serialised (design intact). The fair-ordering scheduler
  (per-country round-robin) feeds the pool.
- **Guardrail — politeness is sacred:** concurrency is **across hosts and
  across circuits**, never N connections hammering one host past its
  robots/crawl-delay. Per-host delay is enforced per host, not globally, so
  parallelism across hosts is free; parallelism *to one host* stays ≤ its
  policy.

## Step 3 — Segmented (HTTP Range) download of one large file over many circuits

The download-accelerator technique, and the cure for a *single* big dump
being slow on a *single* circuit.

- Split one dump into K byte-ranges (`Range:` requests; Wikimedia mirrors
  support it), fetch each range on a separate connection ⇒ separate circuit,
  reassemble on disk, verify the whole-file checksum.
- **Bounded and respectful:** small K (default 2–4), configurable; this is
  multiple connections to ONE host, so it counts against that host's
  politeness budget — conservative default, never aggressive. Fall back to a
  single stream if the server doesn't honour Range (`Accept-Ranges`).
- Pair with **Tor stream isolation** (`IsolateSOCKSAuth`: distinct SOCKS
  user/pass per range) so K ranges map to K genuinely different circuits
  instead of Tor reusing one.

## Step 4 — Mirror selection for dumps

- Wikimedia publishes multiple dump mirrors with different peering. Let the
  user pick (or auto-probe latency, behind consent), default to the
  canonical. Surfaced in the Settings → Download section, not in the user's
  face.

## Step 5 — Automated collection after one consent (the content-first default)

Builds directly on FUTURE_DEVELOPMENTS §"Continuous collection & fair
ordering" — that design is adopted, this plan wires it as the default path.

- After the **guided first-launch wizard** ends at the one consented first
  collect (see §"First-launch guided setup" ruling), background auto-collect
  is **ON by default** — scraping never stops. Zero-network boot is
  untouched: nothing moves before the operator says go, once.
- Ordering: per-country round-robin (shuffled each cycle,
  least-recently-scraped within a country) — structurally breaks the
  US-volume bias. The schedule stays **explainable** ("cycle 14, 37/92
  countries served, next: ke — nation.africa").
- The user *can* organise/prioritise/weight (country & language emphasis
  from the wizard, editable later) — but never *must*. Out of the box it
  just runs.

**Refinements (maintainer field session 2026-06-13):**

- **The app BOOTS in airplane mode (offline) every time.** Zero-network boot
  is already the design; make it explicit and visible — nothing scrapes until
  the user crosses online once. After that one consent, collection is
  continuous.
- **When online, scraping is PERMANENT/continuous.** Replace today's
  run-once-then-idle interval (`src/scheduler/runner.py:326` waits
  `interval_minutes` between passes — this is why the user saw scraping
  "stop": it idles, it did not crash) with a continuous fair-ordering loop
  that always has work in flight (within politeness).
- **Demote the cross-kind arbitration MODAL.** Today a new scrape while a
  pass runs pops "Another network task is running… Start anyway?". Instead a
  new request **queues into the task manager** silently; DB-writer collisions
  still serialise, but invisibly — the user sees a queued job, never a
  question. (The modal was the right primitive for the manual era; continuous
  + queue replaces it.)
- **NO source cap — cover EACH AND EVERY source, ALL modes.** Remove
  `max_sources_per_run` (the 1000 cap): any cap *selects* which sources to skip,
  and that selection cannot be justified. The continuous per-country round-robin
  already guarantees every source is reached over time without starvation, so
  the cap is both unnecessary and unethical. All modes run (RSS + crawl +
  markets + commodities + weather + wiki + DDG).
- **Bandwidth PRIORITY LADDER (ordering ≠ exclusion).** Under constrained
  bandwidth, decide what runs *first*, never what runs *at all*:
  1. **commodities / markets / weather** — small payloads, cheap, high value;
  2. **interactive DDG searches** — snappy UX (user-facing preempts background);
  3. **RSS feeds**;
  4. **recursive crawling** — heaviest, only with bandwidth headroom.
  Weight by (freshness-due, cost, interactivity): periodic markets/weather fetch
  when new data is due, not constantly. The **task manager surfaces and tunes**
  this allocation (a bandwidth budget/meter across job kinds), tied to the
  measured throughput and the Step-2 parallel-download concurrency.

## Step 6 — Move "Collect" into Settings → Download (hide the mechanics)

- The Collect **tab leaves the sidebar.** Its mechanics move to an
  elaborated **Settings → Download** section: source seeding, schedule &
  pace, per-host politeness, proxy/Tor, parallelism (Steps 2–4), mirror
  choice, retry/backoff, dump language list, kill-switch defaults.
- **Nothing is lost** (Desk lesson): every Collect capability has a home in
  Settings or the task-manager window before the tab is removed — enforced
  by an invariant test, like the Search-tab absorption gate.
- The sidebar's data tabs (Home, Insights, Library, Markets, Temporal map,
  Wikipedia, World law, Agenda…) become the whole front-of-house. This is
  invariant #8 ("the UI shows DATA, never plumbing") applied to the biggest
  remaining plumbing surface.

## Step 7 — The Task Manager as a dedicated window (not a bubble)

The vitals popover graduates into a real OS-style task-manager **window/
tab** (maintainer's detailed spec, 2026-06-13). Today's bubble content
(jobs · targets · per-source ↓ rate · system vitals) becomes the seed of a
tabbed window where the user can **understand, explore, manage, organise,
sort, prioritise, queue** every download/scrape and any other job.

Proposed tabs inside the window:

- **Active** — running jobs with live progress, per-job ↓ rate (measured
  from our own responses), circuit/transport label, Stop/Pause/Cancel.
- **Queue** — pending downloads/scrapes; drag-reorder, prioritise, set
  parallelism; the fair-ordering "what's next & why" explainer.
- **Sources / Schedule** — the continuous-collection view: which country is
  next, coverage served, pace.
- **History** — completed/failed jobs with honest verdicts (the T4 transport-
  aware taxonomy: refused ≠ robots-disallowed ≠ dead ≠ unreachable ≠
  offline), bytes, duration, retry.
- **System** — CPU · RAM · aggregate ↓ rate as a compact strip (demoted from
  headline to footer, per invariant #4 spirit).

Built on `/api/jobs` (T9 already aggregates live from the owning systems —
no shadow state). The bubble stays as the at-a-glance minimised indicator;
clicking it opens the window. Informed-consent layering throughout; ×12
locales.

---

## Sequencing

1. **Step 1** (socket factory) — foundation + closes three audit findings.
2. **Step 2** (parallel queue + parallel collect) — the headline speed win.
3. **Step 7** (task-manager window) — so the new parallelism is visible &
   controllable as it lands.
4. **Step 5** (auto-collect default) — needs the guided wizard's consent.
5. **Step 6** (Collect → Settings) — once the window + Settings home exist
   to receive every capability.
6. **Steps 3–4** (segmented Range, mirrors) — the deepest Tor speedups,
   after the cheap parallelism proves the gains.

## Ethics guardrails (binding, every step)

- Per-host politeness is **never** traded for speed; parallelism is across
  hosts/circuits, bounded to one host's policy.
- **Never** a Tor→clearnet fallback for throughput (Step 1 fixes the latent
  leak; no new one may appear).
- The kill switch gates **every** worker and every parallel range.
- Auto-collect is **opt-in** via the one consent design, always visible,
  always stoppable; zero-network boot preserved.
- Dumps parallelise freely (file writes); collect parallelises *fetch* only,
  the single SQLite writer stays single (reliability mandate intact).
- Degrade loudly: every failed/slow job shows the honest transport-aware
  verdict, never a silent retry on a different transport.
