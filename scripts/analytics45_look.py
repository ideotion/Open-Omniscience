#!/usr/bin/env python3
"""
analytics45_look -- the Chromium look at Q712's analytics 4 and 5, from the app as it is.

Living sources -> Wikipedia carries two readers at its foot: "One item across editions"
(divergence) and "Most-viewed pages beside your corpus" (attention). This walks both in a real
browser at 1440x900, 768x1024, 390x844 and the two smaller phones 360x800 and 320x568, in the themes
asked for (default: every theme in the picker), in English and, at the first theme, in Arabic (RTL),
against a state seeded by ``analytics45_seed.py`` whose every figure is known (the seed prints them as
JSON).

What each run does, and judges (a row per check, ``ok`` or ``FAIL`` with the reading):

  * the app answers ``online:false`` (the shared ``csp_sweep.require_loopback_offline``) and every
    request the page makes goes to the loopback origin: a request anywhere else FAILS the run;
  * the suggestions are judged by their numbers (Q42: 9 changes, found in 2 editions; Q34: 3, 4), not only
    their order, and one is clicked: its item is what the box and the table then show;
  * an item typed in lower case is read; the table's six rows are checked against the truth:
    the editions' order, each size, each change count (3, 0, and ``unknown`` -- never 0 -- for an
    edition the stream recorded nothing for), the two absences named with their reason, the
    smallest and largest edition, the size bars' lengths against the largest size;
  * an invalid item is refused in words and draws no table; an item no walk found draws only absences;
  * every drop-down in the Wikipedia panel is opened, another option picked, READ BACK from the
    control after the pick and its effect judged. The control is marked before the pick and found again
    by node identity after it (``csp_sweep``'s ``rebuilt``): the attention edition drop-down is redrawn
    by the page on every pick (its options come from the server's answer), so the pick is read from the
    NEW control, the one a person now sees, and again 700 ms later (it must still hold); the rebuild
    is in the record, never hidden. That drop-down is also judged against the table it must change
    (5 rows -> 3 -> 5) and the request it must make;
  * the Refresh button makes the request it should;
  * both tables fit their frame, with their HEADROOM measured (the frame minus the narrowest the
    table can be drawn: 0 or less means the last column is cut off behind a sideways scroll);
  * no horizontal scroll of the page; the console text kept per width, theme and language, and a
    console error, warning, page error or HTTP >= 400 FAILS the run (it is a check, not only a file).

``--serve app-living.js=PATH`` (or ``app.css=PATH``) serves another file in place of one of the app's static files, which is how
``docs/audit/analytics45-look-2026-10-12/mutation_checks.py`` proves the checks can fail.

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
    require_loopback_offline,
    sweep_selects,
    themes_from_source,
)
from csp_sweep import (
    WIDTHS as _SWEEP_WIDTHS,
)

# row I's three widths plus the two smaller phones (the CSS fix this look found is measured down to 320 px)
WIDTHS = {**_SWEEP_WIDTHS, "360x800": (360, 800), "320x568": (320, 568)}

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
# the frame, what scrolls inside it, and the narrowest the table can be drawn (width forced to 1px = its min-content width)
_WRAP = """id => { const w = document.querySelector(id + ' .wiki-table-wrap'); if (!w) return null;
  const t = w.querySelector('table'), keep = t.style.width; t.style.width = '1px';
  const min = Math.ceil(t.getBoundingClientRect().width); t.style.width = keep;
  return {client: w.clientWidth, scroll: w.scrollWidth, narrowest: min, headroom: w.clientWidth - min}; }"""
# the six editions as the reader draws them (the pill shows the three-letter code): the followed ones, then any other the item was found in
EXPECT_ORDER = ["eng", "deu", "fra", "spa", "ara", "ita"]


# What the page must show, per state. SEED: the figures ``analytics45_seed.py`` writes on purpose. GENERATED: derived from the
# truth ``analytics45_generate.py`` prints (the PLAN of its seeded stand-in world, never read back from the lane).
A3 = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "ar": "ara", "it": "ita"}


def seed_expectations() -> dict:
    return {
        "mode": "seed",
        "cands": [("Q42", [9, 2]), ("Q34", [3, 4])],
        "first": {"qid": "Q42", "found": ["eng", "deu"], "n_rows": 5},
        "item": {"qid": "Q34", "order": EXPECT_ORDER, "rows": [
            {"edition": "eng", "found": True, "size_text": "8.8", "changes": 3, "bar": "75%"},
            {"edition": "deu", "found": True, "size_text": "11.7", "changes": 0, "bar": "100%"},
            {"edition": "fra", "found": True, "size_text": "300", "changes": None, "bar": "3%"},
            {"edition": "spa", "found": False}, {"edition": "ara", "found": False},
            {"edition": "ita", "found": True, "size_text": "500", "changes": None, "bar": "4%"}]},
        "n_followed": 5,
        "att_first_views": "905113",
        "att": {"en": [("4", "6"), ("0", "0"), ("2", "3"), None, ("1", "1")], "de": [None] * 3},
        "att_other": "de", "att_main": "en",
    }


def generated_expectations(truth: dict, item: str = "Q34") -> dict:
    """Expectations from ``analytics45_generate.py``'s truth. The first suggestion is whichever item the plan ranks first."""
    sugg = truth["suggestions"]
    first = truth["divergence"][sugg[0]["qid"]]
    rows = truth["divergence"][item]["rows"]
    att = {c: [None if r["day"] is None else (str(r["day"]), str(r["week"])) for r in rs] for c, rs in truth["attention"].items()}
    editions = [e for e in ("en", "de", "fr", "es", "ar") if e in att]
    return {
        "mode": "generated",
        "cands": [(g["qid"], [g["changes"], g["found_in"]]) for g in sugg[:2]],
        "first": {"qid": sugg[0]["qid"], "found": [r["edition"] for r in first["rows"] if r["found"]], "n_rows": len(first["rows"])},
        "item": {"qid": item, "order": [r["edition"] for r in rows], "rows": rows},
        "n_followed": len(truth["followed"]),
        "att_first_views": str(truth["attention"]["en"][0]["views"]),
        "att": att, "att_other": "de", "att_main": "en", "att_editions": editions,
        "label": truth.get("label"),
    }


def _digits(s: str) -> str:
    """Latin digits of a cell (the app writes Latin digits and a decimal point in every locale)."""
    return re.sub(r"[^0-9.]", "", s.split(" ")[0] if s else "")


def run_one(browser, url: str, wname: str, theme: str, lang: str, out: Path, serve: dict[str, str] | None = None, X: dict | None = None) -> dict:
    X = X or seed_expectations()
    w, h = WIDTHS[wname]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    for fname, path in (serve or {}).items():
        body = Path(path).read_text(encoding="utf-8")
        ctype = "text/css" if fname.endswith(".css") else "application/javascript"

        def fulfil(route, request, body=body, ctype=ctype):  # Playwright hands a route handler (route, request)
            route.fulfill(status=200, content_type=ctype, body=body)

        ctx.route(f"**/static/{fname}*", fulfil)
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
    cands = page.evaluate("() => [...document.querySelectorAll('#wiki-div-cands [data-div-qid]')]"
                          ".map(b => ({qid: b.dataset.divQid, text: b.innerText}))")
    nums = [(c["qid"], [int(x) for x in re.findall(r"[0-9]+", c["text"].replace(c["qid"], ""))]) for c in cands[:2]]
    check(f"suggestions are offered with their numbers {X['cands']} (an item's changes, the editions it was found in)",
          nums == X["cands"], [c["text"] for c in cands])
    fq = X["first"]["qid"]
    page.locator(f'#wiki-div-cands [data-div-qid="{fq}"]').click()
    page.wait_for_timeout(700)
    back = page.input_value("#wiki-div-q")
    heading = page.inner_text("#wiki-div-result h4") if page.locator("#wiki-div-result h4").count() else None
    rows42 = page.evaluate(_DIV_ROWS)
    check("a suggestion fills the box and reads that item", back == fq and heading == fq, {"box": back, "heading": heading})
    found42 = [r["cells"][0] for r in rows42 if not r["colspan"]]
    check(f"{fq} shows {X['first']['found']} found (named), every other row named as an absence",
          found42 == X["first"]["found"] and len(rows42) == X["first"]["n_rows"]
          and sum(1 for r in rows42 if r["colspan"]) == len(rows42) - len(found42), found42)

    # ---- divergence: a typed item (lower case) ------------------------------------------- #
    item = X["item"]
    plan = item["rows"]
    page.fill("#wiki-div-q", item["qid"].lower())
    page.click("#wiki-div-form button[type=submit]")
    page.wait_for_function("q => (document.querySelector('#wiki-div-result h4')||{}).textContent === q", arg=item["qid"], timeout=5000)
    rows = page.evaluate(_DIV_ROWS)
    check(f"{len(plan)} rows", len(rows) == len(plan), len(rows))
    order = page.evaluate("() => [...document.querySelectorAll('#wiki-div-result tbody tr td:first-child')].map(td => td.innerText.trim())")
    check("editions in the order followed, then any extra one the walk found the item in",
          order == item["order"], order)
    found = [r for r in rows if not r["colspan"]]
    pf = [r for r in plan if r["found"]]
    check(f"{len(pf)} found rows, {len(plan) - len(pf)} absences", len(found) == len(pf) and sum(r["colspan"] for r in rows) == len(plan) - len(pf), [len(found)])
    sizes = [_digits(r["cells"][2]) for r in found]
    check(f"sizes {[r['size_text'] for r in pf]} (Latin digits)", sizes == [r["size_text"] for r in pf], sizes)
    changes = [r["cells"][4] for r in found]
    check(f"changes {[r['changes'] for r in pf]} (None = unknown, never 0 for an edition nothing was recorded for)",
          all((c == str(r["changes"])) if r["changes"] is not None else not re.fullmatch(r"[0-9]+", c) for c, r in zip(changes, pf, strict=True)),
          changes)
    bars = [r["bar"] for r in found]
    check(f"size bars from a zero baseline over the largest {[r['bar'] for r in pf]}", bars == [r["bar"] for r in pf], bars)
    absent = [r["cells"][1] for r in rows if r["colspan"]]
    check("every absence carries words (the walk never ran there · finished and found none)", len(absent) == len(plan) - len(pf) and all(len(a) > 12 for a in absent), absent)
    span = page.inner_text("#wiki-div-result .hint") if page.locator("#wiki-div-result .hint").count() else ""
    check("the spread names the smallest and the largest edition and no ratio", len(span) > 10 and "%" not in span and "×" not in span, span)
    check("method and caveat are visible, not behind a toggle", page.locator("#wiki-div-result .card-caveat").is_visible(), None)

    wrap = page.evaluate(_WRAP, "#wiki-div-result")
    check("the table fits its frame: the last column (changes) is not cut off and needs no sideways scroll (headroom in px)",
          bool(wrap) and wrap["scroll"] <= wrap["client"] and wrap["headroom"] >= 0, wrap)
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
    rows999 = page.evaluate(_DIV_ROWS)
    check("an item no walk found draws only absences, each with its reason, and no size bar",
          "Q999" in page.inner_text("#wiki-div-result") and len(rows999) == X["n_followed"]
          and all(r["colspan"] and len(r["cells"][1]) > 12 for r in rows999)
          and page.locator("#wiki-div-result .wiki-size-bar").count() == 0, [r["cells"] for r in rows999][:2])

    # ---- attention ------------------------------------------------------------------------ #
    rows_en = page.evaluate(_ATT_ROWS)
    main_ed, other_ed = X["att_main"], X["att_other"]
    n_main, n_other = len(X["att"][main_ed]), len(X["att"][other_ed])
    check(f"attention {main_ed}: {n_main} rows, ranks 1-{n_main}, views as given", [r[0] for r in rows_en] == [str(i) for i in range(1, n_main + 1)]
          and [_digits(r[2].replace(" ", "").replace(" ", "")) for r in rows_en][:1] == [X["att_first_views"]], rows_en[:2])
    counts = [(r[3], r[4]) for r in rows_en]
    want = X["att"][main_ed]
    check("press counts day/week per row (the Wikipedia-sourced article is not coverage; None = not counted)",
          len(counts) == len(want) and all((c == w) if w is not None else not re.fullmatch(r"[0-9]+", c[0]) for c, w in zip(counts, want, strict=True)), counts[:14])
    n0 = api_calls("/api/wiki/lane/attention")
    page.evaluate("() => { window.__a45 = document.getElementById('wiki-att-edition'); }")  # the control the pick is made on
    page.select_option("#wiki-att-edition", other_ed)
    page.wait_for_function("n => document.querySelectorAll('#wiki-att-result tbody tr').length === n", arg=n_other, timeout=5000)
    held = page.input_value("#wiki-att-edition")
    rebuilt = page.evaluate("() => document.getElementById('wiki-att-edition') !== window.__a45")
    page.wait_for_timeout(700)
    check(f"edition drop-down: {other_ed} picked; the control on screen (a NEW one when the page redrew it: rebuilt is recorded) "
          f"reads {other_ed} now and 700 ms later; the table changed to {n_other} rows; one request",
          held == other_ed and page.input_value("#wiki-att-edition") == other_ed and api_calls("/api/wiki/lane/attention") == n0 + 1,
          {"held": held, "rebuilt": rebuilt, "requests": api_calls("/api/wiki/lane/attention") - n0})
    page.select_option("#wiki-att-edition", main_ed)
    page.wait_for_function("n => document.querySelectorAll('#wiki-att-result tbody tr').length === n", arg=n_main, timeout=5000)
    check(f"edition drop-down: {main_ed} picked back, read back from the control on screen, {n_main} rows", page.input_value("#wiki-att-edition") == main_ed, None)
    if X["mode"] == "generated":
        # every option of the edition drop-down, not one: each is picked, read back from the control now on screen, and the
        # table it draws is judged against the plan's list for that edition (row count, ranks, press counts)
        offered = page.evaluate("() => [...document.querySelectorAll('#wiki-att-edition option')].map(o => o.value)")
        bad: list = []
        for ed in X["att_editions"]:
            want_rows = X["att"][ed]
            page.select_option("#wiki-att-edition", ed)
            page.wait_for_function("n => document.querySelectorAll('#wiki-att-result tbody tr').length === n", arg=len(want_rows), timeout=5000)
            got = page.evaluate(_ATT_ROWS)
            cells = [(r[3], r[4]) for r in got]
            if (page.input_value("#wiki-att-edition") != ed or [r[0] for r in got] != [str(i) for i in range(1, len(want_rows) + 1)]
                    or not all((c == w) if w is not None else not re.fullmatch(r"[0-9]+", c[0]) for c, w in zip(cells, want_rows, strict=True))):
                bad.append({"edition": ed, "held": page.input_value("#wiki-att-edition"), "rows": len(got), "want": len(want_rows)})
        check(f"edition drop-down: all {len(X['att_editions'])} options picked ({', '.join(X['att_editions'])}); each read back from the control "
              "on screen and its table judged against the plan", sorted(offered) == sorted(X["att_editions"]) and not bad, {"offered": offered, "bad": bad})
        page.select_option("#wiki-att-edition", main_ed)
        page.wait_for_function("n => document.querySelectorAll('#wiki-att-result tbody tr').length === n", arg=n_main, timeout=5000)
    wrap = page.evaluate(_WRAP, "#wiki-att-result")
    check("the attention table fits its frame: the last column (articles in 7 days) is not cut off (headroom in px)",
          bool(wrap) and wrap["scroll"] <= wrap["client"] and wrap["headroom"] >= 0, wrap)
    if theme == "ink":
        page.mouse.move(0, 0)
        page.locator("#wiki-att-result").screenshot(path=str(out / f"look-{wname}-{lang}-attention.png"))
    n1 = api_calls("/api/wiki/lane/attention")
    page.click("#wiki-att-tools [data-att-refresh]")
    page.wait_for_timeout(700)
    check("Refresh asks the server once and keeps the chosen edition",
          api_calls("/api/wiki/lane/attention") == n1 + 1 and page.input_value("#wiki-att-edition") == main_ed, None)

    # ---- every drop-down in the Wikipedia panel ------------------------------------------- #
    results: list = []
    sweep_selects(page, "living > wiki", results, console.append, set(), scope="#living-wiki")
    bad = [r for r in results if r["status"] not in ("ok", "skipped")]
    check(f"every drop-down in the panel picked and read back from the control now on screen ({len(results)} of them)",
          not bad and len(results) > 0,
          [{"id": r["id"], "status": r["status"], "effect": r.get("effect"), "rebuilt": r.get("rebuilt")} for r in results])

    # ---- layout and the network ------------------------------------------------------------ #
    ov = page.evaluate(_OVERFLOW)
    check("no horizontal scroll of the page", ov["page"] <= 0, ov)
    if lang == "ar":
        check("the page is right-to-left", ov["dir"] == "rtl", ov)
    foreign = [u for u in requests if not re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)", u) and not u.startswith(("data:", "blob:"))]
    check("every request the page made went to the loopback origin", not foreign, foreign[:5])
    csp = page.evaluate("() => window.__csp")
    check("no CSP violation", not csp, csp)
    check("no console error, warning, page error or HTTP >= 400 (the text is kept in console-*.txt)", not console, console[:5])
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
    ap.add_argument("--serve", action="append", default=[], help="FILE=PATH: serve PATH in place of /static/FILE (mutation checks)")
    ap.add_argument("--lang", action="append", help="default: en, and ar at the first theme")
    ap.add_argument("--truth", help="the JSON ``analytics45_generate.py`` printed: judge the page against that plan (default: the figures the seed writes)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    themes = a.theme or themes_from_source()
    serve = dict(v.split("=", 1) for v in a.serve)
    X = generated_expectations(json.loads(Path(a.truth).read_text(encoding="utf-8"))) if a.truth else seed_expectations()
    runs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for wname in a.width or list(WIDTHS):
            for i, theme in enumerate(themes):
                for lang in a.lang or (("en", "ar") if i == 0 else ("en",)):
                    try:
                        r = run_one(browser, a.url, wname, theme, lang, out, serve, X)
                    except Exception as exc:  # noqa: BLE001
                        r = {"width": wname, "theme": theme, "lang": lang, "checks": [
                            {"check": "the run completed", "status": "FAIL", "reading": f"{type(exc).__name__}: {str(exc)[:300]}"}]}
                    runs.append(r)
                    bad = [c for c in r["checks"] if c["status"] != "ok"]
                    print(f"{wname} {theme} {lang}: {len(r['checks']) - len(bad)} ok, {len(bad)} FAIL", flush=True)
                    for c in bad:
                        print(f"    FAIL {c['check']}: {json.dumps(c['reading'], ensure_ascii=False)[:300]}", flush=True)
        browser.close()
    (out / "look-results.json").write_text(json.dumps({"state": X["mode"], "label": X.get("label"), "themes": themes, "runs": runs}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if any(c["status"] != "ok" for r in runs for c in r["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
