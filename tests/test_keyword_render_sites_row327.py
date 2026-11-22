"""Row 327: a keyword the page draws is never translated, at every site that draws one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``i18n.js`` translates a text node, and a ``title`` / ``aria-label`` / ``placeholder``, whose whole text equals a
locale key. A corpus keyword is data: "person", "delete" or "online" drawn alone in a cell would be shown as the
locale's word for it, the app altering the user's data on screen. Row 326 made the walker leave anything inside
``translate="no"`` alone (and ``data-i18n-dyn`` already was); this row marks the sites.

THE GUARD. Every ``esc(<…>.term)`` / ``esc(<…>.keyword)`` / ``esc(<…>.kw)`` / ``esc(<…>.normalized)`` in the UI modules is listed below and
must sit either inside a ``data-*`` or ``value`` attribute (never translated), or inside a tag that carries
``translate="no"`` or ``data-i18n-dyn`` -- the tag it is written into, or the element it is the content of. A new
site that is neither fails here and names its line. The detector is a property of the source, so a site written in
a new file or a new helper is found too; ``kwLabelHtml`` (the shared label, ``data-i18n-dyn``) draws most keywords
and is pinned by its own tests.
"""

from __future__ import annotations

import re

from tests.js_source_helper import app_modules, read_static, strip_comments

_KW = re.compile(r"esc\(\s*(?:[A-Za-z_$][\w$]*\.)*(?:term|keyword|kw|normalized)\s*\)")
_ATTR_VALUE = re.compile(r"""(?:data-[\w-]+|value)=(["'])[^"']*$""")
_VOID = re.compile(r"<(?:img|br|hr|input|wbr|meta|link|source|col|area)\b", re.I)
_MARK = re.compile(r"""translate=(["'])no\1|\bdata-i18n-dyn\b""")


def _unmarked(src: str) -> tuple[int, list[str]]:
    """(sites seen, the sites that are neither in a data attribute nor in a marked tag)."""
    seen, bad = 0, []
    for m in _KW.finditer(src):
        seen += 1
        before = src[max(0, m.start() - 600) : m.start()]
        line_before = before.rsplit("\n", 1)[-1]
        if _ATTR_VALUE.search(line_before):
            continue
        lt = before.rfind("<")
        tag_end = src.find(">", m.end()) if before.rfind(">") < lt else -1
        if lt != -1 and before.rfind(">") < lt:
            # the match is INSIDE a tag (an attribute): the tag itself must carry the mark
            tag = before[lt:] + src[m.start() : tag_end + 1]
        else:
            # the match is CONTENT: the element it is the content of (the last opening tag) must carry it
            tag = before[lt : before.find(">", lt) + 1] if lt != -1 else ""
            if _VOID.match(tag) or tag.endswith("/>"):
                tag = ""  # a void or self-closed tag has no content: its mark does not cover a sibling
        if not _MARK.search(tag):
            line = src.count("\n", 0, m.start()) + 1
            bad.append(f"line {line}: {src[m.start() - 60 : m.end()].strip()}")
    return seen, bad


def test_every_keyword_render_site_is_marked_as_data():
    total, problems = 0, []
    for name in app_modules():
        seen, bad = _unmarked(strip_comments(read_static(name)))
        total += seen
        problems += [f"{name} {b}" for b in bad]
    assert total >= 20, f"only {total} keyword render sites found: the detector stopped seeing them"
    assert not problems, (
        'a keyword is drawn where the page translator can rewrite it; wrap it in translate="no":\n'
        + "\n".join(problems)
    )


def test_the_guard_bites():
    """Mutants, so the guard is known to see an unmarked site in each shape it accepts."""
    assert _unmarked("`<td>${esc(r.term)}</td>`")[1]
    assert _unmarked('`<td><br translate="no">${esc(r.term)}</td>`')[1]
    assert _unmarked('`<span class="pill">${esc(k.keyword)} · 3</span>`')[1]
    assert _unmarked('`<input aria-label="${esc(f.term)}">`')[1]
    # and passes the shapes it should
    assert not _unmarked('`<td translate="no">${esc(r.term)}</td>`')[1]
    assert not _unmarked('`<input aria-label="${esc(f.term)}" translate="no">`')[1]
    assert not _unmarked('`<b data-kwstat="${esc(t.term)}">x</b>`')[1]
    assert not _unmarked("`<td data-i18n-dyn>${esc(it.keyword)}</td>`")[1]


_SERIES_KW = re.compile(r"\{\s*label:\s*(?:[A-Za-z_$][\w$]*\.)*(?:term|keyword|kw)\b(?![\w$])")


def test_a_keyword_chart_series_and_enlarge_title_are_marked_as_data():
    """A chart series named by a keyword sets ``labelIsData`` (the shared legend then draws it inside
    ``translate="no"``), and an enlarge dialog titled by a keyword passes ``titleIsData``."""
    seen = 0
    for name in app_modules():
        src = strip_comments(read_static(name))
        for m in _SERIES_KW.finditer(src):
            seen += 1
            obj = src[m.start() : src.find("}", m.end()) + 1]
            assert "labelIsData: true" in obj, (name, obj[:120])
    assert seen >= 4, seen
    markets = read_static("app-markets.js")
    assert "labelIsData: !!s.labelIsData," in markets
    assert '`<span translate="no">${esc(s.label)}</span>`' in markets
    corpus = read_static("app-corpus.js")
    assert (
        'if (opts.titleIsData) ttl.setAttribute("translate", "no"); else ttl.removeAttribute("translate");'
        in corpus
    )
    assert corpus.count("{titleIsData: true}") == 1
    assert read_static("app-home.js").count("{titleIsData: true}") == 1
    assert "label: rel[i], labelIsData: true," in read_static("app-analysis.js")
    # the small-multiples panel header and the zero-mention hover name keywords too
    assert (
        'style="cursor:pointer" translate="no" data-on-click=' in corpus
    )  # the slope chart's end label
    assert '<span translate="no">${esc(p.label || "")}</span></a>' in corpus
    assert (
        '<span class="muted" translate="no" title="${esc(g.members.filter(m => m.mentions === 0)'
        in read_static("app-insights.js")
    )


def test_the_custody_table_words_its_actions_and_names_its_signature():
    from src.custody.log import CustodyAction

    js = read_static("app-ai-tools.js")
    table = re.search(r"const _CUSTODY_ACTION_WORDS = \{(.*?)\};", js, re.S)
    assert table, "the custody action map is gone"
    keys = set(re.findall(r"(?:^|[{,])\s*([a-z_]+):", table.group(1)))
    assert keys == {a.value for a in CustodyAction}, keys
    assert "<th>Signature</th>" in js and "<th>Sig</th>" not in js
