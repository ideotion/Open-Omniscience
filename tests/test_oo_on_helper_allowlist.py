"""What an injected ``data-on-*`` binding can reach: the DOM helpers' ids, the destructive names, the form readers (audit A-004, A-010, A-011).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``oo-on.js`` runs any allowed name from any delegated event, ``error`` and ``load`` included, so markup an
attacker managed to inject (``<img src=x data-on-error="...">``) is a zero-click call. The allowlist of
names is the boundary; these are the rules that keep what the names themselves can do small:

* ``ooClickId`` / ``ooSetValue`` touch only the ids the markup names today (an injected binding could
  otherwise fill any form field by id and then call the handler that reads it);
* a name that erases data and has no ``confirm(`` of its own body runs only for a person's click or
  Enter/Space (``GESTURE_ONLY``), and the listed names are bound to click events only;
* the handlers that read consent-bearing fields read them from the panel the pressed control sits in,
  never by a bare id lookup, and ask before the step that cannot be taken back;
* ``/api/safety/secure-erase`` refuses until a panic wipe has run in this process, and runs one at a time.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, function_body

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_OO_ON = (_STATIC / "oo-on.js").read_text(encoding="utf-8")

_DESTRUCTIVE = re.compile(r"^(delete|remove|secure|panic|uninstall|shutdown)")


def _spa_texts() -> dict[str, str]:
    files = [_STATIC / "index.html", *sorted(_STATIC.glob("app-*.js"))]
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def _allowlist() -> list[str]:
    m = re.search(r"const OO_ACTIONS = \[(.*?)\];", _OO_ON, re.S)
    assert m
    return re.findall(r'"([\w$]+)"', m.group(1))


def _set_literal(name: str) -> set[str]:
    m = re.search(rf"const {name} = new Set\(\[(.*?)\]\);", _OO_ON, re.S)
    assert m, f"oo-on.js must declare {name} as a literal Set"
    return set(re.findall(r'"([^"]*)"', m.group(1)))


@pytest.mark.parametrize(("helper", "table"), [("ooClickId", "CLICK_IDS"), ("ooSetValue", "SET_VALUE_IDS")])
def test_the_helper_ids_are_exactly_the_ids_the_markup_names(helper: str, table: str) -> None:
    allowed = _set_literal(table)
    used: set[str] = set()
    for name, text in _spa_texts().items():
        calls = len(re.findall(rf"\b{helper}\(", text))
        literals = re.findall(rf"\b{helper}\(\s*(['\"])([A-Za-z][\w-]*)\1", text)
        assert calls == len(literals), f"{name}: {helper}( with an argument that is not a literal id"
        used |= {i for _, i in literals}
    assert used == allowed, f"{table} must be exactly the ids bound in markup: unlisted {sorted(used - allowed)}, dead {sorted(allowed - used)}"


def test_every_destructive_name_confirms_in_its_own_body_or_is_gesture_only() -> None:
    gesture = _set_literal("GESTURE_ONLY")
    listed = set(_allowlist())
    assert gesture <= listed, f"GESTURE_ONLY names that are not allowlisted actions: {sorted(gesture - listed)}"
    js = app_js()
    unguarded = []
    for name in sorted(listed):
        if not _DESTRUCTIVE.match(name) or name in gesture:
            continue
        body = function_body(js, name)
        if not re.search(r"\b(confirm|prompt)\(", body):
            unguarded.append(name)
    assert not unguarded, (
        "these names erase or remove and neither confirm() in their own body nor sit in GESTURE_ONLY "
        f"(an injected binding would run them with no click): {unguarded}"
    )


def test_a_gesture_only_name_is_bound_only_to_click_events() -> None:
    """Anything else it is bound to would be refused at run time: the button would silently do nothing."""
    gesture = _set_literal("GESTURE_ONLY")
    bad = []
    for fname, text in _spa_texts().items():
        for m in re.finditer(r'data-on-([a-z]+)="([^"\n]*)', text):
            for name in gesture:
                if re.search(rf"\b{name}\(", m.group(2)) and m.group(1) != "click":
                    bad.append((fname, m.group(1), name))
    assert not bad, bad


_READERS = {
    "encryptCorpus": ("atrest-pw1", "atrest-pw2", "atrest-consent", "atrest-msg"),
    "saveFetchMode": ("fetch-mode", "http-proxy"),
    "saveDiscoveryExternal": ("discovery-external",),
    "ingestUrl": ("ing-url", "ing-source"),
    "importCustomFeed": ("feed-url", "feed-symbol", "feed-unit", "feed-currency", "feed-market", "feed-datecol", "feed-valcol"),
}


@pytest.mark.parametrize("name", sorted(_READERS))
def test_a_form_reading_handler_takes_its_fields_from_the_pressed_control(name: str) -> None:
    body = function_body(app_js(), name)
    for fid in _READERS[name]:
        assert not re.search(r"\$\(\s*[\"']" + re.escape(fid) + r"[\"']\s*\)", body), f"{name} reads #{fid} by a bare id lookup"
        assert "getElementById" not in body, f"{name} looks a field up by bare id"
    # ... and the control is handed in by its own binding.
    markup = _spa_texts()["index.html"]
    assert re.search(rf'data-on-(?:click|change)="{name}\(this\)"', markup), f"{name} is not bound as {name}(this)"
    assert "closest(" in body or name == "saveDiscoveryExternal", f"{name} must resolve its fields from an ancestor of the control"


@pytest.mark.parametrize("name", ["encryptCorpus", "secureErase", "saveFetchMode", "saveDiscoveryExternal"])
def test_the_step_that_cannot_be_taken_back_asks_first(name: str) -> None:
    body = function_body(app_js(), name)
    assert re.search(r"\bconfirm\(", body), f"{name} must confirm() before it acts"
    # the confirm comes before the request, not after it
    assert body.index("confirm(") < body.index("api("), f"{name}: the confirm() must precede the request"


_PROMPTS = (
    "Overwrite all free disk space on this machine? This cannot be undone and can take several minutes on a large disk.",
    "Encrypt the corpus with this passphrase? It will be required at every start and there is no recovery.",
    "Send every fetch through this proxy? You must run and trust the proxy yourself; protected mode cannot guarantee anonymity.",
    "Send your topic-discovery queries to DuckDuckGo? Your query leaves this machine.",
)


def test_the_prompts_are_keyed_in_every_locale_and_used_through_t() -> None:
    js = app_js()
    for key in _PROMPTS:
        assert f't("{key}")' in js, f"the prompt is not read through t(): {key}"
    for path in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        for key in _PROMPTS:
            assert key in d, f"{path.name} lacks {key!r}"
            if path.stem != "en":
                assert d[key] != key, f"{path.name} leaves a consent prompt in English: {key!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("script", ["oo_on_gate_node_test.js", "oo_on_node_test.js"])
def test_the_dispatcher_refuses_what_it_should_in_the_real_code(script: str) -> None:
    result = subprocess.run(  # noqa: S603
        ["node", str(_ROOT / "tests" / script)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
