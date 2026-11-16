"""A restore never turns a plaintext library encrypted under a running process (open-on-main row 84, checked 2026-11-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The worry: a restore of an ENCRYPTED backup over a PLAINTEXT library would leave the serves built while it was plaintext (and
their plaintext offload folders) serving, because only the encryption in place closes them. It cannot happen as the code
stands: every restore merges into a working copy that PRESERVES the live at-rest state (``src/backup/merge.py``), and a plain
process starts holding a key only through ``set_passphrase``, whose callers with a key are the encryption in place (which
closes the plaintext-era serves right after), the unlock and the create (both from a locked state, which serves no corpus) and
the offline country-migration command. This pins that list, so a new path that starts holding a key while a plaintext library
is served has to say how its serves are closed.

ONE ASSUMPTION it does not enforce: the operator CLI ``scripts/encrypt_db.py`` runs with the app STOPPED (it says so before it
asks anything). Run beside a live app, it replaces the file under it, and the app's plaintext-era serves stay until it restarts;
nothing in the app holds a lock another process could see. Matching on the name, the scan also misses an aliased import or a
direct write to ``connect._passphrase`` (none exists).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

#: (file, enclosing function) of every call that hands ``set_passphrase`` something other than ``None``.
EXPECTED = {
    ("api/unlock.py", "encrypt_db"),
    ("api/unlock.py", "_unlock_locked"),
    ("api/unlock.py", "create_db"),
    ("backup/country_migration.py", "main"),
}


def _calls_with_a_key() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "set_passphrase"):
                    continue
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and arg.value is None:
                    continue
                found.add((path.relative_to(ROOT).as_posix(), fn.name))
    return found


def test_only_the_known_paths_start_holding_a_key():
    found = _calls_with_a_key()
    unknown = found - EXPECTED
    assert not unknown, f"a new path starts holding a key; say how it closes the serves built while plaintext: {sorted(unknown)}"
    missing = EXPECTED - found
    assert not missing, f"the pinned list names a call that is gone; update it: {sorted(missing)}"


def test_no_restore_or_repair_path_sets_a_key():
    for sub in ("backup", "database"):
        for path in (ROOT / sub).rglob("*.py"):
            if path.name == "connect.py" or path.name == "country_migration.py":
                continue  # the definition itself, and the offline command (its own process, no serves)
            assert "set_passphrase(" not in path.read_text(encoding="utf-8"), f"{path} sets the key: a restore must preserve the at-rest state"


def test_the_encryption_in_place_closes_the_plaintext_era_serves_after_it_holds_the_key():
    src = (ROOT / "api/unlock.py").read_text(encoding="utf-8")
    body = src[src.index("def encrypt_db("):src.index("\n@router", src.index("def encrypt_db("))]
    assert body.index("set_passphrase(body.passphrase)") < body.index("_close_plaintext_serves()")
