"""The Claim Workspace, slice 2 (gate row K, brief S05-11 S2): steps ④ and ⑥.

The brief's acceptance, both halves: a signed bundle VERIFIES WITH CUSTODY (the signature is
made by :class:`src.custody.signing.HybridSigner` and checked by
:func:`src.custody.signing.verify`), and a NEGATIVE-SPACE FIXTURE proves an OSM-derived row is
refused from the bundle (Q823 is unanswered, so the bundle is refused whole rather than
written with a short attribution block). Around them: step ④ scans only the trail, names the
host and the exact request, fetches nothing, and knows which slices are already held; the
bundle carries what it says it carries, and tampering is caught member by member.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import date

import pytest

from src.analytics import claim_bundle as cb
from src.analytics import claim_workspace as cw
from src.backup.attribution import PendingRulingError
from src.custody.signing import HybridSigner, PublicIdentity, canonical_bytes, verify
from src.database.models import ArticleMentionedPlace, Keyword, KeywordMention
from tests.test_claim_workspace import CLAIM, make_corpus, serve

HOST = "archive-api.open-meteo.com"


@pytest.fixture()
def corpus(tmp_path):
    return make_corpus(tmp_path)


@pytest.fixture()
def client(corpus):
    TS, ids = corpus
    with serve(TS) as c:
        yield c, ids


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    return d


@pytest.fixture()
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("step ④ and the bundle must never fetch")

    monkeypatch.setattr("src.safety.fetcher.make_fetcher", refuse)


@pytest.fixture()
def signer(tmp_path):
    return HybridSigner(tmp_path / "k" / "ed.pem", tmp_path / "k" / "ml.key", use_pqc=False)


def _drought(TS, article_ids, *, place="Zermatt", lat=46.02, lon=7.75):
    """A 'drought' keyword mention and a placed city on each of ``article_ids``."""
    with TS() as s:
        kw = Keyword(term="drought", normalized_term="drought", language="en")
        s.add(kw)
        s.flush()
        for aid in article_ids:
            s.add(KeywordMention(keyword_id=kw.id, article_id=aid, count=1,
                                 observed_on=date(2026, 8, 28)))
            s.add(ArticleMentionedPlace(article_id=aid, name=place, country="ch", kind="city",
                                        lat=lat, lon=lon))
        s.commit()


def _ws(TS, claim=CLAIM):
    with TS() as s:
        return cw.build_workspace(s, claim)


def _zip(data):
    return zipfile.ZipFile(io.BytesIO(data))


# --------------------------------------------------------------------------- #
# ④ corroboration offers
# --------------------------------------------------------------------------- #


def test_step_four_offers_weather_for_the_trail_only_and_fetches_nothing(corpus, data_dir, no_network):
    TS, ids = corpus
    _drought(TS, [ids["wire"], ids["indep"]])
    ws = _ws(TS)
    co = ws["corroboration"]
    assert co["total"] == 1 and co["articles_scanned"] == ws["related"]["shown"]
    op = co["offers"][0]
    assert op["kind"] == "weather" and op["rule"] == "drought"
    assert sorted(op["article_ids"]) == sorted([ids["wire"], ids["indep"]])
    assert op["host"] == HOST and op["request_url"].startswith(f"https://{HOST}/")
    assert "latitude=46.0200" in op["request_url"] and op["coords_from"] == "article_mentioned_places"
    assert op["reveals"] == ["ip_address", "coordinates", "date_window"]
    assert op["cached"] is False
    # Asking whether a slice is held creates nothing on disk.
    assert not (data_dir / "weather_context").exists()


def test_a_drought_article_outside_the_trail_makes_no_offer(corpus, data_dir, no_network):
    TS, _ids = corpus
    with TS() as s:
        from src.database.models import Article

        other = s.query(Article).filter(Article.title == "Stock markets close higher").one().id
    _drought(TS, [other])
    assert _ws(TS)["corroboration"]["total"] == 0


def test_an_offer_knows_when_its_slice_is_already_held(corpus, data_dir, no_network):
    from src.weather.openmeteo import cache_path

    TS, ids = corpus
    _drought(TS, [ids["wire"]])
    url = _ws(TS)["corroboration"]["offers"][0]["request_url"]
    cache_path(url).write_text(json.dumps({"ok": True, "daily": {"time": []}, "units": {}}))
    assert _ws(TS)["corroboration"]["offers"][0]["cached"] is True


def test_a_window_longer_than_the_archive_allows_is_narrowed_and_says_so(corpus, data_dir, no_network):
    TS, ids = corpus
    _drought(TS, [ids["wire"]])
    with TS() as s:
        kw = s.query(Keyword).one()
        s.add(KeywordMention(keyword_id=kw.id, article_id=ids["stat"], count=1,
                             observed_on=date(2023, 1, 5)))
        s.add(ArticleMentionedPlace(article_id=ids["stat"], name="Zermatt", country="ch",
                                    kind="city", lat=46.02, lon=7.75))
        s.commit()
    op = _ws(TS)["corroboration"]["offers"][0]
    assert op["window_narrowed"] is True and op["n_articles"] == 2 and op["n_in_window"] == 1
    assert (date.fromisoformat(op["window_end"]) - date.fromisoformat(op["window_start"])).days == 366


# --------------------------------------------------------------------------- #
# ⑥ the signed bundle
# --------------------------------------------------------------------------- #


def test_the_bundle_verifies_with_custody(corpus, data_dir, no_network, signer):
    TS, _ids = corpus
    ws = _ws(TS)
    with TS() as s:
        data, report = cb.build_trail_bundle(s, ws, signer=signer)
    zf = _zip(data)
    manifest = json.loads(zf.read("manifest.json"))
    sig = json.loads(zf.read("SIGNATURE.json"))
    # The custody verifier, pinned to the signer this test holds.
    ok, reason = verify(sig["signature"], canonical_bytes(manifest), pinned=signer.public_identity())
    assert ok, reason
    res = cb.verify_trail_bundle(data)
    assert res["verified"] and res["issues"] == [] and res["members"] == len(manifest["members"])
    assert report["identity"] == signer.public_identity().to_dict()
    assert report["articles"] == ws["related"]["shown"]
    names = set(zf.namelist())
    assert {"README.md", "trail.json", "sources.json", "ATTRIBUTION.md",
            "WHAT-A-READER-CAN-SEE.md", "manifest.json", "SIGNATURE.json"} <= names
    assert sum(n.startswith("articles/") for n in names) == ws["related"]["shown"]
    assert report["members"] == [m["name"] for m in manifest["members"]] + ["manifest.json", "SIGNATURE.json"]


def test_tampering_is_caught_member_by_member(corpus, data_dir, no_network, signer):
    TS, _ids = corpus
    with TS() as s:
        data, _ = cb.build_trail_bundle(s, _ws(TS), signer=signer)

    def rewrite(change):
        src = _zip(data)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for n in src.namelist():
                body = change(n, src.read(n))
                if body is not None:
                    zf.writestr(n, body)
            if change("__extra__", None) is not None:
                zf.writestr("extra.txt", b"added later")
        return out.getvalue()

    altered = rewrite(lambda n, b: b.replace(b"Glacier", b"Glacial") if n == "trail.json" else b)
    assert "member altered: trail.json" in cb.verify_trail_bundle(altered)["issues"]
    removed = rewrite(lambda n, b: None if n == "sources.json" else b)
    assert "member missing: sources.json" in cb.verify_trail_bundle(removed)["issues"]
    added = rewrite(lambda n, b: b"x" if n == "__extra__" else b)
    assert "member not in the manifest: extra.txt" in cb.verify_trail_bundle(added)["issues"]

    def forged(n, b):
        if n != "manifest.json":
            return b
        m = json.loads(b)
        m["claim"] = "something else"
        return json.dumps(m).encode()

    res = cb.verify_trail_bundle(rewrite(forged))
    assert not res["verified"] and any(i.startswith("signature:") for i in res["issues"])


def test_a_bundle_re_signed_by_another_key_fails_when_the_signer_is_pinned(corpus, data_dir, no_network,
                                                                            signer, tmp_path):
    TS, _ids = corpus
    other = HybridSigner(tmp_path / "o" / "ed.pem", tmp_path / "o" / "ml.key", use_pqc=False)
    with TS() as s:
        data, _ = cb.build_trail_bundle(s, _ws(TS), signer=other)
    assert cb.verify_trail_bundle(data)["verified"]  # integrity alone: true
    pinned = cb.verify_trail_bundle(data, pinned=signer.public_identity().to_dict())
    assert not pinned["verified"] and pinned["key_checked"] == "pinned"


def test_an_osm_derived_row_is_refused_from_the_bundle(corpus, data_dir, no_network, signer):
    """The negative-space fixture of the brief's acceptance: Q823 is unanswered, so a trail
    carrying a row pinned by an OSM-derived table writes NOTHING."""
    TS, ids = corpus
    _drought(TS, [ids["wire"]])
    ws = _ws(TS)
    ws["corroboration"]["offers"][0]["coords_from"] = "osm_places"
    with TS() as s, pytest.raises(PendingRulingError, match="Q823"):
        cb.build_trail_bundle(s, ws, signer=signer)
    # And the same trail with the row pinned by the place extractor is written.
    ws["corroboration"]["offers"][0]["coords_from"] = "article_mentioned_places"
    with TS() as s:
        data, _ = cb.build_trail_bundle(s, ws, signer=signer)
    assert cb.verify_trail_bundle(data)["verified"]


def test_the_open_meteo_line_rides_only_with_a_carried_slice(corpus, data_dir, no_network, signer):
    from src.weather.openmeteo import cache_path

    TS, ids = corpus
    _drought(TS, [ids["wire"]])
    ws = _ws(TS)
    with TS() as s:
        data, report = cb.build_trail_bundle(s, ws, signer=signer)
    assert report["weather_slices"] == 0 and "Open-Meteo" not in _zip(data).read("ATTRIBUTION.md").decode()
    cache_path(ws["corroboration"]["offers"][0]["request_url"]).write_text(
        json.dumps({"ok": True, "daily": {"time": ["2026-08-28"], "precipitation_sum": [0.0]},
                    "units": {"precipitation_sum": "mm"}}))
    with TS() as s:
        data, report = cb.build_trail_bundle(s, ws, signer=signer)
    zf = _zip(data)
    assert report["weather_slices"] == 1 and "corroboration/1.json" in zf.namelist()
    assert "Open-Meteo" in zf.read("ATTRIBUTION.md").decode()
    assert [a["key"] for a in report["attribution"]] == ["open_meteo"]


def test_left_out_text_carries_the_hash_and_not_the_words(corpus, data_dir, no_network, signer):
    TS, ids = corpus
    with TS() as s:
        data, report = cb.build_trail_bundle(s, _ws(TS), full_text=False, signer=signer)
    rec = json.loads(_zip(data).read(f"articles/{ids['wire']}.json"))
    assert "content" not in rec and rec["content_included"] is False and len(rec["content_sha256"]) == 64
    note = _zip(data).read("WHAT-A-READER-CAN-SEE.md").decode()
    assert "left out by you" in note and "custody signer" in note
    with TS() as s:
        data, _ = cb.build_trail_bundle(s, _ws(TS), signer=signer)
    assert "Glacier melt" in json.loads(_zip(data).read(f"articles/{ids['wire']}.json"))["content"]


def test_an_empty_trail_is_not_a_bundle(corpus, data_dir, no_network, signer):
    TS, _ids = corpus
    with TS() as s, pytest.raises(cb.TrailBundleError):
        cb.build_trail_bundle(s, _ws(TS, "zzqx wyvern flumph"), signer=signer)


def test_the_bundle_carries_no_score_shaped_field(corpus, data_dir, no_network, signer):
    TS, ids = corpus
    _drought(TS, [ids["wire"]])
    with TS() as s:
        data, _ = cb.build_trail_bundle(s, _ws(TS), signer=signer)
    bad = ("score", "rating", "ranking", "grade", "verdict")

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield f"{path}.{k}", k
                yield from walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from walk(v, f"{path}[{i}]")

    for name in ("trail.json", "manifest.json"):
        for p, k in walk(json.loads(_zip(data).read(name))):
            if k == "degraded":
                continue
            assert not any(b in k.lower() for b in bad), (name, p)


def test_verification_needs_nothing_but_the_standard_library_and_crypto():
    """scripts/verify_claim_trail.py runs where the app's database stack does not."""
    import subprocess
    import sys

    code = (
        "import sys; import src.analytics.claim_bundle as m; "
        "bad = [n for n in ('sqlalchemy', 'src.database.models', 'src.bulletin.privacy') "
        "if n in sys.modules]; print(bad); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_routes_export_verify_and_refuse(client, data_dir, no_network, monkeypatch, tmp_path):
    c, ids = client
    r = c.post("/api/claims/trail-bundle", json={"claim": CLAIM, "full_text": False})
    assert r.status_code == 200, r.text
    body = r.json()
    data = base64.b64decode(body["zip_base64"])
    assert body["filename"].endswith(".zip") and body["bytes"] == len(data)
    v = c.post("/api/claims/trail-bundle/verify", content=data,
               headers={"content-type": "application/zip"})
    assert v.status_code == 200 and v.json()["verified"] is True
    assert c.post("/api/claims/trail-bundle/verify", content=b"not a zip").json()["verified"] is False
    assert c.post("/api/claims/trail-bundle/verify", content=b"").status_code == 400
    assert c.post("/api/claims/trail-bundle", json={"claim": "zzqx wyvern flumph"}).status_code == 400

    real = cw.corroboration_offers

    def osm(session, article_ids, **kw):
        out = real(session, article_ids, **kw)
        out["offers"] = [{"coords_from": "osm_places", "request_url": None}]
        return out

    monkeypatch.setattr(cw, "corroboration_offers", osm)
    r = c.post("/api/claims/trail-bundle", json={"claim": CLAIM})
    assert r.status_code == 409 and "Q823" in r.json()["detail"]


def test_the_custody_identity_signs_by_default(corpus, data_dir, no_network):
    """No signer passed: the bundle is signed by the install's CUSTODY key, the one
    GET /api/custody/settings reports -- not a fresh key per bundle."""
    TS, _ids = corpus
    with TS() as s:
        _data, report = cb.build_trail_bundle(s, _ws(TS))
    custody = HybridSigner(use_pqc=False).public_identity()
    assert report["identity"]["ed25519_pub"] == custody.ed25519_pub
    assert isinstance(PublicIdentity(**report["identity"]), PublicIdentity)
