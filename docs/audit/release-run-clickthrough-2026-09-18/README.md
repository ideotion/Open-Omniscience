# Chromium click-through — the 0.4 release-run box (Settings → Advanced → Diagnostics; Q1128 = a)

**Run 2026-09-18, on `main`@`7ec4bfe` plus this branch.** Chromium 141 (the pinned build at
`/opt/pw-browsers`), driven through Playwright against a live ephemeral instance. Real
rendering, real fonts, real JS — the three things a node harness and a source test cannot see.

**Status:** Chromium-verified (remote sandbox) · **awaiting the maintainer's own pass.**

The run ITSELF — hours of backup, a subprocess restore, a ≥ 72 h soak — was not driven here and
cannot be: it is the operator's, on their machine, and the report it writes is the record. What
this walk verifies is the box the operator will press, and that its safe controls tell the truth
with no run in flight.

---

## The path

> **Settings → Advanced → expand "Diagnostics"** → the box titled *0.4 release run (the board's
> operator rows)*, directly under the P0 data-safety validation box.

The section is collapsed and, by its standing property, fetches nothing on expand. Measured: the
resource-request count was **75 → 75** (en) and **76 → 76** (ar) across the expand.

## What was driven

| Check | en | ar |
|---|---|---|
| The box renders with all eleven controls (three inputs, the hours field, three checkboxes, two run buttons, status, result) | ✅ | ✅ (RTL, `dir="rtl"`) |
| The three checkboxes escape the global `input { width:100% }` rule (recorded 2026-09-16 defect) | 13 px each | 13 px each |
| The row-5 opt-in (ruling A1 deferred it) is **unchecked** by default | ✅ | ✅ |
| **Check now** with no run in flight | *Not running.* | *غير جارٍ.* |
| **Collect now** with no run in flight | *No run is in progress.* | *لا يوجد تشغيل جارٍ.* |
| **Run on this instance** with EMPTY fields: refused before any consent popup; the network state unchanged | ✅ (`online` True → True, popup not opened) | ✅ |

**Zero page errors and zero console errors in both locales.** `report.json` carries every
reading; the four screenshots are the box before and after the safe presses.

## Two things worth knowing before the maintainer's own pass

1. **The ephemeral instance boots ONLINE under `OO_NO_SCHEDULER=1`** — the boot-time airplane
   engagement lives inside that same block. So the "unchanged" claim above is a before/after
   comparison, not a claim that the instance was offline. On a real install the press passes the
   ONE consent popup (invariant #14) before anything starts; that path is pinned by
   `tests/test_release_run.py::test_the_handlers_exist_gate_on_consent_and_drop_the_secret_from_the_dom`
   and was mutation-checked (turning the condition to `false` reddens it by name), but a popup
   needs an offline instance to open, which this harness did not give it.
2. **The passphrase field is 200 px wide, like the P0 box's**, so its placeholder clips at
   "backup passphrase (ne…" in English. Deliberately identical to the sibling field one box up;
   a wider field is a one-attribute change if the maintainer wants it.

## Reproducing it

```bash
rm -rf /tmp/ct-rr
( OO_DATA_DIR=/tmp/ct-rr OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0 \
  OO_PORT=8231 OO_LLM_AUTOSTART=0 \
  .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8231 & echo $! > /tmp/ct-rr.pid )
.venv/bin/python docs/audit/release-run-clickthrough-2026-09-18/walk.py \
  http://127.0.0.1:8231 /tmp/walk-out
kill "$(cat /tmp/ct-rr.pid)"     # by PID; never `pkill -f`, which matches your own command line
```

Playwright installs from PyPI (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`); the browser is the pinned
one under `/opt/pw-browsers` and needs no download.
