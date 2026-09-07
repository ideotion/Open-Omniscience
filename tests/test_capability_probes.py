"""``X_AVAILABLE`` answers "can it do the job?", not "does it import?" (D7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS FILE EXISTS. ``PQC_AVAILABLE`` was set by a bare import succeeding. When
upstream ``pqcrypto`` 1.0.0 renamed ``generate_keypair`` to ``keygen``, the module still
imported, the flag stayed ``True``, ``pqc_unavailable_but_requested`` -- a property that
exists SPECIFICALLY to say "the operator wants PQC and the library cannot provide it" --
returned ``False``, and the call raised. The honest-degrade machine around it was walked
straight past, and ``availability()`` published a capability claim for a library that
could not sign.

THE NEGATIVE DIRECTION IS THE LOAD-BEARING ONE, and it is what these tests are mostly
about: a module that IMPORTS but LACKS the capability must report unavailable, never
raise. A positive-only fixture passes against the broken guard, which is exactly how the
original defect survived.

AND THE FIXTURES ARE DOUBLES OF REAL FAILURES, not invented ones. ``_Pqc100`` reproduces
the measured 1.0.0 contract (renamed keygen; ``verify`` returns ``None`` for a VALID
signature and raises for an invalid one), and ``_Pqc100VerifyOnly`` isolates the half an
ATTRIBUTE probe cannot see -- every attribute present, and every genuine signature
reported as a forgery. That second one is why the probe is a round trip.
"""

from __future__ import annotations

import pytest

from src.custody import settings as custody_settings
from src.custody import signing, timestamp


# --------------------------------------------------------------------------- #
#  Doubles of real upstream shapes
# --------------------------------------------------------------------------- #
class _Pqc040:
    """The version we ship: verify returns True/False."""

    PUBLIC_KEY_SIZE = 1952

    @staticmethod
    def generate_keypair():
        return (b"P" * 1952, b"S" * 32)

    @staticmethod
    def sign(sk, data):
        return b"SIG" + data

    @staticmethod
    def verify(pk, data, sig):
        return sig == b"SIG" + data


class _Pqc100:
    """1.0.0: ``generate_keypair`` is GONE and verify's contract changed.

    Deliberately NOT a subclass of ``_Pqc040``: inheriting and rebinding the name to
    ``None`` leaves the ATTRIBUTE present, which raises a TypeError instead of the
    AttributeError the real absence produces -- a double that describes a library
    upstream never shipped. The measured shape is: the name is absent.
    """

    PUBLIC_KEY_SIZE = 1952

    @staticmethod
    def keygen():
        return (b"P" * 1952, b"S" * 32)

    @staticmethod
    def sign(sk, data):
        return b"SIG" + data

    @staticmethod
    def verify(pk, data, sig):
        if sig != b"SIG" + data:
            raise ValueError("InvalidSignatureError")
        return None


class _Pqc100VerifyOnly(_Pqc040):
    """The half an ATTRIBUTE probe cannot see: every name present, verify inverted.

    This is the dangerous one. It never reaches the renamed function, so an install
    whose keys already exist fails SILENTLY -- every genuine ML-DSA signature read as a
    forgery, in the tamper-evidence path.
    """

    @staticmethod
    def verify(pk, data, sig):
        if sig != b"SIG" + data:
            raise ValueError("InvalidSignatureError")
        return None


class _PqcNoSize(_Pqc040):
    PUBLIC_KEY_SIZE = 0


# --------------------------------------------------------------------------- #
#  PQC: the negative directions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mod", "needle"),
    [
        (None, "not installed"),
        (_Pqc100, "AttributeError"),
        (_Pqc100VerifyOnly, "did not confirm"),
        (_PqcNoSize, "PUBLIC_KEY_SIZE"),
    ],
    ids=["absent", "1.0.0-renamed", "1.0.0-verify-inverted", "no-key-size"],
)
def test_a_library_that_cannot_sign_reports_unavailable_and_never_raises(mod, needle) -> None:
    ok, reason = signing._probe_mldsa(mod)
    assert ok is False, "a build that cannot complete the round trip is NOT available"
    assert needle in reason, f"the reason must place the blame; got {reason!r}"


def test_the_attribute_probe_would_have_missed_the_dangerous_case() -> None:
    """The claim the round trip is FOR, asserted rather than left in a comment.

    An attribute probe over the four names this module uses passes ``_Pqc100VerifyOnly``
    outright -- every name is present -- while the round trip refuses it. If this ever
    stops holding, the round trip has stopped being stronger than the cheap check and
    the reason for its cost is gone.
    """
    names = ("generate_keypair", "sign", "verify", "PUBLIC_KEY_SIZE")
    assert all(getattr(_Pqc100VerifyOnly, n, None) is not None for n in names), (
        "the fixture must have every attribute, or it is not the case being described"
    )
    assert signing._probe_mldsa(_Pqc100VerifyOnly)[0] is False


def test_a_working_library_is_reported_available() -> None:
    """The positive twin. Without it, a probe that returned False unconditionally would
    pass every test above -- a fabricated failure, exactly as dishonest as the
    fabricated pass being fixed."""
    ok, reason = signing._probe_mldsa(_Pqc040)
    assert ok is True and "round trip verified" in reason


def test_the_probe_and_the_production_verifier_share_one_implementation() -> None:
    """They must agree by construction, not by two copies staying in step: a probe that
    tested a contract the shipped call site does not use would certify nothing."""
    assert signing._mldsa_verify(_Pqc040, b"P", b"data", b"SIGdata") is True
    assert signing._mldsa_verify(_Pqc040, b"P", b"data", b"nope") is False
    # A raising verify is absorbed the way _verify_mldsa absorbs it -- False, not a crash.
    assert signing._mldsa_verify(_Pqc100VerifyOnly, b"P", b"data", b"nope") is False


# --------------------------------------------------------------------------- #
#  OTS: the same class, the same shape
# --------------------------------------------------------------------------- #
def test_the_ots_probe_reports_a_reason_either_way() -> None:
    ok, reason = timestamp._probe_ots()
    assert isinstance(ok, bool)
    assert reason, "a flag without a reason cannot tell 'absent' from 'present but broken'"
    if ok:
        assert "round trip verified" in reason
    else:
        assert "opentimestamps" in reason or ":" in reason


def _ots_importable() -> bool:
    """The SOURCE OF TRUTH for "is the library here", which is NOT ``OTS_AVAILABLE``.

    Gating on ``OTS_AVAILABLE`` would key a skip on the very thing under test: a probe
    that wrongly reported unavailable would silently SKIP the tests that exist to catch
    that, which is how the mutation removing the attestation line survived the first
    matrix. Keyed on the import instead.
    """
    try:
        import opentimestamps  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@pytest.mark.skipif(not _ots_importable(), reason="the [timestamping] extra is absent")
def test_an_installed_opentimestamps_is_reported_AVAILABLE() -> None:
    """THE FABRICATED-FAILURE TWIN, and it earned its keep on the first run of the probe
    it guards: the round trip originally serialized an EMPTY timestamp, which the library
    refuses by name -- so every install that HAD opentimestamps would have been told it
    did not. A fabricated failure is exactly as dishonest as the fabricated pass this
    whole slice is fixing, and it is easier to believe, because it looks like the library
    being broken rather than the probe."""
    ok, reason = timestamp._probe_ots()
    assert ok is True, f"opentimestamps is installed but the probe refuses it: {reason}"
    assert timestamp.OTS_AVAILABLE is True


@pytest.mark.skipif(not _ots_importable(), reason="the [timestamping] extra is absent")
def test_the_ots_probe_makes_no_network_call(monkeypatch) -> None:
    """A capability probe must never egress. Submitting to a calendar is real network
    traffic under explicit consent, and a probe that needed it could not tell a missing
    library from a closed port. Asserted by making the calendar unusable."""

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("the capability probe must not touch a calendar")

    monkeypatch.setattr(timestamp, "RemoteCalendar", _Boom)
    assert timestamp._probe_ots()[0] is True


# --------------------------------------------------------------------------- #
#  The payload: the reason reaches a reader
# --------------------------------------------------------------------------- #
def test_availability_publishes_the_reason_beside_the_flag() -> None:
    """``availability()``'s docstring promises "what the build can ACTUALLY do". The
    reason is what makes a False actionable: a missing extra and a broken version are
    opposite problems behind one boolean."""
    out = custody_settings.availability()
    assert set(out) >= {"pqc_available", "pqc_reason", "ots_available", "ots_reason"}
    assert out["pqc_available"] is signing.PQC_AVAILABLE
    assert out["pqc_reason"] == signing.PQC_REASON and out["pqc_reason"]
    assert out["ots_reason"] == timestamp.OTS_REASON and out["ots_reason"]


# --------------------------------------------------------------------------- #
#  The DERIVATION of the module-level flag -- which needs a broken library
# --------------------------------------------------------------------------- #
#
# THIS SHAPE IS A MUTATION-MATRIX FINDING, recorded so it is not "simplified" back.
# The obvious assertion is `PQC_AVAILABLE is _probe_mldsa(_mldsa)[0]`, and it survives
# the mutation that reverts the flag to `_mldsa is not None`: with a WORKING pqcrypto
# installed, an import probe and a round-trip probe agree BY CONSTRUCTION, so the
# assertion compares two values that cannot differ. The discriminating case is a module
# that IMPORTS and CANNOT WORK, which only exists if one is injected -- and it is
# injected in a SUBPROCESS, because reloading a module every custody test imports is
# process-global state this suite would then carry.
_DERIVATION_PROBE = """
import sys, types
mod = types.ModuleType("pqcrypto.sign.ml_dsa_65")
mod.PUBLIC_KEY_SIZE = 1952
mod.generate_keypair = lambda: (b"P" * 1952, b"S" * 32)
mod.sign = lambda sk, data: b"SIG" + data
# The measured pqcrypto 1.0.0 contract: None for a VALID signature.
def _verify(pk, data, sig):
    if sig != b"SIG" + data:
        raise ValueError("InvalidSignatureError")
    return None
mod.verify = _verify
pkg = types.ModuleType("pqcrypto"); sign_pkg = types.ModuleType("pqcrypto.sign")
sign_pkg.ml_dsa_65 = mod
sys.modules.update({"pqcrypto": pkg, "pqcrypto.sign": sign_pkg,
                    "pqcrypto.sign.ml_dsa_65": mod})
from src.custody import signing
print("PQC_AVAILABLE=%r" % (signing.PQC_AVAILABLE,))
"""

_OTS_DERIVATION_PROBE = """
import sys, types
# A module that IMPORTS every name timestamp.py binds and cannot build a proof.
def _blow(*a, **k):
    raise TypeError("upstream changed this constructor")
for name, attrs in [
    ("opentimestamps", {}),
    ("opentimestamps.calendar", {"RemoteCalendar": object}),
    ("opentimestamps.core", {}),
    ("opentimestamps.core.notary",
     {"BitcoinBlockHeaderAttestation": object, "PendingAttestation": _blow}),
    ("opentimestamps.core.op", {"OpSHA256": object}),
    ("opentimestamps.core.serialize",
     {"BytesDeserializationContext": object, "BytesSerializationContext": object}),
    ("opentimestamps.core.timestamp",
     {"DetachedTimestampFile": object, "Timestamp": lambda d: types.SimpleNamespace(
         msg=d, attestations=set())}),
]:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
from src.custody import timestamp
print("OTS_AVAILABLE=%r" % (timestamp.OTS_AVAILABLE,))
"""


def _run_probe(source: str) -> str:
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", source], capture_output=True, text=True, cwd=str(root), timeout=120
    )
    assert out.returncode == 0, f"probe subprocess failed: {out.stderr[-800:]}"
    return out.stdout.strip()


def test_a_library_that_imports_but_cannot_sign_makes_the_FLAG_false() -> None:
    """The whole ruling, at the level that matters: the module-level flag, derived from
    a library that imports perfectly and reports every genuine signature as a forgery.
    An import-derived flag publishes True here -- that IS the shipped 2026-08-20 defect."""
    assert _run_probe(_DERIVATION_PROBE) == "PQC_AVAILABLE=False"


def test_an_opentimestamps_that_imports_but_cannot_build_a_proof_makes_the_FLAG_false() -> None:
    assert _run_probe(_OTS_DERIVATION_PROBE) == "OTS_AVAILABLE=False"
