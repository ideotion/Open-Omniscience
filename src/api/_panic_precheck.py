"""
R809, run on import by src/api/main.py BEFORE anything there opens the data folder: ``open-omniscience panic`` with the
marked data drive not there (or another drive at its place) is a FAILURE said as one, with exit status 2. Without it, the
database import in main.py (src/database/session.py reads the data folder at import) raises DataVolumeMissing and the erase
ends in a traceback.

Row 388 (R813 follow-up): the erase still runs, here, without the database module, on what the app keeps OUTSIDE the drive (a
columnar store or a database that an override puts elsewhere, with their key files); its erase leaves out every store on the
drive (src/safety/crypto_erase.py, R809). Asked first unless ``--yes``, like the erase in main.py. The exit status stays 2: the
drive's own data was not erased. A drive plugged in while the question waits is left whole (``off_drive_only``: the operator
agreed to erase only what is outside it), and another program holding a store outside the drive is said, as in main.py.
Any import of this module with ``panic`` as the first argument runs it, as before; the program name is not checked, since a
packaged launcher may name itself otherwise and must still reach the erase.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sys

#: The CLI's own words (English, like the rest of the CLI). The sentences after "ERASE FAILED: " are the panic page's, as Plan
#: passed them: S1 for a drive not there, S5 (R812 (a)) for one that is there and cannot be identified.
ON_THE_DRIVE = "The stores and keys the app keeps on the data drive were not erased: connect the drive and run the erase again."
NOTHING_OUTSIDE = "Nothing the app keeps outside the data drive was found to erase."
ASK = ("The data drive is not there, so only what the app keeps outside it can be erased now. Irreversibly erase that? "
       "Type 'wipe' to confirm: ")


def drive_failure_for_panic(argv: list[str]) -> str | None:
    """``argv`` (without the program name) asks for the panic erase and the marked data drive is not there or cannot be
    identified: the sentence to print, else None. The erase's own rule (src/safety/crypto_erase.py _drive_state)."""
    if argv[:1] != ["panic"]:
        return None
    try:
        from src.safety import crypto_erase, data_volume

        folder = data_volume.configured_folder()
        state = crypto_erase._drive_state(folder) if folder is not None else "unwatched"
    except Exception:  # noqa: BLE001 - not knowing whether the drive is there is a drive that cannot be identified
        state = "unidentified"
    if state == "absent":
        return crypto_erase._DRIVE_ABSENT_SENTENCE
    if state == "unidentified":
        return "The data drive could not be identified. Nothing on it was checked or erased. The data on that drive still exists."
    return None


def drive_absent_for_panic(argv: list[str]) -> bool:
    return drive_failure_for_panic(argv) is not None


HELD = ("THE ERASE MAY BE INCOMPLETE: another program had a store outside the data drive open during the erase, and it may have "
        "written that store's key material back to the disk. Close that program or restart the computer.")
UNKNOWN = ("The erase could not check whether another program had a store outside the data drive open. If one did, the erase "
           "may be incomplete: close such a program or restart the computer.")
RETURNED = ("The data drive was connected while the erase waited, so nothing on it was erased: you agreed only to erase what is "
            "outside it. Run the erase again to erase the drive.")


def precheck(argv: list[str]) -> None:
    sentence = drive_failure_for_panic(argv)
    if sentence is None:
        return
    print("ERASE FAILED: " + sentence)
    if "--yes" not in argv and "-y" not in argv:
        try:
            answer = input(ASK)
        except EOFError:
            answer = ""
        if answer.strip().lower() != "wipe":
            print("Aborted. Nothing was erased.")
            print(ON_THE_DRIVE)
            sys.exit(2)
    try:
        from src.safety import crypto_erase, panic_wipe

        # off_drive_only: a drive plugged in while the question waited is left whole (the operator agreed to the rest only).
        report = panic_wipe(confirm=True, off_drive_only=True)
    except Exception as exc:  # noqa: BLE001 - said, never a traceback
        print(f"The erase of what the app keeps outside the data drive failed ({type(exc).__name__}): it may be partly erased.")
        print(ON_THE_DRIVE)
        sys.exit(2)
    if report.get("drive_returned"):
        print(RETURNED)
    else:
        found = crypto_erase._drive_failure_sentence(report)
        if found and found != sentence:  # the erase read the drive again and found it otherwise: its reading is the one said
            print("ERASE FAILED: " + found)
    if report.get("files_seen"):
        print(f"Files erased outside the data drive: {report['files_wiped']} of {report['files_seen']}.")
    else:
        print(NOTHING_OUTSIDE)
    holder = report.get("other_holder", "unknown")
    if holder == "held":
        print(HELD)
    elif holder != "none":
        print(UNKNOWN)
    if report.get("unlisted_folders"):
        print(f"THE ERASE MAY BE INCOMPLETE: it could not list {report['unlisted_folders']} of the folders it was to erase, so it "
              "could not check the files in them.")
    if report.get("after_erase_failures"):
        print("The erase completed; these steps after it failed: " + ", ".join(report["after_erase_failures"]))
    print(ON_THE_DRIVE)
    sys.exit(2)


precheck(sys.argv[1:])
