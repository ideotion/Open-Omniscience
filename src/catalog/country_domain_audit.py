"""
Does a source's COUNTRY field contradict its own DOMAIN? (Q1115 = a, 2026-09-15.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FINDING (institutions C7): ``cityofvancouver.us`` — a US city — carries ``country: ca``.
It was found incidentally, the export's country attribution has never been audited, and the
docket is explicit about what the fix must NOT be: **"a naive ccTLD check is NOT the audit
(`.uk` vs `gb` and `.eu` for EU bodies are both legitimate)."**

So this PROPOSES corrections for review and is never an automatic rule. Nothing here writes,
and the ruling is the reason: a rule that rewrote `country` from the ccTLD would "fix"
`cityofvancouver.us` and simultaneously break every `.eu` body, every `.uk` row stored as
`gb`, and every organisation that registered under a ccTLD it is not headquartered in. The
cost of that rule is invisible at the moment it runs and shows up as a country distribution
nobody can explain months later.

WHAT IT REFUSES TO CALL A CONTRADICTION, and why each refusal costs less than the flag:

  * A ccTLD that is not a reliable country signal. ``src.catalog.cctld`` already treats the
    REPURPOSED-AS-GENERIC set (`.io .co .me .ai .tv …`) and every gTLD as unknown — `who.is`
    is not Icelandic — and this reads that same list rather than restating it. One module
    deciding what a ccTLD means is the point; two would drift.
  * ``.uk`` against ``gb``. The ccTLD and the ISO code genuinely differ, and the catalogue
    stores the ISO one. ``cctld._SPECIAL_COUNTRY`` already holds that mapping.
  * ``.eu``. A European body's domain names a UNION, not a country; any member state's code
    is legitimate underneath it, so a disagreement there is not evidence of anything.
  * A row with no country, or no readable ccTLD. Absent is not wrong — the whole point of
    C7's sibling rulings is that "we could not tell" must not be recorded as a finding.

WHAT REMAINS AFTER THOSE REFUSALS is a row whose stored country and whose reliable ccTLD
both exist and disagree. That is a PROPOSAL: the two values, which one the domain implies,
and the reason the pair was surfaced — for a human to accept, reject, or leave alone.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.catalog.cctld import _SPECIAL_COUNTRY, CCTLD_COUNTRY, GENERIC_CCTLDS, _tld

#: ccTLDs that name something other than one country, so a disagreement under them is not
#: evidence. Kept apart from ``GENERIC_CCTLDS`` (which is about REPURPOSED ccTLDs) because
#: the reason differs: `.eu` is not repurposed, it is supranational.
SUPRANATIONAL_TLDS: frozenset[str] = frozenset({"eu"})

#: Why a row was NOT proposed. Counted and published, because a diagnostic that reports only
#: what it flagged cannot be checked for over- or under-reach.
SKIP_NO_COUNTRY = "no_country_stored"
SKIP_NO_SIGNAL = "tld_is_not_a_country_signal"
SKIP_SUPRANATIONAL = "supranational_tld"
SKIP_AGREES = "agrees"


def _domain_country(domain: str | None) -> tuple[str | None, str | None]:
    """``(iso2, skip_reason)`` — the country a domain reliably implies, or why it implies
    none. The ``.uk``→``gb`` mapping is applied here so a caller cannot forget it."""
    tld = _tld(domain)
    if not tld:
        return None, SKIP_NO_SIGNAL
    if tld in SUPRANATIONAL_TLDS:
        return None, SKIP_SUPRANATIONAL
    if tld in GENERIC_CCTLDS:
        return None, SKIP_NO_SIGNAL
    iso = CCTLD_COUNTRY.get(tld) or _SPECIAL_COUNTRY.get(tld)
    return (iso, None) if iso else (None, SKIP_NO_SIGNAL)


def audit_rows(rows: Iterable[tuple[object, str | None, str | None]]) -> dict:
    """The PURE core. ``rows`` is ``(id, domain, stored_country)``.

    Returns the proposals and — equally — the tally of everything it declined to propose,
    with the reason. A diagnostic that publishes only its hits cannot be audited for the two
    failures that matter: flagging legitimate rows, and quietly examining almost nothing.
    """
    proposals: list[dict] = []
    skipped = {
        SKIP_NO_COUNTRY: 0, SKIP_NO_SIGNAL: 0, SKIP_SUPRANATIONAL: 0, SKIP_AGREES: 0,
    }
    examined = 0
    for sid, domain, stored in rows:
        examined += 1
        stored_iso = (stored or "").strip().lower() or None
        implied, why = _domain_country(domain)
        if implied is None:
            skipped[why or SKIP_NO_SIGNAL] += 1
            continue
        if stored_iso is None:
            # Absent is not wrong. It is also not nothing -- a row whose domain names a
            # country and whose country field is empty is worth a human's eye, so it is
            # counted here rather than dropped, but it is never a CONTRADICTION.
            skipped[SKIP_NO_COUNTRY] += 1
            continue
        if stored_iso == implied:
            skipped[SKIP_AGREES] += 1
            continue
        proposals.append({
            "id": sid,
            "domain": domain,
            "stored_country": stored_iso,
            "domain_implies": implied,
            "tld": _tld(domain),
            "reason": (
                f"The stored country is {stored_iso!r} and the domain's country-code "
                f"top-level domain implies {implied!r}. One of them is probably wrong; "
                "which one is a question for a person, because an organisation may "
                "legitimately register under a country it does not operate from."
            ),
        })
    return {
        "proposals": sorted(proposals, key=lambda p: str(p["domain"] or "")),
        "examined": examined,
        "proposed": len(proposals),
        "skipped": skipped,
        "method": (
            "A row is proposed only when BOTH a stored country and a reliable ccTLD exist "
            "and disagree. A repurposed-as-generic ccTLD, a gTLD, the supranational .eu and "
            "the .uk/gb mapping are all read from src.catalog.cctld rather than restated, so "
            "one module decides what a ccTLD means."
        ),
        "caveat": (
            "These are PROPOSALS for review and nothing is applied. A ccTLD is weak evidence "
            "of where a body operates -- an organisation may register under a country it is "
            "not headquartered in -- so a disagreement means one of the two values deserves "
            "a look, never that the domain is right and the stored country is wrong."
        ),
    }
