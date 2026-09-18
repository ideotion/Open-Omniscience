# The Wikipedia lane's S4/S5 surfaces — Chromium click-through, 2026-09-18

Q1128 = a's sandbox half: **Chromium-verified (remote sandbox) · awaiting the
maintainer's own UX pass.** Four locales × four surfaces, driven against a real server
(`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1`, port 8099) over a seeded lane, **zero
findings** on the final tree.

`walk.py` is the harness that produced this, kept beside the record so the run can be
repeated rather than believed. The companion record for the top-bar toggle is
[`../wiki-toggle-clickthrough-2026-09-17/`](../wiki-toggle-clickthrough-2026-09-17/).

## What was walked

`en` · `ar` (RTL) · `zh` · `de`, on:

1. **The first-run wizard** (Q725, Q726) — 12 editions offered and all 12 checked, the
   budget defaulting to `20`, the host line filled from the ONE table, the share line
   computed, and all four disclosure blocks translated.
2. **The reader's licence notice** (Q726) — three outbound links, every one carrying
   `class="ext"` so it passes the reader's own confirm, and one of them the **page
   history**, which is what CC BY-SA asks to be credited.
3. **The Home strip's own figure** (Q714) — appended beside the article counts, never
   merged into them.
4. **The map layer** (Q819 step 1) — 6 markers from 6 seeded located pages, 5 of them
   filled because 5 carry a QID.

## What it asserts, per surface and per locale

Per **surface**, never over a concatenation: the recorded defect is a locale check over
two elements' joined text passing while one stayed English, because the other one
translating changed the string enough.

- the two Wikimedia **hostnames survive every translation verbatim** — a localized
  hostname is an unreachable address on a consent surface;
- the **placeholders are filled**, not printed: a `{pages}` reaching the screen is a
  finding of its own;
- every outbound link in the licence notice is **confirm-gated**;
- the wizard's four English marker strings are **absent** outside `en` and **present**
  in `en`, so the check fails in both directions rather than only one.

## The three findings it produced, all now fixed

1. **The wizard's prose contradicted its own host list.** It said *"Two Wikimedia hosts
   and nothing else"* directly above a list, filled from `net-hosts.js`, of **five** —
   the lane's row covers the change stream, the daily most-read list, each edition's
   API, the optional scoring models and the offline dumps. A number in prose beside a
   list is a second source of truth about the same fact, and the one nobody updates is
   the one an operator reads before consenting. The prose now describes the list.
2. **The share line rendered `1.7 GB` to a German reader.** `toFixed` always emits a
   POINT, which in German is a thousands separator — the same string says 1,700. It
   goes through `toLocaleString` now.
3. **The Home strip's figure was frozen in English** in `ar`, `zh` and `de` while every
   other string on the strip was translated. It is built from a `tf()` frame AND
   carries `data-i18n-dyn`, so **both** repaint paths skipped it: the walker because
   the node opts out, and the `oo:langchange` listener because it was never listed
   there. It repaints from the cached reading now, so a language switch costs no
   request.

None of the three is reachable by a source-text test, which is the whole argument for
the walk: two are contradictions between two correct-in-isolation surfaces, and the
third only exists at the moment a reader switches language.

## The harness's own two bugs, found first

Named because a harness that was never wrong is a harness nobody checked: it read the
wizard's scrolling body and reported the title (in the `<h3>` above it) missing in every
locale, and it asked for a tab called `map` when the wired surface is the coverage map
inside the **timemap** tab.
