"""The default-model download must provision for a backend that is actually here.

Field report 2026-08-02: "the install still fails after reinstall. It seems that model
does not download." The bundle said the install had SUCCEEDED (outcome=installed, exit
0, resolver=uv, 2943 s) on a laptop with an RTX 4070, vLLM installed but never started,
and Ollama not installed at all. Two defects met on the download step, both reproduced
from those facts before anything was changed:

  1. ``_default_model_plan`` read ``resolve_backend()``'s SELECTION as the download
     target. Selection correctly said "ollama" -- Ollama is the ruled fallback, and its
     own reason said outright that nothing was reachable -- so the plan named an Ollama
     TAG and the POST queued a pull into a daemon that does not exist. The setup panel
     said "This machine will use vLLM" on the same screen, because the frontend picks
     its target from the hardware: two notions of "which backend" in one chain.

  2. ``/default-model/status`` published no top-level ``state`` on EITHER branch, and
     the setup chain's follower waits for exactly that. So the chain hung on the
     download step forever -- which is what made defect 1 silent instead of loud.

The rules pinned here are the ones a future change could quietly undo: provisioning is
not routing, an operator's override still wins, and a missing prerequisite is named
rather than queued into.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import src.api.llm as L
import src.llm.backend as B

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def machine(monkeypatch):
    """Drive the REAL ``resolve_backend`` from a machine's facts, so these tests
    exercise the production resolver rather than a hand-written payload that could
    drift from what it actually returns."""

    def _make(*, gpu, vllm_installed, vllm_running, ollama_installed, ollama_running, override=""):
        monkeypatch.setattr(
            B,
            "detect_gpu",
            lambda: {"available": True, "name": "RTX 4070", "vram_mb": 8188}
            if gpu
            else {"available": False},
        )
        monkeypatch.setattr(
            B, "_vllm_status", lambda: {"installed": vllm_installed, "running": vllm_running}
        )
        monkeypatch.setattr(B, "_ollama_available", lambda: ollama_running)
        monkeypatch.setattr(B, "_ollama_installed", lambda: ollama_installed)
        monkeypatch.setenv("OO_LLM_BACKEND", override)
        return B.resolve_backend()

    return _make


# The field machine, exactly as the 2026-08-02 bundle reported it.
FIELD = dict(
    gpu=True, vllm_installed=True, vllm_running=False, ollama_installed=False, ollama_running=False
)


# --------------------------------------------------------------------------- #
#  1. provisioning is not routing
# --------------------------------------------------------------------------- #
def test_the_field_machine_downloads_for_vllm_not_for_an_absent_ollama(machine):
    r = machine(**FIELD)
    # The resolver is NOT wrong -- routing genuinely has nothing to route to, and
    # Ollama is the ruled fallback. That is precisely why the download must not
    # read this field.
    assert r["backend"] == "ollama"
    assert r["no_backend"] is True

    pick = L._provisioning_backend(r)
    assert pick["backend"] == "vllm"
    assert pick["prerequisite"] is None


def test_the_plan_names_the_hugging_face_repo_not_the_ollama_tag(machine):
    """The whole visible symptom: the panel offered an Ollama tag on a machine with no
    Ollama, so nothing could ever download."""
    machine(**FIELD)
    plan = L._default_model_plan()
    assert plan["backend"] == "vllm"
    assert "/" in plan["artifact"], "a HuggingFace repo id, not a quantised tag"
    assert plan["mechanism"] == "download"
    assert ":" not in plan["artifact"]


@pytest.mark.parametrize(
    ("case", "facts", "want"),
    [
        ("vLLM installed but stopped", FIELD, "vllm"),
        (
            "vLLM running",
            dict(FIELD, vllm_running=True),
            "vllm",
        ),
        (
            "Ollama installed but stopped, no GPU",
            dict(
                gpu=False,
                vllm_installed=False,
                vllm_running=False,
                ollama_installed=True,
                ollama_running=False,
            ),
            "ollama",
        ),
        (
            "both installed, neither running, GPU present",
            dict(FIELD, ollama_installed=True),
            "vllm",
        ),
        (
            "both installed, Ollama is the one actually serving",
            dict(FIELD, ollama_installed=True, ollama_running=True),
            "ollama",
        ),
        (
            "nothing installed, GPU present",
            dict(FIELD, vllm_installed=False),
            "vllm",
        ),
        (
            "nothing installed, no GPU",
            dict(
                gpu=False,
                vllm_installed=False,
                vllm_running=False,
                ollama_installed=False,
                ollama_running=False,
            ),
            "ollama",
        ),
    ],
)
def test_the_choice_follows_what_is_installed_then_what_the_hardware_can_use(
    machine, case, facts, want
):
    pick = L._provisioning_backend(machine(**facts))
    assert pick["backend"] == want, case
    assert pick["chosen_because"], "every choice states its reason"


def test_a_reachable_backend_still_wins_even_against_the_hardware_preference(machine):
    """A GPU box whose vLLM is down but whose Ollama is UP should feed the thing that
    is serving. Downloading for the idle backend would leave the running one modelless."""
    pick = L._provisioning_backend(machine(**dict(FIELD, ollama_installed=True, ollama_running=True)))
    assert pick["backend"] == "ollama"
    assert "serving right now" in pick["chosen_because"]


def test_an_explicit_override_is_never_second_guessed(machine):
    """Same precedence as everywhere else in the app -- but an override onto a backend
    that is not installed must still surface as a prerequisite rather than a download."""
    pick = L._provisioning_backend(machine(**FIELD, override="ollama"))
    assert pick["backend"] == "ollama"
    assert pick["prerequisite"] == "ollama"


# --------------------------------------------------------------------------- #
#  2. a missing prerequisite is NAMED, never queued into
# --------------------------------------------------------------------------- #
def test_a_missing_backend_is_reported_as_a_prerequisite(machine):
    for facts, missing in (
        (dict(FIELD, vllm_installed=False), "vllm"),
        (
            dict(
                gpu=False,
                vllm_installed=False,
                vllm_running=False,
                ollama_installed=False,
                ollama_running=False,
            ),
            "ollama",
        ),
    ):
        assert L._provisioning_backend(machine(**facts))["prerequisite"] == missing


def test_the_ollama_install_refuses_by_name_instead_of_queueing_into_nothing(monkeypatch):
    """The pull queue accepts any well-formed tag and only meets the missing daemon
    inside its pump thread, so without this check the operator got a cheerful "queued"
    for a download that could never begin. Its vLLM sibling has had this refusal since
    it shipped; this is the symmetric one."""
    from fastapi import HTTPException

    monkeypatch.setattr(
        L,
        "_default_model_plan",
        lambda: {
            "backend": "ollama",
            "artifact": "ministral-3:3b-instruct-2512-q4_K_M",
            "prerequisite": "ollama",
        },
    )
    from src.ingest import egress_window as ew

    ew._reset_for_tests()  # a clean egress state, so the refusal under test is the one asserted

    enqueued: list[str] = []

    class _Mgr:
        def enqueue(self, model):  # pragma: no cover - must never run
            enqueued.append(model)
            return {}

    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: _Mgr())

    with pytest.raises(HTTPException) as exc:
        L.default_model_install()
    assert exc.value.status_code == 409
    assert "Ollama is not installed" in str(exc.value.detail)
    assert enqueued == [], "nothing may be queued for a backend that cannot run it"


# --------------------------------------------------------------------------- #
#  3. the status endpoint speaks its follower's vocabulary -- on BOTH branches
# --------------------------------------------------------------------------- #
_TERMINAL = {"done", "error", "cancelled", "idle"}


def test_both_branches_publish_a_top_level_state(machine, monkeypatch):
    """The follower returns when ``state`` exists and is not "running". Neither branch
    published one, so it polled forever and the setup chain hung on the download step.
    This is the assertion that would have caught it."""
    machine(**FIELD)
    st = L.default_model_status()
    assert st["backend"] == "vllm"
    assert st["state"] in _TERMINAL | {"running"}

    machine(
        gpu=False,
        vllm_installed=False,
        vllm_running=False,
        ollama_installed=True,
        ollama_running=False,
    )
    st = L.default_model_status()
    assert st["backend"] == "ollama"
    assert st["state"] in _TERMINAL | {"running"}


def test_the_status_payload_still_carries_the_detail_it_always_did(machine):
    """The new fields are additive: a caller reading ``plan`` or ``queue``/``job``
    keeps working."""
    machine(**FIELD)
    st = L.default_model_status()
    assert "plan" in st and "job" in st
    machine(
        gpu=False,
        vllm_installed=False,
        vllm_running=False,
        ollama_installed=True,
        ollama_running=False,
    )
    st = L.default_model_status()
    assert "plan" in st and "queue" in st


@pytest.mark.parametrize(
    ("queue", "installed", "want"),
    [
        ({"active": {"model": "m", "status": "pulling", "percent": 12.5}}, False, "running"),
        ({"active": None, "queue": ["m"]}, False, "running"),
        ({"active": None, "queue": [], "history": [{"model": "m", "status": "done"}]}, False, "done"),
        (
            {"active": None, "queue": [], "history": [{"model": "m", "status": "error"}]},
            False,
            "error",
        ),
        (
            {"active": None, "queue": [], "history": [{"model": "m", "status": "cancelled"}]},
            False,
            "cancelled",
        ),
        # Someone else's model finishing says nothing about ours.
        ({"active": None, "queue": [], "history": [{"model": "other", "status": "done"}]}, False, "idle"),
        ({"active": None, "queue": [], "history": []}, True, "done"),
        ({"active": None, "queue": [], "history": []}, False, "idle"),
        # The daemon is down, so "is it installed" is unknown -- never a fabricated done.
        ({"active": None, "queue": [], "history": []}, None, "idle"),
    ],
)
def test_the_pull_queue_is_mapped_to_that_vocabulary_without_inventing_success(
    queue, installed, want
):
    assert L._pull_queue_state("m", queue, installed)["state"] == want


def test_the_newest_history_entry_wins_over_an_older_one():
    """A retried pull must not read as failed because its first attempt is still in the
    ten-entry history."""
    queue = {
        "active": None,
        "queue": [],
        "history": [{"model": "m", "status": "error"}, {"model": "m", "status": "done"}],
    }
    assert L._pull_queue_state("m", queue, False)["state"] == "done"


def test_idle_is_its_own_answer_and_not_folded_into_done():
    """"Nothing was asked" and "the download finished" are different facts, and a
    follower that treats them alike would report a never-started download as success."""
    assert L._pull_queue_state("m", {}, False)["state"] == "idle"
    assert L._pull_queue_state("m", {}, True)["state"] == "done"


# --------------------------------------------------------------------------- #
#  4. the consumer, driven against the real shapes
# --------------------------------------------------------------------------- #
def _model_step() -> str:
    """The model step of the setup chain, sliced to its own branch so a guard here
    cannot be satisfied by an unrelated line elsewhere in an 18k-line file."""
    src = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    at = src.index('} else if (step.id === "model")')
    return src[at : src.index('say(t("Starting the local AI…"))', at)]


def test_the_chain_stops_when_the_download_never_started():
    """``_installDefaultModel`` catches and toasts its own failures, so a refusal (a
    missing prerequisite, say) is invisible to the chain. The follower then reports
    ``idle`` -- nothing was ever queued -- which is neither error nor cancelled, so the
    chain used to walk straight on and print "Done." over a model that is not coming."""
    step = _model_step()
    assert 'done.state === "idle"' in step, "an unstarted download must not read as success"
    # And it must STOP: reporting the state without returning would still print "Done."
    tail = step.split('done.state === "idle"', 1)[1]
    assert "return;" in tail.split("}", 2)[0] + tail.split("}", 2)[1], (
        "the idle branch must end the chain, not merely mention it"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_setup_chain_can_recognise_the_end_of_the_download():
    """Drives the REAL ``_followJob``, extracted from app.js, against both payloads --
    and against the pre-fix ones, which must still hang. The negative half is what
    makes the positive half mean anything."""
    out = subprocess.run(  # noqa: S603
        [shutil.which("node"), str(_ROOT / "tests" / "default_model_follow_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "can recognise its own end" in out.stdout
