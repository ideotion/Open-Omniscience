"""
R809, run on import by src/api/main.py BEFORE anything there opens the data folder: ``open-omniscience panic`` with the
marked data drive not there (or another drive at its place) is a FAILURE said as one, with exit status 2. Without it, the
database import in main.py (src/database/session.py reads the data folder at import) raises DataVolumeMissing and the erase
ends in a traceback.

Row 388 (R813 follow-up): the erase still runs, here, without the database module, on what the app keeps OUTSIDE the drive (a
columnar store or a database that an override puts elsewhere, with their key files); its erase leaves out every store on the
drive (src/safety/crypto_erase.py, R809). Asked first unless ``--yes``, like the erase in main.py. The exit status stays 2: the
drive's own data was not erased.

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
        from src.safety import panic_wipe

        report = panic_wipe(confirm=True)
    except Exception as exc:  # noqa: BLE001 - said, never a traceback
        print(f"The erase of what the app keeps outside the data drive failed ({type(exc).__name__}): it may be partly erased.")
        print(ON_THE_DRIVE)
        sys.exit(2)
    if not report.get("drive_absent"):
        # The drive came back between this check and the erase, which then erased it as usual: said as the erase says it.
        print(f"Wiped {report.get('files_wiped')}/{report.get('files_seen')} files under {report.get('data_dir')}.")
        print(report.get("limit", ""))
        sys.exit(1 if report.get("drive_lost") else 0)
    if report.get("files_seen"):
        print(f"Files erased outside the data drive: {report['files_wiped']} of {report['files_seen']}.")
    else:
        print(NOTHING_OUTSIDE)
    if report.get("unlisted_folders"):
        print(f"THE ERASE MAY BE INCOMPLETE: it could not list {report['unlisted_folders']} of the folders it was to erase.")
    print(ON_THE_DRIVE)
    sys.exit(2)


precheck(sys.argv[1:])
