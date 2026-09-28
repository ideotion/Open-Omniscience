/* Open Omniscience — the unlock / first-launch page's script, moved out of an inline <script> in unlock.html
   so the CSP can drop script-src 'unsafe-inline' (Q1127 = a, 0.5 row I). It loads at the
   same point in the page as the inline block did, so it runs in the same order. */
  (function () {
    if (window.OOI18N && OOI18N.init) { try { OOI18N.init(); } catch (e) {} }
    const $ = (id) => document.getElementById(id);
    const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);

    async function post(path, body) {
      const r = await fetch(path, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || r.statusText);
      return data;
    }

    // First launch leads with LANGUAGE selection, not the passphrase (maintainer
    // 2026-06-20). Picking a language persists it (localStorage oo.lang, shared with
    // the app) and translates this page, THEN the create-passphrase view is shown --
    // encryption-by-default is preserved, just reordered after the language choice.
    // Native name is the identifier (invariant #15); the flag is visual convention only.
    const LANGS = [
      ["en", "\u{1F1EC}\u{1F1E7}", "English"],   ["fr", "\u{1F1EB}\u{1F1F7}", "Français"],
      ["es", "\u{1F1EA}\u{1F1F8}", "Español"],   ["de", "\u{1F1E9}\u{1F1EA}", "Deutsch"],
      ["zh", "\u{1F1E8}\u{1F1F3}", "中文"],       ["hi", "\u{1F1EE}\u{1F1F3}", "हिन्दी"],
      ["ar", "\u{1F1F8}\u{1F1E6}", "العربية"],  ["bn", "\u{1F1E7}\u{1F1E9}", "বাংলা"],
      ["ru", "\u{1F1F7}\u{1F1FA}", "Русский"],  ["pt", "\u{1F1F5}\u{1F1F9}", "Português"],
      ["id", "\u{1F1EE}\u{1F1E9}", "Bahasa Indonesia"], ["ja", "\u{1F1EF}\u{1F1F5}", "日本語"],
    ];
    function showLanguageStep() {
      const list = $("lang-list");
      list.innerHTML = "";
      for (const [code, flag, name] of LANGS) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "lang-btn"; b.setAttribute("lang", code);
        const f = document.createElement("span");
        f.className = "flag"; f.setAttribute("aria-hidden", "true"); f.textContent = flag;
        const nm = document.createElement("span"); nm.textContent = name;
        b.append(f, nm);
        b.addEventListener("click", () => pickLanguage(code));
        list.appendChild(b);
      }
      $("view-language").classList.remove("hidden");
      const first = list.querySelector("button"); if (first) first.focus();
    }
    async function pickLanguage(code) {
      try { if (window.OOI18N && OOI18N.setLang) await OOI18N.setLang(code); } catch (e) {}
      $("view-language").classList.add("hidden");
      showLegalStep(code);   // accept the legal documents BEFORE the passphrase
    }

    // ---- First-launch legal step (chrome strings come from the endpoint) ---- //
    let _legalLang = "en", _legalVersion = "", _legalWord = "UNINSTALL";
    function escHtml(s) {
      return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    }
    // Minimal, SAFE markdown -> HTML for OUR OWN trusted legal text: escape first,
    // then render headings / blockquotes / lists / bold / rules. Links become plain
    // text (no navigating away from this first-launch page).
    function renderLegalMarkdown(md) {
      const inline = (s) => escHtml(s)
        .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
      // Our legal docs are hand-wrapped at ~80 columns, so a **bold** span or a
      // list item routinely continues onto the NEXT physical source line with no
      // blank line between (markdown's normal soft-wrap). Inline formatting must
      // run on the whole JOINED logical block, never per raw physical line -- else
      // a bold span split across the wrap mismatches with a UNRELATED "**" later
      // in the text, rendering literal asterisks and wrongly-bolded text.
      let html = "", inList = false, inQuote = false;
      let quoteBuf = [], listBuf = [], paraBuf = [];
      const flushQuote = () => { if (quoteBuf.length) { html += "<div>" + inline(quoteBuf.join(" ")) + "</div>"; quoteBuf = []; } };
      const flushItem = () => { if (listBuf.length) { html += "<li>" + inline(listBuf.join(" ")) + "</li>"; listBuf = []; } };
      const flushPara = () => { if (paraBuf.length) { html += "<p>" + inline(paraBuf.join(" ")) + "</p>"; paraBuf = []; } };
      const closeList = () => { flushItem(); if (inList) { html += "</ul>"; inList = false; } };
      const closeQuote = () => { flushQuote(); if (inQuote) { html += "</blockquote>"; inQuote = false; } };
      for (const raw of md.split(/\r?\n/)) {
        const line = raw.replace(/\s+$/, "");
        if (/^#{1,6}\s/.test(line)) {
          flushPara(); closeList(); closeQuote();
          const tag = line.match(/^#+/)[0].length <= 2 ? "h2" : "h3";
          html += "<" + tag + ">" + inline(line.replace(/^#+\s*/, "")) + "</" + tag + ">";
        } else if (/^>\s?/.test(line)) {
          flushPara(); closeList();
          if (!inQuote) { html += "<blockquote>"; inQuote = true; }
          const content = line.replace(/^>\s?/, "");
          if (content.trim() === "") flushQuote(); // a paragraph break WITHIN the quote
          else quoteBuf.push(content);
        } else if (/^[-*]\s/.test(line)) {
          flushPara(); closeQuote(); flushItem();
          if (!inList) { html += "<ul>"; inList = true; }
          listBuf.push(line.replace(/^[-*]\s/, ""));
        } else if (/^(---+|\*\*\*+)$/.test(line)) {
          flushPara(); closeList(); closeQuote(); html += "<hr>";
        } else if (line.trim() === "") {
          flushPara(); closeList(); closeQuote();
        } else if (inList && listBuf.length) {
          listBuf.push(line.trim()); // lazy continuation of the current list item
        } else if (inQuote && quoteBuf.length) {
          quoteBuf.push(line.trim()); // lazy continuation of the current quoted paragraph
        } else {
          closeQuote(); closeList(); paraBuf.push(line.trim());
        }
      }
      flushPara(); closeList(); closeQuote();
      return html;
    }
    async function showLegalStep(code) {
      _legalLang = code;
      try {
        const data = await (await fetch("/api/legal/documents?lang=" + encodeURIComponent(code))).json();
        _legalVersion = data.version || "";
        _legalWord = data.confirm_word || "UNINSTALL";
        const ui = data.ui || {};
        $("lg-heading").textContent = ui.heading || "Legal documents";
        $("lg-intro").textContent = ui.intro || "";
        $("lg-draft").textContent = ui.draft_note || "";
        const trans = $("lg-trans");
        if (data.is_translation) { trans.textContent = ui.translation_note || ""; trans.classList.remove("hidden"); }
        else trans.classList.add("hidden");
        $("lg-accept-label").textContent = ui.accept_label || "I have read and accept these documents.";
        $("lg-accept").textContent = ui.accept_btn || "Accept and continue";
        $("lg-decline").textContent = ui.decline_btn || "Decline";
        $("lg-download").textContent = ui.download_btn || "Download the documents";
        $("lg-decline-warn").textContent = ui.decline_warn || "";
        $("lg-decline-type").textContent = ui.decline_type || "To confirm, type UNINSTALL:";
        $("lg-decline-confirm").textContent = ui.decline_confirm_btn || "Uninstall and delete everything";
        $("lg-decline-cancel").textContent = ui.decline_cancel_btn || "Cancel";
        const docs = (data.documents || []).map((d, i) =>
          (i ? '<div class="doc-sep"></div>' : "") + renderLegalMarkdown(d.markdown || "")).join("");
        $("lg-docs").innerHTML = docs || ("<p>" + escHtml(ui.error || "Could not load the legal documents.") + "</p>");
      } catch (e) {
        $("lg-msg").textContent = (e && e.message) || "Could not load the legal documents.";
      }
      const card = document.querySelector(".card"); if (card) card.classList.add("wide");
      $("view-legal").classList.remove("hidden");
      $("lg-docs").focus();
    }
    function legalToPassphrase() {
      const card = document.querySelector(".card"); if (card) card.classList.remove("wide");
      $("view-legal").classList.add("hidden");
      $("view-create").classList.remove("hidden");
      const pw1 = $("pw1"); if (pw1) pw1.focus();
    }
    // The data-location step sits BETWEEN the two. It is skipped -- silently and
    // deliberately -- whenever the backend says the choice is not offerable: an
    // operator who already set OO_DATA_DIR themselves, or any state but `fresh`.
    // Showing a control that cannot be honoured would be worse than not showing one.
    async function legalToDataLocation() {
      const card = document.querySelector(".card"); if (card) card.classList.remove("wide");
      $("view-legal").classList.add("hidden");
      let info = null;
      try { info = await (await fetch("/api/system/data-location")).json(); } catch (e) { info = null; }
      if (!info || !info.offerable) { legalToPassphrase(); return; }
      $("dl-default-path").textContent = info.data_dir || "";
      $("view-datadir").classList.remove("hidden");
      const c = $("dl-continue"); if (c) c.focus();
    }
    function dlToPassphrase() {
      $("view-datadir").classList.add("hidden");
      $("view-create").classList.remove("hidden");
      const pw1 = $("pw1"); if (pw1) pw1.focus();
    }
    // A chosen folder only takes effect at the NEXT start, so this process must not go
    // on to create a corpus: it would land in the OLD folder while the recorded choice
    // pointed elsewhere -- the orphaning the whole step exists to prevent. So the flow
    // ENDS here, saying what happened and what to do, with a button that stops the app.
    function dlRestartRequired(path) {
      const card = document.querySelector(".card");
      card.classList.remove("wide");
      card.innerHTML = "";
      const h = document.createElement("h1");
      h.textContent = t("Your corpus folder is set");
      const p1 = document.createElement("p");
      p1.textContent = t("Open Omniscience will use this folder the next time it starts:");
      // The path in an inline .path span (U-4): LTR inside the paragraph, while the
      // paragraph keeps the card's own alignment.
      const p2 = document.createElement("p");
      const p2path = document.createElement("span");
      p2path.className = "path"; p2path.textContent = path || "";
      p2.appendChild(p2path);
      const p3 = document.createElement("p");
      p3.textContent = t("Nothing has been created yet. Stop the app and start it again to continue setting it up.");
      const b = document.createElement("button");
      b.id = "dl-stop"; b.textContent = t("Stop the app now");
      card.appendChild(h); card.appendChild(p1); card.appendChild(p2);
      card.appendChild(p3); card.appendChild(b);
    }
    // The probe answers "could the corpus live here", and its warnings are DATA
    // (machine-readable codes + numbers) rendered here as sentences. A warning never
    // blocks: this project does not hard-block on a judgement that belongs to the
    // operator -- it says what it measured and lets them decide.
    function dlWarningText(w) {
      if (!w || !w.code) return "";
      if (w.code === "already_has_a_corpus")
        return t("This folder already holds an Open Omniscience corpus. Continuing will open it rather than create a new one.");
      if (w.code === "parent_is_already_a_corpus")
        return t("That folder looks like an existing Open Omniscience data folder. Continuing creates a new, empty corpus inside it and leaves the existing one alone.");
      if (w.code === "volatile_filesystem")
        return t("This folder is on a RAM-backed filesystem. Anything written here is lost when the machine restarts.");
      if (w.code === "low_free_space")
        return t("Little free space on this drive:") + " " + (w.free_human || "");
      return w.text || "";
    }
    function dlRefusalText(out) {
      const c = out && out.reason_code;
      if (c === "not_absolute") return t("Enter the full path to the folder, starting from the top of the filesystem.");
      if (c === "empty") return t("Enter a folder.");
      if (c === "not_writable") return t("This app cannot write in that folder.");
      if (c === "cannot_create") return t("That folder could not be created.");
      return (out && out.reason) || t("That folder cannot be used.");
    }
    async function dlProbe() {
      return await post("/api/system/data-location/check", { path: $("dl-path").value });
    }
    async function dlCheck() {
      const box = $("dl-report"), txt = $("dl-report-text");
      $("dl-msg").textContent = "";
      try {
        const out = await dlProbe();
        // Built as nodes rather than one string, so the path rides in its own LTR .path
        // span (U-4) instead of being reordered inside the Arabic sentence around it.
        txt.textContent = "";
        if (out.usable) {
          txt.appendChild(document.createTextNode(t("This folder can be used. Your corpus will live in:") + " "));
          const sp = document.createElement("span");
          sp.className = "path"; sp.textContent = out.path || "";
          txt.appendChild(sp);
        } else {
          txt.appendChild(document.createTextNode(dlRefusalText(out)));
        }
        (out.warnings || []).forEach((w) => {
          const s2 = dlWarningText(w);
          if (s2) txt.appendChild(document.createTextNode(" " + s2));
        });
        box.classList.remove("hidden");
        box.classList.toggle("danger", !out.usable);
      } catch (e) {
        txt.textContent = (e && e.message) || t("That folder cannot be used.");
        box.classList.remove("hidden"); box.classList.add("danger");
      }
    }
    async function dlContinue(btn) {
      $("dl-msg").textContent = "";
      if (!$("dl-custom").checked) { dlToPassphrase(); return; }
      btn.disabled = true;
      try {
        const out = await post("/api/system/data-location", { path: $("dl-path").value });
        dlRestartRequired(out && out.path);
      } catch (e) {
        $("dl-msg").textContent = (e && e.message) || t("That folder cannot be used.");
        btn.disabled = false;
      }
    }

    function showUninstalling(msg) {
      const card = document.querySelector(".card");
      card.classList.remove("wide");
      card.innerHTML = "<h1>Open Omniscience</h1>";
      const p = document.createElement("p");
      p.style.textAlign = "center"; p.textContent = msg;
      card.appendChild(p);
    }

    async function boot() {
      try {
        const s = await (await fetch("/api/system/lock-state")).json();
        if (s.state === "fresh") { showLanguageStep(); return; }  // first launch: language first
        const view = s.state === "locked" ? "view-unlock" : "view-open";
        $(view).classList.remove("hidden");
        if (view === "view-unlock") $("pw").focus();
      } catch (e) { $("view-unlock").classList.remove("hidden"); }
    }

    // After a successful unlock/create the server opens the corpus (init_db, run
    // synchronously in the unlock request) and then finishes best-effort upkeep
    // (search stats, catalog seed-dedup, counts, cache warm) in a BACKGROUND thread,
    // reporting progress at /api/system/startup-status. We enter the Console as soon
    // as the server says the corpus is `queryable` — NOT after the whole upkeep — so
    // unlock feels instant on a large encrypted corpus (field report: "unlocking takes
    // ages" while CPU/SSD sat idle waiting on that serial best-effort work). The app is
    // fully usable meanwhile; the upkeep finishes behind the scenes.
    // Q725 = a: the Wikipedia lane's first-run wizard is "reachable from unlock.html
    // AND #set-wikipedia". It is reachable from here by HANDING OFF rather than by
    // being duplicated: this page runs BEFORE the corpus is open, so it cannot read
    // or write a lane setting, and a second copy of the wizard living here would be
    // a second copy to keep in step with the rulings. A fresh corpus enters the app
    // at "/?wikiwizard=1" and the app opens the dialog once; an ordinary unlock
    // enters at "/" exactly as before, because an operator who has already answered
    // must not be asked again on every launch.
    async function waitReadyThenEnter(fresh) {
      const dest = fresh ? "/?wikiwizard=1" : "/";
      ["view-unlock", "view-create", "view-open"].forEach((v) => $(v).classList.add("hidden"));
      $("view-preparing").classList.remove("hidden");
      const phaseEl = $("prep-phase");
      const PHRASES = {
        "opening the database": t("opening the database"),
        "refreshing search statistics": t("refreshing search statistics"),
        "loading the source catalog": t("loading the source catalog"),
        "counting your corpus": t("counting your corpus"),
      };
      for (let i = 0; i < 3600; i++) {  // generous cap — schema self-heal on a first upgrade boot may take a moment
        let s;
        try { s = await (await fetch("/api/system/startup-status")).json(); }
        catch (e) { s = null; }
        if (s && s.phase) phaseEl.textContent = PHRASES[s.phase] || s.phase;
        // Enter as soon as the corpus is queryable (or fully ready) — the upkeep
        // keeps running in the background; nothing the app does needs it finished.
        if (s && (s.queryable || s.state === "ready")) { location.replace(dest); return; }
        await new Promise((r) => setTimeout(r, 300));
      }
      location.replace(dest);  // fail-open: enter anyway rather than trap the user
    }

    // Honest elapsed-time clock (E3 / P0.4 UI half). The unlock POST runs init_db
    // SYNCHRONOUSLY (schema self-heal + one-time migrations + index builds + WAL
    // recovery) BEFORE it returns, so on a first unlock after an upgrade the button
    // could sit pending for minutes with NO feedback (the 981 s field case was exactly
    // this, invisible). We show the preparing view + a ticking elapsed clock the MOMENT
    // the passphrase is submitted — never a fabricated percent, just real elapsed time
    // and the honest one-time-migration explanation.
    let _prepTimer = null, _prepStart = 0, _prepPriorView = null;
    function _stopPrep() { if (_prepTimer) { clearInterval(_prepTimer); _prepTimer = null; } }
    function _startPrep(priorView) {
      // Remember which view was on-screen before we hide it (inferable from which
      // button was clicked -- go() passes it), so a thrown error can re-show THAT
      // exact view instead of leaving the whole form -- and the error message
      // trapped inside it -- hidden forever (LC-VIEW-HIDDEN-ON-ERROR).
      _prepPriorView = priorView || null;
      ["view-unlock", "view-create", "view-open"].forEach((v) => $(v).classList.add("hidden"));
      $("view-preparing").classList.remove("hidden");
      _prepStart = Date.now();
      const el = $("prep-elapsed");
      _stopPrep();
      const tick = () => {
        const s = Math.max(0, Math.floor((Date.now() - _prepStart) / 1000));
        const mm = String(Math.floor(s / 60)).padStart(2, "0");
        const ss = String(s % 60).padStart(2, "0");
        if (el) el.textContent = t("Elapsed") + " " + mm + ":" + ss;
      };
      tick();
      _prepTimer = setInterval(tick, 1000);
    }

    async function go(btn, fn) {
      btn.disabled = true;
      // Show the preparing view + elapsed clock NOW, before the (possibly multi-minute)
      // synchronous init_db that runs inside fn() -- but tell _startPrep which view is
      // being hidden (btn.id says which form this is) so a failure can restore it.
      _startPrep(btn.id === "btn-unlock" ? "view-unlock" : "view-create");
      try { await fn(); await waitReadyThenEnter(btn.id === "btn-create"); }
      catch (e) {
        _stopPrep();
        const box = btn.id === "btn-unlock" ? $("msg") : $("msg2");
        // e.message is the backend's raw detail string ("passphrases do not match",
        // "use at least 8 characters") -- run it through t() so it renders in the
        // user's chosen language like every other string on this page.
        box.textContent = e.message ? t(e.message) : t("Wrong passphrase — try again.");
        btn.disabled = false;
        // A failed prepare-wait shouldn't leave the user stuck on the preparing view --
        // re-show whichever view _startPrep() hid so the form (and the now-visible
        // error inside it) reappears, instead of a blank page.
        $("view-preparing").classList.add("hidden");
        if (_prepPriorView) $(_prepPriorView).classList.remove("hidden");
      }
    }

    document.addEventListener("click", (ev) => {
      const id = ev.target.id;
      if (id === "btn-unlock")
        go(ev.target, () => post("/api/system/unlock", { passphrase: $("pw").value }));
      if (id === "btn-create")
        go(ev.target, () => post("/api/system/create-db",
          { passphrase: $("pw1").value, confirm: $("pw2").value }));
      // --- data-location step ---
      if (id === "dl-default" || id === "dl-custom")
        $("dl-custom-box").classList.toggle("hidden", !$("dl-custom").checked);
      if (id === "dl-check") dlCheck();
      if (id === "dl-continue") dlContinue(ev.target);
      if (id === "dl-stop")
        post("/api/system/shutdown", { confirm: true }).catch(() => {});

      // --- legal step ---
      if (id === "lg-download")
        window.location = "/api/legal/download?lang=" + encodeURIComponent(_legalLang);
      if (id === "lg-accept") {
        const b = ev.target; b.disabled = true; $("lg-msg").textContent = "";
        post("/api/legal/consent", { version: _legalVersion })
          .then(() => legalToDataLocation())
          .catch((e) => { $("lg-msg").textContent = e.message; b.disabled = false; });
      }
      if (id === "lg-decline") { $("lg-decline-panel").classList.remove("hidden"); $("lg-decline-input").focus(); }
      if (id === "lg-decline-cancel") {
        $("lg-decline-panel").classList.add("hidden");
        $("lg-decline-input").value = ""; $("lg-decline-confirm").disabled = true; $("lg-msg").textContent = "";
      }
      if (id === "lg-decline-confirm") {
        const b = ev.target; b.disabled = true; $("lg-msg").textContent = "";
        post("/api/legal/decline", { confirm: true, word: $("lg-decline-input").value.trim() })
          .then((r) => showUninstalling((r && r.note) || "Uninstalling — you can close this window."))
          .catch((e) => { $("lg-msg").textContent = e.message; b.disabled = false; });
      }
    });
    document.addEventListener("change", (ev) => {
      if (ev.target.id === "lg-check") $("lg-accept").disabled = !ev.target.checked;
    });
    document.addEventListener("input", (ev) => {
      if (ev.target.id === "lg-decline-input")
        $("lg-decline-confirm").disabled = ev.target.value.trim() !== _legalWord;
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      if (!$("view-unlock").classList.contains("hidden")) $("btn-unlock").click();
      else if (!$("view-create").classList.contains("hidden")) $("btn-create").click();
    });

    boot();
  })();

// "Already unlocked" -> the Console (was an inline onclick; Q1127 = a).
(function () {
  var b = document.getElementById("open-console");
  if (b) b.addEventListener("click", function () { location.replace("/"); });
})();
