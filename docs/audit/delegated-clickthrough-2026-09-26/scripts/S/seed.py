"""Seed the four predicates Q1114 separates, and a REAL admission history.

Every admission row here is written by `evaluate_and_stamp` itself -- never inserted --
so the audit view is reading the engine's own record rather than a fixture that happens
to look like one. The three reversibility states the panel must be able to draw are
produced by driving the engine into them, in the order a field instance reaches them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""
from __future__ import annotations
import os, sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, "/tmp/claude-0/walk/S/oo-app")
from src.database.models import Source                       # noqa: E402
from src.database.session import SessionLocal, init_db       # noqa: E402
from src.catalog.qualification import (                      # noqa: E402
    STATUS_DISQUALIFIED, STATUS_QUALIFIED, STATUS_UNQUALIFIED,
    evaluate_and_stamp, undo_admission,
)

EXTRACTION_FAIL = [{"name": "extraction_failure", "extraction_failure": True}]
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC).replace(tzinfo=None)

init_db()
s = SessionLocal()


def src(domain: str, name: str, *, status: str, enabled: bool | None) -> Source:
    row = Source(name=name, domain=domain, status=status, enabled=enabled,
                 rss_url=f"https://{domain}/feed", tags="news")
    s.add(row); s.commit(); return row


# --- the four predicates, each genuinely distinct --------------------------------- #
# enabled AND qualified -> COLLECTING (the headline count, Q1114)
src("collecting-one.example", "Collecting One", status=STATUS_QUALIFIED, enabled=True)
src("collecting-two.example", "Collecting Two", status=STATUS_QUALIFIED, enabled=True)
# enabled, no verdict yet -> the catalogue's ordinary shape, NOT collecting
src("awaiting.example", "Awaiting Judgement", status=STATUS_UNQUALIFIED, enabled=True)
# enabled, judged and REFUSED -> never collecting
src("refused.example", "Refused By Judging", status=STATUS_DISQUALIFIED, enabled=True)
# qualified but switched off by the operator -> not collecting either
src("switched-off.example", "Switched Off", status=STATUS_QUALIFIED, enabled=False)
# discovered candidates, untouched
for i in range(3):
    src(f"candidate-{i}.example", f"Candidate {i}", status=STATUS_UNQUALIFIED, enabled=False)

# --- a REAL admission history, in the three states the panel must draw ------------- #
# (1) REVERSIBLE: admitted and still the decision in effect.
live = src("admitted-live.example", "Admitted (still standing)",
           status=STATUS_UNQUALIFIED, enabled=False)
evaluate_and_stamp(s, [live], {}, now=NOW); s.commit()

# (2) BLOCKED by a later verdict: admitted, then a later pass disqualified it. Before this
#     slice the panel offered an Undo here and the endpoint took it, erasing the refusal.
later = src("admitted-then-refused.example", "Admitted, then refused",
            status=STATUS_UNQUALIFIED, enabled=False)
evaluate_and_stamp(s, [later], {}, now=NOW + timedelta(hours=1)); s.commit()
evaluate_and_stamp(s, [later], {later.id: EXTRACTION_FAIL}, now=NOW + timedelta(hours=2))
s.commit()

# (3) ALREADY UNDONE: admitted, and the operator reversed it.
undone = src("admitted-undone.example", "Admitted, then undone",
             status=STATUS_UNQUALIFIED, enabled=False)
evaluate_and_stamp(s, [undone], {}, now=NOW + timedelta(hours=3)); s.commit()
from src.database.models import SourceAdmissionEvent  # noqa: E402
ev = (s.query(SourceAdmissionEvent)
      .filter(SourceAdmissionEvent.source_id == undone.id).one())
undo_admission(s, ev.id, now=NOW + timedelta(hours=4))

# --- what the panel should now be able to say, measured here so the walk can check -- #
from src.catalog.qualification import admission_audit, is_collectable  # noqa: E402
audit = admission_audit(s, limit=25)
collecting = [r.domain for r in s.query(Source).all() if is_collectable(r.enabled, r.status)]
print("SEEDED")
print(f"  sources:            {s.query(Source).count()}")
print(f"  collecting:         {len(collecting)} -> {sorted(collecting)}")
print(f"  admission events:   {audit['total']} (undone {audit['undone_total']})")
for e in audit["events"]:
    print(f"    {e['domain']:<34} reversible={e['reversible']!s:<5} blocked_by={e['blocked_by']}")
print(f"  unaccounted:        {audit['unaccounted']} of {audit['collecting']} collecting")
