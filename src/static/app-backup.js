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
    // The dated export folder THIS export is writing into (R5; Q210-Q213). Allocated
    // ONCE per run by the server and then handed to BOTH phases, because a name computed
    // separately in each phase would give two folders whenever an export crosses a minute
    // boundary -- and neither of them would be the one the panel names. Also what a RESUME
    // must go back to: re-reading the destination box would allocate a SECOND folder and
    // orphan the paused one, which is the resumable-job class of defect where the extra
    // state quietly drops on the way back in.
    let _uxExportDir = null;
    //: The facts the completion panel last drew, so a language switch can redraw them.
    let _uxExportFacts = null;
    document.addEventListener("oo:langchange", () => {
      // Only when a panel is actually on screen: re-rendering into a hidden host would
      // resurrect a previous export's panel the next time the dialog opens.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // The checklist's counts too (R10), while the export dialog is open.
      const dlg = document.getElementById("ux-export");
      if (dlg && dlg.open && _uxInv) _uxPaintInventory(_uxInv, t, true);
      const host = document.getElementById("ux-summary");
      if (!host || !host.innerHTML || !_uxExportFacts) return;
      _uxRenderExportPanel(_uxExportFacts, t);
    });

    async function openUnifiedExport() {
      const dlg = document.getElementById("ux-export");
      document.getElementById("ux-progress").textContent = "";
      const sum = document.getElementById("ux-summary");
      if (sum) sum.innerHTML = "";
      _uxExportFacts = null;
      document.getElementById("ux-run").disabled = false;
      dlg.showModal();
      await _uxLoadInventory();
      _uxShowLastCompletedExportSummary();  // best-effort; never blocks opening the dialog
    }

    // Which of the two managers' finished states is the LAST export (2026-09-26
    // click-through, J1). The folder phase runs after the corpus phase of the same
    // export, so when both name ONE folder the folder job is the later state. When they
    // name DIFFERENT folders they are two exports -- a corpus-only export leaves the
    // folder manager holding an OLDER export's destination -- and the later START wins.
    // (The old rule let the folder job win unconditionally, so the dialog named the
    // older export, and a paused corpus export lost its Resume button to it.)
    // Returns whichever of the two statuses to show, or null.
    function _uxPickLastExport(vol, fold) {
      if (vol && fold) {
        return (_uxSamePath(vol.dest, fold.dest) || (fold.started_at || 0) >= (vol.started_at || 0))
          ? fold : vol;
      }
      return vol || fold || null;
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
      const exportState = (s) => s && s.mode === "backup" && (s.state === "done" || s.state === "paused");
      let vol = null, fold = null;
      try {
        const s = await api("/api/backup/v2/volumes/status");
        if (exportState(s)) vol = s;
      } catch (e) { /* best-effort: one endpoint failing must not hide the other */ }
      try {
        const s = await api("/api/backup/folder/status");
        if (exportState(s)) fold = s;
      } catch (e) { /* best-effort */ }
      const shown = _uxPickLastExport(vol, fold);
      if (!shown) return;
      let phase = null;
      if (shown === fold) phase = "folder";
      else phase = "volumes";
      const dest = shown.dest || (document.getElementById("ux-dest").value || "").trim();
      // Recover the folder BEFORE the branch: a PAUSED export resumed after a page
      // reload must re-enter the folder it paused in, and the only place that survives
      // the reload is the job manager's own dest. Setting it only on the completed
      // branch would leave a reloaded resume allocating a fresh folder.
      _uxExportDir = shown.dest || null;
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
        // A completed export: the panel a reopened dialog shows is the same panel the
        // run itself ended on, built from the same server-side facts rather than from a
        // remembered sentence.
        // dir="ltr": a path is left-to-right data, and inside the Arabic dialog its
        // leading slash was drawn at the far end (J3). The brackets are the LOCALE's, from
        // a keyed frame: welded ASCII ones read "(上次已完成的导出)" in Chinese (J-3).
        const tfb = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf
          : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
        prog.innerHTML = `<b>${esc(t("Backup complete →"))}</b> <span dir="ltr" style="overflow-wrap:anywhere">${esc(dest)}</span> ${esc(tfb("({text})", { text: t("last completed export") }))}`;
        if (dest) {
          try {
            let facts = await api("/api/backup/export-summary?dir=" + encodeURIComponent(dest));
            // J2: the job writes BACKUP_SUMMARY.md when it completes. Should the file
            // still be missing (that write failed), ask for it once more here, and if
            // that fails too the panel NAMES the missing file rather than reading as
            // if one were there.
            if (facts && !facts.summary_path && shown.state === "done") {
              try {
                const w = await api("/api/backup/export-summary", { method: "POST", body: JSON.stringify({ dir: dest }) });
                facts = { ...(w.facts || {}), summary_path: w.summary_path };
              } catch (e) {
                facts = { ...facts, summary_error: String((e && e.message) || e) };
              }
            }
            _uxRenderExportPanel(facts, t);
            // J-1: a folder missing a member the export was asked for is not a completed
            // backup, whatever the job that last wrote into it reported.
            const miss = (facts && facts.missing) || {};
            if (miss.corpus || (miss.categories || []).length) {
              prog.innerHTML = `<b>${esc(t("Backup incomplete →"))}</b> <span dir="ltr" style="overflow-wrap:anywhere">${esc(dest)}</span>`;
            }
          } catch (e) { /* best-effort: the completion line stands on its own */ }
        }
      }
    }

    // ONE renderer for the completion panel (R4; Q208 = a). The facts come from
    // /api/backup/export-summary, which is the SAME function BACKUP_SUMMARY.md renders
    // from -- so the screen and the file on the drive cannot disagree about a number.
    // Nothing here is computed from the request the page made; a panel that quoted its
    // own inputs back would report what was asked for, not what happened.
    function _uxRenderExportPanel(facts, t) {
      const TF = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => tpl.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
      const host = document.getElementById("ux-summary");
      if (!host || !facts) return;
      // Kept so a live language switch can redraw the SAME facts (the panel is
      // data-i18n-dyn, so the DOM walker will not do it -- deliberately, because the
      // walker would translate the table NAMES, which are data).
      _uxExportFacts = facts;
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const v = facts.volumes || {}, el = facts.elapsed || {}, sch = facts.schema || {};
      const enc = facts.encryption || {};
      const dash = "—";
      const bytes = (n) => (n == null ? dash : humanBytes(n));
      // The UNIT rides inside the frame. The old form put the seconds abbreviation
      // through t() on its own -- ONE character, where --audit-chrome floors at three,
      // so the audit never saw it, and it had no en.json key either: every locale
      // rendered a Latin s for seconds, including the ones that write с, ث or 秒.
      // (Described, not pasted as a call: both i18n scans read RAW SOURCE, so a
      // call-shaped literal in a comment is counted as a live UI string.)
      const secs = (n) => (n == null ? null
        : (n < 90 ? TF("{n} s", {n: n.toFixed(1)}) : TF("{n} min", {n: Math.round(n / 60)})));
      const rows = [];
      const row = (label, value, title) =>
        rows.push(`<div class="row" style="gap:6px;align-items:baseline"><span class="muted" style="min-width:150px"${title ? ` title="${esc(title)}"` : ""}>${esc(label)}</span><span>${value}</span></div>`);

      // 1-2. volumes and the bytes they occupy.
      if (facts.corpus_included) {
        // The count through fmtNum inside ONE keyed frame per number (R10): the raw
        // `String(count)` read "12345" under a French UI and carried no noun of its own.
        const vCount = v.count == null ? dash
          : (v.count === 1 ? tf("{n} volume", { n: fmtNum(v.count, 0) }) : tf("{n} volumes", { n: fmtNum(v.count, 0) }));
        row(t("Encrypted volumes"), `${esc(vCount)} · ${esc(bytes(v.bytes))} ${esc(t("on the drive"))} · ${esc(bytes(v.plaintext_bytes))} ${esc(t("of content"))}`);
        row(t("Parity (corruption recovery)"), esc(v.parity ? t("written") : t("none")));
      } else {
        row(t("Encrypted volumes"), esc(t("none — no corpus was selected for this export")));
      }
      // 3. per-table counts, articles FIRST (the ruled headline unit).
      const tables = facts.tables || [];
      const filled = tables.filter((r) => r.rows > 0);
      const empty = tables.length - filled.length;
      if (tables.length) {
        const cells = filled.map((r) => `<span class="pill" style="margin:0 4px 4px 0"><b>${esc(r.name)}</b> ${esc(fmtNum(r.rows, 0))}</span>`).join("");
        const more = !empty ? ""
          : `<div class="muted" style="font-size:11px">${esc(empty === 1
            ? tf("{n} more table is empty in this backup.", { n: fmtNum(empty, 0) })
            : tf("{n} more tables are empty in this backup.", { n: fmtNum(empty, 0) }))}</div>`;
        row(t("Rows per table"), `<div style="display:flex;flex-wrap:wrap">${cells}</div>${more}`,
            t("The counts the export measured while it streamed the corpus, articles first."));
      }
      // 4. files copied, per category.
      const files = facts.files || [];
      if (files.length) {
        row(t("Files copied"), files.map((c) => `<span class="pill" style="margin:0 4px 4px 0"><b>${esc(c.category)}</b> ${esc(c.files === 1
          ? tf("{n} file", { n: fmtNum(c.files, 0) }) : tf("{n} files", { n: fmtNum(c.files, 0) }))} · ${esc(bytes(c.bytes))}</span>`).join(""));
      } else {
        // Its own key, not the shared "none": the shared one agrees with a feminine noun
        // in French (parité : aucune), and "files" needs the masculine (J9).
        row(t("Files copied"), esc(t("no files")));
      }
      // 5. elapsed -- an unmeasured span says so; it never renders as zero.
      // The hovers here and on Encryption are the server's English sentences, looked up
      // as keys: they are caveats, and a caveat ships x12 (J7). The server strings are
      // pinned as keys in all 12 locales by tests/test_export_folder.py, because the
      // i18n gate cannot see a string that only arrives over the wire.
      // ONE keyed frame per case, so each part reads as a phrase in every locale. The old
      // form set a time (or "not recorded") beside a bare noun, and read "— corpus · not
      // recorded files" in English and "non enregistré fichiers" in French. A part for
      // something this export did not carry is left out rather than drawn as a dash.
      const corpusS = secs(el.corpus_s), filesS = secs(el.files_s);
      const spans = [];
      if (facts.corpus_included) {
        spans.push(corpusS ? tf("{d} for the corpus", { d: corpusS }) : t("not recorded for the corpus"));
      }
      if (files.length) {
        spans.push(filesS ? tf("{d} for the files", { d: filesS }) : t("not recorded for the files"));
      }
      row(t("Elapsed"), esc(spans.length ? spans.join(" · ") : dash),
          el.files_s_reason ? t(el.files_s_reason) : "");
      // 6-9. destination, encryption, schema, app version.
      // A filesystem path is ONE unbreakable token, and the dated folder made it longer:
      // measured at 390px it ran 165px past the viewport with no way to read its end.
      // `anywhere` rather than `break-word` because there is no space to break at.
      // dir="ltr": it is left-to-right data inside a possibly right-to-left panel (J3).
      row(t("Destination"), `<code dir="ltr" style="overflow-wrap:anywhere">${esc(facts.destination || "")}</code>`);
      // corpus_encrypted is the SQLCipher state of the corpus DATABASE FILE inside the
      // volumes -- never whether the corpus is encrypted in this backup, which it always
      // is. The false case says which layer it measures, so it no longer contradicts the
      // note on its own hover (J5).
      row(t("Encryption"),
          esc(enc.corpus_encrypted == null
              ? dash
              : (enc.corpus_encrypted ? t("corpus encrypted at rest inside the backup") : t("corpus database not separately encrypted (the backup's volumes are)"))) +
          (files.length ? ` · ${esc(t("copied files are not encrypted"))}` : ""),
          enc.note ? t(enc.note) : "");
      row(t("Schema version"), esc(`${sch.backup_schema || dash} · ${sch.container || dash} · ${t("database")} ${sch.alembic_rev || dash}`));  // esc(): alembic_rev is read out of a database, not a constant
      row(t("App version"), esc(facts.app_version || dash));
      // 10. the licence lines that apply (Q1008 = a).
      const lic = facts.attribution || [];
      if (facts.attribution_error) {
        // The visible sentence is keyed; the backend's own words (which name the ruling
        // and the tables) ride the hover as technical detail rather than as the caveat --
        // behind a keyed lead, so the hover opens in the reader's language before the
        // server's English detail (W14). In the dialog's error colour, not the toast box (W6).
        row(t("Licences"),
            `<span style="color:var(--err)" title="${esc(tf("The attribution query failed: {detail}", { detail: facts.attribution_error }))}">${esc(t("The attribution lines could not be completed — a licence question is unanswered, so this backup is reported without them."))}</span>`);
      } else if (lic.length) {
        // Each line is the server's English sentence, looked up as a key: a licence line
        // is a caveat about what the reader may do with the data, and a caveat ships x12.
        // tests/test_export_folder.py pins every line the registry can emit as a key in
        // all 12 locales, since the i18n gate cannot see a string that arrives over the
        // wire. dir="auto": a line with no key yet stays English data, and inside an
        // Arabic panel its closing period was drawn at the start of the line (J3).
        row(t("Licences"),
            lic.map((l) => `<div dir="auto" title="${esc(tf("applies because: {signal}", { signal: l.because }))}">${esc(t(l.text))}</div>`).join(""));
      } else {
        row(t("Licences"), `<span class="muted">${esc(t("no attribution line applies to what this backup holds"))}</span>`);
      }

      const verify = facts.verify || {};
      // Red for every not-verified verdict EXCEPT "not held": there the export may well
      // have verified its set, and what is missing is this app's memory of it -- an
      // unknown, which a red box would turn into an alarm about a sound backup.
      // A plain status line in the dialog's own colours (R3): the `.note` class is the
      // floating TOAST box -- its shadow and slide-in animation -- and a verdict inside a
      // dialog is not a toast.
      const verdictCls = verify.state === "verified" ? "" : (verify.state === "not_held" ? "muted" : "");
      const verdictCol = (verify.state === "verified" || verify.state === "not_held") ? "" : "color:var(--err);";
      // INCOMPLETE (J-1): what this export was asked for and the folder does not hold,
      // read by the server from the request recorded when the folder was made. It leads
      // the panel, above the verify verdict, because a clean "Verified" over a backup
      // missing a member the operator ticked reads as a finished export -- and the
      // missing large-data files get a button that copies them into this same folder.
      const miss = facts.missing || {};
      const owed = miss.categories || [];
      const lost = [];
      if (miss.corpus) lost.push(t("Corpus"));
      if (owed.length) {
        // The inventory's own member list names the tick each category came from, so
        // "models" + "hf_models" read as the one "LLM models" the operator ticked.
        const members = (typeof _uxInv !== "undefined" && _uxInv && _uxInv.members) || [
          { label: "LLM models", categories: ["models", "hf_models"] },
          { label: "Offline maps", categories: ["osm_regions"] },
          { label: "Wikipedia dumps", categories: ["wiki_dumps"] },
        ];
        for (const m of members) {
          if ((m.categories || []).some((c) => owed.includes(c))) lost.push(t(m.label));
        }
        for (const c of owed) {
          if (!members.some((m) => (m.categories || []).includes(c))) lost.push(c);
        }
      }
      const incomplete = !lost.length ? ""
        : `<div class="ux-incomplete" style="margin-top:8px;color:var(--err)">` +
          `<b>${esc(tf("Incomplete — requested for this export but not in this folder: {members}", { members: lost.join(" · ") }))}</b>` +
          (owed.length
            ? `<div style="margin-top:4px"><button type="button" class="secondary" data-ux-complete title="${esc(t("Starts the large-data copy into this same folder. The encrypted volumes already in it are not touched."))}">${esc(t("Copy the large-data files now"))}</button></div>`
            : "") +
          `</div>`;
      host.innerHTML = incomplete +
        `<div class="ux-verdict ${verdictCls}" style="margin-top:8px;${verdictCol}"${_uxVerifyDetail(verify) ? ` title="${esc(_uxVerifyDetail(verify))}"` : ""}>${esc(_uxVerifySentence(verify, t))}</div>` +
        `<div style="margin-top:6px;display:flex;flex-direction:column;gap:2px;font-size:12px">${rows.join("")}</div>` +
        `<div class="card-caveat" style="margin-top:6px;font-size:11px">${esc(t("Every export writes a new dated folder and every volume in it: nothing is reused from an earlier backup, so this folder's bytes were all written by this one pass."))}</div>` +
        (facts.summary_path
          ? `<div class="muted" style="margin-top:4px;font-size:11px;overflow-wrap:anywhere">${esc(t("A summary of these facts was written beside the backup:"))} <code dir="ltr">${esc(facts.summary_path)}</code></div>`
          : (facts.summary_error
            ? `<div style="color:var(--err);margin-top:4px;font-size:11px;overflow-wrap:anywhere">${esc(t("The backup is written, but its summary file could not be:"))} ${esc(facts.summary_error)}</div>`
            : ""));
      // A listener, not an inline handler: the button is re-drawn on every repaint.
      const again = host.querySelector ? host.querySelector("[data-ux-complete]") : null;
      if (again) again.addEventListener("click", () => _uxCompleteExport(again));
    }

    // The verify verdict as ONE sentence. The five not-verified cases stay apart: "off",
    // "cancelled", "could not be re-read", "no result recorded" and "FAILED" are
    // different facts, and a single missing "verified" would flatten the last one into
    // the others. A sixth, "not known here", is not a not-verified case at all.
    //
    // EVERY branch is a CLIENT-side keyed template, never the backend's own `reason`
    // string. The job writes those in English, and this is a caveat surface, which ships
    // x12 by the informed-consent non-negotiable — piping a backend sentence here would
    // render English under an Arabic heading. The backend's raw wording is still
    // available, as the technical DETAIL on the hover (_uxVerifyDetail), which is the
    // layering the convention asks for rather than a discarded fact.
    function _uxVerifySentence(verify, t) {
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const bad = verify.bad || [];
      if (verify.state === "verified") return tf("Verified — all {total} volumes were re-read and matched their checksums.", { total: verify.total });
      if (verify.state === "failed") return tf("NOT verified — {n} of {total} volumes no longer match their checksum: {names}. Treat this backup as unreliable until it is written again.", { n: bad.length, total: verify.total, names: bad.join(", ") });
      if (verify.state === "off") return t("Not verified — verify-after-write was turned off for this export.");
      if (verify.state === "stopped") return t("Not verified — the re-read was cancelled. The volumes were written, but they were not read back.");
      if (verify.state === "unavailable") return t("Not verified — the volume set could not be read back off the destination.");
      // The folder holds a volume set whose export this app no longer remembers (it ran
      // another job or restarted since). Not a "Not verified": nobody has found anything
      // wrong, and "no corpus" -- what this used to render as -- was simply false (J1).
      if (verify.state === "not_held") return t("Verify result not known here — the app no longer holds what this export measured (it has run another job or restarted since). The volume figures below are read off the drive.");
      return t("Not verified — this export recorded no verify result.");
    }

    //: The backend's own English `reason`/`method` wording, for the hover. Kept BESIDE
    //: the translated sentence rather than instead of it: it names the exact mechanism
    //: (which volumes, compared against what) and is the thing an operator quotes when
    //: something is wrong.
    function _uxVerifyDetail(verify) {
      return [verify.reason, verify.method].filter(Boolean).join(" · ");
    }

    async function _uxLoadInventory() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const st = document.getElementById("ux-inv-status");
      const box = document.getElementById("ux-checklist");
      st.textContent = t("Loading what's available…");
      try {
        const inv = await api("/api/backup/inventory");
        _uxPaintInventory(inv, t, false);
        box.addEventListener("change", _uxSyncInside);
        st.textContent = t("What do you want to back up?");
      } catch (e) {
        st.textContent = t("Could not load the inventory — see console");
        console.error("ux inventory", e);
      }
    }

    //: The inventory the checklist was last drawn from, so a language switch can redraw
    //: its counts (R10) -- they are t()-rendered text the DOM walker cannot re-translate.
    let _uxInv = null;
    // Draws the checklist from one inventory read. A REDRAW (keep) keeps every tick the
    // operator already changed: the boxes are read before and written back after. A
    // fresh load starts from the defaults, as it always has.
    function _uxPaintInventory(inv, t, keep) {
      const box = document.getElementById("ux-checklist");
      if (!box || !inv) return;
      _uxInv = inv;
      const kept = {};
      for (const el of (keep ? Array.from(box.querySelectorAll("input[type=checkbox]")) : [])) {
        if (el.id) kept[el.id] = el.checked;
      }
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      // ONE keyed frame per count, chosen by number, the number through fmtNum (R10).
      const files = (n) => (n === 1 ? tf("{n} file", { n: fmtNum(n, 0) }) : tf("{n} files", { n: fmtNum(n, 0) }));
      {
        const c = inv.corpus || {}, b = c.breakdown || {};
        // "Everything" is the default: a present category (count > 0) is CHECKED so a
        // backup includes the whole corpus + wiki + maps + models unless the user
        // unticks one (field ask 2026-07-02). Absent categories are disabled.
        // Q219 = a: the size an export would ACTUALLY write for this member, shown
        // BEFORE the export starts. `d.bytes` is the sum over the member's categories,
        // so a tick that carries two stores shows both; the per-store split rides the
        // hover (the layered-disclosure convention, invariant #17) rather than crowding
        // the row.
        const opt = (id, label, d) => {
          const parts = Object.entries(d.breakdown || {}).filter(([, x]) => (x.count || 0) > 0);
          // A member the export cannot yet WRITE is never offered, whatever it holds.
          // It would otherwise render CHECKED the moment it had content, carry no
          // categories, and write nothing -- a tick that lies about what the backup
          // contains, which is the one thing a backup dialog may never do. The reason
          // travels as the hover (invariant #17's layered disclosure) because a
          // disabled row with no explanation reads as a bug rather than as a boundary.
          const offerable = d.exportable !== false;
          const why = offerable ? "" : t(d.not_exportable_reason || "");
          const title = why || (parts.length > 1
            ? parts.map(([k, x]) => ooLabelText(k, `${files(x.count || 0)} · ${humanBytes(x.bytes || 0)}`)).join(" · ")
            : "");
          const state = (offerable && (d.count || 0) > 0) ? "checked" : "disabled";
          return `<label class="switch" style="margin:0"${title ? ` title="${esc(title)}"` : ""}><input type="checkbox" id="ux-c-${id}" data-cats="${esc((d.categories || []).join(","))}" ${state}> ${esc(label)} <span class="muted">${esc(tf("({text})", { text: `${files(d.count || 0)} · ${humanBytes(d.bytes || 0)}` }))}</span></label>`;
        };
        // ONE ordered list from the server drives the rows AND the categories each one
        // exports (`data-cats`), so a lane that lands later becomes a row with a real
        // size by appending one entry to src/backup/inventory.py -- with no second
        // mapping here to forget to keep in step. The legacy per-key fallback stays for
        // a server that predates the list.
        const members = inv.members || [
          { key: "models", label: "LLM models", categories: ["models", "hf_models"], ...(inv.models || {}) },
          { key: "maps", label: "Offline maps", categories: ["osm_regions"], ...(inv.maps || {}) },
          { key: "wiki", label: "Wikipedia dumps", categories: ["wiki_dumps"], ...(inv.wiki || {}) },
        ];
        // The corpus is CHECKED by default (a backup still means everything unless the
        // user says otherwise) but no longer `disabled`: it was un-untickable, so the
        // only way to copy models/maps/dumps was to re-encrypt and re-write the whole
        // corpus alongside them (field ask 2026-08-10: "backups should not force user to
        // backup articles and allow them to make compartmented backups"). The import side
        // already discovers corpus, large-data and newsletters independently and only
        // asks for a passphrase when the corpus is among them, so a corpus-less export
        // restores exactly as it is written.
        box.innerHTML =
          `<label class="switch" style="margin:0"><input type="checkbox" id="ux-c-corpus" checked> ${esc(t("Corpus"))} <span class="muted">${esc(tf("({text})", { text: [
            b.articles === 1 ? tf("{n} article", { n: fmtNum(1, 0) }) : tf("{n} articles", { n: fmtNum(b.articles || 0, 0) }),
            b.sources === 1 ? tf("{n} source", { n: fmtNum(1, 0) }) : tf("{n} sources", { n: fmtNum(b.sources || 0, 0) }),
            b.dates === 1 ? tf("{n} date", { n: fmtNum(1, 0) }) : tf("{n} dates", { n: fmtNum(b.dates || 0, 0) }),
            b.keywords === 1 ? tf("{n} keyword", { n: fmtNum(1, 0) }) : tf("{n} keywords", { n: fmtNum(b.keywords || 0, 0) }),
            humanBytes(c.bytes || 0),
          ].join(" · ") }))}</span></label>` +
          members.map((m) => opt(m.key, t(m.label), m)).join("") +
          // S6.2: the same three categories, one artifact instead of two things. Not a
          // better option -- a different trade, so it is a choice and the hover says what
          // it costs. Disabled without a corpus because there would be no artifact to
          // carry them in, and an ignored tickbox is worse than a disabled one.
          `<label class="switch" style="margin:0" title="${esc(t("Inside the artifact they are encrypted and repairable like the corpus, so a restore needs one thing; copied alongside they stay readable on their own and cost nothing to write."))}"><input type="checkbox" id="ux-c-inside"> ${esc(t("Carry them inside the encrypted backup"))}</label>`;
      }
      for (const [id, on] of Object.entries(kept)) {
        const el = document.getElementById(id);
        if (el && !el.disabled) el.checked = on;
      }
      _uxSyncInside();
    }

    //: Every rendered opt-in member row (the corpus is not one -- it is always offered
    //: and has its own box). Carries `data-cats` = the folder-backup categories the
    //: member exports, which is the ONE mapping both the "inside" logic and the run read.
    function _uxMemberBoxes() {
      const box = document.getElementById("ux-checklist");
      if (!box) return [];
      return Array.from(box.querySelectorAll("input[type=checkbox][data-cats]"));
    }

    // The "inside" choice only means something when there IS an artifact and there ARE
    // files to put in it. Rather than silently ignoring the box in the other cases, it is
    // disabled and unticked, so what the run will do is what the dialog shows.
    function _uxSyncInside() {
      const inside = document.getElementById("ux-c-inside");
      if (!inside) return;
      const corpus = document.getElementById("ux-c-corpus");
      // Read the rendered member rows rather than a hardcoded key list, so a lane added
      // to the server's member list is counted here without a second edit.
      const any = _uxMemberBoxes().some((el) => el.checked);
      const usable = (!corpus || corpus.checked) && any;
      inside.disabled = !usable;
      if (!usable) inside.checked = false;
    }

    function _uxEta(secs, t, approx) {
      const TF = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => tpl.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
      if (secs == null) return "";
      const m = Math.round(secs / 60);
      const txt = m >= 1 ? TF("{n} min", {n: m}) : TF("{n} s", {n: Math.max(1, Math.round(secs))});
      // "~" (and the word "estimate") signals a rule-of-three guess, not a promise —
      // the maintainer's ask: humans prefer an approximate number to none at all.
      return ` · ${approx ? "~" : ""}${TF("{d} left", {d: txt})}`;
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
      // `verifying` is the verify-after-write re-read (Q218), the pass that can double an
      // export's time on a slow drive. Without its own entry it fell through to the
      // "Backing up…" default and was never named on screen (J6).
      const back = { starting: t("Preparing…"), building: t("Building encrypted volumes…"),
        volumes: t("Writing encrypted volumes…"), parity: t("Writing parity…"),
        verifying: t("Verifying volumes…"), done: t("Done.") };
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
      // Every count here is ONE keyed frame chosen by number, its figures through fmtNum
      // (R14): "12/40 files" and "3 restored, 0 skipped" welded raw numbers to English
      // nouns and adjectives that agree with nothing in most of the twelve locales.
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      if (kind === "newsletters") {
        const total = s.files_total || 0, done = s.files_done || 0;
        const pct = total ? (s.percent != null ? s.percent : Math.round(100 * done / total)) : null;
        // Each call passes its slots as a literal, which is what the slot check reads.
        const cnt = total === 1
          ? tf("{done} of {total} file", { done: fmtNum(done, 0), total: fmtNum(1, 0) })
          : tf("{done} of {total} files", { done: fmtNum(done, 0), total: total ? fmtNum(total, 0) : "?" });
        return { pct, indeterminate: !total, text: `${esc(cnt)}${esc(_uxEta(s.eta_seconds, t, true))}` };
      }
      if (kind === "folder") {
        const bt = p.bytes_total || 0, bc = p.bytes_copied || 0;
        const pct = bt ? Math.round(100 * bc / bt) : null;
        const n = s.mode === "restore" ? (p.restored || 0) : (p.copied || 0);
        const k = p.skipped || 0;
        const done = s.mode === "restore"
          ? (n === 1 ? tf("{n} file restored", { n: fmtNum(n, 0) }) : tf("{n} files restored", { n: fmtNum(n, 0) }))
          : (n === 1 ? tf("{n} file copied", { n: fmtNum(n, 0) }) : tf("{n} files copied", { n: fmtNum(n, 0) }));
        const skipped = k === 1 ? tf("{n} file skipped", { n: fmtNum(k, 0) }) : tf("{n} files skipped", { n: fmtNum(k, 0) });
        // frac drives the client-side rule-of-three ETA in _uxPoll (bytes are the honest
        // size measure for wiki/maps/models — the big, slow copies the user waits on).
        return { pct, indeterminate: !bt, frac: bt ? bc / bt : null,
          text: `${esc(done)}, ${esc(skipped)}` };
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
          ? `${esc(_uxVolPhase("merging", s.mode, t))} <span class="muted">${esc(tf("({text})", { text: `${fmtNum(p.merge_step || 0, 0)}/${fmtNum(p.merge_steps, 0)} · ${p.merge_label}` }))}</span>`
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
        const rx = p.reindex_total === 1
          ? tf("{done} of {total} article", { done: fmtNum(p.reindex_done || 0, 0), total: fmtNum(p.reindex_total, 0) })
          : tf("{done} of {total} articles", { done: fmtNum(p.reindex_done || 0, 0), total: fmtNum(p.reindex_total, 0) });
        // The brackets are the keyed frame (J-3), so zh and ja get their full-width pair.
        const label = `${esc(_uxVolPhase("reindexing", s.mode, t))} <span class="muted">${esc(tf("({text})", { text: rx }))}</span>`;
        return { pct: Math.round(frac * 100), indeterminate: false, frac, phaseKey: "reindex",
          text: label + `<span class="muted">${phaseCount}</span>` };
      }
      let extra = "";
      if (p.volumes_written) {
        extra += ` · ${esc(p.volumes_written === 1 ? tf("{n} volume", { n: fmtNum(1, 0) }) : tf("{n} volumes", { n: fmtNum(p.volumes_written, 0) }))}`;
      }
      if (p.bytes_written) extra += ` · ${esc(humanBytes(p.bytes_written))}`;
      // The re-read's own count, in the merge label's N/M shape. Only once the total is
      // known: the first report (sent before any volume is hashed) carries none, and a
      // "0/?" would be a figure made up for the gap.
      if (p.phase === "verifying" && p.volumes_total) {
        extra += ` · ${esc(p.volumes_total === 1
          ? tf("{done} of {total} volume", { done: fmtNum(p.volumes_verified || 0, 0), total: fmtNum(p.volumes_total, 0) })
          : tf("{done} of {total} volumes", { done: fmtNum(p.volumes_verified || 0, 0), total: fmtNum(p.volumes_total, 0) }))}`;
      }
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
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      // "Corpus: Preparing…". The separator is the LOCALE's -- French puts a space before
      // the colon, Chinese and Japanese use a full-width one -- so it comes from a keyed
      // frame rather than a hardcoded ": " (J9). The frame is filled with two markers and
      // escaped first, then the markers are swapped for the prefix (text, escaped here)
      // and the progress (already HTML), so neither is escaped twice or not at all.
      const withPrefix = (html) => (!ui.prefix ? html
        : esc(tf("{prefix}: {text}", { prefix: "\u0001", text: "\u0002" }))
          .replace("\u0001", () => esc(ui.prefix)).replace("\u0002", () => html));
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
              ui.label.innerHTML = withPrefix(`<span class="muted">${esc(t("Connection hiccup — retrying…"))}</span>`);
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
          if (ui.label) ui.label.innerHTML = withPrefix(view.text + esc(etaTxt));
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

    async function _uxRun(btn, resumeDir) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const parent = (document.getElementById("ux-dest").value || "").trim();
      if (!parent) { toast(t("Enter a destination folder first."), "err"); return; }
      const prog = document.getElementById("ux-progress");
      const bar = document.getElementById("ux-bar");
      const pauseBtn = document.getElementById("ux-pause");
      // Which folder-backup categories a ticked member carries comes from the member
      // itself (`data-cats`, written by the inventory), never from a list repeated here:
      // the "LLM models" tick has always exported BOTH model stores, and a mapping kept
      // in two places is how the size shown beside it came to count only one of them.
      const blobs = [];
      for (const el of _uxMemberBoxes()) {
        if (!el.checked) continue;
        for (const c of (el.dataset.cats || "").split(",")) { if (c) blobs.push(c); }
      }
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
      // S6.2: carry them INSIDE the artifact instead of copying them alongside it. Only
      // when a corpus is being written, because the artifact is what carries them.
      const insideBox = document.getElementById("ux-c-inside");
      const inside = !!(insideBox && insideBox.checked && !insideBox.disabled && wantCorpus && blobs.length);
      const pass = document.getElementById("ux-pass").value || "";
      if (wantCorpus && !pass) {
        toast(t("Enter a passphrase for the encrypted corpus."), "err"); return;
      }
      // Q218 = a: default ON, and re-read from the box on every start -- including a
      // RESUME, which must re-supply every control it carries rather than leaning on a
      // default. A resumable job that only re-passes its cursor is where a data-safety
      // control silently flips.
      const vBox = document.getElementById("ux-verify");
      const verifyAfterWrite = !vBox || vBox.checked;
      // What THIS export carries, fixed at its start, so a folder copy resumed later
      // names the same parts rather than re-reading ticks the user may have changed (W1).
      _uxExportIncluded = { corpus: wantCorpus, blobs: blobs.slice() };
      btn.disabled = true;
      const sumHost = document.getElementById("ux-summary");
      if (sumHost) sumHost.innerHTML = "";
      if (pauseBtn) { pauseBtn.style.display = ""; pauseBtn.disabled = false; pauseBtn.dataset.mode = "pause"; pauseBtn.textContent = t("Pause"); }
      // THE DATED FOLDER (R5; Q210-Q213). Allocated once, server-side, BEFORE either
      // phase, so both write into the same folder and the panel names the folder that
      // exists. A resume goes back to the folder it paused in -- allocating a second one
      // would orphan the first, along with the volumes already in it.
      let dest = resumeDir || null;
      if (!dest) {
        prog.innerHTML = `<span class="muted">${esc(t("Preparing the export folder…"))}</span>`;
        try {
          // What this export is ASKED to hold rides the allocation, and the server records
          // it in the new folder (J-1): the large-data copy is started from THIS page once
          // the corpus phase is done, so a reload in between left the copy unstarted with
          // nothing anywhere remembering it was wanted. The reopened panel now compares
          // the record with the folder and names what is missing.
          const made = await api("/api/backup/export-folder", { method: "POST", body: JSON.stringify({
            parent, corpus: wantCorpus, categories: blobs, inside }) });
          dest = made.dir;
        } catch (e) {
          prog.innerHTML = `<span style="color:var(--err)">${esc(t("Could not create the export folder:"))} ${esc(e.message || e)}</span>`;
          btn.disabled = false;
          if (pauseBtn) pauseBtn.style.display = "none";
          return;
        }
      }
      _uxExportDir = dest;
      try {
        if (wantCorpus) {
          _uxPhase = "volumes";
          const s1 = await _uxStartThenPoll(
            () => api("/api/backup/v2/volumes/start", { method: "POST", body: JSON.stringify(inside
              ? { dest, passphrase: pass, include_blobs: blobs, verify_after_write: verifyAfterWrite }
              : { dest, passphrase: pass, verify_after_write: verifyAfterWrite }) }),
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
        // Skipped when they rode INSIDE: copying them a second time alongside the
        // artifact would double the bytes on the drive to deliver the same files.
        if (blobs.length && !inside) {
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
        await _uxFinishExport(prog, dest, t);
      } catch (e) {
        _uxPhase = null;
        if (bar) bar.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
        // The dialog's own error colour, not the floating .note toast box (W6; B13's fix
        // for the import dialog): the toast class slid in with a shadow inside the panel.
        prog.innerHTML = `<span style="color:var(--err)">${esc(t("Backup failed:"))} ${esc(ooServerText(e.message || e))}</span>`;
        console.error("ux run", e);
      }
      btn.disabled = false;
    }

    // THE ONE COMPLETION, for a straight run and a resumed large-data copy alike (W1). A
    // folder copy resumed after a pause used to end on a bare "Backup complete →" line:
    // no "Included:" line, no facts panel, and -- because the summary POST lived only in
    // _uxRun -- no BACKUP_SUMMARY.md written into the folder at all.
    let _uxExportIncluded = null;
    async function _uxFinishExport(prog, dest, t) {
      const sumHost = document.getElementById("ux-summary");
      // Name what is actually in it. Now that the corpus can be left out, "Backup
      // complete" alone would let a models-only export read months later as a full one
      // -- the reader has no other way to tell, and that is the expensive direction to
      // be wrong in.
      const inc = _uxExportIncluded || { corpus: false, blobs: [] };
      const included = [];
      if (inc.corpus) included.push(t("Corpus"));
      if (inc.blobs.includes("models")) included.push(t("LLM models"));
      if (inc.blobs.includes("osm_regions")) included.push(t("Offline maps"));
      if (inc.blobs.includes("wiki_dumps")) included.push(t("Wikipedia dumps"));
      prog.innerHTML = `<b>${esc(t("Backup complete →"))}</b> <span dir="ltr" style="overflow-wrap:anywhere">${esc(dest)}</span>`
        + (included.length ? `<div class="muted" style="font-size:12px;margin-top:2px">`
          + `${esc(t("Included:"))} ${esc(included.join(" · "))}</div>` : "");
      // BACKUP_SUMMARY.md is written LAST (Q209 = a), after both phases and after the
      // verify-after-write pass -- which is what lets it carry the verify verdict
      // rather than promise one. A failure HERE is not a failed backup: the bytes are
      // on the drive and verified, so it degrades to a named note beside a completion
      // line that stands, never to "Backup failed".
      try {
        const written = await api("/api/backup/export-summary", { method: "POST", body: JSON.stringify({ dir: dest }) });
        _uxRenderExportPanel({ ...(written.facts || {}), summary_path: written.summary_path }, t);
        // The folder, not this page, has the last word on whether it is complete (J-1).
        const miss = (written.facts && written.facts.missing) || {};
        if (miss.corpus || (miss.categories || []).length) {
          prog.innerHTML = `<b>${esc(t("Backup incomplete →"))}</b> <span dir="ltr" style="overflow-wrap:anywhere">${esc(dest)}</span>`;
        }
      } catch (e) {
        if (sumHost) sumHost.innerHTML = `<div style="color:var(--err);margin-top:8px">${esc(t("The backup is written, but its summary file could not be:"))} ${esc(e.message || e)}</div>`;
        console.error("ux summary", e);
      }
    }

    // Finish an INCOMPLETE export (J-1): copy the large-data files its folder is missing
    // INTO THAT SAME FOLDER, which is exactly the phase _uxRun would have started had the
    // page not been reloaded -- same endpoint, same destination guard, same completion.
    // What to copy comes from the panel's facts, i.e. from the request the server
    // recorded in the folder, never from the checklist, whose ticks may have changed.
    async function _uxCompleteExport(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const facts = _uxExportFacts || {};
      const dest = facts.destination;
      const cats = ((facts.missing || {}).categories || []).slice();
      if (!dest || !cats.length) return;
      const prog = document.getElementById("ux-progress");
      const bar = document.getElementById("ux-bar");
      const pauseBtn = document.getElementById("ux-pause");
      const runBtn = document.getElementById("ux-run");
      if (btn) btn.disabled = true;
      if (runBtn) runBtn.disabled = true;
      _uxExportDir = dest;
      _uxExportIncluded = { corpus: !!facts.corpus_included, blobs: cats };
      const sumHost = document.getElementById("ux-summary");
      if (sumHost) sumHost.innerHTML = "";
      if (pauseBtn) { pauseBtn.style.display = ""; pauseBtn.disabled = false; pauseBtn.dataset.mode = "pause"; pauseBtn.textContent = t("Pause"); }
      try {
        _uxPhase = "folder";
        const s2 = await _uxStartThenPoll(
          () => api("/api/backup/folder/start", { method: "POST", body: JSON.stringify({ dest, categories: cats }) }),
          "/api/backup/folder/status", "folder", { bar, label: prog, prefix: t("Large data") },
          { dest });
        if (s2 && s2.state === "paused") { _uxShowPaused(prog, bar, pauseBtn, t); if (runBtn) runBtn.disabled = false; return; }
        _uxPhase = null;
        if (bar) bar.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
        await _uxFinishExport(prog, dest, t);
      } catch (e) {
        _uxPhase = null;
        if (bar) bar.style.display = "none";
        if (pauseBtn) pauseBtn.style.display = "none";
        prog.innerHTML = `<span style="color:var(--err)">${esc(t("Backup failed:"))} ${esc(ooServerText(e.message || e))}</span>`;
        console.error("ux complete", e);
      }
      if (runBtn) runBtn.disabled = false;
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
          // The same completion the straight run shows, summary file included (W1).
          await _uxFinishExport(prog, _uxExportDir || (document.getElementById("ux-dest").value || "").trim(), t);
        } catch (e) {
          _uxPhase = null; if (bar) bar.style.display = "none"; btn.style.display = "none";
          prog.innerHTML = `<span style="color:var(--err)">${esc(t("Backup failed:"))} ${esc(ooServerText(e.message || e))}</span>`;
        }
        return;
      }
      // Volumes phase: re-running the flow continues the corpus from its resume log,
      // then does any selected large-data blobs -- INSIDE the folder this export already
      // allocated. Without that argument the re-entry would read the destination box and
      // allocate a fresh dated folder, leaving the paused volumes behind in the old one.
      _uxRun(document.getElementById("ux-run"), _uxExportDir);
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
      _uxImSummaryArgs = null;
      document.getElementById("ux-imp-last").innerHTML = "";
      const bar = document.getElementById("ux-imp-bar"); if (bar) bar.style.display = "none";
      document.getElementById("ux-imp-pass-row").style.display = "none";
      document.getElementById("ux-imp-run").disabled = true;
      // ...and the scan's OTHER two parts (2026-09-27 re-walk, I-5). Only a scan sets the
      // trust row, so it stayed up -- a trust statement and its caveat under an empty
      // checklist -- and the folder stayed in the field though `_uxImSrc` (the folder the
      // dialog considers scanned) is cleared just below. A reopen is a fresh page (R1):
      // the whole scan goes, not two thirds of it.
      _uxImTrustRow(false);
      document.getElementById("ux-imp-src").value = "";
      _uxImFound = null; _uxImSrc = "";
      // The re-index read is module-level and outlives the dialog, so a reopen used to
      // render the PREVIOUS run's snapshot -- a stage-4 figure and an "analytics are
      // complete" statement from minutes ago, shown as current, until the first tick
      // replaced them. Cleared here: unknown-until-read ("could not be read") is an
      // honest momentary answer; a stale number presented as current is not. The zeroed
      // timestamp makes the very next tick take the read rather than wait out its pacing.
      _uxImRx = null; _uxImRxAt = 0;
      // ...and the RUN's own surfaces too (R1). Nothing cleared them, so a finished run's
      // header, stage rows, statements and per-backup rows were still in the DOM from
      // the last time the dialog was open, whatever _uxImReattach then decided. Emptied
      // here with their signatures, so the reattach renders onto a genuinely blank page.
      _uxImResetRunView();
      document.getElementById("ux-import").showModal();
      // A FRESH PAGE (R1, Q201 = a). Reopening after an import used to re-render the
      // whole previous run here -- summary, per-item rows, corpus delta -- so the
      // dialog you came back to was the last import's report rather than a place to
      // start the next one. One quiet line now says a previous run exists and links
      // its persisted report, which is where the detail belongs.
      _uxImLastLine();
      _uxImCheckpointNote();
      // Reattach to a run already in flight on the SERVER (ruling item 16): a reload no
      // longer decapitates an import, so the dialog must be able to find it again.
      _uxImReattach();
    }

    // Q201 = a: "Last import - <when> - <n> articles - open report", and nothing else.
    // Reads the newest persisted report from /import-reports, which had no frontend
    // caller at all before this. Three honesty rules ride in one line: an absent
    // article figure renders NO number (a 0 there would say the import added nothing,
    // which is a different fact from "we could not read it"); a run that did not
    // complete is labelled, and its figure says PLANNED, because a plan is computed
    // before the commit point; and a failed read renders nothing rather than a
    // fabricated "no imports yet".
    async function _uxImLastLine() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const host = document.getElementById("ux-imp-last");
      if (!host) return;
      let reports = null, st = null;
      try {
        const [r, q] = await Promise.all([
          api("/api/backup/import-reports"),
          // Which run is in flight, if any (Y7). Unreadable is not fatal: the line then
          // reads as it always did, rather than going blank over a status we lack.
          api("/api/backup/import-queue/status").catch(() => null),
        ]);
        reports = (r && r.reports) || [];
        st = q;
      } catch (e) {
        host.innerHTML = "";  // could not read: say nothing, never "no imports yet"
        return;
      }
      reports = _uxImFinishedReports(reports, st);
      if (!reports.length) { host.innerHTML = ""; return; }
      host.innerHTML = _uxImLastLineHtml(_uxImRunSummary(reports), t, tf);
    }

    // THE LAST FINISHED IMPORT (2026-09-26 leftovers, Y7). A run of several backups
    // persists a report as each one commits, so while it was still going the line summed
    // the reports it had written SO FAR and called that "Last import" -- "2,400 articles"
    // for an import half-way to 4,800, a total no import ever had. Pure: while the queue
    // reports a run in flight, every report written since that run STARTED is its own
    // (one run at a time holds the import window) and is left out, so the line describes
    // the import before it. The time test rather than the run id, because a report is
    // stamped with its run only after it lands; between the two it would read as a
    // run of its own.
    function _uxImFinishedReports(reports, st) {
      if (!st || st.state !== "running" || st.started_at == null) return reports || [];
      const since = Number(st.started_at) * 1000;
      return (reports || []).filter((r) => {
        const at = Date.parse(r && r.created_at);
        return !(Number.isFinite(at) && at >= since);
      });
    }

    // THE LAST IMPORT, not the last REPORT (2026-09-26, I7). One run of several backups
    // leaves one report per backup, stamped with the run's id, so the line quoted
    // whichever backup finished last: "1,200 articles" for a 4,800-article import, and
    // "0 articles" for a run of cumulative backups whose last one added nothing new.
    // Pure: the newest report's run, summed. Each report counts only what ITS backup
    // added (measured against what the earlier ones had already merged), so the sum
    // never counts an article twice; and if any member's figure is absent or merely
    // PLANNED the total is unknown, and the line prints no number rather than a part.
    function _uxImRunSummary(reports) {
      const head = reports && reports[0];
      if (!head || !head.run_id) return head || null;
      const members = reports.filter((r) => r && r.run_id === head.run_id);
      if (members.length < 2) return head;
      const whole = members.every((r) => r.articles != null && r.articles_basis === "merged");
      const failed = members.find((r) => r.outcome && r.outcome !== "ok");
      return {
        ...head,
        articles: whole ? members.reduce((a, r) => a + Number(r.articles || 0), 0) : null,
        articles_basis: whole ? "merged" : head.articles_basis,
        outcome: failed ? failed.outcome : head.outcome,
      };
    }

    // The line itself, as a PURE function of one report row: the only way to assert
    // what it says rather than that the identifiers appear in the source (the recorded
    // "a substring proves a field is MENTIONED, never that it reaches the output").
    function _uxImLastLineHtml(rep, t, tf) {
      if (!rep || !rep.filename) return "";
      const bits = [];
      bits.push(`<b>${esc(t("Last import"))}</b>`);
      if (rep.created_at) bits.push(esc(fmtDateTime(rep.created_at)));
      if (rep.articles != null) {
        const n = fmtNum(Number(rep.articles), 0);
        bits.push(rep.articles_basis === "planned"
          ? esc(tf("{n} articles planned", { n }))
          : esc(tf("{n} articles", { n })));
      }
      // Coloured text, never the toast `.note` box inside a sentence (Y2, as I9 did for
      // the run header): the box's padding and shadow broke the one quiet line apart.
      if (rep.outcome && rep.outcome !== "ok") {
        bits.push(`<span style="color:var(--err)">${esc(t("did not complete"))}</span>`);
      }
      const href = `/api/backup/import-reports/${encodeURIComponent(rep.filename)}?format=md`;
      bits.push(`<a href="${href}" target="_blank" rel="noopener">${esc(t("open report"))}</a>`);
      return bits.join(" \u00b7 ");
    }

    // Q216 = a: what the checkpoint costs, from the queue's OWN resolved K so the
    // sentence can never disagree with the number the run will use. Composed with tf()
    // from a keyed template rather than rendering the backend's `checkpoint.note`,
    // which is English prose (the recorded rule that a method/reason/caveat field is
    // documentation for a reader, so it is subject to i18n).
    async function _uxImCheckpointNote() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const host = document.getElementById("ux-imp-checkpoint");
      if (!host) return;
      let k = null;
      try {
        const st = await api("/api/backup/import-queue/status");
        k = st && st.checkpoint && st.checkpoint.k;
      } catch (e) { /* best-effort: a sentence we cannot ground is not printed */ }
      host.innerHTML = _uxImCheckpointHtml(k, t, tf);
    }

    function _uxImCheckpointHtml(k, t, tf) {
      const n = Number(k);
      if (!Number.isFinite(n) || n < 1) return "";  // unread K: no claim at all
      if (n === 1) return esc(t("Every backup is verified and written to your corpus as soon as it finishes."));
      return esc(tf(
        "Verified and written to your corpus once every {k} backups \u2014 nothing is durable until a save, so a stop or a crash before one means those backups have to be imported again.",
        { k: n }
      ));
    }

    // REMOVED 2026-09-16 (R1, Q201 = a): `_uxShowLastCompletedSummary`.
    //
    // It existed for a real field report (2026-07-16, "after a successful import the
    // interface doesn't show the amounts of deduplicated and other import statistics"):
    // a long restore outlives the browser tab, so the JS closure that would have
    // rendered the result is gone, and reopening the dialog used to blank the summary
    // and discard it forever. Its fix was to recover each job manager's last completed
    // summary and re-render the FULL report on every reopen.
    //
    // The maintainer's own ruling reverses that shape, not the need behind it: the
    // dialog is a fresh page (R1), and the result now lives in the PERSISTED import
    // report, which survives the tab, the process and the machine -- strictly more
    // durable than a process-wide singleton's last summary ever was. `_uxImLastLine`
    // is what points at it, and Settings -> Data & backup lists every one (Q222 = b).
    // Recorded here rather than deleted silently, because the next reader of the
    // 2026-07-16 report needs to know where its answer went.

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
      // NOT DURING AN IMPORT (2026-09-26, I8). The volumes manager runs one job at a time
      // and the import's restore IS that job, so a verify cannot start -- and pointing the
      // one chain at it froze the run's rows. Said in plain words, before anything moves.
      if (_uxImWatch === "queue" || (_uxImLastStatus && _uxImLastStatus.state === "running")) {
        toast(t("An import is running — verify the backup once it has finished."), "err");
        return;
      }
      summary.innerHTML = ""; st.textContent = t("Verifying…"); btn.disabled = true;
      try {
        // ONE chain (Q206 = a): the start is still guarded by the same
        // job-state-as-truth check _uxStartThenPoll applies -- a lost START response
        // must not print a fatal over a job that is genuinely running -- and the
        // POLLING then belongs to _uxImTick, which is the only thing in this dialog
        // that owns #ux-imp-bar. The guard accepts only a live VERIFY job (I8).
        await _uxImStartGuarded(
          () => api("/api/backup/v2/volumes/verify", { method: "POST", body: JSON.stringify({ src, passphrase: pass }) }),
          "/api/backup/v2/volumes/status", "verify");
        const s = await _uxImWatchVerify();
        if (bar) bar.style.display = "none"; prog.textContent = "";
        _uxRenderVerify(summary, (s && s.summary && s.summary.report) || {}, t);
        st.textContent = "";
      } catch (e) {
        if (bar) bar.style.display = "none"; prog.textContent = "";
        summary.innerHTML = `<span style="color:var(--err)">${esc(t("Verification failed:"))} ${esc(ooServerText(e.message || e))}</span>`;
        st.textContent = "";
      }
      btn.disabled = false;
      // The chain was the verify's; hand it back to whatever the dialog was watching
      // before, so a run (or a draining stage 4) does not stay frozen after it (I8).
      if (!_uxImWatch && _uxImLastStatus) {
        if (_uxImLastStatus.state === "running") _uxImWatchQueue();
        else if (_uxImStage4Owed(_uxImRx)) _uxImWatchReindex();
      }
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
        const tfv = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf
          : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
        // The count in a keyed frame (R14) and the signature through the shared label
        // frame (R2): "5 volumes" welded a raw count to an English noun, and "signature:"
        // carried its own colon.
        const nVol = rep.volumes === 1 ? tfv("{n} volume", { n: fmtNum(1, 0) }) : tfv("{n} volumes", { n: fmtNum(rep.volumes, 0) });
        lines.push(`<div class="muted">${esc(nVol)} · ${ooLabelHtml(esc(t("signature")), esc(String(rep.signature || "—")))}${rep.decrypted ? " · " + esc(t("decrypted & checked")) : ""}</div>`);
      }
      const probs = Array.isArray(rep.problems) ? rep.problems : [];
      // padding-inline-START (I-4's class): in RTL the bullets sit on the right.
      if (probs.length) lines.push(`<ul style="margin:4px 0 0;padding-inline-start:18px">${probs.map(p => `<li>${esc(p)}</li>`).join("")}</ul>`);
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

    // THE Q701-NOTE TRUST TOGGLE, import half. Seeded from the operator's stored
    // first-launch answer so the control opens on the choice they already made, and
    // overriding it here changes THIS import only -- the stored default is untouched,
    // because an import is not the place to silently re-answer a setting.
    async function _uxImTrustRow(applies) {
      const row = document.getElementById("ux-imp-trust-row");
      const box = document.getElementById("ux-imp-trust");
      if (!row || !box) return;
      row.style.display = applies ? "block" : "none";
      if (!applies) return;
      try {
        const s = await api("/api/settings");
        box.checked = s.trust_backup_fetch_history !== false;
      } catch (e) {
        // Unreadable settings: fall back to the SHIPPED default rather than to
        // whatever the box happened to hold, so the control never shows a choice
        // nobody made. Mirrors resolve_trust_fetch_history's own fallback.
        box.checked = true;
      }
    }

    // null when the row is hidden -- "this import did not choose", which the server
    // resolves to the stored answer. Never a bool read off an invisible checkbox.
    function _uxImTrust() {
      const row = document.getElementById("ux-imp-trust-row");
      const box = document.getElementById("ux-imp-trust");
      if (!row || !box || row.style.display === "none") return null;
      return !!box.checked;
    }

    async function _uxImScan(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const src = (document.getElementById("ux-imp-src").value || "").trim();
      if (!src) { toast(t("Enter a folder to scan."), "err"); return; }
      const st = document.getElementById("ux-imp-status");
      const box = document.getElementById("ux-imp-checklist");
      document.getElementById("ux-imp-summary").innerHTML = "";
      _uxImSummaryArgs = null;
      // A new scan is a new import in the making, so a FINISHED run's rows and its
      // "Import failed:" line go with the old checklist (2026-09-28 walk): left in place
      // they sat under the new folder's checklist as if they described it. A run still
      // going keeps its rows -- they are live, and Stop lives among them.
      if (!(_uxImLastStatus && _uxImLastStatus.state === "running")) {
        _uxImResetRunView();
        if (_uxImWatch !== "verify") {   // a Verify in flight keeps its chain and its line
          _uxImStopChain();
          const pr = document.getElementById("ux-imp-progress");
          if (pr) pr.textContent = "";
        }
      }
      st.textContent = t("Scanning…"); box.innerHTML = ""; btn.disabled = true;
      try {
        const r = await api("/api/backup/import-scan?path=" + encodeURIComponent(src));
        const f = r.found || {};
        const rows = [];
        const corpus = Array.isArray(f.corpus) ? f.corpus : (f.corpus ? [f.corpus] : []);
        const tfs = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf
          : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
        // Every bracket on this checklist is the keyed "({text})" frame, as on the export
        // side's (J-3): welded ASCII brackets put "(加密卷 …)" around Chinese text, where
        // the locale writes （…）. The frame is filled with a marker and escaped, then the
        // marker is swapped for the (already escaped) HTML, so a file name can ride inside
        // it as an LTR isolate: in Arabic "2 .eml" drew as "eml. 2" (J-2's rule for names).
        const paren = (html) => esc(tfs("({text})", { text: "\u0001" })).replace("\u0001", () => html);
        const ltr = (s) => `<bdi dir="ltr" style="overflow-wrap:anywhere">${esc(s)}</bdi>`;
        if (corpus.length) {
          const nv = corpus.reduce((a, c) => a + (c.volumes || 0), 0);
          // Counts as keyed one/many frames through fmtNum (R14).
          const bits = [t("encrypted volumes — additive, nothing you already have is overwritten")];
          if (nv) bits.push(nv === 1 ? tfs("{n} volume", { n: fmtNum(1, 0) }) : tfs("{n} volumes", { n: fmtNum(nv, 0) }));
          if (corpus.length > 1) bits.push(tfs("{n} sets", { n: fmtNum(corpus.length, 0) }));
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-corpus" checked> ${esc(t("Restore corpus backup"))} <span class="muted">${paren(esc(bits.join(" · ")))}</span></label>`);
        }
        if (f.legacy_backup && f.legacy_backup.length) {
          const n = f.legacy_backup.length;
          // One key per number (R14): an English "s" was welded onto the TRANSLATED label.
          const legacy = n === 1 ? t("Restore legacy backup file") : t("Restore legacy backup files");
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-legacy" checked> ${esc(legacy)} <span class="muted">${paren(`${esc(fmtNum(n, 0))} · ${f.legacy_backup.map(x => ltr(x.name)).join(", ")}`)}</span></label>`);
        }
        if (f.blobs) {
          // Each category by the export checklist's own label with a keyed file count:
          // "wiki 3 · maps 1" was English in every locale.
          const b = f.blobs, parts = [];
          const files = (n) => (n === 1 ? tfs("{n} file", { n: fmtNum(n, 0) }) : tfs("{n} files", { n: fmtNum(n, 0) }));
          if (b.wiki) parts.push(ooLabelText(t("Wikipedia dumps"), files(b.wiki.count || 0)));
          if (b.maps) parts.push(ooLabelText(t("Offline maps"), files(b.maps.count || 0)));
          if (b.models) parts.push(ooLabelText(t("LLM models"), files(b.models.count || 0)));
          rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-blobs" checked> ${esc(t("Restore large data"))} <span class="muted">${paren(esc(parts.join(" · ")))}</span></label>`);
        }
        if (f.newsletters) rows.push(`<label class="switch" style="margin:0"><input type="checkbox" id="ux-i-eml" checked> ${esc(t("Import newsletters"))} <span class="muted">${paren(ltr(`${fmtNum(f.newsletters.count, 0)}${f.newsletters.capped ? "+" : ""} .eml`))}</span></label>`);
        const notes = [];
        if (f.source_csv) notes.push(esc(t("Source CSV found — import it from the Sources panel for now.")) + " " + paren(f.source_csv.map(ltr).join(", ")));
        box.innerHTML = rows.join("") || `<span class="muted">${esc(t("Nothing importable found in this folder."))}</span>`;
        if (notes.length) box.innerHTML += `<p class="muted" style="margin:4px 0 0">${notes.join("<br>")}</p>`;
        // A passphrase is needed for the encrypted corpus AND for legacy archives.
        const needsPass = corpus.length > 0 || (f.legacy_backup && f.legacy_backup.length > 0);
        document.getElementById("ux-imp-pass-row").style.display = needsPass ? "block" : "none";
        // The Q701-note toggle: offered only when this scan found something that CAN
        // carry a scraping history. `needsPass` is the same predicate for the same
        // reason -- a corpus or legacy archive -- but it is read separately here so a
        // future plaintext backup does not silently hide the toggle with the passphrase.
        await _uxImTrustRow(corpus.length > 0 || (f.legacy_backup && f.legacy_backup.length > 0));
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
      // The Q701-note answer for THIS import. Sent ONLY on the two kinds that carry a
      // scraping history; a blobs or newsletters item gets no field at all, so the
      // server sees `None` = "this import did not choose" and nothing is asserted on
      // their behalf. `_uxImTrust()` reads the checkbox only when the row is really
      // shown, so an unseen control can never speak for the operator.
      const trust = _uxImTrust();
      if (corpus.length && cb("ux-i-corpus")) {
        for (const c of corpus) items.push({ kind: "corpus", path: c.path, label: _uxImLabel(c.path, t("Corpus backup")), trust_fetch_history: trust });
      }
      if (legacy.length && cb("ux-i-legacy")) {
        for (const lg of legacy) items.push({ kind: "legacy", path: lg.path, label: lg.name, trust_fetch_history: trust });
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
      // A NEW RUN STARTS ON A BLANK RUN VIEW (2026-09-28 walk). Only a reopen reset these
      // surfaces, so an import started in the SAME opening as a failed one drew its first
      // rows under the failed run's: "2 failed · Failed", both backups red with their
      // error, "Analytics are complete" -- until the first tick replaced them, which is as
      // long as the start request takes on a big backup. The chain is stopped too, or a
      // stage-4 watch left by the last run repaints that run's rows from its own status.
      // The start line in #ux-imp-progress is the only thing shown until the run reports.
      _uxImStopChain();
      _uxImResetRunView();
      const progEl = document.getElementById("ux-imp-progress");
      if (progEl) progEl.textContent = t("Starting…");
      const bgBtn = document.getElementById("ux-imp-bg");
      if (bgBtn) bgBtn.style.display = "";
      try {
        await api("/api/backup/import-queue/start", { method: "POST", body: JSON.stringify({ items, passphrase: pass }) });
      } catch (e) {
        btn.disabled = false;
        if (bgBtn) bgBtn.style.display = "none";
        document.getElementById("ux-imp-progress").innerHTML = `<span style="color:var(--err)">${esc(t("Import failed:"))} ${esc(ooServerText(e.message || e))}</span>`;
        return;
      }
      if (progEl) progEl.textContent = "";
      _uxImWatchQueue();
    }

    // A backup set's folder name is its most useful identity (the maintainer's six
    // backups differ only by folder). Falls back to the generic label, never to a
    // blank row.
    function _uxImLabel(path, fallback) {
      const parts = String(path || "").split(/[\\/]+/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : fallback;
    }

    // ── THE ONE POLL CHAIN (Q206 = a, R2) ──────────────────────────────────
    // ONE timer, ONE subject, ONE bar owner. Until 2026-09-16 the Import dialog had
    // two chains that both painted #ux-imp-bar: the generic 1200 ms job poller behind
    // Verify (_uxPoll) and the 1000 ms queue renderer. They never fought over the bar
    // by LUCK rather than by construction -- pressing Verify while a reattached run
    // was polling had both writing the same element on different clocks, which is the
    // overlapping/blinking R2 calls a defect. The subject is what makes one owner
    // structural: the chain polls whatever it is watching, and it can watch one thing.
    let _uxImPollTimer = null;     // THE timer. There is exactly one.
    let _uxImWatch = null;         // "verify" | "queue" | null -- the chain's subject
    let _uxImFails = 0;            // consecutive transport failures, for the backoff
    let _uxImSettle = null;        // {resolve, reject} for the verify mode's promise
    // THE GENERATION, and why the subject alone was not enough. Every (re)start and every
    // stop bumps it; a tick captures it on entry and abandons itself if it changed across
    // ANY await. Clearing `_uxImPollTimer` cancels a SCHEDULED tick, but a tick that is
    // mid-fetch has already nulled that variable, so it survived the clear -- and
    // `_uxImWatch !== subject` could not see it either, because a re-watch of the SAME
    // subject (Stop re-arms the queue watch; so does reopening the dialog on a live run)
    // leaves the subject identical. Two concurrent queue chains then both reached the
    // terminal branch: two "Import complete." toasts and a twice-rebuilt summary -- the
    // overlapping-messages defect this chain exists to have removed. Found 2026-09-16 by
    // an adversarial read, not by a test, which is why the fix is structural.
    let _uxImGen = 0;
    // What the result block was last drawn from, so a language switch can redraw it in
    // the new language without re-reading the queue (Y6).
    let _uxImSummaryArgs = null;

    // STAGE 4 RIDES THE SAME CHAIN, at its own cadence. The backlog read behind it is
    // LINEAR in the pending article count -- measured on a plaintext fixture, median
    // of five: 0.97 ms at 10,000 pending articles, 10.5 ms at 100,000, 101.9 ms at
    // 1,000,000 -- and the figure it returns moves on the scale of minutes, so putting
    // it on the 1 s tick would spend a tenth of a core on a number that cannot have
    // changed. Same chain, same timer, slower read.
    const _UX_IM_RX_INTERVAL_MS = 5000;
    let _uxImRx = null, _uxImRxAt = 0;
    // The last status the chain rendered. Held ONLY so a language switch can re-render
    // the interpolated surfaces from the same facts -- never polled from, never a
    // second source of truth: the chain overwrites it on every tick.
    let _uxImLastStatus = null;
    // WHICH PICTURE of that status the dialog is showing: "run" (a run watched live --
    // every row) or "fresh" (a reopened dialog: the quiet line, plus only what is still
    // unfinished -- see _uxImFreshView). null before either.
    let _uxImView = null;

    // JOB-STATE-AS-TRUTH for the START request (the property _uxStartThenPoll carries
    // for the export dialog): the POST returns AFTER the worker thread is spawned, so
    // a transport hiccup that loses the RESPONSE -- the request reached the server,
    // the job is running -- must not print a fatal "failed". On a start error consult
    // /status: a LIVE job (running|paused) proves the start landed and we fall through
    // to the chain; anything else re-throws so a real 400/409 still surfaces. NOT
    // "done": a just-started job cannot be instantly done, so a stale "done" here must
    // never mask a failed start as complete.
    //
    // THE JOB MUST BE THE ONE WE STARTED (2026-09-26, I8). The volumes manager runs ONE
    // job of three modes, and during an import that job is the import's own RESTORE -- so
    // a Verify refused with 409 found "a live job" here, fell through, and pointed the one
    // chain at the import's restore: the run's rows froze and "Verify:" narrated someone
    // else's merge. `mode`, when given, has to match as well as the state.
    async function _uxImStartGuarded(startCall, statusUrl, mode) {
      try {
        await startCall();
      } catch (e) {
        let st = null;
        try { st = await api(statusUrl); } catch (_) { throw e; }
        const s = (st && st.state) || "";
        if (!(s === "running" || s === "paused")) throw e;
        if (mode && (st && st.mode) !== mode) throw e;
      }
    }

    function _uxImStopChain() {
      if (_uxImPollTimer) clearTimeout(_uxImPollTimer);
      _uxImPollTimer = null;
      _uxImWatch = null;
      _uxImGen++;                  // an in-flight tick belongs to the old generation
    }

    // Point the chain at the import run and (re)start it.
    function _uxImWatchQueue() {
      _uxImWatch = "queue";
      _uxImFails = 0;
      _uxImGen++;
      if (_uxImPollTimer) { clearTimeout(_uxImPollTimer); _uxImPollTimer = null; }
      _uxImTick();
    }

    // Point the chain at STAGE 4 alone (2026-09-26, I1). The re-index outlives the run:
    // it only STARTS once the run's exclusive window has closed, so the queue's terminal
    // tick -- the last thing that ever read it -- saw at best the backlog before the drain
    // began, and the row froze there ("3,600 left" while 4,800 drained). Same timer, same
    // generation, its own subject, at the pace the backlog read can afford; it stops when
    // the re-index has nothing left or the dialog is closed.
    function _uxImWatchReindex() {
      _uxImWatch = "reindex";
      _uxImFails = 0;
      _uxImGen++;
      if (_uxImPollTimer) { clearTimeout(_uxImPollTimer); _uxImPollTimer = null; }
      _uxImPollTimer = setTimeout(_uxImTick, _UX_IM_RX_INTERVAL_MS);
    }

    // Stage 4's ONE read, shared by the queue tick, the reattach and the stage-4 watch so
    // they can never disagree about where it comes from. Unread is null -- the row then
    // SAYS it could not be read -- and never a zero.
    async function _uxImReadRx() {
      _uxImRxAt = Date.now();
      try { _uxImRx = await api("/api/backup/reindex-backlog/resume/status"); }
      catch (e) { _uxImRx = null; }
      return _uxImRx;
    }

    // Is stage 4 still OWED? Pure. Running, or a readable backlog above zero. An unread
    // status (null) or an unreadable backlog is NOT owed: it is unknown, and a row that
    // could only say "could not be read" on a page that is otherwise fresh adds nothing.
    function _uxImStage4Owed(rx) {
      if (!rx) return false;
      if (rx.state === "running" || rx.state === "paused") return true;
      const bk = rx.backlog || null;
      return !!(bk && bk.available !== false && Number(bk.articles_pending) > 0);
    }

    // What a REOPEN shows of a run that is not running (R1, Q201 = a -- and Q204/Q205,
    // which put stage 4 inside the import experience). Pure, so the decision is testable
    // apart from the DOM. A finished run is NOT re-rendered: the dialog is a fresh page
    // with one quiet line. Two facts may still stand beside that line, because both are
    // about work that has not finished rather than a report of work that has: an
    // INTERRUPTED run (its backups must be imported again -- the one thing a fresh page
    // must not swallow), and a stage 4 still draining ("resuming re-index").
    function _uxImFreshView(st, rx) {
      const running = !!(st && st.state === "running");
      const hasRun = !!(st && (st.items || []).length);
      return {
        full: running,
        interrupted: !running && hasRun && st.state === "interrupted",
        stage4: !running && hasRun && _uxImStage4Owed(rx),
      };
    }

    // Point the chain at a volumes VERIFY job and resolve when it reaches a terminal
    // state. Returns the final status object, exactly as the old _uxPoll promise did,
    // so _uxImVerify's own error handling is unchanged.
    function _uxImWatchVerify() {
      if (_uxImPollTimer) { clearTimeout(_uxImPollTimer); _uxImPollTimer = null; }
      _uxImWatch = "verify";
      _uxImFails = 0;
      _uxImGen++;
      return new Promise((resolve, reject) => {
        _uxImSettle = { resolve, reject };
        _uxImTick();
      });
    }

    // ONE tick of the ONE chain. Polls the current subject, paints the bar, renders,
    // and schedules itself. Nothing else in this file owns #ux-imp-bar.
    async function _uxImTick() {
      _uxImPollTimer = null;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const subject = _uxImWatch;
      const gen = _uxImGen;
      if (!subject) return;
      const url = subject === "verify"
        ? "/api/backup/v2/volumes/status"
        : subject === "reindex"
          ? "/api/backup/reindex-backlog/resume/status"
          : "/api/backup/import-queue/status";
      let st = null;
      try {
        st = await api(url);
        _uxImFails = 0;
      } catch (e) {
        // JOB-STATE-AS-TRUTH: a dropped poll does not mean the job failed -- it keeps
        // running server-side. Back off and keep watching; only a backend-reported
        // terminal error is a failure. (Carried over verbatim from _uxPoll, which the
        // verify path used to reach; the property must not be lost with the chain.)
        _uxImFails++;
        if (subject === "verify" && _uxImFails > 40) {
          const settle = _uxImSettle; _uxImSettle = null; _uxImStopChain();
          if (settle) settle.reject(new Error(t("Lost contact with the backup job — check the task manager; it may still be running.")));
          return;
        }
        if (_uxImWatch !== subject || _uxImGen !== gen) return;  // superseded while we awaited
        if (subject === "reindex") {
          // Stage 4 is watched only for someone looking at it: no retries behind a
          // closed dialog.
          const dlg = document.getElementById("ux-import");
          if (!dlg || !dlg.open) { _uxImStopChain(); return; }
        }
        _uxImPollTimer = setTimeout(_uxImTick, Math.min(1200 * Math.pow(1.6, _uxImFails - 1), 15000));
        return;
      }
      if (_uxImWatch !== subject || _uxImGen !== gen) return;  // a newer chain owns the bar
      if (subject === "verify") { _uxImTickVerify(st, t); return; }
      if (subject === "reindex") { _uxImTickReindex(st, t); return; }
      await _uxImTickQueue(st, t, gen);
    }

    // One stage-4 tick: repaint stage 4 and the analytics statement from the run the
    // dialog is already showing (never a second queue read), and keep going while the
    // re-index still owes work and the dialog is open to see it.
    function _uxImTickReindex(rx, t) {
      _uxImRx = rx; _uxImRxAt = Date.now();
      const dlg = document.getElementById("ux-import");
      const st = _uxImLastStatus;
      if (!dlg || !dlg.open || !st) { _uxImStopChain(); return; }
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const only = _uxImView === "fresh" ? "reindex" : null;
      _uxImRenderStages(st, rx, t, tf, only);
      _uxImRenderStatements(st, rx, t, tf, only);
      if (_uxImStage4Owed(rx)) { _uxImPollTimer = setTimeout(_uxImTick, _UX_IM_RX_INTERVAL_MS); return; }
      _uxImStopChain();
    }

    function _uxImTickVerify(st, t) {
      const bar = document.getElementById("ux-imp-bar");
      const prog = document.getElementById("ux-imp-progress");
      const state = st.state || "";
      const view = _uxProgressView("volumes", st, t);
      _uxPaintBar(bar, view);
      // The locale's separator (R2), not an English colon welded after the label.
      if (prog) prog.innerHTML = ooLabelHtml(esc(t("Verify")), view.text);
      if (state === "done" || state === "paused") {
        const settle = _uxImSettle; _uxImSettle = null; _uxImStopChain();
        if (settle) settle.resolve(st);
        return;
      }
      if (state === "error" || state === "cancelled") {
        const settle = _uxImSettle; _uxImSettle = null; _uxImStopChain();
        if (settle) settle.reject(new Error(st.error || view.text || state));
        return;
      }
      _uxImPollTimer = setTimeout(_uxImTick, 1200);
    }

    async function _uxImTickQueue(st, t, gen) {
      // Stage 4 is a SEPARATE, resumable job that outlives this run, so its numbers
      // come from the job itself rather than from the queue (which would be reporting
      // on work it does not own). Paced; see _UX_IM_RX_INTERVAL_MS.
      // UNPACED ON THE TERMINAL TICK (2026-09-26, I1): the pacing usually made the last
      // tick skip the read, so the row the run ended on was up to five seconds old.
      const now = Date.now();
      if (st.state !== "running" || now - _uxImRxAt >= _UX_IM_RX_INTERVAL_MS) {
        await _uxImReadRx();   // unread: the row says so, never a zero
        // RE-GUARDED after ITS OWN await, not only after the caller's. A stale queue
        // tick resuming here rendered over whatever owned the bar and, on a terminal
        // status, called _uxImStopChain() -- which nulls the chain state whoever owns
        // it. A Verify started during that window was killed silently: its promise
        // never settled, so the button stayed disabled with no error, forever.
        if (gen !== undefined && (_uxImGen !== gen || _uxImWatch !== "queue")) return;
      }
      _uxImRenderQueue(st);
      if (st.state === "running") { _uxImPollTimer = setTimeout(_uxImTick, 1000); return; }
      // Terminal: surface the per-item reports through the SAME summary renderer the
      // single-archive path uses, so nothing about the outcome view changes.
      _uxImStopChain();
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
        // An artifact this corpus had ALREADY merged completes in milliseconds with an
        // empty report. Its row read "nothing imported" -- true, and indistinguishable
        // from a backup that held nothing -- while the server's summary said WHEN and as
        // WHICH batch it was merged (R11). That answer travels with the row now.
        if (sm.skipped === "already-merged") {
          base.merged = {
            batch: sm.merged_as_batch, at: sm.merged_at,
            open_group: !!sm.in_open_checkpoint_group,
          };
        }
        if (it.kind === "corpus" || it.kind === "legacy") {
          const rep = sm.report || sm || {};
          summaries.push({ ...base, plan: rep.plan || {}, ..._uxPlanExtras(rep) });
        } else if (it.kind === "blobs") {
          // Counts as keyed one/many frames with a grouped number (R14): "3 restored"
          // welded a raw count to an English-ordered adjective that agrees with nothing.
          const TF = _uxDurTf();
          const nR = sm.restored || 0, nS = sm.skipped || 0;
          summaries.push({ ...base, tally: { restored: nR, skipped: nS },
            lines: [
              nR === 1 ? TF("{n} file restored", { n: fmtNum(nR, 0) }) : TF("{n} files restored", { n: fmtNum(nR, 0) }),
              nS === 1 ? TF("{n} file skipped", { n: fmtNum(nS, 0) }) : TF("{n} files skipped", { n: fmtNum(nS, 0) }),
            ],
            // A member the restore TURNED AWAY has to be readable in the artifact an
            // operator reads afterwards. This used to ride only on the recovered
            // last-completed summary (removed 2026-09-16 with R1); the queue's own
            // summary is the post-hoc artifact now, and it never carried it -- so the
            // fields travel through the queue item and are rendered here.
            caveat: _fbRefusalLines(sm) });
        } else if (it.kind === "newsletters") {
          const tl = sm.tally || {};
          const TF = _uxDurTf();
          const nSt = tl.stored || 0, nDu = tl.duplicate || 0, nEm = tl.empty || 0, nEr = tl.errors || 0;
          summaries.push({ ...base, tally: { stored: nSt, duplicate: nDu, empty: nEm, errors: nEr },
            lines: [
              nSt === 1 ? TF("{n} newsletter stored", { n: fmtNum(nSt, 0) }) : TF("{n} newsletters stored", { n: fmtNum(nSt, 0) }),
              nDu === 1 ? TF("{n} newsletter already present", { n: fmtNum(nDu, 0) }) : TF("{n} newsletters already present", { n: fmtNum(nDu, 0) }),
              nEm === 1 ? TF("{n} newsletter empty", { n: fmtNum(nEm, 0) }) : TF("{n} newsletters empty", { n: fmtNum(nEm, 0) }),
              nEr === 1 ? TF("{n} error", { n: fmtNum(nEr, 0) }) : TF("{n} errors", { n: fmtNum(nEr, 0) }),
            ] });
        }
      }
      if (summaries.length) {
        _uxImSummaryArgs = {
          summaries,
          run: {
            state: st.state, elapsed_s: st.elapsed_s,
            items_done: st.items_done, items_total: st.items_total,
            // The re-index job's own read, taken unpaced on this terminal tick (I1): the
            // backlog "Articles awaiting indexing" falls back to when no item carries a
            // hand-off snapshot (Y4).
            rx: _uxImRx,
          },
        };
        _renderImportSummary(document.getElementById("ux-imp-summary"), summaries, _uxImSummaryArgs.run);
      }
      // What just finished is now the LAST import (Y7), and a history list the operator
      // already opened in Settings -> Data gains its row (Y5). Both re-read the persisted
      // reports; neither is drawn from this run's in-memory state.
      try { _uxImLastLine(); } catch (_e) {}
      try {
        const h = document.getElementById("imp-history");
        if (h && h.innerHTML.trim()) loadImportHistory();
      } catch (_e) {}
      const dlg = document.getElementById("ux-import");
      if (dlg && !dlg.open) {
        if (st.state === "done") toast(t("Import complete."));
        else if (st.state === "stopped") toast(t("Import stopped."));
        else if (st.state === "error") toast(t("Import finished with errors."), "err");
      }
      // The run is over; stage 4 is not (I1). Keep its row counting while someone can
      // see it -- the drain only starts once the run's window has closed.
      if (dlg && dlg.open && (_uxImStage4Owed(_uxImRx) || !_uxImRx)) _uxImWatchReindex();
    }

    const _UX_IM_STATE_LABEL = {
      queued: "Waiting", running: "Running", done: "Done", error: "Failed",
      cancelled: "Cancelled", skipped: "Skipped", stopped: "Stopped",
      interrupted: "Interrupted",
      // CHECKPOINT INTERVAL K. "Merged, not yet saved" is the whole distinction: the
      // articles are in this run's working copy and not in the corpus, so calling it
      // "Done" would claim a change that has not happened, and calling it "Running"
      // would claim work still going. Both states are unreachable at K = 1, where
      // every backup commits as it finishes; at the ruled K = 3 they are ordinary.
      staged: "Merged — not yet saved",
      discarded: "Discarded — import it again",
    };

    // The four stage rows, in order. `key` matches the backend's own (import_queue
    // ._stage_rows), so neither side invents a stage the other does not have.
    // The run states a stage row can carry that mean "this run ended without finishing",
    // beside the label table it is read with: a row in one of these is labelled from
    // _UX_IM_STATE_LABEL above, so the four words are the ones already shipped x12. The
    // backend's own set is `_ENDED` in import_queue._stage_rows.
    const _UX_IM_ENDED = { interrupted: 1, error: 1, cancelled: 1, stopped: 1 };
    // The RUN's own terminal states (import_queue: `_state` once the loop has left).
    // Named, not "anything but running", so a status that carries no state at all is
    // never read as a finished run.
    const _UX_IM_RUN_ENDED = { done: 1, error: 1, stopped: 1, interrupted: 1 };

    const _UX_IM_STAGE_LABEL = {
      verify_stage: "Check the backup and unpack it",
      merge_swap: "Merge it into your corpus and save",
      search_index: "Merge the search index",
      reindex: "Re-index the imported articles",
    };

    // ROWS PATCHED IN PLACE, keyed (Q206 = a). The old renderer wrote
    // `rows.innerHTML = items.map(...)` on every tick, so a six-item run replaced six
    // unchanged DOM subtrees once a second. The signature is what makes "unchanged"
    // checkable: identical signature, and the DOM is not touched at all.
    function _uxRowNode(host, key) {
      for (const el of host.children) {
        if (el.getAttribute && el.getAttribute("data-row-key") === key) return el;
      }
      return null;
    }
    function _uxPatchRow(host, key, sig, html) {
      let el = _uxRowNode(host, key);
      if (!el) {
        el = document.createElement("div");
        el.setAttribute("data-row-key", key);
        host.appendChild(el);
      }
      if (el.dataset.sig === sig) return el;   // unchanged: no write
      el.dataset.sig = sig;
      el.innerHTML = html;
      return el;
    }
    function _uxPruneRows(host, keys) {
      const want = {};
      for (const k of keys) want[k] = true;
      for (const el of Array.from(host.children)) {
        const k = el.getAttribute && el.getAttribute("data-row-key");
        if (k && !want[k]) el.remove();
      }
    }

    function _uxImRenderQueue(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
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
      // The run's own keyed frame, its numbers grouped (R14): "3/6 imported" welded a
      // bare fraction to an English participle.
      const head = esc(tf("{done} of {total} backups imported", {
        done: fmtNum(items.filter(i => i.state === "done").length, 0), total: fmtNum(items.length, 0) }));
      // COMMITTED vs STAGED, at any moment (the checkpoint-interval ask). Rendered
      // ONLY when something is actually staged: at K = 1 there never is, so this
      // says nothing rather than printing a 0 that would read as a finding about
      // the import. The sentence names what a Stop would cost, because that is the
      // one thing the number alone does not say.
      const cp = st.checkpoint || {};
      //
      // PLAIN BLOCK TEXT, never the toast class (2026-09-26, I9, R2). These lines were
      // inline `<span class="note">` -- the TOAST style: 11 px padding, a shadow and a
      // slide-in animation -- so the box overlapped the header line above it, and because
      // the header carried the elapsed seconds the whole note was rewritten every tick and
      // the animation replayed once a second. The blinking R2 names, by construction.
      const stagedLine = (st.items_staged > 0)
        ? `<div class="card-caveat">${esc(tf(
            "Merged, not yet saved: {n} — written to your corpus at the next checkpoint, one every {k} backups.",
            { n: fmtNum(Number(st.items_staged), 0), k: cp.k || 1 }
          ))}</div>`
        : "";
      // THE TAIL PHASE HAS TO HAVE A HOME (field report 2026-08-11). A run does not end
      // when its last item does: _tune_after_run then merges the search index, inside the
      // same exclusive window, for minutes on a large corpus. The per-item live block
      // below only renders inside a row whose item is `running`, so with every item
      // "Done" that phase had nowhere to appear -- the header read "1/1 imported", the
      // item read "Done", collection was still paused and one core sat at 100%. The
      // backend was already publishing it; there was simply no element to put it in.
      const tail = items.some((i) => i.state === "running") ? "" : _uxImPhaseBits(st.live, t);
      const tailLine = (st.state === "running" && tail) ? `<div>${tail}</div>` : "";
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
      // TWO PARTS, patched apart (I9): the header carries the elapsed seconds and changes
      // every tick; everything under it changes only when the run's facts do, and is not
      // touched in between.
      const headHtml = `<b>${head}</b>${st.elapsed_s != null ? ` · ${esc(_uxImDur(st.elapsed_s))}` : ""}`;
      const bodyHtml = stagedLine
        + tailLine
        + (st.state === "running" && st.collection_paused ? `<div>${esc(t("Background collection is paused for this whole import and resumes when it finishes."))}</div>` : "")
        + (st.state === "interrupted" ? _uxImInterruptedHtml(t) : "");
      if (note) {
        _uxPatchRow(note, "head", headHtml, headHtml);
        _uxPatchRow(note, "body", bodyHtml, bodyHtml);
      }

      _uxImLastStatus = st;
      _uxImView = "run";
      _uxImRenderStages(st, _uxImRx, t, tf);
      _uxImRenderStatements(st, _uxImRx, t, tf);

      for (const it of items) {
        // ISOLATED (2026-09-26, I12): a folder name is Latin text with a leading digit run,
        // and in an RTL page an un-isolated one is reordered around its neighbours --
        // "202609261808_OpenOmniscience_Backup_2" drew as "OpenOmniscience_Backup_2 — Done ·
        // 4s_202609261808". <bdi> keeps it one unit in either direction.
        const label = `<bdi>${esc(it.label || it.kind)}</bdi>`;
        const state = esc(t(_UX_IM_STATE_LABEL[it.state] || it.state));
        const el = it.elapsed_s != null ? ` · ${esc(_uxImDur(it.elapsed_s))}` : "";
        // The item's error as the dialog's inline text (Y2), not the toast `.note` box --
        // a floating notification's padding, shadow and slide-in inside a list of rows.
        const err = it.error
          ? `<div class="hint" style="color:var(--err);margin:2px 0 0;margin-inline-start:14px;overflow-wrap:anywhere">${esc(ooServerText(it.error))}</div>`
          : "";
        const live = it.state === "running" ? _uxImLive(st.live, t) : "";
        const dot = {
          done: "var(--ok)", error: "var(--err)", running: "var(--accent)",
          // Not the OK green: a staged item is real progress that is not yet safe,
          // and painting it as done would say the opposite of its own label.
          staged: "var(--warn)", discarded: "var(--err)",
        }[it.state] || "var(--muted)";
        // Which of the four stages THIS item is in. Absent for a kind that does not
        // walk them (a large-data copy, a newsletter import): the backend says which
        // is which with `stage_applicable`, so an empty cell is never a failed read.
        //
        // ONLY WHILE IT IS ON ITS WAY (2026-09-26, I14). The stage is a high-water mark, so a
        // FINISHED backup kept "stage 2 of 4" -- the last stage it walked itself, stages 3
        // and 4 belonging to the run -- and a row reading "Done · stage 2 of 4" says both
        // "finished" and "half-way". A running item is in that stage; a staged one waits
        // in it for the checkpoint; any other state has left the per-item stages behind.
        const stg = (it.stage_applicable && it.stage && (it.state === "running" || it.state === "staged"))
          ? ` <span class="muted">· ${esc(tf("stage {n} of {total}", { n: it.stage, total: 4 }))}</span>`
          : "";
        // overflow-wrap (I13): at 375 px an unbroken folder name ran 46 px past the dialog.
        // The NAME breaks anywhere (it is a folder name, not prose), so it starts beside
        // its dot instead of leaving the dot alone on a line; the words after it still
        // break only at spaces.
        // margin-inline-END (2026-09-27 re-walk, I-4): a physical margin-right sat on the
        // dot's OUTER side in RTL, and the label touched it.
        const html = `<div style="overflow-wrap:anywhere"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot};margin-inline-end:6px"></span>`
          + `<b style="word-break:break-all">${label}</b> <span class="muted">— ${state}${el}</span>${stg}${live}</div>${err}`;
        _uxPatchRow(rows, String(it.id || it.label || it.kind), html, html);
      }
      _uxPruneRows(rows, items.map((it) => String(it.id || it.label || it.kind)));
    }

    // Q202 = a: four rows with their own progress. `rx` is the re-index job's own
    // status (stage 4 outlives the run, so the queue cannot speak for it) or null when
    // it could not be read -- which the row SAYS, rather than showing a zero.
    // `only` ("reindex") draws stage 4 alone: the fresh page a reopen shows while the
    // re-index of a finished run is still draining (_uxImFreshView).
    // Did the run END having brought nothing into the corpus? Pure. Every restore failed,
    // was cancelled or discarded -- none is done, and none was skipped as already there.
    // Stages 3 and 4 then have nothing of this import's to work on, and their own words
    // ("done", "complete") would claim otherwise beside two red "Failed" rows (2026-09-28
    // walk: a wrong passphrase read "Merge the search index -- done" and "Re-index the
    // imported articles -- complete").
    function _uxImNothingMerged(st) {
      if (!st || !_UX_IM_RUN_ENDED[st.state]) return false;
      const restores = (st.items || []).filter((i) => i.kind === "corpus" || i.kind === "legacy");
      return restores.length > 0 && !restores.some((i) => i.state === "done" || i.state === "skipped");
    }

    function _uxImRenderStages(st, rx, t, tf, only) {
      const host = document.getElementById("ux-imp-stages");
      if (!host) return;
      const stages = (st.stages || []).filter((r) => !only || String(r.key || r.n) === only);
      if (!stages.length) { host.innerHTML = ""; return; }   // older server: no claim
      const none = _uxImNothingMerged(st);
      for (const sRow of stages) {
        const key = String(sRow.key || sRow.n);
        const title = esc(t(_UX_IM_STAGE_LABEL[key] || key));
        // A run that ENDED is not pending, and grey-like-pending is how the backend's
        // own distinction became invisible. Deliberate endings (the operator stopped or
        // cancelled) are warned, not errored; an interrupt or a failure is an error.
        // Stage 4's dot reads the SAME status its text does (2026-09-27 re-walk, I-7): the
        // queue reports that row as "external" by design -- it does not own the re-index
        // -- so a dot keyed on the row's state stayed not-started grey through the whole
        // drain and after it, beside a line counting up to "complete".
        const idle = none && (key === "reindex"
          ? !(rx && (rx.state === "running" || rx.state === "paused"))
            && !(rx && rx.backlog && Number(rx.backlog.articles_pending) > 0)
          : key === "search_index" && sRow.state === "done");
        const dot = idle ? "var(--muted)" : key === "reindex" ? _uxImReindexDot(rx, st) : ({
                      done: "var(--ok)", running: "var(--accent)", pending: "var(--muted)",
                      external: "var(--muted)", stopped: "var(--warn)",
                      cancelled: "var(--warn)", interrupted: "var(--err)",
                      error: "var(--err)" }[sRow.state] || "var(--muted)");
        const bits = [];
        // The error words are COLOURED TEXT, never the toast `.note` box: an inline toast
        // (11 px padding, a shadow, a slide-in) inside a row overlaps the rows above and
        // below it -- the overlap R2 calls a defect (I9).
        if (idle) {
          bits.push(esc(t("nothing to do — no backup was imported")));
        } else if (key === "reindex") {
          bits.push(_uxImReindexBits(rx, t, tf, st));
        } else if (sRow.measured && sRow.total) {
          bits.push(esc(tf("{done} of {total} backups", { done: sRow.done || 0, total: sRow.total })));
          if (sRow.failed) bits.push(`<span style="color:var(--err)">${esc(tf("{n} failed", { n: sRow.failed }))}</span>`);
        } else if (sRow.state === "done") {
          bits.push(esc(t("done")));
        } else if (sRow.state === "running") {
          // No number, and the reason is stated rather than a bar drawn over nothing.
          bits.push(esc(t("running")));
        } else if (sRow.skipped) {
          bits.push(esc(t("skipped — the import was stopped")));
        } else if (!_UX_IM_ENDED[sRow.state]) {
          // "not started" is a claim about the FUTURE; on an ended row the ending below
          // is the whole truth (a stage the process died in HAD started).
          bits.push(esc(t("not started")));
        }
        // ...and it SAYS which ending it was, reusing _UX_IM_STATE_LABEL -- the same four
        // words the item rows already use, already translated. A row that reads "2 of 4
        // backups" with nothing else cannot distinguish "two still to come" from "the app
        // died after two", which is the whole point of the backend carrying the ending.
        if (_UX_IM_ENDED[sRow.state]) {
          bits.push(`<span style="color:var(--err)">${esc(t(_UX_IM_STATE_LABEL[sRow.state] || sRow.state))}</span>`);
        }
        if (sRow.phase) {
          bits.push(`<span class="muted">${esc(_uxVolPhase(sRow.phase, "restore", t))}</span>`);
        }
        const link = key === "reindex"
          ? ` <a href="#" data-on-click="ooPrevent(event);openTaskManager()">${esc(t("open the task manager"))}</a>`
          : "";
        const html = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dot};margin-inline-end:6px"></span>`
          + `<b>${sRow.n}. ${title}</b> <span class="muted">— ${bits.filter(Boolean).join(" · ")}</span>${link}`;
        _uxPatchRow(host, key, html, html);
      }
      _uxPruneRows(host, stages.map((r) => String(r.key || r.n)));
    }

    // Stage 4's own line, as a PURE function of the re-index job's status. THREE
    // states, kept apart on purpose: unread (we could not ask), idle-with-a-backlog
    // (work is owed and nothing is draining it), and running (a measured count). A
    // `0` for any of the first two would claim the re-index is finished.
    //
    // `st`, the run, decides what an EMPTY backlog means (2026-09-26, I2). A run still
    // in flight has not reached stage 4 -- nothing it carries has been merged yet, or
    // its re-index is deferred to the run's end -- so an empty backlog then is "not
    // started", and "complete" at 0 of 4 imported claimed a stage nobody had begun.
    function _uxImReindexBits(rx, t, tf, st) {
      if (!rx) return `<span class="muted">${esc(t("could not be read"))}</span>`;
      const bk = rx.backlog || null;
      if (bk && bk.available === false) {
        return `<span class="muted">${esc(t("the backlog could not be read"))}</span>`;
      }
      const left = bk ? bk.articles_pending : null;
      if (rx.state === "running") {
        const done = rx.done || 0, total = rx.total || 0;
        // Through fmtNum (Y3), the app's one ruled number writer: raw, "1200 of 4800"
        // sat beside "3,600 articles left" one line over, and grouped no thousands at all.
        return total
          ? esc(tf("resuming re-index — {done} of {total} articles", { done: fmtNum(done, 0), total: fmtNum(total, 0) }))
          : esc(t("resuming re-index"));
      }
      if (left != null && left > 0) {
        return esc(tf("{n} articles left to re-index", { n: fmtNum(Number(left), 0) }));
      }
      if (left === 0) return (st && st.state === "running") ? esc(t("not started")) : esc(t("complete"));
      return `<span class="muted">${esc(t("not measured"))}</span>`;
    }

    // Stage 4's DOT, branch for branch the states _uxImReindexBits words, so the colour
    // can never say something the line beside it does not (I-7): running is the accent,
    // work owed with nothing draining it is a warning, a measured empty backlog after the
    // run is done, and everything unread, unmeasured or not yet started stays grey.
    function _uxImReindexDot(rx, st) {
      if (!rx) return "var(--muted)";
      const bk = rx.backlog || null;
      if (bk && bk.available === false) return "var(--muted)";
      if (rx.state === "running") return "var(--accent)";
      const left = bk ? bk.articles_pending : null;
      if (left != null && left > 0) return "var(--warn)";
      if (left === 0) return (st && st.state === "running") ? "var(--muted)" : "var(--ok)";
      return "var(--muted)";
    }

    // Q203 = a: the three statements, each keyed on ITEM STATE (unambiguous) rather
    // than on a live phase (which straddles). A pure function of the two payloads, so
    // what it SAYS is testable, not merely that the identifiers appear in the source.
    function _uxImStatements(st, rx, t, tf) {
      // EVERY ITEM IN THE RUN, not only the restore kinds. The first version filtered to
      // corpus/legacy, so the moment a (fast) corpus restore finished it announced "the
      // import files can be removed" and "safe to close" while a `blobs` item from the
      // SAME click -- wiki dumps, maps, models, gigabytes -- was still copying out of
      // that same folder. `_uxImScan` pre-checks every box, so a mixed run is the normal
      // case, not a corner. An operator acting on that sentence deletes the source of a
      // transfer still reading it. The statement is unscoped in plain words ("the import
      // files", "everything they carried"), so its test has to be unscoped too.
      //
      // And SUCCEEDED, not merely finished: a failed blobs item means the folder still
      // holds something that never arrived, so "everything they carried is in your
      // corpus" would be false in the other direction.
      const done = (i) => i.state === "done" || i.state === "skipped";
      const items = st.items || [];
      const restores = items.filter((i) => i.kind === "corpus" || i.kind === "legacy");
      // BOTH halves, and each is load-bearing on its own. The restores decide whether
      // there is a corpus claim to make at all (a blobs-only run carries nothing INTO
      // the corpus, so it may never say "everything they carried is in your corpus");
      // the whole run decides whether the folder is finished with (see above).
      const saved = restores.length > 0 && restores.every(done) && items.every(done);
      const out = [];
      // A RUN THAT HAS ENDED WITHOUT SAVING EVERYTHING (2026-09-28 walk). "Keep the import
      // files until this import is saved" and "Closing the app now abandons whatever has
      // not been saved yet" are about a run in flight; after a wrong passphrase they sat
      // under two failed backups for good, promising a save that will never come -- and
      // "Analytics are complete -- every imported article is indexed" was vacuously true
      // of an import that brought in nothing. Once the run is over, say what it left.
      if (_UX_IM_RUN_ENDED[st.state] && restores.length > 0 && !saved) {
        if (!restores.some(done)) {
          out.push({ ok: false, text: t("Nothing from this import reached your corpus — it is exactly as it was before.") });
          out.push({ ok: false, text: t("Keep the import files: once the cause is fixed, import them again.") });
          return out;
        }
        out.push({ ok: false, text: t("Keep the import files of the backups that did not finish — they have to be imported again.") });
        out.push({ ok: true, text: t("Safe to close or update the app — the re-index picks up where it left off on the next start.") });
        out.push(..._uxImAnalyticsStatement(st, rx, t, tf));
        return out;
      }
      out.push(saved
        ? { ok: true, text: t("The import files can be removed — everything they carried is in your corpus now.") }
        : { ok: false, text: t("Keep the import files until this import is saved — nothing is durable until then.") });
      out.push(saved
        ? { ok: true, text: t("Safe to close or update the app — the re-index picks up where it left off on the next start.") }
        : { ok: false, text: t("Closing the app now abandons whatever has not been saved yet; your corpus is untouched.") });
      out.push(..._uxImAnalyticsStatement(st, rx, t, tf));
      return out;
    }

    // The third statement, about stage 4, on its own: an ended run that saved part of its
    // backups carries it too, beside its own first two.
    function _uxImAnalyticsStatement(st, rx, t, tf) {
      const bk = rx && rx.backlog;
      if (!rx || !bk || bk.available === false) {
        return [{ ok: false, text: t("Whether analytics have caught up could not be read.") }];
      }
      if ((bk.articles_pending || 0) > 0) {
        return [{ ok: false, text: tf(
          "Analytics are still catching up: {n} imported article(s) carry no keywords until the re-index finishes.",
          { n: fmtNum(Number(bk.articles_pending), 0) }) }];
      }
      if (st.state === "running" || rx.state === "running") {
        // AFTER STAGE 4, and not before (Q203 = a; 2026-09-26, I2). An empty backlog at
        // the START of a run is a fact about the corpus BEFORE this import -- nothing it
        // carries has been merged, let alone re-indexed -- and the check mark read
        // "Analytics are complete" at 0 of 4 imported. While the run (stages 1-3) or the
        // drain (stage 4) is still going, the statement says what it is waiting for.
        return [{ ok: false, text: t("Analytics are complete once the re-index (stage 4) finishes.") }];
      }
      return [{ ok: true, text: t("Analytics are complete — every imported article is indexed.") }];
    }

    // `only` ("reindex") keeps the analytics statement alone -- the one of the three that
    // is about stage 4 -- for the fresh page a reopen shows (_uxImFreshView).
    function _uxImRenderStatements(st, rx, t, tf, only) {
      const host = document.getElementById("ux-imp-statements");
      if (!host) return;
      const all = _uxImStatements(st, rx, t, tf);
      const lines = only === "reindex" ? all.slice(2) : all;
      const html = lines.map((l) =>
        `<div><span aria-hidden="true">${l.ok ? "✓" : "•"}</span> ${esc(l.text)}</div>`
      ).join("");
      if (host.dataset.sig === html) return;
      host.dataset.sig = html;
      host.innerHTML = html;
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
      // Keyed frames with grouped numbers (R14): "2/1 200 articles" welded a raw
      // fraction to an English noun.
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      if (p.phase_index && p.phase_total) bits.push(esc(tf("phase {n} of {total}", { n: fmtNum(p.phase_index, 0), total: fmtNum(p.phase_total, 0) })));
      if (p.merge_steps) {
        bits.push(esc(p.merge_steps === 1 ? tf("{done} of {total} step", { done: fmtNum(p.merge_step || 0, 0), total: fmtNum(1, 0) })
          : tf("{done} of {total} steps", { done: fmtNum(p.merge_step || 0, 0), total: fmtNum(p.merge_steps, 0) })));
      }
      if (p.reindex_total) {
        bits.push(esc(p.reindex_total === 1 ? tf("{done} of {total} article", { done: fmtNum(p.reindex_done || 0, 0), total: fmtNum(1, 0) })
          : tf("{done} of {total} articles", { done: fmtNum(p.reindex_done || 0, 0), total: fmtNum(p.reindex_total, 0) })));
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

    // A queue row's elapsed time: the shared keyed duration frames, isolated and
    // unbreakable like the per-item duration (R14). "3m 5s" was English shorthand in
    // every locale, and "0s" had its unit read first beside Arabic text.
    function _uxImDur(s) {
      s = Math.max(0, Math.round(Number(s) || 0));
      const TF = _uxDurTf();
      if (s < 60) return _uxDurIso(TF("{n} s", { n: s }));
      const m = Math.floor(s / 60);
      if (m < 60) return _uxDurIso(TF("{m} min {s} s", { m, s: s % 60 }));
      return _uxDurIso(TF("{h} h {m} min", { h: Math.floor(m / 60), m: m % 60 }));
    }

    // REMOVED 2026-09-16 (Q207 = a, R2): `_uxImDetails` and the "Show details"
    // <details> block it filled. It duplicated the queue rows -- label, kind, state,
    // elapsed -- and added exactly one fact they did not carry: the item's PATH. That
    // fact did not go with it: it rides the persisted import report, which is the
    // artifact that survives the tab. Q207 was left BLANK on the answer sheet and took
    // the sheet's default (a), so this is an ASSUMPTION and is reversible: the block
    // was ~20 lines over a payload the server still publishes in full.

    // ── IMPORT HISTORY (Q222 = b: Settings -> Data & backup) ───────────────
    // Every persisted report, newest first. This is where the detail the fresh
    // dialog no longer re-renders actually lives (R1) -- and it outlives the tab,
    // the process and the machine, which the recovered last-completed summary it
    // replaces never did.
    async function loadImportHistory() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      const host = document.getElementById("imp-history");
      if (!host) return;
      let reports = null;
      try {
        const r = await api("/api/backup/import-reports");
        reports = (r && r.reports) || [];
      } catch (e) {
        // A failed READ is not an empty history. Saying "no imports yet" here would
        // be a positive claim about the operator's data made from a broken request.
        host.innerHTML = `<span style="color:var(--err)">${esc(t("The import history could not be read."))}</span>`;
        return;
      }
      host.innerHTML = _uxImHistoryHtml(reports, t, tf);
    }

    // Pure, so what the list SAYS is assertable rather than the identifiers appearing
    // in the source. Three honesty rules: an unreadable report's article figure is
    // ABSENT (never 0); a run that did not complete is labelled and its figure reads
    // PLANNED; and an empty list is an honest empty state, never a blank div.
    function _uxImHistoryHtml(reports, t, tf) {
      if (!reports || !reports.length) {
        return `<span class="muted">${esc(t("No imports recorded yet."))}</span>`;
      }
      return reports.map((r) => {
        const bits = [];
        bits.push(`<b>${esc(fmtDateTime(r.created_at))}</b>`);
        if (r.kind) bits.push(`<span class="muted">${esc(r.kind)}</span>`);
        // The backup it came from (I7), isolated for RTL like every folder name (I12).
        if (r.label) bits.push(`<bdi style="overflow-wrap:anywhere">${esc(r.label)}</bdi>`);
        if (r.articles != null) {
          const n = fmtNum(Number(r.articles), 0);
          bits.push(r.articles_basis === "planned"
            ? esc(tf("{n} articles planned", { n }))
            : esc(tf("{n} articles", { n })));
        } else {
          bits.push(`<span class="muted">${esc(t("article count not recorded"))}</span>`);
        }
        if (r.outcome && r.outcome !== "ok") {
          bits.push(`<span style="color:var(--err)">${esc(t("did not complete"))} (${esc(r.outcome)})</span>`);
        }
        const href = `/api/backup/import-reports/${encodeURIComponent(r.filename)}?format=md`;
        bits.push(`<a href="${href}" target="_blank" rel="noopener">${esc(t("open report"))}</a>`);
        return `<div>${bits.join(" \u00b7 ")}</div>`;
      }).join("");
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
      _uxImWatchQueue();
    }

    // Reattach to a run already in flight when the dialog opens -- the whole point of
    // moving the sequencing server-side (ruling 16).
    //
    // ONLY a RUNNING run is re-rendered (2026-09-26, I3; R1, Q201 = a). This used to
    // render ANY persisted run with items, so every reopen after an import -- and every
    // one after a restart -- redrew the previous run's header, stage rows, statements and
    // per-backup rows under the quiet "Last import" line that was meant to replace them.
    // A finished run gets the fresh page (_uxImFreshView): the line, plus only what is
    // still unfinished. Stage 4 is READ BEFORE anything renders (I1): the reopen used to
    // draw it from a cleared read and then never read it again.
    async function _uxImReattach() {
      let st = null;
      try { st = await api("/api/backup/import-queue/status"); } catch { return; }
      if (!st || !(st.items || []).length) return;
      await _uxImReadRx();
      const view = _uxImFreshView(st, _uxImRx);
      if (view.full) { _uxImRenderQueue(st); _uxImWatchQueue(); return; }
      // A chain still pointed at a finished run (or at the stage-4 watch of an earlier
      // opening) is superseded; a Verify in flight keeps its own.
      if (_uxImWatch && _uxImWatch !== "verify") _uxImStopChain();
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf
        : ((s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
      _uxImRenderFresh(st, _uxImRx, t, tf);
      if (view.stage4 && !_uxImWatch) _uxImWatchReindex();
    }

    // The one quiet line an INTERRUPTED run keeps on a fresh page, and the same line in
    // the live header. Coloured text, not the toast box (I9).
    function _uxImInterruptedHtml(t) {
      return `<div style="color:var(--err)">${esc(t("This import was interrupted when the app stopped. It cannot resume (the passphrase is never stored) — start it again."))}</div>`;
    }

    // Empty every surface of the run view, signatures included, so nothing a previous
    // opening drew can survive into this one (R1).
    function _uxImResetRunView() {
      for (const id of ["ux-imp-queue-note", "ux-imp-stages", "ux-imp-statements", "ux-imp-queue-rows"]) {
        const el = document.getElementById(id);
        if (el) { el.innerHTML = ""; delete el.dataset.sig; }
      }
      const box = document.getElementById("ux-imp-queue");
      if (box) box.style.display = "none";
      for (const id of ["ux-imp-stop", "ux-imp-bg"]) {
        const b = document.getElementById(id);
        if (b) b.style.display = "none";
      }
      _uxImLastStatus = null;
      _uxImView = null;
    }

    // The FRESH PAGE's run surfaces (see _uxImFreshView): nothing at all for a finished
    // run whose re-index is done, else the interrupted line and/or stage 4 alone.
    function _uxImRenderFresh(st, rx, t, tf) {
      const box = document.getElementById("ux-imp-queue");
      const note = document.getElementById("ux-imp-queue-note");
      const rows = document.getElementById("ux-imp-queue-rows");
      const stages = document.getElementById("ux-imp-stages");
      const stmts = document.getElementById("ux-imp-statements");
      if (!box) return;
      const view = _uxImFreshView(st, rx);
      _uxImLastStatus = st;
      _uxImView = "fresh";
      if (rows) _uxPruneRows(rows, []);
      if (!view.interrupted && !view.stage4) { box.style.display = "none"; return; }
      box.style.display = "";
      if (note) {
        _uxPruneRows(note, ["body"]);
        const body = view.interrupted ? _uxImInterruptedHtml(t) : "";
        _uxPatchRow(note, "body", body, body);
      }
      if (view.stage4) {
        _uxImRenderStages(st, rx, t, tf, "reindex");
        _uxImRenderStatements(st, rx, t, tf, "reindex");
      } else {
        if (stages) stages.innerHTML = "";
        if (stmts) { stmts.innerHTML = ""; delete stmts.dataset.sig; }
      }
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
      // The label frame (R2): the separator is the locale's, the step name is data.
      if (name.indexOf("merge_step:") === 0) return ooLabelText(t("merge step"), name.slice(11));
      if (name.indexOf("stage_a:") === 0) return ooLabelText(t("stage A"), name.slice(8).replace(/_/g, " "));
      return name.replace(/_/g, " ");
    }
    // A duration as a reader of THIS language writes it (2026-09-27 fix batch B18, R9),
    // the way _sizeText writes a size: the UNIT rides inside one keyed frame per shape
    // ("{n} s" is "{n} ثانية" in Arabic, "{n} 秒" in Chinese), so the locale decides the
    // word and its side; the whole figure rides in a FIRST STRONG ISOLATE (U+2068 ...
    // U+2069), so an Arabic line no longer draws "8.5 s" as "s 8.5"; and its spaces are
    // NO-BREAK, so a narrow cell cannot split the number from its unit. The numbers are
    // unchanged: the same rounding as before, Latin digits and a decimal point.
    function _uxDurIso(txt) {
      return "⁨" + String(txt).replace(/ /g, " ") + "⁩";
    }
    function _uxDurTf() {
      const TF = (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((x, v) => String(x).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m));
      return TF;
    }
    function _uxFmtS(s) {
      const TF = _uxDurTf();
      const n = Number(s) || 0;
      return _uxDurIso(n < 1 ? TF("{n} ms", { n: Math.round(n * 1000) }) : TF("{n} s", { n: n.toFixed(1) }));
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
      const TF = _uxDurTf();
      if (n < 60) return _uxDurIso(TF("{n} s", { n: n.toFixed(n < 10 ? 1 : 0) }));
      if (n < 3600) return _uxDurIso(TF("{m} min {s} s", { m: Math.floor(n / 60), s: Math.round(n % 60) }));
      return _uxDurIso(TF("{h} h {m} min", { h: Math.floor(n / 3600), m: Math.round((n % 3600) / 60) }));
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
      // CHECKPOINT INTERVAL K. Both are `ok: false`, which is what keeps them OUT of
      // the aggregate: by the time a conclusion renders, an item still `staged` is
      // one whose group never reached a checkpoint, so it contributed nothing to the
      // corpus and its numbers must not sit behind a success headline.
      staged:      { ok: false, icon: "◐", label: "Merged, not saved", col: "var(--warn, #e0a800)" },
      discarded:   { ok: false, icon: "↺", label: "Discarded",  col: "var(--err, #d9534f)" },
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
    // The already-merged answer, in the server's own terms (R11): as WHICH batch and
    // WHEN, the date through the app's date formatter -- or, for an artifact already in
    // this run's unsaved working copy, that instead. Both values are isolated so an RTL
    // page cannot reorder them into the words around them.
    function _uxMergedLine(m, t, tf) {
      const iso = (x) => "⁨" + String(x) + "⁩";
      if (m.open_group) return t("Already merged earlier in this run, not yet saved — nothing new to import.");
      const when = m.at ? fmtDateTime(m.at) : "";
      if (m.batch != null && when) {
        return tf("Already merged as batch {batch} on {date} — nothing new to import.",
          { batch: iso(m.batch), date: iso(when) });
      }
      return t("Already merged — nothing new to import.");
    }
    function _uxPerItemView(rows, t, tf) {
      if (rows.length < 2) return "";   // one item: the headline already IS its story
      const num = (n) => fmtNum(Number(n || 0), 0);
      const max = rows.reduce((m, r) => Math.max(m, r.total), 0);
      const body = rows.map((r) => {
        const oc = _uxOutcome(r.state);
        const pct = max > 0 ? (r.total / max) * 100 : 0;
        const seg = (v, col) => v > 0 ? `<span style="flex:${v};background:${col}"></span>` : "";
        // "nothing imported" is right for every state that MERGED nothing --
        // cancelled, stopped, skipped, failed. It is wrong for the two checkpoint
        // states, which merged something and then lost it before it was saved, so
        // those say what actually happened to them instead.
        const _lostIts = (r.state === "staged" || r.state === "discarded");
        const bar = r.total > 0
          ? `<div style="width:${pct.toFixed(1)}%;min-width:2px;display:flex;height:10px;border-radius:5px;overflow:hidden">`
            + seg(r.new, "var(--accent, #4a90d9)") + seg(r.dup, "var(--muted-bg, #888)")
            + seg(r.conf, "var(--err, #d9534f)") + `</div>`
          : `<div class="muted" style="font-size:11px">${esc(
              r.error ? ooServerText(r.error).slice(0, 120)
                      : (!_lostIts && r.merged) ? _uxMergedLine(r.merged, t, tf)
                      : t(_lostIts ? _UX_IM_STATE_LABEL[r.state] : "nothing imported")
            )}</div>`;
        // Each count is ONE keyed frame chosen by number (R9): "1 200 imported" welded a
        // count to an English-ordered adjective, which read as "1 200 مستورد" -- a
        // singular adjective after a plural count -- and could agree with nothing.
        const cnt = [];
        if (r.total > 0) {
          if (r.kind === "blobs") {
            cnt.push(r.new === 1 ? tf("{n} file restored", { n: num(r.new) }) : tf("{n} files restored", { n: num(r.new) }));
            cnt.push(r.dup === 1 ? tf("{n} file skipped", { n: num(r.dup) }) : tf("{n} files skipped", { n: num(r.dup) }));
          } else if (r.kind === "newsletters") {
            cnt.push(r.new === 1 ? tf("{n} newsletter stored", { n: num(r.new) }) : tf("{n} newsletters stored", { n: num(r.new) }));
            cnt.push(r.dup === 1 ? tf("{n} newsletter already present", { n: num(r.dup) }) : tf("{n} newsletters already present", { n: num(r.dup) }));
          } else {
            cnt.push(r.new === 1 ? tf("{n} article imported", { n: num(r.new) }) : tf("{n} articles imported", { n: num(r.new) }));
            cnt.push(r.dup === 1 ? tf("{n} duplicate", { n: num(r.dup) }) : tf("{n} duplicates", { n: num(r.dup) }));
          }
          if (r.conf) {
            cnt.push(r.conf === 1 ? tf("{n} conflict (your version kept)", { n: num(r.conf) })
              : tf("{n} conflicts (your version kept)", { n: num(r.conf) }));
          }
        }
        const counts = cnt.join(" · ");
        // The backup's folder name may WRAP and is ISOLATED (2026-09-26, I13/I12): kept on
        // one line it held this table 130-170 px wider than a 375 px dialog, clipping the
        // names at its edge; un-isolated, an RTL page reordered its digits around it.
        return `<tr>`
          + `<td style="padding:3px 8px 3px 0;overflow-wrap:anywhere"><span style="color:${oc.col}">${esc(oc.icon)}</span> <bdi>${esc(r.title)}</bdi></td>`
          + `<td style="padding:3px 8px;width:40%">${bar}</td>`
          + `<td style="padding:3px 8px;font-size:12px" class="muted">${esc(counts)}</td>`
          + `<td style="padding:3px 0;text-align:right;font-size:12px;white-space:nowrap" class="muted">${esc(_uxFmtDur(r.elapsed_s))}</td>`
          + `</tr>`;
      }).join("");
      return `<div style="margin-top:10px">`
        + `<div class="muted" style="font-size:12px;margin-bottom:2px">`
        + `${esc(t("What each backup brought"))} <span style="opacity:.7">${esc(tf("(bars are relative to the largest of the {n} items)", { n: rows.length }))}</span></div>`
        // `ux-peritem` STACKS the four cells at phone width (W7, app.css): as a table the
        // name cell's `overflow-wrap:anywhere` let auto layout shrink it to ~3 characters
        // a line at 375 px while the bar kept its 40%.
        + `<table class="ux-peritem" style="width:100%;border-collapse:collapse">${body}</table></div>`;
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
      const num = (n) => fmtNum(Number(n || 0), 0);
      // Each date is ONE unbreakable, left-to-right token (Y1, measured at 375 px): the
      // "before" cell broke INSIDE a date ("2023-01-" / "07 –"), and on an Arabic page the
      // bidi pass then moved each fragment's hyphen to the other end ("-2023-01"). The
      // range still wraps, at the dash, and the page direction orders its two ends.
      const fmtDate = (iso) => `<span dir="ltr" style="unicode-bidi:isolate;white-space:nowrap">${esc(iso ? String(iso).slice(0, 10) : "—")}</span>`;
      const dims = [
        [t("Articles"), before.articles, after.articles],
        [t("Sources"), before.sources, after.sources],
        [t("Languages"), before.languages, after.languages],
        [t("Countries"), before.countries, after.countries],
        [t("Keywords"), before.keywords, after.keywords],
      ];
      const rows = dims.map(([label, b, a]) => {
        const d = (a || 0) - (b || 0);
        // ISOLATED (W9): a leading "+" or "-" is a weak bidi character, so on an Arabic
        // page it resolved to the paragraph's direction and was drawn AFTER the number
        // ("2 400+"). The first-strong isolate keeps the sign on the number's left.
        const dTxt = _ltrIsolate(d === 0 ? "±0" : (d > 0 ? "+" + num(d) : num(d)));
        const dCol = d > 0 ? "var(--ok, #4caf50)" : (d < 0 ? "var(--err, #d9534f)" : "");
        return `<tr><td style="padding:2px 8px 2px 0">${esc(label)}</td>`
          + `<td style="text-align:right;padding:2px 8px" class="muted">${esc(num(b))}</td>`
          + `<td style="text-align:right;padding:2px 8px">${esc(num(a))}</td>`
          + `<td style="text-align:right;padding:2px 0"><b style="color:${dCol}">${esc(dTxt)}</b></td></tr>`;
      }).join("");
      const dateRow = `<tr><td style="padding:2px 8px 2px 0">${esc(t("Date range"))}</td>`
        + `<td style="text-align:right;padding:2px 8px" class="muted">${fmtDate(before.date_min)} – ${fmtDate(before.date_max)}</td>`
        + `<td style="text-align:right;padding:2px 8px" colspan="2">${fmtDate(after.date_min)} – ${fmtDate(after.date_max)}</td></tr>`;
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
      let newSources = 0, discoveryAdded = 0, eventsAdded = 0, unindexed = 0, deferredNew = false;
      // Source QUALIFICATION carried by this import (field ask 2026-08-10). Counts
      // only; `qualEngines` maps criteria version -> n, which is the "by which
      // engine" half — never inferred, only what the incoming stamp recorded.
      let qualGained = 0, disqGained = 0;
      const qualEngines = {};
      // "Already judged here, kept" and "Backup disagreed" are SNAPSHOTS, one per item,
      // each read against the corpus as that item found it -- which the items before it
      // in the same run had already grown. A source carried by four backups was counted
      // four times, and a source the first backup introduced read as "already judged
      // here" by the second: a cumulative run summed 6,400 + 6,422 + 6,418 + 14 into
      // "kept: 19,254" over a 6,446-source corpus (2026-09-27 re-walk, I-1). So they are
      // collected per item and never added up; introduced/adopted and the engines above
      // ARE disjoint across items (a source lands once), and are summed as before.
      const qualSnaps = [];
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
            kind: sm.kind, merged: sm.merged,
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
            kind: sm.kind, merged: sm.merged,
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
            qualSnaps.push(pq);
            for (const [eng, n] of Object.entries(pq.engines || {})) {
              qualEngines[eng] = (qualEngines[eng] || 0) + (n || 0);
            }
          }
          discoveryAdded += (p.source_candidates && p.source_candidates.new) || 0;
          detail.push({ title: sm.title, pq: pq || null, body:
            (sm.merged ? `<div class="hint">${esc(_uxMergedLine(sm.merged, t, tf))}</div>` : "")
            + _v2PlanTable(p) + _uxTimingsView(sm.timings, t, tf) });

          if (sm.events_added) eventsAdded += sm.events_added;
          // Real re-index failures only — reindex_imported_articles ran (or was
          // skipped entirely; either way the true count of never-reindexed imported
          // articles is knowable, never guessed).
          //
          // A DEFERRED re-index is not a failure (2026-09-26 leftovers, Y4). This used to
          // add every NEW article of an item whose re-index did not run in-line, so the
          // line said "4,800 Articles awaiting indexing" whatever the corpus's real backlog
          // was -- an article already carrying current-engine rows is not owed, and an
          // earlier import's backlog is owed too. Those items are counted below from the
          // backlog the SERVER measured, never from the plan.
          if (sm.reindexed) unindexed += sm.reindexed.failed || 0;
          else if (art.new) deferredNew = true;
          if (sm.delta && sm.delta.before && sm.delta.after) {
            if (!deltaBefore) deltaBefore = sm.delta.before;
            deltaAfter = sm.delta.after;
          }
        } else {
          const tl = sm.tally || {};
          tallyNew += (tl.stored || 0) + (tl.restored || 0);
          tallyDup += (tl.duplicate || 0) + (tl.skipped || 0);
          if (tl.empty) {
            extra.push(tl.empty === 1 ? tf("{n} newsletter empty", { n: fmtNum(tl.empty, 0) })
              : tf("{n} newsletters empty", { n: fmtNum(tl.empty, 0) }));
          }
          if (tl.errors) {
            extra.push(tl.errors === 1 ? tf("{n} error", { n: fmtNum(tl.errors, 0) })
              : tf("{n} errors", { n: fmtNum(tl.errors, 0) }));
          }
          detail.push({ title: sm.title, body: `<div class="hint">${(sm.lines || []).map(esc).join(" · ")}</div>` });
        }
      }
      if (eventsAdded) perType.push({ keys: [], label: t("Events"), n: eventsAdded });

      const num = (n) => fmtNum(Number(n || 0), 0);
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

      // label: value through the shared frame (R14), the house style the qualification
      // block below already states the reason for: an interpolated count cannot agree,
      // and "8 Sources" welded a count to a capitalised English noun.
      const typeLabels = perType.filter((r) => r.n > 0).map((r) => ooLabelText(r.label, num(r.n)));
      const catchAll = allNew ? [ooLabelText(t("database records, all types"), num(allNew))] : [];
      const typeBlock = (typeLabels.length || catchAll.length)
        ? `<div class="muted" style="font-size:12px;margin-top:4px">${typeLabels.concat(catchAll).map(esc).join(" · ")}</div>`
        : "";

      // Positive-but-honest framing (ruling: "imports should give positive
      // feedback" — the delta IS the good news, no fabricated praise).
      // The frame names only what grew (2026-09-28 walk): "from 0 new sources spanning 0
      // new languages" read as a finding about the import rather than an absence, and an
      // import that added no article at all has no growth to announce -- its headline
      // already says "0 imported" beside what was deduplicated.
      const grow = (deltaBefore && deltaAfter) ? {
        articles: Math.max(0, deltaAfter.articles - deltaBefore.articles),
        sources: Math.max(0, deltaAfter.sources - deltaBefore.sources),
        languages: Math.max(0, deltaAfter.languages - deltaBefore.languages),
      } : null;
      const growFrame = !grow || !grow.articles ? null
        : grow.languages ? "Your corpus grew by {articles} articles from {sources} new sources spanning {languages} new languages."
        : grow.sources ? "Your corpus grew by {articles} articles from {sources} new sources."
        : "Your corpus grew by {articles} articles.";
      const growLine = growFrame
        ? `<div style="margin-top:6px">${esc(tf(growFrame, {
            articles: num(grow.articles), sources: num(grow.sources), languages: num(grow.languages),
          }))}</div>`
        : "";
      const deltaView = _uxCorpusDeltaView(deltaBefore, deltaAfter, t);

      // THE BACKLOG, ONE READING, read once for the two lines that state it (the
      // "still indexing" caveat and "Articles awaiting indexing" below), so they cannot
      // print two different numbers. The items' hand-off snapshots come first, by I6's
      // rule (the LATEST, never a sum -- see the caveat). A run whose items carry none
      // (every backup held for a checkpoint) falls back to the re-index job's own read,
      // which the queue's terminal tick takes just before rendering (`run.rx`).
      const _rxd = summaries.map((s2) => (s2 && s2.report && s2.report.reindex_deferred) || s2.reindex_deferred)
        .filter(Boolean);
      const _live = (run && run.rx) ? (run.rx.backlog || { available: false }) : null;
      const _bk = _rxd.length
        ? _rxd[_rxd.length - 1]
        : ((deferredNew && _live)
            ? { articles_pending: _live.available === false ? null : _live.articles_pending }
            : null);
      const _bkUnreadable = !!_bk && typeof _bk.articles_pending !== "number";

      // WORK INDUCED: stated honestly, only when there is actually something queued.
      const queueLines = [];
      if (newSources > 0) queueLines.push(ooLabelText(t("New sources"), num(newSources)));
      // Awaiting indexing (Y4): an in-line re-index's real FAILURES, or -- when the
      // re-index was deferred -- the backlog the server measured, which already holds any
      // failure too. Unreadable: no number, and the caveat above says why.
      const awaiting = deferredNew ? ((_bk && !_bkUnreadable) ? _bk.articles_pending : null) : unindexed;
      if (awaiting != null && awaiting > 0) queueLines.push(ooLabelText(t("Articles awaiting indexing"), num(awaiting)));
      if (discoveryAdded > 0) queueLines.push(ooLabelText(t("Discovery candidates"), num(discoveryAdded)));
      // SOURCE QUALIFICATION carried by this import (field ask 2026-08-10: "display the
      // amount of qualified sources imported"). Rendered only when the import actually
      // carried a verdict — a run that carried none says nothing rather than "0", which
      // would read as a finding about the backup instead of an absence of data.
      // Every line is label:value rather than a sentence with the count inside it —
      // an interpolated count cannot conjugate, and this app has no CLDR plural rules,
      // so a "{n} sources were ..." frame is wrong in most of the twelve locales.
      let qualBlock = "";
      // Local-wins, stated rather than left to be inferred from numbers that do not add
      // up: a verdict this machine reached itself is never overwritten. ONE item's
      // snapshot is the run's; with several, each stays in its own backup's detail below
      // and the aggregate says why it shows none (I-1).
      const keptLines = (pq) => {
        const out = [];
        if (pq && pq.local_verdict_kept) out.push(tf("Already judged here, kept: {n}", { n: num(pq.local_verdict_kept) }));
        if (pq && pq.local_verdict_disagreed) out.push(tf("Backup disagreed, your verdict kept: {n}", { n: num(pq.local_verdict_disagreed) }));
        return out;
      };
      const qualPerBackup = !!(qualGained || disqGained) && qualSnaps.length > 1;
      if (qualGained || disqGained) {
        const lead = [];
        if (qualGained) lead.push(tf("Qualified sources added: {n}", { n: num(qualGained) }));
        if (disqGained) lead.push(tf("Arrived disqualified: {n}", { n: num(disqGained) }));
        const sub = [];
        if (!qualPerBackup) sub.push(...keptLines(qualSnaps[0]));
        else if (qualSnaps.some((pq) => keptLines(pq).length)) {
          sub.push(t("Sources already judged here are counted per backup, below: the backups of one run overlap, so those counts are not added up."));
        }
        const engNames = Object.keys(qualEngines);
        if (engNames.length) {
          // "unrecorded" is the merge's SENTINEL for a verdict that carried no criteria
          // version (merge.py _qualification_tally), not an engine's name: worded, where
          // a real version (v1, ...) stays data (2026-09-27 re-walk, I-2).
          sub.push(tf("Judged by: {engines}", {
            engines: engNames.map((e) => `${e === "unrecorded" ? t("engine not recorded") : e} (${num(qualEngines[e])})`).join(", "),
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
      // THE 375 px OVERFLOW (the 2026-09-26 leftovers, Y1). Measured in Chromium: the
      // result block held the dialog 26-28 px wider than its content box, and hiding
      // the rows one at a time put it HERE, not in "How your corpus grew" (whose date
      // range fits): each summary is the backup's folder name, one unbreakable token
      // ("202609261808_OpenOmniscience_Backup_2") 59 px wider than the summary, and an
      // opened body -- the plan table, whose conflict samples are unbroken JSON -- took
      // the dialog to 428 px. So the name may wrap and is isolated, as the per-backup
      // table's already is (I13/I12), and the body scrolls inside its own box.
      // Each backup's own qualification snapshot, when several were not added up (I-1).
      const detailQual = (d) => {
        const lines = qualPerBackup ? keptLines(d.pq) : [];
        return lines.length ? `<div class="hint">${esc(lines.join(" · "))}</div>` : "";
      };
      const detailBlocks = detail.map((d) =>
        `<details style="margin-top:6px"><summary class="muted" style="overflow-wrap:anywhere"><bdi>${esc(d.title)}</bdi></summary>`
        + `<div style="overflow-x:auto">${detailQual(d)}${d.body}</div></details>`).join("");

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

      // COMMITTED vs STAGED, at the end of the run (the checkpoint-interval ask).
      // A conclusion that still shows staged or discarded items is a run that ended
      // before its last group reached a checkpoint, so the honest sentence is about
      // work that was DONE and then thrown away — the durability half of K, named
      // where it was paid. Rendered only when there is something to name; at K = 1
      // there never is.
      const stagedRows = perItem.filter((r) => r.state === "staged");
      const discardedRows = perItem.filter((r) => r.state === "discarded");
      const lostLines = [];
      if (discardedRows.length) {
        lostLines.push(tf(
          "Discarded, not in your corpus: {n} — the shared working copy was never saved. Import them again.",
          { n: discardedRows.length }
        ));
      }
      if (stagedRows.length) {
        lostLines.push(tf(
          "Merged but never saved: {n}. Import them again.",
          { n: stagedRows.length }
        ));
      }
      const checkpointNote = lostLines.length
        ? `<div class="card-caveat" style="margin-top:6px">${lostLines.map(esc).join("<br>")}</div>`
        : "";

      // STILL INDEXING (2026-08-03). The import no longer blocks on the re-index, so
      // "import finished" no longer means "fully indexed" -- those articles carry no
      // keywords yet and are absent from analytics. Deferring it SILENTLY would trade a
      // visible three-hour wait for an invisible incomplete corpus, which is strictly
      // worse, so the deferral is stated here with its real count. An unreadable backlog
      // says so rather than showing 0: "could not read" and "nothing pending" must never
      // look alike.
      let indexingLine = "";
      // A MEASURED zero is nothing still to index (Y4): a re-import whose every article was
      // already here read "Indexing continues in the background: 0 article(s) still to
      // index", a caveat about work that does not exist. An unreadable reading still says so.
      if (_bk && (_bkUnreadable || _bk.articles_pending > 0)) {
        // THE LATEST READING, never a sum (2026-09-26, I6). Each item's
        // `articles_pending` is the WHOLE corpus backlog at the moment that item
        // committed (volume_job.hand_off_reindex reads reindex_backlog()), so the
        // second snapshot already contains the first: a four-backup, 4,800-article
        // import summed 3,600 + 4,800 into "8,400 still to index". Inside one run the
        // drain waits for the run's window to close, so the last readable snapshot is
        // the backlog the run ended with. An unreadable LAST snapshot says so: an earlier
        // readable one is a stale undercount, and printing it as current would be the same
        // wrong number in the other direction.
        const unreadable = _bkUnreadable;
        const pend = unreadable ? 0 : _bk.articles_pending;
        const body = unreadable
          ? t("Indexing continues in the background. The number still to index could not be read.")
          : tf("Indexing continues in the background: {n} article(s) still to index. Until it finishes they carry no keywords and are absent from analytics.",
               { n: fmtNum(pend, 0) });
        indexingLine =
          `<div class="card-caveat" style="margin-top:6px">${esc(body)}</div>`;
      }

      // What a large-data restore REFUSED (bytes that did not match the checksum the
      // backup recorded) and what it could not check. Same treatment as the indexing
      // caveat above and for the same reason: the summary is the artifact an operator
      // reads afterwards, and a restore that discarded three rotted files is not a
      // clean one. Built from the summaries' own `caveat` arrays, so a producer that
      // has nothing to say adds nothing.
      const _refusals = summaries.flatMap((s2) => (s2 && s2.caveat) || []);
      const refusalLine = _refusals.length
        ? `<div class="card-caveat" style="margin-top:6px">${_refusals.map(esc).join("<br>")}</div>` : "";

      host.innerHTML =
        `<div class="card" style="margin-top:8px;padding:12px;border-left:3px solid ${head.col}">`
        + `<div style="font-weight:700;font-size:15px">${esc(head.icon)} ${esc(head.text)}</div>`
        + countLine + excludedNote + checkpointNote
        + growLine + headline + bar + typeBlock + extraLine + qualBlock + metaBlock + indexingLine + refusalLine + queueBlock
        + _uxPerItemView(perItem, t, tf)
        + deltaView
        + `<div class="muted" style="font-size:12px;margin-top:6px">${esc(t("Additive restore: nothing in your corpus was replaced or deleted. Duplicates were skipped."))}</div>`
        + `<div style="margin-top:8px"><div class="muted" style="font-size:12px;margin-bottom:2px">${esc(t("Details by source"))}</div>${detailBlocks}</div>`
        + `</div>`;
    }

    // The old large-data folder panel is gone (W2, then R1): folderBackupPlan,
    // folderBackupStart, folderRestoreStart, folderBackupAction and their poller
    // (_fbStartPoll / _fbRefresh) drew into `#fb-*` elements that are in no page, and no
    // button, palette entry or handler reached any of them. The unified export and import
    // dialogs drive the same /api/backup/folder engine; _fbRefusalLines below is still
    // theirs.

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
            if (prog) prog.textContent = t("Failed:") + " " + (s.error ? ooServerText(s.error) : t("unknown error"));
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
    // What a folder RESTORE turned away, and what it could not check. The restore
    // hashes every file as it streams and discards a member whose bytes do not match
    // the checksum the backup recorded when it wrote them -- before it reaches the
    // live data directory. That refusal is only honest end to end if the operator is
    // TOLD: a run that silently dropped three rotted dumps and reported "Done." reads
    // as a complete restore, and the missing files surface later as a mystery.
    // Returns [] when there is nothing to say, so a clean restore renders unchanged.
    // Label:value, never an interpolated sentence -- a count cannot conjugate, and
    // Russian has three plural forms to Arabic's six.
    function _fbRefusalLines(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s2) => s2);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s2, vars) => {
        let out = s2;
        if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null) ? m : String(vars[k]));
        return out;
      });
      const lines = [];
      const refused = p.corrupt_refused || 0;
      if (refused) {
        // The NAMES are the actionable half -- they are what the operator re-downloads
        // -- so they ride the line as data, bounded, with the remainder stated rather
        // than silently cut. The backend caps the named list at 200; this shows a few.
        const named = (p.corrupt || []).slice(0, 6)
          .map((c) => `${c.category}/${c.rel}`);
        const hidden = refused - named.length;
        const tail = named.length
          ? " — " + named.join(" · ") + (hidden > 0 ? " " + tf("+ {n} more (not shown)", { n: hidden }) : "")
          : "";
        // The locale's own separator (ooLabelText, R2): a colon welded here was the
        // English one in every language, and the count goes through fmtNum like every
        // other figure the app prints.
        lines.push(ooLabelText(t("Refused — bytes did not match the checksum this backup recorded, so they were NOT restored"),
          fmtNum(refused, 0) + tail));
      }
      const unverified = p.restored_unverified || 0;
      if (unverified) {
        lines.push(ooLabelText(t("Restored, but not content-verified — this backup recorded no checksum for them"),
          fmtNum(unverified, 0)));
      }
      return lines;
    }

    function _v2PlanTable(plan) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const rows = Object.entries(plan || {})
        .map(([tbl, c]) => ({tbl, new: c.new || 0, dup: c.duplicate || 0, conf: c.conflict || 0, conflicts: c.conflicts || []}))
        .sort((a, b) => (b.new + b.conf) - (a.new + a.conf));
      const active = rows.filter(r => r.new || r.dup || r.conf);
      const quiet = rows.length - active.length;
      let html = `<table style="width:100%;font-size:13px;border-collapse:collapse"><thead><tr>` +
        `<th style="text-align:start">${esc(t("Data"))}</th><th>${esc(t("New"))}</th>` +
        `<th>${esc(t("Already present"))}</th><th>${esc(t("Conflicts (your version kept)"))}</th></tr></thead><tbody>`;
      for (const r of active) {
        html += `<tr><td style="padding:2px 6px">${esc(r.tbl)}</td>` +
          `<td style="text-align:center">${r.new ? `<b>${r.new}</b>` : "0"}</td>` +
          `<td style="text-align:center" class="muted">${r.dup}</td>` +
          `<td style="text-align:center">${r.conf ? `<b>${r.conf}</b>` : "0"}</td></tr>`;
        if (r.conflicts.length) {
          const det = r.conflicts.slice(0, 5).map(c => esc(JSON.stringify(c))).join("<br>");
          // A sample is one JSON token with no break opportunity; it may break anywhere
          // rather than widen the table past a phone's dialog (Y1).
          html += `<tr><td colspan="4" class="muted" style="font-size:12px;padding:0 6px 6px;overflow-wrap:anywhere"><details><summary>` +
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
    //: The state the discovery result line last reported (null: nothing saved yet), so a
    //: language switch can redraw it. The line is `data-i18n-dyn`: it is written through
    //: t() in the active language, and the walker would otherwise cache that translated
    //: text as "the English" and freeze it (the re-walk's H-2).
    let _discoveryResultOn = null;
    function _paintDiscoveryResult() {
      const box = $("discovery-external-result");
      if (!box || _discoveryResultOn === null) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // The disclosure of an egress is a consent string: it ships x12 like the box beside it.
      box.textContent = _discoveryResultOn
        ? t("Enabled: topic-discovery queries will be sent to DuckDuckGo.")
        : t("Disabled (the default): no topic query leaves this machine.");
    }
    async function saveDiscoveryExternal() {
      // ETH-02/RM-03: the one external-service call is an explicit, knowing opt-in.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const on = $("discovery-external").checked;
      try {
        await api("/api/safety/settings",
          {method: "PUT", body: JSON.stringify({discovery_external_enabled: on})});
        _discoveryResultOn = on;
        _paintDiscoveryResult();
        toast(on ? t("External topic discovery enabled.") : t("External topic discovery disabled."));
      } catch (e) {
        $("discovery-external").checked = !on;  // revert the visual state on failure
        toast(_failMsg("Save failed: {error}", e), "err");
      }
    }
    // -- At-rest encryption (PR-E): doctor attestation + one-way encrypt ----- //
    //: The last /api/system/doctor reading the at-rest lines were drawn from, so a language
    //: switch redraws them from it without a request (the re-walk's U-2). #atrest-state is
    //: `data-i18n-dyn`: its lines are composed at render time in the active language, and
    //: the walker would cache "المجموعة: " as the English and never let it go.
    let _atRestDoc = null;
    async function loadAtRestState() {
      const box = $("atrest-state"); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!_atRestDoc) box.textContent = t("Checking…");
      try {
        _atRestDoc = await api("/api/system/doctor");
        _renderAtRest();
      } catch (e) { box.textContent = e.message; }
    }
    function _renderAtRest() {
      const box = $("atrest-state"), d = _atRestDoc;
      if (!box || !d) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const word = (s) => s.state === "encrypted" ? t("Encrypted (SQLCipher 4)")
                        : s.state === "plaintext" ? t("NOT encrypted") : t("not created yet");
      // Each line on the locale's label frame (R2), not an English colon.
      box.innerHTML =
        `<div>${ooLabelHtml(esc(t("Corpus")), `<b>${esc(word(d.corpus))}</b>`)}` +
        (d.corpus.cipher ? ` <span class="muted">${esc(d.corpus.cipher)}</span>` : "") + `</div>` +
        `<div>${ooLabelHtml(esc(t("Custody log")), `<b>${esc(word(d.custody_log))}</b>`)}</div>`;
      $("atrest-encrypt").style.display = d.corpus.state === "plaintext" ? "" : "none";
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
        // The file count is ONE keyed frame, its numbers grouped (R14).
        const tfw = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf
          : ((str, vars) => str.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m));
        $("panic-result").innerHTML =
          `<span class="pill warn">${esc(t("crypto-erased"))}</span> ${esc(tfw("{done} of {total} files erased.", { done: fmtNum(r.files_wiped || 0, 0), total: fmtNum(r.files_seen || 0, 0) }))} ` +
          `${esc(t("The corpus key is destroyed — the encrypted store is now permanently unrecoverable."))} ` +
          `<span class="muted">${esc(r.limit)}</span>` +
          `<div class="hint" style="margin-top:8px">${esc(rec)}` +
          `<div class="row" style="gap:6px;margin-top:6px">` +
          `<button class="danger" data-on-click="secureErase(1)">${esc(t("Single pass"))}</button>` +
          `<button class="danger" data-on-click="secureErase(3)">${esc(t("Triple pass"))}</button>` +
          `<button class="danger" data-on-click="secureErase(8)">${esc(t("Octuple pass"))}</button>` +
          `</div><div class="muted" style="margin-top:4px">${esc(t("This may take several minutes on a large disk. Restart the app when you are done."))}</div></div>`;
        toast(t("Local data crypto-erased. Restart the app."), "warn");
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
        // The size through the one localised writer (Y9): "MiB" was English in every
        // locale and the only binary-prefixed unit the app printed anywhere.
        if (box) box.innerHTML +=
          `<div class="hint" style="margin-top:6px"><span class="pill warn">overwritten</span> ` +
          `${r.passes}× — ${esc(_fmtBytes(r.bytes_written || 0))}. <span class="muted">${esc(r.limit)}</span></div>`;
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
        if (!(s.counts && s.counts.articles === 0 && !guideDone())) return;
        // One first-run dialog at a time, in one order: the Wikipedia wizard the fresh-corpus
        // hand-off asked for first, this guide when it closes (U8, see wikiWizardPending).
        if (typeof wikiWizardPending === "function" && wikiWizardPending()) {
          $("wiki-wizard").addEventListener("close", () => { if (!guideDone()) openGuide(); }, { once: true });
        } else openGuide();
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
    // Every frame goes through fmtNum, the intermediate ones too (W17): the browser's
    // locale drew "6,402" under a French UI for the 600 ms of the tween.
    function animateCount(el, to) {
      to = Math.round(to || 0);
      const from = parseInt(el.dataset.v || "0", 10) || 0;
      if (from === to) { el.dataset.v = to; el.textContent = fmtNum(to, 0); return; }
      const start = performance.now(), dur = 600;
      function step(t) {
        const k = Math.min(1, (t - start) / dur);
        const eased = 0.5 - 0.5 * Math.cos(k * Math.PI);
        el.textContent = fmtNum(Math.round(from + (to - from) * eased), 0);
        if (k < 1) requestAnimationFrame(step); else el.dataset.v = to;
      }
      requestAnimationFrame(step);
    }

    // -- Live language switch: the import dialog's INTERPOLATED surfaces ----- //
    // The recorded frozen-locale bug class (Lead card titles 2026-07, the Composition
    // figures 2026-08, and the same again here): the i18n DOM walker re-translates a
    // text node whose content is still an exact KEY, but an already-interpolated
    // OOI18N.tf() string -- "once every 3 backups", "24 articles" -- is no longer a key
    // and stays in whatever locale first rendered it. Every surface this slice adds is
    // built that way, and the chain that would repaint them STOPS at a terminal state,
    // so after a finished import nothing re-renders them at all.
    //
    // MEASURED, not assumed: the 2026-09-16 Chromium sweep screenshotted the dialog in
    // fr, ar and zh and found the checkpoint sentence still reading "Verified and
    // written to your corpus once every 3 backups" in all three -- a caveat about
    // durability, which the informed-consent non-negotiable says is the one thing that
    // may never reach an operator in a language they did not choose.
    //
    // Re-renders from the SAME facts (the last status, the cached re-index read), never
    // re-fetches: a language switch is not a reason to touch the network or the queue.
    document.addEventListener("oo:langchange", () => {
      const dlg = document.getElementById("ux-import");
      if (dlg && dlg.open) {
        try { _uxImCheckpointNote(); } catch (_e) {}
        try { _uxImLastLine(); } catch (_e) {}
        try {
          if (_uxImLastStatus) {
            const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
            const tf = (window.OOI18N && OOI18N.tf)
              ? OOI18N.tf
              : ((x, v) => x.replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m));
            // The SAME picture it was showing: a fresh page stays fresh (R1).
            if (_uxImView === "fresh") {
              _uxImRenderFresh(_uxImLastStatus, _uxImRx, t, tf);
            } else {
              // The WHOLE run view (2026-09-26 leftovers, Y6), not only its stage rows and
              // statements: the header ("4/4 imported") and the per-backup rows ("— Done ·
              // 4s") are drawn by the same renderer, and once the run was over nothing drew
              // them again, so they stayed in the language the run ended in.
              _uxImRenderQueue(_uxImLastStatus);
            }
          }
        } catch (_e) {}
        // ...and the result block under it, from the arguments it was drawn with. Only
        // while it is still on screen: a scan or a new run empties it on purpose.
        try {
          const sh = document.getElementById("ux-imp-summary");
          if (_uxImSummaryArgs && sh && sh.innerHTML.trim()) {
            _renderImportSummary(sh, _uxImSummaryArgs.summaries, _uxImSummaryArgs.run);
          }
        } catch (_e) {}
      }
      // The history list is the same shape, one surface over. Only if it has rendered.
      try {
        const h = document.getElementById("imp-history");
        if (h && h.innerHTML.trim() && typeof loadImportHistory === "function") loadImportHistory();
      } catch (_e) {}
    });

