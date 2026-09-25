"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

Q1001 + Q1002 (ruled 2026-09-15) — the enumeration guard, beside
``test_network_consent.py`` and in the same family.

That file's ratchets answer "which MODULES can reach the network". This one
answers the other half, "which HOSTS can they reach", and pins three artifacts
against each other so none can drift:

  1. the tree itself — every host literal under ``src/``, ``configs/`` and
     ``scripts/``, plus the scheme-less ``domain:`` fields a URL grep cannot see;
  2. ``docs/SECURITY.md`` §"the full set of endpoints the app can reach";
  3. ``src/static/net-hosts.js`` — the table the consent popup's hover reads.

Q1001 asks for (1) ⊆ (2); Q1002's hover needs (3); and Q1001's "adds it there and
to the consent popup's hover in the same diff" is (2) == (3). A PR that adds a
host has to touch both, or one of these reddens by name.

WHY A `domain:` SWEEP AND NOT ONLY A URL SWEEP. ``configs/markets_sources.yml``
carries 112 sources as bare ``domain:`` values with no ``rss_url`` at all, and
``src/ingest/crawl.py:149`` reaches every one of them at ``https://<domain>``.
A guard that greps only for ``https://`` literals sees NONE of them — measured:
the URL sweep finds 4,816 hosts in ``configs/sources.yml`` and the two sweeps
together find 8,107. A host that is never written down as a URL is still a host.

WHY EXEMPTIONS ARE PER FILE AS WELL AS PER HOST. A catalogue of ~90 government
home pages that exists to be DISPLAYED (``configs/world_events.yml``,
``src/stats/agencies.py``) cannot be listed one host at a time in a security
document without burying the endpoints that matter. Those get one exemption
each, with a written reason AND a structural check: the module that reads the
file must not be a socket importer, which is asserted against
``test_network_consent.py``'s own allowlist rather than re-derived here. A
file-level exemption whose reader could open a socket is the hazard, and that
is the half a reason-string alone would not catch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.js_source_helper import array_literal

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "docs" / "SECURITY.md"
_TABLE = _ROOT / "src" / "static" / "net-hosts.js"
_LOCALES = _ROOT / "src" / "static" / "locales"

#: The section's first and last lines. Scoped deliberately: SECURITY.md also
#: carries a 2026-06 audit report that names hosts in prose, and a needle found
#: anywhere in the file would let the audit's text satisfy a guard about the
#: enumeration -- the recorded "assert the produced value, not the symbol" trap
#: one artifact over.
_SECTION_HEAD = "- **Every other outbound call is consented"
_SECTION_TAIL = "\n## Data at rest & airplane mode"

_URL_HOST = re.compile(r"https?://([A-Za-z0-9._{}%$()*-]+)")
#: ``domain: example.org`` in a YAML catalogue -- the scheme-less half.
_YAML_DOMAIN = re.compile(
    r"^\s*-?\s*domain:\s*[\"']?([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})", re.M
)
#: What may be called a host at all. One dot minimum and an alphabetic final
#: label, which is what drops the regex's own debris (``bihar``, ``x``,
#: ``src{sid``, a bare ``(``) without a hand-written skip list. HONEST LIMIT:
#: it also drops a single-label host; ``localhost`` is the only one this tree
#: has, and it is exempted by name below. The final-label alternation carries
#: ``xn--`` because ``configs/sources.yml`` really does hold a punycode IDN
#: (``xn--80aaafcmcb6evaidf6r.xn--p1ai``), whose TLD ends in a DIGIT -- a plain
#: ``[A-Za-z]{2,}$`` silently dropped one real host, and the count guard below is
#: what said so.
_HOST_SHAPE = re.compile(
    r"^(?:\*\.)?[A-Za-z0-9][A-Za-z0-9.*_-]*\.(?:xn--[A-Za-z0-9-]+|[A-Za-z]{2,})$"
)

_EXTENSIONS = {".py", ".js", ".html", ".css", ".json", ".yml", ".yaml", ".sh",
               ".ps1", ".cmd", ".cfg", ".toml"}
#: Third-party bytes we vendored. Their own licence banners are not our endpoints.
_SKIP_PREFIXES = ("scripts/vendor/", "src/static/guis/vendor/", "src/static/fonts/")

# --------------------------------------------------------------------------- #
# Exemptions. Each states WHY, because the next reader's only defence against a
# silently-added one is that adding it requires writing a sentence they can
# disagree with (the _ALLOWED_SOCKET_IMPORTERS shape, deliberately copied).
# --------------------------------------------------------------------------- #
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

#: RFC 2606 / RFC 6761 reserved names. These cannot resolve on the public
#: internet by standard, so a literal using one is a fixture by construction --
#: an exemption that is a property of the NAME, not of anyone's judgement.
_RESERVED_SUFFIXES = (".example", ".invalid", ".test", ".local", ".localhost")
_RESERVED_EXACT = {"example.com", "example.org", "example.net"}

_NOT_AN_ENDPOINT: dict[str, str] = {
    "www.gnu.org":
        "the GPL-3.0 licence URL in this project's own file header, ~36 files. "
        "Written into source, never dereferenced",
    "creativecommons.org":
        "the canonical CC BY-SA 4.0 deed URL, written INSIDE the attribution line an "
        "export, a bulletin and an evidence ZIP carry when Wikipedia text rides them "
        "(Q1008 = a). Exactly the www.gnu.org shape one entry above: a licence URL "
        "reproduced as part of a licence statement, so that a reader who opens the "
        "folder years later can look the terms up. src/backup/attribution.py imports "
        "nothing that can open a socket and dereferences nothing",
    "www.etalab.gouv.fr":
        "the canonical Licence Ouverte 2.0 URL in src/law/model.py's LICENCES registry "
        "(Q927 = a records a licence per document and shows it in the reader). The same "
        "shape as creativecommons.org above, with ONE difference worth stating plainly: "
        "this one is RENDERED AS A LINK, so a reader can click it. That click is the "
        "reader's browser, through invariant #7's confirm popup, which names the host "
        "and asks first -- src/law/model.py imports nothing that can open a socket and "
        "dereferences nothing itself, and the reader page fetches no licence URL",
    "github.com":
        "this repository's own URL: the contact field of the bot User-Agent, the "
        "docs base URL, and citation strings. The UA value is SENT as a header; the "
        "URL in it is never fetched",
    "astral.sh":
        "named by a docstring explaining what the vLLM installer deliberately does "
        "NOT do (`curl https://astral.sh/uv/install.sh | sh`); uv comes from PyPI",
    "wiki.openstreetmap.org":
        "a comment in osmpbf.js citing the PBF binary-format specification the "
        "parser implements. A comment, in a file that fetches nothing",
    "www.python.org":
        "printed by install.ps1 in a remediation message telling the operator where "
        "to download Python by hand. The script itself never fetches it",
    "git-scm.com":
        "same shape: an install.ps1 remediation message pointing at the Git download "
        "page for a human, never fetched by the script",
    "www.apple.com":
        "the DOCTYPE public identifier of the macOS LaunchAgent plist install.sh "
        "writes. macOS does not dereference it; no HTTP request exists here",
    "www.nuget.org":
        "the human-readable package page recorded beside api.nuget.org in the "
        "artifact registry. The fetch (install.ps1) uses the api. host, which the "
        "enumeration names",
    "duckduckgo.com":
        "the redirector host DuckDuckGo wraps results in. src/services/duckduckgo.py "
        "unwraps the target from the query string LOCALLY and refuses the redirector "
        "itself, so it is never fetched -- named under the SECURITY.md table",
    "probe.invalid":
        "a reserved-TLD literal in the OpenTimestamps module's own self-check",
    "exchange.example":
        "an input placeholder in index.html (RFC 2606 reserved)",
}

_DISPLAY_ONLY_FILES: dict[str, str] = {
    "configs/world_events.yml":
        "~92 official_url values for recurring world events. Reader "
        "src/events/catalog.py has no fetch code at all: the URL is handed to the UI "
        "as a click-through citation and nothing dereferences it",
    "configs/world_timeline.yml":
        "Wikipedia citation links for the bundled historical anchors. Reader "
        "src/timemap/anchors.py passes `url` through as metadata; no fetch",
    "configs/external_artifacts.yml":
        "the external-artifact registry: `upstream` provenance fields recording "
        "where each BUNDLED artifact came from. GET /api/diagnostics/freshness is "
        "network-free by contract; the upstream check is a CI-only script",
    "configs/climate_events.yml":
        "a methodology citation for the NOAA CPC ONI table. src/stats/oni.py is a "
        "pure parser that imports no socket library; the download is an operator step",
    "configs/catalog_query.yml":
        "a comment pointing a maintainer at wikidata.org while editing the QIDs. "
        "src/catalog/build.py reads the file and performs no fetch",
    "configs/legal.yml":
        "a user_agent contact URL and the GPL header. Nothing in src/ loads this "
        "file at all -- grep finds one comment reference and no read call",
    "configs/market_rules.example.yml":
        "a .example TEMPLATE using RFC 2606 .test domains; no code loads this name",
    "configs/email_sources.yaml.example":
        "a .example TEMPLATE; grep finds no reader for email_sources.yaml either",
    "configs/settings.yaml":
        "the bot User-Agent's contact URL, the GPL header, and cors_origins -- which "
        "is an INBOUND allow-list of who may call this app, not an outbound target",
    "src/stats/agencies.py":
        "the curated directory of ~30 statistical agencies. Its own docstring: the "
        "home URLs are 'metadata, not fetched here'; src/stats/ingest.py reduces each "
        "to a registrable domain LOCALLY. The module imports no socket library",
    "src/ingest/non_article.py":
        "the non-article classifier's own recall self-check: a fixture table of real "
        "URLs the classifier must catch. Strings compared against, never fetched",
    "src/api/wiki.py":
        "an example URL in the comment above the paste-a-Wikipedia-URL parser "
        "(`de.wikipedia.org/wiki/...`), documenting what the regex accepts",
    "src/geo/ip_geo.py":
        "the CC BY 4.0 attribution DB-IP requires for the BUNDLED country table",
    "src/api/link_analysis.py":
        "the GraphML XML namespace URI. A namespace is an identifier, never fetched",
    "src/catalog/publicsuffix.py":
        "where the BUNDLED public-suffix list came from, recorded in a comment "
        "together with the sha256 of the bytes actually in the repo",
    "src/testing/corpus_gen.py":
        "synthetic corpus generation for tests: template fragments, no real host",
    "src/testing/collect_soak.py":
        "the soak harness's synthetic sources, on RFC 2606 reserved names",
    "src/static/world_outline.json":
        "a `source` provenance string on a BUNDLED geojson. Grep confirms no JS in "
        "src/static ever reads that key",
    "src/static/osmpbf.js":
        "a format-specification URL in the module's header comment",
    "src/static/app-map.js":
        "the DB-IP attribution anchor the CC BY 4.0 licence requires on the map",
    "src/static/app-settings.js":
        "click-through anchors to the Ollama and Hugging Face model pages. The "
        "operator clicks them; the app never fetches them (and invariant #7's "
        "confirm popup stands between the click and the browser)",
    "src/static/app-ai-tools.js":
        "the 'Install Ollama' click-through anchor, same shape as app-settings.js",
    "src/static/index.html":
        "input `placeholder` examples (a feed URL, a CSV URL, a Wikipedia URL). A "
        "placeholder is never loaded; it is the shape of what the operator types",
    "src/static/locales/en.json":
        "the translation key for that Wikipedia placeholder. A locale string is "
        "display text by construction",
    "src/llm/ollama.py":
        "loopback-only by construction: it talks to a localhost daemon. The literals "
        "are the ollama.com library page the model catalogue is re-verified against "
        "each cycle (a comment) and a huggingface.co path in a docstring; the AI lane "
        "is enumerated, and a model pull is a loopback POST the daemon acts on",
    "src/llm/installer.py":
        "ollama.com download-page URLs handed to the UI as a manual-install link, "
        "and the same page named in a refusal message. api.github.com IS fetched "
        "here and IS enumerated",
    "src/llm/vllm_lifecycle.py":
        "a port probe against the CONFIGURED vLLM URL, which defaults to 127.0.0.1. "
        "Its literals are docstrings recording what was probed and what was blocked; "
        "pypi.org and huggingface.co, which its subprocesses really fetch, are both "
        "enumerated on the AI lane",
    "src/llm/vllm_client.py":
        "loopback-only by construction (a localhost vLLM server). Its one literal is "
        "a docstring citing the pypi.org JSON endpoint the version floor was read "
        "from; pypi.org is enumerated on the AI lane",
    "src/llm/weights_pin.py":
        "the docstring recording why the weight pins ship blank (the hosts needed to "
        "resolve them answer CONNECT 403 in the build sandbox)",
    "src/wiki/dump_sizes.py":
        "the docstring's re-review instruction, naming dumps.wikimedia.org -- which "
        "the enumeration carries. The module is a table of dated estimates",
    "src/catalog/csv_io.py":
        "an example.com row in the CSV round-trip docstring",
    "src/monitoring/bulletin_language.py":
        "an example.org fixture URL inside a docstring, on an RFC 2606 reserved name",
    "src/utils/url_utils.py":
        "a URL fragment inside a regex/docstring, not a target",
    "src/wiki/corpus.py":
        "the canonical *.wikipedia.org article-URL builder, which the enumeration "
        "carries as the Wikipedia lane",
    "src/analytics/extract.py":
        "a URL-shaped fragment in an extraction pattern",
    "src/services/link_analyzer/extractor.py":
        "a URL-shaped fragment in an extraction pattern",
    "src/events/feeds.py":
        "the robots-dead default hosts, named in the module comment that explains "
        "why they are FILTERED OUT of the loaded directory -- and named under the "
        "SECURITY.md table for the same reason",
    "src/api/main.py":
        "the *.wikipedia.org permalink builder for a tracked revision",
    "src/briefing/producers.py":
        "the *.wikipedia.org diff-link builder for a briefing card",
    "src/briefing/recipes.py":
        "the *.wikipedia.org article-link builder for a briefing card",
    "src/config/settings.py":
        "the default bot User-Agent's contact URL and the loopback bind address",
    "src/legal/consent.py":
        "the docs base URL the first-launch consent screen links to",
    "src/services/duckduckgo.py":
        "the bot User-Agent's contact URL, and the refused-redirector docstring. "
        "html.duckduckgo.com IS fetched here and IS enumerated",
    "src/wiki/client.py":
        "the Wikipedia bot User-Agent's contact URL",
    "src/wiki/ores.py":
        "the ORES bot User-Agent's contact URL. ores.wikimedia.org is enumerated",
    "src/ingest/__init__.py":
        "THE fetch path: its real endpoints are the press class, enumerated as a "
        "class. The literals HERE are the bot User-Agent's contact URL and the "
        "netloc templates the per-host politeness keys are built from",
    "src/custody/timestamp.py":
        "a reserved-TLD literal in its own self-check; the three OpenTimestamps "
        "calendars it really submits to are enumerated on the custody lane",
    "src/hazards/parse.py":
        "the USGS and GDACS feed shapes in the parser's docstring; both hosts are "
        "enumerated on the hazards row",
}

#: Everything under scripts/ is maintainer or CI tooling, never reached by the
#: running app -- scripts/README.md says so and the enumeration's own "Installers,
#: maintainer tooling and CI" paragraph names the hosts. This is one exemption
#: rather than seventy because the PROPERTY is the directory: nothing in src/
#: shells out to any of it.
_TOOLING_PREFIXES = ("scripts/",)
_TOOLING_ROOT_FILES = {"install.sh", "install.ps1", "install-offline.sh", "pyproject.toml"}


# --------------------------------------------------------------------------- #
#  Readers
# --------------------------------------------------------------------------- #
def _section() -> str:
    doc = _DOC.read_text(encoding="utf-8")
    start = doc.find(_SECTION_HEAD)
    assert start != -1, (
        f"the enumeration section is gone from {_DOC.name}: no line starts "
        f"{_SECTION_HEAD!r}. Renaming it is fine; update this guard in the same PR"
    )
    end = doc.find(_SECTION_TAIL, start)
    assert end != -1, "the enumeration section has no following '## ' heading"
    return doc[start:end]


def _code_spans(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", text))


def _declared_hosts() -> set[str]:
    """Every host the enumeration section names, anywhere in it."""
    return {t for t in _code_spans(_section()) if _HOST_SHAPE.match(t)}


def _doc_rows() -> dict[str, dict]:
    """The section's markdown table, as {lane label: {hosts, cells}}.

    Keyed on the BOLD lane name in column 1, which is the same string the table
    in net-hosts.js carries as `label` -- one string, so the two cannot be
    matched by a near-miss.
    """
    rows: dict[str, dict] = {}
    for line in _section().splitlines():
        if not line.startswith("| **"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 5, f"unexpected table row shape ({len(cells)} cells): {line[:80]}"
        label = cells[0].strip("* ")
        rows[label] = {
            "hosts": {t for t in _code_spans(cells[1]) if _HOST_SHAPE.match(t)},
            "cells": cells,
        }
    assert rows, "the enumeration section has no table rows"
    return rows


def _lanes() -> list[dict]:
    js = _TABLE.read_text(encoding="utf-8")
    return json.loads(array_literal(js, "OO_NET_LANES"))


def _config_hosts(*rel_paths: str) -> set[str]:
    """Both halves of a catalogue's reach: its URLs and its scheme-less domains."""
    out: set[str] = set()
    for rel in rel_paths:
        text = (_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        out |= set(_URL_HOST.findall(text)) | set(_YAML_DOMAIN.findall(text))
    return {h for h in out if _HOST_SHAPE.match(h)}


def _tree_hosts() -> dict[str, set[str]]:
    """Every host literal in the tree -> the files that carry it."""
    found: dict[str, set[str]] = {}
    targets: list[Path] = []
    for root in ("src", "configs", "scripts"):
        targets += [p for p in (_ROOT / root).rglob("*")
                    if p.is_file() and p.suffix in _EXTENSIONS]
    targets += [_ROOT / name for name in sorted(_TOOLING_ROOT_FILES)]
    for path in targets:
        if not path.is_file():
            continue
        rel = path.relative_to(_ROOT).as_posix()
        if any(rel.startswith(p) for p in _SKIP_PREFIXES):
            continue
        # The eleven non-English locales are translations of en.json, which IS
        # swept; a separate guard below proves none of them introduces a host of
        # its own, so skipping them here costs nothing and saves 11x the noise.
        if rel.startswith("src/static/locales/") and not rel.endswith("/en.json"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hosts = set(_URL_HOST.findall(text))
        # The scheme-less sweep is for YAML catalogues ONLY. Run over JS it
        # matches an object property -- `domain: g.domain` in oosky.js came back
        # as the host "g.domain" on the first run of this guard.
        if path.suffix in {".yml", ".yaml"}:
            hosts |= set(_YAML_DOMAIN.findall(text))
        for host in hosts:
            found.setdefault(host, set()).add(rel)
    return found


def _normalise(host: str) -> str:
    """A templated host becomes its declared wildcard: ``{code}.wikipedia.org`` ->
    ``*.wikipedia.org``. Exact equality afterwards -- never substring containment,
    which this codebase has now been bitten by three times in three subsystems."""
    return re.sub(r"\{[^{}]*\}", "*", host)


def _is_exempt(host: str, files: set[str]) -> bool:
    if host in _LOOPBACK or host in _RESERVED_EXACT:
        return True
    if host.endswith(_RESERVED_SUFFIXES):
        return True
    if host in _NOT_AN_ENDPOINT:
        return True
    if _normalise(host) == "*":          # the host is entirely a variable
        return True
    # Covered when EVERY file carrying it is display-only or tooling.
    return all(
        f in _DISPLAY_ONLY_FILES
        or f.startswith(_TOOLING_PREFIXES)
        or f in _TOOLING_ROOT_FILES
        for f in files
    )


# --------------------------------------------------------------------------- #
#  The guards
# --------------------------------------------------------------------------- #
def test_every_host_literal_in_the_tree_is_enumerated():
    """Q1001: the security document names every host the tree can reach."""
    declared = _declared_hosts()
    classes: set[str] = set()
    for lane in _lanes():
        if lane.get("hostsFrom"):
            classes |= _config_hosts(*lane["hostsFrom"])

    missing: dict[str, set[str]] = {}
    for host, files in _tree_hosts().items():
        if not _HOST_SHAPE.match(_normalise(host)):
            continue                      # regex debris, not a host (see _HOST_SHAPE)
        norm = _normalise(host)
        if norm in declared or host in declared or host in classes:
            continue
        if _is_exempt(host, files):
            continue
        missing[host] = files

    assert not missing, (
        "host(s) the tree can reach that docs/SECURITY.md does not name:\n"
        + "\n".join(f"  {h}  <- {sorted(f)}" for h, f in sorted(missing.items()))
        + "\n\nAdd each to the enumeration AND to src/static/net-hosts.js in this "
          "same diff (Q1001), or add an exemption stating WHY it is not an endpoint."
    )


def test_the_enumeration_and_the_consent_hover_carry_the_same_hosts():
    """Q1001's same-diff rule, enforced in BOTH directions, per lane.

    Per lane and not merely as one pooled set, because a host moved to the wrong
    lane is exactly the drift that makes a consent hover lie while both lists
    still contain the same names.
    """
    rows = _doc_rows()
    problems: list[str] = []
    for lane in _lanes():
        label = lane["label"]
        if label not in rows:
            problems.append(f"{label!r}: no row with that name in the SECURITY.md table")
            continue
        doc_hosts = rows[label]["hosts"]
        if lane.get("hostsFrom"):
            # A CLASS: the document names examples, not the whole reach. The
            # examples must be real members, and the files + count must match.
            real = _config_hosts(*lane["hostsFrom"])
            stray = doc_hosts - real
            if stray:
                problems.append(f"{label!r}: named as examples but not in the catalogues: {sorted(stray)}")
            for path in lane["hostsFrom"]:
                if path not in _code_spans(rows[label]["cells"][1]):
                    problems.append(f"{label!r}: the row does not name {path}")
            if f"{lane['hostCount']:,}" not in rows[label]["cells"][1]:
                problems.append(
                    f"{label!r}: the row does not state the host count {lane['hostCount']:,}"
                )
        else:
            table_hosts = set(lane["hosts"])
            if doc_hosts != table_hosts:
                problems.append(
                    f"{label!r}: only in SECURITY.md {sorted(doc_hosts - table_hosts)}; "
                    f"only in net-hosts.js {sorted(table_hosts - doc_hosts)}"
                )
    extra = set(rows) - {lane["label"] for lane in _lanes()}
    if extra:
        problems.append(f"SECURITY.md rows with no lane in net-hosts.js: {sorted(extra)}")
    assert not problems, "the enumeration and the consent hover have drifted:\n  " + "\n  ".join(problems)


def test_a_class_lane_states_the_real_host_count():
    """`hostCount` is a measurement of the catalogues, so it is measured here.

    A number typed into a table is a claim, and a claim nobody re-checks outlives
    its fact -- this is what stops the hover telling an operator "9,033 hosts"
    after someone adds a thousand sources.
    """
    for lane in _lanes():
        if not lane.get("hostsFrom"):
            continue
        real = len(_config_hosts(*lane["hostsFrom"]))
        assert lane["hostCount"] == real, (
            f"lane {lane['id']!r}: hostCount is {lane['hostCount']} but the "
            f"catalogues carry {real} distinct hosts. Update net-hosts.js AND the "
            f"SECURITY.md row in the same diff."
        )


def test_every_url_bearing_config_is_named_in_the_enumeration():
    """A whole catalogue nobody mentions is the shape of a forgotten lane."""
    unnamed = []
    section = _section()
    for path in sorted((_ROOT / "configs").rglob("*")):
        if not path.is_file() or path.suffix not in {".yml", ".yaml", ".json"}:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not (_URL_HOST.search(text) or _YAML_DOMAIN.search(text)):
            continue
        if rel in _DISPLAY_ONLY_FILES:
            continue
        if rel not in section:
            unnamed.append(rel)
    assert not unnamed, (
        "config file(s) carrying hosts that the enumeration never names: "
        f"{unnamed}\nName the file on the lane it feeds, or exempt it in "
        "_DISPLAY_ONLY_FILES with the reason its URLs are never fetched."
    )


def test_no_display_only_exemption_hides_a_module_that_can_open_a_socket():
    """The structural half of a file-level exemption.

    "This file's URLs are only displayed" is a claim about the file. It is worth
    nothing if the same file can also reach the network, so the claim is checked
    against test_network_consent.py's own allowlist of socket-capable modules --
    read from there rather than restated, so the two cannot disagree.
    """
    from tests.test_network_consent import _ALLOWED_SOCKET_IMPORTERS

    # Modules that ARE socket-capable and are exempted here anyway must say so in
    # their reason: each one's real endpoints are enumerated, and the literals the
    # exemption covers are prose. Anything else is a hole.
    socket_capable = set(_ALLOWED_SOCKET_IMPORTERS)
    overlap = {f for f in _DISPLAY_ONLY_FILES if f in socket_capable}
    for path in sorted(overlap):
        reason = _DISPLAY_ONLY_FILES[path]
        # A word-stem needle, deliberately: it fails CLOSED (a reason that omits
        # it reddens), which is the safe direction -- unlike the recorded traps
        # where a needle the artifact also NAMES let a guard pass on its own prose.
        assert "enumerat" in reason, (
            f"{path} can open a socket (it is in _ALLOWED_SOCKET_IMPORTERS) and is "
            f"exempted here without saying which of its hosts ARE enumerated: {reason!r}"
        )


def test_every_exemption_states_a_reason():
    """A bare entry is a rubber stamp -- the standing rule in this test family."""
    for table, name in ((_NOT_AN_ENDPOINT, "_NOT_AN_ENDPOINT"),
                        (_DISPLAY_ONLY_FILES, "_DISPLAY_ONLY_FILES")):
        for key, reason in table.items():
            assert len(reason.strip()) > 40, f"{name}[{key!r}]: justification too thin: {reason!r}"


def test_no_exemption_is_stale():
    """An exemption for something that is gone is an exemption nobody re-reads."""
    tree = _tree_hosts()
    gone_hosts = sorted(h for h in _NOT_AN_ENDPOINT if h not in tree)
    assert not gone_hosts, f"_NOT_AN_ENDPOINT names hosts no longer in the tree: {gone_hosts}"
    gone_files = sorted(f for f in _DISPLAY_ONLY_FILES if not (_ROOT / f).is_file())
    assert not gone_files, f"_DISPLAY_ONLY_FILES names files that no longer exist: {gone_files}"


def test_the_translated_locales_introduce_no_host_of_their_own():
    """Closes the one hole the locale skip in _tree_hosts would otherwise open."""
    en = set(_URL_HOST.findall((_LOCALES / "en.json").read_text(encoding="utf-8")))
    for path in sorted(_LOCALES.glob("*.json")):
        if path.name == "en.json":
            continue
        theirs = set(_URL_HOST.findall(path.read_text(encoding="utf-8")))
        extra = {h for h in theirs - en if _HOST_SHAPE.match(h)}
        # A localised example (de.wikipedia.org for the German UI) is the same
        # host family en.json carries; anything outside it is a new host.
        extra = {h for h in extra if not h.endswith(".wikipedia.org")}
        assert not extra, f"{path.name} introduces host(s) en.json does not carry: {sorted(extra)}"


@pytest.mark.parametrize("locale", sorted(p.name for p in _LOCALES.glob("*.json")))
def test_every_lane_label_is_translated(locale):
    """The x12 guard for a hover the ratchets cannot see.

    `t(lane.label)` is a VARIABLE call site, so --max-unkeyed-t-calls -- which
    only matches `t("literal")` -- is structurally blind to it. Rather than leave
    the lane names as the one hover surface that could ship English to eleven
    locales, the keys are asserted directly, here, per locale.
    """
    keys = json.loads((_LOCALES / locale).read_text(encoding="utf-8"))
    missing = [lane["label"] for lane in _lanes() if lane["label"] not in keys]
    assert not missing, f"{locale} has no key for lane label(s): {missing}"


def test_the_table_is_pure_data():
    """net-hosts.js must stay a data module: no fetch, no DOM, no prose.

    The value of "one source of truth" is that both readers see the same bytes.
    A table that grew logic would start answering differently in the browser than
    in this guard, and the drift would be invisible to both.
    """
    js = _TABLE.read_text(encoding="utf-8")
    body = array_literal(js, "OO_NET_LANES")
    for banned in ("fetch(", "XMLHttpRequest", "document.", "window.", "eval(", "=>"):
        assert banned not in body, f"net-hosts.js's table contains {banned!r} -- it must stay data"
    assert "fetch(" not in js and "XMLHttpRequest" not in js, "net-hosts.js must make no request"


# --------------------------------------------------------------------------- #
#  The hover itself (Q1002). Source-level wiring guards; the BEHAVIOUR is driven
#  in Chromium, because a DOM-level test verifies what you built and only a
#  rendered page verifies what is legible.
# --------------------------------------------------------------------------- #
def test_the_consent_dialog_carries_the_lane_list():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('<dialog id="net-consent"')
    dialog = html[start:html.index("</dialog>", start)]
    assert 'id="net-consent-lanes"' in dialog, (
        "the per-lane host disclosure is gone from #net-consent (Q1002)"
    )
    # Invariant #14's own content must still be there, and VISIBLE -- the hover is
    # a layer over the hosts, never a place the two standing caveats moved into.
    assert "net-consent-ifaces" in dialog
    assert "this app does not check it" in dialog, "the public-address caveat left the dialog"
    assert "never equal a hardware switch" in dialog, "the hardware-switch caveat left the dialog"
    assert "hidden" not in dialog.split('id="net-consent-lanes"')[1].split(">")[0], (
        "the lane list must not ship hidden"
    )


def test_the_table_loads_before_the_code_that_reads_it():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/static/net-hosts.js"') < html.index('src="/static/app-core.js"'), (
        "net-hosts.js must load before app-core.js, which reads window.OO_NET_LANES"
    )


#: The functions that make up the disclosure, by name. Sliced through
#: ``js_source_helper`` rather than by hand between two literal anchors: an
#: index-to-index slice is the shape ``test_source_slicing_discipline`` budgets
#: with zero slack, and it silently truncates the day a brace lands inside a
#: string. Naming the functions is also the better guard -- each assertion below
#: then lands on the function that owns the property, not on a region.
_HOVER_FUNCS = ("_laneState", "_laneHostTitle", "_laneLine", "_renderNetLanes",
                "_netConsentConfig", "_transportKind", "_laneTransport", "_transportHint")


def _hover_source() -> str:
    """The disclosure block: its functions' own sources, brace-matched."""
    from tests.js_source_helper import function_source

    js = (_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    out = [function_source(js, name) for name in _HOVER_FUNCS]
    # The state constants live above the functions and are asserted on too; take
    # that one declaration by its own statement, not by a region slice.
    line = next(x for x in js.splitlines() if x.strip().startswith("const _NET_STATE_ON"))
    return line + "\n" + "\n".join(out)


def test_the_dialog_renders_the_lanes_when_it_opens():
    js = (_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    from tests.js_source_helper import function_body

    body = function_body(js, "ensureOnline")
    assert "_renderNetLanes" in body, "ensureOnline no longer renders the lane list"
    assert "_netConsentConfig" in body, "ensureOnline no longer reads the lane states"


def test_an_unreadable_setting_renders_as_unknown_not_as_off():
    """The honesty rule this surface exists to keep.

    "we could not check" and "it is off" are opposite answers for someone deciding
    whether to go online, and a `.get(key, false)` would quietly turn the first
    into the second.

    TWO branches produce that state and they fail for different reasons: the whole
    settings payload was unreadable, or the payload arrived without this lane's
    key. The first cut of this guard used ONE needle, `"=== null) return
    _NET_STATE_UNKNOWN"`, which BOTH lines satisfy -- so the mutation that turned
    the payload-unreadable branch into `_NET_STATE_OFF` survived, passing on the
    other line. That is the recorded "a guard over a function containing two
    similar statements is satisfied by the wrong one" trap, and only the mutation
    said so. Each branch is now pinned by its own exact statement.
    """
    from tests.js_source_helper import strip_comments

    src = strip_comments(_hover_source())
    assert "if (src === null) return _NET_STATE_UNKNOWN;" in src, (
        "an unreadable settings payload no longer renders as unknown"
    )
    assert "if (v === undefined || v === null) return _NET_STATE_UNKNOWN;" in src, (
        "a missing settings key no longer renders as unknown"
    )
    assert "|| false" not in src and "? true : false" not in src, (
        "a falsy default would turn 'could not read' into 'off'"
    )
    # ...and the renderer must actually DRAW each bucket. `"by.unknown" in src`
    # was the first version of this line and it survived disabling the section,
    # because the draw call lives INSIDE the `if` whose condition was mutated --
    # a guard that proves the payload exists rather than that anyone renders it.
    for bucket in ("on", "ask", "off", "unknown"):
        assert f"if (by.{bucket}.length) {{" in src, (
            f"the {bucket!r} lanes are computed and never drawn"
        )


def test_the_hover_translates_its_prose_and_keeps_host_names_verbatim():
    """A hover is a caveat surface, so its prose ships x12.

    Host names are literal tokens and must NOT be routed through t() -- that would
    put 300 host names into every locale file. The check is therefore that every
    sentence AROUND them is translated and that the host join is not.
    """
    from tests.js_source_helper import strip_comments

    src = strip_comments(_hover_source())
    assert 'lane.hosts.join(" · ")' in src, "the host list must be joined verbatim"
    assert 't(lane.label)' in src, "the lane name must be translated"
    for prose in ('t("hosts")', 't("Runs on every collection pass:")',
                  't("Only when you ask for it:")', 't("Switched off right now:")',
                  't("Could not read whether these are on:")'):
        assert prose in src, f"untranslated hover prose: {prose}"


def test_the_hover_reads_only_loopback_endpoints():
    """This slice adds NO egress. Every path the dialog reads is the local API."""
    from tests.js_source_helper import strip_comments

    src = strip_comments(_hover_source())
    # Every path-shaped literal in the block, however it reaches api() -- the
    # reads go through a `one(path)` helper, so a needle anchored on `api("` finds
    # nothing and passes vacuously. That is what the first run of this guard did.
    paths = re.findall(r'"(/[A-Za-z0-9/_.-]+)"', src)
    assert paths, "the lane states are no longer read from anywhere"
    for path in paths:
        assert path.startswith("/api/"), f"the consent dialog reads a non-local path: {path}"
    assert len(paths) == 3, f"expected the three loopback settings reads, found {paths}"
    assert "http://" not in src and "https://" not in src, (
        "the disclosure block must contain no absolute URL"
    )


def test_a_no_opt_out_lane_says_so_in_the_hover():
    """The finding this slice recorded, kept visible.

    auto_import_calendars and auto_track_law are read through getattr(..., True)
    against a SchedulerSettings that defines neither, so those lanes cannot be
    switched off. The hover says that in words rather than showing them as
    ordinary opt-outs; this pins the sentence to the flag that produces it.
    """
    from tests.js_source_helper import strip_comments

    src = strip_comments(_hover_source())
    assert "lane.noOptOut" in src, "the no-opt-out lanes no longer disclose themselves"
    lanes = {lane["id"]: lane for lane in _lanes()}
    for lane_id in ("law", "calendar"):
        assert lanes[lane_id].get("noOptOut") is True, (
            f"lane {lane_id!r} lost its noOptOut flag. If SchedulerSettings gained the "
            f"field, drop the flag and the SECURITY.md sentence in the same diff"
        )
    settings = (_ROOT / "src" / "scheduler" / "settings.py").read_text(encoding="utf-8")
    for key in ("auto_import_calendars", "auto_track_law"):
        assert f"{key}: bool" not in settings, (
            f"{key} is now a real SchedulerSettings field -- the lane CAN be switched "
            f"off, so drop its noOptOut flag and correct docs/SECURITY.md"
        )


def test_an_unreachable_opt_out_says_so_until_the_api_can_reach_it():
    """The second, worse shape of the same finding, live-reproduced 2026-09-16.

    `auto_track_signals` IS a SchedulerSettings field and save_settings honours it.
    `SchedulerConfigUpdate` -- the model PUT /api/scheduler/config validates against
    -- does not declare it, so `model_dump(exclude_unset=True)` returns `{}` and the
    endpoint answers **200 having changed nothing**. An operator who opts out is told
    it worked. This pins the disclosure to the cause, so the day someone adds the
    field the sentence has to come down with it.
    """
    from src.api.scheduler import SchedulerConfigUpdate

    declared = set(SchedulerConfigUpdate.model_fields)
    unreachable = {lane["setting"] for lane in _lanes()
                   if lane.get("settingUnreachable") and lane.get("settingFrom") == "scheduler"}
    assert unreachable, "no lane declares an unreachable opt-out -- was the flag dropped?"
    for key in sorted(unreachable):
        assert key not in declared, (
            f"{key} is now a SchedulerConfigUpdate field, so PUT /api/scheduler/config "
            f"CAN set it. Drop the lane's settingUnreachable flag, remove the sentence "
            f"from docs/SECURITY.md's row, and close the OPEN_QUEUE entry -- in this "
            f"same diff, so the document never over-states a defect either"
        )
    # ...and the hover must actually carry the disclosure, not merely the flag.
    from tests.js_source_helper import strip_comments

    src = strip_comments(_hover_source())
    assert "lane.settingUnreachable" in src, (
        "the unreachable-opt-out lanes no longer disclose themselves in the hover"
    )


def test_the_prose_count_of_non_fetcher_rows_matches_the_table():
    """A number in prose is a claim, and this one was wrong when it was written.

    The section says in two places how many lanes do NOT go through the ethical
    fetcher. The first draft said "four"; the table has three. Nobody re-reads a
    small number, so it is measured here against the table instead — from the
    document's own rows AND from net-hosts.js's `fetcher: false`, which must agree.
    """
    rows = _doc_rows()
    # The Transport cell is column 4. A row that is not purely the ethical fetcher
    # either says so outright or says "Mixed" and then says what each part uses.
    doc_non_fetcher = {
        label for label, row in rows.items()
        if "Not the ethical fetcher" in row["cells"][3] or "**Mixed.**" in row["cells"][3]
    }
    table_non_fetcher = {lane["label"] for lane in _lanes() if lane.get("fetcher") is False}
    assert doc_non_fetcher == table_non_fetcher, (
        f"the document and net-hosts.js disagree about which lanes bypass the ethical "
        f"fetcher: only in the document {sorted(doc_non_fetcher - table_non_fetcher)}; "
        f"only in the table {sorted(table_non_fetcher - doc_non_fetcher)}"
    )
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    n = words[len(doc_non_fetcher)]
    # BOTH claims, and they are not both inside the table's own section: the lead-in
    # one sits in the "Model" bullet list ABOVE it, and it wraps across a line. The
    # first cut of this guard searched _section() on raw text and found exactly one
    # of the two -- so the mutation that staled the other survived. Search the whole
    # Model section, whitespace-normalised.
    doc = _DOC.read_text(encoding="utf-8")
    model = " ".join(doc[doc.index("## Model"):doc.index(_SECTION_TAIL)].split())
    claims = re.findall(
        r"(\w+) (?:of them do not use|rows that do \*not\* use) the ethical fetcher", model)
    assert len(claims) == 2, (
        f"expected both statements of how many lanes bypass the ethical fetcher "
        f"(the Model lead-in and the Transport paragraph); found {claims}"
    )
    wrong = [c for c in claims if c != n]
    assert not wrong, (
        f"the section says {wrong} where the table has {len(doc_non_fetcher)} ({n!r})"
    )


def test_the_lane_state_node_suite():
    """``_laneState`` run as REAL code against the REAL table (R31, 2026-09-25).

    A lane's ``setting`` may name several switches; the lane is ON while ANY is on and
    OFF only when every one is. Which of "any", "all" or "the first" the code implements
    is invisible to a source needle -- all three mention every key -- so the node suite
    drives the extracted function. The three wrong readings were each applied as a
    mutation and each failed it.
    """
    import subprocess

    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "net_lane_state_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_scheduler_switch_a_lane_names_is_a_real_reachable_field():
    """A key the popup reads and the settings never carry renders its lane as "could not
    read" forever, and a key the API cannot write is an opt-out the operator is told
    worked (the settingUnreachable finding). So each key a scheduler lane names must be a
    SchedulerSettings field AND a SchedulerConfigUpdate field -- except where the table
    already DISCLOSES the gap (``noOptOut``: no field; ``settingUnreachable``: no
    declaration), which the two guards above pin to their causes.

    Written for R31, whose statistics row gained a second key: a typo in it would still
    show the row as on (the other key is on by default), so nothing else would notice.
    """
    import dataclasses

    from src.api.scheduler import SchedulerConfigUpdate
    from src.scheduler.settings import SchedulerSettings

    fields = {f.name for f in dataclasses.fields(SchedulerSettings)}
    declared = set(SchedulerConfigUpdate.model_fields)
    checked = []
    for lane in _lanes():
        if lane.get("settingFrom") != "scheduler" or not lane.get("setting"):
            continue
        if lane.get("noOptOut"):
            continue
        keys = lane["setting"] if isinstance(lane["setting"], list) else [lane["setting"]]
        for key in keys:
            assert key in fields, f"lane {lane['id']!r} reads {key!r}, not a SchedulerSettings field"
            if not lane.get("settingUnreachable"):
                assert key in declared, (
                    f"lane {lane['id']!r} reads {key!r}, which PUT /api/scheduler/config "
                    f"cannot write -- declare it, or disclose it with settingUnreachable"
                )
            checked.append(key)
    assert "auto_refresh_stat_subscriptions" in checked, (
        "the statistics row no longer names the refresh switch R31 made default-on"
    )
