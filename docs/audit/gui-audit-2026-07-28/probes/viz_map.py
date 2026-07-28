"""Which render functions emit a TABLE but never a chart?

A surface that builds <table>/<tr> markup and never calls any of the shipped
renderers is a numbers-only surface -- a candidate for a visual upgrade.
"""
import re, pathlib

src = pathlib.Path("src/static/app.js").read_text(encoding="utf-8")
RENDERERS = ["dashChartSvg", "ooChart", "chartEnlarge", "ooMap", "renderGraph",
             "commodityOverlaySvg", "renderFamilyGraphs", "slopeChartSvg",
             "ringDumbbellSvg", "ooViz."]

# split on top-level function declarations
parts = re.split(r"\n    (?=(?:async )?function ([A-Za-z_][\w]*)\()", src)
funcs = {}
i = 1
while i < len(parts) - 1:
    name, body = parts[i], parts[i + 1]
    funcs[name] = body
    i += 2

tabular, visual = [], []
for name, body in funcs.items():
    has_table = "<table" in body or "<tr" in body or "<th>" in body
    has_viz = any(r in body for r in RENDERERS)
    if has_table and not has_viz:
        tabular.append((name, len(body.splitlines())))
    elif has_viz:
        visual.append(name)

print(f"parsed {len(funcs)} top-level functions in app.js\n")
print(f"=== TABLE-ONLY render functions (no chart call): {len(tabular)} ===")
for n, ln in sorted(tabular, key=lambda x: -x[1]):
    print(f"  {ln:5d} lines  {n}")
print(f"\n=== functions that DO call a renderer: {len(visual)} ===")
print("  " + ", ".join(sorted(visual)))
