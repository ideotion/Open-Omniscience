"""
R809, run on import by src/api/main.py BEFORE anything there opens the data folder: ``open-omniscience panic`` with the
marked data drive not there (or another drive at its place) is a FAILURE said as one, with exit status 2. Without it, the
database import in main.py (src/database/session.py reads the data folder at import) raises DataVolumeMissing and the erase
ends in a traceback. Reads only (data_volume.probe never makes anything); nothing is asked, since nothing is erased.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sys

#: The CLI's own words (English, like the rest of the CLI). The sentences after "ERASE FAILED: " are the panic page's, as Plan
#: passed them: S1 for a drive not there, S5 (R812 (a)) for one that is there and cannot be identified.
NOTHING_ELSE = (
    "Nothing else was erased either: the app cannot run its erase without its data drive. Connect the drive and run the "
    "erase again."
)


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
    if sentence is not None:
        print("ERASE FAILED: " + sentence)
        print(NOTHING_ELSE)
        sys.exit(2)


precheck(sys.argv[1:])
