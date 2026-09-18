"""The admission audit's row renderer honours the endpoint's own refusal (Q1101).

Q1101 makes judging admit a source unattended and names the audit view's UNDO as the
safety valve the flip rests on. The endpoint refuses an undo whose admission is no longer
the decision in effect -- a later admission, or a later verdict that replaced this one --
and a button that renders anyway is the recorded "a control that renders claims its
capability; refusing on click is the surface lying twice" defect, with a refusal message
written for a different entry point as the second lie.

The BEHAVIOUR is driven in node (``admission_row_node_test.js``) against the function
extracted from the shipped module, because the draw call for the button sits INSIDE the
branch that decides: neutering the decision changes nothing a source grep can see.

The pytest half is the driver the node-suite ratchet requires, plus the two claims that
belong on this side -- that the endpoint really publishes the field the renderer reads,
and that every sentence the renderer can put on screen is keyed in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: Every sentence the blocked branch can render. Listed here rather than trusted to the
#: i18n ratchets, because those are MAXIMA -- a shrinking measured population and an
#: improving codebase move a max-gate the same way, so "the gate is green" is not evidence
#: that THESE strings are covered. (The recorded ratchet-allowance lesson, from this very
#: panel: two English fragments sat inside the allowance and the gate could not say so.)
_BLOCKED_STRINGS = [
    "Already undone",
    "A later admission of this source is in effect",
    "A later verdict replaced this one",
    "This source no longer exists",
    "Cannot be undone",
]


def test_admission_row_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "admission_row_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_blocked_sentence_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12, f"expected twelve locale files, found {len(files)}"
    for path in files:
        data = json.loads(path.read_bytes())
        for s in _BLOCKED_STRINGS:
            if s not in data or not str(data[s]).strip():
                missing.append(f"{path.name}: {s!r}")
    assert not missing, "untranslated blocked-reason strings:\n" + "\n".join(missing)


def test_the_renderer_reads_a_field_the_ENDPOINT_ACTUALLY_PUBLISHES() -> None:
    """The recorded dead-end shape, checked from the consumer's side: a renderer branching
    on a key no producer writes draws the wrong state forever, and the node suite -- which
    supplies its own payloads -- is structurally unable to notice."""
    src = (_ROOT / "src" / "catalog" / "qualification.py").read_text(encoding="utf-8")
    js = (_ROOT / "src" / "static" / "app-ai-tools.js").read_text(encoding="utf-8")
    for field in ('"reversible"', '"blocked_by"'):
        assert field in src, f"admission_audit does not publish {field}"
    for field in ("e.reversible", "e.blocked_by"):
        assert field in js, f"the renderer never reads {field}"
