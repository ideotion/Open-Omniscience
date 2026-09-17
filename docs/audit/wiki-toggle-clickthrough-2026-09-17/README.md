# Wikipedia-stream toggle — Chromium click-through, 2026-09-17

Q1128 = a's sandbox half: **Chromium-verified (remote sandbox) · awaiting the
maintainer's own UX pass.** Five locales × three states, driven against a real server
(`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1`, port 8099), zero findings.

`walk.py` is the harness that produced this, kept beside the record so the run can be
repeated rather than believed.

## What was walked

`en` · `ar` (RTL) · `zh` · `de` · `fr`, each in `running`, `halted` and `stopped`.

## What it asserts, per surface and per locale

Per **surface**, never over a concatenation: the recorded defect is a locale check over
two elements' joined text passing while one of them stayed English, because the other
one translating changed the string enough.

- the button exists in the chrome, in every locale;
- its **footprint is constant** across all three states (invariant #3) — measured 34 px
  wide in all fifteen combinations;
- the mark's **FILL is the state** (invariant #14's grammar: one constant glyph, never
  an action glyph) — `currentColor` for running, `none` otherwise;
- the hover **names what the lane contacts** in every state (a hover is a consent
  surface), and the two host names survive every translation **verbatim** — a localized
  hostname is an unreachable address printed to an operator;
- the hover is **not English** outside `en`;
- every state carries an `aria-label` naming the action the click performs.

## The screenshots

`states-en.png` and `states-ar.png` put the three states side by side at 6× so the
difference is **legible** rather than asserted — the recorded rule that a DOM-level test
verifies what you built and only a rendered page verifies what a reader can see. Left to
right: chosen (filled, accent) · halted (outlined, muted ring) · stopped (outlined,
bare). `chrome-<lang>-running.png` is the whole top bar, so the toggle can be seen in
the run of controls it belongs to.

**The first-run wizard is dismissed before any shot is taken.** The first pass of this
walk photographed the page behind an open modal and still reported zero findings — the
DOM assertions were all true and the pictures showed a dialog. A screenshot taken behind
a modal proves the page loaded and nothing about the control.

## What this run does NOT show

The lane is **not collecting**: no scheduler job constructs a stream yet, so the
`running` state here is the operator's CHOICE and the hover says exactly that
("Chosen, but nothing is collecting yet on this build."). The breathing accent that
means *happening now* is gated on the activity, not on the choice, so it is correctly
absent from every shot in this record. When the collector lands, this walk should be
re-run and the live state photographed.
