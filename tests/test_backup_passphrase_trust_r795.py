"""R795 (row 330) and row 337: the early check names a backup passphrase wrong only when the backup's list of volumes is
signed by THIS installation's own key.

The list carries the public key it was signed with, so a valid signature alone proves nothing about who wrote it. Someone
who swaps the first volume for one sealed under another passphrase, writes that volume's checksum into the list and signs
the list with a key of their own (the three-step swap) used to make the right passphrase read as "wrong". Now every case in
which the list is not this installation's own is still refused, in words that say a wrong passphrase cannot be told apart
from a changed backup, and why. The acceptance rules do not change: what was refused is still refused.

Row 337: the restore's and the import queue's refusals, and the two crypto refusals of rows 312 and 329, reach the page
as English sentences; ``ooServerText`` translates each one whole in all twelve languages."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import src.backup.stream_backup as sb
import src.reporting.evidence as EV
from src.backup.import_queue import UNCHECKED_PASSPHRASE, WRONG_PASSPHRASES, ImportQueueManager
from src.backup.stream_backup import (
    REASON_BAD_SIGNATURE,
    REASON_OTHER_INSTALLATION,
    REASON_OWN_KEY_UNREADABLE,
    REASON_UNSIGNED,
    UNCHECKED_BACKUP_PASSPHRASE,
    UNCHECKED_REASONS,
    WRONG_BACKUP_PASSPHRASE,
    BackupPassphraseUnchecked,
    CorpusSource,
    MemberFile,
    WrongBackupPassphrase,
    backup_passphrase_check,
    backup_passphrase_is_wrong,
    read_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import MANIFEST_NAME, _sha256_file
from src.safety.crypto import _NOT_THE_FILE_CHECKED, EncryptionError, encrypt_file

LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
LANGS = sorted(p.stem for p in LOCALES.glob("*.json"))


def _no_freeze():
    from contextlib import nullcontext

    return nullcontext()


@pytest.fixture
def own_key(tmp_path, monkeypatch) -> Path:
    """This installation's signing key, in the test's own folder (never the suite's)."""
    path = tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(EV, "_default_key_path", lambda: path)
    return path


def _stream_set(tmp: Path, passphrase: str = "pw") -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    corpus = tmp / "corpus.db"
    con = sqlite3.connect(corpus)
    con.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);")
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i:05d}", "x" * 3000) for i in range(50)])
    con.commit()
    con.close()
    a = tmp / "app_settings.json"
    a.write_text('{"k": 1}', encoding="utf-8")
    dest = tmp / "dest"
    write_stream_backup(dest, passphrase, corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False,
                                                                     freeze=_no_freeze),
                        side_members=[MemberFile("app_settings.json", "state", a)], volume_size=65536, parity_fraction=0.0)
    for p in dest.glob("*.oopar"):
        p.unlink()
    return dest


def _manifest(dest: Path) -> dict:
    return json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))


def _write_manifest(dest: Path, m: dict) -> None:
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


def _first_volume(m: dict) -> str:
    names = {v["name"] for v in m["volumes"]}
    return next(v for mm in m["members"] for v in mm["volumes"] if v in names)


def _sign_with(m: dict, key) -> dict:
    from src.reporting.evidence import canonical_bytes, public_key_hex

    body = {k: v for k, v in m.items() if k != "signature"}
    return {**body, "signature": {"algorithm": "ed25519", "public_key": public_key_hex(key),
                                  "signature": key.sign(canonical_bytes(body)).hex()}}


def _three_step_swap(dest: Path, tmp: Path) -> None:
    """Swap the first volume for one sealed under another passphrase, write its checksum and size into the list, and sign
    the list with a key that is not this installation's."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    m = _manifest(dest)
    first = _first_volume(m)
    plain = tmp / "someone_else.bin"
    plain.write_bytes(b"s" * 5000)
    encrypt_file(plain, dest / first, "someone else's words")
    for v in m["volumes"]:
        if v["name"] == first:
            v["sha256"] = _sha256_file(dest / first)
            v["bytes"] = (dest / first).stat().st_size
    _write_manifest(dest, _sign_with(m, Ed25519PrivateKey.generate()))


# --------------------------------------------------------------------------- #
#  the verdict
# --------------------------------------------------------------------------- #
def test_a_wrong_passphrase_on_this_installations_own_backup_is_named_wrong(tmp_path, own_key):
    dest = _stream_set(tmp_path)
    assert own_key.exists()  # the backup was signed by this installation's own key
    assert backup_passphrase_check(dest, "not the words") == ("wrong", None)
    assert backup_passphrase_is_wrong(dest, "not the words") is True
    with pytest.raises(WrongBackupPassphrase) as refused:
        read_stream_backup(dest, "not the words", staging_root=tmp_path / "staging")
    assert str(refused.value) == WRONG_BACKUP_PASSPHRASE
    assert "intact" not in str(refused.value)


def test_the_right_passphrase_is_never_refused(tmp_path, own_key):
    dest = _stream_set(tmp_path)
    assert backup_passphrase_check(dest, "pw") == ("none", None)
    sb._refuse_a_wrong_backup_passphrase(dest, _manifest(dest), "pw")


def test_the_three_step_swap_never_reads_as_a_wrong_passphrase(tmp_path, own_key):
    """The attack the R795 ruling names: the right passphrase must never be called wrong, and the set is still refused."""
    dest = _stream_set(tmp_path)
    _three_step_swap(dest, tmp_path)
    assert sb._manifest_signature_state(_manifest(dest)) == "verified"  # valid, by the key it carries
    assert backup_passphrase_check(dest, "pw") == ("unchecked", REASON_OTHER_INSTALLATION)
    assert backup_passphrase_is_wrong(dest, "pw") is False
    with pytest.raises(BackupPassphraseUnchecked) as refused:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "staging")
    assert str(refused.value) == UNCHECKED_BACKUP_PASSPHRASE.format(reason=REASON_OTHER_INSTALLATION)
    assert "wrong passphrase for" not in str(refused.value)
    assert not (tmp_path / "staging").exists() or not any((tmp_path / "staging").iterdir())


def test_a_backup_with_no_signature_is_refused_with_that_reason(tmp_path, own_key):
    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    m.pop("signature")
    _write_manifest(dest, m)
    assert backup_passphrase_check(dest, "not the words") == ("unchecked", REASON_UNSIGNED)
    with pytest.raises(BackupPassphraseUnchecked, match="could not check the passphrase for this backup"):
        read_stream_backup(dest, "not the words", staging_root=tmp_path / "staging")


def test_a_backup_whose_signature_does_not_match_is_refused_with_that_reason(tmp_path, own_key):
    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    sig = m["signature"]["signature"]
    m["signature"]["signature"] = ("0" if sig[0] != "0" else "1") + sig[1:]
    _write_manifest(dest, m)
    assert backup_passphrase_check(dest, "not the words") == ("unchecked", REASON_BAD_SIGNATURE)
    # the restore itself refuses a bad signature before the passphrase is tried, as before
    with pytest.raises(Exception, match="signature"):
        read_stream_backup(dest, "not the words", staging_root=tmp_path / "staging")


def test_a_backup_from_another_installation_is_refused_neutrally(tmp_path, own_key):
    """Made here, then this installation's key is replaced (a new computer): never worded as tampering."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    dest = _stream_set(tmp_path)
    _write_manifest(dest, _sign_with(_manifest(dest), Ed25519PrivateKey.generate()))
    verdict, reason = backup_passphrase_check(dest, "not the words")
    assert (verdict, reason) == ("unchecked", REASON_OTHER_INSTALLATION)
    assert "tamper" not in reason and "altered" not in reason and "changed" not in reason


def test_an_unreadable_own_key_is_named_and_no_key_is_ever_created(tmp_path, own_key):
    dest = _stream_set(tmp_path)
    own_key.write_bytes(b"not a key at all")
    assert backup_passphrase_check(dest, "not the words") == ("unchecked", REASON_OWN_KEY_UNREADABLE)
    own_key.unlink()
    assert backup_passphrase_check(dest, "not the words") == ("unchecked", REASON_OTHER_INSTALLATION)
    assert not own_key.exists()  # the check reads the key; it never makes one


def test_this_installations_key_spelled_another_way_is_still_this_installations_key(tmp_path, own_key):
    """The comparison is of the keys, not of their spelling: upper case or spaced hex names the same key."""
    from src.reporting.evidence import load_or_create_signing_key

    dest = _stream_set(tmp_path)
    m = _manifest(dest)
    pub = m["signature"]["public_key"]
    m = _sign_with(m, load_or_create_signing_key())
    m["signature"]["public_key"] = " ".join(pub[i:i + 2] for i in range(0, len(pub), 2)).upper()
    _write_manifest(dest, m)
    assert sb._manifest_signature_state(m) == "verified"
    assert backup_passphrase_check(dest, "not the words") == ("wrong", None)


def test_the_reasons_are_the_four_fixed_texts():
    assert set(UNCHECKED_REASONS) == {REASON_UNSIGNED, REASON_BAD_SIGNATURE, REASON_OTHER_INSTALLATION,
                                      REASON_OWN_KEY_UNREADABLE}
    for text in (WRONG_BACKUP_PASSPHRASE, UNCHECKED_BACKUP_PASSPHRASE, WRONG_PASSPHRASES, UNCHECKED_PASSPHRASE):
        assert "intact" not in text


def test_both_refusals_are_encryption_errors(tmp_path, own_key):
    """Every caller that catches the old refusal still catches both."""
    assert issubclass(WrongBackupPassphrase, EncryptionError) and issubclass(BackupPassphraseUnchecked, EncryptionError)


# --------------------------------------------------------------------------- #
#  the import queue
# --------------------------------------------------------------------------- #
def test_the_queue_names_a_wrong_passphrase_and_an_unchecked_one_on_their_own_lines(tmp_path, own_key, monkeypatch):
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: False))
    mine = _stream_set(tmp_path / "mine")
    swapped_dir = tmp_path / "swapped"
    swapped = _stream_set(swapped_dir)
    _three_step_swap(swapped, swapped_dir)
    with pytest.raises(ValueError) as refused:
        ImportQueueManager._refuse_wrong_backup_passphrases(
            [{"kind": "corpus", "path": str(mine), "label": "mine", "passphrase": "typo words"},
             {"kind": "corpus", "path": str(swapped), "label": "swapped"}],
            "pw",
        )
    lines = str(refused.value).split("\n")
    assert lines == [WRONG_PASSPHRASES.format(names="mine"),
                     UNCHECKED_PASSPHRASE.format(name="swapped", reason=REASON_OTHER_INSTALLATION)]
    assert "typo words" not in str(refused.value)  # a passphrase never appears in a refusal


def test_a_folder_name_never_starts_a_line_of_its_own(tmp_path, own_key, monkeypatch):
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: False))
    mine = _stream_set(tmp_path / "mine")
    with pytest.raises(ValueError) as refused:
        ImportQueueManager._refuse_wrong_backup_passphrases(
            [{"kind": "corpus", "path": str(mine), "label": "a\nWrong passphrase for b\x1b", "passphrase": "typo words"}],
            "pw",
        )
    assert str(refused.value) == WRONG_PASSPHRASES.format(names="a Wrong passphrase for b ")


def test_the_queue_starts_when_every_passphrase_opens(tmp_path, own_key, monkeypatch):
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: False))
    mine = _stream_set(tmp_path / "mine")
    ImportQueueManager._refuse_wrong_backup_passphrases([{"kind": "corpus", "path": str(mine)}], "pw")


# --------------------------------------------------------------------------- #
#  row 337: what the page shows, in every language
# --------------------------------------------------------------------------- #
def _messages() -> list[tuple[str, str, dict]]:
    """(server message, locale key, values) for every sentence this row maps."""
    out = [
        (WRONG_BACKUP_PASSPHRASE, "W" + WRONG_BACKUP_PASSPHRASE[1:], {}),
        ("could not restore this backup: " + WRONG_BACKUP_PASSPHRASE, "W" + WRONG_BACKUP_PASSPHRASE[1:], {}),
        ("this file was not read: it is not a regular file, or it is a link",
         "This file was not read: it is not a regular file, or it is a link.", {}),
        ("could not restore this backup: " + _NOT_THE_FILE_CHECKED,
         "This file is not the one that was checked before reading (it was replaced or changed since), so what was read "
         "from it is not used.", {}),
        (WRONG_PASSPHRASES.format(names="May backup"), WRONG_PASSPHRASES, {"names": "May backup"}),
    ]
    for reason in UNCHECKED_REASONS:
        out.append((UNCHECKED_BACKUP_PASSPHRASE.format(reason=reason),
                    "C" + UNCHECKED_BACKUP_PASSPHRASE[1:], {"reason": reason}))
        out.append((UNCHECKED_PASSPHRASE.format(name="May backup", reason=reason), UNCHECKED_PASSPHRASE,
                    {"name": "May backup", "reason": reason}))
    return out


def _expected(table: dict, key: str, values: dict) -> str:
    text = table[key]
    for k, v in values.items():
        if k == "reason":
            text = text.replace("{reason}", table[v])
        else:
            text = text.replace("{" + k + "}", "⁨" + v + "⁩")
    return text


@pytest.mark.parametrize("lang", LANGS)
def test_every_refusal_is_translated_whole_in_every_language(lang):
    from tests.test_export_job import _ooservertext_in

    table = json.loads((LOCALES / f"{lang}.json").read_text("utf-8"))
    msgs = _messages()
    queue_two = msgs[4][0] + "\n" + msgs[6][0]  # the queue's refusal, one sentence per line
    got = _ooservertext_in(lang, [m for m, _k, _v in msgs] + [queue_two])
    for (msg, key, values), shown in zip(msgs, got[:-1], strict=True):
        assert key in table, key
        assert shown == _expected(table, key, values), (msg, shown)
        if lang != "en":
            assert shown != msg
    assert got[-1] == got[4] + "\n" + got[6]


def test_an_unknown_reason_or_a_stray_line_leaves_the_message_in_english():
    from tests.test_export_job import _ooservertext_in

    odd = UNCHECKED_BACKUP_PASSPHRASE.format(reason="something else")
    mixed = WRONG_PASSPHRASES.format(names="a") + "\nsome other sentence"
    assert _ooservertext_in("fr", [odd, mixed]) == [odd, mixed]
