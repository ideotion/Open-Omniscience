# Alternative interfaces — the "GUIs" gallery

*Maintainer-ruled 2026-06-17. Status: shipped (experimental, opt-in). Lives in
Settings → GUIs.*

This document is the critical, professional comparison the gallery summarises
in-app. It explains **why** each alternative exists, **what** it changes versus
the current interface, and **who** it is meant to win — framed around the three
goals set for this work: **user retention, user adoption, and ease of access.**

---

## 1. Why alternatives at all — a critical read of the current GUI

The default interface ("Open Omniscience") is, by deliberate design, **honest,
dense, and complete.** Those are real strengths: caveats are visible by default,
there are no fabricated trust scores, it runs fully offline, it ships 12 locales
and 17 themes, and it is genuinely accessible (ARIA, focus traps, keyboard nav).

But measured against adoption and retention, the same qualities create friction:

1. **Density-first first contact.** Every surface front-loads method, caveats and
   long explanatory prose. This is ethically correct, but intimidating for a
   newcomer — a real bounce risk before the "aha".
2. **Navigation sprawl & overlap.** ~13 sidebar tabs across three groups, Settings
   with ~10 subtabs, and three overlapping analytical surfaces (Search vs.
   Analysis vs. Insights — a debt the project's own ledger records).
3. **Utilitarian visuals.** System font, flat panels, dense tables, a text-chip
   "at a glance". It reads as a tool, not a product; little dataviz-as-hero. This
   is the largest untapped adoption lever.
4. **Desktop-dense responsiveness.** Breakpoints exist, but the resting layout is
   desktop-first; on a phone the sidebar collapses behind a hamburger and tables
   get cramped.

No single interface can be optimal for the newcomer, the keyboard power-user, the
field reporter on a phone, the deep reader, and the dense-data analyst at once.
So instead of one compromise, the gallery offers **eight deliberate, coherent
points of view**, each argued below, and lets the user choose and compare them
live. The default stays the reference and the guarded baseline.

---

## 2. Architecture (how, without losing anything)

- **Shared-core shells.** `app.js` renders by element id (`$('briefing-feed')`,
  `getElementById('home-stats')`, …). Each alternative is a *scoped skin*
  (`html[data-ui="<id>"] …`) — plus, for two of them, a thin interaction layer —
  that reuses **100% of the existing render logic and endpoints**. Nothing is
  re-implemented, so *no functionality is lost* by construction.
- **Sandbox, not a fork.** The three canonical files (`index.html`, `app.js`,
  `app.css`) are untouched except for a tiny additive hook (the gallery boot
  script + the Settings → GUIs subtab). The default interface stays the
  invariant-guarded reference and remains the default.
- **Honesty preserved by construction.** Because every alternative restyles the
  *same DOM*, the ethical non-negotiables travel with it: caveats stay visible,
  the network-consent popup is unchanged, no interface invents a score, and the
  "deduced / never confirmed" labels remain. `tests/test_gui_alternatives.py`
  fails the build if any skin hides a caveat/consent surface.
- **Local-first.** Six interfaces are pure CSS (vanilla). Two — **Command** and
  **Canvas** — use **Alpine.js**, *vendored locally* (`src/static/guis/vendor/`,
  MIT, checksum-pinned, ~15 KB). It is served from `127.0.0.1`, never a CDN, and
  makes no network request, so the offline / anonymity posture is unchanged.
  A test pins the checksum and forbids any outbound URL in the gallery files.
- **Themes × skins.** Skins change layout, type, spacing and component shape but
  inherit the active **theme palette**, so all 17 themes keep working under every
  interface (e.g. Terminal + the Light theme = a dense daylight console).
- **Live switching.** Selecting an interface persists the choice (in the shared
  `oo.ui` blob) and reloads, so the skin applies cleanly from boot with no flash.

---

## 3. The eight interfaces

Each entry: **thesis → the critical argument vs. the default → who it wins and
why (retention / adoption / ease of access) → signature UX moves → responsive →
engine.**

### 3.1 Aurora — calm, progressive disclosure *(vanilla)*
- **Thesis.** Lower the cognitive load; reveal depth on demand.
- **Argument.** The default's biggest adoption risk is front-loading every method,
  hint and caveat at once. Aurora keeps the **caveats visible** (non-negotiable)
  but lets the *verbose method/plumbing* recede until asked for, with generous
  whitespace, a soft reading column and larger type.
- **Wins.** Newcomers and occasional users — **lower bounce, gentler first
  contact** → adoption + early retention.
- **Signature.** Aurora-wash backdrop built from the theme accent; borderless
  translucent sidebar; roomy cards that lift on hover; the caveat promoted to a
  gentle inline callout (more present, not less).
- **Responsive.** Single calm column; gutters tighten on small screens.

### 3.2 Atlas — mission-control dashboard *(vanilla)*
- **Thesis.** At-a-glance situational awareness; data is the hero.
- **Argument.** The default opens on a text-first briefing behind a left rail —
  no live overview, and the rail eats horizontal space the data wants. Atlas
  lifts navigation to a full-width **top bar** and turns the body into a dense
  grid of tiles.
- **Wins.** Returning daily users — **"always something live to see," one click to
  drill in** → retention. (Mirrors the project's own "Home → helicopter view"
  direction.)
- **Signature.** Top navigation (grouped nav flattened via `display:contents`,
  no DOM change); sticky glance strip; instrument-style tabular numerics; denser
  4-up briefing tiles.
- **Responsive.** Tiles reflow via auto-fit grids; the nav becomes a horizontal
  scroller.

### 3.3 Command — keyboard / command-first *(Alpine.js)*
- **Thesis.** Power-user velocity; everything a keystroke away.
- **Argument.** Features are spread across a deep tree; discovery is slow and
  mouse-bound. Command makes the search/command surface the centre of gravity.
- **Wins.** Journalists / OSINT analysts who live in the tool — **speed** →
  retention among the technical core; a credible "pro" story for adoption.
- **Signature.** A prominent omnibar plus an always-present launcher on Home: a
  fuzzy, arrow-key-navigable list of every section and key action, run with
  Enter; unmatched text falls through to a corpus search. Loud keyboard focus.
- **Responsive.** The launcher becomes a single-column sheet; full-width input.
- **Why Alpine.** The fuzzy-filter + selection state is genuine local interaction
  state — exactly what a tiny declarative framework is good at.

### 3.4 Field — mobile-first card stream *(vanilla)*
- **Thesis.** Thumb-friendly, one-handed, feed-like.
- **Argument.** The default is desktop-dense and degrades to an off-canvas drawer
  on a phone — the device a field reporter actually carries is second-class.
- **Wins.** Mobile / tablet / field users — **reach on the device people have on
  them** → adoption beyond the desk.
- **Signature.** A persistent **bottom tab bar** (icon-over-label, horizontally
  scrollable), a single-column card stream, 44px touch targets, sticky search,
  safe-area insets; scales **up** to a calm centred column on the desktop.
- **Responsive.** This *is* the mobile philosophy; it scales up rather than down.

### 3.5 Focus — zen / reader-first *(vanilla)*
- **Thesis.** Distraction-free deep reading and analysis.
- **Argument.** A persistent 250px rail, a full status cluster and a busy top bar
  all compete with content during the long sessions this tool is built for.
- **Wins.** Deep-work sessions (long reads, careful analysis) — **session length**
  → retention.
- **Signature.** Chrome recedes to a thin icon rail that **expands on hover/focus**
  as an overlay; a quiet top bar that wakes on demand; a wide typographic reading
  measure; panels dissolve into a single flowing column. Nothing removed (full
  a11y: keyboard focus expands the rail).
- **Responsive.** The rail narrows; the reading column stays central.

### 3.6 Terminal — maximum density *(vanilla)*
- **Thesis.** A cockpit for experts who want *more* on screen, fewer clicks.
- **Argument.** The opposite critique to Aurora: for a heavy analyst the default
  is comfortable but sparse and click-heavy.
- **Wins.** Power analysts / the OSINT-terminal crowd — **information per screen**
  → adoption among demanding users.
- **Signature.** Monospace, compact rows, square edges, hairline borders, `>`
  section prompts, tabular numerics, high contrast. Pairs with the Terminal theme
  for full hacker mode or a light theme for a daylight console.
- **Responsive.** Type scales down a notch; panes stack.

### 3.7 Canvas — spatial investigation board *(Alpine.js)*
- **Thesis.** Externalise the relational map an investigation really is.
- **Argument.** A list/tab tree flattens the web of related places, people,
  sources and dates. Canvas gives Home a spatial board.
- **Wins.** Differentiation + a genuine "wow" — **memorability and demo appeal** →
  adoption; an exploratory mental-model match for retention.
- **Signature.** A pan/zoom board where every section is a draggable node around a
  hub; wheel-zoom to a cursor anchor, drag to pan, drag a node to move it, click
  to open. The conventional surfaces stay below (no loss; a11y/no-WebGL fallback).
- **Responsive.** Touch pan/zoom via pointer events; board height adapts.
- **Why Alpine.** Pan/zoom/drag is real interaction state; Alpine keeps it
  declarative and small (no WebGL, consistent with the local-first, hand-rolled
  ethos).

### 3.8 Editorial — magazine / newsroom *(vanilla)*
- **Thesis.** Present the output like a publication, for the people who make them.
- **Argument.** The default reads like a database admin console — functional, but
  emotionally flat for the journalist the app is built for.
- **Wins.** The journalist persona — **emotional resonance**: the briefing becomes
  a front page → retention and word-of-mouth adoption.
- **Signature.** A bundled serif display face, a masthead, a **featured lead** per
  section (full-width headline, multi-column body), department-style section
  heads — and the honesty caveat reframed as an italic figure **caption** (more
  prominent, never hidden).
- **Responsive.** Multi-column on desktop, single column on phones.

---

## 4. How to test them live

Settings → **GUIs**. Each interface shows a mini layout preview, a one-line
argument, and **Use this interface**. Switching reloads the app to apply (one
reload, like a heavy theme change). The default card resets you to the original.
The choice is local (`oo.ui.gui` in `localStorage`); nothing is sent anywhere.

---

## 5. Honesty & ethics (what is enforced, not just promised)

- **`tests/test_gui_alternatives.py`** fails the build if any skin hides a
  caveat/consent surface (`.card-caveat`, `.tier-caveat`, `#net-consent`,
  `#net-coach`), if any gallery file references an outbound URL, if Alpine's
  pinned checksum drifts, or if a skin rule is not scoped to its `data-ui`.
- **`test_ui_invariants` (#30)** pins the additive wiring so the gallery cannot be
  silently dropped, and confirms the default interface remains the guarded one.
- Every interface preserves: caveats visible by default, the one network-consent
  popup, no composite scores, "deduced / never confirmed" labels, and the full
  feature set (it is the same DOM and the same endpoints).

---

## 6. Known limitations & next steps

- **Browser-unverified.** Per the project's conservative rule for UI that cannot
  be click-tested in this environment, the skins are validated by `node --check`,
  the invariant + gallery tests, and careful static review — but they need a
  human click-through across themes and breakpoints before being called done.
- The per-interface **"why" detail** is English in-app (the short tagline is
  translated ×12); this document is the full, authoritative rationale.
- Future: optional per-interface thumbnails from real screenshots; a few skins
  could gain small progressive-enhancement touches; user-tunable density per
  interface.
