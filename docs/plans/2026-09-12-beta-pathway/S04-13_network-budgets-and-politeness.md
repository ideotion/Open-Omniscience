# S04-13 — Network budgets and politeness · 0.4, `RELEASE_0.4_GATE.md` row T

> **Scope:** `src/ingest/__init__.py` (`EthicalFetcher`: the per-host sleep, the persisted robots cache,
> `make_fetcher`), `src/ingest/download_rate.py`, the governor knobs in `src/scheduler/settings.py`,
> `src/api/ratelimit.py` and the `@limiter.limit` decorators, the `#net-coach` styling, the task-manager
> airplane title in `src/static/taskmanager.html`, the `model-weights-revision` entry in
> `configs/external_artifacts.yml` and the pull path (`src/api/llm.py`, `src/llm/pull_queue.py`). It must
> NOT: add per-job caps, a second rate
> authority, a Tor → clearnet fallback, or any consent copy beyond Q1126's one string.
> **Implements:** Q1012, Q1013, Q1125, Q1126 ⛔ = a, Q1132, Q1148.
> **Gated on:** the digest values for Q1132 need `huggingface.co` / `ollama.com` (egress-blocked here — an
> operator value); nothing PENDING.
> **Sequencing:** independent; S04-08's lanes compose with the governor through the ONE authority S1 names, so
> land S1 before or with S04-08's per-lane budgets.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§11 for Q1012 / Q1013; §12 for the rest, whose context is the 2026-09-06
register: L4, M2, D6, Q-VIS-7). Grep the tree before building anything — the sheet's anchors were verified at
`main`@`bebcef4` on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1012** — **(a)** «A per-PROCESS budget composed with the collection-speed governor (`#rate-toggle`),
  never a second rate authority beside it; per-job caps stay omitted.»
- **Q1013** — **(a)** «Persist a per-host next-allowed-at beside the robots cache; refuse an inline wait
  beyond a few minutes with a named deferral counted as its own bucket; the ride-along and trial fetch inherit
  both.»
- **Q1125** — **(a)** «Both actions carry equal visual weight; "Not now" is not quieter than "Go online".»
- **Q1126** ⛔ — **(a)** «Align the task-manager title to the stronger, true claim ("every new network request
  will be refused"), re-translated ×12.»
- **Q1132** — **(a)** «Pin digests in the external-artifact registry; the pull verifies them.»
- **Q1148** — **(a)** «Raise it for loopback UI calls (1,000/hour), keep 100 for anything else.»

**Register round 2026-09-15 (L4):** «Adapt the rate limit to what's most ethical while keeping the app's
efficiency and performance in mind.» qualifies Q1148 = a; `RC15` asks whether it means this loopback guard or the
egress politeness (Q1013). D6 = `default` = Q1132 (a), consistent.

**RC round 2026-09-15 — BLANK (0 of 22 `ANSWER` lines carry a letter); §0's blank rules applied, nothing resolved.** `RC15` → **ASSUMPTION (a): L4's «most ethical» is the app's
own loopback guard**, so Q1148's figures stand as this brief already has them (1,000 / hour for loopback UI
calls, 100 for anything else) and the per-host egress politeness (Q1013 = a, also in this slice) is NOT
re-opened. Nothing to change; recorded so that a later reading of L4 as the egress knob is a reversal rather
than a discovery. Writing `b` at `ANSWER RC15` would move the change onto Crawl-delay and the per-host
floor; `c` would reach both.

## 2. Where this stands in the tree — the staleness guard, with anchors

- `CLAUDE.md` invariant #20 already carries the amendment: "RULED 2026-09-15 (answer sheet Q1012 = a; Q222 =
  b): the bandwidth budget is PER PROCESS, composed with the collection-speed governor … per-job caps STAY
  omitted (0.4 slice S04-13)" — grep-verified: `grep -n "Q1012" CLAUDE.md` (line 470).
- The governor: `collect_rate_mode` (`"maximum"` | `"target"`), `collect_target_kbps: int = 500`,
  `collect_parallelism: int = 50` at `src/scheduler/settings.py:63–65`; `#rate-toggle` at
  `src/static/index.html:133` — grep-verified. The per-job MEASUREMENT exists (`src/ingest/download_rate.py`,
  PERF-09); no per-process budget exists.
- The fetcher: `_last_request` per instance at `src/ingest/__init__.py:635` (rebuilt per pass by
  `make_fetcher` — the docket's politeness trap), the injectable `self._sleep = time.sleep` at `:654`,
  `_robots_cache_path` → `robots_cache.json` at `:203–206`, `_declares_crawl_delay` `:736`, `crawl_delay_for`
  `:754` — grep-verified. The docket entry (`OPEN_QUEUE.md` ~13273–13295) names the sleeping method
  `_respect_rate_limit`; `grep -n "def _respect_rate_limit" src/ingest/__init__.py` finds nothing today —
  locate the sleep site by the `_sleep` injection before changing it. The ride-along is
  `advance_qualification` (`src/scheduler/runner.py:413` comment), the trial fetch `trial_fetch`
  (`src/catalog/qualification.py:230`).
- The rate limit: one shared `Limiter` in `src/api/ratelimit.py`; 66 `@limiter.limit` decorators across
  `src/api/*.py` — e.g. `"100/hour"` on `/api/articles` at `src/api/main.py:1434`, with `"50/hour"`,
  `"300/hour"`, `"10/hour"` variants; the handler at `main.py:794–821` reports the honest window —
  grep-verified: `grep -rn "@limiter.limit" src/api/*.py`. Register L4: the 2026-07-22 GUI run produced 384
  console lines that were 100 % rate-limit refusals under 14 concurrent agents.
- `#net-coach` at `src/static/index.html:3178–3186`: `<button class="secondary" id="net-coach-dismiss">Not
  now</button>` beside an unclassed `<button id="net-coach-go">Go online</button>` — the unequal weight
  (grep-verified).
- The two titles: `src/static/app-core.js:652` "Online — click to go offline (airplane mode); every new network
  request will be refused." and `src/static/taskmanager.html:674` "… stops all collection." — grep-verified.
  `app-core.js:645–656` and `:905–912` record a THIRD state: while an AI-install egress window is open the
  "every new network request will be refused" line "is simply FALSE", so the main UI paints a different title
  then. Locales live in `src/static/locales/*.json`.
- The registry: `configs/external_artifacts.yml:197` `model-weights-revision` (and the roster model's
  identifier entry beside it at `:172`) — grep-verified; register D6: weights are "the one downloaded artifact
  with no pin". The pull path: `src/api/llm.py:789` `llm_pull`, `src/llm/pull_queue.py`,
  `src/llm/model_store.py`.

## 3. Slices — what to build, in order

### S1 — The per-process budget, composed with the governor
- **What:** ONE authority: the governor keeps the target; a per-process budget composes with it in one named
  module (the fetch permits already governed there), never a second rate authority; per-job caps stay omitted
  and the invariant #20 text stays true; the task manager shows the process budget and the measured actual
  beside the per-job rates, absent (with a reason) when unmeasured — never 0. Mind the LESSONS entry on a
  control loop reading a whole-machine gauge.
- **Why (ruling):** Q1012. **Acceptance:** a test that the budget composes with the governor in one place
  (gate); the `#rate-toggle` still switches modes through the loopback `PUT /api/scheduler/config`.

### S2 — The Crawl-delay cap
- **What:** a per-host next-allowed-at persisted beside `robots_cache.json` (surviving the per-pass fetcher
  rebuild); an inline wait beyond a cap of a few minutes (the value published in the PR) refused with a NAMED
  `FetchError` ("Crawl-delay N s: not before T") the collector counts as its own bucket and the scheduler
  treats as a deferral, never a failure of the source; no fetch before the declared delay has elapsed; the
  ride-along and the trial fetch inherit both. Strings that reach the UI ×12.
- **Why (ruling):** Q1013. **Acceptance:** on a fixture host declaring a long `Crawl-delay`, the deferral
  bucket appears in the pass summary (gate); a second pass minutes later does NOT fetch that host.

### S3 — The loopback rate limit
- **What:** 1,000/hour for loopback UI calls, 100 kept for anything else, through the one `Limiter`'s key
  function; the handler's window stays honest.
- **Why (ruling):** Q1148. **Acceptance:** a test drives 101 loopback calls and sees no refusal; a
  non-loopback caller (the app binds loopback — the PR states what "anything else" can be) still gets 100.

### S4 — `#net-coach` at equal weight
- **What:** both actions with equal visual weight ("Not now" not quieter than "Go online"); words unchanged.
- **Why (ruling):** Q1125. **Acceptance:** Chromium-verified across several themes (gate).

### S5 — The task-manager airplane title
- **What:** `taskmanager.html:674` aligned to the stronger, true claim, re-translated ×12; the THIRD state of
  `app-core.js:645–656` mirrored, so the stronger claim is never painted while it is false.
- **Why (ruling):** Q1126 ⛔ = a (consent copy). **Acceptance:** the three i18n gates green; the hover
  Chromium-verified in both states.

### S6 — Model-weights digests
- **What:** digests pinned in `configs/external_artifacts.yml` (the `model-weights-revision` entry); the pull
  verifies them and REFUSES a mismatch with a named reason (re-pin deliberately); the pull stays under the one
  consent, refused under the kill switch by name; the digest VALUES are an operator input (§5).
- **Why (ruling):** Q1132. **Acceptance:** a fixture pull with a wrong digest is refused by name.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (470 / 231 today). Plus: `node --check` on touched script blocks; the three i18n gates, run
separately, for the one re-translated title and every deferral / budget string; the whole-tree guard set;
the behavioural tests named per slice; mutation-check each new guard by name (neuter the deferral, watch the
test redden); the consent / kill-switch fixture for the pull (engage airplane mode first); the Chromium
click-through record (Q1128 = a) of `#net-coach` (several themes), the task-manager title hover and the
task-manager budget line, in en / fr / ar at least; the `shipped.csv` numstat + duplicate-key scan.

## 5. Operator steps

1. Supply the weights digests read from the publishers (the sandbox proxy answers `CONNECT … 403`); artifact:
   the registry diff with the values and their source.
2. The click-through of `#net-coach` and the task manager (Q1128 = a).

## 6. What this slice may not decide

- **The cap value** ("a few minutes") — published in the PR, revisable.
- **What "anything else" means** for a loopback-only server (a forwarded or hidden-service caller) — stated,
  not assumed.
- **Whether the digest pin is per revision or per file** — the entry's own shape decides; a mismatch refuses.
- **Any per-job cap** (ruled out) and the History subtab for other job kinds (unruled, per invariant #20).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
