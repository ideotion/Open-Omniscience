"""A delegated document click listener that takes a step only for a click the browser says a person made (R673).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R443 made the ``data-oo-on`` dispatcher refuse a ``click``/``keydown``/``submit`` whose ``isTrusted`` is not true, so a
script's ``el.click()`` or ``dispatchEvent`` cannot press a button for the person. Four document-level listeners act
outside that dispatcher and had no such check: the task manager's job controls (``data-tm``: cancel, resume, reorder),
the reader's AI-keyword curation (``.r-aibtn``), the reader's date confirm/reject/extract (``.amd-act``,
``#amd-extract``) and the unlock page's buttons (unlock, create, shutdown). Each now returns first on an untrusted event.

The sweep below holds the rule for any later document click listener that sends a request or drives the task manager.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_OPEN = re.compile(r"document\.addEventListener\(\s*[\"']click[\"']\s*,\s*(?:function\s*[\w$]*\s*\(\s*(\w+)\s*\)|\(\s*(\w+)\s*\)\s*=>)\s*\{")
_ACTS = re.compile(r"""\bmethod\s*:\s*["'](?:POST|PUT|PATCH|DELETE)["']|\bwindow\.TM\.|\bpost\(""")


def _listeners(js: str):
    """Yield (param, body) for every inline document-level click listener."""
    for m in _OPEN.finditer(js):
        start = m.end()
        depth, i = 1, start
        while depth:
            depth += {"{": 1, "}": -1}.get(js[i], 0)
            i += 1
        yield (m.group(1) or m.group(2)), js[start : i - 1]


def _guarded(param: str, body: str) -> bool:
    first = body.strip().split("\n", 1)[0]
    return re.fullmatch(rf"if \({param}\.isTrusted !== true\) return;(\s*//.*)?", first.strip()) is not None


def test_the_four_named_listeners_return_first_on_an_untrusted_click():
    want = {"taskmanager.js": 1, "reader.js": 2, "unlock.js": 1}
    for name, n in want.items():
        acting = [(p, b) for p, b in _listeners((_STATIC / name).read_text(encoding="utf-8")) if _ACTS.search(b)]
        assert len(acting) == n, (name, len(acting))
        for param, body in acting:
            assert _guarded(param, body), f"{name}: a click listener that acts must first return on an untrusted event"


def test_no_document_click_listener_acts_without_the_check():
    bare = []
    for path in sorted(_STATIC.rglob("*.js")):
        if "vendor" in path.parts:
            continue
        for param, body in _listeners(path.read_text(encoding="utf-8")):
            if _ACTS.search(body) and not _guarded(param, body):
                bare.append(path.name)
    assert not bare, f"document click listeners that send a request or drive the task manager with no isTrusted check: {bare}"


_NODE = r"""
const fs = require("fs");
const js = fs.readFileSync(process.argv[1], "utf8");
const at = js.indexOf("{", js.lastIndexOf('document.addEventListener("click"', js.indexOf('closest("[data-tm]")')));
let d = 1, i = at + 1;
while (d) { if (js[i] === "{") d++; else if (js[i] === "}") d--; i++; }
const calls = [];
const window = { TM: { cancel: (id) => calls.push(["cancel", id]), resume: () => calls.push(["resume"]),
                       storageResume: () => calls.push(["storage-resume"]), move: () => calls.push(["move"]) } };
const handler = new Function("window", "return function (e) {" + js.slice(at + 1, i - 1) + "};")(window);
const btn = { getAttribute: (k) => ({ "data-tm": "cancel", "data-id": "job-7" })[k] };
const ev = (trusted) => ({ isTrusted: trusted, target: { closest: () => btn } });
handler(ev(false)); handler({ target: { closest: () => btn } });
const untrusted = calls.length;
handler(ev(true));
console.log(JSON.stringify({ untrusted, trusted: calls.slice(untrusted) }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_scripted_click_cancels_no_job_and_a_real_one_does():
    out = subprocess.run(  # noqa: S603
        ["node", "-e", _NODE, str(_STATIC / "taskmanager.js")],  # noqa: S607
        capture_output=True, text=True, timeout=60, check=True,
    )
    got = json.loads(out.stdout)
    assert got == {"untrusted": 0, "trusted": [["cancel", "job-7"]]}, got
