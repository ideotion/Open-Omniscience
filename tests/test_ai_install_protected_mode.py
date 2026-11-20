"""R763 (row 226): the AI install's spawned steps refuse protected mode the way the update does, and the dialog that names the
proxy is shown before the install's network steps every time, whether or not the app is already online.

Every step refused here downloads OUTSIDE this app's process, where neither the socket guard nor the protected-mode proxy
reaches:
- the Ollama installer script
- pip / uv installing vLLM
- the Hugging Face snapshot
- the Ollama daemon's model pull

Each test checks that the refusal comes BEFORE the step starts. The in-process installer download goes through
``guarded_session``, which honours the proxy, so it is not refused.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.llm.install_transport import AI_INSTALL_PROTECTED_REFUSAL
from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]


def _settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def _client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app, base_url="http://127.0.0.1")


def test_the_rule_is_the_updates_own_rule(monkeypatch):
    """One rule, not a copy: protected mode, or settings that cannot be read (R117), refuses both the update and the AI install."""
    from src.llm.install_transport import ai_install_protected

    _settings(monkeypatch)
    assert ai_install_protected() is False
    _settings(monkeypatch, fetch_mode="protected")
    assert ai_install_protected() is True
    st = _settings(monkeypatch)
    st.read_failed = True
    assert ai_install_protected() is True
    import src.safety.settings as settings

    monkeypatch.setattr(
        settings, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("locked"))
    )
    assert ai_install_protected() is True


def test_the_ollama_installer_script_is_refused_in_protected_mode_before_it_is_spawned(
    monkeypatch, tmp_path
):
    import src.llm.installer as inst

    spawned: list = []
    script = tmp_path / "s.sh"
    script.write_text("true\n", encoding="utf-8")
    monkeypatch.setattr(inst, "_validate_staged", lambda p: script)
    monkeypatch.setattr(inst, "_check_online", lambda: None)
    monkeypatch.setattr(inst, "_is_root", lambda: True)
    monkeypatch.setattr(
        inst.subprocess,
        "Popen",
        lambda *a, **k: spawned.append(a) or (_ for _ in ()).throw(AssertionError("spawned")),
    )
    _settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(inst.InstallerUnavailable) as exc:
        list(inst.run_installer(str(script)))
    assert str(exc.value) == AI_INSTALL_PROTECTED_REFUSAL and spawned == []


def test_the_vllm_install_and_the_model_snapshot_are_refused_in_protected_mode(monkeypatch):
    """Both vLLM jobs pass through the one ``_check_online`` before anything is spawned."""
    import src.llm.vllm_lifecycle as vl
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(vl.VllmLifecycleError) as exc:
        vl._check_online()
    assert str(exc.value) == AI_INSTALL_PROTECTED_REFUSAL
    with pytest.raises(vl.VllmLifecycleError) as exc2:
        vl.run_model_download_job(
            None,
            model="org/model",
            runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")),
        )
    # the message, not only the type: VllmUnsupportedError (no vLLM here) subclasses it and is raised just after the check
    assert str(exc2.value) == AI_INSTALL_PROTECTED_REFUSAL
    _settings(monkeypatch)
    vl._check_online()  # standard mode, online: allowed


def test_an_ollama_model_pull_is_refused_in_protected_mode_before_the_request(monkeypatch):
    from src.ingest import clear_kill_switch
    from src.llm.ollama import LLMUnavailable, OllamaClient

    clear_kill_switch()
    c = OllamaClient()
    sent: list = []
    monkeypatch.setattr(
        c._client,
        "stream",
        lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(AssertionError("sent")),
    )
    _settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(LLMUnavailable) as exc:
        list(c.pull("qwen2.5:3b"))
    assert str(exc.value) == AI_INSTALL_PROTECTED_REFUSAL and sent == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/llm/vllm/install", {}),
        ("/api/llm/default-model/install", None),
        ("/api/llm/models/install", {"keys": ["x"]}),
        ("/api/llm/models/pull-custom", {"identifier": "qwen2.5:3b"}),
        ("/api/llm/pull/queue", {"model": "qwen2.5:3b"}),
        ("/api/llm/pull", {"model": "qwen2.5:3b"}),
        ("/api/llm/install/run", {"path": "/nonexistent/install.sh"}),
    ],
)
def test_the_install_routes_answer_409_in_protected_mode_before_any_job_starts(
    monkeypatch, path, body
):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected")
    r = _client().post(path, json=body) if body is not None else _client().post(path)
    assert r.status_code == 409, (path, r.status_code, r.text[:300])
    assert r.json()["detail"] == AI_INSTALL_PROTECTED_REFUSAL


def test_the_egress_window_status_names_protected_mode_for_the_dialog(monkeypatch):
    _settings(monkeypatch, fetch_mode="protected")
    assert _client().get("/api/system/egress-window").json()["ai_install_blocked"] == "protected"
    _settings(monkeypatch)
    assert _client().get("/api/system/egress-window").json()["ai_install_blocked"] is None


def test_the_dialog_is_shown_even_when_the_app_is_already_online_and_protected_mode_is_read_first():
    body = function_body(
        (_ROOT / "src/static/app-core.js").read_text(encoding="utf-8"), "ensureAiEgress"
    )
    # the old early return skipped the dialog that names the proxy whenever the app was online
    assert "if (nm.online) return true" not in body
    blocked = body.index('ai_install_blocked === "protected"')
    shown = body.index("dlg.showModal()")
    assert blocked < shown, (
        "protected mode is refused before the dialog, as the update refuses it before the consent popup"
    )
    assert "Protected mode is on, so the AI install did not start" in body
    # the proxy sentence sits in the dialog for both variants, never inside the offline-only block
    html = (_ROOT / "src/static/index.html").read_text(encoding="utf-8")
    dlg = html.split('<dialog id="ai-egress-consent"', 1)[1].split("</dialog>", 1)[0]
    offline_only = dlg.split('id="ai-egress-offline"', 1)[1].split("</div>\n    <div", 1)[0]
    assert "not through your" in dlg and "not through your" not in offline_only


def test_only_the_setup_chain_skips_its_later_asks_and_a_slow_click_rereads_the_window():
    """R763 asks every time, but the "Set up local AI" chain shows the dialog once for all its steps, as it promises; and an
    OK pressed after the window closed itself while the dialog was open reopens it rather than being refused as airplane mode."""
    core = (_ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    body = function_body(core, "ensureAiEgress")
    assert "opts && opts.alreadyAsked && (online || windowOpen)" in body
    assert body.index('ai_install_blocked === "protected"') < body.index("opts.alreadyAsked"), (
        "a chain is refused too"
    )
    ok = body.split("ok.onclick", 1)[1]
    assert 'api("/api/system/egress-window")' in ok and "_openEgressWindow()" in ok
    chain = (_ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    assert "prepareOllamaInstall({alreadyAsked: true})" in chain
    assert "_installDefaultModel(null, {confirmed: true})" in chain
    settings = (_ROOT / "src/static/app-settings.js").read_text(encoding="utf-8")
    # the only flagged calls (the chain passing it, the two steps taking it); every other caller asks every time
    assert (chain + settings).count("alreadyAsked: ") == 3
    for fn, flag in (
        ("prepareOllamaInstall", "opts.alreadyAsked"),
        ("_installDefaultModel", "opts.confirmed"),
    ):
        assert "{alreadyAsked: !!(opts && " + flag + ")}" in function_body(settings, fn), fn
