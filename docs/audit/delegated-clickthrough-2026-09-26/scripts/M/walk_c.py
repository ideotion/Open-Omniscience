"""Phase C: M4 (reload + ar/zh no-reload), M5 (fr hover, keyboard, QID, AI), M6 (senses)."""
import json
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa
from walk_b_lib import tags, open_insights_explore, explore, open_corpus_from_explore  # noqa

BASE = "http://127.0.0.1:8826"
R = {}
DIALOGS = []
MODE = {"accept": False}


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message, "accepted": MODE["accept"]})
    (d.accept if MODE["accept"] else d.dismiss)()


def tip_text(page):
    return page.evaluate("() => { const t=document.getElementById('oo-tip'); return t && t.classList.contains('show') ? t.textContent : null; }")


def an_tab_count(page):
    return page.evaluate("() => document.querySelectorAll('#an-tabstrip [data-an-id], #an-tabstrip .an-tab, #an-tabstrip > *').length")


def surfaces(page, lang, label):
    """Landscape + analysis keywords for 'software', current state."""
    out = {}
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1500)
    out["landscape"] = tags(page, "#ins-landscape")
    shot(page, f"M-M4-landscape-{label}-{lang}.png", selector="#ins-landscape-wrap")
    return out


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    R["lang_at_start"] = page.evaluate("document.documentElement.lang")
    if R["lang_at_start"] != "fr":
        set_lang(page, "fr")
    # ------------- M4 fr after reload -------------
    page.reload()
    page.wait_for_timeout(3000)
    close_guide(page)
    R["fr_reload_lang"] = page.evaluate("document.documentElement.lang")
    open_insights_explore(page)
    R["M4_fr_reload_landscape"] = tags(page, "#ins-landscape")
    shot(page, "M-M4-landscape-reload-fr.png", selector="#ins-landscape-wrap")
    explore(page, "software")
    R["M5_resolved_fr"] = page.inner_text("#ins-trend")[:160]
    open_corpus_from_explore(page)
    R["M4_fr_reload_an"] = tags(page, "#an-keywords")
    shot(page, "M-M5-an-keywords-fr.png", selector="#an-keywords")
    R["an_hint_fr"] = page.inner_text("#an-keywords .hint")[:400]
    # ------------- M5(a) hover -------------
    ver = page.locator("#an-keywords .kw-tag:not(.kw-untranslated):not(.kw-senses)").first
    R["M5_has_verified_chip"] = ver.count() > 0
    if ver.count():
        ver.hover()
        page.wait_for_timeout(600)
        R["M5a_verified_hover"] = tip_text(page)
        shot(page, "M-M5a-hover-verified-fr.png")
    unt = page.locator("#an-keywords .kw-tag.kw-untranslated").first
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    unt.hover()
    page.wait_for_timeout(600)
    R["M5a_untranslated_hover"] = tip_text(page)
    R["M5a_untranslated_term"] = unt.evaluate("e => e.previousElementSibling ? e.previousElementSibling.textContent : null")
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    # keyboard focus: Tab until a chip in #an-keywords is focused
    first_chip = page.locator("#an-keywords .chip").first
    first_chip.evaluate("e => e.previousElementSibling ? null : null")
    page.locator("#an-subtabs [data-tab=keywords]").focus()
    focus_log = []
    for i in range(60):
        page.keyboard.press("Tab")
        page.wait_for_timeout(120)
        info = page.evaluate("() => { const a=document.activeElement; return {tag:a.tagName, cls:a.className, inAn: !!a.closest('#an-keywords'), txt:(a.innerText||'').slice(0,60)}; }")
        if info["inAn"] and "chip" in (info["cls"] or ""):
            page.wait_for_timeout(700)
            info["tip"] = tip_text(page)
            focus_log.append(info)
            if len(focus_log) >= 2:
                break
    R["M5a_keyboard"] = focus_log
    R["M5a_tag_focusable"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .kw-tag')].some(t => t.tabIndex >= 0)")
    page.keyboard.press("Escape")
    # ------------- M5(b) QID -------------
    before_tabs = an_tab_count(page)
    before_query = page.inner_text("#an-query")
    qid = page.locator("#an-keywords .kw-qid").first
    R["M5b_has_qid"] = qid.count() > 0
    if qid.count():
        R["M5b_qid_text"] = qid.inner_text()
        qid.click()
        page.wait_for_timeout(2000)
        R["M5b_preview_open"] = page.evaluate("() => document.getElementById('link-preview').open")
        R["M5b_preview_text"] = page.inner_text("#link-preview")[:800] if R["M5b_preview_open"] else None
        shot(page, "M-M5b-linkpreview-fr.png")
        out = page.locator("#lp-out a").first
        R["M5b_out_link_text"] = out.inner_text() if out.count() else None
        R["M5b_out_link_href"] = out.get_attribute("href") if out.count() else None
        DIALOGS.clear()
        MODE["accept"] = False
        pages_before = len(ctx.pages)
        if out.count():
            out.click()
            page.wait_for_timeout(1200)
        R["M5b_confirm_dialogs"] = list(DIALOGS)
        R["M5b_new_pages_after_cancel"] = len(ctx.pages) - pages_before
        R["M5b_net_after"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
        page.click("#link-preview button.secondary")
        page.wait_for_timeout(1500)
        R["M5b_an_tabs_before_after"] = [before_tabs, an_tab_count(page)]
        R["M5b_an_query_before_after"] = [before_query, page.inner_text("#an-query")]
        R["M5b_active_tab"] = page.evaluate("() => location.hash")
        shot(page, "M-M5b-after-close-fr.png")
    # ------------- M5(c) AI translate -------------
    goto_tab(page, "insights")
    explore(page, "software")
    open_corpus_from_explore(page)
    btn = page.locator("#an-keywords button:has-text('✦')")
    R["M5c_btn_present"] = btn.count() > 0
    if btn.count():
        R["M5c_btn_text"] = btn.inner_text()
        btn.click()
        page.wait_for_timeout(4000)
        R["M5c_toasts"] = page.evaluate("() => [...document.querySelectorAll('.toast, #toast, [role=alert], .toasts > *')].map(e=>e.innerText).filter(Boolean)")
        R["M5c_tentative_tags"] = page.evaluate("() => document.querySelectorAll('#an-keywords .kw-tentative').length")
        R["M5c_btn_after"] = page.locator("#an-keywords button:has-text('✦')").count()
        shot(page, "M-M5c-ai-fr.png")
    # ------------- M6 senses -------------
    goto_tab(page, "insights")
    explore(page, "election")
    R["M6_resolved"] = page.inner_text("#ins-trend")[:160]
    open_corpus_from_explore(page)
    R["M6_an_tags"] = [x for x in tags(page, "#an-keywords") if x["tag"] and ("sens" in x["tag"].lower())]
    R["M6_any_senses_dom"] = page.evaluate("() => document.querySelectorAll('.kw-senses, .kw-sense').length")
    R["M6_landscape_senses"] = page.evaluate("() => document.querySelectorAll('#ins-landscape .kw-sense').length")
    R["M6_election_chip"] = page.evaluate("() => { const c=[...document.querySelectorAll('#an-keywords .chip')].find(b=>/^election/i.test(b.innerText.trim())); return c ? c.outerHTML.slice(0,800) : null; }")
    shot(page, "M-M6-an-election-fr.png", selector="#an-keywords")
    b.close()

with open(log_path("walk_c.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_c_log.json")
