"""Phase B: M3, M4, M5, M6 (labels, locales, hover, QID preview, AI rung, senses)."""
import json
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa

BASE = "http://127.0.0.1:8826"
R = {}
DIALOGS = []
MODE = {"accept": False}


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message, "accepted": MODE["accept"]})
    (d.accept if MODE["accept"] else d.dismiss)()


TAGS_JS = """(sel) => {
  const host = document.querySelector(sel); if (!host) return {missing: true};
  const out = [];
  host.querySelectorAll('.kw-term').forEach(t => {
    const holder = t.closest('button, a, .chip, .ls-chip, li, div');
    const tag = t.parentElement.querySelector(':scope > .kw-tag');
    // find the tag that follows THIS term (sibling scan)
    let sib = t.nextElementSibling, tg = null;
    while (sib) { if (sib.classList.contains('kw-tag')) { tg = sib; break; } if (sib.classList.contains('kw-term')) break; sib = sib.nextElementSibling; }
    let clipped = false, overlap = false;
    if (tg) {
      const r = tg.getBoundingClientRect();
      const box = (t.closest('.ls-chip, .chip, button') || tg.parentElement).getBoundingClientRect();
      clipped = (r.right > box.right + 1) || (r.left < box.left - 1) || tg.scrollWidth > tg.clientWidth + 1;
      const tr = t.getBoundingClientRect();
      overlap = Math.abs(r.top - tr.top) > tr.height;   // wrapped under the term
    }
    out.push({term: t.textContent, tag: tg ? tg.textContent : null, tagClass: tg ? tg.className : null,
              hover: tg ? (tg.getAttribute('title') || tg.dataset.ooTip || '') : '', clipped, wrapped: overlap,
              qid: (t.parentElement.querySelector('.kw-qid')||{}).textContent || null});
  });
  return out;
}"""


def tags(page, sel):
    return page.evaluate(TAGS_JS, sel)


def open_insights_explore(page):
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1500)
    page.wait_for_selector("#ins-landscape .ls-chip", timeout=30000)


def explore(page, term):
    page.fill("#ins-term", term)
    page.click("#ins-explore button:has-text('Explore'), #ins-explore .row button >> nth=0")
    page.wait_for_timeout(2500)


def open_corpus_from_explore(page):
    page.locator("button:has-text('⊞')").first.click()
    page.wait_for_timeout(3000)
    page.click("#an-subtabs [data-tab=keywords]")
    page.wait_for_selector("#an-keywords .chip", timeout=30000)
    page.wait_for_timeout(1500)


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    # ---------------- M3 (en) ----------------
    open_insights_explore(page)
    R["M3_landscape_en"] = tags(page, "#ins-landscape")
    R["M3_landscape_cols"] = page.evaluate("() => [...document.querySelectorAll('#ins-landscape .ls-h')].map(e=>e.textContent)")
    R["M3_landscape_family_titles"] = page.evaluate("() => [...document.querySelectorAll('#ins-landscape .ls-chip')].filter(b=>/family of/.test(b.getAttribute('title')||b.dataset.ooTip||'')).map(b=>b.innerText+' || '+(b.getAttribute('title')||b.dataset.ooTip)).slice(0,6)")
    shot(page, "M-M3-landscape-en.png", selector="#ins-landscape-wrap")
    R["junk_landscape_en"] = junk_in(page, "#ins-landscape")
    # Families (Kind = all)
    page.click("#ins-subtabs [data-tab=families]")
    page.wait_for_timeout(1500)
    try:
        kind = page.locator("#fam-kind")
        R["fam_kind_options"] = kind.evaluate("s => [...s.options].map(o=>o.value+':'+o.text)")
        kind.select_option("non_term") if "non_term" in json.dumps(R["fam_kind_options"]) else None
        page.wait_for_timeout(1500)
    except Exception as e:
        R["fam_kind_err"] = str(e)[:200]
    R["M3_families_text"] = page.inner_text("#fam-list")[:400]
    R["M3_families_tags"] = tags(page, "#fam-list")
    # click a tagged foreign keyword in the landscape
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1000)
    foreign = page.locator("#ins-landscape .ls-chip:has(.kw-untranslated)").first
    R["M3_click_term"] = foreign.inner_text()
    foreign.click()
    page.wait_for_timeout(3000)
    R["M3_after_click_trend"] = page.inner_text("#ins-trend")[:300]
    shot(page, "M-M3-landscape-click-en.png")
    # Analysis window: software -> Corpus -> Keywords
    explore(page, "software")
    R["M3_resolved_line_en"] = page.inner_text("#ins-trend")[:200]
    open_corpus_from_explore(page)
    R["M3_an_kw_en"] = tags(page, "#an-keywords")
    shot(page, "M-M3-an-keywords-en.png", selector="#an-keywords")
    R["junk_an_en"] = junk_in(page, "#an-keywords")
    # ---------------- M4: switch fr WITHOUT reload ----------------
    set_lang(page, "fr")
    R["M4_fr_noreload_an"] = tags(page, "#an-keywords")
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1500)
    R["M4_fr_noreload_landscape"] = tags(page, "#ins-landscape")
    shot(page, "M-M4-landscape-noreload-fr.png", selector="#ins-landscape-wrap")
    # settings famc-list (curation)
    open_settings_advanced(page)
    open_adv(page, "keywords")
    R["M3_famc_text"] = page.inner_text("#famc-list")[:300] if page.locator("#famc-list").count() else None
    ctx.storage_state(path=log_path("state.json"))
    b.close()

with open(log_path("walk_b.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_b_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:9000])
