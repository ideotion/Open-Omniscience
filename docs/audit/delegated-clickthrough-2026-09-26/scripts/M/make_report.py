import json
report = {
 "row": "M",
 "walked_at": "2026-09-26T18:26Z-18:55Z",
 "build": "origin/main 462145c (detached HEAD)",
 "environment": {
  "encrypted": True,
  "seed": "scripts/ui_clickthrough_seed.py default STATE C (440 language-pool articles, 453 total) into an ENCRYPTED store (OO_DB_PASSPHRASE set, OO_DB_PLAINTEXT unset) with OO_EXTRACT_LEMMA=0 at SEED time only; booted with neither variable nor OO_EXTRACT_LEMMA, so it started LOCKED with lemmatisation on; unlocked through #pw/#btn-unlock. data1 (8826) = throwaway for M1-M9; data2 (8827) = a second identical seed standing in for the 'real install' for M11.",
  "ports": [8826, 8827],
  "scratch_dir": "/tmp/claude-0/walk/M",
 },
 "evidence_files": sorted(__import__('os').listdir('/tmp/claude-0/walk/M')),
}
json.dump(report, open('/tmp/claude-0/walk/M/report.json', 'w'), indent=1, ensure_ascii=False)
print("ok")
