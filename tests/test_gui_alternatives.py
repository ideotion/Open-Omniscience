"""
Alternative-interfaces gallery (Settings -> GUIs) invariants.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gallery (maintainer-ruled 2026-06-17) ships eight opt-in alternative
interfaces as a SANDBOX: each is a shared-core SHELL (its own scoped CSS, plus
thin JS for the two Alpine ones) that reuses the ONE app.js render logic, so the
ethical non-negotiables are preserved BY CONSTRUCTION (same DOM). These checks
turn that promise into guardrails:

  * every registered interface has its assets on disk;
  * NO skin hides a caveat / consent surface (informed consent is non-negotiable);
  * every asset is LOCAL — no CDN, no outbound URL (offline / anonymity intact);
  * Alpine.js is vendored, checksum-pinned, and loaded only from the local path;
  * every skin rule is SCOPED under html[data-ui="<id>"] so it cannot leak into
    the default interface.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GUIS = _ROOT / "src" / "static" / "guis"

EXPECTED_IDS = ["aurora", "atlas", "command", "field", "focus", "terminal", "canvas", "editorial"]
ALPINE_IDS = {"command", "canvas"}

# Caveat / consent surfaces that MUST stay visible (the informed-consent mandate).
_CAVEAT_SELECTORS = ("card-caveat", "tier-caveat", "net-consent", "net-coach")
_HIDE_RE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0\s*[;}!])", re.I)
_URL_RE = re.compile(r"https?://", re.I)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _registry_ids() -> list[str]:
    boot = _read(_GUIS / "boot.js")
    # The registry objects look like: { id: "aurora", name: "Aurora", engine: ... }
    return re.findall(r'id:\s*"([a-z]+)",\s*name:\s*"', boot)


def _strip_comments_css(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_registry_lists_the_eight_interfaces():
    ids = _registry_ids()
    assert ids == EXPECTED_IDS, f"boot.js registry must list the 8 interfaces in order, got {ids}"


def test_every_registered_asset_exists():
    boot = _read(_GUIS / "boot.js")
    # css/js filenames referenced by the registry must exist on disk.
    for fn in re.findall(r'(?:css|js):\s*"([^"]+\.(?:css|js))"', boot):
        assert (_GUIS / fn).is_file(), f"registry references a missing asset: {fn}"
    for fn in ("boot.js", "gallery.js", "gallery.css"):
        assert (_GUIS / fn).is_file(), f"framework asset missing: {fn}"
    for ui in EXPECTED_IDS:
        assert (_GUIS / f"ui-{ui}.css").is_file(), f"missing skin: ui-{ui}.css"
    for ui in ALPINE_IDS:
        assert (_GUIS / f"ui-{ui}.js").is_file(), f"missing Alpine controller: ui-{ui}.js"


def test_no_skin_hides_a_caveat_or_consent_surface():
    """Informed consent is non-negotiable: a skin may restyle a caveat, never
    remove it. Fail if any rule whose selector targets a caveat/consent surface
    also sets display:none / visibility:hidden / opacity:0."""
    offenders = []
    for css in sorted(_GUIS.glob("*.css")):
        text = _strip_comments_css(_read(css))
        # Each rule = "<selector> { <body> }"
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            selector, body = m.group(1), m.group(2)
            if any(tok in selector for tok in _CAVEAT_SELECTORS) and _HIDE_RE.search(body):
                offenders.append(f"{css.name}: {selector.strip()[:80]}")
    assert not offenders, f"a skin hides a caveat/consent surface (forbidden): {offenders}"


def test_every_asset_is_local_no_cdn():
    """Offline / anonymity intact: none of the hand-written gallery files may
    reference an outbound URL (the vendored Alpine is checked separately)."""
    offenders = []
    for f in sorted(_GUIS.glob("*.js")) + sorted(_GUIS.glob("*.css")):
        for ln in _URL_RE.findall(_read(f)):
            offenders.append(f"{f.name}: {ln}")
    assert not offenders, f"gallery files must not reference any http(s) URL: {offenders}"


def test_alpine_is_vendored_pinned_and_local():
    vendor = _GUIS / "vendor"
    js = vendor / "alpine.min.js"
    sha = vendor / "alpine.min.js.sha256"
    assert js.is_file() and sha.is_file(), "Alpine must be vendored with a pinned checksum"
    digest = hashlib.sha256(js.read_bytes()).hexdigest()
    assert digest == sha.read_text(encoding="utf-8").strip(), (
        "vendored alpine.min.js does not match its pinned sha256 (supply-chain guard)"
    )
    body = _read(js)
    assert "window.Alpine" in body, "the vendored build must expose window.Alpine (global IIFE build)"
    assert (vendor / "alpine.LICENSE.txt").is_file(), "Alpine MIT license text must be vendored alongside"
    # boot.js loads Alpine ONLY from the local vendor path (never a CDN).
    boot = _read(_GUIS / "boot.js")
    assert 'vendor/alpine.min.js' in boot, "boot.js must load Alpine from the local vendor path"


def test_alpine_controllers_do_not_load_a_remote_framework():
    """The two Alpine UIs must obtain Alpine via the local loader, never a remote."""
    for ui in ALPINE_IDS:
        js = _read(_GUIS / f"ui-{ui}.js")
        assert "OOGUIs.loadAlpine" in js, f"ui-{ui}.js must load Alpine via the local OOGUIs.loadAlpine()"
        assert not _URL_RE.search(js), f"ui-{ui}.js must not reference a remote URL"


def test_every_skin_rule_is_scoped_to_its_data_ui():
    """A skin must only apply when active: every selector is scoped under
    html[data-ui="<id>"] (at-rules like @media/@keyframes are containers and
    their nested rules are checked individually)."""
    for ui in EXPECTED_IDS:
        css = _strip_comments_css(_read(_GUIS / f"ui-{ui}.css"))
        scope = f'[data-ui="{ui}"]'
        assert scope in css, f"ui-{ui}.css never scopes under {scope}"
        unscoped = []
        for m in re.finditer(r"([^{}]+)\{", css):
            sel = m.group(1).strip()
            if not sel or sel.startswith("@"):  # at-rule container (its inner rules are matched too)
                continue
            if scope not in sel:
                unscoped.append(sel[:70])
        assert not unscoped, f"ui-{ui}.css has selectors not scoped to {scope}: {unscoped}"


def test_gallery_uses_event_listeners_not_inline_handlers():
    """The gallery framework is CSP-friendly: it wires actions with
    addEventListener, never inline on*= handlers."""
    gal = _read(_GUIS / "gallery.js")
    assert "addEventListener(" in gal, "gallery.js must wire actions via addEventListener"
    assert "onclick=" not in gal, "gallery.js must not inject inline onclick handlers"
