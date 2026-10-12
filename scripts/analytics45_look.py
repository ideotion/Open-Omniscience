#!/usr/bin/env python3
"""
analytics45_look -- the Chromium look at Q712's analytics 4 and 5, from the app as it is.

Living sources -> Wikipedia carries two readers at its foot: "One item across editions"
(divergence) and "Most-viewed pages beside your corpus" (attention). This walks both in a real
browser at 1440x900, 768x1024 and 390x844 in the themes asked for (default: every theme in the
picker), in English and, at the first theme, in Arabic (RTL), against a state seeded by
``analytics45_seed.py`` whose every figure is known (it prints them as JSON: ``--truth``).

What each run does, and judges (a row per check, ``ok`` or ``FAIL`` with the reading):

  * the app answers ``online:false`` (the shared ``csp_sweep.require_loopback_offline``) and every
    request the page makes goes to the loopback origin: a request anywhere else FAILS the run;
  * a suggestion button is clicked and its item is what the box and the table then show;
  * an item typed in lower case is read; the table's six rows are checked against the truth:
    the editions' order, each size, each change count (3, 0, and ``unknown`` -- never 0 -- for an
    edition the stream recorded nothing for), the two absences named with their reason, the
    smallest and largest edition, the size bars' lengths against the largest size;
  * an invalid item is refused in words and draws no table;
  * every drop-down in the Wikipedia panel is opened, another option picked, READ BACK from the
    control after the pick (a rebuilt control counts as unread) and its effect judged -- the
    attention edition drop-down also against the table it must change (5 rows -> 3 -> 5) and the
    request it must make;
  * the Refresh button makes the request it should;
  * no horizontal scroll of the page, the console text kept per width and theme.

Run against a booted app (OO_NO_SCHEDULER unset, so it starts offline):

    .venv/bin/python scripts/analytics45_look.py --url http://127.0.0.1:8014 --out DIR

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csp_sweep import (  # noqa: E402
    _INIT,
    WIDTHS,
    require_loopback_offline,
    sweep_selects,
    themes_from_source,
)

_DIV_ROWS = r"""
() => [...document.querySelectorAll('#wiki-div-result tbody tr')].map(tr => ({
  cells: [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim()),
  colspan: tr.children.length === 2,
  bar: (tr.querySelector('.wiki-size-bar i') || {style: {}}).style.width || null,
}))
"""
_ATT_ROWS = r"""
() => [...document.querySelectorAll('#wiki-att-result tbody tr')].map(tr =>
  [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim()))
"""
_OVERFLOW = "() => ({page: document.documentElement.scrollWidth - window.innerWidth, dir: document.documentElement.dir || 'ltr'})"
_WRAP = "id => { const w = document.querySelector(id + ' .wiki-table-wrap'); return w ? {client: w.clientWidth, scroll: w.scrollWidth} : null; }"
# the six editions as the reader draws them (the pill shows the three-letter code): the followed ones, then any other the item was found in
EXPECT_ORDER = ["eng", "deu", "fra", "spa", "ara", "ita"]


def _digits(s: str) -> str:
    """Latin digits of a cell (the app writes Latin digits and a decimal point in every locale)."""
    return re.sub(r"[^0-9.]", "", s.split(" ")[0] if s else "")


def run_one(browser, url: str, wname: str, theme: str, lang: str, out: Path) -> dict:
    w, h = WIDTHS[wname]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.add_init_script(_INIT)
    ctx.add_init_script("try { localStorage.setItem('oo_guide_v1', JSON.stringify({done: true})); } catch (e) {}")
    require_loopback_offline(url, ctx.request)
    page = ctx.new_page()
    page.set_default_timeout(5000)
    console: list[str] = []
    requests: list[str] = []
    page.on("console", lambda m: console.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
    page.on("dialog", lambda d: d.dismiss())
    page.on("request", lambda r: requests.append(r.url))
    page.on("response", lambda r: console.append(f"[http {r.status}] {r.request.method} {r.url[len(url):][:120]}")
            if r.status >= 400 else None)
    checks: list[dict] = []

    def check(name: str, ok: bool, reading=None) -> None:
        checks.append({"check": name, "status": "ok" if ok else "FAIL", "reading": reading})

    def api_calls(frag: str) -> int:
        return sum(1 for u in requests if frag in u)

    page.goto(url, wait_until="load")
    page.wait_for_timeout(1500)
    page.evaluate("t => setTheme(t)", theme)
    if lang != "en":
        page.evaluate("l => OOI18N.setLang(l)", lang)
        page.wait_for_timeout(600)
    page.evaluate("showTab('living')")
    page.wait_for_selector("#wiki-att-result table", timeout=8000)
    page.wait_for_timeout(500)
    check("the app answers online:false", page.request.get(url.rstrip("/") + "/api/system/network").json().get("online") is False)

    # ---- the suggestions ---------------------------------------------------------------- #
    cands = page.evaluate("() => [...document.querySelectorAll('#wiki-div-cands [data-div-qid]')].map(b => b.dataset.divQid)")
    check("suggestions are offered (Q42 first: 9 changes; Q34: 3)", cands[:2] == ["Q42", "Q34"], cands)
    page.locator('#wiki-div-cands [data-div-qid="Q42"]').click()
    page.wait_for_timeout(700)
    back = page.input_value("#wiki-div-q")
    heading = page.inner_text("#wiki-div-result h4") if page.locator("#wiki-div-result h4").count() else None
    rows42 = page.evaluate(_DIV_ROWS)
    check("a suggestion fills the box and reads that item", back == "Q42" and heading == "Q42", {"box": back, "heading": heading})
    check("Q42 shows en and de found, the other followed editions named", sum(1 for r in rows42 if not r["colspan"]) == 2, len(rows42))

    # ---- divergence: a typed item (lower case) ------------------------------------------- #
    page.fill("#wiki-div-q", "q34")
    page.click("#wiki-div-form button[type=submit]")
    page.wait_for_function("() => (document.querySelector('#wiki-div-result h4')||{}).textContent === 'Q34'", timeout=5000)
    rows = page.evaluate(_DIV_ROWS)
    check("six rows", len(rows) == 6, len(rows))
    order = page.evaluate("() => [...document.querySelectorAll('#wiki-div-result tbody tr td:first-child')].map(td => td.innerText.trim())")
    check("editions in the order followed (en de fr es ar), then the extra one found (it)",
          order == EXPECT_ORDER, order)
    found = [r for r in rows if not r["colspan"]]
    check("four found rows, two absences", len(found) == 4 and sum(r["colspan"] for r in rows) == 2, [len(found)])
    sizes = [_digits(r["cells"][2]) for r in found]
    check("sizes en 8.8 KB, de 11.7 KB, fr 300 B, it 500 B (Latin digits)", sizes == ["8.8", "11.7", "300", "500"], sizes)
    changes = [r["cells"][4] for r in found]
    check("changes 3, 0, then unknown twice (never 0 for an edition nothing was recorded for)",
          changes[0] == "3" and changes[1] == "0" and not re.fullmatch(r"[0-9]+", changes[2]) and not re.fullmatch(r"[0-9]+", changes[3]),
          changes)
    bars = [r["bar"] for r in found]
    check("size bars from a zero baseline over the largest (de 100%, en 75%, fr 3%, it 4%)",
          bars == ["75%", "100%", "3%", "4%"], bars)
    absent = [r["cells"][1] for r in rows if r["colspan"]]
    check("both absences carry words (the walk never ran there · finished and found none)", len(absent) == 2 and all(len(a) > 12 for a in absent), absent)
    span = page.inner_text("#wiki-div-result .hint") if page.locator("#wiki-div-result .hint").count() else ""
    check("the spread names the smallest and the largest edition and no ratio", len(span) > 10 and "%" not in span and "×" not in span, span)
    check("method and caveat are visible, not behind a toggle", page.locator("#wiki-div-result .card-caveat").is_visible(), None)

    wrap = page.evaluate(_WRAP, "#wiki-div-result")
    check("the table fits its frame: the last column (changes) is not cut off and needs no sideways scroll",
          bool(wrap) and wrap["scroll"] <= wrap["client"], wrap)
    if theme == "ink":
        page.mouse.move(0, 0)  # no hover bubble over the table
        page.locator("#wiki-div-result").screenshot(path=str(out / f"look-{wname}-{lang}-divergence.png"))

    # ---- divergence: refusals ------------------------------------------------------------ #
    page.fill("#wiki-div-q", "42")
    page.click("#wiki-div-form button[type=submit]")
    page.wait_for_selector("#wiki-div-result .note.err", timeout=5000)
    check("an invalid item is refused in words and draws no table",
          page.locator("#wiki-div-result table").count() == 0, page.inner_text("#wiki-div-result .note.err"))
    page.fill("#wiki-div-q", "Q999")
    page.click("#wiki-div-form button[type=submit]")
    page.wait_for_function("() => /Q999/.test(document.getElementById('wiki-div-result').innerText)", timeout=5000)
    check("an item no walk found says so", True, page.inner_text("#wiki-div-result")[:120])

    # ---- attention ------------------------------------------------------------------------ #
    rows_en = page.evaluate(_ATT_ROWS)
    check("attention en: five rows, ranks 1-5, views as given", [r[0] for r in rows_en] == ["1", "2", "3", "4", "5"]
          and [_digits(r[2].replace(" ", "").replace(" ", "")) for r in rows_en][:1] == ["905113"], rows_en[:2])
    counts = [(r[3], r[4]) for r in rows_en]
    check("press counts day/week 4/6, 0/0, 2/3, not counted, 1/1 (the Wikipedia-sourced article is not coverage)",
          counts[0] == ("4", "6") and counts[1] == ("0", "0") and counts[2] == ("2", "3")
          and not re.fullmatch(r"[0-9]+", counts[3][0]) and counts[4] == ("1", "1"), counts)
    n0 = api_calls("/api/wiki/lane/attention")
    page.select_option("#wiki-att-edition", "de")
    page.wait_for_function("() => document.querySelectorAll('#wiki-att-result tbody tr').length === 3", timeout=5000)
    held = page.input_value("#wiki-att-edition")
    check("edition drop-down: de picked, read back from the control, the table changed to 3 rows and it asked the server once",
          held == "de" and api_calls("/api/wiki/lane/attention") == n0 + 1, {"held": held, "requests": api_calls("/api/wiki/lane/attention") - n0})
    page.select_option("#wiki-att-edition", "en")
    page.wait_for_function("() => document.querySelectorAll('#wiki-att-result tbody tr').length === 5", timeout=5000)
    check("edition drop-down: en picked back, read back, 5 rows", page.input_value("#wiki-att-edition") == "en", None)
    wrap = page.evaluate(_WRAP, "#wiki-att-result")
    check("the attention table fits its frame: the last column (articles in 7 days) is not cut off",
          bool(wrap) and wrap["scroll"] <= wrap["client"], wrap)
    if theme == "ink":
        page.mouse.move(0, 0)
        page.locator("#wiki-att-result").screenshot(path=str(out / f"look-{wname}-{lang}-attention.png"))
    n1 = api_calls("/api/wiki/lane/attention")
    page.click("#wiki-att-tools [data-att-refresh]")
    page.wait_for_timeout(700)
    check("Refresh asks the server once and keeps the chosen edition",
          api_calls("/api/wiki/lane/attention") == n1 + 1 and page.input_value("#wiki-att-edition") == "en", None)

    # ---- every drop-down in the Wikipedia panel ------------------------------------------- #
    results: list = []
    sweep_selects(page, "living > wiki", results, console.append, set(), scope="#living-wiki")
    bad = [r for r in results if r["status"] not in ("ok", "skipped")]
    check(f"every drop-down in the panel picked and read back ({len(results)} of them)", not bad and len(results) > 0,
          [{"id": r["id"], "status": r["status"], "effect": r.get("effect")} for r in results])

    # ---- layout and the network ------------------------------------------------------------ #
    ov = page.evaluate(_OVERFLOW)
    check("no horizontal scroll of the page", ov["page"] <= 0, ov)
    if lang == "ar":
        check("the page is right-to-left", ov["dir"] == "rtl", ov)
    foreign = [u for u in requests if not re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)", u) and not u.startswith(("data:", "blob:"))]
    check("every request the page made went to the loopback origin", not foreign, foreign[:5])
    csp = page.evaluate("() => window.__csp")
    check("no CSP violation", not csp, csp)
    check("the app still answers online:false at the end", page.request.get(url.rstrip("/") + "/api/system/network").json().get("online") is False)
    (out / f"console-{wname}-{theme}-{lang}.txt").write_text(
        f"# console (error + warning) and pageerror text, width {wname}, theme {theme}, language {lang}\n"
        + ("\n".join(console) if console else "(no console errors or warnings)") + "\n", encoding="utf-8")
    ctx.close()
    return {"width": wname, "theme": theme, "lang": lang, "checks": checks, "selects": results,
            "console_lines": len(console)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", choices=sorted(WIDTHS), action="append")
    ap.add_argument("--theme", action="append", help="default: every theme in the picker")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    themes = a.theme or themes_from_source()
    runs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for wname in a.width or list(WIDTHS):
            for i, theme in enumerate(themes):
                for lang in ("en", "ar") if i == 0 else ("en",):
                    try:
                        r = run_one(browser, a.url, wname, theme, lang, out)
                    except Exception as exc:  # noqa: BLE001
                        r = {"width": wname, "theme": theme, "lang": lang, "checks": [
                            {"check": "the run completed", "status": "FAIL", "reading": f"{type(exc).__name__}: {str(exc)[:300]}"}]}
                    runs.append(r)
                    bad = [c for c in r["checks"] if c["status"] != "ok"]
                    print(f"{wname} {theme} {lang}: {len(r['checks']) - len(bad)} ok, {len(bad)} FAIL", flush=True)
                    for c in bad:
                        print(f"    FAIL {c['check']}: {json.dumps(c['reading'], ensure_ascii=False)[:300]}", flush=True)
        browser.close()
    (out / "look-results.json").write_text(json.dumps({"themes": themes, "runs": runs}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if any(c["status"] != "ok" for r in runs for c in r["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
