# UI shell & navigation redesign — action plan

> **Status:** maintainer-commissioned 2026-06-13 (field session); awaiting
> review. Planning only — nothing implemented yet. Companion to
> `SCRAPING_AUTOMATION_PLAN.md` (the content-first backend) — this is the
> content-first *front end*. Ledger pointer: CLAUDE.md UI invariants + queue.

## The through-line

The maintainer's many 2026-06-13 UI comments are one idea: **the app should
present DATA, with a calm, consistent shell; the mechanics recede.** A single
navigation grammar everywhere, a minimal top bar, a content-maximised Home,
an always-on search that opens real analysis, and indexing/scraping that just
happen in the background.

This refines (never regresses) invariants #2, #3, #4, #8, #14, #15, #17.

---

## 1. ONE universal navigation grammar (applies app-wide)

**Ruling:** lateral (left sidebar) = the MAIN app tabs; **vertical subtabs
near the top of the content area = subcategories** of the current tab. Same
pattern in Home (card families), Insights (its sections), Settings, the
corpora/search window, and every future multi-section surface.

- Subtabs sit **just below the top bar**, horizontally, close to the top of
  the screen (the maintainer: "bring all subtabs closer to the top").
- The left sidebar stays (invariant #2 — collapsible to the icon rail, never
  off-canvas above 600 px). Lateral = where am I; subtabs = which facet.
- A reusable subtab component (one implementation, themed, keyboard-operable,
  ×12, hover-bubble aware) so the grammar is literally the same everywhere —
  enforced by a new invariant test once built.

## 2. The minimal top bar

**Ruling:** above the subtabs, the ONLY things present are —

1. the **always-on search bar** (see §4),
2. **status** (online/offline + health, compact),
3. **task-manager access** (opens the window from SCRAPING_AUTOMATION_PLAN
   Step 7; replaces today's vitals popover as the entry point),
4. **help** access,
5. the **language picker** (invariant #15 — native names, flag = convention),
6. the **airplane button**, moved up here (see §3).

- Constant footprints preserved (invariant #3): nothing reflows as
  hosts/labels change.
- The version stays out of the chrome (invariant #4). The compact vitals
  (CPU·RAM·↓) move *into* the task-manager window's System tab; a minimised
  animated indicator in the top bar is the at-a-glance + click target.

## 3. Airplane button — placement + honest color semantics

**Ruling:** move it to the top bar; **no text label** (hover bubble is enough,
invariant #17). Keep airplane glyph + FILL = state (invariant #14 untouched).
**New:** the online↔offline transition uses **different colors by direction**,
and the chosen color is **coherent with the icon's on/off state** —

- Offline/engaged (filled): a calm "safe/grounded" color; going-offline
  transition flashes that same family (not an alarming red for the *safe*
  action).
- Online/active (outline + accent): a distinct "live network" color; the
  going-online transition (the consented one) uses that family.
- Rationale: today a single red transition conflates the two opposite
  meanings. Color should *encode which way you're crossing* and match where
  you land. (No fabricated security; airplane mode is still app-layer only,
  stated in the hover.)

## 4. Search — bigger, always-on, opens real analysis

Today: a 560 px omni box with a "Ctrl K" kbd hint that opens a command
palette (`index.html:137,641,646`). Rulings:

- **Larger search box, on top, always visible.** It is the primary verb of
  the app.
- **Remove the visible "Ctrl K" hint** (`index.html:646`). The shortcut can
  still work, but it is not chrome. (Small-screen placeholder already hides
  at ≤560 px, `index.html:540` — keep/extend: drop the overlaid text on
  small screens.)
- **Permanent "Advanced" button** on the bar — always-there entry to the
  advanced query/filters, not hidden behind a keystroke.
- **Shortcuts list** moves into the Help/notice AND becomes **viewable +
  editable in Settings** (a keybindings panel) — discoverable, not folklore.
- **Enter → the advanced-search WINDOW** (this is the corpora system flagship,
  already designed): searching one or many articles opens a dedicated
  analysis window with sub-tabs — **keyword analysis · mindmap · link
  analysis · source analysis · When/Where/Who · sentiment · related**, plus
  the search-only **Advanced search** sub-tab (dates/keywords/sources/tags/
  region/language). See "Why you can't find it yet" below.

### Why the advanced-search window seems missing (honest status)

It is **partially built, by design of the slicing — not lost.** Shipped
(T13 slice 1): the Ctrl-K palette omnibar (index-backed federation, first
3 per group). Shipped (T10 slice 1): the keyword→corpus window with
Trend/Articles/Links sub-tabs only. **NOT yet built:** the full
Enter→corpus-of-articles window with the mindmap/source/sentiment/WWW/
competitive sub-tabs and the Advanced-search tab. That remaining slice is
the single most-requested thing here — promote it in the build order.

## 5. Home tab — content-maximised

- **"At a glance" stats strip → permanent, compact, at the very TOP** of
  Home (today it is pushed down, `index.html:731`). One slim horizontal
  strip: articles · sources · source_groups · keywords · commodity_prices ·
  external_sources · article_links · article_analyses · mentioned_dates.
  Small, always visible, never a screenful.
- **Remove the hero card** ("Understand the world as it really is…",
  `index.html:688-690`) — ruled; takes space, unkeyed.
- **Remove the onboard "corpus is empty" card** (`index.html:675-684`) →
  replaced by the guided first-launch wizard (#24).
- **Remove the Quick actions section** (`index.html:738`) — ruled.
- **Cards take the full width**; today the grid shows ~3 because cards are
  too large. Redesign the card so 4+ fit on a normal screen, denser but
  still one-measured-signal-per-card (evidence-tiered, invariant #9 intact).
- **Family-type colors + families as vertical subtabs**, with an **"All
  cards"** subtab. (Maintainer asked my opinion — see below.)

### My opinion on card families as vertical subtabs

I like it, with one refinement. Families-as-subtabs is the right call: it
applies the universal grammar (§1), gives the color system a home, and lets
a user say "show me only integrity cards" without a filter menu. The
refinement: make **"All cards" the default** and order it by evidence
strength/recency (not by family), so the landing view is still a single
prioritised feed — the families are a *lens*, not a wall the user must sort
first. Color = the family hue as a left border/accent on each card so the
feed stays scannable even in "All". This keeps the calm-feed feel while
making the taxonomy visible and navigable.

## 6. Insights tab

- **Auto-index in the background; remove the "Index corpus" button**
  (`index.html:1287`) and its palette action (`index.html:2655`). Indexing
  follows ingest automatically (the index_article hook already runs at
  ingest — extend it so Insights is never "stale waiting for a click"); a
  background top-up replaces the manual reindex. The user never thinks about
  it. Surface freshness honestly (a small "indexed through <time>" note), but
  no button.
- **Present Insights' sections as subtabs** (universal grammar §1) instead of
  a long scroll.

## 7. Bugs found while investigating (diagnosed, fix queued)

- **Back button returns to the passphrase screen.** Root cause: tab
  navigation uses `history.replaceState` (`index.html:2524`), so tabs add no
  history entries; and a locked API response does a full
  `location.href = "/unlock"` (`index.html:2451`). After unlocking, the only
  prior history entry IS /unlock, so Back lands there. **No, this is not
  good.** Fix: use `pushState` for tab navigation (Back moves between tabs),
  and after a successful unlock navigate to "/" with `replaceState` so
  /unlock never sits in history.
- **"Scraping stopped" is the interval design, not a crash.** The scheduler
  runs one pass, then `self._stop.wait(interval_s)` for `interval_minutes`
  (`src/scheduler/runner.py:326-327`). It did not fail — it is idling until
  the next interval. The arbitration popup ("Another network task is
  running… Start anyway?") fires because run-now is non-overlapping. The fix
  is the content-first ruling below — continuous collection makes the idle
  gap and the in-face popup disappear.

## 8. Content-first scraping — the front-end consequences (cross-ref)

Reinforces `SCRAPING_AUTOMATION_PLAN.md`:

- **The app starts in AIRPLANE MODE** (offline) on every boot — zero-network
  boot is already the design; make it explicit and visible. Nothing scrapes
  until the user crosses online once (the one consent).
- **When online, scraping is PERMANENT/continuous** — replace the
  run-once-then-idle interval with a continuous fair-ordering loop. The
  cross-kind arbitration popup is demoted: a new scrape request **queues**
  into the task manager instead of interrupting the user with a modal
  (DB-writer collisions still serialise, but invisibly — the user sees a
  queued job, not a question).
- Scraping config optimised for speed (parallelism, §SCRAPING Steps 2–4)
  while per-host ethics hold.

---

## Acceptance themes

- One subtab component reused in ≥3 surfaces (Home/Insights/Settings),
  invariant-tested.
- Top bar contains exactly the six elements in §2; nothing else above the
  subtabs; constant footprints.
- Home renders the at-a-glance strip on top + a denser card grid (4+ wide)
  with family subtabs incl. "All"; hero/onboard/quick-actions gone.
- Search bar: larger, no Ctrl-K text, permanent Advanced button; Enter opens
  the full corpora window with all analysis sub-tabs.
- Insights: no Index button; background indexing; sections as subtabs.
- Back button cycles tabs, never the passphrase. App boots offline.
- Every new string ×12 locales; informed-consent layering preserved.
