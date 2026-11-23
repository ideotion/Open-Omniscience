"""Row 352: renderers that freeze after a language switch can only become fewer.

The i18n walker records the first text it sees on a node as "the English" and keeps out of
``[data-i18n-dyn]``; a renderer that writes ``t()``/``tf()`` output into an ordinary node leaves
translated text there that no later switch can change. ``scripts/i18n_frozen_renderers.py``
finds every such renderer from source (its docstring states the method, why the repaint depth is
3, and the BLIND SPOTS -- absence of a hit is weaker evidence than a hit), and
``configs/i18n_frozen_renderers.txt`` lists the ones on main.

THE LIST IS THE RATCHET (Plan's ruling, 2026-11-23): there is deliberately no ceiling number,
because a shared number in a test file makes every fix PR conflict with every other one (the
ledger learned that with ``_LESSONS_LINE_CEILING`` on 2026-10-06). A fix deletes its own line; a
new freeze would have to add one, in plain sight in the diff and the review.

The fixture tests below run the scanner on small synthetic sources, one per exemption and one per
refusal, so the scanner is shown to tell the cases apart rather than assumed to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import i18n_frozen_renderers as fr

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "configs" / "i18n_frozen_renderers.txt"


def _listed() -> list[str]:
    return [
        ln
        for ln in LIST.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def _keys(sources: dict[str, str], index_html: str = "") -> set[str]:
    return {h.key for h in fr.scan_sources(sources, index_html)}


# ---- the ratchet ------------------------------------------------------------------------------


def test_the_lexer_stays_aligned_on_every_scanned_file():
    # A regex literal the division heuristic misreads would shift every later bracket; this is
    # the loud failure the docstring promises instead of a silently wrong scan.
    bad = {}
    for name, js in fr.static_sources().items():
        bal = fr.bracket_balance(fr.lex(js)[1])
        if bal != (0, 0, 0):
            bad[name] = bal
    assert not bad, f"lexer misaligned (open-minus-close of {{ ( [): {bad}"


def test_the_scan_equals_the_committed_list():
    found = {h.key: h for h in fr.scan()}
    listed = set(_listed())
    print(f"\ni18n frozen renderers: {len(listed)} listed, {len(found)} found")
    extra = sorted(set(found) - listed)
    gone = sorted(listed - set(found))
    msg = []
    if extra:
        msg.append(
            "NEW renderer(s) write t()/tf() output into a node no language switch repaints. Mark the "
            "host data-i18n-dyn and repaint it from the oo:langchange listener (rows 350/351 show how), "
            "rather than adding a line to configs/i18n_frozen_renderers.txt:\n"
            + "\n".join(f"  {k}  (line {found[k].line})" for k in extra)
        )
    if gone:
        msg.append(
            "Listed renderer(s) no longer found -- fixed, renamed or removed. Delete their lines from "
            "configs/i18n_frozen_renderers.txt in this PR (a rename re-adds under the new name):\n"
            + "\n".join(f"  {k}" for k in gone)
        )
    assert not msg, "\n\n".join(msg)


def test_the_list_is_sorted_and_has_no_duplicates():
    lines = _listed()
    assert lines == sorted(lines), "keep configs/i18n_frozen_renderers.txt sorted"
    dupes = sorted({x for x in lines if lines.count(x) > 1})
    assert not dupes, f"duplicate lines: {dupes}"
    for ln in lines:
        assert len(ln.split(" ")) == 2 and ln.split(" ")[0].endswith(".js"), (
            f"not 'file name': {ln!r}"
        )


# ---- the scanner, on fixtures -----------------------------------------------------------------

RENDER = 'function paint() { const t = OOI18N.t; $("x").textContent = t("Hello"); }\n'


def test_an_unmarked_renderer_is_counted():
    assert _keys({"a.js": RENDER}) == {"a.js paint"}


@pytest.mark.parametrize(
    "src",
    [
        'function paint() { const h = $("x"); h.innerHTML = esc(t("Hello")); }',
        'function paint() { $("x").textContent += trf("{n} more", {n: 1}); }',
        'function paint() { $("x").outerHTML = `<p>${_t("Hello")}</p>`; }',
        'function paint() { $("x").textContent = _tf("A {b}", {b: 1}) + _custT("C"); }',
        'function paint() { $("x").textContent = OOI18N.t("Hello"); }',
        'const paint = function () { $("x").textContent = t("Hello"); };',
        'const paint = (h = $("x")) => { h.textContent = t("Hello"); };',
        'const paint = h => { h.textContent = t("Hello"); };',
        'function paint() { $("x").innerHTML += `<b>${esc(tf("{n} items", {n: 2}))}</b>`; }',
        'async function paint() { $("x").insertAdjacentHTML("beforeend", OOI18N.tf("A {b}", {b: 1})); }',
        'const paint = (host) => { host.innerText = tr("Hello"); };',
    ],
)
def test_every_sink_and_translator_form_is_counted(src):
    assert _keys({"a.js": src}) == {"a.js paint"}


@pytest.mark.parametrize(
    "src",
    [
        'function paint() { const h = $("x"); h.setAttribute("data-i18n-dyn", ""); h.textContent = t("Hello"); }',
        'function paint() { $("x").innerHTML = `<div data-i18n-dyn="">${esc(t("Hello"))}</div>`; }',
        'function paint() { const h = $("x"); h.dataset.i18nDyn = ""; h.textContent = t("Hello"); }',
    ],
)
def test_a_renderer_that_marks_its_output_is_exempt(src):
    assert _keys({"a.js": src}) == set()


@pytest.mark.parametrize(
    "src",
    [
        # a comparison, then a selector: not a tag in a string
        'function paint() { for (let i = 0; i<3; i++) {} const h = $("x").closest("[data-i18n-dyn]"); h.textContent = t("Hello"); }',
        # a read of the marker is not marking
        'function paint() { const h = $("x"); if (h.dataset.i18nDyn) return; h.textContent = t("Hello"); }',
    ],
)
def test_looking_for_the_marker_is_not_marking(src):
    assert _keys({"a.js": src}) == {"a.js paint"}


def test_a_comment_that_names_the_marker_exempts_nothing():
    src = 'function paint() {\n  // this host is marked data-i18n-dyn elsewhere\n  /* <div data-i18n-dyn> */\n  $("x").textContent = t("Hello");\n}'
    assert _keys({"a.js": src}) == {"a.js paint"}


def test_an_id_index_html_marks_dyn_is_exempt():
    html = '<div id="home-stats" class="x" data-i18n-dyn></div><div data-i18n-dyn id="other"></div>'
    assert fr.dyn_ids(html) == {"home-stats", "other"}
    src = 'function paint() { $("home-stats").textContent = t("Hello"); }'
    assert _keys({"a.js": src}, html) == set()
    sel = 'function paint() { document.querySelector("#home-stats .n").textContent = t("Hello"); }'
    assert _keys({"a.js": sel}, html) == set()
    assert _keys({"a.js": src}, '<div id="home-stats"></div>') == {"a.js paint"}
    # the same word as an ordinary string key is not a lookup of that element
    key = 'function paint() { const m = {"home-stats": 1}; $("x").textContent = t("Hello"); }'
    assert _keys({"a.js": key}, html) == {"a.js paint"}


def _chain(n: int) -> str:
    """A listener that reaches ``paint`` in exactly ``n`` calls."""
    hops = [f"function hop{i}() {{ hop{i + 1}(); }}" for i in range(1, n - 1)]
    first = "hop1()" if n > 1 else "paint()"
    if n > 1:
        hops.append(f"function hop{n - 1}() {{ paint(); }}")
    return (
        f'document.addEventListener("oo:langchange", () => {{ {first}; }});\n'
        + "\n".join(hops)
        + "\n"
        + RENDER
    )


@pytest.mark.parametrize("n,counted", [(1, False), (2, False), (3, False), (4, True)])
def test_a_repaint_counts_within_three_calls_and_not_beyond(n, counted):
    assert ("a.js paint" in _keys({"a.js": _chain(n)})) is counted


def test_a_listener_registered_by_reference_repaints():
    src = RENDER + 'document.addEventListener("oo:langchange", paint);\n'
    assert _keys({"a.js": src}) == set()


def test_a_repaint_in_one_file_does_not_exempt_a_namesake_in_another():
    listener = 'document.addEventListener("oo:langchange", () => { paint(); });\nfunction paint() { $("y").textContent = "x"; }\n'
    assert _keys({"a.js": listener, "b.js": "function wrap() { " + RENDER + " }"}) == {"b.js paint"}
    # a TOP-LEVEL function of another file is what a bare call reaches
    assert (
        _keys(
            {
                "a.js": 'document.addEventListener("oo:langchange", () => { paint(); });',
                "b.js": RENDER,
            }
        )
        == set()
    )


def test_declaring_a_nested_function_is_not_calling_it():
    src = 'document.addEventListener("oo:langchange", () => { outer(); });\nfunction outer() { function inner() { $("x").textContent = t("Hi"); } }'
    assert _keys({"a.js": src}) == {"a.js inner"}


def test_a_call_written_inside_a_string_is_not_a_repaint():
    # onclick text in an HTML string is not a call the listener makes
    src = (
        'document.addEventListener("oo:langchange", () => { $("y").innerHTML = "<a onclick=\\"paint()\\">x</a>"; });\n'
        + RENDER
    )
    assert _keys({"a.js": src}) == {"a.js paint"}


def test_a_translator_name_inside_a_string_is_not_a_call():
    src = 'function paint() { $("x").textContent = "use t(\\"key\\") here"; }'
    assert _keys({"a.js": src}) == set()


def test_a_comparison_is_not_a_sink():
    src = 'function paint() { if ($("x").textContent == t("Hello")) return; }'
    assert _keys({"a.js": src}) == set()


def test_a_regex_holding_a_quote_does_not_derail_the_lexer():
    src = (
        'function esc(s) { return String(s).replace(/"/g, "&quot;").replace(/\'/g, "&#39;"); }\n'
        + RENDER
    )
    code, skel = fr.lex(src)
    assert fr.bracket_balance(skel) == (0, 0, 0)
    assert _keys({"a.js": src}) == {"a.js paint"}


def test_a_nested_renderer_is_charged_to_itself_not_its_parent():
    src = 'function outer() { function inner() { $("x").textContent = t("Hello"); } inner(); log(t("x")); }'
    assert _keys({"a.js": src}) == {"a.js inner"}


def test_the_shipped_walker_still_keeps_out_of_dyn_hosts():
    # The scan's premise: without this skip, marking a host would not stop the freeze.
    walker = (ROOT / "src" / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "closest('[data-i18n-dyn],[translate=\"no\"]')" in walker
