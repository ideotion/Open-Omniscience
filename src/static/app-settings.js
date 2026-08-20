/* app-settings.js — Settings, help, AI models

   The docs/help viewer and the health pill, Ollama install and the model catalog,
   LLM prompts, language detection, custom extractors, the Settings load/save cycle,
   the keyword filter, the card catalog, and newsletter / PDF import.

   PART OF THE UI ENGINE. src/static/app.js was decomposed into ordered modules
   (structural debt S-3; docs/design/APPJS_DECOMPOSITION_2026-08-20.md). They share
   ONE global scope -- there is no module system here, and 413 globals are named by
   inline on*= handlers that can resolve against nothing else -- and they load in the
   order index.html lists them, with app-boot.js last.

   The split was a pure CONTIGUOUS slice, verified at the split commit by
   concatenating the modules in load order and reproducing the pre-split file byte
   for byte. That check is spent now (these files are edited normally), but the rule
   it rested on still holds: DO NOT reorder a declaration across a module boundary.
   Function declarations would survive it, because they hoist; a const or let would
   not, and the failure is a TDZ error at load rather than anything a reader would
   spot in review. Add new code inside the module it belongs to.
*/
    let _docList = null, _docSlug = null, _docRaw = "";
    async function ensureDocList() {   // fetch the list once (also feeds the palette)
      if (_docList === null) {
        try { _docList = (await api("/api/docs")).docs || []; } catch (e) { _docList = []; }
      }
      return _docList;
    }
    async function loadDocs() {
      await ensureDocList();
      if (!_docList.length) { $("doc-nav").innerHTML = '<div class="muted">Docs unavailable.</div>'; return; }
      $("doc-nav").innerHTML = _docList.map(d =>
        `<button class="doc-link ${d.slug === _docSlug ? "active" : ""}" ${d.available ? "" : "disabled"}
           onclick="openDoc('${d.slug}')">${esc(d.title)}<small>${esc(d.blurb)}</small></button>`).join("");
      if (!_docSlug) openDoc((_docList.find(d => d.slug === "user-manual") || _docList[0] || {}).slug);
    }
    async function openDoc(slug) {
      if (!slug) return;
      _docSlug = slug;
      document.querySelectorAll(".doc-link").forEach(b =>
        b.classList.toggle("active", b.getAttribute("onclick").includes("'" + slug + "'")));
      const prose = $("doc-prose"); prose.innerHTML = '<div class="muted">Loading…</div>';
      try {
        // Serve the reader's UI language when a translated draft exists; the
        // X-OO-Doc-Lang header says what was ACTUALLY served (honest banner).
        const lang = (window.OOI18N && OOI18N.current()) || "en";
        const r = await fetch("/api/docs/" + slug + "?lang=" + encodeURIComponent(lang));
        if (!r.ok) throw new Error(String(r.status));
        _docRaw = await r.text();
        const served = r.headers.get("X-OO-Doc-Lang") || "en";
        const banner = (served !== "en")
          ? `<div class="hint" style="border:1px solid var(--border);border-radius:8px;padding:6px 10px;margin-bottom:10px">` +
            `<span>Machine-drafted translation — the English original is authoritative. Found a better wording? Improve it on the project page.</span></div>`
          : "";
        prose.innerHTML = banner + mdToHtml(_docRaw); prose.scrollIntoView({block:"nearest"});
      }
      catch (e) { prose.innerHTML = '<div class="muted">Could not load this document.</div>'; }
      const f = $("doc-find"); if (f && f.value) highlightProse(f.value);
    }
    function filterDoc() {
      if (!_docRaw) return;
      $("doc-prose").innerHTML = mdToHtml(_docRaw);
      highlightProse($("doc-find").value);
    }
    function highlightProse(q) {
      q = (q || "").trim(); if (q.length < 2) return;
      const root = $("doc-prose");
      const rx = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      let first = null;
      for (const n of nodes) {
        if (!rx.test(n.nodeValue)) continue;
        const span = document.createElement("span");
        span.innerHTML = esc(n.nodeValue).replace(rx, '<mark>$1</mark>');
        if (!first) first = span;
        n.parentNode.replaceChild(span, n);
      }
      if (first) first.scrollIntoView({block:"center", behavior:"smooth"});
    }

    // Minimal, safe Markdown → HTML (escape first, then format). Handles
    // headings, lists, tables, code fences, blockquotes, rules and inline marks.
    function mdToHtml(md) {
      const fences = [];
      md = md.replace(/```([\s\S]*?)```/g, (_, code) =>
        ` F${fences.push(`<pre><code>${esc(code.replace(/^\n/, ""))}</code></pre>`) - 1} `);
      const inline = (t) => esc(t)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
        .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, txt, url) =>
          /^(https?:|\/|#)/.test(url) ? `<a href="${esc(url)}" ${url.startsWith("http") ? 'target="_blank" rel="noopener"' : ""}>${txt}</a>` : m);
      const lines = md.split("\n"), out = [];
      let i = 0;
      // help-md-linebreak-bug (P1): calling inline() PER RAW SOURCE LINE, before
      // joining lines together, made a **bold**/*em*/[link]() span whose markers
      // land on different wrapped source lines invisible to the per-line regex on
      // BOTH lines — and could make a dangling opening marker mis-pair with a
      // LATER, unrelated marker on the second line, producing a garbled, wrongly-
      // placed <strong>/<em> (reported in USER_MANUAL.md and the Ethics doc, ~64
      // unrendered spans). Joining the raw lines into ONE string per paragraph
      // BEFORE running inline() lets the regex see the whole span regardless of
      // which source line it was wrapped on.
      const flushPara = (buf) => { if (buf.length) out.push("<p>" + inline(buf.join(" ")) + "</p>"); };
      let para = [];
      while (i < lines.length) {
        const ln = lines[i];
        const fence = ln.match(/^ F(\d+) $/);
        if (fence) { flushPara(para); para = []; out.push(fences[+fence[1]]); i++; continue; }
        if (/^\s*$/.test(ln)) { flushPara(para); para = []; i++; continue; }
        let m;
        if ((m = ln.match(/^(#{1,6})\s+(.*)$/))) { flushPara(para); para = [];
          const lvl = m[1].length; out.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`); i++; continue; }
        if (/^\s*([-*_])\1{2,}\s*$/.test(ln)) { flushPara(para); para = []; out.push("<hr>"); i++; continue; }
        // table: header row + |---| separator
        if (ln.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
          flushPara(para); para = [];
          const cells = (r) => r.replace(/^\s*\|?|\|?\s*$/g, "").split("|").map(c => c.trim());
          const head = cells(ln); i += 2;
          let body = "";
          while (i < lines.length && lines[i].includes("|") && !/^\s*$/.test(lines[i])) {
            body += "<tr>" + cells(lines[i]).map(c => `<td>${inline(c)}</td>`).join("") + "</tr>"; i++;
          }
          out.push(`<table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`);
          continue;
        }
        if (/^\s*>\s?/.test(ln)) { flushPara(para); para = [];
          let q = []; while (i < lines.length && /^\s*>\s?/.test(lines[i])) { q.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
          // Same cross-line fix as flushPara, but a blockquote's line breaks must
          // stay VISIBLE (unlike a paragraph's, which collapse to one space) — join
          // with a placeholder inline() can't possibly escape or match (esc() only
          // touches &<>"'), run inline() on the WHOLE joined string so a span
          // crossing a quoted line is seen as one contiguous string, THEN swap the
          // placeholder for a real <br> after escaping/formatting has already run.
          out.push("<blockquote>" + inline(q.join("\u0000")).replace(/\u0000/g, "<br>") + "</blockquote>"); continue; }
        if (/^\s*([-*+]|\d+\.)\s+/.test(ln)) { flushPara(para); para = [];
          const ordered = /^\s*\d+\.\s+/.test(ln); let items = [];
          while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
            items.push("<li>" + inline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "")) + "</li>"); i++;
          }
          const tag = ordered ? "ol" : "ul";
          out.push(`<${tag}>` + items.join("") + `</${tag}>`); continue; }
        para.push(ln); i++;
      }
      flushPara(para);
      return out.join("\n");
    }

    function humanBytes(n) {
      if (n == null) return "—";
      const u = ["B","KB","MB","GB","TB"]; let i = 0;
      while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
      return n.toFixed(i ? 1 : 0) + " " + u[i];
    }

    // Boot: fetch the version once. The PILL is no longer painted from here --
    // api() paints it from every request's outcome (see _noteReachable), because
    // this function runs exactly once and a one-shot paint can never go red.
    async function loadHealth() {
      try {
        const h = await api("/api/health");
        $("version").textContent = "v" + h.version;
      } catch (e) { /* _noteReachable has already painted the pill honestly */ }
    }

    // -- Settings tab ------------------------------------------------------- //
    // Local UI preferences. DEFAULT_LIMIT feeds the search; the theme is applied by
    // the appearance engine above (applyUi / applyThemeAttr).
    let DEFAULT_LIMIT = 50;
    const _media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
    // Real on-disk DB size (main+wal+shm), refreshed by loadSettings from
    // /api/database/stats; feeds vacuumNow's honest size-gate estimate (DB-10 §1.4).
    let _dbFileBytes = null;

    // --- Ollama BINARY installer (Settings → AI) ------------------------------ //
    // The missing half of model management (maintainer 2026-06-20: "can't find the
    // AI installer"). Shown only when Ollama is NOT already installed. Prepare =
    // download + VERIFY the OFFICIAL installer against GitHub's attested checksum
    // (a clearnet network action via the guarded factory → the ONE consent, #14);
    // then run it here when elevation needs no password, else show the verified
    // command to paste into a terminal. Elevation is always explicit, never hidden.
    let _ollamaInstalling = false;
    async function loadOllamaInstall() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("llm-install-box"); if (!box) return;
      if (_ollamaInstalling) return;  // don't clobber an in-progress run's output
      let s;
      try { s = await api("/api/llm/install/status"); }
      catch (e) { box.style.display = "none"; return; }
      if (s.ollama_present) { box.style.display = "none"; box.innerHTML = ""; return; }
      const p = s.platform || {};
      box.style.display = "";
      if (!p.scripted) {
        // macOS/Windows: honest pointer to the graphical installer, no fake auto-install.
        const url = p.download_url || "https://ollama.com/download";
        box.innerHTML = `<div class="panel" style="border-color:var(--accent)">` +
          `<strong>${esc(t("Install Ollama"))}</strong>` +
          `<p class="muted" style="margin:6px 0">${esc(p.reason || t("Download and run the official installer for your system, then return here."))}</p>` +
          `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(t("Open ollama.com/download ↗"))}</a></div>`;
        return;
      }
      box.innerHTML = `<div class="panel" style="border-color:var(--accent)">` +
        `<strong>${esc(t("Install Ollama"))}</strong>` +
        `<p class="muted" style="margin:6px 0">${esc(t("Ollama is not installed yet. The app can download the official installer, verify its checksum against the publisher's attestation, and run it. Installing needs administrator rights and downloads over the clear internet (not this app's Tor proxy)."))}</p>` +
        `<button id="llm-install-prepare-btn" onclick="prepareOllamaInstall()">${esc(t("Download & verify the official installer"))}</button>` +
        `<div id="llm-install-detail" class="hint" style="margin-top:8px"></div>` +
        `<pre id="llm-install-log" style="display:none;max-height:220px;overflow:auto;background:var(--bg2);padding:8px;border-radius:6px;margin-top:8px;font:12px ui-monospace,monospace;white-space:pre-wrap"></pre></div>`;
    }
    async function prepareOllamaInstall() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const detail = $("llm-install-detail"); const btn = $("llm-install-prepare-btn");
      // The AI-install egress window, not full online: this needs a few
      // infrastructure hosts, not the whole catalogue, and must not start the
      // collector. Already-online installs skip the ask entirely.
      if (!await ensureAiEgress(t("Download and verify the official Ollama installer (downloads over the clear internet)"))) return;
      if (btn) { btn.disabled = true; }
      if (detail) detail.textContent = t("Downloading and verifying…");
      let d;
      try { d = await api("/api/llm/install/prepare", {method: "POST"}); }
      catch (e) { if (detail) detail.textContent = t("Could not prepare the installer:") + " " + e.message; if (btn) btn.disabled = false; return; }
      if (btn) btn.style.display = "none";
      // Show the verified version + checksum + how to run it. The checksum is the
      // publisher's own attestation we verified the bytes against — show it so the
      // user can cross-check; never present an unverified script.
      let st = {};
      try { st = await api("/api/llm/install/status"); } catch (_e) {}
      const runNow = st.can_run_unattended
        ? `<button onclick="runOllamaInstall(${esc(JSON.stringify(d.path))})" style="margin-top:8px">${esc(t("Install now"))}</button>`
        : "";
      const manual = `<p class="muted" style="margin:8px 0 2px">${esc(st.can_run_unattended ? t("Or run it yourself in a terminal:") : t("Administrator rights are needed and the app cannot ask for your password. Run this in a terminal:"))}</p>` +
        `<pre style="background:var(--bg2);padding:8px;border-radius:6px;font:12px ui-monospace,monospace;white-space:pre-wrap">${esc(d.manual_command)}</pre>`;
      if (detail) detail.innerHTML =
        `<div>${esc(t("Verified Ollama"))} <code>${esc(d.version)}</code> · SHA-256 <code>${esc((d.sha256||"").slice(0,16))}…</code></div>` +
        runNow + manual +
        `<p class="muted" style="margin-top:6px">${esc(t("After installing, click Recheck below."))} <button class="tiny secondary" onclick="recheckOllama()">${esc(t("Recheck"))}</button></p>`;
    }
    async function runOllamaInstall(path) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const log = $("llm-install-log"); if (!log) return;
      // The prepare step opened a window, but this is a SEPARATE click and the
      // window closes itself once nothing is running -- so an operator who reads
      // the checksum before pressing Install arrives here with no window and the
      // backend refuses (run_installer calls _check_online too). Re-ask rather
      // than fail: it is the same consent, and skipping it here was the one AI
      // entry point that could dead-end with no way back except going fully
      // online, which starts the collector.
      if (!await ensureAiEgress(t("Run the verified Ollama installer"))) return;
      _ollamaInstalling = true;
      log.style.display = ""; log.textContent = "";
      try {
        const resp = await fetch("/api/llm/install/run", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path}),
        });
        const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
        let exitCode = null;
        for (;;) {
          const {value, done} = await reader.read(); if (done) break;
          buf += dec.decode(value, {stream: true});
          let nl;
          while ((nl = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
            if (!line.trim()) continue;
            let o; try { o = JSON.parse(line); } catch (_e) { continue; }
            if (o.event === "line") { log.textContent += o.text + "\n"; log.scrollTop = log.scrollHeight; }
            else if (o.event === "error") { log.textContent += "\n" + t("Error:") + " " + o.error + "\n"; }
            else if (o.event === "done") { exitCode = o.exit_code; }
          }
        }
        log.textContent += "\n" + (exitCode === 0 ? t("Installation finished.") : t("Installer exited with code") + " " + exitCode) + "\n";
      } catch (e) {
        log.textContent += "\n" + t("Error:") + " " + e.message + "\n";
      } finally {
        _ollamaInstalling = false;
        recheckOllama();
      }
    }
    function recheckOllama() {
      loadLlmHealth(); loadOllamaInstall(); loadLlmModels();
      // The fused setup box's plan is now stale by construction -- a backend that
      // just appeared removes a step from it.
      if (typeof loadAiSetup === "function") loadAiSetup();
      // Same reason: the model catalogue's download button is blocked while its
      // backend is absent, and Ollama just stopped being absent.
      if (typeof loadModelCatalog === "function") loadModelCatalog();
    }

    // The default-model install block. Shared so it renders in BOTH panel states --
    // notably the Ollama-not-running one, where installing the default model is the
    // whole point. Kept SEPARATE from the suggested-models table on purpose: that
    // table is the dated, verified catalog, and this entry carries its own licence
    // provenance, which is shown here rather than only in the confirm dialog so the
    // user reads it before clicking, not after.
    function _miniBlockHtml(d, t) {
      const mini = d && d.ministral && d.ministral.tag ? d.ministral : null;
      if (!mini) return "";
      // The artifact + mechanism are filled in by _paintDefaultModel from
      // /api/llm/default-model, which resolves WHICH backend will actually serve.
      // Rendered as a placeholder first so the block exists even if that call fails,
      // rather than silently vanishing.
      return `<h3 style="margin:14px 0 4px">${esc(t("Default model"))}</h3>` +
        `<div id="llm-default-model"><p class="muted">${esc(t("Checking which backend will be used…"))}</p></div>`;
    }

    // Paint the default-model block from the SERVER's plan. The two backends download
    // differently -- Ollama pulls an image with real byte progress, vLLM fetches the
    // weights when its server starts -- so the button says which one it is about to do
    // instead of implying a single uniform "download".
    let _dlModelPoll = null;
    async function _paintDefaultModel() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("llm-default-model");
      if (!host) return;
      let p = null;
      try { p = await api("/api/llm/default-model"); }
      catch (e) {
        host.innerHTML = `<p class="muted">${esc(t("Could not determine the default model:"))} ${esc(e.message || e)}</p>`;
        return;
      }
      const already = p.installed === true;
      // A PICKER OVER WHAT IS ACTUALLY DOWNLOADED (maintainer 2026-08-09: "replace the
      // bla bla about default model with a drop down menu with only the readily
      // downloaded models"). The list comes from the CATALOGUE, not from
      // /api/llm/models: the catalogue resolves `installed` per model against the
      // backend that will actually serve, so on a vLLM machine it answers about the
      // weight cache rather than about a stopped Ollama daemon.
      //
      // The prose that used to fill this block (the resolver's reason and its
      // mechanism note) has not been deleted -- it moved into the picker's hover,
      // which is where the layering convention puts a long explanation.
      let picker = "";
      try {
        const c = await api("/api/llm/models/catalog");
        const have = (c.models || []).filter((m) => m.available && m.installed === true);
        if (have.length) {
          const cur = c.active || p.artifact;
          const opts = have.map((m) =>
            `<option value="${esc(m.artifact)}"${m.artifact === cur ? " selected" : ""}>` +
            `${esc(m.label)}${m.is_default ? " — " + esc(t("default")) : ""}</option>`).join("");
          picker =
            `<div class="row" style="gap:8px;align-items:center">` +
            `<label for="llm-model-pick" style="flex:0 0 auto;margin:0">${esc(t("Model in use"))}</label>` +
            `<select id="llm-model-pick" style="flex:1;max-width:420px"` +
            ` title="${esc((p.reason || "") + " " + (p.mechanism_note || ""))}"` +
            ` onchange="setActiveModel(this.value)">${opts}</select>` +
            `<span class="pill">${esc(p.backend)}</span></div>`;
        }
      } catch (e) { /* fall through to the download line below */ }

      const lines = [];
      if (picker) {
        lines.push(picker);
      } else {
        // Nothing downloaded yet, so there is nothing to choose BETWEEN -- the only
        // useful control is the one that gets you a first model.
        lines.push(
          `<p><code>${esc(p.artifact)}</code> <span class="muted">${esc(p.size || "")}</span>` +
          ` <span class="pill">${esc(p.backend)}</span>` +
          (already
            ? ` <span class="pill ok">${esc(t("Downloaded"))}</span>`
            : ` <button onclick="installDefaultModel(this)">${esc(t("Download the default model"))}</button>`) +
          `</p>`,
          `<p class="hint">${esc(p.reason || "")}</p>`);
        if (p.installed === null && !already) {
          lines.push(`<p class="hint">${esc(t("Whether it is already present here could not be read — downloading again is harmless."))}</p>`);
        }
      }
      // A live line while the vLLM weights come down. The pull queue already has its
      // own live surface for the Ollama half, so this only fills the gap that existed
      // for vLLM -- where "download" used to mean "the server will fetch it later".
      if (p.backend === "vllm" && !already) {
        try {
          const st = await api("/api/llm/default-model/status");
          const j = (st && st.job) || {};
          if (j.running) {
            lines.push(`<p class="hint">${esc(t("Downloading…"))} ${esc((j.progress && j.progress.detail) || "")}</p>`);
            clearTimeout(_dlModelPoll);
            _dlModelPoll = setTimeout(_paintDefaultModel, 3000);
          } else if (j.error) {
            lines.push(`<p class="card-caveat">${esc(t("Download failed:"))} ${esc(j.error)}</p>`);
          }
        } catch (e) { /* the block still renders without the live line */ }
      }
      lines.push(`<p class="card-caveat">${esc(t("Licence:"))} ${esc(p.license || "")}. ${esc((p.caveats || []).join(" "))}</p>`);
      host.innerHTML = lines.join("");
    }

    // ONE button for both backends. The server decides which artifact and how; this
    // only reports what it did, including the case where "download" means "the vLLM
    // server is now starting and fetching weights" rather than a queued pull.
    function installDefaultModel(btn) { return _installDefaultModel(btn, {}); }

    // `opts.confirmed` is set ONLY by the fused setup chain, which already took a
    // single consent naming this exact artifact and its size. Without it the
    // operator would be asked twice for the same bytes -- and a consent asked
    // twice teaches people to click through it.
    async function _installDefaultModel(btn, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let p = null;
      try { p = await api("/api/llm/default-model"); }
      catch (e) { toast(t("Could not determine the default model:") + " " + (e.message || e), "err"); return; }
      // Consent BEFORE the bytes: this is multi-gigabyte clearnet traffic (the model
      // registry / Hugging Face), and it does NOT go through Tor. Stated with the real
      // artifact and size rather than a generic "download?".
      const ok = (opts && opts.confirmed) || confirm(
        t("Download the default model?") + "\n\n" +
        p.artifact + "  (" + (p.size || "?") + ", " + p.backend + ")\n\n" +
        t("This downloads over the clearnet — not through Tor.") + "\n" +
        (p.mechanism_note || "") + "\n\n" +
        (p.caveats || []).join("\n")
      );
      if (!ok) return;
      // Allow the install online WITHOUT starting the collector. A no-op when the
      // app is already online or the setup chain already opened the window, so
      // this never becomes a second ask for the same bytes.
      if (!await ensureAiEgress(t("Download the default model (several GB over the clear internet)"))) return;
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = t("Starting…"); }
      try {
        const r = await api("/api/llm/default-model/install", {method: "POST"});
        toast(r.action === "queued"
          ? t("Queued — it becomes the active model once downloaded.")
          : t("Downloading the weights. This takes a while the first time."));
        if (typeof _llmPullRefresh === "function") _llmPullRefresh();
        _aiPillSettle();
        _paintDefaultModel();
      } catch (e) {
        toast(t("Download failed:") + " " + (e.message || e), "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was; }
      }
    }

    async function loadLlmModels() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("llm-models-box");
      if (!box) return;
      let d;
      try { d = await api("/api/llm/models"); }
      catch (e) { box.innerHTML = `<p class="muted">${esc(t("Model info unavailable:"))} ${esc(e.message)}</p>`; return; }
      if (!d.available) {
        // Ollama is not answering. This used to return HERE, which hid the Launch
        // control and the one-click model install in the EXACT state where they are
        // the only useful things on the panel (field report 2026-07-30: "I don't see
        // a download the default model"). The installed-models table genuinely cannot
        // be shown -- that truth comes from Ollama -- but the two ACTIONS can, so they
        // are rendered here instead of behind a state the user is trying to leave.
        // The in-panel "Start the local AI" button is GONE (maintainer review
        // 2026-07-31): the top-bar AI pill is the one start control, reachable
        // from every screen, and a second button beside it made two controls for
        // one action. Nothing is lost -- the sentence now POINTS AT the control
        // instead of duplicating it, which is also the only way a reader learns
        // the pill is clickable at all.
        box.innerHTML = `<p class="muted">${esc(t("Ollama isn't running. Click the AI pill in the top bar to start it; your installed models appear here once it answers."))}</p>`
          + _miniBlockHtml(d, t);
        _paintDefaultModel();
        return;
      }
      const ram = d.total_ram_gb ? `${d.total_ram_gb} GB RAM detected` : t("RAM unknown");
      const active = d.active || d.default;   // the stored UI choice (Q10), else the default
      const installed = (d.installed || []).length
        ? `<table><tr><th>${esc(t("Installed model"))}</th><th>${esc(t("Size"))}</th><th>${esc(t("Updated"))}</th><th></th></tr>` +
          d.installed.map(m => {
            const isActive = m.tag === active;
            const badge = isActive ? ` <span class="pill ok">${esc(t("active"))}</span>` : "";
            const setBtn = isActive ? "" : `<button class="tiny secondary" onclick="setActiveModel(${esc(JSON.stringify(m.tag))})">${esc(t("Set active"))}</button> `;
            return `<tr><td><code>${esc(m.tag)}</code>${badge}</td>` +
              `<td>${m.size_gb != null ? m.size_gb + " GB" : ""}</td><td>${esc((m.modified || "").slice(0,10))}</td>` +
              `<td style="white-space:nowrap">${setBtn}<button class="tiny danger" onclick="removeModel(${esc(JSON.stringify(m.tag))})">${esc(t("Remove"))}</button></td></tr>`;
          }).join("") + "</table>"
        : `<p class="muted">${esc(t("No models installed yet — pull one below."))}</p>`;
      // THE "SUGGESTED MODELS" TABLE IS GONE (maintainer, 2026-08-04: "remove the
      // list of suggested models"). It was Ollama-only, hardware-annotated and dated
      // separately from the thing that replaced it -- the dual-backend catalogue
      // below (#llm-catalog-box), which resolves each model to the build the ACTIVE
      // backend can use and says which backends have one at all. Two lists of models
      // on one panel, disagreeing about which backend they meant, was most of what
      // made this tab hard to read.
      //
      // The one-click Ministral block goes with it: the catalogue marks the same
      // model as the default, in the same list, with the same download button.
      //
      // What stays here is the half that only Ollama can answer: what is ACTUALLY
      // installed right now, with set-active and remove.
      box.innerHTML = `<p class="muted">${esc(ram)}.</p>` + installed;
      _paintDefaultModel();
    }
    async function setActiveModel(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        await api("/api/settings", {method: "PUT", body: JSON.stringify({llm_model: tag})});
        toast(t("Active model set:") + " " + tag); loadLlmModels();
      } catch (e) { toast(t("Could not set the active model:") + " " + e.message, "err"); }
    }
    async function removeModel(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Remove this model and free its disk space?") + "\n" + tag)) return;
      try {
        await api("/api/llm/remove", {method: "POST", body: JSON.stringify({model: tag})});
        toast(t("Removed") + " " + tag); loadLlmModels();
      } catch (e) { toast(t("Remove failed:") + " " + e.message, "err"); }
    }
    function pullModelFromBox() {
      const el = $("llm-pull-tag"); if (!el) return;
      const tag = el.value.trim();
      if (tag) pullModel(tag);
    }
    // WHICH BACKEND'S ARTIFACT the operator is being asked for. The two are not
    // interchangeable -- an Ollama image and a Hugging Face repo -- so an example and a
    // link for the wrong one is worse than none: it reads as an instruction and ends in
    // a 404. Read from the server's own provisioning answer (what this machine will
    // serve with), never guessed from the shape of what they type.
    //
    // THE EXAMPLE IS NOT TYPED HERE. It comes from /default-model's own `artifact`,
    // which resolves through the dated MINISTRAL_AS_OF block — the same source the
    // registry's freshness check governs. A literal here would be a second copy of a
    // string the registry owns, and it is the copy an operator reads at the exact
    // moment they are pasting: an example that has drifted teaches the wrong string.
    const _CUSTOM_MODEL_HELP = {
      ollama: {
        label: "Ollama model tag",
        linkText: "ollama.com/library",
        href: "https://ollama.com/library",
        lead: "Your backend is Ollama, so it downloads images from the Ollama library. Browse them at",
        form: "Copy the tag exactly as the model page shows it, including the part after the colon — that part is the quantisation, and leaving it off gets you whichever build the library currently points at.",
      },
      vllm: {
        label: "Hugging Face repo id",
        linkText: "huggingface.co/models",
        href: "https://huggingface.co/models",
        lead: "Your backend is vLLM, so it downloads weights from Hugging Face. Browse them at",
        form: "Copy the repo id from the top of the model page — the owner/name pair, not the full URL. A gated repo will refuse the download until you have accepted its terms on Hugging Face.",
      },
    };

    async function loadCustomModelBox() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const intro = $("custom-model-intro");
      const label = $("custom-model-label");
      const input = $("llm-pull-tag");
      if (!intro && !label && !input) return;
      let backend = null, example = "";
      try {
        const d = await api("/api/llm/default-model");
        backend = d && d.backend;
        // The shipped model's identifier FOR THIS BACKEND, from the dated source.
        // Empty rather than invented if the server did not say: no placeholder at all
        // beats one that might be for the other backend.
        example = (d && d.artifact) || "";
      } catch (e) { backend = null; }
      const h = _CUSTOM_MODEL_HELP[backend];
      if (!h) {
        // No backend answer is its own state: filling in one backend's example on a
        // guess is how an operator ends up typing an Ollama tag into a vLLM field.
        if (intro) intro.textContent = t("Set up the local AI first — until a backend is chosen, there is no telling which kind of model name to ask you for.");
        if (label) label.textContent = t("Model name");
        if (input) input.placeholder = "";
        return;
      }
      if (label) label.textContent = t(h.label);
      if (input) input.placeholder = example;
      if (intro) {
        intro.innerHTML =
          esc(t(h.lead)) + ' <a href="' + esc(h.href) + '" target="_blank" rel="noopener">' +
          esc(h.linkText) + " \u2197</a>. " + esc(t(h.form));
      }
    }

    // Pull a model: a NETWORK action over CLEARNET via the backend's own downloader
    // (NOT this app's Tor proxy), so it passes the ONE consent popup (ensureAiEgress,
    // invariant #14) and is refused under airplane mode (the backend enforces the kill
    // switch too). §2.C1: pulls are QUEUED (one at a time) + visible in the task
    // manager — clicking Download enqueues + gives instant feedback, never a frozen
    // button.
    //
    // ROUTED THROUGH /models/pull-custom rather than the Ollama pull queue directly:
    // that queue only speaks Ollama, so this field was dead on a GPU machine — which is
    // the machine class most likely to want a model of its own.
    let _llmPullPoll = null;
    async function pullModel(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!tag) return;
      if (!await ensureAiEgress(t("Download a model you named (over the clear internet)"))) return;
      const prog = $("llm-pull-progress");
      if (prog) prog.textContent = t("Queued") + " " + tag + "…";  // instant feedback
      try {
        const r = await api("/api/llm/models/pull-custom",
          {method: "POST", body: JSON.stringify({identifier: tag})});
        // A REFUSAL IS AN ANSWER, not a silent no-op: the shape guard can tell an
        // operator they have pasted an Ollama tag into a vLLM field, and that sentence
        // is the whole value of the check.
        const refused = (r && r.refused) || [];
        if (refused.length) {
          if (prog) prog.textContent = refused.map((x) => x.reason || t("refused")).join(" ");
          return;
        }
        const el = $("llm-pull-tag"); if (el) el.value = "";
        if (r && r.backend === "vllm") {
          // vLLM downloads through its own job, not the Ollama pull queue, so the
          // Ollama poller would sit on an empty queue and report nothing happening.
          await _followJob("/api/llm/models/install/status?backend=vllm",
            (m) => { if (prog) prog.textContent = m; });
          loadLlmModels();
        } else {
          _llmPullStartPoll();
        }
      } catch (e) { if (prog) prog.textContent = t("Download failed:") + " " + e.message; }
    }
    async function cancelPull(model) {
      try { await api("/api/llm/pull/cancel", {method: "POST", body: JSON.stringify({model})}); _llmPullRefresh(); }
      catch (e) { toast(e.message, "err"); }
    }
    function _llmPullStartPoll() {
      if (_llmPullPoll) clearInterval(_llmPullPoll);
      _llmPullRefresh();
      _llmPullPoll = setInterval(_llmPullRefresh, 1500);
    }
    async function _llmPullRefresh() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("llm-downloads"); if (!box) return;
      let s;
      try { s = await api("/api/llm/pull/status"); } catch (e) { return; }
      const active = s.active, queue = s.queue || [];
      if (!active && !queue.length) {
        box.style.display = "none"; box.innerHTML = "";
        if (_llmPullPoll) { clearInterval(_llmPullPoll); _llmPullPoll = null; loadLlmModels(); }  // a finished pull now shows as installed
        return;
      }
      let html = `<h3 style="margin:0 0 6px">${esc(t("Downloads"))}</h3>`;
      if (active) {
        const pct = active.percent || 0;
        html += `<div class="row" style="align-items:center;gap:8px;margin-bottom:4px">` +
          `<code>${esc(active.model)}</code> <span class="pill">${esc(t("Pulling"))}</span> ` +
          `<span class="muted">${esc(active.status || "")} ${pct}%</span>` +
          `<button class="tiny danger" onclick="cancelPull(${esc(JSON.stringify(active.model))})">${esc(t("Cancel"))}</button></div>` +
          `<progress value="${pct}" max="100" style="width:100%"></progress>`;
      }
      for (const m of queue) {
        html += `<div class="row" style="align-items:center;gap:8px;margin-top:4px">` +
          `<code>${esc(m)}</code> <span class="pill muted">${esc(t("Queued"))}</span>` +
          `<button class="tiny secondary" onclick="cancelPull(${esc(JSON.stringify(m))})">${esc(t("Cancel"))}</button></div>`;
      }
      box.innerHTML = html; box.style.display = "";
    }

    // --- LLM behaviour & prompts (Settings → Models) --------------------------- //
    // The editable system prompts + keep-alive. Each box is PRE-FILLED with the
    // effective prompt — the saved override if any, else the built-in default — and
    // auto-sized to show the whole thing, so the operator edits the real text
    // (maintainer ask 2026-06-18). Saving a box whose text still equals the default
    // stores "" (= use the default), so provenance stays "default" vs "custom" honest;
    // the exact prompt used is recorded with every result. Saved via PUT /api/settings.
    let _llmPromptDefaults = {summary: "", translate: "", synthesis: ""};
    function _autoGrowPrompt(ta) {
      if (!ta) return;
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight + 4, 640) + "px";  // fit content; cap so one box can't dominate
    }
    async function loadLlmPrompts() {
      if (!$("llm-keep-alive")) return;
      let d;
      // Ruling 14 (2026-07-31): ask for THIS language's built-in bodies, so the
      // editor's placeholders are the prompts that actually run rather than the
      // English ones a non-English operator would never see used.
      try { d = await api("/api/llm/prompts?lang=" + encodeURIComponent(_uiLangCode())); }
      catch (e) { return; }   // optional surface; the models box already reports Ollama state
      $("llm-keep-alive").value = d.keep_alive || "";
      $("llm-keep-alive").placeholder = d.keep_alive_default || "30m";
      const P = d.prompts || {};
      _llmPromptDefaults = {
        summary: (P.summary && P.summary.default) || "",
        translate: (P.translate && P.translate.default) || "",
        synthesis: (P.synthesis && P.synthesis.default) || "",
        ai_keywords: (P.ai_keywords && P.ai_keywords.default) || "",
      };
      for (const k of ["summary", "translate", "synthesis", "ai_keywords"]) {
        const ta = $("llm-prompt-" + k); if (!ta) continue;
        // Pre-fill with the effective prompt (override if set, else the default).
        ta.value = (P[k] && P[k].current) || _llmPromptDefaults[k];
        ta.placeholder = _llmPromptDefaults[k];          // the default, shown if cleared
        if (!ta._ooGrow) { ta.addEventListener("input", () => _autoGrowPrompt(ta)); ta._ooGrow = true; }
        _autoGrowPrompt(ta);                             // size to show the whole prompt
      }
    }
    function resetLlmPrompt(k) {
      // Restore the built-in default TEXT in the box (visible + editable). Saving a box
      // whose text equals the default stores "" (override cleared), so provenance stays
      // "default" — we never bake the default in as a fake "custom".
      const ta = $("llm-prompt-" + k); if (!ta) return;
      ta.value = _llmPromptDefaults[k] || "";
      _autoGrowPrompt(ta);
    }
    function copyLlmPrompt(k, btn) {
      const ta = $("llm-prompt-" + k); if (!ta) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const done = () => {
        if (!btn) return;
        const o = btn.textContent; btn.textContent = t("Copied");
        setTimeout(() => { btn.textContent = o; }, 1200);
      };
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(ta.value).then(done, () => { ta.select(); done(); });
        } else { ta.select(); if (document.execCommand) document.execCommand("copy"); done(); }
      } catch (e) { ta.select(); }
    }
    async function saveLlmBehaviour(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("llm-behaviour-status");
      // Send "" when the box still equals the default (override cleared → use the
      // default), else the operator's exact text — keeps provenance default-vs-custom honest.
      const _promptOut = (k) => {
        const ta = $("llm-prompt-" + k); const v = ta ? ta.value : "";
        return v.trim() && v.trim() !== (_llmPromptDefaults[k] || "").trim() ? v : "";
      };
      const body = {
        llm_keep_alive: ($("llm-keep-alive").value || "").trim() || "30m",
        llm_prompt_summary: _promptOut("summary"),
        llm_prompt_translate: _promptOut("translate"),
        llm_prompt_synthesis: _promptOut("synthesis"),
        llm_prompt_ai_keywords: _promptOut("ai_keywords"),
      };
      if (btn) btn.disabled = true;
      try {
        await api("/api/settings", {method: "PUT", body: JSON.stringify(body)});
        if (status) status.textContent = t("Saved.");
        loadLlmPrompts();
      } catch (e) {
        if (status) status.innerHTML = `<span class="note err">${esc(e.message)}</span>`;
      } finally { if (btn) btn.disabled = false; }
    }

    // --- B15: OPT-IN local-LLM language detection for articles STILL unknown after the
    // offline detector. Writes a THIRD "AI-derived · unreliable" language class (ai_keyword
    // kind="language") — NEVER Article.language / detected_language. A cancellable background
    // job (also visible in the task manager) that (per the 2026-07-24 field-feedback ruling)
    // AUTO-STARTS itself in the background whenever there is work to do, so this panel's ONE
    // button just toggles "start" <-> "stop" and reflects whatever is already happening. ---- //
    let _langDetectPolling = false;
    function _paintLangDetectButton(running) {
      const btn = $("langdetect-btn");
      if (!btn) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      btn.textContent = running ? t("Language detection ongoing — click to stop") : t("Detect languages");
      btn.dataset.running = running ? "1" : "";
    }
    async function pollLangDetect() {
      if (_langDetectPolling) return;
      _langDetectPolling = true;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("langdetect-status");
      let fails = 0;
      try {
        for (;;) {
          let s;
          // JOB-STATE-AS-TRUTH: a dropped status poll never reads as failure while the job runs.
          try { s = await api("/api/ai/detect-language/status"); fails = 0; }
          catch (_e) {
            if (++fails > 30) { if (el) el.textContent = t("Lost contact with the job — see the task manager."); break; }
            if (el) el.textContent = t("Connection hiccup — retrying…");
            await new Promise((r) => setTimeout(r, Math.min(2000 * fails, 8000))); continue;
          }
          const st = s.state, p = s.progress || {}, res = s.result || {};
          if (st === "running") {
            _paintLangDetectButton(true);
            if (el) el.textContent = `${p.done || 0}/${p.total || 0}` + (s.detail ? ` · ${esc(s.detail)}` : "");
            await new Promise((r) => setTimeout(r, 2000)); continue;
          }
          _paintLangDetectButton(false);
          if (st === "done") {
            if (res.ran === false) el.textContent = t("The local model is unavailable (Ollama down or airplane mode).");
            else el.textContent = `${t("Done.")} ${res.stored || 0} ${t("labelled")} · ${res.none || 0} ${t("unclear")} · ${res.total || 0} ${t("scanned")}`;
          } else if (st === "cancelled") el.textContent = t("Cancelled.");
          else if (st === "error") el.textContent = t("Failed:") + " " + esc(s.error || "");
          else if (s.last_run) {
            // Idle in THIS process, but a previous process's run left an honest trace
            // (§1 item 3 — the status line must stay honest about what happened after a
            // restart, not read as blank/never-run).
            const lr = s.last_run;
            if (lr.state === "error") el.textContent = t("Last run failed:") + " " + esc(lr.error || "");
            else el.textContent = `${t("Last run:")} ${lr.stored || 0} ${t("labelled")} · ${lr.none || 0} ${t("unclear")} · ${lr.total || 0} ${t("scanned")}`;
          } else el.textContent = "";
          break;
        }
      } finally { _langDetectPolling = false; }
    }
    async function loadLangDetectCount() {
      const el = $("langdetect-status");
      if (el) {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        try {
          const d = await api("/api/ai/detect-language/candidates");
          const n = d.candidates || 0;
          // Compact, because this now sits INSIDE the "Unknown languages" checkbox
          // label rather than under its own panel heading (2026-08-04: the standalone
          // section was redundant with the background-AI checkbox). The number is the
          // useful half -- it says whether ticking the box has anything to do -- and a
          // full sentence beside a checkbox reads as clutter. Empty when there is
          // nothing to detect, rather than a reassurance nobody asked for.
          el.textContent = n ? `(${n})` : "";
          el.title = n
            ? `${n} ${t("article(s) still unknown after the offline detector.")}`
            : t("No articles are missing a language — nothing to detect.");
        } catch (e) { /* the count is a hint; leave it blank on error */ }
      }
      // Reflect reality: a job may already be running (auto-started in the background,
      // or by another tab) even though this panel was just opened.
      let s;
      try { s = await api("/api/ai/detect-language/status"); } catch (e) { return; }
      _paintLangDetectButton(s.state === "running");
      if (s.state === "running") pollLangDetect();
    }
    async function runLangDetect(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("langdetect-status");
      if (btn && btn.dataset.running === "1") {
        // Currently running -> this click means STOP.
        try { await api("/api/ai/detect-language/cancel", { method: "POST" }); }
        catch (e) { if (el) el.textContent = t("Failed:") + " " + esc(e.message || e); }
        pollLangDetect(); // in case no poll loop is live yet (e.g. a fresh tab), pick up the cancel
        return;
      }
      if (btn) btn.disabled = true;
      if (el) el.textContent = t("Starting…");
      try {
        // Always continuous now — the checkbox is gone (the job auto-retries transient
        // model outages and keeps going until the backlog is drained or cancelled).
        await api("/api/ai/detect-language", { method: "POST", body: JSON.stringify({ continuous: true }) });
        _paintLangDetectButton(true);
      } catch (e) { if (el) el.textContent = t("Failed:") + " " + esc(e.message || e); }
      if (btn) btn.disabled = false;
      pollLangDetect();
    }

    // --- Custom extractors (Settings → Models) — a managed list of user-defined AI
    // prompts (maintainer ask 2026-06-18). Each defines an output_kind (the metadata
    // type) + a prompt; results are stored as ai_keyword rows of that kind (the unified,
    // labelled "AI-derived · unreliable" store), never the trusted index. This surface
    // DEFINES/manages them (CRUD over /api/ai/prompts); running is from an analysis
    // window over a selection. -------------------------------------------------------- //
    const _ct = (s) => ((window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s);
    async function loadCustomPrompts() {
      const box = $("ai-prompts-list"); if (!box) return;
      let d;
      try { d = await api("/api/ai/prompts"); }
      catch (e) { box.textContent = ""; return; }   // optional surface
      const ps = (d && d.prompts) || [];
      if (!ps.length) { box.textContent = _ct("No custom extractors yet."); return; }
      box.innerHTML = "";
      for (const p of ps) {
        const row = document.createElement("div");
        row.className = "row";
        row.style.cssText = "gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)";
        const meta = document.createElement("div");
        meta.style.flex = "1";
        const bits = [esc(p.output_kind)];
        if (p.run_on_ingest) bits.push(_ct("auto on new articles"));
        if (!p.enabled) bits.push(_ct("disabled"));
        meta.innerHTML = `<b>${esc(p.label)}</b> <span class="hint">· ${bits.join(" · ")}</span>`;
        const edit = document.createElement("button");
        edit.className = "ghost tiny"; edit.textContent = _ct("Edit");
        edit.onclick = () => editCustomPrompt(p);
        const del = document.createElement("button");
        del.className = "ghost tiny"; del.textContent = _ct("Delete");
        del.onclick = () => deleteCustomPrompt(p.id);
        row.append(meta, edit, del);
        box.appendChild(row);
      }
    }
    function resetCustomPromptForm() {
      for (const [id, v] of [["ai-prompt-id", ""], ["ai-prompt-label", ""],
                             ["ai-prompt-kind", ""], ["ai-prompt-text", ""]]) {
        if ($(id)) $(id).value = v;
      }
      if ($("ai-prompt-oningest")) $("ai-prompt-oningest").checked = false;
      if ($("ai-prompt-enabled")) $("ai-prompt-enabled").checked = true;
      if ($("ai-prompt-form-title")) $("ai-prompt-form-title").textContent = _ct("Add a custom extractor");
      if ($("ai-prompt-status")) $("ai-prompt-status").textContent = "";
      _autoGrowPrompt($("ai-prompt-text"));
    }
    function editCustomPrompt(p) {
      $("ai-prompt-id").value = p.id;
      $("ai-prompt-label").value = p.label || "";
      $("ai-prompt-kind").value = p.output_kind || "";
      $("ai-prompt-text").value = p.prompt_text || "";
      $("ai-prompt-oningest").checked = !!p.run_on_ingest;
      $("ai-prompt-enabled").checked = !!p.enabled;
      if ($("ai-prompt-form-title")) $("ai-prompt-form-title").textContent = _ct("Edit custom extractor");
      _autoGrowPrompt($("ai-prompt-text"));
      $("ai-prompt-label").focus();
    }
    async function saveCustomPrompt(btn) {
      const st = $("ai-prompt-status");
      const id = ($("ai-prompt-id").value || "").trim();
      const body = {
        label: ($("ai-prompt-label").value || "").trim(),
        output_kind: ($("ai-prompt-kind").value || "").trim(),
        prompt_text: ($("ai-prompt-text").value || "").trim(),
        run_on_ingest: !!($("ai-prompt-oningest") && $("ai-prompt-oningest").checked),
        enabled: !($("ai-prompt-enabled")) || $("ai-prompt-enabled").checked,
      };
      if (btn) btn.disabled = true;
      try {
        await api(id ? `/api/ai/prompts/${id}` : "/api/ai/prompts",
                  {method: id ? "PUT" : "POST", body: JSON.stringify(body)});
        if (st) st.textContent = _ct("Saved.");
        resetCustomPromptForm();
        loadCustomPrompts();
      } catch (e) {
        if (st) st.innerHTML = `<span class="note err">${esc(e.message)}</span>`;
      } finally { if (btn) btn.disabled = false; }
    }
    async function deleteCustomPrompt(id) {
      try { await api(`/api/ai/prompts/${id}`, {method: "DELETE"}); loadCustomPrompts(); }
      catch (e) {
        const st = $("ai-prompt-status");
        if (st) st.innerHTML = `<span class="note err">${esc(e.message)}</span>`;
      }
    }

    async function loadSettings() {
      try {
        const s = await api("/api/settings");
        $("set-limit").value = s.default_result_limit;
        DEFAULT_LIMIT = s.default_result_limit;
        // The local "Customize" theme is authoritative; on first ever run, seed it
        // from the server preference so existing users keep their dark/light choice.
        if (!localStorage.getItem(UI_KEY)) {
          setTheme({dark:"ink", light:"light", system:"system"}[s.theme] || "ink");
        }
        syncThemeSelect();
        _syncRerunGuide();   // reflect the local one-time guide state in the toggle
      } catch (e) { toast("Could not load settings: " + e.message, "err"); }
      // LLM models load lazily when the dedicated Models subtab opens (showSetCat).
      // Backup support is backend-dependent; reflect reality, never assume.
      try {
        const st = await api("/api/database/stats");
        $("vacuum-reclaim").textContent =
          (st.reclaimable_bytes == null) ? "—" : _fmtBytes(st.reclaimable_bytes);
        _dbFileBytes = (st.file && st.file.bytes != null) ? st.file.bytes : null;
      } catch (e) { /* the reclaim readout stays at its placeholder — no panel to report into */ }
      loadDumpLanguages();
      loadWikiDumps();
      loadFetchMode();
    }

    // -- Wikipedia offline baselines (lives in Settings) -------------------- //
    const _TIER_LABEL = {huge: "very large", large: "large", medium: "medium", small: "smaller"};
    let _wikiLangsFlat = [];   // flat [{code,name,autonym,tier}], cached (invariant #1: no continent groups)
    // NOTE: named loadDumpLanguages — a second loadWikiLanguages (the Wikipedia
    // tab's edition picker) is declared later and would override this one (the
    // exact bug behind "the download page can't show the languages").
    async function loadDumpLanguages() {
      const sel = $("dump-lang");
      if (!sel) return;
      try {
        const d = await api("/api/wiki/languages?scope=dumps");
        _wikiLangsFlat = d.languages || [];   // flat, UI-locales first (invariant #1)
        renderWikiLanguages();
        // The inline size estimates are bundled + DATED (no network probe). Show
        // the review date beside the picker so the estimate is honestly caveated.
        const asof = d.size_estimate_as_of;
        const note = $("dump-size-note"), asofEl = $("dump-size-asof");
        if (note && asof) { if (asofEl) asofEl.textContent = asof; note.hidden = false; }
      } catch (e) { /* picker is optional; leave the default option */ }
    }

    // Render the editions <select> as ONE flat list (invariant #1, amended
    // 2026-06-16: no continent optgroups — editions are language-based), filtered
    // by the type-to-filter box (matches name, autonym or code). The label leads
    // with the native name (autonym), the identifier per invariant #15. Keeps the
    // selection if it survives the filter; otherwise selects the first visible edition.
    function renderWikiLanguages() {
      const sel = $("dump-lang");
      if (!sel || !_wikiLangsFlat.length) return;
      const q = ($("dump-lang-filter")?.value || "").trim().toLowerCase();
      const cur = sel.value;
      const match = l => !q
        || l.code.toLowerCase().includes(q)
        || (l.name || "").toLowerCase().includes(q)
        || (l.autonym || "").toLowerCase().includes(q);
      const langs = _wikiLangsFlat.filter(match);
      const opt = l => {
        // Inline, instant size estimate (bundled + dated; never a network probe).
        // "~" + the dated caveat beside the picker keep it honestly an estimate.
        const sz = l.size_estimate_bytes ? ` · ~${_fmtBytes(l.size_estimate_bytes)}` : "";
        return `<option value="${esc(l.code)}">${esc(l.autonym)} — ${esc(l.name)} (${esc(l.code)}, ${esc(_TIER_LABEL[l.tier]||l.tier)})${sz}</option>`;
      };
      sel.innerHTML = langs.length
        ? langs.map(opt).join("")
        : `<option value="" disabled>No edition matches “${esc(q)}”</option>`;
      // Restore prior selection if still visible; else fall back to the first option.
      if (cur && langs.some(l => l.code === cur)) sel.value = cur;
    }

    async function loadKeywordFilter() {
      try {
        const f = await api("/api/insights/filter");
        $("kf-minlen").value = f.min_length;
        $("kf-numeric").checked = !!f.drop_numeric;
        $("kf-builtin").checked = !!f.use_builtin_stopwords;
        $("kf-excluded").value = (f.excluded || []).join("\n");
      } catch (e) { /* leave defaults */ }
      loadBuiltinStoplist();  // populate the read-only built-in-stoplist count + view
    }

    // Show the built-in multilingual stoplist that does the bulk of the filtering
    // (read-only — it is curated + language-scoped; the toggle above turns it on/off).
    // Bounded + searchable so we never dump ~2,500 words at once.
    async function loadBuiltinStoplist() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const qEl = $("kf-builtin-q"), listEl = $("kf-builtin-list"), cEl = $("kf-builtin-count");
      if (!listEl) return;
      const q = (qEl && qEl.value || "").trim();
      try {
        const r = await api("/api/insights/filter/builtin?limit=500&q=" + encodeURIComponent(q));
        if (cEl) cEl.textContent = (r.total || 0).toLocaleString();
        const chips = (r.terms || []).map(w => `<span class="fam-chip" style="cursor:default">${esc(w)}</span>`).join("");
        const capNote = r.capped ? `<div class="muted" style="width:100%">${r.matched.toLocaleString()} ${esc(t("matches"))} — ${esc(t("showing the first"))} ${(r.terms || []).length}. ${esc(t("Refine your search."))}</div>` : "";
        const empty = !r.terms || !r.terms.length;
        listEl.innerHTML = empty
          ? `<span class="muted">${esc(q ? t("No built-in stopword matches that.") : t("No built-in stoplist."))}</span>`
          : capNote + chips;
      } catch (e) { listEl.innerHTML = `<span class="muted">${esc(t("Could not load the stoplist."))}</span>`; }
    }

    async function saveKeywordFilter() {
      const body = {
        excluded: $("kf-excluded").value,
        min_length: Number($("kf-minlen").value),
        drop_numeric: $("kf-numeric").checked,
        use_builtin_stopwords: $("kf-builtin").checked,
      };
      try {
        const f = await api("/api/insights/filter", {method: "PUT", body: JSON.stringify(body)});
        $("kf-excluded").value = (f.excluded || []).join("\n");
        $("kf-result").innerHTML = `<span class="pill ok">saved</span> ${f.excluded.length} excluded term(s), min length ${f.min_length}.`;
        toast("Keyword filter saved.");
      } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }

    // -- Settings -> Cards: every Lead producer, by family (PR-7, rulings 1/2/3). --
    //    Reads the catalog endpoint, which carries each tunable's SAFE RANGE, the
    //    plain-language impact of moving it, and -- where a bound exists to stop an
    //    underpowered claim -- the reason for that bound. Nothing here ranks or
    //    scores a producer; these are the thresholds each already applied.
    let _cardCat = null;
    async function loadCardCatalog() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = $("cards-host"); if (!host) return;
      try { _cardCat = await api("/api/settings/cards"); }
      catch (e) {
        host.innerHTML = `<div class="muted">${esc(t("Could not load the Leads catalogue."))}</div>`;
        return;
      }
      renderCardCatalog();
    }
    function _cardTunableRow(prod, tn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const step = tn.kind === "float" ? "0.01" : "1";
      const changed = Number(tn.value) !== Number(tn.default);
      // The range is SHOWN, not just enforced: an operator should be able to read
      // the bounds without discovering them by being corrected.
      const range = `${tn.lo}–${tn.hi}${tn.unit ? " " + esc(tn.unit) : ""}`;
      return `<div class="card-tune" data-prod="${esc(prod)}" data-key="${esc(tn.key)}">
        <label class="sl" for="ct-${esc(prod)}-${esc(tn.key)}">${esc(tn.label)}</label>
        <input id="ct-${esc(prod)}-${esc(tn.key)}" type="number" class="card-tune-in"
               value="${esc(String(tn.value))}" min="${esc(String(tn.lo))}" max="${esc(String(tn.hi))}"
               step="${step}" data-default="${esc(String(tn.default))}">
        <span class="muted card-tune-range">${esc(t("safe range"))} ${range}</span>
        <button class="ghost tiny card-tune-reset" ${changed ? "" : "disabled"}
                onclick="cardResetTunable('${esc(prod)}','${esc(tn.key)}')"
                title="${esc(t("Put this back to the value the app ships with."))}">${esc(t("Reset"))}</button>
        <div class="hint card-tune-impact">${esc(tn.impact)}${
          tn.floor_reason ? ` <span class="card-tune-floor">${esc(tn.floor_reason)}</span>` : ""}</div>
      </div>`;
    }
    function renderCardCatalog() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = $("cards-host"); if (!host || !_cardCat) return;
      host.innerHTML = (_cardCat.families || []).map(fam => {
        const on = fam.producers.filter(p => p.enabled).length;
        return `<details class="card-fam" data-fam="${esc(fam.family)}">
          <summary><span class="card-fam-t">${esc(fam.label)}</span>
            <span class="muted">— ${on}/${fam.producers.length} ${esc(t("on"))}</span></summary>
          ${fam.producers.map(p => `<div class="card-prod" data-prod="${esc(p.name)}">
            <label class="switch">
              <input type="checkbox" class="card-on" value="${esc(p.name)}" ${p.enabled ? "checked" : ""}
                     onchange="cardSetEnabled(this)"> <b>${esc(p.label)}</b></label>
            <div class="hint card-prod-d">${esc(p.description)}</div>
            ${p.tunables.length ? p.tunables.map(tn => _cardTunableRow(p.name, tn)).join("") : ""}
          </div>`).join("")}
        </details>`;
      }).join("") + `<div class="row" style="margin-top:10px;gap:8px">
        <button onclick="saveCardSettings()">${esc(t("Save Lead settings"))}</button></div>`;
    }
    function cardSetEnabled(cb) {
      const fam = cb.closest(".card-fam");
      if (!fam) return;
      // keep the family's "N/M on" counter honest as you click, before any save
      const boxes = fam.querySelectorAll(".card-on");
      const on = Array.from(boxes).filter(b => b.checked).length;
      const label = fam.querySelector("summary .muted");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (label) label.textContent = `— ${on}/${boxes.length} ${t("on")}`;
    }
    function cardResetTunable(prod, key) {
      const el = document.querySelector(`.card-tune[data-prod="${prod}"][data-key="${key}"] input`);
      if (!el) return;
      el.value = el.dataset.default;
      const btn = el.parentElement.querySelector(".card-tune-reset");
      if (btn) btn.disabled = true;
    }
    async function saveCardSettings() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const msg = $("cards-msg");
      const disabled = Array.from(document.querySelectorAll("#cards-host .card-on"))
        .filter(cb => !cb.checked).map(cb => cb.value);
      const settings = {};
      document.querySelectorAll("#cards-host .card-tune").forEach(row => {
        const input = row.querySelector("input");
        if (!input || input.value === "") return;
        (settings[row.dataset.prod] = settings[row.dataset.prod] || {})[row.dataset.key] =
          Number(input.value);
      });
      try {
        const s = await api("/api/settings", {method: "PUT", body: JSON.stringify(
          {cards_disabled: disabled, card_settings: settings})});
        // A value the backend had to pull into range is REPORTED here, never applied
        // in silence (ruling 3) -- the operator would otherwise believe a Lead runs
        // at a setting it does not have.
        const notes = s.clamped || [];
        if (notes.length) {
          msg.innerHTML = `<span class="note warn">${esc(t("Some values were adjusted to stay in their safe range:"))}</span>` +
            notes.map(n => `<div class="hint">${esc(n.producer)} · ${esc(n.key)}${
              n.given !== undefined ? ` ${esc(String(n.given))} → ${esc(String(n.used))}` : ""} — ${esc(n.reason || "")}</div>`).join("");
        } else {
          msg.innerHTML = `<span class="note ok">${esc(t("Lead settings saved."))}</span>`;
        }
        loadCardCatalog();   // re-read so the inputs show what is actually stored
      } catch (e) {
        msg.innerHTML = `<span class="note err">${esc(_failMsg("Save failed: {error}", e))}</span>`;
      }
    }

    async function saveSettings() {
      const body = {
        theme: $("set-theme").value,
        default_result_limit: Number($("set-limit").value),
        // NOT sent from here any more: Settings → Cards owns which Leads are on.
        // Reading it off checkboxes that no longer exist would post an EMPTY list
        // and silently wipe the operator's choices on every unrelated save — the
        // same lossy-overwrite shape the theme comment below guards against. The
        // backend applies only the fields it is sent (exclude_unset).
      };
      try {
        const s = await api("/api/settings", {method: "PUT", body: JSON.stringify(body)});
        DEFAULT_LIMIT = s.default_result_limit;
        // theme-select-lossy-overwrite (P1): only apply the General panel's 3-way
        // bucket if the user actually changed it HERE since it was last synced --
        // else every Save (of unrelated preferences) silently collapsed a named
        // Graphics theme (e.g. "midnight") down to its bucket's plain default.
        if ($("set-theme").value !== _lastSyncedThemeBucket) {
          setTheme({dark:"ink", light:"light", system:"system"}[$("set-theme").value] || "ink");
        }
        toast("Preferences saved.");
      } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }

    // DB-10 §1.4: a full VACUUM is unbounded synchronous work (proportional to
    // the whole file), so gate it on real size with an honest estimate — never
    // let a multi-GB corpus start a rebuild the user didn't know would take
    // minutes. Rate is the project's own measured whole-file rebuild cost
    // (~10-17 s/GB across corpus sizes) from the DB-10 §1b page-size A/B runs of
    // 2026-07-19/20. That bench was removed once it had answered its question
    // (Settings review 2026-07-31, ruling 6); the MEASUREMENT it produced is what
    // these two constants encode, and it stands on its own.
    const VACUUM_GATE_BYTES = 500 * 1000 * 1000; // 500 MB — below this, always fast
    const VACUUM_LO_S_PER_GB = 10, VACUUM_HI_S_PER_GB = 17;

    function _confirmVacuum() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_dbFileBytes == null) {
        // No cheap estimate available (e.g. non-SQLite backend) — a plain,
        // honest caveat still gates a corpus we can't size.
        return window.confirm(t("Compacting rewrites the whole database file and can take a while on a large corpus. Continue?"));
      }
      if (_dbFileBytes < VACUUM_GATE_BYTES) return true; // small enough to just run
      const gb = _dbFileBytes / 1e9;
      const lo = Math.round(gb * VACUUM_LO_S_PER_GB), hi = Math.round(gb * VACUUM_HI_S_PER_GB);
      const msg = t("Your database is about {size} — compacting typically takes roughly {lo}–{hi} seconds (measured on this project's own benchmark). It will pause writes for the duration. Continue?");
      const filled = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf(msg, {size: _fmtBytes(_dbFileBytes), lo, hi})
        : msg.replace("{size}", _fmtBytes(_dbFileBytes)).replace("{lo}", lo).replace("{hi}", hi);
      return window.confirm(filled);
    }

    async function vacuumNow() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!_confirmVacuum()) return;
      const btn = $("vacuum-btn"), out = $("vacuum-result");
      btn.disabled = true; out.textContent = t("Compacting… this can take a while on a large corpus.");
      try {
        const r = await api("/api/database/vacuum", {method: "POST"});
        const freed = (r.bytes_reclaimed == null) ? "—" : _fmtBytes(r.bytes_reclaimed);
        out.textContent = t("Compacted.") + " " + t("Space freed:") + " " + freed +
          " · " + ((r.duration_ms / 1000).toFixed(1)) + " s";
        $("vacuum-reclaim").textContent = _fmtBytes(0);
      } catch (e) {
        out.textContent = t("Compaction failed:") + " " + e.message;
      } finally { btn.disabled = false; }
    }

    // Local fixity audit (B-2): re-hash the corpus vs the capture-time hash. Loud,
    // read-only; nothing is auto-fixed. Backend: /api/integrity/fixity.
    async function runFixity(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      btn.disabled = true;
      $("fixity-summary").textContent = t("Checking…");
      $("fixity-result").innerHTML = "";
      try {
        const r = await api("/api/integrity/fixity");
        const bad = (r.mismatched || 0) + (r.missing_hash || 0);
        $("fixity-summary").innerHTML =
          `<b>${(r.checked || 0).toLocaleString()}</b> ${esc(t("checked"))} · ` +
          `<span class="pill ok">${(r.ok || 0).toLocaleString()} ${esc(t("intact"))}</span>` +
          (bad ? ` · <span class="pill err">${bad.toLocaleString()} ${esc(t("diverged"))}</span>` : "");
        if (bad) {
          const rows = (r.mismatches || []).slice(0, 200).map(m =>
            `<div class="vr"><span>#${m.id} ${esc(m.title || m.url || "")}</span>` +
            `<b class="muted" title="${esc(m.reason || "")}">${esc((m.stored_hash || "—").slice(0, 12))} ≠ ${esc((m.computed_hash || "").slice(0, 12))}</b></div>`).join("");
          $("fixity-result").innerHTML =
            `<div class="note err">${esc(bad.toLocaleString())} ${esc(t("articles diverge from their capture-time hash — evidence of tampering or bit-rot. Nothing was changed."))}</div>` + rows;
        } else {
          $("fixity-result").innerHTML = `<div class="note ok">${esc(t("All articles match their capture-time hash."))}</div>`;
        }
      } catch (e) { $("fixity-summary").innerHTML = `<span class="note err">${esc(e.message)}</span>`; }
      finally { btn.disabled = false; }
    }

    // ---- Local .eml newsletter import (zero network; anonymised at ingest) ---- //
    async function importNewsletters(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const input = $("nl-files");
      if (!input || !input.files || !input.files.length) {
        toast(t("Choose one or more .eml files first."), "warn"); return;
      }
      btn.disabled = true;
      $("nl-result").textContent = t("Importing…");
      const fd = new FormData();
      for (const f of input.files) fd.append("files", f);
      try {
        // Loopback POST — the endpoint opens ZERO external sockets (local import),
        // so this works in airplane mode and never needs the network-consent gate.
        const r = await fetch("/api/newsletters/import", { method: "POST", body: fd });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json(), tl = d.tally || {};
        const n = (x) => (x || 0).toLocaleString();
        $("nl-result").innerHTML =
          `<b>${n(tl.stored)}</b> ${esc(t("imported"))} · ${n(tl.duplicate)} ${esc(t("duplicates skipped"))} · ` +
          `${n(tl.empty)} ${esc(t("empty"))}` +
          (tl.skipped_non_eml ? ` · ${n(tl.skipped_non_eml)} ${esc(t("not .eml"))}` : "") +
          `<div class="muted" style="margin-top:5px">${esc(t("Anonymisation"))}: ` +
          `${n(tl.recipient_redactions)} ${esc(t("recipient echoes redacted"))}, ` +
          `${n(tl.tracker_params_stripped)} ${esc(t("tracker tokens stripped"))}, ` +
          `${n(tl.trackers_flagged)} ${esc(t("tracker wrappers flagged"))}.</div>`;
        input.value = "";
        toast(t("Newsletters imported."), "ok");
      } catch (e) {
        $("nl-result").innerHTML = `<span class="note err">${esc(t("Import failed"))}: ${esc(e.message)}</span>`;
      } finally { btn.disabled = false; }
    }

    // -- Local PDF-document import (mirrors the .eml importer; zero network) ----- //
    function _pdfTallyHtml(tl) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const n = (x) => (x || 0).toLocaleString();
      let html = `<b>${n(tl.imported)}</b> ${esc(t("imported"))} · ${n(tl.duplicate)} ${esc(t("duplicates skipped"))} · ` +
        `${n(tl.skipped)} ${esc(t("skipped"))}`;
      if (tl.skipped_non_pdf) html += ` · ${n(tl.skipped_non_pdf)} ${esc(t("not PDF"))}`;
      // OCR-derived documents are LOWER-TRUST (a scan Tesseract read) — flag them, never hide it.
      if (tl.ocr) html += `<div class="muted" style="margin-top:5px">${n(tl.ocr)} ${esc(t("read from a scan via OCR — may contain recognition errors; the original PDF is the source of truth"))}</div>`;
      // Surface WHY files were skipped (scanned / encrypted / mis-decoded) — honest, never hidden.
      const reasons = (tl.results || []).filter((r) => r.status === "skipped" && r.reason);
      if (reasons.length) {
        html += `<div class="muted" style="margin-top:5px">` +
          reasons.slice(0, 8).map((r) => `${esc(r.filename || "")}: ${esc(r.reason)}`).join("<br>") + `</div>`;
      }
      return html;
    }
    async function importPdfs(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const input = $("pdf-files");
      if (!input || !input.files || !input.files.length) {
        toast(t("Choose one or more PDF files first."), "warn"); return;
      }
      btn.disabled = true;
      $("pdf-result").textContent = t("Importing…");
      const fd = new FormData();
      for (const f of input.files) fd.append("files", f);
      try {
        // Loopback POST — the endpoint opens ZERO external sockets (local import),
        // so this works in airplane mode and never needs the network-consent gate.
        const r = await fetch("/api/documents/pdf/upload", { method: "POST", body: fd });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        $("pdf-result").innerHTML = _pdfTallyHtml(d.tally || {});
        input.value = "";
        toast(t("PDFs imported."), "ok");
      } catch (e) {
        $("pdf-result").innerHTML = `<span class="note err">${esc(t("Import failed"))}: ${esc(e.message)}</span>`;
      } finally { btn.disabled = false; }
    }
    async function importPdfFolder(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const folder = ($("pdf-folder").value || "").trim();
      if (!folder) { toast(t("Enter a folder path on this machine."), "warn"); return; }
      btn.disabled = true;
      $("pdf-folder-result").textContent = t("Importing…");
      try {
        const d = await api("/api/documents/pdf/import-folder", { method: "POST", body: JSON.stringify({ folder }) });
        $("pdf-folder-result").innerHTML = _pdfTallyHtml(d.tally || {});
        toast(t("PDFs imported."), "ok");
      } catch (e) {
        $("pdf-folder-result").innerHTML = `<span class="note err">${esc(t("Import failed"))}: ${esc(e.message)}</span>`;
      } finally { btn.disabled = false; }
    }

    // -- Remove imported newsletters (the "replace the faulty ones" loop) ------ //
    // -- Server-side .eml FOLDER import as a pausable job (§2.B; 20 GB+ sets) ---- //
    let _nlImportPoll = null;
    async function startFolderImport(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const folder = ($("nl-folder").value || "").trim();
      if (!folder) { toast(t("Enter a folder path on this machine."), "warn"); return; }
      btn.disabled = true;
      try {
        await api("/api/newsletters/import-folder", { method: "POST", body: JSON.stringify({ folder }) });
        _folderImportStartPoll();
      } catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
    }
    async function folderImportAction(action, btn) {
      btn.disabled = true;
      try { await api("/api/newsletters/import-folder/" + action, { method: "POST" }); _folderImportRefresh(); }
      catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
    }
    function _folderImportStartPoll() {
      if (_nlImportPoll) clearInterval(_nlImportPoll);
      _folderImportRefresh();
      _nlImportPoll = setInterval(_folderImportRefresh, 1500);
    }
    async function _folderImportRefresh() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prog = $("nl-folder-progress"); if (!prog) return;
      let s;
      try { s = await api("/api/newsletters/import-folder/status"); } catch (e) { return; }
      const active = s.state === "running" || s.state === "paused";
      if (!active && _nlImportPoll) { clearInterval(_nlImportPoll); _nlImportPoll = null; }
      $("nl-folder-controls").style.display = active ? "" : "none";
      const bar = $("nl-folder-bar");
      if (bar) {
        // show the bar while a run is active OR just finished; honest determinate %
        bar.style.display = (active || s.state === "done") ? "" : "none";
        bar.value = s.percent || 0;
      }
      if ($("nl-folder-pause")) $("nl-folder-pause").style.display = s.state === "running" ? "" : "none";
      if ($("nl-folder-resume")) $("nl-folder-resume").style.display = s.state === "paused" ? "" : "none";
      const tl = s.tally || {};
      const eta = (s.eta_seconds != null) ? ` · ~${Math.max(1, Math.round(s.eta_seconds / 60))} ${t("min left")}` : "";
      if (active) {
        prog.innerHTML = `${esc(t("Importing"))}… ${s.percent || 0}% (${s.files_done}/${s.files_total}) · ` +
          `${(tl.stored || 0)} ${esc(t("imported"))}, ${(tl.duplicate || 0)} ${esc(t("duplicates skipped"))}` +
          (s.state === "paused" ? ` (${esc(t("paused"))})` : eta);
      } else if (s.state === "done") {
        prog.innerHTML = `<b>${esc(t("Done."))}</b> ${(tl.stored || 0)} ${esc(t("imported"))}, ` +
          `${(tl.duplicate || 0)} ${esc(t("duplicates skipped"))}.`;
        if (typeof loadNewsletterRemoveCount === "function") loadNewsletterRemoveCount();
      } else if (s.state === "error") {
        prog.innerHTML = `<span class="note err">${esc(s.error || t("failed"))}</span>`;
      } else { prog.textContent = ""; }
    }

    // Restore is additive-only, so excluding newsletters from a backup never purges
    // the live corpus — this action does. The panel shows only when there's something
    // to remove; removal needs an explicit confirm and nudges "back up first".
    async function loadNewsletterRemoveCount() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("nl-remove-panel"), lab = $("nl-remove-count");
      if (!panel) return;
      try {
        const d = await api("/api/newsletters/imported-count");
        const n = d.count || 0;
        panel.style.display = n > 0 ? "" : "none";
        if (lab) lab.textContent = n > 0 ? `${n.toLocaleString()} ${t("imported newsletters in your corpus")}` : "";
      } catch (e) { panel.style.display = "none"; }
    }
    function downloadBackupFirst(btn) {
      // Route to the unified Export dialog (streams to a folder as volumes + parity —
      // NO size limit). The old in-browser single-file encrypted download hit AES-GCM's
      // ~2 GiB cap at real corpus size (the exact failure a 6 GB corpus hit live), so a
      // "back up first" nudge before a destructive action must use the always-works path.
      openUnifiedExport();
    }
    async function removeImportedNewsletters(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let n = 0;
      try { n = (await api("/api/newsletters/imported-count")).count || 0; } catch (e) {}
      if (!n) { toast(t("No imported newsletters to remove."), "warn"); loadNewsletterRemoveCount(); return; }
      if (!confirm(t("Remove") + ` ${n.toLocaleString()} ` +
          t("imported newsletters from your corpus? This cannot be undone except from a backup."))) return;
      btn.disabled = true;
      $("nl-remove-result").textContent = t("Removing…");
      try {
        const d = await api("/api/newsletters/remove-imported",
          {method: "POST", body: JSON.stringify({confirm: true})});
        $("nl-remove-result").innerHTML =
          `<b>${(d.removed_articles || 0).toLocaleString()}</b> ${esc(t("imported newsletters removed."))} ` +
          esc(t("Re-import the cleaned files to replace them."));
        toast(t("Imported newsletters removed."), "ok");
        loadNewsletterRemoveCount();
      } catch (e) {
        $("nl-remove-result").innerHTML = `<span class="note err">${esc(t("Removal failed"))}: ${esc(e.message)}</span>`;
      } finally { btn.disabled = false; }
    }
    // -- Pull from a mailbox (IMAP/POP3) — ruling #11. English-only; the anonymise +
    // kill-switch guarantees live in the (tested) backend.
    async function pullMailbox() {
      const out = $("mbox-result"), btn = $("mbox-btn");
      const host = ($("mbox-host").value || "").trim();
      const user = ($("mbox-user").value || "").trim();
      const password = $("mbox-pass").value || "";
      if (!host || !user) { if (out) out.textContent = "Enter at least a host and user."; return; }
      // A network action -> the ONE consent popup (invariant #14).
      if (typeof ensureOnline === "function" && !await ensureOnline("Pull newsletters from your mailbox")) return;
      const body = {
        protocol: $("mbox-proto").value, host, user, password,
        port: parseInt($("mbox-port").value || "0", 10) || 0,
        folder: ($("mbox-folder").value || "INBOX").trim(),
        limit: parseInt($("mbox-limit").value || "50", 10),
      };
      if (btn) btn.disabled = true;
      if (out) out.textContent = "Pulling…";
      try {
        const d = await api("/api/newsletters/mailbox", { method: "POST", body: JSON.stringify(body) });
        const tl = d.tally || {}, n = (x) => (x || 0).toLocaleString();
        $("mbox-pass").value = "";  // never keep the password in the field
        if (out) out.innerHTML = `<b>${n(tl.stored)}</b> imported · ${n(tl.duplicate)} duplicates skipped`
          + `<div class="muted" style="margin-top:5px">Anonymisation: ${n(tl.recipient_redactions)} recipient echoes redacted, `
          + `${n(tl.tracker_params_stripped)} tracker tokens stripped, ${n(tl.trackers_flagged)} tracker wrappers flagged.</div>`
          + (d.disclosure ? `<div class="muted" style="margin-top:4px">${esc(d.disclosure)}</div>` : "");
      } catch (e) {
        // 409 = airplane refusal, 502 = transport/auth failure.
        if (out) out.innerHTML = `<span class="note err">Pull failed: ${esc(e.message)}</span>`;
      } finally { if (btn) btn.disabled = false; }
    }

    // ---- Backup v2: one signed archive; restore = MERGE with a preview ---- //
    let _v2Token = null;
    // Local LLM models — an OPT-IN companion backup (models live outside the corpus,
    // so they are a SEPARATE artifact; restore is additive + bit-identical). PR 6.
    // -- Large data backup: stream wiki dumps + maps + models to a folder/drive --- //
    // Server-side copy (never the browser). The corpus stays in the encrypted full
    // backup; these public re-downloadable blobs are copied as-is. Pausable job.
    let _fbPoll = null;
    function _fbCats() {
      const c = [];
      if ($("fb-wiki") && $("fb-wiki").checked) c.push("wiki_dumps");
      if ($("fb-osm") && $("fb-osm").checked) c.push("osm_regions");
      if ($("fb-models") && $("fb-models").checked) { c.push("models"); c.push("hf_models"); }
      return c;
    }
    // ---- Unified Export/Backup dialog -------------------------------------- //
    // ONE entry: pick a folder, choose what to include (inventory-driven), and it
    // drives the ALWAYS-WORKS streaming engines — the encrypted corpus (volumes +
    // parity) then the large public blobs (folder stream) — into that one folder.
    // No new backend: reuses /backup/v2/volumes + /backup/folder. English-only.
