import re
from lib import junk_scan, session, shot, sub, tab, tip

with session("L12") as (page, rec):
    page.on("dialog", lambda d: (rec.notes.append(f"dialog: {d.type}: {d.message[:200]}"), d.accept()))
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='uninstall'] > summary")
    page.wait_for_timeout(1500)
    page.click("details[data-adv='bulletin'] > summary")
    page.wait_for_timeout(3000)
    rec.obs["gate"] = page.locator("#bulletin-gate").inner_text()
    rec.obs["controls_visible"] = page.locator("#bulletin-controls").is_visible()
    shot(page, "L12-bulletin-panel-en")
    if rec.obs["controls_visible"]:
        page.select_option("#bul-cadence", "yearly")
        rec.obs["narrate_checked"] = page.locator("#bul-narrate").is_checked()
        page.click("#bul-generate")
        page.wait_for_function("() => /Draft built|not saved|Could not build/.test(document.getElementById('bulletin-status').textContent)", timeout=180000)
        rec.obs["status"] = page.locator("#bulletin-status").inner_text()
        page.wait_for_timeout(1500)
        rec.obs["editions"] = page.eval_on_selector_all("#bulletin-list tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
        with page.context.expect_page(timeout=20000) as pi:
            page.locator("#bulletin-list button", has_text=re.compile("^Open$")).first.click()
        doc = pi.value
        doc.wait_for_load_state("domcontentloaded")
        doc.wait_for_timeout(1500)
        rec.obs["doc_url"] = doc.url
        text = doc.locator("body").inner_text()
        rec.obs["doc_head"] = text[:1500]
        rec.obs["doc_source_countries"] = re.findall(r"Source countries:[^\n]*", text)
        rec.obs["doc_languages"] = re.findall(r"Languages:[^\n]*", text)
        rec.obs["doc_by_country_heads"] = re.findall(r"[^\n]*\([A-Z]{3}\) · [^\n]*", text)[:12]
        rec.obs["doc_has_by_country"] = "By country" in text
        rec.obs["doc_lower2_in_parens"] = re.findall(r"\(([a-z]{2})\)", text)[:10]
        rec.obs["doc_country_lines_lower2"] = re.findall(r"\b(?:fr|de|us|cn|gb|es|br|ru|sa|eg|mx|pt)\b\s+\d+", text)[:10]
        doc.screenshot(path="/tmp/claude-0/walk/L/L12-bulletin-doc-en.png", full_page=False)
        with open("/tmp/claude-0/walk/L/bulletin-doc.txt", "w") as f:
            f.write(text)
        doc.close()
        # undo: Delete
        page.locator("#bulletin-list button", has_text=re.compile("^Delete$")).first.click()
        page.wait_for_timeout(2500)
        rec.obs["editions_after_delete"] = page.eval_on_selector_all("#bulletin-list tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())") or page.locator("#bulletin-list").inner_text()
    print(rec.obs)
