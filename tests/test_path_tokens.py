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


# --------------------------------------------------------------------------- #
#  A known root ends where a name cannot go on; the forms a diagnostic can write beside it
# --------------------------------------------------------------------------- #
@pytest.fixture
def known_home(monkeypatch):
    def use(path: str) -> None:
        monkeypatch.setenv("HOME", path)
        for name in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
            monkeypatch.delenv(name, raising=False)

    return use


@pytest.mark.parametrize("tail", ["+ice/x", "@corp/x", ".ice/x", "-ice/x", "_ice/x", "ice/x", ":x"])
def test_the_rest_of_another_users_name_does_not_survive_a_known_posix_home(known_home, tail):
    """A quote and a colon END a known root on purpose (``cwd='/home/al'``, ``/home/al:12`` are how a root is followed in a text), so
    ``/home/al'ice`` reads ``<home>'ice``; a name that goes on with any other character is another user's."""
    known_home("/home/al")
    got = tokenise_paths(f"open /home/al{tail} failed")
    assert "ice" not in got and "corp" not in got, got


@pytest.mark.parametrize("tail", [" Ice\\x.py", ".DOMAIN\\x.py", "x\\y.py", "+Ice\\y.py"])
def test_the_rest_of_another_users_name_does_not_survive_a_known_windows_home(known_home, tail):
    known_home("C:\\Users\\Al")
    got = tokenise_paths(f"File C:\\Users\\Al{tail}")
    assert "Ice" not in got and "DOMAIN" not in got and "Alx" not in got, got


def test_a_known_windows_home_is_still_replaced_when_a_separator_follows(known_home):
    known_home("C:\\Users\\Al")
    assert tokenise_paths("File C:\\Users\\Al\\proj\\x.py, line 3") == "File <home>/…/x.py, line 3"


@pytest.mark.parametrize(
    "text",
    [
        r"\\?\UNC\fileserver\home\alice\x.py",
        r"\\?\UNC\fileserver\Users\alice",
        r"\\fileserver\Users\alice\Desktop\x.py",
        r"\\fileserver\share\home\alice",
    ],
)
def test_a_unc_path_in_its_extended_forms_keeps_no_user_name(text):
    got = tokenise_paths(f"error at {text} here")
    assert "alice" not in got and "fileserver" not in got, got


@pytest.mark.parametrize("text", ["/var/home/alice", "/var/home/alice/proj/x.py", "cwd=/var/home/alice"])
def test_fedora_atomic_homes_are_tokenised_too_even_for_a_directory_only_path(text):
    assert "alice" not in tokenise_paths(text)


def test_a_directory_only_path_under_an_unknown_root_keeps_its_last_segment_and_that_is_stated():
    assert tokenise_paths("cwd=/srv/projects/team") == "cwd=…/team"
    from src.monitoring import path_tokens

    assert "keeps its last segment" in path_tokens.__doc__
