"""The R1 disclosure's UI wiring — the facts a node suite cannot see.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What the notice SAYS is proven behaviourally in
``tests/cross_language_notice_node_test.js``, which extracts the real renderer from the
shipped module. Only the wiring is checked here: that the notice is actually rendered
into the article list, that the reader's locale reaches the request, and that the
narrowing control does not silently apply to an id-seeded corpus (which has no term to
widen, so offering the choice would describe a control that does nothing).

Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks exactly
like a passing one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import (
    function_body,
    python_function_source,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> str:
    return read_static("app-analysis.js")


def _insights() -> str:
    return (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")


def _code_without_docstring(src: str, name: str) -> str:
    """One function's statements, from the parser, with its docstring dropped.

    ``python_function_source`` gives the whole def; a negative assertion needs the code
    ALONE, because a docstring that names the route not taken would otherwise read as the
    defect it exists to rule out. Bounded by ``ast`` for the reason that helper documents:
    a delimiter that does not occur silently turns the "body" into the rest of the module.
    """
    import ast

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return "\n".join(ast.get_source_segment(src, n) or "" for n in body)
    raise AssertionError(f"no def of {name!r} in the source")


def test_the_notice_is_rendered_into_the_article_list() -> None:
    """A disclosure that exists and is never drawn is the dead-end shape this feature is
    most exposed to -- the rings themselves were correct and unread for a year."""
    body = strip_comments(function_body(_analysis(), "_anLoadArticles"))
    assert "_crossLangNotice(d.cross_language" in body, (
        "the notice is not rendered from the /api/articles payload"
    )


def test_the_readers_locale_reaches_the_request_and_only_for_a_text_query() -> None:
    """``ui_lang`` NARROWS an ambiguous term to the ring matching the reader's language.

    It is sent only with a text query: an id-seeded corpus is an exact set with no term
    to widen, so sending expansion parameters there would imply a choice that does not
    exist.

    THE SEAM MOVED (S04-07 PR 2) and this test followed it rather than being relaxed.
    The lens used to be built inside ``_articleQuery``, which is the Articles list's own
    query builder -- so every OTHER analysis tab fetched without it. It now lives in one
    ``_anApplyLens``, applied once in ``loadAnalysis`` to the params every tab reads and
    again by ``_articleQuery`` to its own copy. Both halves are asserted here, because
    either one alone is the defect: the builder without the delegation is a lens the
    tabs ignore, and the delegation without the builder is a lens that carries nothing.
    """
    body = strip_comments(function_body(_analysis(), "_anApplyLens"))
    assert 'q.get("query")' in body, "expansion params are not gated on a text query"
    assert "ui_lang" in body and "OOI18N.current" in body, (
        "the reader's locale is not passed, so an ambiguous term cannot be narrowed"
    )
    assert '"expand", "false"' in body, "there is no way to request the literal term"
    assert '"literal_cap", "false"' in body, (
        "Q503's note gives the reader a switch for the 40-form cap; it never reaches "
        "the request"
    )
    caller = strip_comments(function_body(_analysis(), "_articleQuery"))
    assert "_anApplyLens(q)" in caller, (
        "the Articles list builds its query without the one lens -- the tab beside it "
        "would describe a different concept"
    )
    loader = strip_comments(function_body(_analysis(), "loadAnalysis"))
    assert "_anApplyLens(new URLSearchParams(p))" in loader, (
        "the analysis tabs fetch without the lens, which is the exact split this "
        "consolidation exists to close"
    )


def test_expansion_is_on_by_default() -> None:
    """R1 rules it ON by default. A default of false would make the feature invisible."""
    src = strip_comments(_analysis())
    assert "let _anExpand = true;" in src, (
        "cross-language expansion is not on by default -- R1 requires it, and the "
        "disclosure plus the one-click narrowing are what make that honest"
    )


def test_cross_language_notice_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "cross_language_notice_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_omnibar_renders_the_disclosure_it_publishes():
    """`search_omni` publishes `cross_language`, a per-row `via_ring` and a separate
    `cross_language_items` count. Until this landed nothing in the frontend read any of
    them -- the "machine-readable answer with no caller" dead end, in the very feature
    whose own commit message names that trap. The BEHAVIOUR is driven in node (the
    renderer, extracted from the shipped module); this pins that the wiring exists at
    all, so a deletion cannot pass by removing the node suite's subject."""
    shell = strip_comments(read_static("app-shell.js"))
    body = function_body(shell, "_omniItems")
    assert "_omniCrossNote(_omniLive.cross_language)" in body, (
        "the omnibar fetches a disclosure and never renders it"
    )
    assert "_omniTypedRows(g)" in body, (
        "the group total must be compared against the rows the reader TYPED, not the "
        "count padded by cross-language sibling rows"
    )
    assert "it.via_ring" in body, "a sibling row must say which concept put it there"


def test_the_omnibar_disclosure_uses_keyed_templates_not_a_built_sentence():
    """A value-bearing sentence is only translatable if its KEY is a fixed template: the
    frame is keyed x12 and the term and the concept are DATA interpolated after."""
    shell = strip_comments(read_static("app-shell.js"))
    body = function_body(shell, "_omniCrossNote")
    assert "tf(" in body and 'OOI18N.tf' in body
    for frame in (
        "{term} also matched as the concept",
        "{term} denotes several concepts, so it was not expanded",
    ):
        assert frame in body, frame
    en_path = Path(__file__).resolve().parents[1] / "src/static/locales/en.json"
    # encoding= is not optional here: the keys asserted below carry curly quotes, so a
    # cp1252 default (Windows) would crash the read rather than fail the assertion.
    en = json.loads(en_path.read_text(encoding="utf-8"))
    for key in (
        "{term} also matched as the concept “{concept}”",
        "{term} denotes several concepts, so it was not expanded",
    ):
        assert key in en, f"the omnibar renders {key!r} with no key behind it"


def test_the_reader_s_sense_choice_reaches_the_request() -> None:
    """R2a's wiring, and the half a node test cannot see.

    The node suite drives the RENDERER, so it proves the pick buttons exist and call the
    handlers. It says nothing about whether the handler's state ever leaves the browser.
    This asserts the query builder actually sends it -- and sends it only under the same
    text-query guard as the rest of R1, since a pin on an id-seeded corpus would name a
    choice that does not exist there.
    """
    body = strip_comments(function_body(_analysis(), "_anApplyLens"))
    assert "_anSenses" in body, "the reader's sense choices never reach the request"
    assert 'q.append("sense"' in body, "the pin is not sent as the repeatable sense param"
    # The guard is now an EARLY RETURN rather than a wrapping `if`, so the property is
    # read the same way it is written: nothing after the bail-out can reach an id-seeded
    # corpus, and the pin sits after it.
    guarded = body.split('if (!q.get("query")) return q;', 1)
    assert len(guarded) == 2 and "_anSenses" in guarded[1], (
        "the pin is sent outside the text-query guard -- it would ride an id-seeded corpus"
    )
    assert 'q.delete("sense")' in guarded[0], (
        "the lens is applied twice to one query (once in loadAnalysis, once in "
        "_articleQuery) and `sense` is APPENDED, so without clearing it first every pin "
        "is sent to the server twice"
    )


def test_choosing_a_sense_and_clearing_it_both_re_run_the_search() -> None:
    """A pick that does not re-run is a label, not a search.

    And it must now re-run the WHOLE window, not just the Articles list: since the lens
    reaches every tab, a pick that refreshed only the list would leave the Keywords, mind
    map, When/Where/Who, Links, Sentiment and Sources tabs describing the previous sense
    with nothing on screen to say so.
    """
    analysis = strip_comments(_analysis())
    for name in ("_anPickSense", "_anClearSense", "_anSetExpand", "_anSetCap"):
        body = function_body(analysis, name)
        assert "_anRerunForLens()" in body, f"{name} does not re-run the search"
    for name in ("_anPickSense", "_anClearSense"):
        assert "_anSenses" in function_body(analysis, name), (
            f"{name} does not touch the sense state"
        )
    rerun = strip_comments(function_body(analysis, "_anRerunForLens"))
    assert "loadAnalysis(" in rerun, (
        "a lens change refreshes the Articles list alone -- every other tab keeps "
        "answering about the previous lens"
    )
    assert "_anSaveLensOnTab()" in rerun and "_anWriteLensToUrl()" in rerun, (
        "Q504: a lens change that is not persisted to the tab and the URL is undone by "
        "the next reload, silently"
    )


def test_a_rejected_pin_is_rendered_rather_than_swallowed() -> None:
    """The endpoint reports a pin it could not apply; a surface that drops it lies.

    Guarded on the KEY the notice renders, not merely on the field name appearing
    somewhere: the payload field could be read and the sentence still never drawn.
    """
    body = strip_comments(function_body(_analysis(), "_crossLangNotice"))
    assert "pin_applied" in body and "pinned_ring" in body
    assert "The sense you chose is not one this word belongs to" in body


def test_every_string_the_pick_renders_is_keyed_in_all_twelve_locales() -> None:
    """A value-bearing sentence needs a keyable FRAME, and a frame needs all 12 files.

    Adding a key to en.json alone leaves `--min 100` red, so this is the guard that
    catches the half-done version rather than CI.
    """
    body = strip_comments(function_body(_analysis(), "_crossLangNotice"))
    keys = [
        "Search one of them:",
        "{term}: searching the concept “{concept}”, which you chose",
        "Show all senses",
        "The sense you chose is not one this word belongs to, so it was ignored.",
    ]
    for key in keys:
        assert key in body, f"{key!r} is not rendered"
    locales = Path(__file__).resolve().parents[1] / "src/static/locales"
    for path in sorted(locales.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} has no entry for {key!r}"



# --------------------------------------------------------------------------- #
# S04-07 PR 2 — the reader-facing half: the cap switch, the per-form counts,
# the group-by-language view, and the lens's own persistence.
# --------------------------------------------------------------------------- #


def test_cross_language_lens_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "cross_language_lens_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_lens_survives_a_reload_and_a_shared_link() -> None:
    """Q504's two persistence paths, asserted as a PAIR.

    The tab seed answers a reload; the URL answers a shared link. Either one alone is
    the half-done version: a reload that restores a narrowing the link does not means
    two readers looking at "the same" analysis see different corpora, with nothing on
    screen saying which.
    """
    analysis = strip_comments(_analysis())
    slim = function_body(analysis, "_anSaveTabs")
    assert "lens: tb.lens" in slim, "the lens is not persisted with the tab"
    seeded = function_body(analysis, "_anApplySeed")
    assert "_anApplyLensSeed(tb.lens)" in seeded, "a restored tab does not restore its lens"
    boot = strip_comments(read_static("app-boot.js"))
    hydrate = function_body(boot, "_hydrateCardCorpus")
    assert "_anReadLensFromUrl()" in hydrate, (
        "a deep link's lens is never read, so a shared search opens as the default one"
    )
    # It must travel as part of the SEED. Applied beside the spawn instead, the new tab's
    # own _anApplySeed would overwrite it and _anWriteLensToUrl would erase it from the
    # URL in the same breath -- which is what the first version of this did.
    assert "openAnalysisFor(analyze, (prov || lens) ? {prov, lens} : undefined)" in hydrate
    assert "openAnalysisForIds(ids, sp.get(\"label\") || \"\", prov, lens)" in hydrate


def test_the_cap_switch_reaches_the_reader_in_both_directions() -> None:
    """Q503's NOTE. A cap that can only be turned off is a one-way door."""
    body = strip_comments(function_body(_analysis(), "_crossLangNotice"))
    assert "_anSetCap(false)" in body, "a capped search offers no way to lift the cap"
    assert "_anSetCap(true)" in body, "with the cap off there is no way to restore it"
    assert "cross.cap_caveat" in body, (
        "the server's own cap sentence is not drawn, so the reader is told a limit "
        "applies without being told what it limited"
    )


def test_the_per_form_counts_are_lazy_and_share_the_lists_denominator() -> None:
    """Q509. Two properties, and the second is the one that could quietly lie.

    LAZY: the counts are N full-text counts over the corpus, so they hang off a click and
    never ride the search. If they were part of the payload every analysis would pay for
    a readout most readers never open.

    SAME DENOMINATOR: the endpoint counts each form with the same ``search_total`` the
    Articles list's own total comes from. The cheap alternative -- summing keyword
    mentions -- counts a different thing, and putting two same-sounding quantities on one
    line is how a reader concludes the corpus is inconsistent.
    """
    analysis = strip_comments(_analysis())
    notice = function_body(analysis, "_crossLangNotice")
    assert "_anFormCounts(" in notice, "there is no way to ask for the per-form counts"
    assert "an-xforms-" in notice, "the counts have no slot to render into"
    fetch = function_body(analysis, "_anFormCounts")
    assert "/api/insights/concept-forms" in fetch, "the trigger calls no endpoint"
    assert "_anSenses" in fetch and "literal_cap" in fetch, (
        "the counts are taken under a different resolution than the list they sit under"
    )
    src = _insights()
    assert "def insights_concept_forms(" in src
    code = _code_without_docstring(src, "insights_concept_forms")
    assert "search_total(" in code, (
        "the per-form counts do not come from the Articles list's own counter"
    )
    assert "keyword_mentions" not in code, (
        "the counts come from extracted mentions rather than full-text matches -- a "
        "different quantity wearing the same caption"
    )


def test_an_unmeasurable_form_is_absent_with_a_reason_never_a_zero() -> None:
    """The recorded rate-meter rule, in a second place: a 0 is a MEASUREMENT.

    A form the server could not count is not a form with no articles. Publishing 0 for it
    tells the reader this corpus carries nothing in that language, which is a claim
    nobody made.
    """
    body = python_function_source(_insights(), "insights_concept_forms")
    assert '"unmeasured"' in body, "an unreadable form has no honest marker"
    assert '"articles"' in body
    js = strip_comments(function_body(_analysis(), "_anFormCountsHtml"))
    assert "f.articles == null" in js, (
        "the renderer does not distinguish an unmeasured form from a measured zero"
    )


def test_the_cap_may_bound_the_fan_out_and_never_a_reported_number() -> None:
    """The anti-capping rule, on the surface that is most exposed to breaking it.

    ``measured_forms`` says how many forms were counted; ``total_forms`` is the exact
    count the concept has on both sides of the cap. A readout that showed only the first
    would let a partial list read as the whole concept.
    """
    body = python_function_source(_insights(), "insights_concept_forms")
    for key in ('"measured_forms"', '"total_forms"', '"capped"', '"ordering"'):
        assert key in body, f"the per-form payload does not publish {key}"
    js = strip_comments(function_body(_analysis(), "_anFormCountsHtml"))
    assert "total_forms" in js and "measured_forms" in js, (
        "the renderer never says how many forms the concept actually has"
    )


def test_grouping_by_language_is_a_view_and_says_so() -> None:
    """Q508's note. The ruled default is interleaved by date; this is the addition.

    It must not re-run anything: a control that silently re-queries while calling itself
    a grouping would change the set under a reader who believed they were re-arranging
    it.
    """
    analysis = strip_comments(_analysis())
    setter = function_body(analysis, "_anSetGroupByLang")
    assert "_anLoadArticles" in setter, "the grouping never re-renders the list"
    assert "_anRerunForLens" not in setter, (
        "grouping re-runs the search -- it is a view over rows already on screen"
    )
    assert "let _anGroupByLang = false;" in analysis, (
        "grouping is on by default; the ruled default is interleaved by date"
    )
    control = function_body(analysis, "_anGroupByLangControl")
    assert "runs no new search" in control, (
        "the control does not tell the reader it changes nothing about what matched"
    )


def test_every_article_row_carries_its_language() -> None:
    """Q508's own half: the language is ON the row, not only in a grouping."""
    body = strip_comments(function_body(_analysis(), "_anLoadArticles"))
    assert "_anLangCell(a)" in body, "the article rows carry no language"
    assert '_anTh("language"' in body, (
        "the Language column is not sortable, although /api/articles has sorted by "
        "language since before this feature existed"
    )
    # The deduced-language half of _anToneChip would now repeat the cell beside it.
    assert "_anToneChip(a)" not in body, (
        "the Source column still carries the deduced-language chip, which the Language "
        "column now states one cell to its right"
    )


def test_every_string_the_lens_renders_is_keyed_in_all_twelve_locales() -> None:
    """The ×12 non-negotiable, enforced at the point of use rather than by the ratchet.

    ``--min 100`` catches a key added to en.json alone, but only once every locale file
    is compared; this names the strings THIS feature renders, so the half-done version
    fails here with the missing string in the message.
    """
    analysis = strip_comments(_analysis())
    rendered = "".join(
        function_body(analysis, name)
        for name in (
            "_crossLangNotice", "_anFormCountsHtml", "_anLangCell",
            "_anGroupByLangControl", "_anGroupRowsByLanguage", "_anFormCounts",
        )
    )
    keys = [
        "Searching every form of the concept.",
        "Limit the search to the most-mentioned forms",
        "Search every form",
        "Count each form",
        "Counts the articles each form of the concept matches. It runs no new search "
        "on this list.",
        "No forms to count.",
        "This form could not be counted.",
        "{n} articles in total, counted once each",
        "{n} of {total} forms counted",
        "Counting…",
        "The forms could not be counted.",
        "Group by language",
        "Interleave by date",
        "Groups the articles already listed. It runs no new search and changes no count.",
        "Language not recorded",
    ]
    for key in keys:
        assert key in rendered, f"{key!r} is not rendered by any of these functions"
    locales = Path(__file__).resolve().parents[1] / "src/static/locales"
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12, f"expected 12 locale files, found {len(files)}"
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} has no entry for {key!r}"


def test_the_expansion_rail_is_not_the_next_frozen_locale_surface():
    """MEASURED in Chromium (2026-09-17), and the same class the keyword label was in.

    The rail's sentences are built at RENDER time — an `OOI18N.tf` frame plus server prose
    through `t()` — so the i18n DOM walker cannot reach them and nothing repaints them on
    a language switch. Two halves, and either alone leaves a reader looking at a caveat in
    a language they did not choose:

    * a SWITCH is answered by `_anRepaintXLang`, registered in app-boot's ONE
      `oo:langchange` listener (a second listener would be a second enumerator), redrawing
      from the payload already in hand so a switch can never re-run a search;
    * BOOT is answered by awaiting `OOI18N.ready`, which is the promise this project added
      for exactly this race. The walk hit it: a deep link in `hi` rendered the frame in
      English while `ar`, `zh` and `ja` came out translated — which locale loses is a
      matter of file size and timing, so it is a race, not a bug in one locale.
    """
    analysis = strip_comments(_analysis())
    repaint = function_body(analysis, "_anRepaintXLang")
    assert "_crossLangNotice(" in repaint, "the repaint does not redraw the rail"
    assert "api(" not in repaint and "fetch(" not in repaint, (
        "a language switch must never fetch -- it redraws from the payload in hand"
    )
    assert "_anLastCross = {" in analysis, (
        "nothing retains the payload the rail was drawn from, so a switch has nothing "
        "to redraw from"
    )
    boot = strip_comments(read_static("app-boot.js"))
    listener = boot.split('addEventListener("oo:langchange"', 1)
    assert len(listener) == 2, "the one oo:langchange listener is gone"
    assert "_anRepaintXLang()" in listener[1], (
        "the rail is not registered in the language-switch repaint, so it freezes in "
        "whichever locale painted it first"
    )
    loader = strip_comments(function_body(analysis, "loadAnalysis"))
    assert "OOI18N.ready" in loader, (
        "the analysis window renders before the locale is loaded, so whichever locale "
        "loses the race to the analysis fetch renders in English"
    )


def test_the_server_prose_the_rail_renders_goes_through_the_translator():
    """A caveat that arrives from the server is still a string on a translated page.

    It rendered in English in ar/zh/ja/hi while every other string on the rail was
    translated — the strings were server-built and the client escaped them straight onto
    the page. The convention this project already uses is `t(server_string)`, exactly as
    `_anRenderProvenance` renders a Lead's own caveat, and it only works if the key is in
    all twelve files.
    """
    analysis = strip_comments(_analysis())
    notice = function_body(analysis, "_crossLangNotice")
    assert "t(cross.caveat)" in notice, "the expansion caveat is not translated"
    assert "t(cross.cap_caveat)" in notice, "the cap caveat is not translated"
    counts = function_body(analysis, "_anFormCountsHtml")
    assert "t(d.caveat)" in counts, "the per-form overlap caveat is not translated"
    assert "t(f.unmeasured)" in counts, "the unmeasured marker is not translated"
    keys = [
        "This search matched the concept in every language the ring covers, not only the "
        "words you typed. Most terms are in no ring and are unaffected.",
        "The search was widened to the most-mentioned forms only. Turn the limit off to "
        "search every form the concept has.",
        "These figures overlap: an article carrying two forms of the concept is counted "
        "under each of them and ONCE in the total, so the per-form numbers do not add up "
        "to it.",
        "this form could not be counted",
    ]
    # Read the server's STRING CONSTANTS from the parser, not from the file's text: these
    # sentences are written as adjacent literals across several lines, and `ast` folds
    # implicit concatenation into one constant, so the comparison is against the value the
    # server actually emits rather than against one line-wrapping of it.
    import ast

    emitted = set()
    for path in (
        _ROOT / "src" / "api" / "insights.py",
        _ROOT / "src" / "analytics" / "equivalence.py",
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                emitted.add(node.value)
    for key in keys:
        # The server must still EMIT the exact sentence the locale files are keyed on:
        # a reworded caveat silently misses its key in eleven languages and renders in
        # English, which is precisely the defect this pair of tests exists to close.
        assert key in emitted, (
            f"the server no longer emits {key[:60]!r}... — the twelve locale keys for it "
            "are now dead and it will render in English"
        )
    locales = Path(__file__).resolve().parents[1] / "src/static/locales"
    for path in sorted(locales.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} has no entry for {key[:60]!r}..."


def test_the_expansion_caveat_carries_no_count_in_its_prose():
    """It said *"Rings cover 698 concepts"* — a number baked into a sentence.

    Two defects in one: it goes stale the moment the ring file grows, and it makes the
    sentence unkeyable, because a locale key must match verbatim. A count belongs in a
    field that reports counts.
    """
    src = (_ROOT / "src" / "analytics" / "equivalence.py").read_text(encoding="utf-8")
    caveat = python_function_source(src, "disclosure")
    import re

    quoted = re.findall(r'"caveat": \(([^)]*)\)', caveat, re.S)
    assert quoted, "the disclosure caveat could not be located"
    assert not re.search(r"\d", quoted[0]), (
        "the expansion caveat carries a digit again; a number in translated prose cannot "
        f"stay true and cannot be keyed: {quoted[0].strip()[:120]}"
    )
