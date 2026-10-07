"""``tokenise_paths``: no absolute path survives whole, in any of the forms a diagnostic text writes one."""

from __future__ import annotations

import pytest

from src.monitoring.path_tokens import tokenise_paths


@pytest.fixture
def homes(monkeypatch, tmp_path):
    home = tmp_path / "alice smith"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(name, raising=False)
    return home


def test_a_path_under_the_home_keeps_only_its_file_name(homes):
    assert tokenise_paths(f"File \"{homes}/x/y/z.py\", line 12") == 'File "<home>/…/z.py", line 12'


def test_the_app_own_path_is_made_relative():
    from src.monitoring.path_tokens import _roots

    app = next(root for root, how in _roots() if how == "app")
    assert tokenise_paths(f"{app}/src/monitoring/session_hwm.py:12 in run") == "src/monitoring/session_hwm.py:12 in run"


@pytest.mark.parametrize(
    "text",
    [
        r"C:\Users\Alice Smith\AppData\Local\x\y.log",
        r"c:/users/alice smith/appdata/x.log",
        r"C:\\Users\\Alice Smith\\AppData\\x.log",
        r"D:\Documents and Settings\Bob Jones\x.txt",
        "/home/bob/.cache/x.txt",
        "/Users/Bob/Library/x.txt",
        r"\\fileserver\share\carol\x.txt",
        "~carol/x.txt",
    ],
)
def test_no_form_of_a_users_path_leaves_the_name_behind(homes, text):
    got = tokenise_paths(f"error at {text} while opening")
    for name in ("alice", "Alice", "bob", "Bob", "carol", "smith", "Smith", "Jones", "fileserver"):
        assert name not in got.replace("x.txt", "").replace("alice smith", ""), (text, got)
    assert "while opening" in got


def test_a_home_that_is_not_the_one_home_names_is_still_replaced(monkeypatch, homes, tmp_path):
    other = tmp_path / "other user"
    monkeypatch.setenv("USERPROFILE", str(other))
    assert "other user" not in tokenise_paths(f"{other}/a/b.py")


def test_a_text_with_no_path_is_unchanged():
    assert tokenise_paths("nothing to see: 3/4 done, a-b/c") == "nothing to see: 3/4 done, a-b/c"


def test_the_ellipsis_is_not_doubled(homes):
    assert "……" not in tokenise_paths(f"{homes}/a/b.py and …/c.py")
