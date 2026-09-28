"""Recheck row N: coachmark overlap (1440 en/ar, 375 palette), 375 Insights overflow,
group-by-language singular, and watch cleanup."""
import json, re, sys
sys.path.insert(0, "/tmp/claude-0/walk/N-recheck")
from lib import *  # noqa
from playwright.sync_api import sync_playwright

R = {}
rec = Recorder("coach")


def dump():
    (OUT / "R-coach.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))


HIT = """(sel) => { const el = document.querySelector(sel); if (!el) return {missing: sel};
  const r = el.getBoundingClientRect(); const x = r.left + r.width/2, y = r.top + r.height/2;
  const top = document.elementFromPoint(x, y);
  const coach = document.getElementById('net-coach');
  return {sel, rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
          coach_show: coach.classList.contains('show'),
          coach: (() => { const c = coach.getBoundingClientRect(); return [Math.round(c.left), Math.round(c.top), Math.round(c.right), Math.round(c.bottom)]; })(),
          topmost_is_coach: !!(top && top.closest && top.closest('#net-coach')),
          topmost: top ? (top.id || top.className || top.tagName) : null}; }"""


def wait_coach(pg, ms=6000):
    try:
        pg.wait_for_selector("#net-coach.show", timeout=ms)
        pg.wait_for_timeout(600)
        return True
    except Exception:
        return False


def main():
    with sync_playwright() as p:
        b = launch(p)
        # 1440 en then ar
        ctx = b.new_context(viewport={"width": 1440, "height": 950})
        rec.attach_context(ctx, "1440")
        page = ctx.new_page()
        unlock_if_locked(page)
        close_dialogs(page)
        R["en_coach_shown"] = wait_coach(page)
        page.click(".nav-item[data-tab=insights]")
        page.wait_for_timeout(2500)
        R["en_insights_nav"] = page.evaluate(HIT, ".nav-item[data-tab=insights]")
        R["en_watches_subtab"] = page.evaluate(HIT, "#ins-subtabs [data-tab=watches]")
        R["en_trends_subtab"] = page.evaluate(HIT, "#ins-subtabs [data-tab=trends]")
        shot(page, "N-recheck-coach-insights-en")
        set_lang(page, "ar")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        close_dialogs(page)
        R["ar_coach_shown"] = wait_coach(page)
        R["ar_dir"] = page.evaluate("() => document.documentElement.dir")
        R["ar_insights_nav"] = page.evaluate(HIT, ".nav-item[data-tab=insights]")
        shot(page, "N-recheck-coach-sidebar-ar")
        try:
            page.click(".nav-item[data-tab=insights]", timeout=4000)
            R["ar_insights_click"] = "clicked"
        except Exception as e:  # noqa
            R["ar_insights_click"] = "blocked: " + str(e).split("\n")[0][:160]
        dismiss_coach(page)
        set_lang(page, "en")
        # watch cleanup
        page.on("dialog", lambda d: d.accept())
        page.click(".nav-item[data-tab=insights]"); page.wait_for_timeout(2000)
        page.click("#ins-subtabs [data-tab=watches]"); page.wait_for_timeout(2500)
        for _ in range(3):
            dl = page.locator("#wt-list button", has_text="Delete")
            if not dl.count():
                break
            dl.first.click(); page.wait_for_timeout(2500)
        R["watches_after_cleanup"] = text(page, "#wt-list")
        # group by language singular (climate)
        ap = open_analysis_new_tab(ctx, page, "climate")
        ap.wait_for_timeout(6000)
        ap.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
        ap.wait_for_timeout(7000)
        ap.click("#an-subtabs [data-tab=articles]"); ap.wait_for_timeout(2000)
        ap.locator("#an-articles button", has_text="Group by language").first.click()
        ap.wait_for_timeout(2500)
        R["group_headings_climate"] = ap.eval_on_selector_all("#an-art-list tr.an-lang-group", "e=>e.map(x=>x.innerText.trim())")
        ap.locator("#an-articles button", has_text="Interleave by date").first.click()
        ap.wait_for_timeout(1000)
        ctx.close()
        dump()

        # 375 en
        ctx = b.new_context(viewport={"width": 375, "height": 800}, is_mobile=False)
        rec.attach_context(ctx, "375")
        page = ctx.new_page()
        unlock_if_locked(page)
        close_dialogs(page)
        R["375_coach_shown"] = wait_coach(page)
        try:
            page.click(".omni", timeout=4000)
            R["375_omni_click"] = "clicked"
        except Exception as e:  # noqa
            R["375_omni_click"] = "blocked: " + str(e).split("\n")[0][:160]
            page.evaluate("() => { const o=document.querySelector('.omni'); o && o.click(); }")
        page.wait_for_selector("#pal-input", state="visible", timeout=5000)
        page.type("#pal-input", "climate", delay=30)
        page.wait_for_timeout(1200)
        R["375_palette_row0"] = page.evaluate(HIT, ".pal-item")
        R["375_palette_rows"] = palette_rows(page)[:3]
        shot(page, "N-recheck-375-palette-coach-en")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        dismiss_coach(page)
        page.click("#hamburger"); page.wait_for_timeout(800)
        page.click(".nav-item[data-tab=insights]"); page.wait_for_timeout(2500)
        page.click("#ins-subtabs [data-tab=trends]"); page.wait_for_timeout(4000)
        R["375_insights_trends_overflow"] = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        R["375_widest"] = page.evaluate("""() => [...document.querySelectorAll('#tab-insights *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1 && e.offsetParent)
            .slice(0, 6).map(e => [e.tagName + '.' + e.className, Math.round(e.getBoundingClientRect().right), (e.textContent||'').trim().slice(0,70)])""")
        shot(page, "N-recheck-375-insights-trends-en")
        ctx.close()
        dump()
        rec.save()
        b.close()


if __name__ == "__main__":
    main()
