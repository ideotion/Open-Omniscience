"""PRH-31: a daily sparkline drawn on its WINDOW rather than on its own points.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT, as `docs/plans/2026-09-06-repo-analysis/PROMPT_15_ui-browser-backlog.md`
records it: "``_window_daily_series`` omits zero-count days, so the index axis
compresses -- day 1 and day 5 render adjacent". Both daily-series producers omit
those days on purpose (they are honest about the DATA), and ``dashChartSvg``
places points by INDEX unless given a window -- so the honesty of one becomes a
false picture in the other. A reader sees a run where there was a gap.

THE REPAIR IS NOT THE ONE THE BACKLOG SUGGESTED, and the reason is in the
renderer. The backlog proposes zero-FILLING ("for keyword mentions an absent day
is a real zero"). The same renderer already carries the opposite convention on
the same surface -- it prints "The line breaks where nothing was recorded -- a gap
is not a zero" -- and it already implements a real calendar axis (``opts.t0`` /
``opts.t1``) built for exactly this case. Filling zeros would put two conventions
on one quantity, which is how two surfaces come to disagree about one thing; and
it would quietly retire invariant #16's sparse-series rule, because a zero-filled
30-day window always carries 31 points and the n<10 bar mode could never fire
again. So the points are left exactly as they are, and the WINDOW travels beside
them.

THE WINDOW COMES FROM THE SERVER, and from the same ``today`` the series was
sliced with. A browser that recomputed ``now - days`` would draw a window one day
out whenever the two clocks straddle midnight or sit in different zones, and --
worse -- an axis fitted to the DATA silently rescales whenever the newest
observation is older than the window, hiding exactly the quiet tail the rate
figure beside it is reporting.

The geometry itself is proven in ``tests/sparkline_axis_node_test.js``, which
drives the REAL ``dashChartSvg`` extracted from the shipped modules, and which
asserts the two placements genuinely differ before asserting which one is right.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_present,
    python_function_source,
    read_static,
)

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_renderer_places_a_gapped_series_on_real_time() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "sparkline_axis_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "7 passed" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# The server states the axis it drew
# ---------------------------------------------------------------------------

def test_series_window_is_the_window_not_the_data() -> None:
    """It must describe ``[today - days, today]`` whatever the points happen to
    span -- that is the whole point of asking the server for it."""
    from src.analytics.supergroup_stats import series_window

    anchor = date(2026, 9, 9)
    got = series_window(7, today=anchor)
    assert got == {"start": "2026-09-02", "end": "2026-09-09"}, got
    # A 1-day window is a real preset (the 24h trending window).
    assert series_window(1, today=anchor)["start"] == "2026-09-08"


def test_series_window_and_the_series_share_one_clock() -> None:
    """Two unsynchronised ``date.today()`` calls either side of midnight describe
    different windows, and the chart is then drawn on an axis its own points do
    not belong to. Both call sites must thread ONE date through."""
    api_src = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    block = api_src[api_src.index("if series_top > 0:"):]
    block = block[: block.index("# Honesty envelope")]
    assert "today = _date.today()" in block, "the supergroups path must anchor one date"
    for call in ("daily_series(db, gids, days=window_days, today=today)",
                 "series_window(window_days, today=today)"):
        assert call in block, f"{call} must take the anchored date, not its own"

    q_src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    tw = python_function_source(q_src, "trending_windows")
    assert "series_today = date.today()" in tw, (
        "the trending-windows path must anchor one date for the series AND its axis"
    )
    assert "series_window(wdays, today=series_today)" in tw
    assert "today=series_today" in tw, "the series itself must be sliced with that date"


def test_the_window_series_slicer_accepts_an_injected_today() -> None:
    """Without it the caller cannot make the two agree at all."""
    import inspect

    from src.analytics.queries import _window_daily_series

    assert "today" in inspect.signature(_window_daily_series).parameters


# ---------------------------------------------------------------------------
# Every renderer that draws a gappable series asks for a real axis
# ---------------------------------------------------------------------------

def test_the_two_daily_count_sparklines_use_the_servers_window() -> None:
    ins = read_static("app-insights.js")
    assert_present(ins, "g.series_window",
                   why="the supergroup sparkline must be drawn on the window the "
                       "server sliced its series against")
    home = read_static("app-home.js")
    assert_present(home, "wk.series_window",
                   why="Home's trend strip reads the same payload shape")
    assert_present(home, "{t0: _hw.start, t1: _hw.end}",
                   why="the axis has to reach dashChartSvg, not merely be read")
    corpus = read_static("app-corpus.js")
    assert_present(corpus, "w.series_window",
                   why="the Insights trend-windows sparklines carry the same defect")
    assert_present(corpus, "dashChartSvg(pts, \"\", axis)",
                   why="the resolved axis must be the one actually passed")


def test_the_two_series_without_a_server_window_use_their_own_span() -> None:
    """Neither endpoint states a window of its own, so the honest axis is the span
    the data actually covers -- inventing one would be worse than using it."""
    gov = read_static("app-gov-law.js")
    assert_present(gov, 't0: pts[0].year + "-01-01"',
                   why="a missing YEAR is the commonest gap in an official series")
    lib = read_static("app-library.js")
    assert_present(lib, "t0: series[0] && series[0].t",
                   why="a recorded metric can miss days when the recorder was not running")


def test_no_daily_series_renderer_was_left_on_index_placement() -> None:
    """The sweep, not a spot check: every dashChartSvg call over a TIME series must
    now carry an axis. A call left behind is a chart still compressing its gaps."""
    import re

    offenders = []
    for name in ("app-insights.js", "app-home.js", "app-corpus.js",
                 "app-library.js", "app-gov-law.js", "app-markets.js"):
        src = read_static(name)
        for m in re.finditer(r"dashChartSvg\(", src):
            # Slice the call's own argument list, brace/paren matched.
            depth, i = 0, m.end() - 1
            while i < len(src):
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            call = src[m.start():i + 1]
            if "observed_on" not in call:
                continue          # not a time series (the markets caller builds pts above)
            if "t0" not in call:
                offenders.append(f"{name}: {call[:90]}")
    assert not offenders, (
        "these time-series charts still place their points by index:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# End to end, against the real endpoints
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def insights_client(tmp_path_factory):
    """A corpus that actually produces a SERIES.

    The first cut of this fixture created an empty store, so
    ``[g for g in supergroups if "series" in g]`` was empty and the loop below
    asserted nothing at all -- green, and blind to the field it exists to guard.
    The corpus is seeded, and the tests assert they found something before they
    assert anything about it.

    Module-scoped and idempotent because ``models.engine`` binds once per
    process: a function-scoped fixture re-pointing OO_DATA_DIR gets the store the
    first import already opened, and its second insert collides.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OO_DATA_DIR", str(tmp_path_factory.mktemp("spark_axis")))
        mp.setenv("OO_DB_PLAINTEXT", "1")
        mp.setenv("OO_NO_SCHEDULER", "1")
        from fastapi.testclient import TestClient

        from src.api.main import app
        from src.database.models import (
            Article,
            Base,
            Keyword,
            KeywordMention,
            KeywordSuperGroup,
            KeywordSuperGroupMember,
            Source,
            engine,
            get_session,
        )

        Base.metadata.create_all(engine)
        session = get_session()
        try:
            src = session.query(Source).filter_by(domain="axis-fixture.example").one_or_none()
            if src is None:
                src = Source(name="Axis fixture", domain="axis-fixture.example",
                             enabled=True, priority=1)
                session.add(src)
                session.commit()
            kw = session.query(Keyword).filter_by(normalized_term="turbine").one_or_none()
            if kw is None:
                kw = Keyword(term="turbine", normalized_term="turbine", language="en",
                             mention_count=9, article_count=2)
                session.add(kw)
                session.commit()
            # Two observed days with a HOLE between them -- the shape the whole
            # finding is about.
            today = date.today()
            for offset, n in ((6, 4), (1, 5)):
                url = f"https://axis-fixture.example/{offset}"
                art = session.query(Article).filter_by(url=url).one_or_none()
                if art is None:
                    art = Article(url=url, canonical_url=url, source_id=src.id,
                                  title=f"day -{offset}", content="x", hash=url)
                    session.add(art)
                    session.commit()
                if session.query(KeywordMention).filter_by(
                    keyword_id=kw.id, article_id=art.id
                ).one_or_none() is None:
                    session.add(KeywordMention(
                        keyword_id=kw.id, article_id=art.id, count=n,
                        observed_on=today - timedelta(days=offset), source_id=src.id))
            session.commit()
            sg = session.query(KeywordSuperGroup).filter_by(name="Axis fixture group").one_or_none()
            if sg is None:
                sg = KeywordSuperGroup(name="Axis fixture group")
                session.add(sg)
                session.commit()
            if session.query(KeywordSuperGroupMember).filter_by(
                supergroup_id=sg.id, normalized_term="turbine"
            ).one_or_none() is None:
                session.add(KeywordSuperGroupMember(supergroup_id=sg.id,
                                                    normalized_term="turbine", ring_id=None))
                session.commit()
        finally:
            session.close()
        with TestClient(app) as client:
            yield client


def test_the_supergroups_payload_carries_its_axis_when_it_carries_a_series(
    insights_client,
) -> None:
    body = insights_client.get("/api/insights/supergroups?series_top=3&window_days=7").json()
    rows = [g for g in body["supergroups"] if "series" in g]
    assert rows, (
        "the fixture must produce at least one group carrying a series, or every "
        "assertion below is vacuous -- which is exactly what the first cut of this "
        "test was, against an empty store"
    )
    for row in rows:
        assert "series_window" in row, f"{row['name']} has a series but no axis"
        win = row["series_window"]
        assert win["end"] == date.today().isoformat()
        assert win["start"] == (date.today() - timedelta(days=7)).isoformat()
    # And a payload that carries NO series must not carry an axis either: an axis
    # for a chart nobody drew is a field that can only go stale.
    plain = insights_client.get("/api/insights/supergroups").json()
    assert all("series_window" not in g for g in plain["supergroups"])


def test_the_trending_windows_payload_carries_one_axis_per_window(
    insights_client,
) -> None:
    body = insights_client.get("/api/insights/trending-windows?limit=2&series_top=2").json()
    assert body["windows"], "no windows returned -- nothing below would be checked"
    for window in body["windows"]:
        assert "series_window" in window, f"{window['label']} has no axis"
        win = window["series_window"]
        assert win["end"] == date.today().isoformat()
        assert win["start"] == (
            date.today() - timedelta(days=window["window_days"])
        ).isoformat(), (
            f"{window['label']}'s axis must span its OWN window_days, not another's"
        )
    plain = insights_client.get("/api/insights/trending-windows?limit=2").json()
    assert all("series_window" not in w for w in plain["windows"])
