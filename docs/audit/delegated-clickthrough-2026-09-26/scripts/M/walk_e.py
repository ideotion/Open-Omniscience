"""Phase E: M4 ar/zh (no-reload vs reload), ring panel fr/ar/zh/ja, M9 consent (en)."""
import json
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa
from walk_b_lib import tags, open_insights_explore, explore, open_corpus_from_explore  # noqa

BASE = "http://127.0.0.1:8826"
R = {}
DIALOGS = []


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message})
    d.dismiss()


def tip_text(page):
    return page.evaluate("() => { const t=document.getElementById('oo-tip'); return t && t.classList.contains('show') ? t.textContent : null; }")


def summarize(ts):
    from collections import Counter
    return {"n": len(ts), "clipped": sum(x["clipped"] for x in ts), "wrapped": sum(x["wrapped"] for x in ts),
            "tags": Counter(x["tag"] for x in ts).most_common(8),
            "verified": [(x["term"], x["tag"]) for x in ts if x["tag"] and x["tagClass"] and "untranslated" not in x["tagClass"] and "senses" not in x["tagClass"]],
            "senses": [x["term"] for x in ts if x["tagClass"] and "kw-senses" in x["tagClass"]]}


def ring_panel(page, lang):
    open_settings_advanced(page)
    open_adv(page, "keywords")
    sec = page.locator("section.panel:has(#ring-gaps)")
    sec.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    info = page.evaluate("""() => { const s=document.getElementById('ring-gaps').closest('section');
      const over=[...s.querySelectorAll('*')].filter(e=>e.scrollWidth>e.clientWidth+1 && getComputedStyle(e).overflowX!=='visible' ).map(e=>e.tagName+'.'+e.className);
      const r=s.getBoundingClientRect(); const kids=[...s.querySelectorAll('button,input,label,p,h2,span')].filter(e=>{const q=e.getBoundingClientRect(); return q.width && (q.right>r.right+1||q.left<r.left-1);}).map(e=>e.tagName+':'+(e.innerText||'').slice(0,30));
      return {text: s.innerText, overflowing_scroll: over, outside_box: kids, dir: document.documentElement.dir}; }""")
    shot(page, f"M-M4-ringpanel-{lang}.png", selector="section.panel:has(#ring-gaps)")
    return info


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    if page.evaluate("document.documentElement.lang") != "fr":
        set_lang(page, "fr")
        page.reload(); page.wait_for_timeout(3000)
    open_insights_explore(page)
    explore(page, "software")
    open_corpus_from_explore(page)
    for lang in ("ar", "zh"):
        # no-reload
        set_lang(page, lang)
        page.wait_for_timeout(1200)
        R[f"M4_{lang}_noreload_an"] = summarize(tags(page, "#an-keywords"))
        R[f"M4_{lang}_noreload_dir"] = page.evaluate("document.documentElement.dir")
        shot(page, f"M-M4-an-noreload-{lang}.png", selector="#an-keywords")
        goto_tab(page, "insights")
        page.click("#ins-subtabs [data-tab=explore]")
        page.wait_for_timeout(1200)
        R[f"M4_{lang}_noreload_landscape"] = summarize(tags(page, "#ins-landscape"))
        # reload
        page.reload(); page.wait_for_timeout(3500); close_guide(page)
        open_insights_explore(page)
        R[f"M4_{lang}_reload_landscape"] = summarize(tags(page, "#ins-landscape"))
        shot(page, f"M-M4-landscape-reload-{lang}.png", selector="#ins-landscape-wrap")
        explore(page, "software")
        open_corpus_from_explore(page)
        R[f"M4_{lang}_reload_an"] = summarize(tags(page, "#an-keywords"))
        R[f"M4_{lang}_hscroll"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        shot(page, f"M-M4-an-reload-{lang}.png", selector="#an-keywords")
        if lang == "zh":
            explore_ok = True
            goto_tab(page, "insights")
            explore(page, "election")
            open_corpus_from_explore(page)
            R["M6_zh_reload_senses"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .kw-sense')].map(b => b.textContent + ' | ' + (b.getAttribute('title')||b.dataset.ooTip))")
            R["M6_zh_reload_tag"] = page.evaluate("() => (document.querySelector('#an-keywords .kw-tag.kw-senses')||{}).textContent || null")
            # Analysis caveat line in zh
            R["M4_zh_an_hint"] = page.inner_text("#an-keywords .hint")[:300]
    # ring panel in fr / ar / zh / ja
    for lang in ("fr", "ar", "zh", "ja"):
        if page.evaluate("document.documentElement.lang") != lang:
            set_lang(page, lang)
        page.reload(); page.wait_for_timeout(3500); close_guide(page)
        R[f"ring_{lang}"] = ring_panel(page, lang)
    # M9 in English
    set_lang(page, "en")
    page.reload(); page.wait_for_timeout(3500); close_guide(page)
    info = ring_panel(page, "en")
    R["M9_panel_text"] = info["text"]
    R["M9_caveat"] = page.inner_text("section.panel:has(#ring-gaps) .card-caveat")
    R["M9_caveat_color"] = page.evaluate("() => getComputedStyle(document.querySelector('section.panel:has(#ring-gaps) .card-caveat')).color")
    R["M9_gap_text_before"] = page.inner_text("#ring-gaps")
    btn = page.locator("section.panel:has(#ring-gaps) button:has-text('Load from Wikidata')")
    btn.hover(); page.wait_for_timeout(700)
    R["M9_load_btn_hover"] = tip_text(page)
    page.mouse.move(5, 5)
    reqs_before = len(LOG["requests_offhost"])
    page.click("section.panel:has(#ring-gaps) button:has-text('Refresh')")
    page.wait_for_timeout(2000)
    R["M9_after_refresh_online"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    R["M9_plane_fill_after_refresh"] = page.evaluate("() => { const e=document.querySelector('#net-toggle svg [fill]:not([fill=none])'); return e ? e.getAttribute('fill') : (document.querySelector('#net-toggle svg')||{}).outerHTML?.slice(0,300); }")
    page.fill("#ring-limit", "5")
    page.click("section.panel:has(#ring-gaps) button:has-text('Load from Wikidata')")
    page.wait_for_selector("#net-consent[open]", timeout=10000)
    page.wait_for_timeout(2500)
    R["M9_consent_text"] = page.inner_text("#net-consent")
    R["M9_consent_ifaces"] = page.inner_text("#net-consent-ifaces")
    kt = page.locator("#net-consent-lanes :text('Keyword translations')").first
    if kt.count():
        kt.hover(); page.wait_for_timeout(700)
        R["M9_kt_hover"] = tip_text(page) or kt.evaluate("e => (e.closest('[title]')||e).getAttribute('title')")
    shot(page, "M-M9-consent-en.png", selector="#net-consent")
    page.click("#net-consent-cancel")
    page.wait_for_timeout(1500)
    R["M9_consent_closed"] = not page.evaluate("() => document.getElementById('net-consent').open")
    R["M9_after_cancel_online"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    R["M9_ring_status_after"] = page.inner_text("#ring-status")
    R["M9_gap_text_after"] = page.inner_text("#ring-gaps")
    R["M9_offhost_requests_during"] = LOG["requests_offhost"][reqs_before:]
    shot(page, "M-M9-after-stayoffline-en.png", selector="section.panel:has(#ring-gaps)")
    b.close()

with open(log_path("walk_e.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_e_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:12000])
