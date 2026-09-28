"""Phase D: M5a retry (hover timing), M5b chip-behind-QID probe (landscape), M6 sense buttons."""
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


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    if page.evaluate("document.documentElement.lang") != "fr":
        set_lang(page, "fr")
    open_insights_explore(page)
    # --- M5a in the landscape (no data-kwstat on those chips) ---
    vt = page.locator("#ins-landscape .kw-tag:not(.kw-untranslated)").first
    vt.hover()
    page.wait_for_timeout(700)
    R["M5a_landscape_verified_tag_hover"] = tip_text(page)
    shot(page, "M-M5a-hover-landscape-verified-fr.png")
    page.mouse.move(5, 5); page.wait_for_timeout(300)
    ut = page.locator("#ins-landscape .kw-tag.kw-untranslated").first
    ut.hover(); page.wait_for_timeout(700)
    R["M5a_landscape_untranslated_tag_hover"] = tip_text(page)
    page.mouse.move(5, 5); page.wait_for_timeout(300)
    # --- M5b: explore another term first, then click the QID inside the landscape chip ---
    explore(page, "semana")
    R["M5b_trend_before"] = page.inner_text("#ins-trend")[:80]
    q = page.locator("#ins-landscape .kw-qid").first
    R["M5b_landscape_qid"] = q.inner_text()
    q.click()
    page.wait_for_timeout(2500)
    R["M5b_preview_open"] = page.evaluate("() => document.getElementById('link-preview').open")
    R["M5b_trend_after_qid_click"] = page.inner_text("#ins-trend")[:80]
    shot(page, "M-M5b-landscape-qid-behind-fr.png")
    if R["M5b_preview_open"]:
        page.click("#link-preview button.secondary")
        page.wait_for_timeout(800)
    # --- M5a in the analysis window: timing of the bubble on the tag ---
    explore(page, "software")
    open_corpus_from_explore(page)
    page.mouse.move(5, 5); page.wait_for_timeout(300)
    vt = page.locator("#an-keywords .kw-tag:not(.kw-untranslated):not(.kw-senses)").first
    box = vt.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    samples = []
    for ms in (20, 60, 150, 400, 900):
        page.wait_for_timeout(ms if not samples else ms - [20, 60, 150, 400, 900][len(samples) - 1])
        samples.append([ms, tip_text(page)])
    R["M5a_an_verified_tag_hover_timeline"] = samples
    R["M5a_an_verified_tag_title_attr_now"] = vt.evaluate("e => e.getAttribute('title') || e.dataset.ooTip")
    page.mouse.move(5, 5); page.wait_for_timeout(300)
    # --- M6 senses ---
    goto_tab(page, "insights")
    explore(page, "election")
    open_corpus_from_explore(page)
    R["M6_senses_buttons"] = page.evaluate("""() => [...document.querySelectorAll('#an-keywords .kw-sense')].map(b => ({
        label: b.textContent, title: b.getAttribute('title') || b.dataset.ooTip, pin: b.dataset.kwpin,
        insideChip: !!b.closest('.chip'), prev: (b.parentElement.previousElementSibling||{}).outerHTML ? b.parentElement.previousElementSibling.outerHTML.slice(0,160) : null,
        parentNext: b.parentElement.nextSibling ? (b.parentElement.nextSibling.textContent||'').slice(0,40) : null}))""")
    R["M6_senses_wrapper_outer"] = page.evaluate("() => { const s=document.querySelector('#an-keywords .kw-sense'); if(!s) return null; const w=s.parentElement; return w.outerHTML.slice(0,600) + ' ||NEXT|| ' + (w.nextElementSibling ? w.nextElementSibling.outerHTML.slice(0,200) : (w.nextSibling ? w.nextSibling.textContent : '')); }")
    senses = page.locator("#an-keywords .kw-sense")
    hov = []
    for i in range(senses.count()):
        senses.nth(i).hover(); page.wait_for_timeout(600)
        hov.append(tip_text(page))
    R["M6_senses_hover"] = hov
    stag = page.locator("#an-keywords .kw-tag.kw-senses").first
    if stag.count():
        stag.hover(); page.wait_for_timeout(700)
        R["M6_senses_tag_hover"] = tip_text(page)
    shot(page, "M-M6-senses-fr.png", selector="#an-keywords")
    if senses.count():
        before = {"hash": page.evaluate("location.hash"), "query": page.inner_text("#an-query"),
                  "html": page.inner_html("#an-keywords")[:3000]}
        senses.first.click()
        page.wait_for_timeout(2500)
        after = {"hash": page.evaluate("location.hash"), "query": page.inner_text("#an-query"),
                 "html": page.inner_html("#an-keywords")[:3000]}
        R["M6_click_effect"] = {"hash": [before["hash"], after["hash"]], "query": [before["query"], after["query"]],
                                "kw_html_changed": before["html"] != after["html"],
                                "pinned_marker": page.evaluate("() => document.querySelectorAll('#an-keywords .kw-sense.active, #an-keywords [aria-pressed=true]').length")}
    # zh sense labels (read after switching)
    set_lang(page, "zh")
    page.wait_for_timeout(1500)
    R["M6_zh_noreload_senses"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .kw-sense')].map(b => b.textContent)")
    R["M6_zh_noreload_tag"] = page.evaluate("() => (document.querySelector('#an-keywords .kw-tag.kw-senses')||{}).textContent || null")
    b.close()

with open(log_path("walk_d.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_d_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:6000])
