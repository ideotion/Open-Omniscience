"""Row 198: the offline verifiers read a saved bundle as UTF-8, whatever the machine's locale says.

The browser saves an evidence bundle as UTF-8 (a JS string in a Blob), and the custody export is UTF-8 too. Both
verifiers read the file with ``Path.read_text()`` and no encoding, which is the LOCALE's codec: cp1252 on Windows.
Any non-ASCII character in a bundle (an accented article title, a dossier's em dash) then came back as mojibake, and
the verifier reported "signature does not match" on an untouched file -- a false tamper verdict on the very tool the
export dialog sends a third party to.

Reproduced here on any OS by running the scripts under an ASCII locale with UTF-8 mode OFF, which is what makes
``read_text()`` pick a non-UTF-8 codec the way Windows does.
"""

from __future__ import annotations

import ast
import codecs
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.custody.log import CustodyAction, CustodyLog
from src.custody.signing import HybridSigner
from src.reporting.evidence import build_signed_bundle, load_or_create_signing_key

ROOT = Path(__file__).resolve().parents[1]
CASE = "Enquête — Zürich ©"


class _Art:
    def __init__(self, id, content, title):
        self.id = id
        self.url = f"https://e/{id}"
        self.canonical_url = f"https://e/{id}"
        self.source_id = 1
        self.title = title
        self.published_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.hash = f"{id:064d}"
        self.content = content


def _run_non_utf8_locale(script: str, path: Path) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONUTF8", "PYTHONIOENCODING", "LC_ALL", "LANG"}
    }
    env.update(LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0")
    return subprocess.run(
        [sys.executable, "-X", "utf8=0", str(ROOT / "scripts" / script), str(path)],
        capture_output=True,
        env=env,
        cwd=ROOT,
    )


def _evidence(tmp_path: Path) -> dict:
    key = load_or_create_signing_key(tmp_path / "k.pem")
    return build_signed_bundle([_Art(1, "café", "Révolution à Paris — été")], key, case_name=CASE)


def test_a_non_ascii_evidence_bundle_verifies_offline_under_a_non_utf8_locale(tmp_path):
    path = tmp_path / "bundle.json"
    # What the browser writes: JSON.stringify(bundle, null, 2) keeps non-ASCII characters raw, in UTF-8.
    path.write_text(json.dumps(_evidence(tmp_path), ensure_ascii=False, indent=2), encoding="utf-8")
    res = _run_non_utf8_locale("verify_evidence.py", path)
    out = res.stdout.decode("ascii", "replace")
    assert res.returncode == 0, out + res.stderr.decode("ascii", "replace")
    assert "VERIFIED       : True" in out
    # The case name is printed back escaped, never a crash on a console that cannot show it.
    assert "case_name      : Enqu" in out


def test_a_bom_is_tolerated_and_a_tampered_bundle_still_fails(tmp_path):
    bundle = _evidence(tmp_path)
    path = tmp_path / "bundle.json"
    # A re-save in an editor that prepends a BOM changes nothing that is hashed or signed: the BOM is not JSON.
    path.write_bytes(codecs.BOM_UTF8 + json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
    assert _run_non_utf8_locale("verify_evidence.py", path).returncode == 0
    bundle["manifest"]["case_name"] = CASE + " "
    path.write_bytes(codecs.BOM_UTF8 + json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
    res = _run_non_utf8_locale("verify_evidence.py", path)
    assert res.returncode == 1 and b"VERIFIED       : False" in res.stdout


def test_a_non_ascii_custody_bundle_verifies_offline_under_a_non_utf8_locale(tmp_path):
    signer = HybridSigner(
        ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key", use_pqc=False
    )
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=signer, anchoring_mode="local") as log:
        log.record(
            "article:x", "a" * 64, CustodyAction.INGEST, actor="rédaction", metadata={"note": CASE}
        )
        bundle = log.export(item_id="article:x")
    path = tmp_path / "custody.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    res = _run_non_utf8_locale("verify_custody.py", path)
    out = res.stdout.decode("ascii", "replace")
    assert res.returncode == 0 and "VERIFIED       : True" in out, out + res.stderr.decode(
        "ascii", "replace"
    )


def test_every_file_read_in_an_offline_verifier_names_its_encoding():
    """read_text()/open() without an encoding uses the locale's codec, which is how row 198 happened."""
    bare = []
    for script in sorted((ROOT / "scripts").glob("verify_*.py")):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            if name not in {"read_text", "open", "write_text"}:
                continue
            mode = next(
                (
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ),
                "",
            )
            if name == "open" and "b" in mode:
                continue
            if not any(k.arg == "encoding" for k in node.keywords):
                bare.append(f"{script.name}:{node.lineno} {name}()")
    assert not bare, bare
