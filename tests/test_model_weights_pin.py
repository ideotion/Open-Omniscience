"""The model-weights integrity pin (D6): three states, and a mismatch REFUSES.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IS AND IS NOT TESTABLE HERE. The mechanism is fully testable: which pin applies
to which model, what a mismatch does, and that the download path threads ``revision=``.
The pin VALUE is not -- resolving a real Hugging Face commit SHA needs
``huggingface.co``, which answers this sandbox's proxy ``CONNECT ... 403`` (re-probed
2026-09-07 with ``pypi.org`` 200 as the control). So the pins ship blank and these
tests drive the mechanism with fixture SHAs, exactly as the ``httpfs`` loader's tests
prove verify-before-LOAD against a fixture binary.

THE NEGATIVE SPACE IS THE LOAD-BEARING HALF, and it is where a pin goes wrong:
an unpinned download must not report itself verified, a pin recorded for the model
this app chose must never be inherited by a model an operator typed, and a malformed
override must be REFUSED rather than used (a short SHA or a branch name still moves,
so accepting one publishes "pinned" for a moving target).
"""

from __future__ import annotations

import pytest

from src.llm import weights_pin as W
from src.llm.ollama import MINISTRAL_TAG, MINISTRAL_VLLM_MODEL

_SHA = "0123456789abcdef0123456789abcdef01234567"
_OTHER = "fedcba9876543210fedcba9876543210fedcba98"
_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _no_ambient_pin(monkeypatch):
    """The operator env overrides are process-wide; a developer machine that has one
    set must not silently change what these tests measure."""
    monkeypatch.delenv("OO_MODEL_REVISION", raising=False)
    monkeypatch.delenv("OO_OLLAMA_MODEL_DIGEST", raising=False)


# --------------------------------------------------------------------------- #
#  The three states
# --------------------------------------------------------------------------- #
def test_the_shipped_pins_are_blank_and_say_why() -> None:
    """A blank pin is the honest state, not an oversight -- and the reason travels
    with it, because "not pinned" and "pinned and matched" must never read alike."""
    assert W.HF_REVISION_PINS == {}, (
        "a revision written here is a claim this project verified against the "
        "publisher; no session that cannot reach huggingface.co may write one"
    )
    assert W.OLLAMA_DIGEST_PINS == {}
    pin = W.hf_revision_pin(MINISTRAL_VLLM_MODEL)
    assert pin.pinned is False
    assert "huggingface.co" in pin.basis and "OO_MODEL_REVISION" in pin.basis


def test_an_unpinned_download_is_reported_unverified_never_verified() -> None:
    """The fabrication this closes: a download with nothing to check against
    reporting the same shape as one that was checked."""
    out = W.check_downloaded_revision(MINISTRAL_VLLM_MODEL, f"/c/models--x/snapshots/{_SHA}")
    assert out["pinned"] is False
    assert out["verified"] is False, "no pin means nothing was verified"
    # The revision that ARRIVED is still reported: it is a real fact, and it is what
    # lets an operator notice the bytes moved even before they pin anything.
    assert out["revision"] == _SHA


def test_a_pinned_download_that_matches_is_verified(monkeypatch) -> None:
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    out = W.check_downloaded_revision(MINISTRAL_VLLM_MODEL, f"/c/models--x/snapshots/{_SHA}")
    assert out == {
        "pinned": True,
        "basis": "operator pin (OO_MODEL_REVISION)",
        "revision": _SHA,
        "verified": True,
    }


def test_a_mismatch_refuses_and_names_the_way_out(monkeypatch) -> None:
    """Refuse, per the no-fabricated-security rule -- and the message has to carry the
    deliberate re-pin route, or the operator's only option is to distrust the app."""
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    with pytest.raises(W.PinMismatch) as exc:
        W.check_downloaded_revision(MINISTRAL_VLLM_MODEL, f"/c/models--x/snapshots/{_OTHER}")
    msg = str(exc.value)
    assert _SHA in msg and _OTHER in msg
    assert "OO_MODEL_REVISION" in msg, "the refusal must name the deliberate re-pin route"
    assert "Nothing was" in msg and "deleted" in msg, (
        "a refusal must not imply the operator's several GB were destroyed"
    )


def test_a_pin_that_cannot_be_checked_refuses_rather_than_passing(monkeypatch) -> None:
    """An unreadable answer is not a matching answer. ``snapshot_download`` returning
    a path that is not ``snapshots/<sha>`` means the revision could not be read, and
    reading that as "fine" is the ``.get(key, 0)`` fabrication one level up."""
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    with pytest.raises(W.PinMismatch):
        W.check_downloaded_revision(MINISTRAL_VLLM_MODEL, "/c/models--x/snapshots/main")


# --------------------------------------------------------------------------- #
#  Never inherited, never guessed
# --------------------------------------------------------------------------- #
def test_a_pin_is_never_inherited_by_a_model_the_operator_typed(monkeypatch) -> None:
    """A pin for the model this app chose says nothing about somebody else's bytes.
    Inheriting it would check a custom model against a digest nobody claimed for it --
    and, worse, would report it verified."""
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    pin = W.hf_revision_pin("someone-else/Custom-7B")
    assert pin.pinned is False
    assert "did not choose" in pin.basis
    out = W.check_downloaded_revision("someone-else/Custom-7B", f"/c/models--x/snapshots/{_OTHER}")
    assert out["pinned"] is False and out["verified"] is False


@pytest.mark.parametrize("bad", ["main", "v1.0", _SHA[:7], _SHA.upper() + "ff", ""])
def test_a_malformed_override_is_refused_as_a_pin_not_used(monkeypatch, bad) -> None:
    """A branch name, a tag or a short SHA still MOVES, so accepting one would publish
    "pinned" for exactly the moving target this closes. Refusing leaves the honest
    unpinned state instead of a false claim."""
    monkeypatch.setenv("OO_MODEL_REVISION", bad)
    pin = W.hf_revision_pin(MINISTRAL_VLLM_MODEL)
    assert pin.pinned is False
    if bad:
        assert "refused" in pin.basis or "cannot be reached" in pin.basis


def test_revision_is_read_from_the_download_never_guessed() -> None:
    """``snapshot_download`` returns ``.../snapshots/<commit sha>`` -- the resolved
    revision is a fact the download reports. A path of another shape yields "" rather
    than a guess, because a guessed revision compared against a pin is a fabricated
    verification."""
    assert W.revision_of_snapshot_path(f"/hf/models--org--m/snapshots/{_SHA}") == _SHA
    assert W.revision_of_snapshot_path(f"/hf/models--org--m/snapshots/{_SHA}/") == _SHA
    assert W.revision_of_snapshot_path("/hf/models--org--m/snapshots/main") == ""
    assert W.revision_of_snapshot_path("") == ""
    assert W.revision_of_snapshot_path("/hf/refs/main") == ""


# --------------------------------------------------------------------------- #
#  The Ollama half -- same three states, one extra
# --------------------------------------------------------------------------- #
def test_ollama_unreadable_digest_is_a_third_state_not_a_pass(monkeypatch) -> None:
    """Pinned but unreadable is neither a match nor a mismatch. Reporting it as
    verified would answer an unanswered question with an all-clear."""
    monkeypatch.setenv("OO_OLLAMA_MODEL_DIGEST", _DIGEST)
    out = W.check_pulled_digest(MINISTRAL_TAG, None)
    assert out["pinned"] is True and out["verified"] is False
    assert "could not be checked" in out["reason"]


def test_ollama_digest_mismatch_refuses(monkeypatch) -> None:
    monkeypatch.setenv("OO_OLLAMA_MODEL_DIGEST", _DIGEST)
    assert W.check_pulled_digest(MINISTRAL_TAG, f"sha256:{_DIGEST}")["verified"] is True
    with pytest.raises(W.PinMismatch):
        W.check_pulled_digest(MINISTRAL_TAG, "b" * 64)


def test_ollama_pin_is_not_inherited_by_another_tag(monkeypatch) -> None:
    monkeypatch.setenv("OO_OLLAMA_MODEL_DIGEST", _DIGEST)
    assert W.ollama_digest_pin("someone/other:latest").pinned is False


# --------------------------------------------------------------------------- #
#  THE WIRING, not just the helper (a test of a helper is not a test of its use)
# --------------------------------------------------------------------------- #
def test_the_download_passes_the_pin_and_refuses_a_mismatch(monkeypatch, tmp_path) -> None:
    """Drive the REAL download worker. Both halves are asserted because they fail
    independently: threading ``revision=`` without checking would fetch the right bytes
    and never notice a hub that served others, and checking without threading would
    compare a pin against whatever ``main`` happened to be."""
    from src.llm import vllm_lifecycle as V

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    venv_py = tmp_path / "python"
    venv_py.write_text("", encoding="utf-8")
    monkeypatch.setattr(V, "venv_python", lambda: venv_py)
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    cache = tmp_path
    seen: list[list[str]] = []

    def _runner_at(landed: str):
        def _runner(argv, env=None, should_stop=None):
            seen.append(list(argv))
            rev = cache / f"models--{landed}" / "snapshots" / landed_rev
            rev.mkdir(parents=True, exist_ok=True)
            (rev / "config.json").write_text("{}", encoding="utf-8")
            yield f"__downloaded__ {rev}"
            yield "__exit__ 0"

        return _runner

    class _Ctx:
        stopping = False

        def set_progress(self, **_kw) -> None:
            return None

    # (a) the pin reaches the hub call as `revision=`.
    landed_rev = _SHA
    out = V.run_model_download_job(
        _Ctx(), model=MINISTRAL_VLLM_MODEL, runner=_runner_at(MINISTRAL_VLLM_MODEL.replace("/", "--")),
    )
    assert seen[-1][5] == _SHA, "the pinned revision must be passed to snapshot_download"
    assert "revision=rev" in V._SNAPSHOT_SCRIPT, (
        "the script must USE the argument -- passing it and ignoring it fetches main"
    )
    assert out["integrity"] == {
        "pinned": True,
        "basis": "operator pin (OO_MODEL_REVISION)",
        "revision": _SHA,
        "verified": True,
    }

    # (b) a hub that serves OTHER bytes is refused, by the real worker. A FRESH cache
    # dir, because the run above left a loadable tree and the worker correctly
    # short-circuits on an already-cached model -- an already-present model is not a
    # download, so there is nothing for a download-time pin to judge.
    cache = tmp_path / "fresh"
    cache.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    landed_rev = _OTHER
    with pytest.raises(W.PinMismatch):
        V.run_model_download_job(
            _Ctx(),
            model=MINISTRAL_VLLM_MODEL,
            runner=_runner_at(MINISTRAL_VLLM_MODEL.replace("/", "--")),
        )


def test_an_unpinned_download_is_unchanged_and_says_it_was_not_verified(
    monkeypatch, tmp_path
) -> None:
    """The negative-space twin. An over-eager pin that refused an UNPINNED download
    would break every install that has not pinned -- the far commoner case -- while
    looking conservative, so the no-pin path must still complete AND must not claim a
    verification it did not perform."""
    from src.llm import vllm_lifecycle as V

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(V, "venv_python", lambda: tmp_path / "python")
    (tmp_path / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    def _runner(argv, env=None, should_stop=None):
        assert argv[5] == "", "unpinned passes an EMPTY revision, never a branch name"
        rev = tmp_path / "models--org--m" / "snapshots" / _OTHER
        rev.mkdir(parents=True, exist_ok=True)
        (rev / "config.json").write_text("{}", encoding="utf-8")
        yield f"__downloaded__ {rev}"
        yield "__exit__ 0"

    class _Ctx:
        stopping = False

        def set_progress(self, **_kw) -> None:
            return None

    out = V.run_model_download_job(_Ctx(), model="org/m", runner=_runner)
    assert out["downloaded"] is True
    assert out["integrity"]["pinned"] is False and out["integrity"]["verified"] is False


def test_the_cache_state_discloses_the_revision_but_never_refuses(monkeypatch, tmp_path) -> None:
    """The serve side reports; it does not gate. A cache holding a revision OTHER than
    the pin must still read ``cached: True`` -- refusing there would turn a working
    install into a failed one for everyone who downloaded before pinning."""
    from src.llm import vllm_lifecycle as V

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("OO_MODEL_REVISION", _SHA)
    repo = MINISTRAL_VLLM_MODEL.replace("/", "--")
    rev = tmp_path / f"models--{repo}" / "snapshots" / _OTHER
    rev.mkdir(parents=True)
    (rev / "config.json").write_text("{}", encoding="utf-8")

    st = V.model_cache_state(MINISTRAL_VLLM_MODEL)
    assert st["cached"] is True, "a mismatched cache still SERVES -- disclosure, not a gate"
    assert st["cached_revisions"] == [_OTHER]
    assert st["revision_pinned"] is True
    assert st["revision_matches_pin"] is False, "and the disagreement is stated"


def test_an_unpinned_cache_state_omits_the_match_rather_than_claiming_one(
    monkeypatch, tmp_path
) -> None:
    """``revision_matches_pin`` must be ABSENT when nothing is pinned. A ``False`` there
    would read as "the bytes are wrong" when the truth is "nothing was compared" -- the
    omitted-field-versus-a-zero rule."""
    from src.llm import vllm_lifecycle as V

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo = MINISTRAL_VLLM_MODEL.replace("/", "--")
    rev = tmp_path / f"models--{repo}" / "snapshots" / _OTHER
    rev.mkdir(parents=True)
    (rev / "config.json").write_text("{}", encoding="utf-8")

    st = V.model_cache_state(MINISTRAL_VLLM_MODEL)
    assert st["revision_pinned"] is False
    assert "revision_matches_pin" not in st
