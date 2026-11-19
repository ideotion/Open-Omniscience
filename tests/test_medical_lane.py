"""The medical lane (S07-01 S1; R745, R746): its own encrypted file, what a pass keeps, and what it never loses.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fixture only: the parser's invented NLM file. Checks are mostly negative space -- a record nobody
cites is not kept (R745), a withdrawal marks and never deletes, a class change is recorded rather
than overwritten, a failed pass leaves nothing half-applied, and the backup row says plainly that
it does not carry this store yet (R746).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from src.database.connect import connect, is_encrypted_file, set_passphrase
from src.medical import store as M
from src.medical.lane_models import MedicalClassChange, MedicalFile, MedicalPaper
from src.medical.pubmed_xml import ParseTally, parse_pubmed
from src.versioned import store
from src.versioned.lanes import lane

FIXTURE = Path(__file__).parent / "fixtures" / "medical" / "pubmed_update_sample.xml"
PASSPHRASE = "a medical lane test passphrase"


@pytest.fixture
def medical(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.create_lane("medical")
    try:
        yield tmp_path
    finally:
        store.dispose_all()


def _apply(data: bytes, wanted: M.Wanted, name: str = "pubmed25n1300.xml.gz") -> dict:
    tally = ParseTally()
    with store.lane_session("medical") as s:
        return M.apply_file(s, name, parse_pubmed(io.BytesIO(data), tally), tally, wanted)


def _papers() -> dict[int, MedicalPaper]:
    with store.lane_session("medical") as s:
        rows = s.execute(select(MedicalPaper)).scalars().all()
        s.expunge_all()
        return {r.pmid: r for r in rows}


# --- the lane itself --------------------------------------------------------------------------


def test_the_medical_lane_is_its_own_file_beside_the_corpus(medical):
    spec = lane("medical")
    assert (spec.filename, spec.transport, spec.implemented) == ("medical.db", "setting", False)
    assert (medical / "medical.db").is_file()
    assert not (medical / "open_omniscience.db").exists(), "the medical lane must never create the corpus"


def test_its_tables_are_in_medical_db_and_in_no_other_lane(medical):
    con = connect(medical / "medical.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"medical_papers", "medical_class_changes", "medical_wanted", "medical_files"} <= names
    store.create_lane("wiki")
    con = connect(medical / "wiki.db")
    wiki = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not {n for n in wiki if n.startswith("medical_")}, "medical tables leaked into wiki.db"


def test_the_medical_lane_is_encrypted_with_the_corpus_passphrase(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", PASSPHRASE, raising=False)
    try:
        path = store.create_lane("medical")
        assert is_encrypted_file(path), "medical.db was written in the clear"
    finally:
        store.dispose_all()
        set_passphrase(None)


def test_no_column_scores_a_paper():
    from src.medical.lane_models import MEDICAL_LANE_MODELS

    for model in MEDICAL_LANE_MODELS:
        for col in model.__table__.columns:
            assert not any(w in col.name for w in ("score", "rating", "rank", "grade", "trust", "quality")), col.name


# --- R745: what is kept ----------------------------------------------------------------------


def test_only_the_wanted_records_are_kept_and_the_rest_of_the_file_is_dropped(medical):
    wanted = M.Wanted()
    wanted.add("pmid", "90000002")
    wanted.add("doi", "https://doi.org/10.9999/JIR.2024.001")  # case and URL form both normalised
    out = _apply(FIXTURE.read_bytes(), wanted)
    assert (out["read"], out["kept"], out["updated"]) == (5, 2, 0)
    assert sorted(_papers()) == [90000001, 90000002]


def test_an_empty_wanted_set_keeps_nothing_and_still_records_the_file(medical):
    out = _apply(FIXTURE.read_bytes(), M.Wanted())
    assert out["kept"] == 0 and _papers() == {}
    with store.lane_session("medical") as s:
        (f,) = s.execute(select(MedicalFile)).scalars().all()
        assert (f.status, f.articles_read, f.deletions_read, f.books_skipped, f.kept) == ("finished", 5, 2, 1, 0)
        assert json.loads(f.skipped_json) == {"no readable PMID": 1}


def test_a_pmcid_alone_is_enough_to_keep_a_record(medical):
    wanted = M.Wanted()
    wanted.add("pmcid", "9000001")  # the PMC prefix is added
    _apply(FIXTURE.read_bytes(), wanted)
    assert list(_papers()) == [90000001]


def test_the_kept_record_carries_its_class_its_links_and_its_gaps(medical):
    wanted = M.Wanted()
    for p in ("90000002", "90000004"):
        wanted.add("pmid", p)
    _apply(FIXTURE.read_bytes(), wanted)
    papers = _papers()
    retracted = papers[90000002]
    assert retracted.provenance_class == "retracted"
    assert json.loads(retracted.status_links_json) == [["RetractionIn", 90000005, "Invented Clinical Letters 2021;3:4"]]
    old = papers[90000004]
    assert old.abstract_json is None, "a record with no abstract must stay a gap"
    assert (old.pub_date, old.pub_date_text) == (None, "1998 Dec-1999 Jan")


@pytest.mark.parametrize(
    ("kind", "value"),
    [("pmid", "abc"), ("pmid", "0"), ("doi", "not-a-doi"), ("doi", "10.1/a b"), ("pmcid", "PMCabc"), ("isbn", "1")],
)
def test_a_malformed_id_is_refused_by_name(kind, value):
    with pytest.raises(ValueError):
        M.normalise_id(kind, value)


def test_a_named_id_is_kept_once_and_removing_it_does_not_delete_the_paper(medical):
    with store.lane_session("medical") as s:
        assert M.add_wanted(s, "doi", "doi:10.9999/Preprint.3") == "10.9999/preprint.3"
        M.add_wanted(s, "doi", "10.9999/preprint.3")
        assert len(M.user_wanted(s)) == 1
    with store.lane_session("medical") as s:
        wanted = M.user_wanted(s)
    _apply(FIXTURE.read_bytes(), wanted)
    with store.lane_session("medical") as s:
        assert M.remove_wanted(s, "doi", "10.9999/preprint.3") is True
        assert M.remove_wanted(s, "doi", "10.9999/preprint.3") is False
    assert list(_papers()) == [90000003]


# --- what a later file does ------------------------------------------------------------------


def _one(pmid: int, ptypes: str, cc: str = "") -> bytes:
    return (
        f'<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">{pmid}</PMID>'
        f"<Article><ArticleTitle>t</ArticleTitle><PublicationTypeList>{ptypes}</PublicationTypeList></Article>{cc}"
        "</MedlineCitation></PubmedArticle></PubmedArticleSet>"
    ).encode()


def test_a_paper_that_becomes_retracted_keeps_the_record_of_when(medical):
    wanted = M.Wanted()
    wanted.add("pmid", "77")
    _apply(_one(77, "<PublicationType>Journal Article</PublicationType>"), wanted, "pubmed25n1300.xml.gz")
    _apply(_one(77, "<PublicationType>Retracted Publication</PublicationType>"), wanted, "pubmed25n1301.xml.gz")
    paper = _papers()[77]
    assert paper.provenance_class == "retracted" and paper.source_file == "pubmed25n1301.xml.gz"
    with store.lane_session("medical") as s:
        changes = [(c.from_class, c.to_class, c.source_file) for c in s.execute(select(MedicalClassChange)).scalars()]
    assert changes == [("journal", "retracted", "pubmed25n1301.xml.gz")]


def test_restating_the_same_class_records_no_change(medical):
    wanted = M.Wanted()
    wanted.add("pmid", "77")
    for name in ("pubmed25n1300.xml.gz", "pubmed25n1301.xml.gz"):
        _apply(_one(77, "<PublicationType>Journal Article</PublicationType>"), wanted, name)
    with store.lane_session("medical") as s:
        assert s.execute(select(MedicalClassChange)).scalars().all() == []


def test_a_withdrawal_marks_a_kept_paper_and_never_deletes_it(medical):
    wanted = M.Wanted()
    wanted.add("pmid", "90000007")
    _apply(_one(90000007, "<PublicationType>Journal Article</PublicationType>"), wanted)
    out = _apply(FIXTURE.read_bytes(), M.Wanted(), "pubmed25n1301.xml.gz")  # carries DeleteCitation 90000007
    assert out["withdrawn"] == 1
    paper = _papers()[90000007]
    assert paper.withdrawn_at is not None and paper.withdrawn_in_file == "pubmed25n1301.xml.gz"
    # A deletion for a PMID this install never kept stores nothing.
    assert sorted(_papers()) == [90000007]


def test_a_failed_pass_leaves_nothing_half_applied_and_says_failed(medical):
    wanted = M.Wanted()
    wanted.add("pmid", "90000001")
    truncated = FIXTURE.read_bytes()[:-200]
    with pytest.raises(Exception):  # noqa: B017 - the parse error's class is the XML library's
        _apply(truncated, wanted)
    assert _papers() == {}, "a failed pass kept records"
    with store.lane_session("medical") as s:
        M.record_failed_file(s, "pubmed25n1300.xml.gz", ValueError("x"))
    with store.lane_session("medical") as s:
        (f,) = s.execute(select(MedicalFile)).scalars().all()
        assert (f.status, f.error, f.kept) == ("failed", "ValueError", 0)


def test_a_name_that_is_not_an_nlm_file_is_refused(medical):
    with pytest.raises(ValueError, match="not an NLM"):
        _apply(FIXTURE.read_bytes(), M.Wanted(), "../../etc/passwd")


def test_the_summary_counts_classes_and_withdrawals_from_the_store(medical):
    wanted = M.Wanted()
    for p in ("90000001", "90000002", "90000003"):
        wanted.add("pmid", p)
    _apply(FIXTURE.read_bytes(), wanted)
    with store.lane_session("medical") as s:
        out = M.summary(s)
    assert out["papers"] == 3
    assert out["by_class"] == {"journal": 1, "preprint": 1, "retracted": 1}
    assert out["withdrawn"] == 0 and out["last_file"]["name"] == "pubmed25n1300.xml.gz"


# --- R746: the backup row says it plainly -----------------------------------------------------


def test_the_backup_row_says_plainly_that_medical_papers_are_not_carried(medical):
    from src.backup.inventory import MEDICAL_WAITING, _lane_member

    row = _lane_member()
    assert "medical" in row["waiting"] and "medical" not in row["breakdown"]
    assert row["waiting_note"] == MEDICAL_WAITING
    assert "not include your medical papers" in MEDICAL_WAITING and "fetched again" in MEDICAL_WAITING


def test_the_waiting_note_is_translated_and_drawn_visibly_not_only_in_a_hover():
    from src.backup.inventory import MEDICAL_WAITING

    root = Path(__file__).resolve().parents[1]
    for loc in sorted((root / "src" / "static" / "locales").glob("*.json")):
        data = json.loads(loc.read_text(encoding="utf-8"))
        assert data.get(MEDICAL_WAITING), f"{loc.name} lacks the R746 note"
        assert data.get("Medical papers (PubMed)"), f"{loc.name} lacks the lane's name"
    js = (root / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert "d.waiting_note ? `<div" in js and "data-waiting-note" in js
    assert 'medical: t("Medical papers (PubMed)")' in js


# --- erase and uninstall reach medical.db -----------------------------------------------------


def test_crypto_erase_destroys_an_encrypted_medical_db(tmp_path):
    from src.safety import crypto_erase

    data = tmp_path / "OOS data"
    data.mkdir()
    for name in ("open_omniscience.db", "medical.db"):
        con = connect(data / name, key=PASSPHRASE)
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert "medical.db" in report["headers_destroyed"]
    assert not (data / "medical.db").exists()


def test_the_uninstall_watcher_is_handed_medical_db_as_an_app_file(tmp_path, monkeypatch):
    from src.safety import uninstall

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plan = uninstall.plan_uninstall(tmp_path / "src", wipe_data=True)
    spawned = {}
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda argv, **_k: spawned.setdefault("payload", json.loads(argv[-1])))
    uninstall._default_spawn({**plan, "venv": None}, 1)
    assert "medical.db" in spawned["payload"]["enc_names"]
    assert "medical.db" in spawned["payload"]["app_only"]["names"]


def test_the_uninstall_watcher_wipes_a_medical_db_in_a_shared_folder_and_leaves_the_rest(tmp_path):
    from src.safety.data_scope import owned_spec
    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    shared = tmp_path / "Documents"
    shared.mkdir()
    (shared / "medical.db").write_bytes(b"S" * 8192)
    (shared / "my-notes.txt").write_text("not the app's", encoding="utf-8")
    audit = tmp_path / "audit.log"
    plan = {
        "files": [],
        "venv": None,
        "app_folder": None,
        "wipe_data_dir": str(shared),
        "app_only": owned_spec(shared=True),
        "audit_log": str(audit),
    }
    subprocess.run([sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)], check=True, timeout=60)
    assert not (shared / "medical.db").exists(), "the watcher left medical.db behind"
    assert (shared / "my-notes.txt").exists(), "the watcher took a file that was not the app's"


def test_a_doi_written_in_capitals_in_the_record_still_matches(medical):
    xml = (
        b'<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">55</PMID>'
        b"<Article><ArticleTitle>t</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList>"
        b'<ArticleId IdType="doi">10.9999/ABC.Def</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
    )
    wanted = M.Wanted()
    wanted.add("doi", "10.9999/abc.def")
    _apply(xml, wanted)
    assert _papers()[55].doi == "10.9999/abc.def"


# --- the store review read's findings (2026-11-19), each pinned ------------------------------


def _many(*records: tuple[int, int, str], deletions: tuple[tuple[int, int], ...] = ()) -> bytes:
    body = "".join(
        f'<PubmedArticle><MedlineCitation><PMID Version="{v}">{p}</PMID><Article><ArticleTitle>t</ArticleTitle>'
        f"<PublicationTypeList><PublicationType>{pt}</PublicationType></PublicationTypeList></Article></MedlineCitation></PubmedArticle>"
        for p, v, pt in records
    )
    if deletions:
        body += "<DeleteCitation>" + "".join(f'<PMID Version="{v}">{p}</PMID>' for p, v in deletions) + "</DeleteCitation>"
    return f'<?xml version="1.0"?><PubmedArticleSet>{body}</PubmedArticleSet>'.encode()


def _want(*pmids: str) -> M.Wanted:
    w = M.Wanted()
    for p in pmids:
        w.add("pmid", p)
    return w


def test_a_record_stated_twice_in_one_file_is_kept_once_with_its_last_statement(medical):
    out = _apply(_many((77, 1, "Journal Article"), (77, 1, "Retracted Publication")), _want("77"))
    assert (out["kept"], out["updated"]) == (1, 1)
    assert _papers()[77].provenance_class == "retracted"


def test_a_withdrawal_later_in_the_same_file_reaches_the_record_kept_earlier_in_it(medical):
    out = _apply(_many((77, 1, "Journal Article"), deletions=((77, 1),)), _want("77"))
    assert out["withdrawn"] == 1 and _papers()[77].withdrawn_at is not None


def test_a_withdrawal_of_one_version_leaves_the_other_version(medical):
    _apply(_many((77, 1, "Journal Article"), (77, 2, "Journal Article")), _want("77"))
    out = _apply(_many(deletions=((77, 2),)), M.Wanted(), "pubmed25n1301.xml.gz")
    assert out["withdrawn"] == 1
    with store.lane_session("medical") as s:
        rows = {r.version: r.withdrawn_at for r in s.execute(select(MedicalPaper)).scalars()}
    assert rows[1] is None and rows[2] is not None


def test_a_later_file_restating_a_withdrawn_record_brings_it_back(medical):
    _apply(_many((77, 1, "Journal Article"), deletions=((77, 1),)), _want("77"), "pubmed25n1300.xml.gz")
    _apply(_many((77, 1, "Journal Article")), _want("77"), "pubmed25n1301.xml.gz")
    paper = _papers()[77]
    assert paper.withdrawn_at is None and paper.withdrawn_in_file is None


def test_an_older_file_applied_after_a_newer_one_never_undoes_a_retraction(medical):
    _apply(_many((77, 1, "Retracted Publication")), _want("77"), "pubmed25n1301.xml.gz")
    out = _apply(_many((77, 1, "Journal Article"), (78, 1, "Journal Article")), _want("77", "78"), "pubmed25n0005.xml.gz")
    assert out["older_skipped"] == 1 and out["kept"] == 1  # the older file still ADDS what the store lacks
    papers = _papers()
    assert papers[77].provenance_class == "retracted" and papers[77].source_file == "pubmed25n1301.xml.gz"
    assert sorted(papers) == [77, 78]
    with store.lane_session("medical") as s:
        assert s.execute(select(MedicalClassChange)).scalars().all() == []


def test_an_older_file_never_withdraws_what_a_newer_one_stated(medical):
    _apply(_many((77, 1, "Journal Article")), _want("77"), "pubmed25n1301.xml.gz")
    out = _apply(_many(deletions=((77, 1),)), M.Wanted(), "pubmed25n1300.xml.gz")
    assert (out["withdrawn"], out["older_skipped"]) == (0, 1)
    assert _papers()[77].withdrawn_at is None


def test_a_new_years_baseline_ranks_after_last_years_updates():
    assert M.file_sequence("pubmed26n0001.xml.gz") > M.file_sequence("pubmed25n1400.xml.gz")
    assert M.file_sequence("not-a-file") < M.file_sequence("pubmed25n0001.xml")


def test_every_fallback_name_list_and_every_lane_loop_includes_medical_db():
    root = Path(__file__).resolve().parents[1]
    for rel in ("src/safety/uninstall.py", "src/safety/data_scope.py", "src/database/open_stats.py"):
        assert '"medical.db"' in (root / rel).read_text(encoding="utf-8"), rel
    release = (root / "src/monitoring/release_run.py").read_text(encoding="utf-8")
    assert 'for kind in ("wiki", "law", "osm"):' not in release


def test_an_older_file_never_undoes_a_newer_withdrawal(medical):
    _apply(_many((1, 1, "Journal Article")), _want("1"), "pubmed25n0001.xml.gz")
    _apply(_many(deletions=((1, 1),)), _want("1"), "pubmed25n1300.xml.gz")
    # A re-read of the baseline file (say, for an identifier named later) states it again.
    out = _apply(_many((1, 1, "Journal Article")), _want("1"), "pubmed25n0001.xml.gz")
    assert (out["updated"], out["older_skipped"]) == (0, 1)
    paper = _papers()[1]
    assert paper.withdrawn_at is not None and paper.withdrawn_in_file == "pubmed25n1300.xml.gz"


def test_a_restatement_then_a_deletion_in_one_file_ends_withdrawn(medical):
    _apply(_many((2, 1, "Journal Article")), _want("2"), "pubmed25n0002.xml.gz")
    _apply(_many(deletions=((2, 1),)), _want("2"), "pubmed25n1301.xml.gz")
    out = _apply(_many((2, 1, "Journal Article"), deletions=((2, 1),)), _want("2"), "pubmed25n1302.xml.gz")
    assert (out["updated"], out["withdrawn"]) == (1, 1)
    assert _papers()[2].withdrawn_in_file == "pubmed25n1302.xml.gz"


def test_a_deletion_repeated_in_one_file_is_counted_once(medical):
    _apply(_many((2, 1, "Journal Article")), _want("2"), "pubmed25n0002.xml.gz")
    out = _apply(_many(deletions=((2, 1), (2, 1))), _want("2"), "pubmed25n1304.xml.gz")
    assert out["withdrawn"] == 1
    with store.lane_session("medical") as s:
        f = s.execute(select(MedicalFile).where(MedicalFile.name == "pubmed25n1304.xml.gz")).scalar_one()
        assert (f.withdrawn, f.older_skipped) == (1, 0)


def test_the_file_row_records_what_newer_files_had_overtaken(medical):
    _apply(_many((5, 1, "Retracted Publication")), _want("5"), "pubmed25n1301.xml.gz")
    _apply(_many((5, 1, "Journal Article")), _want("5"), "pubmed25n0005.xml.gz")
    with store.lane_session("medical") as s:
        f = s.execute(select(MedicalFile).where(MedicalFile.name == "pubmed25n0005.xml.gz")).scalar_one()
        assert f.older_skipped == 1


@pytest.mark.parametrize(
    "written",
    ["10.1000/ABC", "doi:10.1000/abc", "doi: 10.1000/abc", "https://doi.org/10.1000/abc", "doi.org/10.1000/abc", "dx.doi.org/10.1000/abc"],
)
def test_every_common_way_of_writing_a_doi_names_the_same_paper(written):
    assert M.normalise_id("doi", written) == "10.1000/abc"
