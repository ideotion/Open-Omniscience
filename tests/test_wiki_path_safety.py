"""
Wikipedia dump edition-code path-traversal safety (audit PR C).

A dump ``wiki`` code flows into a filesystem path (``data_dir()/wiki_dumps/
<code>wiki-...``) and into the dump fetch URL. Before the fix it was only
``.strip().lower()``-ed, so ``../`` / ``/`` survived into the path. These tests
prove the validator rejects traversal at BOTH the low-level helpers and the API
boundary, while still accepting every real Wikipedia edition code.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.wiki.dumpread import dump_paths
from src.wiki.dumps import dump_filename, dump_url, validate_wiki_code

# Real Wikipedia edition codes the validator MUST keep accepting (incl. the ones a
# naive ^[a-z]{2,3}(-[a-z]+)?$ would wrongly reject: "simple", multi-hyphen codes).
VALID = ["en", "fr", "de", "zh", "simple", "bat-smg", "zh-min-nan", "be-x-old",
         "nds-nl", "zh-classical", "roa-tara", "map-bms"]

# Edition codes that must be REFUSED — every one carries a path-traversal or
# separator vector, or is otherwise not a clean edition code.
# ("EN" is NOT here: it normalises to the valid "en" — case-folding is not a vector.)
EVIL = ["../etc/passwd", "..", "../../en", "en/../../x", "en/", "/en", "a/b",
        "a\\b", "en wiki", "", "  ", ".", "en..", "-en", "en-", "en--us",
        "$(whoami)", "en;rm", "%2e%2e", "a" * 64]


def test_validate_accepts_real_edition_codes():
    for code in VALID:
        assert validate_wiki_code(code) == code.strip().lower()
    # Case/whitespace are normalised, not rejected.
    assert validate_wiki_code("  EN ") == "en"


def test_validate_rejects_traversal_and_separators():
    for bad in EVIL:
        with pytest.raises(ValueError):
            validate_wiki_code(bad)


def test_dump_filename_never_traverses():
    # A valid code yields a contained filename...
    assert dump_filename("fr", "pages-articles-multistream") == (
        "frwiki-latest-pages-articles-multistream.xml.bz2"
    )
    # ...and a traversal attempt raises rather than producing a "../" filename.
    for bad in ("../../etc", "en/../x", "/en"):
        with pytest.raises(ValueError):
            dump_filename(bad, "pages-articles")


def test_dump_url_and_paths_reject_traversal():
    # dump_url interpolates the code into the URL path — must validate it too.
    assert dump_url("fr").startswith("https://dumps.wikimedia.org/frwiki/latest/")
    with pytest.raises(ValueError):
        dump_url("../../evil")
    # dump_paths builds filesystem paths — every member must stay inside base_dir.
    paths = dump_paths("fr", base_dir=None)
    assert all("/wiki_dumps/" in str(p) and ".." not in str(p) for p in paths.values())
    with pytest.raises(ValueError):
        dump_paths("../../escape")


def test_api_dump_endpoints_reject_traversal_with_400():
    """The API boundary returns a clean 400 (never 500, never a filesystem touch)."""
    from src.api.main import app

    c = TestClient(app)
    # probe rejects BEFORE any network probe; page rejects BEFORE any disk read.
    assert c.get("/api/wiki/dumps/probe", params={"wiki": "../../etc"}).status_code == 400
    assert c.get("/api/wiki/dumps/page", params={"wiki": "../x", "title": "Foo"}).status_code == 400
    assert c.post("/api/wiki/dumps/start", json={"wiki": "../../x",
                  "kind": "pages-articles-multistream"}).status_code == 400
    assert c.post("/api/wiki/dumps/corpus-ingest", json={"wiki": "a/b",
                  "titles": ["Foo"]}).status_code == 400
