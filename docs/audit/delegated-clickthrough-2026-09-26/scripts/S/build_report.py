import json
raw = json.load(open("raw_a.json"))
small = json.load(open("raw_s10_small.json")); ovr = json.load(open("raw_s10_override.json")); n375 = json.load(open("raw_375.json"))
report = {
  "row": "S",
  "run": "2026-09-26, agent-run Chromium click-through (Chromium 1194 pinned build), repo 462145c served from a git-archive copy",
  "raw": {"phase_a": "raw_a.json", "s10_small_machine": "raw_s10_small.json", "s10_override": "raw_s10_override.json", "narrow_375": "raw_375.json"},
  "screenshots_dir": "shots/", "downloads_dir": "downloads/",
  "numbers_seen": {
    "fresh_seed": "C 3; Q/D/U 4/2/5; 6 enabled; 11 sources",
    "after_undo_ar": "headline still 3 until reload (F1); after reload C 2; Q/D/U 3/2/6; 5 enabled",
    "after_adopt": "C 3; Q/D/U 5/3/3; 5 enabled",
    "after_revert": "C 2; Q/D/U 3/2/6",
    "backlog": "S2 N=5; S10 N=6",
  },
  "page_errors": raw["page_errors"], "console_errors": raw["console_errors"], "http_errors": raw["http_errors"],
  "s10": {"small": {k: small[k] for k in ("bulk","overlay","state","done_zero_anywhere")}, "override": {k: ovr[k] for k in ("bulk","overlay","state","done_zero_anywhere")}},
  "narrow_375": {k: n375[k] for k in ("home_overflow","quality_overflow","library_overflow","quality_clip","library_clip")},
}
json.dump(report, open("report.json","w"), indent=2, ensure_ascii=False)
print("ok")
