"""S06-05 S2: the Help coverage banner states the served language and a measured figure.

The behaviour is driven in node (``help_banner_node_test.js``) against the functions
EXTRACTED from the shipped module. This side is the driver, the check that the
browser's heading count agrees with the Python skeleton the translated-documents test
uses (two counters for one number is how a banner comes to disagree with its ratchet),
and the check that the three banner strings are keyed in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

from tests.test_help_docs_translated import _served_docs, _skeleton

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

_BANNER_STRINGS = [
    "This document has no draft in this language yet ({language}), so the English original is shown.",
    "Machine-drafted translation ({language}). How much of this document is translated could "
    "not be measured here. The English original is authoritative. Found a better wording? "
    "Improve it on the project page.",
    "Machine-drafted translation ({language}): this draft has {done} of the {total} headings of "
    "the English original; that counts headings, not translated words. The English original is "
    "authoritative. Found a better wording? Improve it on the project page.",
]


def _run_node() -> str:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "help_banner_node_test.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout
    return proc.stdout


def test_banner_node_suite() -> None:
    _run_node()


def test_browser_section_count_equals_the_python_skeleton() -> None:
    out = _run_node()
    line = next(ln for ln in out.splitlines() if ln.startswith("COUNTS "))
    counts = json.loads(line[len("COUNTS "):])
    expected: dict[str, int] = {}
    for file in _served_docs().values():
        expected[file] = len(_skeleton((_ROOT / "docs" / file).read_text(encoding="utf-8")))
    fr = _ROOT / "docs" / "i18n" / "fr" / "QUICKSTART.md"
    if fr.exists():
        expected["fr/QUICKSTART.md"] = len(_skeleton(fr.read_text(encoding="utf-8")))
    assert counts == expected


def test_banner_strings_are_keyed_in_all_twelve_locales() -> None:
    problems: list[str] = []
    paths = sorted(_LOCALES.glob("*.json"))
    assert len(paths) == 12
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _BANNER_STRINGS:
            if s not in data:
                problems.append(f"{path.name}: missing {s[:40]!r}")
            elif not str(data[s]).strip():
                problems.append(f"{path.name}: empty {s[:40]!r}")
            else:
                for ph in ("{language}", "{done}", "{total}"):
                    if ph in s and ph not in data[s]:
                        problems.append(f"{path.name}: lost {ph} in {s[:30]!r}")
    assert not problems, problems
