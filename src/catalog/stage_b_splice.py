"""
The Stage B splice: admit where both judges agree, defer the contested band (Q1119 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two independent judges read 1,840 paired rows on identical neutral instructions and agreed
97.1 % of the time on ``kind`` and 84.6 % on ``primary_source`` — a ~15 % contested band.
Q1119 = a takes the obvious half and refuses the tempting one: **admit the rows where both
judges agree, defer the contested band.**

DEFER IS NOT REJECT, and that distinction is the reason this module exists rather than a
filter. The robots ruling already settled the principle — a non-answer is not a no — and a
deferred row keeps its evidence, keeps its place in the worklist, and can be admitted by a
later pass or by a person. Nothing here deletes a candidate, and there is no `reject` verdict
in the vocabulary at all.

FOUR OUTCOMES, in the order they are decided. The ORDER is the design: a block must be
reachable even for a row the judges agree about, or the block is decorative.

  1. ``blocked``   — the row tripped ``restricted_namespace`` (Q1112 = b): gambling, adult or
                     pharma lexicon on a namespace no private party can register (.gov.*,
                     .gob.*, .go.id, .gouv.*, .mil). An expired domain cannot explain that, so
                     the site is COMPROMISED rather than lapsed. It cannot be spliced without
                     a WRITTEN override, and it is never a silent drop: it is listed, with its
                     tier and its evidence, in the report the operator reads.
  2. ``declined``  — the row's name is a bare Wikidata Q-id that could not be resolved
                     (Q1116 = a). Admitting it would put an identifier in the catalogue where
                     a name belongs.
  3. ``deferred``  — the two judges disagree, on ``kind`` or on ``primary_source``. The
                     contested band, kept whole.
  4. ``admitted``  — both judges agree, nothing blocks it.

WHAT THIS MODULE DOES NOT DECIDE. It does not touch the flagged embassy platforms beyond
leaving the existing flag to block them, and it publishes nothing and contacts nobody — that
question is ⛔ and stays open. It does not rank, score or prioritise. And it does not write:
it produces catalogue ROWS and a REPORT, and a person applies them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

#: The five outcomes. There is deliberately no `reject`.
ADMITTED = "admitted"
DEFERRED = "deferred"
BLOCKED = "blocked"
DECLINED = "declined"
#: Both judges agree the row is something other than an institution. It is not rejected and
#: not deferred -- it belongs to a DIFFERENT catalogue (journalism, academic), and saying so
#: is routing, not a verdict. Kept as its own bucket so it never inflates `admitted`.
ROUTED = "routed"

#: Why a row was deferred or blocked. A reason is always recorded — a count without reasons
#: is a number nobody can act on, and the contested band is the deliverable.
REASON_KIND = "judges_disagree_on_kind"
REASON_PRIMARY = "judges_disagree_on_primary_source"
REASON_ONE_JUDGE = "only_one_judge_read_this_row"
#: THE ONE THAT IS NOT A DISAGREEMENT. Both judges agree the row IS an institution and agree
#: it is NOT a primary source. Admitting it to `official_sources.yml` would assert the exact
#: opposite of what both of them said -- and rejecting it would decide the `primary_source`
#: axis, which Q1110 = a explicitly DEFERS rather than rejects while it is rewritten as an
#: observable. So it is deferred, under its own reason, and it is the single largest bucket:
#: 623 of 1,843 paired rows on the committed data. A splice that folded these into `admitted`
#: would report nearly twice the admissions it had earned.
REASON_NOT_PRIMARY = "agreed_not_a_primary_source_axis_deferred_by_Q1110"
REASON_RESTRICTED = "restricted_namespace_without_written_override"
REASON_NO_LABEL = "name_is_an_unresolved_identifier"

#: Q1117 = a. 116 of the 267 second-pass rows are Czech municipalities publishing their
#: statutory *úřední deska*, and 42 of them share this path — almost certainly one CMS
#: vendor's product. They are legitimate, distinct institutions and this is not a reason to
#: exclude them. It IS a reason to tag them: admitting them makes a supplier outage a
#: CORRELATED failure across dozens of catalogue rows, and a correlated failure nobody
#: labelled reads later as dozens of independent sources going quiet at once.
VENDOR_PATHS: dict[str, str] = {
    "/uredni-deska": "cms:uredni-deska-atom",
}

_BARE_QID = re.compile(r"^\s*[Qq]\d+\s*$")


def vendor_path_tag(rss_url: str | None) -> str | None:
    """The shared-vendor tag for a feed URL, or None.

    Matched on the PATH, not the host: the whole point is that distinct hosts share one
    product, so the host is exactly the wrong thing to key on.
    """
    if not rss_url:
        return None
    path = (urlsplit(rss_url).path or "").rstrip("/").lower()
    for prefix, tag in VENDOR_PATHS.items():
        if path == prefix or path.startswith(prefix + "/"):
            return tag
    return None


def _agree(a: Mapping, b: Mapping) -> tuple[bool, str | None]:
    """Do the two judgements agree? Returns the DISAGREEING axis when they do not."""
    if (a.get("kind") or "") != (b.get("kind") or ""):
        return False, REASON_KIND
    # `primary_source` is only compared where both called the row an institution -- the axis
    # is undefined for anything else, and comparing it there would manufacture disagreement
    # out of a field neither judge was answering.
    if (a.get("kind") or "") == "institution" and bool(a.get("primary_source")) != bool(
        b.get("primary_source")
    ):
        return False, REASON_PRIMARY
    return True, None


def pair_judgements(
    judge_a: Iterable[Mapping], judge_b: Iterable[Mapping],
) -> tuple[dict[str, tuple[Mapping, Mapping]], dict[str, Mapping]]:
    """``({domain: (a, b)}, {domain: the_only_one})``.

    The second half is not a leftover: 8 of the 60 batches were read by one judge only,
    because agents died to API timeouts. Those rows have NO agreement to measure, and
    counting them as agreeing (or as disagreeing) would invent a measurement. They are
    carried out separately and deferred by name.
    """
    a_by = {str(r.get("domain") or "").strip().lower(): r for r in judge_a if r.get("domain")}
    b_by = {str(r.get("domain") or "").strip().lower(): r for r in judge_b if r.get("domain")}
    both = {d: (a_by[d], b_by[d]) for d in a_by.keys() & b_by.keys()}
    lone = {d: a_by.get(d) or b_by[d] for d in a_by.keys() ^ b_by.keys()}
    return both, {d: r for d, r in lone.items() if r is not None}


def splice(
    judge_a: Iterable[Mapping],
    judge_b: Iterable[Mapping],
    *,
    integrity_tiers: Mapping[str, str] | None = None,
    written_overrides: Iterable[str] = (),
    resolved_labels: Mapping[str, str] | None = None,
    names: Mapping[str, str] | None = None,
    rss_urls: Mapping[str, str] | None = None,
) -> dict:
    """Decide every candidate, and return the rows AND the report.

    ``written_overrides`` is the only way a ``restricted_namespace`` row can be admitted, and
    it is a list of domains a PERSON wrote down — Q1112's "never a silent drop" cuts both
    ways: the block is visible in the report, and lifting it is visible in the inputs.
    """
    tiers = {k.lower(): v for k, v in (integrity_tiers or {}).items()}
    overrides = {str(d).strip().lower() for d in written_overrides}
    labels = {k.upper(): v for k, v in (resolved_labels or {}).items()}
    row_names = {k.lower(): v for k, v in (names or {}).items()}
    feeds = {k.lower(): v for k, v in (rss_urls or {}).items()}

    both, lone = pair_judgements(judge_a, judge_b)
    out: dict[str, list[dict]] = {
        ADMITTED: [], DEFERRED: [], BLOCKED: [], DECLINED: [], ROUTED: [],
    }
    # ANTI-CAPPING, for the one number most likely to be misread: "7 blocked" invites the
    # reading "there are 7 such domains". There are as many as the flags file holds, and this
    # splice can only block the ones inside ITS population. The difference is reported rather
    # than left to be inferred from two files nobody opens together.
    restricted_total = sum(1 for t in tiers.values() if t == "restricted_namespace")
    restricted_in_scope = sum(
        1 for d, t in tiers.items() if t == "restricted_namespace" and d in both
    )

    def _record(bucket: str, domain: str, judgement: Mapping, reason: str | None,
                **extra) -> None:
        out[bucket].append({
            "domain": domain,
            "kind": judgement.get("kind"),
            "primary_source": judgement.get("primary_source"),
            "language": judgement.get("language"),
            "reason": reason,
            **extra,
        })

    for domain in sorted(both):
        a, b = both[domain]
        # 1. THE BLOCK FIRST, and deliberately before the agreement test: a compromised
        #    government namespace is not made safe by two judges agreeing it is an
        #    institution -- they were reading the claimed identity, which is the thing the
        #    flag says is contradicted.
        tier = tiers.get(domain)
        if tier == "restricted_namespace" and domain not in overrides:
            _record(BLOCKED, domain, a, REASON_RESTRICTED, integrity_tier=tier)
            continue
        # 2. A name that is an identifier.
        name = row_names.get(domain)
        if name and _BARE_QID.match(name) and not labels.get(name.strip().upper()):
            _record(DECLINED, domain, a, REASON_NO_LABEL, qid=name.strip().upper())
            continue
        agreed, why = _agree(a, b)
        if not agreed:
            _record(DEFERRED, domain, a, why,
                    judge_a={"kind": a.get("kind"), "primary_source": a.get("primary_source")},
                    judge_b={"kind": b.get("kind"), "primary_source": b.get("primary_source")})
            continue
        # AGREEMENT IS NECESSARY, NOT SUFFICIENT. `official_sources.yml` is a list of primary
        # sources, so what it may contain is the intersection of "both judges agree" and
        # "both judges say primary source" -- and the two other agreeing shapes each go
        # somewhere that is not a rejection.
        kind = (a.get("kind") or "")
        if kind != "institution":
            _record(ROUTED, domain, a, None, belongs_to=kind)
            continue
        if not a.get("primary_source"):
            _record(DEFERRED, domain, a, REASON_NOT_PRIMARY)
            continue
        resolved = labels.get((name or "").strip().upper()) if name else None
        _record(ADMITTED, domain, a, None,
                name=resolved or name,
                renamed_from=(name if resolved else None),
                vendor_tag=vendor_path_tag(feeds.get(domain)),
                integrity_tier=tier,
                overridden=domain in overrides if tier else False)

    for domain in sorted(lone):
        _record(DEFERRED, domain, lone[domain], REASON_ONE_JUDGE)

    report = _report(out, both, lone)
    report["restricted_namespace"] = {
        "flagged_in_total": restricted_total,
        "inside_this_splice": restricted_in_scope,
        "blocked_here": len(out[BLOCKED]),
        "overridden": sum(1 for d in overrides if tiers.get(d) == "restricted_namespace"),
        "note": (
            "`blocked_here` counts the flagged domains this splice's own population "
            "contains, not every flagged domain. The rest were not candidates in this run — "
            "they are neither admitted nor cleared by it."
        ),
    }
    return {**out, "report": report}


def _by_kind(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = row.get("belongs_to") or "unspecified"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _report(out: Mapping[str, list[dict]], both: Mapping, lone: Mapping) -> dict:
    """The SPLICE REPORT — the artifact the operator reviews, per the brief."""
    deferred_by_reason: dict[str, int] = {}
    for row in out[DEFERRED]:
        key = row.get("reason") or "unspecified"
        deferred_by_reason[key] = deferred_by_reason.get(key, 0) + 1

    paired = len(both)
    contested = deferred_by_reason.get(REASON_KIND, 0) + deferred_by_reason.get(
        REASON_PRIMARY, 0
    )

    # PER-AXIS AGREEMENT, computed the way the two-judge README computes it, because the
    # combined figure below is a DIFFERENT and stricter statistic and the two must not be
    # read against each other. The README reports `kind` agreement over all paired rows and
    # `primary_source` agreement over the rows BOTH judges called `institution`; the combined
    # figure requires both axes at once, so it is necessarily lower and comparing it to the
    # README's 84.6 % would manufacture a discrepancy out of a definition.
    kind_agree = both_institution = primary_agree = 0
    for a, b in both.values():
        if (a.get("kind") or "") == (b.get("kind") or ""):
            kind_agree += 1
        if (a.get("kind") or "") == "institution" == (b.get("kind") or ""):
            both_institution += 1
            if bool(a.get("primary_source")) == bool(b.get("primary_source")):
                primary_agree += 1

    return {
        "paired_rows": paired,
        "single_judge_rows": len(lone),
        "admitted": len(out[ADMITTED]),
        "deferred": len(out[DEFERRED]),
        "blocked": len(out[BLOCKED]),
        "declined": len(out[DECLINED]),
        "routed_elsewhere": len(out[ROUTED]),
        "routed_by_kind": _by_kind(out[ROUTED]),
        "deferred_by_reason": deferred_by_reason,
        # The contested band as a RATE over the rows it is defined on -- paired rows only.
        # Including single-judge rows in the denominator would dilute a disagreement rate
        # with rows that had no second opinion to disagree with.
        "contested_band_pct": round(100.0 * contested / paired, 1) if paired else None,
        # BOTH axes at once -- the predicate this splice actually admits on.
        "agreement_pct": round(100.0 * (paired - contested) / paired, 1) if paired else None,
        # The two-judge README's own statistics, so the figures are comparable rather than
        # merely adjacent. Each carries its own denominator, because they have different ones.
        "kind_agreement_pct": round(100.0 * kind_agree / paired, 1) if paired else None,
        "primary_source_agreement_pct": (
            round(100.0 * primary_agree / both_institution, 1) if both_institution else None
        ),
        "both_called_institution": both_institution,
        "agreement_note": (
            "`agreement_pct` requires BOTH axes to agree and is the predicate this splice "
            "admits on. `kind_agreement_pct` and `primary_source_agreement_pct` are the "
            "two-judge run's own statistics, each over its own denominator -- the second is "
            "computed only over rows both judges called `institution`, where the axis is "
            "defined. The combined figure is necessarily the lowest of the three; reading it "
            "against either of the others would manufacture a discrepancy out of a "
            "definition."
        ),
        "vendor_tagged": sum(1 for r in out[ADMITTED] if r.get("vendor_tag")),
        "method": (
            "Two independent judges on identical neutral instructions. A row is admitted "
            "only where both agree on `kind` and, for institutions, on `primary_source`. A "
            "row either judge did not read has no agreement to measure and is deferred as "
            "such rather than counted in either direction."
        ),
        "caveat": (
            "DEFERRED IS NOT REJECTED: a non-answer is not a no, so a deferred row keeps its "
            "evidence and its place in the worklist. Blocked rows are listed with their tier "
            "and are never silently dropped — lifting a block needs a written override, "
            "which is visible in this run's inputs. Nothing here was written to the "
            "catalogue; these are rows and counts for review. The largest deferred group "
            "is rows both judges agree are institutions and agree are NOT primary sources: "
            "admitting them would assert the opposite of what both said, and rejecting them "
            "would decide the very axis Q1110 defers while it is rewritten as an observable."
        ),
    }


def balance_shift(
    existing_countries: Mapping[str, int], admitted: Iterable[Mapping],
    *, top: int = 8,
) -> dict:
    """How this splice moves the corpus's geographic balance (Q1117 = a's disclosure).

    The Czech municipalities are 43 % of one pass's yield, which is a real and legitimate
    concentration — and one that moves the corpus in a single splice by an amount worth
    seeing BEFORE it is applied rather than noticing afterwards. So the shift is published
    per country in percentage points, and the largest mover is named.
    """
    before_total = sum(existing_countries.values())
    added: dict[str, int] = {}
    for row in admitted:
        code = (row.get("country") or row.get("language") or "??").lower()
        added[code] = added.get(code, 0) + 1
    after = dict(existing_countries)
    for code, n in added.items():
        after[code] = after.get(code, 0) + n
    after_total = sum(after.values())

    # Annotated because the row is a deliberate mix of counts and percentages -- a small
    # published record, not a homogeneous mapping -- and the sort below does arithmetic on one.
    rows: list[dict[str, Any]] = []
    for code in sorted(set(existing_countries) | set(added)):
        b = 100.0 * existing_countries.get(code, 0) / before_total if before_total else 0.0
        a = 100.0 * after.get(code, 0) / after_total if after_total else 0.0
        rows.append({
            "country": code, "before": existing_countries.get(code, 0),
            "added": added.get(code, 0), "after": after.get(code, 0),
            "before_pct": round(b, 2), "after_pct": round(a, 2),
            "shift_pp": round(a - b, 2),
        })
    movers = sorted(rows, key=lambda r: abs(r["shift_pp"]), reverse=True)[:top]
    return {
        "before_total": before_total, "after_total": after_total,
        "added_total": sum(added.values()),
        "largest_movers": movers,
        "caveat": (
            "A concentration is not a defect. One country dominating a splice can mean that "
            "country's institutions publish machine-readable notices and others do not — so "
            "this is disclosed to be seen, not to be corrected. What it does mean is that a "
            "single supplier outage becomes a correlated failure across many rows, which is "
            "why the shared-vendor rows carry a tag."
        ),
    }
