# Field-Test Ledger — 2026-06-15 session

Continues the 2026-06-14 intake (`../field-test-2026-06-14/`). **Mode: this session
began as intake + implementation, then the maintainer switched to CAPTURE-ONLY
mid-session (07:55)** — a parallel session owns the `0.09` implementation. Items
**A–B** were already implemented + pushed (draft **PR #162**) before the switch;
**Items C onward are capture-only** — verbatim observation + mapping to existing
rulings/docs + code grounding + what is [PLANNED]/[NEW], with **no code changes**.
The consolidated baseline + numbered question list is rendered on "compile", like
2026-06-14.

Legend: [PLANNED] already ruled · [NEW] net-new · ✅ shipped here · ⏭ remaining.

---

## Item A — Installer must not prompt for a passphrase; defer DB init to first launch; auto-launch the app  [PLANNED — Item 1 / Group D]  ✅

**Verbatim (07:11):** "the terminal installer still asks for a passphrase. I'd
like the installer not to ask this. I think it's linked to database
initialization. Can't the database be initialized later? This could be done
during the app's launch. … I'd like the app to launch automatically when
(promptless) the installation ends. Remember the order of the first
initialization screen: ask for language, then a screen with terms and
conditions, then ask for passphrase."

**Maps to:** field-test-2026-06-14 **Item 1** (installer no-DB-init / no-passphrase
+ auto-launch) and **Item 2** (first-launch wizard order language → T&C →
passphrase); BACKLOG_GROUPED **Group D**; CLAUDE.md "INSTALL-FLOW NEXT SLICE".
Was ruled, not yet shipped.

**✅ Shipped this session (`install.sh`):**
- `init_database()` no longer prompts. It initialises **only** when the choice is
  already made — an existing store, or an explicit headless env choice
  (`OO_DB_PASSPHRASE` / `OO_DB_PLAINTEXT`, handled by `_try_db_init`). In every
  other case it **defers silently** to the app's in-browser first-launch setup.
  The interactive `_prompt_db_protection` function was removed entirely (the env
  vars are the only headless fallback, per the ruling).
- `maybe_launch()` ends an interactive install **inside the running app**: it
  `exec`s `scripts/launch.sh console` (starts the loopback server, waits for
  health, opens the browser at http://127.0.0.1:8000). Interactive only — never
  `--unattended` / `--appvm` / CI / `OO_SKIP_PIP`; opt out with `OO_AUTOLAUNCH=0`.
  Zero-network / airplane-mode boot preserved.
- Deferral is safe by construction: encryption is on by default, a blind init on a
  fresh store would crash (field-tested 2026-06-12), and the deferred-startup path
  seeds sources at the first unlocked boot. `/api/system/create-db` + the in-app
  `/unlock` create flow already own the passphrase choice.

**Verified:** `bash -n` clean; `tests/test_installer.py` green (incl. the
curl|bash no-leak path and unattended-launcher tests); full suite 1165 passed.

**⏭ Remaining (Item 2, larger — own slice):** the first-launch **wizard** with the
ruled order **language → Terms & Conditions (accept) → passphrase**. Wizard slice 1
(language + finish) shipped #150; the **T&C step + authored ×12 T&C content** and
the **encryption-choice step** are the remaining wizard slices. The installer now
hands straight to that in-app setup, so the order the maintainer wants is owned by
the app, not the terminal.

---

## Item B — One search entry (the top one); icon-only, no "Ctrl K"; translate the hover; Enter → analysis window; remove the Search sidebar tab  [PLANNED — Group E/F + "SEARCH = ONE CENTRAL ANALYTICAL TOOL"]  partly ✅

**Verbatim (07:19):** "The app's UI still has two search entries. I'd prefer that
there is only one. The top one. … this top search should be filled with text such
as 'Search everything - data, tools, actions, docs…' it takes too much space.
Remove the Ctrl K information. Just a search icon. Instead of having a bubble while
hovering … saying 'command palette' (not translated by the way!), you should
probably put there … (ie. Search everything - articles, dates, locations,
settings, etc.). Whatever the user searches, clicking 'enter' opens a search
related window with all the agreed subtabs … advanced search tools and the list of
results. There should not be a search button in the tabs. The top icon will
suffice."

**Maps to:** BACKLOG_GROUPED **Group E** (minimal top bar; remove visible "Ctrl K";
bigger always-on search) + **Group F** (Enter → corpus-of-articles analysis window
with sub-tabs + Advanced-search tab — "the single most-requested piece"); CLAUDE.md
"SEARCH = ONE CENTRAL ANALYTICAL TOOL" and "UI SHELL REDESIGN §4/§5".

**✅ Shipped this session (chrome, the safe/ungated part):**
- Removed the visible **`Ctrl K`** badge from the top omnibar (the Ctrl/⌘-K
  shortcut still works; it's just no longer shown).
- The omnibar **hover bubble** (invariant #17 `#oo-tip`, fed by the translated
  `title`) was **untranslated English "Command palette"**. Replaced with
  **"Search everything — articles, dates, locations, settings, etc."**, keyed and
  translated ×12 (RTL Arabic included; AI-drafted, flagged for native review).
  The omnibar `aria-label` now matches.
- Killed the **last** untranslated "Command palette" string: the palette dialog's
  `aria-label` is now the keyed **"Search everything"** ×12. `--audit-chrome` is
  clean of "Command palette"; i18n coverage stays 100% (610 keys ×12).
- The visible placeholder already read "Search everything — data, tools, actions,
  docs…" (keyed) — kept, so the surface layers a short placeholder + a longer hover.

**Verified:** `node --check` of the inline script block OK; all 12 locales
JSON-valid; i18n `--min 100` green; `--audit-chrome` clean; full suite 1165 passed.

**⏭ Remaining (the flagship — own dedicated PR, GATED):**
1. **Enter → the analysis window** with the agreed sub-tabs (keyword · mindmap ·
   link · source · When/Where/Who · sentiment · related) **+ the Advanced-search
   tab** (filters, sort, dates, the result list). This is the Group F flagship /
   keystone #4; partially built (palette T13 s1; keyword→corpus window T10 s1 =
   Trend/Articles/Links only).
2. **Remove the Search sidebar tab** (`data-tab="search"`) so only the top icon
   remains. **This is the "two entries → one" the maintainer wants**, but it is
   **gated by the project's own rule**: the Search tab is removed only **after** the
   Enter→window absorbs **every** Search-tab capability — Boolean query, Source /
   Language / From / To filters, Export CSV/JSON, **Methods appendix**, **Synthesize
   results**, **Export signed evidence** ("never silently lose a tool", the Desk
   lesson). Those live in `#tab-search` today. So the tab stays until (1) lands;
   removing it now would drop signed-evidence export and the methods appendix.

**Recommendation:** do (1)+(2) as the **next** PR (the promoted Group F flagship);
the chrome shipped here is the down-payment.

---

## Item C — Agenda rework: maximize space; view BUTTONS (+ Week view); category dropdown → colored event TAGS; country FLAGS  [mostly NEW · Week view PLANNED]  ⏭ capture-only

**Verbatim (07:55):** "The agenda should take as much space as possible in the
screen. Instead of having a drop down menu to switch between month and list views,
show actual buttons. Add a week (7 days) view. Replace the drop down category menu
by events tags, give them distinct colors. There will be more tags coming, such as
'religious'." **+ follow-up (07:55):** "Concerning the list of countries, can't you
show a list of flags?"

**Where (`src/static/index.html`):** the Agenda tab `<section class="panel">` at
**1039–1070**; the controls row at **1046–1059**:
- `#agenda-view` `<select>` (Month/List) — **1047–1048**
- `#agenda-cat` `<select>` (Category: all/civic/political/economic/technology) — **1049–1051**
- `#agenda-country` `<select>` (dynamic: "all" + JS-filled) — **1052**
- `#agenda-tag` `<select>` (dynamic: "all" + JS-filled) — **1053**
- month bar + `#agenda-month` / `#agenda-day` / `#agenda-list` render targets — **1060–1069**

**Maps to:** invariant **#13** (Agenda data-first, month-grid default) + the
CLAUDE.md **"AGENDA CONTENT"** queue, which already lists **"the remaining views
(week/trimester/semester/year/decade)"** and **"PRELOADED … religious calendars"**.
BACKLOG_GROUPED has **no Agenda group** — these extend the CLAUDE.md agenda queue
(candidate for a new backlog group at "compile"). Colored-chip convention already
exists for **Sources tag-selection** ("multi-tag AND-combination, colored chips" —
the corpora entry). Country substrate = **`src/catalog/countries.py`** (ISO-2
canonical, from the de-US-centring batch).

Sub-parts:
- **(a) [NEW] Maximize screen space for the Agenda.** It renders inside a standard
  `.panel` (padding + the app's content max-width). Ask = a full-bleed / expanded
  layout so the calendar uses the viewport. Design within invariant #13; the month
  grid stays the primary surface.
- **(b) [NEW] View switch → real BUTTONS, not a `<select>`.** Replace `#agenda-view`
  (1047) with a segmented button group (Month · Week · List). Candidate: the
  universal subtab grammar (`ooSubtabs`) or a simple button row; labels keyed ×12
  from the start (see **Item D** — must not repeat the unkeyed-option mistake).
- **(c) [PLANNED] Add a WEEK (7-day) view.** New render mode + its button — already
  in the agenda-content "remaining views" queue. Needs a 7-day grid renderer + week
  navigation (reuse the `agMonthShift`/`agMonthToday` nav pattern, 1061–1064).
- **(d) [NEW; the tag taxonomy is PLANNED] Category dropdown → colored event TAG
  chips.** Replace `#agenda-cat` (1049) with clickable tag chips, each a distinct
  color; the taxonomy is **extensible** ("religious" coming — ties to the queued
  religious-calendars work). Clarify category-vs-tag: there is ALSO a `#agenda-tag`
  select (1053); the rework should converge them into one colored-tag filter. Reuse
  the Sources colored-chip convention; colors must be distinguishable (ideally
  colorblind-safe); chip labels keyed ×12.
- **(e) [NEW] Country picker shows FLAGS.** `#agenda-country` (1052) — show flags
  (with or instead of names). Generalizes to country pickers app-wide. Substrate:
  ISO-2 from `countries.py` → derive a flag (regional-indicator emoji = offline,
  zero-asset; or a bundled SVG set). **Honesty caveat (carry the invariant-#15
  spirit, flags ≠ identity):** a flag is a visual convention — disputed /
  sub-national / multi-country / no-clean-flag entities exist, and emoji flags
  render inconsistently on some OSes; keep the country NAME reachable (accessible
  label / hover) so a flag never becomes the sole identifier. Verify rendering or
  bundle assets.

**⏭ Remaining:** all of C is unbuilt (capture-only). Cross-links to **Item D**:
every new control label here (Week, the view buttons, tag chips, "all") must be
keyed ×12 from the start. Open design questions (hold for "compile"): the exact
button view-set now (Month/Week/List) vs where trimester/semester/year/decade live;
whether tags REPLACE or COMPLEMENT the country/group filters; flags-with-names vs
flags-only.

---

## Item D — App-wide: dropdown `<option>` labels are not translated (66 of 91 unkeyed)  [PLANNED — i18n burn-down]  ⏭ capture-only

**Verbatim (07:55):** "It seems that none of the drop down menus have been
translated. Check app wide."

**Checked app-wide — verified facts (not a feeling):**
- **The engine CAN translate option text.** `i18n.js` `apply()` walks a `SHOW_TEXT`
  TreeWalker (**i18n.js:71**) and translates any text node whose trimmed value
  exactly matches a locale key; its `SKIP` set (**i18n.js:23** = SCRIPT / STYLE /
  TEXTAREA / CODE / PRE) **does not include OPTION/SELECT**. So `<option>` labels
  are translatable by construction — **not** an engine limitation.
- **Root cause = a coverage gap.** Most option labels were never keyed in `en.json`
  (+11 locales). Inventory (read-only audit of `index.html` × `en.json`): **91
  static option labels; 13 keyed; 66 UNKEYED;** the 12 `#oo-lang-select` native
  names are correctly **not** translated (invariant #15).
- **Case-sensitivity trap (same words keyed inconsistently):** `#agenda-group`
  **"month"** is unkeyed while `#agenda-view` **"Month"** is keyed; `#mkt-scale`
  **"1 month"/"6 months"** are unkeyed while `#tmap-window` **"± 1 month"/"± 2
  months"** are keyed. Same vocabulary, opposite outcomes → dropdowns look half- or
  never-translated.
- **Why a "100%" i18n badge coexists with untranslated dropdowns:** the CI gate
  `--min 100` (`i18n_report.py`) only checks that locales translate every
  **existing** `en.json` key — NOT that every chrome string is keyed. The unkeyed
  option labels live in the separate, **non-blocking** `--audit-chrome`
  "untranslatable tail" (~423 strings). `_ChromeExtractor` (**i18n_report.py:45**)
  also doesn't skip OPTION, so these ARE measured there — known-untranslatable, just
  never keyed.
- **Possible secondary caveat (UNVERIFIED headlessly):** whether mutating an
  `<option>` text node via `nodeValue` re-renders the **closed** `<select>` display
  in every target browser. The keyed ones (agenda-view Month/List, `mm-window`,
  `fetch-mode`) presumably do translate in the live app (shipped, never flagged), so
  this is likely fine — **verify in-browser** when implementing; if a keyed option
  does NOT visibly translate, there is an `<option>`-rendering bug on top of the
  coverage gap.
- **Dynamic selects** (`#agenda-country`, `#mkt-source`, `#ing-source`, wiki
  editions…) build options in JS: their CONTROL labels ("all"/"any") need
  `OOI18N.t()` at build time; data labels (source names, editions) stay English by
  design.

**The 66 unkeyed, by select (control labels; data/native excluded):** `anno-kind`
(ownership, leaning, coordination-tag, transparency-fact, correction, note);
`agenda-cat` (all, civic, political, economic, technology); `agenda-group` (month,
calendar, country); `mkt-scale` (1 month, 6 months, 1 year, 5 years, All);
`trd-kind` & `map-kind` (all, terms, entities, people, orgs, places); `cs-by`
(domain, exact link); `fam-kind` (entities, people, orgs, places, all);
`tmap-window` (all of time, ± 2000/100/25/5 yrs, ± 1 yr); `tmap-speed`
(0.5× / 1× / 2× / 4×); `set-theme` (Dark, Light); `sch-mode` (RSS feeds, Recursive
crawl, Markets (price rules), Wikipedia (watched pages)); `bi-enabled` &
`src-enabled` (all/any, enabled, disabled); `feeddir-kind` (all); plus the JS-built
control labels on the dynamic selects.

**Maps to:** CLAUDE.md **"i18n & LANGUAGE UX"** (the elevated `--audit-chrome`
burn-down) + BACKLOG_GROUPED **Group D "Card strings into i18n"** (sibling).
Invariant **#15** stands (native names stay English-by-design).

**⏭ Fix shape (for the implementing session):** (1) key the ~66 control option
labels ×12 (skip data + native-by-design), **normalizing the case mismatches** so
"Month"/"month"/"1 month" share keys; (2) add a **non-regression gate** — promote an
option-label subset of `--audit-chrome` to blocking, OR a test enumerating every
`<select>`'s static option labels asserting each control label is in `en.json`;
(3) translate dynamic-select control labels via `OOI18N.t()` at build time. This
also pre-empts **Item C** (new agenda controls keyed from the start). New locale
strings AI-drafted, flagged for native review.

---

## Item E — Agenda must auto-populate (background verify/import, kill the manual "Verify next 25"); Settings → Agenda = a sortable source manager with bulk select/remove (dysfunctional / per-country) + easy `.ics` import & calendar subscribe  [auto-collect PLANNED · the manager mostly NEW]  ⏭ capture-only

**Verbatim (08:09):** "How come the agenda doesn't auto-populate? We don't want
users to have to go to the settings and click on the 'Verify next 25', especially
if there are few hundred calendar sources. All of this should be automatic,
background. The settings interface should be used to check sources, adjust them,
why not present them with possible sorting capabilities. There should be a way to
bulk select all dysfunctional agendas, or per country, and so forth. This selection
would allow the user to remove them. There should be an easy way to import .ics and
subscribe to other calendars."

**Where (grounded):**
- **"Verify next 25"** = `index.html:1644` → `verifyFeedBatch` → `POST
  /api/events/feeds/verify-batch?limit=25` (`events.py:116–137`). It only **verifies**
  (records verdicts) — it does **not** import events.
- **Per-feed Verify/Import** = `index.html:3811–3812` → `feedAction` → `POST
  /api/events/feeds/{id}/{verify|import}` (`events.py:78–101`). **Import** is what
  actually populates imported events — and it's one click **per feed**.
- **Directory render** = `renderFeedDir` (`index.html:3796–3821`): families as
  `<details>` rows, filter by kind + free text only, status "X feeds · Y folders · Z
  checked", display capped at 40. **No sort, no bulk-select, no remove, no add-your-own.**
- **Background today:** the scheduler runs `feed_preflight` **once on first run**
  (`runner.py:508–515`) = a robots/reachability **sample** → `data/feed_preflight.jsonl`;
  it is **not** an import and never repeats. The collect scheduler modes (`#sch-mode`)
  are RSS / crawl / markets / wiki — **there is no calendar-feed mode**, so feed
  calendars never auto-import.
- **What IS auto-present** (so the agenda is not blank): the **curated/computed**
  events — civic dates, UN days, astronomy/seasons (`events.py` `list_events` /
  `/astronomy`, offline). It's the bundled **feed directory** ("few hundred" `.ics`
  provider candidates) that needs the manual verify+import the maintainer is hitting.
- **ICS substrate exists:** `parse_ics` / `_unfold` / `_ics_unescape`
  (`feeds.py:162–216`), 5 MB cap — but it's invoked **only** by `verify_feed` /
  `import_feed` on **bundled** feeds. There is **no user add-feed** (URL or upload)
  and **no `remove_feed`**.
- **Subscription model:** first run subscribes to all calendars so the agenda isn't
  empty (`index.html:3764`); "subscribed only" filter (`#agenda-subonly`, 1056).
  Subscription is a **client preference** (`events.py:48`); CLAUDE.md D1/D4 "agenda
  subs server-side" is a queued migration.
- **Fields already present to drive bulk ops:** every feed carries `country`
  (`fd.country`) + `verdict` (`fd.verdict`) → "dysfunctional" = `verdict.status != ok`;
  "per country" = `fd.country`. The data for the bulk filters is already there.

**Maps to:** invariant **#8** ("the UI shows DATA, never plumbing — first applied:
Agenda") — the maintainer **sharpens** it here: plumbing should not merely *move* to
Settings, it should be **automated** (background), and Settings becomes an
inspect/adjust/manage surface. Also CLAUDE.md **AGENDA CONTENT** queue + the
**"batch it like calendars"** field-log note + the standing **"we should be flooded;
expand calendars massively; subscribe-default stays off-flood."** Plus BACKLOG_GROUPED
**Group B** (continuous collection + the **bandwidth priority ladder** + no source
cap): calendar verify/import becomes a background **job kind** on the ladder —
bounded, polite, kill-switch-gated, parallel-by-host, like RSS. And the **D1/D4**
agenda-subs-server-side migration (persistence for subscriptions + bulk-manage state).

Sub-parts:
- **(a) [PLANNED — elevate] Background auto verify+import.** Calendar feeds join
  continuous collection so the agenda fills itself; drop "Verify next 25" as the
  PRIMARY path (keep a manual "refresh now" for power users, as elsewhere). Robots /
  kill-switch / politeness inherited via `make_fetcher`; on the bandwidth ladder.
  Honesty: a feed fetch is a network action, so it still rides the ONE consent
  (invariant #14) + auto-collect runs only when online after consent; the curated
  offline catalog keeps the agenda non-empty before any network.
- **(b) [NEW] Settings → Agenda = a SORTABLE source manager.** Sort by name /
  country / kind / verdict / last-checked / imported-count (the directory already
  carries these fields); status + manage instead of per-row verify/import friction.
- **(c) [NEW] BULK select + remove.** Select all **dysfunctional** (`verdict.status
  != ok`), or **per country**, or by kind/filter → remove. **Tension to resolve
  (flag for the maintainer):** the anti-hiding principle (BACKLOG_GROUPED Group B —
  "removing them would hide sources", resolved by design to KEEP showing honest
  verdicts) is preserved ONLY if removal is **user-initiated** and ideally means
  **"unsubscribe / exclude from MY agenda"** (a reversible per-machine choice), NOT
  deleting the bundled candidate from the catalog or silently app-hiding it.
- **(d) [NEW] Easy `.ics` import + subscribe to OTHER calendars.** Add a calendar by
  URL (webcal/https → through the ethical fetcher: robots / kill-switch / consent) or
  by uploading a local `.ics` file (no network). Reuse `parse_ics`; new add/remove
  user-feed endpoints + the D1/D4 server-side subs persistence. Today only the bundled
  directory exists — this is the "subscribe to other calendars" the maintainer wants.

**⏭ Open design questions (hold for "compile"):** (1) does auto-populate IMPORT all
bundled candidates, or only **subscribed** ones? (the standing "subscribe-default
stays off-flood" suggests: auto-**verify** all in the background for honest verdicts,
auto-**import** only subscribed; the user bulk-subscribes by country/kind). (2)
"remove dysfunctional" semantics — recommend **unsubscribe/exclude** (reversible,
per-machine) over delete-candidate, to keep anti-hiding. (3) where bulk-manage +
user-feeds persist (localStorage vs the D1/D4 server-side subs table). Cross-links
**Item C** (manage UI uses the universal subtab/sort grammar) and **Item D** (every
new control keyed ×12 from the start).

---

## Item F — Home/Briefing: auto-refresh (remove the Refresh button); keep the "updated · date · time" stamp; render the date with the FULL month name in the app language (translated)  [NEW · ties to #8 + Item D]  ⏭ capture-only

**Verbatim (08:12):** "In the home tab should automatically be refreshed. Remove the
refresh button. Keep the 'updated + date + time'. Use full text for months. This
should be translated."

**Where (grounded, `src/static/index.html`):**
- **Briefing header** `757–759`: `<span id="brief-generated">` (the "updated …"
  stamp — **KEEP**) + `<button id="brief-refresh-btn" onclick="refreshBriefing()">
  Refresh</button>` (**REMOVE**).
- `refreshBriefing()` `3279–3285` → `POST /api/briefing/refresh` (a server-side
  **recompute**, heavier than a reload).
- The stamp is set in `renderBriefing` **3291**:
  `gen.textContent = "updated " + new Date(data.generated_at).toLocaleString()`.
  Two faults: **(i)** `"updated "` is hardcoded English (built in JS, so the i18n DOM
  walker can't reach it — needs `OOI18N.t()`); **(ii)** `toLocaleString()` with **no
  locale arg** uses the **browser** locale and a **numeric** month (e.g. "6/15/2026,
  8:12:38 AM"), not the **app** language with a full month.
- **Load path:** `loadHome` `3243` → `loadBriefing` `3269` (`GET /api/briefing`,
  cached) on tab open; `renderBriefing` paints. There is **no periodic/auto refresh**
  today — only tab-open + the manual button.
- **The correct pattern already exists:** the Agenda formats months via
  `new Intl.DateTimeFormat(loc, { month: "long", year: "numeric" })` with `loc` =
  `OOI18N.current()` (**index.html:3921**) — reuse it.

**Maps to:** invariant **#8** (the UI shows DATA, never plumbing — a manual Refresh
is plumbing; Home should self-update); the **Home redesign §5** / BACKLOG_GROUPED
**Group E** (content-first, shipped #128/#129); **field-log finding B** (the polling
storm — auto-refresh must be ADAPTIVE, not a constant poll); and it is a **sibling of
Item D** (untranslated chrome + locale-aware dates).

Sub-parts:
- **(a) [NEW] Auto-refresh Home; remove `#brief-refresh-btn` (759).** Cadence to
  settle (see questions): recommend refresh on Home open (already happens) **+**
  auto-update when `generated_at` changes / after a collect pass (push, not poll),
  **+** at most a light adaptive poll **only while the Home tab is visible**. Honesty
  / perf: prefer the **cached `GET /api/briefing`** and only **recompute** (the heavy
  `POST /refresh`, T1 perf 36.6 → 1.5 s) when inputs actually changed — never on a
  blind timer (avoids re-creating the polling storm).
- **(b) [KEEP] The "updated · date · time" stamp** (`#brief-generated`) stays.
- **(c) [NEW] Date format = full month, app language, translated.** Replace the bare
  `toLocaleString()` (3291) with `Intl.DateTimeFormat(OOI18N.current(), { year:
  "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" })`
  (the Agenda pattern, 3921), and **key "updated"** ×12 via `OOI18N.t()`.

**Broader note (sibling to Item D — flag, don't expand here):** many `toLocaleString()`
calls across the app (e.g. `2643`, `4040`, `5128`, `5252`) use the **browser** locale,
not the app language → a **shared locale-aware date/time formatter** (paralleling the
shared units formatter) would fix the whole class consistently. Candidate for the same
PR as Item D.

**⏭ Open design questions (hold for "compile"):** (1) auto-refresh **trigger** —
push-on-pass-complete vs visible-tab adaptive poll vs on-focus (recommend push +
on-open, no idle poll); (2) keep a hidden/manual **recompute** affordance for power
users (since recompute ≠ reload), or drop it entirely; (3) stamp **format** — the
maintainer said "date + time" (absolute, full month) — keep absolute, or absolute +
a relative "updated N min ago" in the hover (the #oo-tip pattern used elsewhere)?

---

## Item G — Specific untranslated chrome strings flagged live (running list; all instances of Item D)  ⏭ capture-only

The maintainer is calling out individual untranslated strings as they appear. Each is
a concrete instance of **Item D**'s class; they accumulate here as a worklist while
Item D holds the systemic fix (+ the non-regression gate so this list can't regrow).

**G1 (08:13) — Home Briefing transparency paragraph.**
> "Equal view — every source is counted once; no source is de-amplified in this
> version. The app gathers and measures; you judge. Each card is one measured signal
> with its evidence and caveat, never a verdict."

- **Where:** the `<p class="hint">` under the Briefing toolbar, **index.html:766–768**.
- **Root cause (the inline-markup-split sub-case):** the sentence is split by
  **`<b>you judge</b>`** into THREE text nodes, so the exact-match engine (`i18n.js`
  `tr`, which matches a WHOLE text node) has no node equal to the full sentence — and
  none of the fragments are keyed (grep across all 12 locales = **0 hits** for "Equal
  view" / "de-amplified" / "gathers and measures"). This is precisely the
  `--audit-chrome` "fragments split by inline markup" category.
- **Contrast (the pattern that works):** the nearby "Analytics over the articles your
  search matched — counts only, never a verdict." (**index.html:826**) is a SINGLE
  text node and IS keyed + translated ×12 — proof the engine handles it once the
  markup doesn't bisect the sentence.
- **Fix:** follow the established **whole-sentence-node** convention (the Agenda intro
  `1041–1045` and Indices intro `1077–1078` wrap each sentence in its own `<span>`):
  restructure this `<p>` into whole-sentence `<span>`s (keep "you judge" emphasis as a
  span that doesn't bisect a sentence, or drop the `<b>`), then key each sentence ×12.
- **Maps to:** Item D + CLAUDE.md "i18n & LANGUAGE UX" + the "Whole-sentence nodes"
  note (index.html:1041).

---

## Item H — Home "at a glance" stats strip: stale (must be LIVE) + labels are raw snake_case table keys (untranslated)  [ties Item F (live) + Item D (i18n) + a raw-label bug]  ⏭ capture-only

**Verbatim (08:16):** [the strip showing] "0 articles / 0 sources / 0 source_groups /
0 keywords / 0 commodity_prices / 0 external_sources / 0 article_links / 0
article_analyses / 0 mentioned_dates / Automatic collection: stopped · everything
stays on this machine — no cloud, no telemetry". "It is not up to date. It should
automatically be updated. the ideal is that it should show live information. It
should be translated in all languages."

**Surface (clarify):** this is the **Home "at a glance" strip** (`.home-glance` panel
= `#home-stats` + `#home-status`, **index.html:750–754**) — invariant **#19**'s
compact strip, NOT the chrome top bar (the top bar's vitals moved into the
task-manager System tab — invariant #4). The maintainer perceives it as a top bar
because #19 pins it at the very top of Home.

**Where (grounded):**
- **`#home-stats` render:** `loadHome` **3245–3250** —
  `entries.map(([k,v]) => "<b>"+v.toLocaleString()+"</b> <span>"+esc(k)+"</span>")`.
  **`k` is printed raw.**
- **The keys** come from `/api/database/stats` → `counts`, keyed by `_COUNTED_TABLES`
  (**database.py:67–77**): articles, sources, source_groups, keywords,
  commodity_prices, external_sources, article_links, article_analyses,
  mentioned_dates — **raw snake_case**, designed for the **Database management tab**
  (database.py:107); the Home strip reuses it verbatim. CSS then **uppercases** them
  (`.stat-strip .s span text-transform:uppercase`, **index.html:469**) → "SOURCE_GROUPS",
  "COMMODITY_PRICES".
- **`#home-status` 3255–3258:** "Automatic collection: {running|stopped} · {privacy
  line}". "Automatic collection", "running", "stopped" are JS-built strings (the i18n
  DOM walker can't reach them → need `OOI18N.t()`). (Aside: the maintainer's build
  shows the OLD "everything stays on this machine" privacy line; HEAD on this branch
  already reads "Your corpus stays on this machine … fetching follows your Network
  mode" — the OO-D3-002 qualification. Not a new issue, just a build-lag note.)
- **Not live:** the strip is painted only by `loadHome` (on Home tab open) — no
  periodic/auto refresh, no push on collect, so it holds the values from when Home was
  last opened. **Same root as Item F.**
- **Fresh-corpus nit:** on an empty corpus every count is 0 **but the keys exist** →
  `entries.length === 9` (truthy) → the strip shows nine "0 …" chips instead of the
  friendly "Your library is empty" empty-state (which only fires when `counts` is
  `{}`). So a brand-new user sees exactly the maintainer's "0 ARTICLES 0 SOURCES 0
  SOURCE_GROUPS …".

**Maps to:** **Item F** (Home must self-update — the "live information" ask is the
same mechanism) + **Item D/G** (untranslated chrome — labels + status strings) +
invariant **#19** (the at-a-glance strip) + invariant **#8** (data, not plumbing).

Sub-parts:
- **(a) [NEW = Item F mechanism] LIVE stats.** Auto-update `#home-stats` /
  `#home-status` — push after each collect pass + refresh on Home open + at most an
  adaptive visible-tab poll (never a blind timer; field-log B). Ideal = counts tick up
  as rows land. Reuse Item F's Home self-update.
- **(b) [NEW] Human, translated labels.** Map each raw key → a human label keyed ×12
  (articles→"Articles", source_groups→"Source groups", commodity_prices→"Commodity
  prices", external_sources→"External sources", article_links→"Article links",
  article_analyses→"Article analyses", mentioned_dates→"Mentioned dates"). Do it in the
  **UI layer** via `OOI18N.t()` (a fixed key→label dict) — do **NOT** rename the server
  `counts` keys (they're identifiers the Database tab + cache rely on). Key the status
  strings ("Automatic collection", "running", "stopped") too.
- **(c) [NEW, minor] Fresh-corpus display.** Show the friendly empty-state when every
  count is 0, instead of nine "0" chips (today it never does because the keys exist).

**⏭ Open questions (compile):** live cadence/trigger (shared with Item F);
empty-state-on-all-zeros yes/no; keep raw keys in the Database management tab (fine
there) while Home gets human labels (recommended split).

---

## Item I — Home cards must ALL be clickable → open the universal search/analysis window seeded with the card's results (not the standalone `/investigate` new-tab page)  [PLANNED remainder + destination refinement; Group F]  ⏭ capture-only

**Verbatim (08:18):** "The cards should be clickable, and open-up a search tab with
the results from the cards' analysis (in the same universal search interface)."

**Where (grounded, `src/static/index.html`):**
- Cards are rendered by `cardHtml(c)` (**3335–3412**). A card is clickable **only if**
  it has `c.recipe.view` — `cardOpen` (**3394–3396**) adds `cursor:pointer` +
  `onclick=window.open('/investigate?view=…&params','_blank')` (a **separate page, NEW
  browser tab**), guarded by `if(!event.target.closest('button,a,details,summary'))`.
  **Cards without a recipe are not clickable.**
- Each card already carries what a seed needs: `c.type`, `c.title`, `c.summary`,
  `c.signal` (metric/value/n/signature/lat/lon), `c.evidence` (article_ids/urls),
  `c.recipe` (view+params), `c.trigger`.
- The universal window = the Group F analysis window: `openAnalysis()` (**7191**) /
  `#tab-analyze` (**822**), sub-tabs Keywords/Articles now (mindmap/links/WWW/sentiment
  planned) — "the seven entries into the same object."

**Two changes the maintainer wants:** (1) **every** card clickable (drop the
recipe-only condition); (2) destination = the **in-app universal search/analysis
window** seeded with the card's analysis, **not** the standalone `/investigate` page
in a new browser tab.

**Maps to:** CLAUDE.md **"Home cards remainder: per-card-TYPE /investigate views so
EVERY card is clickable"** (the every-card-clickable remainder — PLANNED) +
BACKLOG_GROUPED **Group F** (the analysis window + **"the seven entries into the same
window"**) — a card-click becomes another entry. **Refinement:** the destination
unifies onto the ONE universal window ("the same universal search interface"), instead
of bespoke per-type `/investigate` pages.

Sub-parts / design:
- **(a)** Map `card.type → window seed` (query/scope + initial sub-tab): rising→the
  term (trend+associations); framing-split→the keyword (sentiment/competitive);
  echo_chamber→the actor signature (links); overtold/undertold & diet/coverage→sources;
  promise-due→the date/keyword; law/wiki→reader/article-set. `c.recipe.params` is a
  ready seed for recipe cards; non-recipe cards seed from `c.signal` / `c.evidence`.
- **(b)** Keep the inner-control click guard (`closest('button,a,details,summary')`) so
  Dismiss / "+ Add to draft" / evidence links / the "Why am I seeing this?" details
  don't trigger the open.
- **(c)** Preserve shareability: `/investigate?…` is URL-parameterised today
  ("shareable, no hidden state"). The universal window should be URL-addressable too,
  OR `/investigate` stays as the shareable export while in-app clicks open the window.
- **Gated by** the Group F flagship (the window's full sub-tab set is only partly
  built — Keywords/Articles). Card-click entry lands with / after that window.

**⏭ Open questions (compile):** does this RETIRE `/investigate` (and its shareable-URL
property), or do both coexist (in-app window for clicks, `/investigate` for sharing)?
The per-card-type seed table needs sign-off (which sub-tab each card opens on).

---

## Item J — Uniform subtabs app-wide: card categories as subtabs + ONE identical subtab grammar everywhere ("a big one")  [PLANNED — keystone #3 / invariant #18; largely SHIPPED — audit inside]  ⏭ capture-only + CLARIFY

**Verbatim (08:21):** "The cards categories should be represented as subtabs. The UI
should be coherent and show subtabs in a uniformed manner. This is a big one. Subtabs
should be identical in the way they are presented, their name and content will / might
vary depending on the tab the UI is in. If this is not clear, ask questions."

**Maps to:** invariant **#18** (ONE universal subtab component `ooSubtabs` — identical
presentation + ARIA + keyboard nav; content varies per surface) = **keystone #3**
(BACKLOG_GROUPED Group E) = **UI_SHELL_REDESIGN_PLAN §1** ("ONE universal nav grammar
app-wide — lateral sidebar = main tabs, vertical subtabs = subcategories"). This
observation IS that principle, restated by the maintainer.

**Audit (HEAD — the principle is largely SHIPPED):**
- ONE component `ooSubtabs(nav, onSelect, opts)` (**index.html:5834**) owns
  presentation + ARIA (tablist/tab/aria-selected) + keyboard nav + roving tabindex;
  one `<nav class="tabs">` grammar (5827).
- **SIX adopters already use it identically:** Home card families
  (`home-fam-subtabs`, **3326** — #129), Insights (`ins-subtabs`, **7732**), Settings
  (`set-subtabs`, **7733**), corpus window (`corpus-subtabs`, **7734**), task-manager
  window (`tm-subtabs`, **7735**), analysis window (`an-subtabs`, **7736**).
- The legacy divergent impls (`data-ins` / `data-set` / `data-ctab`) are **GONE** —
  all unified onto `data-tab` (44 occurrences, 0 legacy).
- **So "card categories as subtabs" is already shipped (#129) on HEAD** — Home families
  render through the same component as everywhere else.

**Remaining NON-uniform surfaces:** per invariant #18 "NEXT: Markets category tabs,
the analysis window" — the analysis window is now an adopter; **Markets/commodities
category tabs** are still unbuilt (Group G "Split graphs into category tabs" ⬜). Also
candidates from this session: the **Agenda view switch** (Item C(b): Month/Week/List as
a uniform subtab/segmented control) and any surface still using dropdowns/buttons where
the subtab grammar would be more coherent.

**Ambiguity → CLARIFY (the maintainer invited it):** the headline "card categories
should be subtabs" is ALREADY true on the latest build, so the ask is one of: **(A)**
the maintainer's BUILD lags #129 / a regression (Home not showing subtabs) — chase it;
**(B)** EXTEND the same component to surfaces that aren't subtabs yet (Markets
categories, the Agenda view switch) — the invariant-#18 "next adopters"; **(C)** REWORK
the subtab visual design itself across the app (a new look for the one component);
**(D)** something else.

**RESOLVED (maintainer, 08:50):** option **(C)** — **rework the subtab LOOK across the
whole app**. NOT a build-lag, and not (only) extending to new surfaces: keep the ONE
shared component (`ooSubtabs`, **index.html:5834**, + the `<nav class="tabs">` grammar &
its CSS) and **redesign its visual treatment** — which, because it is a single
component/class, propagates to all six adopters AT ONCE (the payoff of invariant #18). So
this is a **centralised CSS/component visual refresh**, applied everywhere uniformly (not
per-surface work). **⏭ OPEN (needs the maintainer's design intent, or the implementer
proposes options):** the SPECIFIC new look — bar shape, active-state (underline vs pill
vs filled), spacing, typography, hue/accent — while preserving ARIA + keyboard nav + the
#oo-tip hover. Item K (the analysis subtabs) and every other adopter inherit it
automatically. Build-lag is moot: choosing "rework the look" means the maintainer DOES
see the subtabs and wants them redesigned.

---

## Item K — Analysis-window sub-tabs (Keywords / Articles / When-Where-Who / Links / Sentiment / Sources / Advanced) as uniform subtabs  [ALREADY SHIPPED at the nav level on HEAD; content = Group F remaining]  ⏭ capture-only

**Verbatim (08:24):** "regarding the analysis tab. Same remark : Keywords / Articles /
When/where/who / links / sntiment / Sources / Advanced should be presented as
sub-tabs. Visually coherent like any other subtabs."

**Grounded:** the analysis nav `#an-subtabs` (**index.html:827–835**) ALREADY renders
exactly that set as `data-tab` buttons — Keywords, Articles, When/Where/Who (`www`),
Links, Sentiment, Sources, Advanced — wired through the SAME `ooSubtabs` component
(7736, `anSelectTab`). So at the **sub-tab grammar** level this is already shipped and
visually coherent with every other surface.

What's actually missing = the **panel CONTENT**: only Keywords + Articles are
implemented (`anSelectTab` 7219 → Keywords = `/api/insights/corpus-keywords`,
counts-only; Articles = the match list). When/Where/Who · Links · Sentiment · Sources ·
Advanced are the **Group F remaining** panels — present as tabs, stubbed as content.

**Resolves Item J's ambiguity (by the maintainer's own example):** BOTH surfaces the
maintainer named (Home card families #129, the analysis sub-tabs) are ALREADY uniform
subtabs on HEAD. ⇒ the maintainer is most likely on a **build that predates #129 / the
Group-F slice**, OR reacting to the **stub panels** (a subtab that switches to empty
content reads as "not a real subtab"). **Action: flag as a build-lag to verify** +
prioritise the Group F panel content (Item L specifies the Keywords panel). The
uniform-subtab MANDATE (invariant #18) stands as the guide for every surface regardless.

---

## Item L — Keyword sub-tab = top-8 daily-occurrence graphs via the commodities engine (ooChart); categorize/tag keywords; tags assemble keyword FAMILIES (graph the family's top-8); fit-on-screen, no scroll  [NEW — Group F keyword panel + #16 + families]  ⏭ capture-only

**Verbatim (08:29):** "The keyword subtab should show the top 8 keywords daily occurence
graph, with the same engine as the commodities are presented. Like commodities, keyword
should be categorized / tagged. Tags should allow user to assemble family of keywords so
that the top 8 keywords from this family are graphed. Try to make everything fit on the
screen so that there's no need to scroll down to see all graphs."

**Where (grounded):**
- The keyword sub-tab `#an-keywords` (**index.html:836**) shows a COUNTS LIST today
  (`anSelectTab` 7219 → `GET /api/insights/corpus-keywords` 7229, counts-only).
- "Same engine as commodities" = **`ooChart`** (**index.html:5620**; invariant #16) —
  already used for markets (5794), the corpus trend (6190), the insights trend (6462).
  The commodities **small-multiples grid** is `#mkt-dashboard`
  (`grid-template-columns:repeat(auto-fill,minmax(300px,1fr))`, **index.html:1109**) —
  the fit-to-screen pattern to mirror.
- Per-keyword daily series substrate: keyword_mentions carry dates; `/api/insights/
  trend` already builds a per-term daily series for ooChart (6462). Top-8 = the top-8
  keywords, each with its series.
- Categorize/tag + families substrate EXISTS: `src/api/keyword_management.py` —
  `get_keyword_categories` (97), `categorize_keywords` (109), `get_top_keywords`
  (123); plus `src/analytics/families.py` (the families engine; `#fam-kind`).

Asks:
- **(a)** Graph the **top-8** keywords' **daily occurrence** via ooChart (full-res per
  #16; honest sparse→points + the early-corpus caveat).
- **(b)** Keywords **categorized/tagged** like commodities (reuse keyword_management +
  families).
- **(c)** Tags let the user **assemble keyword FAMILIES**; selecting a family graphs
  the **family's top-8** (the corpora "curated symbol→family seed table" idea, now
  user-buildable).
- **(d)** **Fit-on-screen, no scroll** — a viewport-fitting small-multiples grid (the
  `#mkt-dashboard` pattern), all top-8 visible at once.

**Maps to:** BACKLOG_GROUPED **Group F** (the keyword panel = the next slice beyond
counts-only) + invariant **#16** (ooChart) + the corpora "KEYWORDS ARE CORPORA" +
time-scope + the keyword **families/tagging** system + the commodities small-multiples
grid (Group G). Cross-links **Item C(d)** (colored tag chips = same tagging UX) and
**Item K** (this IS the Keywords-panel content the window needs).

**⏭ Open Qs (compile):** top-8 by which window (last-N-days vs the time-scope
control)? one multi-series chart vs 8 small multiples? how families are defined (auto
co-occurrence vs purely user-assembled vs seed-table + user edits)?

---

## Item M — "Download keyword log" opens a raw streaming JSON in a new tab (very slow, no feedback) → show progress + make the tab informative ("use it smartly")  [NEW — ties task-manager / Group C]  ⏭ capture-only

**Verbatim (08:31):** "Downloading keywords opens-up a new tab, takes a very long time.
Why not help the user understand what's going on and show a progress bar? This new tab
should show information. Let's use it smartly."

**Where (grounded):**
- The button: **index.html:1719** — `window.open('/api/diagnostics/keywords','_blank')`
  "Download keyword log (.json)" (Settings → diagnostics). It opens a NEW browser tab
  pointed straight at the **streaming JSON** endpoint.
- The endpoint: `src/api/diagnostics.py:57–58` `GET /keywords` → `keyword_log` returns a
  `StreamingResponse`. **Known-slow:** field-log C measured **29.6 s → 65.2 s** under
  live-scrape contention; T1 got it to ~7.8 s encrypted (streamed). So the tab sits
  **blank/loading for tens of seconds**, then dumps raw JSON — no progress, no info.

**Asks:** a **progress bar** + the new tab should **show information** — a real page,
not a raw JSON dump.

**Maps to:** the **task-manager / download-manager** (BACKLOG_GROUPED **Group C** —
every job a VISIBLE job with progress; running/queue/history) + the perf work (the
export is heavy) + the diagnostics channel (the keyword log is part of the maintainer's
debug protocol). Honesty: it's a STREAM — show **honest progress** (items processed /
indeterminate "working… N keywords"), **never a fabricated ETA**.

**Design directions:** (a) make it a **task-manager job** with a progress indicator
instead of a raw `window.open`; OR (b) the new tab loads a **real page** that states
what's being exported + a progress bar, then offers the file when ready; (c) an async
export-then-download (kick the job, stream progress, download on completion) so the UI
never blocks on a blank tab. Fold ALL slow exports/downloads into the same treatment via
the download subsystem.

**⏭ Open Qs (compile):** in-app job + download-when-ready vs an informative export page
in the new tab? does the streaming endpoint expose a progress count, or show
indeterminate progress?

---

## Item N — the "Trust" tabs (Evidence & custody · Source integrity): rethink purpose, spread into the workflow, make them dummy-proof & (semi-)automatic  [NEW — design decision; "help me decide"]  ⏭ capture + RECOMMENDATION (awaits maintainer steer)

**Verbatim (09:00):** "The TRUST tabs might not be used. Note that they are not fully
translated also. I'm wondering if this shouldn't be spread in search related tools and UI.
Anyways, we should think [about] their ultimate purpose and use cases in order to maximize
usefulness and user accessibility. They should become more user friendly anyways, and
accessible to users that are not familiar with these and not experts. They should become
dummy-proof, maybe semi automated, or completely automated. I'm not sure, help me decide."

**What they are (grounded):** the sidebar **"Trust" nav-group** (index.html:654-658) =
exactly TWO tabs:
- **Evidence & custody** (`#tab-custody`, index.html:891) — chain-of-custody: signed,
  tamper-evident provenance for legal defensibility. Expert knobs (post-quantum ML-DSA/
  FIPS-204 signatures, OpenTimestamps→Bitcoin anchoring, auto-log-on-ingest, default actor)
  + actions (view chain / verify / export offline-verifiable bundle / **anchor a raw
  "Merkle root (hex) … 64-char SHA-256 hex"**). Deeply forensic.
- **Source integrity** (`#tab-integrity`, index.html:974) — anti-amplification ("Scan for
  coordination" → collapse a near-duplicate flood to "one voice", reversible), source
  profiling (structure signals: coordination/novelty/output-capacity/transparency —
  explicitly **NO trust score**), and the **web-of-trust** shared annotations (signed,
  contestable facts about sources; trusted-author curation).

**i18n confirmed:** "Chain of custody", "Source integrity & anti-amplification",
"Merkle root", etc. live ONLY in index.html — absent from all 12 `locales/*.json`. So
these tabs are hardcoded English (part of the untranslatable long tail).

**Usage:** we have NO telemetry (by design), so "might not be used" can't be measured —
but structurally they're buried in a silo, expert-heavy, and disconnected from where users
actually work (search/reading/analysis), which predicts low use. The maintainer's instinct
is sound.

**THE REALIZATION (the crux):** these are TWO different things wearing one "Trust" label,
for TWO different audiences:
- **Integrity = for EVERYONE, belongs AMBIENT.** "Is this source manipulating me? Is this
  'consensus' really 10 copies of one origin?" is the project's core anti-single-origin
  ethic — the SAME methodology as the LINKS anti-false-triangulation rule. It should not be
  a destination you remember to visit; it should COME TO the user where they read/search/
  analyze.
- **Custody = for a NARROW expert subset** (journalists / legal / archivists proving an
  artifact existed at T and is unaltered). Inherently forensic. It's the LOCAL end of the
  reliable-memory pillar.

**MY RECOMMENDATION — 4 moves (applies existing rulings, invents no new philosophy):**
1. **Dissolve the "Trust" sidebar group** — apply invariant #8 ("show DATA, never
   plumbing") + the content-first precedent that already moved Collect/Sources/Wikipedia
   into Settings. GATED by an **absorption test** (the Desk lesson: nothing removed until
   its capability lives in its new home).
2. **Integrity → ambient + automatic (the maintainer's "spread into search/UI", endorsed):**
   coordination detection becomes a BACKGROUND pass (like Insights auto-indexing,
   invariant #21 — no manual "Scan" button); in SEARCH results + the corpus/analysis window
   a coordinated cluster shows inline, dummy-proof: *"12 near-identical copies from a
   coordinated network · counted as 1 voice [show all 12]"* (this IS the anti-false-
   triangulation surface LINKS already wants); the READER gets a per-source integrity-
   signals row (method+caveat) + web-of-trust annotations on the source chip; profiling +
   annotations attach to a SOURCE CHIP wherever a source appears (no "type a domain" box).
   Dummy-proof BY CONSTRUCTION — the user never needs the word "anti-amplification".
3. **Custody → an ACTION on content, not a destination:** per-item "Export tamper-evident
   proof" / "Verify this bundle (green=unaltered / red=altered)" on articles + corpora (the
   signed-evidence export already lives in the Search tab = precedent); the raw
   "Merkle root (hex)/Ed25519/OTS" detail moves into the **#oo-tip hover** (informed-
   consent-by-LAYERING — the permanent ruling); the custody PREFERENCES move to **Settings**.
4. **Automation defaults (the genuine rulings needed):** (a) **auto-log custody ON by
   default** — recommended YES (tamper-evidence is the reliable-memory pillar; on by
   construction like at-rest encryption, so users get legal-grade provenance without knowing
   what a Merkle root is; expert knobs in Settings). **OTS/Bitcoin anchoring stays OFF by
   default** either way — it's a network egress that reveals IP/timing (already warned).
   (b) integrity coordination scan → background/auto.

**i18n note:** don't spend the ×12 keying effort on the CURRENT tabs if we're about to
dissolve/move them — key the strings AS they land in their new homes (else we translate
strings we're about to delete). The i18n fix FOLDS INTO the rework.

**Sequencing reality:** integrity's best home (the corpus/analysis window with
source-competitive-analysis + LINKS) is only PARTIALLY built (T10 slice 1). So the full
"spread integrity into the workflow" rides WITH the search/analysis-window completion (the
Enter→corpus-window slice). Custody-as-action can land earlier (reader + Search export
exist).

**Supersedes/extends** the existing queue item *"Custody tab UX: most users won't get it —
rename/explain/guided steps"* — the answer is not rename/explain but spread + automate +
dummy-proof.

**⏭ DECISIONS I need from the maintainer:** (a) dissolve the Trust group & spread into the
workflow (recommended) **vs** keep two tabs but just dummy-proof in place? (b) custody
auto-log ON by default (recommended) **vs** stay opt-in? (c) treat as a now-ish topic **vs**
parked behind the analysis-window build (integrity's natural home)?

**✅ RESOLVED (maintainer 09:59) — all three as recommended:** (a) **DISSOLVE the group &
spread into the workflow**; (b) **custody auto-log ON BY DEFAULT, opt-out in Settings**;
(c) **PARK it behind the analysis-window build + the search UI**. Recorded as a ruling in
CLAUDE.md (supersedes the old "Custody tab UX" queue note). So integrity's home = the analysis
window + search results; custody-as-action rides the same build; OTS/Bitcoin still OFF by
default; i18n folds into the rework. No code this turn (parked, sequenced).

---

## Item O — app tabs should be right-clickable → "open in a new window/tab" (real browser behaviour)  [NEW — ties the routing/back-button rework]  ⏭ capture-only

**Verbatim (09:01):** "tabs should be right-clickable so users can open up a tab in a new
window."

**Where (grounded):** nav is JS-only — `showTab()` swaps `.tab-page` visibility; the
nav-items are `<button data-tab=…>` with NO real `href`, and tab nav uses
`history.replaceState` (the back-button bug, UI-plan §7a). With no URL there is nothing for
the browser's "open in new window/tab", middle-click, or ⌘/Ctrl-click to open.

**THE UNIFYING INSIGHT:** give every tab a REAL URL (deep-link anchor) + `pushState`
history, with `showTab` intercepting plain left-click (preventDefault) while letting
modified clicks (middle / right / ⌘ / Ctrl) fall through to native browser behaviour. ONE
routing fix then delivers THREE things at once: (1) right-click/middle-click → open in new
window/tab; (2) the BACK BUTTON bug fix (already in the queue: pushState for tab nav +
replaceState to "/" after unlock); (3) pop-out analysis/corpus WINDOWS to their own browser
window (aligns with "click a graph → a dedicated window like search results").

**Cross-ref:** the "TWO BUGS … (a) the BACK BUTTON returns to the passphrase screen" queue
item — SAME root, fix together.

**⏭ Open Q (compile):** scope — main nav tabs only, or also the analysis/corpus windows
(so a corpus can pop out to its own browser window)? My read: both, eventually; windows-as-
real-URLs is the bigger lift.

---

## Item P — remove the "Help & docs" SIDEBAR tab (top-bar "?" is sufficient)  [NEW]  ✅ SHIPPED this session

**Verbatim (09:02):** "Remove the help and docs tab, having the top question mark icon is
sufficient."

**Grounded + absorption confirmed:** the sidebar "Help & docs" item (`data-tab="help"`,
was index.html:662) duplicated the **top-bar "?" icon** (index.html:704) — BOTH call
`showTab('help')` → the identical `#tab-help` page; the command palette (index.html:3128/
3134) and the Law-guide link (953) also reach it. Nothing lost.

**Shipped:** removed the `data-grp="system"` nav-group (Help was its only remaining member
after Settings was removed earlier). Help stays **registered + LOCKED** (TABS registry +
`LOCKED` set, index.html:2928/2931) so the "?" icon, palette and deep-links keep working;
in-code breadcrumb left, registry comment updated. No new strings (removal only).
**Verified:** `test_ui_invariants` green (no test pinned Help to the sidebar; the negative
content-first assertions for Collect/Sources/Wikipedia were the precedent).

---

## Item Q — ALL in-app docs should be translated + inherit the repo's docs automatically  [NEW]  ⏭ capture (repo-linkage already exists; translation is the open work)

**Verbatim (09:04):** "All in-app documentation should be translated. We should link them
to the app's repo, so that they inherently inherit changes made to the repo's docs. Maybe
it's already the case."

**Finding (grounded — it IS largely already the case):**
- **Repo-linkage ✅ already exists:** docs are served LIVE from the repo's `docs/` directory
  at runtime (`_DOCS_DIR = …/docs`, src/api/main.py:1310; `GET /api/docs/{slug}`). Any edit
  to the repo docs shows up in-app once the local clone updates (git pull / self-update). We
  do NOT — and should not — live-fetch from GitHub at runtime: that breaks offline-first /
  zero-network boot. So inheritance is via the bundled repo tree, refreshed on app update.
  (Optional nicety: a consented "view the latest on GitHub ↗" external link behind the
  invariant-#7 popup, for users who want the canonical online copy.)
- **Translation infra ✅ shipped, content ❌ mostly empty:** `_doc_path` serves
  `docs/i18n/<lang>/<file>` when a draft exists, else falls back to English (authoritative)
  with the honest machine-drafted banner + `X-OO-Doc-Lang` header (index.html:4105-4116).
  The GAP is that `docs/i18n/<lang>/*.md` is mostly UNPOPULATED (only fr QUICKSTART
  hand-seeded). The actual translation RUN (`scripts/translate_docs.py` on a machine with a
  local model, and/or community translation) is the remaining work.

**So:** reassure the maintainer the repo-inheritance is built; the real action is to
POPULATE the per-language doc drafts. **Elevates** the existing queue item *"Translated
docs: infrastructure shipped … TODO: run scripts/translate_docs.py on a machine with a local
model."*

**⏭ Open Qs (compile):** add a consented "view latest on GitHub" external link? prioritise
which docs first (USER_MANUAL, QUICKSTART)? machine-draft-now-then-human-review vs wait for
human translation (the banner already states machine-drafted + English-authoritative)?

---

## Item R — sidebar has a COLLAPSE button but no discoverable EXPAND button  [NEW]  ⏭ capture (quick win; needs +1 string ×12)

**Verbatim (09:06):** "There's a button to collapse the side bar containing the tabs,
however, there's no button to expand it back."

**Diagnosis (grounded — it's a DISCOVERABILITY bug, not a missing function):**
`toggleSidebar()` (index.html:3062) already toggles BOTH ways
(`collapsed`↔`expanded`), and the button (index.html:671, in `.sb-foot`) is still rendered
when collapsed (only `.lbl` text is hidden, CSS line 125). BUT the button is **static**: its
chevron always points `‹` (collapse direction) and its `title` is always "Collapse
sidebar" — so once collapsed it doesn't read as an expand control (and in the narrow icon
rail it's easy to miss next to the gear).

**Fix (small):** make the toggle **direction-aware** — give it an id, rotate the chevron
180° via `html[data-sidebar="collapsed"] #…  svg { transform:rotate(180deg) }`, and swap the
title to a keyed **"Expand sidebar"** in `applyUi` (currently "Collapse sidebar" is itself
unkeyed → key both). +1 new string ("Expand sidebar") ×12. Optionally add a second, more
obvious rail affordance (e.g., the collapsed brand/logo expands on click). Invariant #2
(sidebar may collapse to an icon rail, never off-canvas >600px) stays intact.

**⏭ Open Q (compile):** direction-aware toggle alone, or also make the collapsed
brand/hamburger expand for redundancy?

---

## Item S — comprehensive keyword-analytics rework: top keywords MIX all languages (unhelpful) → trans-language keyword families  [NEW — elevates the trans-language-equivalence queue item]  ⏭ capture + ACCEPT the keyword log

**Verbatim (09:09):** "We should do a comprehensive work on keyword analytics. For now, the
top keywords appear from all languages. It doesn't help. We've talk[ed] about keyword
trans-language families. If having the keyword log helps, I can send it to you."

**The problem (grounded):** top-keyword / trending / association views aggregate raw
normalized terms across ALL corpus languages, so `fr:élections`, `en:elections`,
`es:elecciones` are counted as THREE different terms; the ranking becomes an artifact of
which language has the most volume, not of importance — the cross-language signal is
fragmented and the list "doesn't help".

**Maps to the EXISTING queue item** *"Trans-language equivalence — LIVE analytics layer
(elevated): rings merge inside grouped trends/trending/associations/graph levels
(fr:élections + en:elections = ONE concept); cross-country recognition via
per-source-country split; guards stay (language-qualified members only, signature-supported
joins, per-language counts visible, user can split). Groundwork shipped (signatures + curated
ring file + first 10 rings from field log #1)."* → THIS is the "comprehensive keyword
analytics" the maintainer wants; **elevate from groundwork to a built feature.**

**Scope to define (compile):** (1) trans-language **FAMILIES as the aggregation unit** for
top-keywords/trending/associations/graph — per-language counts still visible + user can split
(the ruled guards); (2) language-aware views (top keywords per-language AND merged, with a
language filter); (3) merges respect the ruled **over-merge guards** (language-qualified
members only, signature-supported joins, never silent merge — the field-log-#1 guards);
(4) ties into the keyword-as-corpus windows (each family → a corpus). Maintainer position
stands: NOT a fan of capping; use as many keywords as possible (any cap must be DYNAMIC).

**Keyword log — YES, send it.** Grounding the rework in the live keyword distribution is
exactly how field reports #1/#4 produced the stoplists + the first 10 rings. The Settings →
"Download keyword log (.json)" export (the one Item M is about — slow, but fine), or the debug
bundle. I'll use it to: propose the next batch of equivalence rings from real co-occurring
cross-language terms, measure what share of the top-N is fragmented across languages (the size
of the problem), and validate the guards against real data.

**⏭ Open Qs (compile):** families as the DEFAULT view vs an opt-in lens? seeding = curated
ring file + signature auto-join + user edits (the ruled approach)? per-language counts always
shown (informed consent)?

**AFFECTED SURFACE flagged (maintainer 09:10):** the problem shows **prominently in the
keyword TREND screen** (Insights → trend, ooChart per invariant #16) — multiple language
variants of ONE concept render as SEPARATE trend series, fragmenting the trend line and
making the screen hard to read. So the family-merge must drive the **trend view** too (merged
series by default, per-language sub-series available + splittable), not only the top-keywords
list. Add the trend screen to the rework's acceptance criteria.

---

## Item T — "group sources by domain" buckets UNRELATED publishers under apps.apple.com (multi-tenant platform host ≠ publisher)  [NEW — data-quality bug]  ⏭ capture + DATA REQUEST

**Verbatim (09:13):** "The source subtab in the analytics tab allows the user to group
sources by domain. I'm not sure the domain extraction is working properly. Lots of sources
are assembled under apps.apple.com, and within it we find sources as surprising as La
Repubblica (Italy), Hufvudstadsbladet (Finland), RIA Novosti, Hong Kong Free Press, etc. It
doesn't help the user make sense of what they have in common."

**What I traced (grounded):**
- The analysis-window Source view = `#an-sources` ← `GET /api/insights/corpus-sources` ←
  `analytics/queries.py:354 corpus_sources()`, which groups by **`Source.id`** (one row per
  registered source; shows Source.name + Source.domain). I found **no explicit "group by
  domain" toggle** in the code — so CONFIRM which surface (this analysis-window Source subtab
  `#an-sources`, the Settings→Sources tab, or Insights); it changes where the fix goes.
- `Source.domain` is **`nullable=False, unique=True`** (models.py:404/443) ⇒ distinct sources
  CANNOT share `apps.apple.com` as their stored domain. So the bucket is NOT registered-source
  grouping — it's a host **derived** from article/feed URLs (`Article.url`) or a
  group-by-registrable-domain over a field that stored the full Apple URL.
- `apps.apple.com` is **nowhere in the repo catalog** — runtime data in the corpus.

**ROOT CAUSE — the smoking gun (by comparison inside `configs/sources.yml`):**
- Tenant-as-**SUBDOMAIN** platforms are already handled RIGHT: Substack stores
  `domain: thesequence.substack.com` / `importai.substack.com` / `adamtooze.substack.com` —
  each a DISTINCT host ⇒ distinct `Source.domain` ⇒ grouping keeps them separate. ✅
- Apple Podcasts puts the tenant in the **PATH** (`apps.apple.com/…/podcast/<name>/<id>`), so
  host extraction yields `apps.apple.com` for EVERY publisher's podcast ⇒ they all collapse
  into one meaningless bucket. ❌ Same trap: `youtube.com/@x`, `open.spotify.com/show/x`,
  `t.me/x`, `medium.com/@x`, `pod.link`, `anchor.fm`.
- So **"domain extraction" is not buggy per se — registrable/host domain is the WRONG identity
  key for path-tenant platforms.** Podcast RSS items also commonly set the item link to the
  Apple page, so article-URL-host grouping buckets episodes from many publishers there too.

**HONESTY ANGLE:** bucketing La Repubblica + RIA Novosti + Hong Kong Free Press together
because they share a DISTRIBUTION PLATFORM falsely implies an editorial/ownership relationship
— the SAME false-grouping the project fights (false triangulation, over-merge). A platform
bucket must be LABELED "shared distribution platform — not a publisher" and never imply
commonality.

**FIX DIRECTIONS:** (1) an `is_multitenant_platform(host)` classifier (sibling of
`is_commerce_domain`) + a registry of path-tenant platforms with the tenant path-segment rule;
(2) for those, the source IDENTITY / grouping key INCLUDES the tenant segment — mirroring how
Substack's subdomain already IS the identity; backfill existing apps.apple.com rows;
(3) ingest: prefer the publisher's own canonical link for `Article.url` when a platform feed
exposes it, else label the platform origin honestly; (4) don't let discovery or de-US-centring
treat a platform host as a publisher (ties audit-07's "10 named aggregator biases").

**DATA REQUEST (the fact I need):** the **Settings→Sources export** (or the debug bundle) for a
handful of those surprising sources — their `domain` + `rss_url`, and whether there is ONE
apps.apple.com source with mis-attributed articles vs MANY sources whose derived host is
apps.apple.com. That single fact picks the fix (extraction vs grouping-key vs attribution vs
ingest). The keyword log won't show this; the source export / debug bundle will.

**⏭ Open Qs (compile):** which surface exactly? identity-key change (include the tenant path)
vs honest-platform-label-only first? backfill existing rows?

---

## Item U — a precached, normalized, standardized multilingual keyword LEXICON (×12 UI languages): preconfigure families + KILL substring over-merge suggestions ("world cup"→"world", "United States"→"state")  [NEW — the seeding + guard layer for Items S/T]  ⏭ capture (collaborative design)

**Verbatim (09:17):** "I think we can work together on a way to have a precached, normalized,
standardized list [of] keywords in all of the UI available languages. This would help
preconfigure families, avoid recommendations such as: 'world cup' having as merging
recommendation the keyword 'world', or another example the keyword 'United States' have the
suggestion to merge with 'state'."

**Two problems it solves:**
1. **SEEDING families (Item S):** a curated, normalized, multilingual lexicon lets us PRE-build
   trans-language families instead of discovering them cold — the ruled "curated ring file +
   signature auto-join + user edits" seeding, ELEVATED to a standardized ×12 lexicon.
2. **KILLING bad merge suggestions:** the examples are **substring / partial-token false
   positives** — "world cup" ⊃ "world", "United States" ⊃ "state". The recommender is
   proposing merges on LEXICAL CONTAINMENT, not semantic equivalence. A lexicon of known
   multi-word concepts / named entities ("World Cup", "United States") lets the recommender
   treat them as **ATOMIC units**, never decomposed into their substrings.

**Honesty/method angle:** merge SUGGESTIONS must be SEMANTIC equivalence (same concept across
languages, signature-supported) NOT lexical containment. "world cup"→"world" /
"United States"→"state" are containment artifacts — exactly the false equivalence the ruled
over-merge guards forbid (language-qualified members only, signature-supported joins). This is
evidence the recommender currently LEAKS substring matches; the lexicon + an atomic-phrase rule
closes the gap.

**What the lexicon is (to design together):** a normalized, standardized, PRECACHED
keyword/concept list per UI language (12) — each concept with a canonical form per language,
known surface variants/inflections, a type (entity/place/org/event/common term), and
cross-language links (the family seed). **Bootstrap source:** Wikidata labels/aliases
(multilingual by construction — ties the de-US-centring Wikidata generator + the
wiki-as-living-source work) PLUS the EXISTING `configs/keyword_equivalents.yml` +
`configs/keyword_supergroups.yml` seeds. **Precached = bundled, local-first, zero-network at
runtime** (ships with the app; building/refreshing it is an offline tooling step like the
catalog / city gazetteer).

**Relationship to existing config:** `keyword_equivalents.yml` + `keyword_supergroups.yml`
already exist (ring/supergroup seeds). This = expand them into a standardized multilingual
lexicon + use it as BOTH (a) family seeds AND (b) an atomic-phrase / containment-aware GUARD in
the merge recommender. Folds into the Item S keyword-analytics rework as its seeding+guarding
layer.

**Collaborative ("we can work together"):** next step is a design pass — I propose the lexicon
schema + sourcing (Wikidata + existing seeds) + the atomic-phrase guard; maintainer steers.

**⏭ Open Qs (compile):** bootstrap = Wikidata labels/aliases vs hand-curated vs both? scope
order (entities/places/orgs/events first, common terms later)? how the lexicon overrides vs
feeds the live signature auto-join? precached size budget (12 languages × concepts)?

---

## Item V — airplane mode ON still shows GREEN "Collecting…"; should show a PAUSED (not-green) "Collecting paused"  [NEW — status-honesty bug]  ⏭ capture (implementable; +1 string ×12)

**Verbatim (09:34):** "When activating airplane mode, the top bar is still showing
'collecting' in green. Why not mark it as red and display collecting paused."

**Grounded:** the activity chip (`#activity` / `#activity-label`, index.html:689) is painted by
`_paintActivity()` (index.html:2226) from the `_bg` collecting label (set "Collecting N/M…" at
2611) with the green `bg` class. It NEVER consults online/offline state. The airplane state IS
known — `_paintNetwork(online)` (2435, fed by API `online` booleans at 2422/2520/2727/5133) —
but that state never reaches `_paintActivity`.

**Honesty angle:** showing green "Collecting…" while collection is actually paused is a
FABRICATED status — against degrade-loudly / no-theater. Airplane mode trips the kill switch
(Collect-Stop side effect), so the pass really stops; the chip must say so.

**Fix (small):** persist the online state in a module var when `_paintNetwork` runs, and in
`_paintActivity` show a PAUSED style + keyed "Collecting paused" when offline + a collect pass
is in-flight/scheduled. Use the go-OFF calm/grounded accent (invariant #14c's direction-aware
color), NOT a brand-new red that conflates meanings. +1 string ("Collecting paused") ×12.

**⏭ Open Q (compile):** "Collecting paused" vs "Paused (airplane mode)"? exact color = reuse
the go-off calm/grounded accent?

---

## Item W — move the "healthy"/backend-status indicator into the task-manager System tab  [NEW — extends invariant #4]  ⏭ capture (BLOCKED ON Item X)

**Verbatim (09:34):** "the 'healthy' status should be moved to the task manager."

**Grounded:** `#health` (index.html:690, "checking…"/healthy + a status dot) sits in the
top-bar status-cluster. Invariant #4 already moved VITALS out of the chrome into the
task-manager window's System tab (`#tm-system`). This extends that: health joins the same
System tab, decluttering the top bar (UI-shell §2 "minimal top bar").

**DEPENDENCY — BLOCKED ON Item X:** if the task manager doesn't open (the maintainer's report),
moving health INTO it hides health entirely. Land W only once X is confirmed (the TM opens
reliably). **Consider** keeping a MINIMAL chrome health signal (a tiny dot that turns red when
the backend is down) so a down backend is never fully hidden — informed-by-construction; decide
in compile. Keep the persistent `#tm-open` access (invariant #4).

---

## Item X — the TASK MANAGER DOESN'T OPEN (maintainer report); code path verifies CORRECT at HEAD → most likely a STALE/CACHED build  [NEW — repeated pain point ×3+]  ⏭ capture + DIAGNOSTIC REQUEST

**Verbatim (09:34):** "by the way, did I mention that the task manager doesn't work / open up
the task management interface?"

**What I verified at HEAD (code-level):**
- `#tm-open` (index.html:693) AND `#activity` (689) both `onclick="toggleVitals()"`.
- `toggleVitals()` (2869) sets `pop.hidden = false` (2872) — making `#vitals-pop` (708) visible
  — BEFORE anything that can throw; `_vitalsPrevFocus` IS declared (2573); `_ensureVitalsPoll`
  defined (2593); no strict mode.
- The inline app `<script>` (2189 — NOT `type=module`, so inline handlers resolve globally)
  passes **`node --check` cleanly** ⇒ `toggleVitals` IS defined (no syntax error abort).
- CSS: `.vitals-pop[hidden]{display:none}` else `position:fixed;top:52px;right:14px;z-index:60`
  ⇒ visible when not hidden.
- ⇒ **In current code, clicking the task-manager icon MUST open the dialog.** I could not
  reproduce "doesn't open" statically. (Even an init-time throw at the ooSubtabs wiring
  7734-7738 would NOT prevent opening — `toggleVitals` is hoisted — only break subtab switching.)

**Most likely cause:** a **STALE / browser-CACHED build** on the long-running field instance
(served index.html predates task-manager fixes, or the browser cached an old copy). Secondary: a
runtime error I can't see statically.

**DIAGNOSTIC REQUEST (definitive):** (1) **hard-refresh / relaunch** the app and re-test (rules
out cache/stale build); (2) if it STILL fails, open the browser **console**, click the
task-manager icon, and send the error + a screenshot. I can also **run-and-verify here** (launch
+ click) to confirm the current build opens it — say the word and I'll invest the detour.

**Why it matters:** this is the repeatedly-asked task manager (ledger ×3+). Resolving X UNBLOCKS
Item W (health-into-TM) and the whole task-manager vision.

**⏭ Open Q (compile):** stale build (most likely) vs a real runtime error — awaiting the console
output / hard-refresh result.

---

## Item Y — APP-WIDE chart rule: <10 datapoints → BAR graph (not dots); REMOVE the "early corpus… no curve interpolated" caveat, KEEP n=x  [NEW — RULING; amends invariant #16]  ⏭ ruling RECORDED (CLAUDE.md #16); impl PENDING + a baseline-honesty Q

**Verbatim (09:57):** "the 6 months view market data shows only 5 datapoints. I suggest to show
bars in this case. We should make a rule for the entire app's graph visuals so that when there
is less than 10 datapoints, the graph automatically switches to a bar graph. remove the mention
'early corpus: dots shown, no curve interpolated through sparse points (n=x)'. Keep showing the
amount of datapoints (n=x)."

**The ruling:** (1) **app-wide, every graph: n<10 → a BAR graph** (replaces the current
sparse=dots treatment); n≥10 → the systematic full-resolution line/curve. (2) **DROP** the
"early corpus: dots shown, no curve interpolated through sparse points" caveat sentence.
(3) **KEEP "n=x".**

**Where it lands (grounded):** both renderers — `ooChart()` (index.html:5622; `lineMin`=8 +
sparse-dots at 5690-5718; caveat at 5718) and `dashChartSvg()` (5387; dots-vs-line at
5410-5415; caveat at 5417). The caveat is the keyed string `t9("early corpus: dots shown, no
curve interpolated through sparse points")` (present in all 12 locales) → retire the references,
keep `n=${n}`. Amends invariant #16 (was: sparse→dots + caveat, lineMin=8); recorded in
CLAUDE.md #16 as impl-PENDING.

**TEST IMPACT:** `test_ui_invariants` #16 currently asserts **`"early corpus" in html`**
(test_repo_invariants.py:359) — removing the caveat BREAKS it; the test must flip to assert the
bar behaviour + caveat-gone when Y ships. (Why this is a deliberate slice, not an inline edit.)

**⚠ HONESTY WRINKLE — raised, NOT silently shipped:** a bar encodes value by LENGTH ⇒ implies a
ZERO baseline. For PRICE-LEVEL series (markets) that's both misleading AND useless — gold $1900
vs $1950 over 5 months render as ~equal full-height bars (a real ~3% move made invisible) —
exactly the visual distortion the project's "no fabricated visuals" ethic forbids. Bars-from-
zero are fine for COUNT/magnitude series (article counts, mentions — naturally zero-based;
`ooChart` already has a `zeroBase` opt, e.g. index.html:6466). **Proposed resolution (confirm):**
sparse bars anchor to the **window-MIN on a clearly-LABELED axis** (not zero) for level data so
differences stay visible + honest; true-zero baseline only for naturally zero-based/count
series.

**⏭ Open Qs (compile):** bar baseline for price-level data (window-min-labeled vs zero)? "<10"
strict (n≤9 → bars, n≥10 → line)? bar placement for IRREGULAR time spacing (market dates aren't
evenly spaced — bars at true x-position vs evenly categorical)?

---

## Item Z — critical analysis of the diagnostics tools; the keyword log (>60MB) is UNUSABLE in the maintainer→dev channel → make it a DIGEST (compute the analysis locally)  [NEW — maintainer asked "what makes them useful to you?"]  ⏭ analysis + proposal (offer to implement v1)

**Verbatim (10:17):** "Make a critical analysis of the diagnostics logging tools. What can we
make them more useful to you? The keyword log seems too slow to produce. It's OK if there's no
workaround. But I don't know how you will manage to analyse a several megabyte file. Why not do
parts of the analysis locally in the app to help you with easier to ingest files? The keyword
log I just produced is more than 60Mb…"

**THE FOUR TOOLS (src/api/diagnostics.py):**
- `/performance` (perf report): GOOD digest — env + store PRAGMAs + corpus counts + top-80
  endpoint latencies + selftest timings. Bounded, methodful, aggregate. **THE MODEL.**
- `/debug-bundle`: GOOD — runtime, corpus shape, scheduler + recent_runs(30), network verdicts,
  imports(50), law/wiki states, field_test, errors(300). Bounded.
- `/network` (preflight): GOOD — source/feed/calendar verdicts.
- `/keywords` (keyword log): **THE OUTLIER → 60MB.** It already computes the right AGGREGATES
  locally (families via `build_families`, `per_source_concentration` suspects, `language_mismatch`
  flags) BUT ALSO serialises the ENTIRE raw keyword list — up to **5000 PER LANGUAGE × ~16 langs
  ≈ 80k fat entries**, each with a per-keyword `language_signature` dict (lines 328-332, 270-289).
  THAT is the 60MB.

**CORE PROBLEM (verdict):** the diagnostics channel EXISTS for the maintainer→developer(me)
loop. A 60MB JSON CANNOT be pasted into chat or ingested by me in full — so the keyword log is
effectively **unusable in the very channel it was built for** (I'd be reduced to grep/sampling,
losing the holistic view). The other three work BECAUSE they're bounded digests. The maintainer's
instinct — "do parts of the analysis locally, give easier-to-ingest files" — is exactly the fix.

**WHAT MAKES A DIAGNOSTIC USEFUL TO ME (principles):** small enough to read WHOLE (target
≤~1MB, ideally a few hundred KB); AGGREGATE-FIRST (distributions/rates/top-N, not raw rows);
METHODFUL (method+caveat+n per metric — the honesty discipline doubles as machine-readability);
SAMPLED EXAMPLES (a handful per pattern, not all); STABLE SORTED schema (deterministic order ⇒
cross-run DIFFs = drift detection); LAYERED (small summary always + opt-in raw drill-down).

**PROPOSAL — keyword log → DIGEST (reuses existing computation):**
- KEEP: corpus, method, families (summarised: count + largest + a fragmentation metric),
  per_source_concentration (200), supergroups, overrides.
- REPLACE the 80k raw keyword list with: per-language counts, kind distribution, hidden +
  language_mismatch RATES (count+%), and TOP-N keywords per language (≈50-100, not 5000).
- ADD the analyses I do by hand AND that Items S/T/U need: language_mismatch top examples +
  total; trans-language family FRAGMENTATION measure (S); SUBSTRING/containment over-merge
  suspects (U: "world cup⊃world", "United States⊃state"); platform-host source suspects (T) if
  cheap.
- The FULL raw list becomes an OPT-IN (`?full=1`) companion for rare deep dives — never default.
- Result: a few-hundred-KB file I can read WHOLE, that directly feeds the keyword-analytics rework.

**ON SLOWNESS:** the all-mentions scan is inherent (real aggregates); the maintainer accepts it.
A digest still helps (far less to serialise/transmit). `/performance` already times
`keyword_export_streamed`, so any win is measurable.

**OFFER:** I can implement a v1 digest (`?digest=1` on `/keywords`, or a `/keywords/digest`
endpoint) immediately — it's also the substrate for S/T/U. Awaiting go-ahead on the digest
CONTENTS so it carries the right analyses.

**⏭ Open Qs (compile):** digest contents priority? `?digest=1` vs new endpoint? keep full raw as
opt-in or drop? target size cap?
