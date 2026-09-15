# S04-09 — The Wikipedia lane: the stream and the HOT tier · 0.4, `RELEASE_0.4_GATE.md` row P

> **Scope:** `src/wiki/` (a hand-rolled SSE client, tiers, identity, log events, the diff primitive) on
> S04-08's substrate and `wiki.db`; `src/api/wiki.py`; the top-bar toggle (`index.html` + `app-core.js`); the
> first-run wizard; the reader's attribution; the Home strip figure; analytics 1–3; the wiki map layer (Q819
> step 1); the dump→corpus endpoint's retirement. NOT: WARM / COLD ingest and the tail walk (0.5, S05-06),
> analytics 4–5 (0.5), the coverage report (0.6, S06-03), the dump manager and offline reader (they stay),
> the backup format (S04-04), OSM (0.5).
> **Implements:** Q108, Q702 ⛔ (TENSION — the note is the ruling), Q703, Q704, Q705, Q706, Q707, Q708, Q709,
> Q710 🔒, Q711, Q712, Q713, Q714, Q715, Q717, Q718, Q721, Q725, Q726, Q727, Q728, Q819.
> **Gated on:** S04-08 (substrate, `wiki.db`, lanes, the budget table); S04-01 (the hosts and the hover); the
> ≥ 72 h run is an operator step; no ⛔ left blank inside the slice.
> **Sequencing:** after S04-08; the map layer rides S04-11's `project(lon, lat)` seam; S04-03 shows the size.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§8 — its VERIFIED context, SEARCH-VERIFIED scale and FROM MEMORY facts; §2
for Q108; §9 for Q819). Grep the tree before building anything — the sheet's anchors were verified at
`main`@`bebcef4` on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q108** — **(a)** «0.4: the stream (metadata for every edit, all twelve editions) + HOT full text; 0.5:
  WARM + the tail walk under budget; 0.6: the coverage report per edition.» [0.4; 0.5 = S05-06; 0.6 = S06-03]
- **Q702** ⛔ — **(b)** «A dedicated Wikipedia toggle, default off.» — NOTE (verbatim): «but make it default
  on, and add a toggle on the taskbar -like the AI toggle, with a nice and consistent animation- , to allow
  users to stop / start / halt / resume wikipedia streaming» [TENSION: the note is the ruling — DEFAULT ON, a
  top-bar toggle with stop / start / halt / resume; the label's "default off" is overridden.]
- **Q703** — **(a)** «Namespace 0 (articles), excluding redirects, including disambiguation and list pages.»
- **Q704** — **(a)** «Wikitext (the source of truth: infoboxes, `{{coord}}`, categories and templates are
  extractable from it) + a derived plain text for the FTS index.»
- **Q705** — **(a)** «Confirm the list.» (the sheet's proposed per-page metadata list, §8)
- **Q706** — **(a)** «The daily top-1,000 per edition (12 requests a day) + per-article daily views for HOT
  pages.»
- **Q707** — **(a)** «Three tiers under a per-edition daily budget the first-run wizard sets (default proposed:
  20 GB total, published): HOT = pages the corpus already mentions, tracked pages, and the pageview top-1,000
  (full text + `index_article` on every change); WARM = every other changed page (full text, indexed lazily
  under the daily budget); COLD = the tail reached by the walk (metadata now; text as budget allows).»
  [tiers + wizard budget in 0.4; WARM/COLD ingest in 0.5 (S05-06)]
- **Q708** — **(b)** «Every edit as a row for every page.»
- **Q709** — **(b)** «Keep everything raw.»
- **Q710** 🔒 — **(a)** «HOT: every ingested version's text; WARM: latest + previous; counters and metadata
  forever.»
- **Q711** — **(a)** «Against the previous ingested version, section-aware (which section changed),
  per-mention revid anchoring per the standing ruling.»
- **Q712** — **(a)** «Confirm the five and the order (1–3 in 0.4, 4–5 in 0.5).» [1-3 in 0.4; 4-5 in 0.5
  (S05-06)] (the sheet's five: edit velocity · contested pages · newly created pages · divergence · attention)
- **Q713** — **(a)** «Tracked from the stream's log events; a deleted page keeps its last text and is marked
  deleted.»
- **Q714** — **(a)** «Separate lane counts everywhere; the "articles" headline stays press unless a lane
  filter is chosen; the Home strip shows "Wikipedia: N pages · M changes today" as its own figure.»
- **Q715** — **(a)** «`WikiPage` keyed `(wiki, pageid)` with `qid`; the Article carries `wiki_pageid`, `qid`,
  `source_revision` (exists), `source_type="wikipedia"`, the edition as language.»
- **Q717** — **(a)** «Verify Wikimedia's current scoring endpoint (the ORES → Lift Wing migration, FROM
  MEMORY), keep it opt-in, ≈-labelled.»
- **Q718** — **(a)** «Excluded under V1-2 (no key-gated source), confirm.»
- **Q721** — **(a)** «Lane backups are opt-in members with their size shown (Q219); HOT pages' Articles ride
  the corpus backup as any Article.»
- **Q725** — **(a)** «Edition choice (default: all twelve) + the storage budget (Q707) + the plain statement of
  what the lane contacts.»
- **Q726** — **(a)** «`docs/SECURITY.md` lists every Wikimedia host; the Wikipedia surface states the robots
  exemption the way `stats/fetch.py:22–25` does; the reader shows the CC BY-SA 4.0 attribution with a link to
  the page history.»
- **Q727** — **(a)** «If the gap exceeds the stream's retention, fall back to `list=recentchanges` per edition
  (bounded at 30 days by MediaWiki), then record an honest gap ("no change data between … and …").»
- **Q728** — **(a)** «The modal becomes the Living sources view; the dump machinery stays (it is built and
  tested) as an opt-in offline reader, never the tracking path; the dump→corpus endpoint is retired.»
- **Q819** — **(a)** «Confirm the order (1–2 in 0.4/0.5 with the wiki lane, 3 in 0.5, 4 in 0.6).» [steps 1-2
  with the wiki lane (0.4/0.5); 3 = S05-04; 4 = S06-03]

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §8 (VERIFIED, confirmed): nothing watched by default, `WikiPage(` only at `src/wiki/track.py:47`;
  per-page revision polling; `list=recentchanges` has a client (`src/wiki/mediawiki.py:85–103`,
  `src/wiki/client.py:81`) and no consumer; NO EventStreams (`grep -rn "Last-Event-ID\|stream.wikimedia.org"
  src/ --include=*.py` → nothing); wiki tracking is a scheduler MODE (`settings.py:66`, `runner.py:744–761`).
- Only the latest text becomes an Article at `src/wiki/corpus.py:322–336`, with no `pageid`, QID or
  `source_type` (confirmed); `Article.source_revision` is `String(64)` at `src/database/models.py:786`.
  `WikiPage` today: unique on `(wiki, title)`, `pageid` NULLABLE, no `qid`, `missing` at `:2154`;
  `WikiRevision` already carries `editor`, `size`, `delta_bytes`, `tags`, `minor`, `bot`, `diff`, `full_text`,
  `ores_*`, `flagged` (grep-verified over `models.py:2124–2226`).
- The bot UA is `src/wiki/client.py:20–23`. The API robots exemption is the `guarded_session` docstring at
  `src/safety/fetcher.py:173–175` (the sheet wrote `fetcher.py:173–175` without its directory); the SDMX
  precedent is `src/stats/fetch.py:22–26`. `src/wiki/` has 12 `.py` files (the sheet counted 13); `ores.py` is
  the ORES client; `languages_ui_first()` (`src/wiki/languages.py:240`) orders the 12 UI locales first.
- `POST /dumps/corpus-ingest` is `src/api/wiki.py:533` (limit 1,000, no UI); `<dialog id="wiki-tc">` is
  `src/static/index.html:3101`; the first-launch flow is `src/static/unlock.html` (`:336–344`); `#set-wikipedia`
  is `index.html:1693`; `#net-toggle` (invariant #14 grammar) is `:142`; the only AI element in the top bar is
  the `#llm` status PILL at `:124` (`app-ai-tools.js:475/578`); NO attribution anywhere (`grep -rln "CC BY-SA"
  src/` → nothing) — all grep-verified. `docs/SECURITY.md` omits the Action API, ORES / Lift Wing and the
  dumps host (sheet §11) — S04-01 adds them; new hosts land in the SAME diff as the code (Q1001).
- Scale (sheet, SEARCH-VERIFIED unless noted — confirm before building on it): ≈ 24 M articles across the
  twelve; enwiki ≈ 80–160 k edits/day, "the other eleven together are of the same order (FROM MEMORY)"; up to
  50 titles per request, serial; EventStreams resumes with `Last-Event-ID`, retention "7 days by default FROM
  MEMORY; the service can extend to 31"; Q708's "250–300 k rows/day (FROM MEMORY)". The row MEASURES these.

## 3. Slices — what to build, in order

### S1 — Identity and the storage shape on `wiki.db` (data safety: full skeptic matrix)
- **What:** Q715's identity (a lane-file migration — page MOVES change titles, so identity is never the
  title), Q704's two text forms, Q705's fields (absent when unanswered, never 0), Q708 / Q709 (every edit a
  row, raw, bot / minor as flags), Q710's retention declared, Q713's log events (reuse or extend `missing`),
  Q703's namespace rule. **Acceptance:** the synthetic edition round-trips with the identity columns set; a
  fixture move keeps identity, a fixture delete keeps its text.

### S2 — The stream: SSE hand-rolled, resumed, gap-honest (Q108, Q727, Q1015, Q1014)
- **What:** a persistent SSE connection to EventStreams over `guarded_session` (no new client library) for
  the twelve editions, resumed with `Last-Event-ID`; Q727's fallback and gap record (×12, in the Living
  sources view); under the ONE online consent; refused under the kill switch by NAME; the user's transport
  never downgraded (the gate row cites Q722 = b); hosts in `SECURITY.md` + the hover in the same diff; the
  stream's name, filtering and retention confirmed against Wikimedia's documentation, tier recorded.
  **Acceptance:** a replayed fixture stream drives S1 under the airplane socket guard with zero resolutions.

### S3 — The top-bar toggle, DEFAULT ON, stop / start / halt / resume (Q702's NOTE)
- **What:** the toggle as the note rules it; constant footprint (invariant #3); the FILL-state grammar of
  `#net-toggle`, never an action glyph; the first egress still passes `ensureOnline` (invariant #14); the
  hover names what the lane contacts (#17); ×12, caveat visible. Design note for the verbs: stopped = lane
  off · halted = paused, cursor kept · resume = from `Last-Event-ID` · start = on. **Acceptance:** Chromium
  record of every state in en / fr / ar and the consent popup on the first go-online (engage airplane mode
  first); the maintainer's click-through.

### S4 — Tiers, wizard, pageviews, disclosure, superseded surfaces (Q706, Q707, Q716–Q718, Q721, Q725–Q728)
- **What:** Q707's tiers with WARM / COLD DECLARED only (ingest is 0.5), the 20 GB default in S04-08's table;
  Q725's wizard, reachable from `unlock.html` AND `#set-wikipedia` (design note); Q706's pageviews (one
  request per edition per day); `POST /api/wiki/pages` = "pin to HOT"; Q726's three disclosures (the robots
  statement the way `src/safety/fetcher.py:173–175` / `src/stats/fetch.py:22–26` do; the attribution's
  page-history link under invariants #7 and #6); Q728 (the modal → S04-08's view, the dump reader stays,
  the endpoint retired with a test anchored to the router definitions); Q717 (verify, opt-in, ≈); Q718 (a
  stated exclusion); Q721 (the member hook). **Acceptance:** the wizard Chromium-verified; a fixture proves
  the budget stop; the endpoint-gone test; the attribution verified.

### S5 — The diff primitive, analytics 1–3, separate counts, the map layer (Q711, Q712, Q714, Q819)
- **What:** Q711's diff (grep `OPEN_QUEUE.md` for the standing revid-anchoring ruling first); analytics 1–3
  as counts with method + caveat + n (sparse → bars); Q714's separate counts and the Home strip figure (×12);
  Q819 step 1 through the `project(lon, lat)` seam, the QID stored so step 2 joins in 0.5.
  **Acceptance:** fixture counts equal known values; the strip figure and the layer Chromium-verified.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (470 / 231 today); `node --check` on every touched script block; the three i18n gates for
every new string; the whole-tree guard set; the socket-importer ratchet (`tests/test_network_consent.py`);
the fixture stream under the airplane guard; the NAMED kill-switch refusal and transport-wait fixtures; the
resume / fallback / gap / budget-stop fixtures; the endpoint-gone test; the full skeptic matrix on S1; the
Chromium click-through record (Q1128 = a) for the toggle (every state), the wizard, the Home strip, the
attribution and the Living sources wiki facet in en / fr / ar; the `shipped.csv` numstat + duplicate scan.

## 5. Operator steps

1. Run the lane ≥ 72 h on the reference VM inside its budget with all twelve editions; read its OWN counters
   from ONE artifact (rows / day, bytes / day, gap history), written where the soak bundle
   (`GET /api/diagnostics/soak-window`, row D) reads; quote it in the PR; the measured figures replace the
   sheet's FROM MEMORY ones in the ledger. `not-measurable-here`.
2. The click-through of the toggle, wizard, strip and attribution (Q1128 = a), recorded per surface.
3. Confirm the stream's retention and the scoring endpoint on a networked machine while the sandbox probe
   (`curl -o /dev/null -w '%{http_code}' https://<host>/`) still answers `000` (row V).

## 6. What this slice may not decide

- **Q702's exact control** — which control's animation to mirror (`#llm` is a pill) and the stop / halt
  semantics; the PR body states the mapping, the maintainer may move it.
- **Q707's default** — 20 GB total is the sheet's "default proposed"; no `NOTE: budget = …` was written, so it
  stands; changing it is the maintainer's.
- **FROM MEMORY facts** — the retention, rows/day and the scoring endpoint: confirmed with the source named,
  measured by the operator run.
- **Not this release** — WARM / COLD, the tail walk (Q701 = c, per the gate §4), analytics 4–5, the coverage
  report, the Place entity; the wizard for existing installs; the page-history link's shape under #6 / #7.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
