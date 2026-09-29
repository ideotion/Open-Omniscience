"""Locale files stay sorted so parallel PRs merge cleanly (scripts/locales_merge.py)."""
import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "locales_merge.py"
_spec = importlib.util.spec_from_file_location("locales_merge", _SCRIPT)
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)


def test_locale_files_are_canonical():
    assert lm.check() == []


def test_resolve_keeps_both_sides(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(
        '{\n  "_meta": {"a": 1},\n  "a": "A",\n<<<<<<< HEAD\n  "z": "Z"\n=======\n  "m": "M"\n>>>>>>> origin/main\n}\n',
        encoding="utf-8",
    )
    out = json.loads(lm.resolve(p))
    assert list(out) == ["_meta", "a", "m", "z"]
    assert lm.resolve(p).endswith("}\n")


def test_resolve_refuses_contradiction(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(
        '{\n  "a": "A",\n<<<<<<< HEAD\n  "k": "one"\n=======\n  "k": "two"\n>>>>>>> origin/main\n}\n',
        encoding="utf-8",
    )
    try:
        lm.resolve(p)
    except SystemExit as e:
        assert "k" in str(e)
    else:
        raise AssertionError("contradiction was merged silently")
