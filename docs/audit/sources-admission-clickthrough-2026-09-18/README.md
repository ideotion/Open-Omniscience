# Chromium click-through — S04-12's sources surfaces (gate row S, Q1128 = a)

**Run 2026-09-18, on the merge of PR #1158 plus this branch's fixes.** Chromium 141.0.7390.37
(the pinned build at `/opt/pw-browsers`), driven through Playwright against a live instance.
Real rendering, real fonts, real JS — the three things a node harness and a source test
cannot see.

This is the artifact the S04-12 brief's §4 asks for and that PR #1158 did not produce. Two of
its findings could not have come from anywhere else.

**Status:** Chromium-verified (remote sandbox) · **awaiting the maintainer's own pass.**

---

## The path, which is not the one the brief names

The brief and the 0.4 board both say *Settings → Sources*. **There is no Sources subtab.**
`#set-subtabs` offers Graphics · General · Cards · AI · Wikipedia · OpenStreetMap · Agenda ·
Data & backup · Advanced. The three surfaces live at:

> **Settings → Advanced → expand “Quality gates”**

and the panel renders *nothing* until that `<details>` is expanded — its loader is wired to the
section opening, so an operator who lands on Advanced sees a collapsed row and no data. Worth
knowing before the maintainer's own click-through, which is what row S is waiting on.

## What was driven

| Surface | Ruling | en | fr | ar |
|---|---|---|---|---|
| Headline counts + criteria table | Q1114, Q1107/B6 | ✅ | ✅ | ✅ (RTL) |
| Admission audit + undo | Q1101 | ✅ | ✅ | ✅ (RTL) |
| Shipped-verdict editor | Q1106 | ✅ | ✅ | ✅ (RTL) |

`report.json` carries the per-locale text and the row-by-row button state; `overlay.json`
carries the editor's four controls per locale and the adopt→revert round trip.

**Zero page errors and zero console errors across all three locales.**

### The admission audit, and the undo actually clicked

The seed drives `evaluate_and_stamp` into the three states the panel must be able to draw —
reversible, superseded by a later verdict, already undone — so every row is the engine's own
record rather than a fixture shaped to look like one.

| row | Undo offered? | what it says instead |
|---|---|---|
| `admitted-live.example` | **yes** | — |
| `admitted-then-refused.example` | **no** | *A later verdict replaced this one* / *Un verdict plus récent a remplacé celui-ci* / *حكم أحدث حلّ محل هذا الحكم* |
| `admitted-undone.example` | no | *Undone 2026-09-18T13:00:00* |

The Undo was then driven with a **real `page.click`** (a scripted `el.click()` is not a click),
**from the Arabic locale**: `undone_total` 1 → 2 and `collecting` 3 → 2. The safety valve
Q1101's flip rests on works end to end, in RTL.

### The shipped-verdict editor

Walked in both states. With no overlay it says so and offers no controls — which is the state a
real install is in today. With one present, all four controls render and translate, and **Revert
is correctly disabled** while nothing has been adopted.

The adopt → revert round trip was driven with real clicks (the revert's `confirm()` accepted):

```
before        in_force=0 revertible=0 | admissions=3 undone=1 collecting=3
after_adopt   in_force=3 revertible=3 | admissions=4 undone=1 collecting=4
after_revert  in_force=0 revertible=0 | admissions=4 undone=2 collecting=3
```

The `admissions 3 → 4` and `collecting 3 → 4` on adoption is **S2's own fix, seen from the
UI**: an overlay adoption that makes a source collectable now writes an admission row, so the
undo has something to act on. PR #1158 could assert that from tests; this is it happening on
screen.

> The overlay used here was a synthetic fixture written to `configs/source_qualification.yml`
> for the walk and **deleted immediately afterwards**. The real file is generated per instance
> and a session never writes verdicts into the tree (register B5).

## What the walk found that no gate could

**1. Three Quality-gates strings rendered English in fr and ar.** `sources per collection
pass`, `What the source gate looks at`, `can disqualify` — all three are `t()` call sites with
no key, so `--min 100` was structurally blind to them (it compares locale files against
`en.json` and cannot see a string that has no key at all) and both ratchets were green over
them at zero slack. Keyed ×12 in this PR; the untranslatable ratchet drops 464 → 461.

**2. The scope-count sentence was welded from four fragments and two numbers** —
`t("This will scrape") + n + t("sources") + "(" + t("of") + total + t("enabled") + ")."` — two
of whose pieces had never had a key, and which no locale can reorder. It is now one keyable
`tf()` frame; the unkeyed ratchet drops 227 → 224. It renders
`Cela collectera 2 sources (sur 5 activées).`

**3. The `later-verdict` blocker itself**, drawn here for the first time — see the branch's PR
body for the defect it closes.

## Ruled out as harness artifacts, not filed

Both were checked rather than reported, per the standing rule that a UI check's own instrument
is the first suspect:

- **`dir` read as `ltr` in Arabic** on a first pass. A direct probe measured
  `documentElement.dir = "rtl"` and `getComputedStyle(body).direction = "rtl"` both before and
  after navigation. The record now carries the attribute *and* the computed value.
- **The top-bar language switcher still reading “🇬🇧 EN” under a French UI.** That was this
  harness calling `OOI18N.setLang` directly instead of clicking the control. Driven through the
  real switcher, it reads `🇬🇧 EN → 🇫🇷 FR` and sets `html lang="fr"`. Invariant #15 holds.

## Left for their owners, not widened into this PR

Two Advanced *section summaries* — not the Quality-gates panel — still render English under a
French UI: **“Collecte — schedule, crawl modes, manual and batch ingest”** and **“Sources —
discovery candidates, qualification, manage and import/export”**. They belong to the Collect
and Sources sections rather than to S04-12, and are recorded here rather than fixed in a slice
that does not own them.

## Reproducing it

```bash
rm -rf /tmp/ct-state
OO_DATA_DIR=/tmp/ct-state OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0 \
  .venv/bin/python docs/audit/sources-admission-clickthrough-2026-09-18/seed.py
( OO_DATA_DIR=/tmp/ct-state OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0 \
  OO_PORT=8213 OO_LLM_AUTOSTART=0 \
  .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8213 & echo $! > /tmp/ct.pid )
.venv/bin/python docs/audit/sources-admission-clickthrough-2026-09-18/walk.py \
  http://127.0.0.1:8213 /tmp/walk-out
kill "$(cat /tmp/ct.pid)"     # by PID; never `pkill -f`, which matches your own command line
```

Playwright installs from PyPI in this sandbox; the browser does **not** need downloading —
`walk.py` launches the pinned build by `executable_path`.
