"""
ui_walk_playwright — the REAL ``UiWalkDriver`` (gate row 8: "the ``ui_walk`` runner STANDING").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/monitoring/ui_walk.py`` deliberately carries NO browser dependency -- its control flow is
proven against a fake driver so it can be tested anywhere. This module is the build-time decision
that scaffold's docstring said it does not make: Playwright's bundled Chromium (this environment's
pinned build; see ``PLAYWRIGHT_BROWSERS_PATH``), never a network fetch of a browser at run time.

``playwright`` is NOT a core or ``[analysis]`` dependency -- importing this module without it
installed raises a clear ``ImportError`` at the point of use, never a silent no-op. A core install
of the app is completely unaffected; this module exists to be imported by an operator/CI session
actually running a browser walk, never by the app itself.

HONESTY RAILS this driver enforces, each tied to a lesson the 2026-07-22 audit's own report
states explicitly (``docs/audit/GUI_TEST_REPORT_2026-07-22.md`` section 0):

  * ``console_errors()`` separates real uncaught exceptions (Playwright's ``pageerror`` event)
    from ``console.error`` LOG lines. The 2026-07-22 run's headline caveat was that "384 total JS
    errors" was 100% ``console.error`` 429-rate-limit noise from that test's OWN concurrent load,
    with ZERO real ``pageerror`` exceptions anywhere -- conflating the two manufactures a false
    crisis. A ``pageerror`` ALWAYS fails a step here; a ``console.error`` line fails a step only
    when it is not the documented 429-storm signature, and every raw line (noise included) stays
    available via ``last_console_error_lines`` for a caller that wants the full picture.
  * ONE browser drives ONE server instance at a time by construction (a driver is bound to one
    ``Page``/``base_url`` at ``__init__``) -- the 429 storm itself was an artifact of 14 parallel
    browsers hammering one shared server; this module never does that.
  * ``goto()`` navigates through the SPA's REAL nested nav grammar (top-level tab -> the
    relocated ``#subtab-strip`` -> a folded Settings->Advanced ``<details>`` section -> an
    optional trigger click), matching ``Surface``'s fields exactly -- never a raw
    ``document.getElementById(...).click()`` shortcut that could reach a DOM node the real user
    flow cannot. TWO tabs ("analyze", "settings") have no sidebar ``.nav-item`` at all any
    more -- ``goto()`` special-cases them onto the SAME functions their real (non-nav-item)
    entry points call (the settings gear button's own ``onclick``, ``openAnalysisFor`` --
    the function a keyword-chip click invokes), never a shortcut past a real path, since
    for these two there IS no other path. Found live, not by re-grepping harder: a first
    "re-verification" that only checked a DOM id existed missed that its click PATH did not.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from src.monitoring.ui_walk import Surface

_LOG = logging.getLogger(__name__)

try:
    from playwright.sync_api import Page
except ImportError as _exc:  # pragma: no cover - exercised only via the skip-guarded test
    Page = None  # type: ignore[assignment,misc]
    _IMPORT_ERROR: Exception | None = _exc
else:
    _IMPORT_ERROR = None


# The documented 2026-07-22 rate-limit-storm artifact (slowapi's fixed-window limiter under
# concurrent multi-agent load). A single-browser walk essentially never triggers this for real,
# but the filter stays so a driver run under any concurrent load degrades the same honest way the
# audit's own report does -- never silently, never by conflating it with a real exception.
_KNOWN_NOISE_SUBSTRINGS = ("429 (Too Many Requests)",)

# Two tabs with NO ``.nav-item[data-tab]`` sidebar button in the current UI (found live,
# 2026-08-13 -- see ui_walk.py's module docstring for the full story). Settings opens via a
# dedicated gear button in the sidebar footer; the analysis window has no static click target
# at all and is reached only by spawning a search.
_SETTINGS_OPEN_SELECTOR = 'button[onclick="showTab(\'settings\')"]'


class PlaywrightUiWalkDriver:
    """A real ``UiWalkDriver`` (structurally, not by inheritance -- the Protocol needs no base
    class) backed by one Playwright ``Page`` against one running app instance.

    Two capabilities beyond the ``UiWalkDriver`` Protocol are exposed as plain extra methods
    (Python's ``Protocol`` only requires the four it names; extra methods on a conforming class
    are fine) because the click-through brief needs them and no other module should reinvent
    theme/locale switching against this SPA's actual mechanism:

      * ``set_theme(theme_id)`` -- calls the page's own global ``setTheme()`` (app.js), the SAME
        function a real user's theme-select triggers, rather than poking ``localStorage``
        directly and reloading (which would skip ``buildDrawer()``/``syncThemeSelect()``'s own
        side effects and could pass on a state a real user path never reaches).
      * ``set_locale(code)`` -- calls the page's own ``window.OOI18N.setLang(code)``, the SAME
        function the language-switcher menu calls.
    """

    engine = "playwright-chromium"

    def __init__(
        self,
        page: "Page",
        *,
        base_url: str,
        screenshot_dir: Path | None = None,
        greyscale: bool = False,
    ) -> None:
        if _IMPORT_ERROR is not None:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "PlaywrightUiWalkDriver needs the 'playwright' package (not a core dependency -- "
                "install it explicitly for a real browser walk, e.g. `pip install playwright` "
                "then point PLAYWRIGHT_BROWSERS_PATH at a pinned Chromium build)"
            ) from _IMPORT_ERROR
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.screenshot_dir = screenshot_dir
        self.greyscale = greyscale
        self._pageerrors: list[str] = []
        self._console_lines: list[str] = []
        self.last_pageerrors: list[str] = []
        self.last_console_error_lines: list[str] = []
        page.on("pageerror", lambda exc: self._pageerrors.append(str(exc)))
        page.on("console", self._on_console)
        # Only auto-boot when a REAL base_url is configured (the actual app-walking case) --
        # an empty base_url (a hermetic test against a page whose content was set directly via
        # set_content(), never navigated) must never attempt this, or `goto("/")` with no base
        # raises "Cannot navigate to invalid URL" on construction, before the caller gets a
        # chance to set the page up.
        if self.base_url and page.url in ("about:blank", ""):
            page.goto(self.base_url + "/", wait_until="domcontentloaded")
        if greyscale:
            self._apply_greyscale()

    def _apply_greyscale(self) -> None:
        # A page.evaluate() call, applied on-demand after any real navigation -- NOT
        # add_init_script(), which does not reliably fire for content set via set_content()
        # (proven live: the filter stayed 'none' after a set_content() call with an init script
        # registered) and is unnecessary anyway, since this SPA only ever performs ONE full page
        # navigation (first load); every tab/subtab "navigation" the driver performs afterwards
        # is an in-page DOM mutation on the SAME document, so a single evaluate() call here
        # persists across the whole walk. `goto()` re-applies it only for a surface reached via
        # a real ``url`` (a genuine full navigation, e.g. the standalone reader or /tasks).
        try:
            self.page.evaluate("document.documentElement.style.filter = 'grayscale(1)'")
        except Exception as exc:  # noqa: BLE001 - a cosmetic filter must never abort a walk
            _LOG.warning("could not apply greyscale filter: %s", exc)

    def _on_console(self, msg: object) -> None:
        if getattr(msg, "type", None) == "error":
            self._console_lines.append(str(getattr(msg, "text", msg)))

    def _ensure_on_spa(self) -> None:
        """A ``url``-based surface (the standalone reader, ``/tasks``) performs a REAL full-page
        navigation AWAY from the single-page app -- found live 2026-08-13: without restoring it,
        every ``nav_tab``-based surface visited right after one silently fails, and NOT the way
        a missing element normally fails. A ``.click()`` on a page that genuinely has no such
        element burns the full 30s action timeout (a real, LOUD failure) -- but ``goto()``'s
        "analyze" branch calls ``openAnalysisFor`` through ``page.evaluate()`` behind a defensive
        ``typeof x === 'function'`` guard, so on a page where that function is simply undefined
        (any page that is not this SPA) the call SILENTLY DOES NOTHING and ``evaluate()`` returns
        clean -- an entire subtab drill can pass through with ``visible=False`` and no error at
        all, reading as "the surface doesn't render" when the real cause is "wrong page
        entirely". Re-navigating to the SPA's own root is exactly what a real user does closing
        the ``/tasks`` tab or clicking Back -- never a shortcut past anything.

        A no-op when ``base_url`` is empty (the hermetic ``set_content()`` test case, same as
        ``__init__``'s own auto-boot guard) -- there is no real root to navigate back TO, and
        ``page.goto("/")`` with no base raises "Cannot navigate to invalid URL"."""
        if not self.base_url:
            return
        current = self.page.url
        root = self.base_url + "/"
        if current != root and current != self.base_url:
            self.page.goto(root, wait_until="domcontentloaded")
            self.page.wait_for_timeout(300)
            if self.greyscale:
                self._apply_greyscale()

    def _close_any_open_dialog(self) -> None:
        """A ``trigger`` click (e.g. "Import…") can open a native ``<dialog>`` that stays open
        after the surface finishes -- found live 2026-08-13: an open ``<dialog>`` covers the
        WHOLE page with a modal backdrop that intercepts pointer events on everything else,
        including the next surface's own navigation click, so a walk that never closes it
        silently times out every step that follows (the exact same failure mode as the
        first-run guide-wizard modal, wearing a different id). Escape is the native way a
        real user closes an open ``<dialog>`` (the browser's own default ``cancel`` handling),
        so this is not a shortcut past the real UI -- it is calling it once, every ``goto()``,
        so a stray dialog left open by a PRIOR surface never blocks the NEXT one."""
        try:
            if self.page.locator("dialog[open]").count():
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(150)
        except Exception as exc:  # noqa: BLE001 - this is a courtesy reset, never fatal
            _LOG.warning("could not close a leftover open dialog: %s", exc)

    # -- UiWalkDriver Protocol ------------------------------------------------------------- #

    def goto(self, surface: Surface) -> None:
        self._pageerrors.clear()
        self._console_lines.clear()
        self._close_any_open_dialog()
        if surface.url:
            self.page.goto(self.base_url + surface.url, wait_until="domcontentloaded")
            if self.greyscale:
                self._apply_greyscale()
        else:
            self._ensure_on_spa()
            if not surface.nav_tab:
                raise ValueError(f"surface {surface.id!r} carries neither nav_tab nor url")
            if surface.nav_tab == "analyze":
                # No click target reaches this tab at all -- openAnalysisFor(query) IS the
                # real user flow's entry point (a keyword chip / the omnibar's Enter calls
                # the exact same function). _anSpawn dedupes by query, so calling this again
                # for every subtab in a drill reuses one tab rather than spawning N of them.
                self.page.evaluate(
                    "(q) => { if (typeof openAnalysisFor === 'function') openAnalysisFor(q); }",
                    surface.search_query,
                )
            elif surface.nav_tab == "settings":
                # No `.nav-item[data-tab="settings"]` exists -- Settings opens via a gear
                # button in the sidebar footer instead (index.html .sb-foot).
                self.page.click(_SETTINGS_OPEN_SELECTOR)
            else:
                self.page.click(f'.nav-item[data-tab="{surface.nav_tab}"]')
        if surface.subtab:
            # _relocateSubtabs (app.js) moves the active tab's OWN subtab nav into this one
            # shared strip on every showTab() -- so every subtab, on every tab, is reached the
            # same way, never at its markup's original nested location. BUT it APPENDS rather
            # than replacing: a PRIOR tab's relocated nav is set display:none and left behind
            # in the DOM rather than removed, so `#subtab-strip button[data-tab="X"]` can
            # resolve to more than one element when two different tabs' subtab lists share a
            # data-tab value (e.g. "advanced" exists in both #an-subtabs and #set-subtabs) --
            # found live 2026-08-13 driving the real app twice in a row (settings, then
            # settings again after visiting analyze). `:visible` (a Playwright CSS extension,
            # not standard) scopes the click to whichever match is ACTUALLY on screen, which
            # is also the only one a real mouse click could ever reach.
            self.page.click(f'#subtab-strip button[data-tab="{surface.subtab}"]:visible')
        if surface.advanced_section:
            sel = f'details[data-adv="{surface.advanced_section}"]'
            self.page.wait_for_selector(sel, state="attached", timeout=5000)
            is_open = bool(self.page.eval_on_selector(sel, "el => el.open"))
            if not is_open:
                self.page.click(f"{sel} > summary")
        if surface.trigger:
            self.page.click(surface.trigger)
        # a short settle window for lazy loaders / CSS transitions -- surfaces render
        # asynchronously (a loopback fetch, a subtab paint) and is_visible() must see the
        # settled DOM, not a mid-transition frame.
        self.page.wait_for_timeout(200)
        if surface.dom_id:
            # A bounded EXTRA wait for the surface's own target to actually paint content --
            # found live 2026-08-13: a fixed 200ms settle window was enough almost everywhere,
            # but under a long walk (dozens of prior surfaces, real network fetches, real DB
            # queries) a handful of async-rendered surfaces (e.g. the Agenda month grid) can
            # still be mid-fetch at the 200ms mark, so a snapshot taken then reads as a false
            # `visible=False`. This never CHANGES the verdict for a surface that stays
            # genuinely empty (it degrades to a no-op after the timeout, same as before) --
            # it only gives a genuinely-rendering-but-slow surface the room to finish before
            # is_visible() looks. Never raises: a surface that is SUPPOSED to stay empty
            # (e.g. post_import_screen before any import has run) must still report False
            # honestly, not be forced open by this wait.
            with contextlib.suppress(Exception):
                self.page.wait_for_function(
                    "id => { const el = document.getElementById(id); "
                    "return !!(el && el.offsetHeight > 0 && el.innerHTML.trim().length > 0); }",
                    arg=surface.dom_id,
                    timeout=2000,
                )

    def is_visible(self, dom_id: str) -> bool:
        try:
            return bool(self.page.is_visible(f"#{dom_id}"))
        except Exception:  # noqa: BLE001 - a malformed selector must degrade, never crash the walk
            return False

    def console_errors(self) -> list[str]:
        """Per the module docstring: a real ``pageerror`` ALWAYS counts. A ``console.error``
        line counts UNLESS it matches the documented 429-storm noise signature -- but every raw
        line, noise included, is preserved on ``last_console_error_lines`` for a caller that
        wants the honest full picture rather than the filtered pass/fail view."""
        self.last_pageerrors = list(self._pageerrors)
        self.last_console_error_lines = list(self._console_lines)
        errors = list(self._pageerrors)
        for line in self._console_lines:
            if any(noise in line for noise in _KNOWN_NOISE_SUBSTRINGS):
                continue
            errors.append(f"console.error: {line}")
        return errors

    def screenshot(self, surface: Surface) -> str | None:
        if not self.screenshot_dir:
            return None
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-grey" if self.greyscale else ""
        path = self.screenshot_dir / f"{surface.id}{suffix}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True, timeout=10_000)
        except Exception as exc:  # noqa: BLE001 - a screenshot failure must degrade, never crash
            _LOG.warning("screenshot failed for %s: %s", surface.id, exc)
            return None
        return str(path)

    # -- extra, non-Protocol conveniences the click-through matrix needs -------------------- #

    def set_viewport(self, width: int, height: int) -> None:
        self.page.set_viewport_size({"width": width, "height": height})

    def set_theme(self, theme_id: str) -> None:
        """Calls the page's OWN global ``setTheme()`` -- the same function a real theme-select
        change fires -- so ``buildDrawer()``/``syncThemeSelect()``'s side effects run exactly as
        they would for a real user, never a localStorage-and-reload shortcut that could skip
        them."""
        self.page.evaluate("(t) => { if (typeof setTheme === 'function') setTheme(t); }", theme_id)

    def set_locale(self, code: str) -> None:
        """Calls the page's OWN ``window.OOI18N.setLang()`` -- the same function the language
        switcher menu calls."""
        self.page.evaluate(
            "(c) => { if (window.OOI18N && OOI18N.setLang) OOI18N.setLang(c); }", code
        )

    def computed_style(self, selector: str, *, pseudo: str | None = None) -> dict[str, str]:
        """``getComputedStyle`` on the element (or its pseudo-element, e.g. ``::after``) --
        never read declared CSS. Element ``opacity`` composites over whatever sits BEHIND it, and
        a pseudo-element inherits any property it does not itself declare from a lower-specificity
        rule that also matches -- both are invisible to reading source CSS and were each the
        mechanism behind a real shipped contrast defect. Returns {} if the selector matches
        nothing (never raises -- an absent element is a legitimate "not on screen" case)."""
        script = """
        ([sel, pseudo]) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const cs = getComputedStyle(el, pseudo || null);
          const out = {};
          for (const prop of ['color', 'backgroundColor', 'opacity', 'display',
                               'visibility', 'content', 'width', 'height', 'fontSize',
                               'textTransform', 'position']) {
            out[prop] = cs.getPropertyValue(prop) || cs[prop] || '';
          }
          return out;
        }
        """
        result = self.page.evaluate(script, [selector, pseudo])
        return dict(result) if result else {}

    # -- the 2026-08-20 matrix additions: a11y + honesty-rule instruments ------------------ #
    # Each is a GENERIC capability (no app-specific selector baked in) so the walk script
    # composes them per surface, and each is proven on a hermetic set_content() fixture in
    # tests/test_ui_walk_playwright.py before being trusted against the live SPA.

    def emulate_contrast(self, mode: str | None) -> None:
        """Emulate the ``prefers-contrast`` media feature (``'more'`` /
        ``'no-preference'``; ``None`` clears the emulation) — the browser-level switch
        the app.css ``@media (prefers-contrast: more)`` block (GUI-audit G-3 fix)
        responds to. Passing a literal ``None`` through to Playwright is a NO-OP that
        silently keeps the previous emulation (probed live 2026-08-20 — an instrument
        whose reset does nothing would leave every later check running under the
        emulation it claimed to clear), so ``None`` is translated to a real reset
        token here. Both ``'null'`` and ``'no-override'`` behaviorally clear the
        emulation on this pinned Playwright (probed live, matchMedia read back);
        ``'null'`` is the one its own type stub declares, so it is the one used."""
        if mode is None:
            self.page.emulate_media(contrast="null")
        elif mode == "more":
            self.page.emulate_media(contrast="more")
        elif mode == "no-preference":
            self.page.emulate_media(contrast="no-preference")
        else:  # an unknown token must fail loudly, never silently keep the old state
            raise ValueError(f"unsupported prefers-contrast mode: {mode!r}")

    def keyboard_traversal(self, max_tabs: int = 40) -> list[dict]:
        """Tab through the page recording each focus stop: identity, whether the stop is
        inside the viewport, and whether focus is VISIBLY indicated (computed outline or
        box-shadow while focused — the browser's default ring counts; ``outline:none``
        with no replacement does not). Stops early when focus returns to the first
        focused element (a full cycle) or leaves the document. The caller judges the
        chain: a repeated single element is a trap; a critical control absent from the
        chain is unreachable by keyboard."""
        chain: list[dict] = []
        first_key: str | None = None
        for i in range(max_tabs):
            self.page.keyboard.press("Tab")
            info = self.page.evaluate(
                """
                () => {
                  const el = document.activeElement;
                  if (!el || el === document.body) return {tag: 'body'};
                  const cs = getComputedStyle(el);
                  const r = el.getBoundingClientRect();
                  const outlineVisible = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
                  const shadowVisible = cs.boxShadow && cs.boxShadow !== 'none';
                  return {
                    tag: el.tagName.toLowerCase(), id: el.id || '',
                    cls: String(el.className || '').slice(0, 60),
                    text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40),
                    in_viewport: r.right > 0 && r.left < document.documentElement.clientWidth
                                 && r.bottom > 0 && r.top < document.documentElement.clientHeight,
                    focus_indicated: !!(outlineVisible || shadowVisible),
                  };
                }
                """
            )
            key = f"{info.get('tag')}#{info.get('id')}.{info.get('cls')}|{info.get('text')}"
            if first_key is None:
                first_key = key
            elif key == first_key and i > 0:
                break
            chain.append(info)
        return chain

    def run_axe(self, axe_source: str, *, scope: str | None = None) -> dict:
        """Inject the VENDORED axe-core source (never a CDN fetch — the caller reads the
        pinned local file; this method only ever receives its bytes) and run
        ``axe.run()``, returning a serialisable summary: one row per violation with its
        id, impact, help text, node count and up to 5 target selectors. ``scope``
        restricts the audit to one subtree."""
        already = self.page.evaluate("() => typeof window.axe !== 'undefined'")
        if not already:
            self.page.add_script_tag(content=axe_source)
        return self.page.evaluate(
            """
            async (scope) => {
              const target = scope ? document.querySelector(scope) : document;
              if (!target) return {error: 'scope not found: ' + scope, violations: []};
              const r = await axe.run(target, {resultTypes: ['violations']});
              return {violations: r.violations.map(v => ({
                id: v.id, impact: v.impact || '', help: v.help, nodes: v.nodes.length,
                targets: v.nodes.slice(0, 5).map(n => n.target.join(' ')),
              }))};
            }
            """,
            scope,
        )

    def char_x_positions(self, selector: str, substring: str) -> list[float] | None:
        """The rendered x position (left edge) of EACH CHARACTER of ``substring`` inside
        the first text node under ``selector`` that contains it — the RTL bidi-isolate
        instrument (the recorded lesson: in Arabic an interpolated ISO timestamp renders
        with the year at the wrong end, a MISREAD date; the check is per-character
        rendered positions, never eyeballing). Returns None when the substring is not
        found in any text node under the selector."""
        return self.page.evaluate(
            """
            ([sel, sub]) => {
              const root = document.querySelector(sel);
              if (!root) return null;
              const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const idx = node.textContent.indexOf(sub);
                if (idx < 0) continue;
                const el = node.parentElement;
                if (!el || !(el.offsetWidth || el.offsetHeight)) continue;
                const xs = [];
                for (let i = 0; i < sub.length; i++) {
                  const range = document.createRange();
                  range.setStart(node, idx + i);
                  range.setEnd(node, idx + i + 1);
                  const rects = range.getClientRects();
                  if (!rects.length) return null;
                  xs.push(rects[0].left);
                }
                return xs;
              }
              return null;
            }
            """,
            [selector, substring],
        )

    def undefined_classes(self, *, max_report: int = 200) -> list[dict]:
        """Class names USED in the live DOM with NO rule in any readable stylesheet — the
        "a class with no rule is a lie the markup keeps telling" sweep (the recorded
        ``class=\"small\"`` lesson: 35 uses, zero rules, and the markup read as styled).
        Walks every same-document stylesheet INCLUDING nested grouping rules (media
        queries). A hit is a REPORT, not a verdict: many classes are legitimate JS/state
        hooks — the caller triages which names IMPLY presentation. Cross-origin sheets
        (none in this app) are skipped silently rather than crashing the sweep."""
        return self.page.evaluate(
            """
            (maxReport) => {
              const styled = new Set();
              const collect = (rules) => {
                for (const rule of rules) {
                  try {
                    if (rule.selectorText) {
                      for (const m of rule.selectorText.matchAll(/\\.([A-Za-z0-9_-]+)/g))
                        styled.add(m[1]);
                    }
                    if (rule.cssRules) collect(rule.cssRules);
                  } catch (e) { /* one bad rule never aborts the sweep */ }
                }
              };
              for (const sheet of document.styleSheets) {
                try { collect(sheet.cssRules); } catch (e) { /* cross-origin: skip */ }
              }
              const used = new Map();
              for (const el of document.querySelectorAll('[class]')) {
                const cls = el.className.baseVal !== undefined ? el.className.baseVal : el.className;
                for (const c of String(cls).split(/\\s+/)) {
                  if (!c || styled.has(c)) continue;
                  if (!used.has(c)) used.set(c, {cls: c, count: 0, example: ''});
                  const entry = used.get(c);
                  entry.count += 1;
                  if (!entry.example) {
                    entry.example = '<' + el.tagName.toLowerCase()
                      + (el.id ? '#' + el.id : '') + '>';
                  }
                }
              }
              return Array.from(used.values())
                .sort((a, b) => b.count - a.count).slice(0, maxReport);
            }
            """,
            max_report,
        )

    def visible_text_nodes(self, *, limit: int = 3000) -> list[str]:
        """Every VISIBLE text node's normalized text, bounded — the i18n exact-match
        walker's raw material (the engine translates a text node only when its whole
        normalized value matches a key, so a label welded to its value can never key;
        the caller compares these against the locale maps)."""
        return self.page.evaluate(
            """
            (limit) => {
              const out = [];
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode()) && out.length < limit) {
                const text = node.textContent.replace(/\\s+/g, ' ').trim();
                if (!text) continue;
                const el = node.parentElement;
                if (!el) continue;
                if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
                if (!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) continue;
                out.push(text);
              }
              return out;
            }
            """,
            limit,
        )

    def uppercase_reliance_audit(self, *, body_selector: str = "body") -> list[dict]:
        """Elements whose computed ``text-transform`` is uppercase AND whose size/weight/
        color do not differ from body text — i.e. whose visual rank is carried by CASE
        ALONE, which is a no-op in five of the twelve locales (ar/zh/ja/hi/bn — the
        recorded panel-h2 lesson: rank must be carried by size and weight). Elements
        that also differ in size or weight are NOT reported: their hierarchy survives
        translation, and reporting them would be the over-eager mirror."""
        return self.page.evaluate(
            """
            (bodySel) => {
              const body = document.querySelector(bodySel) || document.body;
              const base = getComputedStyle(body);
              const baseSize = parseFloat(base.fontSize);
              const out = [];
              for (const el of document.querySelectorAll('*')) {
                if (!(el.offsetWidth || el.offsetHeight)) continue;
                const cs = getComputedStyle(el);
                if (cs.textTransform !== 'uppercase') continue;
                const text = (el.textContent || '').trim();
                if (!text || el.children.length > 2) continue;
                const size = parseFloat(cs.fontSize);
                const weight = parseInt(cs.fontWeight, 10) || 400;
                const baseWeight = parseInt(base.fontWeight, 10) || 400;
                const sizeDiffers = Math.abs(size - baseSize) >= 1;
                const weightDiffers = Math.abs(weight - baseWeight) >= 100;
                if (!sizeDiffers && !weightDiffers) {
                  out.push({tag: el.tagName.toLowerCase(), id: el.id || '',
                            cls: String(el.className || '').slice(0, 50),
                            text: text.slice(0, 40), fontSize: size, fontWeight: weight});
                }
              }
              return out.slice(0, 80);
            }
            """,
            body_selector,
        )

    def console_error_summary(self) -> dict[str, int]:
        """The honesty-critical split the 2026-07-22 report's own methodology caveat demands:
        real uncaught exceptions vs. console.error noise, counted separately, never blended into
        one number."""
        noise = sum(
            1
            for line in self.last_console_error_lines
            if any(n in line for n in _KNOWN_NOISE_SUBSTRINGS)
        )
        return {
            "pageerror": len(self.last_pageerrors),
            "console_error_total": len(self.last_console_error_lines),
            "console_error_noise_429": noise,
            "console_error_real": len(self.last_console_error_lines) - noise,
        }
