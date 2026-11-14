"""
Honest hybrid (classical + post-quantum) signatures for chain of custody.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the signing primitive behind the custody log and (optionally) evidence
bundles. It combines a classical **Ed25519** signature with a post-quantum
**ML-DSA** (FIPS 204, the standardised successor to CRYSTALS-Dilithium)
signature so that a recorded custody chain stays verifiable even against a future
adversary with a quantum computer ("harvest now, decrypt later").

The design follows two non-negotiables of this project (PRODUCT_SYNTHESIS §3):

1. **Honest labels.** A signature is labelled with *exactly* the algorithms that
   were actually used. If the post-quantum library is not installed we sign with
   Ed25519 alone and label the result ``"ed25519"`` -- never ``"hybrid"``. The
   code can never claim quantum resistance it did not produce.

2. **Hybrid means AND, not OR.** A signature labelled ``"hybrid"`` verifies only
   if **both** the Ed25519 *and* the ML-DSA components verify. (A naive scheme
   that accepts *either* component is worthless: once Ed25519 is broken by a
   quantum adversary, a forged Ed25519 signature alone would pass even though a
   sound ML-DSA signature is attached.) A verifier that cannot check the
   post-quantum half returns a clear *failure*, never a silent pass.

Private keys live under the data dir. They are encrypted at rest when a
passphrase is provided (``OO_KEY_PASSPHRASE``); without one they are written
0600 in the clear and ``key_protection`` reports ``"plaintext-0600"`` so the
operator is never misled about how their keys are stored.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from src.custody import keyfile
from src.monitoring.secret_scrub import env_secret, passphrase_bytes, record_text

# --------------------------------------------------------------------------- #
# Post-quantum backend (optional, import-guarded)
# --------------------------------------------------------------------------- #
# Current pqcrypto (>=0.3) exposes the standardised ML-DSA family. We default to
# ML-DSA-65 (NIST security category 3, ~AES-192) to mirror the original
# "Dilithium3" intent. Older "dilithium3" module names are gone, so we bind to
# the real, current API only.
_MLDSA_VARIANT = "ml_dsa_65"
try:  # pragma: no cover - availability is environment-dependent
    from pqcrypto.sign import ml_dsa_65 as _mldsa  # type: ignore
except Exception:  # noqa: BLE001 - any import failure means "no PQC here"
    _mldsa = None  # type: ignore


def _mldsa_verify(mod: object, pub: bytes, data: bytes, sig: bytes) -> bool:
    """Verify exactly the way :func:`_verify_mldsa` does, in ONE place.

    Both the capability probe below and the production verifier call this, so the
    probe can never test a contract the shipped code does not use -- the two would
    otherwise drift and the probe would certify a call site it never exercised.
    """
    try:
        return bool(mod.verify(pub, data, sig))  # type: ignore[attr-defined]
    except (ValueError, TypeError):
        return False


def _probe_mldsa(mod: object) -> tuple[bool, str]:
    """CAN IT SIGN? -- not "does it import?". Returns ``(available, reason)``.

    THE DEFECT THIS CLOSES (D7, ruled from the 2026-08-20 near-miss). ``PQC_AVAILABLE``
    used to be set by the bare import succeeding, which answers a different question.
    When upstream ``pqcrypto`` 1.0.0 renamed ``generate_keypair`` to ``keygen`` the
    module still imported perfectly: the flag stayed ``True``,
    :attr:`HybridSigner.pqc_unavailable_but_requested` -- a property that exists
    SPECIFICALLY to say "the operator wants PQC and the library cannot provide it" --
    returned ``False``, and the call raised at the call site. A whole honest-degrade
    machine, walked straight past. Worse, ``custody/settings.availability()`` published
    ``{"pqc_available": true}`` for a library that cannot sign, under a docstring
    promising to "report what the BUILD can actually do" -- a fabricated capability
    claim, which is the one thing the non-negotiables forbid outright.

    AN ATTRIBUTE PROBE IS NOT ENOUGH, and that is the half worth writing down. 1.0.0's
    ``verify`` returns ``None`` for a VALID signature and raises for an invalid one, so
    every attribute this module touches is PRESENT while ``bool(verify(...))`` reports
    every genuine signature as a verification FAILURE -- silently, in the tamper-evidence
    path, on an install whose keys already exist and which therefore never reaches the
    renamed function at all. So this is a ROUND TRIP through the real call sites
    (keygen -> sign -> verify-true -> verify-false), and a library that cannot complete it
    is UNAVAILABLE, which is precisely the state the degrade path was built for.

    IT NEVER RAISES. That is the load-bearing property and the negative direction the
    tests pin: a module that imports but cannot do the job must REPORT unavailable, not
    blow up inside the caller that trusted the flag.

    It runs at import, deliberately: it is pure CPU (no I/O, no network, no thread),
    MEASURED at 1.6 ms for the ML-DSA-65 round trip and 0.02 ms for the OTS one on this
    machine (a figure, not a guess -- the recorded rule against writing a quantitative
    claim without counting), and this module is imported by the custody paths rather
    than by boot. A lazy flag would break every existing
    ``monkeypatch.setattr(signing, "PQC_AVAILABLE", ...)`` and every
    ``from ... import PQC_AVAILABLE`` reader for no honesty gain.
    """
    if mod is None:
        return False, "pqcrypto is not installed (the [pqc] extra)"
    probe = b"open-omniscience ml-dsa capability probe"
    try:
        if int(getattr(mod, "PUBLIC_KEY_SIZE", 0)) <= 0:
            return False, "PUBLIC_KEY_SIZE is missing or is not a positive length"
        pk, sk = mod.generate_keypair()  # type: ignore[attr-defined]
        sig = mod.sign(sk, probe)  # type: ignore[attr-defined]
        if not _mldsa_verify(mod, pk, probe, sig):
            return False, (
                "verify() did not confirm a signature this build had just produced "
                "(pqcrypto 1.0.0 returns None here, which reads as a forgery)"
            )
        if _mldsa_verify(mod, pk, probe + b"!", sig):
            return False, "verify() accepted a signature over different data"
    except Exception as exc:  # noqa: BLE001 - the whole point is that NOTHING escapes
        return False, record_text(exc, limit=160, typed=True)
    return True, f"{_MLDSA_VARIANT} round trip verified (keygen, sign, verify true and false)"


#: Set from the CAPABILITY, never from the import. ``PQC_REASON`` travels with it so a
#: report can place the blame -- "not installed" and "installed but cannot sign" call for
#: opposite actions and must not share one boolean.
PQC_AVAILABLE, PQC_REASON = _probe_mldsa(_mldsa)


class SigningError(RuntimeError):
    """Raised when signing cannot proceed (e.g. a requested algorithm is absent)."""


# --------------------------------------------------------------------------- #
# Key paths / at-rest protection
# --------------------------------------------------------------------------- #


def _keys_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "keys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _passphrase() -> bytes | None:
    # OO_KEY_PASSPHRASE wins when set; otherwise THE database passphrase wraps
    # the signing keys too (design D6: one secret, no plaintext stragglers).
    # A passphrase that cannot be written as UTF-8 (an environment variable of
    # bytes that are not UTF-8 reads as a lone surrogate) is refused with fixed
    # words: Python's own error names the character and its place.
    p = env_secret("OO_KEY_PASSPHRASE")
    if not p:
        from src.database.connect import get_passphrase

        p = get_passphrase()
    return passphrase_bytes(p, error=SigningError) if p else None


#: How many scrypt derivations may run at once in this process: as many as the machine has cores to run them on.
#: Each one holds 32 MiB for its 80 ms, and a burst of constructions (the collector opens one custody log per
#: worker at the start of a pass) used to hold them all at the same time, 1.3 GiB for fifty, with no gain in wall
#: time because a derivation is CPU-bound. The bound comes from the machine, not from a number chosen here.
_KDF_SLOTS = threading.BoundedSemaphore(
    max(1, getattr(os, "process_cpu_count", os.cpu_count)() or 1)
)


def _derive(salt: bytes, passphrase: bytes) -> bytes:
    """The AES key for a wrapped file: scrypt (N = 2**15, r = 8, p = 1) of the passphrase, at most one per core at a time."""
    with _KDF_SLOTS:
        return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)


def _wrap(plaintext: bytes, passphrase: bytes) -> bytes:
    """Encrypt key material with AES-256-GCM under a scrypt-derived key.

    Layout: ``salt(16) || nonce(12) || ciphertext+tag``. scrypt parameters are
    embedded implicitly (fixed, conservative) -- this is local at-rest protection
    for a single user, not an interoperable key format.
    """
    salt = os.urandom(16)
    key = _derive(salt, passphrase)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return salt + nonce + ct


def _mldsa_plain_len() -> int:
    """The length of an UNWRAPPED ML-DSA key file (public key + secret key), read from a throwaway pair
    generated now and never stored, so no size constant of the library has to be trusted. Only the failed-unwrap
    path asks (1.6 ms measured for a whole ML-DSA round trip)."""
    pk, sk = _mldsa.generate_keypair()
    return len(pk) + len(sk)


def _unwrap(blob: bytes, passphrase: bytes) -> bytes:
    salt, nonce, ct = blob[:16], blob[16:28], blob[28:]
    return AESGCM(_derive(salt, passphrase)).decrypt(nonce, ct, None)


# The Ed25519 key FILE comes in three forms, told apart by what is in it, never by a flag:
#   "wrapped"   the 32 key bytes under ``_wrap`` (scrypt, then AES-256-GCM): what is written when a passphrase is held
#   "plaintext" a PKCS8 PEM in the clear: what is written with no passphrase, and what a store had before it got one
#   "pkcs8"     a PKCS8 PEM under ``BestAvailableEncryption``: what a store with a passphrase wrote before the wrap.
#               PKCS8 derives its key with PBKDF2-HMAC-SHA256 at 2048 rounds, 0.3 ms a guess, which made this file the
#               cheapest place to test a guess at the database passphrase (SQLCipher prices one at 170 ms).
_PEM_START = b"-----BEGIN"


def seal_ed25519_key(key: Ed25519PrivateKey, passphrase: bytes | None) -> bytes:
    """The bytes of the Ed25519 key file: the wrap of the raw key under a passphrase, else the plaintext PEM.

    Public for the same reason as :func:`parse_ed25519_key`: ``passphrase`` is the one given, not the held one."""
    if passphrase:
        seed = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        return _wrap(seed, passphrase)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _ed25519_public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


def parse_ed25519_key(
    path: Path, raw: bytes, passphrase: bytes | None
) -> tuple[Ed25519PrivateKey, str]:
    """``(key, form)`` from the bytes of an Ed25519 key file (forms above); never writes.

    Public because a restore re-wraps the files it brings (R454): it passes the passphrase the file was
    wrapped under, which this reads from nowhere else (no environment, no held passphrase).

    Every refusal is a :class:`SigningError` that names the file and the cause and carries no
    passphrase and no key byte. None of them is ever a reason to make another key: a new key would
    orphan every signature already made.
    """
    if not raw.strip():
        raise SigningError(
            f"{path.name} is empty (a creation that was cut short). Nothing is replaced for you: "
            "delete it and a new key is made the next time one is needed."
        )
    form = "wrapped"
    pem: object = None
    if _PEM_START in raw:
        # anywhere, not only first: OpenSSL writes a "Bag Attributes" preamble and an editor can add
        # a byte-order mark. A wrapped blob is random bytes, which hold these ten with a chance of
        # about 2**-72.
        form = "plaintext"
        unreadable = False
        try:
            pem = serialization.load_pem_private_key(raw, password=None)
        except TypeError:
            form = "pkcs8"  # a PEM that is itself password-protected
        except ValueError:
            unreadable = True  # truncated, or a PEM of another kind (a public key, a certificate)
        if unreadable:
            raise SigningError(
                f"{path.name} is not a readable PEM private key (damaged, cut short, or another kind "
                "of key file). Nothing is replaced for you: move it aside to have a new key made "
                "(signatures made by the old key stay verifiable against its public key)."
            )
        if form == "pkcs8":
            if not passphrase:
                raise SigningError(
                    f"the signing key {path.name} is wrapped but no passphrase is held "
                    "(unlock the app first)"
                )
            try:
                pem = serialization.load_pem_private_key(raw, password=passphrase)
            except Exception:  # noqa: BLE001 - a wrong passphrase and a damaged file end here alike
                pem = None
            if pem is None:
                raise SigningError(_NOT_OPENED.format(name=path.name))
        if not isinstance(pem, Ed25519PrivateKey):
            raise SigningError(
                f"{path.name} does not hold an Ed25519 private key (found {type(pem).__name__}); "
                "this signer only uses Ed25519."
            )
        return pem, form
    if not passphrase:
        raise SigningError(
            f"the signing key {path.name} is wrapped but no passphrase is held "
            "(unlock the app first)"
        )
    key: Ed25519PrivateKey | None = None
    try:
        key = Ed25519PrivateKey.from_private_bytes(_unwrap(raw, passphrase))
    except Exception:  # noqa: BLE001 - the tag check, a short blob and a wrong-length seed all end here
        key = None
    if key is None:
        raise SigningError(_NOT_OPENED.format(name=path.name))
    return key, form


_NOT_OPENED = (
    "the signing key {name} could not be opened with the passphrase held (a wrong "
    "passphrase, a backup restored from another install that wrapped it under its own, or a "
    "damaged file). Nothing was replaced; restore the passphrase it was wrapped under, or move "
    "the file aside to have a new key made (signatures made by the old key stay verifiable "
    "against its public key)."
)


def parse_mldsa_key(path: Path, raw: bytes, passphrase: bytes | None) -> tuple[bytes, bytes, str]:
    """``(public key, secret key, form)`` from the bytes of an ML-DSA key file; never writes.

    ``form`` is ``"wrapped"`` (``_wrap`` of public + secret key) or ``"plaintext"`` (public + secret key as
    they are: what a store had before it got a passphrase, or has with none). Public for the restore that
    re-wraps the files it brings (R454), so ``passphrase`` is the one given, never the held one, and the
    two refusals are the ones :class:`HybridSigner` has always raised. ``path`` is unused today; it is kept
    so this and :func:`parse_ed25519_key` take the same arguments.
    """
    if passphrase:
        try:
            data = _unwrap(raw, passphrase)
            form = "wrapped"
        except Exception:  # noqa: BLE001 - GCM tag check failed
            # A failed tag check proves only that this blob is not WRAPPED UNDER THIS
            # passphrase: it is equally what a wrong passphrase and an altered file look
            # like (``_wrap`` writes no magic prefix). A legacy plaintext key from before
            # the passphrase existed is told apart by its LENGTH, which is exactly
            # public key + secret key; anything else is refused, never used as a key
            # (audit 0.5.0 A-018: the still-wrapped blob used to be split into a
            # garbage key pair and signed with, silently).
            if len(raw) != _mldsa_plain_len():
                raise SigningError(
                    "the ML-DSA custody key could not be unwrapped with the passphrase held "
                    "(a wrong passphrase, or the key file was altered)"
                ) from None
            data = raw
            form = "plaintext"
    else:
        # No passphrase held: only a blob of exactly the plain key length is a plaintext
        # key; a longer one is still wrapped, and splitting it would sign with garbage
        # (the same defect as above, audit 0.5.0 A-018, read-response).
        if len(raw) != _mldsa_plain_len():
            raise SigningError(
                "the ML-DSA custody key is wrapped but no passphrase is held (unlock the app first)"
            )
        data = raw
        form = "plaintext"
    pk_len = _mldsa.PUBLIC_KEY_SIZE
    return data[:pk_len], data[pk_len:], form


def seal_mldsa_key(pk: bytes, sk: bytes, passphrase: bytes | None) -> bytes:
    """The bytes of the ML-DSA key file: the wrap of public + secret key under ``passphrase``, else as they are."""
    data = pk + sk
    return _wrap(data, passphrase) if passphrase else data


# --------------------------------------------------------------------------- #
# Hybrid signer
# --------------------------------------------------------------------------- #


@dataclass
class PublicIdentity:
    """The public half of a signer -- everything a third party needs to verify."""

    ed25519_pub: str  # hex
    ml_dsa_variant: str | None  # e.g. "ml_dsa_65" or None
    ml_dsa_pub: str | None  # hex or None

    def to_dict(self) -> dict:
        return {
            "ed25519_pub": self.ed25519_pub,
            "ml_dsa_variant": self.ml_dsa_variant,
            "ml_dsa_pub": self.ml_dsa_pub,
        }


class HybridSigner:
    """Persistent Ed25519 (+ optional ML-DSA) signer.

    Loads existing keys or creates them on first use. The post-quantum key is
    only created/used when ``pqcrypto`` is importable; otherwise the signer is
    Ed25519-only and says so via :pyattr:`is_hybrid`.
    """

    def __init__(
        self,
        ed25519_path: Path | None = None,
        mldsa_path: Path | None = None,
        *,
        use_pqc: bool = True,
    ):
        # ``use_pqc`` is the operator's *preference* (see src/custody/settings).
        # When False we sign Ed25519-only and label the result "ed25519" even if
        # the post-quantum library is installed -- the toggle can suppress PQC but
        # the label can never claim quantum resistance that was not produced.
        self._use_pqc = use_pqc
        self._ed_path = ed25519_path or (_keys_dir() / "custody_ed25519.pem")
        self._mldsa_path = mldsa_path or (_keys_dir() / "custody_ml_dsa_65.key")
        for p in (self._ed_path, self._mldsa_path):
            p.parent.mkdir(parents=True, exist_ok=True)
        self._pp = _passphrase()
        # what a key file still holds when a passphrase IS held but the file was not (or could not be) wrapped:
        self._legacy_plain = False  # a key readable in the clear
        self._ed_pkcs8 = False  # the Ed25519 key under PKCS8's cheap KDF (see parse_ed25519_key)
        before = self._file_states(both=True)
        self._ed_key = self._load_or_create_ed25519()
        self._mldsa_pk, self._mldsa_sk = self._load_or_create_mldsa()
        after = self._file_states(both=True)
        # A file that changed while it was being loaded (replaced by another process, or wrapped in place by this one)
        # may not hold what was loaded: recorded as unknown, so the first check reloads and settles it.
        seen = tuple(a if a == b else (0, 0, 0, 0) for a, b in zip(after, before, strict=True))
        self._files_seen = seen if self._mldsa_sk is not None else seen[:1]

    def _file_states(self, *, both: bool = False) -> tuple[tuple[int, int, int, int] | None, ...]:
        """Which key files this signer reads, and which state of each: the Ed25519 file, and the ML-DSA file when the
        post-quantum half is in use, or ``both`` (``None`` for a file that is not there)."""
        paths = [self._ed_path] + ([self._mldsa_path] if both or self._mldsa_sk is not None else [])
        states: list[tuple[int, int, int, int] | None] = []
        for p in paths:
            try:
                states.append(keyfile.identity(os.stat(p)))
            except OSError:
                states.append(None)
        return tuple(states)

    def key_file_changed(self) -> bool:
        """Whether a key file now holds another file than the one this signer loaded (re-created or replaced).

        A long-lived signer would otherwise go on signing with a key the folder no longer holds while a fresh one signs
        with the new key, and a custody log written by both would change key back and forth. A file that is not there
        reads as NOT changed: reloading would create a new key, and a folder moved aside for a moment and put back would
        leave two rotation records and an orphan key behind. A wrap in place of the same key reads as changed; reloading
        it then finds the same key."""
        now = self._file_states()
        return None not in now and now != self._files_seen

    def reloaded(self) -> HybridSigner:
        """A signer loaded afresh from the same key files, with the same post-quantum preference."""
        return HybridSigner(self._ed_path, self._mldsa_path, use_pqc=self._use_pqc)

    # -- properties -------------------------------------------------------- #
    @property
    def is_hybrid(self) -> bool:
        return self._mldsa_sk is not None

    @property
    def pqc_requested(self) -> bool:
        """Whether post-quantum signing was *asked for* (regardless of availability)."""
        return self._use_pqc

    @property
    def pqc_unavailable_but_requested(self) -> bool:
        """True when the operator wants PQC but the library cannot provide it."""
        return self._use_pqc and not PQC_AVAILABLE

    @property
    def key_protection(self) -> str:
        # The FILE's actual state, never the environment's wish: a legacy
        # plaintext key stays reported as plaintext until it is re-wrapped.
        if not self._pp or self._legacy_plain:
            return "plaintext-0600"
        if self._ed_pkcs8:
            # encrypted, but not under the scrypt wrap: it could not be re-wrapped this time
            return "pkcs8-pbkdf2"
        return "aes256gcm-scrypt"

    # -- Ed25519 ----------------------------------------------------------- #
    def _load_or_create_ed25519(self) -> Ed25519PrivateKey:
        """Load the Ed25519 key, creating it once if there is none, wrapped under the passphrase held.

        With a passphrase held the file is the ``_wrap`` of the raw key (scrypt, AES-256-GCM); with
        none it is a plaintext PKCS8 PEM, 0600 from its first byte. A key written in either older
        form (plaintext, or PKCS8-encrypted) is wrapped in place the first time it is loaded under
        a passphrase: the SAME key, read back and compared before it replaces anything
        (:func:`src.custody.keyfile.replace_in_place`), so a failure leaves the file as it was and
        ``key_protection`` says what the file really holds.
        """
        path = self._ed_path
        try:
            raw, seen = keyfile.read_settled(path)
        except FileNotFoundError:
            key = Ed25519PrivateKey.generate()
            try:
                keyfile.create_new(path, seal_ed25519_key(key, self._pp))
            except FileExistsError:
                # another caller created it between our look and our create: ONE key, theirs, and it is
                # judged like any file found there (it may be plaintext, made by a caller with no passphrase)
                raw, seen = keyfile.read_settled(path)
            else:
                return key
        key, form = parse_ed25519_key(path, raw, self._pp)
        if self._pp and form != "wrapped":
            passphrase = self._pp

            def same_key(blob: bytes) -> None:
                back, _form = parse_ed25519_key(path, blob, passphrase)
                if _ed25519_public_bytes(back) != _ed25519_public_bytes(key):
                    raise SigningError("the wrapped copy does not hold the same key")

            if not keyfile.replace_in_place(
                path, lambda: seal_ed25519_key(key, passphrase), same_key, seen, "signing key"
            ):
                # Not replaced by this caller: say what the file holds NOW, not what it held when this
                # caller read it (another caller may have wrapped it in the meantime).
                form = self._form_now(path, form, key)
                if form == "plaintext":
                    self._legacy_plain = True
                elif form == "pkcs8":
                    self._ed_pkcs8 = True
        return key

    def _form_now(self, path: Path, read_as: str, key: Ed25519PrivateKey) -> str:
        """The form the Ed25519 file holds at this moment, when it still holds THIS key.

        ``read_as`` (the answer already given) when the file cannot be read or opened, or holds another
        key: a file restored over this one meanwhile says nothing about how this signer's key is kept.
        """
        try:
            now, form = parse_ed25519_key(path, keyfile.read_settled(path)[0], self._pp)
        except Exception:  # noqa: BLE001 - a status read: gone, unreadable or unopenable all keep the answer given
            return read_as
        return form if _ed25519_public_bytes(now) == _ed25519_public_bytes(key) else read_as

    # -- ML-DSA ------------------------------------------------------------ #
    def _load_or_create_mldsa(self) -> tuple[bytes | None, bytes | None]:
        """Load the ML-DSA key pair, creating it once if there is none, by the same protocol as the Ed25519 key.

        A new pair is created 0600 from its first byte and made once (:func:`src.custody.keyfile.create_new`:
        two first callers end with ONE pair, never the last writer's). A pair written in the clear before
        the passphrase existed is wrapped in place the first time it is loaded under one: the SAME pair,
        read back and compared before it replaces anything (:func:`src.custody.keyfile.replace_in_place`),
        so a failure leaves the file as it was and ``key_protection`` says what the file really holds.
        """
        if not self._use_pqc or not PQC_AVAILABLE:
            return None, None
        path = self._mldsa_path
        try:
            raw, seen = keyfile.read_settled(path)
        except FileNotFoundError:
            pk, sk = _mldsa.generate_keypair()
            try:
                keyfile.create_new(path, seal_mldsa_key(pk, sk, self._pp))
            except FileExistsError:
                # another caller created it between our look and our create: ONE pair, theirs, judged like
                # any file found there (it may be plaintext, made by a caller with no passphrase)
                raw, seen = keyfile.read_settled(path)
            else:
                return pk, sk
        pk, sk, form = parse_mldsa_key(path, raw, self._pp)
        if self._pp and form != "wrapped":
            passphrase = self._pp

            def same_pair(blob: bytes) -> None:
                back_pk, back_sk, back_form = parse_mldsa_key(path, blob, passphrase)
                if back_form != "wrapped" or not (
                    hmac.compare_digest(back_pk, pk) and hmac.compare_digest(back_sk, sk)
                ):
                    raise SigningError("the wrapped copy does not hold the same key")

            if not keyfile.replace_in_place(
                path, lambda: seal_mldsa_key(pk, sk, passphrase), same_pair, seen, "ML-DSA signing key"
            ) and self._mldsa_form_now(path, form, pk, raw) == "plaintext":
                # Not replaced by this caller, and the file still holds this pair in the clear (another
                # caller may have wrapped it in the meantime, which is then what it holds).
                self._legacy_plain = True
        return pk, sk

    def _mldsa_form_now(self, path: Path, read_as: str, pk: bytes, raw: bytes) -> str:
        """The form the ML-DSA file holds at this moment, when it still holds THIS pair (else ``read_as``).

        ``raw`` is what this caller read: a file whose bytes have not changed holds what it held, so it is
        answered without a second scrypt (a wrap that cannot land, a read-only folder or a link, is retried
        on every load, and each one would pay it again).
        """
        try:
            now = keyfile.read_settled(path)[0]
            if now == raw:
                return read_as
            now_pk, _sk, form = parse_mldsa_key(path, now, self._pp)
        except Exception:  # noqa: BLE001 - a status read: gone, unreadable or unopenable all keep the answer given
            return read_as
        return form if hmac.compare_digest(now_pk, pk) else read_as

    # -- identity ---------------------------------------------------------- #
    def public_identity(self) -> PublicIdentity:
        ed_pub = (
            self._ed_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )
            .hex()
        )
        if self._mldsa_pk is not None:
            return PublicIdentity(ed_pub, _MLDSA_VARIANT, self._mldsa_pk.hex())
        return PublicIdentity(ed_pub, None, None)

    # -- signing ----------------------------------------------------------- #
    def sign(self, data: bytes) -> dict:
        """Sign ``data``; the returned dict is JSON-serialisable and self-describing.

        ``algorithm`` reflects what was *actually* produced: ``"hybrid"`` when an
        ML-DSA key is present, otherwise ``"ed25519"``.
        """
        ed_sig = self._ed_key.sign(data).hex()
        ed_pub = (
            self._ed_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )
            .hex()
        )
        if self._mldsa_sk is not None:
            ml_sig = _mldsa.sign(self._mldsa_sk, data).hex()
            return {
                "algorithm": "hybrid",
                "ed25519": {"sig": ed_sig, "pub": ed_pub},
                # `_mldsa_pk` and `_mldsa_sk` are assigned as ONE pair by
                # _load_or_create_mldsa, so the `_sk is not None` guard above settles
                # both; the checker cannot tie two attributes together.
                "ml_dsa": {
                    "variant": _MLDSA_VARIANT,
                    "sig": ml_sig,
                    "pub": cast(bytes, self._mldsa_pk).hex(),
                },
            }
        return {"algorithm": "ed25519", "ed25519": {"sig": ed_sig, "pub": ed_pub}}


# --------------------------------------------------------------------------- #
# Verification (stateless -- needs only the signature dict + data)
# --------------------------------------------------------------------------- #


def _verify_ed25519(pub_hex: str, sig_hex: str, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(sig_hex), data
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _verify_mldsa(variant: str, pub_hex: str, sig_hex: str, data: bytes) -> bool | None:
    """Return True/False, or None if this verifier cannot check the variant."""
    if not PQC_AVAILABLE or variant != _MLDSA_VARIANT:
        return None
    try:
        pub, sig = bytes.fromhex(pub_hex), bytes.fromhex(sig_hex)
    except (ValueError, TypeError):
        return False  # not hex: an invalid signature, never an exception out of a verifier
    return _mldsa_verify(_mldsa, pub, data, sig)


def verify(
    signature: dict, data: bytes, *, pinned: PublicIdentity | None = None
) -> tuple[bool, str]:
    """Verify a signature dict over ``data``.

    Returns ``(ok, reason)``.

    Hybrid signatures require **both** components to verify (AND). A verifier that
    lacks the post-quantum library cannot check the ML-DSA half of a hybrid
    signature and therefore returns *failure* with an explanatory reason -- it
    never silently downgrades to "Ed25519 was fine".

    Pass ``pinned`` (the signer's known :class:`PublicIdentity`) to prove
    *provenance*: the signature's embedded public keys must then match the pinned
    ones, defeating a "tamper, re-sign with my own key" attack.
    """
    alg = signature.get("algorithm")
    ed = signature.get("ed25519") or {}

    if pinned is not None:
        if ed.get("pub") != pinned.ed25519_pub:
            return False, "ed25519 public key does not match the pinned signer"
        if alg == "hybrid":
            ml = signature.get("ml_dsa") or {}
            if ml.get("pub") != pinned.ml_dsa_pub:
                return False, "ml-dsa public key does not match the pinned signer"

    if alg == "ed25519":
        if _verify_ed25519(ed.get("pub", ""), ed.get("sig", ""), data):
            return True, "ok (ed25519; classical signature only -- not quantum-resistant)"
        return False, "ed25519 signature invalid"

    if alg == "hybrid":
        ml = signature.get("ml_dsa") or {}
        ed_ok = _verify_ed25519(ed.get("pub", ""), ed.get("sig", ""), data)
        ml_ok = _verify_mldsa(ml.get("variant", ""), ml.get("pub", ""), ml.get("sig", ""), data)
        if ml_ok is None:
            return False, (
                "cannot verify hybrid signature: the ML-DSA component is "
                f"uncheckable here ({ml.get('variant')!r} unavailable -- install the "
                "'pqc' extra). Refusing to pass on the classical half alone."
            )
        if ed_ok and ml_ok:
            return True, "ok (hybrid Ed25519 + ML-DSA; both components verified)"
        if not ed_ok and not ml_ok:
            return False, "hybrid signature invalid (both components failed)"
        return False, (
            "hybrid signature invalid ("
            + ("ed25519 ok, ml-dsa failed" if ed_ok else "ml-dsa ok, ed25519 failed")
            + ")"
        )

    return False, f"unknown signature algorithm: {alg!r}"


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic serialisation for signing/hashing (sorted keys, compact)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
