import re
from lib import junk_scan, session, shot, sub, tab, tip

with session("L11b") as (page, rec):
    tab(page, "law")
    sub(page, "gov-subtabs", "groups")
    page.wait_for_timeout(2500)
    page.click("#gov-lens button[data-lens='computed']")
    page.wait_for_timeout(2500)
    go = page.eval_on_selector_all("#gov-grp-pick option", "els => els.map(e => [e.value, e.textContent.trim()])")
    rec.obs["grp_all_opts"] = [x[1] for x in go]
    pick = next((v for v, l in go if l == "Europe"), None)
    page.select_option("#gov-grp-pick", pick)
    page.wait_for_timeout(1000)
    page.select_option("#gov-grp-ind", "SP.POP.TOTL")
    page.wait_for_timeout(4000)
    body = page.locator("#gov-grp-body").inner_text()
    rec.obs["grp_body"] = body[:2500]
    rec.obs["range_lines"] = re.findall(r"Range across[^\n]*", body)
    rec.obs["missing_lines"] = re.findall(r"[Mm]issing[^\n]*", body)[:3]
    rec.obs["suspended_lines"] = re.findall(r"Suspended[^\n]*", body)[:3]
    rec.obs["titled"] = page.eval_on_selector_all("#gov-grp-body [title]", "els => els.slice(0,12).map(e => [e.innerText.trim().slice(0,40), e.getAttribute('title').slice(0,80)])")
    rec.obs["lower2"] = sorted(set(re.findall(r"\b[a-z]{2}\b", body)))
    page.locator("#gov-grp-body").scroll_into_view_if_needed()
    shot(page, "L11-groups-computed-europe-en")
    junk_scan(page, rec, "#gov-groups", "Gov>Groups computed")
    print(rec.obs)
