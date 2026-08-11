"""The app's own model store is the one the app looks in.

FIELD REPORT (maintainer, 2026-08-11), verbatim: *"I notice ollama models did download
into the /user/home/.ollama folder, yet there is another folder containing ollama models
in /user/home/open-omniscience/data/models/ollama. I'd prefer if all models were in the
same place, preferable in the second folder. Ollama should point by default in this
folder, detect and use those models and download models directly to it."*

THE DEFECT UNDERNEATH was not the split the operator noticed — it was that
``candidate_stores()`` had never learned about the app's own folder. Since 2026-08-04 a
daemon this app spawns is pointed at ``data/models/ollama``, so that is where OUR pulls
land, and the enumerator that answers "where are the models" listed ``$OLLAMA_MODELS``,
``~/.ollama/models`` and the systemd store — never that one. Which made the app blind to
its own downloads in two places that matter:

  * the model BACKUP walks ``default_store()``, so it enumerated ``~/.ollama`` and
    carried NONE of the operator's app-folder models — a silent, complete omission from
    an archive that reports success;
  * ``store_report()`` compared its configured path against that same wrong answer and
    reported a split that did not exist, sending the operator at a migration they did
    not need.

The tests below pin the fix AND its negative space, because promoting the app folder in
that list creates the opposite hazard: with both folders populated the path heuristic now
names the app folder whatever the running daemon is doing, so a report that trusted it
would claim a clean bill of health while every pull went to ``~/.ollama``. That is the
fabricated-success direction and it gets its own guard.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.backup import ollama_models as bk
from src.llm import model_store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """No inherited store choice, and a data dir of our own."""
    for var in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    return tmp_path


def _seed(store: Path, *models: str) -> None:
    """Write a manifest per model AND the blob it references — the shape ``list_models``
    walks and ``migrate_ollama_store`` copies.

    The blob matters, and so does its NAME being a real digest: ``_digest_to_blob``
    rejects anything that is not ``sha256:<hex>``, so a readable-looking placeholder
    yields an empty blob list and a migration test reports zero copies against
    perfectly good code. (It did, twice, while this file was being written.)"""
    for ref in models:
        name, _, tag = ref.partition(":")
        hexv = hashlib.sha256(ref.encode()).hexdigest()
        digest = f"sha256:{hexv}"
        d = store / "manifests" / "registry.ollama.ai" / "library" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / (tag or "latest")).write_text(
            json.dumps({"config": {"digest": digest}, "layers": []}),
            encoding="utf-8",
        )
        (store / "blobs").mkdir(parents=True, exist_ok=True)
        (store / "blobs" / f"sha256-{hexv}").write_bytes(b"x" * 32)


# ---------------------------------------------------------------------------
# 1. Detection knows about the app folder at all.
# ---------------------------------------------------------------------------


def test_the_apps_own_store_is_a_candidate():
    """The whole defect in one assertion."""
    app = model_store.ollama_store()
    assert str(app) in [str(p) for p in bk.candidate_stores()]


def test_an_explicit_operator_choice_still_comes_first(monkeypatch, tmp_path):
    """Someone who put their weights on a second drive did so deliberately. The app
    folder is a DEFAULT, and a default never outranks a stated choice."""
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "elsewhere"))
    cands = [str(p) for p in bk.candidate_stores()]
    assert cands[0] == str(tmp_path / "elsewhere")
    assert bk.default_store() == tmp_path / "elsewhere"


def test_the_app_folder_outranks_the_legacy_one(tmp_path):
    """When both hold models the app folder is the one a daemon we start reads, so it
    is the one to name. Ordering, not mere membership — membership alone would leave
    ~/.ollama winning every tie."""
    cands = [str(p) for p in bk.candidate_stores()]
    assert cands.index(str(model_store.ollama_store())) < cands.index(
        str(tmp_path / "home" / ".ollama" / "models")
    )


def test_models_in_the_app_folder_are_found(tmp_path):
    """THE REPRODUCTION. Before the fix this returned ~/.ollama/models even though the
    app folder held models.

    ~/.ollama IS SEEDED TOO, deliberately. With only the app folder populated the
    assertion is satisfied by ``default_store``'s fallback and passes whether or not
    the candidate list learned anything — a test that cannot fail for the reason it is
    named. Seeding both makes the ANSWER depend on the ordering being fixed."""
    app = model_store.ollama_store()
    _seed(app, "mistral:7b")
    _seed(tmp_path / "home" / ".ollama" / "models", "qwen3.5:0.8b")
    assert bk.default_store() == app


def test_an_empty_machine_targets_the_app_folder(tmp_path):
    """With nothing to find, the value's real job is to be the target a model RESTORE
    writes into — and writing those where our own daemon will not look is how the
    split starts."""
    assert bk.default_store() == model_store.ollama_store()


# ---------------------------------------------------------------------------
# 2. The consequence that was not cosmetic: the backup could not see them.
# ---------------------------------------------------------------------------


def test_the_backup_enumerates_app_folder_models(tmp_path):
    """The expensive half of the defect. ``store_status`` drives the models-backup UI
    and reads ``default_store()``; with the app folder unknown it reported "No Ollama
    models found" — and an archive built on that carries nothing, successfully.

    ~/.ollama holds a DIFFERENT model, so picking the wrong store yields the wrong
    count rather than an empty one: an assertion that only checked "some models were
    found" would pass against the very bug it is named for."""
    _seed(model_store.ollama_store(), "mistral:7b", "qwen3.5:0.8b")
    _seed(tmp_path / "home" / ".ollama" / "models", "legacy:1b")
    st = bk.store_status()
    assert st["store"] == str(model_store.ollama_store())
    assert len(st["models"]) == 2
    assert not st.get("hint"), "models were found, so there is nothing to advise about"


# ---------------------------------------------------------------------------
# 3. Which store is SERVED is measured, and honestly unmeasurable when it is.
# ---------------------------------------------------------------------------


class _Daemon:
    def __init__(self, names):
        self._names = list(names)

    def list_installed(self):
        return list(self._names)


def _serve(monkeypatch, names):
    import src.llm.ollama as ollama_mod

    monkeypatch.setattr(ollama_mod, "OllamaClient", lambda **kw: _Daemon(names))


def test_a_model_only_one_store_holds_settles_it(monkeypatch, tmp_path):
    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "qwen3.5:0.8b")
    _serve(monkeypatch, ["qwen3.5:0.8b"])

    out = model_store.serving_store()
    assert out["certain"] is True
    assert out["store"] == str(legacy), "the daemon lists what only ~/.ollama has"


def test_identical_stores_cannot_be_distinguished(monkeypatch, tmp_path):
    """The negative-space twin. Two stores holding the same models are a distinction
    without a difference, and guessing one would be inventing evidence."""
    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "mistral:7b")
    _serve(monkeypatch, ["mistral:7b"])

    out = model_store.serving_store()
    assert out["certain"] is False and out["store"] is None
    assert "same models" in out["basis"]


def test_a_stopped_daemon_proves_nothing(monkeypatch):
    import src.llm.ollama as ollama_mod

    def _boom(**kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ollama_mod, "OllamaClient", _boom)
    out = model_store.serving_store()
    assert out["certain"] is False and out["store"] is None


def test_an_empty_daemon_proves_nothing(monkeypatch, tmp_path):
    _seed(model_store.ollama_store(), "mistral:7b")
    _serve(monkeypatch, [])
    assert model_store.serving_store()["certain"] is False


def test_a_model_two_other_stores_share_is_not_unique_to_either(monkeypatch, tmp_path):
    """The set-arithmetic trap this was written wrong once: doing it as
    app-vs-the-rest subtracted a store's own keys from the union of the others, which
    also removed the copy that made the model non-unique — so a model present in BOTH
    ~/.ollama and the service store read as unique to each, and the answer became a
    confident contradiction instead of an honest 'cannot tell'."""
    legacy = tmp_path / "home" / ".ollama" / "models"
    service = tmp_path / "svc"
    monkeypatch.setattr(bk, "_LINUX_SERVICE_STORE", service)
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "shared:1b")
    _seed(service, "shared:1b")
    _serve(monkeypatch, ["shared:1b"])

    out = model_store.serving_store()
    assert out["certain"] is False, "shared by two stores, so it identifies neither"


# ---------------------------------------------------------------------------
# 4. The report prefers the measurement — including when it is unwelcome.
# ---------------------------------------------------------------------------


def test_a_foreign_daemon_is_not_reported_as_the_app_folder(monkeypatch, tmp_path):
    """THE GUARD THAT MATTERS. Both stores populated, a daemon serving ~/.ollama: the
    path heuristic now names the app folder (it is first among candidates), and
    trusting it would report a clean bill of health while every pull lands elsewhere.
    The measurement has to win."""
    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "qwen3.5:0.8b")
    _serve(monkeypatch, ["qwen3.5:0.8b"])

    rep = model_store.store_report()["ollama"]
    assert rep["in_app_folder"] is False
    assert rep["detected"] == str(legacy)
    assert rep["on_disk"] == str(model_store.ollama_store()), (
        "the heuristic's own answer is still published, so the disagreement is visible"
    )
    assert rep["basis"].startswith("measured")
    assert "measured, not" in rep["note"]


def test_the_report_lists_every_store_that_holds_models(monkeypatch, tmp_path):
    """The operator noticed the split in a file manager. It belongs in the payload."""
    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "qwen3.5:0.8b")
    _serve(monkeypatch, [])

    rep = model_store.store_report()["ollama"]
    paths = {s["path"]: s for s in rep["stores"]}
    assert set(paths) == {str(model_store.ollama_store()), str(legacy)}
    assert paths[str(model_store.ollama_store())]["is_app_folder"] is True
    assert "more than one place" in rep["split_note"]


def test_one_store_raises_no_split_note(monkeypatch, tmp_path):
    """Negative space: an operator with everything already in one place must not be
    told to tidy up."""
    _seed(model_store.ollama_store(), "mistral:7b")
    _serve(monkeypatch, ["mistral:7b"])
    rep = model_store.store_report()["ollama"]
    assert "split_note" not in rep
    assert rep["in_app_folder"] is True


def test_an_unmeasurable_split_says_so_rather_than_asserting(monkeypatch, tmp_path):
    """When only the heuristic answered, the note may not claim the daemon is reading
    anywhere — it did not ask one."""
    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(legacy, "qwen3.5:0.8b")
    _serve(monkeypatch, [])

    rep = model_store.store_report()["ollama"]
    assert rep["basis"].startswith("inferred")
    assert "could not be measured" in rep["note"]
    assert "measured, not" not in rep["note"]


# ---------------------------------------------------------------------------
# 5. A pull lands in the app folder where that is ours to arrange, and says where
#    it lands where it is not.
# ---------------------------------------------------------------------------


def test_nothing_running_starts_our_own_daemon(monkeypatch):
    """The one case where the app holds the lever: no daemon is serving, so the one it
    starts — pointed at the app folder by launch_env — is the one that pulls."""
    import src.llm.ollama_lifecycle as ol

    calls: list[str] = []
    monkeypatch.setenv("OO_LLM_AUTOSTART", "1")
    monkeypatch.setattr(ol, "is_running", lambda **kw: False)
    monkeypatch.setattr(ol, "start", lambda **kw: (calls.append("start"), {"started": True, "ready": True})[1])

    out = model_store.prepare_ollama_pull()
    assert calls == ["start"]
    assert out["arranged"] is True
    assert out["dest"] == str(model_store.ollama_store())


def test_the_autostart_opt_out_is_honoured(monkeypatch):
    """A change that makes a code path DO something must not ignore the operator who
    said never start a backend behind my back — and it is what keeps a test run from
    leaving a daemon behind."""
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setenv("OO_LLM_AUTOSTART", "0")
    monkeypatch.setattr(ol, "is_running", lambda **kw: False)
    monkeypatch.setattr(ol, "start", lambda **kw: pytest.fail("must not start a daemon"))

    out = model_store.prepare_ollama_pull()
    assert out["arranged"] is False
    assert "OO_LLM_AUTOSTART=0" in out["reason"]


def test_a_foreign_daemons_store_is_reported_not_papered_over(monkeypatch, tmp_path):
    import src.llm.ollama_lifecycle as ol

    legacy = tmp_path / "home" / ".ollama" / "models"
    _seed(model_store.ollama_store(), "mistral:7b")
    _seed(legacy, "qwen3.5:0.8b")
    _serve(monkeypatch, ["qwen3.5:0.8b"])
    monkeypatch.setattr(ol, "is_running", lambda **kw: True)
    monkeypatch.setattr(ol, "owns_daemon", lambda: False)

    out = model_store.prepare_ollama_pull()
    assert out["arranged"] is False
    assert out["dest"] == str(legacy)
    assert "lands there and not in the app folder" in out["reason"]


def test_a_daemon_we_own_needs_no_arranging(monkeypatch):
    import src.llm.ollama_lifecycle as ol

    monkeypatch.setattr(ol, "is_running", lambda **kw: True)
    monkeypatch.setattr(ol, "owns_daemon", lambda: True)
    out = model_store.prepare_ollama_pull()
    assert out["arranged"] is True and out["started_daemon"] is False


def test_the_pull_records_where_the_model_went(monkeypatch, tmp_path):
    """Recorded WITH the pull, because by the time anyone asks, the serving daemon may
    be a different one and 'where did that model go' would have no answer."""
    from src.llm.pull_queue import ModelPullManager

    monkeypatch.setattr(
        model_store,
        "prepare_ollama_pull",
        lambda: {"dest": str(tmp_path / "somewhere"), "arranged": False, "reason": "because"},
    )

    class _C:
        def pull(self, model):
            yield {"status": "success"}

    mgr = ModelPullManager(client_factory=_C)
    mgr.enqueue("mistral:7b")
    for _ in range(200):
        if mgr.status()["history"]:
            break
        import time as _t

        _t.sleep(0.02)
    hist = mgr.status()["history"]
    assert hist and hist[-1]["status"] == "done"
    assert hist[-1]["store"] == str(tmp_path / "somewhere")
    assert hist[-1]["store_note"] == "because"


# ---------------------------------------------------------------------------
# 6. Consolidating actually consolidates.
# ---------------------------------------------------------------------------


def test_the_migration_reads_every_other_store(monkeypatch, tmp_path):
    """A DEFECT THIS CHANGE INTRODUCED, caught before it shipped. The migration used to
    resolve its source through ``default_store()``; promoting the app folder to the
    front of the candidate list made that return the DESTINATION whenever the app
    folder held anything, so source == dest and the button answered "nothing to do" —
    silently inert in the exact split it exists for."""
    app = model_store.ollama_store()
    legacy = tmp_path / "home" / ".ollama" / "models"
    service = tmp_path / "svc"
    monkeypatch.setattr(bk, "_LINUX_SERVICE_STORE", service)
    _seed(app, "mistral:7b")
    _seed(legacy, "qwen3.5:0.8b")
    _seed(service, "granite:3b")

    out = model_store.migrate_ollama_store()
    assert out["ok"] is True
    assert out["copied"] == 2, "one blob from each of the two other stores"
    assert (app / "blobs" / "sha256-1f6ddf3c8505524f0431c7c64b5b6a0c7dfb83c1bea407829ae71c1a89a1336b").is_file()
    assert (app / "blobs" / "sha256-6ccb0a6bef099f9bedb64d46773538bfc1823937a9427a3344a67d9a560ed083").is_file()
    assert {m.rsplit("/", 1)[-1] for m in out["models"]} == {"qwen3.5:0.8b", "granite:3b"}
    assert (legacy / "blobs" / "sha256-1f6ddf3c8505524f0431c7c64b5b6a0c7dfb83c1bea407829ae71c1a89a1336b").is_file(), "a copy leaves the original"


def test_already_consolidated_says_so_without_pretending_to_work(tmp_path):
    """The negative-space twin: nothing to do is a real outcome, and must not be
    reported as a copy that happened."""
    _seed(model_store.ollama_store(), "mistral:7b")
    out = model_store.migrate_ollama_store()
    assert out["ok"] is True and out["copied"] == 0
    assert "already in the app folder" in out["reason"]


def test_one_unreadable_store_does_not_discard_the_copies_that_worked(monkeypatch, tmp_path):
    """A protected service store is a partial result, not a clean run and not a lost
    one — the mid-batch failure shape this project has been bitten by before."""
    app = model_store.ollama_store()
    legacy = tmp_path / "home" / ".ollama" / "models"
    service = tmp_path / "svc"
    monkeypatch.setattr(bk, "_LINUX_SERVICE_STORE", service)
    _seed(legacy, "qwen3.5:0.8b")
    _seed(service, "granite:3b")

    real_list = bk.list_models

    def _list(store):
        # The service store enumerates for the candidate scan, then refuses when the
        # copy tries to read it — the shape a permission wall really has.
        if str(store) == str(service) and getattr(_list, "seen", False):
            return []
        if str(store) == str(service):
            _list.seen = True
        return real_list(store)

    monkeypatch.setattr(bk, "list_models", _list)
    out = model_store.migrate_ollama_store()
    assert out["ok"] is False, "a store we could not read is not a clean run"
    assert out["copied"] == 1, "and the one that worked is still copied"
    assert (app / "blobs" / "sha256-1f6ddf3c8505524f0431c7c64b5b6a0c7dfb83c1bea407829ae71c1a89a1336b").is_file()


def test_a_failure_to_arrange_never_blocks_the_download(monkeypatch):
    """A model the operator asked for downloads even when we could not place it where
    we would prefer. Placement is best-effort; the download is not."""
    from src.llm.pull_queue import ModelPullManager

    def _boom():
        raise RuntimeError("no idea where this goes")

    monkeypatch.setattr(model_store, "prepare_ollama_pull", _boom)

    class _C:
        def pull(self, model):
            yield {"status": "success"}

    mgr = ModelPullManager(client_factory=_C)
    mgr.enqueue("mistral:7b")
    for _ in range(200):
        if mgr.status()["history"]:
            break
        import time as _t

        _t.sleep(0.02)
    hist = mgr.status()["history"]
    assert hist and hist[-1]["status"] == "done", "the pull must survive a placement failure"
    assert "store" not in hist[-1], "and must not claim a destination it never learned"
