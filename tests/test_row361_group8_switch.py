"""Row 361 group 8: the synthesis window, the bulk panel and queue, and the extractor panel follow a switch.

The behaviour is driven in ``analysis_group8_switch_node_test.js``; this file is its driver, plus the
source checks a fake DOM cannot make: the two frames carry no words of their own and let the earlier
render go first, no drawn part is drawn inside another, and the mind map is left to its own re-fetch.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "src" / "static" / "app-analysis.js").read_text(encoding="utf-8")


def _body(name: str) -> str:
    m = re.search(r"(?:async\s+)?function\s+" + name + r"\s*\(", _SRC)
    assert m, name + " not found -- was it renamed?"
    i = _SRC.index("{", _SRC.index(")", m.start()))
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[m.start() : j + 1]
    raise AssertionError(name + " is unbalanced")


def test_group8_parts_follow_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "analysis_group8_switch_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "analysis_group8_switch_node_test.js: OK" in proc.stdout


def test_the_frames_have_no_words_and_let_the_earlier_render_go():
    # A part whose text changes under a drawn ancestor reads to the helper as a foreign write, and the
    # ancestor then stops following a switch. So the count, the busy button and the progress line are
    # drawn as LEAVES inside a frame that is not itself drawn through the helper.
    for frame, ids in (
        ("_synthSelectFrame", ("synth-sel-intro", "synth-count", "synth-run-btn", "synth-sel-list")),
        ("_aiRunFrame", ("ai-run-head-", "ai-run-pick-", "ai-run-skiplbl-", "ai-run-prog-")),
    ):
        body = _body(frame)
        assert re.search(r"\bt\(|tf\(|_tfn\(", body) is None, frame + " must carry no words of its own"
        assert "ooLive(" in body and ", null)" in body, frame + " must let go of the render drawn before it"
        for i in ids:
            assert 'id="' + i in body, i + " missing from " + frame


def test_the_counts_and_the_busy_button_are_never_drawn_into_a_drawn_parent():
    sel = _body("_synthRenderSelect")
    assert 'ooLiveHtml($("synth-win-body")' not in sel.split("_synthSelectFrame(body)")[1]
    assert 'ooLive($("synth-count")' in _body("_synthCount")
    start = _body("aiRunPromptStart")
    assert "prog.textContent" not in start and "prog.innerHTML" not in start
    assert start.count("_aiProgSet(ctx,") >= 6


def test_the_mind_map_is_left_to_its_own_refetch():
    body = _body("renderAnMindmap")
    assert 'host.setAttribute("data-i18n-dyn", "")' in body
    assert "ooLive(host, null)" in body
    assert '["an-mindmap", "anMindmapRepaint"]' in (_ROOT / "src" / "static" / "app-corpus.js").read_text(
        encoding="utf-8"
    )
