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
