import json
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = br.new_page(viewport={"width": 1440, "height": 950})
    page.goto("http://127.0.0.1:8821/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    out = page.evaluate("""() => {
      const t = OOI18N.t;
      const v = (p) => _uxProgressView('volumes', {mode: 'backup', state: 'running', progress: p}, t).text;
      return {
        verifying: v({phase: 'verifying', volumes_verified: 1, volumes_total: 3}),
        parity: v({phase: 'parity', volumes_written: 3, bytes_written: 17600000}),
        restore_verifying: _uxProgressView('volumes', {mode: 'restore', progress: {phase: 'verifying'}}, t).text,
        verify_label_exists: t('Verifying volumes…'),
      };
    }""")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("results/d6_mapping.json", "w"), ensure_ascii=False, indent=1)
    br.close()
