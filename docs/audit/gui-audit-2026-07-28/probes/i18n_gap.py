"""TRUE i18n gap, v2 -- corrected after reading the engine AND toast().

CORRECTION to a first-pass classification (recorded so the audit does not
repeat it): toast() does `n.textContent = msg` on a node appended to the
plain `#toast` div, which is inside <body>, is not SKIP-listed (DIV) and is
not marked data-i18n-dyn -- so the MutationObserver DOES reach it and DOES
translate it on the next ~120 ms tick, provided a key exists. A bare
toast("...") whose key exists is therefore a brief ENGLISH FLASH, not a
permanent translation gap.

The only strings the observer can NEVER reach are the ones that never
become DOM: window.confirm()/alert() arguments (native browser chrome).

So the honest classes are:
  A  no locale key at all, anywhere DOM-reachable  -> PERMANENTLY English x12
  B  native confirm()/alert() argument            -> unreachable by the walker
  C  key exists, bare literal at the call site    -> ~120 ms English flash
"""
import re, json, pathlib, collections

ROOT = pathlib.Path("src/static")
KEYS = {k for k in json.loads((ROOT / "locales/en.json").read_text(encoding="utf-8")) if k != "_meta"}
norm = lambda s: re.sub(r"\s+", " ", s.strip())

FILES = ["app.js", "reader.js", "index.html", "taskmanager.html",
         "unlock.html", "investigate.html"]
PATTERNS = [
    ("th",          re.compile(r'<th[^>]*>([A-Za-z][^<{`$]{1,80})</th>'),         "dom"),
    ("button",      re.compile(r'<button[^>]*>([A-Za-z][^<{`$]{1,80})</button>'), "dom"),
    ("placeholder", re.compile(r'placeholder="([A-Za-z][^"{`$]{2,90})"'),         "dom"),
    ("title_attr",  re.compile(r'\btitle="([A-Za-z][^"{`$]{2,120})"'),            "dom"),
    ("aria_label",  re.compile(r'aria-label="([A-Za-z][^"{`$]{2,90})"'),          "dom"),
    ("textContent", re.compile(r'\.textContent\s*=\s*"([^"]{3,120})"'),           "dom"),
    ("toast",       re.compile(r'\btoast\(\s*"([^"]{3,140})"'),                   "dom"),
    ("confirm",     re.compile(r'\bconfirm\(\s*"([^"]{3,200})"'),                 "native"),
    ("alert",       re.compile(r'\balert\(\s*"([^"]{3,200})"'),                   "native"),
]

rows = []
for name in FILES:
    p = ROOT / name
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    for kind, rx, reach in PATTERNS:
        for m in rx.finditer(text):
            k = norm(m.group(1))
            if len(k) < 3 or not re.search(r"[A-Za-z]{3}", k):
                continue
            if k.startswith(("http", "/api", "data:", "var(", "#")):
                continue
            keyed = k in KEYS
            if reach == "dom" and keyed:
                cls = "C_flash"
            elif reach == "native":
                cls = "B_native"
            else:
                cls = "A_no_key"
            rows.append({"file": name, "line": text.count("\n", 0, m.start()) + 1,
                         "kind": kind, "cls": cls, "keyed": keyed, "text": k})

A = [r for r in rows if r["cls"] == "A_no_key"]
B = [r for r in rows if r["cls"] == "B_native"]
C = [r for r in rows if r["cls"] == "C_flash"]
print(f"A  PERMANENTLY English (no locale key)      : {len(A):4d}   ({len({r['text'] for r in A})} distinct)")
print(f"B  native confirm()/alert() (unreachable)   : {len(B):4d}   ({len({r['text'] for r in B})} distinct)")
print(f"C  keyed but bare -> ~120ms English flash   : {len(C):4d}")
print()
print("=== A: permanently-English, by file ===")
for f, n in collections.Counter(r["file"] for r in A).most_common():
    print(f"  {n:4d}  {f}")
print("\n=== A: permanently-English, by shape ===")
for f, n in collections.Counter(r["kind"] for r in A).most_common():
    print(f"  {n:4d}  {f}")

out = pathlib.Path(__file__).with_name("i18n_classified.json")
out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"\nfull classification -> {out}")
