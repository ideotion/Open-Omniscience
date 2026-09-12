"""Self-check of the candidate kit -- run from the kit's root, offline, before any credit is spent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Copied into the kit as ``selfcheck.py`` by ``build_candidate_kit.py``. It proves, in this order
and without touching any publisher host:

1. the kit's OWN ``src`` is the one being imported (never an installed copy of the app), and
   every module the three scripts use imports -- the fetcher, the domain tables, the taxonomy,
   the language detector, feedparser, YAML;
2. the language detector really works here (py3langid found its model);
3. the two fake-fetcher test files pass (verification rules, feed discovery, triage glue, the
   splice's refusals);
4. the REAL fetcher is built exactly as ``verify_candidate_feeds.py`` builds it in a kit and
   refuses an unresolvable ``.invalid`` host with a named ``FetchError`` -- the guarded path is
   live -- and its robots cache is rooted under ``OO_DATA_DIR``;
5. prepare -> a scripted result -> merge -> the splice plan, end to end on a two-row fixture.

Prints ``SELFCHECK OK`` and exits 0, or names the first failure and exits 1. Runs in the
repository too (the marker is absent there, so step 4 goes through the app's factory).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OO_DATA_DIR", str(ROOT / "data"))
sys.dont_write_bytecode = True  # the kit stays exactly what the manifest hashes
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

MODULES = (
    "src.ingest", "src.ingest.ssrf_guard", "src.safety.fetcher", "src.safety.settings",
    "src.catalog.countries", "src.catalog.normalize", "src.catalog.taxonomy", "src.catalog.cctld",
    "src.utils.url_utils", "src.analytics.langdetect", "src.paths",
    "feedparser", "yaml", "py3langid",
)


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through here
    spec.loader.exec_module(mod)
    return mod


def step_imports() -> str:
    import importlib

    for m in MODULES:
        importlib.import_module(m)
    import src

    where = Path(src.__file__).resolve().parent
    if where != (ROOT / "src").resolve():
        raise AssertionError(f"src imported from {where}, not from the kit ({ROOT / 'src'})")
    return f"src: {where}"


def step_language() -> str:
    from src.analytics.langdetect import detect_language

    text = " ".join(["Le conseil municipal adopte le budget de la commune pour l'année prochaine"] * 4)
    got = detect_language(text)
    if got != "fr":
        raise AssertionError(f"detector answered {got!r} for a French paragraph (model missing?)")
    return "language detector: fr"


def step_tests() -> str:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise AssertionError("pytest failed:\n" + (proc.stdout + proc.stderr)[-4000:])
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    return f"tests: {last}"


def step_fetcher() -> str:
    from src.ingest import DEFAULT_USER_AGENT, FetchError

    vcf = _load("scripts/analysis/verify_candidate_feeds.py", "verify_candidate_feeds")
    fetcher, mode = vcf.build_fetcher(min_interval_s=0.0, timeout=5.0, max_bytes=4096)
    if fetcher.user_agent != DEFAULT_USER_AGENT:
        raise AssertionError(f"user agent is {fetcher.user_agent!r}, not the honest default")
    cache = Path(fetcher._robots_cache_path).resolve()
    data = Path(os.environ["OO_DATA_DIR"]).resolve()
    if data not in cache.parents:
        raise AssertionError(f"robots cache {cache} is not under OO_DATA_DIR {data}")
    try:
        fetcher.fetch("https://nonexistent-host.invalid/", require_html=True)
    except FetchError as exc:
        return f"fetcher: {mode}; refused .invalid with {type(exc).__name__}"
    raise AssertionError("fetching an .invalid host did not raise a FetchError")


def step_pipeline() -> str:
    tb = _load("scripts/analysis/triage_batches.py", "triage_batches")
    msb = _load("scripts/merge_source_batch.py", "merge_source_batch")
    with tempfile.TemporaryDirectory(prefix="oo-kit-selfcheck-") as tmp:
        d = Path(tmp)
        rows = []
        for i, kind in enumerate(("news", "institution")):
            rows.append({
                "domain": f"s{i}.example", "name": f"Source {i}", "source_type": "news", "country": "fr",
                "language_export": "fr", "status": "verified", "reason": "verified",
                "homepage_url": f"https://s{i}.example/", "site_title": f"Source {i}",
                "description": "Le journal", "feed_url": f"https://s{i}.example/feed", "feed_kind": "link",
                "feed_probes": 1, "entries": 5, "dated_entries": 5,
                "newest_entry": "2026-09-08T10:00:00+00:00", "titles": ["Le conseil municipal adopte le budget"],
                "language_detected": "fr", "language_basis": "detected", "robots": "allowed",
                "tags": ["news", "world-catalog", "via:wikidata-discovery"], "elapsed_s": 1.0,
                "checked_at": "2026-09-10T12:00:00", "_kind": kind,
            })
        verified = d / "verified.jsonl"
        verified.write_text("".join(json.dumps({k: v for k, v in r.items() if k != "_kind"}) + "\n" for r in rows), encoding="utf-8")
        manifest = tb.prepare(verified, d / "triage")
        if len(manifest["batches"]) != 1:
            raise AssertionError(f"expected one batch, got {len(manifest['batches'])}")
        vocab = json.loads((d / "triage" / "vocabulary.json").read_text(encoding="utf-8"))
        if not vocab:
            raise AssertionError("the topic vocabulary is empty -- configs/sources.yml missing from the kit?")
        batch = json.loads(Path(manifest["batches"][0]).read_text(encoding="utf-8"))
        kinds = {r["domain"]: r["_kind"] for r in rows}
        out = []
        for r in batch:
            c = next((x for x in tb.CANARIES if x["domain"] == r["domain"]), None)
            if c:
                # Echo EVERY expected field, including primary_source where the canary carries
                # one -- a canary answered short is a canary failed, which is the point of it.
                out.append({"domain": r["domain"], "topics": [], "confidence": "high",
                            **c["expected"]})
            else:
                k = kinds[r["domain"]]
                row = {"domain": r["domain"], "journalism": k == "news", "kind": k, "language": "fr",
                       "topics": [vocab[0]], "confidence": "high"}
                if k == "institution":
                    # The 2026-09-11 split: an institution is admitted only as a PRIMARY SOURCE.
                    # False here keeps this fixture's one merged entry the news row, so the
                    # assertion below still measures what it always measured.
                    row["primary_source"] = False
                out.append(row)
        Path(manifest["batches"][0].replace(".json", ".result.json")).write_text(json.dumps({"rows": out}), encoding="utf-8")
        summary = tb.merge(verified, d / "triage", d / "triaged.yml", today="2026-09-10")
        if summary["entries"] != 1 or summary["untrusted_batches"]:
            raise AssertionError(f"merge produced {summary}")
        import yaml

        entries = yaml.safe_load((d / "triaged.yml").read_text(encoding="utf-8"))["sources"]
        existing = msb.catalogue_domains(ROOT)
        if not existing:
            raise AssertionError("no catalogue domains loaded -- configs/ missing from the kit?")
        accepted, refused = msb.plan(entries, existing=existing)
        if len(accepted) != 1 or refused:
            raise AssertionError(f"splice plan: accepted {len(accepted)}, refused {refused}")
        bad = dict(entries[0], tags=list(entries[0]["tags"]) + ["via:curated"])
        why = msb.check_entry(bad, existing=existing, seen=set())
        if not why or "via:" not in why:
            raise AssertionError(f"the splice did not refuse a provenance tag: {why!r}")
        return f"pipeline: prepare -> merge ({summary['entries']} entry) -> splice plan (1 accepted, refuses via: tags); {len(existing)} catalogue domains loaded"


STEPS = (
    ("imports", step_imports), ("language", step_language), ("tests", step_tests),
    ("fetcher", step_fetcher), ("pipeline", step_pipeline),
)


def main() -> int:
    print(f"python {sys.version.split()[0]}  root {ROOT}  OO_DATA_DIR {os.environ['OO_DATA_DIR']}")
    for name, fn in STEPS:
        try:
            print(f"ok   {fn()}", flush=True)
        except Exception as exc:  # noqa: BLE001 - the first failure is the report
            print(f"FAIL {name}: {exc}", flush=True)
            print("SELFCHECK FAILED")
            return 1
    print("SELFCHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
