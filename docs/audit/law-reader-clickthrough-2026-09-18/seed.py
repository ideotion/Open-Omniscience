"""Seed one law document through the REAL tracker, never by inserting rows."""
import os, sys
sys.path.insert(0, "/home/user/Open-Omniscience")
from src.database.session import SessionLocal, init_db
from src.database.models import LawDocument, LawRevision
from src.law.track import track_document

CLML = """<?xml version="1.0" encoding="UTF-8"?>
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
    <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Measurement Act 2018</dc:title>
    <ukm:EnactmentDate Date="2018-05-23"/>
    <dct:valid xmlns:dct="http://purl.org/dc/terms/">2024-01-01</dct:valid>
  </ukm:Metadata>
  <Body>
    <P1 id="section-1"><Pnumber>1</Pnumber><P1para><Text>{t}</Text></P1para></P1>
  </Body>
</Legislation>"""

class R:
    def __init__(s, c): s.content, s.content_type, s.raw_content = c, "application/xml", c.encode()
class F:
    def __init__(s, bodies): s.b, s.i = bodies, 0
    def fetch(s, u, **k):
        out = s.b[min(s.i, len(s.b) - 1)]; s.i += 1; return R(out)

init_db()
with SessionLocal() as s:
    doc = LawDocument(jurisdiction="uk", title="Measurement Act 2018",
                      url="https://www.legislation.gov.uk/ukpga/2018/12/data.xml",
                      official_url="https://www.legislation.gov.uk/ukpga/2018/12",
                      category="legislation", consolidated=True, language="en", country="gb")
    s.add(doc); s.commit()
    base = "This Act makes provision about the measurement of things. " * 8
    f = F([CLML.format(t=base),
           CLML.format(t=base + "A duty to publish measurement standards is inserted. " * 3),
           CLML.format(t=base + "A duty to publish measurement standards is inserted. " * 3
                       + "A review clause is added by the 2026 amendment. " * 2)])
    for _ in range(3):
        print(track_document(s, f, doc))
    revs = s.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id).all()
    print("DOC_ID", doc.id); print("BASELINE_REV", revs[0].id); print("REVS", len(revs))
