/* app-diagnostics.js — diagnostics, sweeps, benches

   Auto-indexing and re-index/cleanup jobs, session forensics, the all-diagnostics
   bundle and P0 validation, the progressive AI sweeps, and the gold-set / model
   bench and AI check surfaces.

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
    async function autoIndexInsights() {
      if (_indexing) return;
      // The status poll (every 6 s) calls this whenever there's a backlog; without
      // a cooldown it re-kicks a fresh drain on every tick — the field-test storm
      // (P0-5: /api/insights/reindex called 1,326×/369 s, each batch a heavy write
      // contending with the live scrape). Run ONE bounded pass, then cool down.
      if (Date.now() < _autoIndexCooldownUntil) return;
      _indexing = true;
      try {
        let guard = 0, startRemaining = -1, lastRemaining = 0;
        for (;;) {
          const r = await api("/api/insights/reindex?limit=300", {method: "POST"});
          if (startRemaining < 0) startRemaining = r.remaining;
          lastRemaining = r.remaining;
          const rem = $("ins-remaining");
          if (rem) rem.innerHTML = r.remaining ? `· <strong>${r.remaining.toLocaleString()}</strong> to index` : "";
          // Bound each pass to 40 batches (~12k articles): plenty to drain a normal
          // corpus in one go, but never the old 500-batch (150k) blast.
          if (r.remaining === 0 || r.indexed === 0 || ++guard >= 40) break;
        }
        if (lastRemaining > 0 && lastRemaining >= startRemaining && lastRemaining === _autoIndexLastRemaining) {
          // No progress across two passes ⇒ the backlog is stuck (un-indexable
          // articles). Stop re-attempting this session rather than hammer forever.
          _autoIndexCooldownUntil = Infinity;
        } else {
          // Cool down so the 6 s poll can't re-kick; the next pass continues the drain.
          _autoIndexCooldownUntil = lastRemaining > 0 ? Date.now() + 60000 : Infinity;
        }
        _autoIndexLastRemaining = lastRemaining;
      } catch (_e) { _autoIndexCooldownUntil = Date.now() + 60000; }  /* best-effort */
      finally { _indexing = false; }
    }

    // Maintenance: FORCE-re-index the WHOLE corpus (not just un-indexed articles) —
    // recomputes keywords/metadata with the current engine. Drains stale rows an old
    // engine produced (e.g. pre-markup-strip CSS keywords). Heavy; loops batches with
    // a visible cursor so a big corpus never hangs the request. Confirm first.
    let _reindexAllRunning = false;
    // Core loops (no confirm) so the individual buttons AND the one-click
    // "Clean up keywords" can reuse them. Each writes to the shared status span.
    async function _reindexAllLoop(st, t) {
      let after = 0, total = 0, guard = 0;
      for (;;) {
        const r = await api(`/api/insights/reindex-all?limit=300&after_id=${after}`, { method: "POST" });
        total += r.reindexed || 0;
        after = r.last_id || after;
        if (st) st.textContent = `${total} ${t("re-indexed")}${r.remaining ? ` · ${r.remaining.toLocaleString()} ${t("to go")}` : ""}`;
        if (r.done || ++guard > 5000) break;
      }
      return total;
    }
    async function _pruneCore(st, t) {
      if (st) st.textContent = t("Pruning…");
      const r = await api("/api/insights/prune-keywords", { method: "POST" });
      return r;
    }
    // Phase 1.1: the whole-corpus re-index now runs as a BACKGROUND JOB — it survives a
    // tab close and RESUMES from a persisted cursor (the old client loop above restarted
    // from article 0 and stopped when the tab closed). We start it, then poll its status
    // into the shared span; the work keeps going even if we stop polling, and it is
    // pausable/resumable from the task manager. _reindexAllLoop/_pruneCore stay as the
    // fallback cores (and prune is still a quick client call).
    async function _startReindexJob(pruneAfter, scope, restart) {
      // scope "keywords" (Phase 1.2) re-does the keyword pass only (~2/3 less work);
      // "full" also recomputes when/where/who + sentiment. `restart` discards a paused
      // run's progress and begins again -- the backend continues it by default, so this
      // is only ever sent when the operator chose to start over.
      const sc = scope === "keywords" ? "keywords" : "full";
      const q = `scope=${sc}&prune_after=${pruneAfter ? "true" : "false"}${restart ? "&restart=true" : ""}`;
      try {
        await api(`/api/insights/reindex-job?${q}`, { method: "POST" });
      } catch (_e) { /* 409 = one already running; fall through and poll it */ }
    }
    async function _pollReindexJob(st, t) {
      for (;;) {
        let s;
        try { s = await api("/api/insights/reindex-job/status"); }
        catch { break; }
        if (st) {
          const tal = s.tally || {};
          const bits = [`${(tal.reindexed || 0).toLocaleString()} ${t("re-indexed")}`];
          if (s.articles_total) bits.push(`${s.percent || 0}%`);
          // Speed, so a long run can be estimated rather than guessed at. Both rates
          // are measurements over THIS run and are absent until real -- never a 0/h.
          if (s.keywords_per_hour) bits.push(`${Math.round(s.keywords_per_hour).toLocaleString()} ${t("keywords/h")}`);
          if (s.articles_per_hour) bits.push(`${Math.round(s.articles_per_hour).toLocaleString()} ${t("articles/h")}`);
          if (tal.pruned != null) bits.push(`${(tal.pruned || 0).toLocaleString()} ${t("unused keywords removed")}`);
          if (s.state === "done") bits.push(t("done"));
          else if (s.state === "paused") bits.push(t("paused"));
          else if (s.state === "error") bits.push(esc(s.error || t("error")));
          st.textContent = bits.join(" · ");
        }
        if (s.state !== "running" || !s.running) break;
        await new Promise((r) => setTimeout(r, 1500));
      }
    }


    // One-click "Clean up keywords": re-index the whole corpus (drains markup junk)
    // THEN prune the now-orphaned keywords — the recommended order in one action, so
    // the operator doesn't have to run two buttons and remember the sequence.
    async function cleanupKeywords(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // A PAUSED RUN IS CONTINUED, AND THE CONFIRM SAYS SO. The button used to start
      // from article 0 whatever was on disk -- a day of work discarded silently (field
      // report 2026-08-12). The backend now continues by default; this only makes the
      // click honest about which of the two is about to happen.
      let paused = null;
      try {
        const st0 = await api("/api/insights/reindex-job/status");
        if (st0 && (st0.state === "paused" || st0.state === "error") && (st0.articles_done || 0) > 0) paused = st0;
      } catch (_e) { /* status is a courtesy here; never block the action on it */ }
      const ask = paused
        ? t("Resume the keyword cleanup? It continues from where it stopped — {done} of {total} articles ({percent}%) are already re-indexed.")
            .replace("{done}", (paused.articles_done || 0).toLocaleString())
            .replace("{total}", (paused.articles_total || 0).toLocaleString())
            .replace("{percent}", String(paused.percent || 0))
        : t("Clean up keywords now? This re-indexes every article with the current engine, then removes the keywords left with no mentions. Heavy on a large corpus; keywords still in use and anything you curated are kept.");
      if (!confirm(ask)) return;
      if (btn) btn.disabled = true;
      const st = $("reindex-all-status");
      try {
        // ONE background job: re-index every article (KEYWORD-ONLY scope — this is a
        // keyword cleanup, ~2/3 less work than a full pass), then prune orphaned
        // keywords on completion — survives a tab close, resumes from its cursor.
        await _startReindexJob(true, "keywords");
        await _pollReindexJob(st, t);
      } catch (e) { if (st) st.textContent = esc(e.message); }
      finally { if (btn) btn.disabled = false; }
    }

    // Keyword-growth (vocabulary) curve — cumulative distinct keywords vs cumulative
    // words added (maintainer ask 2026-06-24, at ~909k keywords). The SHAPE is the
    // diagnostic: a line that bows BELOW the dashed origin->end reference = the
    // vocabulary is saturating (healthy); hugging the reference = near-linear junk
    // growth (Heaps beta ~ 1). Data is fetched decrypt-free from the diagnostic
    // endpoint; rendered in the shared #chart-enlarge modal. Browser-unverified (fork-3).
    function _growthSvg(series, t) {
      if (!Array.isArray(series) || series.length < 2) {
        return `<div class="muted">${esc(t("Not enough data yet for a curve."))}</div>`;
      }
      const W = 820, H = 380, padL = 70, padR = 18, padT = 16, padB = 44;
      const xmax = Math.max(1, ...series.map((p) => p.tokens || 0));
      const ymax = Math.max(1, ...series.map((p) => p.keywords || 0));
      const X = (v) => padL + (v / xmax) * (W - padL - padR);
      const Y = (v) => H - padB - (v / ymax) * (H - padT - padB);
      const pts = series.map((p) => `${X(p.tokens || 0).toFixed(1)},${Y(p.keywords || 0).toFixed(1)}`).join(" ");
      const fmt = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : (n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n)));
      const grid = [0, ymax / 2, ymax].map((v) =>
        `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${W - padR}" y2="${Y(v).toFixed(1)}" stroke="var(--border)" stroke-width="1"/>`
        + `<text x="${padL - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc(fmt(Math.round(v)))}</text>`).join("")
        + [0, xmax / 2, xmax].map((v) =>
          `<text x="${X(v).toFixed(1)}" y="${H - padB + 16}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(fmt(Math.round(v)))}</text>`).join("");
      return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("Cumulative keywords versus cumulative words"))}" style="width:100%;height:auto;background:var(--panel2);border:1px solid var(--border);border-radius:8px">`
        + grid
        + `<polyline points="${X(0).toFixed(1)},${Y(0).toFixed(1)} ${X(xmax).toFixed(1)},${Y(ymax).toFixed(1)}" fill="none" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="5 4"/>`
        + `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>`
        + `<text x="${(W / 2).toFixed(0)}" y="${H - 6}" text-anchor="middle" font-size="12" fill="var(--text)">${esc(t("Cumulative words added →"))}</text>`
        + `<text x="14" y="${(H / 2).toFixed(0)}" text-anchor="middle" font-size="12" fill="var(--text)" transform="rotate(-90 14 ${(H / 2).toFixed(0)})">${esc(t("Cumulative keywords →"))}</text>`
        + `</svg>`
        + `<div class="hint muted" style="margin-top:4px">${esc(t("Dashed line = perfectly linear growth. The more the curve bows below it, the more the vocabulary is saturating (fewer junk keywords)."))}</div>`;
    }
    // Diagnostics: force the local corpus source-topic enrichment now (it also runs
    // automatically in the background). Zero-network; additive to Source.tags.
    async function enrichSources(btn) {
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Enriching…";
      try {
        const d = await api("/api/diagnostics/enrich-sources", { method: "POST" });
        btn.textContent = `Enriched ${d.sources_updated || 0} sources (+${d.tags_added || 0} tags)`;
      } catch (e) {
        btn.textContent = "Enrich failed — see console";
        console.error("enrichSources", e);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 4000);
    }

    // Diagnostics: the NETWORKED source_type pass (Wikidata). Gated by the one
    // network consent (invariant #14); the backend also refuses under airplane mode.
    async function enrichSourceTypes(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ensureOnline === "function"
          && !await ensureOnline(t("Fill source types from Wikidata (egresses to Wikidata over your transport)"))) return;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = t("Enriching in the background…");
      try {
        // Runs ~8 min in a background job (returns {mode, started, job}); poll the job
        // to completion for the REAL tally instead of the empty start-state ("Typed 0
        // of 0 scanned" the instant it began).
        await api("/api/diagnostics/enrich-source-types", { method: "POST" });
        const st = await pollJobStatus("/api/diagnostics/enrich-source-types/status");
        if (st.state === "error") {
          btn.textContent = t("Enrich failed — see console");
          console.error("enrichSourceTypes", st.error);
        } else if (_jobStillRunning(st)) {
          // Stopped watching, not finished — never show the start-state's "0/0".
          btn.textContent = t("Still running in the background — see the task manager.");
        } else {
          const res = st.result || {};
          btn.textContent = t("Typed source types:") + " " + (res.sources_typed || 0) + "/" + (res.scanned || 0);
        }
      } catch (e) {
        btn.textContent = t("Enrich failed — see console");
        console.error("enrichSourceTypes", e);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 6000);
    }

    // Session forensics (E2, #596): surface the app's own root-cause records so a crash /
    // slow unlock / mystery disk-bloat answers itself. Read-only GET; the backend method
    // strings (the OOM INFERENCE wording, the inventory method) are shown VERBATIM — they
    // are caveats, kept visible, never re-worded. No delete affordance this round.
    function _fmtTs(s) {
      return s ? String(s).replace("T", " ").replace(/(\+00:00|Z)$/, " UTC") : "—";
    }
    function _renderSessionForensics(d, t) {
      const parts = [];
      // 1) Previous-session verdict (the honest OOM inference).
      const prev = d.previous_session || {};
      const v = prev.previous_session;
      let badge;
      if (v === "clean") badge = '<span class="pill ok">' + esc(t("Ended cleanly")) + "</span>";
      else if (v === "unclean-end") badge = '<span class="pill warn">' + esc(t("Ended unexpectedly")) + "</span>";
      else badge = '<span class="pill">' + esc(String(v || "—")) + "</span>";
      let ph = "<div><b>" + esc(t("Previous session")) + "</b> " + badge + "</div>";
      if (prev.started_at || prev.ended_at)
        ph += '<div class="muted">' + esc(t("Started")) + " " + esc(_fmtTs(prev.started_at)) +
              " · " + esc(t("Ended")) + " " + esc(_fmtTs(prev.ended_at)) + "</div>";
      const smp = prev.last_collector_sample;
      if (smp)
        ph += '<div class="muted">' + esc(t("Last recorded memory")) + ": " +
              (smp.rss_mb != null ? esc(smp.rss_mb) + " MB RSS" : "—") +
              (smp.mem_avail_mb != null ? " · " + esc(smp.mem_avail_mb) + " MB " + esc(t("available")) : "") + "</div>";
      if (prev.method) ph += '<div class="card-caveat">' + esc(prev.method) + "</div>";  // verbatim inference
      if (prev.note) ph += '<div class="muted">' + esc(prev.note) + "</div>";
      parts.push('<div style="margin-top:6px">' + ph + "</div>");

      // 2) Last unlock timing (why unlock was slow — one-time migrations / index / WAL recovery).
      const u = d.last_unlock || prev.last_unlock;
      if (u) {
        let uh = "<div><b>" + esc(t("Last unlock")) + "</b> ";
        if (u.synchronous_total_ms != null) uh += esc((u.synchronous_total_ms / 1000).toFixed(1)) + " s";
        uh += "</div>";
        if (u.wal_bytes_before_open != null)
          uh += '<div class="muted">' + esc(t("WAL before first open")) + ": " + esc(humanBytes(u.wal_bytes_before_open)) + "</div>";
        if (Array.isArray(u.phases) && u.phases.length)
          uh += '<div class="muted">' + esc(t("phases")) + ": " +
                u.phases.map((p) => esc(p.phase) + " (" + esc(Math.round(p.ms)) + " ms)").join(" · ") + "</div>";
        if (u.method) uh += '<div class="card-caveat">' + esc(u.method) + "</div>";  // verbatim method
        parts.push('<div style="margin-top:8px">' + uh + "</div>");
      }

      // 3) Data-dir inventory (what fills the disk; orphaned PLAINTEXT staging flagged loudly).
      const inv = d.inventory || {};
      const tot = inv.totals || {};
      let ih = "<div><b>" + esc(t("Data folder")) + '</b> <span class="muted">' + esc(inv.data_dir || "") + "</span></div>";
      ih += '<div class="muted">' + esc(t("Total on disk")) + ": " + esc(humanBytes(tot.total_bytes || 0)) +
            " (" + esc(t("database")) + " " + esc(humanBytes(tot.db_bytes || 0)) +
            " · WAL " + esc(humanBytes(tot.wal_bytes || 0)) +
            " · " + esc(t("other")) + " " + esc(humanBytes(tot.other_bytes || 0)) + ")</div>";
      const stg = inv.suspect_staging || [];
      if (stg.length) {
        let sh = '<div class="note warn" style="margin-top:6px"><b>' + esc(t("Orphaned staging detected")) + "</b> " +
                 esc(humanBytes(tot.orphaned_staging_bytes || 0)) + '<ul style="margin:4px 0 0 16px">';
        stg.forEach((s) => {
          sh += "<li>" + esc(s.name) + " — " + esc(humanBytes(s.bytes || 0));
          if (s.plaintext_snapshot) sh += " <b>" + esc(t("Decrypted copy on disk — remove it deliberately.")) + "</b>";
          sh += "</li>";
        });
        ih += sh + "</ul></div>";
      }
      const ent = (inv.entries || []).slice(0, 12);
      if (ent.length)
        ih += '<div class="muted" style="margin-top:4px">' +
              ent.map((e) => esc(e.name) + ' <span class="pill">' + esc(e.kind) + "</span> " + esc(humanBytes(e.bytes || 0)) +
                (e.files ? " · " + esc(e.files) + " " + esc(t("files")) : "")).join("<br>") + "</div>";
      if (inv.method) ih += '<div class="card-caveat">' + esc(inv.method) + "</div>";  // verbatim method
      if (inv.note) ih += '<div class="muted">' + esc(inv.note) + "</div>";
      parts.push('<div style="margin-top:8px">' + ih + "</div>");

      return parts.join("");
    }
    async function loadSessionForensics(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("session-forensics-out");
      if (!out) return;
      if (btn) btn.disabled = true;
      out.innerHTML = '<div class="muted">' + esc(t("Loading…")) + "</div>";
      try {
        const d = await api("/api/diagnostics/session-forensics");
        out.innerHTML = _renderSessionForensics(d, t);
      } catch (e) {
        out.innerHTML = '<div class="note err">' + esc(t("Could not load session forensics.")) + " " + esc(e.message) + "</div>";
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    // Diagnostics: DISCOVER new sources from Wikidata for chosen countries and add
    // them DISABLED for review (never scraped until enabled). Networked -> consent-gated.
    async function discoverSources(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const cc = (document.getElementById("discover-cc").value || "").trim();
      if (!cc) { toast(t("Enter country codes first, e.g. ke,ng,br"), "err"); return; }
      if (typeof ensureOnline === "function"
          && !await ensureOnline(t("Discover sources from Wikidata (egresses to Wikidata over your transport)"))) return;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Discovering…";
      try {
        const d = await api("/api/diagnostics/discover-sources?countries=" + encodeURIComponent(cc), { method: "POST" });
        btn.textContent = `Added ${d.added || 0} disabled sources — review in Settings → Sources`;
      } catch (e) {
        btn.textContent = "Discovery failed — see console";
        console.error("discoverSources", e);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 6000);
    }

    // WORLD discovery (maintainer-asked 2026-07-15): the same Wikidata discovery over
    // EVERY country, as a background, cancellable, RESUMABLE job (persisted per-country
    // cursor — a cancel / airplane pause / restart continues where it stopped). Every
    // insert stays a DISABLED source for review. Networked -> the one consent popup;
    // cancel lives in the task manager (kind "discover-world-sources").
    async function discoverWorld(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = document.getElementById("discover-world-status");
      const say = (msg) => { if (out) out.textContent = msg; };
      if (typeof ensureOnline === "function"
          && !await ensureOnline(t("Discover sources worldwide from Wikidata — a long background job over every country (egresses to Wikidata over your transport)"))) return;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = t("Discovering worldwide…");
      try {
        const d = await api("/api/diagnostics/discover-world", { method: "POST" });
        if (d && d.started === false && d.job && d.job.state === "running") {
          say(t("Already running — see the task manager."));
        }
        // Long job: poll with a live status line; give up WATCHING (not the job) after
        // 30 min — it keeps running server-side and stays visible in the task manager.
        const st = await pollJobStatus("/api/diagnostics/discover-world/status", {
          intervalMs: 4000,
          onProgress: (s) => {
            if (!s) return;
            const p = s.progress ? ` ${s.done}/${s.total}` : "";
            say((s.detail || t("Working…")) + p);
          },
        });
        if (st && st.state === "error") {
          say(t("World discovery failed — see console"));
          console.error("discoverWorld", st.error);
        } else if (_jobStillRunning(st)) {
          say(t("Still running in the background — see the task manager."));
        } else if (st && st.result) {
          const r = st.result;
          say(`${r.countries_done}/${r.countries_requested} countries · +${r.added_this_run} new disabled sources (${r.added_total} total)`
            + (r.paused_reason ? ` — ${r.paused_reason}` : ""));
        }
      } catch (e) {
        say(t("World discovery failed — see console"));
        console.error("discoverWorld", e);
      }
      btn.textContent = old;
      btn.disabled = false;
    }

    // The bulletin-language diagnostic. It answers a question about the UI's own
    // language, so the status line summarises the locale the operator is IN before
    // offering the file — a per-locale table nobody can read at a glance is what the
    // download is for.
    async function bulletinLanguageReport(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const out = $("bul-lang-status");
      if (btn) btn.disabled = true;
      if (out) out.textContent = t("Reading the report…");
      try {
        const d = await api("/api/diagnostics/bulletin-language");
        const here = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en";
        const mine = (d.languages || []).find((r) => r.language === here);
        const bits = [];
        if (mine && mine.coverage != null) {
          // The numerator and the denominator, not only the share: a percentage with
          // no n cannot be judged.
          bits.push(tf("{lang}: {done} of {total} sentences translated",
            {lang: here, done: mine.translated, total: mine.strings_seen}));
        } else if (mine) {
          bits.push(t("English — nothing to translate"));
        }
        // A failure COUNT here and the names in the file. The status line is a pointer;
        // the report is the artifact, and it is where a finding can be acted on.
        const ri = d.render_integrity || {};
        const bad = (ri.deterministic === false ? 1 : 0)
          + (ri.unresolved_placeholders || []).length
          + (ri.sections_missing_from_document || []).length
          + (ri.articles_not_printed_total ? 1 : 0)
          + (ri.dangling_references || []).length;
        bits.push(bad
          ? tf("{n} render check(s) failed — the report names each one", {n: bad})
          : t("every render check passed"));
        if (d.measured) bits.push(d.measured);
        if (out) out.textContent = bits.join(" · ");
        window.open("/api/diagnostics/bulletin-language?download=1", "_blank");
      } catch (e) {
        if (out) out.textContent = (e && e.message) ? e.message : t("Could not read the report.");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function viewKeywordGrowth(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn) btn.disabled = true;
      try {
        const d = await api("/api/diagnostics/keyword-growth");
        const dlg = $("chart-enlarge"); if (!dlg) { toast(t("Could not open the chart.")); return; }
        const ttl = $("chart-enlarge-title"); if (ttl) ttl.textContent = t("Keyword-growth curve");
        const note = $("chart-enlarge-note");
        if (note) { note.textContent = d.caveat || ""; note.style.display = d.caveat ? "" : "none"; }
        const body = $("chart-enlarge-body"); if (!body) return;
        const tot = d.totals || {}, heaps = d.heaps || {}, rate = d.minting_rate_per_1000_words || {};
        const head = `${esc(t("Keywords"))}: <b>${(tot.keywords || 0).toLocaleString()}</b> · `
          + `${esc(t("words"))}: <b>${(tot.tokens || 0).toLocaleString()}</b>`
          + (heaps.beta != null ? ` · Heaps β = <b>${esc(String(heaps.beta))}</b>` : "")
          + (rate.start != null && rate.end != null
              ? ` · ${esc(t("new keywords / 1,000 words"))}: <b>${esc(String(rate.start))} → ${esc(String(rate.end))}</b>` : "");
        body.innerHTML = `<div class="hint" style="margin-bottom:6px">${head}</div>` + _growthSvg(d.series, t);
        if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      } catch (e) {
        toast(t("Could not load the keyword-growth curve."));
      } finally { if (btn) btn.disabled = false; }
    }

    // All-diagnostics archive as a BACKGROUND job (D2, field-test Item 10): the old button
    // did a SYNCHRONOUS /api/diagnostics/all build that froze the single-worker server for
    // minutes on a large corpus. This starts the background job, polls its status, shows live
    // progress, and downloads when ready. JOB-STATE-AS-TRUTH: a dropped poll shows an honest
    // "connection hiccup — retrying", NEVER "failed" — only a backend error state says failed.
    //
    // THE CEILING IS A DISPLAY BOUND, NOT A BOUND ON THE BUILD, so outliving it must SAY so.
    // The old loop ran a fixed 1800 iterations and, on exhaustion, simply fell out: no
    // message, the status frozen on its last "Building in the background… N%" line, the
    // button re-enabled. That is indistinguishable from a crash, and it is what a field
    // report described as "takes forever and then seems to stop" — the build had in fact
    // finished, unclaimed, after the watcher had stopped looking. 60 minutes is also
    // structurally too short now: the bundle carries ~55 members and each is allowed
    // OO_ALL_DIAG_{DB,NONDB}_MEMBER_DEADLINE_S (300 s default), so a corpus-scale run is
    // permitted hours and routinely takes them. Any exit without a terminal job state now
    // reports one, and the advice is true at that moment: the job is still registered and
    // RUNNING, so /api/jobs lists it and the task manager shows its live progress.
    const _ALL_DIAG_POLL_CEILING_MS = 6 * 60 * 60 * 1000;
    async function runAllDiagnostics(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("all-diag-status");
      const set = (msg) => { if (el) el.textContent = msg; };
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      if (btn) btn.disabled = true;
      set(t("Starting…"));
      try {
        // Start (idempotent: if one is already running the backend returns started:false and
        // we simply poll the in-flight build).
        try { await api("/api/diagnostics/all-job", { method: "POST" }); }
        catch (e) { /* a transient start failure still lets us poll an existing job */ }
        let miss = 0;
        // `settled` is the honesty latch: it is set by EVERY terminal branch, and whatever
        // ends the loop without it (the ceiling above all) owes the operator a sentence.
        let settled = false;
        const pollStart = Date.now();
        const deadline = pollStart + _ALL_DIAG_POLL_CEILING_MS;
        while (Date.now() < deadline) {
          let s;
          try { s = await api("/api/diagnostics/all-job/status"); miss = 0; }
          catch (e) {
            miss++;
            set(t("Connection hiccup — retrying…"));  // the JOB is still running server-side
            await sleep(Math.min(2000 * miss, 10000));  // backoff, capped
            if (miss > 30) { settled = true; set(t("Still building — check the task manager.")); break; }
            continue;
          }
          const state = s && s.state;
          if (state === "done" && s.ready) {
            const sz = s.download_bytes ? " · " + _fmtBytes(s.download_bytes) : "";
            set(t("Ready — downloading…") + sz);
            window.open("/api/diagnostics/all-job/download", "_blank");
            settled = true;
            break;
          }
          if (state === "error") { settled = true; set(t("Build failed:") + " " + (s.error || t("unknown error"))); break; }
          if (state === "cancelled") { settled = true; set(t("Build cancelled.")); break; }
          if (state === "done") { settled = true; set(t("Done — check the task manager for the file.")); break; }
          // running / idle: show live progress — "member i/N · name · elapsed" (the DIAGNOSE-
          // THE-DIAGNOSTICS run-journal ruling): i/N + name already ride the existing
          // done/total/detail fields, elapsed is computed client-side from started_at so no new
          // backend field is needed for this line.
          // `done` is the count of members COMPLETED so far (0 while the first one is
          // still running), so the human-facing "member i/N" is done+1, capped at N.
          const memberPos = (s.done != null && s.total)
            ? "member " + Math.min(s.done + 1, s.total) + "/" + s.total : "";
          const member = s.detail ? (memberPos ? memberPos + " · " + s.detail : s.detail) : memberPos;
          const elapsedS = s.started_at ? Math.max(0, Math.round(Date.now() / 1000 - s.started_at)) : null;
          const elapsed = elapsedS != null ? " · " + elapsedS + "s" : "";
          const pct = (s.progress && s.progress.percent != null) ? " " + s.progress.percent + "%" : "";
          set(t("Building in the background…") + pct + (member ? " · " + member : "") + elapsed);
          // 2 s keeps a short build feeling immediate; past the first two minutes this is a
          // long haul and a 2 s poll for hours is the polling storm the 2026-06-13 field log
          // already complained about, for a line that changes every few minutes at most.
          await sleep(Date.now() - pollStart > 120000 ? 5000 : 2000);
        }
        // The ceiling, or any other way out that never saw a terminal state. The build is
        // still running server-side; say that rather than leaving the last progress line
        // standing as if it were the outcome.
        if (!settled) set(t("Still building — check the task manager."));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    // P0 data-safety validation (S1.2): the push-button v0.2.0 acceptance run. Starts the
    // background job (POST with dest_dir + backup passphrase), clears the passphrase field the
    // moment it is handed to the backend, then polls status and renders the per-check verdicts +
    // the download links. The heavy work runs server-side on the job thread; a 100 GB backup is
    // slow, so the poll ceiling is generous but bounded (never infinite). No score.
    // ---- Unattended run (2026-08-12 field ask) -------------------------------
    // ONE button pressed before a multi-day absence, and ONE that hands the log back.
    // The log call is a plain file read on the server (it never scans the corpus), so
    // "Copy log" is safe to press mid-run on a slow machine with jobs still going.
    async function unattendedStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("unatt-status");
      const set = (m) => { if (el) el.textContent = m; };
      const note = (($("unatt-note") && $("unatt-note").value) || "").trim();
      if (btn) btn.disabled = true;
      set(t("Arming…"));
      try {
        const r = await api("/api/system/unattended/start", {
          method: "POST", body: JSON.stringify({ note }),
        });
        const q = (r && r.qualification) || {};
        // Say what it DECIDED, not just that it started — a run that declined to
        // qualify must read as a decision, never as one that found nothing to do.
        const qtxt = q.started
          ? t("source qualification running")
          : t("source qualification not started") + " — " + (q.reason || "");
        set(t("Armed.") + " " + t("Collecting") + " · " + qtxt);
      } catch (e) {
        set(t("Could not arm:") + " " + ((e && e.message) || ""));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function unattendedLog(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("unatt-status"); const box = $("unatt-log");
      const set = (m) => { if (el) el.textContent = m; };
      if (btn) btn.disabled = true;
      set(t("Reading…"));
      try {
        const r = await api("/api/system/unattended/log");
        const text = (r && r.text) || "";
        if (box) { box.style.display = "block"; box.value = text; box.focus(); box.select(); }
        // Clipboard is best-effort: it needs a secure context and focus, and neither is
        // guaranteed. The textarea above is the real hand-off — already selected — so a
        // refused clipboard costs nothing and is never reported as success.
        let copied = false;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            copied = true;
          }
        } catch (_e) { copied = false; }
        set(copied ? t("Copied to the clipboard.") : t("Ready below — select and copy."));
      } catch (e) {
        set(t("Could not read the log:") + " " + ((e && e.message) || ""));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function unattendedStop(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("unatt-status");
      if (btn) btn.disabled = true;
      try {
        await api("/api/system/unattended/stop", { method: "POST", body: JSON.stringify({}) });
        if (el) el.textContent = t("Disarmed. Collection is untouched — use airplane mode to stop it.");
      } catch (e) {
        if (el) el.textContent = t("Could not disarm:") + " " + ((e && e.message) || "");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function runP0Validation(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("p0-status"); const out = $("p0-result");
      const set = (m) => { if (el) el.textContent = m; };
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const dest = (($("p0-dest") && $("p0-dest").value) || "").trim();
      const pass = ($("p0-pass") && $("p0-pass").value) || "";
      if (!dest || !pass) { set(t("Enter a destination directory and a backup passphrase first.")); return; }
      if (btn) btn.disabled = true;
      if (out) out.innerHTML = "";
      set(t("Starting…"));
      try {
        try {
          await api("/api/diagnostics/p0-validation", {
            method: "POST", body: JSON.stringify({ dest_dir: dest, passphrase: pass }),
          });
        } catch (e) {
          set(t("Could not start:") + " " + ((e && e.message) || t("check the destination path.")));
          return;
        }
        // Hand-off done: clear the passphrase from the field (never keep a secret in the DOM).
        if ($("p0-pass")) $("p0-pass").value = "";
        let miss = 0;
        // Same honesty latch as the all-diagnostics poller above, for the same reason: a
        // fixed-iteration loop that fell out silently froze the status on its last progress
        // line, which reads as a crash. A P0 run against a multi-GB corpus can outlive any
        // ceiling worth setting, so the ceiling reports rather than just stopping.
        let settled = false;
        const p0Deadline = Date.now() + 6 * 60 * 60 * 1000;
        while (Date.now() < p0Deadline) {
          let s;
          try { s = await api("/api/diagnostics/p0-validation/status"); miss = 0; }
          catch (e) {
            miss++;
            set(t("Connection hiccup — retrying…"));  // the JOB is still running server-side
            await sleep(Math.min(2000 * miss, 10000));
            if (miss > 30) { settled = true; set(t("Still running — check the task manager.")); break; }
            continue;
          }
          const state = s && s.state;
          if (state === "done" && s.ready) { settled = true; set(t("Done.")); renderP0Result(out, (s.result && s.result.report) || {}); break; }
          if (state === "error") { settled = true; set(t("Validation failed:") + " " + (s.error || t("unknown error"))); break; }
          if (state === "cancelled") { settled = true; set(t("Validation cancelled.")); break; }
          if (state === "done") { settled = true; set(t("Done — check the task manager for the report.")); break; }
          const member = s.detail ? " · " + s.detail : "";
          set(t("Running in the background…") + member);
          await sleep(2000);
        }
        if (!settled) set(t("Still running — check the task manager."));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function renderP0Result(out, rep) {
      if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Audit finding 2026-07-17 (M7): this used to shadow the real module-level esc()
      // (top of file) with a fallback to a non-existent global `escapeHtml`, which never
      // exists -- so every esc() call below silently ran as a no-op passthrough into
      // out.innerHTML (an XSS sink). Use the real escaper.
      const order = [
        ["p0_1_backup", "P0.1 backup"], ["p0_1_verify", "P0.1 verify"],
        ["p0_2_restore", "P0.2 restore"], ["p0_4_unlock", "P0.4 unlock"],
        ["p0_3_collector", "P0.3 collector"],
      ];
      const checks = rep.checks || {};
      let rows = "";
      order.forEach(([k, label]) => {
        const c = checks[k]; if (!c) return;
        const v = c.verdict || "?";
        const color = v === "pass" ? "var(--ok)" : (v === "fail" ? "var(--err)" : "var(--caveat)");
        rows += '<div><span style="color:' + color + ';font-weight:600">[' + esc(v.toUpperCase())
          + ']</span> ' + esc(label) + ' — ' + esc(c.reason || "") + '</div>';
      });
      const sum = rep.summary || {};
      out.innerHTML = rows
        + '<div style="margin-top:4px">' + esc(sum.pass || 0) + ' pass · ' + esc(sum.fail || 0)
        + ' fail · ' + esc(sum.not_measurable_here || 0) + ' not-measurable-here</div>'
        + '<div class="hint">' + esc(sum.note || "") + '</div>'
        + '<div style="margin-top:4px"><a href="/api/diagnostics/p0-validation/download?format=json" target="_blank">'
        + t("Download report (.json)") + '</a> · <a href="/api/diagnostics/p0-validation/download?format=txt" target="_blank">'
        + t("readable (.txt)") + '</a></div>';
    }

    async function cancelP0Validation() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try { await api("/api/diagnostics/p0-validation/cancel", { method: "POST" }); } catch (e) { /* idempotent */ }
      const el = $("p0-status"); if (el) el.textContent = t("Cancelling…");
    }


    // Keyword-triage real run (Section 8, ruled 2026-07-20): start the background job, poll
    // status, render the run summary + a download link for the dated JSONL log. Mirrors
    // runP0Validation exactly (the page-size bench it also used to mirror was removed
    // 2026-07-31, Settings review ruling 6).
    // B5 (2026-07-24 Session B, ruled): the numeric limit/batch-size inputs are GONE --
    // one ON/OFF TOGGLE button now drives a PROGRESSIVE sweep across ALL head-scope
    // keywords, resumable across a cancel or an app restart via a persisted cursor
    // (src/ai_layer/triage_job.py:run_progressive_triage_job). The toggle always
    // re-checks the REAL job state before deciding start-vs-stop, so it can never drift
    // out of sync with a sweep left running from a previous page load.
    // --- Shared toggle chassis for the three AI-job progressive sweeps (keyword-triage,
    // source-tags, perception-extract) -- 2026-07-26 field-remarks items 1-3 fix. Mirrors
    // pollLangDetect/_paintLangDetectButton EXACTLY: NEVER holds btn.disabled for the
    // sweep's multi-hour duration (a held-disabled button both fades per app.css's
    // button[disabled]{opacity:.5} AND can't be re-clicked to Start/Stop mid-run) --
    // state is painted via btn.dataset.running instead, disabled is only ever set for
    // the brief instant of the START request itself. A per-job polling guard flag
    // (never a shared one) stops a second poll loop stacking on an existing one, the
    // same way _langDetectPolling does. No model input anywhere -- every run uses the
    // operator's active model (Settings -> AI), resolved server-side by active_model().
    const _aiSweepPolling = {};
    function _paintAiSweepButton(btnId, running) {
      const btn = $(btnId);
      if (!btn) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      btn.textContent = running ? t("Stop sweep") : t("Start sweep");
      btn.dataset.running = running ? "1" : "";
    }
    async function _pollAiSweep(job, btnId, statusEl, resultEl, renderFn) {
      if (_aiSweepPolling[job]) return;
      _aiSweepPolling[job] = true;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const set = (m) => { if (statusEl) statusEl.textContent = m; };
      let fails = 0;
      try {
        for (;;) {
          let s;
          // JOB-STATE-AS-TRUTH: a dropped status poll never reads as failure while it runs.
          try { s = await api(`/api/diagnostics/${job}/status`); fails = 0; }
          catch (e) {
            if (++fails > 30) { set(t("Lost contact with the job — see the task manager.")); break; }
            set(t("Connection hiccup — retrying…"));
            await new Promise((r) => setTimeout(r, Math.min(2000 * fails, 10000)));
            continue;
          }
          const st = s.state;
          if (st === "running") {
            _paintAiSweepButton(btnId, true);
            const detail = s.detail ? " · " + s.detail : "";
            set(t("Sweeping…") + detail);
            await new Promise((r) => setTimeout(r, 2000));
            continue;
          }
          _paintAiSweepButton(btnId, false);
          if (st === "done") {
            const res = s.result || {};
            set(res.complete ? t("Done — sweep complete.") : (res.paused_reason || t("Paused.")));
            renderFn(resultEl, s);
          } else if (st === "error") {
            set(t("Failed:") + " " + esc(s.error || ""));
          } else if (st === "cancelled") {
            set(t("Cancelled — progress is saved."));
          } else {
            set("");
          }
          break;
        }
      } finally { _aiSweepPolling[job] = false; }
    }
    async function _toggleAiSweep(job, btnId, statusEl, resultEl, renderFn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const btn = $(btnId);
      const set = (m) => { if (statusEl) statusEl.textContent = m; };
      if (btn && btn.dataset.running === "1") {
        // Currently running -> this click means STOP (mirrors runLangDetect exactly).
        try { await api(`/api/diagnostics/${job}/cancel`, { method: "POST" }); }
        catch (e) { /* idempotent -- a stale click while it's already stopping is fine */ }
        set(t("Pausing — progress is saved…"));
        _pollAiSweep(job, btnId, statusEl, resultEl, renderFn);
        return;
      }
      if (btn) btn.disabled = true; // brief, START-request-only -- never held across the sweep
      set(t("Starting…"));
      try {
        await api(`/api/diagnostics/${job}/run`, { method: "POST", body: JSON.stringify({}) });
        _paintAiSweepButton(btnId, true);
      } catch (e) {
        set(t("Could not start:") + " " + ((e && e.message) || ""));
      }
      if (btn) btn.disabled = false;
      _pollAiSweep(job, btnId, statusEl, resultEl, renderFn);
    }
    // Re-syncs a toggle button with the REAL job state (called when the AI Settings
    // subtab opens, so a sweep left running/paused from a previous page load shows
    // correctly instead of the static HTML default, and resumes polling if it is
    // still running -- the same "reflect reality on open" contract as
    // loadLangDetectCount).
    // A SAVED run rendered from its own log. The three sweeps' footers all carry their
    // totals at the TOP level (`**totals` spread beside state/batches_completed), and the
    // three renderers read them variously as `res.X` and `res.totals.X` -- so the footer is
    // handed back under both, and every value here comes from it. Nothing is invented:
    // `paused_reason` is deliberately NOT set, because each renderer turns any truthy value
    // there into the word "paused", which would relabel an errored or cancelled run.
    function _savedSweepAsResult(last) {
      const sum = (last && last.summary) || {};
      // THE FILE'S TOTALS WIN OVER THE FOOTER'S. A sweep resumes by appending to the same
      // log, and the footer is written by whichever invocation ended -- so an attempt that
      // did nothing (the backend was down) leaves `batches_completed: 0, verdicts_out: 0`
      // sitting under thousands of batches of real work. A field log had exactly that, and
      // reading the footer rendered "0 batches, 0 verdicts" for 6,208 logged batches: not a
      // missing number but a wrong one, which is worse, because it reads as a run that
      // found nothing. Zero is a legal value, so preferring the footer whenever it is
      // merely non-null is the same trap as defaulting an absent field to 0.
      const logged = (last && last.logged_totals) || {};
      const batches = (last && last.batches_logged) || 0;
      return Object.assign({}, sum, logged, {
        complete: sum.state === "done",
        batches_completed: Math.max(batches, sum.batches_completed || 0),
        totals: Object.assign({}, sum, logged),
      });
    }

    // What the saved state actually was. "in_progress" from a log we are only reading
    // because the job is NOT running means a run that never wrote its summary -- said
    // plainly rather than reused as if it were still going.
    function _savedSweepStateLine(last, t) {
      const st = ((last && last.summary) || {}).state || "in_progress";
      const words = {
        done: t("last saved run: complete"),
        cancelled: t("last saved run: stopped"),
        error: t("last saved run: ended on an error"),
        in_progress: t("last saved run: interrupted before it wrote a summary"),
      };
      // An ERROR footer over a log that DID work is the common resumable case: the last
      // attempt failed, the earlier ones did not. Saying only "ended on an error" beside
      // the file's real totals would read as a contradiction, so the sentence says which
      // of the two it is describing.
      let line = words[st] || words.in_progress;
      if (st !== "done" && ((last && last.batches_logged) || 0) > 0) {
        line = t("the last attempt on this log failed; the work already logged is kept");
      }
      return line + (last && last.filename ? " — " + last.filename : "");
    }

    async function _syncAiSweepToggle(job, btnId, statusEl, resultEl, renderFn) {
      let s;
      try { s = await api(`/api/diagnostics/${job}/status`); } catch (e) { return; }
      _paintAiSweepButton(btnId, s.state === "running");
      if (s.state === "running") { _pollAiSweep(job, btnId, statusEl, resultEl, renderFn); return; }
      // NOT running -- which is exactly when an operator comes looking for the results.
      // The job object lives only as long as the process while the log lives on disk, and
      // rendering only during a run meant the download links did not exist in the DOM at
      // the one moment they are wanted (field report 2026-08-13: "can't find the button").
      // `/last` reads the newest log and answers `available:false` honestly when there is
      // none, so an empty panel still means "no run", never "the run vanished".
      try {
        const last = await api(`/api/diagnostics/${job}/last`);
        if (!last || !last.available || !resultEl) return;
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s2) => s2);
        renderFn(resultEl, { result: _savedSweepAsResult(last) });
        resultEl.insertAdjacentHTML(
          "afterbegin", '<div class="muted">' + esc(_savedSweepStateLine(last, t)) + "</div>");
      } catch (e) { /* a courtesy read; never block the toggle on it */ }
    }

    async function toggleKeywordTriage(btn) {
      await _toggleAiSweep("keyword-triage", "kt-toggle-btn", $("kt-status"), $("kt-result"), renderKeywordTriageResult);
    }

    function renderKeywordTriageResult(out, status) {
      if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const res = (status && status.result) || {};
      const label = res.complete ? t("sweep complete") : (res.paused_reason ? t("paused") : "");
      out.innerHTML = (label ? esc(label) + " — " : "") + esc(res.batches_completed || 0) + " batches, "
        + esc((res.totals && res.totals.verdicts_out) || 0)
        + " verdicts, canaries " + (res.canary_ok_overall === false ? "FAILED" : "ok")
        + '<div style="margin-top:4px"><a href="/api/diagnostics/keyword-triage/download" target="_blank">'
        + t("Download report (.json)").replace(".json", ".jsonl") + "</a>"
        // The raw log is the evidence; the PROPOSAL is what a human can actually judge --
        // junk verdicts grouped per language, with the counts behind each term. Neither
        // applies anything: a stoplist entry only ever changes through a reviewed commit.
        + ' &middot; <a href="/api/diagnostics/keyword-triage/proposal?download=1" target="_blank">'
        + esc(t("Download the stoplist proposal (.json)")) + "</a></div>";
    }

    async function syncKeywordTriageToggle() {
      await _syncAiSweepToggle("keyword-triage", "kt-toggle-btn", $("kt-status"), $("kt-result"), renderKeywordTriageResult);
    }

    // Source-tag assignment progressive sweep (design entry + GO ruling, maintainer
    // 2026-07-20; B5 2026-07-24 Session B): the same toggle chassis as keyword triage above.
    async function toggleSourceTags(btn) {
      await _toggleAiSweep("source-tags", "st-toggle-btn", $("st-status"), $("st-result"), renderSourceTagsResult);
    }

    function renderSourceTagsResult(out, status) {
      if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const res = (status && status.result) || {};
      const totals = res.totals || {};
      const label = res.complete ? t("sweep complete") : (res.paused_reason ? t("paused") : "");
      // 2026-07-26 field-remarks item 6: totals.missing (closed-vocabulary rejections)
      // and totals.parse_failures were computed but never rendered -- real work was
      // silently happening while the panel looked like it was doing nothing.
      out.innerHTML = (label ? esc(label) + " — " : "") + esc(res.batches_completed || 0) + " batches, "
        + esc(totals.assigned_count || 0) + " tagged, "
        + esc(totals.none_count || 0) + " none, " + esc(res.skipped_evidence_floor || 0)
        + " skipped (evidence floor), " + esc(totals.missing || 0) + " rejected (not in your tag vocabulary), "
        + esc(totals.parse_failures || 0) + " unparsable replies, canaries "
        + (res.canary_ok_overall === false ? "FAILED" : "ok")
        + '<div style="margin-top:4px"><a href="/api/diagnostics/source-tags/download" target="_blank">'
        + t("Download report (.json)").replace(".json", ".jsonl") + "</a> — "
        + esc(t("proposed tags are logged only, never applied to Source.tags")) + "</div>";
    }

    async function syncSourceTagsToggle() {
      await _syncAiSweepToggle("source-tags", "st-toggle-btn", $("st-status"), $("st-result"), renderSourceTagsResult);
    }

    // Who/where/when PERCEPTION EXTRACTION (B6, 2026-07-24 Session B). Two parts:
    // (1) a bounded, synchronous run of the S6.5 perception-eval harness against the
    // ACTIVE model -- the gate evidence the extraction sweep below reads (mirrors
    // runIrEval's "bounded read-only eval" posture, not a background job -- it is a
    // SINGLE await, never a poll loop, so briefly disabling the button for its
    // duration is correct double-click-guard UX, not the toggle buttons' held-disabled
    // bug; checked per the 2026-07-26 field-remarks "worth a quick check" note and
    // confirmed NOT the same issue); (2) the progressive extraction sweep itself --
    // same shared toggle chassis as toggleKeywordTriage/toggleSourceTags above.
    async function runPerceptionEvalLive(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("pel-status"); const out = $("pel-result");
      if (btn) btn.disabled = true;
      if (el) el.textContent = t("Running…");
      try {
        const res = await api("/api/diagnostics/perception-eval-live", { method: "POST", body: JSON.stringify({}) });
        if (el) el.textContent = "";
        renderPerceptionEvalResult(out, res);
        loadPerceptionGate();
      } catch (e) {
        if (el) el.textContent = t("Could not run:") + " " + ((e && e.message) || "");
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function renderPerceptionEvalResult(out, res) {
      if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!res || res.status !== "ok") {
        out.textContent = t("unavailable") + (res && res.detail ? " — " + res.detail : "");
        return;
      }
      const r = res.report || {};
      out.textContent = t("model") + " " + (res.model || "?") + " " + t("on") + " " + (res.backend || "?")
        + " — " + (r.n_cases || 0) + " " + t("gold cases scored.");
    }

    // The language gate (B6): which languages cleared the last live perception-eval
    // run, and why not for the rest. Read-only, cheap (pure over the last saved
    // report) -- the standing "gate bites" ruling: the toggle UI shows which strata
    // are active and why, even before the toggle is ever clicked.
    async function loadPerceptionGate() {
      const out = $("pe-gate-result"); if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const g = await api("/api/diagnostics/perception-extract/gate");
        // TRI-STATE (2026-07-29): true = evaluated + cleared, false = evaluated + FAILED,
        // null = NO harness evidence. "unmeasured" is never folded into either of the
        // other two — an absence of measurement is not a verdict.
        const keys = Object.keys(g).filter((l) => g[l]);
        const active = keys.filter((l) => g[l].active === true).sort();
        const disabled = keys.filter((l) => g[l].active === false).sort();
        const unmeasured = keys.filter((l) => g[l].active == null).sort();
        // PER-FIELD (E-S3, 2026-08-01): a language cleared for `where` alone is
        // ACTIVE, but storing `who` there is still refused — so the field states are
        // shown beside the language, or "active" over-reads as "active for everything".
        const fieldBits = (l) => {
          const f = g[l].fields; if (!f) return "";
          const on = Object.keys(f).filter((k) => f[k] && f[k].active === true);
          const off = Object.keys(f).filter((k) => f[k] && f[k].active === false);
          const un = Object.keys(f).filter((k) => f[k] && f[k].active == null);
          return " [" + [
            on.length ? t("stores") + " " + on.join("/") : "",
            off.length ? t("gated") + " " + off.join("/") : "",
            un.length ? t("unmeasured") + " " + un.join("/") : "",
          ].filter(Boolean).map(esc).join(" · ") + "]";
        };
        const detail = (l) => esc(l) + fieldBits(l) + " (" + esc(g[l].reason || "") + ")";
        // Active languages show their reason too — that is what makes "cleared on 1
        // synthetic case — low statistical power" visible rather than implied.
        let html = "<b>" + t("Active languages:") + "</b> "
          + (active.length ? active.map(detail).join("; ") : t("none yet — run the harness above"));
        if (disabled.length) {
          html += "<br><b>" + t("Disabled:") + "</b> " + disabled.map(detail).join("; ");
        }
        if (unmeasured.length) {
          html += "<br><b>" + t("Unmeasured (no harness evidence):") + "</b> "
            + unmeasured.map(detail).join("; ");
        }
        out.innerHTML = html;
      } catch (e) { out.textContent = ""; }
    }

    // ---- THE BACKGROUND-AI MASTER TOGGLE (2026-08-01 ruling 12a) ---------- //
    // One coordinated lane over the sweeps the operator enables, instead of three
    // toggles that would queue behind each other on a single-generation backend.
    // Follows the langdetect/sweep chassis: NEVER holds btn.disabled across a
    // multi-hour run (a disabled button cannot be clicked to stop it) — state is
    // painted from data-running, and the poll is independent of the click.
    let _aicPolling = false;
    function _paintAiCoordinator(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const btn = $("aic-toggle-btn"), out = $("aic-status"), hw = $("aic-hw");
      if (!btn) return;
      const running = (st && st.state) === "running";
      btn.dataset.running = running ? "1" : "0";
      btn.textContent = running ? t("Pause background AI") : t("Start background AI");
      if (out) {
        const held = st && st.user_batch && st.user_batch.held;
        const parts = [];
        if (running) parts.push(esc(st.detail || t("running")));
        else if (st && st.state && st.state !== "idle") parts.push(esc(st.state));
        // The pause is stated, never left looking like a stall (ruling 13).
        if (held) parts.push('<span class="pill warn">' + esc(t("paused — your batch is running")) + "</span>");
        out.innerHTML = parts.join(" · ");
      }
      // The hardware verdict is a DEFAULT, never a block: it explains why the master
      // starts where it does, and the operator's override still turns it on.
      if (hw && st && st.hardware_default) {
        hw.textContent = st.hardware_default.default_on
          ? "" : t("This machine is below the local-inference practicality line ({r}) — background AI is off by default here. You can still start it.")
                   .replace("{r}", String(st.hardware_default.reason || ""));
      }
    }
    async function _pollAiCoordinator() {
      if (_aicPolling) return;
      _aicPolling = true;
      try {
        for (;;) {
          const st = await api("/api/diagnostics/ai-coordinator/status");
          _paintAiCoordinator(st);
          if (st.state !== "running") break;
          await new Promise(r => setTimeout(r, 4000));
        }
      } catch (e) { /* a poll failure must never wedge the button */ }
      finally { _aicPolling = false; }
    }
    async function toggleAiCoordinator(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const on = btn && btn.dataset.running === "1";
      try {
        if (on) await api("/api/diagnostics/ai-coordinator/cancel", {method: "POST"});
        else await api("/api/diagnostics/ai-coordinator/run", {method: "POST"});
      } catch (e) {
        toast(_apiErrorMessage ? _apiErrorMessage(e) : (e && e.message) || String(e), "err");
      }
      _pollAiCoordinator();
    }
    // The per-sweep membership checkboxes: the master coordinates them, it never
    // hides them — the operator can always see and change which sweeps are included.
    // The three COORDINATED sweeps share one settings prefix; language detection is
    // background AI too (the operator's own list says "tags, language...") but it is
    // NOT a coordinator member -- it is its own ride-along with its own flag. Wiring
    // its checkbox to a non-existent ai_sweep_langdetect would have produced a control
    // that saves nothing and reads back unchecked forever, which is worse than not
    // offering it.
    const AI_SWEEP_KEYS = ["keyword_triage", "source_tags", "perception_extract"];
    async function saveAiSweepMembership() {
      const body = {};
      AI_SWEEP_KEYS.forEach(k => {
        const el = $("aic-m-" + k);
        if (el) body["ai_sweep_" + k] = !!el.checked;
      });
      const ld = $("aic-m-langdetect");
      if (ld) body.ai_langdetect_auto = !!ld.checked;
      try { await api("/api/settings", {method: "PUT", body: JSON.stringify(body)}); }
      catch (e) { toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err"); }
    }
    async function syncAiCoordinator() {
      try {
        const st = await api("/api/diagnostics/ai-coordinator/status");
        _paintAiCoordinator(st);
        if (st.state === "running") _pollAiCoordinator();
      } catch (e) { /* absent backend: leave the panel at its default text */ }
      try {
        const s = await api("/api/settings");
        AI_SWEEP_KEYS.forEach(k => {
          const el = $("aic-m-" + k);
          if (el) el.checked = !!s["ai_sweep_" + k];
        });
        const ld = $("aic-m-langdetect");
        if (ld) ld.checked = !!s.ai_langdetect_auto;
      } catch (e) { /* settings unavailable: the checkboxes stay as rendered */ }
    }

    async function togglePerceptionExtract(btn) {
      await _toggleAiSweep("perception-extract", "pe-toggle-btn", $("pe-status"), $("pe-result"), renderPerceptionExtractResult);
    }

    function renderPerceptionExtractResult(out, status) {
      if (!out) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const res = (status && status.result) || {};
      const totals = res.totals || {};
      const label = res.complete ? t("sweep complete") : (res.paused_reason ? t("paused") : "");
      out.innerHTML = (label ? esc(label) + " — " : "") + esc(res.batches_completed || 0) + " batches, "
        + esc(totals.stored || 0) + " articles extracted (" + esc(totals.who || 0) + " who, "
        + esc(totals.where || 0) + " where, " + esc(totals.when || 0) + " when), "
        + esc(totals.gated || 0) + " gated, " + esc(totals.skipped_existing || 0) + " already done"
        + '<div style="margin-top:4px"><a href="/api/diagnostics/perception-extract/download" target="_blank">'
        + t("Download report (.json)").replace(".json", ".jsonl") + "</a></div>";
    }

    async function syncPerceptionExtractToggle() {
      await _syncAiSweepToggle("perception-extract", "pe-toggle-btn", $("pe-status"), $("pe-result"), renderPerceptionExtractResult);
    }

    // ----------------------------------------------------------------------- //
    //  Details — what the background AI has been doing (maintainer ask 2026-08-09)
    // ----------------------------------------------------------------------- //
    // FOLDED MEANS NOT FETCHED, and the poll lives and dies with the disclosure: a
    // details panel nobody has opened must not cost a request every few seconds.
    let _aiActivityTimer = null;

    function onAiActivityToggle(el) {
      if (el && el.open) {
        loadAiActivity();
        if (!_aiActivityTimer) _aiActivityTimer = setInterval(loadAiActivity, 5000);
      } else if (_aiActivityTimer) {
        clearInterval(_aiActivityTimer);
        _aiActivityTimer = null;
      }
    }

    // Two rates per sweep, never one. They diverge by the duty cycle -- the sweeps take
    // turns in the coordinator's lane -- so the model's own speed and what the corpus
    // actually gains are different numbers, and either alone tells a different story.
    function _aiRateLine(r, unit) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!r || r.measurable !== true) {
        return `<div class="muted">${esc(t("Rate:"))} ${esc((r && r.reason) || t("not measurable yet"))}</div>`;
      }
      const w = r.while_working_per_hour, c = r.wall_clock_per_hour;
      if (w === null && c === null) {
        return `<div class="muted">${esc(t("Too little time observed to state a rate yet."))}</div>`;
      }
      return `<div>` +
        `<strong>${esc(String(w === null ? "—" : w))}</strong> ${esc(unit)}/h ` +
        `<span class="muted">${esc(t("while working"))}</span> · ` +
        `<strong>${esc(String(c === null ? "—" : c))}</strong> ${esc(unit)}/h ` +
        `<span class="muted">${esc(t("wall clock"))}</span>` +
        ` <span class="muted">(n=${esc(String(r.batches))} ${esc(t("batches"))})</span></div>`;
    }

    async function loadAiActivity() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("ai-activity-body");
      if (!host) return;
      let r;
      try { r = await api("/api/diagnostics/ai-activity"); }
      catch (e) {
        host.innerHTML = `<p class="muted">${esc(t("Could not read the AI activity feed."))}</p>`;
        return;
      }
      const sweeps = (r.sweeps || []).map((s) => {
        const rows = [`<div style="font-weight:600;margin-top:8px">${esc(s.label || s.key)}</div>`];
        if (s.note) rows.push(`<div class="muted">${esc(s.note)}</div>`);
        rows.push(_aiRateLine(s.rates, s.unit || t("items")));
        const st = s.state || {};
        const totals = st.totals || {};
        const bits = Object.keys(totals).map((k) => `${esc(k)} ${esc(String(totals[k]))}`);
        if (st.batches_completed !== undefined) {
          bits.unshift(`${esc(t("batches"))} ${esc(String(st.batches_completed))}`);
        }
        if (bits.length) rows.push(`<div class="muted">${bits.join(" · ")}</div>`);
        if ((s.latest || []).length) {
          const items = s.latest.slice(0, 12).map((x) =>
            `<span class="pill">${esc(x.term || x.domain || "")}` +
            (x.verdict ? ` · ${esc(x.verdict)}` : "") +
            (Array.isArray(x.tags) && x.tags.length ? ` · ${esc(x.tags.join(", "))}` : "") +
            `</span>`).join(" ");
          rows.push(`<div style="margin-top:4px">${items}</div>`);
        } else if (s.latest_note) {
          // An empty list would read as "it found nothing", which is a different claim.
          rows.push(`<div class="muted">${esc(s.latest_note)}</div>`);
        }
        return rows.join("");
      }).join("");

      let stored = "";
      const sd = r.stored || {};
      if (sd.available === true) {
        // The TOTAL is over the STORED rows only, because those share one unit. Summing
        // keywords/h with sources/h with articles/h would put three different things
        // under one label -- so the per-sweep rates above stay in their own units.
        let total = 0, any = false;
        const kinds = (sd.kinds || []).map((k) => {
          if (typeof k.per_hour === "number") { total += k.per_hour; any = true; }
          const latest = (k.latest || []).slice(0, 8)
            .map((x) => `<span class="pill">${esc(x.term || "")}</span>`).join(" ");
          return `<div style="margin-top:6px"><strong>${esc(k.kind)}</strong> · ` +
            `${esc(t("total"))} ${esc(String(k.total))} · ` +
            `${esc(t("in the last"))} ${esc(String(sd.window_hours))}h: ${esc(String(k.in_window))}` +
            (typeof k.per_hour === "number" ? ` · <strong>${esc(String(k.per_hour))}</strong>/h` : "") +
            `</div>` + (latest ? `<div style="margin-top:2px">${latest}</div>` : "");
        }).join("");
        stored =
          `<div style="font-weight:600;margin-top:10px">${esc(t("Stored by the AI layer"))}</div>` +
          kinds +
          (any ? `<div style="margin-top:6px"><strong>${esc(String(Math.round(total * 10) / 10))}</strong> ` +
                 `${esc(t("AI-layer rows per hour, all categories"))}</div>` : "") +
          `<div class="card-caveat" style="margin-top:4px">${esc(sd.caveat || "")}</div>`;
      } else if (sd.reason) {
        stored = `<div class="muted" style="margin-top:8px">${esc(sd.reason)}</div>`;
      }

      const coord = (r.coordinator || {}).note
        ? `<div class="muted" style="margin-top:8px">${esc(r.coordinator.note)}</div>` : "";
      host.innerHTML = sweeps + stored + coord +
        `<div class="card-caveat" style="margin-top:8px">${esc(r.caveat || "")}</div>`;
    }

    // IR retrieval-eval over a human-judged gold set (keyword-engine P3): open the
    // /api/diagnostics/ir-eval report for a gold-set FILE — score the live search at the
    // current BM25F default, or (both weight boxes filled) A/B two (title,body) weight
    // sets via the conflation delta. Measure-before-trust; metrics only, no score. The
    // endpoint 400s on a missing/malformed gold set or half-specified weights.
    function runIrEval() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const path = (($("ir-eval-path") && $("ir-eval-path").value) || "").trim();
      if (!path) {
        if (typeof toast === "function") toast(t("Enter the gold-set file path first."));
        return;
      }
      const wa = (($("ir-eval-wa") && $("ir-eval-wa").value) || "").trim();
      const wb = (($("ir-eval-wb") && $("ir-eval-wb").value) || "").trim();
      const p = new URLSearchParams({gold_path: path});
      if (wa && wb) { p.set("weights_a", wa); p.set("weights_b", wb); }
      window.open("/api/diagnostics/ir-eval?" + p.toString(), "_blank");
    }

    // S5.4: surface the lemma-conflation PREVIEW visibly in the Diagnostics panel (it was
    // only reachable by downloading the engine-report JSON). Shows what OO_FAMILY_LEMMA
    // (default OFF) would merge among the top keywords + the would-merge counts, with the
    // _MISLEMMA_DENYLIST affordance. Reviews the decision, never flips it. Un-keyed English
    // (matches the diagnostics panel); browser-unverified per fork-3.
    async function loadLemmaPreview(btn) {
      const host = $("lemma-preview-body"); if (!host) return;
      if (btn) btn.disabled = true;
      host.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/diagnostics/lemma-preview");
        if (!d.available) {
          host.innerHTML = `<div class="hint muted">${esc(d.method || "Lemmatization preview unavailable (simplemma not installed).")}</div>`;
        } else {
          const overlapLabel = { plural_rule: "already via plural rule", mixed: "mixed", lemma_only: "lemma-only (true delta)" };
          const rows = (d.examples || []).map((c) => {
            const ov = c.plural_overlap || "";
            const ovTag = ov ? ` <span class="muted" style="font-size:11px">(${esc(overlapLabel[ov] || ov)})</span>` : "";
            return `<tr><td><b>${esc(c.lemma)}</b> <span class="muted">${esc(c.language || "?")}</span>${ovTag}</td>`
              + `<td>${(c.members || []).map(esc).join(", ")}</td>`
              + `<td style="text-align:right;font-variant-numeric:tabular-nums">${c.n}</td></tr>`;
          }).join("");
          const state = d.enabled ? "ON (default)" : "OFF";
          const bpo = d.by_plural_overlap || {};
          const overlapNote = (bpo.lemma_only !== undefined)
            ? ` Of these, <b>${bpo.lemma_only || 0}</b> are lemma-only (the true delta — verb forms/irregulars), `
              + `<b>${bpo.plural_rule || 0}</b> the plural rule already covers, and <b>${bpo.mixed || 0}</b> are mixed.`
            : "";
          host.innerHTML =
            `<div class="hint muted" style="margin-top:4px">OO_FAMILY_LEMMA is currently <b>${esc(state)}</b>. `
            + `Scanned top ${d.scanned_top_n} keywords → <b>${d.candidate_groups}</b> candidate merge groups, `
            + `<b>${d.keywords_that_would_merge}</b> keywords merge.${overlapNote} Review for precision; `
            + `a WRONG merge is a note for the _MISLEMMA_DENYLIST, or set OO_FAMILY_LEMMA=0 to opt out. ${esc(d.method || "")}</div>`
            + (rows
              ? `<table class="data" style="margin-top:6px"><thead><tr><th>Lemma</th><th>Merges</th><th style="text-align:right">n</th></tr></thead><tbody>${rows}</tbody></table>`
              : `<div class="muted" style="margin-top:6px">No candidate merges among the top keywords.</div>`);
        }
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      if (btn) btn.disabled = false;
    }

    // S5.3: the IR gold-set BUILDER. Samples real corpus queries (top keywords; search
    // history is not stored, so nothing is invented), lets the maintainer grade each live
    // result 0/1/2 with keyboard speed, and writes the EXACT ir_eval gold-set file the run
    // above scores — closing the measure-before-trust loop for OO_FAMILY_LEMMA + BM25F.
    // Un-keyed English (matches this diagnostics panel). Browser-unverified per fork-3.
    let _gbQueries = null;
    async function goldBuilderLoad(btn) {
      const body = $("gold-builder-body"); if (!body) return;
      if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
      try {
        const d = await api("/api/diagnostics/gold-builder/sample?n_queries=15&per_query=10");
        _gbQueries = (d.queries || []).map((q) => ({ ...q, relevances: {} }));
        _gbRenderBuilder(d.note, d.grading);
      } catch (e) { body.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      if (btn) { btn.disabled = false; btn.textContent = "Build an IR gold set (grade queries 0/1/2)"; }
    }
    function _gbRenderBuilder(note, grading) {
      const body = $("gold-builder-body"); if (!body) return;
      const blocks = (_gbQueries || []).map((q, qi) => {
        const rows = (q.results || []).map((r) => {
          const cur = q.relevances[r.article_id];
          const btns = [0, 1, 2].map((g) =>
            `<button class="tiny${cur === g ? " active" : ""}" data-g="${g}" onclick="goldBuilderGrade(${qi},${r.article_id},${g})">${g}</button>`).join("");
          return `<div class="gb-row" tabindex="0" data-q="${qi}" data-a="${r.article_id}" onkeydown="goldBuilderKey(event,${qi},${r.article_id})" style="display:flex;gap:8px;align-items:center;padding:2px 0">`
            + `<span style="min-width:70px">${btns}</span>`
            + `<a href="/api/articles/${r.article_id}/view" target="_blank" rel="noopener" title="offline stored copy">${esc(r.title || ("#" + r.article_id))}</a>`
            + `<span class="muted" style="font-size:11px">${esc(r.source || "")}${r.language ? " · " + esc(r.language) : ""}</span></div>`;
        }).join("");
        return `<div class="an-panel" style="margin-top:8px"><b>${esc(q.query)}</b> `
          + `<span class="muted">(${esc(q.language)} · ${esc(q.axis)})</span>`
          + (rows || `<div class="muted">No results in your corpus for this query.</div>`) + `</div>`;
      }).join("");
      body.innerHTML = `<div class="hint muted">${esc(note || "")} ${esc(grading || "")}</div>` + blocks;
      _gbUpdateCoverage();
    }
    function goldBuilderGrade(qi, aid, g) {
      const q = _gbQueries && _gbQueries[qi]; if (!q) return;
      q.relevances[aid] = g;   // grade IN PLACE (never re-render — keeps keyboard focus)
      const row = document.querySelector(`.gb-row[data-q="${qi}"][data-a="${aid}"]`);
      if (row) row.querySelectorAll("button").forEach((b) => b.classList.toggle("active", +b.dataset.g === g));
      _gbUpdateCoverage();
    }
    function goldBuilderKey(ev, qi, aid) {
      if (ev.key === "0" || ev.key === "1" || ev.key === "2") { ev.preventDefault(); goldBuilderGrade(qi, aid, +ev.key); }
    }
    function _gbUpdateCoverage() {
      const el = $("gold-builder-cov"); if (!el) return;
      let graded = 0, total = 0; const langs = {};
      (_gbQueries || []).forEach((q) => {
        const n = Object.keys(q.relevances).length; total += n;
        if (n) { graded++; langs[q.language] = (langs[q.language] || 0) + 1; }
      });
      const langStr = Object.keys(langs).length ? " · by language " + JSON.stringify(langs) : "";
      el.textContent = `Coverage: ${graded}/${(_gbQueries || []).length} queries graded · ${total} judgements${langStr}`;
    }
    async function goldBuilderSave(btn) {
      const path = (($("gold-builder-path") && $("gold-builder-path").value) || "").trim();
      if (!path) { if (typeof toast === "function") toast("Enter a save path first.", "err"); return; }
      if (!_gbQueries || !_gbQueries.length) { if (typeof toast === "function") toast("Load + grade queries first.", "err"); return; }
      const queries = _gbQueries.map((q) => ({ id: q.id, query: q.query, language: q.language, axis: q.axis, relevances: q.relevances }));
      if (btn) btn.disabled = true;
      try {
        const r = await api("/api/diagnostics/gold-builder/save", { method: "POST", body: JSON.stringify({ path, queries }) });
        const c = r.coverage || {};
        if (typeof toast === "function") toast(`Saved · ${c.graded_queries || 0} graded queries · ${c.total_judgements || 0} judgements`);
        const el = $("gold-builder-cov");
        if (el) el.textContent = `Saved to ${r.saved} — ${c.total_judgements || 0} judgements across ${JSON.stringify(c.by_language || {})}. Point the IR-eval run below at this path.`;
      } catch (e) { if (typeof toast === "function") toast(_failMsg("Save failed: {error}", e), "err"); }
      if (btn) btn.disabled = false;
    }

    // ---- E-S2 (2026-08-01, rulings 14-16): the COMPARATIVE model bench ---- //
    // Freeze the inputs once, grade the anchors once, then measure every roster
    // model over exactly those inputs. The panel deliberately shows the REFUSALS as
    // prominently as the results: a model that is not installed, a backend that is
    // unreachable and an ungraded anchor set are all facts the reader of the numbers
    // needs, and hiding them would make a partial bench read as a complete one.
    let _mbAnchors = null, _mbPolling = false;

    async function mbBuildBatch(btn) {
      const out = $("mb-batch"); if (btn) btn.disabled = true;
      try {
        const d = await api("/api/diagnostics/model-bench/batch", { method: "POST", body: JSON.stringify({}) });
        _mbRenderBatch(d);
      } catch (e) { if (out) out.innerHTML = `<div class="note err">${esc((e && e.message) || String(e))}</div>`; }
      if (btn) btn.disabled = false;
    }

    function _mbRenderBatch(d) {
      const out = $("mb-batch"); if (!out) return;
      if (!d || d.available === false) {
        out.innerHTML = `<span class="muted">${esc((d && d.reason) || "no frozen batch yet")}</span>`;
        return;
      }
      const strata = (d.keyword_strata || []).map((s) =>
        `${esc(s.language)} ${s.n} (${s.n_head} head · ${s.n_tail} tail)`).join(" · ");
      out.innerHTML = `<b>${d.n_keywords || 0}</b> keywords · <b>${d.n_sources || 0}</b> sources · `
        + `${(d.source_tag_vocabulary || []).length} tags · digest <code>${esc(d.digest || "?")}</code>`
        + `<div class="hint muted">${esc(strata)}</div>`
        + ((d.normalized_collisions || []).length
          ? `<div class="hint muted">${d.normalized_collisions.length} term group(s) differ only by case or accents — matched by exact echo only.</div>` : "");
    }

    async function mbAnchorsLoad(btn) {
      const body = $("mb-anchors-body"); if (!body) return;
      if (btn) btn.disabled = true;
      try {
        const d = await api("/api/diagnostics/model-bench/anchors?sample=50");
        _mbAnchors = (d.candidates || []).map((c) => ({ term: c.term, language: c.language, verdict: null, kind: null }));
        _mbRenderAnchors();
      } catch (e) { body.innerHTML = `<div class="note err">${esc((e && e.message) || String(e))}</div>`; }
      if (btn) btn.disabled = false;
    }

    function _mbRenderAnchors() {
      const body = $("mb-anchors-body"); if (!body) return;
      const rows = (_mbAnchors || []).map((a, i) => {
        const vb = ["junk", "content", "unsure"].map((v) =>
          `<button class="tiny${a.verdict === v ? " active" : ""}" data-v="${v}" onclick="mbAnchorGrade(${i},'${v}')">${v[0].toUpperCase()}</button>`).join("");
        const kb = ["person", "org", "place", "other"].map((k) =>
          `<button class="tiny${a.kind === k ? " active" : ""}" data-k="${k}" onclick="mbAnchorKind(${i},'${k}')">${esc(k)}</button>`).join("");
        return `<div class="mb-row" tabindex="0" data-i="${i}" onkeydown="mbAnchorKey(event,${i})" style="display:flex;gap:8px;align-items:center;padding:2px 0">`
          + `<span style="min-width:78px">${vb}</span>`
          + `<span style="min-width:170px">${esc(a.term)}</span>`
          + `<span class="muted" style="font-size:11px;min-width:26px">${esc(a.language || "")}</span>`
          + `<span>${kb}</span></div>`;
      }).join("");
      body.innerHTML = `<div class="hint muted">J = junk · C = content · U = unsure on a focused row. A kind is optional — leaving it blank costs one kind case, an invented kind costs the measurement.</div>` + rows;
      _mbUpdateAnchorCov();
    }

    function mbAnchorGrade(i, v) {
      const a = _mbAnchors && _mbAnchors[i]; if (!a) return;
      a.verdict = v;   // in place, never a re-render — keeps keyboard focus
      const row = document.querySelector(`.mb-row[data-i="${i}"]`);
      if (row) row.querySelectorAll("button[data-v]").forEach((b) => b.classList.toggle("active", b.dataset.v === v));
      _mbUpdateAnchorCov();
    }

    function mbAnchorKind(i, k) {
      const a = _mbAnchors && _mbAnchors[i]; if (!a) return;
      a.kind = (a.kind === k) ? null : k;
      const row = document.querySelector(`.mb-row[data-i="${i}"]`);
      if (row) row.querySelectorAll("button[data-k]").forEach((b) => b.classList.toggle("active", b.dataset.k === a.kind));
      _mbUpdateAnchorCov();
    }

    function mbAnchorKey(ev, i) {
      const map = { j: "junk", c: "content", u: "unsure" };
      const v = map[(ev.key || "").toLowerCase()];
      if (v) { ev.preventDefault(); mbAnchorGrade(i, v); }
    }

    function _mbUpdateAnchorCov() {
      const el = $("mb-anchors-cov"); if (!el) return;
      const all = _mbAnchors || [];
      const graded = all.filter((a) => a.verdict).length;
      el.textContent = all.length ? `${graded}/${all.length} graded` : "";
    }

    async function mbAnchorsSave(btn) {
      const rows = (_mbAnchors || []).filter((a) => a.verdict)
        .map((a) => (a.kind ? { term: a.term, verdict: a.verdict, kind: a.kind } : { term: a.term, verdict: a.verdict }));
      if (!rows.length) { if (typeof toast === "function") toast("Grade at least one anchor first.", "err"); return; }
      if (btn) btn.disabled = true;
      try {
        const r = await api("/api/diagnostics/model-bench/anchors", { method: "POST", body: JSON.stringify({ anchors: rows }) });
        if (typeof toast === "function") toast(`Saved ${r.n} anchors.`);
      } catch (e) { if (typeof toast === "function") toast(_failMsg("Save failed: {error}", e), "err"); }
      if (btn) btn.disabled = false;
    }

    function _mbPaint(st) {
      // ONE button since the one-model ruling, so the painter targets it directly.
      // It used to paint a second, comparative control; leaving that id here would
      // have made the surviving button silently unpaintable — running for tens of
      // minutes with nothing on screen saying so.
      const btn = $("mb-default-btn"), el = $("mb-default-status");
      const running = st && st.state === "running";
      if (btn) {
        btn.dataset.running = running ? "1" : "0";
        btn.textContent = running ? "Stop the bench" : "Bench the model (this backend)";
      }
      const p = (st && st.progress) || {};
      if (el) {
        el.textContent = running
          ? `${p.done || 0}/${p.total || "?"} · ${p.detail || ""}`
          : (st && st.state === "error" ? `failed: ${st.error || ""}` : "");
      }
      if (!running && st && st.result) _mbRenderResult(st.result);
    }

    function _mbRenderResult(res) {
      const out = $("mb-result"); if (!out || !res) return;
      if (res.status === "refused") {
        out.innerHTML = `<div class="note err">${esc(res.detail || res.reason || "refused")}</div>`;
        return;
      }
      const rows = Object.keys(res.results || {}).map((key) => {
        const r = res.results[key], tk = r.tasks || {};
        const bits = [];
        const tri = tk.triage || {};
        if (tri.format_validity != null) bits.push(`triage validity ${tri.format_validity}`);
        if (tri.valid_verdicts_per_s != null) bits.push(`${tri.valid_verdicts_per_s}/s`);
        // WITH ITS DENOMINATOR. Bare "canary FAILED" read identically for a model
        // that failed 2 of 36 canary slots and three that failed 36 of 36 — the one
        // distinction a comparative bench exists to make.
        if (tri.canary && tri.canary.ok === false) {
          bits.push(tri.canary.checked
            ? `canary ${tri.canary.failed_n || 0}/${tri.canary.checked} FAILED`
            : "canary FAILED");
        }
        const stg = tk.source_tags || {};
        if (stg.format_validity != null) bits.push(`tags validity ${stg.format_validity}`);
        const ld = tk.langdetect || {};
        if (ld.accuracy_over_all != null) bits.push(`langdetect ${ld.accuracy_over_all} (n=${ld.n})`);
        const xl = tk.translation || {};
        if (xl.in_target_rate != null) {
          // The RATE with what it was taken over, and the unmeasurable count beside
          // it: an answer the referee refused to read is a gap in the check, not a
          // failed translation, and the two must not be read as one number.
          const judged = (xl.asked || 0) - (xl.unmeasurable || 0);
          bits.push(`translation in-target ${xl.in_target_rate} (${xl.in_target}/${judged})`);
          if (xl.unmeasurable) bits.push(`${xl.unmeasurable} unmeasurable`);
          if (xl.echoed) bits.push(`${xl.echoed} echoed the source`);
        }
        if (r.tasks_not_asked) bits.push(`not asked: ${r.tasks_not_asked.tasks.join(", ")}`);
        // THE DEVICE, on the row. Ollama falling back to the CPU makes every timing
        // beside it a measurement of a different machine, and the reader has to see
        // that where they read the numbers — not only in the JSON.
        const dev = (r.device || {}).device;
        if (dev && dev !== "gpu") bits.push(dev === "cpu" ? "ran on CPU" : `device: ${dev}`);
        const errs = Object.keys(tk).filter((k) => tk[k] && tk[k].status === "error");
        if (errs.length) bits.push(`errors: ${errs.join(", ")}`);
        return `<div><b>${esc(key)}</b>${r.quantization ? ` <span class="muted">${esc(r.quantization)}</span>` : ""} — ${esc(bits.join(" · ") || "no metrics")}</div>`;
      }).join("");
      // A skip names the model where there IS one. A roster model with no build for
      // this backend has no identifier to print — nothing to install, so nothing to
      // name — and its roster key is the only thing that says WHICH model is absent.
      const skipped = (res.skipped || []).map((s) => {
        const who = s.model || s.roster_key || "";
        return `${esc(s.backend)}${who ? " · " + esc(who) : ""} — ${esc(s.reason)}`;
      }).join("<br>");
      out.innerHTML = rows
        + (res.pairs_pending && res.pairs_pending.length
          ? `<div class="hint muted" style="margin-top:4px">Not yet measured: ${esc(res.pairs_pending.join(", "))}</div>` : "")
        + (skipped ? `<div class="hint muted" style="margin-top:4px">${skipped}</div>` : "")
        + (res.anchors && res.anchors.available === false
          ? `<div class="card-caveat" style="margin-top:4px">No graded anchors: accuracy against a human grade is UNMEASURED. Models agreeing is not either being right.</div>` : "")
        + `<div class="hint muted" style="margin-top:4px">${esc(res.caveat || "")}</div>`;
      mbShowGates();
    }

    // E-S3: what the bench's per-language verdicts actually gate. Shown BESIDE the
    // results, because a measurement nobody can act on is a dead end — and because
    // the two gate shapes behave oppositely on unmeasured input, which the reader
    // has to be told rather than left to infer.
    async function mbShowGates() {
      const out = $("mb-gates"); if (!out) return;
      try {
        const d = await api("/api/diagnostics/model-bench/gates");
        const rows = Object.keys(d.gates || {}).map((task) => {
          const g = d.gates[task] || {};
          const keys = Object.keys(g);
          if (!keys.length) return `<div><b>${esc(task)}</b> — no bench evidence</div>`;
          const on = keys.filter((k) => g[k].active === true).sort();
          const off = keys.filter((k) => g[k].active === false).sort();
          const un = keys.filter((k) => g[k].active == null).sort();
          const wired = (d.wired || []).includes(task) ? "" : " (computed, not yet applied)";
          return `<div><b>${esc(task)}</b>${esc(wired)} — `
            + `cleared: ${esc(on.join(", ") || "none")}`
            + (off.length ? ` · refused: ${esc(off.join(", "))}` : "")
            + (un.length ? ` · unmeasured: ${esc(un.join(", "))}` : "") + `</div>`;
        }).join("");
        out.innerHTML = rows + `<div class="hint muted" style="margin-top:4px">${esc(d.caveat || "")}</div>`;
      } catch (e) { out.textContent = ""; }
    }

    async function _mbPoll() {
      if (_mbPolling) return;
      _mbPolling = true;
      try {
        for (;;) {
          const st = await api("/api/diagnostics/model-bench/status");
          _mbPaint(st);
          if (st.state !== "running") break;
          await new Promise((r) => setTimeout(r, 4000));
        }
      } catch (e) { /* a poll failure must never wedge the button */ }
      finally { _mbPolling = false; }
    }

    // Measure THE model on whichever backend the operator has running.
    //
    // RULED 2026-08-12: the operator manages the backends, so this sends nothing that
    // could start, stop or switch one. There is no mode flag any more -- with one model
    // the bench has one mode, and a flag whose only legal value is true is a flag that
    // will eventually be passed wrongly. Two runs, one per backend, compared afterwards;
    // each report says which backend and which device it measured, which is what makes
    // the pair comparable at all.
    async function mbRun(btn) {
      const on = btn && btn.dataset.running === "1";
      try {
        if (on) await api("/api/diagnostics/model-bench/cancel", { method: "POST" });
        else await api("/api/diagnostics/model-bench/run", { method: "POST", body: "{}" });
      } catch (e) {
        if (typeof toast === "function") toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      }
      _mbPoll();
    }

    // ---- ONE BUTTON: every AI check, one report ---------------------------- //
    // Maintainer 2026-08-09: "Can you simplify all AI related diagnostics into one
    // single button to test everything at once?" A background job, because the
    // throughput sweep and the live eval take minutes; the button toggles run/stop
    // rather than disabling, so a multi-minute run never leaves a dead control.
    let _aiCheckPolling = false;

    function _aiCheckLine(label, body) {
      return `<div><b>${esc(label)}</b> — ${body}</div>`;
    }

    function _renderAiCheck(res) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const out = $("aicheck-result");
      if (!out) return;
      if (!res) { out.innerHTML = ""; return; }
      const r = res.reading || {};
      const rows = [];
      const b = r.backend || {};
      rows.push(_aiCheckLine(
        t("Backend"),
        b.available
          ? `${esc(b.serves_with || b.backend || "?")} · ${esc(b.model || "?")}`
          : `<span class="warn">${esc(b.reason || t("no backend is reachable"))}</span>`,
      ));
      const th = r.throughput;
      if (th) {
        rows.push(_aiCheckLine(
          t("Throughput"),
          `${esc(String(th.best_calls_per_hour))} ${esc(t("per hour"))} `
          + `${esc(t("at concurrency"))} ${esc(String(th.best_measured_concurrency))} `
          + `(${esc(t("configured"))} ${esc(String(th.configured_concurrency))})`
          + `<div class="hint">${esc(th.action || "")}</div>`,
        ));
      }
      const g = r.extraction_gate;
      if (g && !g.error) {
        rows.push(_aiCheckLine(
          t("Extraction gate"),
          `${esc(t("cleared"))}: ${esc((g.cleared || []).join(", ") || t("none"))}`
          + ((g.refused || []).length ? ` · ${esc(t("refused"))}: ${esc(g.refused.join(", "))}` : "")
          + ((g.unmeasured || []).length ? ` · ${esc(t("unmeasured"))}: ${esc(g.unmeasured.join(", "))}` : ""),
        ));
      }
      // WHAT THE BENCH COVERED, never a headline number for it: the numbers are per
      // model, per task, per language, and a single figure over those is the composite
      // the whole bench exists to refuse. This says what is IN the table.
      const m = r.models;
      if (m && !m.refused) {
        const ran = (m.pairs_measured || []).length;
        const both = m.same_model_on_both_backends || [];
        const skipped = Object.entries(m.skipped_by_reason || {})
          .map(([why, who]) => `${esc(why)} (${who.length})`).join(" · ");
        rows.push(_aiCheckLine(
          t("Models measured"),
          `${esc(String(ran))} ${esc(t("model/backend pairs"))}`
          + (both.length ? ` · ${esc(String(both.length))} ${esc(t("on both backends"))}` : "")
          + (skipped ? `<div class="hint">${esc(t("skipped"))}: ${skipped}</div>` : "")
          + `<div class="hint">${esc(t("Anchor accuracy"))}: ${esc(m.anchor_accuracy || "")}</div>`,
        ));
      } else if (m && m.refused) {
        rows.push(_aiCheckLine(t("Models measured"), `<span class="warn">${esc(m.refused)}</span>`));
      }
      // Every step, with its own time — including the ones that failed, because a
      // report from a half-broken machine is most useful when it says which half.
      const steps = (res.steps || []).map((s) =>
        `${esc(s.step)} ${s.ok ? "✓" : "✗"} ${esc(String(s.seconds))}s`
        + (s.ok ? "" : ` <span class="warn">${esc((s.error || "").slice(0, 120))}</span>`),
      ).join(" · ");
      rows.push(`<div class="hint" style="margin-top:4px">${steps}</div>`);
      const sep = (res.not_run_here || []).map((n) =>
        `${esc(n.name)} — ${esc(n.why)} (${esc(n.where)})`).join("<br>");
      if (sep) rows.push(`<div class="hint muted" style="margin-top:4px">${t("Not part of this check")}: ${sep}</div>`);
      if (res.caveat) rows.push(`<div class="card-caveat" style="margin-top:4px">${esc(res.caveat)}</div>`);
      out.innerHTML = rows.join("");
    }

    function _paintAiCheck(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const btn = $("aicheck-btn"), el = $("aicheck-status");
      const running = st && st.state === "running";
      if (btn) {
        btn.dataset.running = running ? "1" : "0";
        btn.textContent = running ? t("Stop the AI checks") : t("Run all AI checks");
      }
      const p = (st && st.progress) || {};
      if (el) {
        el.textContent = running
          ? `${p.done || 0}/${p.total || "?"} · ${p.detail || ""}`
          : (st && st.state === "error" ? `${t("failed:")} ${st.error || ""}` : "");
      }
      if (!running && st && st.result) _renderAiCheck(st.result);
    }

    async function _aiCheckPoll() {
      if (_aiCheckPolling) return;
      _aiCheckPolling = true;
      try {
        for (;;) {
          const st = await api("/api/diagnostics/ai-check/status");
          _paintAiCheck(st);
          if (st.state !== "running") break;
          await new Promise((r) => setTimeout(r, 2000));
        }
      } catch (e) { /* a poll failure must never wedge the button */ }
      finally { _aiCheckPolling = false; }
    }

    async function runAiCheck(btn) {
      const on = btn && btn.dataset.running === "1";
      // The deep run adds the model bench: tens of minutes rather than minutes, running
      // the frozen batch through the model task by task. That is worth one confirm — it
      // is resumable, so the honest promise is "cancelling keeps what it measured", not
      // "you can undo this". It no longer restarts anything: since the one-model ruling
      // the bench measures whatever backend is already serving and manages nothing, so
      // there is also no download to survey and consent to first.
      const deep = !on && !!($("aicheck-deep") || {}).checked;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (deep && !confirm(t("Benching the model takes tens of minutes. It measures whichever backend is already running and starts, stops and switches nothing. It is resumable: cancelling keeps what it measured. Start it?"))) return;
      try {
        if (on) await api("/api/diagnostics/ai-check/cancel", { method: "POST" });
        else await api("/api/diagnostics/ai-check/run", { method: "POST", body: JSON.stringify({ deep }) });
      } catch (e) {
        if (typeof toast === "function") toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      }
      _aiCheckPoll();
    }

    // ---- T10 slice 1: the corpora window (keyword-click entry) ---- //
