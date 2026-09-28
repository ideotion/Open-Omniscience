import re
from lib import close_guide, session, set_lang, shot, sub, tab, tip

with session("Lfr-extra", lang="fr") as (page, rec):
    rec.obs["lang"] = page.evaluate("() => document.documentElement.lang")
    tab(page, "library"); sub(page, "library-views", "coverage")
    page.wait_for_selector("#coverage-table tr td", timeout=60000); page.wait_for_timeout(2000)
    reg = page.locator("#coverage-regions").inner_text()
    rec.obs["top_country_fr"] = re.findall(r"[^\n]*(?:Top country|Pays principal)[^\n]*", reg)
    rec.obs["gaps_head_fr"] = page.locator("#coverage-gaps").inner_text()[:60]
    rec.obs["table_head_fr"] = page.eval_on_selector_all("#coverage-table tr:first-child th", "els => els.map(e => e.innerText)")
    first = page.locator("#coverage-table tr td strong > span").first
    rec.obs["none_tip_fr"] = [first.inner_text(), tip(page, first)]
    tab(page, "home")
    page.wait_for_timeout(4000)
    card = page.locator("#tab-home :text('Law changed')").first
    if card.count():
        card.scroll_into_view_if_needed()
        shot(page, "L13-home-law-card-fr")
        rec.obs["home_card_text"] = card.inner_text()
    print(rec.obs)
