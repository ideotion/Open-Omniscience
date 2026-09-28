"""Phase H: tag contrast on analysis chips vs landscape chips (en), bulletin review keyword tags."""
import json
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa
from walk_b_lib import tags, open_insights_explore, explore, open_corpus_from_explore  # noqa

BASE = "http://127.0.0.1:8826"
R = {}
CONTRAST = """(sel) => {
  function rgb(s){ const m=s.match(/[\\d.]+/g).map(Number); return m; }
  function lum(c){ const a=c.slice(0,3).map(v=>{v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4);}); return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2]; }
  function bg(e){ while(e){ const c=getComputedStyle(e).backgroundColor; const v=rgb(c); if(v.length<4 || v[3]>0.5) { if (!(v.length>=4 && v[3]===0)) return v; } e=e.parentElement; } return [255,255,255]; }
  const t=document.querySelector(sel); if(!t) return null;
  const fg=rgb(getComputedStyle(t).color); const b=bg(t);
  const L1=lum(fg), L2=lum(b); const r=(Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
  return {fg: getComputedStyle(t).color, bg: 'rgb('+b.slice(0,3).join(',')+')', ratio: Math.round(r*100)/100, text: t.textContent};
}"""

with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page(); attach(page, "main")
    page.on("dialog", lambda d: d.dismiss())
    unlock_if_needed(page, BASE); close_guide(page)
    if page.evaluate("document.documentElement.lang") != "en":
        set_lang(page, "en"); page.reload(); page.wait_for_timeout(3000); close_guide(page)
    R["theme"] = page.evaluate("document.documentElement.getAttribute('data-theme')")
    open_insights_explore(page)
    R["landscape_untranslated_tag"] = page.evaluate(CONTRAST, "#ins-landscape .kw-tag.kw-untranslated")
    explore(page, "election")
    open_corpus_from_explore(page)
    R["an_untranslated_tag"] = page.evaluate(CONTRAST, "#an-keywords .chip .kw-tag.kw-untranslated")
    R["an_senses_tag"] = page.evaluate(CONTRAST, "#an-keywords .chip .kw-tag.kw-senses")
    R["an_chip_term"] = page.evaluate(CONTRAST, "#an-keywords .chip .kw-term")
    shot(page, "M-M3-an-election-contrast-en.png", selector="#an-keywords .chip >> nth=5")
    # bulletin review: open the latest edition and look for keyword tags
    open_settings_advanced(page)
    open_adv(page, "uninstall")
    open_adv(page, "bulletin")
    page.wait_for_timeout(2500)
    rev = page.locator("#bulletin-list button:has-text('Review')").first
    if rev.count():
        rev.click(); page.wait_for_timeout(3000)
        R["bulletin_review_text"] = page.inner_text("#bulletin-review")[:1500]
        R["bulletin_review_tags"] = page.evaluate("() => document.querySelectorAll('#bulletin-review .kw-tag').length")
        shot(page, "M-M8h-bulletin-review-en.png", selector="#bulletin-review")
    op = page.locator("#bulletin-list :text('Open')").first
    if op.count():
        with ctx.expect_page(timeout=8000) as pi:
            op.click()
        bp = pi.value; bp.wait_for_timeout(2500)
        R["bulletin_doc_text"] = bp.inner_text("body")[:1500]
        R["bulletin_doc_tags"] = bp.evaluate("() => document.querySelectorAll('.kw-tag').length")
        bp.screenshot(path=log_path("M-M8h-bulletin-doc-en.png"))
        bp.close()
    b.close()

with open(log_path("walk_h.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_h_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:5000])
