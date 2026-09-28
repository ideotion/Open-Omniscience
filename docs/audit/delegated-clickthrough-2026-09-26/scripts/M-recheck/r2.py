"""Recheck phase 2: labels, click-through of folded display terms, QID bubbling, hover, contrast,
senses, AI toast, language switch without reload."""
import json
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M-recheck")
from harness import *  # noqa

BASE = "http://127.0.0.1:8828"
R = {}
DIALOGS = []


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message})
    d.dismiss()


CONTRAST_JS = """(el) => {
  function rgb(s){ const m = s.match(/rgba?\\(([^)]+)\\)/); if(!m) return null; const p=m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; }
  function lum(c){ const f=v=>{v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4)}; return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b); }
  let bgEl = el, bg = null;
  while (bgEl) { const c = rgb(getComputedStyle(bgEl).backgroundColor); if (c && c.a > 0.5) { bg = c; break; } bgEl = bgEl.parentElement; }
  const fg = rgb(getComputedStyle(el).color);
  const L1 = lum(fg), L2 = lum(bg); const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
  return {fg: getComputedStyle(el).color, bg: getComputedStyle(bgEl).backgroundColor, bgTag: bgEl.tagName + '.' + bgEl.className, ratio: Math.round(ratio*100)/100, text: el.textContent};
}"""


def tip(page):
    return page.evaluate("() => { const t=document.getElementById('oo-tip'); return t && t.classList.contains('show') ? t.textContent : null; }")


def open_explore(page):
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1200)
    page.wait_for_selector("#ins-landscape .ls-chip", timeout=30000)


def explore(page, term):
    page.fill("#ins-term", term)
    page.press("#ins-term", "Enter")
    page.wait_for_timeout(2500)


def open_an_keywords(page):
    page.locator("#ins-trend button:has-text('⊞'), button:has-text('⊞')").first.click()
    page.wait_for_timeout(3000)
    page.click("#an-subtabs [data-tab=keywords]")
    page.wait_for_selector("#an-keywords .chip", timeout=30000)
    page.wait_for_timeout(1500)


def landscape_labels(page):
    return page.evaluate("() => [...document.querySelectorAll('#ins-landscape .ls-chip')].map(b => b.innerText.replace(/\\s+/g,' '))")


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    R["lang0"] = page.evaluate("document.documentElement.lang")
    # ---------- D1: folded display term click ----------
    open_explore(page)
    R["landscape_en"] = landscape_labels(page)
    chip = page.locator("#ins-landscape .ls-chip", has=page.locator(".kw-term", has_text="nouvelle")).first
    R["d1_chip_text"] = chip.inner_text()
    chip.click()
    page.wait_for_timeout(3000)
    R["d1_after_click_trend"] = page.inner_text("#ins-trend")[:200]
    R["d1_ins_term_value"] = page.input_value("#ins-term")
    shot(page, "Mr-D1-landscape-click-nouvelle-en.png")
    # also type the lemma for comparison
    explore(page, "nouveau")
    R["d1_explore_nouveau"] = page.inner_text("#ins-trend")[:200]
    # ---------- D9: QID click bubbles to the chip ----------
    explore(page, "semana")
    R["d9_before"] = page.inner_text("#ins-trend")[:90]
    q = page.locator("#ins-landscape .ls-chip .kw-qid").first
    R["d9_qid"] = q.inner_text()
    R["d9_qid_chip"] = q.evaluate("e => e.closest('.ls-chip').innerText.replace(/\\s+/g,' ')")
    q.click()
    page.wait_for_timeout(2500)
    R["d9_preview_open"] = page.evaluate("() => { const d=document.getElementById('link-preview'); return !!(d && d.open); }")
    R["d9_after"] = page.inner_text("#ins-trend")[:90]
    R["d9_ins_term_after"] = page.input_value("#ins-term")
    shot(page, "Mr-D9-qid-behind-en.png")
    if R["d9_preview_open"]:
        page.evaluate("() => document.getElementById('link-preview').close()")
        page.wait_for_timeout(500)
    # ---------- D8a: switch en -> fr without reload, landscape ----------
    set_lang(page, "fr")
    page.wait_for_timeout(2500)
    R["d8_landscape_fr_noreload"] = landscape_labels(page)[:10]
    shot(page, "Mr-D8-landscape-noreload-fr.png", selector="#ins-landscape-wrap")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    close_guide(page)
    open_explore(page)
    R["d8_landscape_fr_reload"] = landscape_labels(page)[:10]
    # landscape tag hover (no data-kwstat there)
    lt = page.locator("#ins-landscape .kw-tag").first
    lt.hover(); page.wait_for_timeout(700)
    R["d12_landscape_tag_hover_fr"] = tip(page)
    R["d12_landscape_tag_text"] = lt.inner_text()
    page.mouse.move(5, 5); page.wait_for_timeout(300)
    # ---------- analysis window: software (fr) ----------
    explore(page, "software")
    R["d14_resolved_line_fr"] = page.inner_text("#ins-trend")[:160]
    open_an_keywords(page)
    R["an_fr_chips"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .chip[data-kwstat]')].slice(0,12).map(c => c.innerText.replace(/\\s+/g,' '))")
    R["an_hint_fr"] = page.inner_text("#an-keywords .hint")[:300]
    vt = page.locator("#an-keywords .chip .kw-tag:not(.kw-untranslated):not(.kw-senses)").first
    R["d2_verified_tag_text"] = vt.inner_text() if vt.count() else None
    if vt.count():
        page.mouse.move(5, 5); page.wait_for_timeout(300)
        box = vt.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        samples = []
        acc = 0
        for ms in (30, 100, 300, 700, 1500):
            page.wait_for_timeout(ms - acc); acc = ms
            samples.append([ms, tip(page)])
        R["d2_an_tag_hover_timeline"] = samples
        R["d2_tag_title_now"] = vt.evaluate("e => e.getAttribute('title') || e.dataset.ooTip")
        shot(page, "Mr-D2-an-tag-hover-fr.png")
        page.mouse.move(5, 5); page.wait_for_timeout(400)
        # second hover (stats now cached)
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(600)
        R["d2_an_tag_hover_second"] = tip(page)
        page.mouse.move(5, 5); page.wait_for_timeout(300)
        # contrast
        R["d3_contrast_verified_in_chip"] = vt.evaluate(CONTRAST_JS)
        R["d3_contrast_qid_in_chip"] = page.locator("#an-keywords .chip .kw-qid").first.evaluate(CONTRAST_JS) if page.locator("#an-keywords .chip .kw-qid").count() else None
    ut = page.locator("#an-keywords .chip .kw-tag.kw-untranslated").first
    if ut.count():
        R["d3_contrast_untranslated_in_chip"] = ut.evaluate(CONTRAST_JS)
    R["d3_contrast_chip_text"] = page.locator("#an-keywords .chip .kw-term").first.evaluate(CONTRAST_JS)
    R["d3_theme"] = page.evaluate("() => [document.documentElement.dataset.theme || '(none)', matchMedia('(prefers-color-scheme: dark)').matches]")
    # focusability of tags
    R["d2_tag_tabindex"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .kw-tag')].slice(0,3).map(t => t.tabIndex)")
    shot(page, "Mr-D3-an-keywords-fr.png", selector="#an-keywords")
    # AI toast
    ai = page.locator("#an-keywords button:has-text('✦')")
    if ai.count():
        ai.first.click()
        page.wait_for_timeout(2500)
        R["d13_toasts"] = page.evaluate("() => [...document.querySelectorAll('.toast, #toast, [class*=toast]')].map(t=>t.textContent).filter(Boolean)")
        shot(page, "Mr-D13-ai-toast-fr.png")
    # ---------- D8b: fr -> zh without reload, analysis window ----------
    set_lang(page, "zh")
    page.wait_for_timeout(2500)
    R["d8_an_zh_noreload"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .chip[data-kwstat]')].filter(c => c.querySelector('.kw-tag:not(.kw-untranslated)')).slice(0,3).map(c => c.innerText.replace(/\\s+/g,' '))")
    shot(page, "Mr-D8-an-noreload-zh.png", selector="#an-keywords")
    set_lang(page, "fr")
    page.wait_for_timeout(1500)
    # ---------- D4: senses ----------
    goto_tab(page, "insights")
    explore(page, "election")
    open_an_keywords(page)
    R["d4_senses"] = page.evaluate("""() => [...document.querySelectorAll('#an-keywords .kw-sense')].map(b => ({
        label: b.textContent, title: b.getAttribute('title') || b.dataset.ooTip, pin: b.dataset.kwpin,
        insideChip: !!b.closest('.chip'), parentTag: b.parentElement.tagName + '.' + b.parentElement.className}))""")
    R["d4_senses_tag"] = page.evaluate("() => { const t=document.querySelector('#an-keywords .kw-tag.kw-senses'); if(!t) return null; const c=t.closest('.chip'); return {tag: t.textContent, chip: c ? c.outerHTML.slice(0,400) : null, chipNext: c && c.nextSibling ? (c.nextSibling.outerHTML || c.nextSibling.textContent).slice(0,400) : null}; }")
    shot(page, "Mr-D4-senses-fr.png", selector="#an-keywords")
    s = page.locator("#an-keywords .kw-sense")
    if s.count():
        before = {"hash": page.evaluate("location.hash"), "html": page.inner_html("#an-keywords"), "tabs": page.evaluate("() => localStorage.getItem('oo.an.tabs.v1')")}
        s.first.click()
        page.wait_for_timeout(2500)
        after = {"hash": page.evaluate("location.hash"), "html": page.inner_html("#an-keywords"), "tabs": page.evaluate("() => localStorage.getItem('oo.an.tabs.v1')")}
        R["d4_click"] = {"hash": [before["hash"], after["hash"]], "html_changed": before["html"] != after["html"], "tabs_changed": before["tabs"] != after["tabs"],
                         "pressed": page.evaluate("() => document.querySelectorAll('#an-keywords .kw-sense.active, #an-keywords [aria-pressed=true]').length")}
    b.close()

with open(log_path("r2.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("r2_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:12000])
