import csv
import io
import re

from lib import cells, junk_scan, session, shot, sub, tab, tip


def open_adv(page, key):
    page.click(f"details[data-adv='{key}'] > summary")
    page.wait_for_timeout(2500)


with session("L3") as (page, rec):
    downloads = []
    page.context.on("page", lambda p: p.on("download", lambda d: downloads.append(d)))
    page.on("download", lambda d: downloads.append(d))
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    # --- calendar directory: the 2-letter codes seen in L2 ---
    open_adv(page, "calendars")
    page.wait_for_selector("#agenda-feeds .cs-row", timeout=20000)
    for code in ["AX", "AI", "BQ"]:
        loc = page.locator("#agenda-feeds .cs-row summary span.muted span", has_text=re.compile(f"^{code}$")).first
        if loc.count():
            rec.obs[f"dir_{code}_tip"] = tip(page, loc)
            if code == "AX":
                shot(page, "L2-directory-AX-tip-en")
    page.click("details[data-adv='calendars'] > summary")  # fold back
    page.wait_for_timeout(500)
    # --- Sources ---
    open_adv(page, "sources")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_timeout(1500)
    rec.obs["src_meta"] = page.locator("#src-meta").inner_text()
    cc = cells(page, "#src-table tr td:nth-child(4) span")
    lc = cells(page, "#src-table tr td:nth-child(5) span")
    rec.obs["table_country_sample"] = cc[:8]
    rec.obs["table_lang_sample"] = lc[:8]
    rec.obs["table_country_bad"] = [c for c in cc if not re.fullmatch(r"[A-Z]{3}", c["text"])][:10]
    rec.obs["table_lang_bad"] = [c for c in lc if not re.fullmatch(r"[a-z]{3}", c["text"])][:10]
    if cc:
        rec.obs["table_country_tip"] = [cc[0]["text"], tip(page, page.locator("#src-table tr td:nth-child(4) span").first)]
        shot(page, "L3-table-country-tip-en")
    if lc:
        rec.obs["table_lang_tip"] = [lc[0]["text"], tip(page, page.locator("#src-table tr td:nth-child(5) span").first)]
    # Country filter
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(800)
    opts = page.eval_on_selector_all("#src-msel-country .msel-opt", "els => els.map(e => [e.querySelector('input').value, e.innerText.trim()])")
    rec.obs["country_filter_n"] = len(opts)
    rec.obs["country_filter_first10"] = opts[:10]
    rec.obs["country_filter_unlabelled"] = [o for o in opts if not re.search(r"\([A-Z]{3}\)", o[1])][:30]
    shot(page, "L3-country-filter-open-en")
    names = [re.sub(r"\s*\([A-Z]{3}\).*$", "", o[1]) for o in opts if re.search(r"\([A-Z]{3}\)", o[1])]
    rec.obs["country_filter_sorted"] = names == sorted(names, key=str.casefold)
    rec.obs["country_filter_sorted_collator"] = page.evaluate("""(names) => { const c = new Intl.Collator('en');
        const s = names.slice().sort(c.compare); const bad = []; for (let i=0;i<names.length;i++) if (names[i]!==s[i]) bad.push([i,names[i],s[i]]); return bad.slice(0,6); }""", names)
    # tick France
    fr = page.locator("#src-msel-country .msel-opt", has_text=re.compile(r"^\s*France \(FRA\)"))
    rec.obs["fr_opt"] = fr.count()
    fr.first.locator("input").check()
    page.wait_for_timeout(1500)
    page.click("#src-msel-country > summary")  # close by clicking title
    page.wait_for_timeout(800)
    rec.obs["country_filter_closed_label"] = page.locator("#src-msel-country > summary").inner_text().strip()
    ccf = page.eval_on_selector_all("#src-table tr td:nth-child(4)", "els => els.map(e => e.innerText.trim())")
    rec.obs["rows_after_FRA"] = sorted(set(ccf))
    rec.obs["src_meta_after_FRA"] = page.locator("#src-meta").inner_text()
    shot(page, "L3-country-filter-closed-en")
    # Language filter
    page.click("#src-msel-language > summary")
    page.wait_for_timeout(800)
    lopts = page.eval_on_selector_all("#src-msel-language .msel-opt", "els => els.map(e => [e.querySelector('input').value, e.innerText.trim()])")
    rec.obs["lang_filter_n"] = len(lopts)
    rec.obs["lang_filter_first12"] = lopts[:12]
    rec.obs["lang_filter_nonstandard"] = [o for o in lopts if not re.search(r"\([a-z]{3}\)", o[1])][:20]
    en = page.locator("#src-msel-language .msel-opt", has_text=re.compile(r"^\s*English \(eng\)"))
    if en.count():
        en.first.locator("input").check()
        page.wait_for_timeout(1200)
    page.click("#src-msel-language > summary")
    page.wait_for_timeout(600)
    rec.obs["lang_filter_closed_label"] = page.locator("#src-msel-language > summary").inner_text().strip()
    shot(page, "L3-filters-closed-en")
    # Clear
    page.click("button[onclick='clearSrcFilters()']")
    page.wait_for_timeout(1500)
    rec.obs["src_meta_after_clear"] = page.locator("#src-meta").inner_text()
    rec.obs["labels_after_clear"] = [page.locator("#src-msel-country > summary").inner_text(), page.locator("#src-msel-language > summary").inner_text()]
    # pcm row? search via filter language 'pcm'
    pcm = [o for o in lopts if o[0] == "pcm"]
    rec.obs["pcm_option"] = pcm
    junk_scan(page, rec, "details[data-adv='sources']", "Sources")
    # --- L4: CSV export ---
    hint = page.locator("#src-csv-hint").inner_text()
    rec.obs["csv_hint"] = hint
    page.click("button[onclick=\"window.open('/api/catalog/export.csv','_blank')\"]")
    page.wait_for_timeout(4000)
    content = None
    if downloads:
        d = downloads[0]
        path = "/tmp/claude-0/walk/L/open-omniscience-sources.csv"
        d.save_as(path)
        rec.obs["csv_suggested_filename"] = d.suggested_filename
        content = open(path, encoding="utf-8").read()
        rec.obs["csv_via"] = "browser download from the Export all (CSV) button"
    else:
        rec.notes.append("no download event caught; pages open: " + str([p.url for p in page.context.pages]))
    if content:
        rows = list(csv.reader(io.StringIO(content)))
        head = rows[0]
        rec.obs["csv_header"] = head
        ic, i3 = head.index("country"), head.index("country_iso3")
        body = rows[1:]
        rec.obs["csv_rows"] = len(body)
        rec.obs["csv_iso3_last"] = head[-1] == "country_iso3"
        fr_rows = [r for r in body if r[ic] == "fr"][:3]
        de_rows = [r for r in body if r[ic] == "de"][:3]
        rec.obs["csv_fr"] = [(r[ic], r[i3]) for r in fr_rows]
        rec.obs["csv_de"] = [(r[ic], r[i3]) for r in de_rows]
        rec.obs["csv_empty_country"] = sum(1 for r in body if not r[ic])
        rec.obs["csv_empty_country_nonempty_iso3"] = sum(1 for r in body if not r[ic] and r[i3])
        unres = {}
        for r in body:
            if r[ic] and not r[i3]:
                unres[r[ic]] = unres.get(r[ic], 0) + 1
        rec.obs["csv_country_without_iso3"] = unres
        pairs = {}
        for r in body:
            if r[ic]:
                pairs.setdefault(r[ic], set()).add(r[i3])
        rec.obs["csv_pairs_multi"] = {k: sorted(v) for k, v in pairs.items() if len(v) > 1}
        rec.obs["csv_pairs_sample"] = {k: sorted(v) for k, v in list(pairs.items())[:25]}
    # --- Statistics producers ---
    open_adv(page, "stats")
    page.wait_for_timeout(2000)
    rec.obs["stat_agencies_text_head"] = page.locator("#stat-agencies").inner_text()[:600]
    sc = cells(page, "#stat-agencies table tr td span.oo-tip-target")
    rec.obs["stat_codes_sample"] = sc[:10]
    codes = page.eval_on_selector_all("#stat-agencies table tr", "els => els.map(e => Array.from(e.children).map(c => c.innerText.trim()))")
    rec.obs["stat_rows_sample"] = codes[:12]
    if sc:
        rec.obs["stat_code_tip"] = [sc[0]["text"], tip(page, page.locator("#stat-agencies table tr td span.oo-tip-target").first)]
        shot(page, "L3-stat-producers-tip-en")
    junk_scan(page, rec, "#stat-agencies", "Statistics producers")
    print(rec.obs)
