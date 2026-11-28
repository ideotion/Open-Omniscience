"""Row 366(c): the corpus encryption, panic wipe, free-space overwrite and uninstall results follow a language switch.

Each wrote ``t()`` output straight into a node (``textContent``/``innerHTML``), which the i18n walker then reads as English that
matches no key, so the words stayed in the first language until the next run. They now draw through ``ooLive``/``ooLiveHtml``
(row 364) with every translated word computed INSIDE the render, and the uninstall dialog's English lines are keyed. The four
lines left ``configs/i18n_frozen_renderers.txt``; ``tests/test_i18n_frozen_renderers.py`` keeps them out.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
LOCALES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

UNINSTALL_KEYS = (
    "This mode WIPES your data and keys — IRREVERSIBLE.",
    "Create an encrypted backup first?",
    "OK = back up now (then click Uninstall again)",
    "Cancel = continue WITHOUT a backup",
    "UNINSTALL: remove the virtualenv and desktop launchers, then stop the server.",
    "Also delete the app folder.",
    "Also WIPE your data and keys — IRREVERSIBLE.",
    "Your data is KEPT.",
    "Continue?",
    "To confirm, type WIPE in capitals:",
    "To confirm, type UNINSTALL in capitals:",
    "Uninstall cancelled.",
    "Uninstalling — the app is stopping.",
    "Nothing to remove.",
    "uninstalling",
    "Running full overwrite… this can take a while.",
)


def _sinks(body: str) -> list[str]:
    return re.findall(r"\.(?:innerHTML|textContent|innerText|outerHTML)\s*\+?=(?!=)|\.insertAdjacentHTML\s*\(", body)


def test_the_four_renderers_write_no_node_directly():
    for name in ("encryptCorpus", "panicWipe", "secureErase", "uninstallApp"):
        assert _sinks(function_body(JS, name)) == [], name
    listed = (ROOT / "configs" / "i18n_frozen_renderers.txt").read_text(encoding="utf-8").splitlines()
    for name in ("encryptCorpus", "panicWipe", "secureErase", "uninstallApp"):
        assert f"app-backup.js {name}" not in listed


def test_the_wipe_result_translates_inside_its_render():
    wipe = function_body(JS, "panicWipe")
    # words translated once, outside the render, would be redrawn in the old language: they are functions now
    for name in ("psWords", "rec", "holderNote"):
        assert re.search(rf"const {name} = \(\) =>", wipe), name
        assert f"esc({name}())" in wipe, name
    assert 'ooLiveHtml($("panic-result"), _panicPaint)' in wipe
    assert "_panicScrubs = [];" in wipe, "a new wipe's result replaces the overwrites listed under the last one"


def test_an_overwrite_is_listed_under_the_wipe_and_redrawn_with_it():
    erase = function_body(JS, "secureErase")
    assert "_panicScrubs.push(r)" in erase
    assert 'ooLiveHtml(box, _panicPaint || (() => _panicScrubs.map(_panicScrubHtml).join("")))' in erase
    scrub = function_body(JS, "_panicScrubHtml")
    assert "OOI18N.t" in scrub, "it translates where it is called, so a redraw follows a switch"


def test_the_uninstall_dialog_is_keyed_and_the_typed_words_stay_ascii():
    body = function_body(JS, "uninstallApp")
    for key in UNINSTALL_KEYS[:-1]:
        assert f't("{key}")' in body, key
    assert 'const want = sel.wipe_data ? "WIPE" : "UNINSTALL";' in body
    assert "`To confirm, type ${want}" not in body
    assert 'ooLive($("uninstall-result")' in body and 'ooLiveHtml($("uninstall-result")' in body
    assert 't("Running full overwrite… this can take a while.")' in function_body(JS, "secureErase")


def test_every_key_is_in_all_twelve_locales_and_the_typed_words_survive_translation():
    for lang in LOCALES:
        d = json.loads((ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in UNINSTALL_KEYS:
            assert d.get(key), (lang, key)
        assert "UNINSTALL" in d["To confirm, type UNINSTALL in capitals:"], lang
        assert "WIPE" in d["To confirm, type WIPE in capitals:"], lang


def test_the_results_follow_a_language_switch_in_node():
    """The shipped functions, run in ``erase_live_text_366c_node_test.js``, redraw in the new language with no request."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "erase_live_text_366c_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "erase_live_text_366c_node_test.js: OK" in proc.stdout
