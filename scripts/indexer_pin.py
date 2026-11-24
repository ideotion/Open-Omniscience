#!/usr/bin/env python3
"""Record the engine files' digest against INDEXER_VERSION (R412, which amends R24).

The engine identity carries a hand-bumped ``INDEXER_VERSION``; ``code_digest()`` (the hash of the
files an indexing pass reads) polices it. ``configs/indexer_pin.json`` holds the digest as of the
last judgement, and ``tests/test_indexer_pin.py`` is red whenever the two disagree. This script is
the only sanctioned way to turn it green again, and it refuses to do so without a sentence:

    python scripts/indexer_pin.py --bump "what changed in the rows an article gets"
    python scripts/indexer_pin.py --same "why the rows an article gets are identical"
    python scripts/indexer_pin.py --check       # exit 1 when the pin is stale (what the test asserts)

``--engine www`` does the same for the places-and-entities stage (``WWW_INDEXER_VERSION``, ``configs/www_indexer_pin.json``, R415).

``--bump`` raises INDEXER_VERSION by one: every article's stamp stops matching, so the next restore or
re-index re-extracts it, and the release notes owe a line (R319). ``--same`` keeps the version: a
backup from the previous build still carries its derived rows. Choose ``--same`` only for a change that
cannot alter any row ``index_article`` writes (a docstring, a log line, a rename, an unrelated function).
A data file, a dictionary, a rule or a stoplist entry DOES alter rows: that is a ``--bump``.
The sentence goes into the pin's log and must be repeated in the PR description.

THE OUTPUT DIGEST (R824 step 1, row 405) is the guard on that sentence. ``configs/extraction_digests.json`` records, per
engine, the digest of the rows a real baseline pass writes over the golden corpus (``tests/fixtures/extraction_golden/``,
computed by ``src/analytics/golden_output.py``) and the environment it was computed in. ``--same`` REFUSES unless the
output digest computed here equals the recorded one, and refuses as well when this environment differs from the recorded
one (it cannot judge here). ``--same --engine www`` also refuses while the www rules can match a script the golden www rows do not
hold (R824 addition 2: no ACK without golden coverage of the scripts a stage handles). ``--bump`` re-records the output digest at
the new version.

    python scripts/indexer_pin.py --record-output   # first stamping only: version unchanged, no digest recorded yet
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: ``OO_INDEXER_PIN`` / ``OO_INDEXER_MODULE`` point the script at copies; the tests use them so that exercising the script can never
#: record a judgement in the real pin.
MODULE = Path(os.environ.get("OO_INDEXER_MODULE") or ROOT / "src" / "analytics" / "engine_identity.py")
#: engine -> (pin file, version constant, digest function). "kw" is the keyword-and-dates engine (R412); "www" is the places-and-entities
#: engine (R415), whose code and gazetteers are versioned and pinned on their own.
ENGINES = {
    "kw": ("indexer_pin.json", "INDEXER_VERSION", "code_digest"),
    "www": ("www_indexer_pin.json", "WWW_INDEXER_VERSION", "www_code_digest"),
}
MIN_NOTE = 12
STAGE_OF = {"kw": "kw", "www": "www"}


def _pin_path(engine: str) -> Path:
    return Path(os.environ.get("OO_INDEXER_PIN") or ROOT / "configs" / ENGINES[engine][0])


def _digests_path() -> Path:
    """``OO_EXTRACTION_DIGESTS`` names a copy; when only ``OO_INDEXER_PIN`` is set (a test exercising the script) the
    digests file is the pin's sibling, so a test can never record an output digest in the real file by forgetting it."""
    if os.environ.get("OO_EXTRACTION_DIGESTS"):
        return Path(os.environ["OO_EXTRACTION_DIGESTS"])
    if os.environ.get("OO_INDEXER_PIN"):
        return Path(os.environ["OO_INDEXER_PIN"]).with_name("extraction_digests.json")
    return ROOT / "configs" / "extraction_digests.json"


def _golden(engine: str) -> dict:
    sys.path.insert(0, str(ROOT))
    from src.analytics import golden_output

    return golden_output.golden_output(STAGE_OF[engine])


def _record_output(engine: str, version: int, golden: dict) -> Path:
    path = _digests_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    from src.analytics import golden_output

    fx = golden_output.load_fixture()
    data[engine] = {
        "version": version,
        "output_digest": golden["output_digest"],
        "environment": golden["environment"],
        "articles": golden["articles"],
        "rows": golden["rows"],
        "scripts_covered": golden_output.scripts_covered(fx),
    }
    data = {k: data[k] for k in sorted(data)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def _refuse_same_on_output(engine: str) -> None:
    """--same is a claim that the rows did not change: check it against the golden corpus before recording it."""
    from src.analytics.golden_output import environment_differences

    rec = (json.loads(_digests_path().read_text(encoding="utf-8")) if _digests_path().exists() else {}).get(engine)
    if not rec or not rec.get("output_digest"):
        raise SystemExit(
            f"--same refused: no output digest is recorded for the {engine} engine in {_digests_path().name}; "
            "record one first (--record-output on an unchanged version)"
        )
    golden = _golden(engine)
    diffs = environment_differences(rec.get("environment") or {}, golden["environment"])
    if diffs:
        raise SystemExit(
            "--same refused: cannot judge here. The output digest was recorded in another environment "
            f"(differs in: {', '.join(diffs)}); run it in a venv installed from requirements.lock "
            "(pip install --require-hashes -r requirements.lock; pip install -e . --no-deps), the environment CI's "
            "lockfile-install job checks the digest in"
        )
    if engine == "www":
        # R824 addition 2: an ACK needs golden coverage of every script the stage handles. The golden corpus holds texts in all twelve
        # UI scripts, but it exercises the www stage only in the scripts its rows come out in, so a stage that can match a script the
        # golden rows never hold cannot be judged unchanged here.
        from src.analytics import golden_output

        handled = golden_output.www_rule_scripts()
        covered = golden_output.www_golden_scripts(golden_output._cached_pass()["www"])
        missing = sorted(set(handled) - set(covered))
        if missing:
            raise SystemExit(
                f"--same refused: the places-and-entities rules now match {', '.join(missing)}, which the golden corpus's www rows do "
                "not cover; add golden articles whose places or entities are in that script (and re-record with --bump), or --bump"
            )
    if golden["output_digest"] != rec["output_digest"]:
        raise SystemExit(
            f"--same refused: the output changed (golden corpus digest {golden['output_digest'][:12]}, recorded "
            f"{rec['output_digest'][:12]}): the rows index_article writes are different, this is a --bump"
        )


def _load(pin: Path) -> dict:
    return json.loads(pin.read_text(encoding="utf-8")) if pin.exists() else {"version": 0, "digest": "", "log": []}


def _digest(engine: str) -> str:
    sys.path.insert(0, str(ROOT))
    from src.analytics import engine_identity as ei

    fn = getattr(ei, ENGINES[engine][2])
    fn.cache_clear()
    return fn()


def _set_version(engine: str, new: int) -> None:
    const = ENGINES[engine][1]
    line = re.compile(rf"^{const} = (\d+)$", re.M)
    text = MODULE.read_text(encoding="utf-8")
    if not line.search(text):
        raise SystemExit(f"{const} line not found in engine_identity.py")
    MODULE.write_text(line.sub(f"{const} = {new}", text, count=1), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=sorted(ENGINES), default="kw", help="kw (keywords and dates, the default) or www (places and entities)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bump", metavar="WHAT", help="the output of the engine changed: raise the version")
    g.add_argument("--same", metavar="WHY", help="the output did not change: keep the version, re-record the digest")
    g.add_argument("--check", action="store_true")
    g.add_argument(
        "--record-output", action="store_true",
        help="first stamping only: record the golden output digest when the version is unchanged and none is recorded",
    )
    a = ap.parse_args(argv)
    pin_path = _pin_path(a.engine)
    pin = _load(pin_path)
    digest = _digest(a.engine)
    if a.check:
        ok = pin.get("digest") == digest
        print("pin current" if ok else f"pin STALE: recorded {pin.get('digest','')[:12]} actual {digest[:12]}")
        return 0 if ok else 1
    if a.record_output:
        found = re.search(rf"^{ENGINES[a.engine][1]} = (\d+)$", MODULE.read_text(encoding="utf-8"), re.M)
        if not found:
            raise SystemExit(f"{ENGINES[a.engine][1]} line not found in engine_identity.py")
        const = int(found.group(1))
        if int(pin.get("version", 0)) != int(const):
            raise SystemExit(f"--record-output refused: the pin says version {pin.get('version')} and the code {const}")
        rec = (json.loads(_digests_path().read_text(encoding="utf-8")) if _digests_path().exists() else {}).get(a.engine)
        if rec and rec.get("output_digest"):
            raise SystemExit(
                "--record-output refused: an output digest is already recorded; it moves only with --bump "
                "(or stays, checked, with --same)"
            )
        golden = _golden(a.engine)
        path = _record_output(a.engine, int(const), golden)
        print(f"recorded {a.engine} output digest {golden['output_digest'][:12]} at version {const} in {path.name}")
        return 0
    note = (a.bump or a.same or "").strip()
    if len(note) < MIN_NOTE:
        raise SystemExit(f"say what changed (>= {MIN_NOTE} characters); the sentence is the record")
    if a.same and pin.get("digest") == digest:
        raise SystemExit("--same refused: the engine files have not changed since the last judgement")
    if a.same:
        _refuse_same_on_output(a.engine)
    golden = _golden(a.engine) if a.bump else None
    if golden is not None:
        # The digest is checked in the lock environment (CI's lockfile-install job); one recorded anywhere else would be red there.
        from src.analytics.golden_output import environment_differences

        rec_env = ((json.loads(_digests_path().read_text(encoding="utf-8")) if _digests_path().exists() else {}).get(a.engine) or {}).get("environment")
        diffs = environment_differences(rec_env or {}, golden["environment"]) if rec_env else []
        if diffs:
            raise SystemExit(
                f"--bump refused: this environment differs from the one the output digest is recorded in ({', '.join(diffs)}); "
                "run it in a venv installed from requirements.lock (pip install --require-hashes -r requirements.lock; "
                "pip install -e . --no-deps)"
            )
    version = int(pin.get("version", 0)) + (1 if a.bump else 0)
    if a.bump:
        _set_version(a.engine, version)
    pin.update({"version": version, "digest": digest})
    pin.setdefault("log", []).append(
        {"version": version, "digest": digest, "kind": "bump" if a.bump else "same", "note": note}
    )
    pin_path.write_text(json.dumps(pin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'bumped to' if a.bump else 'kept'} {ENGINES[a.engine][1]} {version}; digest {digest[:12]}")
    if golden is not None:
        _record_output(a.engine, version, golden)
        print(f"re-recorded the {a.engine} output digest {golden['output_digest'][:12]} at version {version} "
              f"under this environment: {json.dumps(golden['environment'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
