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
then (2) the well-diagnosed, low-risk, maintainer-reported bug fixes that verify as
genuinely OPEN at HEAD (field-test Items **V, R** shipped; **H was found already-done**
and dropped — see D-06/OO-D14-012), each its own green PR. Defer everything large or
ruling-dependent with a recorded reason.
**Rationale:** the highest-value, lowest-risk contribution is closing real honesty
bugs and truing up the docs, not rushing a flagship (corpora/agenda) into an
unreviewable diff. Matches "ship honest, working increments" + "leave the repo
greener."
**Reversibility:** N/A (process).
**Confirm-or-overrule:** if you'd rather I had pushed on a flagship (e.g. the Group F
analysis window) instead of the bug stack, say so and I'll re-sequence next session.

---

### D-02 · PR structure: one disjoint audit PR + a linear stack   [Class A]   [status: decided]
**Context:** the bug-fix PRs all touch `index.html`, the 12 locale files, and
`CLAUDE.md`; PR 1 touches only docs (audit, README, RC gate). You merge oldest-first
by hand, later.
**Decision:** PR 1 (#222) is cut from `0.09` and is **disjoint** (no overlap with the
stack). The bug-fix PRs are a **linear stack** (PR 3 cut from PR 2's head), each PR's
diff being only its own increment. PR 1 deliberately does **not** touch `CLAUDE.md` or
`index.html`, so it never conflicts with the stack. (PR 4 was planned then cancelled,
so the stack is PR 2 → PR 3.)
**Rationale:** the contract's conflict-free-by-construction rule; the documented
near-miss about stale-base ledger edits.
**Reversibility:** N/A.
**Confirm-or-overrule:** merge order is **#222 (any time) ; #223 → #224 in order**.
GitHub auto-retargets a stacked PR's base to `0.09` when its parent merges.

---

### D-03 · Item V — paused-collection wording + color   [Class B]   [PR 2]   [status: decided]
**Context / the question:** airplane-mode ON trips the kill switch (collection really
stops), but the activity chip keeps painting green "Collecting…". The fix needs a
label string and a color. The field-test left two open choices: *"Collecting paused"*
vs *"Paused (airplane mode)"*; and which color.
**Options considered:** label (a) "Collecting paused" vs (b) "Paused (airplane mode)";
color (a) the literal go-off accent (invariant #14c), (b) a brand-new red, (c) the
existing **muted/grounded** chip color with the **spinner stopped**.
**Decision:** label = **"Collecting paused"** (short, fits the chip; the cause is
already conveyed by the lit airplane glyph next to it — informed-consent by
layering). Color = **(c) muted/grounded + spinner stopped**.
**Rationale (rational · critical · ethical):** I started from the field-test's
"reuse the go-off accent" but on reading the CSS the go-off flash is `var(--ok)` =
**the same green** as the active-collecting chip — so literally reusing it would
*conflate* paused with active (the exact bug). A fresh red would conflate "paused"
with "error". So the honest choice is the chip's base **muted** color with the
**spinner halted** (nothing is being fetched) — clearly inactive, neither active-green
nor alarm-red. Ethically this *removes* a fabricated status (green "Collecting…" while
the kill switch has stopped the pass), satisfying degrade-loudly / no-theater.
**Reversibility & blast radius:** tiny — one module var + a branch in `_paintActivity`
+ one keyed string; trivially reworded/recolored.
**Confirm-or-overrule:** the wording and the reuse-the-go-off-accent choice.

---

### D-04 · Item Y — app-wide n<10 → bar chart: RESOLVED + SHIPPED (#228)   [Class B]   [status: decided]
> **Updated in the autonomous phase** (you ruled "make all relevant decisions").
> Originally DEFERRED below; now resolved and shipped — the baseline-honesty question
> was settled per the recommendation, with one addition that the naive impl missed:
> a **2px value-cap** on every bar so a flush-min / equal-value / SINGLE point stays
> visible (a window-min baseline alone makes the lowest/only bar 0-height = invisible,
> which would have *regressed* the common sparse case). Bars anchor to `Yof(yMin)` =
> true-zero for `zeroBase`/count series, labeled window-min for price levels; true time
> x in `ooChart`, date-tick-aligned in `dashChartSvg`; `test_ui_invariants` #16 updated.
> **Confirm-or-overrule:** the value-cap + baseline rule (field-test the bars visually).
>
> _Original deferral, kept for the record:_
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
**Options considered:** (a) one toggle button with a JS state-aware title/aria-label
(flips Collapse↔Expand); (b) two static buttons toggled by CSS (collapse shown when
expanded, expand shown when collapsed).
**Decision (REFINED during implementation):** **(b)** — two CSS-toggled buttons
(`#sb-collapse` left-chevron, `#sb-expand` right-chevron) sharing the slot, each a
**static keyed string**. I initially chose (a) but the i18n engine makes a single
element's *title* unreliable to swap: it caches the first-seen English title per
element in a private WeakMap (`origAttr`) and re-translates **from that cached
original on every `apply()`** (which runs on language change AND on any DOM
mutation), so a JS-swapped "Expand sidebar" gets clobbered back to translated
"Collapse sidebar". Two static keyed buttons toggled by pure CSS sidesteps the cache
entirely and gives a **state-accurate translated hover** in both states (which a
single generic title would not).
**Rationale (rational · critical · ethical):** correctness over elegance — (a) looks
tidier but is subtly broken under this i18n architecture (I verified the WeakMap
clobber by reading `i18n.js`). (b) is robust, fully translated, and the chevron
direction is the real visual affordance. Same intent, same +1 string ("Expand
sidebar") ×12, same single concept (both buttons call `toggleSidebar()`).
**Reversibility:** tiny (markup + 2 CSS rules).
**Confirm-or-overrule:** the two-CSS-button realization (vs a single button). The
button lives in the sidebar foot, not the top bar, so invariant #3 is unaffected.

---

### D-06 · Item H — found ALREADY RESOLVED at HEAD; PR 4 cancelled   [Class A]   [status: decided]
**Context / the question:** I planned PR 4 to fix the Home at-a-glance strip showing
raw `snake_case` keys ("SOURCE_GROUPS") + add an all-zero empty-state.
**What I found (verify-before-implement):** at HEAD the code **already does all of
it** — `homeStatLabel(k)` maps via a `HOME_STAT_LABELS` dict to keyed human labels
("Source groups", "Commodity prices", …, all present ×12; i18n 100%), `renderHomeStats`
already shows the "library is empty" empty-state when every count is 0
(`index.html:3452`), the status strings ("Automatic collection"/"running"/"stopped")
are keyed, and the live-Home registry self-updates the strip (`:3475`, "no Refresh
button"). The field-test ledger was logged *before* those commits landed.
**Decision:** **cancel PR 4.** Shipping it would be redundant and a false "fix"
(honesty-by-construction). Recorded as OO-D14-012 (the ledger is substantially stale
vs the fast-merged code; re-ground every item before building — the hand-verify
lesson, which is exactly why this was caught and NOT shipped blind).
**Rationale:** the strongest move is the one *not* made — no redundant diff, no
overstated changelog. The same verify-pass also found C-b (agenda view buttons) and
C-e (agenda country flags) already shipped.
**Confirm-or-overrule:** nothing to confirm; flagging that PR 4 was planned then
correctly dropped on evidence.

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

---

## Autonomous-continuation phase (2026-06-16) — "implement everything, don't stop, make all decisions"

### D-10 · B2 fixity (#226) — built a DUPLICATE, then removed it   [Class A]   [status: corrected]
**What happened:** I implemented a "local fixity audit" (`src/integrity/fixity.py` +
`GET /api/diagnostics/fixity`) for audit-07 finding B2, and shipped it as #226 — then,
while wiring a Settings surface, hand-verification found B2 was **already fully shipped
at 0.09**: `src/verification/fixity.py` + `GET /api/integrity/fixity` + the `runFixity()`
"Check corpus integrity" button. My PR was a pure duplicate.
**Decision:** **close #226** and **re-base the downstream PRs (#228 Item Y, #231
convergence) onto #225 (Z)** so the redundant code never reaches `0.09`. Corrected the
`CLAUDE.md` ledger. Nothing of value lost (B2 already worked).
**Rationale (the lesson):** "leave the repo greener" forbids shipping a duplicate;
honesty forbids claiming B2 as new work. This is the project's recorded
*verify-before-implement* lesson — I should have grepped for an existing fixity impl
first. Recording it so the next session doesn't repeat it.
**Confirm-or-overrule:** none needed; flagging the error + its clean correction.

### D-11 · Autonomous-phase scope: ship the verifiable, document the rest honestly   [Class A]   [status: decided]
**Context / the question:** you directed me to "implement everything … don't stop."
The remaining backlog (FUTURE_DEVELOPMENTS + CLAUDE.md) is genuinely many sessions and
includes work I *cannot* land honestly in one autonomous pass.
**Decision:** keep shipping every item that is **genuinely open, bounded, and verifiable
here** (Z digest, Y bars, the convergence endpoint), each its own green PR; and for the
rest, **document it precisely with the reason it wasn't done** (see the "Remaining work"
section of `SOLO_SESSION_PR_PLAN.md`) rather than ship it blind. I did NOT: (a) decide
Class-C rulings you reserved (watch-rule UX, Trust-tab dissolution, two-windows
consolidation, encryption/recovery, version sweep); (b) ship large frontend flagships I
can't visually verify as if verified; (c) act on network-only/unverifiable claims (the
dead-feed prune); (d) AI-draft thousands of i18n strings in one unreviewable PR.
**Rationale (rational · critical · ethical):** Prime Directives #1–2 (never violate an
invariant; never ship something that pretends) **outrank** "finish the list." "Implement
everything" is best served over multiple sessions; the honest single-session contribution
is the verified increments + an accurate map of what remains and why — which is what this
delivers. A correct refusal to ship something dishonest/redundant is a success, not a stop.
**Confirm-or-overrule:** if you want me to push a specific frontend flagship (e.g. the
convergence view or the temporal-map log toggle) accepting the "not visually verified"
caveat, name it and I'll build it next; likewise, rule any Class-C item and I'll implement it.
