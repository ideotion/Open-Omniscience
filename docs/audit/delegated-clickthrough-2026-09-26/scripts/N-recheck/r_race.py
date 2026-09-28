"""Recheck row N: P1 race (new analysis tab paints another tab's results), P2 sense-pin
leak, literal-lens leak, legend chip, default order. Chromium 1440x950, en."""
import json, re, sys, time
sys.path.insert(0, "/tmp/claude-0/walk/N-recheck")
from lib import *  # noqa
from playwright.sync_api import sync_playwright

R = {}
rec = Recorder("race")


def an_state(ap):
    return ap.evaluate("""() => ({
      url: location.href,
      query_label: (document.getElementById('an-query')||{}).textContent,
      strip_active: [...document.querySelectorAll('.an-tab.active .an-tab-label')].map(b=>b.textContent.trim()),
      xlang: ((document.getElementById('an-xlang')||{}).innerText||'').slice(0,160),
      total: (() => { const h=document.querySelector('#an-art-total b'); return h ? h.textContent.trim() : null; })(),
      chips: [...document.querySelectorAll('#an-art-facets .an-facet')].map(b=>b.innerText.trim()).filter(s=>/^[a-z]{3}\\b/.test(s)),
      adv_query: (document.getElementById('an-adv-query')||{}).value,
      ls: (() => { try { const r = JSON.parse(localStorage.getItem('oo.an.tabs.v1')); return {active: r.active, tabs: r.tabs.map(t=>({id:t.id,q:t.query,lens:t.lens}))}; } catch(e) { return null; } })(),
    })""")


def settle(ap, ms=9000):
    ap.wait_for_timeout(1500)
    try:
        ap.click("#an-subtabs [data-tab=articles]")
    except Exception:
        pass
    ap.wait_for_timeout(ms)


def dump():
    (OUT / "R-race.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))


def main():
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        rec.attach_context(ctx, "en")
        reqlog = []  # (page_tag, url)
        pages = {}

        def on_page(pg):
            tag = f"p{len(pages)}"
            pages[tag] = pg
            pg.on("request", lambda r, tag=tag: reqlog.append((tag, r.url)) if "/api/articles?" in r.url else None)
        ctx.on("page", on_page)
        page = ctx.new_page()
        rec.attach(page, "main")
        unlock_if_locked(page)
        close_dialogs(page)
        dismiss_coach(page)
        R["net"] = page.evaluate("() => fetch('/api/system/network').then(r=>r.json())")
        R["plane_fill"] = page.evaluate("() => { const b=document.getElementById('net-toggle'); const s=b&&b.querySelector('path,svg'); return s ? (s.getAttribute('fill')||'') : null }")

        # A. climate in a new browser tab
        ap1 = open_analysis_new_tab(ctx, page, "climate")
        settle(ap1)
        R["A_climate_tab"] = an_state(ap1)
        shot(ap1, "N-recheck-A-climate-en")

        # B. natural repetition: make climate the persisted active, then open election
        R["B_runs"] = []
        for i in range(6):
            # make climate the persisted active tab through a real strip click
            ap1.bring_to_front()
            tabbtn = ap1.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$"))
            tabbtn.first.click()
            ap1.wait_for_timeout(1500)
            ls_before = ap1.evaluate("() => JSON.parse(localStorage.getItem('oo.an.tabs.v1')).active")
            n0 = len(reqlog)
            page.bring_to_front()
            ep = open_analysis_new_tab(ctx, page, "election")
            tag = [k for k, v in pages.items() if v is ep][0]
            settle(ep, 9000)
            st = an_state(ep)
            reqs = [u for (t_, u) in reqlog[n0:] if t_ == tag]
            st["articles_requests_from_this_tab"] = [re.sub(r".*/api/articles\?", "", u)[:120] for u in reqs]
            st["climate_request_issued"] = any("query=climate" in u for u in reqs)
            st["election_request_issued"] = any("query=election" in u for u in reqs)
            st["persisted_active_before"] = ls_before
            st["race_lost"] = not (st["xlang"] or "").startswith("election")
            if st["race_lost"]:
                st["shot"] = shot(ep, f"N-recheck-B-race-run{i}-en")
            R["B_runs"].append(st)
            ep.close()
            dump()
            print("B run", i, "lost" if st["race_lost"] else "ok", st["total"], st["xlang"][:50])

        # C. deterministic: hold climate's /api/articles until election's has painted
        held = []

        def hold(route):
            if "query=climate" in route.request.url and "/api/articles?" in route.request.url:
                held.append(route)
            else:
                route.continue_()
        ap1.bring_to_front()
        ap1.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
        ap1.wait_for_timeout(1500)
        ctx.route(re.compile(r".*/api/articles\?.*"), hold)
        page.bring_to_front()
        ep = open_analysis_new_tab(ctx, page, "election")
        ep.wait_for_timeout(6000)
        R["C_before_release"] = an_state(ep)
        R["C_held_n"] = len(held)
        for r in held:
            r.continue_()
        ep.wait_for_timeout(5000)
        R["C_after_release"] = an_state(ep)
        dump()
        shot(ep, "N-recheck-C-race-forced-en")
        ctx.unroute(re.compile(r".*/api/articles\?.*"), hold)
        ep.close()

        # D. sense-pin leak: pick "public election" in an election tab, leave it pinned
        page.bring_to_front()
        ep = open_analysis_new_tab(ctx, page, "election")
        settle(ep, 8000)
        # recover from a race with a real strip click if needed
        if not (an_state(ep)["xlang"] or "").startswith("election"):
            ep.locator(".an-tab-label", has_text=re.compile(r"^\s*election\s*$")).first.click()
            ep.wait_for_timeout(6000)
        R["D_election_initial"] = an_state(ep)
        ep.click("#an-subtabs [data-tab=articles]"); ep.wait_for_timeout(1000)
        ep.locator("#an-xlang button", has_text="public election").first.click()
        ep.wait_for_timeout(7000)
        R["D_election_pinned"] = an_state(ep)
        shot(ep, "N-recheck-D-election-pinned-en")
        # now open climate in a new browser tab from the first tab
        page.bring_to_front()
        cp = open_analysis_new_tab(ctx, page, "climate")
        settle(cp, 9000)
        R["D_climate_new_tab"] = an_state(cp)
        shot(cp, "N-recheck-D-climate-url-leak-en")
        # then election again in a new browser tab
        page.bring_to_front()
        ep2 = open_analysis_new_tab(ctx, page, "election")
        settle(ep2, 9000)
        R["D_election_again_new_tab"] = an_state(ep2)
        shot(ep2, "N-recheck-D-election-prepinned-en")
        # clean the pin through the UI
        dump()
        try:
            ep2.click("#an-subtabs [data-tab=articles]"); ep2.wait_for_timeout(1000)
            ep2.locator("#an-xlang button", has_text="Show all senses").first.click()
            ep2.wait_for_timeout(5000)
        except Exception as e:  # noqa
            R["D_clear_err"] = str(e)[:200]
        for x in (ep, cp, ep2):
            try: x.close()
            except Exception: pass

        # E. literal-lens leak: climate literal, then a DIFFERENT term (climat) in a new tab
        page.bring_to_front()
        cp = open_analysis_new_tab(ctx, page, "climate")
        settle(cp, 9000)
        if not (an_state(cp)["xlang"] or "").startswith("climate"):
            cp.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
            cp.wait_for_timeout(6000)
        cp.click("#an-subtabs [data-tab=articles]"); cp.wait_for_timeout(1000)
        cp.locator("#an-xlang button", has_text="Show only the words I typed").first.click()
        cp.wait_for_timeout(7000)
        R["E_climate_literal"] = an_state(cp)
        page.bring_to_front()
        fp = open_analysis_new_tab(ctx, page, "climat")
        settle(fp, 10000)
        R["E_climat_new_tab"] = an_state(fp)
        shot(fp, "N-recheck-E-climat-literal-leak-en")
        # restore
        try:
            cp.bring_to_front()
            cp.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
            cp.wait_for_timeout(4000)
            btn = cp.locator("#an-xlang button", has_text="Search the concept in every language")
            cp.click("#an-subtabs [data-tab=articles]"); cp.wait_for_timeout(1000)
            if btn.count():
                btn.first.click(); cp.wait_for_timeout(4000)
        except Exception as e:  # noqa
            R["E_restore_err"] = str(e)[:200]

        # F. legend chip + default order in the climate tab
        cp.bring_to_front()
        R["F_state"] = an_state(cp)
        select_subtab(cp, "articles")
        cp.wait_for_timeout(3000)
        R["F_default_order"] = {
            "sort_value": cp.evaluate("() => { const s=document.getElementById('an-adv-sort'); return s ? [s.value, s.options[s.selectedIndex] && s.options[s.selectedIndex].text] : null }"),
            "interleave_pressed": cp.evaluate("() => [...document.querySelectorAll('#an-articles button')].filter(b=>/Interleave by date/.test(b.textContent)).map(b=>b.getAttribute('aria-pressed'))"),
            "dates": cp.eval_on_selector_all("#an-art-list tr[data-aid]", "rs=>rs.slice(0,15).map(r=>r.querySelectorAll('td')[3].innerText.trim())"),
        }
        select_subtab(cp, "trend")
        cp.wait_for_timeout(3000)
        cp.locator("#an-trend button", has_text="By language").first.click()
        cp.wait_for_timeout(3000)
        legsel = "#an-trend .fig-leg"
        R["F_legend_before"] = cp.eval_on_selector_all(legsel, "e=>e.map(x=>[x.innerText.trim(), x.getAttribute('aria-pressed')])")
        cp.locator(legsel).first.click()
        cp.wait_for_timeout(1500)
        R["F_legend_after_hide"] = cp.eval_on_selector_all(legsel, "e=>e.map(x=>[x.innerText.trim(), x.getAttribute('aria-pressed')])")
        shot(cp, "N-recheck-F-legend-hidden-en")
        # try to find a dimmed chip to click back
        R["F_dimmed_chip_present"] = cp.evaluate("() => [...document.querySelectorAll('#an-trend .fig-leg')].some(x=>x.getAttribute('aria-pressed')==='false')")
        (OUT / "R-race.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
        rec.data = {}
        rec.save()
        b.close()


if __name__ == "__main__":
    main()
