# GUI Redesign — "0.05"

> A ground-up redesign of the Open Omniscience interface, reasoned from the user
> outward. This document is the *why*; `src/static/index.html` is the *what*.
> Read this first if you want to understand (or argue with) the decisions.

---

## 0. The brief, restated

Redesign the entire GUI for a specific person: **a truth-seeking operative — an
investigator/journalist who is *not* fond of computers**, who wants to understand
the world as it really is and to communicate findings credibly. The result must be
slick, beautiful, adaptable, highly customizable, simple *and* deep, and good
enough that a colleague glancing over a shoulder says *"what is this — can I have
it?"* It must respect what the project already is: **single-user, loopback-only,
offline-first, dependency-free, no telemetry**, governed by the **Munich Charter**
(truth, source verification, privacy, no propaganda).

### Engineering stance (and the honest tradeoff)

The previous UI is a single 2,200-line `index.html` wiring ~110 functions to ~150
API endpoints. Those functions *work and are tested*. A from-scratch rewrite would
have produced a prettier shell with a high chance of silently broken buttons — the
exact opposite of a tool whose entire selling point is **honesty**. So this is a
**total redesign of everything the user sees and touches** — visual language,
layout, navigation model, information architecture, naming, onboarding,
customization, and two brand-new surfaces (a Home dashboard and an in-app Docs
reader) — built *on top of the proven data layer*, with every original element ID
preserved so nothing regresses. Dependency-free remains absolute: **no CDN, no web
fonts, no framework** — one self-contained file that runs with the NetVM detached.

---

## 1. Personas (who we are actually serving)

**Amara — investigative journalist, 44. Primary persona.**
Covers procurement corruption. Brilliant reporter, reluctant computer user. Works
on sensitive stories and is (rightly) paranoid about surveillance and data loss.
*Needs:* find things fast across her own corpus; prove a document is authentic and
unaltered; export something she can hand an editor or a court; never feel stupid.
*Fears:* losing work, being tracked, jargon, looking amateur next to a "tech" colleague.
*Win condition:* she opens the app and immediately knows what to do, and what she
produces looks and *is* trustworthy.

**Daniel — freelance OSINT researcher, 29. Power persona.**
Semi-technical, fast, keyboard-driven, runs many sources. *Needs:* density, batch
operations, trends/associations, market correlations, keyboard shortcuts, a command
palette. *Fears:* hand-holding that slows him down; hidden features.
*Win condition:* he never has to touch the mouse and finds advanced power on tap.

**Sister-of-the-cause — the "operative", 50s. Values persona.**
Distrusts Big Tech; wants sovereignty. *Needs:* proof nothing phones home; offline
operation; plain explanations of what each action does to her network exposure.
*Win condition:* she can read, in the app, exactly what it will and won't do.

**Elliot — the editor, 38. Recipient persona.**
Never opens the app; *receives* its outputs. *Needs:* exports that are legible and
verifiable on their own. The UI serves him indirectly: evidence bundles, signed
custody, clean CSV/JSON.

**Design implication:** lead for Amara (clarity, guidance, trust), layer in Daniel's
depth so it never gets in her way (progressive disclosure + command palette),
honour the operative's sovereignty in copy and behaviour, and make Elliot's
artifacts first-class.

---

## 2. Design principles (derived, not borrowed)

1. **Clarity over cleverness.** Plain verbs, human labels, one obvious primary
   action per screen. Jargon ("ingest", "corpus", "Merkle root") is translated or
   explained inline, never assumed.
2. **Trust is the product.** Verifiability, provenance and "this number is real,
   not estimated" are surfaced, not buried. The aesthetic should *feel* like an
   instrument, not a toy.
3. **Progressive disclosure.** Simple by default; depth one click away. Advanced
   panels collapse; rarely-used modules can be hidden entirely.
4. **Customizable, because trust is personal.** Themes, accent, density, font size,
   layout, and *which tools even appear* are the user's to set — and persist
   locally only.
5. **Honesty in the interface.** If a capability depends on an optional extra, the
   UI says so instead of pretending. Nothing fakes success.
6. **Sovereign by construction.** No external requests of any kind. The look is
   achieved with system fonts and hand-built SVG icons.
7. **Keyboard-first is also accessibility-first.** A command palette and shortcuts
   serve Daniel *and* make the whole app reachable without precise mousing.

---

## 3. Per-tool analysis — pros, cons, decision

The old top-tab set: *Search · Ingest · Sources · Database · Markets · Insights ·
Wikipedia · Chain of custody · Settings.* Evaluated one by one for our personas.

| Old tab | Pros | Cons | **Decision** |
|---|---|---|---|
| **Search** | The core act. Everyone needs it. | Buried as one tab among nine; no orientation for a new user. | **Keep & elevate.** Becomes the heart, reachable instantly; a new **Home** gives orientation around it. |
| **Ingest** | Necessary to pull data in. | "Ingest" is engineer jargon; intimidating; conflated scheduler + manual fetch. | **Keep, rename → "Collect."** Lead with the simple manual action; the scheduler is "Automatic collection," framed as set-and-forget. |
| **Sources** | Credibility lives here; provenance starts with *where*. | Dense tables; felt like admin, not journalism. | **Keep, reframe as "Sources" (your newsroom's beat list).** Restyled to read like a library, not a database console. |
| **Database** | Honest live counts; backup/restore. | "Database" means nothing to Amara; she has a *library/archive*, not a DB. | **Keep, rename → "Library."** Same real counts and world-coverage, framed as "what you've gathered." |
| **Markets** | Powerful for "follow the money" investigations. | Irrelevant to most stories; heavy, niche; clutter for Amara. | **Keep, mark Advanced, hideable.** Off the critical path; one toggle removes it for users who don't do financial work. |
| **Insights** | The visual showpiece — trends, associations, map. The "wow." | Was a quiet middle tab; under-sold. | **Keep & promote.** This is a headline feature; given prominence and polish. |
| **Wikipedia** | Strong fit: "the world as it really is," offline knowledge, edit-war detection. | Two different things (live tracking vs heavy offline dumps) split across tabs confusingly. | **Keep.** Tracking stays here; heavy dumps stay in Settings, clearly cross-linked (already done in prior work). |
| **Chain of custody** | The trust differentiator. This is what makes Elliot trust the output and Amara look professional. | Named in legalese; felt like a vault few would open. | **Keep, rename → "Evidence & custody," promote.** Part of the "what is this?!" moment. |
| **Settings** | Needed. | Was a junk drawer (prefs + keyword filter + dumps + backup). | **Keep, restructure.** Plus a new live **Customize** drawer for look-and-feel so cosmetic tweaks don't require a tab trip. |

### New surfaces added

- **Home (dashboard).** *Rationale:* Amara needs orientation, not a blank search box.
  Status at a glance (corpus size, sources, scheduler, last activity), big quick
  actions ("Search," "Collect now," "Verify a document"), and an empty-state that
  teaches. This is the single biggest usability win for the primary persona.
- **Help / Docs reader.** The user explicitly asked for direct access to the detailed
  manual. A first-class **Help** surface renders the User Manual (and other docs)
  *inside* the app — searchable, offline, no leaving the tool. Also reachable from
  the top bar (`?`) and the command palette.

### Resulting information architecture

The flat 9-tab strip becomes a **grouped sidebar** (collapsible to icons), ordered
by how the work actually flows:

- **Investigate** — Home · Search · Insights · Wikipedia · *Markets (advanced)*
- **Collect** — Collect · Sources · Library
- **Trust** — Evidence & custody
- **System** — Settings · Help

Grouping turns "nine equal strangers" into "four intentions," which is how Amara
thinks ("I want to *find* something" / "I want to *gather*" / "I want to *prove*").

---

## 4. The "wow" — what makes a journalist lean in

- **A coherent visual system.** Deep "ink" dark theme by default with a confident
  single accent, generous spacing rhythm, real typographic hierarchy, monospace for
  data/hashes, soft depth, and restrained motion. It reads as *instrument*, not
  *dashboard template*.
- **Command palette (Ctrl/⌘-K).** Type to jump anywhere or run any action or open
  any doc. Power for Daniel; a "what can I even do here?" map for Amara.
- **Live Customize drawer.** Theme presets (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), accent swatches, density, font size, sidebar collapse,
  and **module visibility** — all instant, all local, all persistent.
- **A Home that orients**, an onboarding that teaches, and empty states that guide.
- **Trust, made visible.** Custody/verification and "measured, not estimated"
  framing are part of the aesthetic, not fine print.
- **Total offline integrity.** No network calls for the chrome — which is itself a
  feature you can *show* a security-conscious colleague.

---

## 5. Customization model

Look-and-feel is stored in `localStorage` (`oo.ui`) — never sent anywhere — so it
is instant and survives offline. Functional preferences (default result limit, base
theme) continue to persist server-side via `/api/settings`. Customizable: theme
preset, accent colour, density, font scale, sidebar state, and the set of visible
modules. Sensible defaults mean a first-run user touches none of it.

---

## 6. What I deliberately did **not** do (honesty)

- **No framework / build step / CDN.** Would break the offline, auditable, sovereign
  ethos for cosmetic gain. Vanilla, single file, system fonts, hand-drawn SVG.
- **No fabricated features.** Every button maps to a real, working endpoint. Capability
  that depends on an optional extra still says so.
- **No silent backend changes** beyond an additive, read-only, allow-listed docs
  endpoint (`/api/docs`) to power the Help reader.
- **The free-text language inputs stayed free-text** (already noted in OPEN_QUESTIONS);
  redesign doesn't invent dropdowns that the backend can't back.

---

## 7. Status

`0.05` is now the repository's **default branch** (mainline); earlier lines (0.04
and before) remain in git history. Functional parity is preserved (same element
IDs, same wiring); the change is everything *around* that engine. The default ships
**two** interfaces — Console (`/`) and Desk (`/desk`) — compared in
[`GUI_DIALECTIC.md`](GUI_DIALECTIC.md).
