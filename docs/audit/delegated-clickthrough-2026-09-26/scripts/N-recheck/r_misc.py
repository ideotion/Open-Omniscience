"""Recheck row N: the P3 items + a clean literal-lens leak check."""
import json, re, sys
sys.path.insert(0, "/tmp/claude-0/walk/N-recheck")
from lib import *  # noqa
from playwright.sync_api import sync_playwright

R = {}
rec = Recorder("misc")
ONLY = set(sys.argv[1:])


def want(k):
    return not ONLY or k in ONLY


def dump():
    (OUT / "R-misc.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))


def arts(ap):
    ap.click("#an-subtabs [data-tab=articles]")
    ap.wait_for_timeout(1200)


def strip_click(ap, term):
    ap.locator(".an-tab-label", has_text=re.compile(r"^\s*" + re.escape(term) + r"\s*$")).first.click()
    ap.wait_for_timeout(7000)
    arts(ap)
    ap.wait_for_timeout(1500)


def st(ap):
    return ap.evaluate("""() => ({url: location.href, label: (document.getElementById('an-query')||{}).textContent,
      xlang: ((document.getElementById('an-xlang')||{}).innerText||''),
      total: (() => { const h=document.querySelector('#an-art-total b'); return h ? h.textContent.trim() : null; })()})""")


def main():
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        rec.attach_context(ctx, "en")
        page = ctx.new_page()
        rec.attach(page, "main")
        unlock_if_locked(page)
        close_dialogs(page)
        dismiss_coach(page)

        if want("G"):
            # G. literal-lens leak, isolated from the race by a real strip click on the NEW term
            cp = open_analysis_new_tab(ctx, page, "climate")
            strip_click(cp, "climate")
            s0 = st(cp)
            if "Show only the words I typed" in s0["xlang"]:
                cp.locator("#an-xlang button", has_text="Show only the words I typed").first.click()
                cp.wait_for_timeout(6000)
            R["G_climate_literal"] = st(cp)
            page.bring_to_front()
            fp = open_analysis_new_tab(ctx, page, "climat")
            fp.wait_for_timeout(8000)
            strip_click(fp, "climat")
            R["G_climat_after_own_strip_click"] = st(fp)
            shot(fp, "N-recheck-G-climat-literal-leak-en")
            # compare with the default lens: restore climat to expanded and read the total
            btn = fp.locator("#an-xlang button", has_text="Search the concept in every language")
            if btn.count():
                btn.first.click(); fp.wait_for_timeout(6000)
            R["G_climat_expanded"] = st(fp)
            # restore climate too
            fp.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
            fp.wait_for_timeout(6000); arts(fp)
            btn = fp.locator("#an-xlang button", has_text="Search the concept in every language")
            if btn.count():
                btn.first.click(); fp.wait_for_timeout(6000)
            R["G_climate_restored"] = st(fp)
            dump()
            cp.close()
            ap = fp
        else:
            ap = open_analysis_new_tab(ctx, page, "climate")
            strip_click(ap, "climate")

        if want("H"):
            # H. mindmap concept + enlarge + literal
            ap.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
            ap.wait_for_timeout(7000)
            select_subtab(ap, "mindmap")
            ap.wait_for_timeout(2500)
            ap.locator("#an-mindmap button", has_text="Concept").first.click()
            ap.wait_for_timeout(1500)

            def centre():
                return ap.evaluate("""() => { const svg=document.querySelector('#an-mindmap svg'); if(!svg) return null;
                  const vb=svg.getAttribute('viewBox'); const r=svg.getBoundingClientRect();
                  const texts=[...svg.querySelectorAll('text')];
                  const c=texts.find(t=>t.textContent.trim().startsWith('climate'))||texts[0];
                  const cr=c?c.getBoundingClientRect():null;
                  return {viewBox: vb, svg_w: Math.round(r.width), svg_h: Math.round(r.height), centre_text: c?c.textContent.trim():null,
                          centre_h_px: cr?Math.round(cr.height):null, font_attr: c?c.getAttribute('font-size'):null,
                          arms: texts.map(t=>t.textContent.trim()).slice(0,14)}; }""")
            R["H_concept_default"] = centre()
            shot(ap, "N-recheck-H-concept-default-en")
            ap.locator("#an-mindmap button", has_text="⛶").first.click()
            ap.wait_for_timeout(1500)
            R["H_concept_enlarged"] = centre()
            shot(ap, "N-recheck-H-concept-enlarged-en")
            ap.locator("#an-mindmap button", has_text="⛶").first.click()
            ap.wait_for_timeout(800)
            # I. concept map with the literal toggle
            arts(ap)
            ap.locator("#an-xlang button", has_text="Show only the words I typed").first.click()
            ap.wait_for_timeout(8000)
            R["I_literal_state"] = st(ap)
            select_subtab(ap, "mindmap")
            ap.wait_for_timeout(2500)
            cbtn = ap.locator("#an-mindmap button", has_text="Concept")
            R["I_concept_button_present"] = cbtn.count()
            R["I_mindmap_text_literal"] = ap.eval_on_selector("#an-mindmap", "e=>e.innerText.slice(0,600)")
            R["I_concept_svg_literal"] = centre()
            shot(ap, "N-recheck-I-concept-literal-en")
            arts(ap)
            ap.locator("#an-xlang button", has_text="Search the concept in every language").first.click()
            ap.wait_for_timeout(6000)
            dump()

        if want("J"):
            # J/K/L. election block wording, limit sentence, group-by singular
            page.bring_to_front()
            ep = open_analysis_new_tab(ctx, page, "election")
            ep.wait_for_timeout(6000)
            strip_click(ep, "election")
            R["J_election_block"] = st(ep)
            ep.locator("#an-xlang button", has_text="public election").first.click()
            ep.wait_for_timeout(7000)
            R["K_pinned_block"] = st(ep)
            R["K_payload_cap_fields"] = ep.evaluate("""async () => { const r = await fetch('/api/articles?query=election&sense=election:public-election&ui_lang=en&limit=1');
               const d = await r.json(); const c = d.cross_language || d.concept || null; if (!c) return Object.keys(d);
               return {capped: c.capped, cap: c.cap, cap_caveat: c.cap_caveat, terms: (c.terms||[]).map(t=>({term:t.term, searched_forms:t.searched_forms, total_forms:t.total_forms, capped:t.capped}))}; }""")
            shot(ep, "N-recheck-K-limit-sentence-en")
            ep.locator("#an-xlang button", has_text="Show all senses").first.click()
            ep.wait_for_timeout(6000)
            # group by language
            ep.locator("#an-articles button", has_text="Group by language").first.click()
            ep.wait_for_timeout(2500)
            R["L_group_headings"] = ep.eval_on_selector_all("#an-art-list tr.an-lang-group", "e=>e.map(x=>x.innerText.trim())")
            ep.locator("#an-articles button", has_text="Interleave by date").first.click()
            ep.wait_for_timeout(1500)
            ep.close()
            dump()

        if want("M"):
            # M. zh: declined-sense sentence punctuation
            set_lang(page, "zh")
            page.wait_for_timeout(1500)
            zp = open_analysis_new_tab(ctx, page, "election", analysis_label=page.evaluate("() => OOI18N.t('Analysis')"))
            zp.wait_for_timeout(6000)
            strip_click(zp, "election")
            R["M_zh_election_block"] = st(zp)
            shot(zp, "N-recheck-M-election-zh")
            zp.close()
            # N. fr: Search page result line
            set_lang(page, "fr")
            open_palette_type(page, "climat")
            R["N_fr_palette_rows"] = palette_rows(page)[:8]
            rows = page.query_selector_all(".pal-item")
            hit = None
            for r in rows:
                t = r.inner_text().strip()
                if "Boolean" in t or "booléen" in t.lower() or "recherche" in t.lower() and "climat" in t:
                    hit = t; r.click(); break
            R["N_fr_clicked_row"] = hit
            page.wait_for_timeout(4000)
            R["N_fr_search_meta"] = text(page, "#search-meta")
            shot(page, "N-recheck-N-search-fr")
            set_lang(page, "en")
            dump()

        if want("W"):
            page.wait_for_timeout(2000)
            R["W_coach_rect"] = page.evaluate("() => { const e=document.getElementById('net-coach'); const n=document.querySelector('.nav-item[data-tab=insights]'); return {coach_show: e.classList.contains('show'), coach: e.getBoundingClientRect().toJSON(), insights: n.getBoundingClientRect().toJSON(), dir: document.documentElement.dir, lang: document.documentElement.lang, ls: localStorage.getItem('oo_net_coach_v1')} }")
            dismiss_coach(page)
            # W. watches: add in en, switch to ar, read, reload, read, delete
            page.click(".nav-item[data-tab=insights]")
            page.wait_for_timeout(2500)
            page.click("#ins-subtabs [data-tab=watches]")
            page.wait_for_timeout(2500)
            page.fill("#wt-name", "Climate")
            page.fill("#wt-query", "climate")
            page.fill("#wt-threshold", "2")
            page.fill("#wt-window", "30")
            page.click("#ins-watches button:has-text('Add watch')") if page.query_selector("#ins-watches") else page.click("button:has-text('Add watch')")
            page.wait_for_timeout(3000)
            R["W_en"] = text(page, "#wt-list")
            set_lang(page, "ar")
            page.wait_for_timeout(2000)
            page.click("#ins-subtabs [data-tab=trends]"); page.wait_for_timeout(1500)
            page.click("#ins-subtabs [data-tab=watches]"); page.wait_for_timeout(2000)
            R["W_ar_no_reload"] = text(page, "#wt-list")
            R["W_ar_name_html"] = page.eval_on_selector("#wt-list b", "e=>e.outerHTML")
            shot(page, "N-recheck-W-watch-ar-noreload")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            close_dialogs(page)
            page.click(".nav-item[data-tab=insights]"); page.wait_for_timeout(2500)
            page.click("#ins-subtabs [data-tab=watches]"); page.wait_for_timeout(3000)
            R["W_ar_after_reload"] = text(page, "#wt-list")
            shot(page, "N-recheck-W-watch-ar-reload")
            # O. insights trends hover in ar
            page.click("#ins-subtabs [data-tab=trends]"); page.wait_for_timeout(4000)
            lab = page.locator(".tb-label[data-kwstat='climate']").first
            if lab.count():
                lab.hover(); page.wait_for_timeout(2500)
                R["O_ar_hover"] = page.evaluate("() => { const e=document.getElementById('oo-tip'); return e ? e.textContent.trim() : null }")
                shot(page, "N-recheck-O-insights-hover-ar")
            else:
                R["O_ar_hover"] = "no climate row: " + str(page.eval_on_selector_all(".tb-label", "e=>e.slice(0,10).map(x=>x.textContent)"))
            # delete the watch
            page.on("dialog", lambda d: d.accept())
            page.click("#ins-subtabs [data-tab=watches]"); page.wait_for_timeout(2000)
            dl = page.locator("#wt-list button").filter(has_text=re.compile("حذف|Delete"))
            R["W_delete_buttons"] = dl.count()
            if dl.count():
                dl.first.click(); page.wait_for_timeout(2500)
            R["W_after_delete"] = text(page, "#wt-list")
            set_lang(page, "en")
            dump()

        rec.save()
        b.close()


if __name__ == "__main__":
    main()
