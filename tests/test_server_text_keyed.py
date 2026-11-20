"""Row 206: a caveat, method or reason the server writes reads in the page's language, or says it is English.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two halves, both blind spots of the i18n gates before this row (they read the locale files and the client's t()
calls, never a sentence the SERVER sends):

* the SERVER: every ``said(field, template, ...)`` call in ``src/`` names its template as a string literal, and that
  template is a locale key in all twelve languages whose holes the call fills. A sentence cannot be added in English
  only, nor a hole left unfilled.
* the PAGE: no client file prints a server caveat, method or reason raw (``esc(x.caveat)``, ``el.title = x.method``).
  Each goes through ``ooSaidHtml`` / ``ooSaidText`` (app-core.js), which renders the keyed frames, looks up a
  keyed constant, and otherwise shows the English behind the visible "Server text, in English" label (R289) -- never
  passed off as translated. The few sites left print text the PAGE built and translated itself; they are listed
  below with their reason, and the list is exact: a new raw print fails, and so does a listed one that went away.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"
LOCALES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

#: A server sentence printed raw: escaped as is into HTML, or set as is on a title or a textContent.
_RAW = re.compile(
    r"esc\(\s*[\w$.]+\.(?:caveat|method|reason)\s*\)"
    r"|\.(?:textContent|title)\s*=\s*[\w$.]+\.(?:caveat|method|reason)\s*(?:;|\|\||\+)"
)

#: (file, the matched text) -> (how many, why it is not a server sentence). Exact: zero slack either way.
_PAGE_TEXT = {
    ("app-climate.js", "esc(txt.method)"): (1, "climateText() builds it with t() from the page's own keys"),
    ("app-climate.js", "esc(txt.caveat)"): (1, "climateText() builds it with t() from the page's own keys"),
    ("app-corpus.js", "esc(spec.caveat)"): (1, "the slope chart's caller passes a t() string"),
    ("app-map.js", "esc(opts.method)"): (1, "ooMap's argument; every caller renders it with ooSaidText"),
    ("app-map.js", "esc(opts.caveat)"): (1, "ooMap's argument; every caller renders it with ooSaidText or t()"),
    ("app-map.js", "esc(cd.caveat)"): (1, "ooViz.choroplethData writes it through the translator (keyed x12)"),
    ("app-map.js", ".textContent = cd.caveat +"): (1, "ooViz.choroplethData writes it through the translator"),
    ("app-markets.js", "esc(d.method)"): (1, "a correlation method's NAME (spearman), an identifier"),
}


def _raw_prints() -> Counter:
    found: Counter = Counter()
    for f in sorted(STATIC.glob("*.js")):
        for m in _RAW.finditer(f.read_text(encoding="utf-8")):
            found[(f.name, m.group(0))] += 1
    return found


def test_no_page_prints_a_server_sentence_raw():
    found = _raw_prints()
    listed = Counter({k: v[0] for k, v in _PAGE_TEXT.items()})
    new = found - listed
    assert not new, (
        "a server caveat, method or reason is printed raw -- render it with ooSaidHtml/ooSaidText "
        f"(app-core.js) so it reads in the page's language or says it is English: {dict(new)}"
    )
    gone = listed - found
    assert not gone, f"listed as page text but no longer printed raw -- take it off _PAGE_TEXT: {dict(gone)}"


def test_the_ratchet_sees_a_raw_print():
    """The pattern is the guard; prove it catches each shape it claims to."""
    for line in ('x.innerHTML = `<p>${esc(d.caveat)}</p>`;', "el.title = r.method;", 'n.textContent = d.reason || "";'):
        assert _RAW.search(line), line
    for line in ('el.title = ooSaidText(r, "method");', '`${ooSaidHtml(d, "caveat")}`', "el.textContent = t(d.caveat);"):
        assert not _RAW.search(line), line


def _said_calls():
    """Every ``said(...)`` call, with its arguments as text: a string literal, or the NAME of a module-level string
    constant in the same file (``FETCH_CAVEAT``), resolved here. Anything else stays an AST node and is refused."""
    for path in sorted((ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - the suite's own import would fail first
            continue
        consts = {
            t.id: n.value.value
            for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "said":
                args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str)
                        else consts.get(a.id, a) if isinstance(a, ast.Name) else a for a in node.args]
                yield path.relative_to(ROOT), node, args


def test_every_server_sentence_is_a_key_in_twelve_languages():
    locales = {lang: json.loads((STATIC / "locales" / f"{lang}.json").read_text(encoding="utf-8")) for lang in LOCALES}
    calls = list(_said_calls())
    assert len(calls) >= 10, "said() is no longer found -- was it renamed?"
    problems = []
    for where, call, args in calls:
        at = f"{where}:{call.lineno}"
        if len(args) != 2 or not all(isinstance(a, str) for a in args):
            problems.append(f"{at}: said(field, template) takes two strings, each a literal or a module constant")
            continue
        template = args[1]
        missing = [lang for lang in LOCALES if template not in locales[lang]]
        if missing:
            problems.append(f"{at}: not a key in {missing}: {template[:70]!r}")
        holes = set(re.findall(r"\{(\w+)\}", template))
        given = {k.arg for k in call.keywords if k.arg not in (None, "tr")}
        if holes != given:
            problems.append(f"{at}: holes {sorted(holes)} but values {sorted(given)}")
        for lang in LOCALES:
            if template in locales[lang] and set(re.findall(r"\{(\w+)\}", locales[lang][template])) != holes:
                problems.append(f"{at}: the {lang} translation does not keep the holes {sorted(holes)}")
    assert not problems, "\n".join(problems)


def test_said_builds_the_english_from_its_frame():
    from src.shared_text import said

    out = said("method", "Flags at z >= {z} with >= {n} revisions.", z=3.5, n=4)
    assert out == {
        "method": "Flags at z >= 3.5 with >= 4 revisions.",
        "method_i18n": [{"t": "Flags at z >= {z} with >= {n} revisions.", "v": {"z": 3.5, "n": 4}}],
    }
    assert said("caveat", "Plain.") == {"caveat": "Plain.", "caveat_i18n": [{"t": "Plain.", "v": {}}]}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_helpers_run():
    proc = subprocess.run(["node", str(ROOT / "tests" / "server_text_node_test.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_helpers_are_declared_once():
    """The modules share ONE global scope, where a second declaration of a name silently wins: this row's first draft
    named its helper ooServerText, which app-core.js already declares (an error-message translator), and every call
    ran the other function."""
    src = "\n".join(f.read_text(encoding="utf-8") for f in sorted(STATIC.glob("*.js")))
    for name in ("_ooSaidFramed", "ooSaidText", "ooSaidHtml"):
        assert len(re.findall(rf"\bfunction {name}\(", src)) == 1, name
