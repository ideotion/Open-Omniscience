/* app-core.js — core runtime and chrome services

   Core helpers ($, esc, safeUrl), the frontend error-capture feed, the activity
   indicator and toasts, the language menu, the first-launch guided setup, airplane
   mode with its network-consent popup and the AI egress window, adaptive polling,
   vitals, the task manager and its job controls, and the api client with its retry,
   health and crash-screen layer.

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
    const $ = (id) => document.getElementById(id);
    // Escapes ' too: data reaches single-quoted attributes (onclick='…'), where
    // an apostrophe in scraped content would otherwise break out (audit 0.0.9).
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])));
    // Render an ingested URL as a link only if it is plain http(s) — esc() does NOT
    // neutralize a javascript:/data: scheme, which would execute on click (S-005).
    const safeUrl = (u) => {
      const cleaned = String(u == null ? "" : u).replace(/[\x00-\x20\x7f]+/g, "");
      if (/^https?:\/\//i.test(cleaned)) return cleaned;        // absolute http(s)
      if (/^[a-z][a-z0-9+.\-]*:/i.test(cleaned)) return "";      // any other scheme -> reject
      return cleaned;                                            // relative / same-origin
    };

    // ===================================================================== //
    //  Frontend error capture (recursive-augmentation log #1) — turns the    //
    //  "browser-unverified" debt into an OBSERVABLE feed: window.onerror,     //
    //  unhandledrejection, and failed/5xx fetches are reported (throttled) to //
    //  the local rolling log so a `t is not defined` or a dead click shows in //
    //  the debug bundle instead of the maintainer finding it one tab at a     //
    //  time. Loopback-only, no PII by contract (error text + which function / //
    //  endpoint only — never anything the user typed). Best-effort; a broken  //
    //  reporter must NEVER break the app or loop on its own failure.          //
    // ===================================================================== //
    const _OO_ERR_EP = "/api/diagnostics/frontend-error";
    const _ooErrSeen = new Map();   // signature -> last-sent ms (client-side throttle)
    const _ooRawFetch = window.fetch ? window.fetch.bind(window) : null;
    function _ooReportError(kind, message, source, endpoint, lineno) {
      try {
        if (!_ooRawFetch) return;
        const msg = String(message == null ? "" : message).slice(0, 500);
        const sig = kind + "|" + msg.slice(0, 120) + "|" + (source || "");
        const now = Date.now();
        const last = _ooErrSeen.get(sig);
        if (last != null && (now - last) < 5000) return;   // throttle identical
        if (_ooErrSeen.size > 200) _ooErrSeen.clear();
        _ooErrSeen.set(sig, now);
        let lang = null;
        try { lang = (window.OOI18N && OOI18N.current && OOI18N.current()) || null; } catch (e) {}
        const body = {kind: String(kind).slice(0, 40), message: msg};
        if (source) body.source = String(source).slice(0, 300);
        if (endpoint) body.endpoint = String(endpoint).slice(0, 300);
        if (lineno != null) body.lineno = lineno | 0;
        if (lang) body.ui_lang = String(lang).slice(0, 16);
        // Use the RAW fetch so the wrapper below can't recurse on this very POST.
        _ooRawFetch(_OO_ERR_EP, {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body), keepalive: true,
        }).catch(() => {});
      } catch (e) { /* a broken reporter must never break the app */ }
    }
    window.addEventListener("error", (e) => {
      // Element/resource load errors have no `.error`; script errors do.
      const m = (e && e.error && e.error.stack) ? String(e.error.stack).split("\n").slice(0, 3).join(" | ")
               : (e && e.message) || "error";
      const src = e && e.filename ? (e.filename + (e.lineno ? ":" + e.lineno : "")) : null;
      _ooReportError("error", m, src, null, e && e.lineno);
    });
    window.addEventListener("unhandledrejection", (e) => {
      const r = e && e.reason;
      const m = r && r.stack ? String(r.stack).split("\n").slice(0, 3).join(" | ")
              : String(r && r.message ? r.message : r);
      _ooReportError("unhandledrejection", m, null, null, null);
    });
    // Wrap the global fetch to catch NETWORK failures + 5xx (a 4xx is often the
    // correct answer and the backend already logs it, so we don't double-report it).
    // The report POST itself uses the raw fetch above, so it can't recurse here.
    if (_ooRawFetch) {
      window.fetch = function (input, init) {
        const url = (typeof input === "string") ? input : (input && input.url) || "";
        const p = _ooRawFetch(input, init);
        if (url && url.indexOf(_OO_ERR_EP) === -1) {
          p.then((res) => {
            if (res && res.status >= 500) _ooReportError("fetch-5xx", res.status + " " + res.statusText, null, url, null);
          }, (err) => {
            _ooReportError("fetch-failed", (err && err.message) || "network error", null, url, null);
          });
        }
        return p;
      };
    }

    // ONE translatable frame for the ~36 distinct "<Verb> failed: <detail>"
    // toasts scattered through this file.
    //
    // WHY A TEMPLATE AND NOT 36 KEYED SENTENCES: a plain toast whose message
    // is a WHOLE literal is reachable by i18n.js's DOM walker (the toast node
    // lands in #toast, which is neither SKIP-listed nor data-i18n-dyn), so it
    // translates on the next tick if a key exists. A CONCATENATED message is
    // not: the text node is "Save failed: NetworkError", which can never match
    // a static key. So these genuinely need an explicit lookup -- and the
    // honest shape is OOI18N.tf's: the KEY is a fixed template ("{action}
    // failed: {error}", keyable x12) and the values are DATA interpolated
    // AFTER translation, so the FRAME translates and the error text does not.
    // The template is passed WHOLE at each call site ("Save failed: {error}")
    // rather than assembled from a bare action noun. Two reasons, both
    // load-bearing:
    //   * GRAMMAR. 18 of the 36 action words already exist as keys, but as
    //     BUTTON LABELS in the imperative ("Save" -> fr "Enregistrer").
    //     Reusing one as a sentence subject yields "Échec de Enregistrer" --
    //     wrong in every language with case or article agreement. A full
    //     sentence per action translates naturally everywhere.
    //   * GREPPABILITY. The literal stays in the source, so the i18n audit
    //     (and any future widened gate) can still find it; a key built by
    //     string concatenation would be invisible to static analysis.
    // The error detail stays DATA, interpolated after translation.
    // NB: dereferenced as window.OOI18N.tf, not the bare global OOI18N. The
    // surrounding file's older `(window.OOI18N && OOI18N.tf)` idiom relies on
    // a browser aliasing window properties into global scope -- true in a
    // page, but it makes the helper untestable outside one and breaks the
    // moment this runs in a module scope. Same behaviour, no ambient
    // assumption.
    function _failMsg(template, err) {
      const i18n = (typeof window !== "undefined" && window.OOI18N) || null;
      const F = (i18n && i18n.tf)
        ? i18n.tf
        : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)));
      const detail = (err && err.message) ? err.message : String(err == null ? "" : err);
      return F(template, { error: detail });
    }

    function toast(msg, kind="ok", onClick=null) {
      const n = document.createElement("div");
      n.className = "note " + kind; n.textContent = msg;
      if (onClick) {  // a clickable toast acts as a shortcut to what it announces
        n.style.cursor = "pointer";
        n.title = "Click to open";
        n.setAttribute("role", "button");
        n.addEventListener("click", () => { try { onClick(); } finally { n.remove(); } });
      }
      $("toast").appendChild(n);
      // Stay on screen at least a few seconds; errors/warnings linger longer (they carry
      // failure info the user needs to read), and hovering or keyboard-focusing the message
      // PAUSES the auto-dismiss so it is never lost mid-read (resumes with a short grace on
      // leave). Floor of 4 s so no message ever flashes.
      const base = kind === "err" ? 9000 : kind === "warn" ? 7000 : 5000;
      const dur = Math.max(4000, onClick ? Math.max(base, 8000) : base);
      n.tabIndex = 0;  // focusable so keyboard users get the same hover-pause
      let timer = setTimeout(() => n.remove(), dur);
      const pause = () => clearTimeout(timer);
      const resume = () => { clearTimeout(timer); timer = setTimeout(() => n.remove(), 1500); };
      n.addEventListener("mouseenter", pause);
      n.addEventListener("mouseleave", resume);
      n.addEventListener("focusin", pause);
      n.addEventListener("focusout", resume);
    }

    // -- Background-activity indicator -------------------------------------- //
    // Honest "the app is doing something" signal in the top bar. Sources:
    //   * in-flight requests -- every backend call goes through api(), so a counter
    //     there lights a "Working…" spinner for ANY action, app-wide. Shown only
    //     after a short delay so fast status polls don't flicker the chrome.
    //   * background work -- a running scrape (scheduler status .active) shows a
    //     persistent "Collecting… <host>" chip; the host is the URL being fetched
    //     right now (live, truncated). Click the chip for a vitals popover.
    let _inflight = 0, _bg = null, _spinTimer = null, _curHost = null;
    // Last known network state (airplane mode). Default true (online): never paint
    // "paused" until we actually learn we are offline (no fabricated status either way).
    let _netOnline = true;
    function _paintActivity() {
      const el = $("activity"); if (!el) return;
      const host = $("activity-host");
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_bg) {
        // Airplane mode trips the kill switch, so a "background pass" while offline
        // is actually PAUSED — show that honestly (grounded, not the active green),
        // never a fabricated "Collecting…".
        const paused = (_netOnline === false);
        el.hidden = false;
        el.classList.toggle("bg", !paused);
        el.classList.toggle("paused", paused);
        $("activity-label").textContent = paused ? T("Collecting paused") + "…" : _bg;
        host.textContent = paused ? "" : (_curHost || "");
      }
      else if (_inflight > 0) { el.hidden = false; el.classList.remove("bg"); el.classList.remove("paused");
        $("activity-label").textContent = "Working…"; host.textContent = ""; }
      else { el.hidden = true; el.classList.remove("paused"); host.textContent = ""; }
    }
    function _bumpInflight(d) {
      _inflight = Math.max(0, _inflight + d);
      if (_inflight > 0 && !_bg) {
        if (!_spinTimer) _spinTimer = setTimeout(() => { _spinTimer = null; _paintActivity(); }, 350);
      } else {
        if (_spinTimer) { clearTimeout(_spinTimer); _spinTimer = null; }
        _paintActivity();
      }
    }
    function setBackgroundActivity(label) {
      const next = label || null;
      if (next === _bg) return;
      _bg = next; if (!_bg) _curHost = null;
      _paintActivity();
      if (!_bg) _bumpInflight(0);   // re-evaluate any still-pending in-flight spinner
      _ensureVitalsPoll();
    }
    // ---- Permanent top-bar language switcher (flag = convention, native name = truth) ---- //
    const LANGS_12 = [
      ["en", "\u{1F1EC}\u{1F1E7}", "English"],   ["fr", "\u{1F1EB}\u{1F1F7}", "Fran\u00e7ais"],
      ["es", "\u{1F1EA}\u{1F1F8}", "Espa\u00f1ol"],   ["de", "\u{1F1E9}\u{1F1EA}", "Deutsch"],
      ["zh", "\u{1F1E8}\u{1F1F3}", "\u4e2d\u6587"],       ["hi", "\u{1F1EE}\u{1F1F3}", "\u0939\u093f\u0928\u094d\u0926\u0940"],
      ["ar", "\u{1F1F8}\u{1F1E6}", "\u0627\u0644\u0639\u0631\u0628\u064a\u0629"],  ["bn", "\u{1F1E7}\u{1F1E9}", "\u09ac\u09be\u0982\u09b2\u09be"],
      ["ru", "\u{1F1F7}\u{1F1FA}", "\u0420\u0443\u0441\u0441\u043a\u0438\u0439"],  ["pt", "\u{1F1F5}\u{1F1F9}", "Portugu\u00eas"],
      ["id", "\u{1F1EE}\u{1F1E9}", "Bahasa Indonesia"], ["ja", "\u{1F1EF}\u{1F1F5}", "\u65e5\u672c\u8a9e"],
    ];
    function _paintLangButton() {
      const c = (window.OOI18N && OOI18N.current()) || "en";
      const row = LANGS_12.find(l => l[0] === c) || LANGS_12[0];
      const f = document.getElementById("lang-flag"), k = document.getElementById("lang-code");
      if (f) f.textContent = row[1];
      if (k) k.textContent = row[0].toUpperCase();
    }
    function toggleLangMenu(ev) {
      ev.stopPropagation();
      const menu = document.getElementById("lang-menu");
      if (!menu.hidden) { menu.hidden = true; return; }
      const cur = (window.OOI18N && OOI18N.current()) || "en";
      menu.innerHTML = LANGS_12.map(([code, flag, native]) =>
        `<div role="menuitem" tabindex="0" data-lang="${code}"
              style="display:flex;align-items:center;gap:9px;padding:7px 12px;border-radius:7px;cursor:pointer${code === cur ? ";font-weight:700" : ""}"
              onmouseover="this.style.background='var(--line)'" onmouseout="this.style.background=''"
              onclick="pickLang('${code}')" onkeydown="if(event.key==='Enter'){pickLang('${code}')}">
           <span aria-hidden="true">${flag}</span><span>${esc(native)}</span>
           ${code === cur ? '<span style="margin-inline-start:auto">\u2713</span>' : ""}</div>`).join("");
      const r = ev.currentTarget.getBoundingClientRect();
      menu.style.top = (r.bottom + 6) + "px";
      const rtl = document.documentElement.dir === "rtl";
      menu.style.left = rtl ? (r.left) + "px" : "";
      menu.style.right = rtl ? "" : (window.innerWidth - r.right) + "px";
      menu.hidden = false;
      const closer = (e) => { if (!menu.contains(e.target)) { menu.hidden = true; document.removeEventListener("click", closer, true); } };
      document.addEventListener("click", closer, true);
    }
    async function pickLang(code) {
      document.getElementById("lang-menu").hidden = true;
      if (window.OOI18N) await OOI18N.setLang(code);
      const sel = document.getElementById("oo-lang-select");
      if (sel) sel.value = code;   // Settings stays in sync
      _paintLangButton();
    }
    _paintLangButton();

    // -- First-launch guided setup (maintainer-ruled 2026-06-13) -------------- //
    // A ONE-TIME, stepped GUI to a working app. SLICE 1: shell + Language step +
    // Finish/start-collecting step; Encryption + sources-by-theme are placeholder
    // steps for the next slices. INVITATION LAYER for the network: the wizard
    // NEVER posts the network — "Go online & start collecting" closes the wizard
    // and routes through the existing firstRun()/toggleNetwork() flow, so the ONE
    // consent popup (ensureOnline) always fires. The one-time state is a
    // user-visible setting (Settings → General) + a localStorage flag, never hidden.
    // Zero-network on load by construction: it only reads localStorage and reuses
    // the in-memory LANGS_12 list (no fetch).
    const _GUIDE_KEY = "oo_guide_v1";
    // The visible step order. The encryption choice is made in the DB-unlock/install
    // flow (not a wizard placeholder) and sources auto-seed on boot, so those inert
    // "Coming soon" steps were removed (maintainer 2026-06-18). The first-launch flow
    // chooses the language FIRST (unlock.html, #420) and a permanent top-bar switcher
    // (invariant #15) always changes it, so the wizard's language step is redundant
    // (§2.5, autonomous 2026-06-21) — dropped; the #guide-wizard lang DOM + _gwRenderLangs
    // stay unreachable (the Desk lesson). S4.7: the real SOURCES-BY-THEME step is now
    // slotted before Finish (theme picker + language emphasis; loopback reads/writes only,
    // never external egress — the finish step's consented go-online is the only network path).
    const _GW_STEPS = ["sources", "finish"];
    let _gwIdx = 0;
    function _guideState() {
      try { return JSON.parse(localStorage.getItem(_GUIDE_KEY)) || {}; } catch { return {}; }
    }
    function _guideSave(s) {
      try { localStorage.setItem(_GUIDE_KEY, JSON.stringify(s)); } catch { /* private mode */ }
    }
    function guideDone() { return !!_guideState().done; }
    function _gwT(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
    function _gwRenderLangs() {
      const box = $("gw-langs"); if (!box) return;
      const cur = (window.OOI18N && OOI18N.current()) || "en";
      // Native name = the identifier (invariant #15); flag is a visual cue only.
      box.innerHTML = LANGS_12.map(([code, flag, native]) =>
        `<button type="button" class="gw-lang" role="option" data-lang="${code}"
                 aria-selected="${code === cur ? "true" : "false"}">
           <span aria-hidden="true">${flag}</span>
           <span class="gw-native">${esc(native)}</span>
           ${code === cur ? '<span aria-hidden="true">✓</span>' : ""}</button>`).join("");
      box.querySelectorAll(".gw-lang").forEach(b => {
        b.onclick = async () => {
          await pickLang(b.dataset.lang);   // switches the WHOLE UI via THE i18n engine
          _gwRenderLangs();                 // repaint the selection + dir-aware layout
        };
      });
    }
    function _gwRenderDots() {
      const dots = $("gw-dots"); if (!dots) return;
      dots.innerHTML = _GW_STEPS.map((_, i) =>
        `<span class="gw-dot${i < _gwIdx ? " on" : ""}${i === _gwIdx ? " cur" : ""}" role="listitem"></span>`).join("");
    }
    function _gwPaint() {
      const step = _GW_STEPS[_gwIdx];
      document.querySelectorAll("#guide-wizard .gw-step").forEach(s =>
        s.hidden = s.dataset.step !== step);
      _gwRenderDots();
      // Step indicator "Step X / Y" — number-substituted at runtime so the keyed
      // template string ("Step") stays translatable (no ${} baked into the key).
      const prog = $("gw-progress");
      if (prog) prog.textContent = _gwT("Step") + " " + (_gwIdx + 1) + " / " + _GW_STEPS.length;
      const back = $("gw-back"), next = $("gw-next"), fin = $("gw-finish");
      const last = _gwIdx === _GW_STEPS.length - 1;
      if (back) back.disabled = _gwIdx === 0;
      // On the final step, Next/Finish hide — the step itself carries the
      // explicit "Go online & start collecting" / "Stay offline" choice, so the
      // generic Finish never implies a network action by itself.
      if (next) next.hidden = last;
      if (fin) fin.hidden = !last;
      if (step === "lang") _gwRenderLangs();
      if (step === "sources") _gwRenderSources();
      if (step === "finish") _gwRenderFinish();
    }
    // The finish step's own informed-consent disclosure (product feedback 2026-07-17:
    // the SAME local-interface-IP info used to appear only in the SEPARATE #net-consent
    // dialog AFTER clicking "Go online" here -- two consecutive screens asking the same
    // thing). Reads-only (GET /api/system/interfaces, no state change) so this is safe to
    // fetch as soon as the step is shown, before the user has decided anything.
    async function _gwRenderFinish() {
      const box = $("gw-ifaces"); if (!box) return;
      box.textContent = "…";
      const t = _gwT;
      try {
        const d = await api("/api/system/interfaces");
        const rows = (d.interfaces || []).map((i) => `${i.interface}: ${i.addresses.join(", ")}`);
        box.textContent = rows.length ? rows.join("\n") : t("No non-loopback network interfaces were found.");
      } catch (e) {
        box.textContent = t("No non-loopback network interfaces were found.");
      }
    }
    // S4.7 sources-by-theme step. Real catalog tag taxonomy from the app's OWN loopback
    // /api/scheduler/coverage; the config is applied via a loopback PUT /config on leaving
    // the step. NEVER external egress (the app runs on loopback; the finish step's consented
    // go-online is the only path to the network). Themes default to ALL selected = collect
    // everything (the cover-everything ruling); a partial pick sets select_tags (a filter —
    // the user's explicit, reversible focus). Language emphasis -> language_equilibrium (a
    // cadence lever that ORDERS, never excludes).
    const _gwSrc = { picked: null, emph: {} };
    async function _gwRenderSources() {
      const box = $("gw-themes"); if (!box) return;
      let cov = null, cfg = null;
      try { cov = await api("/api/scheduler/coverage"); } catch (_e) { cov = null; }
      try { cfg = await api("/api/scheduler/config"); } catch (_e) { cfg = null; }
      const curTags = (cfg && cfg.select_tags) || [];
      const curEmph = (cfg && cfg.language_equilibrium) || {};
      const covTags = (cov && cov.tags) || [];
      const byTotal = {}; covTags.forEach((x) => { byTotal[x.tag] = x.total || 0; });
      let tags = covTags.map((x) => x.tag).filter((x) => x && x !== "(untagged)");
      tags.sort((a, b) => (byTotal[b] || 0) - (byTotal[a] || 0));   // top themes by source count
      tags = tags.slice(0, 16);
      if (!tags.length) {
        box.innerHTML = `<div class="muted">${esc(_gwT("Themes will appear once your sources are set up. Your app collects from every source by default."))}</div>`;
      } else {
        if (_gwSrc.picked === null) {   // first open: default all-checked, unless a prior config narrowed it
          _gwSrc.picked = {};
          tags.forEach((tg) => { _gwSrc.picked[tg] = curTags.length ? curTags.indexOf(tg) >= 0 : true; });
        }
        box.innerHTML = tags.map((tg) =>
          `<label class="gw-theme" style="display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:8px;padding:4px 9px;cursor:pointer">`
          + `<input type="checkbox" data-theme="${esc(tg)}"${_gwSrc.picked[tg] ? " checked" : ""}> `
          + `<span>${esc(tg)}</span> <span class="muted">${byTotal[tg] || 0}</span></label>`).join("");
        box.querySelectorAll("input[data-theme]").forEach((cb) => {
          cb.onchange = () => { _gwSrc.picked[cb.dataset.theme] = cb.checked; _gwUpdateThemeNote(); };
        });
      }
      const emphBox = $("gw-emph-langs");
      if (emphBox) {
        if (!Object.keys(_gwSrc.emph).length) { for (const k in curEmph) _gwSrc.emph[k] = true; }
        emphBox.innerHTML = LANGS_12.map(([code, flag, native]) =>
          `<button type="button" class="gw-lang" data-emph="${code}" aria-pressed="${_gwSrc.emph[code] ? "true" : "false"}">`
          + `<span aria-hidden="true">${flag}</span> <span class="gw-native">${esc(native)}</span></button>`).join("");
        emphBox.querySelectorAll("[data-emph]").forEach((b) => {
          b.onclick = () => {
            const c = b.dataset.emph; _gwSrc.emph[c] = !_gwSrc.emph[c];
            b.setAttribute("aria-pressed", _gwSrc.emph[c] ? "true" : "false");
          };
        });
      }
      _gwUpdateThemeNote();
    }
    function _gwUpdateThemeNote() {
      const note = $("gw-theme-note"); if (!note || !_gwSrc.picked) return;
      const all = Object.keys(_gwSrc.picked), on = all.filter((k) => _gwSrc.picked[k]);
      note.textContent = (on.length === 0 || on.length === all.length)
        ? _gwT("Collecting from every source (all themes).")
        : _gwT("Focusing your first collection on the selected themes. You can widen it anytime in Settings → Collect.");
    }
    // Apply the picks as scheduler config (a LOOPBACK settings write — never egress, never
    // starts a collection). All-or-none themes => NO filter (collect everything). Best-effort:
    // a settings write must never block onboarding.
    async function _gwApplySourcePrefs() {
      if (!_gwSrc.picked) return;   // the step was never opened -> change nothing
      const all = Object.keys(_gwSrc.picked), on = all.filter((k) => _gwSrc.picked[k]);
      const select_tags = (on.length === 0 || on.length === all.length) ? [] : on;
      const language_equilibrium = {};
      for (const k in _gwSrc.emph) if (_gwSrc.emph[k]) language_equilibrium[k] = 1;
      try {
        await api("/api/scheduler/config",
          { method: "PUT", body: JSON.stringify({ select_tags: select_tags, language_equilibrium: language_equilibrium }) });
      } catch (_e) { /* best-effort local settings write; never block the guide */ }
    }
    function openGuide() {
      const dlg = $("guide-wizard"); if (!dlg) return;
      _gwIdx = 0; _gwPaint();
      if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      else dlg.setAttribute("open", "");
      if (window.OOI18N && OOI18N.apply) OOI18N.apply(dlg);  // translate freshly-shown chrome
      // Product feedback 2026-07-17: the network-status poll that decides whether to
      // show the airplane-mode coachmark runs independently of (and typically resolves
      // before) this wizard opening, so the coach could already be showing when the
      // wizard's own finish step arrives with the SAME "go online" invitation. Hide it
      // NON-permanently (never sets the "dismissed forever" flag) -- the wizard covers
      // the teaching purpose for this session; a future session where the user is still
      // offline (and the one-time guide won't reopen) can still show it normally.
      if (typeof dismissNetCoach === "function") dismissNetCoach(false);
    }
    // Closing the wizard for good marks the one-time state done (the user-visible
    // Settings toggle can flip it back on for the next load). It NEVER touches the
    // network — that is the finish step's explicit, consented choice.
    function closeGuide(markDone) {
      const dlg = $("guide-wizard"); if (!dlg) return;
      if (markDone !== false) { const s = _guideState(); s.done = true; _guideSave(s); }
      try { dlg.close(); } catch { dlg.removeAttribute("open"); }
      _syncRerunGuide();
    }
    // The Settings "Re-run the first-launch guide" toggle is the user-VISIBLE
    // one-time state (not a hidden flag): ticking it clears `done` so the guide
    // shows again next load; unticking marks it done. Checked == "will re-run".
    function setRerunGuide(on) {
      const s = _guideState(); s.done = !on; _guideSave(s);
    }
    function _syncRerunGuide() {
      const cb = $("set-rerun-guide"); if (cb) cb.checked = !guideDone();
    }
    (function _wireGuide() {
      const next = $("gw-next"), back = $("gw-back"), fin = $("gw-finish"),
            close = $("gw-close"), go = $("gw-go-online"), stay = $("gw-stay-offline");
      if (next) next.onclick = async () => {
        if (_GW_STEPS[_gwIdx] === "sources") await _gwApplySourcePrefs();  // apply on leaving the step
        if (_gwIdx < _GW_STEPS.length - 1) { _gwIdx++; _gwPaint(); }
      };
      if (back) back.onclick = () => { if (_gwIdx > 0) { _gwIdx--; _gwPaint(); } };
      if (fin) fin.onclick = () => closeGuide(true);
      if (close) close.onclick = () => closeGuide(true);   // X also completes the one-time guide
      if (stay) stay.onclick = () => closeGuide(true);
      // Product feedback 2026-07-17: this step's OWN screen now carries the informed-
      // consent disclosure (local interface IPs, _gwRenderFinish) that used to only
      // appear in a SEPARATE #net-consent dialog opened right after this click -- two
      // consecutive screens confirming the same decision. ensureOnline(reason,
      // {skipDialog:true}) still performs the ONLY POST /api/system/network in the
      // whole app (invariant #14: it stays the ONE canonical consent-enforcing
      // function) — it just skips re-opening its OWN dialog for a caller that has
      // already shown the equivalent disclosure with its own confirming click.
      if (go) go.onclick = async () => {
        const t = _gwT;
        go.disabled = true;
        await _gwApplySourcePrefs();   // persist theme/emphasis picks before collecting (loopback, no egress)
        const online = await ensureOnline(t("Go online & start collecting"), { skipDialog: true });
        if (!online) {
          go.disabled = false;
          return;   // let the user retry or choose "Stay offline" instead of closing on failure
        }
        if (typeof _flashNet === "function") _flashNet(true);
        toast(t("Back online — network requests allowed again."), "ok");
        // Once online the background collector runs continuously on its own (only
        // airplane mode stops it) — no manual seed/ingest step or progress card needed.
        closeGuide(true);
      };
      const dlg = $("guide-wizard");
      if (dlg) dlg.addEventListener("cancel", () => closeGuide(true));   // Esc completes it too
    })();

    async function toggleNetwork() {
      const btn = $("net-toggle");
      const goingOnline = btn.classList.contains("off");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!goingOnline) {
        // GOING OFFLINE: react INSTANTLY. The POST that trips the kill switch + installs
        // the airplane socket guard can take a moment (esp. with an in-flight fetch), and
        // waiting on it before any feedback made the button feel laggy/broken. So paint the
        // button offline, fire the direction-aware flash + a brief "Entering airplane mode"
        // pop-up NOW, then POST in the background — reverting only if the backend refuses
        // (it shouldn't; airplane is a local flag). Honest: on failure we are NOT offline.
        _paintNetwork(false);
        _flashNet(false);
        _airplanePopup(t("Entering airplane mode"));
        // Tentative until the POST that actually trips the kill switch resolves — don't
        // claim requests are refused BEFORE that is true (honesty by construction).
        toast(t("Going offline — cutting new network requests…"), "err");
        try {
          const r = await api("/api/system/network", {method:"POST", body: JSON.stringify({online:false})});
          _paintNetwork(r.online);  // reconcile with the backend truth
          if (!r.online) toast(t("Offline — every new network request is refused. One in-flight request may finish."), "err");
        } catch (e) {
          _paintNetwork(true);      // the backend refused -> we are NOT offline; revert honestly
          toast(e.message, "err");
        }
        return;
      }
      // GOING ONLINE: EVERY transition is consented (maintainer-ruled). ensureOnline runs
      // the ONE consent popup + POSTs + repaints, so its dialog IS the immediate feedback.
      try {
        if (!await ensureOnline(t("Allow network requests again"))) return;
        _flashNet(true);
        toast(t("Back online — network requests allowed again."), "ok");
      } catch (e) { toast(e.message, "err"); }
    }
    // AI-install egress-window state. Declared HERE, above _paintNetwork, because
    // that function reads _egressState for its third-state title; the rest of the
    // window's functions live further down beside ensureOnline.
    let _egressState = null;      // last status payload, or null
    let _egressTimer = 0;         // poll handle while a window is open
    let _egressBarHtml = "";      // last markup WRITTEN to the bar (aria-live: no-op when unchanged)
    // Direction-aware transition flash (§3): go-on = live accent, go-off = calm/grounded.
    function _flashNet(online) {
      let f = document.getElementById("net-flash");
      if (!f) { f = document.createElement("div"); f.id = "net-flash"; document.body.appendChild(f); }
      f.classList.remove("go-on", "go-off"); void f.offsetWidth;
      f.classList.add(online ? "go-on" : "go-off");
    }
    // A brief centered pop-up acknowledging airplane mode INSTANTLY (the backend
    // kill-switch + socket-guard install lags a moment). Auto-dismisses (~1.6 s), or
    // click the backdrop / OK to close now. Purely cosmetic, non-blocking feedback.
    function _airplanePopup(msg) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const old = document.getElementById("net-popup"); if (old) old.remove();
      const wrap = document.createElement("div");
      wrap.id = "net-popup"; wrap.className = "net-popup";
      wrap.innerHTML = `<div class="net-popup-card" role="status" aria-live="polite">`
        + `<div class="net-popup-glyph" aria-hidden="true">✈</div>`
        + `<div class="net-popup-msg">${esc(msg)}</div>`
        + `<button type="button" class="net-popup-ok">${esc(t("OK"))}</button></div>`;
      let tm = 0;
      const close = () => { clearTimeout(tm); wrap.remove(); };
      wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });  // click outside = close
      wrap.querySelector(".net-popup-ok").addEventListener("click", close);
      document.body.appendChild(wrap);
      tm = setTimeout(close, 1600);
    }
    function _paintNetwork(online) {
      // Remember the state so the activity chip can show "Collecting paused" when a
      // background pass is in flight but the kill switch is engaged (Item V).
      const _was = _netOnline;
      _netOnline = online;
      // The local LLM (Ollama) is refused under airplane mode, so its pill goes
      // stale offline at boot (we boot offline). Re-check it the moment we go online
      // so it reflects a now-reachable Ollama without the user opening Settings.
      if (online && _was !== true && typeof loadLlmHealth === "function") loadLlmHealth();
      _paintActivity();
      const btn = $("net-toggle"); if (!btn) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Airplane-mode semantics (maintainer-ruled): ONE constant glyph whose
      // FILL is the state — filled = offline engaged. Never an action glyph.
      const plane = document.getElementById("net-plane");
      if (plane) plane.setAttribute("fill", online ? "none" : "currentColor");
      const label = document.getElementById("net-label");
      if (label) label.textContent = online ? t("Online") : t("Offline");
      // State-specific hover title (field test 2026-06-19 #5): name the ACTION the
      // click performs. The button is data-i18n-dyn so the i18n observer won't revert
      // this; the oo:langchange listener re-calls _paintNetwork to re-translate it.
      // THIRD STATE. With an AI-install egress window open the plain offline
      // title -- "every new network request will be refused" -- is simply FALSE,
      // and a hover that lies about the operator's own exposure is exactly the
      // fabricated assurance this project forbids. The plane's FILL still means
      // the kill switch (invariant #14, untouched); only the words change.
      const _egressOpen = !!(_egressState && _egressState.open);
      btn.title = online
        ? t("Online — click to go offline (airplane mode); every new network request will be refused.")
        : _egressOpen
          ? t("Offline (airplane mode), except the AI install you allowed — collection stays stopped. Click to go fully online.")
          : t("Offline (airplane mode) — click to go online; you'll be asked to confirm first.");
      btn.classList.toggle("off", !online);
      btn.classList.toggle("egress-open", !online && _egressOpen);
      document.body.classList.toggle("net-offline", !online);
      // Onboarding coachmark: invite once when we first learn we're offline;
      // retire it for good once the user is online (they've learned the switch).
      // An open window must NOT retire it (the operator has not gone online in the
      // sense the coach teaches) and must not trigger it either (inviting someone
      // to "go online" while a window is already open just muddles the two).
      if (online) { _coachChecked = true; dismissNetCoach(true); }
      else if (!_coachChecked && !_egressOpen) { _coachChecked = true; maybeShowNetCoach(); }
    }
    // -- Airplane-mode onboarding coachmark (maintainer-ruled 2026-06-13) ------
    // Teaches the ONE online/offline switch. INVITATION LAYER ONLY: the "Go
    // online" action routes through toggleNetwork() -> ensureOnline, so the ONE
    // consent popup still fires; the coach NEVER calls the network API itself.
    // Dismissal is remembered locally; prominent on first launches, then subtle,
    // and never naggy (capped, and retired once the user goes online).
    const _COACH_KEY = "oo_net_coach_v1";
    let _coachChecked = false;
    function _coachState() {
      try { return JSON.parse(localStorage.getItem(_COACH_KEY)) || {}; } catch { return {}; }
    }
    function _coachSave(s) {
      try { localStorage.setItem(_COACH_KEY, JSON.stringify(s)); } catch { /* private mode */ }
    }
    function _placeCoach() {
      const el = $("net-coach"), btn = $("net-toggle");
      if (!el || !btn || !el.classList.contains("show")) return;
      const b = btn.getBoundingClientRect();
      const w = el.offsetWidth, h = el.offsetHeight, gap = 12, pad = 8;
      const arrow = el.querySelector(".coach-arrow");
      let left, top, side;
      if (b.right + gap + w <= window.innerWidth - pad) {   // prefer to the right of the button
        left = b.right + gap; top = b.top + b.height / 2 - h / 2; side = "left";
      } else {
        // No room to the right. The coach must go BELOW the whole protected-button
        // cluster, never above it: the topbar sits at the very top of the viewport,
        // so placing it above the button (its top computed from the button's own
        // top, minus the gap and the coach's height) is almost always deeply
        // negative, and the clamp below collapses it right back into the topbar's
        // own row -- overlapping every button in it (net-coach-blocks-topbar-buttons,
        // P0; this was the exact, guaranteed-every-time root cause, not an
        // occasional mispositioning). Below the union of every button the coach
        // must never cover is the one direction structurally guaranteed to have
        // room and to never overlap any of them.
        const guard = ["net-toggle", "lang-switch", "tm-open", "app-shutdown"]
          .map((id) => $(id)).filter(Boolean).map((e) => e.getBoundingClientRect());
        const guardBottom = guard.length ? Math.max(...guard.map((r) => r.bottom)) : b.bottom;
        left = b.left; top = guardBottom + gap; side = "below";
      }
      left = Math.max(pad, Math.min(left, window.innerWidth - w - pad));
      top = Math.max(pad, Math.min(top, window.innerHeight - h - pad));
      el.style.left = left + "px"; el.style.top = top + "px";
      if (arrow) {
        if (side === "left") {
          arrow.style.left = "-6px"; arrow.style.right = "auto";
          arrow.style.top = Math.max(8, Math.min(b.top + b.height / 2 - top - 5, h - 16)) + "px";
          arrow.style.transform = "rotate(45deg)";
        } else {
          // "below": the arrow must point UP at the button cluster, so it peeks out
          // the TOP edge (mirrors the "left" case's left:-6px) -- never the bottom,
          // which was only correct for the old, unsafe above-the-button placement.
          arrow.style.top = "-6px";
          arrow.style.left = Math.max(8, Math.min(b.left + b.width / 2 - left - 5, w - 16)) + "px";
          arrow.style.transform = "rotate(45deg)";
        }
      }
    }
    function dismissNetCoach(permanent) {
      const el = $("net-coach"); if (el) el.classList.remove("show", "prominent");
      if (permanent) { const s = _coachState(); s.dismissed = true; _coachSave(s); }
      window.removeEventListener("resize", _placeCoach);
    }
    function maybeShowNetCoach() {
      const el = $("net-coach"), btn = $("net-toggle"); if (!el || !btn) return;
      const offline = document.body.classList.contains("net-offline") || btn.classList.contains("off");
      if (!offline) return;                              // only invite when actually offline
      // Product feedback 2026-07-17: on a first-run install the guide wizard's OWN
      // finish step already invites "Go online & start collecting" -- showing this
      // bubble AT THE SAME TIME pointed two separate prompts at the same decision.
      // The wizard covers the same teaching purpose for a first-run user, so skip
      // the coach while it's open (openGuide() also hides it non-permanently if it
      // was already showing, for the reverse ordering).
      const wiz = $("guide-wizard");
      if (wiz && wiz.open) return;
      const s = _coachState();
      if (s.dismissed || (s.seen || 0) >= 6) return;     // respected + never naggy
      s.seen = (s.seen || 0) + 1; _coachSave(s);
      const go = $("net-coach-go"), no = $("net-coach-dismiss");
      if (go) go.onclick = () => { dismissNetCoach(true); toggleNetwork(); };  // consent still fires
      if (no) no.onclick = () => dismissNetCoach(true);
      el.classList.add("show");
      el.classList.toggle("prominent", s.seen <= 2);     // prominent first launches, subtle after
      _placeCoach();
      setTimeout(_placeCoach, 220);                      // reposition after i18n reflow
      window.addEventListener("resize", _placeCoach);
    }
    // ONE consent design for every offline->online transition: what will
    // happen + the machine's LOCAL addresses (kernel tables; fetching a
    // public-IP echo pre-consent would itself be a network call, so we never
    // do it — the popup says what the public IP is instead).
    //
    // opts.skipDialog (product feedback 2026-07-17): for a caller that has ALREADY
    // shown this exact disclosure (interfaces + wording) on its OWN screen with its
    // own confirming click — today only the first-launch wizard's finish step
    // (_gwRenderFinish) — skip re-opening #net-consent for the identical decision.
    // This function REMAINS the only one that ever POSTs /api/system/network: a
    // skipping caller still goes through the SAME POST + repaint below, just without
    // a SECOND dialog on top of its own already-shown disclosure. Every other caller
    // (the airplane toggle, collect start, wiki page add, dump start, market imports…)
    // is unaffected — they never pass skipDialog and still get the full popup.
    // The single POST that ever flips the network online — shared by the dialog's
    // "ok" button AND a skipDialog caller, so there is exactly ONE place in the app
    // that performs this request (never duplicated inline per-caller).
    async function _postGoOnline() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const r = await api("/api/system/network", {method:"POST", body: JSON.stringify({online:true})});
        _paintNetwork(r.online);
        // The endpoint re-READS the kill switch rather than echoing the request (it is
        // honest about the state it actually reached), so a 200 can still carry
        // online:false. That path used to return quietly: the button repainted to
        // airplane and the operator was told nothing -- the silent half of the field
        // report "sometimes the app remains in airplane mode with no explanation"
        // (2026-08-02). A refusal must be as loud as a failure.
        if (!r.online) {
          toast(t("Still offline — the request was accepted but airplane mode is still on. Try again."), "err");
        }
        return r.online;
      } catch (e) { toast(e.message, "err"); return false; }
    }
    async function ensureOnline(reason, opts) {
      opts = opts || {};
      try {
        const nm = await api("/api/system/network");
        _paintNetwork(nm.online);
        if (nm.online) return true;
      } catch (_e) { /* fall through to consent — flipping online still asks */ }
      if (opts.skipDialog) return _postGoOnline();
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const dlg = document.getElementById("net-consent");
      dlg.querySelector("#net-consent-reason b").textContent = reason;
      const box = document.getElementById("net-consent-ifaces");
      box.textContent = "…";
      api("/api/system/interfaces").then(d => {
        const rows = (d.interfaces || []).map(i => `${i.interface}: ${i.addresses.join(", ")}`);
        box.textContent = rows.length ? rows.join("\n") : t("No non-loopback network interfaces were found.");
        box.style.whiteSpace = "pre-line";
      }).catch(() => { box.textContent = t("No non-loopback network interfaces were found."); });
      return new Promise((resolve) => {
        const ok = document.getElementById("net-consent-ok");
        const cancel = document.getElementById("net-consent-cancel");
        const done = (val) => { dlg.close(); ok.onclick = cancel.onclick = dlg.oncancel = null; resolve(val); };
        ok.onclick = async () => done(await _postGoOnline());
        cancel.onclick = () => done(false);
        dlg.oncancel = () => done(false); // Esc = stay offline
        dlg.showModal();
      });
    }

    // ---- AI-install egress window ------------------------------------------
    // Operator, 2026-08-01: install Ollama/vLLM without starting the collector --
    // "divulging your IP to ollama and vllm is not the same as divulging it to all
    // scrapped sources". This is a THIRD state, not a weakened online: the kill
    // switch stays engaged, so the collector and every other gated download keep
    // refusing themselves, and only the AI-install gates are exempted.
    //
    // Deliberately does NOT go through _postGoOnline(): that function remains the
    // one and only place that POSTs /api/system/network (invariant #14 and
    // tests/test_network_consent.py both key on it), and this path is not going
    // online. Separate endpoint, separate dialog, nothing to regress.
    // (_egressState / _egressTimer are declared above, beside _paintNetwork,
    // which reads _egressState for its third-state title.)

    // Ask for an egress window if one is needed. Returns true when the AI install
    // may proceed: already fully online (nothing to ask), a window already open,
    // or the operator consented just now.
    async function ensureAiEgress(reason) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const nm = await api("/api/system/network");
        _paintNetwork(nm.online);
        if (nm.online) return true;   // no window needed; the app is simply online
      } catch (_e) { /* fall through and ask -- never assume online */ }
      try {
        const st = await api("/api/system/egress-window");
        _paintEgressWindow(st);
        if (st.open) return true;     // already allowed, still running
      } catch (_e) { /* fall through and ask */ }
      const dlg = document.getElementById("ai-egress-consent");
      if (!dlg) return false;         // no dialog -> never silently proceed
      const slot = dlg.querySelector("#ai-egress-reason b");
      if (slot) slot.textContent = reason || t("Install the local AI");
      return new Promise((resolve) => {
        const ok = document.getElementById("ai-egress-ok");
        const cancel = document.getElementById("ai-egress-cancel");
        const done = (val) => {
          dlg.close();
          ok.onclick = cancel.onclick = dlg.oncancel = null;
          resolve(val);
        };
        ok.onclick = async () => done(await _openEgressWindow());
        cancel.onclick = () => done(false);
        dlg.oncancel = () => done(false);   // Esc = stay offline
        dlg.showModal();
      });
    }

    // The single place that opens a window (mirrors _postGoOnline's discipline).
    async function _openEgressWindow() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const st = await api("/api/system/egress-window",
          {method: "POST", body: JSON.stringify({open: true})});
        _paintEgressWindow(st);
        _startEgressPoll();
        return !!st.open;
      } catch (e) {
        // api() has already normalised the payload into e.message via
        // _apiErrorMessage, so a dict-valued FastAPI `detail` never renders as
        // "[object Object]" here.
        toast(e.message, "err");
        return false;
      }
    }

    async function closeEgressWindow() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const st = await api("/api/system/egress-window",
          {method: "POST", body: JSON.stringify({open: false})});
        _paintEgressWindow(st);
        // NOT "the install can no longer reach the network": a download already
        // in flight runs in a child process (pip / Hugging Face / Ollama's
        // daemon) that this app cannot stop, exactly as the consent dialog said
        // when it was opened. Closing revokes the GATES -- the next step is
        // refused -- and claiming more than that here would contradict the
        // dialog three clicks earlier.
        toast(t("Closed. New install steps are refused again; a download already running finishes on its own."), "ok");
      } catch (e) { toast(e.message, "err"); }
    }

    // Render the bar. A change in the operator's network exposure must never be
    // silent, so a window CLOSING announces itself even when nothing asked --
    // including when it closed because the install failed or was cancelled.
    function _paintEgressWindow(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const bar = document.getElementById("egress-window-bar");
      const was = _egressState && _egressState.open;
      _egressState = st || null;
      const open = !!(st && st.open);
      // Re-derive the airplane button's hover title from its ONE source rather
      // than duplicating the wording here: while a window is open the plain
      // "every new network request will be refused" line is false, and a hover
      // that lags the truth by a poll interval is still a hover that lies.
      if (!!was !== open) _paintNetwork(_netOnline);
      const netBtn = $("net-toggle");
      if (netBtn) netBtn.classList.toggle("egress-open", open);
      if (was && !open) {
        toast(t("The AI install window closed — the network is refused again."), "ok");
        _stopEgressPoll();
      }
      if (!bar) return;
      if (!open) { bar.hidden = true; bar.innerHTML = ""; _egressBarHtml = ""; return; }
      // "The collector is stopped" is a MEASURED read of the scheduler, not our
      // own assumption -- null means we could not measure it and we say so rather
      // than printing a reassuring "stopped" we did not check.
      const coll = st.collector_running;
      const collLine = coll === false
        ? t("Collection is stopped — no source is being contacted.")
        : coll === true
          ? t("Warning: the collector is running.")
          : t("The collector's state could not be read just now.");
      bar.hidden = false;
      const html =
        `<span aria-hidden="true">⬤</span>` +
        `<span class="egress-msg"><b>${esc(t("The AI install is allowed online."))}</b> ` +
        `<span class="egress-sub">${esc(collLine)} ` +
        `${esc(t("Which hosts the installer contacts is not restricted, and it does not use your proxy or Tor."))}` +
        `</span></span>` +
        `<button class="tiny secondary" id="egress-close-btn">${esc(t("Close now"))}</button>`;
      // Assign ONLY on a real change. This is an aria-live region, and a polite
      // region announces on every mutation -- rewriting identical markup each
      // 5 s poll would read the whole banner aloud, over and over, for the length
      // of a multi-GB download. Unchanged text must therefore be a no-op, not a
      // re-render that happens to look the same. Compared against what we last
      // WROTE, never against bar.innerHTML: the browser normalises markup on
      // read-back, so that comparison would never match and the guard would
      // silently do nothing.
      if (_egressBarHtml === html) return;
      _egressBarHtml = html;
      bar.innerHTML = html;
      const btn = document.getElementById("egress-close-btn");
      if (btn) btn.addEventListener("click", closeEgressWindow);
    }

    // Poll only WHILE a window is open (it stops itself on close), so this adds
    // no idle traffic. The GET also drives the server-side idle reap, which is
    // what closes the window after the install succeeds, fails or is cancelled.
    function _startEgressPoll() {
      if (_egressTimer) return;
      _egressTimer = setInterval(async () => {
        try { _paintEgressWindow(await api("/api/system/egress-window")); }
        catch (_e) { /* transient: keep the bar as-is, keep polling */ }
      }, 5000);
    }
    function _stopEgressPoll() {
      if (_egressTimer) { clearInterval(_egressTimer); _egressTimer = 0; }
    }

    // A window can outlive a page reload (it lives in the server process), so a
    // freshly-loaded page must discover it -- otherwise the operator would have an
    // open window with no visible indication and no way to close it.
    async function initEgressWindow() {
      try {
        const st = await api("/api/system/egress-window");
        _paintEgressWindow(st);
        if (st.open) _startEgressPoll();
      } catch (_e) { /* the bar simply stays hidden */ }
    }

    // The 5 s background poll keeps the airplane state fresh as a FALLBACK (the
    // primary repaint rides scheduler responses). Vitals are no longer polled here
    // -- they live in the task-manager window's System tab, polled only while that
    // window is open or a scrape is live (§2: vitals moved out of the chrome).
    // Adaptive background poll (audit PR G): poll at `fast` while state is changing,
    // backing off to `slow` once nothing has changed for `quietMs` — this cuts the
    // idle polling storm (field-log finding B) without adding any boot-time network.
    // State stays event-fresh because scheduler/airplane transitions push immediate
    // repaints; this governs only the passive refresh. Work pauses while the tab is
    // hidden. It self-reschedules in EVERY path, so it can neither stall nor
    // hot-spin. `fn` returns truthy when it observed a change/activity (-> reset to
    // fast). Returns {wake} to force fast from the outside.
    function _adaptivePoll(fn, {fast = 5000, slow = 20000, quietMs = 45000} = {}) {
      let lastActive = Date.now();
      const tick = async () => {
        if (!document.hidden) {
          try { if (await fn()) lastActive = Date.now(); } catch (_e) { /* transient */ }
        }
        const idle = document.hidden || (Date.now() - lastActive) > quietMs;
        setTimeout(tick, idle ? slow : fast);
      };
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) lastActive = Date.now();  // refocus -> poll fast again
      });
      tick();
      return {wake: () => { lastActive = Date.now(); }};
    }

    let _lastOnline = null;
    async function _pollNetwork() {
      if (document.hidden) return false;
      try {
        const nm = await api("/api/system/network");
        const changed = nm.online !== _lastOnline;
        _lastOnline = nm.online;
        _paintNetwork(nm.online);
        return changed;  // a flip resets the adaptive poll to fast
      } catch (_e) { return false; }
    }
    _adaptivePoll(_pollNetwork);

    async function _pollActivity() {
      try {
        const s = await api("/api/scheduler/status");
        // Honor the online flag the scheduler already reports (online = not
        // kill_switch_active()): the activity poll runs fast while a pass is live,
        // so without this it could repaint a green "Collecting…" chip AFTER airplane
        // mode paused the pass (the slower network poll lands later). Flip + repaint
        // on a change, even though setBackgroundActivity keeps the same label. (Item V)
        if (s && typeof s.online === "boolean" && s.online !== _netOnline) {
          _netOnline = s.online;
          _paintActivity();
        }
        const active = !!(s && s.active);
        setBackgroundActivity(active ? "Collecting…" : null);
        return active;  // live (fast) while a scrape runs; backs off when idle
      } catch { return false; /* transient: keep the last known state */ }
    }

    // -- Live vitals (CPU/RAM/disk + real, app-attributed scraping throughput) -- //
    // Polls /api/system/vitals (and, when the panel is open or a scrape is live,
    // /api/scheduler/activity) only while needed, so an idle app makes no extra
    // requests. Rates are derived by diffing two snapshots (cumulative counters --
    // never a guessed instantaneous value). Hosts are shown as DOMAINS, never
    // full URLs (maintainer-ruled 2026-06-10).
    let _vitalsTimer = null, _vitalsOpen = false, _vitalsPrev = null, _actData = null;
    let _covData = null, _covLoading = false, _covEq = null;
    // a11y (OO-D13-001): remember who opened a non-native dialog so focus returns.
    let _vitalsPrevFocus = null, _palPrevFocus = null;
    function _shortUrl(u) {
      if (!u) return "";
      const s = String(u).replace(/^https?:\/\//i, "").replace(/^www\./i, "");
      return s.length > 40 ? s.slice(0, 39) + "…" : s;
    }
    function _fmtBytes(n) {
      if (n == null) return "—";
      const u = ["B","KB","MB","GB","TB"]; let i = 0, v = n;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return (v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)) + " " + u[i];
    }
    function _rateBytes(curr, prev, pick) {
      if (!prev) return null;
      const dt = curr.at - prev.at; if (dt <= 0) return null;
      const a = pick(curr), b = pick(prev);
      if (a == null || b == null) return null;
      return Math.max(0, (a - b) / dt);
    }
    function _vitalsShouldRun() { return _vitalsOpen || !!_bg; }
    // Cadence (field diagnostics 2026-07-01, F5 -- the idle polling storm): the panel
    // OPEN means the user is watching live vitals -> a responsive 2 s. Chip-only (a
    // background scrape with the panel CLOSED) only updates the "Collecting N/M" chip,
    // which nobody watches sub-second -> a calm 6 s. An overnight scrape had polled
    // /api/system/vitals + /api/scheduler/activity every 2 s (~28.9k scheduler/activity
    // calls contending with the encrypted DB); this cuts the closed-panel case ~3x. The
    // airplane/network state stays fresh on its OWN _adaptivePoll, so this never dulls
    // it, and opening the panel snaps back to 2 s with an immediate refresh.
    function _vitalsCadence() { return _vitalsOpen ? 2000 : 6000; }
    function _ensureVitalsPoll() {
      if (_vitalsTimer) { clearTimeout(_vitalsTimer); _vitalsTimer = null; }
      if (!_vitalsShouldRun()) { _vitalsPrev = null; return; }
      const tick = () => {
        if (!document.hidden) _pollVitals();
        _vitalsTimer = _vitalsShouldRun() ? setTimeout(tick, _vitalsCadence()) : null;
      };
      _pollVitals();                                  // immediate refresh on (re)start / panel open
      _vitalsTimer = setTimeout(tick, _vitalsCadence());
    }
    async function _pollVitals() {
      let v; try { v = await api("/api/system/vitals"); } catch { return; }
      const cur = v.scraping && v.scraping.current_fetch;
      if (_vitalsOpen || _bg) {
        try { _actData = await api("/api/scheduler/activity"); } catch { _actData = null; }
      }
      if (_bg) {
        const pg = _actData && _actData.progress;
        _curHost = pg && pg.current ? pg.current : (cur ? _shortUrl(cur.url) : null);
        if (pg && pg.total) {
          $("activity-label").textContent = `Collecting ${Math.min(pg.done + 1, pg.total)}/${pg.total}…`;
        }
        _paintActivity();
      }
      if (_vitalsOpen) { _renderVitals(v); _renderJobs(); _renderSchedule(); }
      _vitalsPrev = v;
    }
    function _fmtDur(s) {
      if (s == null) return "—";
      if (s < 90) return `~${Math.max(1, Math.round(s))} s`;
      return `~${Math.round(s / 60)} min`;
    }
    function _renderVitals(v) {
      const p = v.process || {}, sc = v.scraping || {};
      const dl = _rateBytes(v, _vitalsPrev, x => x.scraping && x.scraping.bytes_total);
      const a = _actData || {};
      const pg = a.progress, plan = a.plan || {}, rates = a.per_host_rates || [];
      const row = (k, val) => `<div class="vr"><span>${k}</span><b>${val}</b></div>`;
      const sect = (t) => `<div class="vsect">${t}</div>`;
      // -- Now: live run progress (domains only, a real bar) ---------------- //
      let nowHtml;
      if (pg && pg.total) {
        const pct = Math.round(100 * Math.min(pg.done, pg.total) / pg.total);
        nowHtml =
          row("Now collecting", `${esc(pg.current || "…")} <span class="muted">· ${pg.mode}</span>`) +
          `<div class="cap-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">` +
          `<div class="cap-fill" style="width:${pct}%"></div><span class="cap-txt">${pg.done}/${pg.total} · ${pct}%</span></div>` +
          (pg.pages ? row("Pages this run", String(pg.pages)) : "");
      } else {
        const nr = a.next_run ? new Date(a.next_run) : null;
        const mins = nr ? Math.max(0, Math.round((nr - Date.now()) / 60000)) : null;
        // A pass can be ACTIVE while past the per-source scrape (progress is cleared
        // once the articles are in): show the honest PHASE so a lingering market or
        // calendar fetch reads as "finishing", not "idle" (maintainer 2026-06-18 — the
        // task-manager's whole point). Phase comes from /api/scheduler/activity.
        const _phaseTxt = {
          collecting: "Collecting articles",
          background: "Background tasks (markets · calendars · checks)",
          briefing: "Building the briefing",
        }[a.phase];
        nowHtml = row("Now collecting", a.active
          ? `<span class="muted">${esc(_phaseTxt || "Collecting…")}</span>`
          : a.running
            ? `<span class="muted">idle</span>${mins != null ? ` · <span title="${esc(fmtDateTime(a.next_run))}">⏱ ${mins} min</span>` : ""}`
            : '<span class="muted">scheduler stopped</span>');
      }
      // -- Next pass: targets as domain chips + the honest estimate --------- //
      const chips = (plan.next_targets || []).map(d => `<span class="cap-chip">${esc(d)}</span>`).join("");
      const extra = Math.max(0, (plan.planned_total || 0) - (plan.next_targets || []).length);
      const planHtml = (plan.planned_total || plan.estimated_seconds != null) ?
        sect("Next pass") +
        row("Targets", `${plan.planned_total || 0} <span class="muted">· ${esc(plan.mode || "")}</span>`) +
        (chips ? `<div class="cap-chips">${chips}${extra ? `<span class="cap-chip muted">+${extra}</span>` : ""}</div>` : "") +
        (plan.estimated_seconds != null
          ? row("Estimated duration", `${_fmtDur(plan.estimated_seconds)}`) +
            `<div class="vnote">${esc(plan.estimate_method || "")}</div>`
          : "") : "";
      // -- Per-source rates: the app's OWN fetches, discrete ---------------- //
      const rateHtml = rates.length
        ? sect("Per-source download rate") +
          rates.map(r => `<div class="vr vr-dim"><span>${esc(r.host)}</span>` +
            `<b>${r.kbps} KB/s <span class="muted">· ${_fmtBytes(r.bytes)} · ${r.fetches}×</span></b></div>`).join("") +
          '<div class="vnote">Measured from this app’s own responses (bytes ÷ transfer time) — not a system network counter.</div>'
        : "";
      // -- System: the hardware row, compact -------------------------------- //
      const sysHtml = sect("System") +
        row("CPU", p.cpu_percent == null ? "—" : p.cpu_percent + "%") +
        row("Memory", _fmtBytes(p.rss_bytes)) +
        row("Scraping ↓", (dl == null ? "—" : _fmtBytes(dl) + "/s") +
            ` <span class="muted">· total ${_fmtBytes(sc.bytes_total)} · ${sc.fetches_total||0}×</span>`);
      $("vitals-body").innerHTML = nowHtml + planHtml + rateHtml + sysHtml;
      $("vitals-note").innerHTML = "";
    }
    // ---- T9: the visible-jobs section of the task manager ---- //
    let _jobsData = null;
    // The two resumable bulk-download kinds (wiki dumps + OSM regions) share the
    // SAME control grammar: pause (running) / up-down reorder (queued) / resume
    // (paused/failed). The reorder endpoint differs per kind (each manager owns
    // its own queue), so jobMove takes the kind. The id is "<prefix>:<key>"; the
    // key may itself contain ':' so slice after the FIRST colon, never a fixed N.
    const _isDownloadKind = (k) => k === "wiki-dump" || k === "osm-map";
    const _dlKey = (j) => j.id.slice(j.id.indexOf(":") + 1);
    const _reorderEndpoint = (k) => k === "osm-map" ? "/api/jobs/osm/reorder" : "/api/jobs/dumps/reorder";
    function _jobRow(j, queuedKeysByKind, t) {
        const pill = j.state === "running" ? "ok" : (j.state === "failed" ? "err" : "warn");
        let prog = "";
        if (j.progress && j.progress.total) {
          const pct = j.progress.percent || Math.round(100 * j.progress.done / j.progress.total);
          // EVERY progress was formatted as BYTES, but four producers publish counts
          // (items/stages/files/articles) -- so a re-index of 700,000 articles read
          // "700 kB / 1.4 MB" and a one-item import read "1 B / 1 B". The unit was
          // already travelling with the numbers; nothing read it.
          const unit = j.progress.unit || "bytes";
          const amount = unit === "bytes"
            ? `${_fmtBytes(j.progress.done)} / ${_fmtBytes(j.progress.total)}`
            : `${fmtNum(j.progress.done, 0)} / ${fmtNum(j.progress.total, 0)} ${esc(t(unit))}`;
          prog = `<div class="cap-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>` +
                 `<div class="muted" style="font-size:11px">${amount} · ${pct}%</div>`;
        }
        const acts = [];
        if (j.id === "collect:current") acts.push(`<button class="tiny danger" title="${esc(t("Stopping collection engages the network kill switch — the app goes offline."))}" onclick="jobCancel('${esc(j.id)}')">${esc(t("Stop"))}</button>`);
        if (_isDownloadKind(j.kind) && j.state === "running") acts.push(`<button class="tiny secondary" onclick="jobCancel('${esc(j.id)}')">${esc(t("Pause"))}</button>`);
        if (_isDownloadKind(j.kind) && j.state === "queued") {
          const k = _dlKey(j), keys = queuedKeysByKind[j.kind] || [], idx = keys.indexOf(k);
          if (idx > 0) acts.push(`<button class="tiny secondary" onclick="jobMove('${esc(k)}', -1, '${esc(j.kind)}')" title="${esc(t("Move earlier in the queue"))}">\u2191</button>`);
          if (idx >= 0 && idx < keys.length - 1) acts.push(`<button class="tiny secondary" onclick="jobMove('${esc(k)}', 1, '${esc(j.kind)}')" title="${esc(t("Move later in the queue"))}">\u2193</button>`);
          acts.push(`<button class="tiny secondary" onclick="jobCancel('${esc(j.id)}')">${esc(t("Cancel"))}</button>`);
        }
        // Paused/failed downloads gain a Resume control (start() continues the
        // partial file). It routes through the ONE network-consent popup.
        if (_isDownloadKind(j.kind) && (j.state === "paused" || j.state === "failed"))
          acts.push(`<button class="tiny secondary" onclick="jobResume('${esc(j.id)}')">${esc(t("Resume"))}</button>`);
        // The whole-corpus re-index (Phase 1.1) is a DB-writer job pausable from here:
        // pause (running) stops between batches; resume continues from the persisted
        // cursor — so closing the tab no longer restarts it from article 0.
        if (j.kind === "reindex" && j.state === "running")
          acts.push(`<button class="tiny secondary" onclick="jobCancel('${esc(j.id)}')">${esc(t("Pause"))}</button>`);
        if (j.kind === "reindex" && (j.state === "paused" || j.state === "failed"))
          acts.push(`<button class="tiny secondary" onclick="jobResume('${esc(j.id)}')">${esc(t("Resume"))}</button>`);
        const qpos = j.queue_position ? ` <span class="muted">#${j.queue_position} ${esc(t("in queue"))}</span>` : "";
        return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;flex-wrap:wrap">` +
          `<span class="pill ${pill}">${esc(t(j.state))}</span><b style="font-size:12.5px">${esc(j.label)}</b>${qpos}` +
          `<span style="margin-inline-start:auto;display:flex;gap:4px">${acts.join("")}</span>` +
          `<div style="flex-basis:100%">${prog}</div></div>`;
    }
    async function _renderJobs() {
      const elA = $("jobs-body"), elQ = $("queue-body");
      if (!elA && !elQ) return;
      try { _jobsData = await api("/api/jobs"); }
      catch { if (elA) elA.innerHTML = ""; if (elQ) elQ.innerHTML = ""; return; }
      _paintJobs();
    }
    // Render from the cached _jobsData (no fetch) — so an optimistic reorder can move
    // a row INSTANTLY before the backend round-trip (maintainer 2026-06-21: prioritising
    // in the task manager must visually move the item).
    function _paintJobs() {
      const elA = $("jobs-body"), elQ = $("queue-body");
      if (!elA && !elQ) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (!_jobsData) return;
      const jobs = (_jobsData.jobs || []).filter(j => j.state !== "done");
      // Queue = jobs waiting their turn (each manager's single-download queue, in
      // order). Per-kind queued keys (dumps + OSM each have their OWN order), so a
      // reorder up/down never crosses kinds.
      const queued = jobs.filter(j => j.state === "queued")
                         .sort((a, b) => (a.queue_position || 0) - (b.queue_position || 0));
      const queuedKeysByKind = {};
      for (const j of queued) if (_isDownloadKind(j.kind))
        (queuedKeysByKind[j.kind] = queuedKeysByKind[j.kind] || []).push(_dlKey(j));
      // Active = everything else that is not done (a running pass, downloading
      // dumps, the in-flight fetch, the idle loop, paused/failed downloads).
      const active = jobs.filter(j => j.state !== "queued");
      if (elA) {
        elA.innerHTML = `<div class="vsect">${esc(t("Active"))}</div>` + (active.length
          ? active.map(j => _jobRow(j, queuedKeysByKind, t)).join("")
          : `<div class="muted" style="font-size:12px;padding:2px 0 6px">${esc(t("Nothing running right now — active tasks (a collection pass, downloads, the fetch on the wire) appear here."))}</div>`);
      }
      if (elQ) {
        let qHtml = `<div class="vsect">${esc(t("Queue"))}</div>` + (queued.length
          ? queued.map(j => _jobRow(j, queuedKeysByKind, t)).join("")
          : `<div class="muted" style="font-size:12px;padding:2px 0 6px">${esc(t("The queue is empty — downloads waiting their turn appear here, in order; use the arrows to reorder them."))}</div>`);
        // Read-only "Up next" preview of the COLLECTION pass order. The download
        // queue above is a fixed, reorderable list; the collection order is NOT — it
        // is re-randomised every pass (stratified by language + tag), so we show it
        // as an informative preview, never as reorderable rows (would imply a fixed
        // queue that doesn't exist). Reuses the plan already in _actData (the same
        // /api/scheduler/activity the window polls — no new endpoint, no new poll).
        const plan = (_actData && _actData.plan) || {};
        const ups = plan.next_targets || [];
        if (ups.length) {
          const more = Math.max(0, (plan.planned_total || 0) - ups.length);
          qHtml += `<div class="vsect">${esc(t("Up next this pass"))}</div>` +
            `<div class="cap-chips">` +
            ups.map(d => `<span class="cap-chip">${esc(d)}</span>`).join("") +
            (more ? `<span class="cap-chip muted">+${more}</span>` : "") + `</div>` +
            `<div class="muted" style="font-size:11px;padding:2px 0 6px">` +
            esc(t("Order is re-randomised every pass — stratified by language and tag, not a fixed queue.")) +
            `</div>`;
          // Show the ACTUAL strata the pass interleaves by (#5): the languages & tags
          // present, with real counts — not just the claim "stratified". A "·"-prefixed
          // key is the unknown/untagged bucket (shown muted). Sampled from the next
          // sources, re-randomised every pass (the note above already states it).
          const st = plan.strata || {};
          const _stratHtml = (rows) => (rows || []).map(x => {
            const bucket = String(x.key || "").startsWith("·");
            const label = bucket ? esc(t(x.key === "·untagged" ? "untagged" : "unknown")) : esc(x.key);
            return `<span class="cap-chip${bucket ? " muted" : ""}">${label}<span class="muted"> ·${x.n}</span></span>`;
          }).join("");
          if ((st.languages || []).length) {
            qHtml += `<div class="vrow"><span class="vk">${esc(t("Languages"))}</span>` +
              `<span class="vv cap-chips">${_stratHtml(st.languages)}</span></div>`;
          }
          if ((st.tags || []).length) {
            qHtml += `<div class="vrow"><span class="vk">${esc(t("Tags"))}</span>` +
              `<span class="vv cap-chips">${_stratHtml(st.tags)}</span></div>`;
          }
        }
        elQ.innerHTML = qHtml;
      }
    }
    async function jobCancel(id) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      try {
        const r = await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, {method: "POST"});
        if (typeof r.online === "boolean") _paintNetwork(r.online);
        toast(r.detail || t("Cancelled."));
        _renderJobs();
      } catch (e) { toast(e.message, "err"); }
    }
    async function jobResume(id) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      // A resume re-opens a network fetch -> the ONE consent popup first
      // (invariant #14; a no-op when already online). The download path itself
      // still refuses while the kill switch is engaged.
      if (typeof ensureOnline === "function" && !await ensureOnline(t("Resume a paused download"))) return;
      try {
        const r = await api(`/api/jobs/${encodeURIComponent(id)}/resume`, {method: "POST"});
        toast(r.detail || t("Resumed."));
        _renderJobs();
      } catch (e) { toast(e.message, "err"); }
    }
    async function jobMove(key, dir, kind) {
      const jobs = (_jobsData && _jobsData.jobs) || [];
      const queuedJobs = jobs.filter(j => j.state === "queued" && j.kind === kind)
                             .sort((a, b) => (a.queue_position || 0) - (b.queue_position || 0));
      const queued = queuedJobs.map(_dlKey);
      const i = queued.indexOf(key);
      if (i < 0 || i + dir < 0 || i + dir >= queued.length) return;
      [queued[i], queued[i + dir]] = [queued[i + dir], queued[i]];
      // OPTIMISTIC: renumber the cached jobs to the new order and repaint NOW, so the
      // row visibly moves immediately (the backend round-trip + next poll reconcile it).
      queued.forEach((k, idx) => {
        const j = queuedJobs.find(x => _dlKey(x) === k);
        if (j) j.queue_position = idx + 1;
      });
      _paintJobs();
      try { await api(_reorderEndpoint(kind), {method: "POST", body: JSON.stringify({keys: queued})}); _renderJobs(); }
      catch (e) { toast(e.message, "err"); _renderJobs(); }   // revert to backend truth on failure
    }
    // ---- Schedule tab (CLAUDE.md #20 REMAINING "Sources/Schedule") ---- //
    // Reads the SAME _actData that _pollVitals already fetched from
    // /api/scheduler/activity (no new endpoint, no extra poll). Renders only
    // REAL scheduler facts: whether collection is running/idle/stopped, the
    // current pass progress (DOMAIN only — never a full URL), the cadence
    // (continuous vs every interval_minutes), the last run, and the backend's
    // OWN next_run timestamp. The next-pass time is NEVER fabricated as a
    // precise countdown — its method (last run + the inter-pass gap) is stated
    // in the #oo-tip hover bubble. Honest empty state when nothing is scheduled.
    function _renderSchedule() {
      const el = $("sched-tm-body");
      if (!el) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const a = _actData;
      if (!a) {  // the activity poll has not landed yet (or failed transiently)
        el.innerHTML = `<div class="muted" style="font-size:12px;padding:2px 0 6px">` +
          `${esc(t("No collection scheduled or running right now — when collection is on, the schedule appears here."))}</div>`;
        return;
      }
      const s = a.settings || {};
      const pg = a.progress;
      const row = (k, val) => `<div class="vr"><span>${k}</span><b>${val}</b></div>`;
      const sect = (x) => `<div class="vsect">${x}</div>`;
      // -- State: the real thread state, never a simulated "healthy" ---------- //
      let stateHtml;
      if (a.active) {
        stateHtml = `<span class="pill ok">${esc(t("running — collection in progress"))}</span>`;
      } else if (a.running) {
        stateHtml = `<span class="pill ok">${esc(t("running"))}</span>`;
      } else {
        stateHtml = `<span class="pill">${esc(t("stopped"))}</span>`;
      }
      // -- Current pass progress (domains only, the real bar) ----------------- //
      let nowHtml;
      if (pg && pg.total) {
        const pct = Math.round(100 * Math.min(pg.done, pg.total) / pg.total);
        nowHtml = row(t("Current pass"),
            `${esc(pg.current || "…")} <span class="muted">· ${esc(pg.mode || "")}</span>`) +
          `<div class="cap-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">` +
          `<div class="cap-fill" style="width:${pct}%"></div><span class="cap-txt">${pg.done}/${pg.total} · ${pct}%</span></div>`;
      } else {
        nowHtml = row(t("Current pass"), `<span class="muted">${esc(t("idle — no pass in flight"))}</span>`);
      }
      // -- Cadence: continuous (the default) vs a fixed interval -------------- //
      // No bare "every"/"min" fragments (the i18n engine does not interpolate):
      // each branch is ONE complete translatable phrase; the real interval is
      // shown as a separate number so the figure stays honest and locale-clean.
      let cadence;
      if (s.continuous) {
        cadence = `<span title="${esc(t("Continuous: passes run back-to-back with only a short gap while online. Going offline stops the loop."))}">${esc(t("continuous (back-to-back passes)"))}</span>`;
      } else {
        const mins = s.interval_minutes != null ? esc(String(s.interval_minutes)) : "—";
        cadence = `<span title="${esc(t("Legacy cadence: one pass, then wait the interval before the next."))}">` +
          `<b>${mins}</b> ${esc(t("minutes between passes"))}</span>`;
      }
      // -- Next pass: the backend's REAL next_run; method stated, not faked --- //
      let nextHtml;
      if (!a.running) {
        nextHtml = row(t("Next pass"), `<span class="muted">${esc(t("not scheduled — collection is stopped"))}</span>`);
      } else if (a.active) {
        nextHtml = row(t("Next pass"), `<span class="muted">${esc(t("a pass is running now"))}</span>`);
      } else if (a.next_run) {
        // next_run is a real server timestamp (last run + the inter-pass gap).
        // We show the honest relative time; the exact local moment + the method
        // live in the hover bubble — never a precise live countdown we invent.
        nextHtml = row(t("Next pass"),
          `<span title="${esc(fmtLocal(a.next_run))} · ${esc(t("Computed as the last run plus the inter-pass gap; robots delays can stretch it."))}">` +
          `${esc(fmtRelative(a.next_run))}</span>`);
      } else {
        nextHtml = row(t("Next pass"), `<span class="muted">${esc(t("scheduled — timing not yet known"))}</span>`);
      }
      // -- Last run (read straight from the scheduler) ------------------------ //
      const lastHtml = a.last_run
        ? row(t("Last run"), `<span title="${esc(fmtLocal(a.last_run))}">${esc(fmtRelative(a.last_run))}</span>`)
        : row(t("Last run"), `<span class="muted">${esc(t("no run yet"))}</span>`);
      const modeHtml = row(t("Mode"), `<span class="muted">${esc(s.mode || a.mode || "")}</span>`);
      el.innerHTML =
        sect(t("Collection")) +
        `<div class="vr"><span>${esc(t("State"))}</span><b>${stateHtml}</b></div>` +
        nowHtml +
        sect(t("Schedule")) +
        `<div class="vr"><span>${esc(t("Cadence"))}</span><b>${cadence}</b></div>` +
        nextHtml + lastHtml + modeHtml +
        _housekeepingHtml(a.housekeeping, t, row, sect) +
        `<div class="vnote">${esc(t("These are the scheduler’s own facts — the schedule is managed in Settings. Times are relative; hover for the exact local moment and the method."))}</div>`;
    }
    // The last housekeeping lane's own tallies, rendered from what it ACTUALLY
    // reported — the calendar-feed verification rides the collect pass now
    // (there is no manual button), so this is where a user sees it happening.
    // Absent keys render nothing rather than a fabricated zero: a lane that did
    // not run this pass has no number to show.
    function _housekeepingHtml(hk, t, row, sect) {
      if (!hk || typeof hk !== "object") return "";
      if (hk.skipped) {
        return sect(t("Background work")) +
          row(t("Housekeeping"), `<span class="muted">${esc(t("paused — airplane mode is engaged"))}</span>`);
      }
      const cal = hk.calendar;
      if (!cal || typeof cal !== "object") return "";
      const rows = [];
      // A broken verification is SAID, never hidden behind an absent row — the
      // absence of a number must not read the same as "nothing was due".
      if (cal.verify_error) {
        rows.push(row(t("Calendar feeds checked"),
          `<span class="pill warn" title="${esc(String(cal.verify_error))}">${esc(t("check failed — see the diagnostics log"))}</span>`));
      }
      if (cal.verified != null) {
        const ok = cal.verified_ok || 0, bad = cal.verified_failed || 0;
        rows.push(row(
          `<span title="${esc(t("Calendar feeds are checked a few at a time on each pass, never at startup. A feed that fails is re-checked after 1 month, then 2, 4 and 6 — capped, so it is never written off."))}">${esc(t("Calendar feeds checked"))}</span>`,
          `${cal.verified} <span class="muted">· ${ok} ${esc(t("reachable"))} · ${bad} ${esc(t("failed"))}</span>`));
      }
      if (cal.imported != null) {
        const off = cal.backed_off
          ? ` <span class="muted">· ${cal.backed_off} ${esc(t("waiting on a re-check"))}</span>` : "";
        rows.push(row(t("Calendar events imported"), `${cal.imported}${off}`));
      }
      return rows.length ? sect(t("Background work")) + rows.join("") : "";
    }
    // Per-tag scraping COVERAGE (the "how far has collection reached" view).
    // Lazy: fetched only when the Coverage subtab is opened (its own read-only
    // endpoint, NOT part of the 2 s vitals poll), cached in _covData, refreshable.
    async function loadTagCoverage(force) {
      const el = $("cov-tm-body");
      if (!el) return;
      if (_covData && !force) { _renderCoverage(); return; }
      if (_covLoading) return;
      _covLoading = true;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      el.innerHTML = `<div class="muted" style="font-size:12px;padding:2px 0 6px">${esc(t("Loading coverage…"))}</div>`;
      try { _covData = await api("/api/scheduler/coverage"); }
      catch { _covData = null; }
      // The per-language equilibrium lever is OPTIONAL (default off) — best-effort,
      // its absence never blocks the coverage view.
      try { _covEq = await api("/api/scheduler/equilibrium"); }
      catch { _covEq = null; }
      _covLoading = false;
      _renderCoverage();
    }
    function _renderEquilibrium(t) {
      const e = _covEq;
      if (!e) return "";
      const sect = (x) => `<div class="vsect">${x}</div>`;
      if (!e.enabled) {
        return sect(t("Language equilibrium")) +
          `<div class="vr"><span>${esc(t("Cadence lever"))}</span><b><span class="pill">${esc(t("off"))}</span></b></div>` +
          `<div class="vnote">${esc(t("Optional: re-check over-represented languages less often to steer the corpus mix toward a target you set in Settings. Off = the pure random rotation. Never excludes a source."))}</div>`;
      }
      const langs = Object.keys(e.target || {}).sort((a, b) => (e.target[b] - e.target[a]));
      const rows = langs.map(l => {
        const cur = Math.round(100 * ((e.corpus_shares || {})[l] || 0));
        const tgt = Math.round(100 * (e.target[l] || 0));
        const pace = (e.pace || {})[l];
        const paceTxt = (pace != null && pace < 1)
          ? `<span class="muted" title="${esc(t("Re-check cadence multiplier (1 = full speed)"))}">· ${esc(t("pace"))} ${pace.toFixed(2)}</span>` : "";
        return `<div class="vr"><span>${esc(l.toUpperCase())}</span>` +
          `<b>${cur}% <span class="muted">→ ${tgt}%</span> ${paceTxt}</b></div>`;
      }).join("");
      return sect(t("Language equilibrium")) +
        `<div class="vr"><span>${esc(t("Cadence lever"))}</span><b><span class="pill ok">${esc(t("on"))}</span></b></div>` +
        rows +
        `<div class="vnote">${esc(t("Corpus share → target; over-represented languages are re-checked less often (pace < 1). A cadence nudge, never an exclusion — set in Settings."))}</div>`;
    }
    function _covBar(reach, fresh, total) {
      // A single honest bar: reach fills it (fresh is the brighter leading part);
      // the unfilled remainder is what has not been reached yet. Counts only.
      const rp = total ? Math.round(100 * reach / total) : 0;
      const fp = total ? Math.round(100 * fresh / total) : 0;
      return `<div class="cap-bar" role="progressbar" aria-valuenow="${rp}" aria-valuemin="0" aria-valuemax="100">` +
        `<div class="cap-fill" style="width:${rp}%;opacity:.55"></div>` +
        `<div class="cap-fill" style="width:${fp}%"></div>` +
        `<span class="cap-txt">${reach}/${total} · ${rp}%</span></div>`;
    }
    function _renderCoverage() {
      const el = $("cov-tm-body");
      if (!el) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const d = _covData;
      if (!d) {
        el.innerHTML = `<div class="muted" style="font-size:12px;padding:2px 0 6px">` +
          `${esc(t("Coverage is unavailable right now."))} ` +
          `<button class="lnk" onclick="loadTagCoverage(true)">${esc(t("Retry"))}</button></div>`;
        return;
      }
      const tot = d.totals || {};
      const tags = d.tags || [];
      const reachedTags = tags.filter(x => x.reached > 0).length;
      const sect = (x) => `<div class="vsect">${x}</div>`;
      const head =
        sect(t("Collection coverage")) +
        `<div class="vr"><span>${esc(t("Tags with any coverage"))}</span><b>${reachedTags}/${tags.length}</b></div>` +
        `<div class="vr"><span>${esc(t("RSS sources reached"))}</span><b>${tot.reached || 0}/${tot.total || 0} · ${Math.round(100 * (tot.reach_pct || 0))}%</b></div>` +
        `<div class="vr"><span>${esc(t("Fresh in the last N hours"))}</span><b title="${esc(t("Freshness window (hours)"))}: ${esc(String(d.fresh_window_hours))}">${tot.fresh || 0} · ${Math.round(100 * (tot.fresh_pct || 0))}%</b></div>` +
        (tot.backed_off ? `<div class="vr"><span>${esc(t("Backed off (de-churn, not failures)"))}</span><b>${tot.backed_off}</b></div>` : "") +
        (d.crawl_sources ? `<div class="vr"><span>${esc(t("Crawl sources (reach not tracked)"))}</span><b>${d.crawl_sources}</b></div>` : "");
      // Per-tag rows, least-reached first (the backend already sorts them so —
      // the honest worklist of what still needs a pass).
      const rows = tags.map(x => {
        const badges = [];
        if (x.never_reached) badges.push(`<span class="muted">${x.never_reached} ${esc(t("not yet reached"))}</span>`);
        if (x.backed_off) badges.push(`<span class="muted">${x.backed_off} ${esc(t("backed off"))}</span>`);
        if (x.crawl) badges.push(`<span class="muted">${x.crawl} ${esc(t("crawl"))}</span>`);
        return `<div class="cov-row" style="padding:4px 0">` +
          `<div style="display:flex;justify-content:space-between;gap:8px">` +
          `<b style="font-size:12px">${esc(x.tag)}</b>` +
          `<span class="muted" style="font-size:11px">${badges.join(" · ")}</span></div>` +
          _covBar(x.reached, x.fresh, x.total) + `</div>`;
      }).join("");
      el.innerHTML = head + _renderEquilibrium(t) + sect(t("By tag")) + (rows || `<div class="muted">${esc(t("No tagged sources yet."))}</div>`) +
        `<div class="vnote">${esc(d.method || "")} ${esc(d.caveat || "")} ` +
        `<button class="lnk" onclick="loadTagCoverage(true)">${esc(t("Refresh"))}</button></div>`;
    }

    // The arbitration ASK (ruled): a new heavy task while one runs is offered
    // a choice, never silently piled up. Dumps queue automatically (real
    // queue); collect/import ask proceed-or-wait.
    async function arbitrate(actionLabel, note) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      let d; try { d = await api("/api/jobs"); } catch { return true; }
      // Parallel across kinds is the DEFAULT (maintainer-amended): a wiki
      // dump downloading never blocks or nags article collection — only a
      // real DB-writer collision asks.
      if (!d.db_writers_busy) return true;
      const busy = (d.busy_with || []).join(", ");
      // "network task" was wrong for the collision this actually fires on -- it fires
      // ONLY on db_writers_busy, and a re-index is not a network task. Re-keyed, not
      // re-worded around, so the twelve reviewed translations carry the new claim.
      return confirm(`${t("Another job is writing to the database:")} ${busy}\n\n`
        + (note ? note + "\n\n" : "")
        + `${t("Start anyway? (Cancel waits — the running task keeps the bandwidth and the database writer to itself.)")} ${actionLabel}`);
    }

    // Task-manager window subtab switch (Tasks / System). The render targets
    // (#jobs-body, #vitals-body) are unchanged — the poll keeps filling them; we
    // only show/hide the panel that wraps each.
    function tmSelectTab(key) {
      document.querySelectorAll("#vitals-pop .tm-panel").forEach(p =>
        p.style.display = (p.id === "tm-" + key) ? "" : "none");
      // Repaint the Schedule panel from the data the poll ALREADY cached, so
      // switching to it is instant (no new fetch); the 2 s poll keeps it fresh.
      if (key === "schedule") _renderSchedule();
      if (key === "coverage") loadTagCoverage();
      // The storage footprint is a recursive disk walk — measure it lazily when the System
      // tab is opened (cached; the vitals poll never triggers it), so opening the tab is snappy.
      if (key === "system") renderStorageFootprint("vitals-storage");
    }
    // a11y focus management for the two non-native dialogs (palette, task manager)
    // -- the native <dialog>.showModal() modals trap focus implicitly (OO-D13-001).
    function _focusables(el) {
      if (!el) return [];
      return [...el.querySelectorAll(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),'
        + 'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
      )].filter(n => n.offsetParent !== null || n === document.activeElement);
    }
    function _trapTab(el, e) {
      if (e.key !== "Tab") return;
      const f = _focusables(el);
      if (!f.length) { e.preventDefault(); return; }  // keep focus inside even when empty
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    function toggleVitals() {
      const pop = $("vitals-pop"); if (!pop) return;
      _vitalsOpen = !_vitalsOpen;
      pop.hidden = !_vitalsOpen;
      const chip = $("activity"); if (chip) chip.setAttribute("aria-expanded", String(_vitalsOpen));
      if (_vitalsOpen) {
        _vitalsPrev = null;
        _vitalsPrevFocus = document.activeElement;  // restore on close
        const f = _focusables(pop); if (f.length) setTimeout(() => f[0].focus(), 30);
      } else if (_vitalsPrevFocus && _vitalsPrevFocus.focus) {
        try { _vitalsPrevFocus.focus(); } catch (_) { /* opener gone */ }
      }
      _ensureVitalsPoll();
    }
    // The task manager opens in its OWN browser tab (maintainer 2026-06-18) so it
    // can stay parked on the desktop while the user works in the app. A NAMED
    // window target ("oo-tasks") means re-clicking FOCUSES the existing tab
    // instead of piling up duplicates. The standalone /tasks page polls the same
    // /api/jobs · /api/scheduler · /api/system endpoints (no in-app popover state).
    function openTaskManager() {
      const w = window.open("/tasks", "oo-tasks");
      if (w && w.focus) { try { w.focus(); } catch (_) { /* popup blocked / cross-tab */ } }
    }
    // A full-screen terminal overlay that REPLACES the UI when the app stops
    // (shutdown or uninstall) — so the user can't keep clicking dead tabs against a
    // server that's gone (maintainer 2026-06-21). It also attempts window.close():
    // browsers only let a script close a script-opened tab, so this is best-effort —
    // the overlay is the reliable end-state + tells the user to close the tab.
    function _terminalOverlay(message, { tryClose = false } = {}) {
      let o = document.getElementById("oo-terminal-overlay");
      if (!o) { o = document.createElement("div"); o.id = "oo-terminal-overlay"; document.body.appendChild(o); }
      o.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;"
        + "justify-content:center;text-align:center;padding:24px;font-size:18px;line-height:1.5;"
        + "background:var(--bg,#111);color:var(--fg,#eee)";
      o.textContent = message;
      if (tryClose) {
        // Give the message a moment, then try to close (works only if scriptable).
        setTimeout(() => { try { window.close(); } catch (e) { /* not scriptable */ } }, 1200);
      }
    }
    // Shut the app down from the GUI (a visual equivalent of Ctrl-C; maintainer
    // 2026-06-21). Confirms first, then stops the server process — NOT uninstall,
    // NOT panic: the data directory, corpus and keys are untouched.
    async function appShutdown() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Shut down the app? The server will stop and you'll need to relaunch it. Your data is untouched.")))
        return;
      try {
        await api("/api/system/shutdown", {method: "POST", body: JSON.stringify({confirm: true})});
      } catch (e) { /* the server may drop the connection as it exits — expected */ }
      _terminalOverlay(t("The app is shutting down — you can close this tab."), {tryClose: true});
    }
    // Esc closes the task manager; Tab is trapped inside it (OO-D13-001).
    function vitalsKey(e) {
      if (e.key === "Escape") { e.preventDefault(); if (_vitalsOpen) toggleVitals(); return; }
      if (_vitalsOpen) _trapTab($("vitals-pop"), e);
    }

    // Backpressure: A1's heavy-load guard returns 429 + Retry-After when the server is
    // saturated (a spike of heavy analytics), and the slowapi rate limiter can too. A 429
    // means the request was REFUSED before doing any work, so a bounded retry that honours
    // Retry-After is safe for GET and POST alike — it reads as the app protecting itself,
    // never as breakage. After the retries are spent the caller sees the honest error.
    const _API_MAX_RETRIES = 4;
    const _API_RETRY_MAX_MS = 8000;
    let _busyNoticeAt = 0;
    function _noteBusyRetry() {
      const now = Date.now();
      if (now - _busyNoticeAt < 8000) return;  // one notice per burst — never a toast storm
      _busyNoticeAt = now;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      toast(t("The app is busy — retrying shortly…"), "warn");
    }
    // ins-convergence-window-cap-mismatch (P1, the api() half): a FastAPI/Pydantic
    // 422 response body's `detail` is an ARRAY of {type, loc, msg} objects, which
    // Error() string-coerces into the useless "[object Object],[object Object]" --
    // this is the SHARED error path for essentially every call made through api(),
    // so the fix applies everywhere a validation error can surface, not just the
    // endpoint the finding was reported against. A plain string `detail` (or none)
    // renders BYTE-IDENTICALLY to before -- only the Array case changes.
    // AMENDED 2026-07-29 (skeptic finding, same shared-path reasoning): a `detail`
    // can also be a PLAIN OBJECT. POST /api/llm/vllm/install returns one so the
    // frontend can tell an acknowledgeable warning from a hard refusal -- and a
    // bare object hits `msg = d`, which is truthy, so the old code returned the
    // OBJECT and `new Error(obj).message` rendered "[object Object]": the exact
    // string this helper exists to abolish, re-entered through the sibling case.
    // Prefer the object's own `error`/`detail`/`msg` prose; JSON.stringify only as
    // a last resort so a shape we did not anticipate is still readable.
    function _apiErrorMessage(data, res) {
      const d = data && data.detail;
      let msg;
      if (Array.isArray(d)) {
        msg = d.map((item) => (item && typeof item === "object" && item.msg) ? item.msg : JSON.stringify(item)).join("; ");
      } else if (d && typeof d === "object") {
        msg = d.error || d.detail || d.msg || JSON.stringify(d);
      } else {
        msg = d;
      }
      return msg || (res.status + " " + res.statusText);
    }
    // ------------------------------------------------------------------ //
    //  Is the server actually there? (field report 2026-08-07, item 4)     //
    // ------------------------------------------------------------------ //
    // loadHealth() runs ONCE, at boot, so the green "healthy" pill was a
    // boot-time paint that could never go red: the app could be dead and the
    // chrome would still say healthy. A dedicated health poll is the wrong
    // repair -- this app already carries a measured polling-storm lesson
    // (~10k status polls in one 2h session) -- and it is unnecessary, because
    // every request the UI makes is already evidence.
    //
    // THE DISTINCTION THAT MAKES THIS HONEST: a rejected fetch means the
    // server did not answer. An HTTP error status means it answered, and said
    // no -- which is a working server, so it must NOT paint the app as down.
    // api() is the one chokepoint every call goes through, so recording the
    // outcome there costs nothing and cannot miss a caller.
    const _DOWN_STRIKES = 3;      // consecutive unanswered calls before the crash screen
    let _downStreak = 0;
    let _lastReachableAt = Date.now();
    let _serverDown = false;
    function _noteReachable(ok) {
      if (ok) {
        _downStreak = 0;
        _lastReachableAt = Date.now();
        if (_serverDown) { _serverDown = false; _paintCrashScreen(); }
        _paintHealth(true);
        return;
      }
      _downStreak++;
      _paintHealth(false);
      // One blip is a blip. Only a run of unanswered calls is an outage -- and
      // the screen below states what was observed, never a diagnosis of why.
      if (_downStreak >= _DOWN_STRIKES && !_serverDown) {
        _serverDown = true;
        _paintCrashScreen();
      }
    }
    function _paintHealth(ok) {
      const el = $("health"); if (!el) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      el.innerHTML = ok
        ? '<span class="dot ok"></span> ' + esc(t("healthy"))
        : '<span class="dot err"></span> ' + esc(t("not responding"));
    }

    // The honest crash screen (maintainer rulings 17-19, 2026-08-07).
    //
    // RULING 19 IS "NO AUTO-RESTART -- honesty first", and it shapes everything
    // here. This screen does not reload, does not retry in the background, and
    // does not reconnect and carry on as if nothing happened. It says what was
    // OBSERVED -- calls stopped being answered, and when the last one was -- and
    // leaves every action to the reader.
    //
    // It also refuses to diagnose. From the browser, "crashed", "killed",
    // "shutting down" and "the machine went to sleep" are indistinguishable:
    // all four are just silence. Naming one would be a fabricated cause on the
    // screen a reader trusts most, so the wording stays at what is known.
    //
    // THE RUN-JOURNAL LINK IS CONDITIONAL, and that is the point rather than a
    // limitation: the journal lives behind /api/diagnostics/run-journal, so if
    // the server is not answering, that download cannot work either. Offering
    // the button anyway would be a control that fabricates a capability. It
    // appears only once the server answers again, and until then the screen
    // says plainly why it is absent.
    // Each of these is ONE literal, deliberately: t() resolves a concatenation fine at
    // runtime, but the i18n audit's scan sees only the first fragment -- so a fully
    // keyed sentence would still be counted as untranslatable, and the gate would be
    // measuring something other than what ships. Hoisted rather than inlined only
    // because they are too long for the call site.
    const _CRASH_WHAT = "Requests to the local server are going unanswered. This page is still here, but it is showing you the last data it received, which may now be out of date.";
    const _CRASH_UNKNOWN = "What happened is not known from here: a stopped server, a crash and a sleeping machine look identical to this page. Nothing has been restarted for you.";
    const _CRASH_CORPUS = "Your corpus is on disk and is not affected by this. Relaunch the app the way you normally start it.";

    function _paintCrashScreen() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let o = document.getElementById("oo-crash-screen");
      if (!_serverDown) { if (o) o.remove(); return; }
      if (!o) {
        o = document.createElement("div");
        o.id = "oo-crash-screen";
        o.setAttribute("role", "alertdialog");
        o.setAttribute("aria-modal", "true");
        document.body.appendChild(o);
      }
      const secs = Math.max(0, Math.round((Date.now() - _lastReachableAt) / 1000));
      o.innerHTML =
        '<div class="crash-box">'
        + '<h2>' + esc(t("The app stopped answering")) + '</h2>'
        + '<p>' + esc(t(_CRASH_WHAT)) + '</p>'
        + '<p class="card-caveat">' + esc(t(_CRASH_UNKNOWN)) + '</p>'
        + '<p class="muted" id="crash-since"></p>'
        + '<div class="crash-actions">'
        + '<button id="crash-retry">' + esc(t("Check again")) + '</button>'
        + '<span id="crash-journal"></span>'
        + '</div>'
        + '<p class="hint">' + esc(t(_CRASH_CORPUS)) + '</p>'
        + '</div>';
      // tf() so the number is DATA interpolated into a keyable frame, never a
      // sentence built by concatenation (the composite-string i18n rule).
      const since = $("crash-since");
      if (since) {
        since.textContent = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf("Last answered {seconds}s ago.", {seconds: secs})
          : "Last answered " + secs + "s ago.";
      }
      const btn = $("crash-retry");
      if (btn) {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = t("Checking…");
          try {
            await api("/api/health");   // success clears _serverDown via _noteReachable
          } catch (e) {
            btn.disabled = false;
            btn.textContent = t("Check again");
            const s = $("crash-since");
            if (s) s.textContent = t("Still not answering.");
          }
        });
      }
      // Only reachable-again offers the journal, because only then can it load.
      const jslot = $("crash-journal");
      if (jslot) {
        jslot.innerHTML = '<span class="hint">'
          + esc(t("The run journal cannot be downloaded while the server is not answering."))
          + '</span>';
      }
    }

    async function api(path, opts={}) {
      _bumpInflight(1);
      try {
        for (let attempt = 0; ; attempt++) {
          let res;
          try {
            res = await fetch(path, {
              headers: {"Content-Type": "application/json"}, ...opts,
            });
          } catch (netErr) {
            // The fetch itself failed: no response at all. This is the only
            // shape that means "the server is not there".
            _noteReachable(false);
            throw netErr;
          }
          _noteReachable(true);  // it answered -- an error STATUS is still an answer
          if (res.status === 429 && attempt < _API_MAX_RETRIES) {
            const ra = parseFloat(res.headers.get("Retry-After"));
            const waitMs = Math.min(
              (isFinite(ra) && ra >= 0) ? ra * 1000 : 500 * (attempt + 1), _API_RETRY_MAX_MS);
            _noteBusyRetry();
            await new Promise((r) => setTimeout(r, waitMs));
            continue;  // 429 = refused before work; re-issuing is safe
          }
          const text = await res.text();
          let data; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
          if (res.status === 503 && data && data.locked) { location.replace("/unlock"); throw new Error(data.detail); }
          if (!res.ok) {
            // ADDITIVE (2026-07-29): the message is unchanged; the STRUCTURED detail
            // and status ride along so a caller that can act on a machine-readable
            // refusal (e.g. an acknowledgeable vLLM-install 409) is not forced to
            // re-parse prose. Every existing `catch (e) { ... e.message }` is
            // byte-identical.
            const err = new Error(_apiErrorMessage(data, res));
            err.status = res.status;
            err.detail = data && data.detail;
            throw err;
          }
          return data;
        }
      } finally { _bumpInflight(-1); }
    }

    // Poll a background-job status endpoint to a terminal state and hand back the
    // FINAL status. The heavy button actions (governments load / enrich source types /
    // keyword-tag backfill) now return {started, job:{...}} and finish in a daemon
    // thread — so a caller must poll ``.../status`` instead of parsing the immediate
    // response, or it reports the empty start-state as a false result (the #595/A2
    // contract break: "Loaded 0 figures." / "Typed 0 of 0" / "Tagged undefined"). The
    // job status shape is src/jobs/background.py:BackgroundJob.status() —
    // {state: idle|running|done|cancelled|error, done, total, detail, progress,
    //  error, result, ...}. Returns the last status on timeout (never hangs forever) —
    //  marked `timedOut: true` so a caller can tell "we stopped WATCHING" apart from
    //  "the job finished": a non-terminal status carries the empty/partial start-state
    //  tallies, and toasting those as a result would fabricate a completion ("Loaded 0
    //  figures." for a job still running). Use _jobStillRunning(st) at the call site.
    async function pollJobStatus(statusUrl, opts = {}) {
      const intervalMs = opts.intervalMs || 1500;
      const maxMs = opts.maxMs || 1800000;  // 30 min: enrich-source-types can run ~8 min
      const onProgress = opts.onProgress;
      const t0 = Date.now();
      let last = null;
      while (true) {
        last = await api(statusUrl);
        if (onProgress) { try { onProgress(last); } catch (e) {} }
        const st = last && last.state;
        if (st === "done" || st === "error" || st === "cancelled" || st === "idle") return last;
        if (Date.now() - t0 > maxMs) {
          // Give up POLLING, not the job: it keeps running server-side.
          if (last && typeof last === "object") last.timedOut = true;
          return last;
        }
        await new Promise((r) => setTimeout(r, intervalMs));
      }
    }

    // True when a pollJobStatus result means the job has NOT reached a terminal state
    // (we stopped watching, it is still running). Callers must report that honestly
    // instead of reading st.result — the not-yet-final tallies read as "0".
    function _jobStillRunning(st) {
      return !!st && (st.timedOut === true || st.state === "running");
    }

    // ===================================================================== //
    //  SHELL "0.05": navigation, customization, command palette, docs, home //
    //  Built on top of the existing (tested) feature functions below — this  //
    //  layer only changes what the user sees, not how the data works.        //
    // ===================================================================== //

    // The menu, as the user thinks of it (id ↔ human label ↔ intention group).
