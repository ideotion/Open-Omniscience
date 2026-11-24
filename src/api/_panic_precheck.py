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

#: The CLI's own words (English, like the rest of the CLI). The first sentence is the panic page's, as Plan passed it.
DRIVE_ABSENT_LINES = (
    "ERASE FAILED: The data drive was not present. Nothing on it was checked or erased. The data on that drive still exists.",
    "Nothing else was erased either: the app cannot run its erase without its data drive. Connect the drive and run the "
    "erase again.",
)


def drive_absent_for_panic(argv: list[str]) -> bool:
    """``argv`` (without the program name) asks for the panic erase and the marked data drive is not there."""
    if argv[:1] != ["panic"]:
        return False
    from src.safety import data_volume

    try:
        return data_volume.watched() and data_volume.probe().get("state") != "ok"
    except Exception:  # noqa: BLE001 - not knowing whether the drive is there is the drive not being there
        return True


def precheck(argv: list[str]) -> None:
    if drive_absent_for_panic(argv):
        for line in DRIVE_ABSENT_LINES:
            print(line)
        sys.exit(2)


precheck(sys.argv[1:])
