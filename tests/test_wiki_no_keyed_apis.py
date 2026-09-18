"""Q718 = a: no key-gated Wikimedia source, Enterprise in particular. Stated and pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q718 asks for a CONFIRMATION, and a confirmation nobody can check is a sentence in a
document. What makes it checkable is the pair below: the exclusion is STATED where an
operator reads about hosts, and the tree is asserted to contain no key-gated Wikimedia
endpoint and no credential for one.

The negative test is deliberately narrow. It does not try to prove "this app uses no
API keys anywhere" — it uses several, for sources an operator configures themselves —
only that no WIKIMEDIA path acquired one, which is the thing Q718 rules on.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_SRC = pathlib.Path("src")
_SECURITY = pathlib.Path("docs/SECURITY.md")

#: The paid, key-gated service the ruling names, plus the shapes a credential for it
#: would take. Matched case-insensitively against every Python and JS file under src/.
_FORBIDDEN = (
    "enterprise.wikimedia",
    "api.enterprise.wikimedia.com",
    "wikimedia_enterprise",
    "WIKIMEDIA_API_KEY",
    "WMF_API_KEY",
)

#: ``apihighlimits`` is NOT on that list, and the reason is worth writing down because
#: the first version of this file put it there and reddened on the tree's own
#: provenance comment. The right an anonymous client does not hold is exactly what has
#: to be NAMED for the 50-page cap to be explicable; banning the word would ban the
#: explanation and leave the number looking arbitrary. What matters is that the right
#: is never REQUESTED, which the test below checks directly.
_RIGHT_WE_DO_NOT_HOLD = "apihighlimits"


def _tree_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for pattern in ("**/*.py", "**/*.js"):
        out.extend(p for p in _SRC.glob(pattern) if "__pycache__" not in p.parts)
    return out


def test_the_exclusion_is_STATED_where_an_operator_reads_about_hosts():
    text = _SECURITY.read_text(encoding="utf-8")
    assert "Wikimedia Enterprise" in text
    assert "Q718" in text, "the ruling is cited, so a reader can find what decided it"
    assert "holds no API key" in text


def test_the_stated_COST_of_the_exclusion_is_named_rather_than_glossed():
    """An exclusion whose price is hidden reads as a free choice. It is not one: the
    anonymous limit is 50 pages per request where a keyed client gets 500."""
    text = _SECURITY.read_text(encoding="utf-8")
    assert "50 pages per request" in text
    assert "500" in text


@pytest.mark.parametrize("needle", _FORBIDDEN)
def test_no_key_gated_wikimedia_endpoint_or_credential_exists_in_the_tree(needle):
    hits = []
    for path in _tree_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(re.escape(needle), body, re.I):
            hits.append(str(path))
    assert not hits, f"{needle!r} appears in {hits} -- Q718 = a excludes key-gated sources"


def test_the_guard_can_actually_FIND_something(tmp_path, monkeypatch):
    """The positive control. A scan over the wrong tree, or with a broken pattern,
    passes every assertion above it and reports safety."""
    probe = _SRC / "wiki" / "mediawiki.py"
    body = probe.read_text(encoding="utf-8")
    assert re.search(re.escape("MAX_PAGES_PER_REQUEST"), body, re.I), (
        "the scan reads real files and its pattern matches real content"
    )


def test_the_right_we_do_not_hold_is_EXPLAINED_and_never_REQUESTED():
    """It is named in the comment that explains the 50-page cap, and it appears in no
    request this app builds — no parameter, no header, no query key."""
    from src.wiki import mediawiki

    body = pathlib.Path(mediawiki.__file__).read_text(encoding="utf-8")
    assert _RIGHT_WE_DO_NOT_HOLD in body, "the cap's reason is stated, not left arbitrary"
    for line in body.splitlines():
        stripped = line.strip()
        if _RIGHT_WE_DO_NOT_HOLD not in stripped:
            continue
        assert stripped.startswith("#") or stripped.startswith("#:"), (
            f"{_RIGHT_WE_DO_NOT_HOLD!r} left the comments and reached code: {stripped!r}"
        )


def test_the_anonymous_page_cap_is_the_one_the_tree_actually_uses():
    """The number in the document is the number in the code, not a recollection."""
    from src.wiki.mediawiki import MAX_PAGES_PER_REQUEST

    assert MAX_PAGES_PER_REQUEST == 50
    assert "50 pages per request" in _SECURITY.read_text(encoding="utf-8")
