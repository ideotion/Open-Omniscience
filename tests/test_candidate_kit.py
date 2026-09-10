"""The candidate kit: a session without the repository gets everything the pipeline imports.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Pinned here: the kit carries the scripts at their repository paths, the whole ``src`` minus the
UI and bytecode, the catalogues, the runbook byte-for-byte, a pinned requirements file and a
manifest whose hashes match; it carries no app shell and no ledger; the worklists are the
shortlist and the ordered remainder with the columns Stage A reads; the kit's own self-check
passes when run from the kit alone (its ``src`` is the kit's, not the repository's); and the
Stage A script builds the ONE ethical fetcher directly in a kit and through the app's factory
in the repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, default: Path):
    p = Path(os.environ.get(name) or default)
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bck = _load("BCK_MODULE", _ROOT / "scripts" / "analysis" / "build_candidate_kit.py")
vcf = _load("VCF_MODULE", _ROOT / "scripts" / "analysis" / "verify_candidate_feeds.py")

_HEADER = "name,domain,rss_url,source_type,country,language,region,tags,priority,rate_limit_ms,enabled,reliability_score\n"


def _export(tmp_path: Path, *, catalogue_fr: int = 20) -> Path:
    """A tiny export. With 20 French catalogue rows the French candidates are T4 (the country has
    5+ sources and the language 20+); with 2 they are T2 -- the gap classes are the catalogue's."""
    rows = [
        f'Journal {i},journal{i}.fr,https://journal{i}.fr/rss,news,fr,fr,europe,"news,via:curated",1,2000,True,'
        for i in range(catalogue_fr)
    ] + [
        # discovered news: one in a country with NO catalogue source (T1), three French
        '24ora,24ora.com,,news,aw,,global,"news,world-catalog,via:wikidata-discovery",2,2000,False,',
        'Ouest-France,ouest-france.fr,,news,fr,fr,global,"news,world-catalog,via:wikidata-discovery",2,2000,False,',
        'Le Télégramme,letelegramme.fr,,news,fr,fr,global,"news,world-catalog,via:wikidata-discovery",2,2000,False,',
        'La Dépêche,ladepeche.fr,,news,fr,fr,global,"news,world-catalog,via:wikidata-discovery",2,2000,False,',
        # discovered but not news: never a candidate
        'Ministère,interieur.gouv.fr,,institution,fr,fr,global,"government,institution,via:wikidata-discovery",2,2000,False,',
        # a discovered duplicate of a catalogue domain: dropped
        'Journal 0 (dup),www.journal0.fr,,news,fr,fr,global,"news,via:wikidata-discovery",2,2000,False,',
    ]
    p = tmp_path / "open-omniscience-sources.csv"
    p.write_text(_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def _read(path: Path) -> list[dict]:
    import csv

    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def kit(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("kit")
    return bck.build_kit(export=_export(tmp), out_dir=tmp / "out", date_str="2026-09-10", commit="abc1234")


def test_the_kit_carries_the_pipeline_at_its_repository_paths_and_nothing_of_the_shell(kit: Path):
    for rel in bck.SCRIPT_FILES + bck.TEST_FILES:
        assert (kit / rel).read_bytes() == (_ROOT / rel).read_bytes(), rel
    assert (kit / "RUN.md").read_bytes() == (_ROOT / bck.RUNBOOK).read_bytes()
    assert (kit / "selfcheck.py").read_bytes() == (_ROOT / bck.SELFCHECK).read_bytes()
    for rel in ("LICENSE", "requirements.txt", "tests/conftest.py", "KIT_MANIFEST.json",
                "src/ingest/__init__.py", "src/safety/fetcher.py", "src/catalog/data/public_suffix_list.dat",
                "src/analytics/langdetect.py", "configs/sources.yml", "configs/sources_spectrum.yml",
                "worklists/worklist_1_shortlist.csv", "worklists/worklist_2_remainder.csv", "worklists/WORKLISTS.md",
                "export/open-omniscience-sources.csv"):
        assert (kit / rel).is_file(), rel
    assert not (kit / "src" / "static").exists()
    assert not (kit / "src" / "geo" / "data").exists()
    assert not (kit / "CLAUDE.md").exists() and not (kit / "docs").exists() and not (kit / "pyproject.toml").exists()
    assert not list(kit.rglob("__pycache__")) and not list(kit.rglob("*.pyc"))


def test_the_manifest_names_the_build_and_hashes_every_file(kit: Path):
    m = json.loads((kit / "KIT_MANIFEST.json").read_text(encoding="utf-8"))
    assert m["id"] == "oo-candidate-kit-2026-09-10-abc1234" and m["commit"] == "abc1234" and m["kit_version"] == bck.KIT_VERSION
    assert m["export"]["rows"] == 26
    files = m["files"]
    assert "KIT_MANIFEST.json" not in files
    on_disk = {p.relative_to(kit).as_posix() for p in kit.rglob("*") if p.is_file()} - {"KIT_MANIFEST.json"}
    assert set(files) == on_disk
    for rel in ("RUN.md", "scripts/analysis/verify_candidate_feeds.py", "configs/sources.yml"):
        assert files[rel] == hashlib.sha256((kit / rel).read_bytes()).hexdigest()


def test_the_requirements_pin_what_the_scripts_import(kit: Path):
    text = (kit / "requirements.txt").read_text(encoding="utf-8")
    for name in ("requests==", "feedparser==", "py3langid==", "PyYAML==", "pytest==", "cryptography==", "bleach=="):
        assert name in text, name
    assert all("==" in ln for ln in text.splitlines() if ln and not ln.startswith("#"))


def test_the_worklists_are_the_shortlist_and_the_ordered_remainder(kit: Path):
    short = _read(kit / "worklists" / "worklist_1_shortlist.csv")
    rest = _read(kit / "worklists" / "worklist_2_remainder.csv")
    assert list(short[0].keys()) == list(bck.WORKLIST_FIELDS)
    assert [r["domain"] for r in short] == ["24ora.com"] and short[0]["tier"] == "T1"
    assert short[0]["source_type"] == "news" and "via:wikidata-discovery" in short[0]["tags"]
    assert [r["domain"] for r in rest] == ["ladepeche.fr", "letelegramme.fr", "ouest-france.fr"]  # T4, by name
    assert {r["tier"] for r in rest} == {"T4"}
    all_domains = {r["domain"] for r in short + rest}
    assert "interieur.gouv.fr" not in all_domains and "journal0.fr" not in all_domains and "www.journal0.fr" not in all_domains
    m = json.loads((kit / "KIT_MANIFEST.json").read_text(encoding="utf-8"))["worklists"]
    assert m["worklist_1_shortlist"] == 1 and m["worklist_2_remainder"] == 3 and m["news_rows"] == 5 and m["news_kept"] == 4


def test_the_remainder_starts_with_the_capped_out_overflow(tmp_path: Path):
    rows, _ = bck.load_export(_export(tmp_path, catalogue_fr=2))  # two French catalogue rows -> French candidates are T2
    counts = bck.build_worklists(rows, _ROOT, tmp_path / "wl", cap=1)
    short = _read(tmp_path / "wl" / "worklist_1_shortlist.csv")
    rest = _read(tmp_path / "wl" / "worklist_2_remainder.csv")
    assert [(r["tier"], r["domain"]) for r in short] == [("T1", "24ora.com"), ("T2", "ladepeche.fr")]  # one per country
    assert [(r["tier"], r["domain"]) for r in rest] == [("T2", "letelegramme.fr"), ("T2", "ouest-france.fr")]
    assert counts["capped_countries"] == {"fr": 3} and counts["worklist_1_shortlist"] == 2 and counts["worklist_2_remainder"] == 2


def test_the_kit_self_check_passes_from_the_kit_alone(kit: Path, tmp_path: Path):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "OO_REPO_ROOT", "VCF_MODULE", "TB_MODULE", "MSB_MODULE")}
    env["OO_DATA_DIR"] = str(tmp_path / "data")
    proc = subprocess.run([sys.executable, "selfcheck.py"], cwd=kit, env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELFCHECK OK" in proc.stdout
    assert f"src: {(kit / 'src').resolve()}" in proc.stdout, proc.stdout
    assert "fetcher: kit" in proc.stdout


def test_the_zip_is_the_folder_with_the_build_date_as_every_timestamp(kit: Path):
    import zipfile

    z = bck.zip_kit(kit)
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert all(n.startswith(kit.name + "/") for n in names)
        assert kit.name + "/RUN.md" in names and kit.name + "/KIT_MANIFEST.json" in names
        assert {i.date_time for i in zf.infolist()} == {(2026, 9, 10, 0, 0, 0)}


# ------------------------------------------------------------------ the fetcher seam

def test_in_a_kit_stage_a_builds_the_same_ethical_fetcher_directly_in_transparent_mode(tmp_path: Path):
    from src.ingest import DEFAULT_USER_AGENT, EthicalFetcher

    (tmp_path / vcf.KIT_MARKER).write_text("{}", encoding="utf-8")
    fetcher, mode = vcf.build_fetcher(min_interval_s=2.0, timeout=20.0, max_bytes=4096, root=tmp_path)
    assert isinstance(fetcher, EthicalFetcher) and fetcher.user_agent == DEFAULT_USER_AGENT
    assert fetcher.proxy is None and fetcher.min_interval_s == 2.0 and fetcher.timeout == 20.0 and fetcher.max_bytes == 4096
    assert mode.startswith("kit")


def test_in_the_repository_stage_a_goes_through_the_app_factory(tmp_path: Path, monkeypatch):
    import src.safety.fetcher as sf

    calls: list[dict] = []
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: calls.append(kw) or "FACTORY")
    fetcher, mode = vcf.build_fetcher(min_interval_s=1.5, timeout=9.0, max_bytes=7, root=tmp_path)
    assert fetcher == "FACTORY" and calls == [{"min_interval_s": 1.5, "timeout": 9.0, "max_bytes": 7}]
    assert "make_fetcher" in mode
