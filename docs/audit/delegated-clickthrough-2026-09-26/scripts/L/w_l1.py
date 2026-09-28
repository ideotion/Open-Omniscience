import re
import sys

from lib import cells, junk_scan, session, shot, sub, tab, tip

with session("L1") as (page, rec):
    tab(page, "law")
    sub(page, "gov-subtabs", "law")
    page.wait_for_timeout(1500)
    # Legal changes (seeded fr/uk/eu revisions)
    ch = cells(page, "#law-changes .panel > b > span")
    rec.obs["changes_codes"] = ch
    tips = {}
    for i, c in enumerate(ch[:4]):
        tips[c["text"] + f"#{i}"] = tip(page, page.locator("#law-changes .panel > b > span").nth(i))
    rec.obs["changes_tips"] = tips
    shot(page, "L1-changes-en")
    # Re-seed catalog (local, no network)
    page.click("button[onclick='lawSeed()']")
    try:
        page.wait_for_selector("text=/Seeded \\d+ sources/", timeout=20000)
        rec.obs["seed_toast"] = page.locator("text=/Seeded \\d+ sources/").first.inner_text()
    except Exception as e:  # noqa: BLE001
        rec.obs["seed_toast"] = f"NOT SEEN: {e}"
    page.wait_for_timeout(3000)
    rows = cells(page, "#law-docs tbody tr td:first-child span")
    raw_td = page.eval_on_selector_all("#law-docs tbody tr td:first-child", "els => els.map(e => e.innerText.trim())")
    rec.obs["docs_n"] = len(raw_td)
    rec.obs["docs_codes_set"] = sorted(set(raw_td))
    rec.obs["docs_bad"] = [t for t in raw_td if not re.fullmatch(r"[A-Z]{3}", t)]
    per_code = {}
    for r in rows:
        per_code.setdefault(r["text"], r)
    rec.obs["docs_per_code_attr"] = per_code
    tipd = {}
    for code in ["GBR", "DEU", "EUU", "INT", "FRA", "CAN", "USA"]:
        loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile(f"^{code}$")).first
        if loc.count():
            tipd[code] = tip(page, loc)
            if code == "GBR":
                shot(page, "L1-tip-GBR-en")
            if code == "EUU":
                shot(page, "L1-tip-EUU-en")
        else:
            tipd[code] = "ABSENT"
    rec.obs["docs_tips"] = tipd
    # underline check
    rec.obs["docs_first_style"] = rows[:3]
    junk_scan(page, rec, "#tab-law", "Governments>Law")
    print(rec.obs)
