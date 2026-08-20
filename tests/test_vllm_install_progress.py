"""Install PROGRESS reporting (field report 2026-08-01).

"Clicking on the install button just changes its color, and users are left with
no UI information about what's going on, whether the install is really ongoing,
or not."

The cause was NOT a missing widget. ``POST /api/llm/vllm/install`` only spawns
the worker thread and returns at once (the BackgroundJob chassis is explicit
about this), so the setup chain's ``await _vllmInstallStart()`` had STARTED the
install, not finished it. It then raced on to download a model into a venv that
might not exist yet and to start a server whose backend was still installing --
while the status line sat frozen on one sentence.

The behavioural half runs in Node against the REAL app.js; this wrapper runs it
in CI and skips cleanly where node is absent. The source guards below pin the
wiring that the Node test cannot see (that the chain actually AWAITS each job).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.js_source_helper import app_js

_ROOT = Path(__file__).resolve().parents[1]


def _setup_chain() -> str:
    """The body of the one-button setup runner, scoped so a 'must await' guard
    cannot be satisfied by an unrelated await elsewhere in an 18k-line file."""
    src = app_js()
    at = src.index('if (step.id === "install-vllm")')
    end = src.index('say(t("Starting the local AI…"))', at)
    return src[at:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_follow_job_reports_progress_and_distinguishes_failure_from_outage():
    out = subprocess.run(  # noqa: S603
        [shutil.which("node"), str(_ROOT / "tests" / "vllm_install_progress_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "VLLM INSTALL PROGRESS OK" in out.stdout


def test_the_setup_chain_awaits_the_vllm_install_instead_of_racing_past_it():
    chain = _setup_chain()
    assert "_followJob(\"/api/llm/vllm/install/status\"" in chain, (
        "the chain must FOLLOW the install to completion -- starting it is not "
        "finishing it, and the POST returns as soon as the thread is spawned"
    )
    assert re.search(r'state === "error"', chain), (
        "a failed install must stop the chain, never fall through into steps "
        "that need the backend"
    )


def test_the_setup_chain_awaits_the_model_download_too():
    chain = _setup_chain()
    assert "_followJob(\"/api/llm/default-model/status\"" in chain, (
        "the model step POSTs a multi-GB Hugging Face fetch; without following "
        "it the chain reported Done while gigabytes were still arriving"
    )


def test_progress_is_reported_as_a_real_step_count_never_a_fake_percentage():
    chain = _setup_chain()
    src = app_js()
    assert "Step {i} of {n}" in src, (
        "the plan is a known finite list, so step i of N is a REAL count"
    )
    # The installer is explicit that pip gives no reliable percentage and it must
    # never fake one; the UI must not invent one either.
    assert "%" not in chain.replace("100%", ""), (
        "no synthesised percentage may appear in the setup chain -- the job "
        "reports text, and turning it into a fraction would be a guess"
    )


def test_the_step_template_ships_in_every_locale():
    import json

    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12, f"expected 12 locales, found {len(locales)}"
    for p in locales:
        data = json.loads(p.read_text(encoding="utf-8"))
        val = data.get("Step {i} of {n} — {label}")
        assert val, f"{p.name} is missing the step-counter template"
        # The placeholders are DATA and must survive translation verbatim, or the
        # frame renders a literal {i}/{n}/{label} to the user.
        for ph in ("{i}", "{n}", "{label}"):
            assert ph in val, f"{p.name} dropped {ph} from the step template"
