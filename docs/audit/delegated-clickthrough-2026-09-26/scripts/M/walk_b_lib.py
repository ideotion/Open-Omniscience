import json
import sys
sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa

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


