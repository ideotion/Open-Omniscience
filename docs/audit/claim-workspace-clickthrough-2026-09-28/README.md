# Claim workspace click-through — 2026-09-28 (S05-11 S1, gate 0.5 row K)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against a real server started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1`, no proxy variables, on a data folder
`seed.py` prepared: one wire story carried four ways (the wire, a near-identical copy, a rewrite
attributing the wire, a report citing the same origin page), two reports with nothing linking
them, a statistics office's record, an Arabic report and an unrelated market story. All
invented, `.invalid` hosts. The app boots in airplane mode; the workspace reads loopback only.

| Check | Result |
|---|---|
| Omnibar (Ctrl-K, claim typed) | Row 0 is still **Analysis** and it is the row Enter runs (Q608 = a); row 1 is **Check as a claim**; ArrowDown + Enter opened the workspace |
| The trail, en | 6 steps in order (① ② ③ ④ ⑤ ⑥), 4 method sentences on the page, ④ and ⑥ drawn as not built; 7 related articles; the four wire-story articles in **one path** joined by near-identical text, the shared origin page and the Reuters attribution; 3 articles under "No shared origin found" with the absence-of-evidence caveat; 7 timeline rows, the statistics record marked first in the corpus; 0 links leaving the app (every article opens the local reader) |
| Arabic | `dir=rtl`; the switch redrew the trail from the payload it held (**0 new requests**); no English left in the steps checked |
| Search tab button, ar | The search box's Arabic text became the claim; 1 related article |
| No related article | Every step drawn; ⑤ says what would be needed |
| The reader's own words | `"Tokyo"` → one path, "as you typed them"; `(glacier OR` → the grammar's own refusal on the status line (the one 400 in the log) |
| 375 px, en | No horizontal page scroll (`scrollWidth - clientWidth = 0`) |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it. **0 page errors;
no `undefined`, `null` or `NaN`.** The only console error is the deliberate 400 above.

**Found and fixed by this walk, before it was recorded:**

- **Two sentences of step ⑤ stayed in English on the Arabic page.** They were never keyed in any
  locale, and all four repo i18n gates passed: the `t()`-literal gate skips a literal carrying a
  `{placeholder}`, and the `tf()`-frame gate does not see a frame called through a parameter.
  Keyed ×12 now, and `tests/test_claim_workspace.py` checks this file's literals itself.
- **A path's article numbers read out of order** (`#3 #4 #7 #2`); they follow step ①'s order now.

Chromium-verified (remote sandbox) · awaiting human UX pass.
