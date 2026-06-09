"""
Market ingestion: fetch a page ethically, extract one price by rule, store it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Per the product decision ("capture raw + per-source price rules"): every market
page is fetched through the one ethical path and, when it yields prose, captured
as a normal Article (raw, searchable, in the unified corpus). Independently, if a
rule extracts a real number, a single :class:`CommodityPrice` point is stored for
that day -- feeding the existing /api/commodities charts + news correlation. A
rule that matches nothing stores NO price and records why; it never guesses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.database.models import CommodityPrice, MarketExtractionRule
from src.ingest import (
    EthicalFetcher,
    FetchError,
    RobotsDisallowed,
    RobotsUnavailable,
)
from src.ingest.pipeline import IngestResult, store_fetched
from src.markets.extract import extract_price

_LOG = logging.getLogger(__name__)


@dataclass
class RuleOutcome:
    rule_id: int
    symbol: str
    status: str  # stored_price | duplicate_price | no_match | fetch_failed | blocked_robots | robots_unavailable
    value: float | None = None
    observed_on: str | None = None
    reason: str | None = None
    raw_capture: str | None = None  # IngestResult of the raw article capture, if attempted

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "symbol": self.symbol,
            "status": self.status,
            "value": self.value,
            "observed_on": self.observed_on,
            "reason": self.reason,
            "raw_capture": self.raw_capture,
        }


def _record(rule: MarketExtractionRule, status: str) -> None:
    rule.last_run_at = datetime.now(UTC)
    rule.last_status = status[:255]


def run_rule(
    session: Session, rule: MarketExtractionRule, *, fetcher: EthicalFetcher
) -> RuleOutcome:
    """Fetch the rule's page and store one price point (and a raw capture) for today.

    Idempotent per day: a second run on the same date is reported as a duplicate
    rather than appending another point for the same (symbol, market, date).
    """
    try:
        fetched = fetcher.fetch(rule.url, require_html=True)
    except RobotsDisallowed as exc:
        _record(rule, f"blocked_robots: {exc}")
        return RuleOutcome(rule.id, rule.symbol, "blocked_robots", reason=str(exc))
    except RobotsUnavailable as exc:
        _record(rule, f"robots_unavailable: {exc}")
        return RuleOutcome(rule.id, rule.symbol, "robots_unavailable", reason=str(exc))
    except FetchError as exc:
        _record(rule, f"fetch_failed: {exc}")
        return RuleOutcome(rule.id, rule.symbol, "fetch_failed", reason=str(exc))

    # Best-effort raw capture into the corpus (only stores if a real article body
    # is present; pure data pages simply yield extract_failed, which is fine).
    raw = store_fetched(session, rule.source, fetched)
    raw_capture = raw.result.value

    result = extract_price(
        fetched.content,
        selector=rule.selector,
        attribute=rule.attribute,
        value_regex=rule.value_regex,
    )
    if not result.ok:
        _record(rule, f"no_match: {result.reason}")
        session.commit()
        return RuleOutcome(
            rule.id, rule.symbol, "no_match", reason=result.reason, raw_capture=raw_capture
        )

    observed_on = fetched.fetched_at.date()
    exists = (
        session.query(CommodityPrice.id)
        .filter_by(symbol=rule.symbol, market=rule.market, observed_on=observed_on)
        .first()
    )
    if exists:
        _record(rule, f"duplicate_price: {result.value} already recorded for {observed_on}")
        session.commit()
        return RuleOutcome(
            rule.id,
            rule.symbol,
            "duplicate_price",
            value=result.value,
            observed_on=observed_on.isoformat(),
            raw_capture=raw_capture,
        )

    session.add(
        CommodityPrice(
            symbol=rule.symbol,
            market=rule.market,
            observed_on=observed_on,
            price=result.value,
            currency=rule.currency,
            unit=rule.unit,
            source=f"market-rule:{rule.id}:{fetched.final_url}",
        )
    )
    _record(rule, f"stored_price: {result.value} {rule.currency}/{rule.unit} on {observed_on}")
    session.commit()
    return RuleOutcome(
        rule.id,
        rule.symbol,
        "stored_price",
        value=result.value,
        observed_on=observed_on.isoformat(),
        raw_capture=raw_capture,
    )


def run_rules(
    session: Session, rules: list[MarketExtractionRule], *, fetcher: EthicalFetcher
) -> dict:
    """Run a batch of rules and return an aggregated tally + per-rule outcomes."""
    tally: dict[str, int] = {}
    outcomes: list[dict] = []
    for rule in rules:
        try:
            outcome = run_rule(session, rule, fetcher=fetcher)
        except Exception as exc:  # noqa: BLE001 - one bad rule must not abort the batch
            _LOG.warning("market rule %s failed", rule.id, exc_info=True)
            session.rollback()
            outcome = RuleOutcome(rule.id, rule.symbol, "error", reason=str(exc))
        tally[outcome.status] = tally.get(outcome.status, 0) + 1
        outcomes.append(outcome.to_dict())
    return {
        "tally": tally,
        "outcomes": outcomes,
        "prices_stored": tally.get("stored_price", 0),
        "raw_capture_counts": _count_raw(outcomes),
    }


def _count_raw(outcomes: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for o in outcomes:
        rc = o.get("raw_capture")
        if rc:
            counts[rc] = counts.get(rc, 0) + 1
    # Surface the canonical IngestResult labels even when zero, for a stable shape.
    for r in IngestResult:
        counts.setdefault(r.value, counts.get(r.value, 0))
    return counts
