"""Every in-page link in a Help document must land on a real heading.

The docket left this as the residue of the Help axe pass: "9 of USER_MANUAL.md's 50
in-page links that no single consistent slugifier can resolve alongside the reference
anchors (the markdown hand-shortens three targets and pre-dates a heading rename for the
others)", re-measured as INERT rather than ejecting the reader, and so "cosmetic residue,
not the P0".

It turned out not to need a different slugifier. All nine were the SAME class -- a link
typed against the collapsing GitHub convention while the renderer implements the
non-collapsing one, or a target written before its heading was renamed. Every one of the
nine had a real heading to point at, and three of them already appeared in their CORRECT
form elsewhere in the same file, one screen away from the broken copy.

THIS TEST IS THE POINT OF THE FIX. Nine links rot silently: a dead in-page anchor renders
as a perfectly ordinary link and does nothing when clicked, so nobody reports it and
nothing goes red. The check is cheap and mechanical, so it runs over EVERY shipped Help
document rather than only the one that was broken.

The slugifier below is a PORT of `slugifyHeading` in app-settings.js, and the port itself
is guarded (`test_the_port_matches_the_shipped_slugifier_on_its_own_documented_cases`)
against the exact examples that function's comment cites -- otherwise a drifting port
would make this suite quietly test nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _slugify(raw: str) -> str:
    """Port of `slugifyHeading` (src/static/app-settings.js).

    Strip markdown emphasis/code/link syntax, lowercase, DELETE every character that is
    not a letter/number/underscore/hyphen/space, then turn each SURVIVING space into its
    own hyphen -- so a deleted "&" or em dash leaves the spaces on both sides and they
    become two hyphens, never collapsed to one. That double hyphen is exactly what the
    nine broken links were missing.
    """
    t = re.sub(r"`([^`]+)`", r"\1", raw)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"(^|[^*])\*([^*]+)\*", r"\1\2", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = t.lower()
    t = "".join(c for c in t if c.isalnum() or c in "_- ")
    return re.sub(r"^-+|-+$", "", t.replace(" ", "-")) or "section"


def _anchors(md: str) -> set[str]:
    """Heading slugs, with the renderer's per-document dedupe (slug, slug-1, slug-2...)."""
    out: set[str] = set()
    seen: dict[str, int] = {}
    for m in re.finditer(r"^#{1,6}\s+(.*)$", md, re.M):
        slug = _slugify(m.group(1).strip())
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        out.add(slug)
    return out


def _help_docs() -> list[Path]:
    """The documents the Help viewer actually SERVES, read out of the API's own allow-list
    rather than listed here or globbed.

    Globbing `docs/*.md` was wrong in both directions: it pulled in repo documents no
    reader can open from Help, and it would silently stop covering a served document that
    moved. Reading `_DOCS` means a new Help document inherits this check on the commit
    that publishes it, without anyone remembering."""
    src = (_ROOT / "src" / "api" / "main.py").read_text("utf-8")
    block = src[src.index("_DOCS: dict") : src.index('@app.get("/api/docs')]
    names = sorted(set(re.findall(r'"file": "([^"]+)"', block)))
    assert len(names) >= 8, f"the Help allow-list did not parse; got {names}"
    docs = [_ROOT / "docs" / n for n in names]
    missing = [str(d) for d in docs if not d.exists()]
    assert not missing, f"Help serves documents that do not exist: {missing}"
    return docs


def test_the_port_matches_the_shipped_slugifier_on_its_own_documented_cases():
    """`slugifyHeading`'s comment cites the anchors it was verified against. If the port
    drifts from the shipped function, every other test here passes while checking the
    wrong convention -- so pin the port to the same examples first."""
    assert _slugify("1. Install & first run") == "1-install--first-run"
    assert _slugify("3.8 Evidence & custody").endswith("evidence--custody")
    assert _slugify("3.1a Analysis — the corpora window") == "31a-analysis--the-corpora-window"
    assert _slugify("`code` and **bold** and *em*") == "code-and-bold-and-em"


@pytest.mark.parametrize("doc", _help_docs(), ids=lambda p: p.name)
def test_every_in_page_link_resolves_to_a_heading(doc: Path):
    md = doc.read_text("utf-8")
    anchors = _anchors(md)
    dead = sorted({
        link for link in re.findall(r"\]\((#[^)\s]+)\)", md)
        if link[1:] not in anchors
    })
    assert not dead, (
        f"{doc.name} has {len(dead)} in-page link(s) that land on nothing:\n  "
        + "\n  ".join(dead)
        + "\n\nA dead anchor renders as an ordinary link and silently does nothing when "
        "clicked. The usual cause is the COLLAPSING GitHub convention: a deleted '&' or "
        "em dash leaves a space on each side, and both become hyphens -- so the target "
        "needs a DOUBLE hyphen there."
    )


def test_the_user_manual_still_has_the_links_worth_guarding():
    """Negative space: if the manual's in-page links were deleted rather than repaired,
    the parametrised test above would pass while guarding nothing."""
    md = (_ROOT / "docs" / "USER_MANUAL.md").read_text("utf-8")
    links = re.findall(r"\]\((#[^)\s]+)\)", md)
    assert len(links) >= 40, f"expected the manual's table of contents to survive; got {len(links)}"


def test_the_three_targets_that_were_already_right_elsewhere_are_now_consistent():
    """Three of the nine appeared in their CORRECT form elsewhere in the same file while a
    broken copy sat in the table of contents. Pinned because that shape -- one document
    carrying both spellings of one anchor -- is what let it survive a reading."""
    md = (_ROOT / "docs" / "USER_MANUAL.md").read_text("utf-8")
    for target in ("#32-collect-in-settings--collect",
                   "#33-sources-in-settings--sources",
                   "#37-wikipedia-in-settings--wikipedia"):
        assert f"]({target})" in md
        stale = target.split("-in-settings")[0]
        assert f"]({stale})" not in md, f"the pre-rename target {stale} is back"
