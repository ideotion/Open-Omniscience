# Encrypted click-through — 2026-09-16 (Q1149 = a / register L7)

**Status: EXECUTED.** This is the first UI walk this project has recorded against a genuinely
ENCRYPTED corpus. Every earlier walk seeded its states with `OO_DB_PLAINTEXT=1` for speed
(`scripts/ui_clickthrough_seed.py`'s own usage line said so), so the app's encrypted path — the
one every real operator runs, and the one that starts behind a lock screen — had never been
walked. State A alone booted locked, because its job is the first-launch *create* flow.

The ruling: Q1149 = a, "add an encrypted variant to the runner", consistent with register L7
("keep plaintext for speed and add one encrypted run before a release"). The release half is now
a named per-release ritual in `CLAUDE.md` and a bar on `RELEASE_0.4_GATE.md` row V.

Artifacts: this report ·
[`encrypted-clickthrough-2026-09-16/report.json`](encrypted-clickthrough-2026-09-16/report.json)
(including the `at_rest` block) ·
[`findings.csv`](encrypted-clickthrough-2026-09-16/findings.csv) ·
[`coverage.csv`](encrypted-clickthrough-2026-09-16/coverage.csv). The 69 evidence screenshots are
NOT committed: following the 2026-08-13 and 2026-08-20 precedent the committed set is what the
findings cite, and every finding here is cited to a file and line or to a measurement reproduced
in the text, so nothing below rests on an image. Re-run `scripts/ui_clickthrough_run.py` to
regenerate them.

## 1. How it was run, and what makes it an *encrypted* run rather than a claim

```
# seed into a genuinely encrypted store: passphrase set, OO_DB_PLAINTEXT UNSET
OO_DATA_DIR=…/state-c OO_DB_PASSPHRASE='…' .venv/bin/python scripts/ui_clickthrough_seed.py

# boot with NEITHER set, so the app starts LOCKED and serves the unlock flow
OO_DATA_DIR=…/state-c OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 OO_AIRPLANE_SOCKET_GUARD=1 \
    .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

# walk it, refusing to produce a report unless a seeded state MEASURES encrypted
OO_UIWALK_ENCRYPTED_PASS='…' .venv/bin/python scripts/ui_clickthrough_run.py --require-encrypted
```

The runner walks each seeded state in through its **real `#view-unlock` form** (`#pw` →
`#btn-unlock`) rather than being handed an already-open app. Booting with `OO_DB_PASSPHRASE` set
would produce an unlocked instance and a walk that never touches the screen an encrypted operator
sees on every launch — which is most of what an encrypted variant is for.

`--require-encrypted` is the difference between a claim and a precondition: without it, "this run
was encrypted" is a sentence in a report; with it, the harness exits 2 rather than produce a
report in which no seeded, walked state measures encrypted at rest.

## 2. The at-rest attestation — `configured` and `detected`, kept apart

The record may not say "encrypted" because an env var was set; that is the **configured** value.
The app's own header read is the **detected** value, and the recorded rule for any configuration
feature is that the two are reported as separate facts — an operator whose passphrase silently did
not take has no other way to find out.

| state | when | configured | **detected** | via | cipher | custody log |
|---|---|---|---|---|---|---|
| A (virgin, 8001) | before-walk | encrypted | `absent` | `lock-state` (`fresh`) | — | — |
| B (empty, catalog-seeded, 8002) | before-walk | encrypted | **`encrypted`** | `lock-state` (`locked`) | — (the app holds no key yet) | — |
| C (populated, 8000) | before-walk | encrypted | **`encrypted`** | `lock-state` (`locked`) | — (the app holds no key yet) | — |
| A | after-walk | encrypted | **`encrypted`** | `doctor` | `4.12.0 community` | `absent` |
| B | after-walk | encrypted | **`encrypted`** | `doctor` | `4.12.0 community` | `absent` |
| C | after-walk | encrypted | **`encrypted`** | `doctor` | `4.12.0 community` | `absent` |

State A is `absent` before the walk and `encrypted` after it, which is the right reading and an
attestation in its own right: A is virgin, so the walk's own first-launch **create** flow produced
that encrypted store. B and C are encrypted before anything typed a passphrase at them.

`custody_log: absent` is honest rather than alarming — no custody log exists in these states,
which is a different fact from one existing in plaintext, and the probe reads it separately from
the corpus for exactly that reason.

**The unlock, walked rather than bypassed:**

```
state_b_unlock | verified | walked in through the real #view-unlock form (#pw -> #btn-unlock)
state_c_unlock | verified | walked in through the real #view-unlock form (#pw -> #btn-unlock)
```

**The run:** 53 walk steps · 167 coverage rows (155 verified · 7 partial · 5 blocked, each with its
reason) · 22 findings (13 positive confirmations, 8 new). The whole flagship + subtab matrix
renders on an encrypted corpus; **no finding below is caused by encryption itself.**

**Why two readings per state.** The before-walk reading is taken while an encrypted state is still
LOCKED, so it can only come from `lock-state`; the after-walk reading is taken once the walk has
unlocked it, when `doctor` answers and adds the cipher the running engine reports. One after-walk
row alone could not distinguish a store that was ALREADY encrypted from one this run encrypted
itself; one before-walk row alone has no cipher. The pair is the evidence.

### The defect the run itself found, in the runner's own design

**`GET /api/system/doctor` is not in `ALLOWED_WHILE_LOCKED` and answers `503 {"locked": true}` on
exactly the state an encrypted run boots into.** It is the endpoint whose entire job is to attest
the real at-rest state from the file header — so a doctor-only probe reports `unknown` for every
encrypted state, and `--require-encrypted` would have refused every genuinely encrypted run while
passing none. The fallback is `/api/system/lock-state`, which **is** allowlisted while locked and
whose `state` comes from the same header read (`app_lock_state` → `main_header_state` →
`state_for_header`), so it is the same fact in lock vocabulary rather than a weaker second source.
`via` records which endpoint answered.

The first design was written from `doctor`'s docstring, which describes exactly the right
behaviour and says nothing about the middleware in front of it. One boot against a real encrypted
store settled it in seconds. **The general form is worth keeping: an attestation surface tends to
be gated behind the very state it attests, because the gate is written against "the app is not
usable yet" and attestation is the one thing that must be usable then.**

## 3. A drill that raises is now a finding, not the end of the run

The first attempt at this run walked A, B and C, took all three at-rest attestations — and then
`drill_bulletin` hit a 30 s `Page.click` timeout, the exception left `main()`, and
`report.json` / `findings.csv` / `coverage.csv` **were never written**. An entire walk lost to one
broken surface, and the three attestations the encrypted run exists to produce lost with it.

That is backwards: the drill that fails is exactly the one whose failure the report should carry.
Every state-C drill now runs through `_drill()`, which records a `blocked` coverage row and a P1
finding carrying the exception, and continues.

## 4. The finding that timeout was pointing at — a real markup defect on `main`

**The Bulletin advanced section is nested inside the Uninstall & wipe section.**

`src/static/index.html:2820`:

```html
<details class="adv-sec adv-sec-danger" data-adv="uninstall">
  <summary>Uninstall &amp; wipe — irreversible: destroy the key and remove this install</summary>
  <section class="panel" id="uninstall-panel">
    <div class="phead"><h2>Uninstall &amp; wipe</h2>    <!-- The Bulletin (design record §16) … -->
    <details class="adv-sec" data-adv="bulletin">      ← the whole Bulletin section, INSIDE the phead
      …
    </details>
</div>
      <p class="muted">Both actions below are irreversible…</p>   ← the panic-wipe controls resume here
```

Measured in Chromium rather than inferred: `details[data-adv="bulletin"] > summary` has a
non-empty box (467 × 52) but `innerText === ""` and Playwright visibility `false` — the signature
of a subtree inside a *closed* `<details>`. Its parent chain is
`DETAILS(bulletin) → DIV → SECTION#uninstall-panel → DETAILS(uninstall) → DIV#set-advanced`.

**Consequences, live on `main` today:**

1. The Bulletin section cannot be reached from Settings → Advanced unless the operator first opens
   the danger-marked "Uninstall & wipe" fold — and it then renders *inside* it, above the panic
   wipe, where it reads as part of a destructive section.
2. `#uninstall-panel`'s own `<div class="phead">` wraps an entire unrelated feature.

**Introduced by `93c001a6` (2026-08-20, "Fold Safety into Advanced, split out Uninstall & wipe
(rulings 24-27, 42)")** — the same commit whose own comment, four lines above, reads: *"panic wipe
must not become hard to reach, because the person who needs it may need it in a hurry. A top-level
section is one click from the Advanced subtab; a subsection inside another fold is two, and the
second one is not obvious."* It has been live for 27 days.

**Why no test caught it.**
`tests/test_repo_invariants.py::test_the_bulletin_is_the_last_advanced_section…` asserts the
Bulletin is LAST by scanning `re.findall(r'data-adv="([a-z]+)"', markup)` — a source-ORDER check,
and the defect is DEPTH. It still passes, correctly and uselessly: a flat regex over source order
is blind to nesting by construction. **The gap to close is a structural check that every
`data-adv` section is a direct child of `#set-advanced`**, which would have failed on the commit
that introduced this.

**Not fixed in this PR, deliberately.** It is a UI markup change to a surface Q1149 does not
touch, and it needs its own Advanced-subtab re-verification (both sections, both folds, all
breakpoints). The fix is to move the Bulletin block — its comment through its `</details>` — out
of `#uninstall-panel`'s `phead` and back to a top-level sibling in `#set-advanced`, after the
Uninstall section's own `</details>`.

## 5. The second finding: an uncaught `ReferenceError` on the path an encrypted operator takes

`Home / Leads` failed its walk step with `console_errors: ['startLive is not defined']`.

**Measured, as an A/B on the same corpus and the same code:**

| boot | `typeof window.startLive` | page errors |
|---|---|---|
| the app holds the key (`OO_DB_PASSPHRASE` set) — an ordinary cold load | `function` | **none** |
| the app holds no key — the operator unlocks through `#view-unlock` | throws before it is defined | `startLive is not defined` |

**The mechanism.** `src/static/app-shell.js:151`, inside `showTab()`, calls `startLive(name, …)`
**unguarded**. `startLive` is defined in `src/static/app-library.js:1014` — six `<script>` tags
further down `index.html` (`app-shell.js` at `:3301`, `app-library.js` at `:3307`). Any `showTab`
during the window between those two files loading throws. Reproduced directly: immediately after
the unlock reaches `#tab-home`, even `showTab` itself is not yet defined.

The line *immediately above* it already guards the same hazard —
`if (name !== "timemap" && typeof stopTmapPlay === "function") stopTmapPlay();` — so the file knows
the pattern; this one call was left bare.

**Why a cold load never shows it, and the unlock path does.** `#tab-home` is static markup, present
from the first byte, so it is not a readiness signal. On a cold load nothing calls `showTab` until
a human clicks, by which time every script has landed. The unlock flow drops the operator onto the
app the instant a passphrase is accepted — which is the one moment they are certain to be acting.
**This is exactly the class of defect a plaintext-only harness cannot see**, and the argument for
the ritual rather than for this one run.

Proposed fix (not made here, see §7): guard the call the way its neighbour is guarded, or move
`app-library.js` above `app-shell.js` in the load order.

## 6. The other new findings, as recorded

| severity | surface | finding |
|---|---|---|
| P1 | `home_leads` | §5 above |
| P1 | `bulletin` (×2: the surface step and the drill) | §4 above |
| P2 | `agenda` | axe serious: `link-in-text-block`, 124 nodes |
| P2 | `tasks` | axe serious: `color-contrast`, 1 node |
| P2 | `reader` | axe serious: `color-contrast`, 2 nodes |
| P2 | app-wide | 7 used-but-unstyled class names that look presentational — triage candidates, not verdicts |
| POSITIVE | `reader` | the Reader (tabs, provenance classes, Loaded-language) is walked — the 2026-08-13 report's largest named-surface gap stays closed |

The three axe rows and the class sweep are **not new to encryption**; they are this matrix's
standing checks reporting on the current tree, recorded here because this run is where they were
measured rather than because the encrypted variant caused them.

## 7. Why the two P1s are reported and not fixed in the same PR

Both are UI defects on surfaces Q1149 does not touch, and each needs its own verification pass —
the Bulletin one across both Advanced sections and every breakpoint, the `startLive` one across the
load-order change or the guard it implies. Folding either into a harness PR would mix concerns and
make both harder to review. They are recorded here, with the exact file, line, mechanism, first
bad commit where known, and the proposed fix, so either can be picked up as its own slice.

## 8. What this run does and does not establish

**Establishes:** the seeder writes a genuinely encrypted store; the app boots locked against it;
the real unlock screen lets a walk in; the at-rest attestation is available while locked and
reports the cipher once open; and the whole flagship + subtab matrix renders on an encrypted
corpus with no encryption-specific failure.

**Does not establish, and is not claimed:**

- **State D** (the import fixture) self-skips without `OO_UIWALK_IMPORT_ARTIFACT`; this run covered
  A, B and C. The unlock hook is wired into D identically and guarded by a source test.
- **Performance under encryption.** Nothing here is a benchmark; SQLCipher costs are not measured.
- **The human UX pass.** Per the 2026-09-15 bar (Q117 = a on Q1128 = a), that is the maintainer's
  click-through and this run does not stand in for it.
- **A second engine.** Chromium only, as ruled.

---

*Open Omniscience — Global Intelligence Platform for Investigative Journalism.
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.*
