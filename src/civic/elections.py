"""Election date confidence — the three ruled tiers, and the refusals that keep them honest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-07-14 (V1_PATHWAY §4.5), extending the shipped ``confirmed: false``
convention. An election date carries ONE of three confidence tiers:

  * ``scheduled`` — an officially set date, sourced from the electoral authority.
  * ``window``    — a legally/constitutionally bounded window, exact date pending (the
                    shipped France-2027 pattern: ``confirmed: false`` + ``official_url``).
  * ``projected`` — derived from a sourced recurrence rule plus the last held election
                    ("every N years since YYYY"). **Explicitly unreliable by design.**

Three refusals carry the honesty, and each is a REFUSAL rather than a caveat — a sentence
under a fabricated date does not un-fabricate it:

1. **No sourced rule + last-held ⇒ NO projected entry.** A projection needs all three of
   ``interval_years``, ``last_held`` and ``recurrence_rule_source``; missing any one yields
   a GAP (``None``), never a guess. ``cadence`` is deliberately NOT consulted: it is free
   prose ("every 2 years (Congress) / 4 years (president)") and reading an interval out of
   it would manufacture exactly the sourced-rule the ruling requires.

2. **A projection yields a YEAR, never a day.** ``last_held + N years`` on a real date
   would print 2027-04-10 — a day precision no recurrence rule can support. The rule says
   "every N years since YYYY", so the output is a year, plus a month ONLY where the
   catalog itself states one. See ``projection()``.

3. **A passed projected date is NEVER silently re-projected.** It is marked
   ``passed`` — "projected date passed; status unknown, check the official source" — which
   is itself an investigative lead: an election that did not happen is exactly what this
   app exists to surface. There is deliberately no loop advancing to the next cycle, and
   ``tests/test_elections_confidence.py`` pins that absence, because rolling forward is the
   single edit that would turn this module into a date fabricator.

The tier vocabulary is elections-only. Applying it to a trade summit would be a category
error, so ``date_confidence`` returns ``None`` for any event outside the ``elections``
calendar rather than inventing a fourth meaning for an existing tier.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# The three ruled tiers. Ordered most- to least-certain; a surface may rely on that order.
SCHEDULED = "scheduled"
WINDOW = "window"
PROJECTED = "projected"
TIERS: tuple[str, ...] = (SCHEDULED, WINDOW, PROJECTED)

#: The calendar whose entries carry a confidence tier.
ELECTIONS_CALENDAR = "elections"

# Caveats. VISIBLE BY DEFAULT (the informed-consent non-negotiable) — these are the short
# forms that render inline; the long form travels in the #oo-tip hover. Each is an i18n key
# present in all twelve locale files (tests/test_elections_confidence.py pins that).
CAVEAT_SCHEDULED = "Date set by the electoral authority. Confirm at the official source."
CAVEAT_WINDOW = (
    "The exact day is not yet set — only the legal window is known. "
    "Confirm at the official source."
)
CAVEAT_PROJECTED = (
    "Projected from a recurrence rule, not announced. Elections are postponed, moved or "
    "cancelled — treat this as a prompt to check the official source, never as a date."
)
CAVEAT_PASSED = (
    "The projected date has passed and no result is recorded here — status unknown. "
    "Check the official source."
)

#: Every field a projection requires. Absent any one of them, there is no projection.
PROJECTION_REQUIRED_FIELDS: tuple[str, ...] = (
    "interval_years",
    "last_held",
    "recurrence_rule_source",
)


def _positive_int(value: object) -> int | None:
    """A strictly positive int, or None. Rejects bools, floats and numeric strings.

    ``interval_years`` decides how far a projection reaches, so a lenient read is a
    fabrication risk: ``int(4.9)`` is 4 and ``int(True)`` is 1, and both would arrive
    looking like a legitimately-sourced interval (the recorded "a single downstream
    validator is a lie if the builder pre-coerces" lesson).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _iso_date(value: object) -> date | None:
    """An ISO ``YYYY-MM-DD`` (or a real ``date``) as a date, else None.

    A YAML loader hands back a real ``date`` for an unquoted 2022-04-10, and a ``str`` for
    a quoted one; both are legitimate spellings of the same fact, so both are accepted and
    everything else is refused.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _month(value: object) -> int | None:
    """A calendar month 1..12, or None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= 12 else None


def _year(value: object) -> int | None:
    """A plausible calendar year, or None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= 9999 else None


def is_election(event: dict[str, Any]) -> bool:
    """Is this catalog entry an election (and so eligible for a confidence tier)?"""
    return str(event.get("calendar") or "") == ELECTIONS_CALENDAR


def projectable(event: dict[str, Any]) -> bool:
    """Does the entry carry ALL of the fields a projection requires?

    The whole of refusal (1). Note it checks the PARSED value, not mere presence: an
    ``interval_years: "five"`` is as absent as no field at all, and reading it as present
    is how a gap becomes a guess.
    """
    return (
        _positive_int(event.get("interval_years")) is not None
        and _iso_date(event.get("last_held")) is not None
        and bool(str(event.get("recurrence_rule_source") or "").strip())
    )


def missing_projection_fields(event: dict[str, Any]) -> list[str]:
    """Which required projection fields this entry lacks — the gap, named.

    Published rather than counted, because "we have no date for Chad" and "we have no
    SOURCE for Chad's rule" are different facts and only the second is actionable by the
    research pass that fills the coverage floor.
    """
    missing = []
    if _positive_int(event.get("interval_years")) is None:
        missing.append("interval_years")
    if _iso_date(event.get("last_held")) is None:
        missing.append("last_held")
    if not str(event.get("recurrence_rule_source") or "").strip():
        missing.append("recurrence_rule_source")
    return missing


def date_confidence(event: dict[str, Any]) -> str | None:
    """The ruled tier for an election entry, or None.

    ``None`` has two distinct causes and both are honest: the entry is not an election
    (the tier vocabulary does not apply), or it is an election that states no date and
    cannot be projected — which is the GAP refusal (1) requires. A caller that needs to
    tell them apart asks ``is_election`` first.
    """
    if not is_election(event):
        return None
    # An officially set date: confirmed AND a concrete day. `confirmed` alone is not a
    # date — an entry confirmed to fall in October is a window, not a schedule.
    if bool(event.get("confirmed")) and _positive_int(event.get("day")) is not None:
        return SCHEDULED
    # A stated month with no fixed day is the legal window (the France-2027 pattern).
    # A sourced `window_year` is the same tier one notch coarser, for a law that fixes a
    # year but not a month. Both must be STATED: a year read off a title would collapse
    # "due by 2029" (a dissolution deadline an early election beats) into "falls in 2029".
    if _month(event.get("month")) is not None or _year(event.get("window_year")) is not None:
        return WINDOW
    # No stated date at all: a projection if — and only if — it is fully sourced.
    if projectable(event):
        return PROJECTED
    return None


def projection(event: dict[str, Any], today: date | None = None) -> dict[str, Any] | None:
    """The projected period for a ``projected`` entry, or None.

    Returns ``{year, month, basis, status, caveat}``:

    * ``year`` — ``last_held.year + interval_years``. **A year, never a day** (refusal 2).
    * ``month`` — only when the catalog states one; ``None`` otherwise, never derived from
      ``last_held``'s month, since a rule that says "every 5 years" says nothing about
      which month the next one falls in.
    * ``basis`` — the sentence a reader checks the arithmetic against, carrying the
      recurrence rule's own source.
    * ``status`` — ``upcoming`` or ``passed``.

    **There is no branch that advances past one interval.** A passed projection stays
    passed and says so; computing ``last_held + 2N`` would fabricate a cycle nobody
    announced, which is refusal (3).
    """
    if not is_election(event) or not projectable(event):
        return None
    interval = _positive_int(event.get("interval_years"))
    last = _iso_date(event.get("last_held"))
    if interval is None or last is None:  # unreachable via projectable(); mypy needs it
        return None

    year = last.year + interval
    month = _month(event.get("month"))
    today = today or date.today()

    # Passed = the projected period is wholly behind us. With a month, that is (year,
    # month) < (now.year, now.month); with a year alone the whole year must be past,
    # because "some time in 2027" has not passed on 2027-01-02.
    if month is not None:
        passed = (year, month) < (today.year, today.month)
    else:
        passed = year < today.year

    source = str(event.get("recurrence_rule_source") or "").strip()
    return {
        "year": year,
        "month": month,
        "basis": (
            f"last held {last.isoformat()}, every {interval} year"
            f"{'s' if interval != 1 else ''} per {source}"
        ),
        "recurrence_rule_source": source,
        "last_held": last.isoformat(),
        "interval_years": interval,
        "status": "passed" if passed else "upcoming",
        "caveat": CAVEAT_PASSED if passed else CAVEAT_PROJECTED,
    }


def caveat_for(tier: str | None) -> str | None:
    """The visible-by-default caveat for a tier, or None outside the vocabulary."""
    return {
        SCHEDULED: CAVEAT_SCHEDULED,
        WINDOW: CAVEAT_WINDOW,
        PROJECTED: CAVEAT_PROJECTED,
    }.get(tier or "")


def annotate(event: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """``event`` plus its confidence tier — additive, and a no-op off the elections calendar.

    Every non-election entry comes back byte-identical, so wiring this into the shared
    agenda cannot change what a summit or an observance renders. An election gains
    ``date_confidence``, ``date_caveat`` and (only where one exists) ``projection``.
    """
    if not is_election(event):
        return event
    tier = date_confidence(event)
    out = dict(event)
    out["date_confidence"] = tier
    proj = projection(event, today) if tier == PROJECTED else None
    # A projected entry's caveat is the projection's own (it distinguishes upcoming from
    # passed); every other tier takes the static one. A tierless election — the refusal-(1)
    # gap — gets no caveat, because there is no date to caveat.
    out["date_caveat"] = proj["caveat"] if proj else caveat_for(tier)
    if proj is not None:
        out["projection"] = proj
    return out
