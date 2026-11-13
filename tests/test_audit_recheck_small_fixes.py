"""Audit recheck 2026-11-13: the small fixes (P4 oo.env, P6 bulletin links, P10 author removal).

Each test is red on main ca1ab824 and green after the fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import src.safety.data_location as dl
import src.safety.data_volume as dv
from src.bulletin.i18n import Translator
from src.bulletin.render import _article_lines, _inline


# --- P4: oo.env is never left cut short ----------------------------------------------------------
def test_forgetting_the_id_never_writes_oo_env_in_place(tmp_path, monkeypatch) -> None:
    """A write cut short (a crash, a full disk) must leave the previous file whole: launch.sh sources it,
    and a truncated file names no data folder, so the next start opens the default one.
    The cut is simulated at the only in-place writer the old code used, ``Path.write_text``."""
    env = tmp_path / "oo.env"
    before = f"export OO_DATA_DIR=/media/drive/oo\nexport {dv.ENV_ID}=abc\n"
    env.write_text(before, encoding="utf-8")
    monkeypatch.setattr(dl, "env_file_path", lambda: env)
    real = Path.write_text

    def cut_short(self: Path, data: str, *a, **k) -> int:
        if self == env:
            real(self, data[:5], *a, **k)
            raise OSError(28, "No space left on device")
        return real(self, data, *a, **k)

    monkeypatch.setattr(Path, "write_text", cut_short)
    dv.forget_volume_id()
    assert env.read_text(encoding="utf-8") == "export OO_DATA_DIR=/media/drive/oo\n"


def test_a_failed_replace_keeps_the_old_oo_env_and_no_temp(tmp_path, monkeypatch) -> None:
    env = tmp_path / "oo.env"
    before = f"export OO_DATA_DIR=/media/drive/oo\nexport {dv.ENV_ID}=abc\n"
    env.write_text(before, encoding="utf-8")
    monkeypatch.setattr(dl, "env_file_path", lambda: env)

    def no_replace(*_a, **_k):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(dl.os, "replace", no_replace)
    dv.forget_volume_id()  # logs, never raises
    assert env.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["oo.env"]


# --- P6: the bulletin links only to http, https and mailto ---------------------------------------
@pytest.mark.parametrize(
    "url",
    ["javascript:alert`1`", "JavaScript:fetch`//x`", "data:text/html,x", "vbscript:x", "java\tscript:x", " javascript:x", "file:///etc/passwd", "no-scheme", ""],
)
def test_a_link_the_reader_cannot_follow_safely_is_not_a_link(url: str) -> None:
    lines = _article_lines({"title": "Headline", "url": url}, Translator("en"))
    assert "](" not in lines[0]
    assert "href" not in _inline(lines[0])


@pytest.mark.parametrize("url", ["https://example.org/a?b=1", "http://example.org/", "mailto:desk@example.org"])
def test_ordinary_links_stay_links(url: str) -> None:
    lines = _article_lines({"title": "Headline", "url": url}, Translator("en"))
    assert f"[Headline]({url})" in lines[0]
    assert f'href="{url}"' in _inline(lines[0])


@pytest.mark.parametrize("url", [None, "https://a.example/"])
def test_a_link_hidden_in_a_title_is_not_a_link(url) -> None:
    """Found by a security read of PR #1949: the title is source text and reaches the same link builder."""
    lines = _article_lines({"title": "[click](javascript:location=name)", "url": url}, Translator("en"))
    assert not [h for h in re.findall(r'href="([^"]*)"', _inline(lines[0])) if "javascript" in h]


# --- P10: a removed author stays removed ---------------------------------------------------------
def test_removing_an_author_takes_the_record_lock(tmp_path, monkeypatch) -> None:
    """``set_trusted`` rewrites the record under its lock; an unlocked unlink can be undone by it."""
    from src.annotations import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    rec = store._imported_dir() / "a1.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text('{"author_id": "a1", "annotations": []}', encoding="utf-8")
    held: list[Path] = []
    real = store.file_lock

    def watching(path, *a, **k):
        held.append(Path(path))
        return real(path, *a, **k)

    monkeypatch.setattr(store, "file_lock", watching)
    assert store.remove_author("a1") is True
    assert held == [rec]
    assert not rec.exists()
