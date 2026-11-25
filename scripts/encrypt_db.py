#!/usr/bin/env python3
"""One-way encryption of an existing plaintext corpus (operator CLI).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Equivalent of Settings -> Safety -> "Encrypt this corpus": snapshot first,
explicit consent, verify, atomic swap; covers the corpus AND the custody log
under THE one passphrase. Run with the app STOPPED.

    OO_DATA_DIR=... python scripts/encrypt_db.py
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    # Before any prompt (2026-10-06): the passphrase typed below is in this process's memory from the moment it is read, and a
    # crash while the corpus is exported would write that memory out as a core dump. The store's own key-handing functions guard
    # the process too, but a key is read here before it reaches one.
    from src.monitoring.secret_scrub import guard_process

    guard_process()

    from src.api.unlock import main_db_path
    from src.database.connect import is_encrypted_file
    from src.database.encrypt_tool import EncryptPartial, EncryptToolError, encrypt_all

    p = main_db_path()
    if p is None:
        print("non-SQLite backend: nothing to encrypt here")
        return 1
    state = is_encrypted_file(p)
    if state is None:
        print(f"no database at {p} yet -- first launch will create it encrypted")
        return 1
    if state:
        # R821 (3): the header alone never says "already encrypted". This installation's record naming this very file does; without
        # it, nothing is changed and nothing is claimed.
        from src.database import at_rest_state

        if at_rest_state.claim_for(p) == "encrypted":
            # Security reads (row 400): the corpus alone is not the whole answer; an earlier run that stopped part-way (R742) can
            # leave the custody log or a lane in plaintext, or one that only looks encrypted.
            st = at_rest_state.status(p)
            if st.get("complete"):
                print(f"{p.name} is encrypted, per this installation's record; nothing to do")
                return 0
            left = sorted({*st.get("pending", []), *st.get("looks_encrypted", []), *st.get("busy", [])})
            print(f"{p.name} is encrypted, per this installation's record, but these stores are not shown encrypted: "
                  + (", ".join(left) or "(could not be told)"))
            print("Open the app, unlock it, and finish with Settings -> Safety -> 'Encrypt this corpus'.")
            return 1
        print(f"{p.name} looks encrypted, but this cannot be told from here: nothing was changed.")
        print("Open the app and unlock it once with your passphrase (that checks it), then run this again.")
        return 1

    print("Stop the app first. A running app keeps what it built from the plaintext file, and the")
    print("temporary files that hold it, until it restarts. While it runs, use Settings -> Safety ->")
    print("'Encrypt this corpus', which closes them.")
    print("This encrypts your corpus and custody log IN PLACE (SQLCipher 4).")
    print("There is NO recovery and NO decryption alternative if the passphrase")
    print("is lost. A plaintext snapshot is kept as your escape hatch -- delete")
    print("it once you have unlocked successfully.")
    if input("Type 'encrypt' to continue: ").strip() != "encrypt":
        print("aborted -- nothing was changed")
        return 1
    pw = getpass.getpass("Choose THE passphrase (min 8 chars): ")
    if pw != getpass.getpass("Repeat it: "):
        print("passphrases do not match -- nothing was changed")
        return 1
    try:
        reports = encrypt_all(pw)
    except EncryptPartial as exc:
        # R742: the library IS encrypted with this passphrase; the stores named here are not yet. Starting the app and
        # unlocking finishes them, or Settings -> Safety -> Encrypt with the same passphrase.
        print(f"partly done: {exc}")
        print("still unencrypted: " + ", ".join(exc.pending))
        return 1
    except EncryptToolError as exc:
        print(f"refused: {exc}")
        return 1
    for store, rep in reports.items():
        print(f"  {store}: {rep}")
    print("Done. Start the app and unlock with your passphrase")
    print("(or set OO_DB_PASSPHRASE for scripted runs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
