# Two interfaces, one argument — "Console" vs "Desk"

> You asked for a *contradictory* argument: not a defense of the 0.05 redesign, but
> an honest case that it might be the **wrong** interface for this app — and a
> concrete alternative to test it against. This document is that argument. The two
> interfaces ship side by side so you can run both on the same data and judge for
> yourself.

---

## 0. First, re-ground in what this app actually is

Before arguing about chrome, the non-negotiables (from `ETHICS.md`,
`PRODUCT_SYNTHESIS.md`, the Munich Charter):

- **One user, one machine, loopback only, offline-first.** No accounts, no cloud,
  no telemetry. Often run in a Qubes AppVM with the network qube *detached*.
- **A truth-seeking operative who is not fond of computers.** An investigator /
  journalist whose job is to *understand reality and communicate it credibly*.
- **The product is trust.** Provenance, source verification, "measured not
  estimated," tamper-evidence. The Munich Charter (truth, verify sources, protect
  sources, resist propaganda) is the spine.
- **Sovereignty as aesthetic.** The tool should *feel* like it belongs to the user,
  not to a platform.

Any interface must be judged against *those*, not against "does it look like a
2025 SaaS product."

---

## 1. The charge sheet against "Console" (the 0.05 redesign)

Steelmanning the case that 0.05 is the wrong direction:

1. **It dresses a sovereign tool in surveillance-capitalism clothes.** Persistent
   left sidebar, status pills, command palette, a customization drawer with eight
   themes — this is the visual grammar of Slack, Linear, Notion: *cloud SaaS*. For
   a user who distrusts Big Tech and works on sensitive stories, that grammar can
   read as "another app that watches me," undermining the one thing that matters
   most here: trust. The look fights the values.

2. **It optimizes for the demo, not the work.** The brief included "make a
   journalist say *can I have it?*" — a five-second over-the-shoulder reaction.
   Designing for that pulls toward dashboard flash (gradients, animated counts,
   theme zoo) and away from the quiet, reading-heavy, document-centric reality of
   investigation. The best tools for deep work (a text editor, a notebook) are
   *plain*. Console may be impressive and shallow.

3. **Customization is a tax disguised as a gift.** Eight themes, accent swatches,
   density, font scale, per-module hiding. For *Amara* (not fond of computers) every
   one of these is a decision she didn't want and a way to misconfigure her tool.
   "Highly customizable" served the brief's wording and the *designer's* idea of
   generosity — but a genuinely simple tool is **opinionated**: it makes the right
   call so the user doesn't have to. Choice is cognitive load.

4. **The information architecture is still the software's, not the user's.** Console
   renamed and regrouped the tabs, but the menu is still a list of *modules*
   (Search, Sources, Insights, Markets, Custody…). Amara doesn't think in modules;
   she thinks in a **case**: "I'm chasing this story — gather, read, connect, prove,
   publish." Both 0.04 and 0.05 make the user translate their *job* into the app's
   *features*. A persistent nav of nine destinations is a map of the codebase.

5. **Chrome competes with content.** A fixed sidebar + top bar permanently spend
   ~250px and a horizontal band on *navigation the user uses for two seconds per
   session*. The thing they actually do — read articles, scan results, compare
   diffs — gets the leftovers. Investigation is reading; Console under-serves
   reading.

6. **The "wow" is borrowed, not earned.** A palette and themes are *table stakes*
   in modern apps — impressive precisely because they're familiar. The genuinely
   differentiating, "I've never seen that" features here are the *substance*:
   offline Wikipedia edit-war detection, tamper-evident custody, "every number is a
   real COUNT(\*)". Console decorates; it doesn't dramatize what's actually unique.

That is a serious indictment. It deserves a real alternative, not a rebuttal.

---

## 2. In Console's defense (so the argument is fair)

- A persistent nav is **discoverable**: nothing is hidden, which matters for a
  novice who doesn't yet know what the tool can do. Hub-and-spoke models hide
  power behind a click and a guess.
- Customization is **opt-out**: defaults are sane; a user who ignores the drawer
  loses nothing. And theming genuinely helps the eye-strain/late-night reality of
  the work, and the accessibility (high-contrast, text size) of *real* users.
- The "SaaS grammar" is also just **current usability convention** — people know how
  to use it on day one. Novelty for its own sake has its own tax.
- It is still **100% offline and dependency-free**. The grammar is borrowed; the
  substance (no network, no telemetry) is not.

Both positions are legitimate. The way to resolve it is not more arguing — it's to
**build the antithesis and use both**.

---

## 3. The antithesis: "Desk"

If Console is a **broad operations console** (everything always one click away,
maximally flexible, modern-app grammar), **Desk** is the opposite thesis:

> **An investigator's desk: calm, opinionated, content-first, and task-framed.
> Almost no chrome. One job at a time. The interface gets out of the way of reading
> and thinking.**

Concrete commitments where Desk deliberately *disagrees* with Console:

| Dimension | Console (thesis) | Desk (antithesis) |
|---|---|---|
| Navigation | Persistent left sidebar (always visible) | **No persistent nav.** Navigation is *on demand* — a calm home, a "Go to…" overlay, and ⌘K. Chrome appears only when summoned. |
| Entry point | A status dashboard | **A job-framed home:** "What are you working on?" → Gather · Find & read · Connect · Verify & share. Framed by the user's task, not the app's modules. |
| Customization | 8 themes, accent, density, font, module toggles | **Two themes only** (Paper / Ink), no knobs. Opinionated. The tool decides so you don't. |
| Aesthetic | Modern app console (sans, pills, gradients) | **Editorial / print:** serif headings, paper warmth, generous margins, reading measure. Feels like a newsroom, not a SaaS. |
| What gets the space | Navigation + status, then content | **Content.** A single centered reading column; tables and the article reader get the room. |
| Trust signal | A status pill | A persistent, quiet **"Local · Offline · Nothing leaves this machine"** line — sovereignty stated, not implied. |
| Demo reaction | "Slick!" | "…oh, this is *calm*. And it's all mine." A slower, deeper kind of wow. |

What Desk **keeps** (because it's the point of the app, not chrome): every feature
and every working endpoint. Desk and Console share the exact same engine and the
same content panels — they differ *only* in shell, navigation model, IA framing,
and aesthetic. That's deliberate: it keeps the experiment controlled, so what you're
comparing is **the philosophy**, not which one I happened to wire up more carefully.

---

## 4. How to judge them (rubric)

Score each against the values — not against your gut "which looks nicer":

1. **Trust** — which one *feels* like it belongs to you and won't betray you?
2. **Calm vs capability** — which lets you think? which makes power findable?
3. **Novice path** — drop *Amara* in cold: which gets her to a result faster, with
   less fear?
4. **Power path** — *Daniel* on the keyboard: which gets out of his way?
5. **Reading** — open a long article / a Wikipedia diff in each. Which is the better
   place to *read*?
6. **The 5-second test** — show a colleague each. Which provokes "can I have it?" —
   and is that the reaction you actually want to optimize for?
7. **Fit to ethos** — which one would you trust to run with the network detached in
   a Qubes vault?

---

## 5. Predicted pros / cons (my honest bet, to be tested)

**Console** — *Pros:* discoverable, conventional, flexible, accessible knobs, demo
shine. *Cons:* chrome-heavy, decision load, generic-SaaS feel that may erode trust,
IA still module-centric.

**Desk** — *Pros:* calm, content/reading-first, opinionated (no config tax),
task-framed entry, an aesthetic that *reinforces* sovereignty and trust. *Cons:*
power is one summon away (a click/keystroke), fewer accessibility knobs, less
immediately "impressive," novelty has a small learning cost.

---

## 6. My recommendation (synthesis — provisional, pending your test)

I expect the right answer is **neither pure Console nor pure Desk**, but a synthesis
that leans on Desk's *values fit* and Console's *discoverability*:

- **Adopt Desk's task-framed home and editorial calm** as the default mood. The job
  framing ("gather / read / connect / verify") is the single biggest fix to the
  "IA is the codebase" critique.
- **Adopt Desk's restraint on customization:** ship two excellent themes
  (Paper/Ink) + a text-size control for accessibility, and **cut** the accent /
  density / module-hiding sprawl. Opinionated beats configurable here.
- **Keep a *quiet, collapsible* nav from Console** for discoverability — but
  collapsed by default, so content leads and the nav is there when wanted.
- **Keep ⌘K** (it serves both novice and power user and is genuinely useful).
- **Dramatize the substance, not the chrome:** make custody, offline Wikipedia, and
  "real counts" the visual heroes — that's the earned wow.
- **Lead the trust line everywhere** ("nothing leaves this machine"). It is the
  brand.

But that's a hypothesis. Run both, score them against §4, and tell me where reality
diverges from my bet — then I'll fold the verdict into a single 0.06.

---

## 7. Running both at once

Both interfaces are served by the same local backend on the same data:

- **Console** → `http://127.0.0.1:8000/`  (the default)
- **Desk** → `http://127.0.0.1:8000/desk`

The installer creates **two desktop icons** — *Open Omniscience* (Console) and
*Open Omniscience — Desk* — so you can launch either, or open both windows together
and compare them tab-for-tab on identical data. Pick a winner (or ask for the
synthesis) and we collapse back to one in 0.06.
