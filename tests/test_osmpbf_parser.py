"""The in-browser OSM PBF parser (src/static/osmpbf.js) is proven by a Node test
against a hand-encoded fixture (tests/osmpbf_node_test.js): the protobuf
varint/zigzag primitives, the dense-node delta decode to exact WGS84 degrees, the
full .osm.pbf container parse, and the bounded-preview (maxBlocks) behaviour.

The parser is the genuinely VERIFIABLE core of the THEME-2 offline-map render
(maintainer batch-1 answer: in-browser .pbf parser). The fetch + zlib + ooMap
overlay are the browser glaze, flagged browser-unverified. This wrapper runs the
Node test inside CI (skips cleanly where node is absent)."""
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_osmpbf_parser_decodes_a_fixture():
    test_js = _ROOT / "tests" / "osmpbf_node_test.js"
    assert test_js.exists(), "the node test script must exist"
    r = subprocess.run(
        ["node", str(test_js)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_ROOT),
    )
    assert r.returncode == 0, f"osmpbf node test failed:\n{r.stdout}\n{r.stderr}"
    assert "OSMPBF OK" in r.stdout


def test_osmpbf_module_is_self_contained():
    """The parser must be dependency-free + node/browser dual (it attaches to the
    global AND exports for the node test), and must NOT make any network call (it
    reads bytes the caller already has). No fabricated geometry."""
    src = (_ROOT / "src" / "static" / "osmpbf.js").read_text(encoding="utf-8")
    assert "root.OOPBF = API" in src, "must attach to the global as OOPBF"
    assert "module.exports = API" in src, "must export for the node test"
    # bounded preview (never OOM on a multi-hundred-MB region)
    assert "maxBlocks" in src and "truncated" in src, "the parser must be bounded + flag truncation"
    # zero network: no fetch/XHR/import of a remote — it only decodes a given buffer
    for forbidden in ("fetch(", "XMLHttpRequest", "import(", "require('http"):
        assert forbidden not in src, f"the parser must not touch the network ({forbidden})"
