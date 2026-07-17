"""
Investigation-recipe producers — space-time scenario cards (0.0.8 WP8 / RM-20).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each producer turns one space-time scenario (docs/FUTURE_DEVELOPMENTS.md, "Ten
space-time scenario cards") into a Home card with a ``recipe`` — a one-click
deep-link into the ``/investigate`` dashboard, opened in a new browser tab.

The first three are the ones whose data already flows (DB-only — a producer
must NEVER make a network call):

  * promises_due     — a *future* date mentioned in an article has now arrived.
  * edit_war_burst   — a tracked Wikipedia page's revisions are bursting.
  * region_gone_quiet— a country your corpus usually covers went quiet.

Two of the originally sketched three were honestly swapped out: *silent
disasters* needs persisted hazard events (the hazards relay is fetch-on-render,
nothing stored) and *law takes effect* needs an effective-date column on
LawDocument — both parked until their data is modelled.

Operators can switch recipes off individually (Settings → recipes_disabled);
a disabled producer returns no cards.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.briefing.card import Card

_LOG = logging.getLogger(__name__)

_MAX_CARDS_PER_RECIPE = 3


def _disabled(name: str) -> bool:
    try:
        from src.config.app_settings import load_settings

        return name in (load_settings().recipes_disabled or [])
    except Exception:  # noqa: BLE001 - settings must never take down the briefing
        return False


# --------------------------------------------------------------------------- #
#  Promises due — a future date mentioned in an article has now arrived
# --------------------------------------------------------------------------- #


def promises_due(session) -> list[Card]:
    """Scenario: *promises-due review*. An article mentioned a date that was in
    the FUTURE when the article was published (a promise, a deadline, a planned
    reopening). That date has now arrived (within the last 7 days): time to ask
    what happened."""
    if _disabled("promises_due"):
        return []
    from src.database.models import Article, ArticleMentionedDate

    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=7)

    rows = (
        session.query(ArticleMentionedDate, Article)
        .join(Article, ArticleMentionedDate.article_id == Article.id)
        .filter(
            ArticleMentionedDate.status != "rejected",
            ArticleMentionedDate.mentioned_on >= window_start,
            ArticleMentionedDate.mentioned_on <= today,
            Article.published_at.isnot(None),
        )
        .order_by(ArticleMentionedDate.mentioned_on.desc())
        .limit(50)
        .all()
    )

    cards: list[Card] = []
    for tag, article in rows:
        # only dates that were *future* when the article was written are promises
        if tag.mentioned_on <= article.published_at.date():
            continue
        lead_days = (tag.mentioned_on - article.published_at.date()).days
        cards.append(
            Card(
                type="recipe_promise",
                title=f"A promised date has arrived: {tag.mentioned_on.isoformat()}",
                summary=(
                    f"“{article.title}” ({article.published_at.date().isoformat()}) pointed "
                    f"{lead_days} days ahead to {tag.mentioned_on.isoformat()} — that date is "
                    f"now here. Worth checking what actually happened."
                ),
                bucket="watch",
                signal={
                    "metric": "lead_days",
                    "value": lead_days,
                    "promised_date": tag.mentioned_on.isoformat(),
                    "tag_status": tag.status,
                },
                method=(
                    "date tags extracted from article text (explicit and publication-anchored "
                    "dates), kept where the date was later than the article's publication date "
                    "and falls in the last 7 days"
                ),
                caveat=(
                    "A mentioned future date is not always a promise (it may be a citation or "
                    "a schedule note) — read the snippet; candidate tags are unconfirmed "
                    "extractions."
                ),
                evidence=[
                    {
                        "title": article.title,
                        "url": article.url,
                        "source": getattr(article.source, "name", None),
                        "snippet": tag.snippet,
                    }
                ],
                n=1,
                key=f"{article.id}:{tag.mentioned_on.isoformat()}",
                recipe={
                    "view": "promise",
                    "params": {
                        "article_id": article.id,
                        "date": tag.mentioned_on.isoformat(),
                        "title": (article.title or "")[:120],
                    },
                },
            )
        )
        if len(cards) >= _MAX_CARDS_PER_RECIPE:
            break
    return cards


# --------------------------------------------------------------------------- #
#  Edit-war seismograph — a tracked Wikipedia page's revisions are bursting
# --------------------------------------------------------------------------- #

_BURST_MIN_RECENT = 6  # revisions in the last 7 days
_BURST_MIN_RATIO = 3.0  # vs the prior 28-day weekly rate


def edit_war_burst(session) -> list[Card]:
    """Scenario: *edit-war seismograph*. A page you track is being edited far
    faster than its own recent baseline — its public record is being fought
    over right now."""
    if _disabled("edit_war_burst"):
        return []
    from sqlalchemy import func

    from src.database.models import WikiPage, WikiRevision

    now = datetime.now(UTC).replace(tzinfo=None)  # revision timestamps are naive UTC
    recent_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=35)

    recent = dict(
        session.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .filter(WikiRevision.timestamp >= recent_start)
        .group_by(WikiRevision.page_id)
        .all()
    )
    prior = dict(
        session.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .filter(WikiRevision.timestamp >= prior_start, WikiRevision.timestamp < recent_start)
        .group_by(WikiRevision.page_id)
        .all()
    )

    cards: list[Card] = []
    for page_id, n_recent in sorted(recent.items(), key=lambda kv: -kv[1]):
        if n_recent < _BURST_MIN_RECENT:
            continue
        prior_n = prior.get(page_id, 0)
        weekly_prior = prior_n / 4.0
        if prior_n == 0:
            # No prior revisions at all in the 28-day baseline -- there is no real rate to
            # divide by. The old `or 0.25` floor FABRICATED a baseline that was never
            # measured (a made-up number surfaced to the user as "prior_weekly_rate").
            # A page dormant for 4+ weeks then getting >=_BURST_MIN_RECENT edits in a
            # week is itself the strongest honest signal available -- surface it
            # directly, with an honestly undefined ratio, rather than invent one.
            ratio = None
        else:
            ratio = n_recent / weekly_prior
            if ratio < _BURST_MIN_RATIO:
                continue
        page = session.query(WikiPage).filter_by(id=page_id).first()
        if page is None:
            continue
        if ratio is None:
            rate_desc = "no revisions at all in the prior 4 weeks"
        else:
            rate_desc = f"about {ratio:.0f}× its prior weekly rate"
        cards.append(
            Card(
                type="recipe_edit_war",
                title=f"Edit burst on “{page.title}”",
                summary=(
                    f"{n_recent} revisions in 7 days on {page.wiki}:{page.title} — "
                    f"{rate_desc}. Its public record is in motion."
                ),
                bucket="investigate",
                signal={
                    "metric": "weekly_revision_ratio",
                    "value": round(ratio, 1) if ratio is not None else None,
                    "recent_7d": n_recent,
                    "prior_weekly_rate": round(weekly_prior, 2),
                },
                method=(
                    "stored revision counts on a tracked page: last 7 days vs the prior "
                    "28-day weekly rate (a ratio, not a significance test)"
                ),
                caveat=(
                    "A burst measures editing activity, not wrongdoing — releases, "
                    "vandalism cleanup and genuine news all cause bursts. Read the diffs."
                ),
                evidence=[
                    {
                        "title": f"{page.wiki}: {page.title}",
                        "url": f"https://{page.wiki}.wikipedia.org/wiki/{page.title}",
                        "source": "tracked Wikipedia page",
                    }
                ],
                n=n_recent,
                key=f"{page.wiki}:{page.title}",
                recipe={
                    "view": "edit-war",
                    "params": {"page_id": page.id, "title": page.title, "wiki": page.wiki},
                },
            )
        )
        if len(cards) >= _MAX_CARDS_PER_RECIPE:
            break
    return cards


# --------------------------------------------------------------------------- #
#  Region gone quiet — a country your corpus usually covers stopped arriving
# --------------------------------------------------------------------------- #

_QUIET_MIN_PRIOR = 8  # articles in the prior 28 days to count as "usually covered"
_QUIET_MAX_RECENT = 1  # at most this many in the last 7 days


def region_gone_quiet(session) -> list[Card]:
    """Scenario: *news-desert / silence lens on your own corpus*. A country that
    reliably produced articles for you has (almost) stopped. Could be source
    rot, could be censorship, could be real quiet — worth finding out which."""
    if _disabled("region_gone_quiet"):
        return []
    from sqlalchemy import func

    from src.database.models import Article

    now = datetime.now(UTC).replace(tzinfo=None)
    recent_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=35)

    prior = dict(
        session.query(Article.country, func.count(Article.id))
        .filter(
            Article.created_at >= prior_start,
            Article.created_at < recent_start,
            Article.country.isnot(None),
            Article.country != "",
        )
        .group_by(Article.country)
        .all()
    )
    recent = dict(
        session.query(Article.country, func.count(Article.id))
        .filter(Article.created_at >= recent_start, Article.country.isnot(None))
        .group_by(Article.country)
        .all()
    )

    cards: list[Card] = []
    for country, n_prior in sorted(prior.items(), key=lambda kv: -kv[1]):
        n_recent = recent.get(country, 0)
        if n_prior < _QUIET_MIN_PRIOR or n_recent > _QUIET_MAX_RECENT:
            continue
        weekly_prior = n_prior / 4.0
        cards.append(
            Card(
                type="recipe_quiet_region",
                title=f"Your coverage of “{country}” went quiet",
                summary=(
                    f"{country} averaged ~{weekly_prior:.0f} articles/week over the prior month "
                    f"but produced {n_recent} in the last 7 days. Source rot, a feed change, "
                    f"or real silence — find out which."
                ),
                bucket="undertold",
                signal={
                    "metric": "weekly_articles",
                    "value": n_recent,
                    "prior_weekly_rate": round(weekly_prior, 1),
                    "country": country,
                },
                method=(
                    "stored-article counts per country: last 7 days vs the prior 28-day "
                    "weekly rate (collection volume, nothing else)"
                ),
                caveat=(
                    "This measures *your corpus*, not the region: a dead feed or a source "
                    "outage looks identical to real silence. Check the sources first."
                ),
                evidence=[],
                n=n_prior,
                key=country,
                recipe={
                    "view": "quiet-region",
                    "params": {
                        "country": country,
                        "recent_7d": n_recent,
                        "prior_weekly": round(weekly_prior, 1),
                    },
                },
            )
        )
        if len(cards) >= _MAX_CARDS_PER_RECIPE:
            break
    return cards




# --------------------------------------------------------------------------- #
#  Source candidates awaiting review (WP5 / RM-19 -- transparency surface)
# --------------------------------------------------------------------------- #


def source_candidates_waiting(session) -> list[Card]:
    """Surface machine-suggested source candidates so background discovery is
    never hidden: one card saying how many await the operator's decision."""
    if _disabled("source_candidates_waiting"):
        return []
    from src.database.models import SourceCandidate

    n = session.query(SourceCandidate).filter_by(status="candidate").count()
    if n == 0:
        return []
    return [
        Card(
            type="recipe_source_candidates",
            title=f"{n} source candidate{'s' if n != 1 else ''} await your review",
            summary=(
                f"Offline discovery (citations in your corpus + the packaged catalog) "
                f"staged {n} suggested source{'s' if n != 1 else ''}. Each carries its "
                f"evidence; nothing is fetched or enabled until you decide."
            ),
            bucket="context",
            signal={"metric": "candidates_waiting", "value": n},
            method=(
                "count of source_candidates rows in status 'candidate' (staged by the "
                "offline citation/catalog channels under the scheduler's budget)"
            ),
            caveat=(
                "A suggestion is not an endorsement: review each candidate's evidence "
                "in Sources before promoting, and remember promotion still creates a "
                "disabled source."
            ),
            evidence=[],
            n=n,
            key="source-candidates",
        )
    ]


RECIPE_PRODUCERS: tuple[tuple[str, object], ...] = (
    ("promises_due", promises_due),
    ("edit_war_burst", edit_war_burst),
    ("region_gone_quiet", region_gone_quiet),
    ("source_candidates_waiting", source_candidates_waiting),
)
