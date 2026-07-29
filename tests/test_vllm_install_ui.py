"""The vLLM-install frontend blocker (skeptic finding, 2026-07-29).

The 2026-07-29 diff made ``POST /api/llm/vllm/install`` answer 409 with a DICT
``detail`` so the frontend could tell an acknowledgeable resource warning from a
hard refusal. Two things then made the button UNUSABLE on exactly the machine the
work existed to serve (the operator's 6.03 GB host, which WARNS on every click):

  1. ``_apiErrorMessage`` branched only on an Array detail, so a plain object fell
     through as an object and ``new Error(obj).message`` rendered the literal
     "[object Object]" -- the same string that helper was written to abolish.
  2. ``installVllm`` always POSTed ``{}``, so ``acknowledge_low_resources`` was
     never sent and the 409 repeated forever with no way to consent.

The behavioural half runs in Node against the REAL app.js (functions extracted by
name, never re-typed -- a copy would pass while the shipped code was broken). This
wrapper runs it in CI and skips cleanly where node is absent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_object_detail_renders_as_prose_and_the_acknowledge_flow_works():
    test_js = _ROOT / "tests" / "vllm_install_ui_node_test.js"
    assert test_js.exists(), "the node test script must exist"
    r = subprocess.run(
        ["node", str(test_js)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_ROOT),
    )
    assert r.returncode == 0, f"vLLM install UI node test failed:\n{r.stdout}\n{r.stderr}"
    assert "VLLM INSTALL UI OK" in r.stdout


def test_the_install_button_can_reach_the_acknowledged_retry():
    """Source guard for the wiring the node test drives: without a caller that
    sends ``acknowledge_low_resources``, the endpoint's acknowledgeable-409 branch
    is unreachable from the UI and the preflight warning becomes a dead end."""
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    assert "async function _vllmInstallStart()" in app, \
        "the acknowledge-aware start helper must exist"
    fn = app.split("async function _vllmInstallStart() {", 1)[1].split("\n    }\n", 1)[0]
    assert "acknowledge_low_resources: true" in fn, \
        "the retry must send the acknowledgement"
    assert "d.acknowledgeable" in fn, \
        "only an ACKNOWLEDGEABLE refusal may be retried -- a blocking one never is"
    assert "confirm(" in fn, \
        "the operator must be asked before a several-GB download is armed"
    assert "await _vllmInstallStart();" in app, \
        "installVllm must route through the helper, not POST {} directly"
