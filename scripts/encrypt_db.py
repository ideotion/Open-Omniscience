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
    from src.api.unlock import main_db_path
    from src.database.connect import is_encrypted_file
    from src.database.encrypt_tool import EncryptToolError, encrypt_all

    p = main_db_path()
    if p is None:
        print("non-SQLite backend: nothing to encrypt here")
        return 1
    state = is_encrypted_file(p)
    if state is None:
        print(f"no database at {p} yet -- first launch will create it encrypted")
        return 1
    if state:
        print(f"{p.name} is already encrypted")
        return 0

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
