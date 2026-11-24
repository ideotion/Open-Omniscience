"""Row 376 (Audit 17 SEC-4): HTML sinks that take a value no escaper clears can only become fewer.

A value written into ``innerHTML``/``outerHTML``/``insertAdjacentHTML`` is parsed as markup; the app's rule is that
every value from a feed, a page, a backup or the user passes through ``esc()`` first. ``scripts/innerhtml_escape_scan.py``
finds, from source, every sink whose right-hand side still holds a name once the known-safe forms are taken out (its
docstring states the method and the BLIND SPOTS -- absence of a hit is weaker evidence than a hit), and
``configs/innerhtml_unescaped_sinks.txt`` lists them per unit with a count.

THE LIST IS THE RATCHET (row 352's shape, Plan's ruling for row 376): no ceiling number, because a shared number makes
every fix PR conflict with every other one. A sink rewritten to escape where it writes lowers its unit's count; a new
raw sink would have to raise one, in plain sight in the diff and the review.

The fixture tests run the scan on small synthetic sources, one per exemption and one per refusal, so the scan is shown
to tell the cases apart rather than assumed to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import innerhtml_escape_scan as ih

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "configs" / "innerhtml_unescaped_sinks.txt"


def _listed() -> list[str]:
    return [ln for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def _hits(js: str) -> int:
    return len(ih.scan_source("f.js", js))


# ---- the ratchet ------------------------------------------------------------------------------


def test_the_lexer_stays_aligned_on_every_scanned_file():
    bad = {}
    for name, js in ih.static_sources().items():
        bal = ih.bracket_balance(ih.lex(js)[1])
        if bal != (0, 0, 0):
            bad[name] = bal
    assert not bad, f"lexer misaligned (open-minus-close of {{ ( [): {bad}"


def test_the_scan_equals_the_committed_list():
    found = ih.counted(ih.scan())
    listed = _listed()
    print(f"\nunescaped HTML sinks: {sum(int(x.rsplit(' ', 1)[1]) for x in found)} in {len(found)} units")
    new = sorted(set(found) - set(listed))
    gone = sorted(set(listed) - set(found))
    assert not new and not gone, (
        "configs/innerhtml_unescaped_sinks.txt is not the scan. "
        f"Found but not listed (a new raw value in an HTML sink: escape it with esc() where it is written): {new}. "
        f"Listed but not found (fixed or moved: update the line in the same PR): {gone}"
    )


def test_the_list_is_sorted_and_has_no_duplicate_unit():
    listed = _listed()
    assert listed == sorted(listed)
    units = [ln.rsplit(" ", 1)[0] for ln in listed]
    assert len(units) == len(set(units))


def test_only_the_two_vendored_folders_and_the_service_worker_are_left_out(tmp_path):
    names = ih.static_sources()
    assert names and not any(n.startswith(("simple/vendor/", "guis/vendor/")) for n in names)
    assert "sw.js" not in names
    assert any("/" in n for n in names), "sub-folders other than the vendored ones (guis, simple) are scanned"
    for rel in ("simple/vendor/x.js", "guis/vendor/x.js", "sw.js", "vendor/glue.js", "simple/sw.js", "a/vendor/b.js"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x.innerHTML = y;\n", encoding="utf-8")
    assert sorted(ih.static_sources(tmp_path)) == ["a/vendor/b.js", "simple/sw.js", "vendor/glue.js"]


def test_the_escapers_are_defined_only_where_they_were_read():
    """An escaper is cleared by its name; a new function, parameter or variable of that name could make a raw sink
    look escaped, so where they are defined is pinned and a new one is read in review (the security read of row 376)."""
    import re

    decl = re.compile(r"(?:function\s+(?:esc|escHtml)\s*\(|(?:const|let|var)\s+(?:esc|escHtml)\s*=)")
    where = sorted(n for n, js in ih.static_sources().items() if decl.search(ih.lex(js)[0]))
    assert where == ["app-core.js", "guis/gallery.js", "investigate.js", "reader.js", "taskmanager.js", "unlock.js"], where


# ---- exemptions: what the scan clears ---------------------------------------------------------


@pytest.mark.parametrize(
    "rhs",
    [
        '""',
        "'<b>fixed markup</b>'",
        "`<td>${esc(row.name)}</td>`",
        "'<a title=\"' + esc(x.title) + '\">' + esc(x.text) + '</a>'",
        "esc(a) + esc(b(c, d))",
        'escHtml(md)',
        '`<b>${t("Saved")}</b>`',
        "OOI18N.t('Loading…')",
        "`${items.length} rows`",
        "`${(v * 100).toFixed(1)} %`",
        "42",
    ],
)
def test_a_cleared_value_is_no_hit(rhs):
    assert _hits(f"function f(el, row, x, a, b, c, d, md, items, v) {{ el.innerHTML = {rhs}; }}") == 0


def test_an_empty_insert_with_a_literal_position_is_no_hit():
    assert _hits('function f(el) { el.insertAdjacentHTML("beforeend", "<hr>"); }') == 0


# ---- refusals: what the scan counts -----------------------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    [
        "el.innerHTML = row.name;",
        "el.innerHTML = `<td>${row.name}</td>`;",
        "el.innerHTML = '<b>' + row.name + '</b>';",
        "el.innerHTML += row.name;",
        "el.outerHTML = html;",
        'el.insertAdjacentHTML("beforeend", html);',
        "el.innerHTML = tf('{n} rows', {n: row.name});",  # tf inserts its variables raw
        "el.innerHTML = t(row.label);",  # only a literal is a translation of the app's own text
        "el.innerHTML = esc(a) + row.name;",  # one escaped part clears only itself
        "el.innerHTML = a.length + row.name;",  # so does a number
        "el.innerHTML = '<b>'\n  + row.name;",  # a statement going on over a line
        "el.innerHTML = '<b>' +\n  row.name;",
        "el.innerHTML = `<div>\n${row.name}</div>`;",  # a template over lines (the security read's must-fix)
        "el.innerHTML = `<div>\n  <b>x</b>\n</div>` + row.name;",
        "el.innerHTML ||= row.name;",
        "el.innerHTML ??= row.name;",
        "el.innerHTML &&= row.name;",
    ],
)
def test_a_raw_value_is_a_hit(stmt):
    assert _hits(f"function f(el, row, html, a) {{ {stmt} }}") == 1


def test_a_comment_or_a_string_that_says_esc_clears_nothing():
    assert _hits("function f(el, x) { el.innerHTML = /* esc( */ x; }") == 1
    assert _hits("function f(el, x) { el.innerHTML = 'esc(' + x; }") == 1


def test_a_lookalike_escaper_clears_nothing():
    assert _hits("function f(el, x) { el.innerHTML = myesc(x) + o.esc(x); }") == 1


def test_a_string_that_mentions_a_sink_is_no_sink():
    assert _hits("function f(x) { log('el.innerHTML = ' + x); }") == 0


def test_the_right_hand_side_ends_where_the_statement_does():
    # the next statement's names are not the sink's
    assert _hits("function f(el, x) {\n  el.innerHTML = ''\n  x.go();\n}") == 0
    assert _hits("function f(el, x) { el.innerHTML = ''; x.go(); }") == 0
    assert _hits("function f(el, x) { if (x) el.innerHTML = ''; else go(x); }") == 0


def test_hits_are_counted_per_innermost_named_unit():
    js = (
        "function outer(el, x) {\n"
        "  el.innerHTML = x;\n"
        "  function inner(y) { el.innerHTML = y; el.innerHTML = y + y; }\n"
        "  const arrow = (z) => { el.innerHTML = z; };\n"
        "}\n"
        "document.body.innerHTML = window.name;\n"
    )
    assert ih.counted(ih.scan_source("f.js", js)) == [
        "f.js (top level) 1",
        "f.js arrow 1",
        "f.js inner 2",
        "f.js outer 1",
    ]


# ---- ooLiveHtml(el, render): a sink too (row 361 moved renderers onto it) -----------------------


@pytest.mark.parametrize(
    "stmt,hits",
    [
        ("ooLiveHtml(el, () => esc(row.name));", 0),
        ('ooLiveHtml(el, () => `<b>${esc(t("Saved"))}</b>`);', 0),
        ("ooLiveHtml(el, (x) => esc(x));", 0),  # an arrow's parameters are no values
        ("ooLiveHtml(el, null);", 0),  # nothing rendered
        ("ooLiveHtml(el);", 0),
        ("ooLiveHtml(el, () => row.name);", 1),
        ("ooLiveHtml(el, () => '<b>' + row.name + '</b>');", 1),
        ("ooLiveHtml(el, render);", 1),  # a function the scan cannot read is counted
        ("ooLiveHtml(el, () => { const h = esc(row.name); return h; });", 1),  # a block body is read whole (strict)
        ("x.ooLiveHtml(el, () => row.name);", 0),  # only the app's own helper is the sink
    ],
)
def test_oolivehtml_is_read_as_a_sink(stmt, hits):
    assert _hits(f"function f(el, row, render) {{ {stmt} }}") == hits


def test_the_oolivehtml_definition_is_no_sink():
    assert _hits("function ooLiveHtml(el, render) { _take(el, null, render); }") == 0
