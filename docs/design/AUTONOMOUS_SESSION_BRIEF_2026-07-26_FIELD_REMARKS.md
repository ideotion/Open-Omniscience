# Field Remarks 2026-07-26 — Investigation Brief

**Executing session: start with the operating manual, not this doc** —
[`AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md`](../archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md)
carries the slice table, sequencing, risk classes, skeptic mandates, and verification gates;
this doc is the fix-specification REFERENCE it routes into (items 1–3 and 6–7 are in scope
this cycle; items 4–5 and 9 are fenced out pending their own build/ruling).

**Status:** investigation complete, nothing built. Every claim below was verified against `main`
by a dedicated read-only agent (six independent investigation threads, one per remark cluster);
file:line citations are real, not inferred from the ledger's own prose. This brief is the input
for a future coding session — treat it as a punch list with root causes already found, not a
"go investigate" list.

**Source:** nine maintainer field remarks, 2026-07-26, live corpus at time of report — 700,522
articles / 6,914,218 keywords / 315,699 commodity_prices / 4,163,474 article_links / 1,031,565
mentioned_dates / 2,209 collecting sources / 1,391 sources awaiting qualification / 73,079
discovered candidates.

**Companion work delivered:** the maintainer separately sent diagnostic-log exports from 7
parallel instances on different hardware; the cross-instance comparison, now including precise,
code-cited fix specifications for every buildable finding, lives in
[`AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md).
That doc's §11 also documents an 8-machine parallel-instance confirming experiment the maintainer
ran the same day, directly relevant to this brief's item 9 (qualification wastefully judging
disabled candidates is one concrete software-side mechanism that experiment's hypothesis — a
software, not Tor-bandwidth or single-machine-hardware, ceiling on per-instance throughput — would
implicate). Read that doc's §1 (WAL/checkpoint starvation) and §2 (`/api/database/countries`)
before starting item 9's throughput-adjacent work below.

---

## Quick-reference map

| # | Item | Verdict | Fix shape |
|---|---|---|---|
| 1–3 | AI-job toggle UI (fade/no-feedback, needs real on/off, needs to auto-pick the active model, needs collapsed descriptions) | Real, single root cause across all 3 panels | Rework the polling chassis (reference pattern already exists in-repo) |
| 4–5 | Translation gaps + a screenshot/DOM-walk untranslated-text detector | Real, structurally invisible to today's tooling | New Playwright-driven `UiWalkDriver` + a locale-diff pass |
| 6 | Source-tags job: 13×(0/0) then hard failure | Root-caused: two distinct bugs (silent counter + uncaught `LLMError`) | Surface hidden counters + widen the caught-exception set |
| 7 | Keyword-triage job stops at 56 batches | Root-caused: same `LLMUnavailable`-no-retry family, worse — pause reads as "done" everywhere except one field | Retry-with-backoff + stop conflating paused/done |
| 8 | Remove P0-validation / pagesize-bench? | **KEEP both** — concrete, current, cited reasons | No removal; one ledger-staleness fix instead |
| 9 | 73,079 discovered candidates invisible to qualification's "awaiting" bucket | Working-as-designed at the counter level, but a real wiring gap underneath (qualification judges disabled candidates and then throws the verdict away) | Needs one maintainer ruling before it's buildable |

---

## 1–3. AI background-job control panels: toggle UX, model auto-selection, collapsed descriptions

**Symptom (verbatim):** "the buttons to run keyword triage, source tag management, Who / where /
when extractions should change indicating on/off. Or the UI should change and replace buttons by
toggles. Currently, users can only click buttons once, their color fades and clicking again does
not give visual feedback. Users cannot tell if each is currently active or not... All AI related
background work should use the default / active model, there shouldn't be a need to enter text to
say which model to use... Each ... section should have their respective description minimized by
default."

### Root cause (all three panels — the same copy-pasted bug)

Three panels in `src/static/index.html` (keyword-triage `:1793-1802`, source-tags `:1808-1817`,
perception-extract `:1828-1843`) each wire a single button to a JS handler
(`toggleKeywordTriage`/`toggleSourceTags`/`togglePerceptionExtract`, `src/static/app.js:11707-
11970`) that:

```js
if (btn) btn.disabled = true;
try {
  ...
  await api(".../run", { method: "POST", body: JSON.stringify({ model }) });
  if (btn) btn.textContent = t("Stop sweep");
  for (let i = 0; i < 5400; i++) {           // up to ~3h @ 2s poll interval
    ...
    if (s && s.state === "done") { ...; break; }
    set(t("Sweeping…") + detail);
    await sleep(2000);
  }
} finally {
  if (btn) btn.disabled = false;             // only reached once the loop above exits
}
```

Since these are *intentionally long-running progressive sweeps* (that's the whole point of the
2026-07-24 conversion to on/off toggles — sweep everything, not a bounded N), the button stays
`disabled` for the **entire run duration**. `app.css:248` fades any `button[disabled]`
(`opacity:.5`), and a disabled `<button>` never fires `onclick` — so a second click is a genuine
no-op, and there is no separate Stop control (same element does both roles).

`syncKeywordTriageToggle()`/`syncSourceTagsToggle()` (`app.js:11775-11861`) only re-sync the
button **label** on panel-open, not `disabled` — so reloading the page while a sweep is running
still shows a clickable-looking but functionally locked control.

### The correct reference pattern already exists in this exact file

`pollLangDetect()`/`_paintLangDetectButton()` (`app.js:4886-4973`, the language-detection
continuous job, right next to the three broken panels) does this correctly: never sets
`disabled`, uses a module-level `_langDetectPolling` flag (independent of the click closure) so
polling survives across page state, and `loadLangDetectCount()` — called on every Settings→AI
open (`app.js:1742`) — re-checks status and **restarts the poll if a job is already running**, so
the panel is honest after a reload. It also requires **zero model input**
(`POST /api/ai/detect-language {continuous:true}`).

The airplane-mode button (`_paintNetwork()`, `app.js:496-526`) is the house pattern for painting
state without disabling: SVG `fill` attribute + a CSS class (`#net-toggle.off`, `app.css:412-
413`), button always clickable, state reconciled asynchronously against backend truth.

A generic checkbox-styled toggle class already exists too (`.switch`, `app.css:736-737`, used
e.g. `index.html:636-637, 2362-2363`) if a literal switch widget is preferred over a state-painted
button.

**Collapsible-description convention already exists:** `<details class="adv-collect">
<summary class="muted" style="cursor:pointer">…</summary>…</details>` (`index.html:2031, 2097,
2119`) — none of the three `.hint` paragraphs use it; they're always visible.

### Model auto-selection: the endpoints deliberately require what the frontend deliberately asks for

`src/api/llm.py:124-153`, `active_model()` — the house-wide single source of truth every other AI
feature already falls back to (`src/api/llm.py:418,745,805,1017,1189`; `src/api/ai.py:129,391,
564`; `src/ai_layer/auto.py:100`; and crucially the **sibling module**
`src/ai_layer/perception_job.py:49` already does `model = model or active_model()`).

But the three run endpoints declare `model` as a *required* field with no fallback:
- `KeywordTriageRunBody` (`src/api/diagnostics.py:~3960`)
- `SourceTagsRunBody` (`~4089`)
- `PerceptionExtractRunBody` (`~4235`)

each `Field(..., description="an INSTALLED ... tag ...")` — mandatory, validated against
`verify_roster([body.model], installed)`, 400 on mismatch. None call `active_model()`. This is the
direct cause of the `#kt-model`/`#st-model`/`#pe-model` free-text boxes and the "Enter an installed
model tag first" dead-end toast.

### Fix shape for the executing session

1. **Backend:** make `model: str | None = None` on all three request bodies; resolve
   `body.model or active_model()` before the `verify_roster` check. Drop the three model inputs
   from the frontend entirely.
2. **Frontend:** rebuild the three toggle handlers on the `pollLangDetect`/`_paintLangDetectButton`
   pattern — never disable the control, poll via an independent flag/interval, paint state via
   `_paintNetwork`-style attribute/class toggling (or the `.switch` checkbox pattern if a literal
   switch look is preferred), and re-sync full state (not just the label) on every panel-open.
   **This is one shared bug, so build ONE reusable helper and wire all three panels to it** —
   don't re-copy-paste a fourth near-identical implementation. Check whether
   `runPerceptionEvalLive` (the separate "Run perception-eval harness" button in the same panel)
   has the same disable-for-duration issue — not explicitly confirmed by this investigation, worth
   a quick check.
3. **Frontend:** wrap each of the three `.hint` description paragraphs in
   `<details><summary>…</summary>…</details>`, collapsed by default (no `open` attribute), matching
   `index.html:2031/2097/2119`.
4. **Note for consistency, not required by the remark:** `runP0Validation`/`runPagesizeBench`
   (Settings → Data & backup) share the identical `disabled`-for-duration pattern, though they at
   least have an independent, never-disabled Cancel button. Since item 8 below keeps both tools,
   it may be worth applying the same UI fix there too while the pattern is fresh — optional, not
   requested.

### Backend test to add (the `model: str | None = None` fallback)

New tests in `tests/test_triage_and_source_tags_endpoints.py` (alongside the existing
`test_keyword_triage_run_refuses_an_uninstalled_model`/`test_source_tags_run_refuses_an_uninstalled_model`
at lines 94/169) and the perception-extract equivalent in `tests/test_perception_extract_endpoints.py`:

```python
def test_keyword_triage_run_falls_back_to_the_active_model_when_none_is_given(monkeypatch):
    """model omitted entirely (or null) must resolve via active_model() -- the SAME
    fallback perception_job.py:49 already uses -- never a required-field 422."""
    monkeypatch.setattr("src.api.llm.active_model", lambda: "installed-default:tag")
    # ... POST /api/diagnostics/keyword-triage/run with NO "model" key in the body
    # assert 200/202, and assert the run actually used "installed-default:tag"
    # (e.g. via an injected fake client asserting the model kwarg it received).
```

Mirror the identical shape for `SourceTagsRunBody` and `PerceptionExtractRunBody`. This closes the
loop the moment `model: str | None = None` + `body.model or active_model()` lands — a request with
no `model` key at all must succeed, not 422 on a missing required field.

### Frontend verification note

The three toggle-handler rewrites (backed by one shared helper, per the fix shape above) are
browser-verify-gated per this repo's own Q6a convention (`CLAUDE.md`'s "ENVIRONMENT" ruling —
frontend ships conservative + `node --check`-clean + guarded by an extended
`tests/test_repo_invariants.py::test_ui_invariants` assertion, but a human click-through is still
owed). A concrete, cheap invariant to add there: assert the shared helper function exists (by
name) and that none of the three `onclick`/button-init call sites in `app.js` still set
`btn.disabled = true` around the polling loop — the same "must be gone" source-scoped assertion
style already used elsewhere in that test file (scope the assertion to each handler's own function
body via a `def ` split, per this project's own documented "false-pass on a whole-file substring
search" lesson — never a bare whole-file grep for `disabled`, since other, legitimate uses of
`btn.disabled` exist elsewhere in the same file).

---

## 4–5. Translation coverage gaps + a GUI/screenshot-based untranslated-text detector

**Symptom (verbatim):** "translations should all be verified, including through a GUI check.
Large parts of the page is currently not translated... We should program a GUI based screenshot
session to automatically detect parts of the interface's text that is not translated / included
in the translation engine."

### What today's tooling can and cannot see

`scripts/i18n_report.py` has two checks, both static:
- `--min N` (`i18n_report.py:100-134`) diffs `src/static/locales/*.json` against `en.json`'s
  2,131-key canonical set. **It never opens any HTML/JS source** — it only compares JSON files to
  each other, so it can't tell whether a key is reachable by anything on screen.
- `--audit-chrome` (`i18n_report.py:78-88`, `_ChromeExtractor`, `:41-75`) is a static
  `HTMLParser` scan of **`src/static/index.html` only** (line 38), collecting text nodes +
  `placeholder`/`title`/`aria-label` attributes, then diffing against `en.json` keys. It executes
  nothing.

**Confirmed structural blind spots:**
- It never opens `investigate.html`, `taskmanager.html`, `unlock.html`, or the server-rendered
  reader template in `src/api/main.py` — all four load `i18n.js` and translate live, but none are
  parsed by `--audit-chrome`.
- **It never opens `app.js` (18,599 lines) — the actual UI engine.** Confirmed hardcoded,
  never-`t()`-wrapped literal strings feeding real screen content: table headers at `app.js:4341`
  (Law tab), `:7632` (Source management), `:9315` (Markets), `:15866` (Wikipedia), `:17256`
  (search/analysis); empty-state text at `:1785` (`No leads yet.`); a button label + `title`
  attribute at `:2708` ("Collapse to one actor…"). None of this exists in `index.html`'s source,
  so `--audit-chrome` reports zero gaps here while non-English locales render permanent English.
- **A live inconsistency invisible to any static tool:** the identical phrase "Loading…" is
  correctly wrapped at `app.js:2055` (`t(esc(t("Loading…")))`) and left completely bare at
  `app.js:1806` and `:3304` — both in `app.js`, so a source scan of `index.html` alone can never
  compare them.
- No tool cross-checks that a literal string passed to `t("...")` actually has a matching key in
  `en.json` — **1,845 `t("...")` call sites exist in `app.js`**; if a key is missing, `t()`'s own
  fallback (see below) silently returns the English literal with zero signal anywhere.

### `OOI18N` engine facts a detector must be grounded in (`src/static/i18n.js`)

- `t(key)` (`i18n.js:133`): `return map[s] == null ? s : map[s];` — a missing key silently
  returns the literal argument, not an error/placeholder. **There is no runtime signal
  distinguishing "never wrapped in `t()`" from "wrapped but the key is missing from this
  locale."** Both render as plain English — a detector must compare *strings*, not look for a
  marker.
- `OOI18N.tf(template, vars)` (`i18n.js:146-153`) — the composite-string templating helper; same
  fallback rule on the template string, then interpolates `{named}` placeholders with untranslated
  data. Only 4 call sites in `app.js` today.
- Locale files: `en.json` = 2,131 keys, each `"<English>": "<English>"` (English is its own
  canonical key set) + a `_meta` block; other locales (`ar bn de en es fr hi id ja pt ru zh`)
  carry the same key set with translated values. This is exactly the ground truth a detector needs
  — for locale X, any on-screen string that exactly matches an `en.json` **key** while X is active
  is a candidate.

### Existing browser-automation infrastructure

`src/monitoring/ui_walk.py` (234 lines) — **a skeleton, not a working driver.** Its own docstring:
*"NOT a real browser session... uses `UnconnectedDriver`, which fails every step with an honest
'not connected' error."* Defines `Surface`, a hardcoded 5-item `FLAGSHIP_SURFACES` tuple, a
`UiWalkDriver` Protocol (`goto`/`is_visible`/`console_errors`/`screenshot`), and orchestration —
but **no implementation of `UiWalkDriver` exists anywhere in the repo.**
`docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md` explicitly lists it as "Gated (not code
this cycle) — needs a headless browser (playwright/selenium), absent in the non-VM session."

A real Chromium-driven pass DID happen once (`docs/audit/GUI_TEST_REPORT_2026-07-22.md`,
`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md`) — ad hoc Playwright
`pip install`ed into a throwaway venv, launched against `/opt/pw-browsers/chromium-<build>`, run
by orchestrated subagents. That report states plainly (line 157): *"No `UiWalkDriver`
implementation... was built this pass... that remains a clean follow-up."* It was never committed
as reusable repo code.

**Playwright is not a repo dependency** — zero hits in `pyproject.toml` (including the `dev`
extras block), no `package.json`, no CI workflow installs or runs it. The sandbox environment
generally has `/opt/pw-browsers/` binaries and a Node `playwright` CLI pre-staged, but the Python
package needs a per-session `pip install` today.

### Proposed mechanism (concrete, buildable, grounded in the above — additive to `ui_walk.py`)

1. **Boot** the same scratch-instance recipe already proven in this exact sandbox by the
   2026-07-22 GUI-test brief (`OO_DATA_DIR` → temp dir, `OO_DB_PLAINTEXT=1`, a synthetic corpus
   seeded through `index_article` so lazy-loaded panels render real rows, airplane mode engaged —
   zero network, real corpus never touched).
2. **Drive** a real `UiWalkDriver` implementation (Playwright + the sandbox's pinned Chromium
   build) against a **drastically expanded surface list** — `FLAGSHIP_SURFACES` (5 top-level
   tabs) is far too coarse, since every confirmed blind spot above lives inside a subtab, not a
   top-level tab. Walk every sidebar nav tab × every `ooSubtabs` facet within it, plus dialogs
   that only render on interaction.
3. **Extract DOM text nodes + `placeholder`/`title`/`aria-label` attributes — not screenshots +
   OCR.** This is a byte-exact mirror of what `i18n.js`'s own `tr()`/`doText()`/`doAttrs()`
   (`i18n.js:35-79`, `document.createTreeWalker(root, NodeFilter.SHOW_TEXT)` at line 87) already
   considers "translatable chrome," so it's both cheaper and ground-truth-accurate; OCR can't
   recover `title`/`aria-label` at all (they never render as pixels) and adds font-noise for zero
   accuracy gain.
4. **Compare** per non-English locale X: for every extracted string S, check (a) `S` is an
   `en.json` key AND `X.json[key] != key` AND `S` still rendered verbatim → **engine bug**
   (highest-confidence finding — a keyed string that failed to translate live, e.g. a race or a
   stale-cached `data-i18n-dyn` container); (b) `S` is an `en.json` key but absent/identical in
   `X.json` → translator-coverage gap (what `--min` already aggregates in bulk — this pinpoints
   *where on screen*); (c) `S` is **not** a key in `en.json` at all → the highest-value new finding
   class, exactly the population `--audit-chrome` structurally can't see. Attach a screenshot per
   finding for human triage (the `screenshot(surface)` method already exists on the Protocol).
5. **Guard against false positives on real corpus data:** seed the synthetic corpus with clearly
   non-English content, or scope extraction to known chrome selectors (`<th>`, `.muted`, nav
   labels, button text) rather than trusting raw `innerText` indiscriminately — mirroring how
   `_ChromeExtractor`'s `SKIP` set already distinguishes structural regions.

This composes with the standing "R3 the AppVM runner + `ui_walk` = the browser burn-down engine"
ambition already on the roadmap — this detector is a concrete, buildable first deliverable of
that standing to-do, not a new, unrelated capability.

### Fix shape for the executing session

- **Phase 1 (immediate, no new infra):** key the concrete gaps already found above
  (`app.js:4341/7632/9315/15866/17256/1785/2708`) and fix the "Loading…" wrapping inconsistency
  (`:1806`/`:3304` → wrap like `:2055`).
- **Phase 2 (the new capability):** add Playwright as a `[dev]`-only dependency, implement
  `UiWalkDriver`, expand the surface list, build the locale-diff comparison and a downloadable
  JSON+Markdown report (matching this project's established diagnostics-report convention).

---

## 6. BUG: Source-tag assignment — 13 batches of 0/0, then hard failure; restart worked

**Symptom (verbatim):** "Source tag management should be checked, sweeping 13 batches, 0 sources
were tagged and 0 skipped, and then the process failed. After starting it again, it successfully
tagged 2 sources after a while."

### Root cause, part 1 — the "13× (0,0)" is a real, silent counter, not nothing happening

`src/ai_layer/source_tags.py::select_source_tag_candidates` (`:318-435`) ranks every `Source` row
by `(-article_count, source.id)`, resumes from a persisted `after_domain` cursor, and slices a
page. Sources below the evidence floor (`article_count < min_articles=5` or
`mention_count < min_mentions=0`) are counted into `skipped` with reason `"insufficient
evidence"` (`:385-398`) — that path **is** visible in the UI.

The vocabulary the model must pick from is *every distinct comma-split token currently on any
`Source.tags` row in the whole corpus* (`:301-315`) — no size cap, stated **verbatim** in the
prompt (`:124`). On a corpus assembled from ~2,200 collecting + tens of thousands of
discovered/legal/catalog-generated sources across many curation batches, this is plausibly
80–150+ distinct strings.

`parse_source_tags` (`:173-257`) validates by exact-or-unambiguous-fold domain match, and rejects
the **whole line** if any tag token fails to resolve against the closed vocabulary (`:242-254`).
Rejected/unmatched domains land in `pb.missing` and increment `pb.parse_failures` — **but the live
progress string** (`src/ai_layer/source_tags_job.py:634-641`) **only ever surfaces
`assigned_count` ("tagged") and `skipped_evidence_floor_total` ("skipped")**; `missing` and
`parse_failures` are written to the persisted JSONL log but never rendered anywhere in the UI
(`renderSourceTagsResult`, `app.js:11839-11852`, shows only `assigned_count`/`none_count`/
`skipped_evidence_floor`).

**Most likely explanation for 13 consecutive batches at 0/0:** the model responded without any
HTTP error, but every response in those batches failed validation (echo mismatch, or — far more
likely given the large embedded vocabulary — an out-of-vocabulary/misspelled tag token) — real
work and real rejections were happening the entire time, invisibly.

An empty page (cursor bug) is ruled out as the explanation: `if last_domain is None: complete =
True; break` fires immediately on an empty batch (`source_tags_job.py:529-531`) — it would end
the sweep after one iteration, not loop 13 times reporting 0/0. An empty page also never writes a
`oo-source-tags-batch-1` JSONL record at all (`:534`), so the downloaded log is directly
inspectable to confirm which of these actually happened.

### Root cause, part 2 — the eventual hard failure

`BackgroundJob._run()` (`src/jobs/background.py:125-138`) sets `state="error"` on **any** uncaught
exception. The progressive job only catches `LLMUnavailable`:

```python
except LLMUnavailable as exc:
    paused_reason = f"the local model became unavailable — progress is saved; start again to resume ({str(exc)[:200]})"
    break
```

but does **not** catch `LLMError` — its sibling base class, raised by `OllamaClient.generate`
(`src/llm/ollama.py:298-308`) and `VllmClient` alike for any **non-404 HTTP error status** from a
server that is up but erroring (e.g. a 500, plausibly from a context-length overflow triggered by
the large verbatim vocabulary + a 20-source batch). An uncaught `LLMError` propagates straight
through to `BackgroundJob._run()`'s catch-all, flipping the job to a hard, unresumable-in-place
`"error"` state instead of the graceful pause `LLMUnavailable` gets.

### Restart behavior — confirmed correct

The cursor is saved only after a page "settles" (`source_tags_job.py:619-633`), which the crashing
page never reached — so restart resumes past the 13 already-attempted batches, matching the
report of tagging succeeding "after a while" on later, further-down-the-ranking sources.

### Fix shape for the executing session

1. Surface `pb.missing`/`pb.parse_failures` in both the live progress detail string and the final
   result render — e.g. `"batch N · X tagged · Y skipped (evidence floor) · Z rejected
   (validation)"` — so a validation-storm is diagnosable in real time, not silently absorbed.
   `renderSourceTagsResult` (`app.js:11839-11852`) needs the two new fields threaded through; the
   backend already logs them per-batch (`source_tags_job.py:634-641` computes the detail string —
   extend it there, not just at render time, so the JSONL log and the live UI show the same
   numbers).
2. Catch `LLMError` alongside `LLMUnavailable` in the per-batch try/except — either treat it as
   pause-with-reason like `LLMUnavailable`, or (better, and see item 7's shared fix) add
   bounded retry-with-backoff before pausing.
3. Worth a follow-up question for the fix session, not confirmed as the cause here: is the
   uncapped, verbatim, corpus-wide tag vocabulary itself a contributing factor to the validation
   storm? Consider whether the prompt should cap/dedupe/normalize it.
4. Ties directly into item 1's UI fix — once the job can genuinely fail, the toggle UI needs to
   visibly distinguish "error" from "running"/"paused"/"idle."

### Precise test additions (reuse the exact `_FlakyOllama` pattern already proven for langdetect)

The 2026-07-24 Session A fix for the language-detection job (`src/ai_layer/langdetect_llm.py`,
tested in `tests/test_ai_langdetect_resilience.py`) is the exact, already-proven reference
implementation for both halves of this fix (retry-with-backoff AND the terminal-vs-transient
distinction). Its test file's `_FlakyOllama` fake client is directly reusable:

```python
# tests/test_ai_langdetect_resilience.py:55-73 (the reference to copy/reuse)
class _FlakyOllama:
    """Raises LLMUnavailable on the first ``fail_times`` generate() calls, then answers
    normally (or forever, if ``fail_times`` exceeds the number of calls the test makes)."""
    def __init__(self, reply, *, fail_times: int):
        self.base_url = "http://127.0.0.1:11434"
        self._reply = reply
        self._fail_times = fail_times
        self.calls = 0
    def is_available(self) -> bool:
        return True
    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise LLMUnavailable("simulated transient outage")
        text = self._reply(prompt) if callable(self._reply) else self._reply
        return GenerationResult(model=model, text=text)
```

Add to `tests/test_source_tags_job.py` (which already has
`test_ollama_outage_mid_run_is_an_honest_error` at line 148 — that test proves the CURRENT,
broken, zero-retry behavior and should be **kept as a regression guard on the terminal-failure
case**, not deleted, once the new tests below prove the transient case is now handled first):

```python
def test_a_transient_outage_retries_and_the_batch_still_completes(db, monkeypatch, tmp_path):
    """One simulated LLMUnavailable on a batch must NOT abort the sweep -- mirrors
    tests/test_ai_langdetect_resilience.py::test_a_transient_outage_retries_and_the_run_stays_alive
    exactly, applied to run_progressive_source_tags_job / _FlakyOllama with fail_times=1."""
    ...
    flaky = _FlakyOllama(_reply, fail_times=1)
    # wire flaky in place of the real client (same monkeypatch shape as the langdetect test)
    result = run_progressive_source_tags_job(...)
    assert flaky.calls == 2, "exactly one retry after the one simulated failure"
    assert result["assigned_count"] >= 1
    assert "error" not in result

def test_llm_error_alongside_llm_unavailable_is_also_retried_not_a_hard_crash(db, monkeypatch, tmp_path):
    """The field bug's actual trigger: OllamaClient.generate raises LLMError (not
    LLMUnavailable) on a non-404 HTTP error status from a server that is UP but
    erroring -- e.g. a 500, plausibly from a context-length overflow triggered by the
    large verbatim vocabulary. Today this is UNCAUGHT and propagates to
    BackgroundJob._run()'s catch-all, flipping state to a hard "error". Must instead
    be caught by the same retry/backoff path as LLMUnavailable."""
    # a fake client whose generate() raises LLMError (not LLMUnavailable) on the
    # first N calls, then succeeds -- same shape as _FlakyOllama but for the sibling
    # exception class; assert the run does NOT reach BackgroundJob state=="error"
    # and instead completes/pauses honestly like the LLMUnavailable case.

def test_after_the_configured_consecutive_failure_budget_the_job_gives_up_loudly(db, monkeypatch, tmp_path):
    """Mirrors test_ai_langdetect_resilience.py::test_n_consecutive_failures_gives_up_loudly_never_as_done
    exactly: a backend that never recovers must not spin forever, but the terminal
    state must be genuinely 'error' (or the job's existing honest 'paused' state),
    never a silent, benign-looking 'done'."""
    ...

def test_13_consecutive_zero_zero_batches_are_now_diagnosable_via_missing_and_parse_failures(db, monkeypatch, tmp_path):
    """Direct regression test for the reported symptom: seed a vocabulary + model
    responses that fail validation (not HTTP failure) on every source in several
    consecutive batches -- assert the live progress detail string / final result now
    surfaces non-zero pb.missing / pb.parse_failures (the fix for item 6's Fix-shape #1),
    instead of a silent 0-tagged/0-skipped batch that looks like nothing happened."""
```

---

## 7. BUG: Keyword-triage stops after 56 batches / 984 verdicts

**Symptom (verbatim):** "Keyword triage stopped after testing 56 batches with 984 verdicts."

### Confirmed NOT a scope limit

`select_triage_batch_after` (`src/ai_layer/triage.py:415-444`) is confirmed full keyset pagination
over `Keyword.article_count >= 1` — since `article_count` is "distinct articles mentioning the
keyword" (`src/database/models.py:899-901`), `>= 1` is functionally the entire ~6.9M-row table,
not a head-scope filter. No `max_batches`/`limit` is reachable from the API
(`KeywordTriageRunBody` exposes only `model`/`restart`), and no scheduler ride-along caps it.
56 × (25 real + 2 canaries) ≈ 1,500 keywords considered — nowhere near exhausting the table, so
`chunk` coming back empty (`complete = True`) at batch 56 is implausible.

### Confirmed cause: same family as item 6, worse in one respect

`run_progressive_triage_job` (`src/ai_layer/triage_job.py:362-390`) catches exactly one exception
around one `client.generate()` call per batch:

```python
except LLMUnavailable as exc:
    paused_reason = "the local model became unavailable — progress is saved; start again to resume (...)"
    break
```

**Zero retry, zero backoff** — a single connection failure/timeout (default timeout 120s,
`ollama.py:187`) ends the run immediately. This part matches item 6 exactly.

**What makes this one worse:** the pause path *is* the tested, intended design — but it collapses
"paused, resumable" and "genuinely finished" into the **identical** `BackgroundJob.state ==
"done"`, and this is test-pinned as intentional
(`tests/test_triage_and_source_tags_endpoints.py:207-270`):
```python
assert body["state"] == "done"
assert body["result"]["complete"] is False
assert "simulated outage" in body["result"]["paused_reason"]
```
The consequences, all confirmed by direct code read:
- `GET .../status` reports `"done"`.
- `GET .../last` (reading the JSONL) reports `"in_progress"`, because a pause never writes the
  completion footer (`triage_job.py:435-449`, `if complete: ... export_triage_jsonl(...)`). **These
  two endpoints disagree with each other about a paused run.**
- `/api/jobs` (the generic task manager) filters out any job whose `BackgroundJob.state` is not
  `"running"` or `"error"` (`src/api/jobs.py:441-443`) — so a paused-but-resumable sweep becomes
  **invisible in the task manager entirely.**
- Nothing anywhere automatically re-invokes `/keyword-triage/run` — only a manual click in
  Settings → AI resumes it, and nothing in the app currently prompts the user that a resume is
  needed.

### Arithmetic sanity check

984 verdicts / 56 batches ≈ 17.6 verdicts per ~27-keyword batch ⇒ ~65% valid-yield across **56
full, complete batches** (batch atomicity means either a batch fully succeeds and its totals are
added, or the exception fires before anything is added — no partial-batch accounting exists). This
is consistent with a clean stop *between* batches — exactly the `LLMUnavailable`→`break` shape —
not a crash mid-batch or a cursor bug.

### Secondary findings (worth a look, not the cause of this report)

- The old one-shot `run_keyword_triage_job` has zero live callers (dead from the API's
  perspective), yet its own test asserts `state=="error"` on outage — giving false confidence
  about the wired path, which behaves completely differently (pause → `"done"`, never `"error"`).
- After a sweep genuinely completes, the *next* un-`restart`ed call silently resets the cursor and
  starts a fresh sweep from scratch (`triage_job.py:313`) rather than staying "finished," which
  contradicts the function's own docstring — a documentation/behavior mismatch, not implicated in
  this specific report.

### Fix shape for the executing session

1. **Shared fix with item 6:** add bounded retry-with-backoff before treating a single
   `LLMUnavailable`/`LLMError` as pause-worthy. This exact pattern was already ruled and shipped
   once in this codebase for the language-detection job (Session A, 2026-07-24 — "the resilient
   retry-with-backoff job, never abort-to-done") — use it as the template rather than inventing a
   new one, and apply it uniformly to keyword-triage, source-tags, and (worth checking)
   perception-extract, since all three share the same progressive-sweep chassis shape. The exact
   reference implementation is `src/ai_layer/langdetect_llm.py`'s worker loop, backed by
   `ai_api._LANGDETECT_BACKOFF_BASE_S`/`_LANGDETECT_BACKOFF_CAP_S`/`_LANGDETECT_MAX_CONSECUTIVE_
   FAILURES` (`src/api/ai.py`) — port the same three constants + the same retry-then-give-up-loudly
   shape into `src/ai_layer/triage_job.py:run_progressive_triage_job` (around the single
   `except LLMUnavailable as exc: ... break` at lines 362-390).
2. Stop conflating "paused, resumable" with "done" at the `BackgroundJob.state` layer — either a
   distinct state value, or ensure `paused_reason` is surfaced consistently in `/status`, `/last`,
   AND `/api/jobs` (today only `/status` shows it).
3. Reconcile the `/status` vs `/last` disagreement on a paused run.
4. Fold into item 1's UI rework: the Settings → AI toggle should honestly show "paused — click to
   resume," not silently revert to "Start sweep" with no explanation.
5. Small cleanup, low priority: mark/remove the dead `run_keyword_triage_job` one-shot function and
   its misleading test, or explicitly flag in its docstring that it isn't what the live endpoint
   calls.

### Precise test additions

Mirroring the `_FlakyOllama` pattern documented under item 6 above (reused verbatim from
`tests/test_ai_langdetect_resilience.py`), add to `tests/test_triage_job.py` (which already has
`test_ollama_outage_mid_run_is_an_honest_error_never_a_fabricated_completion` at line 182 — keep
it as the terminal-failure regression guard):

```python
def test_a_transient_outage_retries_and_the_sweep_continues_past_batch_56(db, monkeypatch, tmp_path):
    """Direct regression test for the reported symptom: seed enough keywords for well
    over 56 batches, inject exactly ONE LLMUnavailable failure partway through (e.g.
    at batch 56, matching the field report's own arithmetic -- 984 verdicts / 56
    batches), and assert the sweep RETRIES and continues past batch 56 rather than
    stopping there. Mirrors
    tests/test_ai_langdetect_resilience.py::test_a_transient_outage_retries_and_the_run_stays_alive."""
    flaky = _FlakyOllama(_reply, fail_times=1)  # fails once, at some batch boundary
    ...
    result = run_progressive_triage_job(...)
    assert result["batches_logged"] > 56
    assert "error" not in result

def test_status_and_last_agree_on_a_paused_run(db, monkeypatch, tmp_path):
    """Direct regression test for the confirmed /status-vs-/last disagreement: after
    a run pauses (state=="done" at the BackgroundJob layer per the existing,
    intentionally-pinned test at tests/test_triage_and_source_tags_endpoints.py:207-270),
    BOTH GET .../status AND GET .../last must report the SAME completion state --
    today .../last reads "in_progress" (triage_job.py:435-449 never writes the
    completion footer on a pause) while .../status reads "done". Pick one honest,
    consistent representation and assert both endpoints agree on it."""

def test_a_paused_run_is_visible_in_the_task_manager(monkeypatch):
    """Direct regression test: /api/jobs (src/api/jobs.py:441-443) filters out any
    job whose BackgroundJob.state is not "running"/"error" -- so a paused-but-
    resumable sweep is invisible in the task manager today. After the fix (either a
    distinct paused state, or /api/jobs's filter widened to include a paused
    progressive sweep), assert the job DOES appear in GET /api/jobs while paused."""
```

---

## 8. P0 validation + pagesize A/B bench — recommendation: KEEP BOTH

**Symptom (verbatim):** "P0 data-safety validation has been done and is successful, shouldn't we
remove it entirely? Same for Page size A/B bench. In case you see future use for them, explain to
me, if not, remove entirely."

### `src/monitoring/p0_validation.py` — KEEP

Two currently-**open** gate conditions in this repo's own governing documents explicitly require
re-running this exact tool:

- `RELEASE_0.3_GATE.md` (repo root, dated 2026-07-21) row 7: *"v0.2.0 P0 follow-ups: cold-boot
  unlock at full scale + multi-day live collector soak | Blocked — hard | ...out of scope for an
  autonomous session entirely, not attempted"*; row 4: *"Full DB import re-checking ALL sources at
  scale (doubles as backup/restore-at-scale validation) | Blocked — hard"*.
- `CLAUDE.md`'s own current "0.3 CLOSE GATE" row 7 (edited 2026-07-25, i.e. current): *"the v0.2.0
  P0 report's OWN follow-ups CLOSED — cold-boot unlock at full scale on the complete corpus + a
  multi-day live collector soak... both were flagged by the P0 report itself as not-yet-confirmed."*
- The module's own code encodes this as its designed re-entry point:
  `p0_validation.py:533-539`/`:616-620` (`_COLD_BOOT_HOWTO`/`_SOAK_HOWTO`) literally instruct
  "re-run this validation immediately after" a cold boot or a multi-day soak.
- It's also a named, live KPI source (K3, "Backup at corpus scale") in
  `docs/design/V1_PATHWAY_2026-07-14.md`'s K1–K14 board, intended to be re-triggered "when the
  backup/scale engines changed," as part of a recurring improvement cycle — not a one-shot
  artifact.

Fully wired: 5 API routes, a Settings panel, an all-diagnostics bundle member, a dedicated test
file (412 lines) plus an invariant guard. Removing it would also require editing the diagnostics
bundle's coverage-ratchet map (`test_all_diagnostics_bundle_covers_every_get_diagnostic` would
fail otherwise).

### `src/monitoring/pagesize_bench.py` — KEEP (stronger case)

- **It is now production-code-coupled, not a standalone artifact.** `src/database/connect.py`
  (`:84-98`, `:329-333`) — the app's live DB connection factory — directly cross-references this
  module's constants and proven pragma-ordering **by name** in load-bearing code comments: *"the
  same domain `pagesize_bench.py`'s own `_ALLOWED_PAGE_SIZES` covers"* and *"matching
  `pagesize_bench.rebuild_at_pragmas`'s proven ordering exactly."* The empirical fact this bench
  proved (cipher_page_size must be set before auto_vacuum on a fresh SQLCipher connection) is what
  production code now relies on.
- **It's the named reference implementation for a not-yet-built future feature.** CLAUDE.md's
  "BACKUP/RESTORE BAR = PLAIN-FOLDER-COPY PARITY" ruling (2026-07-17) states the honest way to
  migrate an *existing* corpus to new pragmas is a store rebuild "the same machinery `connect.py`
  already uses" and explicitly says to verify the target honors the pragmas "a P2.4-style probe —
  never assert it from docs." No `migrate_store` function exists yet; `rebuild_at_pragmas()` is
  that already-proven, self-verifying probe.
- A still-open remediation brief
  (`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_PR740_PR744_REMEDIATION.md:161-227`)
  explicitly instructs future sessions to read `rebuild_at_pragmas()` *first* before writing
  related code, and cites its measured rebuild-seconds-per-GB for time estimates elsewhere.
- Its own docstring states the design intent is a repeatable trend instrument: *"compare the TREND
  across corpus sizes/machines, never one point alone"* — consistent with re-running it as the
  corpus scales toward the 5 TB target, not a single decision aid.

Same wiring depth as p0-validation (5 routes, Settings panel, bundle membership, 263-line test
file, invariant guard).

### A ledger-staleness bug found along the way (fold into the same PR)

CLAUDE.md's own "0.3 CLOSE GATE" row 6 currently reads *"the §1b `page_size` ruling MADE on that
evidence (currently waiting on the large-corpus run..."* — but `docs/ledger/shipped.csv`
(2026-07-23 row) and `connect.py`'s own commits (`248253c`, `cc76426`, both 2026-07-23) show
`page_size=16384`/`auto_vacuum=INCREMENTAL` are **already live in production** for every fresh
corpus, and the shipped.csv row is self-labeled as the ratification. CLAUDE.md's most recent edit
(2026-07-25) touched a different clause of the same gate and missed updating this one. This is
exactly the "ledger failure — fix the gap AND the ledger" pattern this project's own protocol
calls out. **Recommend a small, separate housekeeping fix: update CLAUDE.md row 6's wording to
reflect that §1b already shipped**, distinct from (and much smaller than) the bench-removal
question this remark actually asked.

### Full blast-radius list (kept for reference if either is ever removed after its open dependency closes)

Both tools' complete file inventories (API routes, bundle membership, frontend panels, tests,
docs) were compiled during this investigation and are available on request — omitted here since
the recommendation is KEEP, not remove.

---

## 9. Why 73,079 discovered candidates never show up in "sources awaiting qualification"

**Symptom (verbatim):** "2,209 Sources (collecting) / 1,391 Sources awaiting qualification
(enabled) / 73,079 Discovered candidates. How come the 73079 discovered candidates are not part of
the sources awaiting qualification?"

### The three numbers, exact source

`database_stats()` (`src/api/database.py:159-173`), rendered via `DB_STAT_LABELS`
(`app.js:6994-6999`):

```python
counts["sources_qualified"]   = enabled=True  AND status == "qualified"    # "Sources (collecting)"
counts["sources_pending"]     = enabled=True  AND status != "qualified"    # "Sources awaiting qualification (enabled)"
counts["sources_candidates"]  = enabled=False                              # "Discovered candidates"
```

These three **partition** the full `sources` table exactly (they sum to the total row count,
which the UI deliberately hides — `DB_STAT_HIDDEN_KEYS`). By construction, a row cannot be counted
in both "candidates" and "awaiting qualification" — they're opposite states of the single
`Source.enabled` boolean.

### Confirmed: every live discovery/promotion channel hardcodes `enabled=False`

- World-discovery (`src/catalog/discover.py:100-103`): `kwargs["enabled"] = False  # review-before-enable`
- Citation-candidate promotion (`src/api/source_management.py:107-114`) and the citation-count
  auto-promotion pass (`src/discovery/cited_sources.py:148`): both hardcode
  `enabled=False,  # the operator's deliberate act stays required` / `# metadata only`.

This matches — and is intentional per — the standing 2026-07-15/2026-07-20 ledger rulings
("every find stays a DISABLED source for review... AUTOMATION COVERS DISCOVERY, NEVER ENABLING").
**At the counter level, this is working exactly as designed, not a bug.**

One minor inconsistency noted in passing: `scripts/build_world_news_catalog.py` →
`seed_default_sources()` (the offline generator + boot-seed path) never writes an `enabled` key at
all, so those rows fall through to the SQLAlchemy column default (`enabled=True`) — different
posture from the two live discovery channels above. Likely low-impact since this file doesn't
appear to be the source of the current 73,079 rows (per the 2026-07-23 field-diagnostics analysis,
`world_news_sources.yml` was not generated/committed at that time) — flagged for completeness, not
as the cause of this remark.

### The real gap: qualification judges disabled candidates and then discards the verdict

`select_unqualified()` (`src/catalog/qualification.py:178-224`) — used by BOTH the scheduler
ride-along and the bulk backlog-drain job — filters **only** on `Source.status ==
STATUS_UNQUALIFIED`, with **no `Source.enabled` filter at all**. `trial_fetch()`/`ingest_source()`
(`src/ingest/pipeline.py:390-408`) act purely on `rss_url`/`domain` and never check `enabled`
either. So the qualification job genuinely trial-fetches, stores real articles from, and judges
disabled candidates too — but `evaluate_and_stamp()` (`qualification.py:273-307`) writes only
`status`/`qualified_at`/`qualification_criteria_version`, **never `enabled`**. A disabled
candidate that gets a `qualified` verdict stays `enabled=False` forever: permanently invisible to
`select_sources()` (the scheduler's actual collection admission gate, which DOES filter
`enabled=True`), and permanently still counted as a "Discovered candidate" in the UI regardless of
its internal status.

No auto-enable-on-qualified hook exists anywhere. No bulk-enable UI control exists. The "Phase-2
promotion frontier (candidate → trial → graduated)" repeatedly referenced in the ledger since
2026-07-13 is confirmed still entirely unbuilt.

### Plain-English answer for the maintainer

The two numbers are opposite states of one switch (`Source.enabled`), and by deliberate,
repeatedly-reaffirmed design, nothing in the app flips that switch automatically — so a discovered
candidate can never appear in "awaiting qualification (enabled)" until something manually enables
it. That much is intentional. But underneath the visible counters, the qualification job doesn't
actually respect that boundary — it silently trial-fetches and judges disabled candidates anyway,
and then throws the verdict away, since nothing wires a successful judgment back to `enabled`. So
today, real network effort is being spent qualifying 73,079 sources whose qualification currently
means nothing.

### This needs one maintainer ruling before it's buildable — two coherent directions

**(a) Tighten the gate:** add `enabled=True` to `select_unqualified()`'s filter, mirroring
`select_sources()`. Qualification then never touches a candidate until something enables it first
— candidates stay purely in the "discovered" bucket, no wasted trial-fetch effort, but the
73,079-row backlog then needs a *separate* enable step (manual or automated) before it can ever be
qualified at all.

**(b) Close the loop:** have `evaluate_and_stamp()` flip `enabled=True` on a successful `qualified`
verdict, implementing a slice of the long-parked Phase-2 promotion frontier — qualification itself
becomes the auto-promotion mechanism. This reading is more consistent with the maintainer's own
2026-07-20 ruling language ("QUALIFICATION IS THE ADMISSION GATE — only QUALIFIED sources are
scraped... every not-previously-qualified source gets the qualification pass BEFORE joining
regular collection"), which reads as already assuming discovered candidates flow *through*
qualification into collection, not around it.

**Recommend surfacing this exact (a) vs (b) choice to the maintainer before building** — it's a
real scale/throughput decision (73,079 candidates × real trial fetches over Tor is meaningful
bandwidth, and this ties directly into the qualification-backlog-scale concerns already on record
from the 2026-07-23 field diagnostics), not something to default silently.

---

## Cross-cutting notes for the executing session

- **Items 1, 6, and 7 share one underlying architecture problem**: the progressive-sweep
  `BackgroundJob` chassis used by keyword-triage, source-tags, and (likely, unconfirmed)
  perception-extract all copy-paste the same broken polling/disable pattern (item 1) and the same
  too-narrow, no-retry exception handling (items 6/7). **Fix once, as a shared helper/pattern, not
  three times.** The already-shipped language-detection job (`pollLangDetect`/
  `_paintLangDetectButton`, and its Session-A 2026-07-24 retry-with-backoff fix) is the correct
  reference implementation for both halves of the fix.
- **Item 9's finding (qualification silently judging disabled candidates) is one concrete
  software-side mechanism directly relevant to the maintainer's 2026-07-26 8-machine confirming
  experiment** (a parallel-instance test of whether per-instance throughput is Tor-bandwidth-bound,
  single-machine-hardware-bound, or software-bound — see the companion doc's §11). It's also
  cross-referenced against the companion hardware-diagnostics doc's §1 (WAL/checkpoint starvation
  — the single highest-value structural fix, universal across all 7 instances) and §2
  (`/api/database/countries` scaling ceiling) — both now have precise, code-cited fix
  specifications and are the recommended FIRST builds if the goal is raising per-instance
  throughput, ahead of resolving item 9's (a)/(b) qualification-gate question.
- None of items 1–7 require a maintainer ruling to build — they're bug fixes with clear, cited
  root causes. Item 8 requires no build at all (explicit keep + one small ledger fix). **Item 9 is
  the only item in THIS doc that needs a decision before code gets written** (the companion
  hardware-diagnostics doc's §1/§2/§6/§7/§8/§9.1 fixes are all buildable without a ruling too).

## Recommended sequencing

0. **(New, highest-leverage for throughput) The companion hardware-diagnostics doc's §1
   (WAL/checkpoint starvation) and §2 (`/api/database/countries`)** — universal across all 7
   diagnosed instances, both now have complete fix specifications with exact code/tests, and both
   are plausible concrete mechanisms behind whatever software-side ceiling the maintainer's
   8-machine confirming experiment is probing. Consider building these ahead of, or alongside,
   items 1/6/7 below if throughput is the priority.
1. Items 6+7 (data-safety/visibility adjacent — jobs silently failing or looking done when they
   aren't) and item 1 (the UI that makes both bugs invisible to the user in the first place) — do
   these together as one PR, since the retry/backoff fix and the UI rework touch the same three
   panels and the same handful of backend job files.
2. Item 8's small ledger-staleness fix — trivial, standalone, do it whenever.
3. Item 9 — put the (a)/(b) question to the maintainer, then build whichever is chosen.
4. Items 4–5 (the i18n gap-fill + the new screenshot-detector build) — the larger, more
   open-ended build; the Phase-1 immediate keying fixes can ride with item 1's PR since they're in
   the same files, but the new `UiWalkDriver` infrastructure is its own, bigger effort.
