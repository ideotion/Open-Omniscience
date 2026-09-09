# Runtime i18n audit (2026-09-08)

> Produced by the live visual audit of 2026-09-08 —
> see [`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`](../audit/11_VISUAL_UI_AUDIT_2026-09-08.md) for the
> method and the honest scope. **Report-only: nothing here was fixed.**
>
> Four locale sweeps across all 12 languages × 15 surfaces, four targeted probes, two translation-quality
> reviews, and one adversarial re-verification pass that re-derived every headline claim from source and
> from a live browser rather than trusting the sweeps.
>
> **A correction this document must carry, because the orchestrating session got it wrong first.** The
> 2026-09-08 code audit's finding §4.1 — that the completeness gate's regex matches only literal `t(` and
> is structurally blind to the `t9()`/`t9m()` alias family — **was true when written and is no longer
> true.** Commit `860ab73` ("Fix i18n audit tool blind spots: t9/t9m aliases + the guis/ directory")
> landed before this audit; `scripts/i18n_report.py:148-154` now matches `t9(` and `t9m(` and carries a
> comment explaining that exact bug, and `_guis_js()` brings the skin directory into scope. This session
> repeated the stale finding before checking it. **[hand-verified]**
>
> The real picture, measured by running the tool in this session:
>
> | mode | what it measures | today | CI ratchet | slack |
> |---|---|---|---|---|
> | `--min 100` | locale-file key parity | 3,151/3,151 = 100.0% | =100 % | 0 |
> | `audit_chrome()` | chrome strings with no `en.json` key | **552** of 2,771 | ≤554 | **2** |
> | `unkeyed_t_calls()` | call sites with no key | **294** of 2,002 | ≤295 | **1** |
>
> So the gate is not blind in the way the earlier finding said. The sharper problem is that **the two
> real ratchets are caps on growth, not requirements to close the gap**: a fully green CI run today is
> compatible with 552 permanently-English chrome strings, with two strings of headroom before a
> regression would be noticed. And three mechanisms remain invisible *by construction* — none of their
> strings are counted in the 552 — one of which carries an informed-consent string. §2 is the table.

---

# Runtime i18n audit

*Open Omniscience — synthesis of 4 locale sweeps, 4 live probes, 2 translation-quality reviews, and one adversarial re-verification pass. Port range 8011–8039 (STATE C, 453 articles / 3,618 sources / 8 languages), theme=ink, 1440×900 unless noted. Claims below are the adversarially-verified set — source-confirmed and, where noted, live-reproduced in this session's own browser passes.*

**Honest stamp: Chromium-verified (remote sandbox) · awaiting human UX pass.**

---

## 1. The headline number: reported coverage vs measured runtime coverage

`scripts/i18n_report.py --json` reports **3,151 keys, 100.0% coverage across all 12 locales**. That is the number CI prints and the number the project's own session ritual ("locale files must stay 100%... when adding chrome strings") is built around.

It is real, and it is also the least informative of the three numbers the tool itself computes, because it measures exactly one thing: *does every locale JSON file contain a value for every key `en.json` has*. It has no path back to the rendered page at all, so it is unconditionally blind to any string that was never extracted into a key in the first place.

Re-running the tool's other two functions live in this session gives the honest picture:

| Metric | What it measures | Live count today | CI ratchet | Slack |
|---|---|---|---|---|
| `--min 100` | locale-file mutual key parity | 3,151/3,151, 100% | required =100% | 0 (by design — but blind to extraction gaps) |
| `audit_chrome()` | HTML+JS chrome strings not in en.json | **552 missing** / 2,771 scanned | `≤554` | **2** |
| `unkeyed_t_calls()` | `t()`/`t9()`/`t9m()` call sites with no key | **294 unkeyed** / 2,002 sites | `≤295` | **1** |

Both real ratchets are **caps on growth, not requirements to close the gap** — a fully green CI run today is explicitly compatible with 552 permanently-English chrome strings and 294 unkeyed call sites, and has almost no headroom left before it would have to notice a regression (2 strings, 1 call site).

And even those two numbers undercount the real gap, because — see §2 — three entire files/mechanisms are invisible to `audit_chrome()`/`unkeyed_t_calls()` by construction: the article reader's server-rendered HTML (`src/api/main.py`), the Task Manager's and Unlock screen's inline `<script>` blocks, and canvas-drawn text (Observatory). None of the strings confirmed missing in those three surfaces (§3) appear in the 552/294 above. So "100.0%" on the dashboard, "552 missing / 294 unkeyed" in the tool's own stricter modes, and a materially larger true gap once the tool's blind spots are counted, are three different facts, in increasing order of honesty and decreasing order of visibility.

---

## 2. What the gate cannot see — the mechanism table, and the exact fix for each row

| Mechanism | Where | Seen by the gate? | Root cause | The fix |
|---|---|---|---|---|
| `t()`/`t9()`/`t9m()` calls, quoted literal | `app-*.js`, `guis/*.js` | **Yes** | — | already working (t9/t9m alias + `guis/` scope fixed in commit `860ab73`, prior to this audit — see §10) |
| Same calls inside an inline `<script>` | `taskmanager.html`, `unlock.html` | **No** | `_ChromeExtractor.SKIP` excludes `script` content entirely, and `_aux_js()` only globs `app(-[a-z-]+)?\.js` + `reader.js` — never these two files | Add the two files' inline scripts to the JS-scanner file list, not just the HTML-text scanner |
| Static HTML text/`title`/`placeholder`/`aria-label` | `index.html` + aux HTML files' markup | **Yes**, via `_ChromeExtractor` | — | this is where the real 552 come from |
| Server-rendered Python f-string HTML | `src/api/main.py` (article reader, `/api/articles/{id}/view`) | **No, structurally** | The tool has zero code paths into `src/api/` in any mode | Give the tool an `src/api/main.py` scan path, or move these strings into a client-rendered template so the existing JS/HTML scanners see them |
| Chrome text inside a backtick template literal, unwrapped in `t()` | ~12 of 18 `app-*.js` modules + `reader.js` (sampled ~50 candidates, 47% of a 15-string spot-check unkeyed) | **No** | Every extraction regex requires a `"` or `'` delimiter; none matches backtick-delimited strings | Extend the regex family to also match inside backtick template literals |
| `reader.js` itself | `src/static/reader.js` | **Partially** (the tool's own shape-regex count for this file is 7; a manual read found 14+) | Zero calls to `t()`/`t9()`/`t9m()`/`OOI18N.t()` anywhere in 575 lines (grep-confirmed) — some strings translate only by *coincidence*, matching an unrelated key elsewhere | Wire `reader.js` to `t()`/`t9()` properly, then the existing scanners will see it |
| Canvas-drawn text | `oosky.js:495` (Observatory's 12 domain-wedge labels) | **No, structurally** | `ctx.fillText(da.domain, …)` — canvas paint has no DOM node for any text-based scanner (or the i18n MutationObserver walker) to see | Wrap the value in `t()`/`OOI18N.t()` before the `fillText` call; register the 11 missing domain-name keys |
| CSS `content:"…"` | any `.css`/`guis/*.css` | **No scan path exists** | — | Currently 0 live instances (checked) — a latent gap, not an active one |

The unifying lesson: **"100% coverage" only ever describes the strings the tool was told to look at.** Every row above is a place a string can be 100% present in every locale file and still render in raw English on screen, because it was never counted as a string that needed a key.

---

## 3. Untranslated strings actually on screen

Consent/security/informed-consent strings first, per the project's own priority.

### Consent, safety, and informed-consent-critical (P0/P1)

| Text | Surface(s) | Live-confirmed | Root cause | Evidence |
|---|---|---|---|---|
| **Article reader's external-link consent note** — "Opening the source makes a live request from your machine; the site may see your visit. You'll be asked to confirm." — plus "Author", "Captured (downloaded)", "Content hash", the full dates-extraction caveat paragraph, "Extract dates from this article" | `/api/articles/{id}/view` (the local reader, invariant #6/#17) | **Yes** — ru screenshot, surrounding chrome (Опубликовано, tab labels) correctly Russian, these 5+ strings raw English | `src/api/main.py` f-string template, no `t()` path exists at all | `reader-ru-234.png` (this pass), `EVIDENCE`/`reader-ru-top.png` (gate-blindspot probe) |
| **Agenda's top informed-consent caveat**: "A forward-looking agenda of major recurring events. Fixed civic dates are confirmed; summit/meeting dates move each year — follow the official source for the exact date. Nothing here is fabricated." | agenda, **all 12 locales** (source-level, not fr/es/pt/id-specific) | Yes (ru, fr, es, pt, id) | `src/api/events.py`'s `_CAVEAT` says "agenda"; every locale JSON key still says the pre-rename "calendar" wording — exact-match lookup fails, falls through to English | `textmap-ru-agenda.json`; sweep-romance `EVIDENCE-fr-agenda-nextprev-tooltip.png` |
| **Home Lead-card "why am I seeing this" rationale**: "Ranked by a disclosed order (independent sources → sample magnitude → recency), never a score…" (invariant #9/#23 trigger-audit-trail text) | home, every card, **all 12 locales** | Yes — 4 occurrences per Home load confirmed live in ru | `leads.py`'s `explain_order()` is a raw Python f-string, never routed through `t()`/`tf()` | `textmap-ru-home.json` (this pass); indic-rtl F2 |
| **Home Lead-card substance** (title, `.sum` summary, `.card-caveat`, method text, the math table, the type chip) — e.g. "3 sources, one origin: wire-agency.example", "Only ZH Regional Herald cn carried this…" | home, **every card, all 12 locales** | Yes | `producers.py` builds `Card.summary`/`.caveat`/`.method` as raw f-strings; `cardHtml()` (`app-home.js`) does `esc(c.summary)` etc. directly, with no `summary_i18n`/`summary_vars` counterpart to the `title_i18n` pattern that already exists one field over | `textmap-ru-home.json` (this pass); indic-rtl F1 |
| **`#net-toggle` aria-label** ("Airplane mode (network on/off)") — the kill switch, invariant #14 | top bar, **every one of 16 surfaces, all 11 non-English locales** | Yes — cold-load ru: title correct Russian, aria-label still literal English | `data-i18n-dyn` opts the element out of the generic walker's attribute pass; `_paintNetwork()` updates `.title` on every state change/langchange but never calls `setAttribute('aria-label', …)` — even though the correct translation exists and is unused in all 11 locales | `aria-check-ru-coldload.json` (this pass, cold load); sweep-romance/germanic-slavic/cjk/indic-rtl all confirm independently |
| **`#rate-toggle` title + aria-label** (collection-speed governor) | top bar, every surface | Yes — cold Russian load renders the full English sentence deterministically, not intermittently | `loadRateMode()` runs synchronously in `app-boot.js` **before** `i18n.js`'s `DOMContentLoaded`-gated `init()` even starts fetching the locale JSON, so `t9()` always resolves against an empty map on first paint; `_paintRateMode` is the one top-bar control **absent** from the single `oo:langchange` re-render listener, so it never self-heals for the rest of the session unless the button is clicked (which also changes the setting). aria-label has **no key in any of the 12 locale files at all**, including en.json | `aria-check-ru-coldload.json` (this pass) |
| **Task Manager's** CPU / Memory / Disk I/O / Network ↓ / Live / degraded / the empty-state sentence | Task Manager window (invariant #20, per-job rate/ETA extension) | Yes — ru: surrounding chrome (Ожидание, Процессы, Очередь, Расписание) correctly Russian, these 6+ labels raw English | Live inside one inline `<script>`, invisible to both scanner modes (§2); `en.json` has zero entries for these literals at all — not a translation gap, a registration gap | `ru-taskmanager-standalone.png` (this pass) |

### Elsewhere — real, but lower-stakes (P1–P3)

| Text | Surface | Scope | Root cause |
|---|---|---|---|
| Search result count: "N result(s)" | search, every result | all 12 locales, every search | `app-analysis.js`, not wrapped in `t()`/`tf()` at all; no plural handling even in English |
| `commodity_prices` / `article_links` / `mentioned_dates` (raw field names) | Library → Database panel | **all 12 locales AND English** — a plain bug, not a translation gap | `DB_STAT_LABELS` map covers only the `sources_*` keys |
| "sources qualified" / "sources pending" / "sources candidates" | Home stat strip | **all 12 locales AND English** | `HOME_STAT_LABELS` map, independently drifted from the Library one above, missing the same class of newer field |
| 12 Observatory domain-wedge labels (Technology, Climate & environment, …) | Observatory canvas | all 12 locales | `oosky.js:495` `fillText`, no `t()` wrap possible on canvas text without an explicit call |
| Chinese/CJK keyword chips are unsegmented whole clauses (e.g. "分析人士指出") | Insights → Map, `cn` row | zh-sourced content, any UI locale | `keyword_extractor.py` categorizes by `len(w.split())` — whitespace-only; no CJK segmenter (no jieba) |
| `reader.js` chrome: "Keywords in this article", "Summarize now", "Translate now", the per-keyword "Analyse … across your corpus ↗" hover | article reader | all 11 non-English locales | Zero `t()`/`t9()`/`OOI18N.t()` calls anywhere in the file (grep-confirmed) |
| 15 of 17 theme names (Ink, Slate, Midnight, Arctic, Cyber, Forest, Aubergine, Garnet, Solar, Sepia, Terminal, Contrast, Mist, Dawn, Mint, Paper) | Settings → Appearance | all 12 locales | No key exists for any of the 15; only Light/System have one |
| "Compare" (Law subtab), "adv" (Commodities nav badge), "previous"/"next" (Agenda month arrows), "🛒 Draft (" / ") →" | law / nav / agenda / home | all 12 locales | No en.json key at all for any of the four |
| The manual body (Help tab) — thousands of words | help | 11 of 12 locales (only `docs/i18n/fr/` exists) | Not a wiring bug — content translation for the manual has only been done for French; no other-language draft, and no "this document is English-only" disclosure fires for de/ru/zh/ja/etc. (the machine-drafted-translation banner only fires when a draft *was* found) |

**Overflow/clipping caused by translation:** none, in every locale and surface tested at 1440×900 across all four locale sweeps — every clipped/ellipsised element found (Home's `.sum` line-clamp, Agenda's holiday-chip ellipsis, a `.sr-only` Markets div) reproduces byte-identically in the English reference. See §6.

---

## 4. Locale freeze on language switch — what freezes, why, and the reproduction

`src/static/app-boot.js` carries exactly **one** `oo:langchange` listener (grep-confirmed, no other file registers one). It explicitly re-renders: the world map, the sources table (if loaded), Home Briefing (`loadBriefing()` → also `renderCorpusTier`), Library Composition figures (if visited), the Observatory canvas (if a payload exists), Library Activity graphs (if visited), `#net-toggle`'s title (`_paintNetwork`), and the AI prompt editor (if open). Everything else sits outside this one safety net.

**Confirmed genuine freeze (not merely "never wired"): the Home corpus-tier hover tooltip.** The *visible* badge text (`span.tier-badge`) correctly re-renders in Russian after a switch — this part is not frozen. But the tooltip's `title` attribute stays the pre-switch English sentence, both immediately after the switch and 15s later (checked against the live ambient poll), while a **cold** Russian load of the same page shows the correct Russian tooltip. Mechanism: `i18n.js`'s DOM walker caches a persistent element's **first-ever-seen** `title` value in a `WeakMap` and, on every debounced pass (any body mutation — including the very re-render that just wrote the correct Russian text), looks up a translation for that *cached original*. Because the tooltip is built by string-concatenating several `t()` fragments plus interpolated numbers, `tr()` finds no exact match for the cached original and returns it unchanged — and the walker force-writes that unchanged English value back over the correct update one tick later. Registering the element in the `oo:langchange` listener a second time would **not** fix this (it's already re-rendered); the fix has to either mark the element `data-i18n-dyn` (opting it out of the walker, the same pattern already used for `#net-toggle`/`#rate-toggle`) or build the tooltip from one `tf()` key instead of concatenation.

**Confirmed: this is architecturally distinct from "the Home card body never translates" (§3).** A four-way diff (EN baseline → RU-after-switch → RU-15s-later → cold-RU-load) shows the Lead-card substance strings are byte-identical in **all four** conditions, including cold-load — there is nothing to un-freeze there; the content was never wired to i18n at all.

**Confirmed self-heal, narrower than invariant #17's own wording implies.** With the mouse held stationary over an already-open `#oo-tip` bubble on `#net-toggle`, calling `OOI18N.setLang('ru')` flips the bubble's visible text to Russian within ~1s with no re-hover — genuinely live. But this works only because (a) `_paintNetwork` explicitly rewrites `.title` on every langchange (the same explicit-rewrite mechanism, not a generic bubble property), and (b) the displayed text happens to be an exact, unmodified key the generic walker's synchronous text-node pass can match during `setLang()` itself. A tooltip built from an interpolated `tf()` string (exactly the Home corpus-tier case above) would not self-heal this way.

**Positive, adversarially re-tested:** a 5x rapid-fire switch stress test (en→fr→de→ru→ja→es, interleaved with Home/Library/Insights visits) left `html[lang]`, `dir`, and the Settings language `<select>` in one consistent final state (`es`/`ltr`/`es`) with no stale intermediate language surviving anywhere — the core switch mechanism itself is solid; the defects are all in individual downstream features. Library → Composition's `tf()`-interpolated "top 3 sources hold {pct}%" line was independently re-verified live to correctly re-render on every switch in the stress test, correcting an initial source-only hypothesis that it would freeze the same way as the Home tooltip.

---

## 5. Formatting: numbers, dates, units, plurals

**Four independent number-formatting code paths exist, not one shared formatter**, confirmed by direct source read:
- `fmtNum()` (`app-markets.js`) — hand-rolled, fixed space-thousands + period-decimal, ignores the active locale entirely; used by Markets, Indices, Home, task-manager byte/count amounts.
- bare `.toLocaleString()` (three separately-declared copies across `app-home.js`/`app-corpus.js`/`app-analysis.js`) — correctly locale-aware (confirmed: fr → "3 618", de → "3.618", ru → "3\u00a0618").
- `_fmtBytes()` (`app-core.js`) — hand-rolled binary math (÷1024) but labels the result with **decimal** SI prefixes (KB/MB/GB instead of KiB/MiB/GiB), and always calls `.toFixed(1)`, hard-coding a period decimal point in every locale (fr/de/ru all show "36.1 KB" where a comma is customary) — a direct conflict with the project's own SI-units non-negotiable, on a surface (Library storage) that in the same breath already knows the correct name "KiB/s" elsewhere in the codebase.
- a fourth ad-hoc M/k-suffix formatter (`app-diagnostics.js`).

One job row in the Task Manager visibly mixes two of these four side by side depending on the progress unit.

**Dates are the one area the platform gets right by design, with one exception.** `fmtDateTime()` correctly uses `Intl.DateTimeFormat` keyed to the app's *chosen* language (not the browser's) — verified live: Home's timestamp read "actualisé 8 septembre 2026 à 19:21" in French with the correct full month name. But `fmtRelative()` (used for future countdowns) is entirely hard-coded English with no `t()`/`tf()` call at all, unlike its sibling `fmtAgo()` three lines below it, which is correctly wrapped — and `_renderSchedule`'s "Last run" row calls the future-oriented `fmtRelative()` on a **past** timestamp, whose first branch (`mins<=0 → "any moment now"`) fires for any past date, meaning a real "last run 2 hours ago" would render as the fabricated-sounding "any moment now." This is source-confirmed but **live-unverified**: the disposable instance used had never run its scheduler (`last_run: null`), so the buggy branch was unexercised — an untested path, not a pass.

**Plurals do not exist anywhere in the i18n layer.** `i18n.js`'s `t()`/`tf()` are flat string-template substitutions with no `Intl.PluralRules`/CLDR branching. Confirmed live at n=1, 2, and 20 on Search: all nine renders (3 counts × en/ru/ar) show the identical broken "N result(s)" pattern — not even English pluralises correctly, and because the string bypasses `t()`/`tf()` entirely (§3) it isn't fixable by adding translations alone. Where a translated `{n}`-template *does* exist (e.g. "{n} articles mention this date"), Russian's fixed genitive-plural form is grammatically wrong for n=1 and n=2–4; Arabic's fixed plural form is wrong for n=1 (needs singular) and n=2 (Arabic has a dedicated dual, unaddressed). This lands hardest exactly where the app's own honesty vocabulary concentrates — small counts (thin evidence, "too few mentions").

---

## 6. Layout consequences of translation

**No translated string was found causing new overflow, clipping, or an ellipsis at 1440×900, in any of the ~120 locale × surface combinations captured across four sweeps.** The only clipped/ellipsised elements found on any locale (Home's `.sum` article-summary line-clamp, Agenda's "Independence Day (Mex…" chip, a Markets `.sr-only` chart-data div) reproduce byte-identically — same element, same clip amount — in the English reference, confirming they are pre-existing truncation-by-design, not something German/Russian/Arabic/CJK expansion worsened. `document.documentElement.scrollWidth` matched the 1440 viewport width in every captured combination.

One real RTL-specific layout defect was found and independently reproduced via a targeted element crop in this pass: **a leading digit gets bidi-relocated into the middle of an English hostname in Arabic.** The card title `"{n} sources, one origin: {dom}"` (`producers.py`) renders as "sources, one origin: wire- 3" / "agency.example" on two lines — the digit visually splits the domain name. No `<bdi>` or `unicode-bidi: isolate` wraps any dynamically-inserted URL/domain or number-leading sentence anywhere in `app-home.js`/`app.css` (grep-confirmed zero occurrences). Confirmed pixel-for-pixel via `ar-bidi-crop.png` in this pass. This is the general risk the project's own honesty rules name ("punctuation-joined values need bidi isolates in RTL") realized concretely, and it will recur for any server-built sentence that leads with a number and embeds Latin-script content (a source name, a domain).

CJK glyph fallback was stress-tested (forcing a Latin-only bundled face under zh/ja) and rendered cleanly via the OS system-font fallback with no tofu/missing glyphs — every custom `@font-face` declaration already carries a `system-ui, sans-serif` fallback.

---

## 7. Translation quality per language

*(AI-drafted; 200+ keys per language read side-by-side against English across chrome, the honesty vocabulary, consent/security/legal strings, error states, and long explanatory sentences.)*

**Headline positive, true across all ten languages reviewed (fr, de, es, pt, ru, id, ar, zh, ja, hi, bn):** hunting specifically for meaning-reversing mistranslations in every consent/network/encryption/passphrase/custody/legal string turned up **none**. The single highest-stakes sentence in the app — the no-recovery/no-decryption-alternative warning — is worded correctly and unambiguously in every language, every time it appears. No consent, security, or legal string changes meaning versus the English source in any of the ten languages sampled.

What breaks is internal consistency within a single locale, not accuracy against English:

- **French (fr) — publishable with light edits.** The safety-critical term "passphrase" is "phrase secrète" throughout the main encryption flow but flips to "phrase de passe" in the adjacent unencrypted-backup (`.oobak`) dialog — two different French terms for the one no-recovery secret in the same product, reading as two unreconciled translation passes. "Custody log" → "journal de custodie" is not standard French (a calque; "chaîne de possession" is the real forensic term).
- **German (de) — publishable as-is.** 438 formal `Sie/Ihr` markers found against exactly 1 informal `du/dein` slip (one string reading "Dein Korpus…dein Netzwerkmodus"), otherwise flawless.
- **Spanish (es) — needs a dedicated pass before shipping.** Register is not committed anywhere in the file: ~170 informal `tú` markers vs ~220 formal `usted` markers, mixed **inside the single most safety-critical screen in the app** — "Crea la frase de contraseña de tu corpus" (tú) sits beside "Guarde la frase de contraseña en un lugar seguro" (usted) in the same passphrase-creation flow. The term itself drifts three ways ("frase de contraseña" / "frase de paso" / bare "la frase") for the identical no-recovery secret.
- **Portuguese (pt) — needs a dedicated pass; one concrete navigational bug.** The file mixes Brazilian and European Portuguese vocabulary throughout (aplicativo/aplicação, arquivo/ficheiro, coleta/recolha, configurações/definições) badly enough that help text repeatedly tells users to go to "Definições" — a tab name that does not exist; the real tab is labelled "Configurações." Separately, "pista" (Lead) is grammatically feminine in Portuguese but is wrongly treated as masculine in 11 of 32 sampled occurrences ("o pista", "Todos os pistas") while the identical word is correctly feminized elsewhere in the same file ("esta pista") — an inconsistent gender-agreement bug, not a style choice.
- **Russian (ru) — very high quality.** 161/161 formal "вы" markers, zero informal "ты." One anglicism ("журнал custody," left partially untranslated) and the systemic plural-grammar limitation described in §5 (Russian's three plural categories vs. the app's one fixed template form), which is most visible precisely where the app's honesty vocabulary displays small counts.
- **Indonesian (id) — consistently formal (290/290 "Anda"),** but the core offline/online vocabulary that gates the entire consent system splits between the official terms ("luring"/"daring") and untranslated loanwords ("offline"/"online") — including on the bare status-chip labels — landing on exactly the vocabulary invariant #14's consent gate depends on.
- **Arabic (ar) — strongest sample overall,** fluent and precise on the hardest sentences, correct diacritics on ambiguous roots. "Caveat" is inconsistent (تحفّظ in 6 of 8 occurrences vs. the stronger, more alarmist تحذير "warning" in 2), and "Source integrity" is rendered with a moral/trust-honesty word (نزاهة) rather than a structural one, which sits at odds with the app's own stated no-trust-score philosophy for that exact feature.
- **Chinese (zh) — extremely high quality,** including the trickier double-negative logic in the backup/encryption copy. "Caveat" is rendered four different ways across 8 sampled occurrences of the identical English source string (注意事项/提醒/告诫/保留说明); "Source integrity" carries the same moral-trust overclaim as Arabic (诚信, "honesty," vs. the technical 完整性 used for "Data integrity").
- **Japanese (ja) — the only language with a concrete data-corruption-style bug found:** one Observatory string mid-sentence contains a stray **Korean** Hangul character (각, U+AC01) where the Japanese kanji 各 belongs — verified as the only Hangul character anywhere in `ja.json`, with the equivalent string clean in all 9 other non-Japanese files. "Caveat" shows the widest spread of any language (5 different renderings across 7–8 occurrences).
- **Hindi (hi) — accurate, correctly formal (आप throughout), but carries a distinctive systemic AI-drafting artifact not found in any other file:** ~20+ instances re-append the source English ALL-CAPS emphasis word in parentheses immediately after translating it (e.g. "हर (EVERY) स्रोत", "कभी (NEVER) अधिलेखित नहीं") — pure redundant clutter since Hindi's own words already carry the emphasis, distinct from the many *legitimate* bracketed technical terms (CSV, PDF, VADER) that correctly stay in Latin script.
- **Bengali (bn) — cleanest of the two Indic samples,** no parenthetical-English artifact, perfectly consistent terminology throughout; shares the moral-trust "Source integrity" overclaim pattern (সততা, "honesty").

**Cross-language pattern worth a maintainer terminology-glossary pass:** "caveat" — the visible half of the app's own core informed-consent mechanism (invariant #23) — resists clean translation in every language reviewed, either through within-language inconsistency (ar/zh/ja: 2–5 different renderings of the identical source string) or through convergence on a stronger "warning" sense than the neutral, always-present qualifier the English word is designed to be (hi/bn). And "Source integrity" independently drifts into a moral/trust-honesty sense in 4 of 5 CJK/Indic/Arabic languages checked, quietly reintroducing in the UI's own labels the exact trust/quality judgment the project's non-negotiables state the app deliberately never makes.

---

## 8. CJK, Indic and RTL specifics

- **CJK keyword segmentation is broken by construction, not merely untranslated (P1, data-quality).** `keyword_extractor.py` classifies n-grams via Python's whitespace `str.split()`; a Chinese clause has no interior whitespace, so a 6-character clause is classified and kept as a single "keyword." Confirmed live in the Insights → Map country-keyword table: the `cn` row shows five full un-segmented clauses ("分析人士指出" = "analysts pointed out") as single 2-frequency "keywords," while every other language row shows clean single/two-word terms. No `jieba` import exists anywhere in the file.
- **Observatory's category taxonomy is unreadable to any non-English-only zh/ja/etc. reader** — the 12 domain labels are canvas `fillText` calls on the raw English taxonomy string, with no translation hook possible without an explicit code change (§2, §3).
- **RTL bidi scrambling of a leading digit** (§6) is the one concrete Arabic-specific visual defect found and pixel-confirmed; the app's Arabic RTL calendar mirroring, form-field order, and network-consent dialog were otherwise found correctly mirrored and fully translated in every sweep that reached them.
- **Indic-specific**: Hindi's parenthetical-English-emphasis artifact (§7) and both Hindi's and Bengali's convergence on a "warning"-leaning rendering of "caveat" (§7) are the two Indic-specific findings; no meaning-reversing defect was found in either language's consent/security copy.
- Font fallback for CJK glyphs under a forced Latin-only bundled face was tested and found clean (§6) — a real risk category that did not materialize.

---

## 9. Ranked remediation plan

**Tier 1 — fixes that close a whole class of findings at once, ranked by leverage:**

1. **Extend `_paintNetwork()`/`_paintRateMode()` to also call `setAttribute('aria-label', …)`, and register `_paintRateMode`/`loadRateMode` in the one `oo:langchange` listener.** Two lines of code fix the airplane-mode kill switch's accessibility name in 11 locales, the collection-speed knob's aria-label wiring, and its guaranteed-English-on-cold-load title, on every one of 16 surfaces at once. Add the missing `aria-label` key to `en.json` and translate ×12.
2. **Fix the Agenda `_CAVEAT` key drift** (update the 12 locale keys to match the current backend wording, "calendar"→"agenda") — restores a maintainer-mandated informed-consent string in all 12 locales with a one-line text change per file, plus add a build-time check that a server-emitted caveat constant still exact-matches its translation key (this exact failure mode — a backend copy edit silently orphaning its translation — is exactly what such a guard exists to catch, per the project's own ledger discipline).
3. **Give the article reader (`src/api/main.py`), Task Manager/Unlock inline `<script>` blocks, and backtick template literals a scan path in `scripts/i18n_report.py`.** This is the single highest-leverage process fix: today's ratchets (552/294) are both nearly out of slack and don't even see these three categories, so the project's own gate cannot prevent this exact class of gap from recurring. Fixing the tool matters more than fixing any one string, because it's what stops this list from needing to be re-derived by hand next cycle.
4. **Extend `title_i18n`/`title_vars` (the pattern that already exists for `Card.title`) to `Card.summary` and to `leads.py`'s `explain_order()`.** This is the single largest volume of untranslated visible text in the app (every Lead card, on the primary landing surface, in all 12 locales) and the mechanism to fix it is already built and proven on the adjacent field.

**Tier 2 — real defects, narrower blast radius:**

5. Wrap `reader.js`'s hardcoded strings in `t()`/`t9()` (14+ strings, zero calls today).
6. Wrap `oosky.js:495`'s `fillText(da.domain, …)` in `t()` and register the 11 missing domain-name keys.
7. Fix `DB_STAT_LABELS` (Library) and `HOME_STAT_LABELS` (Home) to cover the same `sources_*`/newer backend fields — these are plain bugs (they leak in English too), not translation gaps, and the two maps having independently drifted apart is itself worth a note: one shared label-map source of truth would prevent the next backend field from doing this again.
8. Wrap Search's result count in `tf()` and give the app a plural-category mechanism (`Intl.PluralRules`/CLDR-style `{n, plural, one{…} few{…} many{…} other{…}}`) — a schema change, not a per-string fix, and the one item on this list that plausibly warrants an `OPEN_QUEUE.md` architectural ruling rather than a quick patch, since it recurs for every `{n}`-templated string in Russian and Arabic today and will recur for any future Slavic/Arabic-family locale.
9. Add `<bdi>`/`unicode-bidi: isolate` around dynamically-inserted domains/URLs and number-leading server-built sentences in `app-home.js` (fixes the Arabic bidi-scramble class, not just the one instance found).
10. Add a CJK-aware segmenter (e.g. jieba) ahead of `keyword_extractor.py`'s whitespace-based n-gram categorizer, gated on article language.

**Tier 3 — quality/polish, easy and low-risk:**

11. Add the missing keys for "Compare," "adv," Agenda's "previous"/"next," the Draft-button fragments, and 15 of 17 theme names (or, if intentionally untranslated proper nouns, record that as a deliberate ruling rather than leaving Light/System as the sole inconsistent exception).
12. Fix `_fmtBytes()`'s unit naming (KiB/MiB/GiB, not KB/MB/GB) and locale-aware decimal points; consolidate the four number-formatting code paths into the one the project's own non-negotiable already claims exists.
13. Fix `fmtRelative()` being called on past timestamps in `_renderSchedule` (source-confirmed, live-unverified — needs a fixture with a real `last_run` to confirm before shipping the fix).
14. Native-speaker register passes for es (commit to "usted," already the majority form) and pt (pick BR or EU Portuguese and fix the "Definições"/"Configurações" navigational mismatch immediately regardless of which); a one-word terminology-glossary decision for "caveat" across ar/zh/ja/hi/bn; fix the single stray Hangul character in `ja.json`; strip Hindi's ~20 parenthetical-English-emphasis artifacts; re-terminology "Source integrity" away from a moral/trust word in ar/zh/hi/bn to avoid contradicting the app's own no-trust-score philosophy in its own UI labels.

---

## 10. Refuted / unverified

**Refuted:**
- **"`#rate-toggle`'s title has no key in `en.json` at all"** (as stated in one sweep) — false. The key exists and is correctly, completely translated in every locale checked. The user-visible symptom (English title shown) is real, but the cause is the boot-order race + missing `oo:langchange` registration (§3/§4), not a missing translation. (Its aria-label, separately, genuinely has no key anywhere — that half of the claim stands.)
- **The t9()/t9m() alias blind spot and the `guis/` directory scope gap**, treated as current defects in two of the four sweeps — **stale.** Both were fixed on `main` before this audit began (commit `860ab73`). Re-running the tool's own `_T_CALL`/`_JS_SHAPES` regex and `_guis_js()` wiring confirms both are correctly handled today; all 43 current `t9`/`t9m` call sites across the 7 modules named in one sweep are fully keyed, and `guis/*.js` is scanned by both `audit_chrome()` and `unkeyed_t_calls()`.

**Unverified / not reached (reported, not silently skipped, per the project's own honesty rule):**
- The other 8 shipped locales beyond the 10 covered here for translation-quality review (only fr/de/es/pt/ru/id/ar/zh/ja/hi/bn were sampled across the two quality reviews — that is in fact 11 of 12; no locale was entirely unreviewed for quality, but sample sizes vary and none was a full census).
- The Observatory's canvas-drawn labels were confirmed via source read (the `fillText` call and its taxonomy source are locale-agnostic by construction) but not independently re-screenshotted in every locale by this synthesis pass.
- `fmtRelative()`-on-a-past-timestamp (§5, §9-13) is source-confirmed but could not be exercised live — every disposable instance used had `last_run: null`.
- axe-core/contrast/perf probes were out of scope for every sweep and probe in this audit (explicitly reserved for other audit workstreams per each job's own framing) — no accessibility-tree or WCAG contrast regression specific to any locale is confirmed or ruled out here, beyond the two aria-label findings that surfaced incidentally.
- Only the default panel/subtab of most multi-subtab surfaces was driven in most sweeps (Insights' non-default views, Law's Compare/Map/Statistics bodies, Settings' non-default categories, Search's advanced-filter panel, Markets'/Indices' detail modals) — a locale defect gated behind one more click is plausible and not ruled out.
- Only one theme (ink) and one viewport (1440×900) were exercised throughout; no narrower/mobile viewport, no other of the 17 themes, and no locale-× RTL-× narrow-viewport combination was tested — invariant #3's fixed-width top-bar slots under real translation-length pressure at smaller widths remains unverified.
- The exact "~79% real coverage" / "~600 of ~2,930 strings" extrapolation from one probe is a reasoned estimate from a partial sample (backtick-literal candidates were spot-checked, not censused) — directionally corroborated by everything above, but not independently re-derived as a precise figure in this synthesis, and should be cited as "a real, multi-hundred-string gap the tooling cannot see," not as a hard percentage.