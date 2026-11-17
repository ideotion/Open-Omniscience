"""A robots.txt that could not be READ is not the host's rule (field test 2026-11-14, row 72).

The Law table badged every robots refusal "robots-blocked", including the fail-closed refusal
when robots.txt could not be read at all (``RobotsUnavailable``: the host's 401/403, a 5xx, or
no answer, which a DNS failure on the operator's own machine also gives). On the field test
``laws-lois.justice.gc.ca``'s robots.txt was "unreachable" and its documents read as blocked by
the publisher, which nothing had measured. They now read "robots.txt not readable"; the fetch
is still refused (robots fail-closed is unchanged), and the stored message stays on hover.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.api.law import _verdict_of
from tests.js_source_helper import function_source, object_literal, read_static

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"


def test_the_two_robots_refusals_are_told_apart():
    unread = "fetch error: robots.txt for https://laws-lois.justice.gc.ca could not be determined (unreachable); refusing to fetch"
    assert _verdict_of(unread) == "robots_unread"
    assert _verdict_of(unread.replace("(unreachable)", "(refused)")) == "robots_unread"
    assert _verdict_of(unread.replace("(unreachable)", "(server_error)")) == "robots_unread"
    assert _verdict_of("fetch error: robots.txt disallows https://x.test/a") == "robots_blocked"
    # A redirect hop's disallow keeps its verdict too.
    assert _verdict_of("fetch error: robots.txt disallows https://y.test/b (a redirect hop)") == "robots_blocked"


def test_the_label_is_keyed_in_all_twelve_languages():
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for path in files:
        assert json.loads(path.read_text(encoding="utf-8")).get("robots.txt not readable"), path.stem


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_law_table_badges_it_as_a_warning_with_its_own_words():
    js = read_static("app-gov-law.js")
    script = (
        "const window = {};\n"
        "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n"
        "const _LAW_VERDICT_PILL = " + object_literal(js, "_LAW_VERDICT_PILL") + ";\n"
        + function_source(js, "lawVerdictBadge")
        + "\nconsole.log(lawVerdictBadge({verdict: 'robots_unread', last_status: 'fetch error: robots.txt for h could not be determined (unreachable); refusing to fetch'}));"
        + "\nconsole.log(lawVerdictBadge({verdict: 'robots_blocked', last_status: 'fetch error: robots.txt disallows h'}));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout.splitlines()  # noqa: S607
    assert 'class="pill warn"' in out[0] and ">robots.txt not readable<" in out[0]
    assert "could not be determined (unreachable)" in out[0], "the stored reason stays on hover"
    assert ">robots-blocked<" in out[1]
