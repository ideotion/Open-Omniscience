/* app-backup.js — backup, restore, uninstall

   The unified export/import dialogs and their progress views, folder and volume
   backups, fetch mode, at-rest encryption, and the uninstall flow.

   PART OF THE UI ENGINE. src/static/app.js was decomposed into ordered modules
   (structural debt S-3; docs/design/APPJS_DECOMPOSITION_2026-08-20.md). They share
   ONE global scope -- there is no module system here, and 394 of these top-level names
   are called by inline on*= handlers, which resolve against the global scope and
   nothing else -- and they load in the order index.html lists them, boot last.

   The split was a pure CONTIGUOUS slice, verified at the split commit by
   concatenating the modules in load order and reproducing the pre-split file byte
   for byte. That check is spent now (these files are edited normally), but the rule
   it rested on still holds: DO NOT reorder a declaration across a module boundary.
   Function declarations would survive it, because they hoist; a const or let would
   not, and the failure is a TDZ error at load rather than anything a reader would
   spot in review. Add new code inside the module it belongs to.
*/
    async function openUnifiedExport() {
      const dlg = document.getElementById("ux-export");
      document.getElementById("ux-progress").textContent = "";
      document.getElementById("ux-run").disabled = false;
      dlg.showModal();
      await _uxLoadInventory();
      _uxShowLastCompletedExportSummary();  // best-effort; never blocks opening the dialog
    }

    // Mirrors _uxShowLastCompletedSummary() for the Import dialog (audit finding
    // 2026-07-17 -- the same field report 2026-07-16 root cause applies here too): a
    // large export can run for hours as a background job (task-manager-visible), so
    // the tab is very likely closed/reloaded before it finishes, and this function's
    // own closure -- the one that would have written "Backup complete" into
    // #ux-progress -- is gone with it. openUnifiedExport() unconditionally blanked
    // #ux-progress on every reopen, discarding that result forever. Each job manager
    // (get_volume_manager(), get_folder_manager()) is a PROCESS-WIDE singleton whose
    // last completed state survives any number of page reloads until a NEW job
    // starts -- so recover it here, filtered to mode==="backup" (never show a
    // restore's or verify's status in the EXPORT dialog).
    async function _uxShowLastCompletedExportSummary() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prog = document.getElementById("ux-progress");
      const bar = document.getElementById("ux-bar");
      const pauseBtn = document.getElementById("ux-pause");
      let shown = null, phase = null;
      try {
        const s = await api("/api/backup/v2/volumes/status");
        if (s && s.mode === "backup" && (s.state === "done" || s.state === "paused")) { shown = s; phase = "volumes"; }
      } catch (e) { /* best-effort: one endpoint failing must not hide the other */ }
      try {
        // The folder (large-data) phase runs AFTER volumes in a full export -- if it
        // also completed/paused, it is the more recent state to show.
        const s = await api("/api/backup/folder/status");
        if (s && s.mode === "backup" && (s.state === "done" || s.state === "paused")) { shown = s; phase = "folder"; }
      } catch (e) { /* best-effort */ }
      if (!shown) return;
      const dest = shown.dest || (document.getElementById("ux-dest").value || "").trim();
      if (shown.state === "paused") {
        // Audit finding 2026-07-17 (M8): a reopened dialog used to print "paused" text
        // with NO way to resume -- _uxPhase (which endpoint a resume must target) stayed
        // null from page load, and the actual #ux-pause button (default display:none)
        // was never unhidden/relabelled, only this status text. _uxShowPaused is the
        // SAME helper _uxRun already uses for a mid-run pause -- reuse it here so the
        // reopened dialog gets a real, correctly-targeted Resume button.
        _uxPhase = phase;
        _uxShowPaused(prog, bar, pauseBtn, t);
      } else {
        prog.innerHTML = `<b>${esc(t("Backup complete →"))}</b> ${esc(dest)} (${esc(t("last completed export"))})`;
      }
    }

    async function _uxLoadInventory() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const st = document.getElementById("ux-inv-status");
      const box = document.getElementById("ux-checklist");
      st.textContent = t("Loading what's available…");
      try {
        const inv = await api("/api/backup/inventory");
        const c = inv.corpus || {}, b = c.breakdown || {};
        // "Everything" is the default: a present category (count > 0) is CHECKED so a
        // backup includes the whole corpus + wiki + maps + models unless the user
        // unticks one (field ask 2026-07-02). Absent categories are disabled.
        const opt = (id, label, d) =>
          `<label class="switch" style="margin:0"><input type="checkbox" id="ux-c-${id}" ${(d.count || 0) > 0 ? "checked" : "disabled"}> ${esc(label)} <span class="muted">(${d.count || 0} · ${humanBytes(d.bytes || 0)})</span></label>`;
        // The corpus is CHECKED by default (a backup still means everything unless the
        // user says otherwise) but no longer `disabled`: it was un-untickable, so the
        // only way to copy models/maps/dumps was to re-encrypt and re-write the whole
        // corpus alongside them (field ask 2026-08-10: "backups should not force user to
        // backup articles and allow them to make compartmented backups"). The import side
        // already discovers corpus, large-data and newsletters independently and only
        // asks for a passphrase when the corpus is among them, so a corpus-less export
        // restores exactly as it is written.
        box.innerHTML =
          `<label class="switch" style="margin:0"><input type="checkbox" id="ux-c-corpus" checked> ${esc(t("Corpus"))} <span class="muted">(${b.articles || 0} ${esc(t("articles"))} · ${b.sources || 0} ${esc(t("sources"))} · ${b.dates || 0} ${esc(t("dates"))} · ${b.keywords || 0} ${esc(t("keywords"))} · ${humanBytes(c.bytes || 0)})</span></label>` +
          opt("models", t("LLM models"), inv.models || {}) +
          opt("maps", t("Offline maps"), inv.maps || {}) +
          opt("wiki", t("Wikipedia dumps"), inv.wiki || {});
        st.textContent = t("What do you want to back up?");
      } catch (e) {
        st.textContent = t("Could not load the inventory — see console");
        console.error("ux inventory", e);
      }
    }

    function _uxEta(secs, t, approx) {
      if (secs == null) return "";
      const m = Math.round(secs / 60);
      const txt = m >= 1 ? `${m} ${t("min")}` : `${Math.max(1, Math.round(secs))} ${t("s")}`;
      // "~" (and the word "estimate") signals a rule-of-three guess, not a promise —
      // the maintainer's ask: humans prefer an approximate number to none at all.
      return ` · ${approx ? "~" : ""}${txt} ${t("left")}`;
    }
    // A rule-of-three time-remaining estimate from wall-clock elapsed and the fraction
    // done: remaining ≈ elapsed × (1 − frac) / frac. Deliberately simple + honest — it
    // assumes a steady rate and says so ("~ … left"). Held back until enough has run
    // (a few seconds AND ≥3% done) so the first wild guess never shows.
    function _uxRuleOfThree(startMs, frac) {
      if (frac == null || frac <= 0.03 || frac >= 1) return null;
      const elapsed = (Date.now() - startMs) / 1000;
      if (elapsed < 3) return null;
      return elapsed * (1 - frac) / frac;
    }
    // Honest progress view for a manager status. Managers that report a TOTAL
    // (folder bytes, newsletter files) give a real %; the volume engine streams and
    // knows no total ahead of time, so we show an INDETERMINATE bar + the phase + how
    // many volumes are done — never a fabricated/animated-fake percentage.
    function _uxVolPhase(phase, mode, t) {
      const back = { starting: t("Preparing…"), building: t("Building encrypted volumes…"),
        volumes: t("Writing encrypted volumes…"), parity: t("Writing parity…"), done: t("Done.") };
      const rest = { verifying: t("Verifying volumes…"), reassembling: t("Reassembling the archive…"),
        merging: t("Merging (additive)…"), reindexing: t("Re-indexing merged articles…"), done: t("Done."),
        // "Progress everywhere" (§4 item 2): named labels for the run_restore
        // stages that are slow/significant enough to be worth naming distinctly
        // (a real corpus-file copy, the post-merge verification scan, the
        // atomic commit itself) -- every OTHER stage (the cheap post-commit
        // housekeeping: corpus_delta_*/corpus_epoch_bump/event_mirror_refresh/
        // quarantine_scan/work_induced_tally/prune_snapshots/prepare_staged)
        // honestly falls through to the generic "Restoring…" default below,
        // since they are typically sub-second and a distinct label per one
        // would be noise, not signal.
        verify: t("Verifying the merge…"),
        snapshot_working_copy: t("Snapshotting your corpus…"),
        pre_restore_snapshot: t("Snapshotting your corpus…"),
        swap: t("Committing…"),
        // The import run's OWN tail phase (ImportQueueManager._tune_after_run), not
        // one of run_restore's stages: an FTS5 'optimize' that runs once after the
        // last item. It is single-threaded and index-scaled, so on a large corpus it
        // is minutes of 100%-of-one-core work AFTER every item already reads "Done".
        tuning: t("Merging the search index…") };
      // verify + restore share the phase names (verifying/reassembling); only a backup
      // uses the write-side names. Default is mode-aware so a verify never falls back to
      // "Backing up…" or shows a raw untranslated phase.
      const m = (mode === "backup" ? back : rest);
      const dflt = mode === "backup" ? t("Backing up…")
        : mode === "verify" ? t("Verifying volumes…") : t("Restoring…");
      return m[phase] || dflt;
    }
    // "phase 9 of 18" — the honest position of the current phase within THIS run.
    // Both numbers come from the backend (src/backup/merge.py::restore_stage_plan +
    // volume_job's own manager phases), never from a hardcoded denominator: a dry run
    // walks 5 stages, a committing restore 16, and one fewer when the re-index is
    // skipped. index 0 means the backend could not place the stage in its own plan —
    // an honest unknown, so we render nothing rather than a guess.
    function _uxPhaseCount(p, t) {
      const i = p.phase_index || 0, n = p.phase_total || 0;
      if (!i || !n || i > n) return "";
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      return ` · ${tf("phase {n} of {total}", { n: i, total: n })}`;
    }
    function _uxProgressView(kind, s, t) {
      const p = s.progress || {};
      if (kind === "newsletters") {
        const total = s.files_total || 0, done = s.files_done || 0;
        const pct = total ? (s.percent != null ? s.percent : Math.round(100 * done / total)) : null;
        return { pct, indeterminate: !total, text: `${done}/${total || "?"} ${esc(t("files"))}${esc(_uxEta(s.eta_seconds, t, true))}` };
      }
      if (kind === "folder") {
        const bt = p.bytes_total || 0, bc = p.bytes_copied || 0;
        const pct = bt ? Math.round(100 * bc / bt) : null;
        const verb = s.mode === "restore" ? esc(t("restored")) : esc(t("copied"));
        const n = s.mode === "restore" ? (p.restored || 0) : (p.copied || 0);
        // frac drives the client-side rule-of-three ETA in _uxPoll (bytes are the honest
        // size measure for wiki/maps/models — the big, slow copies the user waits on).
        return { pct, indeterminate: !bt, frac: bt ? bc / bt : null,
          text: `${n} ${verb}, ${p.skipped || 0} ${esc(t("skipped"))}` };
      }
      // volumes: mostly phase-driven + indeterminate, EXCEPT the merge/reindex phases,
      // which report real N-of-M progress — show a real bar there + drive the
      // rule-of-three ETA (field ask). The reindex phase used to be entirely silent
      // (frozen on the merge's last-reported step) for however long the post-merge
      // per-article re-index took — sometimes hours on a large restore, reading as a
      // hang (2026-07-19 field report).
      const phaseCount = esc(_uxPhaseCount(p, t));
      if (p.merge_steps) {
        const frac = Math.min(1, (p.merge_step || 0) / p.merge_steps);
        const label = p.merge_label
          ? `${esc(_uxVolPhase("merging", s.mode, t))} <span class="muted">(${p.merge_step}/${p.merge_steps} · ${esc(p.merge_label)})</span>`
          : esc(_uxVolPhase("merging", s.mode, t));
        // phaseKey scopes the rule-of-three ETA to THIS phase (see _uxPoll): the
        // merge and the re-index are different units of work at wildly different
        // rates, so one baseline across both produced the field report's absurd
        // "4000 min left" the instant the phase flipped and frac reset to ~0.
        return { pct: Math.round(frac * 100), indeterminate: false, frac, phaseKey: "merge",
          text: label + `<span class="muted">${phaseCount}</span>` };
      }
      if (p.reindex_total) {
        const frac = Math.min(1, (p.reindex_done || 0) / p.reindex_total);
        const label = `${esc(_uxVolPhase("reindexing", s.mode, t))} <span class="muted">(${p.reindex_done || 0}/${p.reindex_total} ${esc(t("articles"))})</span>`;
        return { pct: Math.round(frac * 100), indeterminate: false, frac, phaseKey: "reindex",
          text: label + `<span class="muted">${phaseCount}</span>` };
      }
      let extra = "";
      if (p.volumes_written) extra += ` · ${p.volumes_written} ${esc(t("volumes"))}`;
      if (p.bytes_written) extra += ` · ${esc(humanBytes(p.bytes_written))}`;
      return { pct: null, indeterminate: true, phaseKey: `phase:${p.phase || ""}`,
        text: `${esc(_uxVolPhase(p.phase, s.mode, t))}${extra}<span class="muted">${phaseCount}</span>` };
    }
    function _uxPaintBar(bar, view) {
      if (!bar) return;
      bar.style.display = "";
      if (view.indeterminate || view.pct == null) bar.removeAttribute("value");
      else { bar.max = 100; bar.value = view.pct; }
    }
    // Poll a job's status endpoint, painting an honest <progress> bar + phase label.
    // Resolves with the final status object (so the caller can read its summary/tally).
    function _uxPoll(url, kind, ui) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prefix = ui.prefix ? `${esc(ui.prefix)}: ` : "";
      // PER-PHASE ETA baseline (field report 2026-07-29: a 50,000-article import
      // quoted "~4000 min left"). This used to be ONE startMs for the whole job while
      // `view.frac` resets to ~0 at every phase boundary, so the rule of three computed
      // (verify + reassemble + merge + reindex-so-far) x (1-f)/f — charging the whole
      // preceding job to the fraction of the phase that had just started, an
      // over-estimate of roughly 5-15x early in the re-index. Re-baselining per phase
      // makes the estimate mean what it says: time left in THIS phase.
      let etaKey = null;
      let etaStart = Date.now();
      return new Promise((resolve, reject) => {
        // JOB-STATE-AS-TRUTH (field-test Item 9): a dropped/failed status poll does NOT
        // mean the backup failed — the job keeps running server-side. So a transport hiccup
        // shows an honest "connection hiccup — retrying" and keeps polling with backoff;
        // ONLY a backend-reported error/cancelled STATE is a real failure. Without this a
        // single lost /volumes/status poll printed a fatal "Backup failed: NetworkError"
        // over a healthy multi-hour job.
        let fails = 0;                    // consecutive poll-transport failures
        const MAX_FAILS = 40;             // give up POLLING (not the job) after ~minutes of backoff
        const tick = async () => {
          let s;
          try {
            s = await api(url);
            fails = 0;                    // a good poll clears the hiccup
          } catch (e) {
            fails++;
            if (fails > MAX_FAILS) {
              return reject(new Error(t("Lost contact with the backup job — check the task manager; it may still be running.")));
            }
            if (ui.label) {
              ui.label.innerHTML = prefix + `<span class="muted">${esc(t("Connection hiccup — retrying…"))}</span>`;
            }
            setTimeout(tick, Math.min(1200 * Math.pow(1.6, fails - 1), 15000));
            return;
          }
          const state = s.state || "";
          const view = _uxProgressView(kind, s, t);
          _uxPaintBar(ui.bar, view);
          // A client-side rule-of-three ETA for byte/fraction-based jobs (folder copy);
          // the newsletter job carries its own backend eta_seconds already in view.text.
          const key = view.phaseKey || kind;
          if (key !== etaKey) { etaKey = key; etaStart = Date.now(); }
          const etaSec = _uxRuleOfThree(etaStart, view.frac);
          const etaTxt = etaSec != null ? _uxEta(etaSec, t, true) : "";
          if (ui.label) ui.label.innerHTML = prefix + view.text + esc(etaTxt);
          if (state === "done" || state === "paused") return resolve(s);  // paused = stopped, not a hang
          if (state === "error" || state === "cancelled") {
            // Surface the REAL backend error (the volume manifest/checksum message),
            // never a bare "cancelled" — field report: "Import failed — see console".
            return reject(new Error(s.error || view.text || state));
          }
          setTimeout(tick, 1200);
        };
        tick();
      });
    }

    // Which phase is live, so the Pause button can address the right job and a Resume
    // re-enters where it left off. The volume + folder jobs are RESUMABLE (their manifest /
    // dest dir IS the durable progress), so pause never risks the partial data.
    let _uxPhase = null;   // "volumes" | "folder" | null

    // JOB-STATE-AS-TRUTH for the START request too (skeptic MED-LOW): the start/resume/verify
    // POST returns AFTER the worker thread is spawned, so a transport hiccup that loses the
    // RESPONSE (the request reached the server, the job is running) must NOT print a fatal
    // "failed". On a start error we consult /status: if the job is actually live we fall
    // through to the poll; only a genuine reject (no job / idle, or /status also unreachable)
    // re-throws so a real 400/409 still surfaces.
    // Path equality tolerant of a trailing slash (the backend stores str(Path(dest)), the UI holds
    // the raw input) — used to prove a masked/live job belongs to THIS destination, not another drive.
    function _uxSamePath(a, b) {
      const norm = (p) => String(p == null ? "" : p).replace(/[\\/]+$/, "");
      return norm(a) === norm(b);
    }

    async function _uxStartThenPoll(startCall, statusUrl, kind, ui, expect) {
      try {
        await startCall();
      } catch (e) {
        let st = null;
        try { st = await api(statusUrl); } catch (_) { throw e; }  // can't confirm → original error
        const s = (st && st.state) || "";
        // Only a LIVE job (running|paused) proves the start reached the server despite the
        // lost response. NOT "done": a just-started job cannot be instantly done, so a "done"
        // here is a STALE state from a prior run and must not mask a failed start as complete.
        if (!(s === "running" || s === "paused")) throw e;
        // …and the live job must be OURS. All volume ops share one manager + one /status, so a
        // 409 from an UNRELATED job (a Verify, a restore, or a backup to a DIFFERENT drive) would
        // otherwise be adopted here and its "done" reported as our corpus backup (data-safety bug:
        // the corpus for THIS dest is never written). Re-throw when mode/dest don't match ours.
        if (expect && expect.mode && st.mode && st.mode !== expect.mode) throw e;
        if (expect && expect.dest && st.dest && !_uxSamePath(st.dest, expect.dest)) throw e;
        // else: the job is live AND ours despite the lost start response → poll it
      }
      return _uxPoll(statusUrl, kind, ui);
    }

    async function _uxRun(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dest = (document.getElementById("ux-dest").value || "").trim();
      if (!dest) { toast(t("Enter a destination folder first."), "err"); return; }
      const prog = document.getElementById("ux-progress");
      const bar = document.getElementById("ux-bar");
      const pauseBtn = document.getElementById("ux-pause");
      const blobs = [];
      if (document.getElementById("ux-c-models") && document.getElementById("ux-c-models").checked) { blobs.push("models"); blobs.push("hf_models"); }
      if (document.getElementById("ux-c-maps") && document.getElementById("ux-c-maps").checked) blobs.push("osm_regions");
      if (document.getElementById("ux-c-wiki") && document.getElementById("ux-c-wiki").checked) blobs.push("wiki_dumps");
      // A corpus-less export is now a first-class choice, so neither half is assumed:
      // refuse an empty selection outright rather than writing a destination folder that
      // looks like a backup and holds nothing.
      const cCorpus = document.getElementById("ux-c-corpus");
      const wantCorpus = !cCorpus || cCorpus.checked;
      if (!wantCorpus && !blobs.length) {
        toast(t("Choose at least one thing to back up."), "err"); return;
      }
      // The passphrase protects the CORPUS. The large-data files are public,
      // re-downloadable blobs copied as-is (which is what makes 100 GB feasible), so
      // demanding one for a models-only export would be asking for a secret that
      // protects nothing.
      const pass = document.getElementById("ux-pass").value || "";
      if (wantCorpus && !pass) {
        toast(t("Enter a passphrase for the encrypted corpus."), "err"); return;
      }
      btn.disabled = true;
      if (pauseBtn) { pauseBtn.style.display = ""; pauseBtn.disabled = false; pauseBtn.dataset.mode = "pause"; pauseBtn.textContent = t("Pause"); }
      try {
        if (wantCorpus) {
          _uxPhase = "volumes";
          const s1 = await _uxStartThenPoll(
            () => api("/api/backup/v2/volumes/start", { method: "POST", body: JSON.stringify({ dest, passphrase: pass }) }),
            "/api/backup/v2/volumes/status", "volumes", { bar, label: prog, prefix: t("Corpus") },
            { mode: "backup", dest });
          if (s1 && s1.state === "paused") { _uxShowPaused(prog, bar, pauseBtn, t); btn.disabled = false; return; }
          // DATA-SAFETY GATE (field 2026-07-14): the large-data (blob) phase is unreachable, and
          // "Backup complete" is never shown, unless the volumes phase PROVABLY completed as a
          // `backup` of the corpus into THIS dest. Without this a lost/masked start that adopted an
          // unrelated live job's "done" would skip the corpus yet print success.
          //
          // Deselecting the corpus does NOT weaken this. The gate exists so a corpus the user
          // ASKED for cannot be silently skipped behind a success message; when they did not ask
          // for one there is nothing to confirm, and the completion line below says so by name
          // rather than letting "Backup complete" imply a corpus is in there.
          if (!s1 || s1.state !== "done" || s1.mode !== "backup" || (s1.dest && !_uxSamePath(s1.dest, dest))) {
            throw new Error(t("The corpus backup could not be confirmed — aborting before the large-data files so you never get a partial backup that looks complete."));
          }
        }
        if (blobs.length) {
          _uxPhase = "folder";
          const s2 = await _uxStartThenPoll(
            () => api("/api/backup/folder/start", { method: "POST", body: JSON.stringify({ dest, categories: blobs }) }),
            "/api/backup/folder/status", "folder", { bar, label: prog, prefix: t("Large data") },
            { dest });
          if (s2 && s2.state === "paused") { _uxShowPaused(prog, bar, pauseBtn, t); btn.disabled = false; return; }
        }
        _uxPhase = null;
        if (bar) bar.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
        // Name what is actually in it. Now that the corpus can be left out, "Backup
        // complete" alone would let a models-only export read months later as a full one
        // -- the reader has no other way to tell, and that is the expensive direction to
        // be wrong in.
        const included = [];
        if (wantCorpus) included.push(t("Corpus"));
        if (blobs.includes("models")) included.push(t("LLM models"));
        if (blobs.includes("osm_regions")) included.push(t("Offline maps"));
        if (blobs.includes("wiki_dumps")) included.push(t("Wikipedia dumps"));
        prog.innerHTML = `<b>${esc(t("Backup complete →"))}</b> ${esc(dest)}`
          + `<div class="muted" style="font-size:12px;margin-top:2px">`
          + `${esc(t("Included:"))} ${esc(included.join(" · "))}</div>`;
      } catch (e) {
        _uxPhase = null;
        if (bar) bar.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
        prog.innerHTML = `<span class="note err">${esc(t("Backup failed:"))} ${esc(e.message || e)}</span>`;
        console.error("ux run", e);
      }
      btn.disabled = false;
    }

    // Paused ≠ complete (the paused-state label, field-test Item 9): show the honest state
    // and flip the button to Resume so the user continues where it left off.
    function _uxShowPaused(prog, bar, pauseBtn, t) {
      if (bar) bar.style.display = "none";
      prog.innerHTML = `<b>${esc(t("Backup paused."))}</b> ${esc(t("Resume to continue where it left off."))}`;
      if (pauseBtn) { pauseBtn.style.display = ""; pauseBtn.disabled = false; pauseBtn.dataset.mode = "resume"; pauseBtn.textContent = t("Resume"); }
    }

    // Pause the live phase, or resume a paused backup — continuing from the resume log /
    // already-copied files, never re-doing finished work.
    async function _uxPauseResume(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn.dataset.mode === "resume") { btn.dataset.mode = "pause"; await _uxResume(btn); return; }
      const ep = _uxPhase === "folder" ? "/api/backup/folder/pause" : "/api/backup/v2/volumes/pause";
      btn.disabled = true;
      try { await api(ep, { method: "POST" }); }
      catch (e) { toast(t("Could not pause:") + " " + (e.message || e), "err"); btn.disabled = false; }
      // The poll then observes state="paused" and _uxShowPaused flips this button to Resume.
    }

    async function _uxResume(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prog = document.getElementById("ux-progress");
      const bar = document.getElementById("ux-bar");
      if (_uxPhase === "folder") {
        // The folder copy has a dedicated resume endpoint (re-plans + skips copied files).
        btn.dataset.mode = "pause"; btn.textContent = t("Pause");
        try {
          // Re-enable the Pause button for the resumed copy (skeptic MED: it was stuck
          // disabled through the whole multi-GB resume). _uxStartThenPoll keeps the resume
          // request hiccup-tolerant (job-state-as-truth), same as a fresh start.
          btn.disabled = false;
          const s = await _uxStartThenPoll(
            () => api("/api/backup/folder/resume", { method: "POST" }),
            "/api/backup/folder/status", "folder", { bar, label: prog, prefix: t("Large data") });
          if (s && s.state === "paused") { _uxShowPaused(prog, bar, btn, t); return; }
          _uxPhase = null;
          if (bar) bar.style.display = "none"; btn.style.display = "none";
          prog.innerHTML = `<b>${esc(t("Backup complete →"))}</b> ${esc((document.getElementById("ux-dest").value || "").trim())}`;
        } catch (e) {
          _uxPhase = null; if (bar) bar.style.display = "none"; btn.style.display = "none";
          prog.innerHTML = `<span class="note err">${esc(t("Backup failed:"))} ${esc(e.message || e)}</span>`;
        }
        return;
      }
      // Volumes phase: re-running the flow continues the corpus from its resume log,
      // then does any selected large-data blobs.
      _uxRun(document.getElementById("ux-run"));
    }

    // ---- Unified Import dialog (folder discovery) -------------------------- //
    // Point at a folder -> /api/backup/import-scan classifies it -> a checklist of what
    // was FOUND -> restore/import the selected kinds via the existing endpoints. Additive.
    let _uxImFound = null, _uxImSrc = "";

    function openUnifiedImport() {
      document.getElementById("ux-imp-checklist").innerHTML = "";
      document.getElementById("ux-imp-status").textContent = "";
      document.getElementById("ux-imp-progress").textContent = "";
      document.getElementById("ux-imp-summary").innerHTML = "";
      const bar = document.getElementById("ux-imp-bar"); if (bar) bar.style.display = "none";
      document.getElementById("ux-imp-pass-row").style.display = "none";
      document.getElementById("ux-imp-run").disabled = true;
      _uxImFound = null; _uxImSrc = "";
      document.getElementById("ux-import").showModal();
      _uxShowLastCompletedSummary();  // best-effort; never blocks opening the dialog
      // Reattach to a run already in flight on the SERVER (ruling item 16): a reload no
      // longer decapitates an import, so the dialog must be able to find it again.
      _uxImReattach();
    }

    // Field report 2026-07-16: "after a successful import/merge, the interface doesn't
    // show the amounts of deduplicated and other import statistics." Root cause: a large
    // restore runs for hours as a background job (task-manager-visible), so the browser
    // tab is very likely closed or reloaded before it finishes -- and the SAME JS closure
    // that would have called _renderImportSummary() is gone with it. openUnifiedImport()
    // then unconditionally blanked #ux-imp-summary on every reopen, discarding the result
    // forever even though it was never shown. But each job manager (get_volume_manager(),
    // get_folder_manager(), the newsletter import job) is a PROCESS-WIDE singleton whose
    // last completed summary survives any number of page reloads until a NEW job starts --
    // so recover it here and render it via the same _renderImportSummary the live run uses,
    // labelled as the last completed run (never confused with a fresh one).
    async function _uxShowLastCompletedSummary() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const label = (title) => `${title} (${t("last completed import")})`;
      const summaries = [];
      try {
        const s = await api("/api/backup/v2/volumes/status");
        if (s && s.state === "done" && s.mode === "restore" && s.summary && s.summary.report) {
          const rep = s.summary.report;
          summaries.push({ title: label(t("Corpus backup")), plan: rep.plan || {}, ..._uxPlanExtras(rep) });
        }
      } catch (e) { /* best-effort: one endpoint failing must not hide the others */ }
      try {
        const s = await api("/api/backup/folder/status");
        if (s && s.state === "done" && s.mode === "restore") {
          const p = s.progress || {};
          summaries.push({ title: label(t("Large data")), tally: { restored: p.restored || 0, skipped: p.skipped || 0 }, lines: [
            `${p.restored || 0} ${t("restored")}`, `${p.skipped || 0} ${t("skipped")}`] });
        }
      } catch (e) { /* best-effort */ }
      try {
        const s = await api("/api/newsletters/import-folder/status");
        if (s && s.state === "done") {
          const tl = s.tally || {};
          summaries.push({ title: label(t("Newsletters")), tally: { stored: tl.stored || 0, duplicate: tl.duplicate || 0, empty: tl.empty || 0, errors: tl.errors || 0 }, lines: [
            `${tl.stored || 0} ${t("stored")}`, `${tl.duplicate || 0} ${t("already present")}`,
            `${tl.empty || 0} ${t("empty")}`, `${tl.errors || 0} ${t("errors")}`] });
        }
      } catch (e) { /* best-effort */ }
      if (summaries.length) _renderImportSummary(document.getElementById("ux-imp-summary"), summaries);
    }

    // VERIFY a backup at the source folder without restoring (field-test Item 9). Runs the
    // shipped /volumes/verify job: manifest signature + every volume + parity checksum; with
    // a passphrase every volume is additionally stream-decrypted into a hash sink (nothing
    // written, the live corpus untouched). Names exactly which volumes are bad and whether
    // parity can still recover them — honest, no score.
    async function _uxImVerify(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = (document.getElementById("ux-imp-src").value || "").trim();
      if (!src) { toast(t("Enter a folder to scan."), "err"); return; }
      const st = document.getElementById("ux-imp-status");
      const summary = document.getElementById("ux-imp-summary");
      const bar = document.getElementById("ux-imp-bar");
      const prog = document.getElementById("ux-imp-progress");
      // A passphrase is OPTIONAL for verify (structural check needs none); with it, the
      // deep decrypt-check runs. Reveal the field so the user can add one if they want it.
      document.getElementById("ux-imp-pass-row").style.display = "block";
      const passEl = document.getElementById("ux-imp-pass");
      const pass = (passEl && passEl.value) || "";
      summary.innerHTML = ""; st.textContent = t("Verifying…"); btn.disabled = true;
      try {
        const s = await _uxStartThenPoll(
          () => api("/api/backup/v2/volumes/verify", { method: "POST", body: JSON.stringify({ src, passphrase: pass }) }),
          "/api/backup/v2/volumes/status", "volumes", { bar, label: prog, prefix: t("Verify") });
        if (bar) bar.style.display = "none"; prog.textContent = "";
        _uxRenderVerify(summary, (s && s.summary && s.summary.report) || {}, t);
        st.textContent = "";
      } catch (e) {
        if (bar) bar.style.display = "none"; prog.textContent = "";
        summary.innerHTML = `<span class="note err">${esc(t("Verification failed:"))} ${esc(e.message || e)}</span>`;
        st.textContent = "";
      }
      btn.disabled = false;
    }

    function _uxRenderVerify(host, rep, t) {
      if (!rep || typeof rep !== "object" || rep.ok === undefined) {
        host.innerHTML = `<span class="muted">${esc(t("No verification report was returned."))}</span>`;
        return;
      }
      const lines = [];
      lines.push(rep.ok === true
        ? `<b style="color:var(--ok)">✓ ${esc(t("Backup verified — the set is complete and intact."))}</b>`
        : `<b style="color:var(--err)">✗ ${esc(t("Verification found problems:"))}</b>`);
      if (typeof rep.volumes === "number") {
        host.dataset.ok = String(rep.ok);
        lines.push(`<div class="muted">${rep.volumes} ${esc(t("volumes"))} · ${esc(t("signature:"))} ${esc(String(rep.signature || "—"))}${rep.decrypted ? " · " + esc(t("decrypted & checked")) : ""}</div>`);
      }
      const probs = Array.isArray(rep.problems) ? rep.problems : [];
      if (probs.length) lines.push(`<ul style="margin:4px 0 0;padding-left:18px">${probs.map(p => `<li>${esc(p)}</li>`).join("")}</ul>`);
      if (rep.bad_volumes && rep.bad_volumes.length || (rep.missing_volumes && rep.missing_volumes.length)) {
        const bad = (rep.bad_volumes || []).concat(rep.missing_volumes || []);
        const rec = rep.recoverable ? esc(t("recoverable from parity")) : esc(t("NOT recoverable — the backup is incomplete"));
        lines.push(`<div style="color:var(--err)">${esc(t("Corrupt/missing:"))} ${esc(bad.join(", "))} — ${rec}</div>`);
      }
      if (rep.parity && typeof rep.parity === "object") {
        lines.push(`<div class="muted">${esc(t("Parity:"))} ${rep.parity.volumes} · ${esc(t("can still lose"))} ${rep.parity.tolerance_remaining}</div>`);
      }
      if (rep.method) lines.push(`<div class="hint" style="margin-top:4px">${esc(t("Method:"))} ${esc(rep.method)}</div>`);
      host.innerHTML = lines.join("");
    }

    async function _uxImScan(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = (document.getElementById("ux-imp-src").value || "").trim();
      if (!src) { toast(t("Enter a folder to scan."), "err"); return; }
      const st = document.getElementById("ux-imp-status");
      const box = document.getElementById("ux-imp-checklist");
      document.getElementById("ux-imp-summary").innerHTML = "";
      st.textContent = t("Scanning…"); box.innerHTML = ""; btn.disabled = true;
      try {
        const r = await api("/api/backup/import-scan?path=" + encodeURIComponent(src));
        const f = r.found || {};
        const rows = [];
        const corpus = Array.isArray(f.corpus) ? f.corpus : (f.corpus ? [f.corpus] : []);
        if (corpus.length) {
          const nv = corpus.reduce((a, c) => a + (c.volumes || 0), 0);
          const where = corpus.length > 1 ? ` · ${corpus.length} ${esc(t("sets"))}` : "";
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-corpus" checked> ${esc(t("Restore corpus backup"))} <span class="muted">(${esc(t("encrypted volumes — additive, nothing you already have is overwritten"))}${nv ? ` · ${nv} ${esc(t("volumes"))}` : ""}${where})</span></label>`);
        }
        if (f.legacy_backup && f.legacy_backup.length) {
          const n = f.legacy_backup.length;
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-legacy" checked> ${esc(t("Restore legacy backup file"))}${n > 1 ? "s" : ""} <span class="muted">(${n} · ${esc(f.legacy_backup.map(x => x.name).join(", "))})</span></label>`);
        }
        if (f.blobs) {
          const b = f.blobs, parts = [];
          if (b.wiki) parts.push(`wiki ${b.wiki.count}`);
          if (b.maps) parts.push(`maps ${b.maps.count}`);
          if (b.models) parts.push(`models ${b.models.count}`);
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-blobs" checked> ${esc(t("Restore large data"))} <span class="muted">(${parts.join(" · ")})</span></label>`);
        }
        if (f.newsletters) rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-eml" checked> ${esc(t("Import newsletters"))} <span class="muted">(${f.newsletters.count}${f.newsletters.capped ? "+" : ""} .eml)</span></label>`);
        const notes = [];
        if (f.source_csv) notes.push(esc(t("Source CSV found — import it from the Sources panel for now.")) + ` (${esc(f.source_csv.join(", "))})`);
        box.innerHTML = rows.join("") || `<span class="muted">${esc(t("Nothing importable found in this folder."))}</span>`;
        if (notes.length) box.innerHTML += `<p class="muted" style="margin:4px 0 0">${notes.join("<br>")}</p>`;
        // A passphrase is needed for the encrypted corpus AND for legacy archives.
        const needsPass = corpus.length > 0 || (f.legacy_backup && f.legacy_backup.length > 0);
        document.getElementById("ux-imp-pass-row").style.display = needsPass ? "block" : "none";
        document.getElementById("ux-imp-run").disabled = rows.length === 0;
        st.textContent = rows.length ? t("What do you want to import?") : "";
        _uxImFound = f; _uxImSrc = src;
      } catch (e) {
        st.textContent = t("Scan failed:") + " " + (e.message || e);
        console.error("ux import scan", e);
      }
      btn.disabled = false;
    }

    // The RUN. Field remarks 2026-07-29 remark 2: this used to be a client-side loop
    // over the discovered items, POSTing each in turn and writing every one of them into
    // the same bar behind a constant "Corpus" prefix. That shape made four things
    // structurally impossible -- per-item identity, a Stop, survival of a reload, and a
    // single exclusive collection window across the run. So the sequencing now lives on
    // the server (/api/backup/import-queue) and this function only BUILDS the plan and
    // renders what the server reports.
    async function _uxImRun(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = _uxImSrc, f = _uxImFound || {};
      const summaryEl = document.getElementById("ux-imp-summary");
      summaryEl.innerHTML = "";
      const cb = (id) => { const el = document.getElementById(id); return el && el.checked; };
      const corpus = Array.isArray(f.corpus) ? f.corpus : (f.corpus ? [f.corpus] : []);
      const legacy = f.legacy_backup || [];
      const blobRoots = f.blob_roots || (f.blobs ? [{ root: src, categories: Object.keys(f.blobs).map(k => ({ wiki: "wiki_dumps", maps: "osm_regions", models: "models" }[k])) }] : []);
      const pass = document.getElementById("ux-imp-pass").value || "";
      // The volume corpus is ALWAYS encrypted -> a passphrase is required. A legacy
      // single-file archive may be plaintext, so its passphrase is optional here;
      // an encrypted one with an empty/wrong passphrase fails loudly at the backend.
      if (corpus.length && cb("ux-i-corpus") && !pass) {
        toast(t("Enter the passphrase to restore the corpus."), "err"); return;
      }
      // Each volume set lives in its OWN folder (the scan returns the exact dir the
      // manifest is in) -- queue each with THAT path, never the scanned parent.
      const items = [];
      if (corpus.length && cb("ux-i-corpus")) {
        for (const c of corpus) items.push({ kind: "corpus", path: c.path, label: _uxImLabel(c.path, t("Corpus backup")) });
      }
      if (legacy.length && cb("ux-i-legacy")) {
        for (const lg of legacy) items.push({ kind: "legacy", path: lg.path, label: lg.name });
      }
      if (blobRoots.length && cb("ux-i-blobs")) {
        for (const br of blobRoots) items.push({ kind: "blobs", path: br.root, label: t("Large data"), categories: br.categories });
      }
      if (f.newsletters && cb("ux-i-eml")) items.push({ kind: "newsletters", path: src, label: t("Newsletters") });
      if (!items.length) { toast(t("Nothing selected to import."), "err"); return; }

      // ASK before piling onto a running DB writer (2026-08-11). The Collect button
      // has always asked; the import never did, so a re-index quietly parked with no
      // word to the operator about why its counter stopped. The reassurance is the
      // point of asking here: the honest answer is "yes, and nothing is lost".
      if (!await arbitrate(t("Import"), t("A running re-index pauses while the import runs and resumes afterwards — nothing is lost."))) return;
      btn.disabled = true;
      const bgBtn = document.getElementById("ux-imp-bg");
      if (bgBtn) bgBtn.style.display = "";
      try {
        await api("/api/backup/import-queue/start", { method: "POST", body: JSON.stringify({ items, passphrase: pass }) });
      } catch (e) {
        btn.disabled = false;
        if (bgBtn) bgBtn.style.display = "none";
        document.getElementById("ux-imp-progress").innerHTML = `<span class="note err">${esc(t("Import failed:"))} ${esc(e.message || e)}</span>`;
        return;
      }
      _uxImQueuePoll();
    }

    // A backup set's folder name is its most useful identity (the maintainer's six
    // backups differ only by folder). Falls back to the generic label, never to a
    // blank row.
    function _uxImLabel(path, fallback) {
      const parts = String(path || "").split(/[\\/]+/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : fallback;
    }

    let _uxImPollTimer = null;

    // Poll the ONE server-side run and mirror it. Deliberately not a client-side
    // sequencer: nothing here decides what runs next, so closing the tab or reloading
    // the page cannot decapitate the import (the reason the old loop could not).
    async function _uxImQueuePoll() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_uxImPollTimer) { clearTimeout(_uxImPollTimer); _uxImPollTimer = null; }
      let st = null;
      try { st = await api("/api/backup/import-queue/status"); }
      catch (e) { console.error("import queue status", e); }
      if (!st) { _uxImPollTimer = setTimeout(_uxImQueuePoll, 3000); return; }
      _uxImRenderQueue(st);
      if (st.state === "running") { _uxImPollTimer = setTimeout(_uxImQueuePoll, 1000); return; }
      // Terminal: surface the per-item reports through the SAME summary renderer the
      // single-archive path uses, so nothing about the outcome view changes.
      const runBtn = document.getElementById("ux-imp-run");
      const stopBtn = document.getElementById("ux-imp-stop");
      const bgBtn = document.getElementById("ux-imp-bg");
      if (runBtn) runBtn.disabled = false;
      if (stopBtn) stopBtn.style.display = "none";
      if (bgBtn) bgBtn.style.display = "none";
      const summaries = [];
      for (const it of (st.items || [])) {
        const sm = it.summary || {};
        // Every item's OWN outcome travels with its numbers. Without this an item
        // that failed, was cancelled or was skipped still produced a summary object
        // ({} is truthy, so `rep.plan || {}` sailed straight into the plan branch)
        // and landed in the aggregate as a silent zero -- under a header that read
        // "Import successful". A six-backup run with two failures looked identical
        // to one with none.
        const base = { title: it.label, state: it.state, error: it.error, elapsed_s: it.elapsed_s, kind: it.kind };
        if (it.kind === "corpus" || it.kind === "legacy") {
          const rep = sm.report || sm || {};
          summaries.push({ ...base, plan: rep.plan || {}, ..._uxPlanExtras(rep) });
        } else if (it.kind === "blobs") {
          summaries.push({ ...base, tally: { restored: sm.restored || 0, skipped: sm.skipped || 0 },
            lines: [`${sm.restored || 0} ${t("restored")}`, `${sm.skipped || 0} ${t("skipped")}`] });
        } else if (it.kind === "newsletters") {
          const tl = sm.tally || {};
          summaries.push({ ...base, tally: { stored: tl.stored || 0, duplicate: tl.duplicate || 0, empty: tl.empty || 0, errors: tl.errors || 0 },
            lines: [`${tl.stored || 0} ${t("stored")}`, `${tl.duplicate || 0} ${t("already present")}`,
                    `${tl.empty || 0} ${t("empty")}`, `${tl.errors || 0} ${t("errors")}`] });
        }
      }
      if (summaries.length) {
        _renderImportSummary(document.getElementById("ux-imp-summary"), summaries, {
          state: st.state, elapsed_s: st.elapsed_s,
          items_done: st.items_done, items_total: st.items_total,
        });
      }
      const dlg = document.getElementById("ux-import");
      if (dlg && !dlg.open) {
        if (st.state === "done") toast(t("Import complete."));
        else if (st.state === "stopped") toast(t("Import stopped."));
        else if (st.state === "error") toast(t("Import finished with errors."), "err");
      }
    }

    const _UX_IM_STATE_LABEL = {
      queued: "Waiting", running: "Running", done: "Done", error: "Failed",
      cancelled: "Cancelled", skipped: "Skipped", stopped: "Stopped",
      interrupted: "Interrupted",
    };

    function _uxImRenderQueue(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = document.getElementById("ux-imp-queue");
      const rows = document.getElementById("ux-imp-queue-rows");
      const note = document.getElementById("ux-imp-queue-note");
      if (!box || !rows) return;
      const items = st.items || [];
      if (!items.length) { box.style.display = "none"; return; }
      box.style.display = "";
      const stopBtn = document.getElementById("ux-imp-stop");
      if (stopBtn) stopBtn.style.display = st.state === "running" ? "" : "none";
      const runBtn = document.getElementById("ux-imp-run");
      if (runBtn && st.state === "running") runBtn.disabled = true;
      // The run header: what it is doing overall + the collection statement (ruling 12).
      const head = `${items.filter(i => i.state === "done").length}/${items.length} ${esc(t("imported"))}`;
      // THE TAIL PHASE HAS TO HAVE A HOME (field report 2026-08-11). A run does not end
      // when its last item does: _tune_after_run then merges the search index, inside the
      // same exclusive window, for minutes on a large corpus. The per-item live block
      // below only renders inside a row whose item is `running`, so with every item
      // "Done" that phase had nowhere to appear -- the header read "1/1 imported", the
      // item read "Done", collection was still paused and one core sat at 100%. The
      // backend was already publishing it; there was simply no element to put it in.
      const tail = items.some((i) => i.state === "running") ? "" : _uxImPhaseBits(st.live, t);
      const tailLine = (st.state === "running" && tail) ? `<br><span class="note">${tail}</span>` : "";
      // The RUN's bar counts STAGES, not items: with every item done the item count is
      // 100% while the search-index merge still holds the machine, and a full bar beside
      // a run that has not finished is exactly the claim this reports wrongly. `stages_*`
      // is absent on an older server, and then there is simply no bar — never a fallback
      // to the item count, which is the number being corrected.
      const runBar = document.getElementById("ux-imp-bar");
      if (runBar) {
        if (st.state === "running" && st.stages_total) {
          runBar.max = st.stages_total;
          runBar.value = Math.min(st.stages_done || 0, st.stages_total);
          runBar.style.display = "";
        } else {
          runBar.style.display = "none";
        }
      }
      note.innerHTML = `<b>${head}</b>${st.elapsed_s != null ? ` · ${esc(_uxImDur(st.elapsed_s))}` : ""}`
        + tailLine
        + (st.state === "running" && st.collection_paused ? `<br>${esc(t("Background collection is paused for this whole import and resumes when it finishes."))}` : "")
        + (st.state === "interrupted" ? `<br><span class="note err">${esc(t("This import was interrupted when the app stopped. It cannot resume (the passphrase is never stored) — start it again."))}</span>` : "");
      rows.innerHTML = items.map((it) => {
        const label = esc(it.label || it.kind);
        const state = esc(t(_UX_IM_STATE_LABEL[it.state] || it.state));
        const el = it.elapsed_s != null ? ` · ${esc(_uxImDur(it.elapsed_s))}` : "";
        const err = it.error ? `<div class="note err" style="margin-left:14px">${esc(it.error)}</div>` : "";
        const live = it.state === "running" ? _uxImLive(st.live, t) : "";
        const dot = { done: "var(--ok)", error: "var(--err)", running: "var(--accent)" }[it.state] || "var(--muted)";
        return `<div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot};margin-right:6px"></span>`
          + `<b>${label}</b> <span class="muted">— ${state}${el}</span>${live}</div>${err}`;
      }).join("");
      const body = document.getElementById("ux-imp-details-body");
      if (body) body.innerHTML = _uxImDetails(st, t);
    }

    // The current PHASE's own honest unit (ruling 14) -- never a made-up percentage of
    // the whole run, whose items are different kinds of work over different units.
    function _uxImPhaseBits(live, t) {
      // TWO SHAPES, one reader. A sub-job's mirrored status nests its phase under
      // `progress`; the run's own tail phase (_tune_after_run) is a flat dict with no
      // sub-job to mirror. Reading only the nested one silently dropped the tail phase
      // even where it WAS rendered -- a second, independent reason it was invisible.
      const p = (live && (live.progress || live)) || {};
      if (!p.phase) return "";
      const bits = [esc(_uxVolPhase(p.phase, "restore", t))];
      if (p.phase_index && p.phase_total) bits.push(`${p.phase_index}/${p.phase_total}`);
      if (p.merge_steps) bits.push(`${p.merge_step || 0}/${p.merge_steps} ${esc(t("steps"))}`);
      if (p.reindex_total) {
        bits.push(`${p.reindex_done || 0}/${p.reindex_total} ${esc(t("articles"))}`);
      }
      return bits.join(" · ");
    }

    function _uxImLive(live, t) {
      // The per-ITEM form: a trailing clause on that item's own row. The header wants
      // the same facts without the leading separator, so the bits are shared rather
      // than the string sliced.
      const bits = _uxImPhaseBits(live, t);
      return bits ? ` <span class="muted">· ${bits}</span>` : "";
    }

    function _uxImDur(s) {
      s = Math.max(0, Math.round(Number(s) || 0));
      if (s < 60) return `${s}s`;
      const m = Math.floor(s / 60);
      if (m < 60) return `${m}m ${s % 60}s`;
      return `${Math.floor(m / 60)}h ${m % 60}m`;
    }

    // "Show details" (ruling 16): the per-item facts behind the rows. Reads from the
    // SERVER's status, so it is still correct after a reload -- there is no client-side
    // record it could disagree with.
    function _uxImDetails(st, t) {
      const rows = (st.items || []).map((it) => {
        const bits = [`<b>${esc(it.label || it.kind)}</b>`, esc(it.kind), esc(t(_UX_IM_STATE_LABEL[it.state] || it.state))];
        if (it.elapsed_s != null) bits.push(esc(_uxImDur(it.elapsed_s)));
        bits.push(`<span class="muted">${esc(it.path)}</span>`);
        return `<div>${bits.join(" · ")}</div>`;
      });
      if (st.started_at) {
        // fmtDateTime, never toLocaleString: dates render in the APP language, not
        // whatever locale the browser happens to be set to.
        rows.unshift(`<div class="muted">${esc(t("Started"))}: ${esc(fmtDateTime(st.started_at * 1000))}</div>`);
      }
      return rows.join("") || `<span class="muted">${esc(t("No details yet."))}</span>`;
    }

    // Stop the run. The two halves are genuinely different, so the confirmation says
    // which one the user is about to get rather than implying an undo that does not
    // exist for an already-swapped backup.
    async function _uxImStop(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Stop this import? Any backup that has not yet been swapped in is abandoned completely — your corpus is untouched. A backup already merged stays merged (there is no undo); only the remaining work stops, and its re-index resumes later."))) return;
      btn.disabled = true;
      try { await api("/api/backup/import-queue/stop", { method: "POST" }); }
      catch (e) { toast(t("Could not stop the import:") + " " + (e.message || e), "err"); }
      btn.disabled = false;
      _uxImQueuePoll();
    }

    // Reattach to a run already in flight (or just finished) when the dialog opens --
    // the whole point of moving the sequencing server-side (ruling 16).
    async function _uxImReattach() {
      let st = null;
      try { st = await api("/api/backup/import-queue/status"); } catch { return; }
      if (!st || !(st.items || []).length) return;
      _uxImRenderQueue(st);
      if (st.state === "running") { _uxImQueuePoll(); }
    }

    // Leave the (modal) Import dialog while the import keeps running as background
    // jobs — the user asked to keep working meanwhile. The async _uxImRun above is not
    // aborted by closing the dialog, so the sequence continues and finishes; the task
    // manager shows every job (and pauses/resumes the pausable ones — folder + .eml;
    // a volume-corpus merge is atomic, so it runs to completion). A toast reports the
    // outcome. Since 2026-07-29 the SEQUENCING itself lives on the server, so this now
    // genuinely survives a reload: the whole run appears in the task manager as one
    // "Importing …" job, and reopening this dialog reattaches to it (_uxImReattach).
    function _uxImBackground() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dlg = document.getElementById("ux-import");
      if (dlg && dlg.open) dlg.close();
      toast(t("Import continues in the background — watch it in the task manager."));
      if (typeof openTaskManager === "function") openTaskManager();
    }

    // Extra, honest post-import signals a merge-restore's REPORT carries beyond the
    // per-table plan (corpus-delta 2026-07-20) -- pulled out once so every call site
    // (a live run, the legacy-restore loop, and the recovered last-completed-run) feeds
    // the SAME shape into _renderImportSummary. `rep` is a run_restore() report dict;
    // absent/best-effort fields degrade to "no signal" (never a fabricated one).
    function _uxPlanExtras(rep) {
      const r = rep || {};
      const cal = ((r.side_files || {}).state || {})["calendar_feed_imports.json"];
      return {
        delta: r.corpus_delta || null,       // {before, after} cheap-counter snapshot
        reindexed: r.reindexed || null,      // {reindexed, failed} post-merge re-index
        events_added: (cal && cal.added) || 0,
        timings: r.timings || null,          // {stages, wall_s} -- Session A §4, "instrument first"
        // THE PRODUCER for the "still indexing" caveat below. The renderer read this
        // key from the moment the deferral shipped and NOTHING ever wrote it, so the
        // caveat could not render on any path -- a reader with no producer, which is
        // the honesty defect the deferral's own rationale calls "strictly worse" than
        // the wait it replaced. It belongs HERE rather than at the three push sites
        // precisely because this helper exists so every one of them feeds the same
        // shape; adding it at a call site would have fixed one path and left the others.
        reindex_deferred: r.reindex_deferred || null,
      };
    }

    // "How long did this take?" (§4 item 5, "render its existing timings in
    // the completion UI"): a real, measured number per stage, collapsed by
    // default (a full restore has 15+ named stages plus 14 merge-step and
    // several stage-A sub-entries — too many to show at a glance) with the
    // biggest few surfaced first, since THOSE are the evidence base for any
    // future "optimise the measured biggest stage" work. Never a projected/
    // estimated number anywhere here -- every value came straight off the
    // backend's own StageTimings report.
    function _uxStageLabel(name, t) {
      if (name.indexOf("merge_step:") === 0) return `${t("merge step")}: ${name.slice(11)}`;
      if (name.indexOf("stage_a:") === 0) return `${t("stage A")}: ${name.slice(8).replace(/_/g, " ")}`;
      return name.replace(/_/g, " ");
    }
    function _uxFmtS(s) {
      const n = Number(s) || 0;
      return n < 1 ? `${Math.round(n * 1000)} ms` : `${n.toFixed(1)} s`;
    }
    // A whole-run/whole-item duration, which for a real import is hours. _uxFmtS is
    // for STAGE times (sub-second to minutes) and prints "61585.0 s" here, which is a
    // number nobody can read. Kept separate rather than widened: the stage table's
    // format is load-bearing for comparing stages against each other.
    function _uxFmtDur(s) {
      // null/undefined FIRST and explicitly: Number(null) is 0 and isFinite(0) is
      // true, so the natural "keep the finite ones" guard turns a missing
      // measurement into a confident "0.0 s" -- a fabricated number exactly where
      // the payload was honest enough to send nothing (status() sets elapsed_s to
      // null for an item that never started). The recorded house trap.
      if (s === null || s === undefined || s === "") return "—";
      const n = Number(s);
      if (!isFinite(n) || n < 0) return "—";      // no measurement, never a fake 0
      if (n < 60) return `${n.toFixed(n < 10 ? 1 : 0)} s`;
      if (n < 3600) return `${Math.floor(n / 60)} min ${Math.round(n % 60)} s`;
      return `${Math.floor(n / 3600)} h ${Math.round((n % 3600) / 60)} min`;
    }

    // Per-item outcome, kept in ONE place so the badge, the aggregate filter and the
    // run headline can never disagree about what "counted".
    const _UX_OUTCOME = {
      done:        { ok: true,  icon: "✓", label: "Imported",   col: "var(--ok, #4caf50)" },
      error:       { ok: false, icon: "✗", label: "Failed",     col: "var(--err, #d9534f)" },
      cancelled:   { ok: false, icon: "■", label: "Cancelled",  col: "var(--muted, #888)" },
      stopped:     { ok: false, icon: "■", label: "Stopped",    col: "var(--muted, #888)" },
      skipped:     { ok: false, icon: "–", label: "Skipped",    col: "var(--muted, #888)" },
      interrupted: { ok: false, icon: "!", label: "Interrupted", col: "var(--warn, #e0a800)" },
    };
    function _uxOutcome(state) {
      // An ABSENT state is treated as counted: the recovered-last-run path
      // (_uxShowLastCompletedSummary) only ever reads a job whose own status was
      // already "done", so it carries no per-item state and must not be demoted.
      return state === undefined || state === null
        ? _UX_OUTCOME.done
        : (_UX_OUTCOME[state] || { ok: false, icon: "?", label: String(state), col: "var(--muted, #888)" });
    }

    // "Which backup brought what" — the multi-backup ask. One row per queued item,
    // in RUN ORDER (so it lines up with the progress list the user just watched),
    // each with its own article split, its own measured elapsed time and its own
    // outcome. Bars are scaled to the LARGEST item in the run, so the comparison is
    // between the backups actually present; the numbers are printed beside every bar,
    // so nothing rests on reading a width. An item that produced nothing gets no bar
    // rather than a minimum-width one -- a visible sliver would claim a contribution
    // it did not make.
    function _uxPerItemView(rows, t, tf) {
      if (rows.length < 2) return "";   // one item: the headline already IS its story
      const num = (n) => Number(n || 0).toLocaleString();
      const max = rows.reduce((m, r) => Math.max(m, r.total), 0);
      const body = rows.map((r) => {
        const oc = _uxOutcome(r.state);
        const pct = max > 0 ? (r.total / max) * 100 : 0;
        const seg = (v, col) => v > 0 ? `<span style="flex:${v};background:${col}"></span>` : "";
        const bar = r.total > 0
          ? `<div style="width:${pct.toFixed(1)}%;min-width:2px;display:flex;height:10px;border-radius:5px;overflow:hidden">`
            + seg(r.new, "var(--accent, #4a90d9)") + seg(r.dup, "var(--muted-bg, #888)")
            + seg(r.conf, "var(--err, #d9534f)") + `</div>`
          : `<div class="muted" style="font-size:11px">${esc(r.error ? String(r.error).slice(0, 120) : t("nothing imported"))}</div>`;
        const counts = r.total > 0
          ? `${num(r.new)} ${t("imported")} · ${num(r.dup)} ${t("deduplicated")}`
            + (r.conf ? ` · ${num(r.conf)} ${t("conflicts (your version kept)")}` : "")
          : "";
        return `<tr>`
          + `<td style="padding:3px 8px 3px 0;white-space:nowrap"><span style="color:${oc.col}">${esc(oc.icon)}</span> ${esc(r.title)}</td>`
          + `<td style="padding:3px 8px;width:40%">${bar}</td>`
          + `<td style="padding:3px 8px;font-size:12px" class="muted">${esc(counts)}</td>`
          + `<td style="padding:3px 0;text-align:right;font-size:12px;white-space:nowrap" class="muted">${esc(_uxFmtDur(r.elapsed_s))}</td>`
          + `</tr>`;
      }).join("");
      return `<div style="margin-top:10px">`
        + `<div class="muted" style="font-size:12px;margin-bottom:2px">`
        + `${esc(t("What each backup brought"))} <span style="opacity:.7">${esc(tf("(bars are relative to the largest of the {n} items)", { n: rows.length }))}</span></div>`
        + `<table style="width:100%;border-collapse:collapse">${body}</table></div>`;
    }
    function _uxTimingsView(timings, t, tf) {
      if (!timings || !timings.stages) return "";
      const entries = Object.entries(timings.stages);
      if (!entries.length) return "";
      const sorted = entries.slice().sort((a, b) => b[1] - a[1]);
      const top = sorted.slice(0, 6);
      const rows = top.map(([name, secs]) =>
        `<tr><td style="padding:1px 8px 1px 0">${esc(_uxStageLabel(name, t))}</td>`
        + `<td style="text-align:right;padding:1px 0" class="muted">${esc(_uxFmtS(secs))}</td></tr>`
      ).join("");
      const restCount = entries.length - top.length;
      const restNote = restCount > 0
        ? `<div class="muted" style="font-size:11px;margin-top:2px">${esc(tf("+ {n} more stages", { n: restCount }))}</div>`
        : "";
      return `<details style="margin-top:6px"><summary class="muted">`
        + `${esc(tf("How long did this take? ({wall})", { wall: _uxFmtS(timings.wall_s) }))}</summary>`
        + `<table style="width:100%;font-size:12px;margin-top:4px">${rows}</table>${restNote}</details>`;
    }

    // "How your corpus grew": a plain BEFORE -> AFTER table over the backend's cheap
    // counter snapshot (never a post-merge re-scan — merge.py's _corpus_snapshot is
    // COUNT/DISTINCT/MIN/MAX on indexed columns only). One row per dimension named
    // by the ruling; the date-range row shows the actual span rather than a bare
    // number since a day-count alone would hide what actually moved.
    function _uxCorpusDeltaView(before, after, t) {
      if (!before || !after) return "";
      const num = (n) => Number(n || 0).toLocaleString();
      const fmtDate = (iso) => iso ? String(iso).slice(0, 10) : "—";
      const dims = [
        [t("Articles"), before.articles, after.articles],
        [t("Sources"), before.sources, after.sources],
        [t("Languages"), before.languages, after.languages],
        [t("Countries"), before.countries, after.countries],
        [t("Keywords"), before.keywords, after.keywords],
      ];
      const rows = dims.map(([label, b, a]) => {
        const d = (a || 0) - (b || 0);
        const dTxt = d === 0 ? "±0" : (d > 0 ? "+" + num(d) : num(d));
        const dCol = d > 0 ? "var(--ok, #4caf50)" : (d < 0 ? "var(--err, #d9534f)" : "");
        return `<tr><td style="padding:2px 8px 2px 0">${esc(label)}</td>`
          + `<td style="text-align:right;padding:2px 8px" class="muted">${esc(num(b))}</td>`
          + `<td style="text-align:right;padding:2px 8px">${esc(num(a))}</td>`
          + `<td style="text-align:right;padding:2px 0"><b style="color:${dCol}">${esc(dTxt)}</b></td></tr>`;
      }).join("");
      const dateRow = `<tr><td style="padding:2px 8px 2px 0">${esc(t("Date range"))}</td>`
        + `<td style="text-align:right;padding:2px 8px" class="muted">${esc(fmtDate(before.date_min))} – ${esc(fmtDate(before.date_max))}</td>`
        + `<td style="text-align:right;padding:2px 8px" colspan="2">${esc(fmtDate(after.date_min))} – ${esc(fmtDate(after.date_max))}</td></tr>`;
      return `<div style="margin-top:8px">`
        + `<div class="muted" style="font-size:12px;margin-bottom:2px">${esc(t("How your corpus grew"))}</div>`
        + `<table style="width:100%;font-size:13px;border-collapse:collapse">`
        + `<thead><tr><th></th><th style="text-align:right">${esc(t("Before"))}</th><th style="text-align:right">${esc(t("After"))}</th><th></th></tr></thead>`
        + `<tbody>${rows}${dateRow}</tbody></table></div>`;
    }

    // Render "what was imported" as a prominent, honest success view (maintainer field
    // ask 2026-07-02: "a clear view of what was successfully imported…"). ROOT-CAUSED
    // 2026-07-20 (maintainer, after merging a 10 GB corpus: "4,855,433 imported… I'm
    // sure it doesn't contain 5 million articles"): the old headline summed EVERY
    // merged TABLE (articles, keyword mentions, links, dates, custody rows, …) under
    // the single unlabeled word "imported" — mentions alone outnumber articles by an
    // order of magnitude, so the row-sum read as an article count and was wrong.
    // REDESIGNED: (1) an ARTICLES-first headline (the user's own unit), plus a labeled
    // per-type breakdown — the old row-sum survives ONLY as an explicitly-labeled
    // "database records, all types" figure, never unlabeled again; (2) a CORPUS-DELTA
    // view (before -> after per dimension) from the backend's cheap-counter snapshot;
    // (3) an honest WORK-INDUCED queue — new sources to look over, articles still
    // awaiting indexing (real re-index failures, never fabricated), discovery
    // candidates added. (A source's QUALIFICATION status is not yet a built feature —
    // deliberately NOT claimed here; see the code comment on newSources below.) A
    // tally-only run (newsletters/large-data — no per-table plan) keeps its ORIGINAL
    // generic imported/deduplicated headline unchanged. Every count is a real backend
    // number; nothing here is fabricated.
    function _renderImportSummary(host, summaries, run) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, vars) => {
        let out = s;
        if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null) ? m : String(vars[k]));
        return out;
      });
      if (!summaries || !summaries.length) { host.innerHTML = ""; return; }

      // ARTICLES — the headline, in the user's own unit. plan.articles is the real
      // per-article tally; no OTHER plan table is ever added to it.
      let artNew = 0, artDup = 0, artConf = 0;
      // "database records, all types" (ruling 2026-07-20): the SAME cross-table
      // row-sum the old headline computed, kept ONLY as an explicitly-labeled
      // catch-all — never presented as an article count again.
      let allNew = 0, allDup = 0, allConf = 0;
      // Per-type labeled breakdown, the ruling's own list: sources · keywords ·
      // mentions · links · law docs · wiki pages · events · analyses.
      const perType = [
        { keys: ["sources"], label: t("Sources"), n: 0 },
        { keys: ["keywords"], label: t("Keywords"), n: 0 },
        { keys: ["keyword_mentions"], label: t("Keyword mentions"), n: 0 },
        { keys: ["article_links"], label: t("Links"), n: 0 },
        { keys: ["law_documents", "law_revisions"], label: t("Law docs"), n: 0 },
        { keys: ["wiki_pages", "wiki_revisions"], label: t("Wiki pages"), n: 0 },
        { keys: ["article_analyses"], label: t("Analyses"), n: 0 },
      ];
      // Fallback headline for a tally-only run (no plan at all — newsletters/large
      // data): reproduces the ORIGINAL generic imported/deduplicated stat, unchanged.
      let tallyNew = 0, tallyDup = 0;
      let newSources = 0, discoveryAdded = 0, eventsAdded = 0, unindexed = 0;
      // Source QUALIFICATION carried by this import (field ask 2026-08-10). Counts
      // only; `qualEngines` maps criteria version -> n, which is the "by which
      // engine" half — never inferred, only what the incoming stamp recorded.
      let qualGained = 0, disqGained = 0, qualKept = 0, qualDisagreed = 0;
      const qualEngines = {};
      // Metadata a DUPLICATE article contributed (field question 2026-08-10). The
      // article was not stored again; only fields this corpus never had were filled.
      let metaEnriched = 0;
      const metaByColumn = {};
      let deltaBefore = null, deltaAfter = null;
      const extra = [];  // empty/errored newsletters, surfaced honestly
      const detail = [];
      let sawPlan = false;
      // One row per queued item, in run order, for the per-backup view -- built for
      // EVERY item including the ones that contributed nothing, because "this backup
      // failed" is the single most important thing a multi-backup conclusion can say.
      const perItem = [];
      for (const sm of summaries) {
        const counted = _uxOutcome(sm.state).ok;
        if (sm.plan) {
          const a = sm.plan.articles || {};
          perItem.push({
            title: sm.title, state: sm.state, error: sm.error, elapsed_s: sm.elapsed_s,
            new: counted ? (a.new || 0) : 0, dup: counted ? (a.duplicate || 0) : 0,
            conf: counted ? (a.conflict || 0) : 0,
            total: counted ? ((a.new || 0) + (a.duplicate || 0) + (a.conflict || 0)) : 0,
          });
        } else {
          const tl0 = sm.tally || {};
          const nNew = counted ? ((tl0.stored || 0) + (tl0.restored || 0)) : 0;
          const nDup = counted ? ((tl0.duplicate || 0) + (tl0.skipped || 0)) : 0;
          perItem.push({
            title: sm.title, state: sm.state, error: sm.error, elapsed_s: sm.elapsed_s,
            new: nNew, dup: nDup, conf: 0, total: nNew + nDup,
          });
        }
        // An item that failed, was cancelled, skipped or interrupted contributes
        // NOTHING to the aggregate. Its numbers are absent or partial by definition,
        // and folding them in would put a half-finished merge behind a "successful"
        // headline -- the defect this whole block exists to close.
        if (!counted) continue;
        if (sm.plan) {
          sawPlan = true;
          const p = sm.plan;
          const art = p.articles || {};
          artNew += art.new || 0; artDup += art.duplicate || 0; artConf += art.conflict || 0;
          for (const c of Object.values(p)) {
            if (c && typeof c === "object") {
              allNew += c.new || 0; allDup += c.duplicate || 0; allConf += c.conflict || 0;
            }
          }
          for (const row of perType) {
            for (const k of row.keys) { const c = p[k]; if (c) row.n += c.new || 0; }
          }
          // New sources: reported plainly (worth a look in Source Management). The
          // qualification lifecycle DOES exist now (Source.status + the admission gate
          // in select_sources), so the qualification block below states what this
          // import actually carried; this line stays the plain count of added sources,
          // qualified or not.
          newSources += (p.sources && p.sources.new) || 0;
          const pm = p._article_metadata;
          if (pm) {
            metaEnriched += pm.articles_enriched || 0;
            for (const [c, n] of Object.entries(pm.by_column || {})) {
              metaByColumn[c] = (metaByColumn[c] || 0) + (n || 0);
            }
          }
          const pq = p._source_qualification;
          if (pq) {
            qualGained += (pq.introduced_qualified || 0) + (pq.adopted_qualified || 0);
            disqGained += (pq.introduced_disqualified || 0) + (pq.adopted_disqualified || 0);
            qualKept += pq.local_verdict_kept || 0;
            qualDisagreed += pq.local_verdict_disagreed || 0;
            for (const [eng, n] of Object.entries(pq.engines || {})) {
              qualEngines[eng] = (qualEngines[eng] || 0) + (n || 0);
            }
          }
          discoveryAdded += (p.source_candidates && p.source_candidates.new) || 0;
          detail.push({ title: sm.title, body: _v2PlanTable(p) + _uxTimingsView(sm.timings, t, tf) });

          if (sm.events_added) eventsAdded += sm.events_added;
          // Real re-index failures only — reindex_imported_articles ran (or was
          // skipped entirely; either way the true count of never-reindexed imported
          // articles is knowable, never guessed).
          if (sm.reindexed) unindexed += sm.reindexed.failed || 0;
          else if (art.new) unindexed += art.new;  // re-index was skipped for this run
          if (sm.delta && sm.delta.before && sm.delta.after) {
            if (!deltaBefore) deltaBefore = sm.delta.before;
            deltaAfter = sm.delta.after;
          }
        } else {
          const tl = sm.tally || {};
          tallyNew += (tl.stored || 0) + (tl.restored || 0);
          tallyDup += (tl.duplicate || 0) + (tl.skipped || 0);
          if (tl.empty)  extra.push(`${tl.empty} ${t("empty")}`);
          if (tl.errors) extra.push(`${tl.errors} ${t("errors")}`);
          detail.push({ title: sm.title, body: `<div class="hint">${(sm.lines || []).map(esc).join(" · ")}</div>` });
        }
      }
      if (eventsAdded) perType.push({ keys: [], label: t("Events"), n: eventsAdded });

      const num = (n) => Number(n || 0).toLocaleString();
      const seg = (v, col) => v > 0 ? `<span style="flex:${v};background:${col}"></span>` : "";
      const stat = (n, label, col) =>
        `<div style="text-align:center;min-width:88px"><div style="font-size:22px;font-weight:700;color:${col}">${esc(num(n))}</div>`
        + `<div class="muted" style="font-size:12px">${esc(label)}</div></div>`;

      let headline, bar;
      if (sawPlan) {
        // HEADLINE: articles, in the user's own unit — never a cross-table row-sum.
        const artTotal = artNew + artDup + artConf;
        bar = artTotal > 0
          ? `<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin:8px 0 4px">`
            + seg(artNew, "var(--accent, #4a90d9)") + seg(artDup, "var(--muted-bg, #888)")
            + seg(artConf, "var(--err, #d9534f)") + `</div>`
          : "";
        headline =
          `<div class="muted" style="font-size:12px">${esc(t("Articles"))}</div>`
          + `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:2px">`
          + stat(artNew, t("imported"), "var(--accent, #4a90d9)")
          + stat(artDup, t("deduplicated"), "")
          + (artConf ? stat(artConf, t("conflicts (your version kept)"), "var(--err, #d9534f)") : "")
          + `</div>`;
      } else {
        // No per-table plan at all (newsletters/large-data only) — the ORIGINAL
        // generic stat, unchanged.
        const tallyTotal = tallyNew + tallyDup;
        bar = tallyTotal > 0
          ? `<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin:8px 0 4px">`
            + seg(tallyNew, "var(--accent, #4a90d9)") + seg(tallyDup, "var(--muted-bg, #888)") + `</div>`
          : "";
        headline = `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:6px">`
          + stat(tallyNew, t("imported"), "var(--accent, #4a90d9)")
          + stat(tallyDup, t("deduplicated"), "")
          + `</div>`;
      }

      const typeLabels = perType.filter((r) => r.n > 0).map((r) => `${num(r.n)} ${r.label}`);
      const catchAll = allNew ? [`${num(allNew)} ${t("database records, all types")}`] : [];
      const typeBlock = (typeLabels.length || catchAll.length)
        ? `<div class="muted" style="font-size:12px;margin-top:4px">${typeLabels.concat(catchAll).map(esc).join(" · ")}</div>`
        : "";

      // Positive-but-honest framing (ruling: "imports should give positive
      // feedback" — the delta IS the good news, no fabricated praise).
      const growLine = (deltaBefore && deltaAfter)
        ? `<div style="margin-top:6px">${esc(tf(
            "Your corpus grew by {articles} articles from {sources} new sources spanning {languages} new languages.",
            {
              articles: num(Math.max(0, deltaAfter.articles - deltaBefore.articles)),
              sources: num(Math.max(0, deltaAfter.sources - deltaBefore.sources)),
              languages: num(Math.max(0, deltaAfter.languages - deltaBefore.languages)),
            }
          ))}</div>`
        : "";
      const deltaView = _uxCorpusDeltaView(deltaBefore, deltaAfter, t);

      // WORK INDUCED: stated honestly, only when there is actually something queued.
      const queueLines = [];
      if (newSources > 0) queueLines.push(`${num(newSources)} ${t("New sources")}`);
      if (unindexed > 0) queueLines.push(`${num(unindexed)} ${t("Articles awaiting indexing")}`);
      if (discoveryAdded > 0) queueLines.push(`${num(discoveryAdded)} ${t("Discovery candidates")}`);
      // SOURCE QUALIFICATION carried by this import (field ask 2026-08-10: "display the
      // amount of qualified sources imported"). Rendered only when the import actually
      // carried a verdict — a run that carried none says nothing rather than "0", which
      // would read as a finding about the backup instead of an absence of data.
      // Every line is label:value rather than a sentence with the count inside it —
      // an interpolated count cannot conjugate, and this app has no CLDR plural rules,
      // so a "{n} sources were ..." frame is wrong in most of the twelve locales.
      let qualBlock = "";
      if (qualGained || disqGained) {
        const lead = [];
        if (qualGained) lead.push(tf("Qualified sources added: {n}", { n: num(qualGained) }));
        if (disqGained) lead.push(tf("Arrived disqualified: {n}", { n: num(disqGained) }));
        const sub = [];
        // Local-wins, stated rather than left to be inferred from numbers that do not
        // add up: a verdict this machine reached itself is never overwritten.
        if (qualKept) sub.push(tf("Already judged here, kept: {n}", { n: num(qualKept) }));
        if (qualDisagreed) sub.push(tf("Backup disagreed, your verdict kept: {n}", { n: num(qualDisagreed) }));
        const engNames = Object.keys(qualEngines);
        if (engNames.length) {
          sub.push(tf("Judged by: {engines}", {
            engines: engNames.map((e) => `${e} (${num(qualEngines[e])})`).join(", "),
          }));
        }
        qualBlock =
          `<div style="margin-top:8px"><div style="font-size:13px">`
          + esc("✓ " + lead.join(" · ")) + `</div>`
          + (sub.length
              ? `<div class="muted" style="font-size:12px">${esc(sub.join(" · "))}</div>`
              : "")
          + `</div>`;
      }

      // Only when something was actually filled: a run that gained nothing says nothing,
      // rather than showing a 0 that reads as a finding about the backup.
      let metaBlock = "";
      if (metaEnriched) {
        const cols = Object.keys(metaByColumn).sort()
          .map((c) => `${c} (${num(metaByColumn[c])})`).join(", ");
        metaBlock =
          `<div style="margin-top:8px"><div style="font-size:13px">`
          + esc("\u2713 " + tf("Existing articles that gained metadata: {n}", { n: num(metaEnriched) }))
          + `</div>`
          + (cols ? `<div class="muted" style="font-size:12px">${esc(tf("Fields filled: {fields}", { fields: cols }))}</div>` : "")
          + `</div>`;
      }

      const queueBlock = queueLines.length
        ? `<div class="muted" style="font-size:12px;margin-top:6px">${queueLines.map(esc).join(" · ")}</div>`
        : "";

      const extraLine = extra.length
        ? `<div class="muted" style="font-size:12px;margin-top:4px">${esc(extra.join(" · "))}</div>` : "";
      const detailBlocks = detail.map((d) =>
        `<details style="margin-top:6px"><summary class="muted">${esc(d.title)}</summary>${d.body}</details>`).join("");

      // OUTCOME-AWARE HEADER. This was hardcoded "✓ Import successful", so a run in
      // which two of six backups failed announced itself exactly like a clean one.
      // The verdict is derived from the ITEMS (the run state agrees, but the items
      // are what the numbers came from, so they are the honest source), and the
      // n-of-m line is stated whenever more than one thing was queued.
      const failed = perItem.filter((r) => !_uxOutcome(r.state).ok);
      const okCount = perItem.length - failed.length;
      const allOk = failed.length === 0;
      const stoppedOnly = !allOk && failed.every((r) => r.state === "cancelled" || r.state === "stopped" || r.state === "skipped");
      const head = allOk
        ? { icon: "✓", text: t("Import successful"), col: "var(--ok, #4caf50)" }
        : (stoppedOnly
            ? { icon: "■", text: t("Import stopped — not everything was imported"), col: "var(--muted, #888)" }
            : { icon: "⚠", text: t("Import finished with errors"), col: "var(--warn, #e0a800)" });
      const countLine = perItem.length > 1
        ? `<div class="muted" style="font-size:12px;margin-top:2px">`
          + esc(tf("{done} of {total} backups imported", { done: okCount, total: perItem.length }))
          + (run && run.elapsed_s != null ? ` · ${esc(tf("{d} in total", { d: _uxFmtDur(run.elapsed_s) }))}` : "")
          + `</div>`
        : "";
      // Only the counted items are behind the aggregate, so say so rather than
      // letting the totals imply the whole queue succeeded.
      const excludedNote = failed.length
        ? `<div class="muted" style="font-size:12px;margin-top:4px">`
          + esc(tf("The totals below cover the {n} that completed; the rest are listed with their outcome.", { n: okCount }))
          + `</div>`
        : "";

      // STILL INDEXING (2026-08-03). The import no longer blocks on the re-index, so
      // "import finished" no longer means "fully indexed" -- those articles carry no
      // keywords yet and are absent from analytics. Deferring it SILENTLY would trade a
      // visible three-hour wait for an invisible incomplete corpus, which is strictly
      // worse, so the deferral is stated here with its real count. An unreadable backlog
      // says so rather than showing 0: "could not read" and "nothing pending" must never
      // look alike.
      let indexingLine = "";
      const _rxd = summaries.map((s2) => (s2 && s2.report && s2.report.reindex_deferred) || s2.reindex_deferred)
        .filter(Boolean);
      if (_rxd.length) {
        let pend = 0, unreadable = false;
        for (const r of _rxd) {
          if (typeof r.articles_pending === "number") pend += r.articles_pending;
          else unreadable = true;
        }
        const body = unreadable && !pend
          ? t("Indexing continues in the background. The number still to index could not be read.")
          : tf("Indexing continues in the background: {n} article(s) still to index. Until it finishes they carry no keywords and are absent from analytics.",
               { n: pend.toLocaleString() });
        indexingLine =
          `<div class="card-caveat" style="margin-top:6px">${esc(body)}</div>`;
      }

      host.innerHTML =
        `<div class="card" style="margin-top:8px;padding:12px;border-left:3px solid ${head.col}">`
        + `<div style="font-weight:700;font-size:15px">${esc(head.icon)} ${esc(head.text)}</div>`
        + countLine + excludedNote
        + growLine + headline + bar + typeBlock + extraLine + qualBlock + metaBlock + indexingLine + queueBlock
        + _uxPerItemView(perItem, t, tf)
        + deltaView
        + `<div class="muted" style="font-size:12px;margin-top:6px">${esc(t("Additive restore: nothing in your corpus was replaced or deleted. Duplicates were skipped."))}</div>`
        + `<div style="margin-top:8px"><div class="muted" style="font-size:12px;margin-bottom:2px">${esc(t("Details by source"))}</div>${detailBlocks}</div>`
        + `</div>`;
    }

    async function folderBackupPlan(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dest = ($("fb-dest").value || "").trim();
      if (!dest) { toast(t("Enter a destination folder."), "warn"); return; }
      btn.disabled = true; $("fb-plan").textContent = t("Checking…");
      try {
        const d = await api("/api/backup/folder/plan",
          { method: "POST", body: JSON.stringify({ dest, categories: _fbCats() }) });
        $("fb-plan").innerHTML =
          `${(d.files || 0).toLocaleString()} ${esc(t("files"))} · ${esc(t("needs"))} <b>${esc(d.needed_human)}</b> · ` +
          `${esc(d.free_human)} ${esc(t("free"))}` +
          (d.enough_space ? "" : ` <span class="warn">— ${esc(t("not enough space"))}</span>`);
      } catch (e) { $("fb-plan").innerHTML = `<span class="note err">${esc(e.message)}</span>`; }
      finally { btn.disabled = false; }
    }
    async function folderBackupStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dest = ($("fb-dest").value || "").trim();
      if (!dest) { toast(t("Enter a destination folder."), "warn"); return; }
      btn.disabled = true;
      try {
        await api("/api/backup/folder/start",
          { method: "POST", body: JSON.stringify({ dest, categories: _fbCats() }) });
        _fbStartPoll();
      } catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
    }
    async function folderRestoreStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = ($("fb-src").value || "").trim();
      if (!src) { toast(t("Enter a folder to restore from."), "warn"); return; }
      btn.disabled = true;
      try {
        await api("/api/backup/folder/restore",
          { method: "POST", body: JSON.stringify({ src, categories: _fbCats() }) });
        _fbStartPoll();
      } catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
    }
    async function folderBackupAction(action, btn) {
      btn.disabled = true;
      try { await api("/api/backup/folder/" + action, { method: "POST" }); _fbRefresh(); }
      catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
    }

    // Large ENCRYPTED backup as a volume set + Reed-Solomon parity (field test
    // 2026-06-24; slice 1c). Server-side folder, cancellable background job.
    // Browser-unverified (fork-3) — node-checked + invariant-guarded.
    let _volPollTimer = null;
    async function _volRefresh(progId, btn, cancelId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, vars) => {
        let out = s;
        if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null) ? m : String(vars[k]));
        return out;
      });
      const prog = $(progId);
      try {
        const s = await api("/api/backup/v2/volumes/status");
        const p = s.progress || {};
        const phase = p.phase || s.state;
        const vols = p.volumes_written ? (" · " + p.volumes_written + " " + t("volumes")) : "";
        const cancel = cancelId ? $(cancelId) : null;
        if (s.state === "running") {
          if (prog) prog.textContent = (s.mode === "restore" ? t("Restoring") : t("Backing up")) + "… " + phase + vols;
          if (cancel) cancel.style.display = "";
        } else {
          if (_volPollTimer) { clearInterval(_volPollTimer); _volPollTimer = null; }
          if (cancel) cancel.style.display = "none";
          if (btn) btn.disabled = false;
          const sum = s.summary || {};
          if (s.state === "done" && s.mode === "restore") {
            if (prog) prog.textContent = t("Restore complete.");
          } else if (s.state === "done") {
            const par = sum.parity_available === false ? (" " + t("(volumes only — parity needs the analysis features)")) : "";
            // "How long did this take?" — the export side's own real, measured
            // wall/gate-held numbers (stream_backup.py), same "instrument first"
            // ask as the restore side; gate_held_s is the corpus writes-paused
            // window, always <= wall_s.
            const timing = (typeof sum.wall_s === "number")
              ? " (" + tf("took {wall}, {gate} with writes paused", {
                  wall: _uxFmtS(sum.wall_s), gate: _uxFmtS(sum.gate_held_s || 0),
                }) + ")"
              : "";
            if (prog) prog.textContent = t("Backup complete:") + " " + (sum.volumes || "?") + " " + t("volumes") + par + timing;
          } else if (s.state === "cancelled") {
            if (prog) prog.textContent = t("Cancelled.");
          } else if (s.state === "error") {
            if (prog) prog.textContent = t("Failed:") + " " + (s.error || t("unknown error"));
          }
        }
      } catch (e) { if (prog) prog.textContent = t("Status check failed."); if (btn) btn.disabled = false; }
    }
    function _volStartPoll(progId, btn, cancelId) {
      if (_volPollTimer) clearInterval(_volPollTimer);
      _volRefresh(progId, btn, cancelId);
      _volPollTimer = setInterval(() => _volRefresh(progId, btn, cancelId), 1500);
    }
    async function volBackupStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dest = ($("vb-dest").value || "").trim();
      const pass = $("vb-pass").value || "";
      if (!dest) { toast(t("Choose a destination folder."), "warn"); return; }
      if (!pass) { toast(t("Enter a passphrase."), "warn"); return; }
      btn.disabled = true;
      const prog = $("vb-progress"); if (prog) prog.textContent = t("Starting…");
      try {
        await api("/api/backup/v2/volumes/start",
          { method: "POST", body: JSON.stringify({ dest, passphrase: pass, include_newsletters: true, parity_fraction: 0.1 }) });
        _volStartPoll("vb-progress", btn, "vb-cancel");
      } catch (e) { if (prog) prog.textContent = (e.message || e); btn.disabled = false; }
    }
    async function volBackupCancel(_btn) {
      try { await api("/api/backup/v2/volumes/cancel", { method: "POST" }); } catch (e) { /* best effort */ }
    }
    async function volRestoreStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = ($("vb-src").value || "").trim();
      const pass = $("vb-rpass").value || "";
      if (!src) { toast(t("Choose a folder to restore from."), "warn"); return; }
      if (!pass) { toast(t("Enter the passphrase."), "warn"); return; }
      if (!confirm(t("Restore merges this backup into your corpus (additive — nothing is replaced). Continue?"))) return;
      btn.disabled = true;
      const prog = $("vb-rprogress"); if (prog) prog.textContent = t("Starting…");
      try {
        await api("/api/backup/v2/volumes/restore",
          { method: "POST", body: JSON.stringify({ src, passphrase: pass }) });
        _volStartPoll("vb-rprogress", btn, null);
      } catch (e) { if (prog) prog.textContent = (e.message || e); btn.disabled = false; }
    }
    function _fbStartPoll() {
      if (_fbPoll) clearInterval(_fbPoll);
      _fbRefresh();
      _fbPoll = setInterval(_fbRefresh, 1500);
    }
    async function _fbRefresh() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prog = $("fb-progress"); if (!prog) return;
      let s;
      try { s = await api("/api/backup/folder/status"); } catch (e) { return; }
      const active = s.state === "running" || s.state === "paused";
      if (!active && _fbPoll) { clearInterval(_fbPoll); _fbPoll = null; }
      $("fb-controls").style.display = active ? "" : "none";
      if ($("fb-pause")) $("fb-pause").style.display = s.state === "running" ? "" : "none";
      if ($("fb-resume")) $("fb-resume").style.display = s.state === "paused" ? "" : "none";
      const p = s.progress || {};
      const verb = s.mode === "restore" ? t("Restoring") : t("Backing up");
      if (active) {
        const pct = p.bytes_total ? Math.round(100 * (p.bytes_copied || 0) / p.bytes_total) : 0;
        prog.innerHTML = `${esc(verb)}… ${pct}% · ${(p.copied || 0)} ${esc(t("copied"))}, ` +
          `${(p.skipped || 0)} ${esc(t("skipped"))}` + (s.state === "paused" ? ` (${esc(t("paused"))})` : "");
      } else if (s.state === "done") {
        prog.innerHTML = `<b>${esc(t("Done."))}</b> ${(p.copied || 0)} ${esc(t("copied"))}, ` +
          `${(p.restored || 0)} ${esc(t("restored"))}, ${(p.skipped || 0)} ${esc(t("skipped"))}.`;
      } else if (s.state === "error") {
        prog.innerHTML = `<span class="note err">${esc(s.error || t("failed"))}</span>`;
      } else { prog.textContent = ""; }
    }

    function _v2PlanTable(plan) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const rows = Object.entries(plan || {})
        .map(([tbl, c]) => ({tbl, new: c.new || 0, dup: c.duplicate || 0, conf: c.conflict || 0, conflicts: c.conflicts || []}))
        .sort((a, b) => (b.new + b.conf) - (a.new + a.conf));
      const active = rows.filter(r => r.new || r.dup || r.conf);
      const quiet = rows.length - active.length;
      let html = `<table style="width:100%;font-size:13px;border-collapse:collapse"><thead><tr>` +
        `<th style="text-align:left">${esc(t("Data"))}</th><th>${esc(t("New"))}</th>` +
        `<th>${esc(t("Already present"))}</th><th>${esc(t("Conflicts (your version kept)"))}</th></tr></thead><tbody>`;
      for (const r of active) {
        html += `<tr><td style="padding:2px 6px">${esc(r.tbl)}</td>` +
          `<td style="text-align:center">${r.new ? `<b>${r.new}</b>` : "0"}</td>` +
          `<td style="text-align:center" class="muted">${r.dup}</td>` +
          `<td style="text-align:center">${r.conf ? `<b>${r.conf}</b>` : "0"}</td></tr>`;
        if (r.conflicts.length) {
          const det = r.conflicts.slice(0, 5).map(c => esc(JSON.stringify(c))).join("<br>");
          html += `<tr><td colspan="4" class="muted" style="font-size:12px;padding:0 6px 6px"><details><summary>` +
            esc(t("conflict samples (local value kept)")) + `</summary>${det}</details></td></tr>`;
        }
      }
      html += `</tbody></table>`;
      if (!active.length) html = `<div class="hint">${esc(t("Nothing new: every row in this archive is already in your corpus."))}</div>` ;
      if (quiet > 0) html += `<div class="muted" style="font-size:12px;margin-top:4px">${quiet} ${esc(t("further table(s) with no changes."))}</div>`;
      return html;
    }
    // Encryption auto-detect (field test 2026-06-22 #10): read the chosen file's
    // first 8 bytes LOCALLY (no upload-to-check) and look for the OOENC1 magic — the
    // exact same signature read_artifact uses — so the passphrase field appears ONLY
    // for an encrypted backup; a plaintext archive needs none. Degrades safely: on any
    // read error it just shows the field (the old always-visible behaviour).


    // restoreBackup() (destructive replace-restore) was REMOVED 2026-06-13:
    // restore is additive-only via the merge restore (Settings → Data & backup).

    // -- Safety (Theme 2): encrypted backup/restore, fetch mode, panic ------ //
    async function loadFetchMode() {
      try {
        const s = await api("/api/safety/settings");
        if ($("fetch-mode")) $("fetch-mode").value = s.fetch_mode || "transparent";
        if ($("http-proxy")) $("http-proxy").value = s.http_proxy || "";
        if ($("discovery-external")) $("discovery-external").checked = !!s.discovery_external_enabled;
        onFetchModeChange();
      } catch (e) { /* safety API unavailable -> leave defaults */ }
    }
    function onFetchModeChange() {
      const protectedMode = $("fetch-mode") && $("fetch-mode").value === "protected";
      if ($("http-proxy")) $("http-proxy").required = protectedMode;
    }
    async function saveFetchMode() {
      const body = {fetch_mode: $("fetch-mode").value, http_proxy: $("http-proxy").value.trim()};
      try {
        await api("/api/safety/settings", {method: "PUT", body: JSON.stringify(body)});
        toast("Fetch mode saved.");
      } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }
    async function saveDiscoveryExternal() {
      // ETH-02/RM-03: the one external-service call is an explicit, knowing opt-in.
      const on = $("discovery-external").checked;
      try {
        await api("/api/safety/settings",
          {method: "PUT", body: JSON.stringify({discovery_external_enabled: on})});
        $("discovery-external-result").textContent = on
          ? "Enabled: topic-discovery queries will be sent to DuckDuckGo."
          : "Disabled (the default): no topic query leaves this machine.";
        toast(on ? "External topic discovery enabled." : "External topic discovery disabled.");
      } catch (e) {
        $("discovery-external").checked = !on;  // revert the visual state on failure
        toast(_failMsg("Save failed: {error}", e), "err");
      }
    }
    // -- At-rest encryption (PR-E): doctor attestation + one-way encrypt ----- //
    async function loadAtRestState() {
      const box = $("atrest-state"); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/system/doctor");
        const word = (s) => s.state === "encrypted" ? t("Encrypted (SQLCipher 4)")
                          : s.state === "plaintext" ? t("NOT encrypted") : t("not created yet");
        box.innerHTML =
          `<div>${esc(t("Corpus"))}: <b>${esc(word(d.corpus))}</b>` +
          (d.corpus.cipher ? ` <span class="muted">${esc(d.corpus.cipher)}</span>` : "") + `</div>` +
          `<div>${esc(t("Custody log"))}: <b>${esc(word(d.custody_log))}</b></div>`;
        $("atrest-encrypt").style.display = d.corpus.state === "plaintext" ? "" : "none";
      } catch (e) { box.textContent = e.message; }
    }
    async function encryptCorpus(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const msg = $("atrest-msg");
      if (!$("atrest-consent").checked) { msg.textContent = t("Tick the consent box first."); return; }
      btn.disabled = true; msg.textContent = t("Encrypting — this rewrites the whole database…");
      try {
        const r = await api("/api/system/encrypt-db", { method: "POST", body: JSON.stringify({
          passphrase: $("atrest-pw1").value, confirm: $("atrest-pw2").value, consent: true })});
        msg.textContent = "";
        toast(t("Encrypted. Your passphrase is now required at every start — there is no recovery."), "ok");
        loadAtRestState();
      } catch (e) { msg.textContent = e.message; }
      finally { btn.disabled = false; }
    }

    // encryptedRestore() (destructive replace-restore) was REMOVED 2026-06-13:
    // restore is additive-only via the merge restore (the signed backup artifact).
    async function panicWipe() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Security dialog must be readable in the operator's language (field test
      // 2026-06-19 #64). The typed keyword stays the literal ASCII "WIPE" so the
      // confirmation never depends on locale-specific input.
      if (!confirm(t("PANIC WIPE: irreversibly delete the corpus, keys and caches on this machine?") + "\n\n" +
                   t("This cannot be undone. Type-confirm follows."))) return;
      if (prompt(t("To confirm, type WIPE in capitals:")) !== "WIPE") {
        toast(t("Panic wipe cancelled."), "err"); return; }
      try {
        // Phase 1 — instant crypto-erase (destroys the SQLCipher salt; fast at any size).
        const r = await api("/api/safety/panic", {method: "POST", body: JSON.stringify({confirm: true})});
        const plaintext = r.encrypted_corpus === false;
        // Phase 2 — OPTIONAL full free-space overwrite, offered honestly per store state.
        const rec = plaintext
          ? t("Your store was not encrypted, so a full disk-overwrite is recommended before you stop.")
          : t("For defence-in-depth against forensic recovery, you can also overwrite the freed disk space. This is optional — the corpus is already cryptographically unrecoverable.");
        $("panic-result").innerHTML =
          `<span class="pill warn">crypto-erased</span> ${r.files_wiped}/${r.files_seen} files. ` +
          `${esc(t("The corpus key is destroyed — the encrypted store is now permanently unrecoverable."))} ` +
          `<span class="muted">${esc(r.limit)}</span>` +
          `<div class="hint" style="margin-top:8px">${esc(rec)}` +
          `<div class="row" style="gap:6px;margin-top:6px">` +
          `<button class="danger" onclick="secureErase(1)">${esc(t("Single pass"))}</button>` +
          `<button class="danger" onclick="secureErase(3)">${esc(t("Triple pass"))}</button>` +
          `<button class="danger" onclick="secureErase(8)">${esc(t("Octuple pass"))}</button>` +
          `</div><div class="muted" style="margin-top:4px">${esc(t("This may take several minutes on a large disk. Restart the app when you are done."))}</div></div>`;
        toast("Local data crypto-erased. Restart the app.", "warn");
      } catch (e) { toast(_failMsg("Panic wipe failed: {error}", e), "err"); }
    }

    // Phase 2 of the panic flow: an optional full free-space overwrite (defence-in-depth
    // on top of the crypto-erase). passes is 1 / 3 / 8 (Single / Triple / Octuple).
    async function secureErase(passes) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("panic-result");
      try {
        toast("Running full overwrite… this can take a while.", "warn");
        const r = await api("/api/safety/secure-erase",
          {method: "POST", body: JSON.stringify({confirm: true, passes})});
        const mib = Math.round((r.bytes_written || 0) / 1048576);
        if (box) box.innerHTML +=
          `<div class="hint" style="margin-top:6px"><span class="pill warn">overwritten</span> ` +
          `${r.passes}× — ${mib} MiB. <span class="muted">${esc(r.limit)}</span></div>`;
        toast("Full overwrite complete. Restart the app.", "warn");
      } catch (e) { toast(_failMsg("Full overwrite failed: {error}", e), "err"); }
    }

    // Resolve {mode, remove_folder, wipe_data, passes} from the picker. Data is removed
    // only in 'secure' or an explicit 'custom' opt-in — never minimal/full (maintainer-
    // ruled). passes (1/3/8, or null for crypto-erase only) mirrors the post-panic
    // optional full-overwrite offer — parity between the two data-destroying flows.
    function _uninstallSel() {
      const mode = (($("uninstall-mode") || {}).value) || "minimal";
      const remove_folder = mode === "custom"
        ? !!(($("uninstall-folder") || {}).checked)
        : (mode === "full" || mode === "secure");
      const wipe_data = mode === "custom"
        ? !!(($("uninstall-data") || {}).checked)
        : (mode === "secure");
      const passesRaw = (($("uninstall-passes-select") || {}).value) || "";
      const passes = (wipe_data && passesRaw) ? parseInt(passesRaw, 10) : null;
      return {mode, remove_folder, wipe_data, passes};
    }

    // Show the Customize checkboxes + a live preview of the EXACT paths a mode removes
    // (informed consent before anything irreversible). Deletes nothing — GET only.
    async function onUninstallMode() {
      const sel = _uninstallSel();
      const cust = $("uninstall-custom"); if (cust) cust.style.display = sel.mode === "custom" ? "" : "none";
      const pdiv = $("uninstall-passes"); if (pdiv) pdiv.style.display = sel.wipe_data ? "" : "none";
      const box = $("uninstall-preview"); if (!box) return;
      try {
        const qs = `mode=${encodeURIComponent(sel.mode)}&remove_folder=${sel.remove_folder}&wipe_data=${sel.wipe_data}`;
        const p = await api(`/api/safety/uninstall/plan?${qs}`);
        const bits = [`virtualenv${p.venv ? "" : " (none found)"}`, `${(p.launchers || []).length} launcher(s)`];
        if (p.app_folder) bits.push(`the app folder <code>${esc(p.app_folder)}</code>`);
        if (p.wipe_data_dir) bits.push(`<strong>your data &amp; keys</strong> at <code>${esc(p.wipe_data_dir)}</code>`);
        let html = `Will remove: ${bits.join(", ")}.`;
        if (!p.wipe_data_dir && p.data_dir) html += ` Your data at <code>${esc(p.data_dir)}</code> is kept.`;
        if (p.wipe_data_dir) html += ` <span class="muted">Overwrite can’t guarantee erasure on SSD/flash/copy-on-write disks — the real protection is that your corpus was encrypted and the key is destroyed.</span>`;
        html += ` <span class="muted">An uninstall log is written to ${esc(p.audit_log || "")}.</span>`;
        box.innerHTML = html;
      } catch (e) { box.textContent = ""; }
    }

    // Offer a backup before a destructive uninstall (maintainer-asked). Reuses the
    // encrypted-backup endpoint; downloads the .ooenc, then the user re-clicks Uninstall
    // (we never run the uninstall while a backup is still streaming from this server).

    async function uninstallApp() {
      const sel = _uninstallSel();
      // Only the data-wiping modes risk losing the corpus — offer a backup there first.
      if (sel.wipe_data) {
        const backFirst = confirm("This mode WIPES your data and keys — IRREVERSIBLE.\n\n" +
          "Create an encrypted backup first?\n\nOK = back up now (then click Uninstall again)\n" +
          "Cancel = continue WITHOUT a backup");
        if (backFirst) { openUnifiedExport(); return; }
      }
      let msg = "UNINSTALL: remove the virtualenv and desktop launchers, then stop the server.";
      if (sel.remove_folder) msg += "\nAlso delete the app folder.";
      if (sel.wipe_data) msg += "\nAlso WIPE your data and keys — IRREVERSIBLE.";
      else msg += "\nYour data is KEPT.";
      if (!confirm(msg + "\n\nContinue?")) return;
      const want = sel.wipe_data ? "WIPE" : "UNINSTALL";
      if (prompt(`To confirm, type ${want} in capitals:`) !== want) {
        toast("Uninstall cancelled.", "err"); return; }
      try {
        const r = await api("/api/safety/uninstall", {method: "POST",
          body: JSON.stringify({confirm: true, mode: sel.mode,
            remove_folder: sel.remove_folder, wipe_data: sel.wipe_data, passes: sel.passes})});
        if (!r.scheduled) { $("uninstall-result").textContent = r.note || "Nothing to remove."; return; }
        $("uninstall-result").innerHTML =
          `<span class="pill warn">uninstalling</span> ${esc(r.note || "")}`;
        toast("Uninstalling — the app is stopping.", "warn");
        // The server is about to SIGTERM itself; replace the whole UI with a terminal
        // screen so the user can't keep clicking dead tabs, and try to close the tab
        // (best-effort — browsers only close script-opened tabs). Maintainer 2026-06-21.
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        _terminalOverlay(
          t("Open Omniscience has been uninstalled and the app has stopped. You can close this window."),
          {tryClose: true});
      } catch (e) { toast(_failMsg("Uninstall failed: {error}", e), "err"); }
    }

    // -- First-run onboarding (empty corpus) -------------------------------- //
    // The guided wizard is the first-run entry (maintainer-ruled 2026-06-13). The
    // old "corpus is empty" bubble was RETIRED (2026-06-17): sources auto-seed on
    // boot and the background collector runs continuously once online (only airplane
    // stops it), so an empty corpus needs no manual seed/ingest prompt — just the
    // one-time guide. A returning empty user (guide done) sees the briefing's honest
    // empty state, never a banner.
    async function checkEmptyCorpus() {
      try {
        const s = await api("/api/database/stats");
        if (s.counts && s.counts.articles === 0 && !guideDone()) openGuide();
      } catch (e) { /* stats unavailable -> no banner */ }
    }

    async function firstRun(btn) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!await ensureOnline(t9("Start a collection pass (RSS, crawl, markets, watched Wikipedia pages)"))) return;
      if (btn) btn.disabled = true;
      // The visible #onboard bubble was retired (2026-06-17); firstRun() stays as a
      // programmatic seed+collect helper that still consents first (ensureOnline,
      // above). Its status writes no-op safely when the card element is absent.
      const st = $("onboard-status") || {};
      try {
        const stats = await api("/api/database/stats");
        if (!stats.counts || stats.counts.sources === 0) {
          st.textContent = "Seeding curated sources…";
          await api("/api/sources/seed-defaults", {method: "POST"});
        }
        st.textContent = "Importing market data (official price feeds)…";
        await api("/api/markets/feeds/import-all", {method: "POST"}).catch(() => null);
        st.textContent = "Running a first news ingestion (bounded; may take a moment)…";
        await api("/api/scheduler/run-now", {method: "POST"});
        let n = 0;
        const poll = setInterval(async () => {
          const s = await api("/api/database/stats").catch(() => null);
          const arts = s && s.counts ? s.counts.articles : 0;
          st.textContent = `Ingesting… ${arts} article(s) so far.`;
          if (arts > 0 || ++n > 40) {
            clearInterval(poll);
            if (arts > 0) { st.innerHTML = `<span class="pill ok">done</span> ${arts} article(s) ingested.`;
              setTimeout(() => { const ob = $("onboard"); if (ob) ob.style.display = "none"; }, 2500); doSearch(); loadDbStats && loadDbStats(); }
            else st.textContent = "No articles yet — check the Sources tab and the scheduler's last run.";
            btn.disabled = false;
          }
        }, 2000);
      } catch (e) { st.textContent = _failMsg("First run failed: {error}", e); btn.disabled = false; }
    }

    // -- Database tab ------------------------------------------------------- //
    // Tween a stat number from its current value to `to` (ease-in-out) so the
    // database visibly "grows" on each poll. Cosmetic only — the value is real.
    function animateCount(el, to) {
      to = Math.round(to || 0);
      const from = parseInt(el.dataset.v || "0", 10) || 0;
      if (from === to) { el.dataset.v = to; el.textContent = to.toLocaleString(); return; }
      const start = performance.now(), dur = 600;
      function step(t) {
        const k = Math.min(1, (t - start) / dur);
        const eased = 0.5 - 0.5 * Math.cos(k * Math.PI);
        el.textContent = Math.round(from + (to - from) * eased).toLocaleString();
        if (k < 1) requestAnimationFrame(step); else el.dataset.v = to;
      }
      requestAnimationFrame(step);
    }

