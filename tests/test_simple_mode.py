"""
Simple mode (CLAUDE.md invariant #34, ruling R682).

A second, task-first interface over the same page: one switch in the top bar, a flag read before
first paint, Preact + hooks + htm vendored under ``src/static/simple/vendor``. These tests pin the
parts R682 made conditions of the ruling:

* the vendored files are the pinned upstream bytes, with their licence texts shipped;
* nothing simple mode loads can reach outside the app's own origin (CI has no browser, so this is
  proved from the sources: every request simple mode makes is a same-origin path, and the vendored
  code holds no request API at all; the live measurement is in the PR);
* the surfaces that are never hidden in either mode are not hidden by its stylesheet;
* going online uses the full app's one consent path;
* every string ships in all 12 languages, placeholders intact;
* the ⓘ disclosure is a real button with aria-expanded/aria-controls, and the marks carry text.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_SIMPLE = _STATIC / "simple"
_VENDOR = _SIMPLE / "vendor"

#: The upstream bytes (npm tarballs preact@10.29.8, htm@3.1.1). A change here is an upgrade: follow
#: simple/vendor/README.md and configs/external_artifacts.yml in the same commit.
_PINS = {
    "preact.min.umd.js": "aa558e32247d4ccea18c5addbb0311bc1771bf39734185be01dc0c3c4cf3fd6d",
    "hooks.umd.js": "5c29238e5dc99df306d7f7fff038591a397cfcfabb59f81fbdef43d670aa0566",
    "htm.umd.js": "7a31776e04bd4afde0d4308177d26f377716fcf7e4bd70be590746d6aa594f08",
}
_LANGS = ("en", "fr", "de", "es", "pt", "ru", "zh", "ja", "ar", "hi", "bn", "id")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


def test_vendored_files_match_their_pins_and_ship_licences():
    sums = {}
    for line in _read(_VENDOR / "SHA256SUMS").splitlines():
        digest, name = line.split()
        sums[name] = digest
    assert sums == _PINS, "SHA256SUMS and this test's pins must name the same files and digests"
    for name, digest in _PINS.items():
        assert hashlib.sha256((_VENDOR / name).read_bytes()).hexdigest() == digest, f"{name} is not the pinned upstream file"
    assert "MIT License" in _read(_VENDOR / "preact.LICENSE.txt")
    assert "Apache License" in _read(_VENDOR / "htm.LICENSE.txt")
    registry = _read(_ROOT / "configs" / "external_artifacts.yml")
    for name, digest in _PINS.items():
        assert digest in registry, f"{name} must have a pinned entry in configs/external_artifacts.yml"


def test_page_loads_simple_mode_from_this_origin_only():
    html = _read(_STATIC / "index.html")
    srcs = re.findall(r'<script src="([^"]+)"', html) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    simple = [s for s in srcs if "/simple/" in s]
    assert sorted(simple) == sorted([
        "/static/simple/boot.js", "/static/simple/simple.css", "/static/simple/simple.js",
        "/static/simple/vendor/preact.min.umd.js", "/static/simple/vendor/hooks.umd.js", "/static/simple/vendor/htm.umd.js",
    ]), simple
    # The renderer loads before the mode, and the mode after app-boot.js (it wraps showTab).
    order = [s for s in re.findall(r'<script src="([^"]+)"', html)]
    assert order.index("/static/app-boot.js") < order.index("/static/simple/vendor/preact.min.umd.js")
    assert order.index("/static/simple/vendor/htm.umd.js") < order.index("/static/simple/simple.js")


def test_simple_mode_requests_only_same_origin_paths():
    for name in ("simple.js", "boot.js"):
        code = _strip_js_comments(_read(_SIMPLE / name))
        assert not re.search(r"https?://|wss?://|[\"'`]//[a-z0-9]", code, re.I), f"{name} names an absolute URL"
        assert "XMLHttpRequest" not in code and "WebSocket" not in code and "sendBeacon" not in code and "EventSource" not in code
    code = _strip_js_comments(_read(_SIMPLE / "simple.js"))
    # Every request goes through fetch() or the app's api() helper with a literal same-origin path.
    for m in re.finditer(r"\b(?:fetch|apiCall)\(\s*([^,)]+)", code):
        arg = m.group(1).strip()
        if arg in ("path",):  # apiCall's own definition forwards its argument
            continue
        assert re.match(r"""^["'`]/(static|api)/""", arg), f"a request in simple.js is not a same-origin literal path: {arg}"
    css = _read(_SIMPLE / "simple.css")
    assert "url(" not in css and "@import" not in css, "simple.css loads nothing"


def test_vendored_code_holds_no_request_api():
    for name in _PINS:
        code = _read(_VENDOR / name)
        for api in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts", "eval(", "new Function"):
            assert api not in code, f"{name} contains {api}"
        # The only URLs are XML namespace names, which are identifiers, never fetched.
        urls = set(re.findall(r"https?://[^\"'\s)]+", code))
        assert urls <= {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xhtml", "http://www.w3.org/1998/Math/MathML",
                        "http://www.w3.org/1999/xlink"}, (name, urls)


def _css(name: str) -> str:
    return re.sub(r"/\*.*?\*/", "", _read(_SIMPLE / name), flags=re.S)


def _hidden_selectors(css: str) -> list[str]:
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"display\s*:\s*none", body) or re.search(r"visibility\s*:\s*hidden", body):
            out += [s.strip() for s in sel.split(",")]
    return out


def test_never_hidden_surfaces_stay_visible_in_simple_mode():
    css = _css("simple.css")
    hidden = [s for s in _hidden_selectors(css) if s.startswith("html[data-mode")]
    allowed = {
        'html[data-mode="simple"] #navGroups', 'html[data-mode="simple"] .tab-page',
        'html[data-mode="simple"] .tab-page.active', 'html[data-mode="simple"] #subtab-strip',
        'html[data-mode="simple"] #rate-toggle', 'html[data-mode="simple"] #tm-open', 'html[data-mode="simple"] #llm',
        'html[data-mode="simple"] #health:has(.dot.ok)',
    }
    assert set(hidden) <= allowed, f"simple mode hides something new: {set(hidden) - allowed}"
    # R682: never hidden in either mode.
    never = ("#net-toggle", "#net-consent", "#ai-egress-consent", "#egress-window-bar", "#wiki-toggle", "#activity",
             "#lang-switch", "#app-shutdown", "dialog", "#toast", ".toast", "#net-coach", "#crash")
    for sel in hidden:
        for n in never:
            assert n not in sel, f"{sel} would hide a never-hidden surface ({n})"
    # The health pill hides only while it says healthy.
    assert 'html[data-mode="simple"] #health:has(.dot.ok)' in hidden
    assert 'html[data-mode="simple"] #health {' not in css.replace("  ", " ")


def test_going_online_uses_the_one_consent_path():
    code = _strip_js_comments(_read(_SIMPLE / "simple.js"))
    assert "window.toggleNetwork()" in code
    assert not re.search(r"method\s*:\s*[\"']POST", code), (
        "simple mode never writes the network state itself (#14)"
    )
    # Outbound originals open the local preview first (invariant #6), never the site.
    assert "openLinkPreview" in code
    assert not re.search(r"href=\$\{a\.url\}", code), "an article's original URL is never a bare link"


def test_strings_ship_in_twelve_languages():
    code = _read(_SIMPLE / "simple.js")
    keys = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', code))
    for name, desc in re.findall(r'\["[a-z]+", "([^"]+)", "([^"]+)"\]', code):
        keys |= {name, desc}
    en = json.loads(_read(_SIMPLE / "locales" / "en.json"))["strings"]
    assert keys <= set(en), f"strings missing from en.json: {sorted(keys - set(en))}"
    for lang in _LANGS:
        data = json.loads(_read(_SIMPLE / "locales" / f"{lang}.json"))
        assert data["_meta"]["dir"] == ("rtl" if lang == "ar" else "ltr")
        strings = data["strings"]
        assert set(strings) == set(en), f"{lang}: keys differ from en.json"
        for k, v in strings.items():
            assert v.strip(), f"{lang}: empty translation for {k!r}"
            assert set(re.findall(r"\{\w+\}", k)) == set(re.findall(r"\{\w+\}", v)), f"{lang}: placeholders differ in {k!r}"


def test_details_and_marks_are_accessible():
    code = _read(_SIMPLE / "simple.js")
    details = code.split("function Details(", 1)[1].split("\n  }\n", 1)[0]
    assert 'type="button"' in details and "aria-expanded" in details and "aria-controls" in details
    assert "aria-label" in details and "Escape" in details
    mark = code.split("function Mark(", 1)[1].split("\n  }\n", 1)[0]
    assert 'class="s-sr"' in mark and "title=" in mark, "a mark carries words for screen readers and a hover"
    # The switch is a real switch.
    html = _read(_STATIC / "index.html")
    assert re.search(r'id="ui-simple-toggle" role="switch" aria-checked="false"', html)
    assert "aria-checked" in code


def test_full_mode_is_untouched_when_the_switch_is_off():
    boot = _read(_SIMPLE / "boot.js")
    assert 'localStorage.getItem("oo.ui.simple") === "1"' in boot, "simple mode is opt-in, remembered per device"
    css = _css("simple.css")
    # Every rule that changes the full interface is scoped to a simple-mode attribute or to simple mode's own ids.
    for sel, _body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        for s in sel.split(","):
            s = s.strip()
            if not s or s.startswith(("from", "to")):
                continue
            assert (
                s.startswith(("html[data-mode", "#simple-", "#ui-simple-toggle", "[dir=\"rtl\"] #ui-simple-toggle"))
            ), f"unscoped rule in simple.css: {s}"
