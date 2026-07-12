# P0 data-safety validation — operator runbook

> The `v0.2.0` tag is **held** on one thing: a live-corpus run of the P0
> data-safety set (backup/restore at scale · unlock-at-scale · collector RSS).
> No sandbox can run a 100 GB corpus, so this run is **yours**. This runbook is
> the exact procedure; the in-app **P0 data-safety validation** job does the
> heavy lifting and writes one report you send back.
>
> **Honesty first.** Every check reports `pass` / `fail` / `not-measurable-here`
> against a *written* acceptance bar. There is no composite score and never a
> fabricated pass: a check that cannot run on your machine says **why** and names
> the step that would measure it. Read each check — the tag decision is a
> conjunction of them, not a number.

The engine bars this run tests against live in
[`docs/product/SCALE_ROADMAP.md`](SCALE_ROADMAP.md) (P0.1–P0.4). This document is
the click-by-click; keep it and the report open together.

---

## 0. What this proves (and what it cannot)

| Check | What the job does on YOUR corpus | What it proves | What still needs you |
|---|---|---|---|
| **P0.1 backup** | Streams an `oo-volumes-2` backup to your dest dir, sampling process RSS the whole run; then an incremental refresh pass | The backup completes with **bounded RAM** (RSS does not scale with the corpus) and reuses unchanged volumes | The bounded-RAM verdict is only meaningful at scale — run it on the **full** corpus |
| **P0.1 verify** | Verifies the signed manifest + every volume checksum, decrypts every volume into a hash sink | The backup is **verifiable** and not silently corrupt | — |
| **P0.2 restore** | Restores into a **throwaway** staging dir + a **dry-run merge preview** (`commit=false`) | The backup **imports cleanly**; the machinery runs end to end **without touching the live corpus** | A true fresh-install import is the ultimate proof (optional, below) |
| **P0.4 unlock** | Reads the last boot's per-phase unlock timing | Steady-state unlock is **under the 2 s bar** | The recorded timing reflects the corpus size *at that boot* — measure with a **cold boot on the full corpus** |
| **P0.3 collector** | Reads the collect-perf RSS curve + memory-guard state over recent passes | RSS stays **flat across passes** (no OOM signature) | A **multi-day live soak** is the real test |

**It cannot corrupt or delete your data.** The backup only writes to the
destination directory you choose (the job refuses a destination that overlaps
the live data folder); its one touch of the live store is the engine's standard
WAL checkpoint under the write lock — a content-preserving fold, never a
replace/delete. The restore is a staged probe plus a *preview* merge —
`commit=false` means the restore **never writes** the live corpus at all. Your
live corpus is never replaced, deleted, or corrupted on any path. All temporary
files are cleaned up on finish or cancel.

**Two honest limits worth knowing.** (1) The backup briefly **pauses collection
writes** while it streams the corpus (the write lock is the snapshot-consistency
guarantee), so run this when collection is idle. (2) If the app is **hard-killed**
mid-run (OOM / kill), the restore probe's temporary `.restore-p0-probe-*` folder in
your destination may be left behind — and for an encrypted corpus it holds a
*plaintext* staged copy. Re-running the validation (or any backup) to that same
destination sweeps it automatically after 24 h; to be safe you can delete any
`.restore-*` folder in the destination directory yourself.

---

## 1. Pre-flight (do these first)

1. **Install the release you intend to tag.** Update to the exact build whose
   SHA you will tag `v0.2.0`, so the report's `app_version` /
   `backup_engine_format` stamp matches the tagged code. (`./install.sh`; the
   report records both so a stale run is detectable.)
2. **Free disk on the destination.** The backup writes a full copy of the corpus
   as encrypted volumes, and the restore probe stages a plaintext conversion +
   a working merge copy. Budget **~2.5× the corpus size free** on the
   destination drive. The job disk-preflights and refuses loudly if short — but
   check first so you are not waiting for a late failure.
3. **Pick a SEPARATE, EMPTY destination** — ideally an external drive with room.
   Not the data folder, not inside it (the job rejects that).
4. **Clean shutdown, then cold boot** (for the unlock measurement). Stop the app
   with the power button (or Ctrl-C) so the session ends cleanly, then start it
   and unlock. That boot's per-phase unlock timing is recorded automatically —
   the P0.4 check reads it. Do this on the **full** corpus.
5. **Airplane is fine.** The whole validation is local (no network). You do not
   need to go online.

---

## 2. Run the validation (the push-button step)

1. Open **Settings → Diagnostics log**. Find **“P0 data-safety validation
   (v0.2.0 acceptance)”**.
2. Enter the **backup destination directory** (your separate/empty folder) and a
   **backup passphrase**. The passphrase encrypts the backup volumes; it is
   cleared from the field the instant it is handed to the backend and never
   stored or written into the report.
3. Click **Run P0 validation**. It runs as a background job — you can watch it in
   the task manager. On a large corpus the backup is slow (that is the point:
   it streams, it does not buffer); leave it running.
4. When it finishes it shows a **verdict per check** and two download links:
   **Download report (.json)** (the artifact) and **readable (.txt)** (the same
   thing to skim). It is also folded into the **debug bundle** and the
   **all-diagnostics** archive automatically.

To stop early: **Cancel** — the throwaway restore staging and any partial backup
are cleaned up (a partial backup can never be mistaken for a complete one; the
streaming engine writes no final manifest until the set is whole).

You can also drive it without the UI:

```
POST /api/diagnostics/p0-validation        {"dest_dir": "...", "passphrase": "..."}
GET  /api/diagnostics/p0-validation/status
POST /api/diagnostics/p0-validation/cancel
GET  /api/diagnostics/p0-validation/download?format=json   (or format=txt)
GET  /api/diagnostics/p0-validation/last                   (read-only, no re-run)
```

---

## 3. What PASS looks like, per check

- **P0.1 backup → `pass`** — the backup completed **and** peak RSS stayed well
  under the corpus size (RAM did not scale with the corpus). On a corpus under
  ~2 GB (or without psutil) this reads **`not-measurable-here`**: the backup
  completed and will verify, but the P0.1 bar *is* bounded-RAM-at-scale, which
  cannot be tested at that size — that is why you run it on the **full** corpus.
  Verification of that sub-scale backup still shows under P0.1 verify.
- **P0.1 verify → `pass`** — signature verified, no bad or missing volumes, every
  volume decrypted and cross-checked against the signed envelope.
- **P0.2 restore → `pass`** — restored + previewed the merge with
  `committed=false`; the live corpus was only read.
- **P0.4 unlock → `pass`** — the last boot's synchronous unlock was **< 2000 ms**.
  If it reads `not-measurable-here`, no cold-boot timing was recorded — do step
  1.4 and re-run. The report includes the cold-boot instruction inline.
- **P0.3 collector → `pass`** — RSS stayed flat across recycled passes. If it
  reads `not-measurable-here`, there were not enough passes in the window — run
  the soak (step 4) and re-run.

A `fail` is a real defect on your corpus — send the report (below). A
`not-measurable-here` is a step still owed on your machine, never a pass.

---

## 4. The multi-day collector soak (for P0.3)

The flat-RSS property is only real over a long run. Go online (the one network
consent), let continuous collection run for a **few days**, then re-run the
validation. The P0.3 check reads the collect-perf RSS curve across passes: a rise
of more than ~512 MB from the first pass to the peak pass is flagged as the OOM
signature; a smaller rise passes. The memory guard should pause (never die) under
pressure — its state is in the report.

**Honest limit of the P0.3 check:** the collect-perf log retains only ~2 hours, so
this check sees the passes in that recent window — a *slower* multi-day leak may
not appear in it. The real multi-day acceptance signal is the app **surviving days
of collection without an OOM**: check the memory guard did not stay engaged and the
previous session ended cleanly (session forensics), not just this window.

If the soak crashes or the app OOMs, that is exactly the P0.3 defect — capture
the debug bundle and the collect-perf log (Settings → Diagnostics) and send them.

---

## 5. Optional: a true fresh-install import (the strongest P0.2 proof)

The in-app P0.2 check proves the restore machinery end to end without risk. If
you want the ultimate proof — a real 100 GB backup imports on a clean machine:

1. Copy the backup dir (from step 2) to a second machine / fresh install.
2. Settings → **Import…** → restore from the volume backup folder → **preview**.
3. The preview reports the plan (additive-only; nothing replaced). Commit it on
   the fresh install only.

Never do the commit on your live machine to “test” it — the in-app P0.2 preview
already exercises the same code with `commit=false`.

---

## 6. Send the report back

Download the **.json** (and optionally the **.txt**). It carries `app_version`,
`backup_engine_format`, every check's measurements + verdict, and no secrets. It
is the single artifact the whole v0.2.0 tag is gated on. Send it to the
maintainer channel along with the debug bundle if any check failed.

---

## 7. TAG-DAY CHECKLIST (maintainer-only — the tag stays held until this is done)

Do NOT run this until the report above is green for the data-safety checks and
unlock/collector were measured (cold boot + soak). The tag and the live run are
maintainer-only.

1. **Report green.** The P0.1 backup, P0.1 verify and P0.2 restore checks are
   `pass`; P0.4 unlock is `pass` on a cold boot of the full corpus; P0.3
   collector is `pass` over a multi-day soak. Any `fail` blocks the tag.
2. **Version already set.** `pyproject.toml` reads `0.2.0` (single source of
   truth); `README` / `CONTRIBUTING` / `CHANGES` already say “the tag awaits the
   live-corpus scale validation” — no version-number edit is needed at tag time.
3. **CI green at the SHA you will tag.** Because the maintainer fast-merges even
   with a red lane, do not trust “merged”: dispatch `ci.yml`
   (`workflow_dispatch`) on the exact commit and **watch it to completion**.
4. **Tag `v0.2.0`.** `git tag v0.2.0 <sha> && git push origin v0.2.0`.
   `release.yml` gates the release job on the full test suite (`pytest -q`) and
   verifies `tag == pyproject version` (`v0.2.0` == `0.2.0`) before publishing —
   a red tree or a mismatched tag stops it.
5. **Verify the release assets.** The workflow builds the sdist + wheel and a
   `SHA256SUMS`. After it publishes, download the assets and check them against
   the published `SHA256SUMS` (checksums-only; there is no signing key yet — a
   tracked future item).
6. **Rename the branch** `0.1 → 0.2` (mirrors the `0.09 → 0.1` flip). Do this in
   a quiet window with no parallel PRs in flight against `origin/0.1` (the #548
   stale-base revert precedent).
7. **Softening the caveat.** Once the tag lands, the “tag awaits live validation”
   lines in `README` / `CONTRIBUTING` / `CHANGES` / `ROADMAP` can be softened to
   “released”. That edit is a follow-up, not a blocker.
