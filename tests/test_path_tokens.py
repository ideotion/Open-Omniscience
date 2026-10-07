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


@pytest.mark.parametrize("tail", ["+ice/x", "@corp/x", ".ice/x", "-ice/x", "_ice/x", "ice/x"])
def test_the_rest_of_another_users_name_does_not_survive_a_known_posix_home(known_home, tail):
    """A colon ENDS a known root on purpose (``/home/al:12`` is how a root is followed in a text), and so does a quote that no word
    character follows (``cwd='/home/al'``); a name that goes on with any other character is another user's."""
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


# --------------------------------------------------------------------------- #
#  An apostrophe inside a name, and a long run of backslashes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        r"C:\Users\O'Brien\Documents\x.py",
        r"\\fileserver\Users\o'brien\x.doc",
        r"\\fs\Users\o'brien\x",
        "/Users/O'Brien/Library/x.db",
        "/home/o'brien/x.py",
        "/var/home/o'brien/x.py",
    ],
)
def test_an_apostrophe_inside_a_profile_name_leaves_no_part_of_it(text):
    got = tokenise_paths(f"File {text}, line 3")
    assert "rien" not in got and "Brien" not in got and "brien" not in got, got


def test_an_apostrophe_inside_a_known_home_name_is_another_users_name(known_home):
    known_home("/home/al")
    got = tokenise_paths("open /home/al'ice/x failed")
    assert "ice" not in got, got


@pytest.mark.parametrize(
    "text, expected",
    [
        ("cwd='/home/al'", "cwd='<home>'"),
        ("cwd='C:\\Users\\Al'", "cwd='<home>'"),
        ("['/home/al', '/x']", "['<home>', '…/x']"),
        ("('C:\\Users\\Al', 'x')", "('<home>', 'x')"),
        ("/home/al:12", "<home>:12"),
    ],
)
def test_a_quote_or_colon_that_ends_a_path_still_ends_it(known_home, text, expected):
    known_home("/home/al")
    assert tokenise_paths(text) == expected


@pytest.mark.parametrize("run", [8_000, 20_000])
def test_a_long_run_of_backslashes_is_read_in_linear_time(run):
    """Timing-free: the patterns bound the run (an unbounded run restarts the match at every backslash, the square of its length), so
    the work is checked by the bound itself and the long text must come back unchanged in shape."""
    from src.monitoring import path_tokens

    assert path_tokens._UNC_LEAD == r"\\{2,8}"
    for pattern in (path_tokens._ABS, path_tokens._PROFILE_UNC):
        assert r"\\{2,}" not in pattern.pattern, "an unbounded run of backslashes"
    for root in ("/home/al", "\\\\server\\share"):  # the roots with a separator lead; a drive root has none
        assert path_tokens._root_pattern(root).pattern.startswith("(?<![\\w.<>~$…\\\\/])"), "a root starts at the first separator of a run"
    for text in ("\\" * run + "x", "/" * run + "x"):
        got = tokenise_paths(text)
        assert isinstance(got, str) and got.endswith("x")


def test_a_non_profile_extended_unc_path_keeps_only_its_file_name():
    """Pins the extended-prefix branch of the generic rule (no profile directory in it)."""
    assert tokenise_paths(r"open \\?\UNC\fileserver\share\data\file.txt now") == "open …/file.txt now"


def test_a_drive_root_after_an_extended_prefix_is_still_found(known_home):
    """MUTATION TARGET: the lookbehind of a root with no separator lead (``_root_pattern``): refusing a backslash before a drive-letter
    root loses ``\\\\?\\D:\\Profiles\\alice`` and leaves the whole path."""
    known_home(r"D:\Profiles\alice")
    out = tokenise_paths(r"open \\?\D:\Profiles\alice\proj\x.py")
    assert "alice" not in out and out.endswith("<home>/…/x.py"), out
    assert "alice" not in tokenise_paths(r"open \\?\d:\profiles\ALICE\proj\x.py")


def test_an_extended_prefix_with_a_drive_and_no_known_root_leaves_the_file_name_only():
    out = tokenise_paths(r"open \\?\D:\Work\data\x.py")
    assert out == r"open …/x.py" or out.endswith("…/x.py"), out
    assert "Work" not in out


def test_the_generic_rule_keeps_an_apostrophe_inside_a_name():
    out = tokenise_paths("/mnt/data/O'Brien/docs/x.py")
    assert "Brien" not in out and out.endswith("x.py"), out
    # a quote that ends a path is still an end
    assert tokenise_paths("cwd='/mnt/data/work/x.py'").endswith("x.py'")


def test_only_roots_with_a_separator_lead_refuse_a_separator_before_them():
    from src.monitoring.path_tokens import _root_pattern

    assert _root_pattern("/srv/app").search("x //srv/app/y").start() == 2  # the first separator of the run, never the second
    assert _root_pattern("D:/Profiles/alice").search(r"\\?\D:\Profiles\alice\x") is not None
    assert _root_pattern("D:/Profiles/alice").search(r"xD:\Profiles\alice\x") is None  # a word character still refuses
