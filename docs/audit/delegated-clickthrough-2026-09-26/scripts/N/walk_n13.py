"""N13 stand-in: a store SEEDED BY THE PRE-S8 CODE (git archive 1af520c^, encrypted), served by
current main on :8831. BEFORE totals -> re-index (task manager watched) -> report -> AFTER
totals -> second run (expect re-indexed: 0)."""
import json, re, sys, traceback
sys.path.insert(0, "/tmp/claude-0/walk/N")
import lib
lib.URL = "http://127.0.0.1:8831"
from lib import *
from playwright.sync_api import sync_playwright

URL = lib.URL
WORDS = {"zh_budget": "预算", "zh_clinic": "诊所", "ar_teh": "الإقليمية", "ar_heh": "الاقليميه",
         "ar_harakat": "الإِقْلِيمِيَّة", "ar_alef_maqsura": "على", "ar_yeh": "علي", "climate": "climate"}
R: dict = {"server": URL}
rec = Recorder("n13")


def totals(ctx, page, tag):
    out = {}
    for k, w in WORDS.items():
        page.bring_to_front()
        open_palette_type(page, w)
        with ctx.expect_page(timeout=20000) as pinfo:
            row = click_palette_row(page, [f"Analysis: “{w}”"])
        ap = pinfo.value
        ap.wait_for_load_state("domcontentloaded"); ap.wait_for_timeout(2500); dismiss_coach(ap)
        ap.click("#an-subtabs [data-tab=articles]"); ap.wait_for_timeout(1500)
        try:
            t = wait_art_total(ap, timeout=20000)
        except Exception:
            t = None
        ap.wait_for_timeout(1500)
        x = text(ap, "#an-xlang") or ""
        # the stale-render race: if the block names another term, re-click this tab
        if x and not x.startswith(w):
            out.setdefault("_races", []).append({"word": w, "xlang_head": x[:60]})
            tab = ap.locator(".an-tab").filter(has_text=w)
            if tab.count():
                tab.first.click(); ap.wait_for_timeout(1500)
                ap.click("#an-subtabs [data-tab=articles]"); ap.wait_for_timeout(1500)
                t = wait_art_total(ap)
        if t is None:
            t0 = text(ap, "#an-art-list") or ""
            t = 0 if t0 else None
            out.setdefault("_empty_msgs", {})[w] = t0[:120]
        langs = sorted(set(ap.eval_on_selector_all("#an-art-list table tr[data-aid]", "rs=>rs.map(r=>(r.querySelectorAll('td')[2]||{innerText:''}).innerText.trim().slice(0,3))")))
        out[k] = {"word": w, "total": t, "langs": langs}
        if k in ("zh_budget", "ar_heh"):
            shot(ap, f"N-N13-{tag}-{k}")
        ap.close()
    return out


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    rec.attach_context(ctx, "n13")
    page = ctx.new_page()
    rec.attach(page, "main")
    dialogs = []
    accept = {"on": False}

    def on_dialog(d):
        dialogs.append({"type": d.type, "message": d.message})
        d.accept() if accept["on"] else d.dismiss()
    page.on("dialog", on_dialog)
    try:
        page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(2000)
        R["lock_form"] = page.is_visible("#pw")
        if R["lock_form"]:
            shot(page, "N-N13-lock-en")
            page.fill("#pw", PASS); page.click("#btn-unlock")
            page.wait_for_url(re.compile(r".*#home.*"), timeout=90000); page.wait_for_timeout(4000)
        close_dialogs(page); dismiss_coach(page)
        R["status_before"] = page.evaluate("async () => (await fetch('/api/search/index-job/status')).json()")
        R["before"] = totals(ctx, page, "before")
        # open the task manager first (its own browser tab), then run the job
        page.bring_to_front()
        with ctx.expect_page(timeout=20000) as pinfo:
            page.click("#tm-open")
        tm = pinfo.value
        tm.wait_for_load_state("domcontentloaded"); tm.wait_for_timeout(2500)
        R["tm_title"] = tm.title()
        tabs = tm.eval_on_selector_all("button", "e=>e.map(b=>b.innerText.trim()).filter(x=>x)")
        R["tm_buttons"] = tabs[:30]
        pr = tm.locator("button", has_text="Processes")
        if pr.count():
            pr.first.click(); tm.wait_for_timeout(800)
        page.bring_to_front()
        page.click("button[onclick=\"showTab('settings')\"]")
        page.click("#set-subtabs button[data-tab=advanced]"); page.wait_for_timeout(800)
        page.click("details[data-adv=diagnostics] > summary")
        page.wait_for_selector("#fts-reindex-btn", state="visible", timeout=20000)
        accept["on"] = True
        n0 = len(dialogs)
        page.click("#fts-reindex-btn")
        page.wait_for_timeout(300)
        accept["on"] = False
        R["confirm1"] = dialogs[n0:]
        # watch the task manager while it runs
        seen = []
        for i in range(40):
            tm.bring_to_front()
            body = tm.evaluate("() => document.body.innerText")
            hit = [ln for ln in body.split("\n") if re.search(r"Re-index|re-index|reindex|Réindex", ln)]
            st = page.evaluate("async () => (await fetch('/api/search/index-job/status')).json()")
            seen.append({"i": i, "tm_lines": hit[:6], "state": st.get("state"), "pct": st.get("percent"), "checked": st.get("articles_checked")})
            if hit and i < 3:
                shot(tm, "N-N13-taskmanager-en")
            if st.get("state") != "running":
                break
            tm.wait_for_timeout(250)
        R["tm_during"] = seen
        R["tm_row_buttons"] = tm.evaluate("""() => { const out=[]; for (const el of document.querySelectorAll('*')) { if (el.children.length && /Re-indexing search/.test(el.innerText||'') && el.innerText.length < 300) out.push({text: el.innerText.trim().slice(0,200), buttons:[...el.querySelectorAll('button')].map(b=>b.innerText.trim())}); } return out.slice(-2); }""")
        shot(tm, "N-N13-taskmanager-after-en")
        page.bring_to_front()
        page.wait_for_function("() => /Articles checked: [\\d,]+ ·|not been upgraded|error/.test((document.getElementById('fts-reindex-status')||{}).textContent||'')", timeout=600000)
        page.wait_for_timeout(800)
        R["status_line1"] = text(page, "#fts-reindex-status")
        shot(page, "N-N13-reindex1-en")
        with ctx.expect_page(timeout=20000) as pinfo:
            page.click("#fts-reindex-report")
        rp = pinfo.value; rp.wait_for_load_state("domcontentloaded"); rp.wait_for_timeout(800)
        body = rp.evaluate("() => document.body.innerText")
        try:
            R["report1"] = json.loads(body)
        except Exception:
            R["report1_text"] = body[:1500]
        (OUT / "n13-report1.json").write_text(body)
        rp.close()
        R["after"] = totals(ctx, page, "after")
        # second run
        page.bring_to_front()
        accept["on"] = True
        n0 = len(dialogs)
        page.click("#fts-reindex-btn")
        page.wait_for_timeout(500)
        accept["on"] = False
        R["confirm2"] = dialogs[n0:]
        page.wait_for_function("() => /Articles checked: [\\d,]+ ·|not been upgraded|error/.test((document.getElementById('fts-reindex-status')||{}).textContent||'')", timeout=600000)
        page.wait_for_timeout(2500)
        R["status_line2"] = text(page, "#fts-reindex-status")
        R["report2"] = page.evaluate("async () => (await fetch('/api/search/index-job/report')).json()")
    except Exception as e:  # noqa: BLE001
        R["exception"] = f"{type(e).__name__}: {str(e)[:500]}"
        R["trace"] = traceback.format_exc()[-1500:]
    R["dialogs"] = dialogs
    b.close()

rec.data = R
rec.save()
(OUT / "R-n13.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1)[:12000])
print("PAGE ERRORS", rec.page_errors, "CONSOLE", rec.console_errors, "HTTP", rec.http_errors)
