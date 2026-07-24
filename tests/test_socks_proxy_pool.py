"""
C10 (2026-07-24 throughput brief, S-C): an OPERATOR-RUN pool of SOCKS
endpoints -- raising collect_parallelism (C9) hits a single Tor client's own
circuit ceiling first; a pool of several independently-run Tor instances is
the lever that scales past it. The app never spawns these processes; it only
shards HOSTS across a list the operator already runs.

Covers: the pure sharding/validation helpers, SafetySettings round-trip +
ALL-TOR-OR-REFUSED validation (never a downgrade, never a partial apply),
make_fetcher wiring, and EthicalFetcher end-to-end (stable host->endpoint
mapping across separate instances, per-host circuit isolation preserved on
top of the sharded endpoint, and the C8 remote-resolve skip correctly
consulting the SHARDED member's scheme rather than the now-empty single
``proxy`` field).
"""

from __future__ import annotations

import socket

import pytest

import src.ingest as ingest_mod
from src.ingest import EthicalFetcher
from src.safety.fetcher import (
    is_socks_proxy,
    shard_host_to_proxy,
    validate_socks_pool,
)
from src.safety.settings import SafetySettingsError, load_settings, save_settings


# --------------------------------------------------------------------------- #
# Pure helpers.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("socks5h://127.0.0.1:9050", True),
        ("socks4a://127.0.0.1:9050", True),
        ("socks5://127.0.0.1:9050", True),
        ("socks4://127.0.0.1:9050", True),
        ("http://127.0.0.1:8118", False),
        ("https://127.0.0.1:8118", False),
        ("", False),
        (None, False),
        ("not-a-url", False),
    ],
)
def test_is_socks_proxy(url, expected):
    assert is_socks_proxy(url) is expected


def test_shard_host_to_proxy_is_stable_across_repeated_calls():
    pool = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051", "socks5h://127.0.0.1:9052"]
    picks = {shard_host_to_proxy("news.example", pool) for _ in range(20)}
    assert picks == {shard_host_to_proxy("news.example", pool)}  # always the same one


def test_shard_host_to_proxy_distributes_across_a_pool():
    """Sanity, not a strict guarantee: a handful of distinct hosts should not
    ALL land on the exact same pool member (that would defeat the pool's whole
    purpose of spreading load across several Tor clients)."""
    pool = [f"socks5h://127.0.0.1:{9050 + i}" for i in range(5)]
    hosts = [f"host{i}.example" for i in range(30)]
    picked = {shard_host_to_proxy(h, pool) for h in hosts}
    assert len(picked) > 1


def test_shard_host_to_proxy_raises_on_empty_pool():
    with pytest.raises(ValueError):
        shard_host_to_proxy("news.example", [])


def test_validate_socks_pool_accepts_an_all_socks_list():
    validate_socks_pool(["socks5h://127.0.0.1:9050", "socks4a://127.0.0.1:9051"])  # no raise


def test_validate_socks_pool_refuses_on_the_first_non_socks_entry():
    with pytest.raises(ValueError, match="not a SOCKS proxy"):
        validate_socks_pool(
            ["socks5h://127.0.0.1:9050", "http://127.0.0.1:8118", "socks5h://127.0.0.1:9052"]
        )


# --------------------------------------------------------------------------- #
# SafetySettings: round-trip + ALL-TOR-OR-REFUSED (never a downgrade, never
# partially applied).
# --------------------------------------------------------------------------- #


def test_http_proxies_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_HTTP_PROXIES", raising=False)
    save_settings(
        {"fetch_mode": "protected", "http_proxies": ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]}
    )
    loaded = load_settings()
    assert loaded.http_proxies == ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]
    assert loaded.is_protected is True


def test_protected_mode_is_satisfiable_by_a_pool_alone_without_http_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_HTTP_PROXIES", raising=False)
    # No http_proxy set at all -- the pool alone must satisfy "protected mode
    # requires a transport".
    save_settings({"http_proxies": ["socks5h://127.0.0.1:9050"]})
    save_settings({"fetch_mode": "protected"})  # must NOT raise
    assert load_settings().http_proxies == ["socks5h://127.0.0.1:9050"]


def test_a_non_socks_entry_refuses_the_whole_pool_update_never_a_partial_apply(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_HTTP_PROXIES", raising=False)
    save_settings({"http_proxies": ["socks5h://127.0.0.1:9050"]})  # a good baseline first
    with pytest.raises(SafetySettingsError, match="not a SOCKS proxy"):
        save_settings(
            {"http_proxies": ["socks5h://127.0.0.1:9060", "http://127.0.0.1:8118"]}
        )
    # NEGATIVE-SPACE: the bad update must be REFUSED entirely -- the prior good
    # pool stays in place, never partially overwritten with the bad list.
    assert load_settings().http_proxies == ["socks5h://127.0.0.1:9050"]


def test_http_proxies_env_override_is_comma_separated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "OO_HTTP_PROXIES", "socks5h://127.0.0.1:9050, socks5h://127.0.0.1:9051"
    )
    s = load_settings()
    assert s.http_proxies == ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]


def test_http_proxies_must_be_a_list_of_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with pytest.raises(SafetySettingsError):
        save_settings({"http_proxies": "socks5h://127.0.0.1:9050"})  # a bare string, not a list
    with pytest.raises(SafetySettingsError):
        save_settings({"http_proxies": [1, 2, 3]})


# --------------------------------------------------------------------------- #
# make_fetcher wiring: the pool takes precedence over the single http_proxy.
# --------------------------------------------------------------------------- #


def test_make_fetcher_passes_the_pool_when_configured(monkeypatch):
    from types import SimpleNamespace

    from src.safety import fetcher as fetcher_mod

    monkeypatch.setattr(
        fetcher_mod,
        "load_settings",
        lambda: SimpleNamespace(
            is_protected=True,
            http_proxy="socks5h://127.0.0.1:9999",  # must be IGNORED once a pool exists
            http_proxies=["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"],
        ),
    )
    f = fetcher_mod.make_fetcher()
    assert f.proxy is None
    assert f._proxy_pool == ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]


def test_make_fetcher_falls_back_to_the_single_proxy_when_no_pool(monkeypatch):
    from types import SimpleNamespace

    from src.safety import fetcher as fetcher_mod

    monkeypatch.setattr(
        fetcher_mod,
        "load_settings",
        lambda: SimpleNamespace(
            is_protected=True, http_proxy="socks5h://127.0.0.1:9999", http_proxies=[]
        ),
    )
    f = fetcher_mod.make_fetcher()
    assert f.proxy == "socks5h://127.0.0.1:9999"
    assert f._proxy_pool is None


# --------------------------------------------------------------------------- #
# EthicalFetcher end-to-end: construction refuses a bad pool; host->endpoint
# mapping is stable ACROSS separate instances; per-host circuit isolation is
# preserved on top of the sharded endpoint; the C8 remote-resolve skip
# consults the SHARDED member's scheme.
# --------------------------------------------------------------------------- #


def test_construction_refuses_a_pool_containing_a_non_socks_entry():
    """Defence in depth: re-validated at construction, not just at the
    settings-save layer (an older/hand-edited persisted file could bypass it)."""
    with pytest.raises(ValueError, match="not a SOCKS proxy"):
        EthicalFetcher(
            min_interval_s=0.0,
            proxy_pool=["socks5h://127.0.0.1:9050", "http://127.0.0.1:8118"],
        )


def test_host_to_endpoint_mapping_is_stable_across_separate_fetcher_instances():
    pool = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051", "socks5h://127.0.0.1:9052"]
    f1 = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)
    f2 = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)  # a fresh "restart"
    assert f1._isolated_proxies("news.example") is not None
    p1 = f1._effective_base_proxy("news.example")
    p2 = f2._effective_base_proxy("news.example")
    assert p1 == p2, "the same host must map to the same pool endpoint across instances"


def test_per_host_circuit_isolation_is_layered_on_top_of_the_sharded_endpoint():
    pool = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]
    f = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)
    proxies_a = f._isolated_proxies("a.example")
    proxies_b = f._isolated_proxies("b.example")
    assert proxies_a is not None and proxies_b is not None
    # Each carries per-host SOCKS auth (distinct credentials), even when two
    # hosts happen to shard onto the SAME pool member.
    assert proxies_a["https"] != proxies_b["https"] or (
        shard_host_to_proxy("a.example", pool) != shard_host_to_proxy("b.example", pool)
    )
    assert "@" in proxies_a["https"]  # isolation credentials were injected


def test_isolated_proxies_returns_the_sharded_endpoint_even_with_isolation_off():
    pool = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]
    f = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)
    f._stream_isolation = False
    expected = shard_host_to_proxy("news.example", pool)
    assert f._isolated_proxies("news.example") == {"http": expected, "https": expected}


def test_guard_target_remote_resolve_skip_consults_the_sharded_members_scheme(monkeypatch):
    """C8's skip logic must consult the POOL's per-host member, not the (now
    empty) single ``self.proxy`` -- else pooling would silently defeat the C8
    optimisation even when every pool member is remote-resolving."""

    def fake_getaddrinfo(host, *a, **k):
        raise AssertionError("must never resolve locally under an all-socks5h pool")

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    pool = ["socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9051"]
    f = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)
    f._guard_target("public.example")  # must not raise, must not resolve


def test_guard_target_still_resolves_locally_under_a_local_resolving_pool(monkeypatch):
    """The critical verify-at-build negative-space case, ported to pools: a
    socks5:// (no "h") pool member must NOT skip local resolution."""
    calls = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    pool = ["socks5://127.0.0.1:9050", "socks5://127.0.0.1:9051"]  # local-resolving
    f = EthicalFetcher(min_interval_s=0.0, proxy_pool=pool)
    f._guard_target("public.example")
    assert calls["n"] == 1
