## 2026-10-27 — a route pin written as an f-string is invisible to a grep for the decorator text

**Found by CI, one miss in R278 (#1526).** Adding `dependencies=[Depends(...)]` to 28 `@router.get("/path")` decorators broke one test the local battery did not run: `test_source_audit.py` pins the route as `f'@router.get("{path}")'`, a literal built from a loop variable, so a grep for `router.get("/source-audit-selftest")` over `tests/` found nothing. The Core-only job failed 72 minutes in; the cost was one more CI cycle.

**Rules.**
1. Before changing a decorator's text, search the tests for the PATH on its own (`source-audit-selftest`) and for `f'@router`, not only for the decorator spelled out; a pin built from a variable has no decorator text in the file.
2. A pin that must survive decorator arguments matches the path followed by `,` or `)` (`rf'@router\.get\("{re.escape(path)}"[,)]'`), so a dropped route still fails it and an added dependency does not.
3. Run every test file that reads the changed module's source (`grep -l diagnostics_source tests/*.py`), not only the files named for the feature.
