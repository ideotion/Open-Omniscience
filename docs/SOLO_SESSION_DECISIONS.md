# Solo session decisions — 2026-06-15

> Autonomous session, maintainer unavailable. This is the first thing to read after
> the session: every judgment call I made while you were away, and every question I
> could not answer that I left for you with a conservative default. Classes follow
> the session contract: **A** = sequencing/ordinary implementation (logged only when
> non-obvious); **B** = reversible internal ruling (made on the documented principles,
> flagged CONFIRM-OR-OVERRULE); **C** = a genuine ruling I must NOT make alone (took
> the conservative default, recorded DEFERRED).
>
> **Baseline → final gate.** Start: 1306 passed / 4 skipped, mypy 114≤127, bandit
> clean, pip-audit clean, i18n 100%×12, alembic clean. Every shipped PR re-ran the
> full gate green. No invariant weakened; no network/security/encryption posture
> touched.

---

### D-01 · Session scope: a small honest stack, not "everything"   [Class A]   [status: decided]
**Context:** the mission lists the whole RC backlog. A single session cannot ship it
all at quality, and the project's ethic punishes half-working code.
**Decision:** deliver (1) a run-verified audit + the docs-honesty fixes it surfaced,
then (2) three well-diagnosed, low-risk, maintainer-reported bug fixes (field-test
Items V, R, H), each its own green PR. Defer everything large or ruling-dependent
with a recorded reason.
**Rationale:** the highest-value, lowest-risk contribution is closing real honesty
bugs and truing up the docs, not rushing a flagship (corpora/agenda) into an
unreviewable diff. Matches "ship honest, working increments" + "leave the repo
greener."
**Reversibility:** N/A (process).
**Confirm-or-overrule:** if you'd rather I had pushed on a flagship (e.g. the Group F
analysis window) instead of the bug stack, say so and I'll re-sequence next session.

---

### D-02 · PR structure: one disjoint audit PR + a 3-PR linear stack   [Class A]   [status: decided]
**Context:** PRs 2–4 all touch `index.html`, the 12 locale files, and `CLAUDE.md`;
PR 1 touches only docs (audit, README, RC gate). You merge oldest-first by hand,
later.
**Decision:** PR 1 is cut from `0.09` and is **disjoint** (no overlap with 2–4).
PRs 2→3→4 are a **linear stack** (3 cut from 2's head, 4 from 3's head), each PR's
diff being only its own increment. PR 1 deliberately does **not** touch `CLAUDE.md`
or `index.html`, so it never conflicts with the stack.
**Rationale:** the contract's conflict-free-by-construction rule; the documented
near-miss about stale-base ledger edits.
**Reversibility:** N/A.
**Confirm-or-overrule:** merge order is **PR1 (any time) ; PR2 → PR3 → PR4 in order**.
GitHub auto-retargets a stacked PR's base to `0.09` when its parent merges.

---

### D-03 · Item V — paused-collection wording + color   [Class B]   [PR 2]   [status: decided]
**Context / the question:** airplane-mode ON trips the kill switch (collection really
stops), but the activity chip keeps painting green "Collecting…". The fix needs a
label string and a color. The field-test left two open choices: *"Collecting paused"*
vs *"Paused (airplane mode)"*; and which color.
**Options considered:** (a) "Collecting paused"; (b) "Paused (airplane mode)";
for color (a) reuse the direction-aware **go-off calm/grounded** accent (invariant
#14c), (b) a brand-new red.
**Decision:** label = **"Collecting paused"** (short, fits the chip, the cause is
already conveyed by the lit airplane glyph next to it — informed-consent by
layering). Color = **reuse the go-off calm/grounded accent**, NOT a new red.
**Rationale (rational · critical · ethical):** a fresh red would conflate "paused"
with "error/danger" and re-introduce exactly the two-meanings-one-color confusion
invariant #14c was written to kill. Reusing the existing go-off accent keeps the
visual language coherent. Ethically this *removes* a fabricated status (green =
"actively collecting" while it is not), satisfying degrade-loudly / no-theater.
**Reversibility & blast radius:** tiny — one module var + a branch in `_paintActivity`
+ one keyed string; trivially reworded/recolored.
**Confirm-or-overrule:** the wording and the reuse-the-go-off-accent choice.

---

### D-04 · Item Y — app-wide n<10 → bar chart: DEFERRED   [Class C]   [status: DEFERRED]
**Context / the question:** you ruled (field-test Item Y, recorded in CLAUDE.md #16)
that every chart with <10 datapoints should render as a **bar** graph (not dots) and
that the "early corpus … no curve interpolated" caveat be removed (keep n=x). The
ruling also flags a genuine honesty wrinkle that you yourself marked open.
**Why I did not just ship it:** a bar encodes value by **length**, which implies a
**zero baseline**. For price-LEVEL series (gold $1900 vs $1950) zero-based bars render
a real ~3% move as ~equal full-height bars — a *fabricated-flat* visual the
no-fabricated-visuals ethic forbids. Choosing the baseline (window-min-labeled axis
for level data vs true-zero for count data) **is** a chart-honesty ruling, and the
ledger records it as still-open ("must settle BEFORE shipping"). Shipping a default
silently would be deciding a Class-C honesty question alone.
**Recommendation (for you to confirm):** sparse bars anchor to the **window-min on a
clearly-labeled axis** for level/price series, and to **true-zero** only for naturally
zero-based count series (article counts, mentions — `ooChart` already has a `zeroBase`
opt). Strict cutoff **n≤9 → bars, n≥10 → line**. Bars at their **true x-position**
(irregular market dates), not evenly categorical.
**Reversibility & blast radius:** medium — touches both renderers (`ooChart` ~5622,
`dashChartSvg` ~5387) AND flips `test_ui_invariants` #16 (it currently asserts
`"early corpus" in html`, `test_repo_invariants.py:359`). That test-flip is why this
is a deliberate slice, not an inline edit.
**Confirm-or-overrule:** approve the baseline rule above (or pick another) and I'll
ship the bar rule + the #16 test flip as a dedicated PR next session.

---

### D-05 · Item R — discoverable expand affordance   [Class B]   [PR 3]   [status: decided]
**Context / the question:** the sidebar collapses to an icon rail via a top-bar
button (`toggleSidebar`), but in the collapsed rail there is no obvious "expand"
affordance — the same top-bar button toggles back, but its title still says
"Collapse sidebar" and nothing in the rail invites expansion.
**Options considered:** (a) make the existing top-bar toggle button *state-aware*
(its title/aria-label flips Collapse↔Expand, and the glyph reflects state); (b) add a
second, separate expand button in the rail.
**Decision:** (a) — make the one existing toggle button state-aware: title/aria-label
read "Expand sidebar" when collapsed and "Collapse sidebar" when expanded, and the
chevron glyph points the way it will move. One control, honest label, no new chrome.
**Rationale:** one control for one concept (no redundant buttons), keeps the constant
top-bar footprint (invariant #3), and the title feeds the #oo-tip hover (invariant
#17) so the affordance is discoverable on hover/focus. +1 keyed string ("Expand
sidebar") ×12.
**Reversibility:** tiny.
**Confirm-or-overrule:** the one-state-aware-button choice over a second button.

---

### D-06 · Item H — Home stat labels + all-zeros empty-state   [Class B]   [PR 4]   [status: decided]
**Context / the question:** the Home at-a-glance strip prints raw server `counts`
keys (`source_groups`, `commodity_prices`, …) which CSS then uppercases
("SOURCE_GROUPS"). The field-test asked for human, translated labels and a friendly
empty-state on a fresh (all-zero) corpus.
**Decision:** map each known key → a keyed human label **in the UI layer**
(`OOI18N.t`), leaving the server `counts` keys untouched (the Database tab + cache
rely on them as identifiers — the ledger's explicit recommended split). Show the
existing "library is empty" empty-state when every count is 0 (today it never fires
because the keys exist). I am shipping H(b)+(c); the live-update H(a) is deferred
(shared mechanism with Item F).
**Rationale:** raw DB identifiers shown to a user is a small honesty/clarity bug;
fixing it in the UI layer avoids renaming server identifiers (no churn, no risk to
the Database tab/cache). Keys not in the dict fall back to the prettified key, so a
new count never renders blank.
**Reversibility:** small (a label dict + an all-zero guard in `loadHome`).
**Confirm-or-overrule:** the UI-layer mapping (vs renaming server keys) and shipping
labels now while deferring live-refresh.

---

### D-07 · RC-gate reconciliation is conservative   [Class B]   [PR 1]   [status: decided]
**Context:** the RC gate understates shipped progress (OO-D14-010). I could rewrite
it wholesale or advance only verified rows.
**Decision:** advance **only** rows I spot-checked in code at HEAD (agenda views,
corpus sub-tabs, indices-on-ooChart, ooTimeScope, reader-reads-stored-rows,
convergence slice 1). Everything else is left as-is. Added a dated note that
`CLAUDE.md` is the live ledger and the gate is a snapshot.
**Rationale:** marking something ✅ that isn't fully done would be the exact
overstatement the audit exists to catch. Under-claiming is safe; over-claiming is not.
**Reversibility:** docs-only.
**Confirm-or-overrule:** that you want the gate kept in sync this way (vs letting it
lag deliberately as a coarse snapshot).

---

### D-08 · Item N ("Trust" tabs dissolve/spread) — untouched   [Class C]   [status: DEFERRED]
**Context:** you marked Item N explicitly "help me decide" (a design direction for
dissolving the Evidence-&-custody / Source-integrity tabs into the workflow). CLAUDE.md
also records the rework as "PARKED behind the analysis-window build + the search UI."
**Decision:** do not touch it. The conservative default is the status quo (both tabs
remain, working).
**Rationale:** it is outward-facing UX architecture you reserved for yourself, and it
is sequenced behind larger builds. Deciding it alone would violate the Class-C rule.
**Confirm-or-overrule:** nothing to confirm — flagging that I consciously left it.

---

### D-09 · Item X (task manager "doesn't open") — no code change   [Class A]   [status: decided]
**Context:** you reported the task manager not opening. I re-verified the code path at
HEAD (`toggleVitals` hoisted, sets `pop.hidden=false` before anything that can throw;
`node --check` clean; CSS shows it when not hidden). I could not reproduce the failure
statically.
**Decision:** ship no speculative "fix" (a blind change to a working path risks
breaking it). Recorded as needs-live-repro; most likely a stale/cached build on the
long-running field instance.
**Rationale:** faithful reporting — don't claim a fix for something I can't reproduce.
**Confirm-or-overrule:** hard-refresh/relaunch and re-test; if it still fails, the
browser-console error would let me find a real cause.
