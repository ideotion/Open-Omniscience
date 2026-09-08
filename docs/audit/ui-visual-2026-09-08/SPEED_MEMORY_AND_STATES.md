# Speed, memory and the states nobody sees (2026-09-08)

> One of five per-workflow syntheses from the live visual audit. See
> [`../11_VISUAL_UI_AUDIT_2026-09-08.md`](../11_VISUAL_UI_AUDIT_2026-09-08.md) for method and scope.
> **Report-only.** Every wall-clock number here was taken on a host shared with ~12 concurrent
> agents (load average 20-151, two Chromium crashes, one OOM-killed server): treat the RATIOS,
> byte counts, call counts and node counts as the findings, not the absolute milliseconds.

**Method conditions that apply throughout:** measurements below come from five parallel audit sessions plus one adversarial re-verification pass, all run against loopback instances of Open Omniscience sharing a sandbox with roughly a dozen other concurrent agents (`uptime` load average ranged 20–151 across sessions; two Chromium crashes and one OOM-killed server process were recorded). Where a number is wall-clock and contention-sensitive, it is flagged; **byte counts, call counts, node counts, and same-session ratios are treated as the reliable numbers** and are what this report leans on. Every finding marked Confirmed below was independently re-driven live during adversarial verification, not merely re-read from the original claim.

---

## 1. What a user actually waits for

**Cold boot (port 8011, n=3, State C corpus):** FCP median 216ms, DOMContentLoaded median 352ms, load median 363ms — fast on this idle server, and not the number that matters. A synthetic "Home actually usable" metric (last `responseEnd` among Home's own rendering calls) lands at **median 866ms** — roughly 650ms after first paint, because Home's skeleton paints before its five briefing/signals/insights calls have returned.

**The honest number for the app's real audience is the CPU-throttle comparison**, taken adjacent (same session, same load conditions) rather than minutes apart:

| rate | DCL (ms) | FCP (ms) | long tasks (n) | sum(long-task ms) |
|---|---|---|---|---|
| 1x | 390 | 268 | 2 | 122 |
| 4x | 958 (**2.46×**) | 524 (**1.96×**) | 9 (**4.5×**) | 986 (**8.1×**) |
| 6x | 696–822 (**1.8–2.1×**) | 376–420 (**1.4–1.6×**) | 13–14 | 1199–1202 (**~9.8×**) |

At 4× CPU throttle — a plausible proxy for a several-year-old laptop, the population this app is explicitly built for — DOMContentLoaded roughly **doubles** and main-thread jank (long-task time) increases **~8×** relative to unthrottled. This is the app's own 1.66MB of eagerly-parsed/executed JS (§2) becoming a *felt* cost rather than an invisible one: a journalist on real hardware sees the sidebar and top bar for the better part of a second while the browser is still compiling code for 15 tabs they haven't opened. This 4×/6× data could not be repeated a full 3× at every rate (host contention), so treat the ratios, not the absolute ms, as the finding.

**Per-surface switch cost (n=1 per surface, port 8012 — repeats were lost to an OOM kill of that session's own server, confirmed via `dmesg`):** 14 of 16 surfaces show a tight 17–45ms paint delay on first (cold) switch. Two measured outliers stand out:

- **Help** (167k-character user manual): cold open adds **3,755 DOM nodes**, and costs **119ms layout / 654ms total task time** in the measurement window — 5–10× every other surface's numbers (next-highest layout: 19ms; next-highest task: 327ms). This is the direct, measured cost of running the whole manual through a hand-rolled markdown-to-HTML converter into one panel.
- **Indices** (Confirmed live, adversarial pass): opening it fires **~25–26 parallel API calls** (one `GET /api/commodities/<symbol>/prices` per world index/commodity plus `/api/markets/board`), all launched from a single `Promise.all`. `scriptDurationDelta` for this switch was the 2nd-highest of any surface measured.

**Warm revisits genuinely cost almost nothing** for most surfaces: across all measurement sessions, 14 of 15 non-Home surfaces add **zero DOM nodes** and fire **zero API calls beyond the two always-on ambient polls** (`/api/scheduler/status`, `/api/system/network`) on a repeat visit — confirming the app's per-tab `TAB_LOADERS`/`_loaded`-Set architecture works exactly as designed (POSITIVE, load-bearing).

**But this "warm = free" property is narrower than any single report claimed.** One report characterized Insights as "the ONE exception" that re-fetches on revisit. Adversarial re-testing refutes the *uniqueness* of that framing while confirming the underlying mechanism: `startLive(name, {loaderJustRan})` only marks `loaderJustRan:true` on a tab's very first visit; on **every** warm revisit, for **every** tab, that flag is false, so the discount that lets `home`/`insights`/`library` skip their first live-poll tick never applies on a revisit. Live-testing this directly: switching Feed→Home (a warm Home revisit) immediately fired `/api/database/stats`, `/api/scheduler/status`, `/api/briefing`, `/api/insights/trending-windows`, and `/api/signals/alerts` — the identical class of duplicate-tick refetch the original report pinned only on Insights. Library's apparent immunity is coincidental (its tick only refetches when the Storage sub-view is active), not structural. **No report tested Home's own warm-revisit path against this logic, which is why the asymmetry was mis-scoped.**

---

## 2. The bundle and the boot fetch storm

**Compression is off, confirmed by direct header check** (adversarial re-check): `curl -H "Accept-Encoding: gzip" .../app-map.js` returns no `Content-Encoding` header and `Content-Length: 158817` — the full uncompressed size. Locally measured `gzip -9` on the app's own files gives ~70% reduction across the board (app-map.js 158,817→46,106B; app-core.js 117,106→38,007B; index.html 272,860→74,125B). Static assets also carry no `Cache-Control`/`Expires` header — only `Last-Modified`/`ETag` — so the (real, measured) warm-cache win (script transfer 1671KB→0KB, all 25 files served from Chrome's disk cache on reload) rests on heuristic freshness, not an explicit directive.

**No code splitting:** all 25 `<script>` tags are plain (`grep`-confirmed: no `defer`/`async`/`type=module`), all begin downloading within the same 1–2ms window regardless of which of the 16 tabs is about to show. Of the 1664KB decoded script payload, only **305KB (18.4%)** is needed for Home + global chrome; the remaining **1359KB (81.6%)** belongs to per-surface modules a Home-only session never runs a function from.

**The single biggest confirmed defect in this whole audit is a route-shadowing bug on `GET /api/sources`.** Adversarially reproduced live: two independently-registered handlers exist for this path — a bare `GET /api/sources` in `main.py` (`db.query(Source).all()`, ignores every query parameter) and a correct, paginated `GET /api/sources/` (trailing slash) in `source_management.py`. FastAPI routes every actual frontend caller (`app-sources.js`, `app-markets.js` — both call the no-slash form) to the bare handler:

| call | rows returned | bytes |
|---|---|---|
| `GET /api/sources` (no limit) | 3,618 (all) | 714,399 |
| `GET /api/sources?limit=100` | **3,618 — limit silently ignored** | 714,399 |
| `GET /api/sources/` (correct route, never reached by the frontend) | 100 | 34,866 |

This one call is **98.8% of the 723,374 bytes of API traffic Home fetches at boot but never renders** — it exists only to feed a hidden `<select>` in a Settings panel most sessions never open. It scales linearly with catalog size (measured 197.5 bytes/row): a 10× corpus (~36k sources) would ship **~7.1MB** on every single page load. Repeated testing during this audit tripped the endpoint's own `100/hour` rate limiter, returning a genuine `429` with **no `Retry-After` header** (Confirmed, adversarial reproduction: 105 rapid calls → 429 with no `Retry-After` line) — meaning a user who reloads the app a few dozen times an hour is one boot away from `loadSources()` silently failing.

**Correction to an earlier code-audit lead, confirmed by three independent live sessions plus adversarial re-check:** the `article_count` field on this same paginated endpoint is **not** computed via `len(s.articles)` (a full per-article decrypt) as an earlier static audit claimed — it already uses a maintained counter with a single batched `COUNT(*)...GROUP BY` fallback. The lead was stale. The **live, still-unfixed** cost on the same endpoint is a different N+1: `"groups": [g.name for g in s.groups.all()]` runs once per returned row, and `Source.groups` is declared `lazy="dynamic"`. Measured marginal cost between `limit=100` (85.5ms) and `limit=1000` (909.3ms): **≈0.92ms/row**, consistent with an O(n) round-trip pattern. This route isn't on any idle-poll interval — it fires once at boot and once when a batch-ingest picker opens — so it's a load-time cost, not a recurring one.

**Measured saving if fixed:** replacing the boot-time call with a narrow, purpose-built projection (id+name+rss_url of RSS-enabled sources only) and moving it into the existing `TAB_LOADERS` lazy-load pattern (which the app already uses correctly for every *other* surface) would cut Home's non-rendered API bytes by ~714KB — 90% of the entire boot-time API budget — at any corpus size, with zero feature loss.

---

## 3. Idle cost

**Home, foreground/visible, measured over a 45s live network window:** 31 requests, 213,627 bytes → extrapolated **~2,480 req/hr, ~16.3 MiB/hr**. **79% of that byte cost is one endpoint**: `GET /api/briefing`, called 3 times in the window at **56,096 bytes each, byte-for-byte identical every time**. `briefing.py`'s handler reads a server-side cache but has no ETag/If-None-Match/conditional path, so every 15-second poll re-transmits the full cached body even when nothing changed. The same codebase already solved this exact shape of problem elsewhere — `/api/insights/status` is keyed on SQLite's own `PRAGMA data_version`, costing one O(1) probe on an unchanged corpus — so the fix pattern is proven, just not applied here.

**A second, smaller redundancy on the same surface:** `/api/scheduler/status` is fetched independently by two uncoordinated pollers on Home (the app-wide adaptive poll and Home's own live tick), producing roughly double the calls either alone would generate — a duplicate-work pattern the same codebase's comments elsewhere explicitly hunt down and fix, that missed this particular overlap.

**Every timer that should stop when hidden, does — with one confirmed exception.** `document.hidden` dispatched live: Home's requests drop from 31/45s to **0/20s**, and resume with an immediate catch-up burst on visibility restore. Settings (a tab absent from the surface-specific `LIVE` poller registry) shows exactly the two global ambient polls and nothing else over 30s idle — confirming the majority of the 16 surfaces cost zero idle traffic by construction. **The one surface that does not go to zero hidden is the standalone `/tasks` task-manager page** — opened in its own browser tab, whose own design comment states its intent is to "stay parked on the desktop" — measured at 30 requests/45s visible, dropping only to **9 requests/20s hidden** (~1,620 req/hr, ~1.2 MiB/hr, indefinitely). The fix is trivial: the file already has a `document.hidden` ternary six lines away from the unguarded interval, in the exact same file.

**Server-side cost of the idle-polled endpoints** (curl, warm connection, 3 repeats): all single-digit-to-low-double-digit milliseconds except `/api/llm/health` (0.55–0.84s across all 3 repeats) and `/api/wiki/status` (0.38–0.46s) — consistently the two slowest, suggesting a real per-call probe (`resolve_backend()`) rather than sandbox noise, though this was not independently confirmed with server-side instrumentation. Idle-polled endpoints that touch the DB are largely cheap or cached (`/api/insights/status` uses the same `PRAGMA data_version` cache-key mentioned above); `/api/scheduler/activity` is the one that genuinely queries and is polled from three independent idle call sites at once.

**Recommendation ranking:** (1) an ETag or `PRAGMA data_version`-style cache on `/api/briefing` — collapses ~79% of Home's idle bytes on the (common) no-change case; (2) guard the `/tasks` page's 15s interval with `document.hidden`, mirroring code six lines away in the same file; (3) coalesce the duplicate `/api/scheduler/status` fetch on Home.

---

## 4. Memory and long-session behaviour

**No confirmed memory leak.** Adversarial re-verification independently reproduced this on a separate port using correct methodology (forced `HeapProfiler.collectGarbage` ×2 before each measurement, comparing round-over-round rather than raw deltas): across a 3-round, 16-tab churn, DOM nodes went 5,152→10,162→10,187 (flat after round 1, +0.25% in round 3) and heap went 6.29→7.44→7.45MB (flat after round 1, +0.1%). This corroborates the original 80-switch/5-round finding (DOM nodes flat at 12,957 for 3 consecutive rounds, heap within 0.03MB, net listeners flat at 217, `removeEventListener` called 0 times, `MutationObserver` construction pinned at exactly 2 across all 80 switches).

A CDP heap-snapshot scan for Chrome's `"Detached <ClassName>"` convention (orphaned DOM subtrees invisible to a plain node count) found **zero** detached instances among 242,793 heap nodes after the full churn — a coarse class-name proxy, not a full retainer-path parse, but a clean zero under that method is a meaningful negative result.

**Canvas/chart churn** (Insights→Observatory→Home ×7): `canvasEls` and cumulative `getContext()` calls both pinned at exactly 1 across all 7 iterations — Observatory's night-sky canvas acquires its 2D context once and reuses it, the correct non-leaking pattern.

**The one open lead, explicitly not confirmed:** a single 5-minute idle run on Home showed a small heap rise, 1.86MB→2.00MB (+0.14MB, +7.5%), after one forced GC at the end, alongside negligible DOM/listener movement (+1 node, +1 listener). This is the only metric across the whole memory audit that moved in a leak-consistent direction without also plateauing — but it is a **single run**, not the project's own 3×-repeat standard for noisy numbers (host memory instability prevented a repeat). Reported as an unconfirmed lead for a follow-up session, not a defect.

---

## 5. First launch — the real flow, measured, in English and in Arabic

**Environment caveat, stated plainly:** both assigned "fresh install" ports (8020, 8021) were already `unlocked` when the session began — one `unlocked-encrypted`, one `unlocked-plaintext` — with no in-app relock/log-out affordance and no permission to restart the shared server. The literal server-authoritative fresh-install flow (`lock-state == "fresh"`) could not be driven end-to-end; screens were rendered by route-faking only the *initial* `GET /api/system/lock-state` response so the app's own unmodified client code renders the real screens, while every subsequent call (legal docs/consent, create-db, unlock) hit the real live server.

**Reading burden, measured (English):** ~5,063 words of mandatory reading before a workable Home — **97% of it (4,924 words) is the legal document**, not the security warning (111 words for the passphrase-creation screen).

**A genuine surprise, verified live rather than assumed from static code:** the no-recovery passphrase warning was suspected to be untranslated (the view's markup carries no `data-i18n`/`t()` calls at all). Live testing in Arabic and French disproved this — `i18n.js` translates by exact text-node match across the whole `<body>`, independent of `data-i18n` attributes, and all 20 strings on the create-passphrase screen, including the no-recovery sentence, render correctly translated (full RTL for Arabic).

**A real, live-reproduced RTL bidi defect:** in the Arabic legal document, the underlying text `تاريخ السريان: 2026-07-16` (correct ISO order, confirmed via `textContent` and the raw API response) renders on screen as **`16-07-2026`** — day and year visually swapped, because the hyphen-joined date has no bidi isolate and the neutral hyphens inherit the surrounding RTL direction. This is a live instance of a defect class the project's own lessons file already names, occurring in the one document every Arabic-locale user must accept.

**Wrong-passphrase retries — genuinely real, not simulated** (a route-shadow-adjacent surprise: the unlock endpoint's existence check reads the on-disk file header, not the in-memory lock flag, so a wrong passphrase against a really-encrypted file genuinely fails to decrypt). Three consecutive real attempts against the live server: 1505/1712/1623ms, flat — no growth, no backoff — matching the maintainer's documented no-rate-limiting policy exactly. Minor gap: the password field is not cleared or refocused after a failure.

**The post-unlock onboarding wizard** (0-article trigger) was fully, genuinely reachable and driven three ways, all with zero console errors and no orphaned state: declined at the network-consent step ("Stay offline"), closed early via ×, and interrupted by a raw mid-flow reload (the wizard restarts at step 1, but a real server-side setting change already made survives and reflects correctly on reopen).

---

## 6. Empty states across all 16 surfaces

**"Home must never go blank-and-silent" genuinely generalizes to all 16 surfaces**, not just Home. On a zero-article, catalog-seeded corpus, every surface (home, feed, insights, observatory, timemap, law, agenda, indices, markets, library, settings, search, analyze, custody, integrity, help) plus 8 Insights and 13 Analyze subtabs rendered a specific, method+caveat-consistent explanation of what's missing — never a blank div — with **zero console errors, zero uncaught exceptions, zero failed requests** across all 24 surfaces/subtabs checked. This directly answers, and refutes, the assignment's implicit hypothesis that the discipline stops at Home. **POSITIVE, load-bearing.**

One real interaction defect surfaced during this sweep rather than in the failure-state testing proper: a genuine first-run native `<dialog id="guide-wizard">` correctly blocks real clicks elsewhere on the page (proven by a real Playwright click timing out with "intercepts pointer events" while the modal was open) — expected, correct modal behavior, but it meant an initial pass using the app's own `showTab()` JS function (which bypasses modal inertness) had to be redone with real clicks to get a trustworthy sweep.

---

## 7. Failure states — the honesty test

This is where the audit's strongest confirmed findings live, because they are binary, corpus-state-independent facts (a specific string either renders or it doesn't) rather than noisy timings.

**Confirmed, and strengthened during adversarial verification: malformed API responses render as the legitimate empty-corpus message, not an error — on a *populated* corpus, not just an empty one.** The original claim tested this against an empty catalog; adversarial re-testing repeated it against **453 real articles and 3,618 real sources**. Route-intercepting `/api/database/stats` and `/api/briefing` to return invalid JSON with HTTP 200: Home's stats strip displays **"Your library is empty — head to Collect to gather your first material"** and the briefing panel shows **"No Leads yet — that's expected on a young corpus"** — both with zero uncaught exceptions and zero visual distinction from a genuinely empty corpus, while 453 articles and 3,618 sources actually exist. Root cause confirmed in the shared `api()` wrapper: `try { data = JSON.parse(text) } catch { data = text }` — a parse failure never throws, it hands the raw string to the renderer, which reads `undefined` properties and falls through to the empty-state branch. There is no toast, no status line, nothing distinguishing this from success. **This is the sharpest violation of "degrade loudly" found in the whole audit**: the app doesn't fail quietly, it actively asserts a false fact.

**Confirmed, exact string match:** a malformed `/api/articles` response (`[]` instead of `{total, results}`) produces a toast reading verbatim **"Search failed: Cannot read properties of undefined (reading 'length')"** — a raw V8 `TypeError`, not a message written for users, and one that cannot be translated by construction since it's engine-generated.

**Confirmed by code read:** Markets' "Configure data sources" `<select>` has a literal `catch (e) { /* leave as-is */ }` on a `/api/sources` 500, and the `<select>` carries zero default options — it silently renders as a permanently empty dropdown with no error text distinguishing "server down" from "you have zero sources."

**Confirmed by code read:** two error strings bypass the ×12-locale rule entirely. `app-home.js`'s briefing-load catch sets a hardcoded English string (`"Briefing unavailable right now."`) with no `t()` wrapper at all; the Feed catch's fallback `(e && e.message) || t("The feed could not load.")` makes its own translated string dead code, because the raw (always-English) server-detail message is always truthy and wins. Screenshotted live in Arabic: every surrounding label on the page is correctly RTL Arabic; these three error strings sit as untranslated, unindicated left-to-right English fragments inside it.

**A held-open request never escalates.** With `/api/briefing` intercepted and never fulfilled, Home's "Loading the briefing…" text is unchanged at 1s, 3s, 8s, 15s, and 25s — no spinner animation, no elapsed-time cue, no client-side timeout (`api()` has no `AbortController` anywhere). A genuinely hung backend is visually indistinguishable at 2 seconds from 2 minutes.

**Under simulated slow-3G**, cold boot shows an honest partial-load state at ~6.3s — sidebar rendered, status pill reading "checking…", briefing panel correctly reading "Loading the briefing…" — never fake or blank content. **POSITIVE.**

---

## 8. Dialogs, overlays and focus behaviour

**The most consequential finding in the entire audit — Confirmed decisively, adversarially reproduced.** The external-link guard's native `confirm()` runs on the capture phase, **before** `openLinkPreview()` — a direct architectural consequence of `_externalLinkGuard` being registered `true` (capture) on `document`, which necessarily fires ahead of the target anchor's own inline `onclick`. Reproduced live: **dismissing** the guard's popup (the safe-sounding choice — "Cancel" on "this leaves the app and contacts an outside server") leaves `document.getElementById('link-preview').open === false` — nothing happens at all, and invariant #6's promised local-preview-first behavior is silently skipped. **Accepting** the popup (ostensibly agreeing to leave the app) is what actually opens the local preview — and the real external navigation is still blocked afterward by the anchor's own `preventDefault()`. The popup asks exactly the wrong question for this control: users who read the warning and act cautiously get nothing; users who click through get the safety net.

**Confirmed, pixel-close match to the original measurement:** a flip-card's back face overflows its fixed 292px height by **2.2×** (`scrollHeight=632` vs `clientHeight=288`), pushing the primary "Open corpus" CTA **219px below the visible box** by default. **Severity correction from adversarial verification:** the original claim framed this as the action being *hidden* with "no scrollbar." A genuine `overflow-y:auto` container with a custom scrollbar rule does exist in the CSS, and programmatically scrolling the container does reveal the CTA cleanly — so the content is not lost, only **undiscoverable without knowing to scroll a flipped card face**, and whether a real browser paints a visible scrollbar affordance here could not be confirmed in headless Chromium. Net: still a real P1-adjacent UX defect (a primary action off-screen by default with no visible cue), but "the action is present but requires an unindicated scroll gesture," not "the action is lost."

**Confirmed, exact ratio match:** the card-back's own "⟲ Back" button (`.lead-flip-hint.back`) fails WCAG AA badly and consistently — contrast ratio **1.04:1** in the default theme, 1.96:1 in a second theme tested live (need 4.5:1) — precisely the control a user needs to find in order to navigate off the overflowing back face.

**Confirmed, a real invariant regression.** The task-manager window documented at length in the project's own ledger (`#vitals-pop`, with Active/Queue/Schedule/Coverage/System tabs) is unreachable: `toggleVitals()` — the only function that shows it — has no unconditional open call site anywhere; every caller closes it (Escape, outside-click, its own Close button). The actually-reachable control (`#tm-open`) instead opens a standalone `/tasks` browser tab serving a different file (`taskmanager.html`) whose real panel set, confirmed by a live fetch, is exactly **Processes / Performance / Queue / Schedule / History (Sessions) — no Coverage, no System.** The per-tag scraping-reach Coverage feature the ledger documents as shipped and load-bearing exists only in orphaned markup no control opens.

**`#corpus-win` confirmed genuinely dead code** — no `onclick` reference anywhere except its own Close button, and forced open (purely to document) renders visibly broken/collapsed markup consistent with unmaintained code — matching, and verifying, the maintainer's own note that it's pending a browser-verified deletion pass.

**Positive findings held up under adversarial scrutiny:** dialogs correctly survive a live theme switch and a live language switch while open (full repaint / full retranslation, dialog stays open); invariant #17's hover-bubble convention works exactly as designed, including auto-marking a dynamically-injected element within 500ms via `MutationObserver` with zero explicit registration; `#folder-picker` correctly stacks over `#ux-export` with Escape closing only the top dialog.

**A newly-found structural gap, missed by every original report:** the "You're offline" coachmark's placement guard (`_placeCoach()`) only checks against 4 named top-bar buttons — it has no concept of arbitrary page content below it. Adversarially confirmed geometrically: the coach box fully overlaps the Analyze window's Sources and Competitive subtab buttons, and a real Playwright click on those subtabs times out with Playwright's own diagnostic naming the coach's subtree as intercepting pointer events. The guard's "safe" placement is only safe *for the 4 buttons it was written to protect* — it blindly overlaps whatever unrelated content happens to render in that same screen region.

---

## 9. Consent gates

Ten distinct gated actions were exercised end-to-end (click → popup captured verbatim → decline → re-verify offline + no side effect), four of them repeated in French, across six separate browser sessions. **Zero non-loopback requests were observed in any session, on any decline.** Two direct backend-bypass tests (loopback-only, never left the machine) sharpened the picture:

- `PUT /api/custody/settings {"anchoring_mode":"opentimestamps"}` with no consent flag, called directly, **Confirmed live**: HTTP 400 with a fully-named refusal citing the recurring, IP-revealing nature of the egress. The server-side backstop behind the client-side gate genuinely works — a strong positive, and it sharpens the next finding by showing the pattern *can* be applied.
- `POST /api/wiki/pages`, called directly while offline, **Confirmed live**: HTTP 200, and it created a real watchlist row. Code confirms this specific endpoint is a pure local DB write with no network capability and no consent/kill-switch check of its own — so nothing leaked — but it means the client-side `ensureOnline()` gate is the *only* thing standing between a caller and the write, unlike the OTS endpoint above. This is the exact asymmetry invariant #14f was written to close, just not yet generalized here.
- `GET /api/wiki/dumps/sizes` while offline, **Confirmed live**: returns `reason:"airplane"` per edition — never a bare failure — confirming the #14e "name the kill-switch refusal as such" corollary holds server-side.

**Confirmed, and the second-most consequential interaction finding in the audit: the airplane-toggle button is functionally dead for ~5 seconds after every boot, due to a request-queue race, and independently re-measured three times.** `#net-toggle`'s only state signal — its `off` CSS class, set exclusively by the first resolved `GET /api/system/network` — arrives a median of **4885–4941ms** after `domcontentloaded` in the original measurement, and **4837–4934ms** in an independent adversarial re-measurement: a tight, load-independent spread, not sandbox jitter. This call is one of ~30 competing boot-time API calls (§2) and is evidently queued behind the others. Reproduced live: clicking the toggle at ~700ms after page settle leaves `#net-consent.open === false` — the click is silently swallowed, taking the "already offline, no-op" branch instead of opening the consent dialog, because `goingOnline = btn.classList.contains("off")` reads false during the race window. This never bypasses consent (the failure mode is a no-op, not an unconsented transition) but it sits directly on top of the app's most safety-critical control, at exactly the moment — right after the page paints — a real user is most likely to click it. It is a direct, rendered consequence of the eager-boot finding in §2: bundle cost isn't only wasted bytes, it measurably delays the correctness of a top-bar safety control.

**Confirmed, exact string match: a French consent dialog mixes languages.** The native `confirm()` behind "Set up local AI" reads verbatim: `"Set up local AI on this machine?\n\n• Install Ollama\n\nCe téléchargement passe par le clearnet — pas par Tor."` — title and step label stayed English, only the trailing disclosure sentence was translated. Root cause confirmed: the title string is absent from the French locale file (silent fallback to English); the step labels are never passed through the translation function at all. This sits inside a consent moment specifically, not decorative chrome, making it a direct violation of the ×12-locale non-negotiable at the worst possible place for it.

**Judgment on consent as a UX system:** mostly one learnable pattern, with one visible seam. Eight of ten gated actions share a single, well-designed, reused dialog (`#net-consent`) that lists real local interface addresses, never a public-IP echo, and defaults focus to the safe choice. Where it fractures is three places where a plain, unstyled native `confirm()` gates *ahead of* the styled dialog (dump-size warning, OpenTimestamps recurrence warning, AI-setup plan preview) — these cannot carry theme, RTL layout, or the hover-bubble convention, and it is precisely one of these three where the untranslated-French defect above was found. Routing those three through the existing styled components would put every consent string through the one translation pipeline already known to be complete, closing this class of gap by construction — recorded as an IDEA, not a defect, since it proposes consolidating presentation, never removing a question.

---

## 10. Keyboard and the command palette

The command palette opens via its trigger, moves focus to its input, filters live on typing, and closes on Escape; probing its DOM confirms `#vitals-pop` (the dead task-manager markup from §8) is present but permanently hidden, consistent with the dead-code finding above. No dedicated keyboard-navigation battery (tab order, arrow-key roving tabindex across `ooSubtabs`, focus trap correctness inside open dialogs beyond Escape) was completed in any of the five sessions this synthesis draws from — this is a genuine gap in the underlying audit coverage, not a "looks fine."

---

## 11. Ranked remediation — measured benefit-to-effort

1. **Fix the `/api/sources` route shadow** (§2). Highest measured ROI: recovers 714KB (90%) of Home's non-rendered boot-API bytes at any corpus size, on a route already flagged as hitting its own rate limiter in normal use. Single-change fix (route rename or a narrow projection endpoint).
2. **Stop malformed JSON from rendering as "empty corpus"** (§7, DEG-1). The single sharpest honesty violation confirmed against a populated corpus. Fix is narrow: make a JSON-parse failure throw instead of degrading to a raw string the renderers coerce into "nothing here."
3. **Guard `/tasks`'s 15s interval with `document.hidden`** (§3). The only surface in the entire idle-cost audit that doesn't reach zero when backgrounded, despite its own documented design intent being to sit backgrounded — and the fix pattern already exists six lines away in the same file.
4. **Reorder the external-link guard behind `openLinkPreview()`** (§8). Currently the guard's capture-phase `confirm()` makes "Cancel" (the safe-sounding choice) silently skip the local-preview safety net the app explicitly promises. This is a live inversion of invariant #6, not a cosmetic issue.
5. **Cache `/api/briefing` with the `PRAGMA data_version` pattern already used by `/api/insights/status`** (§3). Collapses ~79% of Home's idle bandwidth on the common no-change case with a proven, in-codebase pattern.
6. **Fix the airplane-toggle boot race** (§9). A ~5-second window where the app's most safety-relevant control silently swallows clicks — a direct, measured consequence of the eager-boot problem in §2, so fixing §2's deferred-loading proposal (moving non-essential boot calls out of the critical path) would likely shrink this window as a side effect; independently, `toggleNetwork()` could read a definitive server-confirmed state rather than a CSS class that isn't guaranteed painted yet.
7. **Add `defer` to all 25 `<script>` tags** (§2). Zero functional risk (scripts already run after boot, not on their own parse); should measurably improve FCP, and especially the 4×/6× throttled numbers in §1 where script execution is the dominant cost.
8. **Wrap the two untranslated Home error strings in `t()`, and fix the French "Set up local AI" key** (§7, §9). Both are small, isolated string-level fixes that close confirmed, live, ×12-locale non-negotiable violations — one in an error path, one inside a consent moment.
9. **Increase the flip-card back's default visible height, or add a scroll-affordance cue** (§8). The primary "Open corpus" CTA is present but undiscoverable 219px below the fold with no visible indicator that more content exists; fix the `.lead-flip-hint.back` contrast (1.04:1) at the same time since it's the control needed to escape the overflow.
10. **Lazy-inject each `app-<surface>.js` on first `TAB_LOADERS` fire rather than at parse time** (§2). Middle-step fix (no ES-module rewrite needed) that would defer 81.6% of script bytes for a Home-only session — the single largest remaining structural win, ranked last only because it's the most involved to implement safely given 394 inline `on*=` handlers depending on the current global scope.

---

## 12. Refuted / unverified

- **"Insights is the ONE exception that re-fetches on warm revisit"** — refuted as stated. The underlying mechanism (`loaderJustRan` never true on a revisit) applies to every tab in the `LIVE` registry, including Home, which was never tested for this in the original claim. Insights' asymmetry is real but not unique; Library's apparent immunity is coincidental, not structural. See §1.
- **"No scrollbar renders... hides the primary action" (flip-card overflow)** — severity corrected, not refuted. A genuine `overflow-y:auto` scroll container exists with a custom scrollbar rule; the content is reachable by scroll, just undiscoverable by default. See §8.
- **"Very likely to produce a visible stutter" (Help's per-keystroke search rebuild)** — the underlying defect (full-document rebuild + full tree-walk on every keystroke, no debounce) is confirmed by code read, but the dramatic framing was never backed by a live measurement in the original reports. A direct measurement obtained during adversarial verification found 13–20ms per call on an already-loaded sandbox — real and worth fixing (borderline over a frame budget), but not a confirmed visible stutter absent an actual CPU-throttled measurement, which no session obtained.
- **Time-to-usable-Home during real first-launch passphrase creation** — not measured on either assigned "fresh" port, since both were already unlocked; the reported 1.5–1.7s figure is a real, live measurement of an *adjacent* code path (wrong-passphrase KDF verification on the same live process), not the create-db path itself. Labelled as inference, not measurement, throughout.
- **10×/100× corpus extrapolations for `/api/sources`** (§2) — stated with explicit method and confidence: the byte-scaling figure is solid (linear by construction from a flat per-row size), the time-scaling figure for the paginated endpoint's N+1 assumes constant per-row cost at scale, which was not verified against an actual larger corpus (out of scope — would have required writing into the shared data directory).
- **Not reached at all, across every session:** a full keyboard-navigation/focus-trap battery beyond Escape-closes-dialogs (§10); the 4×/6× CPU-throttle comparison for any of the 16 individual surface switches (only the aggregate boot comparison in §1 was obtained before that session's server was OOM-killed); a true server-fresh (`lock-state=="fresh"`) create-passphrase flow driven live rather than via route-faked initial state; touch long-press behavior for the hover-bubble convention; and a repeated (3×) 5-minute idle-heap run to confirm or refute the one unconfirmed +0.14MB lead in §4.