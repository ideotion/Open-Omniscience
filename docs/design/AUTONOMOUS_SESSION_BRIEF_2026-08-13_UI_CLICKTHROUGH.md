# Autonomous session brief — the UI click-through (0.3 gate row 8)

**Written:** 2026-08-13 · **For:** one fully autonomous Sonnet 5 session ·
**Closes:** [`RELEASE_0.3_GATE.md`](../product/RELEASE_0.3_GATE.md) **row 8**
**Mode:** full autonomy, **draft-PR-only** — nothing auto-merges; the review is the gate.
**Branch:** `claude/oos-ui-clickthrough-*`

---

## 0. Why this exists

Almost every frontend slice since the fork-3 ruling shipped **conservative and flagged**:
`node --check` clean, invariant-guarded, defensive empty states — and **never once
rendered**. The ledger carries 28 distinct "browser-unverified / a click-through is owed"
markers. The `0.3` cycle is named *measured & verified*; it cannot honestly tag with the
flagship UI in that state.

Gate row 8 offers two ways to close: **the `ui_walk` runner standing**, or **a defined hand
click-through**. This brief does the first and uses it to drive the second, because a
standing runner keeps paying after this session ends.

**Two things you are NOT doing.** You are not re-running the 2026-07-22 systematic GUI test
— its 72 findings are recorded and its P0s are fixed; **compose with it, never repeat it.**
And you are not fixing every finding you make: fix what is cheap and safe, record the rest.

---

## 1. Read first (the staleness guard)

The UI moved a great deal in three weeks. **Before writing a line**, confirm against the
live tree:

1. [`docs/audit/GUI_TEST_REPORT_2026-07-22.md`](../audit/GUI_TEST_REPORT_2026-07-22.md) —
   the methodology precedent, its five P0s, and **its critical caveat about the 429 storm**
   (§4 below). Its `findings.csv` is your dedup baseline: a finding already recorded there
   is not new.
2. `src/monitoring/ui_walk.py` — 233 lines of **scaffold**. `Surface`, the `UiWalkDriver`
   Protocol, `UnconnectedDriver`, `walk()`, `run_ui_walk()` and `FLAGSHIP_SURFACES` all
   exist. **No real driver does.** That is your Phase 1.
3. `CLAUDE.md` → "THE 0.3 CLOSE GATE" row 8, and the **Session-rituals Lessons** list —
   §5 below extracts the ones that bite in a browser, but read the source.
4. `docs/CHANGES.md` → `0.3.0` — what this cycle actually shipped, i.e. what is most likely
   to be unrendered.

**If a surface named below has moved, follow the anchor rather than the name.** Several
already have: `FLAGSHIP_SURFACES` records that `post_import_screen` points at the *current*
import-summary target because the redesign is still pending.

---

## 2. Environment — this sandbox has a browser and Python 3.13

The standing "browser-unverified per fork-3" caveat is a **habit, not a limit** (recorded
2026-08-04). Verify each step; do not assume.

```bash
# Chromium is pre-installed; PLAYWRIGHT_BROWSERS_PATH is already set.
ls /opt/pw-browsers/                       # confirm the pinned build
# Do NOT run `playwright install`.

# The default python3 is 3.11; the repo needs 3.13.
/usr/bin/python3.13 -m venv .venv
export TMPDIR="$PWD/.tmp-pip"              # pip unpacks big wheels in TMPDIR (tmpfs → ENOSPC)
mkdir -p "$TMPDIR"
.venv/bin/pip install -e ".[analysis]" pytest playwright
```

**Seed a synthetic corpus through the REAL chokepoint** — `index_article`, so keyword
extraction, When/Where/Who, sentiment and FTS are genuinely exercised. Never hand-insert
rows: a fixture that bypasses ingestion tests a corpus that cannot occur.

```bash
OO_DATA_DIR=/tmp/oo-ui/state \
OO_DB_PLAINTEXT=1 \
OO_NO_SCHEDULER=1 \
OO_LLM_AUTOSTART=0 \
.venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8010
```

```python
pw.chromium.launch(executable_path="/opt/pw-browsers/chromium-<build>/chrome-linux/chrome")
```

**Honest stamp.** This is Chromium in a remote sandbox. Surfaces you verify graduate to
**"Chromium-verified (remote sandbox) · awaiting human UX pass"** — explicitly **not** the
queued *Gecko-verified (VM)* bar, and it does not replace the maintainer's own pass. Do not
inflate the stamp; the whole value of this exercise is that the stamp means something.

---

## 3. The three states

Boot three separate instances, **each on its own port and its own `OO_DATA_DIR`** (§4
explains why one shared server is not acceptable):

| | State | Contents |
|---|---|---|
| **A** | virgin | no data dir at all — first-launch: language step → passphrase → wizard |
| **B** | empty | catalog seeded, zero articles — the **empty-state honesty** pass |
| **C** | populated | see below |

**State C must contain the specimens that make defects visible.** Minimum:

- ≥ 400 articles across **≥ 8 languages** including **Arabic** (RTL) and one
  **unsegmented** language (zh or ja);
- a multi-year `published_at` spread **and** articles whose `published_at` is NULL (the
  coalesce/deduced-date paths);
- a 3-source **near-duplicate cluster** sharing an outbound link (Related / coordination);
- one **nav-soup** specimen, one **mislabeled-language** specimen, one **empty-body**
  specimen;
- a **dense** (≥ 60 point) and a **sparse** (< 10 point) series, **plus one with a real gap**
  — the honest-gaps renderers cannot be verified against data that has no holes;
- one sample each of **law**, **wiki**, **newsletter** and **hazard** provenance;
- ≥ 2 sources in each qualification state (qualified / disqualified / never-judged /
  disabled candidate) so the Library qualification tile has four real lines.

---

## 4. Phase 1 — implement the real driver

Implement `UiWalkDriver` against the **existing Protocol**. Do not redesign the seam; the
scaffold deliberately keeps the selectors (`nav_tab` → a `data-tab` click, then a visibility
check on `dom_id`) so a driver drops in without guessing.

Required beyond the Protocol's four methods:

- **`console_errors()` must separate `pageerror` from `console.error`.** This is the single
  most important lesson from 2026-07-22: it reported "384 JS errors" of which **100% were
  429 rate-limit resource lines and zero were uncaught exceptions**. A driver that conflates
  them manufactures a crisis.
- **One browser per server instance.** The 429 storm was an artifact of 14 parallel agents
  hammering one server. Parallelise across the three *states*, never within one.
- **Screenshot on every step**, plus a greyscale variant (§5).
- **Structured output** — one row per (surface × axis) with the verification stamp.

Extend `FLAGSHIP_SURFACES` with the backlog surfaces in §6. Keep the gate-row-8 five
**first and in order** — that ordering is verbatim from the ruling and a test may pin it.

---

## 5. The honesty rules — mandatory

These are not style notes. Each is a recorded lesson that already cost a shipped defect.

**Measure rendered pixels, not declared tokens.** `getComputedStyle` on the element *and*
the pseudo-element. Two families of defect are invisible to reading CSS:

- **Element `opacity` composites the whole element over what is behind it**, so the real
  text pixel is `α·fg + (1−α)·parent_bg` while the background stays `parent_bg`. The
  `.ag-cal` chip failed WCAG AA on **16 of 17 themes** this way while every declared colour
  looked fine.
- **A `::after` inherits every property it does not declare** from any lower-specificity
  rule that also matches. The AI pill's diagonal bar silently became a 4×4 dot at 55%
  opacity, and had not rendered since the pill gained a title.

Check with `getComputedStyle(el, '::after')`, and compute contrast from the composited
value.

**A class with no rule is a lie the markup keeps telling.** `class="small"` appeared 35
times with **no rule anywhere in the tree**. Before trusting what a class name implies,
confirm it is defined.

**Greyscale is a browser filter, captured mid-interaction.**
`documentElement.style.filter = 'grayscale(1)'` so you judge rendered pixels — and capture
*during* the interaction. A greyscale screenshot taken after a click navigated away tests
nothing; that exact mistake meant "the selection band is visible without colour" had never
been tested despite a greyscale screenshot existing.

**An untested path is not a pass.** If State C contains no gap, you have not verified gap
rendering — say so and add the specimen. A critic that refuses to certify an unexercised
path is doing its job.

**RTL is a correctness axis, not a cosmetic one.** In Arabic, an interpolated ISO timestamp
renders in visual order with the year at the wrong end — a *misread* date, not an ugly one.
Punctuation-joined runs (dates, versions, IDs, URLs, ranges) need `U+2068`…`U+2069`
isolates. Verify by reading each character's rendered **x position**, not by eye.

**`uppercase` is a no-op in five of the twelve locales.** A hierarchy carried by
`text-transform` disappears in Arabic, Chinese, Japanese, Hindi and Bengali. Rank must be
carried by size and weight.

**The i18n walker matches a text node EXACTLY.** A label welded to its value
(`` `${t("Method")}: ${env.method}` ``) is one node and can never match a key. Any
value-bearing sentence needs `OOI18N.tf` with a fixed template. And an already-interpolated
`tf()` string is no longer a key — a render-once surface freezes in whatever locale first
rendered it unless it registers with `oo:langchange`.

**Hand screenshots to adversarial critics.** Three critics reading PNGs found things numbers
could not — including one that correctly *refused* to certify a path the data never
exercised.

---

## 6. Phase 2 — the matrix

**Surfaces.** Gate row 8's five first, then the backlog. Each entry names why it is here:

| Surface | Why |
|---|---|
| Home / Leads · the Overview lens | flagship; `sort_leads` reorders it live |
| The analysis window (all subtabs) | flagship; parallel tabs, Related, Conjunction picker |
| The post-import screen + corpus-delta view | flagship; redesign pending — verify what ships |
| Source management + the qualification panel | flagship; four-line tile, drills, undo |
| The one-button diagnostics panel | flagship; the surviving action controls |
| Export / Import (unified dialog) | data-safety flow; **compartmented export is new** |
| Library — the five views + graphs | the axis-honesty pass; hide-flat-zero; window switcher |
| World map (`ooMap`) — dimensions · granularity · signals · Server-IP layer | never rendered |
| Settings — all ten subtabs incl. **Cards** and **Advanced** | 15→10 restructure |
| Settings → AI — pill, backend panel, roster install | the pill's third state |
| Keyword / group / super-group surfaces + the concept map | the circle grammar |
| Agenda — month grid, glyphs, deduced events | provenance pills |
| Reader — tabs, provenance classes, Loaded-language | **the two-class headings** |
| Task manager — Active · Queue · System · Schedule | per-job controls |
| Bulletin — review screen + the Settings section | never clicked through |

**Axes.** For every surface: **17 themes** (at minimum `ink`, `paper`, `contrast`, and the
six light themes that failed `--warn`), **12 locales** (at minimum `en`, `fr`, `ar`, `zh`),
**breakpoints** 375 / 768 / 1024 / 1440 (the 900–1024 band has *no* layout media query),
and **a11y** (axe, keyboard-only traversal, focus visibility, `prefers-contrast`).

Full cross-product is combinatorially silly. **Every surface × the default axis**, then
**every axis × a representative surface**, then the cross-product only where a defect
family predicts one (contrast → light themes; RTL → Arabic; overflow → 375 px).

---

## 7. Fix policy

**Fix in this session** — mechanical, provably safe, invariant-guarded: a missing i18n key,
a contrast token, a missing label/`aria-*`, a missing rule for a used class, an overflow
container.

**Record, do not fix** — anything that changes behaviour, ordering, or a payload; anything
touching a non-negotiable; anything needing a maintainer ruling. Write it up with a
reproduction.

Every fix needs its **negative-space twin**: an over-eager fix reads as conservative while
quietly deleting data. Mutation-check each guard — and remember that a "must be present"
source guard is satisfied by the comment explaining it, so read comment-stripped source or
assert behaviour.

---

## 8. Output

1. `docs/audit/UI_CLICKTHROUGH_2026-08-13.md` — the report: what ran, the verification
   stamp per surface, findings by severity, **and what you could not verify and why**.
2. `docs/audit/ui-clickthrough-2026-08-13/findings.csv` + `coverage.csv` — machine-readable,
   deduped against the 2026-07-22 `findings.csv`.
3. Screenshots for every P0/P1, colour and greyscale.
4. The real driver merged into `src/monitoring/ui_walk.py` (or a sibling), with tests.
5. A `docs/ledger/shipped.csv` row, and any reusable lesson appended to the CLAUDE.md
   Lessons list.
6. **The gate-row-8 line in `RELEASE_0.3_GATE.md` updated** with the artifact path.

---

## 9. Gates before push

Reproduce each CI command **verbatim and separately** — the three i18n gates are three
invocations, and running the combined form exercises a different computation:

```bash
ruff check --select=F,B --extend-ignore=B008 src/ tests/
python -m mypy src/ | grep -c " error: "          # must be ≤ 127, and NOT ~3 (an aborted run)
bandit -r src/ -ll -q > /tmp/b.txt 2>&1; echo "rc=$?"   # never `| tail` — $? becomes tail's
python scripts/i18n_report.py --min 100
python scripts/i18n_report.py --audit-chrome --max-untranslatable <ratchet>
python scripts/i18n_report.py --max-unkeyed-t-calls <ratchet>
node --check src/static/app.js
pytest -q                                          # full suite, on the py3.13 venv
```

**Baseline-diff the suite**, and prove the head side ran your tree: a PR that adds tests must
show a **pass-count delta equal to the tests added**. Identical counts on both sides is proof
the head run never executed the change. Use `--continue-on-collection-errors`, print both
summary lines, and echo the cwd — a `cd` persists into the next command.

**Lower a ratchet you clear.** If keying strings drops the untranslatable count below the
bar, lower the bar in the same PR.

---

## 10. Scope fence

**Out of scope** — do not start these, however tempting:

- The **Observatory** (`ooSky`) — designed, prerequisites unmet, its own build.
- The **inline-handler retirement** (~556 handlers) — real debt, needs its own reviewed pass.
- Re-litigating the 2026-07-22 findings.
- The five new **verticals**; anything needing the **Ollama/GPU rig**; anything **networked**
  (airplane mode stays engaged — a UI pass must never egress).
- **Row 4's** committed import — postponed to `0.4`.

**Never** relax a non-negotiable to make a surface pass. If a surface can only be verified by
weakening airplane mode, robots handling, or a caveat's visibility, **record that as the
finding** — it is a more valuable result than a green row.
