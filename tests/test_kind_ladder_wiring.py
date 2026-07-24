"""C2 (2026-07-24 throughput brief): wire the shipped ``KindLadder`` (S5/§5,
``src/ingest/tor_throughput.py``) as the housekeeping lane's scheduler,
implementing the 2026-06-13 bandwidth PRIORITY LADDER ruling — "commodities/
markets/weather FIRST... recursive crawling ONLY with bandwidth headroom".

Pure, DB-free, network-free: exercises ``src.scheduler.runner``'s pending-kind
selection and ladder-ordering functions directly against injected ``KindLadder``
instances, never the shared module-level singleton (so these tests can never be
coupled to another test's call history).
"""

from __future__ import annotations

from src.ingest.tor_throughput import KindLadder
from src.scheduler.runner import (
    _LANE_FLOORS,
    _LANE_RATES,
    _lane_kind_order,
    _lane_pending_kinds,
)
from src.scheduler.settings import SchedulerSettings


def _fresh_ladder() -> KindLadder:
    return KindLadder(rates=dict(_LANE_RATES), floors=dict(_LANE_FLOORS))


# --------------------------------------------------------------------------- #
# _lane_pending_kinds: each ride-along's OWN settings toggle/budget is its
# off-switch -- never the ladder's job.
# --------------------------------------------------------------------------- #


def test_default_settings_makes_every_kind_pending():
    # §8 (C3): the crawl supplement is now ALSO on by default; C15's archive
    # backfill ride-along is on by default too (queue-driven -- a no-op when
    # nothing has ever qualified), so a fresh SchedulerSettings has every kind
    # pending.
    pending = _lane_pending_kinds(SchedulerSettings())
    assert pending == {
        "markets", "calendar", "law", "hazards",
        "world_discovery", "qualification", "country_data", "crawl", "backfill",
    }


def test_markets_mode_excludes_the_markets_kind():
    # markets MODE already runs its own import inside run_scrape_once.
    s = SchedulerSettings(mode="markets")
    assert "markets" not in _lane_pending_kinds(s)


def test_toggles_and_zero_budgets_exclude_their_kind():
    # auto_track_law/auto_import_calendars have no real SchedulerSettings field
    # today (a pre-existing dead toggle, unchanged by this slice -- both
    # ride-alongs always read True via getattr's fallback); auto_track_signals,
    # crawl_supplement, and the per-pass budgets (incl. C15's archive_backfill_
    # per_pass) ARE real fields.
    s = SchedulerSettings(
        auto_track_signals=False,
        world_discovery_per_pass=0,
        qualification_per_pass=0,
        country_data_per_pass=0,
        crawl_per_pass=0,
        archive_backfill_per_pass=0,
    )
    pending = _lane_pending_kinds(s)
    assert pending == {"markets", "calendar", "law"}


# --------------------------------------------------------------------------- #
# _lane_kind_order: priority ordering, with the mandatory safety net (ordering
# must never become exclusion for a kind whose OWN settings said "run me").
# --------------------------------------------------------------------------- #


def test_lane_kind_order_never_drops_a_pending_kind():
    """The safety net: even an UNKNOWN kind name (not in the ladder's rate
    table at all -- a hypothetical naming-drift bug) is never silently
    dropped, only unordered by the ladder."""
    ladder = _fresh_ladder()
    pending = {"markets", "law", "an-unknown-future-kind"}
    order = _lane_kind_order(pending, ladder=ladder)
    assert set(order) == pending
    assert len(order) == len(pending)  # no duplicates


def test_higher_priority_kind_is_served_before_a_floor_only_kind():
    """The 2026-06-13 bandwidth ladder ruling: commodities/markets first,
    the discovery/qualification/country-data ride-alongs (floor-only,
    weight 0.2) later, and the §8 crawl-supplement rung (C3, floor 0.05)
    LAST of all. A FRESH ladder ties on passv=0, broken by descending
    weight -- markets (rate 5.0, the highest) must come before qualification
    (floor 0.2), and qualification before crawl (the lowest floor)."""
    ladder = _fresh_ladder()
    full = set(_LANE_RATES)
    order = _lane_kind_order(full, ladder=ladder)
    assert order.index("markets") < order.index("qualification"), order
    assert order.index("hazards") < order.index("world_discovery"), order
    assert order.index("qualification") < order.index("crawl"), order


def test_no_kind_starves_across_many_invocations():
    """Ordering != exclusion: a floor-only kind (qualification, weight 0.2 vs
    markets' 5.0) must still appear in EVERY invocation's order, never
    starved out just because it is served last -- proven over many repeated
    full-pending draws against the SAME persistent ladder (the production
    shape: one ladder instance across many real pass invocations). Includes
    the §8 crawl rung (the lowest floor of all), the case the "lowest rung"
    ruling most needs proven -- lowest priority is never the same as never."""
    ladder = _fresh_ladder()
    full = set(_LANE_RATES)
    for _ in range(20):
        order = _lane_kind_order(full, ladder=ladder)
        assert "qualification" in order, order
        assert "markets" in order, order
        assert "crawl" in order, order
        assert set(order) == full


def test_zero_weight_kind_is_a_no_op_at_the_ladder_level():
    """A kind the LADDER itself was configured with no priority and no floor
    (rate=0, floor=0 -- distinct from a settings toggle/budget of 0, which
    already excludes a kind from ``pending`` before the ladder ever sees it)
    is never served by ``next_kind`` -- the ladder's own documented contract
    (re-pinned here at the wiring layer, not just in tor_throughput's own
    selftest)."""
    ladder = KindLadder(rates={"markets": 1.0, "off_kind": 0.0}, floors={"off_kind": 0.0})
    served = {ladder.next_kind({"markets", "off_kind"}) for _ in range(5)}
    assert served == {"markets"}
    assert ladder.next_kind({"off_kind"}) is None


def test_crawl_rung_is_reserved_at_the_lowest_priority():
    """§8 crawl-by-default (C3): the crawl-supplement's ladder entry sits at
    the second-lowest floor of every registered kind (only C15's backfill
    rung sits lower -- see the next test) -- pin the table shape here so a
    future edit cannot silently drop the "lowest rung" property the
    crawl-by-default ruling requires."""
    assert _LANE_RATES["crawl"] == 0.0
    others = [v for k, v in _LANE_FLOORS.items() if k not in ("crawl", "backfill") and v > 0]
    assert 0 < _LANE_FLOORS["crawl"] < min(others)


def test_backfill_rung_is_the_true_lowest_priority_of_all():
    """C15 (2026-07-24 throughput brief, S-E slice 2): the archive-backfill
    ride-along must sit BELOW even the crawl-supplement rung -- a newly-
    qualified source's multi-hundred-page history must never compete with
    live collection, INCLUDING the crawl rung, for bandwidth."""
    assert _LANE_RATES["backfill"] == 0.0
    assert 0 < _LANE_FLOORS["backfill"] < _LANE_FLOORS["crawl"]
    assert _LANE_FLOORS["backfill"] < min(
        v for k, v in _LANE_FLOORS.items() if k != "backfill" and v > 0
    )
