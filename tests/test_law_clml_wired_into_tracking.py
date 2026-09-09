"""The CLML adapter had no caller, so every tracked law was read as a web page.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/law/adapters/clml.py`` is a complete, spec-documented, fixture-tested
structured-XML reader — adapter #1 of the law brief's S6, ruled adapter-first —
written specifically so legislation.gov.uk documents would be READ rather than
reconstructed. Until 2026-09-09 nothing called it: ``track.py``'s
``_document_text`` had exactly two branches, PDF and HTML, so a document
available as marked-up law was reduced by guessing which parts of a web page
were chrome.

THE ADAPTER IS ITS OWN GATE. It refuses a root element it does not know ("an
HTML error page, a search result, a redirect notice — all parse as 'some XML'"),
refuses malformed and unsafe XML, and refuses when recovered text falls below
``TEXT_RECOVERY_FLOOR``. That is why the branch may be attempted on any XML-ish
body and fall back on refusal — and why NOTHING is decided from the URL. A
legislation.gov.uk allow-list would send that site's own HTML pages into an XML
parser and would miss the identical markup served from anywhere else.

The status is ``"clml"``, deliberately not ``"ok"``: ``check_document`` uses
``reason == "ok"`` to decide it holds HTML worth re-checking for an
extractor-version change, and XML has no chrome to strip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.law.track import _document_text, _looks_like_xml

_FIXTURE = Path(__file__).parent / "fixtures" / "law" / "example_act.clml.xml"


class _Result:
    """The shape ``_document_text`` reads off a fetch result."""

    def __init__(self, content: str, content_type: str = "", raw: bytes | None = None):
        self.content = content
        self.content_type = content_type
        self.raw_content = raw if raw is not None else content.encode("utf-8")


@pytest.fixture(scope="module")
def clml() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_a_clml_body_is_read_by_the_adapter_not_the_html_stripper(clml) -> None:
    text, reason = _document_text(_Result(clml, "application/xml"))
    assert reason == "clml", "the structured reader must be the one that ran"
    assert text
    # Its provisions are present as law text, not as a page reduced by chrome-guessing.
    assert "This Act makes provision about the measurement of things." in text


def test_the_status_is_not_ok_so_the_html_extractor_check_stays_out_of_it(clml) -> None:
    """``check_document`` keeps ``raw_html`` only when ``reason == "ok"``, and then
    re-reads it with the LEGACY stripper to tell "our extractor improved" from "the
    law changed". Running that comparison over XML would compare a structured
    document against a web-page heuristic."""
    _text, reason = _document_text(_Result(clml, "application/xml"))
    assert reason != "ok"
    src = (Path(__file__).resolve().parents[1] / "src" / "law" / "track.py").read_text(
        encoding="utf-8"
    )
    assert 'raw_html = result.content if reason == "ok" else None' in src, (
        "the premise moved: this test explains why the CLML status is not 'ok'"
    )


def test_an_html_page_is_untouched_by_the_new_branch() -> None:
    html = (
        "<html><body><nav>menu</nav><main><p>" + ("The law says a thing. " * 20)
        + "</p></main></body></html>"
    )
    text, reason = _document_text(_Result(html, "text/html"))
    assert reason == "ok", "an ordinary page must still take the HTML path"
    assert "The law says a thing." in text
    assert "menu" not in text, "the boilerplate strip must still run"


def test_xml_that_is_not_clml_falls_back_rather_than_failing(clml) -> None:
    """The commonest real case: the site answers a .xml request with an error
    document. It parses as XML and is not law, and the adapter's root check is
    what catches it."""
    not_law = '<?xml version="1.0"?><error><message>' + ("Not found. " * 40) + "</message></error>"
    text, reason = _document_text(_Result(not_law, "application/xml"))
    assert reason == "ok", "a refusal must fall back, never abort the poll"
    assert "Not found." in text


def test_malformed_xml_falls_back_rather_than_raising() -> None:
    broken = "<?xml version='1.0'?><Legislation><Body><P1>unclosed" + ("x" * 400)
    text, reason = _document_text(_Result(broken, "application/xml"))
    assert reason == "ok"
    assert text is not None, "tracking must survive a body no parser can read"


def test_nothing_is_decided_from_the_url() -> None:
    """A host allow-list would send legislation.gov.uk's own HTML pages into an XML
    parser, and would miss the same markup served from anywhere else."""
    src = (Path(__file__).resolve().parents[1] / "src" / "law" / "track.py").read_text(
        encoding="utf-8"
    )
    import ast

    tree = ast.parse(src)
    code = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ("_document_text", "_looks_like_xml"):
            body = fn.body[1:] if ast.get_docstring(fn) else fn.body
            code.append("\n".join(ast.unparse(node) for node in body))
    assert len(code) == 2, "both halves of the extraction decision must be present"
    decision = "\n".join(code)
    # The docstrings are excluded on purpose: they NAME legislation.gov.uk to explain
    # what CLML is, and a plain substring search over the source would read that
    # explanation as the behaviour -- the recorded house lesson about guards that
    # match the comment instead of the code.
    for host in ("legislation.gov.uk", "result.url", "doc.url", "urlparse", "netloc"):
        assert host not in decision, (
            f"{host!r} appears in the extraction decision; the adapter's own refusal "
            "is the gate, not the address"
        )


@pytest.mark.parametrize(
    ("body", "ctype", "expected"),
    [
        ("<?xml version='1.0'?><Legislation/>", "application/xml", True),
        ("   \n<Legislation/>", "", True),
        ("<!DOCTYPE html><html><body>x</body></html>", "text/html", False),
        ("<html><body>x</body></html>", "", False),
        ("plain text, no markup at all", "text/plain", False),
        ("", "application/xml", False),
        # XHTML served as html: an XML declaration, but it is a web page.
        ("<?xml version='1.0'?><html xmlns='...'><body>x</body></html>", "text/html", False),
    ],
)
def test_the_pre_check_only_pays_for_a_parse_when_the_body_looks_like_xml(
    body, ctype, expected
) -> None:
    assert _looks_like_xml(body, content_type=ctype) is expected


def test_an_adapter_that_raises_something_else_still_falls_back(clml, monkeypatch) -> None:
    """``AdapterRefusal`` is the adapter's designed answer; a ``RuntimeError`` is a
    bug in it. Neither may take the poll down with it, because the HTML path is a
    perfectly good reading and the alternative is a tracked law that silently
    stops being tracked.

    This case survived the first mutation round: removing the broad ``except``
    left every other test green, because nothing here made the adapter fail in a
    way it does not plan for.
    """
    import src.law.adapters.clml as clml_mod

    def _boom(*_a, **_k):
        raise RuntimeError("an adapter bug, not a refusal")

    monkeypatch.setattr(clml_mod, "parse_clml", _boom)
    text, reason = _document_text(_Result(clml, "application/xml"))
    assert reason == "ok", "an adapter crash must fall back to the HTML reading"
    assert text, "and must still produce a body, not None"
