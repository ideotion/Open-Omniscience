"""Seed a TWO-LANGUAGE law document through the REAL tracker, for the S2 click-through.

The original and its official translation are separate tracked documents that land on one
identity by construction (both CLML fixtures state act-number 2019/7 in ZZZ). Only the
provenance and the licence are set by hand afterwards, because nothing in the catalogue
states them for a synthetic jurisdiction -- and inventing a catalogue row to avoid one
hand-set field would be inventing a source.
"""
import sys
sys.path.insert(0, "/home/user/Open-Omniscience")
from pathlib import Path

from src.database.models import LawDocument, LawRevision
from src.database.session import SessionLocal, init_db
from src.law.lane_models import LawDocumentMeta
from src.law.model import identity_group, set_translation_kind
from src.law.track import track_document
from src.versioned.store import lane_session

F = Path("tests/fixtures/law/synthetic")


class _R:
    def __init__(self, body: bytes):
        self.raw_content, self.content, self.content_type = body, body.decode(), "application/xml"


class _Fetch:
    def __init__(self, names):
        self.bodies = [(F / f"{n}.clml.xml").read_bytes() for n in names]
        self.i = 0

    def fetch(self, _u, **_k):
        out = self.bodies[min(self.i, len(self.bodies) - 1)]
        self.i += 1
        return _R(out)


init_db()
with SessionLocal() as s:
    original = LawDocument(
        jurisdiction="ZZZ", title="Measurement Standards Act",
        url="https://gazette.zzz.test/act/2019/7/data.xml",
        official_url="https://gazette.zzz.test/act/2019/7",
        category="legislation", consolidated=True, language="zxx", country="zz",
    )
    translation = LawDocument(
        jurisdiction="ZZZ", title="Loi sur les normes de mesure",
        url="https://gazette.zzz.test/act/2019/7/fr/data.xml",
        official_url="https://gazette.zzz.test/act/2019/7/fr",
        category="legislation", consolidated=True, language="zxx-fr", country="zz",
    )
    s.add_all([original, translation])
    s.commit()
    print(track_document(s, _Fetch(["act.v1"]), original))
    print(track_document(s, _Fetch(["act.v2"]), original))
    print(track_document(s, _Fetch(["act.translation"]), translation))
    o_id, t_id = original.id, translation.id
    o_key, t_key = original.lane_key, translation.lane_key
    baseline = (
        s.query(LawRevision.id)
        .filter_by(document_id=o_id)
        .order_by(LawRevision.id.asc())
        .first()
    )[0]

with lane_session("law") as ls:
    metas = {m.lane_key: m for m in ls.query(LawDocumentMeta).all()}
    set_translation_kind(metas[o_key], "original")
    metas[o_key].licence_id = "ogl-3.0"
    set_translation_kind(metas[t_key], "official")
    metas[t_key].translated_by = "Office of the Government Translator"
    metas[t_key].licence_id = "cc-by-4.0"
    ls.flush()
    group = identity_group(ls, metas[o_key].identity_id)
    print("GROUP languages:", group.languages, "| original_state:", group.original_state)

print("DOC_ID", o_id)
print("TRANSLATION_ID", t_id)
print("BASELINE_REV", baseline)
