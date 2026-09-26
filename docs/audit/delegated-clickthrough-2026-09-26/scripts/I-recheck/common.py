"""Shared helpers for the Row I walk (scratch; not part of the repo)."""
import json, os, re, subprocess, time

W = "/tmp/claude-0/walk/I-recheck"
SHOTS = W
PORT = 8816
BASE = f"http://127.0.0.1:{PORT}"
PASS = "walk-pass-2026"          # the throwaway's DB passphrase
BPASS = "walk-backup-2026"       # the backups' passphrase
TGT = f"{W}/tgt"
LOG = open(f"{W}/events.jsonl", "a")
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


def ev(kind, **kw):
    kw.update(kind=kind, t=round(time.time(), 3))
    LOG.write(json.dumps(kw, ensure_ascii=False) + "\n"); LOG.flush()
    print(kind, json.dumps({k: v for k, v in kw.items() if k not in ("kind", "t")}, ensure_ascii=False)[:600], flush=True)


def listener_pid(port=PORT):
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
    return r.stdout.strip()


def start_server(ddir=TGT, port=PORT):
    out = subprocess.run([f"{W}/srv.sh", ddir, str(port)], capture_output=True, text=True).stdout
    pid = out.strip().splitlines()[-1] if out.strip() else ""
    ev("server_start", port=port, pid=pid, ddir=ddir)
    return pid


def wire(page, tag):
    page.on("pageerror", lambda e: ev("pageerror", page=tag, err=str(e)[:400]))
    page.on("console", lambda m: ev("console_error", page=tag, text=m.text[:400]) if m.type == "error" else None)
    page.on("response", lambda r: ev("http_error", page=tag, url=r.url, status=r.status) if r.status >= 400 else None)


DIALOG_MODE = {"accept": set()}   # substrings of confirm texts we accept


def on_dialog(d):
    msg = d.message
    ok = any(s in msg for s in DIALOG_MODE["accept"])
    ev("js_dialog", type=d.type, message=msg[:300], action="accept" if ok else "dismiss")
    (d.accept() if ok else d.dismiss())


def unlock_if_needed(page):
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if "/unlock" in page.url:
        page.wait_for_selector("#view-unlock:not(.hidden)", timeout=30000)
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*/(#.*)?$"), timeout=60000)
        page.wait_for_timeout(2500)
    close_wizard(page)


def close_wizard(page):
    for _ in range(3):
        if page.evaluate("() => { const d = document.getElementById('wiki-wizard'); return !!(d && d.open); }"):
            ev("wiki_wizard_open_closing")
            try:
                page.click("#wiki-wizard-cancel", timeout=3000)
            except Exception:
                page.evaluate("() => document.getElementById('wiki-wizard').close()")
            page.wait_for_timeout(400)
        if page.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
            try:
                page.click("#gw-close", timeout=3000)
            except Exception:
                page.evaluate("() => document.getElementById('guide-wizard').close()")
            page.wait_for_timeout(400)
        else:
            break


def goto_data(page):
    page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_timeout(500)
    page.click("#set-subtabs button[data-tab='data']")
    page.wait_for_timeout(1200)


def open_import(page):
    page.click("#set-data button[onclick='openUnifiedImport()']")
    page.wait_for_selector("#ux-import[open]", timeout=5000)
    page.wait_for_timeout(1500)


def close_import(page):
    page.click("#ux-import .row button.secondary:has-text('Close'), #ux-import button[onclick*=\"ux-import').close\"]")
    page.wait_for_timeout(300)


SNAP_JS = r"""() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.innerText.trim() : null; };
  const dlg = q('#ux-import');
  const vis = (e) => { if (!e) return false; const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const rowsOf = (host) => host ? Array.from(host.children).map(el => {
    const dot = el.querySelector('span[style*="border-radius:50%"]');
    return { key: el.getAttribute('data-row-key'), text: el.innerText.trim(), dot: dot ? (dot.getAttribute('style').match(/background:([^;]+)/) || [])[1] : null };
  }) : [];
  const bars = Array.from(document.querySelectorAll('progress')).filter(vis).map(p => p.id || '(anon)');
  return {
    open: !!(dlg && dlg.open),
    last: txt('#ux-imp-last'),
    status: txt('#ux-imp-status'),
    progress: txt('#ux-imp-progress'),
    note: txt('#ux-imp-queue-note'),
    stages: rowsOf(q('#ux-imp-stages')),
    statements: txt('#ux-imp-statements'),
    rows: rowsOf(q('#ux-imp-queue-rows')),
    queue_visible: vis(q('#ux-imp-queue')),
    summary: (txt('#ux-imp-summary') || '').slice(0, 600),
    checkpoint: txt('#ux-imp-checkpoint'),
    bars,
    details: dlg ? (dlg.querySelectorAll('details').length + ' details; showdetails=' + /Show details/i.test(dlg.innerText)) : null,
    toasts: Array.from(document.querySelectorAll('#toast > *')).map(n => n.innerText.trim()),
    stop_visible: vis(q('#ux-imp-stop')), bg_visible: vis(q('#ux-imp-bg')),
    lang: document.documentElement.lang, dir: document.documentElement.dir,
  };
}"""


def snap(page):
    return page.evaluate(SNAP_JS)


def set_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_timeout(300)
    page.click(f"#lang-menu [data-lang={code}]")
    page.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=10000)
    page.wait_for_timeout(1200)


def junk_scan(page, sel, tag):
    t = page.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : ''; }", sel)
    hits = sorted(set(m.group(0) for m in JUNK.finditer(t or "")))
    if hits:
        ev("junk", where=tag, sel=sel, hits=hits)
    return hits


def api(path):
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(BASE + path, timeout=30) as r:
        return json.loads(r.read())
