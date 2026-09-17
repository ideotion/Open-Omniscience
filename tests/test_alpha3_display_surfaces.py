"""Every surface that shows a country or a language goes through the ONE helper.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-05 asks for "a table-driven test that every display surface calls the helper
(grep-anchored)". This is that test, built as TWO INSTRUMENTS, because either one
alone is a different kind of blind:

* ``_SURFACES`` is the TABLE. One row per surface the brief names, anchored by a
  literal the module must still contain. It answers "did the sweep reach here?"
  and it goes red if a rewired site is reverted. It cannot see a surface nobody
  put in it -- which is the whole failure mode of a hand-written list.

* the DETECTORS answer the other half: "is there a country- or language-shaped
  value reaching a screen that does NOT go through a helper?" They read the tree
  rather than a list, so a NEW surface is covered the day it is written. Every
  exception is registered with a reason, and the reasons are all one reason: a
  STORED value handed to a click handler or a comparison is not a rendering.

The one-hop detector exists because of a real miss in this slice. The insights
per-country chart read ``names[r.country] || String(r.country).toUpperCase()``
into a local and interpolated THAT, so a detector that only reads ``${...}``
expressions saw nothing: the country field and the screen were one assignment
apart. It was found by hand, and a test that could not find it again would be a
test that agreed with the bug.

WHY THE HELPERS AND NOT ``Intl`` DIRECTLY: ``Intl.DisplayNames({type:"region"})``
accepts alpha-2 and M49 only, and ``{type:"language"}`` wants a BCP-47 tag. Handed
``FRA`` or ``fra`` NEITHER throws -- both hand the input straight back. So a call
site that reaches ``Intl`` with a display code fails by printing the code it was
given, which reads as "CLDR has no name for this" and is invisible in review. The
last test here pins ``Intl.DisplayNames`` to the two functions that own it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"

#: The helpers. A call site that names any of these has been through the layer that
#: knows about alpha-3, the four non-ISO codes and the hover.
_HELPERS = (
    "ooCountryCell",
    "ooCountryCode",
    "ooCountryName",
    "ooCountryTitle",
    "ooCountryFlag",
    "ooCountryCompare",
    "ooCountryAlpha2",
    "ooCountryKind",
    "ooLangCell",
    "ooLangCode",
    "ooLangDisplayName",
    "ooLangStorage",
    "ooLangBase",
    "ooLangName",
    "ooRegionName",
)

#: A country- or language-shaped field read off a payload object.
_FIELD = re.compile(
    r"\.(country|jurisdiction|language|detected_language|source_language|target_language)\b"
)

# --------------------------------------------------------------------------- #
#  Instrument 1 — THE TABLE                                                     #
# --------------------------------------------------------------------------- #

#: (module, anchor, what it renders). The anchor is a literal that must still be in
#: the module; the test fails if it is gone, so a revert cannot pass quietly and a
#: deliberate rewrite has to update this row on purpose.
_SURFACES: tuple[tuple[str, str, str], ...] = (
    # --- Governments / law -------------------------------------------------- #
    ("app-gov-law.js", "ooCountryCell(ch.jurisdiction)", "the law-changes feed row"),
    ("app-gov-law.js", "ooCountryCell(x.jurisdiction)", "the tracked-documents table"),
    (
        "app-gov-law.js",
        'ooCountryCode(code), name = ooCountryName(code, "")',
        "the jurisdiction picker (Q308: an <option> has no hover, so it carries both)",
    ),
    ("app-gov-law.js", "ooCountryCompare", "the roster ordering"),
    (
        "app-gov-law.js",
        "`${ooCountryCode(iso)} · ${ooCountryName(iso, iso)}",
        "the choropleth value label (a map tooltip IS the hover)",
    ),
    # --- The map ------------------------------------------------------------ #
    ("app-map.js", "ooCountryCell(s.country)", "a signal's country in the detail list"),
    ("app-map.js", "ooCountryCell(a.country)", "the stats table row"),
    ("app-map.js", "ooCountryCell(iso2By[c.area] || c.area)", "the per-area figures table"),
    ("app-map.js", "ooCountryCode(iso) || ooRegionName(iso,", "the stat-map ranked rows"),
    # --- Sources ------------------------------------------------------------ #
    ("app-sources.js", "ooCountryCell(c.code)", "the country facet chips"),
    ("app-sources.js", "s.country ? ooCountryCell(s.country)", "the sources table row"),
    ("app-sources.js", "s.language ? ooLangCell(s.language)", "the sources table language"),
    (
        "app-sources.js",
        "_pickLabel(ooCountryCode(k), ooCountryName(k",
        "the multi-select country filter (Q308)",
    ),
    (
        "app-sources.js",
        "_pickLabel(ooLangCode(k), ooLangDisplayName(k",
        "the multi-select language filter (Q308)",
    ),
    # --- Agenda ------------------------------------------------------------- #
    ("app-agenda.js", "ooCountryCell(e.country,", "the event row pill"),
    ("app-agenda.js", "ooCountryCell(f.country)", "the calendar-feed directory row"),
    ("app-agenda.js", "ooCountryCell(k)", "the List-view country grouping heading"),
    ("app-agenda.js", "ooCountryFlag(cc)", "the flag beside the code (a convention, never the identifier)"),
    # --- Home --------------------------------------------------------------- #
    ("app-home.js", "ooCountryCell(tr.country)", "the transparency card dimension"),
    ("app-home.js", "ooLangCell(lang)", "a briefing card's language"),
    # --- The corpus window -------------------------------------------------- #
    ("app-corpus.js", "ooCountryCell(meta.country)", "a source's country fact"),
    ("app-corpus.js", "ooLangCell(meta.language)", "a source's language fact"),
    ("app-corpus.js", "ooCountryCell(m.country)", "a matched article's country"),
    # --- The analysis window ------------------------------------------------ #
    ("app-analysis.js", "ooLangCell(a.language)", "the article table language column"),
    ("app-analysis.js", "ooLangCell(l.language)", "the language facet chip"),
    ("app-analysis.js", "ooCountryCode(pl.country)", "the place-facet subtitle"),
    # --- Insights ----------------------------------------------------------- #
    ("app-insights.js", "ooCountryCell(c.country)", "the per-country drill table"),
    ("app-insights.js", "ooCountryCell(c.place_country)", "a place's country"),
    (
        "app-insights.js",
        "font-size=\"10\" fill=\"var(--fg)\">${cc}</text>",
        "the per-country chart axis label (the SVG <title> beside it carries the name)",
    ),
    ("app-insights.js", "ooLangCell(k.language)", "a keyword's language"),
    # --- Diagnostics -------------------------------------------------------- #
    ("app-diagnostics.js", "ooLangCell(q.language)", "the gold-set query header"),
    ("app-diagnostics.js", "ooLangCell(rf.language)", "a write-gate refusal line"),
    ("app-diagnostics.js", "ooLangCell(s.language)", "the frozen-batch keyword strata"),
    ("app-diagnostics.js", "ooLangCell(a.language)", "a mention-builder anchor row"),
    # --- AI tools ----------------------------------------------------------- #
    ("app-ai-tools.js", "ooCountryCell(c.evidence.country)", "a catalog suggestion's evidence"),
    ("app-ai-tools.js", "ooLangName(r.target_language)", "a translation job's language pair"),
    # --- The library -------------------------------------------------------- #
    ("app-library.js", "ooLangName(s.language)", "the per-language shelf label"),
    ("app-library.js", "ooLangName(r.language)", "a row's language"),
    ("app-library.js", "ooLangName(l)", "an export's language list"),
    # --- The observatory (invariant #31: COLOUR is language, never the only signal) #
    ("app-observatory.js", "ooLangName(c)", "the language legend chip"),
    ("app-observatory.js", "ooLangName(code)", "the ranked table's main-language column"),
)

#: The server-rendered half. The bulletin is TEXT and has no hover, so the rule
#: there is the code in the same alphabet as every screen, with the name beside it
#: where the layout already carried one.
_PY_SURFACES: tuple[tuple[str, str, str], ...] = (
    ("src/bulletin/render.py", "country_display_code(r['country'])", "the masthead source-country split"),
    ("src/bulletin/render.py", "language_display_code(r['language'])", "the masthead language split"),
    ("src/bulletin/render.py", 'country_display_code(row.get("country"))', "the by-country heading"),
    ("src/bulletin/coverage.py", "country_display_code(code)", "the coverage label's fallback"),
    ("src/api/source_io.py", "country_payload_iso3(country)", "the source export's country_iso3"),
    ("src/api/law.py", "country_payload_iso3(doc.country)", "a law row's country_iso3"),
    ("src/api/law.py", "country_payload_iso3(doc.jurisdiction)", "a law row's jurisdiction_iso3"),
    ("src/api/timemap.py", "country_payload_iso3(", "a timemap signal's country_iso3"),
    ("src/api/source_management.py", "country_payload_iso3(s.country)", "a source row's country_iso3"),
    ("src/catalog/csv_io.py", "language_storage_code(out[\"language\"])", "the CSV language column, both forms in"),
)


@pytest.mark.parametrize(("module", "anchor", "what"), _SURFACES, ids=lambda v: None)
def test_each_display_surface_still_calls_the_helper(module: str, anchor: str, what: str) -> None:
    path = _STATIC / module
    assert path.exists(), f"{module} moved; the table points at nothing"
    text = path.read_text(encoding="utf-8")
    assert anchor in text, (
        f"{module}: {what} no longer renders through the country/language helper. "
        f"Q302/Q306: the CODE is displayed and the localised name is the hover. "
        f"Missing anchor: {anchor!r}"
    )


@pytest.mark.parametrize(("rel", "anchor", "what"), _PY_SURFACES, ids=lambda v: None)
def test_each_server_side_surface_still_calls_the_helper(rel: str, anchor: str, what: str) -> None:
    path = _ROOT / rel
    assert path.exists(), f"{rel} moved; the table points at nothing"
    assert anchor in path.read_text(encoding="utf-8"), (
        f"{rel}: {what} no longer goes through the one conversion layer. Missing: {anchor!r}"
    )


def test_the_table_covers_every_module_the_sweep_touched() -> None:
    """ANTI-VACUITY. A table-driven test whose table shrank to three rows passes just
    as loudly as one that covers the app, so the population is asserted too: every
    static module that calls a helper at all must have at least one row here."""
    listed = {m for m, _, _ in _SURFACES}
    calling = set()
    for path in sorted(_STATIC.glob("app*.js")):
        if path.name == "app-core.js":
            continue  # where the helpers are DEFINED, not a display surface
        text = path.read_text(encoding="utf-8")
        # A DEFINITION is not a display: `app-map.js` declares ooRegionName/ooLangName
        # and would otherwise be counted for that alone. Subtracting the declarations
        # rather than excluding those two helpers keeps app-library.js and
        # app-observatory.js — whose only country/language rendering goes through
        # ooLangName — inside the table's reach. (Measured: excluding the helpers
        # instead let both modules out, which is a hole shaped like a convenience.)
        for h in _HELPERS:
            if text.count(h + "(") > len(re.findall(r"\bfunction[ \t]+" + h + r"[ \t]*\(", text)):
                calling.add(path.name)
                break
    missing = calling - listed
    assert not missing, (
        "these modules render a country or language through a helper and have no row "
        f"in _SURFACES, so nothing here would notice them regressing: {sorted(missing)}"
    )
    assert len(_SURFACES) >= 36, (
        f"_SURFACES shrank to {len(_SURFACES)} rows; it covered 43 surfaces when written"
    )


# --------------------------------------------------------------------------- #
#  Instrument 2 — THE DETECTORS                                                 #
# --------------------------------------------------------------------------- #

#: Registered exceptions: (module, a literal from the expression) -> why. Every one
#: of them is the same fact -- a STORED value being handed back to code, not shown
#: to a person. They are listed individually anyway, because "it's probably a click
#: handler" is the sentence a real miss hides behind.
_NOT_A_RENDERING: dict[tuple[str, str], str] = {
    (
        "app-analysis.js",
        "esc(JSON.stringify(l.language))",
    ): "the stored code as an onclick argument to the facet toggle — it is sent back to the API",
    (
        "app-insights.js",
        "esc(r.country)",
    ): "the stored code as an onclick argument to _conceptDrillCountry",
    (
        "app-insights.js",
        "esc(c.country)",
    ): "the stored code as an onclick argument to _conceptDrillCountry (the visible cell beside it is ooCountryCell)",
    (
        "app-analysis.js",
        "_anArtFacetSel.language === l.language",
    ): "a boolean for a CSS class, never a code on a screen",
    (
        "app-insights.js",
        "_conceptDrillCountry",
    ): "an onclick attribute built into a local, carrying the stored code as its argument",
}


def _interpolations(text: str) -> list[tuple[int, str]]:
    """Every ``${...}`` expression with its offset, brace-balanced so a nested
    template literal is one expression rather than a truncated prefix."""
    out: list[tuple[int, str]] = []
    i = 0
    while True:
        j = text.find("${", i)
        if j < 0:
            return out
        k, depth = j + 2, 1
        while k < len(text) and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        out.append((j, text[j + 2 : k - 1]))
        i = k


def _rhs(text: str, start: int, cap: int = 4000) -> str:
    """An assignment's whole right-hand side: to the first ``;`` at bracket depth 0.

    Stopping at the newline instead (the obvious implementation) truncates a
    ``.filter(...)\\n.map(...)`` chain at the line break and loses the helper call in
    the ``.map`` — measured: it reported the insights drill table, which is correct
    code, as a leak."""
    depth, i, end = 0, start, min(len(text), start + cap)
    while i < end:
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            break
        i += 1
    return text[start:i]


_ASSIGN = re.compile(r"^[ \t]*(?:const|let|var)[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*", re.M)


def direct_leaks(text: str) -> list[tuple[int, str]]:
    """Interpolations that read a country/language field and name no helper."""
    return [
        (off, expr)
        for off, expr in _interpolations(text)
        if _FIELD.search(expr) and not any(h in expr for h in _HELPERS)
    ]


def one_hop_leaks(text: str, window: int = 40) -> list[tuple[int, str]]:
    """A local derived from a country/language field, then interpolated raw.

    One assignment of distance is all it took to hide the insights chart from the
    direct pass, so the local is followed forward: if every interpolation that uses
    it within ``window`` lines also names a helper, the value was converted on the
    way to the screen and this is not a leak."""
    lines = text.splitlines(keepends=True)
    starts, off = [], 0
    for line in lines:
        starts.append(off)
        off += len(line)
    out: list[tuple[int, str]] = []
    for m in _ASSIGN.finditer(text):
        rhs = _rhs(text, m.end())
        if not _FIELD.search(rhs) or any(h in rhs for h in _HELPERS):
            continue
        idx = max(i for i, s in enumerate(starts) if s <= m.start())
        chunk = "".join(lines[idx + 1 : idx + 1 + window])
        word = re.compile(r"\b" + re.escape(m.group(1)) + r"\b")
        uses = [e for _, e in _interpolations(chunk) if word.search(e)]
        if uses and not any(any(h in e for h in _HELPERS) for e in uses):
            out.append((m.start(), rhs))
    return out


def _unregistered(module: str, hits: list[tuple[int, str]]) -> list[str]:
    left = []
    for _, expr in hits:
        if any(k[0] == module and k[1] in expr for k in _NOT_A_RENDERING):
            continue
        left.append(expr.strip()[:120])
    return left


def test_no_country_or_language_reaches_a_screen_without_the_helper() -> None:
    """The negative space the table cannot cover: a surface written tomorrow."""
    found: dict[str, list[str]] = {}
    for path in sorted(_STATIC.glob("app*.js")):
        hits = direct_leaks(path.read_text(encoding="utf-8"))
        left = _unregistered(path.name, hits)
        if left:
            found[path.name] = left
    assert not found, (
        "a country or language value is interpolated into rendered markup without "
        "passing a display helper. Q302: the CODE is displayed (alpha-3 for a "
        "country, 639-2/T for a language) and the localised name is the hover. If "
        "this is a STORED value going to a click handler or an API call, register it "
        f"in _NOT_A_RENDERING with the reason. {found}"
    )


def test_no_country_or_language_reaches_a_screen_one_assignment_later() -> None:
    found: dict[str, list[str]] = {}
    for path in sorted(_STATIC.glob("app*.js")):
        hits = one_hop_leaks(path.read_text(encoding="utf-8"))
        left = _unregistered(path.name, hits)
        if left:
            found[path.name] = left
    assert not found, (
        "a local derived from a country or language field is rendered without ever "
        f"passing a display helper — the shape that hid the insights chart: {found}"
    )


@pytest.mark.parametrize(
    ("detector", "injected"),
    [
        (direct_leaks, '`<td>${esc(row.country)}</td>`;'),
        (direct_leaks, '`<span>${r.language || "?"}</span>`;'),
        (one_hop_leaks, 'const shown = String(row.country).toUpperCase();\n'
                        'out = `<td>${shown}</td>`;'),
    ],
)
def test_the_detectors_actually_fire(detector, injected: str) -> None:
    """MUTATION CHECK. Both detectors report zero on the tree as it stands, which is
    also what a detector that matches nothing at all reports. So each is handed the
    bypass it exists to catch and must find it."""
    assert detector(injected), f"the detector did not see {injected!r} — it proves nothing"


def test_the_registered_exceptions_are_all_still_real() -> None:
    """A stale allowlist entry is a hole with a comment on it: the expression it
    forgives is gone, so what it now forgives is whatever grows into the same shape."""
    dead = []
    for module, needle in _NOT_A_RENDERING:
        path = _STATIC / module
        if not path.exists() or needle not in path.read_text(encoding="utf-8"):
            dead.append(f"{module}: {needle}")
    assert not dead, f"these _NOT_A_RENDERING entries no longer match anything: {dead}"


# --------------------------------------------------------------------------- #
#  The layer itself                                                             #
# --------------------------------------------------------------------------- #


def test_each_helper_is_declared_exactly_once() -> None:
    """The recorded lesson: duplicate top-level JS function names silently override,
    and every one of these lives in the same global scope."""
    decls: dict[str, list[str]] = {h: [] for h in _HELPERS}
    for path in sorted(_STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for h in _HELPERS:
            n = len(re.findall(r"\bfunction[ \t]+" + re.escape(h) + r"[ \t]*\(", text))
            decls[h].extend([path.name] * n)
    wrong = {h: where for h, where in decls.items() if len(where) != 1}
    assert not wrong, f"a display helper is declared zero or twice: {wrong}"


def test_intl_displaynames_is_reached_only_through_the_two_owning_helpers() -> None:
    """The silent-miss guard, and the reason the helpers exist at all.

    ``Intl.DisplayNames({type:"region"})`` takes alpha-2 or M49; ``{type:"language"}``
    takes BCP-47. Handed a display code NEITHER throws — both return the input. A new
    call site therefore fails by printing the code it was given, which is exactly what
    a missing CLDR name looks like. Keeping construction inside ``ooRegionName`` and
    ``ooLangName`` means one place converts, and that place is tested."""
    sites: list[str] = []
    for path in sorted(_STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"new[ \t]+Intl\.DisplayNames", text):
            line = text.count("\n", 0, m.start()) + 1
            sites.append(f"{path.name}:{line}")
    assert sites, "no Intl.DisplayNames anywhere — this guard stopped measuring"
    owners = {"app-map.js"}
    stray = [s for s in sites if s.split(":")[0] not in owners]
    assert not stray, (
        "Intl.DisplayNames is constructed outside ooRegionName/ooLangName. It answers "
        "an alpha-3 or a 639-2/T code by handing it straight back — no exception, no "
        f"empty string — so this call site will fail silently: {stray}"
    )


def test_the_coverage_repaint_guard_is_locale_aware() -> None:
    """A repaint guard that fingerprints only the PAYLOAD is right about a live poll
    and wrong about a language switch. The 2026-09-16 Chromium walk went en → fr → ar
    → zh and left all 218 country hovers in the coverage panel reading FRENCH, because
    the data never changed and the guard returned early — the same frozen-locale family
    `app-boot.js`'s `oo:langchange` handler already documents for the Lead titles and
    the Composition figures. It became load-bearing here the moment the localised name
    moved out of the visible text and into a hover."""
    src = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    stamps = re.findall(r"const stamp = JSON\.stringify\(\[([^\]]*)\]\)", src)
    assert len(stamps) == 2, (
        "the coverage panel has TWO repaint guards -- one for the map, one for the "
        f"218-row table -- and this test found {len(stamps)}. The first fix made only "
        "the map's locale-aware and the table kept its French hovers, so the COUNT is "
        "asserted: a third guard must be made locale-aware too, not just tolerated."
    )
    for parts in stamps:
        assert "_covUiLang()" in parts, (
            "a coverage repaint fingerprint does not include the active locale, so a "
            f"language switch will not repaint its hovers: [{parts}]"
        )
    assert "OOI18N.current()" in src, "the locale is not read from the i18n engine"

    # AND the other half, because the guards alone are not the fix and this is where
    # the first attempt stopped: with locale-aware guards but nothing re-running the
    # loader, a language switch still left the panel painted in the old locale --
    # measured in Chromium, where a forced `loadCoverage()` came back correct and a
    # bare switch did not. Guarded on the table already having rows, so a switch never
    # fetches for a panel the reader has not opened (also measured: 0 rows).
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    hook = re.search(r'oo:langchange", \(\) => \{(.*?)\n    \}\);', boot, re.S)
    assert hook, "the oo:langchange handler moved; the re-render guard measures nothing"
    # COMMENTS STRIPPED FIRST. The handler's own comment names `loadCoverage()` while
    # explaining why the call is there, so a needle read against raw source is
    # satisfied by the prose ABOUT the call -- measured: deleting the call left this
    # assertion green. That is the recorded "a commented-out call still matched its
    # needle" defect, arriving as a comment that was never code.
    body = re.sub(r"//[^\n]*", "", hook.group(1))
    assert re.search(r"\bloadCoverage\(\)", body), (
        "nothing re-renders the coverage panel on a language switch, so its hovers "
        "will freeze in whichever locale painted them first"
    )
    assert "coverage-table" in body, "the re-render is not guarded on the panel being open"
