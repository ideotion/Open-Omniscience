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
    const NAV = [
      {id:"home",     label:"Home",               grp:"Investigate"},
      {id:"search",   label:"Search",             grp:"Investigate"},
      {id:"insights", label:"Insights",           grp:"Investigate"},
      {id:"timemap",  label:"World map",          grp:"Investigate"},
      {id:"wiki",     label:"Wikipedia",          grp:"Investigate"},
      {id:"law",      label:"Governments",        grp:"Investigate"},
      {id:"agenda",   label:"Agenda",             grp:"Investigate"},
      {id:"indices",  label:"Indices",            grp:"Investigate"},
      {id:"markets",  label:"Commodities",        grp:"Investigate"},
      {id:"ingest",   label:"Collect",            grp:"Collect"},
      {id:"sources",  label:"Sources",            grp:"Collect"},
      {id:"library",  label:"Library",            grp:"Collect"},
      {id:"custody",  label:"Evidence & custody", grp:"Trust"},
      {id:"integrity",label:"Source integrity",   grp:"Trust"},
      // Settings is NOT a menu item (maintainer-ruled 2026-06-10: the top-bar
      // gear button is the single entry; a duplicate menu row was confusing).
      // Help is ALSO not a sidebar item (maintainer-ruled 2026-06-15: the top-bar
      // "?" icon is sufficient). Both stay registered/LOCKED so deep-links, the
      // command palette and the top-bar buttons keep working.
      {id:"help",     label:"Help & docs",        grp:"System"},
    ];
    // Always-available tools can't be hidden, so the user can never lock themselves out.
    const LOCKED = new Set(["home","settings","help"]);

    // -- Tab navigation ----------------------------------------------------- //
    // Every entry is an ARROW, never a bare function reference. A bare reference is
    // evaluated when this object literal is BUILT, so it depends on the loader having
    // been hoisted -- which holds only while the whole UI engine is one script. The
    // arrow defers the lookup to the click, so load order stops mattering. This is the
    // shape _ADV_LOADERS, _LIB_VIEW_LOADERS, LIVE and this table's own `library:` entry
    // already use; the twelve bare references here were the only construct in the file
    // that reached forward across the module split (measured: 12 forward refs, all here,
    // and zero TDZ references anywhere -- docs/design/APPJS_DECOMPOSITION_2026-08-20.md).
    const TAB_LOADERS = {
      home: () => loadHome(),
      search: () => buildSearchTimeScope(),   // mount the ooTimeScope date-range control once
      indices: () => loadIndices(),
      markets: () => loadMarkets(),
      insights: () => loadInsights(),
      timemap: () => loadOoMapCoverage(),   // slice 5b: the Map tab is now the unified ooMap (the temporal map was folded in + retired)
      law: () => loadGovernments(),   // Governments tab (Countries · Map · Law subtabs)
      agenda: () => loadAgenda(),
      library: () => { _wireLibraryViews(); },  // per-view lazy loaders (2026-08-01 ruling 9); stats ride the live poller (startLive)
      custody: () => loadCustody(),
      integrity: () => loadIntegrity(),
      settings: () => loadSettings(),
      help: () => loadDocs(),
    };
    const _loaded = new Set();

    // Facet subtabs live JUST UNDER the status bar (maintainer 2026-06-20): each tab's
    // ooSubtabs nav is relocated into #subtab-strip the first time the tab is shown —
    // moving the DOM node preserves its listeners + active state — then only the active
    // tab's nav is displayed. Tabs without facet subtabs hide the strip.
    const _SUBTAB_NAV = {
      analyze: "an-subtabs", insights: "ins-subtabs", settings: "set-subtabs",
      agenda: "agenda-views", indices: "indices-cats", markets: "commodities-cats",
      law: "gov-subtabs",   // Governments: Countries · Map · Law
      timemap: "oomap-lenses",   // World map: Coverage · Stories · Places · Server IPs (field-test Item 6)
      library: "library-views",  // Library: Overview · Activity · Tracked · Database & storage · World coverage
    };
    function _relocateSubtabs(name) {
      const strip = $("subtab-strip"); if (!strip) return;
      const id = _SUBTAB_NAV[name];
      if (id) { const nav = $(id); if (nav && nav.parentNode !== strip) strip.appendChild(nav); }
      let any = false;
      Array.prototype.forEach.call(strip.children, (ch) => {
        const on = !!id && ch.id === id;
        ch.style.display = on ? "" : "none";
        if (on) any = true;
      });
      strip.hidden = !any;
    }
    function showTab(name, push = true) {
      if (name === "database") name = "library";  // legacy #database deep-links
      if (name === "ingest") {  // Collect moved into Settings → Advanced → Collection
        showTab("settings", push);
        _openAdvanced("collect");
        return;
      }
      if (name === "sources") {  // Sources moved into Settings → Advanced → Sources
        showTab("settings", push);
        _openAdvanced("sources");
        return;
      }
      if (name === "wiki") {  // Wikipedia moved into Settings → Wikipedia (content-first §6)
        showTab("settings", push);
        try { _setSubtabs.select("wikipedia"); } catch (e) { showSetCat("wikipedia"); }
        return;
      }
      if (!document.getElementById("tab-" + name)) name = "home";
      document.querySelectorAll(".nav-item[data-tab]").forEach(b => {
        const on = b.dataset.tab === name;
        b.classList.toggle("active", on);
        if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
      });
      document.querySelectorAll(".tab-page").forEach(p =>
        p.classList.toggle("active", p.id === "tab-" + name));
      _relocateSubtabs(name);   // move this tab's facet subtabs into the top strip (under the status bar)
      if (TAB_LOADERS[name] && !_loaded.has(name)) { _loaded.add(name); TAB_LOADERS[name](); }
      // THEME-3: opening Analysis hydrates the restored active tab the first time (the
      // strip is restored at boot; the active tab's data loads lazily here), or shows
      // the launcher empty state when there are no tabs.
      if (name === "analyze" && !_anHydrated) {
        _anHydrated = true;
        _anFillLangSelect();   // populate the Advanced language <select> (flags + names)
        const tb = _anActiveId ? _anTabs.find(x => x.id === _anActiveId) : null;
        if (tb) { _anRenderStrip(); _anApplySeed(tb); }
        else if (!_anTabs.length) _anShowEmpty();
      }
      if (name !== "timemap" && typeof stopTmapPlay === "function") stopTmapPlay();  // don't animate a hidden tab
      startLive(name);                                  // live status for the active tab
      document.body.classList.remove("nav-open");       // close mobile drawer
      closePalette();
      const m = document.querySelector("main"); if (m) m.scrollTop = 0;
      window.scrollTo(0, 0);
      // Each user tab-switch PUSHES a history entry so the browser Back button
      // moves between visited tabs (it used to replaceState, leaving no entries —
      // so Back escaped the app, landing on /unlock). popstate re-renders without
      // re-pushing; the initial load (below) replaces, so /home isn't a dead Back.
      if (location.hash !== "#" + name) {
        if (push) history.pushState(null, "", "#" + name);
        else history.replaceState(null, "", "#" + name);
      }
    }
    document.querySelectorAll(".nav-item[data-tab]").forEach(b =>
      b.addEventListener("click", () => showTab(b.dataset.tab)));
    // Back/Forward navigates the tab history (render only — the URL already moved).
    window.addEventListener("popstate", () =>
      showTab((location.hash || "#home").slice(1), false));
    // imp-ghost-modal-after-back (P1): no popstate listener anywhere closed an open
    // <dialog> -- browser Back while e.g. #ux-export was open left the tab underneath
    // repainted while the dialog's native modal top-layer backdrop stayed active,
    // blocking every click with no visual cue (only Escape recovered). Close EVERY
    // open dialog on Back/Forward via the one shared native mechanism -- this covers
    // all of them (#ux-import/#ux-export/#chart-enlarge/#synth-window/#link-preview/
    // #wiki-tc/#folder-picker/#net-consent/#guide-wizard/#corpus-win), not just one.
    //
    // A BARE .close() is not enough: per the <dialog> spec it fires only "close",
    // never "cancel" -- and #net-consent's ensureOnline() Promise only ever resolves
    // via its ok/cancel click handlers OR dlg.oncancel (the same for #guide-wizard's
    // closeGuide bookkeeping, wired to "cancel"). A bare .close() would silently
    // ORPHAN that Promise forever (every ensureOnline() caller hangs with no error),
    // and leave the guide marked not-done. Dispatch a synthetic "cancel" first (the
    // same signal Escape sends) so each dialog's own resolve/cleanup path runs --
    // resolving #net-consent as `false` ("stay offline"), the same safe default as
    // Esc -- THEN force-close (a no-op if the cancel handler already closed it).
    window.addEventListener("popstate", () =>
      document.querySelectorAll("dialog[open]").forEach((d) => {
        d.dispatchEvent(new Event("cancel", {cancelable: true}));
        d.close();
      }));

    // -- Appearance / customization (local-only, never transmitted) --------- //
    const UI_KEY = "oo.ui";
    const UI_DEFAULTS = {theme:"ink", accent:"", density:"comfortable", face:"", sidebar:"expanded"};
    const THEMES = [
      {id:"ink",name:"Ink",c:"#5b9dd9"}, {id:"slate",name:"Slate",c:"#7aa2f7"},
      {id:"midnight",name:"Midnight",c:"#8b7dff"}, {id:"arctic",name:"Arctic",c:"#88c0d0"},
      {id:"cyber",name:"Cyber",c:"#22d3ee"}, {id:"forest",name:"Forest",c:"#6fbf73"},
      {id:"aubergine",name:"Aubergine",c:"#c084fc"}, {id:"garnet",name:"Garnet",c:"#d96c7f"},
      {id:"solar",name:"Solar",c:"#b58900"}, {id:"sepia",name:"Sepia",c:"#d8a657"},
      {id:"terminal",name:"Terminal",c:"#36d97a"}, {id:"contrast",name:"Contrast",c:"#ffd400"},
      {id:"light",name:"Light",c:"#2f6fb3"}, {id:"mist",name:"Mist",c:"#5e81ac"},
      {id:"dawn",name:"Dawn",c:"#b4637a"}, {id:"mint",name:"Mint",c:"#2e7d5b"},
      {id:"paper",name:"Paper",c:"#9a6a2f"}, {id:"system",name:"System",c:"#8c95a6"},
    ];
    const ACCENTS = ["", "#5b9dd9", "#7aa2f7", "#8b7dff", "#36d97a", "#e0698f", "#d9a441", "#e8743b", "#2bb3a3"];
    // Bundled OFL typefaces (/static/fonts). "" = the theme's own font; a pick
    // overrides every theme. Variable fonts carry the full weight range
    // (Inter/Outfit go down to Thin 100 — the maintainer's modern-thin ask).
    const FACES = [
      {id:"", name:"Theme default", ff:""},
      {id:"cantarell", name:"Cantarell", ff:'"Cantarell", system-ui, sans-serif'},
      {id:"inter", name:"Inter", ff:'"Inter", system-ui, sans-serif'},
      {id:"outfit", name:"Outfit", ff:'"Outfit", system-ui, sans-serif'},
      {id:"manrope", name:"Manrope", ff:'"Manrope", system-ui, sans-serif'},
      {id:"serif", name:"Source Serif", ff:'"Source Serif 4", Georgia, serif'},
      {id:"mono", name:"JetBrains Mono", ff:'"JetBrains Mono", ui-monospace, monospace'},
    ];

    function getUi() { try { return {...UI_DEFAULTS, ...JSON.parse(localStorage.getItem(UI_KEY) || "{}")}; }
      catch { return {...UI_DEFAULTS}; } }
    function saveUi(ui) { localStorage.setItem(UI_KEY, JSON.stringify(ui)); }

    function applyThemeAttr(theme) {
      const eff = theme === "system" ? (_media && _media.matches ? "light" : "")
                : theme === "ink" ? "" : theme;
      const r = document.documentElement;
      if (eff) r.setAttribute("data-theme", eff); else r.removeAttribute("data-theme");
    }
    function applyUi(ui) {
      const r = document.documentElement;
      applyThemeAttr(ui.theme);
      if (ui.accent) r.style.setProperty("--accent", ui.accent); else r.style.removeProperty("--accent");
      const face = FACES.find(f => f.id === (ui.face || ""));
      if (face && face.ff) r.style.setProperty("--ff", face.ff); else r.style.removeProperty("--ff");
      if (ui.density === "compact") r.setAttribute("data-density", "compact"); else r.removeAttribute("data-density");
      if (ui.sidebar === "collapsed") r.setAttribute("data-sidebar", "collapsed"); else r.removeAttribute("data-sidebar");
      // The sidebar-visibility feature was removed (#17, 2026-06-22): the flat nav is
      // always complete (every tab also reachable via the palette), so no nav-item is
      // ever hidden here. A legacy ui.hidden in stored prefs is simply ignored.
    }
    function setTheme(t)   { const u = getUi(); u.theme = t;   saveUi(u); applyUi(u); buildDrawer(); syncThemeSelect(); }
    function setAccent(a)  { const u = getUi(); u.accent = a;  saveUi(u); applyUi(u); buildDrawer(); }
    function setDensity(d) { const u = getUi(); u.density = d; saveUi(u); applyUi(u); buildDrawer(); }
    function setFace(f)    { const u = getUi(); u.face = f;    saveUi(u); applyUi(u); buildDrawer(); }
    function setSidebar(s) { const u = getUi(); u.sidebar = s; saveUi(u); applyUi(u); buildDrawer(); }
    function toggleSidebar(){ setSidebar(getUi().sidebar === "collapsed" ? "expanded" : "collapsed"); }
    function resetUi() { localStorage.removeItem(UI_KEY); applyUi(getUi()); buildDrawer(); syncThemeSelect();
      toast("Appearance reset to defaults."); }
    // theme-select-lossy-overwrite (P1): the Settings -> General panel's #set-theme
    // select is a lossy 3-way dark/light/system BUCKET of the full 17/18-theme value
    // (Settings -> Graphics is the authoritative picker). _lastSyncedThemeBucket
    // remembers which bucket syncThemeSelect() just assigned, so saveSettings() can
    // tell "the user left this alone" (skip re-applying the bucket default) apart
    // from "the user actually picked a different bucket here" (honor it).
    let _lastSyncedThemeBucket = null;
    function syncThemeSelect() { const t = getUi().theme; const sel = $("set-theme");
      const lightish = ["light", "paper", "mist", "dawn", "mint"];
      const bucket = (t === "system" ? "system" : lightish.includes(t) ? "light" : "dark");
      if (sel) sel.value = bucket;
      _lastSyncedThemeBucket = bucket; }

    // Appearance now lives in Settings → Appearance (the old drawer is gone).
    // openDrawer() is kept as the single "take me to appearance" entry point so the
    // command palette and any deep link still work; closeDrawer() is a safe no-op.
    function openDrawer()  { showTab("settings"); (_setSubtabs || {select: showSetCat}).select("graphics"); }
    function closeDrawer() { /* drawer removed — appearance is a Settings section */ }

    // -- Keyboard shortcuts (local-only, rebindable; UI-shell §4) ----------- //
    // The global shortcuts are stored on THIS DEVICE (localStorage), never transmitted.
    // The command palette (Ctrl/⌘-K) is bound by default; the rest are opt-in (default
    // unset) so a fresh install never hijacks a keystroke. One dispatcher reads the
    // bindings, so a rebind takes effect immediately without reloading.
    const KEYS_KEY = "oo.keys";
    const KB_DEFAULTS = { palette: "Mod+K", home: "", settings: "", airplane: "", help: "" };
    function getKeys() { try { return {...KB_DEFAULTS, ...JSON.parse(localStorage.getItem(KEYS_KEY) || "{}")}; }
      catch { return {...KB_DEFAULTS}; } }
    function saveKeys(k) { localStorage.setItem(KEYS_KEY, JSON.stringify(k)); }
    // Normalize a keydown into a canonical combo string ("Mod+K", "Alt+Shift+H"). Ctrl and
    // Cmd both fold to "Mod" (cross-platform). Returns "" while only a modifier is held.
    function _kbCombo(e) {
      const k = e.key;
      if (!k || ["Control", "Shift", "Alt", "Meta", "OS", "Dead"].includes(k)) return "";
      const parts = [];
      if (e.ctrlKey || e.metaKey) parts.push("Mod");
      if (e.altKey) parts.push("Alt");
      if (e.shiftKey) parts.push("Shift");
      parts.push(k.length === 1 ? k.toUpperCase() : k);
      return parts.join("+");
    }
    function _kbShow(c) { return c ? c.replace("Mod", "Ctrl/⌘") : ""; }
    function _kbInField(el) {
      const tag = el && el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el && el.isContentEditable);
    }
    function _kbActions() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return [
        { id: "palette",  label: t("Open the command palette"), always: true, run: () => openPalette() },
        { id: "home",     label: t("Go to Home"),               run: () => showTab("home") },
        { id: "settings", label: t("Open Settings"),            run: () => showTab("settings") },
        { id: "airplane", label: t("Toggle airplane mode"),     run: () => { if (typeof toggleNetwork === "function") toggleNetwork(); } },
        { id: "help",     label: t("Open Help"),                run: () => showTab("help") },
      ];
    }
    // The single global keydown dispatcher: Escape closes overlays; a bound combo runs its
    // action. A plain-key binding never fires while typing in a field; the palette (Mod-combo)
    // always may. Ctrl/⌘-K keeps its default behaviour unless the user rebinds it.
    function _kbDispatch(e) {
      if (e.key === "Escape") { closePalette(); closeDrawer(); document.body.classList.remove("nav-open"); return; }
      if (_kbRecording) return;   // a rebind capture is in progress
      const combo = _kbCombo(e); if (!combo) return;
      const binds = getKeys(), field = _kbInField(e.target);
      for (const a of _kbActions()) {
        if (binds[a.id] !== combo) continue;
        if (field && !a.always) continue;
        e.preventDefault(); a.run(); return;
      }
    }
    // Settings → Shortcuts: list the shortcuts + rebind the global ones (the recorder
    // captures the next keystroke). Reference rows document the fixed contextual keys.
    let _kbRecording = null;
    function loadShortcuts() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("kb-panel"); if (!host) return;
      const binds = getKeys();
      const rows = _kbActions().map(a => {
        const cur = binds[a.id];
        const chip = cur
          ? `<span class="kb-chip">${esc(_kbShow(cur))}</span>`
          : `<span class="muted">${esc(t("Not set"))}</span>`;
        return `<tr><td>${esc(a.label)}</td><td>${chip}</td>
          <td style="white-space:nowrap">
            <button class="secondary tiny" data-kb-change="${esc(a.id)}">${esc(t("Change"))}</button>
            <button class="secondary tiny" data-kb-clear="${esc(a.id)}"${cur ? "" : " disabled"}>${esc(t("Clear"))}</button>
          </td></tr>`;
      }).join("");
      const ref = [
        [t("Close overlays and dialogs"), "Esc"],
        [t("Move within lists and subtabs"), "← → ↑ ↓"],
        [t("Submit search / run the selection"), "Enter"],
      ].map(([lbl, k]) => `<tr><td>${esc(lbl)}</td><td><span class="kb-chip">${esc(k)}</span></td><td class="muted">${esc(t("Fixed"))}</td></tr>`).join("");
      host.innerHTML =
        `<table><thead><tr><th>${esc(t("Action"))}</th><th>${esc(t("Shortcut"))}</th><th></th></tr></thead><tbody>${rows}</tbody></table>
         <div style="margin:8px 0"><button class="secondary tiny" onclick="kbReset()">${esc(t("Reset to defaults"))}</button></div>
         <h3 style="margin-top:14px;font-size:14px">${esc(t("Fixed shortcuts"))}</h3>
         <p class="hint muted">${esc(t("These contextual keys are always available and are not rebindable."))}</p>
         <table><tbody>${ref}</tbody></table>`;
      host.querySelectorAll("[data-kb-change]").forEach(b =>
        b.addEventListener("click", () => kbRecord(b.getAttribute("data-kb-change"), b)));
      host.querySelectorAll("[data-kb-clear]").forEach(b =>
        b.addEventListener("click", () => kbClear(b.getAttribute("data-kb-clear"))));
    }
    function kbRecord(id, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_kbRecording) return;
      _kbRecording = id; btn.textContent = t("Press a key…"); btn.classList.add("kb-rec");
      function done() { document.removeEventListener("keydown", onKey, true); _kbRecording = null; }
      function onKey(e) {
        e.preventDefault(); e.stopPropagation();
        if (e.key === "Escape") { done(); loadShortcuts(); return; }   // cancel the capture
        const combo = _kbCombo(e); if (!combo) return;                 // wait for a real key
        const binds = getKeys();
        Object.keys(binds).forEach(k => { if (k !== id && binds[k] === combo) binds[k] = ""; });  // no dup
        binds[id] = combo; saveKeys(binds); done(); loadShortcuts();
      }
      document.addEventListener("keydown", onKey, true);   // capture: beats the global dispatcher
    }
    function kbClear(id) { const b = getKeys(); b[id] = ""; saveKeys(b); loadShortcuts(); }
    function kbReset() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      saveKeys({...KB_DEFAULTS}); loadShortcuts(); toast(t("Shortcuts reset to defaults."));
    }

    // Settings sections (Appearance · General · Wikipedia · Data · Safety).
    function showSetCat(cat) {
      // Button/ARIA state is owned by the ooSubtabs component; this callback
      // switches the panel + does the section's one-time setup.
      document.querySelectorAll("#tab-settings .set-view").forEach(v =>
        v.style.display = (v.id === "set-" + cat) ? "" : "none");
      if (cat !== "advanced") stopSchedRatePoll();  // the scheduler panel moved into Advanced
      // Graphics = Appearance + the alternative-interfaces gallery, fused (remark 11).
      if (cat === "graphics") {
        buildDrawer();                                                    // (re)paint theme/accent state
        if (window.OOGUIs && OOGUIs.renderGallery) OOGUIs.renderGallery();  // the GUIs gallery
      }

      if (cat === "agenda" && !AG.cals.length) loadAgenda();  // calendars/directory live here now
      // loadLlmPrompts/loadCustomPrompts are NOT here any more: their panels moved to
      // Advanced → AI and load when that section is expanded (2026-08-09).
      if (cat === "models") { loadOllamaInstall(); loadLlmModels(); loadLlmHealth(); _llmPullStartPoll(); loadLangDetectCount(); loadAiBackendPanel(); loadVllmStatusPanel(); loadAiSetup(); loadAiHero(); loadAiStore(); loadModelCatalog(); syncKeywordTriageToggle(); syncSourceTagsToggle(); syncPerceptionExtractToggle(); loadPerceptionGate(); syncAiCoordinator(); }  // LLM-management subtab (Q6) — also offer the binary installer + re-check the pill + show any in-progress pull + the dual-backend panel (B1/B2/B4) + the B5 progressive-sweep toggles + the B6 perception-extract toggle/gate
      if (cat === "advanced") _advWire();             // Collection / Sources / Keywords, lazily per section
      if (cat === "general") loadShortcuts();         // the shortcuts panel moved into General (2026-07-31)
      if (cat === "cards") loadCardCatalog();     // the Leads catalogue (PR-7): lazy, one loopback read
      if (cat === "wikipedia") loadWiki();            // moved Wikipedia tracking onShow (dumps load via loadSettings)
      if (cat === "offlinemap") loadOsmMap();         // OSM offline-map region downloads (Group M)
      if (cat === "safety") { loadAtRestState(); onUninstallMode(); }  // at-rest attestation + uninstall preview
      // The newsletter/PDF import panels moved into Data & backup (2026-07-31). Both
      // calls are cheap and loopback-only -- a count query and a job-status poll -- so
      // they load with the subtab rather than needing the Advanced lazy treatment.
      if (cat === "data") { loadNewsletterRemoveCount(); _folderImportStartPoll(); }
    }

    // ADVANCED subtab (2026-07-31 Settings review): Collection, Sources and Keywords moved
    // into folded <details> sections. Their loaders run when a SECTION IS EXPANDED, never
    // when the subtab is selected -- folded must not mean fetched. That distinction is not
    // cosmetic here: the source catalog can hold ~46k rows, and loading all three eagerly
    // would make opening Advanced the most expensive click in Settings.
    const _ADV_LOADERS = {
      collect:  () => { loadScheduler(); },
      // The system prompts and the operator's own extractors (maintainer 2026-08-09:
      // "move the entire Behaviour & prompts section to an AI section in the advanced
      // subtab"). They are a developer surface -- four full prompt textareas and a CRUD
      // form -- and having them under the AI tab made the page a console for a reader
      // who only wanted to switch AI on. Nothing is lost: both panels moved WHOLE, and
      // they load on expand rather than with the subtab.
      // The three progressive-sweep panels live in THIS section too, and their syncs were
      // left behind on the AI subtab when the markup moved -- so opening the section that
      // contains them never asked whether a run existed, and the download links (rendered
      // by the sync) could not appear where the panels actually are. Field report
      // 2026-08-13: "can't find your keyword triage button". A moved panel takes its
      // loader with it.
      ai:       () => {
        loadLlmPrompts(); loadCustomPrompts();
        syncKeywordTriageToggle(); syncSourceTagsToggle(); syncPerceptionExtractToggle();
      },
      sources:  () => { loadSrcFacets(); loadManagedSources(); loadCandidates(); },
      // Both quality gates + the scope toggles + the bulk catch-up (absorbed from the
      // Sources section, which now points here — never two homes for one control).
      qualification: () => { loadQualificationGates(); loadQualifyBulk(); },
      // The official-statistics producer DIRECTORY is source management, so it lives here;
      // the FIGURES surface moved to Governments → Statistics (2026-07-31).
      stats:    () => { loadStatAgencies(); },
      // loadKeywordFilter moved off loadSettings with its panel, so it loads here too.
      keywords: () => { loadKeywordExplorer(); loadFamilyCuration(); loadSupergroupCuration(); loadKeywordFilter(); },
      // The ~500-feed calendar catalogue: plumbing, so it moved out of the Agenda
      // subtab (invariant #8). It no longer loads with the agenda — only on expand.
      calendars: () => { loadFeedDir(); },   // loadFeedDir renders the user calendars too
      // The Bulletin (§16): last section, folded, and its availability check +
      // edition list run on EXPAND like the rest. Both are loopback.
      bulletin: () => { loadBulletin(); },
    };
    // Deep-link into one Advanced section. The old showTab("ingest") / showTab("sources")
    // redirects pointed at subtabs that no longer exist, so every palette entry and
    // "Collect now" button that used them would have landed on nothing. They now select
    // Advanced and OPEN the right section -- which also fires its toggle listener, so the
    // section loads exactly as if the user had opened it by hand.
    function _openAdvanced(section) {
      try { _setSubtabs.select("advanced"); } catch (e) { showSetCat("advanced"); }
      _advWire();
      const d = document.querySelector(`#set-advanced details.adv-sec[data-adv="${section}"]`);
      if (d && !d.open) d.open = true;
      if (d) d.scrollIntoView({block: "start"});
    }
    function _advWire() {
      document.querySelectorAll("#set-advanced details.adv-sec").forEach(d => {
        if (d.dataset.advWired === "1") return;
        d.dataset.advWired = "1";
        d.addEventListener("toggle", () => {
          if (!d.open || d.dataset.advLoaded === "1") return;
          d.dataset.advLoaded = "1";                       // load once, keep the data on re-collapse
          const load = _ADV_LOADERS[d.dataset.adv];
          if (!load) return;
          // One section failing must not take the others down with it.
          try { load(); } catch (e) { console.error("advanced section failed to load", d.dataset.adv, e); }
        });
      });
    }

    function buildDrawer() {
      const ui = getUi();
      $("dr-themes").innerHTML = THEMES.map(t =>
        `<button class="theme-card ${t.id === ui.theme ? "sel" : ""}" onclick="setTheme('${t.id}')">
           <span class="tdot" style="background:${t.c}"></span>${esc(t.name)}</button>`).join("");
      $("dr-accents").innerHTML = ACCENTS.map(a =>
        `<button class="sw ${a === ui.accent ? "sel" : ""}" title="${a || "Theme default"}"
           onclick="setAccent('${a}')" style="background:${a || "linear-gradient(135deg,var(--muted),var(--accent))"}"></button>`).join("");
      $("dr-density").innerHTML = ["comfortable", "compact"].map(d =>
        `<button class="${d === ui.density ? "sel" : ""}" onclick="setDensity('${d}')">${d[0].toUpperCase() + d.slice(1)}</button>`).join("");
      $("dr-faces").innerHTML = FACES.map(f =>
        `<button class="${f.id === (ui.face || "") ? "sel" : ""}" onclick="setFace('${f.id}')"
           style="${f.ff ? "font-family:" + esc(f.ff) : ""}">${esc(f.name)}</button>`).join("");
      $("dr-sidebar").innerHTML = [["expanded", "Expanded"], ["collapsed", "Collapsed"]].map(([v, l]) =>
        `<button class="${v === ui.sidebar ? "sel" : ""}" onclick="setSidebar('${v}')">${l}</button>`).join("");
      // (The "Tools shown in the sidebar" checklist was removed — #17, 2026-06-22.)
    }

    // -- Command palette = the OMNIBAR (Ctrl/⌘-K; T13 slice 1) -------------- //
    // Static commands (pages/actions/docs) match instantly; from 2 typed
    // characters the palette ALSO federates over the indexed data surfaces
    // (articles via FTS5, keywords, sources, wiki pages, law documents) —
    // debounced and sequence-guarded, never scan-on-type: the endpoint is
    // index-backed and discloses the true totals behind the first three.
    let _palItems = [], _palFiltered = [], _palSel = 0;
    let _omniLive = null, _omniTimer = null, _omniSeq = 0;
    function palCommands() {
      const pages = NAV.map(n => ({grp:"Pages", label:n.label, sub:n.grp, run:() => showTab(n.id)}));
      const actions = [
        {grp:"Actions", label:"Run a search", sub:"Search", run:() => { showTab("search"); setTimeout(() => $("q").focus(), 50); }},
        {grp:"Actions", label:"Collect now (one scraper pass)", sub:"Collect", run:() => { showTab("ingest"); schedulerRunNow(); }},
        {grp:"Actions", label:"Track Wikipedia now", sub:"Wikipedia", run:() => { showTab("wiki"); trackWikiNow(); }},
        {grp:"Actions", label:"Export / Back up…", sub:"Data & backup", run:() => { showTab("settings"); openUnifiedExport(); }},
        {grp:"Actions", label:"Open the User Manual", sub:"Help", run:() => { showTab("help"); openDoc("user-manual"); }},
        {grp:"Actions", label:"Open Settings", sub:"System", run:() => showTab("settings")},
        {grp:"Actions", label:"Customize appearance", sub:"Theme", run:() => openDrawer()},
        {grp:"Actions", label:"API reference (Swagger)", sub:"System", run:() => window.open("/docs", "_blank")},
      ];
      const docs = (_docList || []).map(d => ({grp:"Documentation", label:d.title, sub:"Doc",
        run:() => { showTab("help"); openDoc(d.slug); }}));
      return [...pages, ...actions, ...docs];
    }
    function openPalette() {
      _palItems = palCommands();
      _omniLive = null;
      _palPrevFocus = document.activeElement;  // a11y: restore focus on close (OO-D13-001)
      $("palOverlay").classList.add("open"); $("palette").classList.add("open");
      const i = $("pal-input"); i.value = ""; renderPalette(); setTimeout(() => i.focus(), 30);
    }
    function closePalette() {
      $("palOverlay").classList.remove("open"); $("palette").classList.remove("open");
      if (_palPrevFocus && _palPrevFocus.focus) {
        try { _palPrevFocus.focus(); } catch (_) { /* opener gone */ }
        _palPrevFocus = null;
      }
    }
    // The live half of the omnibar: items built from /api/search/omni results.
    // Each carries a run() like any static command, so keyboard navigation and
    // Enter work unchanged. Group headers disclose the TRUE total behind the
    // first three (the display bound never hides the magnitude).
    function _omniItems(q) {
      if (!_omniLive || _omniLive.q !== q) return [];
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const head = (label, g) => label + (g.total > (g.items || []).length ? ` · ${g.total} ${t("matches in total")}` : "");
      const out = [];
      (_omniLive.groups || []).forEach(g => {
        const items = g.items || [];
        if (!items.length) return;
        if (g.kind === "articles") {
          const grp = head(t("Articles"), g);
          items.forEach(it => out.push({grp, label: it.title || ("#" + it.article_id),
            sub: (it.published_at || "").slice(0, 10) || t("article"),
            run: () => window.open(it.url, "_blank")}));
        } else if (g.kind === "keywords") {
          const grp = head(t("Keywords"), g);
          items.forEach(it => {
            // S3: keyword -> super-group navigation. Plural membership renders every
            // group name (never picks one); the palette row's single action still
            // opens the keyword's own corpus window — the group VIEW is one more
            // click away via the Keywords-subtab chip (richer HTML there).
            const sgNote = (it.supergroups && it.supergroups.length)
              ? " · " + t("part of") + " ⊕ " + it.supergroups.map(g2 => g2.name).join(", ")
              : "";
            out.push({grp,
              label: it.term + (it.frequency ? ` (${it.frequency})` : ""),
              sub: t("opens its corpus window") + sgNote,
              run: () => openCorpus(it.normalized_term)});
          });
        } else if (g.kind === "sources") {
          const grp = head(t("Sources"), g);
          items.forEach(it => out.push({grp, label: it.name, sub: it.domain || "",
            run: () => showTab("sources")}));
        } else if (g.kind === "wiki") {
          const grp = head(t("Wikipedia"), g);
          // A content hit carries a reader url (open the LOCAL article); a watched-page
          // title hit (no url) jumps to the Wikipedia settings/tracker.
          items.forEach(it => out.push({grp, label: it.title, sub: it.wiki || "",
            run: it.url ? (() => window.open(it.url, "_blank")) : (() => showTab("wiki"))}));
        } else if (g.kind === "law") {
          const grp = head(t("World law"), g);
          items.forEach(it => out.push({grp, label: it.title,
            sub: (it.jurisdiction || "").toUpperCase(),
            run: () => showTab("law")}));
        }
      });
      return out;
    }
    function _omniFetch(q) {
      clearTimeout(_omniTimer);
      _omniTimer = setTimeout(async () => {
        const seq = ++_omniSeq;
        try {
          const d = await api("/api/search/omni?q=" + encodeURIComponent(q));
          if (seq !== _omniSeq) return;  // a newer keystroke superseded this reply
          _omniLive = d;
          if ($("palette").classList.contains("open") && $("pal-input").value.trim() === q) renderPalette();
        } catch (_e) { /* static commands still work; the server logs the why */ }
      }, 160);
    }
    function renderPalette() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const raw = $("pal-input").value.trim();
      const q = raw.toLowerCase();
      const statics = _palItems.filter(it => !q ||
        it.label.toLowerCase().includes(q) || (it.sub || "").toLowerCase().includes(q));
      let live = [];
      if (raw.length >= 2) {
        live = _omniItems(raw);
        if (!_omniLive || _omniLive.q !== raw) _omniFetch(raw);
        // Ruled: Enter -> the corpus/analysis window (default), now opening in a NEW
        // BROWSER TAB (field remark 9). The in-SPA spawn (openAnalysisFor) stays the
        // default for clicking a specific result + every card/commodity entry; the
        // Boolean Search tab is still one item away (nothing lost).
        live.unshift({grp: t("Search"), label: `${t("Run the full Boolean search for")} “${raw}”`,
          sub: "", run: () => { showTab("search"); setTimeout(() => { $("q").value = raw; doSearch(); }, 60); }});
        live.unshift({grp: t("Search"), label: `${t("Analysis")}: “${raw}”`,
          sub: "↵ ↗", run: () => openAnalysisInNewTab(raw)});
      }
      _palFiltered = [...statics, ...live];
      _palSel = 0;
      let html = "", lastGrp = null;
      _palFiltered.forEach((it, i) => {
        if (it.grp !== lastGrp) { html += `<div class="pal-group">${esc(it.grp)}</div>`; lastGrp = it.grp; }
        html += `<div class="pal-item ${i === 0 ? "sel" : ""}" data-i="${i}" onclick="palRun(${i})">
          ${esc(it.label)}<span class="pal-sub">${esc(it.sub || "")}</span></div>`;
      });
      $("pal-list").innerHTML = html || `<div class="pal-group">No matches</div>`;
    }
    function palMove(d) {
      if (!_palFiltered.length) return;
      _palSel = (_palSel + d + _palFiltered.length) % _palFiltered.length;
      document.querySelectorAll(".pal-item").forEach(el =>
        el.classList.toggle("sel", +el.dataset.i === _palSel));
      const cur = document.querySelector(".pal-item.sel"); if (cur) cur.scrollIntoView({block:"nearest"});
    }
    function palRun(i) { const it = _palFiltered[i]; if (it) { closePalette(); it.run(); } }
    function palKey(e) {
      if (e.key === "ArrowDown") { e.preventDefault(); palMove(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); palMove(-1); }
      else if (e.key === "Enter") { e.preventDefault(); palRun(_palSel); }
      else if (e.key === "Escape") { closePalette(); }
      else if (e.key === "Tab") { _trapTab($("palette"), e); }  // a11y trap (OO-D13-001)
    }

    // -- Home dashboard ----------------------------------------------------- //
    // Locale-aware date/time in the APP language (not the browser locale), full
    // month name. Shared formatter (parallels the smart units formatter); the
    // i18n DOM walker cannot reach JS-built date strings, so format them here.
    function fmtDateTime(ts) {
      const d = new Date(ts); if (isNaN(d)) return "";
      try {
        return new Intl.DateTimeFormat(OOI18N.current(),
          { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
      } catch (e) { return d.toLocaleString(); }
    }
    // Human, translated labels for the at-a-glance stat keys. The server keys are
    // raw snake_case identifiers (the Database tab + cache rely on them), so the
    // Home strip maps them to translated labels in the UI layer; an unknown key
    // falls back to a prettified form so a new server key never shows raw.
    const HOME_STAT_LABELS = {
      articles: "Articles", sources: "Sources",
      keywords: "Keywords", commodity_prices: "Commodity prices",
      article_links: "Article links", mentioned_dates: "Mentioned dates",
    };
    function homeStatLabel(k) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return t(HOME_STAT_LABELS[k] || k.replace(/_/g, " "));
    }
    function renderHomeStats(counts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-stats"); if (!el) return;
      const entries = Object.entries(counts || {});
      const allZero = entries.length > 0 && entries.every(([, v]) => !v);
      el.innerHTML = (entries.length && !allZero)
        ? entries.map(([k, v]) =>
            `<span class="s"><b>${(v || 0).toLocaleString()}</b> <span>${esc(homeStatLabel(k))}</span></span>`).join("")
        : `<div class="muted">${esc(t("Your library is empty — head to Collect to gather your first material."))}</div>`;
    }
    function renderHomeStatus(running) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-status"); if (!el) return;
      const priv = t("Your corpus stays on this machine — no cloud, no telemetry; fetching follows your Network mode.");
      el.innerHTML =
        `${esc(t("Automatic collection"))}: <span class="pill ${running ? "ok" : ""}">${esc(t(running ? "running" : "stopped"))}</span> ` +
        `· <span class="muted">${esc(priv)}</span>`;
    }
    async function loadHome() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try { const s = await api("/api/database/stats"); renderHomeStats(s.counts); }
      catch (e) { $("home-stats").innerHTML = `<div class="muted">${esc(t("Stats unavailable."))}</div>`; }
      try { const sc = await api("/api/scheduler/status"); renderHomeStatus(sc.running); }
      catch (e) { renderHomeStatus(false); }
      loadBriefing();
      loadHomeAlerts();
      loadHomeTrends();
      // Each panel decides its OWN visibility (it hides when it has nothing), and the
      // subtab list is built from the panels that actually have something to show. So
      // the sync runs from HERE, once each loader has settled, rather than inside the
      // loaders: their fail-safe hide statements are pinned verbatim by
      // test_ui_channel_facet / test_ui_home_latest / test_ui_home_recent, and those
      // guards protect a real honesty property (a panel with no data must hide) that
      // this change has no business touching.
      const pRecent = loadHomeRecent();
      const pLatest = loadHomeLatest();
      const pChannels = loadHomeChannels();
      Promise.allSettled([pRecent, pLatest, pChannels]).then(_syncHomeSubtabs);
      refreshDraftCount();
    }
    // Home "Latest in your corpus" (wave 4 I / GET /api/insights/latest): a recency LENS
    // with transparent substance FILTERS — newest first by COLLECTION time (un-spoofable,
    // never the publisher's claimed date), gated by the min-words AND min-cited-sources
    // thresholds the user sets AND sees, near-identical wire reprints collapsed. Each row
    // shows its REAL word count + cited-source count + channel — counts, NEVER a score.
    // The facet <select>s (content type + tag) are populated once from the endpoint's
    // window-wide options (independent of the active gates) and preserve the selection.
    // Hidden until the corpus has recent articles so Home is never blank-and-silent (the
    // Briefing still renders); when it HAS articles but none pass the gates it shows the
    // panel with an honest "loosen the gates" message so the controls stay reachable.
    async function loadHomeLatest() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-latest-panel"), box = $("home-latest");
      if (!panel || !box) return;
      const mw = Math.max(0, parseInt(($("latest-minwords") || {}).value, 10) || 0);
      const ms = Math.max(0, parseInt(($("latest-minsources") || {}).value, 10) || 0);
      const ct = (($("latest-channel") || {}).value || "").trim();
      const tg = (($("latest-tag") || {}).value || "").trim();
      const collapse = ($("latest-collapse") ? $("latest-collapse").checked : true) ? "1" : "0";
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const p = new URLSearchParams({
          limit: "12", min_words: String(mw), min_sources: String(ms),
          collapse, facets: "1",
        });
        if (ct) p.set("content_type", ct);
        if (tg) p.set("tag", tg);
        const d = await api("/api/insights/latest?" + p.toString());
        const arts = d.articles || [];
        const types = d.available_content_types || {};
        const tags = d.available_tags || [];
        // No recent articles in the corpus at all (not just "none pass the gates") ->
        // hide the panel entirely so Home is never blank-and-silent.
        if (!arts.length && !Object.keys(types).length && !tags.length) {
          panel.hidden = true; return;
        }
        panel.hidden = false;
        _fillLatestFacet($("latest-channel"), t("All channels"),
          Object.keys(types).map(k => ({v: k, label: k, n: types[k]})));
        _fillLatestFacet($("latest-tag"), t("All tags"),
          tags.map(x => ({v: x.tag, label: x.tag, n: x.articles})));
        if (!arts.length) {
          box.innerHTML = `<div class="muted">${esc(t("No recent articles pass these gates yet — loosen the gates or collect more."))}</div>`;
          return;
        }
        box.innerHTML = arts.map(a => {
          const src = (a.source || {});
          const date = String(a.created_at || "").slice(0, 10);
          const meta = [esc(src.name || src.domain || ""), esc(date)].filter(Boolean).join(" · ");
          // REAL substance figures (counts, never a score): word count (flagged when the
          // language is unsegmented, where word_count is meaningless) + cited sources.
          const wc = (a.word_count != null && !a.unsegmented)
            ? `${esc(String(a.word_count))} ${esc(t("words"))}` : "";
          const cs = `${esc(String(a.cited_sources || 0))} ${esc(t("cited sources"))}`;
          const chan = src.source_type ? `<span class="pill">${esc(src.source_type)}</span>` : "";
          const facts = [wc, cs].filter(Boolean).join(" · ");
          // Spread honesty (anti-false-triangulation): count DISTINCT OTHER outlets that
          // ran the same story (the backend's deduped `also_reported_by`, which excludes
          // the survivor's own outlet re-posting) — NEVER the raw duplicates_collapsed,
          // which would overstate independent confirmation. Absent when no OTHER outlet.
          const others = (a.also_reported_by || []).length;
          const also = others > 0
            ? ` <span class="muted">— ${esc(t("also reported by {n} more").replace("{n}", String(others)))}</span>` : "";
          return `<div class="home-recent-row"><a href="${esc(a.url || ("/api/articles/" + a.id + "/view"))}" target="_blank" rel="noopener" title="${esc(t("offline stored copy"))}">${esc(a.title || t("(untitled)"))}</a>`
            + (meta ? ` <span class="muted">— ${meta}</span>` : "")
            + `<div class="muted small" style="margin-top:2px">${chan} ${facts}${also}</div></div>`;
        }).join("")
          + `<div class="hint muted" style="font-size:11px;margin-top:6px">${esc(d.caveat || "")}</div>`;
      } catch (e) { panel.hidden = true; box.innerHTML = ""; }
    }
    // Populate a Latest facet <select> once (preserving the current selection), an "all"
    // default first then each option with its article count. Idempotent: repopulates so a
    // growing corpus surfaces new channels/tags, but keeps what the user picked.
    function _fillLatestFacet(sel, allLabel, opts) {
      if (!sel) return;
      const cur = sel.value;
      const parts = [`<option value="">${esc(allLabel)}</option>`];
      opts.forEach(o => { if (o.v) parts.push(`<option value="${esc(o.v)}">${esc(o.label)} (${esc(String(o.n))})</option>`); });
      sel.innerHTML = parts.join("");
      if (cur && opts.some(o => o.v === cur)) sel.value = cur;
    }
    // Home "By channel" (wave 4 I / GET /api/insights/source-types): the content-provenance
    // facet — article counts per ASSERTED content channel (news/newsletter/wiki/statistics/
    // law/market/discovery/untyped), a descriptive fact known by construction, NEVER a
    // quality score. Clicking a channel opens the analysis window over EXACTLY that
    // channel's articles: /api/articles?source_type= resolves the id set, which every
    // analysis subtab honours (openAnalysisForIds), so the whole corpus narrows honestly
    // by channel using only endpoints that already exist. Hidden when the corpus has no
    // channels (Home is never blank-and-silent).
    async function loadHomeChannels() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-channels-panel"), box = $("home-channels");
      if (!panel || !box) return;
      try {
        const d = await api("/api/insights/source-types");
        const facets = (d.facets || []).filter(f => (f.articles || 0) > 0);
        if (!facets.length) { panel.hidden = true; box.innerHTML = ""; return; }
        panel.hidden = false;
        // A bare count cannot answer "is this channel most of my corpus or a rounding
        // error?", so each chip carries its SHARE and the denominator is stated once
        // above them. Article.source_id is NOT NULL and the facet excludes quarantined
        // articles exactly as the browse path does, so the facets really do sum to the
        // corpus this share is a share OF -- an unstated denominator is the usual way a
        // percentage lies. Shares are shown BESIDE the counts, never instead: the raw
        // number is what the reader checks the percentage against.
        //
        // Deliberately NOT a waffle, and not a second bar view either. The project's own
        // chart framework prescribes sorted bars for part-to-whole and never mentions a
        // waffle at all; `_ooShareBars` already implements that form -- but its rows are
        // not clickable, and these chips open the channel's corpus (openChannelCorpus).
        // Replacing them would trade a working tool for a prettier read of the same
        // numbers, so the shares come to the chips instead.
        const total = facets.reduce((s, f) => s + (f.articles || 0), 0);
        const pct = (n) => (total > 0 ? (n / total * 100) : 0);
        // Below 0.5% a rounded share reads as "0%", which looks like nothing rather than
        // like a little; "<1%" says small without claiming a precision the rounding lost.
        const share = (n) => (pct(n) >= 0.5 ? Math.round(pct(n)) + "%" : "<1%");
        const totalLine = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf("{n} articles across {k} channels", {n: fmtNum(total), k: facets.length})
          : `${fmtNum(total)} articles across ${facets.length} channels`;
        box.innerHTML = `<div class="hint muted" style="margin-bottom:4px">${esc(totalLine)}</div>`
          + `<div style="display:flex;gap:6px;flex-wrap:wrap">` + facets.map(f =>
          `<button class="chip" onclick="openChannelCorpus(${esc(JSON.stringify(f.source_type))})" title="${esc(t("An asserted content channel (newsletter, web article, wiki, statistic, law, market, discovery), never a quality score. Click a channel to explore its corpus."))}">${esc(f.source_type)} <span class="muted">${esc(String(f.articles))} · ${esc(share(f.articles))}</span></button>`).join("")
          + `</div>`;
      } catch (e) { panel.hidden = true; box.innerHTML = ""; }
    }
    // Open the analysis window over exactly one content channel's articles. Resolves the
    // channel to an explicit id set through /api/articles?source_type= (the endpoint that
    // supports the filter) then hands it to openAnalysisForIds, so ALL analysis subtabs
    // (keywords / WWW / mindmap / …) narrow to the channel — not just the article list.
    async function openChannelCorpus(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/articles?source_type=" + encodeURIComponent(st) + "&limit=1000");
        const ids = (d.results || []).map(a => a.id).filter(Boolean);
        if (!ids.length) { toast(t("No articles for this channel yet.")); return; }
        openAnalysisForIds(ids, t("Channel: {c}").replace("{c}", st));
      } catch (e) { toast((e && e.message) || String(e), "err"); }
    }
    // Home "Most recent by tag" (item #36 / Home helicopter view): a recency LENS onto the
    // corpus, never a reweighting — newest-first by the article's PUBLISHED date among sources
    // carrying a chosen source tag. REDUNDANT by design (every title deep-links to the offline
    // stored reader, invariant #6). Reuses /api/sources/facets (the tag list) + /api/articles
    // (tags + sort_by=date). Hidden until it has a tag + articles so Home is never blank-and-
    // silent (the Briefing still renders below).
    async function loadHomeRecent() {
      const panel = $("home-recent-panel"), sel = $("home-recent-tag");
      if (!panel || !sel) return;
      try {
        const f = await api("/api/sources/facets");
        const tags = (f.tags || []).filter(x => x && x.key).slice(0, 20);
        if (!tags.length) { panel.hidden = true; return; }
        const cur = sel.value;
        sel.innerHTML = tags.map(x => `<option value="${esc(x.key)}">${esc(x.key)} (${x.n})</option>`).join("");
        sel.value = (cur && tags.some(x => x.key === cur)) ? cur : tags[0].key;
        await loadHomeRecentList(sel.value);
      } catch (e) { panel.hidden = true; }
    }
    async function loadHomeRecentList(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-recent-panel"), box = $("home-recent");
      if (!panel || !box) return;
      if (!tag) { panel.hidden = true; return; }
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const q = "/api/articles?tags=" + encodeURIComponent(tag) + "&sort_by=date&sort_dir=desc&limit=8";
        const d = await api(q);
        const rows = d.results || [];
        if (!rows.length) { box.innerHTML = `<div class="muted">${esc(t("No articles for this tag yet."))}</div>`; panel.hidden = false; return; }
        box.innerHTML = rows.map(a => {
          const meta = [esc(a.source || ""), esc(String(a.published_at || "").slice(0, 10))].filter(Boolean).join(" · ");
          return `<div class="home-recent-row"><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="${esc(t("offline stored copy"))}">${esc(a.title || t("(untitled)"))}</a>`
            + (meta ? ` <span class="muted">— ${meta}</span>` : "") + `</div>`;
        }).join("");
        panel.hidden = false;
      } catch (e) {
        // home-recent-panel-hidden-on-error (P1): both SUCCESS paths above clear
        // `hidden`, but this catch branch set an honest error message into the
        // panel's own box while leaving the panel itself hidden -- the message was
        // written but never shown. The panel must render its error the same way it
        // renders any other outcome.
        box.innerHTML = `<div class="muted">${esc(e && e.message || e)}</div>`;
        panel.hidden = false;
      }
    }
    // Home "Trending now" glance (UI rethink, Home → helicopter view). Compact +
    // REDUNDANT by design: the past-week RISING keywords (the disclosed window-vs-
    // baseline RATE — never a score), each a chip that deep-links to its own
    // analysis window; a small honest sparkline rides along (dashChartSvg: line
    // when dense, Item-Y bars when sparse). The panel HIDES when nothing is
    // trending yet (Home is never blank-and-silent — the Briefing still renders);
    // "More in Insights →" deep-links to the canonical Trends view. Reuses
    // /api/insights/trending-windows + dashChartSvg; no new backend, no new poll.
    let _homeTrendTerms = [], _homeTrendCaveat = "";   // stash for enlargeHomeTrend(i)
    async function loadHomeTrends() {
      const panel = $("home-trends-panel"), box = $("home-trends");
      if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/insights/trending-windows?limit=4&series_top=4" + tgtLangParam());
        const wk = (d.windows || []).find(w => w.label === "7d") || (d.windows || [])[0];
        const terms = (wk && wk.terms) || [];
        if (!terms.length) { if (panel) panel.hidden = true; box.innerHTML = ""; return; }
        if (panel) panel.hidden = false;
        _homeTrendTerms = terms;              // stash so enlargeHomeTrend(i) needs no refetch
        _homeTrendCaveat = d.caveat || "";
        const cards = terms.map((x, i) => {
          const spark = Array.isArray(x.series)
            ? dashChartSvg(x.series.map(p => ({observed_on: p.date, price: p.count})), "")
            : "";
          // Click-to-enlarge into the interactive ooChart (invariant #16), matching
          // the Insights Trends UX — the daily series is already in the payload.
          const enlarge = Array.isArray(x.series)
            ? `<button class="ghost tiny" style="margin-inline-start:auto" onclick="enlargeHomeTrend(${i})" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>`
            : "";
          return `<div style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
            <div style="display:flex;align-items:baseline;gap:6px">
              <a href="#" onclick='openAnalysisFor(${esc(JSON.stringify(x.term))});return false' title="${esc(t("Open this keyword's own analysis window"))}">${esc(x.term)}</a>${kwTransHtml(x)}
              <span class="muted" style="font-size:12px">${esc(growthFallback(x) || `↑${x.growth}× · ${x.recent}`)}</span>${enlarge}
            </div>${spark}</div>`;
        }).join("");
        box.innerHTML = `<div style="display:flex;gap:8px;flex-wrap:wrap">${cards}</div>`
          + `<div class="hint muted" style="font-size:11px;margin-top:6px">${esc(d.caveat || "")}</div>`;
        _renderOverviewTrends();   // the compact row folded into Overview (ruling 7a)
        _syncHomeSubtabs();
      } catch (e) {
        if (panel) panel.hidden = true; box.innerHTML = "";
        _renderOverviewTrends(); _syncHomeSubtabs();
      }
    }
    // Enlarge a Home "Trending now" sparkline into the interactive ooChart (invariant
    // #16). The daily series is already in the stashed payload — no extra fetch.
    // Global (reached from the inline onclick, matching the card's local convention).
    function enlargeHomeTrend(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const x = _homeTrendTerms[i];
      if (!x || !Array.isArray(x.series)) return;   // defensive: nothing to enlarge
      chartEnlarge(x.term, [{label: x.term, unit: t("mentions"),
        points: x.series.map(p => ({t: p.date, v: p.count}))}], _homeTrendCaveat || "");
    }
    // Home severity alert strip (info / watch / urgent) — GET /api/signals/alerts, LOCAL,
    // no network (reads the cached hazard snapshot; a producer NEVER fetches). Compact +
    // honest: 'urgent' is ONLY a provider-declared RED hazard (we never promote a magnitude
    // band); every alert states its provider + the snapshot's staleness ("silence is not
    // safety"); the method + caveat are VISIBLE (invariant #23). Watch/convergence article
    // sets open the exact corpus (openAnalysisForIds); a hazard URL is external so it goes
    // through extLink (the confirm popup, invariant #7). The panel HIDES when there is
    // nothing (Home is never blank-and-silent — the Briefing still renders below).
    async function loadHomeAlerts() {
      const panel = $("home-alerts-panel"), box = $("home-alerts");
      if (!box) return;
      try {
        const d = await api("/api/signals/alerts");
        if (!d || !d.total) { if (panel) panel.hidden = true; box.innerHTML = ""; return; }
        if (panel) panel.hidden = false;
        _renderHomeAlerts(d);
      } catch (e) { if (panel) panel.hidden = true; box.innerHTML = ""; }
    }
    // Item 3 (field-feedback A6, ruled): a distinct glyph per hazard TYPE (never a
    // score/severity encoding -- purely a scannability aid), "⚠" for an unlisted type.
    const HAZARD_GLYPH = {
      earthquake: "◉", cyclone: "🌀", flood: "≈", volcano: "🌋",
      drought: "☀", wildfire: "🔥", tsunami: "〰",
    };
    // The hazard TYPE IN WORDS. A glyph alone is not deducible by someone seeing
    // it for the first time — the maintainer's report (2026-08-01, ruling 4) was
    // that opening an earthquake's detail never says it IS an earthquake. Every
    // hazard render states the type in words, translated; an unlisted type falls
    // back to the provider's own raw string rather than inventing a name.
    const HAZARD_TYPE_KEYS = {
      earthquake: "Earthquake", cyclone: "Cyclone", flood: "Flood", volcano: "Volcano",
      drought: "Drought", wildfire: "Wildfire", tsunami: "Tsunami",
    };
    function hazardTypeLabel(type) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const raw = String(type || "").trim().toLowerCase();
      if (!raw) return t("Hazard");
      return HAZARD_TYPE_KEYS[raw] ? t(HAZARD_TYPE_KEYS[raw]) : String(type);
    }
    // The provider's magnitude, always labelled as the BAND it is. "M6.8 · strong"
    // is a measurement of size, never a statement about consequences — which is
    // exactly why a magnitude is never promoted into an urgency tier.
    function hazardMagLabel(h) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (h.magnitude == null) return "";
      const band = h.band ? ` <span class="muted">· ${esc(t(h.band))}</span>` : "";
      return `<b>M${esc(fmtNum(h.magnitude, 1))}</b>${band} · `;
    }
    // The compact hazard strip item: type glyph, real magnitude (never fabricated),
    // place, RELATIVE date (the stored "time" field, finally rendered -- it used to
    // be fetched and dropped), and TWO deep links: the World map (centred on the
    // event) and the internal article (once ingested; absent until then, never a
    // broken link). The tier dot is the existing per-tier pill above the list.
    function _hazardStripItem(h) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const glyph = HAZARD_GLYPH[h.type] || "⚠";
      const kind = `<span class="haz-kind">${esc(hazardTypeLabel(h.type))}</span> · `;
      const mag = hazardMagLabel(h);
      const place = esc(h.place || h.title || h.type || "");
      const when = h.time ? esc(fmtAgo(h.time)) : "";
      // A grouped entry is ONE event two providers both reported — a deduction
      // from coordinates and time, labelled as such, never presented as a
      // provider statement. Both providers are named.
      const provs = (h.providers && h.providers.length) ? h.providers : (h.source ? [h.source] : []);
      const prov = provs.length
        ? ` <span class="muted">${esc(t("via {p}").replace("{p}", provs.join(" + ")))}</span>`
        : "";
      const grouped = h.grouped
        ? ` <span class="pill tiny" title="${esc(t("Same hazard type, within 0.5° and 2 hours — a deduced grouping of two providers' reports of one event, never a merge of the stored records."))}">${esc(t("grouped"))}</span>`
        : "";
      const mapBtn = (typeof h.lat === "number" && typeof h.lon === "number")
        ? ` <button class="ghost tiny" onclick="openWorldMapAt(${h.lat}, ${h.lon}, ${esc(JSON.stringify(h.time || null))}, ${h.article_id != null ? h.article_id : "null"})" title="${esc(t("Open on the World map"))}">🗺</button>`
        : "";
      const artLink = (h.article_id != null)
        ? ` <a href="/api/articles/${h.article_id}/view" target="_blank" rel="noopener" class="ghost tiny" title="${esc(t("Open the local article"))}">📄</a>`
        : "";
      const srcLink = (h.url && /^https?:\/\//i.test(h.url)) ? " " + extLink(h.url, t("source ↗")) : "";
      return `<li class="alert-hazard-item${h.major ? " haz-major" : ""}">${glyph} ${kind}${mag}${place}`
        + `${when ? ` <span class="muted">· ${when}</span>` : ""}${prov}${grouped}${mapBtn}${artLink}${srcLink}</li>`;
    }
    function _renderHomeAlerts(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("home-alerts"); if (!box) return;
      const TIER_LABEL = { urgent: t("Urgent"), watch: t("Watch"), info: t("Info") };
      const TIER_CLASS = { urgent: "err", watch: "warn", info: "" };
      // The DISPLAY floor (2026-08-01 rulings 1-2). The backend already ordered
      // each tier by the provider's own facts and marked which entries clear the
      // floor; the strip shows those first, capped, and collapses the rest into
      // ONE line that opens the World map. Nothing is removed: every hazard is
      // still in this payload, on the map, and behind "Open corpus" — which is
      // what makes a floor honest rather than a silent exclusion.
      const cap = Math.max(1, Number(d.strip_cap) || 5);
      const blocks = ["urgent", "watch", "info"].map(tier => {
        const T = (d.tiers || {})[tier];
        if (!T || !T.count) return "";
        const items = [];
        const hz = T.hazards || [];
        const major = hz.filter(h => h.major);
        const shown = major.length ? major.slice(0, cap) : hz.slice(0, cap);
        const hidden = hz.length - shown.length;
        shown.forEach(h => items.push(_hazardStripItem(h)));
        if (hidden > 0) {
          const note = major.length
            ? t("{n} more, below the M{m} display floor — open the World map")
            : t("{n} more — open the World map");
          items.push(`<li class="alert-more"><button class="ghost tiny" onclick="openWorldMapHazards()">`
            + esc(note.replace("{n}", String(hidden))
                     .replace("{m}", fmtNum(d.major_min_magnitude != null ? d.major_min_magnitude : 6, 1)))
            + ` →</button></li>`);
        }
        (T.watches || []).forEach(w => {
          const nm = esc(w.name || w.query || "");
          const n = (w.n_articles != null) ? ` <span class="muted">${esc(String(w.n_articles))} ${esc(t("articles"))}</span>` : "";
          items.push(`<li>${nm}${n}</li>`);
        });
        (T.convergences || []).forEach(c => {
          const pl = [c.place || "", c.place_country || ""].filter(Boolean).map(esc).join(", ");
          const meta = ` <span class="muted">${esc(String(c.distinct_sources || 0))} ${esc(t("sources"))} · ${esc(String(c.n_articles || 0))} ${esc(t("articles"))}</span>`;
          items.push(`<li>${pl}${meta}</li>`);
        });
        const open = (Array.isArray(T.article_ids) && T.article_ids.length)
          ? ` <button class="ghost tiny" onclick="openAnalysisForIds(${esc(JSON.stringify(T.article_ids))}, ${esc(JSON.stringify(TIER_LABEL[tier]))})">${esc(t("Open corpus"))} ↗</button>`
          : "";
        return `<div class="alert-tier"><span class="pill ${TIER_CLASS[tier]}">${esc(TIER_LABEL[tier])} · ${esc(String(T.count))}</span>${open}<ul>${items.join("")}</ul></div>`;
      }).join("");
      // Hazard-snapshot staleness (silence is not safety): state the age + stale flag, or
      // that there is no local snapshot at all.
      let stale;
      if (d.hazards_available) {
        const age = (d.hazards_age_hours != null) ? " (" + esc(t("{h}h old").replace("{h}", Math.round(d.hazards_age_hours))) + ")" : "";
        const asof = d.hazards_as_of ? esc(String(d.hazards_as_of).slice(0, 16).replace("T", " ")) : "—";
        stale = `<span class="hint">${esc(t("Hazard snapshot"))}: ${asof}${age}${d.hazards_stale ? " · " + esc(t("stale")) : ""}</span>`;
      } else {
        stale = `<span class="hint">${esc(t("No local hazard snapshot — silence is not safety."))}</span>`;
      }
      // Caveat VISIBLE by default (#23); the method rides the #oo-tip hover (the "how").
      const caveat = d.caveat ? `<div class="card-caveat" title="${esc(d.method || "")}">${esc(d.caveat)}</div>` : "";
      box.innerHTML = `<div class="phead"><h2>${esc(t("Alerts"))}</h2><span class="sp"></span>${stale}</div>`
        + blocks + caveat;
    }
    // Live Home (the at-a-glance strip + briefing self-update; no Refresh button).
    // Only runs while Home is the active, visible tab (the LIVE registry). Cheap:
    // stats are server-cached ~30 s; the briefing feed re-renders ONLY when its
    // generated_at actually changes, so the user's card triage is never reset.
    async function refreshHomeLive() {
      // Awaited end-to-end so the LIVE single-flight guard covers the WHOLE Home chain
      // (under 429 backpressure a poll can outlast its 15 s interval; without this the
      // trailing trends/alerts would race the next tick).
      try { const s = await api("/api/database/stats"); renderHomeStats(s.counts); } catch (e) {}
      try { const sc = await api("/api/scheduler/status"); renderHomeStatus(sc.running); } catch (e) {}
      try {
        const data = await api("/api/briefing");
        if (data.generated_at !== _lastBriefGen) renderBriefing(data);
      } catch (e) {}
      try { await loadHomeTrends(); } catch (e) {}
      try { await loadHomeAlerts(); } catch (e) {}
    }

    // -- The Home briefing (triage cards) ----------------------------------- //
    // Cards are produced server-side from real analytics; this layer only renders
    // them and lets the user triage (dismiss / add to draft). It never computes a
    // verdict. The full method + caveat for every figure is one toggle away.
    let _briefCards = {};   // id -> card (so "Add to draft" has the full card)
    let _lastBriefGen = null;  // last rendered briefing generated_at (live-refresh guard)

    async function loadBriefing(force) {
      const feed = $("briefing-feed");
      try {
        const data = await api("/api/briefing" + (force ? "?force=true" : ""));
        renderBriefing(data);
      } catch (e) {
        feed.innerHTML = '<div class="muted">Briefing unavailable right now.</div>';
      }
    }

    async function refreshBriefing() {
      const btn = $("brief-refresh-btn");
      if (btn) { btn.disabled = true; btn.textContent = "Refreshing…"; }
      try { const data = await api("/api/briefing/refresh", {method:"POST"}); renderBriefing(data); toast("Briefing refreshed."); }
      catch (e) { toast("Could not refresh briefing: " + e.message, "err"); }
      finally { if (btn) { btn.disabled = false; btn.textContent = "Refresh"; } }
    }

    // -- Corpus maturity tier (descriptive STAGE, never a score) ------------ //
    // Calibrates how much weight the evidence cards deserve. The visible surface
    // keeps the stage word + the REAL "N articles · M days" present; an EARLY
    // corpus also shows the short "thin evidence" caveat inline. The long plain-
    // language explanation AND the exact thresholds live in the #oo-tip hover
    // (informed-consent layering, invariant #17). Numbers come from the backend;
    // the JS only formats — no second corpus-age definition lives here.
    function renderCorpusTier(ct) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-tier"); if (!el) return;
      if (!ct || !ct.tier) { el.hidden = true; el.innerHTML = ""; el.removeAttribute("title"); return; }
      const tier = ct.tier;
      const arts = (ct.articles || 0).toLocaleString();
      const days = (ct.age_days || 0).toLocaleString();
      const th = ct.thresholds || {};
      // The stage word (one of three constant labels — each keyed ×12).
      const stageLabel = t(tier === "early" ? "Early corpus"
        : tier === "established" ? "Established corpus" : "Developing corpus");
      // The real numbers, always shown beside the stage (constant unit labels keyed).
      const nums = `${arts} ${t("articles")} · ${days} ${t("days")}`;
      // What the stage MEANS (plain language) + the exact thresholds — the hover
      // long form. Built from keyed sentence fragments + the real numbers so the
      // bubble is translated ×12 by construction (i18n.t on each fragment).
      const meaning = t(tier === "early"
          ? "Early stage: the Leads rest on thin evidence — read them as first hints, not established patterns."
          : tier === "established"
          ? "Established stage: enough breadth and time for patterns to be more than a first hint — still descriptive, never a verdict."
          : "Developing stage: patterns are forming but the corpus is not yet broad or old enough to lean on heavily.");
      const rule = t("Stages are descriptive, from real corpus facts — never a score.") + " " +
        t("Thresholds: early is below {a} articles or {d} days; established is at least {b} articles and {e} days; developing is in between.")
          .replace("{a}", th.young_articles ?? 200)
          .replace("{d}", th.min_span_days ?? 14)
          .replace("{b}", th.established_articles ?? 1000)
          .replace("{e}", th.established_days ?? 90);
      el.className = "corpus-tier tier-" + tier;
      // The #oo-tip hover re-reads this live-translated title (invariant #17).
      el.title = stageLabel + " — " + meaning + " " + rule;
      const caveat = (tier === "early")
        ? `<span class="tier-caveat">${esc(t("thin evidence — read with care"))}</span>` : "";
      el.innerHTML =
        `<span class="tier-badge">${esc(stageLabel)}</span>` +
        `<span class="tier-nums">${esc(nums)}</span>` + caveat;
      el.hidden = false;
    }

    function renderBriefing(data) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _briefCards = {};
      renderCorpusTier(data.corpus_tier);
      _lastBriefGen = data.generated_at || null;
      const feed = $("briefing-feed");
      const gen = $("brief-generated");
      if (gen) gen.textContent = data.generated_at ? (t("updated") + " " + fmtDateTime(data.generated_at)) : "";
      // Recompute now runs OFF the request thread (field test 2026-06-24: Home froze on
      // "Loading the briefing…" at 60K). While a background refresh runs we show a real
      // progress bar and re-poll until cards land; if we already have (stale) cards we
      // keep showing them under a slim "updating…" banner so Home is never blank.
      const refreshing = !!(data.refreshing || data.building);
      if (refreshing) _scheduleBriefRepoll(); else _cancelBriefRepoll();
      const banner = refreshing ? briefProgressHtml(data, t) : "";
      if (!data.buckets || !data.buckets.length) {
        if (refreshing) { feed.innerHTML = banner; return; }
        feed.innerHTML = `<div class="card">
          <h4>No Leads yet — that's expected on a young corpus</h4>
          <p class="sum">Leads are computed from YOUR collected material; an empty feed means the
          signals haven't accumulated, never that the engine is gone. As the corpus grows you'll see:
          <b>Rising now</b> (terms accelerating vs their own baseline), <b>Overtold/Undertold</b>,
          <b>framing splits</b>, <b>promises due</b> (a mentioned future date arrives),
          <b>edit-war bursts</b> on tracked Wikipedia pages, <b>regions gone quiet</b>,
          and <b>source candidates</b> from offline discovery.</p>
          <p class="muted" style="margin-top:6px">Collection and Leads update automatically in the
          background while you're online — there's nothing to start by hand.</p></div>`;
        return;
      }
      // Family-type colors: a deterministic hue per bucket, applied as the card
      // left-accent (--fam) so the feed stays scannable in "All", and echoed as a
      // dot in the family subtab. "All cards" is the default lens (a single
      // prioritised feed); the families are a lens, never a wall (§5).
      const famHue = bi => `hsl(${(bi * 53) % 360} 60% 55%)`;
      const html = data.buckets.map((b, bi) => {
        b.cards.forEach(c => { _briefCards[c.id] = c; });
        const cards = b.cards.map(cardHtml).join("");
        return `<div class="brief-bucket" data-fam="${bi}" style="--fam:${famHue(bi)}">`
          + `<h3>${esc(b.label)} <span class="ct">· ${b.cards.length}</span></h3>`
          + `<div class="cards">${cards}</div></div>`;
      }).join("");
      // OVERVIEW (2026-08-01 rulings 5-8): the DEFAULT lens is the top card of each
      // family, taken from the feed's OWN already-sorted order — one ordering
      // system, not a second selector. Each card carries the visible "why this
      // card" (order_explain), which restores the transparency surface the
      // Settings restructure removed when it deleted the Leads preview. "All
      // Leads" keeps the full feed; nothing is lost, the wall is just no longer
      // the first thing you meet.
      const ovHtml = _overviewHtml(data, famHue, t);
      const famTabs = `<button class="active" data-tab="__ov">${esc(t("Overview"))}</button>`
        + `<button data-tab="__all">${esc(t("All Leads"))}</button>`
        + data.buckets.map((b, bi) =>
            `<button data-tab="${bi}"><span class="fam-dot" style="background:${famHue(bi)}"></span>${esc(b.label)}</button>`).join("")
        + _homePanelTabsHtml(t);
      feed.innerHTML = banner
        + `<nav class="tabs home-fam" id="home-fam-subtabs">${famTabs}</nav>`
        + ovHtml + html;
      ooSubtabs($("home-fam-subtabs"), selectHomeFamily, {initial: _homeTabKey});
      selectHomeFamily(_homeTabKey);
      _renderOverviewTrends();
    }
    // The Overview lens: TOP-1 card per family, in the feed's own disclosed order.
    function _overviewHtml(data, famHue, t) {
      const tops = data.buckets.map((b, bi) => {
        const c = (b.cards || [])[0];
        if (!c) return "";
        // The card renders exactly as it does in its family (same component, same
        // actions), plus the disclosed reason it leads its family.
        const why = c.order_explain
          ? `<div class="ov-why" title="${esc(c.order_explain)}">${esc(c.order_explain)}</div>` : "";
        return `<div class="ov-item" style="--fam:${famHue(bi)}">`
          + `<h4 class="ov-fam"><span class="fam-dot" style="background:${famHue(bi)}"></span>${esc(b.label)}`
          + ` <a href="#" class="ov-more" onclick='selectHomeFamily(${esc(JSON.stringify(String(bi)))});return false'>`
          + `${esc(t("all {n}").replace("{n}", String((b.cards || []).length)))} →</a></h4>`
          + `<div class="cards">${cardHtml(c)}</div>${why}</div>`;
      }).join("");
      return `<div class="brief-bucket" data-fam="__ov">`
        + `<div id="ov-trending"></div>`
        + `<div class="ov-grid">${tops}</div>`
        + `<div class="card-caveat">${esc(t("One Lead per family, chosen by the same disclosed order as the full feed — independent sources, then sample magnitude, then recency. Never a score, and nothing is hidden: “All Leads” has every card."))}</div>`
        + `</div>`;
    }

    // -- S4.3: the synthesized-Leads carousel (Home dashboard) --------------------------- //
    // A rolling rotation of the TOP local-analytic Leads (never LLM — Home is zero-network).
    // PAUSABLE (WCAG 2.2: pause on hover/focus + a manual toggle); the caveat rides EVERY face
    // so a timed rotation never hides it (#23); each face DEEP-LINKS (#8) via the SAME action
    // the full card uses; ordering is the briefing's own (evidence tier + recency + spread —
    // never a hidden score). Hidden with <2 Leads so Home is never blank-and-silent.
    let _carTimer = null, _carIdx = 0, _carCards = [], _carPaused = false;

    function renderLeadsCarousel(cards) {
      const panel = $("home-carousel-panel"), host = $("home-carousel");
      if (!panel || !host) return;
      _carStop();
      _carCards = (cards || []).filter(c => c && c.title).slice(0, 8);
      if (_carCards.length < 2) { panel.hidden = true; host.innerHTML = ""; return; }
      panel.hidden = false;
      _carIdx = 0;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML =
        `<div class="carousel" role="region" aria-roledescription="${esc(t("carousel"))}" aria-label="${esc(t("Leads"))}" tabindex="0">`
        + `<div class="carousel-face" id="carousel-face" aria-live="polite"></div>`
        + `<div class="carousel-ctl">`
        +   `<button class="tiny secondary" onclick="carouselStep(-1)" aria-label="${esc(t("Previous Lead"))}">‹</button>`
        +   `<button class="tiny secondary" id="carousel-pause" onclick="carouselToggle()" aria-pressed="false" aria-label="${esc(t("Pause the carousel"))}">⏸</button>`
        +   `<button class="tiny secondary" onclick="carouselStep(1)" aria-label="${esc(t("Next Lead"))}">›</button>`
        +   `<span class="carousel-dots" id="carousel-dots"></span>`
        + `</div></div>`;
      const car = host.querySelector(".carousel");
      // WCAG 2.2: the auto-rotation pauses on hover/focus, plus the explicit pause toggle.
      car.addEventListener("mouseenter", _carHold);
      car.addEventListener("mouseleave", _carRelease);
      car.addEventListener("focusin", _carHold);
      car.addEventListener("focusout", _carRelease);
      car.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") { carouselStep(-1); e.preventDefault(); }
        else if (e.key === "ArrowRight") { carouselStep(1); e.preventDefault(); }
      });
      _carPaint();
      if (!_carPaused) _carStart();
    }

    function _carPaint() {
      const face = $("carousel-face"); if (!face || !_carCards.length) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = _carCards[_carIdx]; if (!c) return;
      const n = _carCards.length;
      const aq = cardAnalyzeQuery(c);
      const aIds = (Array.isArray(c.article_ids) && c.article_ids.length) ? c.article_ids : null;
      const action = aIds
        ? `openCardCorpus(${esc(JSON.stringify(aIds))}, ${esc(JSON.stringify(aq))})`
        : `openCardCorpusQuery(${esc(JSON.stringify(aq))})`;
      // the CAVEAT rides EVERY rotated face — a timed rotation never hides it (#23 + the brief).
      const caveat = c.caveat ? `<p class="card-caveat">${esc(c.caveat)}</p>` : "";
      face.innerHTML =
        `<div class="carousel-card bk-${esc(c.bucket)}" role="group" aria-label="${esc(t("Lead"))} ${_carIdx + 1} / ${n}">`
        + `<h4>${esc(cardTitle(c))}</h4>`
        + (c.summary ? `<p class="sum">${esc(c.summary)}</p>` : "")
        + caveat
        + `<div><button class="tiny" onclick="${action}">${esc(t("Open corpus"))} ↗</button></div>`
        + `</div>`;
      const dots = $("carousel-dots");
      if (dots) dots.innerHTML = _carCards.map((_, i) =>
        `<button class="carousel-dot${i === _carIdx ? " on" : ""}" onclick="carouselGo(${i})" aria-label="${esc(t("Lead"))} ${i + 1}"${i === _carIdx ? ' aria-current="true"' : ""}></button>`).join("");
    }

    function carouselStep(d) {
      if (!_carCards.length) return;
      _carIdx = (_carIdx + d + _carCards.length) % _carCards.length;
      _carPaint();
    }
    function carouselGo(i) { _carIdx = i; _carPaint(); }
    function carouselToggle() {
      _carPaused = !_carPaused;
      const b = $("carousel-pause");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (b) {
        b.textContent = _carPaused ? "▶" : "⏸";
        b.setAttribute("aria-pressed", _carPaused ? "true" : "false");
        b.setAttribute("aria-label", _carPaused ? t("Play the carousel") : t("Pause the carousel"));
      }
      if (_carPaused) _carStop(); else _carStart();
    }
    function _carStart() { _carStop(); if (_carPaused || _carCards.length < 2) return; _carTimer = setInterval(() => carouselStep(1), 7000); }
    function _carStop() { if (_carTimer) { clearInterval(_carTimer); _carTimer = null; } }
    function _carHold() { _carStop(); }                 // hover/focus pause (keeps the user's toggle state)
    function _carRelease() { if (!_carPaused) _carStart(); }

    // The "pleasing progress bar" for a background briefing recompute (remarks 6/7).
    // Determinate once producers report (done/total), indeterminate until then. Honest:
    // it counts ANALYSES completed, not elapsed time (producers vary in cost), and is
    // labelled as such — never a fabricated time estimate.
    function briefProgressHtml(data, t) {
      t = t || ((s) => s);
      const p = data.progress || {};
      const total = +p.total || 0, done = +p.done || 0;
      const label = data.building ? t("Building your briefing…") : t("Updating your briefing…");
      const bar = total > 0
        ? `<progress max="${total}" value="${done}" style="width:100%;height:8px"></progress>`
        : `<progress style="width:100%;height:8px"></progress>`;
      const detail = total > 0 ? `${done} / ${total} ${t("analyses")}` : "";
      return `<div class="brief-progress card" role="status" aria-live="polite" style="margin-bottom:10px">`
        + `<div style="display:flex;justify-content:space-between;gap:8px">`
        + `<span>${esc(label)}</span><span class="muted">${esc(detail)}</span></div>${bar}</div>`;
    }
    // Re-poll the briefing while a background recompute runs so the bar advances and the
    // final cards appear without a manual reload. One timer at a time; renderBriefing
    // cancels it on a non-refreshing payload. 1.5 s is responsive without hammering.
    let _briefRepoll = null;
    function _scheduleBriefRepoll() {
      if (_briefRepoll) return;
      _briefRepoll = setTimeout(() => { _briefRepoll = null; loadBriefing(); }, 1500);
    }
    function _cancelBriefRepoll() {
      if (_briefRepoll) { clearTimeout(_briefRepoll); _briefRepoll = null; }
    }
    // The standalone Home panels become SUBTABS beside the families (ruling 7a):
    // the long scroll was every block stacked at once. They keep their own DOM,
    // their own loaders and their own honest empty states — only their visibility
    // is driven from here, so nothing is lost and no listener is re-bound.
    let _homeTabKey = "__ov";
    const _HOME_PANEL_TABS = [
      {key: "__recent", id: "home-recent-panel", label: "Most recent"},
      {key: "__latest", id: "home-latest-panel", label: "Latest in your corpus"},
      {key: "__channels", id: "home-channels-panel", label: "By channel"},
    ];
    // A panel tab appears only once its panel has something to show: these panels
    // unhide themselves when loaded (and stay hidden when there is nothing), so
    // offering a tab onto an empty panel would be offering an empty room.
    function _homePanelTabsHtml(t) {
      return _HOME_PANEL_TABS.filter(p => { const el = $(p.id); return el && !el.hidden; })
        .map(p => `<button data-tab="${p.key}">${esc(t(p.label))}</button>`).join("");
    }
    function selectHomeFamily(key) {
      _homeTabKey = key;
      const panelKeys = _HOME_PANEL_TABS.map(p => p.key);
      const onPanel = panelKeys.indexOf(key) !== -1;
      document.querySelectorAll("#briefing-feed .brief-bucket").forEach(el => {
        const fam = el.dataset.fam;
        const show = onPanel ? false
          : (key === "__ov") ? (fam === "__ov")
          : (key === "__all") ? (fam !== "__ov")
          : (fam === key);
        el.style.display = show ? "" : "none";
      });
      // Clearing the inline style (rather than forcing a display) lets each panel's
      // own `hidden` still win — a panel with nothing to show stays hidden even
      // while its tab is selected, instead of rendering an empty box.
      _HOME_PANEL_TABS.forEach(p => {
        const el = $(p.id);
        if (el) el.style.display = (key === p.key) ? "" : "none";
      });
      // Trending is folded INTO Overview as a compact row, so its standalone panel
      // no longer competes for the same screen (ruling 7a).
      const tr = $("home-trends-panel");
      if (tr) tr.style.display = "none";
    }
    // Re-sync after an async panel loader unhides its panel: the subtab list is
    // built from what is actually available, so a panel that arrives late must be
    // able to claim its tab (and must not stay force-hidden by a stale inline
    // style set before it had content).
    function _syncHomeSubtabs() {
      const nav = $("home-fam-subtabs");
      if (!nav) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const want = _HOME_PANEL_TABS.filter(p => { const el = $(p.id); return el && !el.hidden; })
        .map(p => p.key).join(",");
      const have = Array.prototype.slice.call(nav.querySelectorAll("button[data-tab]"))
        .map(b => b.dataset.tab).filter(k => _HOME_PANEL_TABS.some(p => p.key === k)).join(",");
      if (want === have) { selectHomeFamily(_homeTabKey); return; }
      _HOME_PANEL_TABS.forEach(p => {
        const btn = nav.querySelector(`button[data-tab="${p.key}"]`);
        const el = $(p.id), avail = !!(el && !el.hidden);
        if (avail && !btn) {
          const b = document.createElement("button");
          b.dataset.tab = p.key; b.textContent = t(p.label);
          nav.appendChild(b);
        } else if (!avail && btn) {
          if (_homeTabKey === p.key) _homeTabKey = "__ov";
          btn.remove();
        }
      });
      ooSubtabs(nav, selectHomeFamily, {initial: _homeTabKey});
      selectHomeFamily(_homeTabKey);
    }
    // The compact Trending row inside Overview (ruling 7a). Reuses the SAME stashed
    // payload the standalone panel already fetched — no second request, no new poll.
    function _renderOverviewTrends() {
      const host = $("ov-trending");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const terms = _homeTrendTerms || [];
      if (!terms.length) { host.innerHTML = ""; return; }
      const chips = terms.slice(0, 6).map(x =>
        `<a class="chip tiny" href="#" onclick='openAnalysisFor(${esc(JSON.stringify(x.term))});return false'`
        + ` title="${esc(t("Open this keyword's own analysis window"))}">${esc(x.term)}`
        + ` <span class="muted">${esc(growthFallback(x) || `↑${x.growth}× · ${x.recent}`)}</span></a>`).join("");
      host.innerHTML = `<div class="ov-trend"><span class="muted">${esc(t("Trending now"))}:</span>${chips}`
        + `<a class="ov-more" href="#" onclick="showTab('insights');return false">${esc(t("More in Insights"))} →</a></div>`
        + (_homeTrendCaveat ? `<div class="hint muted" style="font-size:11px">${esc(_homeTrendCaveat)}</div>` : "");
    }

    // The query that reproduces a card's article selection in the analysis window
    // (maintainer 2026-06-16: clicking a card opens the unified analysis interface
    // "whose corpus corresponds to the selection of articles the card identified").
    // Prefer the quoted term in the title (the original searchable surface form),
    // then the card key (the normalized term/identity), then the bare title. For
    // keyword/topic cards this is the EXACT, full selection (openAnalysisFor re-runs
    // the same FTS search); for set-based cards it is the closest honest query and
    // the analysis window states its scope.
    function cardAnalyzeQuery(c) {
      const m = (c.title || "").match(/[“"]([^”"]{2,})[”"]/);
      if (m && m[1].trim()) return m[1].trim();
      if (c.key && String(c.key).trim()) return String(c.key).trim();
      return (c.title || "").replace(/[“”"]/g, "").trim();
    }
    // S4.5: a card's DISPLAY title. When the producer emits a translatable title
    // (title_i18n = a fixed keyable template + title_vars = language-neutral data),
    // render OOI18N.tf(template, vars) — the frame translates ×12, the keyword term
    // stays data. Otherwise the English `title` (additive fallback; cards without a
    // template, or a browser without tf, are byte-identical to before).
    function cardTitle(c) {
      if (c && c.title_i18n && window.OOI18N && OOI18N.tf) return OOI18N.tf(c.title_i18n, c.title_vars || {});
      return (c && c.title) || "";
    }
    // Click a Lead card to FLIP it (front <-> back). Inner controls (buttons/links/
    // inputs) are not flip triggers. Keyboard: Enter/Space flips when focused.
    function leadFlip(card, ev) {
      if (ev && ev.target && ev.target.closest("button,a,input,label,details,summary")) return;
      card.classList.toggle("flipped");
    }
    function leadFlipKey(card, ev) {
      if ((ev.key === "Enter" || ev.key === " ") &&
          !(ev.target && ev.target.closest("button,a,input,label,details,summary"))) {
        ev.preventDefault();
        card.classList.toggle("flipped");
      }
    }
    // dblclick-opens-duplicate-analysis-tabs (P1): a fast double-click (or an
    // accidental double-tap) on a card's "Open corpus" button fired window.open()
    // twice at the identical URL before the first tab settled -- neither
    // openCardCorpus nor openAnalysisInNewTab guarded against a second call for the
    // same URL in quick succession. A single user action should be idempotent
    // against an accidental repeat activation, so both now route through one
    // shared debounce: a call for the SAME URL within 700ms of the last one is a
    // no-op (a deliberate second open of a DIFFERENT corpus a moment later still
    // works normally -- only the identical-URL-in-quick-succession case is guarded).
    let _lastCorpusOpenUrl = "", _lastCorpusOpenAt = 0;
    function _openCorpusUrlOnce(url) {
      const now = Date.now();
      if (url === _lastCorpusOpenUrl && (now - _lastCorpusOpenAt) < 700) return;
      _lastCorpusOpenUrl = url; _lastCorpusOpenAt = now;
      window.open(url, "_blank", "noopener");
    }
    // Open the card's corpus IN A NEW WINDOW (maintainer 2026-06-23) — a real browser
    // tab the SPA hydrates from the URL (boot handler below), so the analysis lives
    // outside the current view. Exact set when the card carries article_ids, else the
    // seed query (the diagnostic flags any card whose query loses its corpus).
    function openCardCorpus(ids, label, tab) {
      const p = new URLSearchParams();
      p.set("corpus", (ids || []).join(","));
      if (label) p.set("label", label);
      if (tab) p.set("tab", tab);   // item #5: land the new window on the type's best subtab
      _openCorpusUrlOnce("/?" + p.toString());
    }
    // Open a query's analysis window in a NEW BROWSER TAB (field remark 9: search +
    // Enter should open a new tab). A fresh SPA boot hydrates ?analyze= via
    // _hydrateCardCorpus() → openAnalysisFor(), so the new tab lands on the same
    // analysis. Shared by the home-card flip and the omnibar/palette Enter.
    function openAnalysisInNewTab(q, tab) {
      const p = new URLSearchParams();
      p.set("analyze", q || "");
      if (tab) p.set("tab", tab);   // optional deep-link subtab (item #5); omnibar Enter omits it
      _openCorpusUrlOnce("/?" + p.toString());
    }
    function openCardCorpusQuery(q, tab) { openAnalysisInNewTab(q, tab); }
    // Route a Lead to the most useful analysis subtab for its type (item #5): a rising
    // keyword -> its Trend; a coordination/near-dup/framing Lead -> Related; a reading-diet
    // or coverage Lead -> Sources; a space-time convergence -> When/Where/Who. Anything
    // else lands on Overview. The deep-link only applies a tab whose an-<tab> panel exists.
    const _CARD_SUBTAB = {
      rising: "trend", manufactured_emergence: "trend", price_narrative: "trend",
      echo_chamber: "related", source_laundering: "related", flooded_topic: "related",
      copypasta: "related", recycled_claim: "related", headline_body_mismatch: "related",
      framing_split: "related",
      diet_self_audit: "sources", coverage_advisor: "sources", reading_diet: "sources",
      space_time_convergence: "www", weather_corroboration: "www",
    };
    function cardSubtab(c) { return (c && _CARD_SUBTAB[c.type]) || "overview"; }
    function cardHtml(c) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sig = c.signal || {};
      const sigLine = (sig.metric != null && sig.value != null)
        ? `<div class="sig">${esc(sig.metric)} = ${esc(sig.value)}${c.n != null ? " · n=" + c.n : ""}</div>` : "";
      const evid = (c.evidence || []).filter(e => e && (e.url || e.title)).slice(0, 3).map(e => {
        const label = esc(e.title || e.url);
        const meta = [e.source, (e.published_at || "").slice(0,10)].filter(Boolean).map(esc).join(" · ");
        // External evidence opens the LOCAL preview first (invariant #6
        // extension, maintainer-repeated first target): never a bare jump.
        const ext = e.url && /^https?:\/\//i.test(e.url);
        const link = e.article_id
          ? `<a href="/api/articles/${e.article_id}/view" target="_blank" rel="noopener" title="offline stored copy">${label}</a>`
          : (e.url
            ? (ext
              ? `<a href="${esc(safeUrl(e.url))}" onclick="event.preventDefault();openLinkPreview('${esc(safeUrl(e.url))}')" title="Opens the local preview first — what your database knows about this link">${label}</a>`
              : `<a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${label}</a>`)
            : label);
        return `<span>${link}${meta ? ` <span class="muted">— ${meta}</span>` : ""}</span>`;
      }).join("");
      const evidBlock = evid ? `<div class="evid">${evid}</div>` : "";
      const dismiss = c.dismissible === false ? ""
        : `<button class="ghost tiny" onclick="dismissCard(${esc(JSON.stringify(c.id))}, ${esc(JSON.stringify(c.type || ''))})">Dismiss</button>`;
      // Echo-chamber cards carry an actor signature: offer user-guided collapse (never auto).
      let collapseBtn = "";
      if (c.type === "echo_chamber" && sig.signature) {
        collapseBtn = sig.collapse_applied
          ? `<button class="secondary tiny" onclick="cardCollapse('${esc(sig.signature)}', false)">Expand (revert)</button>`
          : `<button class="secondary tiny" onclick="cardCollapse('${esc(sig.signature)}', true)" title="Count this coordinated network as one voice (reversible, stays flagged)">Collapse to one actor</button>`;
      }
      // Weather-corroboration cards (if-this-then-SUGGEST, 2026-06-12): the
      // bounded Open-Meteo fetch happens ONLY from this button, behind the one
      // consent popup — the producer that made the card never touched the network.
      let weatherBtn = "";
      let weatherBox = "";
      if (c.type === "weather_corroboration" && sig.lat != null && sig.lon != null) {
        weatherBtn = `<button class="secondary tiny" onclick="cardWeatherFetch('${c.id}')" title="Fetches the bounded Open-Meteo slice for this place and window — only after your consent.">Fetch weather context</button>`;
        weatherBox = `<div class="wx" id="wx-${c.id}" style="margin-top:6px"></div>`;
      }
      // Investigation recipe (0.0.8 WP8/RM-20): opens /investigate in a NEW tab,
      // fully URL-parameterised (shareable, no hidden state), main UI stays put.
      let recipeBtn = "";
      if (c.recipe && c.recipe.view) {
        const qp = new URLSearchParams({view: c.recipe.view, ...(c.recipe.params || {})});
        recipeBtn = `<a class="btnlike tiny" href="/investigate?${qp.toString()}" target="_blank" rel="noopener" title="Opens a dedicated investigation view in a new tab">Open investigation ↗</a>`;
      }
      // Flip cards (maintainer 2026-06-23): the front is the lead at a glance; the
      // BACK carries the method + the exact math + the caveat + evidence + the action
      // row. The verbose "why"/math is no longer behind a per-card "?" — the flip IS
      // the detail layer (the back has room). Labels are i18n-translated; math values
      // are numbers/symbols (language-neutral).
      const _whyRows = (c.trigger && c.trigger.math || []).map(r =>
        `<tr><td>${esc(r.label)}</td><td class="why-val">${esc(r.value)}</td></tr>`).join("");
      const _whyPlain = (c.trigger && c.trigger.plain) ? `<p class="why-plain">${esc(c.trigger.plain)}</p>` : "";
      const methodBlock = c.method ? `<div class="mc"><b>${esc(t("Method"))}:</b> ${esc(c.method)}</div>` : "";
      const mathBlock = _whyRows
        ? `<details class="card-info"><summary>${esc(t("The exact math"))}</summary>
             <table class="why-math">${_whyRows}</table></details>` : "";
      // The CAVEAT is VISIBLE on the BACK — an equal side of the card, revealed by ONE
      // flip (never a hidden toggle), right beside the action that opens its corpus
      // (#23 amended 2026-06-23 / informed-consent preserved by LAYERING, not hiding).
      const caveatLine = c.caveat ? `<p class="card-caveat">${esc(c.caveat)}</p>` : "";
      // The standardized, family-themed "open corpus" button — opens the card's corpus
      // IN A NEW WINDOW (exact set when the card carries article_ids, else the seed query).
      const _aq = cardAnalyzeQuery(c);
      const _aIds = (Array.isArray(c.article_ids) && c.article_ids.length) ? c.article_ids : null;
      const _tab = cardSubtab(c);   // item #5: the most useful analysis subtab for this Lead's type
      const _openCorpus = _aIds
        ? `openCardCorpus(${esc(JSON.stringify(_aIds))}, ${esc(JSON.stringify(_aq))}, ${esc(JSON.stringify(_tab))})`
        : `openCardCorpusQuery(${esc(JSON.stringify(_aq))}, ${esc(JSON.stringify(_tab))})`;
      const openBtn = _aq
        ? `<button class="lead-open" onclick="${_openCorpus}" title="${esc(t("Open this Lead's corpus in a new window"))}">${esc(t("Open corpus"))} ↗</button>`
        : "";
      const chip = `<span class="chip">${esc(c.type.replace(/_/g, " "))}</span>`;
      const _title = cardTitle(c);
      // lead-card-nested-interactive (P1, axe): role="button" tabindex="0" on this
      // OUTER container, while it ALSO hosted genuinely interactive descendants
      // (the back face's buttons/links once flipped), is an invalid ARIA pattern --
      // a "button" must not contain more focusable content. leadFlip/leadFlipKey
      // already guarded against clicks/keys originating from a nested interactive
      // element (so the CLICK BEHAVIOUR was already correct), but the STRUCTURE
      // itself was wrong. Fixed by moving the interactive button role onto the
      // FRONT face specifically (it has no interactive children of its own -- chip/
      // heading/summary/sig-line/hint are all plain text), and giving the BACK
      // face's own "Back" hint its own small, explicitly-scoped button instead of
      // relying on the whole (interactive-descendant-hosting) back face being
      // itself a button. The outer container is now role="group" -- a plain
      // semantic wrapper, not an interactive element that could conflict with what
      // it contains.
      return `<div class="card bk-${esc(c.bucket)}" data-card="${c.id}" role="group" aria-label="${esc(_title)}">
        <div class="card-inner">
          <div class="card-face card-front" tabindex="0" role="button" aria-label="${esc(_title)}"
               onclick="leadFlip(this.closest('.card'),event)" onkeydown="leadFlipKey(this.closest('.card'),event)">
            ${chip}
            <h4>${esc(_title)}</h4>
            <p class="sum">${esc(c.summary)}</p>
            ${sigLine}
            <span class="lead-flip-hint">${esc(t("Details & corpus"))} ⟲</span>
          </div>
          <div class="card-face card-back">
            ${chip}
            ${caveatLine}
            ${methodBlock}
            ${(_whyPlain || mathBlock) ? `<div class="why-mathlabel">${esc(t("Why am I seeing this?"))}</div>` : ""}
            ${_whyPlain}
            ${mathBlock}
            ${evidBlock}
            ${weatherBox}
            <div class="acts">
              ${openBtn}
              ${recipeBtn}
              ${weatherBtn}
              <button class="secondary tiny" onclick="addToDraft('${c.id}')">+ Add to draft</button>
              ${collapseBtn}
              ${dismiss}
            </div>
            <button class="lead-flip-hint back" onclick="leadFlip(this.closest('.card'))">⟲ ${esc(t("Back"))}</button>
            <!-- the Back button intentionally omits ",event": leadFlip's own
                 interactive-descendant guard (ev.target.closest("button,a,...")) would
                 always match the button ITSELF (ev.target IS the button), silently
                 blocking every flip-back click. Passing no event makes the guard's
                 "ev &&" check false, so it falls straight to the toggle -- exactly what
                 a dedicated, single-purpose flip-back control should do. -->
          </div>
        </div></div>`;
    }

    // The global "Show method" toggle was retired (P2-2, 2026-06-19): each Lead's
    // method + "why" now live behind a per-card "?" affordance (cardHtml -> infoBlock).

    // Reasons offered when dismissing a Lead (the evidence-tier feedback loop). The chip
    // KEYS are stable identifiers; only the labels translate. A free-text box captures
    // anything the chips don't cover.
    function _leadDismissReasons() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return [
        ["not-relevant", t("Not relevant")],
        ["already-knew", t("Already knew this")],
        ["too-noisy", t("Too noisy / repetitive")],
        ["not-useful", t("Not useful")],
        ["disagree", t("I don't think this holds")],
      ];
    }
    // Dismissing a Lead offers an OPTIONAL reason (POST /api/signals/dismiss-reason). The
    // reason is recorded SEPARATELY from the dismissed-id set, so a failed record never
    // blocks the (unchanged) dismissal mechanic (_dismissCardNow). A chip dismisses with
    // that reason; the text box + Dismiss confirm with typed text; "Dismiss" with an empty
    // box is a valid skip (an explicit "dismissed, no reason" — nothing is sent).
    function dismissCard(id, type) {
      const el = document.querySelector(`.card[data-card="${id}"]`);
      const acts = el && el.querySelector(".acts");
      if (!acts) { _dismissCardNow(id); return; }               // no card back — just dismiss
      if (acts.querySelector(".lead-dismiss-form")) return;     // already open
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const form = document.createElement("div");
      form.className = "lead-dismiss-form";
      form.style.cssText = "margin-top:6px;width:100%";
      form.addEventListener("click", (e) => e.stopPropagation());   // never flip the card while choosing
      const label = document.createElement("div");
      label.className = "hint"; label.textContent = t("Why dismiss? (optional)");
      const chips = document.createElement("div");
      chips.className = "lead-dreasons"; chips.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin:4px 0";
      _leadDismissReasons().forEach(([k, lbl]) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "ghost tiny"; b.textContent = lbl;
        b.addEventListener("click", (e) => { e.stopPropagation(); _leadDismissWith(id, type, k); });
        chips.appendChild(b);
      });
      const row = document.createElement("div");
      row.className = "row"; row.style.cssText = "gap:6px";
      const inp = document.createElement("input");
      inp.className = "lead-dreason-text"; inp.type = "text";
      inp.placeholder = t("Add a reason…"); inp.style.flex = "1";
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.stopPropagation(); _leadDismissWith(id, type, inp.value.trim()); }
      });
      const go = document.createElement("button");
      go.type = "button"; go.className = "ghost tiny"; go.textContent = t("Dismiss");
      go.addEventListener("click", (e) => { e.stopPropagation(); _leadDismissWith(id, type, inp.value.trim()); });
      row.appendChild(inp); row.appendChild(go);
      form.appendChild(label); form.appendChild(chips); form.appendChild(row);
      acts.appendChild(form);
      inp.focus();
    }
    function _leadDismissWith(id, type, reason) {
      // Record the OPTIONAL reason (best-effort — never blocks the dismissal); a blank
      // reason is a valid skip and is not sent.
      if (reason) {
        api("/api/signals/dismiss-reason", {method: "POST",
          body: JSON.stringify({card_id: id, reason: reason, card_type: type || null})}).catch(() => {});
      }
      _dismissCardNow(id);
    }
    async function _dismissCardNow(id) {
      try {
        await api("/api/briefing/dismiss", {method:"POST", body: JSON.stringify({id})});
        const el = document.querySelector(`.card[data-card="${id}"]`);
        if (el) el.remove();
      } catch (e) { toast("Could not dismiss: " + e.message, "err"); }
    }

    // --- Local link preview (invariant #6 extension) ---------------------------
    // The database extraction for an outbound URL, shown BEFORE leaving the
    // machine; the outbound anchor's text IS the full address, and clicking it
    // still passes the external-link confirm (invariant #7) — layered consent.
    //
    // extLink(): the ONE way to render an outbound "source ↗" link anywhere
    // (invariant #6e — search rows, markets, law, events, insights, reader…).
    // It never jumps straight out: it opens the local preview first. Use this
    // for every external source link so none can regress to a bare jump.
    // evidence-links-contrast-and-no-underline (P1): these links rendered at
    // 2.41:1 with no underline (axe: link-in-text-block) -- color alone is
    // insufficient distinction per WCAG 1.4.1. The shared "ext-link" class
    // (app.css) adds a permanent underline, since this IS the one shared
    // chokepoint every evidence link renders through.
    function extLink(url, label, cls, style) {
      const u = safeUrl(url);
      const classes = cls ? `ext-link ${cls}` : "ext-link";
      return `<a class="${classes}"${style ? ` style="${style}"` : ""} href="${esc(u)}" rel="noopener" `
        + `onclick="event.preventDefault();openLinkPreview('${esc(u)}')" `
        + `title="Opens the local preview first — what your database knows about this link">`
        + `${esc(label)}</a>`;
    }
    async function openLinkPreview(url) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const dlg = $("link-preview"), body = $("lp-body"), out = $("lp-out");
      if (!dlg) { window.open(url, "_blank", "noopener"); return false; }
      body.textContent = t("Loading…"); out.innerHTML = "";
      dlg.showModal();
      try {
        const d = await api("/api/links/preview?url=" + encodeURIComponent(url));
        const rows = [`<div class="muted small">${esc(d.domain)}</div>`];
        if (d.local_article) {
          rows.push(`<div>${esc(t("A stored local copy exists — read it without going online:"))} <a href="${esc(d.local_article.reader_url)}" target="_blank" rel="noopener">${esc(d.local_article.title || "")}</a></div>`);
        }
        if (d.known_source) {
          rows.push(`<div>${esc(t("Known source in your catalog:"))} <b>${esc(d.known_source.name)}</b>${d.known_source.country ? ` <span class="muted">(${esc(ooRegionName(d.known_source.country, String(d.known_source.country).toUpperCase()))})</span>` : ""}</div>`);
        }
        rows.push(`<div>${esc(t("Articles in your corpus citing this URL:"))} <b>${d.cited_by_articles}</b></div>`);
        if ((d.citing_examples || []).length) {
          rows.push(`<div class="muted small">${d.citing_examples.map(x => `<a href="/api/articles/${x.article_id}/view" target="_blank" rel="noopener">${esc(x.title || ("#" + x.article_id))}</a>`).join(" · ")}</div>`);
        }
        if (d.law_document) rows.push(`<div>${esc(t("Tracked law document:"))} <b>${esc(d.law_document.title)}</b> <span class="muted">(${esc(String(d.law_document.jurisdiction || "").toUpperCase())})</span></div>`);
        if (d.wiki_page) rows.push(`<div>${esc(t("Watched Wikipedia page:"))} <b>${esc(d.wiki_page.title)}</b> <span class="muted">(${esc(d.wiki_page.wiki)})</span></div>`);
        if (d.keywords && d.keywords.length) rows.push(`<div class="muted small">${esc(t("Top keywords of the local copy:"))} ${d.keywords.map(esc).join(", ")}</div>`);
        if (!d.local_article && !d.known_source && !d.cited_by_articles) rows.push(`<div class="muted">${esc(t("No local record of this link yet."))}</div>`);
        rows.push(`<div class="muted small" style="margin-top:4px" title="${esc(d.method || "")}">${esc(t("Built from your local database only — no network call."))}</div>`);
        body.innerHTML = rows.join("");
        out.innerHTML = `<div class="muted small">${esc(t("The transparent outbound link — its text is the full address; opening it leaves this machine:"))}</div>` +
          `<a href="${esc(safeUrl(d.url))}" target="_blank" rel="noopener noreferrer" style="word-break:break-all">${esc(d.url)}</a>`;
      } catch (e) {
        body.innerHTML = `<div class="note err">${esc(e.message)}</div>`;
        out.innerHTML = `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer" style="word-break:break-all">${esc(url)}</a>`;
      }
      return false;
    }

    // --- Weather corroboration (if-this-then-SUGGEST, 2026-06-12) -------------
    // The card only OFFERS the check; this click is the consent moment. The
    // fetch is one bounded (place, window) reanalysis slice through the same
    // ethical fetch path as everything else; failures render the honest
    // transport verdict, results render per-variable (one chart per unit —
    // mixed units on one axis would be a fabricated comparison).
    async function cardWeatherFetch(id) {
      const c = _briefCards[id]; if (!c) return;
      const sig = c.signal || {};
      const box = document.getElementById("wx-" + id); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (!await ensureOnline(t("Fetch weather context for one place and time window (Open-Meteo)"))) return;
      box.textContent = t("Loading…");
      try {
        const body = {
          lat: sig.lat, lon: sig.lon,
          start_date: sig.window_start, end_date: sig.window_end,
          variables: String(sig.variables || "").split(",").filter(Boolean),
          label: sig.rule_label || c.title
        };
        const d = await api("/api/weather/context", {method: "POST", body: JSON.stringify(body)});
        renderWeatherContext(box, d, sig);
      } catch (e) {
        box.innerHTML = `<div class="note err">${esc(e.message)}</div>`;
      }
    }

    function renderWeatherContext(box, d, sig) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (!d || !d.ok) {
        const verdict = d ? `${d.verdict || ""} — ${d.verdict_note || ""}` : "";
        box.innerHTML = `<div class="note err"><b>${esc(t("Weather fetch refused:"))}</b> <span>${esc(verdict)}</span></div>`;
        return;
      }
      const days = (d.daily && d.daily.time) || [];
      const vars = Object.keys(d.daily || {}).filter(k => k !== "time");
      let html = "";
      vars.forEach(k => {
        html += `<div class="muted" style="margin:4px 0 2px">${esc(k)}${d.units && d.units[k] ? " (" + esc(d.units[k]) + ")" : ""}</div><div class="wx-chart" data-var="${esc(k)}"></div>`;
      });
      const prov = d.provenance || {};
      const facts = [
        prov.fetched_at ? prov.fetched_at.slice(0, 16).replace("T", " ") + " UTC" : "",
        d.cached ? t("cached copy") : "",
        (sig && sig.geocode) ? `geocode: ${sig.geocode}` : ""
      ].filter(Boolean).join(" · ");
      html += `<div class="muted small" style="margin-top:4px"><span title="${esc(prov.requested_url || "")}">${esc(t("Open-Meteo reanalysis (CC BY 4.0): a model estimate for this place and window — corroboration, never proof."))}</span> <span>${esc(facts)}</span></div>`;
      box.innerHTML = html;
      box.querySelectorAll(".wx-chart").forEach(el => {
        const k = el.getAttribute("data-var");
        const pts = days.map((dt, i) => ({t: dt, v: (d.daily[k] || [])[i]})).filter(p => p.v != null);
        if (pts.length) {
          try { ooChart(el, [{label: k, unit: (d.units && d.units[k]) || "", points: pts}], {height: 120}); }
          catch (_e) { el.textContent = pts.map(p => `${p.t}: ${p.v}`).join("  "); }
        } else {
          el.innerHTML = `<span class="muted small">${esc(t("No values were returned for this variable and window."))}</span>`;
        }
      });
    }

    // -- The newsletter draft (card → reproducible Markdown) ---------------- //
    async function addToDraft(id) {
      const card = _briefCards[id];
      if (!card) return;
      try {
        const d = await api("/api/briefing/draft/add", {method:"POST", body: JSON.stringify({card})});
        updateDraftCount(d.items.length);
        // Clickable (maintainer-ruled 2026-06-10): the confirmation IS the way in.
        toast("Added to draft — click to open it.", "ok", () => { showTab("home"); openDraft(); });
      } catch (e) { toast("Could not add to draft: " + e.message, "err"); }
    }
    async function refreshDraftCount() {
      try { const d = await api("/api/briefing/draft"); updateDraftCount((d.items||[]).length);
        const t = $("draft-title"); if (t && d.title) t.value = d.title; }
      catch (e) { /* draft is optional */ }
    }
    function updateDraftCount(n) { const el = $("draft-count"); if (el) el.textContent = n; }

    async function openDraft() {
      $("draft-panel").hidden = false;
      await renderDraft();
      $("draft-panel").scrollIntoView({behavior:"smooth", block:"start"});
    }
    function closeDraft() { $("draft-panel").hidden = true; }

    async function renderDraft() {
      const box = $("draft-items");
      try {
        const d = await api("/api/briefing/draft");
        updateDraftCount((d.items||[]).length);
        const t = $("draft-title"); if (t) t.value = d.title || "";
        if (!d.items || !d.items.length) { box.innerHTML = '<div class="muted">No Leads pinned yet. Use “+ Add to draft” on a briefing Lead.</div>'; return; }
        box.innerHTML = d.items.map(it => {
          const c = it.card;
          return `<div class="draft-item" data-id="${c.id}">
            <div class="di-body">
              <div class="di-title">${esc(c.title)}</div>
              <div class="hint" style="margin-top:2px">${esc(c.summary || "")}</div>
              <textarea placeholder="Your note (ships in the export)…" onchange="saveDraftItemNote('${c.id}', this.value)">${esc(it.note||"")}</textarea>
            </div>
            <button class="ghost tiny" onclick="removeDraftItem('${c.id}')">Remove</button>
          </div>`;
        }).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load the draft.</div>'; }
    }
    async function removeDraftItem(id) {
      try { const d = await api("/api/briefing/draft/" + encodeURIComponent(id), {method:"DELETE"});
        updateDraftCount((d.items||[]).length); renderDraft(); } catch (e) { toast(e.message, "err"); }
    }
    async function saveDraftItemNote(id, note) {
      try { await api("/api/briefing/draft/note", {method:"PUT", body: JSON.stringify({id, note})}); }
      catch (e) { toast("Could not save note: " + e.message, "err"); }
    }
    async function saveDraftTitle() {
      try { await api("/api/briefing/draft/title", {method:"PUT", body: JSON.stringify({title: $("draft-title").value})}); }
      catch (e) { toast(e.message, "err"); }
    }
    async function clearDraft() {
      if (!confirm("Clear all pinned Leads from the draft?")) return;
      try { await api("/api/briefing/draft/clear", {method:"POST"}); updateDraftCount(0); renderDraft(); }
      catch (e) { toast(e.message, "err"); }
    }
    function exportDraft() { window.open("/api/briefing/draft/export.md", "_blank"); }
    async function copyDraft() {
      try {
        const md = await (await fetch("/api/briefing/draft/export.md")).text();
        await navigator.clipboard.writeText(md);
        toast("Draft Markdown copied to clipboard.");
      } catch (e) { toast("Could not copy: " + e.message, "err"); }
    }

    // ===================================================================== //
    //  SOURCE INTEGRITY & ANTI-AMPLIFICATION (§6) — propose → you dispose     //
    // ===================================================================== //
    async function cardCollapse(signature, apply) {
      try {
        await api("/api/integrity/collapse/" + (apply ? "apply" : "revert"),
          {method:"POST", body: JSON.stringify({signature})});
        toast(apply ? "Collapsed to one actor (reversible)." : "Expanded — raw equal view restored.");
        await refreshBriefing();            // counts that measure consensus now reflect the choice
      } catch (e) { toast("Could not update collapse: " + e.message, "err"); }
    }

    function loadIntegrity() { loadMineAnnotations(); loadAuthors(); }

    async function loadActors() {
      const box = $("actors-list");
      box.innerHTML = '<div class="muted">Scanning recent corpus for coordination…</div>';
      try {
        const d = await api("/api/integrity/actors");
        if (!d.actors || !d.actors.length) {
          box.innerHTML = '<div class="muted">No coordinated near-duplicate clusters found in the recent window.</div>'; return;
        }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` + d.actors.map(a => {
          const members = a.sources.map(esc).join(", ");
          const btn = a.applied
            ? `<button class="secondary tiny" onclick="collapseAction('${esc(a.signature)}', false)">Expand (revert)</button>`
            : `<button class="secondary tiny" onclick="collapseAction('${esc(a.signature)}', true)">Apply collapse</button>`;
          const flag = a.applied ? '<span class="pill ok">collapsed</span> ' : '<span class="pill warn">annotated only</span> ';
          return `<div class="panel" style="background:var(--panel2); margin-top:8px">
            ${flag}<b>${a.size} sources</b> · ${a.shared_stories} shared story(ies)
            ${a.shared_hosts && a.shared_hosts.length ? "· host "+esc(a.shared_hosts[0]) : ""}
            ${a.median_span_hours!=null ? "· ~"+a.median_span_hours+"h span" : ""}
            <div class="hint" style="margin-top:4px">${members}</div>
            <div class="acts" style="margin-top:6px">${btn}</div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not scan: ' + esc(e.message) + '</div>'; }
    }
    async function collapseAction(sig, apply) {
      try { await api("/api/integrity/collapse/" + (apply?"apply":"revert"), {method:"POST", body: JSON.stringify({signature: sig})});
        loadActors(); } catch (e) { toast(e.message, "err"); }
    }
    async function revertAllCollapse() {
      try { await api("/api/integrity/collapse/revert_all", {method:"POST"}); toast("All collapses reverted."); loadActors(); }
      catch (e) { toast(e.message, "err"); }
    }

    async function loadProfile() {
      const src = $("prof-source").value.trim(); if (!src) return;
      const out = $("profile-out");
      out.innerHTML = '<div class="muted">Measuring…</div>';
      try {
        const p = await api("/api/integrity/profile?source=" + encodeURIComponent(src));
        const d = p.dimensions;
        const dim = (title, body, m, c) => `<div class="panel" style="background:var(--panel2); margin-top:8px">
          <b>${esc(title)}</b><div style="margin-top:4px">${body}</div>
          <div class="hint" style="margin-top:4px"><i>Method:</i> ${esc(m)}<br><i>Caveat:</i> ${esc(c)}</div></div>`;
        const co = d.coordination, nv = d.novelty, oc = d.output_capacity, tr = d.transparency, rec = d.track_record;
        out.innerHTML =
          `<p class="hint"><b>No composite score</b> — these are independent measured dimensions you weigh yourself.</p>` +
          dim("Coordination", co.is_member ? `Member of ${co.actors.length} detected actor(s).` : "No coordination detected.", co.method, co.caveat) +
          dim("Novelty (originates vs echoes)", nv.mean_ratio==null ? "Not enough data." : `Mean novelty <b>${nv.mean_ratio}</b> over ${nv.n} articles.`, nv.method, nv.caveat) +
          dim("Output capacity", `${oc.articles} articles · ~${oc.per_day}/day (corpus median ${oc.corpus_median_per_day}/day).`, oc.method, oc.caveat) +
          dim("Transparency", `${esc(tr.country?ooRegionName(tr.country,tr.country):"?")} · ${esc(tr.language?ooLangName(tr.language):"?")} · ownership: ${(tr.ownership_tags||[]).join(", ")||"—"} · leaning: ${(tr.leaning_tags||[]).join(", ")||"—"}`, tr.method, tr.caveat) +
          dim("Track record", `${rec.total_articles} articles in your corpus.`, rec.method, rec.caveat);
      } catch (e) { out.innerHTML = '<div class="muted">' + esc(e.message) + '</div>'; }
    }

    // -- Crowdsourced annotations (web of trust) ---------------------------- //
    async function addAnnotation() {
      const target = $("anno-target").value.trim(), kind = $("anno-kind").value, value = $("anno-value").value.trim();
      if (!target || !value) { toast("Target and value are required.", "err"); return; }
      try { await api("/api/annotations/mine", {method:"POST", body: JSON.stringify({target, kind, value})});
        $("anno-value").value = ""; loadMineAnnotations(); toast("Annotation added."); }
      catch (e) { toast(e.message, "err"); }
    }
    async function loadMineAnnotations() {
      const box = $("anno-mine");
      try {
        const d = await api("/api/annotations/mine");
        if (!d.annotations || !d.annotations.length) { box.innerHTML = '<div class="muted">No annotations yet.</div>'; return; }
        box.innerHTML = d.annotations.map((a, i) =>
          `<div class="draft-item"><div class="di-body"><b>${esc(a.target)}</b> · <span class="chip">${esc(a.kind)}</span> ${esc(a.value)}
            ${a.note ? '<div class="hint">'+esc(a.note)+'</div>' : ''}</div>
            <button class="ghost tiny" onclick="removeAnnotation(${i})">Remove</button></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load.</div>'; }
    }
    async function removeAnnotation(i) {
      try { await api("/api/annotations/mine/" + i, {method:"DELETE"}); loadMineAnnotations(); } catch (e) { toast(e.message, "err"); }
    }
    function exportAnnotations() { window.open("/api/annotations/export", "_blank"); }
    async function importAnnotations(input) {
      const file = input.files && input.files[0]; if (!file) return;
      try {
        const bundle = JSON.parse(await file.text());
        const r = await api("/api/annotations/import", {method:"POST", body: JSON.stringify({bundle})});
        toast(`Imported ${r.annotations} annotation(s) from ${r.author_name}.`);
        loadAuthors();
      } catch (e) { toast(_failMsg("Import failed: {error}", e), "err"); }
      finally { input.value = ""; }
    }
    async function loadAuthors() {
      const box = $("anno-authors");
      try {
        const d = await api("/api/annotations/authors");
        if (!d.authors || !d.authors.length) { box.innerHTML = '<div class="muted">No imported authors yet.</div>'; return; }
        box.innerHTML = d.authors.map(a =>
          `<div class="draft-item"><div class="di-body"><b>${esc(a.author_name||a.author_id.slice(0,12))}</b>
            <span class="hint">· ${a.annotations} annotation(s) · ${esc(a.author_id.slice(0,16))}…</span></div>
            <label class="switch" style="margin-top:0"><input type="checkbox" ${a.trusted?"checked":""}
              onchange="trustAuthor('${a.author_id}', this.checked)"> trust</label>
            <button class="ghost tiny" onclick="removeAuthor('${a.author_id}')">Remove</button></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load.</div>'; }
    }
    async function trustAuthor(id, trusted) {
      try { await api("/api/annotations/authors/trust", {method:"PUT", body: JSON.stringify({author_id:id, trusted})}); }
      catch (e) { toast(e.message, "err"); }
    }
    async function removeAuthor(id) {
      try { await api("/api/annotations/authors/" + encodeURIComponent(id), {method:"DELETE"}); loadAuthors(); }
      catch (e) { toast(e.message, "err"); }
    }
    async function lookupAnnotations() {
      const target = $("anno-lookup").value.trim(); if (!target) return;
      const box = $("anno-aggregate");
      try {
        const d = await api("/api/annotations/for?target=" + encodeURIComponent(target));
        if (!d.total_assertions) { box.innerHTML = '<div class="muted">No annotations for that source (from you or trusted authors).</div>'; return; }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` +
          (d.dissent_kinds.length ? `<p class="hint"><b>Dissent on:</b> ${d.dissent_kinds.map(esc).join(", ")}</p>` : "") +
          d.claims.map(c => `<div class="draft-item"><div class="di-body"><span class="chip">${esc(c.kind)}</span> <b>${esc(c.value)}</b>
            <div class="hint">asserted by: ${c.asserted_by.map(a=>esc(a.author)).join(", ")}</div></div></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">' + esc(e.message) + '</div>'; }
    }

    // ===================================================================== //
    //  WORLD LAW — change tracking (§5)                                       //
    // ===================================================================== //
    // -- Agenda (world events): subscribe to calendars, filter & group ------ //
    const _MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const AG = { events: [], cals: [], caveat: "", meta: {}, categories: [] };
    // The agenda calendar SUBSCRIPTIONS now live SERVER-SIDE (GET/PUT /api/agenda/prefs,
    // D4) so they survive a browser reset AND a reinstall and ride backups — they used to
    // sit in localStorage ("oo.agenda.subs"), invisible to the server and to every backup.
    // Loaded once per agenda open into this in-memory cache so the sync getters stay
    // synchronous; the setter fires a best-effort PUT (the UI never blocks on the
    // round-trip). `configured=false` means the server has no explicit choice yet, so we
    // keep the first-run default (subscribe to EVERY calendar) — never silently dropping a
    // first-run user's calendars. NOTE: feed EXCLUSIONS and the chosen VIEW deliberately
    // STAY per-machine in localStorage (below) — a per-device display/curation choice ruled
    // per-machine (2026-06-15), not a corpus-level subscription that should ride a backup.
    let _agPrefs = null;   // { subs: Set, configured: bool } — the server-backed subscriptions
    function _agPrefsDefault() { return { subs: new Set(), configured: false }; }
    async function agLoadPrefs() {
      try {
        const p = await api("/api/agenda/prefs");
        _agPrefs = { subs: new Set(p.subs || []), configured: !!p.configured };
      } catch (_e) {
        // Offline / pre-unlock / older backend: a permissive in-memory default so the
        // agenda still works; nothing is persisted until the server answers.
        if (!_agPrefs) _agPrefs = _agPrefsDefault();
      }
      return _agPrefs;
    }
    function agPutPrefs(patch) {
      // Persist a partial prefs update (best-effort — the in-memory cache already reflects
      // it, so a failed write only means it won't survive this session). Loopback only.
      api("/api/agenda/prefs", { method: "PUT", body: JSON.stringify(patch) }).catch(() => {});
    }
    function agSubs() { return new Set((_agPrefs || _agPrefsDefault()).subs); }
    function agSaveSubs(set) {
      if (!_agPrefs) _agPrefs = _agPrefsDefault();
      _agPrefs.subs = new Set(set); _agPrefs.configured = true;
      agPutPrefs({ subs: [..._agPrefs.subs] });
    }
    // Per-machine EXCLUDED feed families (ruled 2026-06-15: "remove = reversible
    // unsubscribe, never delete-from-catalog"; a per-machine store, kept in localStorage).
    // Excluded folders keep their honest verdicts in the directory (anti-hiding) but
    // contribute no imported events.
    function agExcluded() { try { return new Set(JSON.parse(localStorage.getItem("oo.agenda.excluded") || "null") || []); } catch (_e) { return new Set(); } }
    function agSaveExcluded(set) { localStorage.setItem("oo.agenda.excluded", JSON.stringify([...set])); }

    // An imported feed event (already cross-feed deduped server-side) mapped into
    // the agenda's event shape, flagged as the IMPORTED provenance class so it is
    // filterable and never silently blended with curated events.
    function mapImportedToAgenda(e) {
      const d = e.date || "";
      // "imported" is NOT a category — everything in the agenda is imported, so it
      // told the user nothing (maintainer 2026-06-18). Use the feed's REAL facets:
      // category = its kind (holidays / religion / civic / space / science /
      // community), the country, and tags so the agenda filters to a thin view.
      const kind = e.kind || "other";
      const tags = [kind].concat(e.country ? [e.country] : []);
      return {
        title: e.title, category: kind, country: e.country || null, tags: tags,
        confirmed: true,                       // an ICS VEVENT carries a concrete date
        next_occurrence: d,
        // month/day stay NULL deliberately (fix 2026-07-17): those fields are the
        // ANNUAL-RULE placement keys, and an imported VEVENT is evidence for ITS
        // year only. Filling them ghosted every dated instance into EVERY displayed
        // year — three contradictory moon phases on one day (each year's phases
        // drift ~11 days), a 2025 movable feast projected onto 2026, etc. Dated
        // instances place via next_occurrence alone; projecting a dated instance
        // to other years would be fabrication for anything movable.
        month: null,
        day: null,
        calendar: e.family, family_name: e.family_name, family_names: e.family_names,
        kind: kind, countries: e.countries || (e.country ? [e.country] : []),
        sources: e.sources || [], source_count: e.source_count, family_count: e.family_count,
        imported: true,
      };
    }
    // Article-DEDUCED dates → the agenda event shape (mirrors mapImportedToAgenda so
    // every view places them via next_occurrence for free). DEDUCED, never confirmed:
    // a date the text MENTIONS, not proof an event will happen. Clicking opens the
    // exact article set (openAnalysisForIds, via agRow). Counts only, no score.
    function mapDeducedToAgenda(e) {
      const d = e.date || "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return {
        title: t("{n} articles mention this date").replace("{n}", e.n_articles),
        category: "deduced", country: null, tags: [],
        confirmed: false,                      // deduced from text — never a confirmed event
        next_occurrence: d,
        // NULL like mapImportedToAgenda (fix 2026-07-17): a deduced DATE is
        // year-specific evidence; month/day are the annual-rule keys and would
        // ghost it into every displayed year.
        month: null,
        day: null,
        calendar: "deduced", deduced: true,
        article_ids: e.article_ids || [], n_articles: e.n_articles, n_sources: e.n_sources,
        note: t("Deduced from {n} articles ({s} sources), never confirmed.")
          .replace("{n}", e.n_articles).replace("{s}", e.n_sources),
      };
    }
    async function loadAgenda() {
      const box = $("agenda-list");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const today = new Date().toISOString().slice(0, 10);
        const [ev, fac, imp, ded] = await Promise.all([
          api("/api/events"), api("/api/events/calendars"),
          api("/api/events/imported?from=" + today).catch(() => ({ events: [] })),
          // Article-DEDUCED upcoming dates (the agenda's article-extracted layer).
          // Degrade quietly — never break the agenda if this is unavailable.
          api("/api/events/deduced").catch(() => ({ events: [] })),
          // Server-side subscription prefs (D4) — populates _agPrefs before agExcluded()
          // below reads it; a failure degrades to the permissive in-memory default.
          agLoadPrefs(),
        ]);
        const excl = agExcluded();
        const imported = (imp.events || []).map(mapImportedToAgenda).filter(e => !excl.has(e.calendar));
        const deduced = (ded.events || []).map(mapDeducedToAgenda).filter(e => !excl.has(e.calendar));
        AG.events = ev.events.concat(imported, deduced); AG.caveat = ev.caveat; AG.cals = fac.calendars;
        // Category chips = the REAL event kinds (holidays / religion / civic / …),
        // never a useless "imported" bucket (maintainer 2026-06-18). Imported events
        // each carry their feed's kind; deduced stays its own honest class. De-duped,
        // sorted, only kinds actually present so the chip row stays thin.
        const importedKinds = [...new Set(imported.map(e => e.category).filter(Boolean))].sort();
        AG.categories = [...new Set((fac.categories || []).concat(importedKinds))].sort()
          .concat(deduced.length ? ["deduced"] : []);
        AG.meta = Object.fromEntries(fac.calendars.map(c => [c.key, c]));
        // First run: the server has no explicit choice yet (configured=false) → default to
        // subscribing to EVERY calendar so the agenda isn't empty. Kept in-memory (NOT
        // persisted) until the user makes an explicit choice, so a newly-added catalog
        // calendar is auto-included and nothing is ever silently dropped (honors the flag).
        if (_agPrefs && !_agPrefs.configured) _agPrefs.subs = new Set(fac.calendars.map(c => c.key));
        $("agenda-country").innerHTML = '<option value="">all</option>' + fac.countries.map(x => `<option value="${esc(x)}">${agFlag(x)} ${esc(x)}</option>`).join("");
        $("agenda-tag").innerHTML = '<option value="">all</option>' + fac.tags.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
        if (!_agViewTabs) _agViewTabs = ooSubtabs($("agenda-views"), agendaSetView);
        renderAgendaCatChips();
        renderAgenda();
      } catch (e) { box.innerHTML = `<div class="muted">Could not load agenda: ${esc(e.message)}</div>`; }
      // The feed DIRECTORY is no longer loaded here: it moved to Settings → Advanced
      // (invariant #8 — this tab shows the agenda, not the catalogue that feeds it)
      // and loads only when that section is expanded. The agenda's own per-event
      // provenance pills do not depend on it: _agFeedById() self-loads the map on
      // first use when _feedDir is still null.
    }

    // -- The Bulletin (design record §13/§16) -------------------------------- //
    // A periodic document built from the corpus. Everything here is LOOPBACK: the
    // deterministic layer is SQL, the optional narration runs on the local model,
    // and nothing in this panel touches the network -- so no consent gate.
    //
    // The load-bearing mechanic: a producer toggle RE-RENDERS from the persisted
    // record. It recomputes nothing and edits nothing, so a number in a published
    // document is always a number the record contains. Excluding is done by
    // passing the exclusions to the render URL, never by writing a trimmed copy.
    // `t` is per-function in this file, never global, so the bulletin block gets its
    // own helper on the _gwT precedent -- a bare t() here passes node --check and
    // throws a ReferenceError in the browser.
    function _bulT(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
    // Guarded like _bulT, for the same reason: i18n.js may not have loaded. The
    // template is the key and the count is data, so the frame can be translated
    // later without the number ever going through a translation table.
    function _bulTf(s, vars) {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf(s, vars)
        : String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m);
    }
    let _bulExcludeSections = new Set();
    let _bulExcludeStories = new Set();
    let _bulFile = null;

    function _bulQuery() {
      const p = new URLSearchParams();
      if (_bulExcludeSections.size) p.set("exclude_sections", [..._bulExcludeSections].join(","));
      if (_bulExcludeStories.size) p.set("exclude_stories", [..._bulExcludeStories].join(","));
      // The document is written in the language the operator is READING the app in.
      // Built here, in the one place both the report and the annexes take their query
      // from, so the two can never come out in different languages.
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en";
      if (lang && lang !== "en") p.set("lang", lang);
      return p;
    }

    async function loadBulletin() {
      const gate = $("bulletin-gate"), controls = $("bulletin-controls");
      if (!gate) return;
      let g = null;
      try { g = await api("/api/bulletin/availability"); }
      catch (e) { gate.textContent = _bulT("Could not check this machine: ") + e.message; return; }
      if (!g.available) {
        // A refusal states its REASON and points at the override, because the
        // gate is never a hard block -- it is a default with a stated basis.
        gate.innerHTML = `<span>${esc(g.reason || _bulT("This machine cannot build a bulletin."))}</span>` +
          ` <span class="muted">${esc(_bulT("You can turn this on anyway in Settings → AI."))}</span>`;
        controls.hidden = true;
        return;
      }
      gate.hidden = true;
      controls.hidden = false;
      await loadBulletinEditions();
    }

    async function loadBulletinEditions() {
      const box = $("bulletin-list");
      if (!box) return;
      let d = null;
      try { d = await api("/api/bulletin/editions"); }
      catch (e) { box.innerHTML = `<div class="muted">${esc(_bulT("Could not list editions: ") + e.message)}</div>`; return; }
      const rows = d.editions || [];
      if (!rows.length) {
        box.innerHTML = `<div class="muted">${esc(_bulT("No editions yet. Build a draft above."))}</div>`;
        return;
      }
      box.innerHTML = `<div style="overflow:auto"><table><tr>
          <th>${esc(_bulT("Covers through"))}</th><th>${esc(_bulT("Period"))}</th><th></th></tr>` +
        rows.map(r => `<tr>
          <td>${esc(r.covers_through || r.filename)}</td>
          <td>${esc(r.cadence || "—")}</td>
          <td class="row" style="gap:6px;justify-content:flex-end">
            <button class="secondary" onclick="bulletinReview('${esc(r.filename)}')">${esc(_bulT("Review"))}</button>
            <button class="secondary" onclick="bulletinOpenFile('${esc(r.filename)}')">${esc(_bulT("Open"))}</button>
            <button class="secondary" onclick="bulletinDelete('${esc(r.filename)}')">${esc(_bulT("Delete"))}</button>
          </td></tr>`).join("") + "</table></div>";
    }

    async function bulletinGenerate(btn) {
      const status = $("bulletin-status");
      const cadence = ($("bul-cadence") || {}).value || "weekly";
      const narrate = !!($("bul-narrate") || {}).checked;
      btn.disabled = true;
      status.textContent = _bulT("Building…");
      try {
        const out = await api(
          `/api/bulletin/generate?cadence=${encodeURIComponent(cadence)}&persist=true&narrate=${narrate}`,
          {method: "POST"});
        status.textContent = out.persisted
          ? _bulT("Draft built.")
          : _bulT("Built, but not saved: ") + (out.persist_error || "");
        await loadBulletinEditions();
        if (out.filename) bulletinReview(out.filename);
      } catch (e) {
        status.textContent = _bulT("Could not build: ") + e.message;
      } finally { btn.disabled = false; }
    }

    async function bulletinReview(filename) {
      const box = $("bulletin-review");
      if (!box) return;
      _bulFile = filename;
      _bulExcludeSections = new Set();
      _bulExcludeStories = new Set();
      box.innerHTML = `<div class="muted">${esc(_bulT("Loading…"))}</div>`;
      let v = null;
      try { v = await api(`/api/bulletin/editions/${encodeURIComponent(filename)}/review`); }
      catch (e) { box.innerHTML = `<div class="muted">${esc(_bulT("Could not open this edition: ") + e.message)}</div>`; return; }
      _bulRender(v);
    }

    function _bulRender(v) {
      const box = $("bulletin-review");
      const state = v.state === "published"
        ? `<span class="pill">${esc(_bulT("published"))}</span>`
        : `<span class="pill">${esc(_bulT("draft"))}</span>`;
      const secs = (v.sections || []).map(s => {
        const off = _bulExcludeSections.has(s.section);
        // A section's REAL window is printed when it differs from the period --
        // §12's whole point is that a 14-day number in a 7-day edition is visible
        // during review rather than discovered afterwards.
        const w = s.window || {};
        const win = (w.days != null && w.matches_period === false)
          ? ` <span class="warn">${esc(_bulT("window:"))} ${esc(w.days)} ${esc(_bulT("days"))}</span>` : "";
        const why = s.error
          ? ` <span class="warn">${esc(_bulT("failed:"))} ${esc(s.error)}</span>`
          : (s.skipped ? ` <span class="muted">${esc(_bulT("skipped:"))} ${esc(s.skipped)}</span>` : "");
        return `<label class="row" style="gap:8px;align-items:baseline">
          <input type="checkbox" ${off ? "" : "checked"} onchange="bulletinToggleSection('${esc(s.section)}')">
          <span><strong>${esc(String(s.section).replace(/_/g, " "))}</strong>
            <span class="muted">${esc(s.rows)} ${esc(_bulT("row(s)"))}</span>${win}${why}</span></label>`;
      }).join("");

      const stories = (v.stories || []).map(s => {
        const off = _bulExcludeStories.has(s.key);
        // Per SENTENCE, per §13: a sentence you can see was checked is a different
        // thing from a paragraph labelled "validated".
        const sents = (s.sentences || []).map(x => x.kept
          ? `<li>${esc(x.text)}</li>`
          : `<li class="muted"><s>${esc(x.text)}</s> — ${esc(_bulT("dropped; not in the evidence:"))} ${esc((x.unsupported || []).join(", "))}</li>`
        ).join("");
        const label = s.narrated
          ? `<div class="warn">${esc(_bulT("AI-derived — unreliable"))}${s.partial ? esc(_bulT("; sentences naming something absent from the sources were removed")) : ""}</div>`
          : `<div class="muted">${esc(_bulT("No model text: "))}${esc(s.fallback_reason || "")}</div>`;
        return `<div style="margin:8px 0">
          <label class="row" style="gap:8px;align-items:baseline">
            <input type="checkbox" ${off ? "" : "checked"} onchange="bulletinToggleStory('${esc(s.key)}')">
            <span><strong>${esc((s.shared_terms || []).join(", ") || "—")}</strong>
              <span class="muted">${esc(s.articles)} ${esc(_bulT("articles"))} · ${esc(s.distinct_sources)} ${esc(_bulT("sources"))}${s.single_source ? esc(_bulT(" · one source only")) : ""}</span></span></label>
          ${label}${sents ? `<ul style="margin:4px 0 0 26px">${sents}</ul>` : ""}</div>`;
      }).join("");

      box.innerHTML = `<h3 style="margin:0 0 4px">${esc(_bulT("Review"))} ${state}</h3>
        <p class="hint" style="margin-top:0">${esc(v.caveat || "")}</p>
        <p class="hint">${esc(v.method || "")}</p>
        <h4 style="margin:12px 0 4px">${esc(_bulT("Sections"))}</h4>${secs || `<div class="muted">${esc(_bulT("None."))}</div>`}
        ${stories ? `<h4 style="margin:12px 0 4px">${esc(_bulT("Stories"))}</h4>${stories}` : ""}
        <div class="row" style="gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="secondary" onclick="bulletinOpen('html')">${esc(_bulT("Preview"))}</button>
          <button class="secondary" onclick="bulletinDownloadBundle(this)">${esc(_bulT("Download report + annexes"))}</button>
          <button class="secondary" onclick="bulletinOpen('markdown')">${esc(_bulT("Report only"))}</button>
          <button onclick="bulletinPublish(this)">${esc(_bulT("Publish"))}</button>
          <div id="bul-pub" class="hint" style="align-self:center"></div>
        </div>
        <p class="hint">${esc(_bulT("The annexes are one Markdown file per article the report cites, numbered to match, with a contents page. They carry the sources' own text — keep them where you keep the corpus."))}</p>`;
    }

    function bulletinToggleSection(key) {
      if (_bulExcludeSections.has(key)) _bulExcludeSections.delete(key);
      else _bulExcludeSections.add(key);
    }
    function bulletinToggleStory(key) {
      if (_bulExcludeStories.has(key)) _bulExcludeStories.delete(key);
      else _bulExcludeStories.add(key);
    }

    function bulletinOpen(fmt) {
      if (!_bulFile) return;
      const q = _bulQuery();
      q.set("fmt", fmt);
      window.open(`/api/bulletin/editions/${encodeURIComponent(_bulFile)}/render?${q}`, "_blank", "noopener");
    }

    // One click, two files. A browser cannot put two downloads in one response, so
    // the button fetches both and saves each -- the report and the annexes ZIP whose
    // reference numbers match it.
    //
    // BOTH REQUESTS CARRY THE SAME SELECTION. The reference numbers are assigned over
    // the document as it will be published, so annexes built without the operator's
    // exclusions would number a different set and `[0007]` in the report would open
    // the wrong article. Sending the selection to one and not the other is the whole
    // failure mode, which is why the query is built once here.
    async function bulletinDownloadBundle(btn) {
      if (!_bulFile) return;
      const out = $("bul-pub");
      const q = _bulQuery();
      const base = `/api/bulletin/editions/${encodeURIComponent(_bulFile)}`;
      btn.disabled = true;
      if (out) out.textContent = _bulT("Building the annexes…");
      try {
        const rq = new URLSearchParams(q); rq.set("fmt", "markdown");
        const report = await fetch(`${base}/render?${rq}`);
        await _throwIfNotOk(report);
        _saveBlob(await report.blob(), _filenameOf(report, "bulletin.md"));

        const zip = await fetch(`${base}/annexes?${q}`);
        await _throwIfNotOk(zip);
        const n = zip.headers.get("X-OO-Annex-Articles");
        _saveBlob(await zip.blob(), _filenameOf(zip, "annexes.zip"));
        if (out) {
          out.textContent = n && n !== "0"
            ? _bulTf("Downloaded: the report and {n} annexed article(s).", {n: n})
            : _bulT("Downloaded the report. This edition names no articles, so the annexes are empty — regenerate it to populate them.");
        }
      } catch (e) {
        if (out) out.textContent = _bulT("Could not download: ") + e.message;
      } finally { btn.disabled = false; }
    }

    // These two fetches are raw rather than through api(), because their bodies are a
    // document and a ZIP rather than JSON. So the error path has to be re-created —
    // and it goes through the SAME _apiErrorMessage the rest of the app uses, which
    // takes a PARSED payload, so a refusal reads as its reason instead of "500".
    async function _throwIfNotOk(res) {
      if (res.ok) return;
      let data = null;
      try { data = await res.json(); } catch (_) { /* a non-JSON error body is fine */ }
      throw new Error(_apiErrorMessage(data, res));
    }

    // The server names these files; it knows the period and the cadence. Reading the
    // name off Content-Disposition rather than rebuilding it here keeps one namer.
    function _filenameOf(res, fallback) {
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="([^"]+)"/.exec(cd);
      return (m && m[1]) || fallback;
    }

    function _saveBlob(blob, name) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Revoked on a later tick: revoking synchronously can cancel the download in
      // some browsers before it has read the blob.
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }

    // Opening from the LIST shows the whole edition. A selection belongs to the
    // review screen, where you can see what you are excluding -- carrying one
    // silently into a list click would hand you a document you did not choose.
    function bulletinOpenFile(filename) {
      window.open(
        `/api/bulletin/editions/${encodeURIComponent(filename)}/render?fmt=html`, "_blank", "noopener");
    }

    async function bulletinPublish(btn) {
      if (!_bulFile) return;
      const out = $("bul-pub");
      btn.disabled = true;
      try {
        const r = await api(
          `/api/bulletin/editions/${encodeURIComponent(_bulFile)}/publish?${_bulQuery()}`,
          {method: "POST"});
        out.textContent = _bulT("Published — the record itself is unchanged.");
        toast(_bulT("Published. Nothing was sent anywhere; the document is yours to share."));
        if (r) await loadBulletinEditions();
      } catch (e) { out.textContent = _bulT("Could not publish: ") + e.message; }
      finally { btn.disabled = false; }
    }

    async function bulletinDelete(filename) {
      if (!confirm(_bulT("Delete this edition? The corpus is untouched — only the document goes."))) return;
      try {
        await api(`/api/bulletin/editions/${encodeURIComponent(filename)}`, {method: "DELETE"});
        if (_bulFile === filename) { _bulFile = null; $("bulletin-review").innerHTML = ""; }
        await loadBulletinEditions();
      } catch (e) { toast(_bulT("Could not delete: ") + e.message, "err"); }
    }

    // -- Calendar feed directory: candidates -> explicit verify/import ------- //
    // Families SHOW duplicate providers (one folder, every source listed with a
    // transparent URL). Verify/import are operator clicks through the ethical
    // fetcher -- the directory itself never touches the network.
    let _feedDir = null;
    async function loadFeedDir() {
      try { _feedDir = await api("/api/events/feeds"); } catch { _feedDir = null; }
      if (!_feedDir) { $("feeddir-list").innerHTML = '<div class="muted">Could not load this document.</div>'; return; }
      const kinds = [...new Set(_feedDir.families.map(f => f.kind))].sort();
      $("feeddir-kind").innerHTML = '<option value="">all</option>' +
        kinds.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
      renderFeedDir();
      renderUserCalendars();
    }
    function _verdictChip(v, feed) {
      if (!v) return '<span class="pill">not checked yet</span>';
      if (v.status === "ok") {
        const stale = v.stale_year ? ' <span class="pill warn">stale year</span>' : "";
        return `<span class="pill ok">reachable · ${v.events}</span>${stale}`;
      }
      if (v.status === "not_ical") return '<span class="pill warn">not an iCal file</span>';
      return `<span class="pill err" title="${esc(v.error || "")}">unreachable</span>`;
    }
    // A folder's overall health from its feeds' verdicts: reachable if ANY feed is
    // reachable, dysfunctional if all checked feeds failed, else not-yet-checked.
    function famStatus(f) {
      let anyOk = false, anyChecked = false;
      for (const fd of (f.feeds || [])) {
        if (fd.verdict) { anyChecked = true; if (fd.verdict.status === "ok") anyOk = true; }
      }
      return anyOk ? "ok" : (anyChecked ? "error" : "unchecked");
    }
    const _FEED_SORTS = {
      name: (a, b) => a.name.localeCompare(b.name),
      country: (a, b) => (a.country || "￿").localeCompare(b.country || "￿") || a.name.localeCompare(b.name),
      kind: (a, b) => (a.kind || "").localeCompare(b.kind || "") || a.name.localeCompare(b.name),
      // dysfunctional first, so problems surface (the maintainer's "find the broken ones")
      status: (a, b) => ({ error: 0, unchecked: 1, ok: 2 }[famStatus(a)] - { error: 0, unchecked: 1, ok: 2 }[famStatus(b)]) || a.name.localeCompare(b.name),
      imported: (a, b) => ((b.imported_events || 0) - (a.imported_events || 0)) || a.name.localeCompare(b.name),
    };
    function _feedDirFiltered() {
      if (!_feedDir) return [];
      const kind = $("feeddir-kind").value, q = ($("feeddir-q").value || "").toLowerCase();
      const sf = $("feeddir-status-filter").value, sort = $("feeddir-sort").value || "name";
      const fams = _feedDir.families.filter(f =>
        (!kind || f.kind === kind) &&
        (!sf || famStatus(f) === sf) &&
        (!q || f.name.toLowerCase().includes(q) || (f.country || "").toLowerCase().includes(q)));
      fams.sort(_FEED_SORTS[sort] || _FEED_SORTS.name);
      return fams;
    }
    // Bulk exclude/include (reversible). 'dysfunctional' = every broken folder;
    // 'shown' = the current filtered+sorted set (so the Status filter doubles as a
    // selector, e.g. show Dysfunctional then Exclude shown).
    function agExcludeBulk(which) {
      const s = agExcluded();
      const fams = which === "dysfunctional"
        ? (_feedDir ? _feedDir.families.filter(f => famStatus(f) === "error") : [])
        : _feedDirFiltered();
      fams.forEach(f => s.add(f.key));
      agSaveExcluded(s); renderFeedDir(); _agendaMaybeReload();
    }
    function agExcludeClear() { agSaveExcluded(new Set()); renderFeedDir(); _agendaMaybeReload(); }
    function agToggleExclude(key) {
      const s = agExcluded(); s.has(key) ? s.delete(key) : s.add(key);
      agSaveExcluded(s); renderFeedDir(); _agendaMaybeReload();
    }
    function _agendaMaybeReload() {  // keep the agenda in sync if it's open
      const t = $("tab-agenda"); if (t && t.classList.contains("active")) loadAgenda();
    }
    function renderFeedDir() {
      if (!_feedDir) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const excl = agExcluded();
      let fams = _feedDirFiltered();
      const total = fams.length;
      fams = fams.slice(0, 40);
      // The manual "Verify next 25" button is gone; what replaced it is stated here
      // instead, with the REAL backlog — so the automation is visible rather than
      // implied (ruling 10/11). Every figure is a count the backend measured.
      const _v = _feedDir.verification || {};
      $("feeddir-status").innerHTML =
        esc(`${_feedDir.total_feeds} feeds · ${_feedDir.families.length} folders · ${_feedDir.checked} checked`) +
        (_v.unchecked
          ? ` <span class="muted" title="${esc(_v.method || "")}">· ${_v.unchecked} ${esc(t("not checked yet"))}</span>`
          : "");
      const bulk = `<div class="row" style="gap:6px;margin-bottom:8px;align-items:center;flex-wrap:wrap">
        <button class="secondary tiny" onclick="agExcludeBulk('dysfunctional')">Exclude dysfunctional</button>
        <button class="secondary tiny" onclick="agExcludeBulk('shown')">Exclude shown</button>
        ${excl.size ? `<button class="ghost tiny" onclick="agExcludeClear()">Clear exclusions</button>
          <span class="hint">${excl.size} <span>excluded</span></span>` : ""}</div>`;
      $("feeddir-list").innerHTML = bulk + fams.map(f => {
        const feeds = f.feeds.map(fd => `
          <div class="vr">
            <span>${esc(fd.provider)}${fd.year_pinned ? ` <span class="muted">· ${fd.year_pinned}</span>` : ""}</span>
            <b>${_verdictChip(fd.verdict, fd)}
              <button class="ghost tiny" onclick="feedAction('${esc(fd.id)}','verify')">Verify</button>
              <button class="secondary tiny" onclick="feedAction('${esc(fd.id)}','import')">Import</button></b>
          </div>
          <div class="hint" style="word-break:break-all;margin:0 0 4px"><a href="${esc(fd.url)}" target="_blank" rel="noopener noreferrer">${esc(fd.url)}</a></div>`).join("");
        const isExcl = excl.has(f.key);
        return `<details class="cs-row${isExcl ? " excluded" : ""}" style="padding:6px 10px">
          <summary style="cursor:pointer">${esc(f.name)}
            ${f.duplicates ? `<span class="pill" title="Several providers publish this calendar — compare them below">${f.feeds.length} sources</span>` : ""}
            ${f.imported_events ? `<span class="pill ok">${f.imported_events} imported</span>` : ""}
            ${isExcl ? `<span class="pill warn">excluded</span>` : ""}
            <span class="muted">· ${esc(f.kind)}${f.country ? " · " + esc(f.country) : ""}</span>
            <button class="ghost tiny" style="float:inline-end" onclick="event.preventDefault();event.stopPropagation();agToggleExclude('${esc(f.key)}')">${isExcl ? "Include" : "Exclude"}</button></summary>
          ${feeds}</details>`;
      }).join("") + (total > 40 ? `<div class="hint">+${total - 40} — type to filter</div>` : "");
    }
    async function feedAction(id, action) {
      try {
        await api(`/api/events/feeds/${encodeURIComponent(id)}/${action}`, {method: "POST"});
        toast(action === "import" ? "Imported." : "Checked.", "ok");
      } catch (e) { toast(e.message, "err"); }
      loadFeedDir();
    }
    // NOTE: the "Verify next 25" button is gone (ruling 10/11, 2026-07-31) —
    // verification is progressive now, riding each collection pass, and its tally
    // shows in the task manager's Schedule tab. The per-feed "Check" action below
    // stays: verifying ONE feed you are looking at is a real, bounded choice, not
    // the manual sweep the ruling retired. POST /api/events/feeds/verify-batch is
    // deliberately KEPT on the backend — never remove an endpoint, only a
    // redundant button (the Desk lesson).
    // Upload a local .ics (no network): events join the agenda (deduped) as a
    // removable, user-owned calendar. The file is read client-side and posted.
    async function importIcsFile(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const f = $("ics-file").files && $("ics-file").files[0];
      if (!f) { toast(t("Choose a .ics file first."), "err"); return; }
      const name = ($("ics-name").value || f.name.replace(/\.ics$/i, "")).trim();
      btn.disabled = true;
      try {
        const ics = await f.text();
        const r = await api("/api/events/feeds/import-ics", { method: "POST", body: JSON.stringify({ name, ics }) });
        toast(`${r.added} / ${r.events_in_file}`, "ok");
        $("ics-file").value = ""; $("ics-name").value = "";
        renderUserCalendars(); _agendaMaybeReload();
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; }
    }
    // Add a calendar by URL (network): the ONE consent popup fires first, then the
    // fetch goes through the guarded fetcher (robots / kill switch / politeness).
    async function importIcsUrl(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const url = ($("ics-url").value || "").trim();
      if (!url) { toast(t("Enter a calendar URL first."), "err"); return; }
      if (!await ensureOnline(t("Fetch a calendar from a URL you provided"))) return;
      const name = ($("ics-name").value || "").trim();
      btn.disabled = true;
      try {
        const r = await api("/api/events/feeds/import-url", { method: "POST", body: JSON.stringify({ url, name }) });
        toast(`${r.added} / ${r.events_in_file}`, "ok");
        $("ics-url").value = ""; $("ics-name").value = "";
        renderUserCalendars(); _agendaMaybeReload();
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; }
    }
    async function renderUserCalendars() {
      let d; try { d = await api("/api/events/feeds/user"); } catch { return; }
      const box = $("feeddir-user"); if (!box) return;
      if (!d.feeds || !d.feeds.length) { box.innerHTML = ""; return; }
      box.innerHTML = `<h3 style="margin-bottom:6px">Your calendars</h3>` + d.feeds.map(f =>
        `<div class="vr"><span>${esc(f.name)} <span class="muted">· ${f.events}</span></span>` +
        `<button class="ghost tiny" onclick="removeUserCalendar('${esc(f.key)}')">Remove</button></div>`).join("");
    }
    async function removeUserCalendar(key) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try { await api("/api/events/feeds/user/" + encodeURIComponent(key), { method: "DELETE" }); toast(t("Calendar removed."), "ok"); }
      catch (e) { toast(e.message, "err"); }
      renderUserCalendars(); _agendaMaybeReload();
    }

    function renderAgendaCals() {
      const subs = agSubs();
      $("agenda-cals").innerHTML = AG.cals.map(c =>
        // aria-pressed: subscribed/not is a TOGGLE state, and after the contrast fix
        // it is carried by the accent background + border. Colour alone must never be
        // the only channel, so the state is announced too.
        `<button class="ag-cal${subs.has(c.key) ? " on" : ""}" data-k="${esc(c.key)}" onclick="toggleCalSub(this)"
           aria-pressed="${subs.has(c.key) ? "true" : "false"}"
           title="${esc(c.description || "")}">${esc(c.name)} <span class="muted">${c.count}</span></button>`).join("");
    }
    function toggleCalSub(btn) {
      const subs = agSubs(); const k = btn.dataset.k;
      subs.has(k) ? subs.delete(k) : subs.add(k);
      agSaveSubs(subs); renderAgendaCals(); renderAgenda();
    }

    function agWhen(e) {
      return e.next_occurrence
        ? `<span class="pill ok">${esc(e.next_occurrence)}</span>`
        : `<span class="pill" title="exact date moves each year">${e.month ? esc(_MONTHS[e.month-1]) : esc(e.cadence||"")}</span>`;
    }
    // Feed id -> {name, url} from the calendar directory, for the visible provenance
    // pill on imported events (maintainer 2026-07-17: "when clicking on events, the
    // source should be clear"). Lazy: reuses the Calendars panel's _feedDir when
    // loaded, else kicks ONE best-effort background load (loopback) and falls back
    // to the family name meanwhile — agRow never blocks on it.
    let _agFeedMap = null, _agFeedMapAsked = false;
    function _agFeedById() {
      if (_agFeedMap) return _agFeedMap;
      if (_feedDir) {
        _agFeedMap = {};
        for (const fam of (_feedDir.families || [])) {
          for (const f of (fam.feeds || [])) {
            if (f && f.id) _agFeedMap[f.id] = { name: f.name || f.id, url: f.url || "" };
          }
        }
        return _agFeedMap;
      }
      if (!_agFeedMapAsked) {
        _agFeedMapAsked = true;
        api("/api/events/feeds").then(d => { _feedDir = d; _agFeedMap = null; }).catch(() => {});
      }
      return null;
    }
    function agRow(e) {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const conf = e.deduced
        ? `<span class="pill warn" title="${esc(T("A date your articles mention — deduced from text, never confirmed."))}">${esc(T("deduced · never confirmed"))}</span>`
        : e.confirmed ? '<span class="pill ok" title="fixed annual date">confirmed</span>'
                      : '<span class="pill" title="follow the official source for the exact date">approx · check source</span>';
      const tags = (e.tags||[]).map(t => `<span class="ag-tag" onclick="$('agenda-tag').value='${esc(t)}';renderAgenda()">${esc(t)}</span>`).join("");
      const alsoIn = (e.also_in && e.also_in.length) ? ` <span class="pill" title="this event also appears in: ${esc(e.also_in.join(', '))}">also in ${e.also_in.length}</span>` : "";
      const imp = (e.imported && e.source_count > 1)
        ? ` <span class="pill" title="${esc((e.family_names || [e.family_name || ""]).filter(Boolean).join(', '))}">${e.source_count}×</span>` : "";
      // Visible provenance on every imported event: WHICH feed(s) delivered it —
      // feed name(s) + URL(s) in the hover (the #oo-tip layering convention), the
      // first provider named in the pill itself. Falls back to the family name
      // until the directory map loads.
      let prov = "";
      if (e.imported && Array.isArray(e.sources) && e.sources.length) {
        const fm = _agFeedById();
        const names = e.sources.map(id => (fm && fm[id] && fm[id].name) || id);
        const detail = e.sources.map(id => fm && fm[id] ? `${fm[id].name} — ${fm[id].url}` : id).join("\n");
        const label = names[0] + (names.length > 1 ? ` +${names.length - 1}` : "");
        prov = ` <span class="pill" title="${esc(T("Calendar feed(s) this event came from:") + "\n" + detail)}">${esc(T("from"))} ${esc(label)}</span>`;
      } else if (e.imported && e.family_name) {
        prov = ` <span class="pill" title="${esc(T("Imported calendar folder"))}">${esc(T("from"))} ${esc(e.family_name)}</span>`;
      }
      const variants = (e.date_variants && e.date_variants.length > 1)
        ? `<div class="hint" style="color:var(--warn)">date varies by source: ${esc(e.date_variants.join(' · '))}</div>` : "";
      const src = e.official_url ? " · " + extLink(e.official_url, "official source ↗") : "";
      // The event title opens the unified analysis window over this event in your
      // corpus (maintainer 2026-06-16: agenda content "highly visible and clickable").
      // A DEDUCED event opens its EXACT article set (the dates came from those
      // articles); other events open a search over the title.
      const openExpr = (e.deduced && Array.isArray(e.article_ids) && e.article_ids.length)
        ? `openAnalysisForIds(${esc(JSON.stringify(e.article_ids))}, ${esc(JSON.stringify(e.title))})`
        : `openAnalysisFor(${esc(JSON.stringify(e.title))})`;
      const titleEl = `<b class="ag-evtitle" style="cursor:pointer" title="Open in analysis — explore this event in your corpus" onclick="event.stopPropagation();${openExpr}">${esc(e.title)}</b>`;
      return `<div class="ag-row"><div class="ag-when">${agWhen(e)}</div>
        <div class="ag-body"><div>${titleEl} <span class="pill">${esc(e.category)}</span> ${e.country&&e.country!=='INT'?`<span class="pill">${esc(e.country)}</span>`:""} ${conf}${alsoIn}${imp}${prov}</div>
          ${variants}
          <div class="hint">${tags} ${e.note?"· "+esc(e.note):""}${src}</div></div></div>`;
    }
    // -- Agenda views: MONTH grid (the ruled default) + the original list ----- //
    // The tab shows DATA only (maintainer principle 2026-06-11): calendar
    // subscriptions and the feed directory live in Settings -> Agenda.
    // The chosen VIEW (month/week/list/…) stays a per-device UI preference in localStorage
    // (the subscriptions moved server-side; which layout you last looked at is transient,
    // per-device display state — MONTH remains the ruled default).
    function agView() { return localStorage.getItem("oo.agenda.view") || "month"; }
    function agendaSetView(v) { localStorage.setItem("oo.agenda.view", v); if (_agViewTabs) _agViewTabs.paint(v); renderAgenda(); }
    let _agViewTabs = null;                          // the Month·Week·List ooSubtabs handle
    const AGV = { y: null, m: null, day: null };   // displayed month (m = 1-12) + picked day
    // Category filter: colored chips replaced the dropdown (ruled 2026-06-15,
    // Item C). The taxonomy is data-driven (derived from the catalog facets), so a
    // new category (e.g. "religious") appears as a chip automatically. Distinct,
    // separable hues; the translated label stays the real identifier (colour is
    // decorative). Single-select with toggle-off.
    let _agCat = "";
    const AG_CAT_HUE = { civic: 210, political: 0, economic: 140, technology: 280, religious: 45, other: 30 };
    function agCatHue(c) {
      if (AG_CAT_HUE[c] != null) return AG_CAT_HUE[c];
      let h = 0; for (let i = 0; i < c.length; i++) h = (h * 31 + c.charCodeAt(i)) >>> 0;
      return h % 360;
    }
    function renderAgendaCatChips() {
      const box = $("agenda-cats"); if (!box) return;
      // Labels are the English category slugs (all keyed ×12) emitted as DOM text,
      // so the i18n engine translates them live on a language switch.
      const chips = [`<button type="button" class="ag-catchip${_agCat === "" ? " on" : ""}" onclick="agSetCat('')">all</button>`];
      for (const c of (AG.categories || [])) {
        chips.push(`<button type="button" class="ag-catchip${_agCat === c ? " on" : ""}" style="--cat:${agCatHue(c)}" onclick="agSetCat('${esc(c)}')"><span class="ag-catdot"></span>${esc(c)}</button>`);
      }
      box.innerHTML = chips.join("");
    }
    function agSetCat(c) { _agCat = (_agCat === c) ? "" : c; renderAgendaCatChips(); renderAgenda(); }
    // ISO-2 → regional-indicator flag emoji (offline, zero-asset). The country CODE
    // stays visible beside it as the unambiguous identifier — a flag is a visual
    // convention, never the sole label (flags ≠ identity; some entities have none,
    // and emoji flags render inconsistently on some platforms).
    function agFlag(cc) {
      if (!cc) return "";
      cc = cc.toUpperCase();
      if (/^[A-Z]{2}$/.test(cc)) return String.fromCodePoint(...[...cc].map(ch => 0x1F1E6 + ch.charCodeAt(0) - 65));
      return "\u{1F310}";   // globe for INT / non-ISO entities
    }
    function agLocale() { return document.documentElement.lang || "en"; }
    // The concrete anchor date the views pivot on (picked day, else 1st of the
    // displayed month, else today) — drives the Week window.
    function agAnchorDate() {
      if (AGV.y == null) return new Date();
      return new Date(AGV.y, AGV.m - 1, AGV.day || 1);
    }
    function agPickDate(y, m, d) { AGV.y = y; AGV.m = m; AGV.day = d; renderAgenda(); }
    function agMonthShift(d) {
      // Audit fix 2026-07-17: the old single-step wraparound (`if (m<1){m=12;y--}
      // if (m>12){m=1;y++}`) only ever handled a +-1 shift correctly -- it hardcoded
      // month 12 / month 1 regardless of how far m had actually gone, so Trimester
      // (+-3) and Semester (+-6) nav landed on the WRONG month across a year
      // boundary (e.g. Feb 2026 - 3 months gave "December 2025" instead of the
      // correct "November 2025"). True modular arithmetic over a 0-based total
      // month count handles any shift correctly, including the plain +-1 case.
      const total = AGV.y * 12 + (AGV.m - 1) + d;
      const y = Math.floor(total / 12);
      const m = ((total % 12) + 12) % 12 + 1;
      AGV.y = y; AGV.m = m; AGV.day = null; renderAgenda();
    }
    function agWeekShift(d) {
      const a = agAnchorDate(); a.setDate(a.getDate() + d * 7);
      AGV.y = a.getFullYear(); AGV.m = a.getMonth() + 1; AGV.day = a.getDate(); renderAgenda();
    }
    // The nav bar (‹ · label · › · Today) is shared by Month and Week — dispatch
    // by the active view so one bar serves both.
    function agNavShift(d) {
      const v = agView();
      if (v === "week") agWeekShift(d);
      else if (v === "year") agYearShift(d);
      else if (v === "decade") agYearShift(d * 10);
      else if (v === "trimester") agMonthShift(d * 3);
      else if (v === "semester") agMonthShift(d * 6);
      else agMonthShift(d);
    }
    function agYearShift(d) { AGV.y = (AGV.y || new Date().getFullYear()) + d; AGV.day = null; renderAgenda(); }
    // YEAR view (Item C remaining): a 12-month overview — per-month event counts +
    // a few honest chips; click a month to drill into the Month grid. Annual rules
    // (e.month) and this year's dated instances are both counted.
    function renderAgendaYear(rows) {
      const box = $("agenda-year"), loc = agLocale(), y = AGV.y;
      const byMonth = {}; for (let m = 1; m <= 12; m++) byMonth[m] = [];
      for (const e of rows) {
        if (e.month) byMonth[e.month].push(e);
        else if (e.next_occurrence && +e.next_occurrence.slice(0, 4) === y) byMonth[+e.next_occurrence.slice(5, 7)].push(e);
      }
      const now = new Date(), curY = now.getFullYear(), curM = now.getMonth() + 1;
      let cards = "";
      for (let m = 1; m <= 12; m++) {
        const evs = byMonth[m];
        const name = new Intl.DateTimeFormat(loc, { month: "long" }).format(new Date(y, m - 1, 1));
        const isCur = y === curY && m === curM;
        const chips = evs.slice(0, 4).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
        cards += `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" onclick="agOpenMonth(${m})" title="${esc(name)}">
          <div class="ag-ymon">${esc(name)} <span class="muted">${evs.length || ""}</span></div>${chips}${more}</div>`;
      }
      box.innerHTML = `<div class="ag-ygrid">${cards}</div>`;
    }
    function agOpenMonth(m) { AGV.m = m; AGV.day = null; agendaSetView("month"); }
    function agOpenMonthYear(y, m) { AGV.y = y; AGV.m = m; AGV.day = null; agendaSetView("month"); }
    function agOpenYear(y) { AGV.y = y; AGV.day = null; agendaSetView("year"); }
    // Count the events that fall in a given (year, month) — the SAME placement rule
    // the Year view uses: annual rules by e.month, plus dated instances whose
    // next_occurrence lands in that exact year-month. Returns the matching events.
    function agEventsInMonth(rows, y, m) {
      const ym = `${y}-${String(m).padStart(2, "0")}`, out = [];
      for (const e of rows) {
        if (e.month === m) out.push(e);
        else if (e.next_occurrence && e.next_occurrence.slice(0, 7) === ym && !out.includes(e)) out.push(e);
      }
      return out;
    }
    // One clickable month summary card (the Year view's .ag-ycard grammar, reused).
    function agMonthCard(rows, y, m, loc, curY, curM) {
      const evs = agEventsInMonth(rows, y, m);
      const name = new Intl.DateTimeFormat(loc, { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
      const isCur = y === curY && m === curM;
      const chips = evs.slice(0, 4).map(e =>
        `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
      const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
      return `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" onclick="agOpenMonthYear(${y},${m})" title="${esc(name)}">
        <div class="ag-ymon">${esc(name)} <span class="muted">${evs.length || ""}</span></div>${chips}${more}</div>`;
    }
    // TRIMESTER (3 months) + SEMESTER (6 months): a row of consecutive month
    // summary cards anchored on the displayed month — same data path + same click
    // (→ that Month grid) as the Year view. `span` = 3 or 6.
    function renderAgendaMonths(rows, span) {
      const box = $("agenda-months"), loc = agLocale();
      const now = new Date(), curY = now.getFullYear(), curM = now.getMonth() + 1;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let y = AGV.y, m = AGV.m;
      const months = [];
      for (let i = 0; i < span; i++) { months.push([y, m]); m++; if (m > 12) { m = 1; y++; } }
      const start = months[0], end = months[span - 1];
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "short", year: "numeric" }).format(new Date(start[0], start[1] - 1, 1)) + " – " +
        new Intl.DateTimeFormat(loc, { month: "short", year: "numeric" }).format(new Date(end[0], end[1] - 1, 1));
      const total = months.reduce((n, [yy, mm]) => n + agEventsInMonth(rows, yy, mm).length, 0);
      if (!total) { box.innerHTML = `<div class="muted">${esc(t9("No events in this period."))}</div>`; return; }
      box.innerHTML = `<div class="ag-mgrid">` + months.map(([yy, mm]) => agMonthCard(rows, yy, mm, loc, curY, curM)).join("") + `</div>`;
    }
    // DECADE: a 10-year overview, the Year view's year-summary scaled to a per-year
    // cell × 10. Each cell counts the year's events (annual rules + that year's dated
    // instances) and links to that Year view. Decade anchored on the floor-10 year.
    function renderAgendaDecade(rows) {
      const box = $("agenda-decade"), loc = agLocale(), now = new Date(), curY = now.getFullYear();
      const y0 = Math.floor((AGV.y || curY) / 10) * 10;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      $("agenda-monthlabel").textContent = `${y0}–${y0 + 9}`;
      // Per-year count: annual rules count once a year; dated instances count in
      // their own year (same placement the Year view applies, summed over months).
      const yearCount = (y) => {
        let n = 0;
        for (const e of rows) {
          if (e.month) n++;
          else if (e.next_occurrence && +e.next_occurrence.slice(0, 4) === y) n++;
        }
        return n;
      };
      let cells = "";
      for (let y = y0; y < y0 + 10; y++) {
        const n = yearCount(y), isCur = y === curY;
        cells += `<div class="ag-ycard${isCur ? " today" : ""}${n ? " has" : ""}" onclick="agOpenYear(${y})" title="${y}">
          <div class="ag-ymon">${y} <span class="muted">${n || ""}</span></div></div>`;
      }
      box.innerHTML = `<div class="ag-dgrid">${cells}</div>`;
    }
    function agNavToday() {
      const t = new Date(); AGV.y = t.getFullYear(); AGV.m = t.getMonth() + 1;
      AGV.day = t.getDate(); renderAgenda();
    }
    function agFiltered() {
      const subs = agSubs();
      const cat = _agCat, country = $("agenda-country").value, tag = $("agenda-tag").value;
      const subOnly = $("agenda-subonly").checked;
      return AG.events.filter(e =>
        (!cat || e.category === cat) && (!country || e.country === country) &&
        (!tag || (e.tags||[]).includes(tag)) &&
        // imported events were explicitly imported -> always shown (bypass subscribed-only)
        (!subOnly || e.imported || (e.sources || [e.calendar]).some(s => subs.has(s))));
    }
    function agShowDay(d) { AGV.day = d; renderAgenda(); }
    // T11: the astronomy layer (Meeus, computed locally) — moon glyphs in the
    // month grid; method+accuracy ride the hover convention (informed consent).
    let _astroYear = null, _astroByDate = {}, _seasonByDate = {};
    async function _ensureAstro(year) {
      if (_astroYear === year) return;
      try {
        const d = await api(`/api/events/astronomy?year=${year}`);
        _astroByDate = {}; _seasonByDate = {};
        for (const fm of (d.full_moons || [])) _astroByDate[fm.date] = {glyph: "\u{1F315}", kind: "full", time: fm.time_utc, method: d.method, acc: d.accuracy};
        for (const nm of (d.new_moons || [])) _astroByDate[nm.date] = {glyph: "\u{1F311}", kind: "new", time: nm.time_utc, method: d.method, acc: d.accuracy};
        // Seasons (equinoxes/solstices, Meeus ch.27) — named astronomically
        // (hemisphere-honest); a solstice sun glyph, an equinox star.
        for (const s of (d.seasons || [])) {
          _seasonByDate[s.date] = {glyph: /solstice/i.test(s.event) ? "☀" : "✦",
            name: s.event, time: s.time_utc, method: d.method, acc: d.accuracy};
        }
        _astroYear = year;
      } catch (_e) { _astroByDate = {}; _seasonByDate = {}; _astroYear = null; }
    }
    // The day-of-month (1..31) of the Nth `weekday` (0=Mon..6=Sun) of month m/year y
    // — week=-1 is the LAST; null when it doesn't exist (e.g. a 5th Friday). Mirrors
    // catalog.nth_weekday so floating events ("3rd Tuesday of March") place every year.
    function nthWeekday(y, m, weekday, week) {
      const ndays = new Date(y, m, 0).getDate();                      // days in month m (1-based)
      const dow = d => (new Date(y, m - 1, d).getDay() + 6) % 7;      // -> 0=Mon … 6=Sun
      if (week === -1) return ndays - ((dow(ndays) - weekday + 7) % 7);
      if (week == null || week < 1) return null;
      const day = 1 + ((weekday - dow(1) + 7) % 7) + (week - 1) * 7;
      return day <= ndays ? day : null;
    }
    function renderAgendaMonth(rows) {
      const box = $("agenda-month"), dayBox = $("agenda-day");
      if (AGV.y == null) { const t = new Date(); AGV.y = t.getFullYear(); AGV.m = t.getMonth() + 1; }
      const y = AGV.y, m = AGV.m, loc = agLocale();
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
      // Events on a specific day of THIS grid: annual rules (month+day, any year)
      // + dated instances (next_occurrence inside exactly this year-month).
      const ym = `${y}-${String(m).padStart(2, "0")}`;
      const byDay = {}, monthOnly = [];
      for (const e of rows) {
        if (e.month === m && e.day) (byDay[e.day] = byDay[e.day] || []).push(e);
        // FLOATING rule (e.g. 3rd Tuesday of March): compute the day for THIS browsed
        // year so it places correctly every year, not only the one next_occurrence holds.
        else if (e.month === m && e.weekday != null && e.week != null) {
          const fd = nthWeekday(y, m, e.weekday, e.week);
          if (fd) (byDay[fd] = byDay[fd] || []).push(e);
        }
        else if (e.next_occurrence && e.next_occurrence.slice(0, 7) === ym) {
          const d = +e.next_occurrence.slice(8, 10);
          if (!(byDay[d] || []).includes(e)) (byDay[d] = byDay[d] || []).push(e);
        } else if (e.month === m && !e.day) monthOnly.push(e);
      }
      // Monday-start grid (4-6 week rows), days outside the month dimmed.
      const first = new Date(y, m - 1, 1), daysIn = new Date(y, m, 0).getDate();
      const lead = (first.getDay() + 6) % 7;                  // Mon=0 … Sun=6
      const cells = [], prevDays = new Date(y, m - 1, 0).getDate();
      for (let i = 0; i < lead; i++) cells.push({ d: prevDays - lead + 1 + i, out: true });
      for (let d = 1; d <= daysIn; d++) cells.push({ d, out: false });
      for (let nd = 1; cells.length % 7; nd++) cells.push({ d: nd, out: true });
      const t = new Date();
      const inThisMonth = t.getFullYear() === y && t.getMonth() + 1 === m;
      const t9m = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const wd = [...Array(7)].map((_, i) =>
        new Intl.DateTimeFormat(loc, { weekday: "short" }).format(new Date(2024, 0, i + 1))); // 2024-01-01 was a Monday
      let html = `<div class="ag-grid ag-grid-head">` + wd.map(w => `<div class="ag-wd">${esc(w)}</div>`).join("") + `</div>`;
      html += `<div class="ag-grid">` + cells.map((c) => {
        if (c.out) return `<div class="ag-cell out"><span class="ag-dn">${c.d}</span></div>`;
        const evs = byDay[c.d] || [];
        const today = inThisMonth && t.getDate() === c.d;
        const iso = `${y}-${String(m).padStart(2, "0")}-${String(c.d).padStart(2, "0")}`;
        const moon = _astroByDate[iso];
        const moonHtml = moon
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc((moon.kind === "full" ? t9m("Full moon") : t9m("New moon")) + " " + moon.time + " UTC — " + moon.method + "; " + moon.acc)}">${moon.glyph}</span>`
          : "";
        const season = _seasonByDate[iso];
        const seasonHtml = season
          ? `<span class="ag-season" style="float:inline-end;font-size:11px;margin-inline-end:2px" title="${esc(t9m(season.name) + " " + season.time + " UTC — " + season.method + "; " + season.acc)}">${season.glyph}</span>`
          : "";
        const chips = evs.slice(0, 3).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}${e.confirmed ? "" : " — exact date moves; check the official source"}">${esc(e.title.length > 22 ? e.title.slice(0, 21) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 3 ? `<span class="ag-more">+${evs.length - 3}</span>` : "";
        return `<div class="ag-cell${today ? " today" : ""}${evs.length ? " has" : ""}${AGV.day === c.d ? " sel" : ""}" onclick="agShowDay(${c.d})">
          <span class="ag-dn">${c.d}</span>${moonHtml}${seasonHtml}${chips}${more}</div>`;
      }).join("") + `</div>`;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (monthOnly.length)
        html += `<div class="hint" style="margin-top:8px"><span>${esc(t9("This month — no fixed day:"))}</span> ` +
          monthOnly.map(e => `<span class="ag-tag" title="${esc(e.title)}">${esc(e.title)}</span>`).join(" ") + `</div>`;
      box.innerHTML = html;
      // Day detail under the grid: the familiar honest rows for the picked day.
      if (AGV.day && (byDay[AGV.day] || []).length) {
        const label = new Intl.DateTimeFormat(loc, { dateStyle: "full" }).format(new Date(y, m - 1, AGV.day));
        dayBox.innerHTML = `<h3 style="font-size:13px;margin:12px 0 6px">${esc(label)}</h3>` +
          byDay[AGV.day].map(agRow).join("");
      } else dayBox.innerHTML = "";
    }
    // Events falling on ONE concrete date: annual rules (month+day, any year) +
    // dated instances (next_occurrence === that ISO date). Shared by the Week view.
    function agEventsOn(rows, dt) {
      const y = dt.getFullYear(), m = dt.getMonth() + 1, d = dt.getDate();
      const iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const out = [];
      for (const e of rows) {
        if (e.month === m && e.day === d) out.push(e);
        else if (e.next_occurrence === iso && !out.includes(e)) out.push(e);
      }
      return out;
    }
    // WEEK view (ruled 2026-06-15, Item C): the Monday-start 7-day window around
    // the anchor date — taller day columns with more events, the same honest chips
    // + moon glyphs as the month grid; click a day for its detail below.
    function renderAgendaWeek(rows) {
      const box = $("agenda-week"), dayBox = $("agenda-day"), loc = agLocale();
      const anchor = agAnchorDate();
      const monday = new Date(anchor); monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
      const days = [...Array(7)].map((_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; });
      const sunday = days[6];
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "short", day: "numeric" }).format(monday) + " – " +
        new Intl.DateTimeFormat(loc, { month: "short", day: "numeric", year: "numeric" }).format(sunday);
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const now = new Date();
      const same = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
      const monthsInWeek = new Set(days.map(d => d.getMonth() + 1));
      let html = `<div class="ag-grid">` + days.map(d => {
        const evs = agEventsOn(rows, d);
        const isToday = same(d, now);
        const isSel = AGV.day === d.getDate() && AGV.m === d.getMonth() + 1 && AGV.y === d.getFullYear();
        const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        const moon = _astroByDate[iso];
        const moonHtml = moon
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc((moon.kind === "full" ? t9("Full moon") : t9("New moon")) + " " + moon.time + " UTC — " + moon.method + "; " + moon.acc)}">${moon.glyph}</span>`
          : "";
        const wd = new Intl.DateTimeFormat(loc, { weekday: "short" }).format(d);
        const dn = new Intl.DateTimeFormat(loc, { day: "numeric", month: "short" }).format(d);
        const chips = evs.slice(0, 6).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}${e.confirmed ? "" : " — exact date moves; check the official source"}">${esc(e.title.length > 30 ? e.title.slice(0, 29) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 6 ? `<span class="ag-more">+${evs.length - 6}</span>` : "";
        return `<div class="ag-cell${isToday ? " today" : ""}${evs.length ? " has" : ""}${isSel ? " sel" : ""}" onclick="agPickDate(${d.getFullYear()},${d.getMonth() + 1},${d.getDate()})">
          <div class="ag-wd">${esc(wd)} <span class="ag-wd-d">${esc(dn)}</span>${moonHtml}</div>${chips}${more}</div>`;
      }).join("") + `</div>`;
      const monthOnly = rows.filter(e => e.month && !e.day && !e.next_occurrence && monthsInWeek.has(e.month));
      if (monthOnly.length)
        html += `<div class="hint" style="margin-top:8px"><span>${esc(t9("This week — no fixed day:"))}</span> ` +
          monthOnly.map(e => `<span class="ag-tag" title="${esc(e.title)}">${esc(e.title)}</span>`).join(" ") + `</div>`;
      box.innerHTML = html;
      const picked = AGV.day ? new Date(AGV.y, AGV.m - 1, AGV.day) : null;
      if (picked && picked >= days[0] && picked <= sunday) {
        const evs = agEventsOn(rows, picked);
        if (evs.length) {
          const label = new Intl.DateTimeFormat(loc, { dateStyle: "full" }).format(picked);
          dayBox.innerHTML = `<h3 style="font-size:13px;margin:12px 0 6px">${esc(label)}</h3>` + evs.map(agRow).join("");
        } else dayBox.innerHTML = "";
      } else dayBox.innerHTML = "";
    }
    function renderAgenda() {
      renderAgendaCals();
      const view = agView();
      if (_agViewTabs) _agViewTabs.paint(view);
      const isMonth = view === "month", isWeek = view === "week", isYear = view === "year", isList = view === "list";
      const isTri = view === "trimester", isSem = view === "semester", isDec = view === "decade";
      const hasBar = isMonth || isWeek || isYear || isTri || isSem || isDec;
      $("agenda-monthbar").style.display = hasBar ? "" : "none";
      $("agenda-month").style.display = isMonth ? "" : "none";
      $("agenda-week").style.display = isWeek ? "" : "none";
      $("agenda-months").style.display = (isTri || isSem) ? "" : "none";
      $("agenda-year").style.display = isYear ? "" : "none";
      $("agenda-decade").style.display = isDec ? "" : "none";
      $("agenda-day").style.display = (isMonth || isWeek) ? "" : "none";
      $("agenda-list").style.display = isList ? "" : "none";
      $("agenda-group-wrap").style.display = isList ? "" : "none";
      const rows = agFiltered();
      $("agenda-monthhint").textContent = AG.caveat || "";
      if (AGV.y == null && hasBar) { const _t = new Date(); AGV.y = _t.getFullYear(); AGV.m = _t.getMonth() + 1; }
      if (isMonth) {
        _ensureAstro(AGV.y).then(() => renderAgendaMonth(rows));
        return;
      }
      if (isWeek) {
        _ensureAstro(agAnchorDate().getFullYear()).then(() => renderAgendaWeek(rows));
        return;
      }
      if (isTri) { renderAgendaMonths(rows, 3); return; }
      if (isSem) { renderAgendaMonths(rows, 6); return; }
      if (isDec) { renderAgendaDecade(rows); return; }
      if (isYear) {
        $("agenda-monthlabel").textContent = String(AGV.y);
        renderAgendaYear(rows);
        return;
      }
      const box = $("agenda-list");
      const groupBy = $("agenda-group").value;
      const tt = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!rows.length) { box.innerHTML = `<p class="hint">${esc(AG.caveat)}</p><div class="muted">${esc(tt("No events this month — adjust filters or subscribe to more calendars in Settings."))}</div>`; return; }
      const groups = {};
      for (const e of rows) {
        const k = groupBy === "month" ? (e.next_occurrence ? _MONTHS[+e.next_occurrence.slice(5,7)-1] : (e.month ? _MONTHS[e.month-1] : "Movable / no fixed date"))
                : groupBy === "calendar" ? (AG.meta[e.calendar]?.name || e.calendar)
                : (e.country || "—");
        (groups[k] = groups[k] || []).push(e);
      }
      box.innerHTML = `<p class="hint">${esc(AG.caveat)} · showing ${rows.length} of ${AG.events.length}</p>` +
        Object.entries(groups).map(([k, list]) =>
          `<h3 style="font-size:13px;margin:12px 0 6px">${esc(k)} <span class="muted">${list.length}</span></h3>` + list.map(agRow).join("")).join("");
    }

    // ===================================================================== //
    //  GOVERNMENTS tab (maintainer chat 2026-06-22): per-country data + a
    //  world-map choropleth + the law tracker, as subtabs over the existing
    //  vintaged official-statistics store (/api/governments/*). Honesty carried:
    //  a value is a producer's published figure (never a score), a gap is a gap.
    // ===================================================================== //
    let _govSubtabs = null, _govInds = null, _govMapData = null, _govMapInit = false, _govCountriesInit = false;

    function _govCompact(v) {
      const a = Math.abs(v);
      if (a >= 1e12) return (v / 1e12).toFixed(a >= 1e13 ? 0 : 1) + "T";
      if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "B";
      if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
      if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "k";
      return fmtNum(v, 1);
    }
    // Every unit in the catalog gets a branch, and an UNKNOWN unit is appended
    // rather than dropped. The old fallthrough was `fmtNum(v, 2)`, which silently
    // discarded the unit for six of the catalog's eleven: GDP-PPP rendered as
    // "99 594 884 137 256.80" and mobile subscriptions as a bare "141.60", which
    // reads as a broken percentage rather than as subscriptions per 100 people
    // (field feedback 2026-08-07, item 8). A new unit added to the catalog now
    // degrades to "value unit" instead of to a naked number, and
    // test_governments_units.py fails if it has no explicit branch here.
    function _govFmt(v, unit) {
      // `t` is NOT a global in this file; bind it or every call throws at runtime
      // (test_no_app_function_calls_i18n_t_without_binding_it exists because that
      // has shipped before). Unkeyed units fall back to their English form.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (v == null || !isFinite(v)) return "—";
      if (unit === "%") return fmtNum(v, 1) + "%";
      if (unit === "years" || unit === "index") return fmtNum(v, 1);
      if (unit === "USD") return "$" + _govCompact(v);
      // International dollars are PPP-converted and are NOT US dollars; giving them
      // a "$" would silently equate two different units.
      if (unit === "intl$") return "Int$" + _govCompact(v);
      if (unit === "people") return _govCompact(v);
      // These use fmtNum's OWN magnitude-scaled precision rather than a fixed number
      // of decimals, per the app-wide units principle (sensible significant digits
      // scaled to magnitude). A fixed 1 decimal would render 141.6 correctly and turn
      // 3.78 physicians per 1,000 into 3.8, losing a real digit on the small end.
      if (unit === "per 100" || unit === "per 1,000" || unit === "per 100,000")
        return fmtNum(v) + " " + t(unit);
      if (unit === "births/woman") return fmtNum(v) + " " + t("births/woman");
      if (unit === "t/capita") return fmtNum(v) + " " + t("t/capita");
      return unit ? fmtNum(v, 2) + " " + t(unit) : fmtNum(v, 2);
    }

    async function loadGovIndicators() {
      if (_govInds) return _govInds;
      try { _govInds = (await api("/api/governments/indicators")).indicators || []; }
      catch (e) { _govInds = []; }
      return _govInds;
    }

    // Entry point (TAB_LOADERS.law): wire the subtabs once, then show the default.
    async function loadGovernments() {
      const nav = $("gov-subtabs");
      // {initial:"countries"} fires showGovView("countries") on creation; on a re-open
      // select() re-paints the nav highlight AND fires the loader (stays in sync).
      if (nav && !_govSubtabs) _govSubtabs = ooSubtabs(nav, showGovView, {initial: "countries"});
      else if (_govSubtabs) _govSubtabs.select("countries");
    }
    function showGovView(cat) {
      ["countries", "map", "law", "statistics"].forEach(v =>
        { const el = $("gov-" + v); if (el) el.style.display = (v === cat) ? "" : "none"; });
      if (cat === "countries") loadGovCountries();
      else if (cat === "map") loadGovMap();
      else if (cat === "law") loadLaw();
      // Official FIGURES (2026-07-31): vintages, revision anomalies, triangulation and the
      // tracked auto-refresh list are DATA about governments, so they live here rather than
      // in Settings (invariant #8). The producer directory stayed in Settings → Advanced.
      else if (cat === "statistics") { loadStatFigures(); loadStatSubs(); }
    }

    // ---- Countries subtab ---- //
    async function loadGovCountries() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      loadLawPointer();
      if (_govCountriesInit) return;
      _govCountriesInit = true;
      const sel = $("gov-country"); if (!sel) return;
      await loadGovIndicators();
      // Derive the available countries from a populous indicator's coverage.
      let rows = [];
      try { rows = (await api("/api/governments/map?indicator=SP.POP.TOTL")).by_country || []; }
      catch (e) { rows = []; }
      if (!rows.length) {
        // try GDP as a fallback before declaring the store empty
        try { rows = (await api("/api/governments/map?indicator=NY.GDP.MKTP.CD")).by_country || []; }
        catch (e) { rows = []; }
      }
      const codes = [...new Set(rows.map(r => r.country))].sort(
        (a, b) => ooRegionName(a, a).localeCompare(ooRegionName(b, b)));
      if (!codes.length) {
        sel.innerHTML = "";
        $("gov-country-data").innerHTML =
          `<div class="muted">${esc(t("Country data loads automatically in the background when online — or use “Load standard country data” to fetch it now."))}</div>`;
        return;
      }
      sel.innerHTML = codes.map(c => `<option value="${esc(c)}">${esc(ooRegionName(c, c))}</option>`).join("");
      loadGovCountry(codes[0]);
    }
    async function loadGovCountry(iso) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-country-data"); if (!host || !iso) return;
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      let d; try { d = await api("/api/governments/country/" + encodeURIComponent(iso)); }
      catch (e) { host.innerHTML = `<div class="muted">${esc(t("Could not load this country."))}</div>`; return; }
      // group indicators by category
      const cats = {};
      (d.indicators || []).forEach(i => { (cats[i.category] = cats[i.category] || []).push(i); });
      const block = (ind) => {
        const latest = ind.latest;
        const val = latest ? _govFmt(latest.value, ind.unit) : "—";
        const yr = latest ? ` <span class="muted">(${esc(latest.year)})</span>` : "";
        // Gate the chart on the points that will actually be PLOTTED, not on the raw
        // series: a series of several entries with one non-null value used to pass
        // this check and then hand dashChartSvg a single point, which is how a
        // one-point card ended up drawing an axis at all.
        const pts = (ind.series || []).filter(p => p.value != null);
        const spark = pts.length > 1
          ? dashChartSvg(pts.map(p => ({observed_on: p.year + "-01-01", price: p.value})),
                         ind.unit || "", {nUnit: t("years")})
          : "";
        // A definition where the number reads as an error and is not one. Rides the
        // #oo-tip hover convention (invariant #17), which marks the element for free.
        const note = ind.note ? ` title="${esc(ind.note)}"` : "";
        return `<div class="gov-ind">
          <div class="gov-ind-label"${note}>${esc(ind.label)}</div>
          <div class="gov-ind-val">${esc(val)}${yr}</div>
          <div class="gov-ind-spark">${spark}</div></div>`;
      };
      host.innerHTML = Object.keys(cats).map(c =>
        `<h3 style="font-size:13px;margin:14px 0 6px;text-transform:capitalize">${esc(c)}</h3>
         <div class="gov-ind-grid">${cats[c].map(block).join("")}</div>`).join("")
        + `<div class="card-caveat" style="margin-top:10px">${esc(d.caveat || "")}</div>`;
    }

    // ---- Map subtab ---- //
    async function loadGovMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sel = $("gov-map-ind"); if (!sel) return;
      if (!_govMapInit) {
        _govMapInit = true;
        await loadGovIndicators();
        sel.innerHTML = (_govInds || []).map(i => `<option value="${esc(i.id)}">${esc(i.label)}</option>`).join("");
      }
      const indicator = sel.value || (_govInds && _govInds[0] && _govInds[0].id);
      if (!indicator) return;
      const host = $("gov-map-host");
      if (host) host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try { _govMapData = await api("/api/governments/map?indicator=" + encodeURIComponent(indicator)); }
      catch (e) { _govMapData = null; }
      // year selector from the data's years (latest first); "" = latest available per country
      const ysel = $("gov-map-year");
      if (ysel && _govMapData) {
        const years = (_govMapData.years || []).slice().reverse();
        ysel.innerHTML = `<option value="">${esc(t("Latest available"))}</option>`
          + years.map(y => `<option value="${esc(y)}">${esc(y)}</option>`).join("");
      }
      renderGovMap();
    }
    async function renderGovMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-map-host"); if (!host) return;
      const sel = $("gov-map-ind"), ysel = $("gov-map-year");
      const indicator = sel && sel.value, year = ysel && ysel.value;
      let data = _govMapData;
      // a specific year needs its own fetch (the cached payload is "latest per country")
      if (year && (!data || data.year !== year)) {
        try { data = await api("/api/governments/map?indicator=" + encodeURIComponent(indicator) + "&year=" + encodeURIComponent(year)); }
        catch (e) { data = null; }
      }
      if (!data || !(data.by_country || []).length) {
        host.innerHTML = `<div class="muted">${esc(t("Country data loads automatically in the background when online — the map fills in once it lands."))}</div>`;
        $("gov-map-caveat").textContent = "";
        return;
      }
      const meta = data.indicator || {};
      const values = {}, names = {};
      (data.by_country || []).forEach(r => {
        if (r.value != null) values[r.country] = r.value;
        names[r.country] = ooRegionName(r.country, r.country);
      });
      await ooMap(host, {
        values, names,
        scale: "sequential", label: meta.label || "", unit: meta.unit || "",
        valueLabel: (iso, v) => `${ooRegionName(iso, iso)}: ${_govFmt(v, meta.unit)}`,
        caveat: data.caveat || "",
        onCountry: (iso) => {   // click a country -> its detail in the Countries subtab
          if (_govSubtabs) _govSubtabs.select("countries");
          const cs = $("gov-country");
          if (cs) { cs.value = iso; if (cs.value === iso) loadGovCountry(iso); }
        },
      });
      $("gov-map-caveat").textContent = (meta.label ? meta.label + " · " : "")
        + (data.year ? data.year + " · " : t("Latest available") + " · ") + (data.caveat || "");
    }

    async function govLoadStandard(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ensureOnline === "function" && !(await ensureOnline())) return;  // the ONE consent
      const old = btn && btn.textContent;
      if (btn) { btn.disabled = true; btn.textContent = t("Loading…"); }
      try {
        // The load runs ~3 min in a background job (returns {started, job}); poll the
        // job to completion and report the REAL stored figures — never the empty
        // start-state (which read "Loaded 0 figures." the instant the job began).
        await api("/api/governments/load-standard", {method: "POST", body: JSON.stringify({})});
        toast(t("Loading country data in the background…"), "ok",
          (typeof openTaskManager === "function") ? openTaskManager : null);
        const st = await pollJobStatus("/api/governments/load-standard/status", {
          onProgress: (s) => { if (btn && s.total) btn.textContent = t("Loading…") + " " + (s.done || 0) + "/" + s.total; },
        });
        if (st.state === "error") {
          toast((st.error) || t("Could not load country data."), "err");
        } else if (_jobStillRunning(st)) {
          // Polling gave up before the job finished — say so; never toast the
          // not-yet-final tally as if it were the result ("Loaded 0 figures.").
          toast(t("Still loading in the background — check the task manager for the result."), "ok",
            (typeof openTaskManager === "function") ? openTaskManager : null);
        } else {
          const res = st.result || {};
          let msg = t("Loaded country data:") + " " + (res.stored || 0) + " " + t("figures.");
          if (res.complete === false) msg += " " + t("(stopped early — partial)");
          toast(msg, "ok");
        }
        _govCountriesInit = false; _govMapInit = false; _govMapData = null;
        loadGovCountries();
      } catch (e) {
        toast((e && e.message) || t("Could not load country data."), "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = old || t("Load standard country data"); }
      }
    }

    let _lawStatus = null;
    async function loadLaw() {
      try {
        const s = await api("/api/law/status");
        _lawStatus = s;
        const jur = Object.entries(s.jurisdictions || {});
        $("law-status").innerHTML =
          `<div class="stat"><div class="n">${s.documents}</div><div class="k">laws</div></div>` +
          `<div class="stat"><div class="n">${s.tracked}</div><div class="k">with baseline</div></div>` +
          `<div class="stat"><div class="n">${s.changes}</div><div class="k">changes</div></div>` +
          `<div class="stat"><div class="n">${s.flagged}</div><div class="k">flagged</div></div>` +
          `<div class="stat"><div class="n">${jur.length}</div><div class="k">jurisdictions</div></div>`;
      } catch (e) { _lawStatus = null; $("law-status").innerHTML = '<div class="muted">Status unavailable.</div>'; }
      loadLawChanges(); loadLawDocs();
    }
    // Field report 2026-07-17 (S2c): the law tracker is 2 clicks deep from the
    // Governments tab's default (Countries) view -- a small always-visible chip
    // makes it discoverable without changing the default subtab.
    // governments-law-pointer-misleading-zero-tracked (P1): this chip used to
    // label /api/law/status's `tracked` field (server-side: documents WITH A
    // COMPLETED BASELINE) as "tracked" -- reading "0 tracked" on a corpus with 23
    // real documents being watched, before any online pass has run a baseline. One
    // click away, the Law subtab uses the SAME API response correctly, showing
    // BOTH numbers ("23 documents tracked · 0 baselined"). Since the two concepts
    // are legitimately distinct, the pointer now shows both too, matching that
    // established wording exactly instead of collapsing to one misleading word.
    async function loadLawPointer() {
      const host = $("gov-law-pointer"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      try {
        const s = await api("/api/law/status");
        host.textContent = "⚖ " + tf("Law: {documents} tracked · {baselined} baselined · {changes} changes",
          { documents: s.documents, baselined: s.tracked, changes: s.changes });
        host.title = t("Open the Law subtab — change tracking for statutes, gazettes and IP records.");
      } catch (e) { host.textContent = ""; }
    }
    // Colourised unified diff (green added / red removed), bounded for the feed.
    function renderDiff(diff, max = 400) {
      if (!diff) return "";
      const lines = diff.split("\n").slice(0, max);
      const more = diff.split("\n").length > max ? `<div class="dl ctx">… (diff truncated)</div>` : "";
      return `<div class="law-diff">` + lines.map(ln => {
        const c = ln[0] === "+" ? "add" : (ln[0] === "-" ? "del" : "ctx");
        return `<div class="dl ${c}">${esc(ln)}</div>`;
      }).join("") + more + `</div>`;
    }

    async function loadLawChanges() {
      const box = $("law-changes");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      const fo = $("law-flagged-only") ? $("law-flagged-only").checked : false;
      try {
        const d = await api("/api/law/changes?flagged_only=" + fo);
        if (!d.changes || !d.changes.length) {
          // Field report 2026-07-17 (S2a): distinguish "nothing changed" from
          // "never ran" -- a working tracker with zero real amendments must NOT
          // read like a broken/never-started one.
          const s = _lawStatus;
          if (s && s.documents) {
            const scope = fo ? t("no FLAGGED changes") : t("no changes");
            const when = s.last_checked_at
              ? tf("last pass {ago}", { ago: fmtAgo(s.last_checked_at) })
              : t("never checked yet");
            box.innerHTML = `<div class="muted">` + esc(tf(
              "{scope} — {documents} documents tracked · {tracked} baselined · {when}.",
              { scope, documents: s.documents, tracked: s.tracked, when })) + `</div>`;
          } else {
            box.innerHTML = `<div class="muted">${esc(t("No documents tracked yet."))}</div>`;
          }
          return;
        }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` + d.changes.map(ch =>
          `<div class="panel" style="background:var(--panel2); margin-top:8px">
            <b>${esc(ch.jurisdiction.toUpperCase())}</b> · ${esc(ch.title)}
            <span class="pill ${ch.flagged?'warn':''}">${ch.delta_bytes>0?'+':''}${ch.delta_bytes} bytes</span>
            ${(ch.flag_reasons||[]).length?'<span class="hint">'+ch.flag_reasons.map(esc).join(', ')+'</span>':''}
            <div class="hint" style="margin-top:4px">${ch.observed_at?fmtDateTime(ch.observed_at):''} ·
              <a href="/api/law/documents/${ch.document_id}/view" target="_blank" rel="noopener" title="offline stored copy + history">open reader</a> ·
              ${extLink(ch.official_url, "official source ↗", "muted")}</div>
            ${renderDiff(ch.diff)}
            <div class="law-ai-summary" data-rev="${ch.id}">${lawAiSummaryHtml(ch.id, ch.ai_summary)}</div>
          </div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load changes.</div>'; }
    }
    // AI change summaries (S3, ruled): auto-populated for UI-language-floor
    // jurisdictions; every other change offers an on-demand button. Loopback local
    // inference (airplane-safe since the §7 gate split) -- no ensureOnline gate,
    // matching the single-article summarize() precedent.
    function lawAiSummaryHtml(revId, s) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (s && s.summary) {
        return `“${esc(s.summary)}” <span class="muted">— ${esc(s.model)}</span>`
          + `<div class="hint muted">${esc(t("Generated by a local model — verify against the diff above."))}</div>`;
      }
      return `<button class="secondary tiny" onclick="lawSummarize(${revId}, this)">${esc(t("Summarize this change"))}</button>`;
    }
    async function lawSummarize(revId, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = btn.closest(".law-ai-summary");
      btn.disabled = true; btn.textContent = t("Summarizing locally…");
      try {
        const r = await api(`/api/law/revisions/${revId}/summarize`, { method: "POST" });
        if (r.ai_summary) { if (host) host.innerHTML = lawAiSummaryHtml(revId, r.ai_summary); return; }
        toast(t("Failed:") + " " + esc(r.status || "unavailable"), "err");
      } catch (e) {
        toast(t("Failed:") + " " + esc(e.message || e), "err");
      }
      btn.disabled = false; btn.textContent = t("Summarize this change");
    }
    // Field report 2026-07-17 (S2b): the per-doc last_status was written to the
    // table but never surfaced loudly -- classify it (verdict, from the API) into
    // a small coloured badge, keeping the REAL message on hover (never invented).
    const _LAW_VERDICT_PILL = {
      never_checked: "", robots_blocked: "warn", error: "warn", empty: "warn",
      changed: "ok", reverted: "", baselined: "ok", unchanged: "", other: "",
    };
    function lawVerdictBadge(x) {
      const tr = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const labels = {
        never_checked: tr("not checked yet"), robots_blocked: tr("robots-blocked"),
        error: tr("fetch error"), empty: tr("no usable text"), changed: tr("changed"),
        reverted: tr("reverted"), baselined: tr("baselined"), unchanged: tr("unchanged"),
        other: tr("other"),
      };
      const cls = _LAW_VERDICT_PILL[x.verdict] || "";
      const label = labels[x.verdict] || x.verdict;
      const hover = x.last_status ? esc(x.last_status) : tr("Never fetched yet.");
      return `<span class="pill ${cls}" title="${hover}">${esc(label)}</span>`;
    }
    let _lawDocsById = {};
    async function loadLawDocs() {
      const tr = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/law/documents");
        const tbl = $("law-docs");
        _lawDocsById = {};
        d.documents.forEach(x => { _lawDocsById[x.id] = x; });
        tbl.innerHTML = "<thead><tr><th>Jurisdiction</th><th>Title</th><th>Category</th><th>Status</th><th>Changes</th><th></th></tr></thead><tbody>" +
          d.documents.map(x =>
            `<tr${x.watched?'':' style="opacity:.55"'}><td>${esc(x.jurisdiction.toUpperCase())}</td><td>${esc(x.title)}</td><td>${esc(x.category)}</td>
              <td>${lawVerdictBadge(x)}${x.watched?'':' <span class="pill">'+esc(tr("not tracked"))+'</span>'}</td>
              <td>${x.revisions}${x.flagged?` (${x.flagged} flagged)`:''}</td>
              <td><a href="/api/law/documents/${x.id}/view" target="_blank" rel="noopener" title="offline stored copy + history">reader</a>
                · ${extLink(x.official_url||x.url, "official ↗", "muted")}
                · <a href="#" onclick="lawSetWatched(${x.id}, ${!x.watched}); return false" title="${x.watched?esc(tr('Stop tracking this document (its history stays).')):esc(tr('Resume tracking this document.'))}">${x.watched?esc(tr('stop')):esc(tr('resume'))}</a></td></tr>`).join("") +
          "</tbody>";
      } catch (e) { /* table optional */ }
    }
    async function lawAddDocument(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const msg = $("law-add-msg");
      const jurisdiction = $("law-add-jur").value.trim();
      const title = $("law-add-title").value.trim();
      const url = $("law-add-url").value.trim();
      const official_url = $("law-add-official").value.trim() || null;
      if (!jurisdiction || !title || !url) {
        msg.textContent = t("Jurisdiction, title and URL are all required.");
        return;
      }
      const online = await ensureOnline(t("Track a document now"));
      if (!online) return;
      btn.disabled = true;
      const label = btn.textContent; btn.textContent = t("Adding & tracking…");
      try {
        const r = await api("/api/law/documents", {
          method: "POST",
          body: JSON.stringify({ jurisdiction, title, url, official_url }),
        });
        msg.textContent = `${t("Added.")} ${t("Status:")} ${r.last_status || r.track_result.status}`;
        $("law-add-jur").value = ""; $("law-add-title").value = "";
        $("law-add-url").value = ""; $("law-add-official").value = "";
        loadLaw();
      } catch (e) {
        msg.textContent = e.message;
      } finally {
        btn.disabled = false; btn.textContent = label;
      }
    }
    async function lawSetWatched(id, watched) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        if (watched) {
          // Resuming re-adds by URL (the backend reactivates the SAME row rather
          // than duplicating it) -- a real fetch happens immediately, so gate it
          // like any other "track now" action.
          const x = _lawDocsById[id];
          if (!x) return;
          const online = await ensureOnline(t("Resume tracking this document"));
          if (!online) return;
          await api("/api/law/documents", {
            method: "POST",
            body: JSON.stringify({
              jurisdiction: x.jurisdiction, title: x.title, url: x.url,
              official_url: x.official_url || null,
            }),
          });
        } else {
          await api(`/api/law/documents/${id}`, { method: "DELETE" });
        }
      } catch (e) {
        toast(e.message, "err");
      }
      loadLaw();
    }
    async function lawTrack(btn) {
      // Long synchronous op (ethical, rate-limited fetch of each watched document):
      // give a persistent busy state so it never reads as "nothing happened".
      const label = btn ? btn.textContent : null;
      if (btn) { btn.disabled = true; btn.textContent = "Tracking…"; }
      const st = $("law-status");
      if (st) st.innerHTML = '<div class="muted">Tracking watched laws — ethical, rate-limited fetch; this can take a moment…</div>';
      try { const r = await api("/api/law/track", {method:"POST"});
        toast(`Tracked ${r.documents} law(s): ${r.baselines} baselines, ${r.changed} changed, ${r.flagged} flagged, ${r.errors} errors.`);
        loadLaw(); loadLawChanges && loadLawChanges();
      } catch (e) { toast(_failMsg("Tracking failed: {error}", e), "err"); if (st) loadLaw(); }
      finally { if (btn) { btn.disabled = false; btn.textContent = label || "Track changes now"; } }
    }
    async function lawSeed() {
      try { const r = await api("/api/law/seed", {method:"POST"});
        toast(`Seeded ${r.sources.created} sources, ${r.documents.created} laws.`); loadLaw(); }
      catch (e) { toast(e.message, "err"); }
    }

    // -- In-app documentation reader ---------------------------------------- //
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

    let DB_KEYS = null;   // current rendered stat keys (rebuild grid only when they change)

    // Two-class sources split (2026-07-23 field-feedback S1.3): the raw "sources" COUNT(*)
    // blends enabled+qualified (actively collecting) sources with disabled discovery
    // candidates awaiting review — the exact figure a field export showed as "~50k sources"
    // and read as an alarm. Never show it as one bare number: skip the flat key, label the
    // two split keys the backend now sends (database.py's counts["sources_qualified"] /
    // counts["sources_candidates"]) in plain language.
    const DB_STAT_HIDDEN_KEYS = new Set(["sources"]);
    const DB_STAT_LABELS = {
      sources_qualified: "Sources (collecting)",
      sources_pending: "Sources awaiting qualification (enabled)",
      sources_candidates: "Discovered candidates",
    };

    // B14: the COMPLETE on-disk footprint (A12b backend, GET /api/diagnostics/storage-footprint)
    // shown wherever storage size shows — the Library dashboard + the task-manager System tab.
    // It is a RECURSIVE disk walk (potentially slow on a 100 GB+ corpus), so it is fetched
    // LAZILY on tab open + CACHED — NEVER on the live poll (which would self-inflict the freeze
    // the scale mandate warns against) — with a Re-measure button. Honest split: the ENCRYPTED
    // private corpus (irreplaceable) vs re-downloadable PUBLIC blobs (dumps/maps/models). Bytes
    // only, no score; the method rides the #oo-tip hover.
    const _SF_PUBLIC = new Set(["wiki_dumps", "osm_regions", "ollama_models"]);
    let _sfCache = null;     // last storage-footprint payload (envelope .data)
    let _sfPending = null;   // in-flight promise, so two hosts share one walk

    async function _fetchStorageFootprint(force) {
      if (_sfCache && !force) return _sfCache;
      if (_sfPending) return _sfPending;
      _sfPending = api("/api/diagnostics/storage-footprint")
        .then(r => { _sfCache = (r && r.data) || null; _sfPending = null; return _sfCache; })
        .catch(e => { _sfPending = null; throw e; });
      return _sfPending;
    }

    function _sfLabel(kind, name, t) {
      const L = { db: t("Database"), wal: t("Database WAL"), shm: t("Database SHM"),
        wiki_dumps: t("Wikipedia dumps"), osm_regions: t("OpenStreetMap regions"),
        staging: t("Backup/restore staging"), other: t("Other (data folder)"),
        ollama_models: t("Local AI models") };
      return L[kind] || name || kind;
    }

    function _sfPaint(host, d, t) {
      if (!d || !Array.isArray(d.components)) {
        host.innerHTML = `<div class="muted">${esc(t("No storage measurement yet."))}</div>`; return;
      }
      const total = (d.totals || {}).grand_total_bytes || 0;
      const priv = d.components.filter(c => !_SF_PUBLIC.has(c.kind)).reduce((a, c) => a + (c.bytes || 0), 0);
      const pub = d.components.filter(c => _SF_PUBLIC.has(c.kind)).reduce((a, c) => a + (c.bytes || 0), 0);
      const rows = d.components.filter(c => (c.bytes || 0) > 0).sort((a, b) => b.bytes - a.bytes).map(c => {
        const pct = total ? Math.round(100 * c.bytes / total) : 0;
        const isPub = _SF_PUBLIC.has(c.kind);
        // "encrypted" is strictly true only of the DB triple (SQLCipher at rest); the honest
        // per-component tag is public=re-downloadable vs private=local. The summary line below
        // carries the "encrypted corpus" framing where the DB dominates the private bytes.
        const tag = isPub ? t("re-downloadable") : t("private (local)");
        const ttl = (c.detail || "") + (c.outside_data_dir ? ` · ${t("outside the data folder")}` : "");
        return `<div class="sf-row" style="display:flex;gap:8px;align-items:center;margin:3px 0"${ttl ? ` title="${esc(ttl)}"` : ""}>`
          + `<div style="flex:0 0 42%;min-width:0">${esc(_sfLabel(c.kind, c.name, t))} <span class="muted" style="font-size:11px">· ${esc(tag)}</span></div>`
          + `<div style="flex:1;height:8px;background:var(--panel2, rgba(128,128,128,.18));border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${isPub ? "var(--muted, #8c95a6)" : "var(--accent)"}"></div></div>`
          + `<div style="flex:0 0 auto;font-variant-numeric:tabular-nums">${esc(_fmtBytes(c.bytes))}</div></div>`;
      }).join("");
      host.innerHTML =
        `<div class="row" style="justify-content:space-between;align-items:baseline;gap:8px">`
        + `<div><b style="font-size:1.15em">${esc(_fmtBytes(total))}</b> <span class="muted">${esc(t("on disk, all stores"))}</span></div>`
        + `<button class="secondary" style="font-size:11px;padding:2px 8px" onclick="renderStorageFootprint('${esc(host.id)}', true)">${esc(t("Re-measure"))}</button></div>`
        + `<div class="muted" style="font-size:11px;margin:3px 0 8px"${d.method ? ` title="${esc(d.method)}"` : ""}>`
        // Honest label (no fabricated security): the private sum includes -shm + backup
        // staging, which are NOT necessarily encrypted — so it is "Private (local)", with the
        // corpus's at-rest encryption noted, not a blanket "encrypted" claim over every byte.
        + `${esc(t("Private (local; corpus encrypted at rest)"))}: <b>${esc(_fmtBytes(priv))}</b> · `
        + `${esc(t("Re-downloadable (dumps / maps / models)"))}: <b>${esc(_fmtBytes(pub))}</b></div>`
        + rows;
    }

    // Fetch (lazily, cached) + paint the footprint into a host. Paints the cache instantly on
    // re-open, then re-measures only when forced. Called on Library-tab open + System-tab open.
    async function renderStorageFootprint(hostId, force) {
      const host = document.getElementById(hostId);
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      if (_sfCache && !force) { _sfPaint(host, _sfCache, t); return; }
      host.innerHTML = `<div class="muted">${esc(t("Measuring on-disk footprint…"))}</div>`;
      try {
        const d = await _fetchStorageFootprint(force);
        _sfPaint(host, d, t);
        if (typeof loadDbStats === "function" && document.getElementById("db-file")) loadDbStats();
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(t("Could not measure storage:"))} ${esc(e.message || e)}</div>`;
      }
    }

    // Library central dashboard (field remark 16): the at-a-glance roll-up of everything
    // DOWNLOADED (the raw, re-downloadable layer) + everything EXTRAPOLATED (the AI-derived
    // layer). Honest counts + on-disk byte sizes only, no score; own stamp so the 16s poll
    // only repaints on a real change. The Database section below keeps the store detail.
    let _libOvStamp = "";
    // -- Ingest rhythm heatmap (2026-08-01 ruling 10) ---------------------- //
    // The maintainer asked to diversify the app's data-visualization vocabulary.
    // This is the first activation: a weekday x hour-of-day density grid over the
    // SAME articles_per_hour series the Activity tiles already fetch — no new
    // backend, no new poll, and it answers a question a line chart cannot ("when
    // does my collection actually run?").
    //
    // The honesty problem this had to solve: an empty cell is ambiguous. The
    // backend returns a bucket only for hours that HAVE articles, so a missing
    // hour inside the observed span is a true zero — but a slot that never
    // occurred at all (a 3-day-old corpus has no second Tuesday) is NOT a zero,
    // it is unobserved. Those two are rendered differently and never blended,
    // the same rule ooMap's no-data hatch follows.
    const _RHYTHM_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    function _ingestRhythm(series) {
      const pts = (series || [])
        .map(p => ({ms: Date.parse(String(p.t).length <= 19 ? p.t + "Z" : p.t), n: +p.n || 0}))
        .filter(p => isFinite(p.ms));
      if (!pts.length) return null;
      const first = Math.min(...pts.map(p => p.ms)), last = Math.max(...pts.map(p => p.ms));
      // slot = [weekday 0..6 (Mon-first)][hour 0..23]
      const total = [], seen = [];
      for (let d = 0; d < 7; d++) { total.push(new Array(24).fill(0)); seen.push(new Array(24).fill(0)); }
      const slot = (ms) => {
        const dt = new Date(ms);
        return [(dt.getUTCDay() + 6) % 7, dt.getUTCHours()];
      };
      // Walk every hour of the OBSERVED span so a slot's occurrence count is real:
      // an average over "times this hour actually came round" is comparable, an
      // average over an assumed full week is not.
      const HOUR = 36e5, MAX_HOURS = 24 * 400;   // bounded: a huge window can't hang the UI
      let steps = 0;
      for (let ms = first; ms <= last && steps < MAX_HOURS; ms += HOUR, steps++) {
        const [d, h] = slot(ms); seen[d][h] += 1;
      }
      if (steps >= MAX_HOURS) return null;       // honestly render nothing rather than a partial grid
      pts.forEach(p => { const [d, h] = slot(p.ms); total[d][h] += p.n; });
      return {total, seen, first, last, n: pts.reduce((a, p) => a + p.n, 0)};
    }
    function ingestRhythmSvg(series) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const g = _ingestRhythm(series);
      if (!g) return "";
      // Colour by the AVERAGE per occurrence (comparable across slots seen a
      // different number of times); the hover states both the total and the
      // occurrences, so the reader can always recover the raw counts.
      let peak = 0;
      for (let d = 0; d < 7; d++) for (let h = 0; h < 24; h++) {
        if (g.seen[d][h] > 0) peak = Math.max(peak, g.total[d][h] / g.seen[d][h]);
      }
      const cw = 15, ch = 15, padL = 34, padT = 16;
      const w = padL + 24 * cw + 4, hgt = padT + 7 * ch + 16;
      let cells = "";
      for (let d = 0; d < 7; d++) for (let h = 0; h < 24; h++) {
        const x = padL + h * cw, y = padT + d * ch;
        const occ = g.seen[d][h];
        if (!occ) {   // NEVER a zero: this slot did not occur in the observed span
          cells += `<rect x="${x}" y="${y}" width="${cw - 1}" height="${ch - 1}" fill="url(#rhythm-none)"`
            + `><title>${esc(t(_RHYTHM_DAYS[d]))} ${h}:00 — ${esc(t("not observed yet"))}</title></rect>`;
          continue;
        }
        const avg = g.total[d][h] / occ;
        const frac = peak > 0 ? avg / peak : 0;
        const fill = frac <= 0 ? "var(--panel2)"
          : `color-mix(in srgb, var(--accent) ${Math.round(12 + frac * 88)}%, var(--panel2))`;
        const title = `${t(_RHYTHM_DAYS[d])} ${h}:00 — `
          + t("{total} articles over {occ} occurrence(s), {avg} on average")
              .replace("{total}", fmtNum(g.total[d][h])).replace("{occ}", String(occ))
              .replace("{avg}", fmtNum(avg, 1));
        cells += `<rect x="${x}" y="${y}" width="${cw - 1}" height="${ch - 1}" fill="${fill}"`
          + ` stroke="var(--border)" stroke-width="0.4"><title>${esc(title)}</title></rect>`;
      }
      const dayLabels = _RHYTHM_DAYS.map((d, i) =>
        `<text x="${padL - 4}" y="${padT + i * ch + 11}" text-anchor="end" font-size="8.5"
           fill="var(--muted)">${esc(t(d).slice(0, 3))}</text>`).join("");
      const hourLabels = [0, 6, 12, 18].map(h =>
        `<text x="${padL + h * cw}" y="${padT - 5}" font-size="8.5" fill="var(--muted)">${h}:00</text>`).join("");
      return `<div class="lib-rhythm">
        <svg viewBox="0 0 ${w} ${hgt}" width="100%" style="display:block;max-width:${w}px" role="img"
             aria-label="${esc(t("Ingest rhythm: articles collected by weekday and hour of day (UTC)."))}">
          <defs><pattern id="rhythm-none" width="4" height="4" patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4"
            stroke="var(--border)" stroke-width="1"></line></pattern></defs>
          ${dayLabels}${hourLabels}${cells}
        </svg>
        <div class="hint muted">${esc(t("Hatched = that hour has not come round yet in the recorded span — not a zero."))}</div>
        <div class="card-caveat">${esc(t("Shading is the AVERAGE articles per occurrence of that weekday-hour (UTC), because slots recur a different number of times in a short window; the hover gives the real total and how many times the slot occurred. Counts only, never a score."))}</div>
      </div>`;
    }

    // -- Library subtabs (2026-08-01 ruling 9) ----------------------------- //
    // Seven stacked sections became five views through the ONE universal subtab
    // component (invariant #18). The panels are untouched — this is a regrouping,
    // not a rewrite — and each view's loaders fire on SELECT, not on tab open, so
    // opening the Library no longer pays for the recursive storage walk and the
    // coverage map before you have asked for them ("folded must not mean
    // fetched", the Advanced-tab precedent). Each view loads once per session.
    let _libViewTabs = null, _libView = "overview";
    const _libViewLoaded = new Set();
    const _LIB_VIEW_LOADERS = {
      overview: () => { renderLibraryOverview(); },
      activity: () => { renderLibraryActivityGraphs(); },
      tracked:  () => { renderLibraryWikiGraphs(); renderLibraryLawGraphs(); },
      composition: () => { renderCompositionFigures(); },
      storage:  () => { renderStorageFootprint("library-storage"); },
      coverage: () => { loadCoverage(); },
    };
    function selectLibraryView(key) {
      if (!_LIB_VIEW_LOADERS[key]) key = "overview";
      _libView = key;
      document.querySelectorAll("#tab-library .lib-view").forEach(el => {
        el.style.display = (el.id === "lib-view-" + key) ? "" : "none";
      });
      if (!_libViewLoaded.has(key)) {
        _libViewLoaded.add(key);
        try { _LIB_VIEW_LOADERS[key](); }
        catch (e) { _libViewLoaded.delete(key); }   // a failed load must be retryable
      }
    }
    function _wireLibraryViews() {
      const nav = $("library-views");
      if (!nav) { renderLibraryOverview(); return; }   // defensive: markup missing
      if (!_libViewTabs) _libViewTabs = ooSubtabs(nav, selectLibraryView, {initial: _libView});
      selectLibraryView(_libView);
    }
    async function renderLibraryOverview() {
      const host = $("library-overview");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      let d, fig;
      try {
        // Figures endpoint is 60 s-cached server-side, so polling it here is cheap.
        [d, fig] = await Promise.all([
          api("/api/library/overview"),
          api("/api/database/figures").catch(() => ({})),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const stamp = JSON.stringify([d.downloaded, d.derived, fig]);
      if (stamp === _libOvStamp) return;   // live poll: unchanged, no repaint
      _libOvStamp = stamp;
      const num = v => (v == null ? "—" : fmtNum(v));
      const sz = v => (v == null || !v) ? "—" : _fmtBytes(v);
      const tile = (n, k) => `<div class="stat"><div class="n">${esc(n)}</div><div class="k">${esc(k)}</div></div>`;
      const dl = d.downloaded || {}, der = d.derived || {};
      const wiki = dl.wikipedia || {}, maps = dl.maps || {}, laws = dl.laws || {};
      const dlTiles = [
        tile(num(wiki.tracked_pages), t("Wikipedia pages tracked")),
        tile(num(wiki.revisions), t("Wikipedia revisions")),
        tile(`${num((wiki.dumps || {}).count)} · ${sz((wiki.dumps || {}).total_bytes)}`, t("Wikipedia dumps")),
        tile(`${num((maps.osm_regions || {}).count)} · ${sz((maps.osm_regions || {}).total_bytes)}`, t("OpenStreetMap regions")),
        tile(num((dl.markets || {}).commodity_prices), t("Market price points")),
        tile(num(laws.documents), t("Law documents")),
        tile(num(laws.revisions), t("Law revisions")),
        tile(num((dl.statistics || {}).figures), t("Official statistics figures")),
        tile(`${num((dl.models || {}).count)} · ${sz((dl.models || {}).total_bytes)}`, t("Local AI models")),
      ].join("");
      // EXTRAPOLATED: each AI-analysis kind shown by name (nothing hidden) + AI keywords + watches.
      const KIND_LABELS = { summary: t("AI summaries"), translation: t("AI translations"),
        synthesis: t("AI syntheses"), entities: t("AI entities") };
      const aaKinds = (der.article_analyses || {}).by_kind || {};
      const aaTiles = Object.keys(aaKinds).length
        ? Object.entries(aaKinds).map(([k, v]) => tile(num(v), KIND_LABELS[k] || `${t("AI")} ${esc(k)}`)).join("")
        : tile("—", t("AI summaries"));
      const derTiles = aaTiles
        + tile(num((der.ai_keywords || {}).total), t("AI-extracted keywords"))
        + tile(num(der.watches_enabled), t("Active watches"));
      // Computed corpus figures (field ask 2026-07-02): averages + ingestion rate.
      // Real counts, no score; each label states its method. "—" when not yet known.
      const figTiles = (fig && fig.articles) ? [
        tile(num(fig.avg_word_count), t("Avg words / article")),
        tile(num(fig.avg_keywords_per_article), t("Avg keywords / article")),
        tile(num(fig.articles_per_day), t("Articles / day (avg since first)")),
        tile(num(fig.articles_per_hour_recent), t("Articles / hour (last 24h)")),
      ].join("") : "";
      // Downloaded section TIDIED (field feedback item 5): a compact, collapsed-by-
      // default <details> disclosure — the established "adv-collect" convention
      // (Settings' own legacy/advanced sections) — instead of a permanently-open
      // 9-tile grid. Nothing lost, just less default visual space; the live
      // Activity/Wikipedia/Law GRAPH sections below carry the evolution-over-time
      // view these bare counts used to be the only source of.
      host.innerHTML =
        (figTiles
          ? `<div class="hint" style="margin-bottom:6px">${esc(t("Corpus figures — measured averages and the current ingestion rate:"))}</div>`
            + `<div class="stat-grid">${figTiles}</div>`
          : "")
        + `<details class="adv-collect" style="margin-top:10px"><summary>${esc(t("Downloaded — the raw, re-downloadable layer"))}</summary>`
        + `<div class="stat-grid" style="margin-top:8px">${dlTiles}</div></details>`
        + `<div class="hint" style="margin:12px 0 6px">${esc(t("Extrapolated — AI-derived from your corpus (unreliable, never the trusted index):"))}</div>`
        + `<div class="stat-grid">${derTiles}</div>`;
    }

    // -- Library counter-evolution graphs (S2, 2026-07-23 field-feedback) -------
    // Small honest evolution graphs for counters that had no history anywhere
    // (sources/keywords/Wikipedia+law tracked counts) plus a live-DERIVED
    // articles/hour series (real history since Article.created_at already
    // existed -- backfills with no gap). Reuses the EXISTING dashChartSvg (the
    // small-tile renderer, line-when-dense/bars-when-sparse, invariant #16) and
    // chartEnlarge (click-to-enlarge into an interactive ooChart) -- no new
    // visual language, no larger tile footprint than any other Library number.
    const LIB_METRIC_LABEL_KEYS = {
      articles_per_hour: "Articles / hour",
      sources: "Sources tracked",
      keywords: "Distinct keywords",
      wiki_pages: "Wikipedia pages tracked",
      wiki_revisions: "Wikipedia revisions tracked",
      law_documents: "Law documents tracked",
      law_revisions: "Law revisions tracked",
    };
    // The y-axis UNIT per metric — the tiles used to pass "" so the axis stated
    // no unit at all, which is half of why a flat "23" beside a bare "n=2" read
    // as "23 documents or 2?" (maintainer-reported 2026-08-01).
    const LIB_METRIC_UNIT_KEYS = {
      articles_per_hour: "articles / hour",
      sources: "sources",
      keywords: "keywords",
      wiki_pages: "pages",
      wiki_revisions: "revisions",
      law_documents: "documents",
      law_revisions: "revisions",
    };
    // What one DATAPOINT is, per metric: the counter metrics are hourly
    // SNAPSHOTS of a running total, while articles_per_hour is a per-HOUR
    // bucket derived from created_at. n= now says which.
    const LIB_METRIC_N_UNIT_KEYS = {articles_per_hour: "hours"};
    const LIB_DEFAULT_N_UNIT = "snapshots";
    // 2026-07-24 Session A §5: per-tile WINDOW SWITCHER (ruled) — every Library
    // graph tile, including the new qualification one, starts on the SAME
    // default window and can be independently switched without reloading the
    // whole panel. "All" maps to the backend's own generous (not literally
    // unbounded) history cap.
    const LIB_WINDOWS = [[7, "7d"], [30, "30d"], [90, "90d"], [3650, "All"]];
    const LIB_DEFAULT_DAYS = 30;
    let _libTileDays = {};    // metric (or "__qual") -> the window currently shown
    let _libGraphData = {};   // metric -> last-fetched /api/library/history payload
    function _libAllZero(nums) {
      // "zero/no-data" (ruled): every point is 0, or there simply are no points —
      // hide-flat collapses this to a one-line note instead of a silently blank
      // or misleadingly-flat chart (the never-blank-and-silent rule).
      return !nums.length || nums.every(n => !n);
    }
    function _libWindowChips(key, current) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return `<div style="display:flex;gap:3px;margin-top:4px" class="lib-win-row">` +
        LIB_WINDOWS.map(([d, lbl]) =>
          `<button type="button" class="chip tiny${d === current ? " on" : ""}" onclick="_libSetWindow('${key}', ${d})">${esc(t(lbl))}</button>`
        ).join("") + `</div>`;
    }
    async function _libGraphTile(metric, days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const cur = days || _libTileDays[metric] || LIB_DEFAULT_DAYS;
      _libTileDays[metric] = cur;
      const label = t(LIB_METRIC_LABEL_KEYS[metric] || metric);
      let d;
      try {
        d = await api(`/api/library/history?metric=${encodeURIComponent(metric)}&days=${cur}`);
      } catch (e) {
        return `<div id="lib-tile-${esc(metric)}" style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      _libGraphData[metric] = d;
      const series = Array.isArray(d.series) ? d.series : [];
      const flat = _libAllZero(series.map(p => p.n));
      // Library metrics are COUNTS: zero-based axis (Item Y), a NEUTRAL colour
      // (a falling keyword count is not "bad" — market up=green semantics do not
      // apply), the real unit on the axis, and an n= that says what it counts.
      const body = flat
        ? `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`
        : dashChartSvg(series.map(p => ({observed_on: p.t, price: p.n})),
                       t(LIB_METRIC_UNIT_KEYS[metric] || ""),
                       {zeroBase: true, neutral: true,
                        nUnit: t(LIB_METRIC_N_UNIT_KEYS[metric] || LIB_DEFAULT_N_UNIT)});
      const began = d.recording_began_at
        ? `<div class="hint muted" style="font-size:11px">${esc(t("Recording began at {x}.").replace("{x}", d.recording_began_at))}</div>`
        : "";
      return `<div id="lib-tile-${esc(metric)}" style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
        <div style="display:flex;align-items:baseline;gap:6px;justify-content:space-between">
          <b style="font-size:12.5px">${esc(label)}</b>
          <button class="ghost tiny" onclick="enlargeLibMetric('${metric}')" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
        </div>${body}${began}${_libWindowChips(metric, cur)}</div>`;
    }
    async function _renderLibGraphHost(hostId, metrics) {
      const host = $(hostId);
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const tiles = await Promise.all(metrics.map(([m, days]) => _libGraphTile(m, days)));
        host.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:10px">${tiles.join("")}</div>`;
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(e.message || e)}</div>`;
      }
    }

    // -- The 4-line source-QUALIFICATION tile (2026-07-24 Session A §5) --------
    // qualified / disqualified / never-judged / candidates on ONE shared axis
    // (all four are source COUNTS — same unit, so multi-axis is never the
    // honest answer here per the dual-axis rejection); auto-switches to log10
    // when the cross-series spread is large, always labelled "log scale",
    // never silently. Counts only — never a quality score.
    const LIB_QUAL_METRICS = [
      "sources_qualified", "sources_disqualified", "sources_never_judged", "sources_candidates",
    ];
    const LIB_QUAL_LABELS = {
      sources_qualified: "Qualified", sources_disqualified: "Disqualified",
      // NOT "Never judged", which this line claimed until 2026-08-04 and is false for
      // roughly the population the livelock fix was about: the metric counts
      // status == "unqualified", and an attempt that concludes no_evidence deliberately
      // leaves status alone, so an enabled feedless source is tried over and over and
      // still counted here. "Awaiting a verdict" is what the number actually measures.
      sources_never_judged: "Awaiting a verdict", sources_candidates: "Candidates",
    };
    // Wrap an LTR-shaped VALUE before interpolating it into a translated sentence, so the
    // bidi algorithm treats it as one run instead of reordering its parts against the
    // surrounding RTL text. Measured in the real Arabic page: "بدأ التسجيل في " + an ISO
    // timestamp renders in visual order ".07T18:00:00-07-2026" -- the year at the wrong
    // end, which is a MISREAD date, not merely an ugly one. With U+2068 FIRST STRONG
    // ISOLATE / U+2069 POP DIRECTIONAL ISOLATE around it: ".2026-07-07T18:00:00".
    //
    // Plain characters, not markup, so they survive esc() and work anywhere a string is
    // interpolated. Needed for punctuation-joined runs (dates, versions, IDs, URLs,
    // ranges); a bare number does not need it and does not get one, since an isolate on a
    // lone digit is invisible clutter. LTR locales are unaffected -- the characters are
    // zero-width and the reordering they suppress only happens in an RTL paragraph.
    const _LTR_ISOLATE = ["⁨", "⁩"];
    function _ltrIsolate(v) {
      return v == null ? v : _LTR_ISOLATE[0] + String(v) + _LTR_ISOLATE[1];
    }
    // Fetched for the composition note, deliberately NOT charted as a fifth line: it is a
    // SUBSET of the line above (nested series on one axis read as separate populations),
    // and it starts recording today while the others have months, so a new line would
    // appear to begin at zero when it simply was not being recorded. One data point is
    // enough to state the split in words, which is what the note does.
    const LIB_QUAL_SPLIT_METRIC = "sources_never_attempted";
    let _libQualSeries = [];   // stashed live series (enlarge + in-place re-render)
    function _libQualSpread(series) {
      const vals = series.flatMap(s => s.points.map(p => p.v)).filter(v => v > 0);
      return vals.length ? Math.max(...vals) / Math.min(...vals) : 1;
    }
    // Whether a log axis is even POSSIBLE for these series. Source counts legitimately
    // start at zero and log10(0) is undefined, so ooChart refuses log mode on such data
    // and falls back to linear -- this asks the same question, so the tile's own "log
    // scale" chip can never claim a scale the chart declined to use.
    function _libQualLogOk(series) {
      return series.every(s => (s.points || []).every(p => p.v != null && +p.v > 0));
    }
    async function _libQualificationTile(days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const cur = days || _libTileDays.__qual || LIB_DEFAULT_DAYS;
      _libTileDays.__qual = cur;
      const label = t("Source qualification");
      let payloads, splitPayload = null;
      try {
        const all = await Promise.all(
          LIB_QUAL_METRICS.concat([LIB_QUAL_SPLIT_METRIC]).map(m =>
            api(`/api/library/history?metric=${encodeURIComponent(m)}&days=${cur}`)));
        payloads = all.slice(0, LIB_QUAL_METRICS.length);
        splitPayload = all[all.length - 1];
      } catch (e) {
        return `<div id="lib-tile-__qual" style="flex:2;min-width:280px;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      _libQualSeries = LIB_QUAL_METRICS.map((m, i) => ({
        // NO unit. ooChart's legend renders `label` then `n=N · unit`, where n is the
        // DATAPOINT count -- so the slot is the unit OF N, not of the values. Passing the
        // label read "Qualified n=29 · Qualified" (redundant); passing "sources" read
        // "Qualified n=29 · sources", which a reader takes as "29 sources in this
        // category" and cannot be true of all four series at once. It is 29 daily
        // samples. An adversarial critic reading the screenshot caught the second form.
        // What the values count is said by the tile's title and its caveat.
        label: t(LIB_QUAL_LABELS[m] || m),
        points: (payloads[i].series || []).map(p => ({t: p.t, v: p.n})),
      }));
      const flat = _libAllZero(_libQualSeries.flatMap(s => s.points.map(p => p.v)));
      const logY = _libQualSpread(_libQualSeries) > 50 && _libQualLogOk(_libQualSeries);
      const began = payloads.map(p => p.recording_began_at).filter(Boolean).sort()[0];
      const beganNote = began
        ? `<div class="hint muted" style="font-size:11px">${esc(t("Recording began at {x}.").replace("{x}", _ltrIsolate(began)))}</div>`
        : "";
      const body = flat
        ? `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`
        : `<div class="lib-qual-chart"></div>` + (logY
            ? `<div class="hint muted" style="font-size:10.5px">${esc(t("log scale"))}</div>` : "");
      return `<div id="lib-tile-__qual" style="flex:2;min-width:280px;padding:6px;border:1px solid var(--border);border-radius:8px">
        <div style="display:flex;align-items:baseline;gap:6px;justify-content:space-between">
          <b style="font-size:12.5px">${esc(label)}</b>
          <button class="ghost tiny" onclick="enlargeLibQualification()" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
        </div>${body}${_libQualSplitNote(payloads, splitPayload)}${beganNote}${_libWindowChips("__qual", cur)}</div>`;
    }
    // The composition of the "Awaiting a verdict" line, in words. Extracted as a pure
    // function of the two payloads so a test can drive it directly: a source guard
    // asserting the identifier appears would survive deleting the sentence.
    function _libQualNewest(payload) {
      const pts = (payload && payload.series) || [];
      // Newest by timestamp, not by array position: a reordered payload must not silently
      // become "the latest reading".
      let best = null;
      for (const p of pts) if (best === null || String(p.t) > String(best.t)) best = p;
      return best === null ? null : best.n;
    }
    function _libQualSplitText(awaiting, never) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : null;
      const fmt = (tpl, vars) => (tf ? tf(tpl, vars)
        : Object.keys(vars).reduce((s, k) => s.split("{" + k + "}").join(String(vars[k])), t(tpl)));
      // An absent reading is stated as absent. Rendering 0 here would claim every waiting
      // source had been attempted, which is the opposite of what "not recorded yet" means.
      if (awaiting === null || never === null) {
        return t("Not yet recorded: how many of these have never been attempted.");
      }
      if (never > awaiting) {
        // Structurally a subset, so this can only be two readings from different
        // snapshots. Say that rather than printing a negative remainder.
        return t("The two readings come from different snapshots, so the split is not comparable yet.");
      }
      // Label:value, not prose. A conjugated verb cannot agree with an interpolated
      // count without CLDR plural rules this app does not have -- the prose form read
      // "1 have never been attempted", and the French carried the identical error
      // because the TEMPLATE always pluralised. Russian has three plural forms and
      // Arabic six, so per-form keys are not the answer either. Nothing conjugates here,
      // so every locale is correct by construction. Caught by an adversarial critic
      // reading the rendered screenshot, not by any mechanical check.
      return fmt(
        "Awaiting a verdict: {awaiting} · never attempted: {never} · tried without one: {tried}",
        {awaiting: awaiting, never: never, tried: awaiting - never});
    }
    function _libQualSplitNote(payloads, splitPayload) {
      const i = LIB_QUAL_METRICS.indexOf("sources_never_judged");
      const awaiting = i < 0 ? null : _libQualNewest(payloads[i]);
      const never = _libQualNewest(splitPayload);
      return `<div class="hint muted" style="font-size:11px">${esc(_libQualSplitText(awaiting, never))}</div>`;
    }
    function _libRenderQualChart(root) {
      const scope = root || document;
      const host = scope.querySelector ? scope.querySelector(".lib-qual-chart") : null;
      const live = _libQualSeries.filter(s => s.points.length);
      if (!host || !live.length) return;   // defensive: a flat/errored tile has no chart host
      // zeroBase: these are source COUNTS, so the axis starts at a true zero
      // (ignored under logY, where log(0) is undefined — stated in ooChart).
      const logY = _libQualSpread(_libQualSeries) > 50 && _libQualLogOk(_libQualSeries);
      ooChart(host, live, {height: 150, indexed: false, logY: logY, zeroBase: !logY});
    }
    function enlargeLibQualification() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const live = _libQualSeries.filter(s => s.points.length);
      if (!live.length) return;   // defensive: nothing to enlarge
      chartEnlarge(t("Source qualification"), live,
        t("Counts only, never a quality score. Qualified = actively collecting; disqualified and awaiting-a-verdict are enabled but not (yet) admitted; candidates are disabled, awaiting review. Awaiting a verdict does not mean untried: an attempt that finds nothing to judge is recorded and leaves the status alone, so a source with no feed stays here however often it is tried."),
        {scales: true});
    }

    // -- Per-language corpus growth (small multiples) --------------------------
    // "Which languages is my corpus actually growing in" — the feedback surface
    // the language-equilibrium lever never had. One panel per language on ONE
    // shared scale, which is what makes the panels comparable at a glance.
    //
    // Every number the endpoint declines to plot is stated here rather than
    // dropped: the ranked-out tail, the articles with no asserted language (the
    // lever's own blind spot), and where the series starts if the corpus is
    // younger than the window.
    const LIB_LANG_TOP_N = 12;
    // Pure, so the disclosures can be tested for what they SAY rather than for
    // which identifiers appear in the source. A substring guard over the tile
    // survives a mutation that leaves `d.other` in a variable binding and drops
    // the sentence -- which is precisely the class of silent truncation these
    // sentences exist to prevent.
    function _libLangNotes(d, t, tf) {
      const notes = [];
      notes.push(d.bucket === "hour" ? t("Articles stored per hour.") : t("Articles stored per day."));
      const other = d.other || {};
      if (other.languages) {
        notes.push(tf("{langs} more languages ({articles} articles) are counted but not drawn.",
          {langs: other.languages, articles: other.articles}));
      }
      const un = d.unassigned || {};
      if (un.articles) {
        notes.push(tf("{n} articles have no asserted language and are not drawn — the equilibrium lever cannot see them either ({deduced} carry a deduced one).",
          {n: un.articles, deduced: un.with_deduced_language}));
      }
      // Said only when the series is genuinely CLAMPED by the corpus's own start —
      // the backend decides that, rather than the frontend re-deriving it from two
      // timestamps and getting the bucket arithmetic subtly wrong.
      if (d.clamped_to_corpus_start && d.corpus_began_at) {
        notes.push(tf("The corpus itself begins at {x}, so the series starts there.", {x: d.corpus_began_at}));
      }
      return notes;
    }
    async function _libLanguageTile(days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => String(tpl).replace(/\{(\w+)\}/g, (m, k) => (k in v ? v[k] : m)));
      const cur = days || _libTileDays.__lang || LIB_DEFAULT_DAYS;
      _libTileDays.__lang = cur;
      const label = t("Growth by language");
      let d;
      try {
        d = await api(`/api/library/languages?days=${cur}&top_n=${LIB_LANG_TOP_N}`);
      } catch (e) {
        return `<div id="lib-tile-__lang" style="flex:1 1 100%;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      // The panel label is the language NAME in the current UI locale, via the
      // browser's own CLDR data (ooLangName) — the code is what the lever keys on,
      // not what a reader should have to decode. Degrades to the code.
      const panels = (d.series || []).map(s => ({
        label: ooLangName(s.language, s.language),
        points: (s.points || []).map(p => ({date: p.t, count: p.n})),
      }));
      // neutral: a language growing more slowly than another is not "bad", so the
      // market up=green/down=red semantics must not be borrowed here.
      const body = panels.length
        ? smallMultiplesSvg(panels, {neutral: true})
        : `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`;

      const notes = _libLangNotes(d, t, tf).map(esc);
      return `<div id="lib-tile-__lang" style="flex:1 1 100%;padding:6px;border:1px solid var(--border);border-radius:8px">
        <b style="font-size:12.5px">${esc(label)}</b>
        ${body}
        <div class="hint muted" style="font-size:11px">${notes.join(" ")}</div>
        ${_libWindowChips("__lang", cur)}</div>`;
    }

    // Re-render exactly ONE tile in place when its window chip is clicked —
    // never the whole panel (a switch on one metric must not disturb the
    // others' state or cause a visible flash across the row).
    async function _libSetWindow(key, days) {
      const el = $(key === "__qual" ? "lib-tile-__qual"
        : key === "__lang" ? "lib-tile-__lang" : "lib-tile-" + key);
      if (!el) return;
      const html = key === "__qual" ? await _libQualificationTile(days)
        : key === "__lang" ? await _libLanguageTile(days)
        : await _libGraphTile(key, days);
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      const fresh = tmp.firstElementChild;
      if (!fresh) return;
      el.replaceWith(fresh);
      if (key === "__qual") _libRenderQualChart(fresh);
    }

    // The live current-rate readout stays in renderLibraryOverview's own
    // "Articles / hour (last 24h)" tile above (unchanged) — this graph adds the
    // EVOLUTION over time the maintainer asked for, alongside the counters that
    // had no history at all until this feature shipped, plus the qualification
    // funnel's own 4-line breakdown (§5).
    // ===== Library -> Composition: what the corpus is MADE OF ============== //
    // Three figures (GUI visualization plan C1/C2/C5). Each is a horizontal SORTED
    // BAR or a Lorenz curve — position and length carry the quantity, colour carries
    // only category, and every one ends in the shared figMeta panel so its method,
    // caveat and n are on screen without a click.
    //
    // SVG, not canvas: an SVG figure has a DOM, so the .sr-only data table below each
    // chart is the same numbers a sighted reader sees, and the figure can be exported
    // as vector. Canvas is reserved for ooChart, where pan/zoom over many points
    // earns it.

    // A horizontal bar row set. `rows` are {label, n, hatched?, title?}. The bar
    // LENGTH is the only quantitative channel; a hatched row is an absence and is
    // textured rather than coloured, so it can never be mistaken for a short bar.
    function _figBars(rows, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const o = opts || {};
      if (!rows.length) return figEmpty(o.empty);
      const max = Math.max(...rows.map(r => Math.max(0, +r.n || 0)), 1);
      const w = 100, labelW = o.labelW || 34;
      const body = rows.map((r) => {
        const n = Math.max(0, +r.n || 0);
        const pct = (n / max) * (w - labelW - 12);
        const fill = r.hatched ? figGapFill() : (r.color || "var(--fig-1)");
        return `<div class="fig-bar-row"${r.title ? ` title="${esc(r.title)}"` : ""}>` +
          `<span class="fig-bar-label">${esc(r.label)}</span>` +
          `<span class="fig-bar-track"><span class="fig-bar-fill" style="width:${pct.toFixed(2)}%;` +
          `background:${r.hatched ? "transparent" : fill};` +
          (r.hatched ? "background-image:repeating-linear-gradient(45deg, var(--fig-gap) 0 1.25px, transparent 1.25px 6px);border:1px solid var(--border)" : "") +
          `"></span></span>` +
          `<span class="fig-bar-n">${r.hatched ? esc(t("not measured")) + " · " : ""}${esc(fmtNum(n))}</span>` +
          `</div>`;
      }).join("");
      // One shared <defs> for the hatch, and the sr-only table so the numbers are
      // readable without seeing the bars.
      return `<svg width="0" height="0" style="position:absolute">${figGapDefs()}</svg>` +
        `<div class="fig-bars" role="img" aria-label="${esc(o.aria || o.title || "")}">${body}</div>` +
        `<table class="sr-only"><caption>${esc(o.title || "")}</caption><tbody>` +
        rows.map(r => `<tr><th scope="row">${esc(r.label)}</th><td>` +
          (r.hatched ? esc(t("not measured")) : esc(fmtNum(Math.max(0, +r.n || 0)))) +
          `</td></tr>`).join("") + `</tbody></table>`;
    }

    // The Lorenz curve: cumulative share of articles against cumulative share of
    // sources. The equality DIAGONAL is drawn and labelled, because the curve means
    // nothing without it — the gap between the two IS the inequality, and a curve
    // shown alone reads as an arbitrary shape.
    function _figLorenz(curve, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const o = opts || {};
      if (!curve || curve.length < 2) return figEmpty(o.empty);
      const W = 320, H = 220, padL = 40, padB = 30, padT = 10, padR = 10;
      // ooViz.linearScale, wired here for the first time (it was written, node-tested
      // and never called).
      const X = ooViz.linearScale(0, 1, padL, W - padR);
      const Y = ooViz.linearScale(0, 1, H - padB, padT);
      const pts = curve.map(p => `${X(p.sources).toFixed(2)},${Y(p.articles).toFixed(2)}`).join(" ");
      const ticks = [0, 0.25, 0.5, 0.75, 1];
      const grid = ticks.map(v =>
        `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${W - padR}" y2="${Y(v).toFixed(1)}"` +
        ` stroke="var(--border-soft)" stroke-width="1"/>` +
        `<text x="${padL - 5}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end" font-size="8.5"` +
        ` fill="var(--muted)">${Math.round(v * 100)}%</text>`).join("");
      const xlab = ticks.map(v =>
        `<text x="${X(v).toFixed(1)}" y="${H - padB + 12}" text-anchor="middle" font-size="8.5"` +
        ` fill="var(--muted)">${Math.round(v * 100)}%</text>`).join("");
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;max-width:${W}px"` +
        ` role="img" aria-label="${esc(o.aria || "")}">${grid}${xlab}` +
        `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="var(--fig-6)"` +
        ` stroke-width="1.5" stroke-dasharray="4 3"/>` +
        `<polyline points="${pts}" fill="none" stroke="var(--fig-1)" stroke-width="2"/>` +
        // The diagonal's label sits BESIDE the line, not on it: printed on the line it
        // was unreadable exactly where the two cross.
        `<text x="${X(0.56)}" y="${Y(0.34)}" font-size="8.5" fill="var(--muted)">` +
        `${esc(t("equal draw"))}</text>` +
        `</svg>` +
        `<div class="hint muted">${esc(t("Horizontal: share of sources, fewest articles first. Vertical: share of articles."))}</div>`;
    }

    async function renderCompositionFigures() {
      const host = $("lib-composition");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Each figure fetches independently and renders its own failure, so one broken
      // endpoint leaves the other two on screen instead of blanking the whole view.
      const get = async (path) => { try { return await api(path); } catch (e) { return {__err: e}; } };
      const [quar, sent, conc] = await Promise.all([
        get("/api/insights/figures/quarantine-composition"),
        get("/api/insights/figures/sentiment-measurability"),
        get("/api/insights/figures/source-concentration"),
      ]);
      const block = (title, inner, d) =>
        `<div class="fig-block"><h3 class="fig-title">${esc(title)}</h3>${inner}` +
        (d && !d.__err ? figMeta(d) : "") + `</div>`;
      const errLine = (d) => `<div class="fig-empty">${esc(t("Could not load this figure."))}</div>`;

      // --- C2: tone measurability. Deliberately FIRST: it is the figure that makes
      // an existing gap visible, and on a multilingual corpus it is the largest one.
      let sentHtml;
      if (sent.__err) sentHtml = errLine(sent);
      else {
        const rows = [];
        for (const r of (sent.rows || [])) {
          // ooLangName, not a bare code: the shipped CLDR helper already renders the
          // full language name in the reader's own locale.
          const name = ooLangName(r.language, r.language);
          if (r.measured > 0) {
            rows.push({label: `${name} · ${t("measured")}`, n: r.measured, color: "var(--fig-1)",
                       title: t("A tone value was stored for these articles.")});
          }
          if (r.unmeasured > 0) {
            // The label is just the language: the hatch and the value's own "not
            // measured" prefix already state the condition, and saying it a third
            // time in the label crowded the row for no added information.
            rows.push({label: r.supported ? `${name} · ${t("no tone stored")}` : name,
                       n: r.unmeasured, hatched: !r.supported,
                       color: "var(--fig-3)",
                       title: r.supported
                         ? t("This language can be scored, but these articles carry no tone value.")
                         : t("The tone engine cannot read this language, so these articles were never scored.")});
          }
        }
        if (sent.untagged && sent.untagged.n) {
          rows.push({label: t("no asserted language"), n: sent.untagged.n, hatched: true,
                     title: t("These articles carry no language, which is the tone gate's own blind spot.")});
        }
        sentHtml = _figBars(rows, {
          title: t("Articles with and without a tone measurement, by language"),
          aria: t("Articles with and without a tone measurement, by language"),
          empty: t("No article carries a language yet."),
        }) + figGapKey();
      }

      // --- C1: quarantine composition
      let quarHtml;
      if (quar.__err) quarHtml = errLine(quar);
      else if (!(quar.rows || []).length) {
        quarHtml = figEmpty(t("Nothing in this corpus is quarantined."));
      } else {
        quarHtml = _figBars((quar.rows || []).map(r => ({
          label: (r.reason || t("reason not recorded")) +
            (r.criteria_version ? ` · ${r.criteria_version}` : ""),
          n: r.n, color: "var(--fig-3)",
        })), {
          title: t("Quarantined articles by the reason recorded"),
          aria: t("Quarantined articles by the reason recorded"),
        });
      }

      // --- C5: source concentration
      let concHtml;
      if (conc.__err) concHtml = errLine(conc);
      else {
        const g = conc.gini;
        // gini() returns null when undefined (fewer than two sources, or no
        // articles). A Gini of 0 means perfect EQUALITY, so printing 0 here would
        // state the opposite of "we cannot say".
        const gLine = g == null
          ? `<div class="hint">${esc(t("Gini is undefined for this set — it needs at least two sources with articles."))}</div>`
          : `<div class="hint"><strong>${esc(fmtNum(g, 3))}</strong> ${esc(t("Gini"))}` +
            (conc.top_share != null
              ? ` <span class="muted">· ${esc(OOI18N && OOI18N.tf
                  ? OOI18N.tf("top 3 sources hold {pct}% of articles",
                              {pct: fmtNum(conc.top_share * 100, 1)})
                  : "top 3 hold " + fmtNum(conc.top_share * 100, 1) + "%")}</span>`
              : "") + `</div>`;
        concHtml = _figLorenz(conc.curve, {
          aria: t("Lorenz curve of how unevenly the corpus draws on its sources"),
          empty: t("No source has stored an article yet."),
        }) + gLine;
      }

      host.innerHTML =
        block(t("Tone measurement by language"), sentHtml, sent) +
        block(t("Quarantine composition"), quarHtml, quar) +
        block(t("How evenly the corpus draws on its sources"), concHtml, conc) +
        // C4 is a FULL articles scan, so it stays behind an explicit click — never
        // loaded just because the subtab was opened.
        `<div class="fig-block"><h3 class="fig-title">${esc(t("Article length"))}</h3>` +
        `<div id="fig-length-host"><button class="secondary" id="fig-length-run">` +
        `${esc(t("Measure article lengths"))}</button>` +
        `<div class="hint muted">${esc(t("This reads every article row, so it runs only when you ask."))}</div>` +
        `</div></div>`;
      const runBtn = $("fig-length-run");
      if (runBtn) runBtn.addEventListener("click", renderArticleLengthFigure);
    }

    // C4 — the word-count distribution. Its own function because it is the one figure
    // here that costs a full scan, so it must be reachable only by a deliberate act.
    async function renderArticleLengthFigure() {
      const box = $("fig-length-host");
      if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      box.innerHTML = `<div class="muted">${esc(t("Measuring…"))}</div>`;
      let d;
      try { d = await api("/api/insights/figures/article-length"); }
      catch (e) { box.innerHTML = `<div class="fig-empty">${esc(t("Could not load this figure."))}</div>`; return; }
      // measurable === false means the set was EMPTY. The underlying report returns
      // all-None percentiles with an all-ZERO histogram for an empty set, which draws
      // as a flat row of bars — a fabricated "we measured, and found nothing".
      if (!d.measurable) {
        box.innerHTML = figEmpty(t("No article carries a word count in a space-separated language yet.")) +
          figMeta(d);
        return;
      }
      const ex = d.excluded_unsegmented || {};
      const rows = (d.buckets || []).map(b => ({label: b.label, n: b.n, color: "var(--fig-1)"}));
      box.innerHTML =
        _figBars(rows, {
          title: t("Articles by word-count range"),
          aria: t("Articles by word-count range"),
        }) +
        `<div class="hint muted">${esc(t("Ranges, not equal-width bins — compare one bar with another, not the shape."))}</div>` +
        `<div class="hint">${esc(OOI18N && OOI18N.tf
          ? OOI18N.tf("{scanned} articles scanned · {counted} had a word count · {excluded} excluded as not space-separated",
                      {scanned: fmtNum(d.scanned), counted: fmtNum(d.with_word_count), excluded: fmtNum(ex.n || 0)})
          : `${d.scanned} scanned · ${d.with_word_count} counted · ${ex.n || 0} excluded`)}</div>` +
        ((ex.languages || []).length
          ? `<div class="hint muted">${esc(t("Excluded languages"))}: ` +
            (ex.languages || []).map(l => esc(ooLangName(l, l))).join(", ") + `</div>`
          : "") +
        figMeta(d);
    }

    async function renderLibraryActivityGraphs() {
      const host = $("lib-activity-graphs");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const tiles = await Promise.all([
          _libGraphTile("articles_per_hour", LIB_DEFAULT_DAYS),
          _libGraphTile("sources", LIB_DEFAULT_DAYS),
          _libGraphTile("keywords", LIB_DEFAULT_DAYS),
          _libQualificationTile(LIB_DEFAULT_DAYS),
        ]);
        // The rhythm heatmap sits BESIDE the tiles, never instead of them (the
        // chart-beside-table rule): it reuses the articles_per_hour series
        // _libGraphTile has already fetched and stashed, so it costs no request.
        const rhythmSeries = ((_libGraphData.articles_per_hour || {}).series) || [];
        const rhythm = ingestRhythmSvg(rhythmSeries);
        // Per-language growth sits BESIDE the counters, never instead of them.
        // Its own fetch: it is the one series the /history metrics cannot express
        // (a list of series, not a single [{t,n}]).
        const lang = await _libLanguageTile(LIB_DEFAULT_DAYS);
        host.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:10px">${tiles.join("")}</div>`
          + `<div class="row" style="flex-wrap:wrap;gap:10px;margin-top:10px">${lang}</div>`
          + (rhythm ? `<h3 class="lib-sub">${esc(t("Ingest rhythm"))}</h3>` + rhythm : "");
        _libRenderQualChart(host);
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(e.message || e)}</div>`;
      }
    }
    function renderLibraryWikiGraphs() {
      return _renderLibGraphHost("lib-wiki-graphs", [
        ["wiki_pages", LIB_DEFAULT_DAYS], ["wiki_revisions", LIB_DEFAULT_DAYS],
      ]);
    }
    function renderLibraryLawGraphs() {
      return _renderLibGraphHost("lib-law-graphs", [
        ["law_documents", LIB_DEFAULT_DAYS], ["law_revisions", LIB_DEFAULT_DAYS],
      ]);
    }
    function enlargeLibMetric(metric) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _libGraphData[metric];
      if (!d || !Array.isArray(d.series)) return;   // defensive: nothing to enlarge
      const label = t(LIB_METRIC_LABEL_KEYS[metric] || metric);
      const caveat = d.recording_began_at
        ? t("Recording began at {x}.").replace("{x}", d.recording_began_at) : "";
      chartEnlarge(label, [{label, unit: label,
        points: d.series.map(p => ({t: p.t, v: p.n}))}], caveat);
    }

    async function loadDbStats() {
      const el = $("db-stats");
      try {
        const s = await api("/api/database/stats");
        const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
        const entries = Object.entries(s.counts || {}).filter(([k]) => !DB_STAT_HIDDEN_KEYS.has(k));
        const keys = entries.map(([k]) => k).join(",");
        if (DB_KEYS !== keys) {                       // (re)build grid with stable number nodes
          DB_KEYS = keys;
          el.innerHTML = entries.length
            ? entries.map(([k]) =>
                `<div class="stat"><div class="n" id="db-n-${k}" data-v="0">0</div><div class="k">${esc(t9(DB_STAT_LABELS[k] || k))}</div></div>`).join("")
            : '<div class="muted">No tables yet.</div>';
        }
        for (const [k, v] of entries) {
          const n = document.getElementById("db-n-" + k);
          if (n) animateCount(n, v);
        }
        // The DB file is ONE component of the whole footprint; once the Storage-footprint
        // panel has measured it, show the all-stores total here too so the number is honest
        // about being only the database (never implying it is the app's whole disk use).
        const _t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
        const gt = _sfCache && (_sfCache.totals || {}).grand_total_bytes;
        const foot = gt ? ` <span class="muted">· ${esc(_t("all stores"))} <strong>${esc(_fmtBytes(gt))}</strong> (${esc(_t("see Storage footprint below"))})</span>` : "";
        $("db-file").innerHTML = s.file
          ? `Backend <span class="pill">${esc(s.backend)}</span> · on disk ` +
            `<strong>${humanBytes(s.file.bytes)}</strong> ` +
            `<span class="muted">(${esc(s.file.path)})</span>` + foot
          : `Backend <span class="pill">${esc(s.backend)}</span> · ${esc(s.url_summary)}`;
      } catch (e) { el.innerHTML = `<div class="note err">Could not load stats: ${esc(e.message)}</div>`; DB_KEYS = null; }
    }

    // Live polling manager: each tab can register a refresh fn + interval; only
    // the active tab's poller runs, and only while the window is visible.
    const LIVE = {
      // Home self-updates while open: stats strip + status + briefing (the latter
      // re-renders only when generated_at changes). Replaces the old Refresh
      // button. Conservative cadence; stats are server-cached ~30 s.
      home:     {ms: 15000, fn: () => refreshHomeLive()},
      // Stats every tick; the coverage panel every 4th (it groups all sources,
      // cheap but no need for 4s cadence) — live data, so no Refresh button.
      // Only the VISIBLE Library view is polled (2026-08-01 ruling 9): refreshing a
      // subtab nobody is looking at would re-fetch the coverage map and re-walk the
      // counters behind the user's back, defeating the point of loading a view on
      // select. Each branch refreshes exactly the panels its own view shows.
      library:  {ms: 4000, fn: () => {
        if (_libView === "storage") loadDbStats();
        if ((++_covTick % 4) === 1) {
          if (_libView === "coverage") loadCoverage();
          if (_libView === "overview") renderLibraryOverview();
        }
      }},
      ingest:   {ms: 5000, fn: () => refreshSchedulerLive()},
      insights: {ms: 6000, fn: () => loadInsights()},
      wiki:     {ms: 6000, fn: () => refreshWikiLive()},
    };
    let _live = null;
    function startLive(name) {
      stopLive();
      const spec = LIVE[name];
      if (!spec) return;
      // Single-flight: never stack an identical poll while the previous one is still in
      // flight. Under 429 backpressure a poll (which awaits several api() calls, each of
      // which may itself be retrying) can outlast its interval; without this guard the
      // ticks pile up and add load exactly when the server is already saturated.
      // refreshHomeLive returns a promise for its whole awaited chain, so Home is covered.
      let inflight = false;
      const tick = async () => {
        if (inflight) return;
        inflight = true;
        try { await spec.fn(); } finally { inflight = false; }
      };
      tick();
      _live = {name, timer: setInterval(() => { if (!document.hidden) tick(); }, spec.ms)};
    }
    function stopLive() { if (_live) { clearInterval(_live.timer); _live = null; } }
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      const active = document.querySelector(".tab-page.active");
      if (active && !_live) startLive(active.id.replace("tab-", ""));
    });

    // Live refreshers that only touch STATUS/PROGRESS displays (never the config
    // inputs the user may be editing).
    async function refreshSchedulerLive() {
      try { renderSchedStatus(await api("/api/scheduler/status")); } catch (e) { /* keep last */ }
    }
    let _wikiStatusBuilt = false;
    function renderWikiStatus(s) {
      const el = $("wiki-status");
      if (!_wikiStatusBuilt) {
        _wikiStatusBuilt = true;
        el.innerHTML =
          `<span class="pill"><span id="wiki-n-watched" data-v="0">0</span>/` +
          `<span id="wiki-n-pages" data-v="0">0</span> pages watched</span> · ` +
          `<span id="wiki-n-rev" data-v="0">0</span> tracked edits · ` +
          `<span class="pill" id="wiki-flag-pill"><span id="wiki-n-flagged" data-v="0">0</span> flagged</span>`;
      }
      animateCount($("wiki-n-watched"), s.watched);
      animateCount($("wiki-n-pages"), s.pages);
      animateCount($("wiki-n-rev"), s.revisions);
      animateCount($("wiki-n-flagged"), s.flagged);
      $("wiki-flag-pill").className = "pill " + (s.flagged ? "warn" : "ok");
    }

    async function refreshWikiLive() {
      try { renderWikiStatus(await api("/api/wiki/status")); } catch (e) { /* keep last */ }
      loadWikiDumps();
    }

    // -- World coverage ----------------------------------------------------- //
    let COV_COUNTRIES = [];   // cached per-country rows for client-side filtering
    let COV_MISSING = [];     // [{code, name}] for the gap pills
    let _covTick = 0;         // slow-cadence counter for the library live poller
    let _covStamp = "";       // last payload fingerprint (skip repaint when unchanged)

    // Part-to-whole with more categories than a donut can honestly carry: sorted
    // horizontal bars, the replacement this project's OWN chart-decision framework
    // names (docs/research/dataviz/chart_decision_framework.md). Bar length on a
    // common scale beats angle/area for reading shares, and it degrades gracefully
    // to any number of rows. Same data contract and same honesty as ooDonut: real
    // total, real per-row counts, no score.
    function _ooShareBars(el, items, total, opts, t) {
      const max = items[0] ? items[0].value : 1;
      const rows = items.map((d) =>
        `<div style="display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.7">`
        + `<span style="flex:0 0 34%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"`
        + ` title="${esc(d.label)}">${esc(d.label)}</span>`
        + `<span style="flex:1;background:var(--panel3);border-radius:3px;height:9px;position:relative">`
        + `<span style="display:block;height:100%;border-radius:3px;background:var(--accent);`
        + `width:${Math.max(1, Math.round(d.value / max * 100))}%"></span></span>`
        + `<span class="muted" style="flex:0 0 auto">${esc(fmtNum(d.value))} · `
        + `${Math.round(d.value / total * 100)}%</span></div>`
      ).join("");
      el.innerHTML =
        `<div role="img" aria-label="${esc(opts.aria || "")}">`
        + `<div style="font-size:12px;margin-bottom:6px">${esc(fmtNum(total))} `
        + `${esc(opts.centerLabel || "")}</div>${rows}</div>`;
    }

    // Reusable self-contained SVG DONUT (no deps; like ooChart/ooMap) — categorical
    // proportions with a legend. data: [{label, value}] (labels already display-ready).
    // Stroke-dasharray on one circle per slice handles any slice count AND the single
    // full-ring case robustly. Honest: shows the real total + per-slice counts; no score.
    //
    // SLICE-COUNT GUARD (GUI audit 2026-07-28, finding V-4). The project's own
    // committed chart-decision framework says, for part-to-whole: "Pie/donut only
    // if <=4-5 slices, share labels shown, and precise comparison is not required;
    // otherwise bars" — and lists "many-slice pie" on its REJECT list. This
    // renderer had no guard and its only caller feeds it `unlocated.by_language`,
    // an UNBOUNDED language set: past ~5 slices the evenly-spaced hues stop being
    // distinguishable and angle-reading stops being reliable, which is exactly the
    // failure the framework rejects. Above the threshold we fall back to sorted
    // bars. NOTHING IS TRUNCATED -- every category is still shown, just in the
    // encoding that can carry it (the anti-capping rule: a display cap may never
    // silently drop data).
    const _DONUT_MAX_SLICES = 5;

    function ooDonut(host, data, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      const el = (typeof host === "string") ? document.getElementById(host) : host;
      if (!el) return;
      opts = opts || {};
      const items = (data || []).filter(d => d && d.value > 0).slice().sort((a, b) => b.value - a.value);
      const total = items.reduce((s, d) => s + d.value, 0);
      if (!items.length || total <= 0) {
        el.innerHTML = `<div class="muted">${esc(opts.empty || t("Nothing to chart."))}</div>`;
        return;
      }
      if (items.length > _DONUT_MAX_SLICES) { _ooShareBars(el, items, total, opts, t); return; }
      const size = opts.size || 184, cx = size / 2, cy = size / 2;
      const sw = size * 0.16, rMid = size * 0.42 - sw / 2;
      const C = 2 * Math.PI * rMid;
      const color = i => `hsl(${Math.round(i * 360 / items.length) % 360} 60% 55%)`;
      let acc = 0;
      const slices = items.map((d, i) => {
        const frac = d.value / total;
        const seg = `<circle cx="${cx}" cy="${cy}" r="${rMid.toFixed(2)}" fill="none" stroke="${color(i)}"`
          + ` stroke-width="${sw.toFixed(2)}" stroke-dasharray="${(frac * C).toFixed(2)} ${C.toFixed(2)}"`
          + ` stroke-dashoffset="${(-acc * C).toFixed(2)}"><title>${esc(d.label)}: ${esc(fmtNum(d.value))}`
          + `${opts.unit ? " " + esc(opts.unit) : ""} (${Math.round(frac * 100)}%)</title></circle>`;
        acc += frac;
        return seg;
      }).join("");
      const legend = items.map((d, i) =>
        `<div style="display:flex;align-items:center;gap:6px;font-size:12px;line-height:1.6">`
        + `<span style="width:10px;height:10px;border-radius:2px;background:${color(i)};flex:none"></span>`
        + `<span>${esc(d.label)}</span>`
        + `<span class="muted" style="margin-left:auto">${esc(fmtNum(d.value))} · ${Math.round(d.value / total * 100)}%</span></div>`
      ).join("");
      el.innerHTML =
        `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">`
        + `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(opts.aria || "")}" style="flex:none">`
        + `<g transform="rotate(-90 ${cx} ${cy})">${slices}</g>`
        + `<text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="${(size * 0.17).toFixed(0)}" font-weight="700" fill="currentColor">${esc(fmtNum(total))}</text>`
        + `<text x="${cx}" y="${(cy + size * 0.13).toFixed(0)}" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.6">${esc(opts.centerLabel || "")}</text>`
        + `</svg><div style="flex:1;min-width:160px;max-height:200px;overflow:auto">${legend}</div></div>`;
    }

    // Library "World coverage" map (field remark 10): per-country ARTICLE counts via the
    // shared ooMap choropleth + a donut of the 'no country' articles by language. Its own
    // stamp so a live poll only repaints when the data actually changes (no zoom-reset churn).
    let _covMapStamp = "";
    async function renderCoverageMap() {
      const mapHost = $("coverage-map");
      if (!mapHost) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      let d;
      try { d = await api("/api/insights/map-coverage"); }
      catch (e) { mapHost.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const stamp = JSON.stringify([d.by_country, d.unlocated]);
      if (stamp === _covMapStamp) return;   // live poll: unchanged, no repaint
      _covMapStamp = stamp;
      const values = {}, names = {}, points = [];
      (d.by_country || []).forEach(r => {
        names[r.country] = ooRegionName(r.country, r.name);
        const v = r.articles;
        if (v != null && isFinite(v) && v > 0) {
          values[r.country] = v;
          if (r.lat != null && r.lon != null) {
            points.push({ iso2: r.country, lat: r.lat, lon: r.lon, value: v, label: names[r.country] });
          }
        }
      });
      const unloc = (d.unlocated && d.unlocated.articles) || 0;
      ooMap(mapHost, {
        values, names, points, unit: t("articles"),
        valueLabel: (iso, v) => `${fmtNum(v)} ${t("articles")}`,
        // click a country -> filter the catalogue table below to it (ties the map to the table).
        onCountry: (code) => { const f = $("cov-filter"); if (f) { f.value = names[code] || code; renderCoverageTable(); } },
        aria: t("Articles collected per country."),
        method: t("Articles collected, grouped by each source's catalogued country (ISO-2). Counts only, no score."),
        caveat: t("Country is operator/catalogue-asserted; articles whose source has no country are counted but never placed on the map — see the language breakdown below.")
          + (unloc ? `  ${fmtNum(unloc)} ${t("with no country.")}` : ""),
      });
      // donut: the 'no country' articles by language (full names via ooLangName).
      const donutHost = $("coverage-unlocated");
      if (donutHost) {
        const byLang = (d.unlocated && d.unlocated.by_language) || {};
        const ddata = Object.keys(byLang).map(code => ({
          value: byLang[code], label: code ? ooLangName(code, code) : t("Unknown language"),
        })).filter(x => x.value > 0);
        if (!ddata.length) {
          donutHost.innerHTML = `<div class="muted">${esc(t("All collected articles have a country."))}</div>`;
        } else {
          const tot = ddata.reduce((s, x) => s + x.value, 0);
          donutHost.innerHTML =
            `<div class="hint" style="margin-bottom:6px">${esc(fmtNum(tot))} ${esc(t("articles with no country, by language"))}</div>`
            + `<div id="cov-donut-svg"></div>`;
          ooDonut("cov-donut-svg", ddata, { unit: t("articles"), centerLabel: t("articles"),
            aria: t("Articles with no country, by language.") });
        }
      }
    }

    async function loadCoverage() {
      renderCoverageMap();   // fire-and-forget the world map + unlocated donut (own stamp)
      const el = $("coverage-summary");
      if (!_covStamp) el.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const [c, d] = await Promise.all([
          api("/api/database/coverage"),
          api("/api/database/countries"),
        ]);
        const stamp = JSON.stringify([c, d.countries, d.missing]);
        if (stamp === _covStamp) return;   // live poll: nothing changed, no repaint
        _covStamp = stamp;
        el.innerHTML =
          `<div class="stat"><div class="n">${c.covered}/${c.total_countries}</div><div class="k">countries</div></div>` +
          `<div class="stat"><div class="n">${c.coverage_pct}%</div><div class="k">coverage</div></div>` +
          `<div class="stat"><div class="n">${c.missing_count}</div><div class="k">not covered</div></div>` +
          `<div class="stat"><div class="n">${(c.thin||[]).length}</div><div class="k">thin (&lt;${c.thin_threshold})</div></div>`;
        renderCoverageRegions(c);
        COV_COUNTRIES = d.countries || [];
        COV_MISSING = (d.missing || []).map(code =>
          ({code, name: (d.missing_names || {})[code] || code}));
        renderCoverageTable();
      } catch (e) {
        _covStamp = "";   // error rendered: force a repaint on the next good poll
        el.innerHTML = `<div class="note err">Coverage unavailable: ${esc(e.message)}</div>`;
      }
    }

    // Regional balance vs the configured floors (configs/catalog_targets.yml) —
    // the de-US-centring metric. Floors are labelled aspirations, never claims.
    // Sorted bars for "sources per region, against that region's floor".
    //
    // GUI audit 2026-07-28 finding V-2: this surface emitted a table and no
    // chart, yet the question it answers -- WHICH regions sit below their
    // floor -- is a length comparison against a target, which the project's
    // own chart-decision framework puts squarely in bar territory (position
    // on a common scale beats reading paired numbers out of a table).
    //
    // Added BESIDE the table, never replacing it (invariant #8 + the Desk
    // lesson: the table stays the precise, screen-readable, sortable record;
    // the chart is the glance). Honest by construction: real counts only, no
    // score; the floor is drawn as its own marked line so "below floor" is
    // visible rather than asserted; a region with no floor configured is
    // still plotted, just without a marker (never a fabricated target).
    function _regionFloorBars(regions) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const rows = (regions || []).filter(r => r && (r.sources > 0 || r.countries_total > 0));
      if (rows.length < 2) return "";          // one bar compares nothing
      rows.sort((a, b) => (b.sources || 0) - (a.sources || 0));
      // Scale to the largest of value-or-floor so a floor above every bar is
      // still on-canvas -- otherwise a badly-missed target would fall off the
      // right edge and read as "no floor".
      const max = Math.max(1, ...rows.map(r => Math.max(r.sources || 0, r.min_sources || 0)));
      const scale = (window.ooViz && ooViz.linearScale)
        ? ooViz.linearScale(0, max, 0, 100)
        : (v => (v / max) * 100);
      const bars = rows.map(r => {
        const below = r.sources_met === false;
        const w = Math.max(0.5, scale(r.sources || 0));
        const floorPct = (r.min_sources != null) ? scale(r.min_sources) : null;
        const marker = floorPct == null ? "" :
          `<span title="${esc(t("floor"))}: ${esc(String(r.min_sources))}" style="position:absolute;`
          + `left:${floorPct.toFixed(1)}%;top:-2px;bottom:-2px;width:2px;background:var(--fg);opacity:.55"></span>`;
        return `<div style="display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.8">`
          + `<span style="flex:0 0 30%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.region)}</span>`
          + `<span style="flex:1;position:relative;background:var(--panel3);border-radius:3px;height:10px">`
          + `<span style="display:block;height:100%;border-radius:3px;width:${w.toFixed(1)}%;`
          + `background:${below ? "var(--warn)" : "var(--accent)"}"></span>${marker}</span>`
          + `<span class="muted" style="flex:0 0 auto">${esc(String(r.sources || 0))}`
          + `${r.min_sources != null ? " / " + esc(String(r.min_sources)) : ""}</span></div>`;
      }).join("");
      return `<div style="margin-top:8px" role="img" aria-label="${esc(t("Sources per region against each region's floor."))}">`
        + bars
        + `<div class="hint" style="margin-top:4px">${esc(t("Bar = sources collected; the vertical mark is that region's floor. Counts only, no score."))}</div></div>`;
    }

    function renderCoverageRegions(c) {
      const reg = c.regional;
      const host = $("coverage-regions");
      if (!reg || !(reg.regions || []).length) { host.innerHTML = ""; return; }
      const mark = ok => ok === null ? '<span class="muted">—</span>'
        : ok ? '<span class="pill ok">ok</span>' : '<span class="pill warn">below floor</span>';
      const rows = reg.regions.filter(r => r.countries_total > 0 || r.sources > 0).map(r =>
        `<tr><td>${esc(r.region)}</td>` +
        `<td>${r.sources}${r.min_sources != null ? ` <span class="muted">/ ${r.min_sources}</span>` : ""} ${mark(r.sources_met)}</td>` +
        `<td>${r.countries_covered}/${r.countries_total}${r.min_countries != null ? ` <span class="muted">/ ${r.min_countries}</span>` : ""} ${mark(r.countries_met)}</td></tr>`
      ).join("");
      const tc = reg.top_country || {};
      const tcName = (c.names || {})[tc.code] || tc.code || "—";
      const over = tc.max_share_pct != null && tc.share_pct > tc.max_share_pct;
      const located = reg.located_share_pct != null
        ? ` · ${reg.located_share_pct}% of sources carry a country` +
          (reg.min_located_share_pct != null ? ` <span class="muted">(floor ${reg.min_located_share_pct}%)</span>` : "")
        : "";
      host.innerHTML =
        `<strong>Regional balance</strong> <span class="muted">(floors are working targets from configs/catalog_targets.yml)</span>` +
        _regionFloorBars(reg.regions) +
        `<div style="overflow:auto;margin-top:6px"><table>` +
        `<tr><th>Region</th><th>Sources / floor</th><th>Countries / floor</th></tr>${rows}</table></div>` +
        `<div style="margin-top:6px">Top country: <strong>${esc(tcName)}</strong> — ${tc.sources} sources, ` +
        `${tc.share_pct}% of located${tc.max_share_pct != null ?
          ` <span class="pill ${over ? "warn" : "ok"}">${over ? "above" : "within"} the ${tc.max_share_pct}% guard</span>` : ""}` +
        `${located}</div>`;
    }

    function renderCoverageTable() {
      const q = ($("cov-filter").value || "").trim().toLowerCase();
      const rows = COV_COUNTRIES.filter(c => {
        if (!q) return true;
        if (c.code.includes(q)) return true;
        if ((c.name || "").toLowerCase().includes(q)) return true;
        return (c.top_tags || []).some(([t]) => t.toLowerCase().includes(q));
      });
      const t = $("coverage-table");
      t.innerHTML = "<tr><th>Country</th><th>Region</th><th>Sources</th><th>Enabled</th><th>Topic keywords (source tags)</th></tr>" +
        (rows.length ? rows.map(c => {
          const label = c.name && c.name !== c.code
            ? `${esc(c.name)} <span class="muted">${esc(c.code.toUpperCase())}</span>`
            : esc(c.code);
          const tags = (c.top_tags || []).map(([t, n]) =>
            `<span class="pill" style="cursor:pointer" title="show ${esc(t)} sources in ${esc(c.name || c.code)}"
                onclick="openSourcesForKeyword(${esc(JSON.stringify(c.code))}, ${esc(JSON.stringify(t))})">${esc(t)} ${n}</span>`
          ).join(" ") || '<span class="muted">—</span>';
          const codeCell = `<strong style="cursor:pointer" title="show sources in ${esc(c.name || c.code)}"
                onclick="openSourcesForKeyword(${esc(JSON.stringify(c.code))}, null)">${label}</strong>`;
          return `<tr><td>${codeCell}</td><td class="muted">${esc(c.region || "—")}</td><td>${c.sources}</td>
                  <td class="muted">${c.enabled}</td><td>${tags}</td></tr>`;
        }).join("") : `<tr><td colspan="5" class="muted">No matching countries.</td></tr>`);
      // Not-covered list (same filter, matched on name or code).
      const miss = COV_MISSING.filter(x =>
        !q || x.code.includes(q) || x.name.toLowerCase().includes(q));
      $("coverage-gaps").innerHTML = miss.length
        ? `<strong>Not covered (${miss.length})</strong>: ` +
          miss.slice(0, 120).map(x =>
            `<span class="pill" title="${esc(x.code.toUpperCase())}">${esc(x.name)}</span>`).join(" ") +
          (miss.length > 120 ? ` <span class="muted">…and ${miss.length - 120} more</span>` : "")
        : `<span class="pill ok">every listed country has at least one source</span>`;
    }

    // -- Sources: ingest dropdown + add + seed ------------------------------ //
    async function loadSources() {
      let sources = [];
      try { sources = await api("/api/sources"); } catch (e) { toast("Could not load sources: " + e.message, "err"); }
      const sel = $("ing-source");
      sel.innerHTML = sources.filter(s => s.rss_url).map(s =>
        `<option value="${s.id}">${esc(s.name)}</option>`).join("")
        || '<option value="">(no sources with an RSS feed)</option>';
      loadUnmanagedLanguages();
    }

    // Surface how many enabled sources are in languages the keyword engine cannot
    // analyse (no stoplist / unsegmented) — junk that pollutes analytics + slows the
    // app. The panel only appears when there's something to disable.
    async function loadUnmanagedLanguages() {
      const panel = $("unmanaged-lang-panel"); if (!panel) return;
      let r; try { r = await api("/api/sources/unmanaged-languages"); } catch (e) { panel.style.display = "none"; return; }
      if (!r || !r.enabled_unmanaged) { panel.style.display = "none"; return; }
      const langs = Object.entries(r.by_language).map(([k, n]) => `${esc(k)} (${n})`).join(", ");
      $("unmanaged-lang-summary").innerHTML =
        `<strong>${r.enabled_unmanaged}</strong> enabled source(s) in languages we can't analyse yet: ${langs}.`;
      panel.style.display = "";
    }

    async function disableUnmanagedLanguages() {
      const btn = $("unmanaged-lang-btn"); if (btn) btn.disabled = true;
      try {
        const r = await api("/api/sources/disable-unmanaged-languages", {method: "POST"});
        toast(`Disabled ${r.disabled} source(s) in unmanaged languages (kept — re-enable any time).`);
        loadUnmanagedLanguages();
        if (typeof loadManagedSources === "function") loadManagedSources();
      } catch (e) { toast(e.message, "err"); }
      finally { if (btn) btn.disabled = false; }
    }

    async function seedDefaults() {
      try {
        const r = await api("/api/sources/seed-defaults", {method: "POST"});
        toast(`Seeded ${r.seeded.created} new source(s) (${r.seeded.skipped} already present).`);
        loadSources(); loadManagedSources(); loadDbStats(); loadCoverage();
      } catch (e) { toast(_failMsg("Seed failed: {error}", e), "err"); }
    }

    async function addSource() {
      const body = {
        name: $("s-name").value.trim(),
        domain: $("s-domain").value.trim(),
        rss_url: $("s-rss").value.trim() || null,
        tags: $("s-tags").value.trim(),
      };
      if (!body.name || !body.domain) { toast("Name and domain are required.", "err"); return; }
      try {
        await api("/api/sources/", {method: "POST", body: JSON.stringify(body)});
        toast("Source added.");
        ["s-name","s-domain","s-rss","s-tags"].forEach(id => $(id).value = "");
        loadSources(); loadManagedSources(); loadDbStats();
      } catch (e) { toast(_failMsg("Add failed: {error}", e), "err"); }
    }

    // -- Sources: management table ------------------------------------------ //
    // Source-management list state: filters + sort + paging.
    const SRC = {offset: 0, limit: 50, sort: "name", order: "asc"};

    // Multi-select dropdown filters (#23): each <details class="msel"> is a checklist.
    // Within a filter the checked values are OR'd; across filters AND'd; tags add an
    // any|all toggle. Read only the checklist's own checkboxes (NOT the tag-mode box).
    function mselValues(id) {
      const det = $(id); if (!det) return [];
      const list = det.querySelector(".msel-list");
      return list ? [...list.querySelectorAll("input:checked")].map(c => c.value) : [];
    }
    function updateMselSummary(id) {
      const det = $(id); if (!det) return;
      const sum = det.querySelector("summary"); if (!sum) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const v = mselValues(id);
      sum.textContent = v.length === 0 ? t("Any") : (v.length === 1 ? v[0] : v.length + " " + t("selected"));
    }
    async function loadSrcFacets() {
      let f; try { f = await api("/api/sources/facets"); } catch (e) { return; }
      const fill = (id, rows, labeler) => {
        const det = $(id); if (!det) return;
        const list = det.querySelector(".msel-list"); if (!list) return;
        list.innerHTML = (rows || []).length
          ? rows.map(x => `<label class="msel-opt"><input type="checkbox" value="${esc(x.key)}" onchange="srcMselChanged('${id}')"> ${esc(labeler ? labeler(x.key) : x.key)} <span class="muted">·${x.n}</span></label>`).join("")
          : `<div class="muted" style="padding:4px">—</div>`;
      };
      fill("src-msel-language", f.languages, k => (typeof ooLangName === "function" ? ooLangName(k, k) : k));
      fill("src-msel-country", f.countries, k => (typeof ooRegionName === "function" ? ooRegionName(k, k) : k));
      fill("src-msel-source_type", f.types);
      fill("src-msel-tag", f.tags);
      ["src-msel-language", "src-msel-country", "src-msel-source_type", "src-msel-tag"].forEach(updateMselSummary);
    }
    function srcMselChanged(id) { updateMselSummary(id); applySrcFilters(); }

    function srcQuery() {
      const p = new URLSearchParams();
      const q = $("src-search").value.trim(); if (q) p.set("q", q);
      const lang = mselValues("src-msel-language"); if (lang.length) p.set("language", lang.join(","));
      const country = mselValues("src-msel-country"); if (country.length) p.set("country", country.join(","));
      const types = mselValues("src-msel-source_type"); if (types.length) p.set("source_type", types.join(","));
      const tags = mselValues("src-msel-tag");
      if (tags.length) { p.set("tag", tags.join(",")); if ($("src-tag-all") && $("src-tag-all").checked) p.set("tag_mode", "all"); }
      const en = $("src-enabled").value; if (en) p.set("enabled", en);
      p.set("sort", SRC.sort); p.set("order", SRC.order);
      p.set("limit", SRC.limit); p.set("offset", SRC.offset);
      return p;
    }

    function applySrcFilters() { SRC.offset = 0; loadManagedSources(); }
    function clearSrcFilters() {
      $("src-search").value = "";
      ["src-msel-language", "src-msel-country", "src-msel-source_type", "src-msel-tag"].forEach(id => {
        const det = $(id); if (det) det.querySelectorAll(".msel-list input").forEach(c => { c.checked = false; });
        updateMselSummary(id);
      });
      if ($("src-tag-all")) $("src-tag-all").checked = false;
      $("src-enabled").value = ""; SRC.offset = 0; loadManagedSources();
    }
    function srcPage(dir) {
      const next = SRC.offset + dir * SRC.limit;
      if (next < 0) return;
      SRC.offset = next; loadManagedSources();
    }
    function setSrcSort(col) {
      if (SRC.sort === col) SRC.order = (SRC.order === "asc" ? "desc" : "asc");
      else { SRC.sort = col; SRC.order = "asc"; }
      SRC.offset = 0; loadManagedSources();
    }
    function srcTh(label, col) {
      const arrow = SRC.sort === col ? (SRC.order === "asc" ? " ▲" : " ▼") : "";
      return `<th style="cursor:pointer" onclick="setSrcSort('${col}')">${label}${arrow}</th>`;
    }

    async function loadManagedSources() {
      const t = $("src-table");
      try {
        const d = await api("/api/catalog/sources?" + srcQuery().toString());
        const shownFrom = d.total ? SRC.offset + 1 : 0;
        const shownTo = Math.min(SRC.offset + SRC.limit, d.total);
        $("src-meta").textContent = `${d.total} source(s)` + (d.total ? ` · showing ${shownFrom}–${shownTo}` : "");
        $("src-page").textContent = `page ${Math.floor(SRC.offset / SRC.limit) + 1} of ${Math.max(1, Math.ceil(d.total / SRC.limit))}`;
        t.innerHTML = "<tr>" + srcTh("Name","name") + srcTh("Domain","domain") + srcTh("Type","source_type") +
          srcTh("Country","country") + srcTh("Lang","language") + srcTh("Pri","priority") +
          srcTh("Articles","articles") + "<th>Enabled</th><th></th></tr>" +
          (d.sources.length ? d.sources.map(s => sourceRow(s)).join("")
            : `<tr><td colspan="9" class="muted">No sources match. Adjust filters, add one, or seed the starter set.</td></tr>`);
      } catch (e) { toast("Could not load sources: " + e.message, "err"); }
    }

    function sourceRow(s) {
      const tags = (s.tags || []).map(x =>
        `<span class="pill" style="cursor:pointer" title="filter by this tag" onclick="srcFilterTag(${esc(JSON.stringify(x))})">${esc(x)}</span>`).join(" ");
      const prio = [1,2,3].map(p =>
        `<option value="${p}" ${s.priority===p?"selected":""}>${p}</option>`).join("");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      return `<tr>
        <td>${esc(s.name)}<div class="muted" style="font-size:12px">${tags}</div></td>
        <td>${esc(s.domain)}${s.rss_url?' <span class="pill ok" title="has RSS feed">rss</span>':''}</td>
        <td class="muted">${esc(s.source_type || "—")}</td>
        <td class="muted" title="${esc((s.country || "").toUpperCase())}">${esc(s.country ? ooRegionName(s.country, s.country_name) : (s.country_name || "—"))}</td>
        <td class="muted" title="${esc(s.language || "")}">${esc(s.language ? ooLangName(s.language, s.language) : "—")}</td>
        <td><select class="tiny" style="width:auto;padding:3px"
              onchange="updateSource(${s.id},{priority:Number(this.value)})">${prio}</select></td>
        <td class="muted">${s.article_count!=null?s.article_count:'—'}</td>
        <td><input type="checkbox" style="width:auto" ${s.enabled?"checked":""}
              onchange="updateSource(${s.id},{enabled:this.checked})"></td>
        <td><button class="tiny ghost" onclick="toggleSourceTrail(${s.id})" title="${esc(t("Discovery"))}">${esc(t("Trail"))}</button>
        <button class="tiny ghost" onclick="qualifyAssist(${s.id}, this)" title="${esc(t("Ask the local model whether this source's stored articles read as articles or as navigation soup. A PROPOSAL to review beside the auditor's own evidence — it never changes this source's status or tags."))}">${esc(t("AI check"))}</button>
        <button class="tiny danger" onclick="deleteSource(${s.id}, ${esc(JSON.stringify(s.name))})">Delete</button></td>
      </tr>
      <tr id="src-trail-${s.id}" style="display:none"><td colspan="9"></td></tr>`;
    }

    // E-S5 (2026-08-01): the qualification ASSIST finally has a home. It has existed
    // since B7.2 with no UI trigger at all — a propose-only classifier nobody could
    // reach, which is a dead end rather than a feature. It stays propose-only: the
    // verdict lands in a dated artifact for review BESIDE the auditor's own evidence,
    // and Source.status / Source.tags are never touched by it.
    async function qualifyAssist(sourceId, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const row = document.getElementById("src-trail-" + sourceId);
      if (btn) { btn.disabled = true; btn.textContent = t("Checking…"); }
      try {
        const r = await api("/api/diagnostics/qualification-assist/run",
          {method: "POST", body: JSON.stringify({source_id: sourceId})});
        // Read against the module's REAL keys (article_count / junk_count /
        // unparseable_count / canary), not an assumed {counts: …} shape.
        const msg = `${t("AI check")}: ${r.checked != null ? r.checked : "?"} ${t("checked")} — `
          + `${r.article_count != null ? r.article_count : "?"} ${t("read as articles")}, `
          + `${r.junk_count != null ? r.junk_count : "?"} ${t("as navigation soup")}, `
          + `${r.unparseable_count != null ? r.unparseable_count : "?"} ${t("unreadable")}`
          + ` — ${t("a proposal only; nothing about this source was changed.")}`;
        // A failed canary means the run itself is untrustworthy, which matters more
        // than any of its numbers — so it is stated first, not buried.
        const bad = r.canary && r.canary.ok === false;
        if (row) {
          row.style.display = "";
          row.firstElementChild.innerHTML =
            (bad ? `<div class="card-caveat">${esc(t("The canary check FAILED — treat this run's numbers as unreliable."))}</div>` : "")
            + `<div class="small">${esc(msg)}</div>`;
        } else if (typeof toast === "function") { toast(msg); }
      } catch (e) {
        if (typeof toast === "function") toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      }
      if (btn) { btn.disabled = false; btn.textContent = t("AI check"); }
    }

    // -- Discovery-trail / qualified-citations panel (2026-07-20 ruling, items 1+2) -- //
    // Per-source provenance (where it was discovered + the citing trail) and the
    // qualified-citations tally, expandable inline in the Sources management row.
    // Reuses the row's own table (no new UI paradigm); the qualification status
    // (L1's Source.status) is surfaced here too, since this panel is exactly where
    // "is this admitted yet" belongs.
    const _srcTrailData = {};   // {sourceId: {qualified:[], disqualified:[], pending:[], never_registered:[]}}
    async function toggleSourceTrail(id) {
      const row = $("src-trail-" + id); if (!row) return;
      if (row.style.display !== "none") { row.style.display = "none"; return; }
      row.style.display = "";
      const cell = row.querySelector("td");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      cell.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const [prov, tally] = await Promise.all([
          api(`/api/sources/${id}/provenance`),
          api(`/api/sources/${id}/citation-tally`),
        ]);
        // Every class -- including never_registered/filtered -- keeps its own dict
        // shape from the API (domain + sample_article_ids, +source_id/name when
        // matched), so the drill list always matches the chip's own count.
        _srcTrailData[id] = {
          qualified: tally.qualified || [], disqualified: tally.disqualified || [],
          pending: tally.pending || [], never_registered: tally.never_registered || [],
        };
        cell.innerHTML = _srcTrailHtml(id, prov, tally);
      } catch (e) { cell.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    function _srcTrailHtml(id, prov, tally) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const qs = prov.qualification_status || "unqualified";
      const qsLabel = qs === "unqualified" ? t("pending") : t(qs);
      const qsClass = qs === "qualified" ? "ok" : (qs === "disqualified" ? "err" : "");
      let html = `<div><span class="pill ${qsClass}">${esc(qsLabel)}</span></div>`;
      html += `<div style="margin-top:6px"><strong>${esc(t("Discovery"))}:</strong> `
        + `${esc(prov.channel || "—")} <span class="muted">— ${esc(prov.detail || "")}</span></div>`;
      if (prov.citing_trail) {
        const ct = prov.citing_trail;
        const citerLink = ct.citing_source_domain
          ? ` (<a href="#" onclick="srcJumpToDomain(${esc(JSON.stringify(ct.citing_source_domain))});return false">${esc(ct.citing_source_name || ct.citing_source_domain)}</a>)`
          : (ct.citing_source_name ? ` (${esc(ct.citing_source_name)})` : "");
        html += `<div class="muted" style="margin-top:2px">${esc(t("First cited by"))}: `
          + `<a href="/api/articles/${ct.article_id}/view" target="_blank" rel="noopener">${esc(ct.article_title || ("#" + ct.article_id))}</a>`
          + citerLink + "</div>";
      }
      // Four DRILLABLE classes (qualified/disqualified/pending/never-registered) --
      // each chip's number is exactly the length of the list it expands to (never a
      // rolled-up total that the drill can't account for). The filtered classes
      // (commerce/social/infrastructure -- guardrail b's "tallied separately", NOT
      // folded into never-registered) get their own always-visible, non-drilling line.
      const classes = [
        ["qualified", tally.qualified || []],
        ["disqualified", tally.disqualified || []],
        ["pending", tally.pending || []],
        ["never_registered", tally.never_registered || []],
      ];
      const chips = classes.map(([k, arr]) => {
        const label = k === "never_registered" ? t("never-registered") : t(k);
        return `<button class="tiny ghost" onclick="_srcTrailToggleClass(${id},'${k}')">${esc(label)}: ${arr.length}</button>`;
      }).join(" ");
      html += `<div style="margin-top:8px">${chips}</div>`;
      html += `<div id="src-trail-cls-${id}" class="muted" style="display:none;margin:4px 0;font-size:.85em"></div>`;
      const c = tally.counts || {};
      html += `<div class="muted" style="font-size:.82em;margin-top:4px">`
        + `filtered (excluded from the funnel, not guilt either way): `
        + `commerce ${c.filtered_commerce || 0} · social ${c.filtered_social || 0} · infrastructure ${c.filtered_infrastructure || 0}</div>`;
      html += `<div class="muted" style="font-size:.82em;margin-top:2px">${esc(tally.caveat || "")}</div>`;
      return html;
    }
    function _srcTrailToggleClass(id, cls) {
      const host = $("src-trail-cls-" + id); if (!host) return;
      const arr = (_srcTrailData[id] && _srcTrailData[id][cls]) || [];
      host.style.display = "";
      host.innerHTML = arr.length
        ? arr.map(d => {
            const jump = `<a href="#" onclick="srcJumpToDomain(${esc(JSON.stringify(d.domain))});return false">${esc(d.domain)}</a>`;
            // "the sources' sources" grammar: also link to THIS source's own
            // citing articles for that domain, not just the domain's own row.
            const ids = d.sample_article_ids || [];
            const artsLink = ids.length
              ? ` <a href="#" onclick="openAnalysisForIds(${esc(JSON.stringify(ids))}, ${esc(JSON.stringify(d.domain))});return false" title="Open the articles that cite this domain">↗</a>`
              : "";
            return jump + artsLink;
          }).join(", ")
        : `<span class="muted">—</span>`;
    }
    // Jump to a cited domain's OWN management row (the drill's "linking to that
    // source's own management row" -- the pending/qualified/disqualified classes'
    // domains ARE sources; never_registered domains simply won't match anything).
    function srcJumpToDomain(domain) {
      $("src-search").value = domain;
      applySrcFilters();
    }

    // Check one option in a multi-select checklist by value (used by tag pills + the
    // coverage→sources jump). If the facets list hasn't loaded the value yet, no-op.
    function srcMselCheck(id, value) {
      const det = $(id); if (!det) return false;
      const cb = [...det.querySelectorAll(".msel-list input")].find(c => c.value === value);
      if (cb) { cb.checked = true; updateMselSummary(id); return true; }
      return false;
    }
    function srcFilterTag(tag) { srcMselCheck("src-msel-tag", tag); applySrcFilters(); }

    // Jump from the Database coverage view to the matching sources.
    function openSourcesForKeyword(code, tag) {
      clearSrcFilters();
      showTab("sources");
      // Facets fill on tab open; wait a tick so the checkboxes exist, then check them.
      loadSrcFacets().then(() => {
        if (code && code !== "(none)") srcMselCheck("src-msel-country", code);
        if (tag) srcMselCheck("src-msel-tag", tag);
        applySrcFilters();
      });
    }

    async function updateSource(id, body) {
      try { await api("/api/sources/" + id, {method: "PUT", body: JSON.stringify(body)});
        toast("Source updated."); }
      catch (e) { toast(_failMsg("Update failed: {error}", e), "err"); loadManagedSources(); }
    }

    async function deleteSource(id, name) {
      if (!confirm(`Delete source "${name}"? This also removes its stored articles.`)) return;
      try { await api("/api/sources/" + id, {method: "DELETE"});
        toast("Source deleted."); loadManagedSources(); loadSources(); loadDbStats(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    async function importSources() {
      const f = $("imp-file").files[0];
      if (!f) { toast("Choose a CSV file first.", "err"); return; }
      $("imp-result").textContent = "Importing…";
      try {
        const fd = new FormData(); fd.append("file", f);
        const res = await fetch("/api/catalog/import", {method: "POST", body: fd});
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || res.statusText);
        const errs = (d.parse_errors || []).concat(d.errors || []);
        $("imp-result").innerHTML =
          `<span class="pill ok">imported</span> created ${d.created}, updated ${d.updated}, ` +
          `skipped ${d.skipped}.` +
          (errs.length ? ` <span class="muted">First issues: ${errs.slice(0,5).map(esc).join("; ")}</span>` : "");
        toast(`Import: +${d.created} new, ${d.updated} updated.`);
        loadManagedSources(); loadSources(); loadDbStats(); loadCoverage();
      } catch (e) { $("imp-result").textContent = ""; toast(_failMsg("Import failed: {error}", e), "err"); }
    }

    function tally(t) {
      return Object.entries(t).filter(([k,v]) => v > 0)
        .map(([k,v]) => `${esc(k)}: ${v}`).join(", ") || "nothing new";
    }

    async function ingestSource() {
      const id = $("ing-source").value;
      if (!id) { toast("No RSS source selected.", "err"); return; }
      $("ingest-result").textContent = "Fetching feed… (rate-limited, may take a moment)";
      try {
        const r = await api(`/api/sources/${id}/ingest`, {method: "POST"});
        $("ingest-result").textContent = "Feed result — " + tally(r.tally);
        toast("Ingest complete."); doSearch();
      } catch (e) { $("ingest-result").textContent = ""; toast(_failMsg("Ingest failed: {error}", e), "err"); }
    }

    async function ingestUrl() {
      const url = $("ing-url").value.trim();
      const id = $("ing-source").value;
      if (!url) { toast("Enter a URL.", "err"); return; }
      if (!id) { toast("Select a source to attribute it to.", "err"); return; }
      $("ingest-result").textContent = "Fetching…";
      try {
        const r = await api("/api/ingest", {method: "POST",
          body: JSON.stringify({source_id: Number(id), url})});
        $("ingest-result").innerHTML = `Result: <span class="pill ${r.result==='stored'?'ok':'warn'}">${esc(r.result)}</span>` +
          (r.detail ? ` — ${esc(r.detail)}` : "");
        if (r.result === "stored") { $("ing-url").value = ""; doSearch(); }
      } catch (e) { $("ingest-result").textContent = ""; toast(_failMsg("Ingest failed: {error}", e), "err"); }
    }

    // -- Batch ingest picker ------------------------------------------------ //
    const BI = { sources: [], selected: new Set() };

    async function loadBatchPicker() {
      try {
        BI.sources = await api("/api/sources/?limit=1000");
        BI.selected = new Set();
      } catch (e) { BI.sources = []; }
      renderBatchPicker();
    }

    function _biFiltered() {
      const q = ($("bi-search").value || "").trim().toLowerCase();
      const lang = ($("bi-lang").value || "").trim().toLowerCase();
      const country = ($("bi-country").value || "").trim().toLowerCase();
      const type = ($("bi-type").value || "").trim().toLowerCase();
      const en = $("bi-enabled").value;
      return BI.sources.filter(s => {
        if (q && !((s.name||"").toLowerCase().includes(q) || (s.domain||"").toLowerCase().includes(q))) return false;
        if (lang && (s.language||"").toLowerCase() !== lang) return false;
        if (country && (s.country||"").toLowerCase() !== country) return false;
        if (type && !(s.source_type||"").toLowerCase().includes(type)) return false;
        if (en === "1" && !s.enabled) return false;
        if (en === "0" && s.enabled) return false;
        return true;
      });
    }

    function renderBatchPicker() {
      const list = $("bi-list"); if (!list) return;
      const rows = _biFiltered();
      if (!rows.length) { list.innerHTML = '<div class="muted">No sources match these filters.</div>'; }
      else {
        list.innerHTML = rows.map(s => {
          const feed = !!s.rss_url;
          const meta = [s.language ? ooLangName(s.language, s.language) : null,
                        s.country ? ooRegionName(s.country, s.country) : null,
                        s.source_type].filter(Boolean).map(esc).join(" · ");
          return `<label class="bi-row${feed ? "" : " bi-nofeed"}" title="${feed ? esc(s.rss_url) : "no RSS feed — cannot batch-fetch"}">
            <input type="checkbox" ${feed ? "" : "disabled"} ${BI.selected.has(s.id) ? "checked" : ""}
              onchange="batchToggle(${s.id}, this.checked)">
            <span class="bi-name">${esc(s.name)}</span>
            <span class="bi-meta muted">${meta}${feed ? "" : " · no feed"}${s.enabled ? "" : " · disabled"}</span></label>`;
        }).join("");
      }
      const ingestable = rows.filter(s => s.rss_url).length;
      $("bi-count").textContent = `${BI.selected.size} selected · ${ingestable} feed-bearing of ${rows.length} shown`;
    }

    function batchToggle(id, on) { on ? BI.selected.add(id) : BI.selected.delete(id); renderBatchPicker(); }

    function batchSelectAll(on) {
      const rows = _biFiltered().filter(s => s.rss_url);
      if (on) rows.forEach(s => BI.selected.add(s.id));
      else rows.forEach(s => BI.selected.delete(s.id));
      renderBatchPicker();
    }

    async function ingestBatch(btn) {
      const ids = [...BI.selected];
      if (!ids.length) { toast("Select at least one source with a feed.", "err"); return; }
      btn.disabled = true;
      $("bi-status").textContent = `Fetching ${ids.length} feed(s)… (ethical & rate-limited; may take a while)`;
      $("bi-results").innerHTML = "";
      try {
        const r = await api("/api/sources/ingest-batch", {method: "POST", body: JSON.stringify({source_ids: ids})});
        $("bi-status").textContent = `Done: ${r.ingested}/${r.requested} fetched · ${tally(r.aggregate)}`;
        $("bi-results").innerHTML = `<table class="bi-res"><tr><th>Source</th><th>Result</th></tr>` +
          r.results.map(x => `<tr><td>${esc(x.source || ("#" + x.source_id))}</td>` +
            `<td>${x.status === "ok" ? tally(x.tally)
              : `<span class="pill warn">${esc(x.status)}</span>${x.detail ? " " + esc(x.detail) : ""}`}</td></tr>`).join("") +
          `</table>`;
        toast("Batch ingest complete."); doSearch();
      } catch (e) { $("bi-status").textContent = ""; toast(_failMsg("Batch ingest failed: {error}", e), "err"); }
      finally { btn.disabled = false; }
    }

    // -- Scheduler ---------------------------------------------------------- //
    function toggleCrawlFields() {
      $("crawl-fields").style.display = $("sch-mode").value === "crawl" ? "flex" : "none";
    }

    // Timezone-proof: the backend reports UTC; the browser knows the operator's
    // zone. Show a relative time ("in ~N min") and keep the exact local moment
    // in the tooltip (maintainer ruling 2026-06-10: no naked zone-less clock).
    function fmtRelative(iso) {
      const d = new Date(iso); if (isNaN(d)) return "";
      const mins = Math.round((d.getTime() - Date.now()) / 60000);
      if (mins <= 0) return "any moment now";
      if (mins < 60) return `in ~${mins} min`;
      const h = Math.floor(mins / 60), m = mins % 60;
      return `in ~${h} h${m ? ` ${m} min` : ""}`;
    }
    // Honest PAST relative time ("2 h ago") -- fmtRelative above is future-oriented
    // ("in ~X min") and reads wrong applied to a past timestamp.
    function fmtAgo(iso) {
      const t = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      const d = new Date(iso); if (isNaN(d)) return "";
      const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
      if (mins < 1) return t("just now", {});
      if (mins < 60) return t("{n} min ago", { n: mins });
      const h = Math.floor(mins / 60);
      if (h < 24) return t("{n} h ago", { n: h });
      return t("{n} d ago", { n: Math.floor(h / 24) });
    }
    function fmtLocal(iso) {
      return fmtDateTime(iso);   // app language + full month (not the browser locale)
    }
    function renderSchedStatus(st) {
      if (typeof st.online === "boolean") _paintNetwork(st.online);  // repaint NOW, not at the next poll
      setBackgroundActivity(st.active ? "Collecting…" : null);
      const pill = st.running
        ? (st.active ? '<span class="pill ok">running — scrape in progress</span>'
                     : '<span class="pill ok">running</span>')
        : '<span class="pill">stopped</span>';
      const next = st.next_run
        ? ` · <span title="${esc(fmtLocal(st.next_run))}">next ${esc(fmtRelative(st.next_run))}</span>`
        : "";
      $("sched-status").innerHTML = pill + next;
      const r = st.last_result;
      $("sched-last").innerHTML = st.last_error
        ? `<span class="pill err">last run failed</span> ${esc(st.last_error)}`
        : (r ? `Last run (${esc(r.mode)}): <strong>${r.articles_stored}</strong> stored` +
               (r.pages_fetched ? `, ${r.pages_fetched} pages fetched` : "") +
               `, ${r.sources_processed} source(s), ${esc(String(r.duration_s))}s ` +
               `<span class="muted">at ${esc(fmtLocal(r.finished_at || ""))}</span>`
             : '<span class="muted">No run yet.</span>');
    }

    // Collection-speed slider stops (kbps = kilobits/s, the consumer "download
    // speed" unit). The last stop is "Maximum" (governor mode = maximum).
    const SCHED_SPEED_STOPS = [100, 250, 500, 1000, 2500, 5000, "max"];
    function schedSpeedLabel() {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const sl = $("sch-speed"); if (!sl) return;
      const v = SCHED_SPEED_STOPS[Number(sl.value)];
      const el = $("sch-speed-val");
      if (el) el.textContent = (v === "max") ? T("Maximum") : (v + " kbps");
    }
    // Live "Now: X kbps" readout — polls the activity endpoint ONLY while the
    // Collect settings panel is visible (self-stops when it isn't).
    let _schedRateTimer = null;
    async function _pollSchedRate() {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const el = $("sch-speed-now"), view = $("set-collect");
      if (!el || !view || view.style.display === "none") { stopSchedRatePoll(); return; }
      let a; try { a = await api("/api/scheduler/activity"); } catch { return; }
      const r = a && a.download_rate_kbps, cp = a && a.collect_perf;
      if (r == null || !a.active) { el.textContent = ""; return; }
      let txt = T("Now") + ": " + r + " kbps";
      if (cp && cp.active_workers != null) txt += " · " + cp.active_workers + " " + T("workers");
      el.textContent = txt;
    }
    function startSchedRatePoll() {
      stopSchedRatePoll();
      _pollSchedRate();
      _schedRateTimer = setInterval(() => { if (!document.hidden) _pollSchedRate(); }, 3000);
    }
    function stopSchedRatePoll() {
      if (_schedRateTimer) { clearInterval(_schedRateTimer); _schedRateTimer = null; }
    }

    function applySchedConfig(c) {
      $("sch-interval").value = c.interval_minutes;
      $("sch-mode").value = c.mode;
      $("sch-depth").value = c.crawl_max_depth;
      $("sch-pages").value = c.crawl_max_pages;
      $("sch-autostart").checked = !!c.autostart;
      $("sch-langs").value = (c.select_languages || []).join(", ");
      $("sch-types").value = (c.select_source_types || []).join(", ");
      $("sch-tags").value = (c.select_tags || []).join(", ");
      if ($("sch-export-dir")) $("sch-export-dir").value = c.export_dir || "";
      // Collection speed: map the stored rate mode/target onto the slider stops.
      if ($("sch-speed")) {
        let idx = 2; // 500 kbps default
        if (c.collect_rate_mode === "maximum") {
          idx = SCHED_SPEED_STOPS.length - 1;
        } else {
          const t = Number(c.collect_target_kbps) || 500;
          idx = SCHED_SPEED_STOPS.findIndex(v => v !== "max" && v >= t);
          if (idx < 0) idx = SCHED_SPEED_STOPS.length - 2;  // largest numeric stop
        }
        $("sch-speed").value = idx;
        schedSpeedLabel();
      }
      toggleCrawlFields();
    }

    const _csv = id => $(id).value.split(",").map(x => x.trim()).filter(Boolean);

    // -- Top-bar collection-speed knob (maintainer ruling 2026-07-23) ------- //
    // One click toggles the bandwidth governor between "maximum" (ramp to the
    // worker ceiling; contention back-off + per-host politeness untouched) and
    // the considerate 500 KiB/s "target". PUT /api/scheduler/config is a
    // loopback settings write with no egress side effect (verified S4.7), so
    // no consent popup; the governor reads the mode at the next pass.
    let _rateMode = null;
    function _paintRateMode(mode) {
      const btn = $("rate-toggle");
      if (!btn) return;
      _rateMode = mode;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const max = mode === "maximum";
      btn.classList.toggle("rate-max", max);
      const needle = document.getElementById("rate-needle");
      if (needle) needle.setAttribute("transform", max ? "rotate(48 12 15.5)" : "rotate(-48 12 15.5)");
      btn.title = max
        ? t9("Collection speed: Maximum — uses your connection fully (politeness per host unchanged). Click for the considerate 500 KiB/s target.")
        : t9("Collection speed: 500 KiB/s target — deliberately gentle. Click for Maximum (full speed).");
      btn.setAttribute("aria-pressed", max ? "true" : "false");
    }
    async function loadRateMode() {
      try {
        const c = await api("/api/scheduler/config");
        _paintRateMode(c.collect_rate_mode || "maximum");
      } catch (_e) { /* chrome stays at the default paint; Settings still works */ }
    }
    async function toggleRateMode() {
      const next = _rateMode === "maximum" ? "target" : "maximum";
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const c = await api("/api/scheduler/config",
          {method: "PUT", body: JSON.stringify({collect_rate_mode: next})});
        _paintRateMode((c && c.collect_rate_mode) || next);
        // Keep the Settings → Collect speed slider in sync if that panel is live.
        try { if ($("sch-speed") && c) applySchedConfig(c); } catch (_e) {}
        toast(next === "maximum"
          ? t9("Collection speed set to Maximum — applies from the next pass.")
          : t9("Collection speed set to the 500 KiB/s target — applies from the next pass."));
      } catch (e) { toast("Could not change the collection speed: " + e.message, "err"); }
    }

    async function loadScheduler() {
      try { const s = await api("/api/scheduler/status"); renderSchedStatus(s); _paintCollectToggle(!!(s && s.running)); }
      catch (e) { $("sched-status").textContent = "Scheduler status unavailable: " + e.message; }
      try { applySchedConfig(await api("/api/scheduler/config")); }
      catch (e) { /* config panel stays at defaults */ }
      previewTargets();
      loadBatchPicker();
      startSchedRatePoll();
    }

    // The single primary Collection control: on/off. The schedule / mode / manual /
    // batch knobs are demoted to the "Advanced (legacy)" sections — collection is
    // continuous & automatic; this just switches it on or off.
    function _paintCollectToggle(running) {
      const btn = $("collect-toggle");
      if (!btn) return;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      btn.textContent = running ? t9("Collection is ON — click to turn off")
                                : t9("Collection is OFF — click to turn on");
      btn.setAttribute("aria-pressed", running ? "true" : "false");
    }
    async function collectToggle() {
      let running = false;
      try { running = !!(await api("/api/scheduler/status")).running; } catch (e) {}
      if (running) { await schedulerStop(); } else { await schedulerStart(); }
      loadScheduler();
    }

    async function previewTargets() {
      const el = $("sched-targets");
      try {
        const t = await api("/api/scheduler/targets");
        if (!t.applies) { el.innerHTML = `<span class="muted">Selection applies to RSS / crawl modes; current mode is <strong>${esc(t.mode)}</strong>.</span>`; return; }
        const langs = Object.entries(t.by_language).map(([k,v])=>`${esc(k)}:${v}`).join("  ");
        const types = Object.entries(t.by_source_type).map(([k,v])=>`${esc(k)}:${v}`).join("  ");
        el.innerHTML = `<span class="pill ${t.matched?'ok':'warn'}">${t.matched} sources targeted</span> ` +
          `of ${t.total_enabled} enabled · this run will process up to <strong>${t.will_process_this_run}</strong>` +
          `<div class="muted" style="font-size:12px;margin-top:4px">by language: ${langs||'—'}</div>` +
          `<div class="muted" style="font-size:12px">by type: ${types||'—'}</div>`;
      } catch (e) { el.textContent = "Could not preview targets: " + e.message; }
    }

    async function schedulerStart() {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!await ensureOnline(t9("Start continuous background collection"))) return;
      try { renderSchedStatus(await api("/api/scheduler/start", {method: "POST"}));
        toast("Scheduler started."); } catch (e) { toast(_failMsg("Start failed: {error}", e), "err"); }
    }
    async function schedulerStop() {
      try { renderSchedStatus(await api("/api/scheduler/stop", {method: "POST"}));
        toast("Scheduler stopped."); } catch (e) { toast(_failMsg("Stop failed: {error}", e), "err"); }
    }
    async function schedulerRunNow() {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!await ensureOnline(t9("Start a collection pass (RSS, crawl, markets, watched Wikipedia pages)"))) return;
      if (!await arbitrate(t9("Start a collection pass (RSS, crawl, markets, watched Wikipedia pages)"))) return;
      try {
        const st = await api("/api/scheduler/run-now", {method: "POST"});
        renderSchedStatus(st);
        toast(st.started ? "Scrape started — results will appear shortly." : "A run is already in progress.");
        // Poll the status a few times so the last-run summary updates without a manual refresh.
        let tries = 0;
        const poll = setInterval(async () => {
          try { const s = await api("/api/scheduler/status"); renderSchedStatus(s);
            if ((!s.active && s.last_run) || ++tries > 20) { clearInterval(poll); doSearch(); loadDbStats(); } }
          catch { clearInterval(poll); }
        }, 1500);
      } catch (e) { toast(_failMsg("Run now failed: {error}", e), "err"); }
    }

    async function saveScheduler() {
      const body = {
        interval_minutes: Number($("sch-interval").value),
        mode: $("sch-mode").value,
        crawl_max_depth: Number($("sch-depth").value),
        crawl_max_pages: Number($("sch-pages").value),
        autostart: $("sch-autostart").checked,
        select_languages: _csv("sch-langs"),
        select_source_types: _csv("sch-types"),
        select_tags: _csv("sch-tags"),
        export_dir: $("sch-export-dir") ? $("sch-export-dir").value.trim() : "",
      };
      // Collection speed: the slider's last stop is "Maximum" (governor mode),
      // every other stop is a download-rate target in kbps.
      if ($("sch-speed")) {
        const sv = SCHED_SPEED_STOPS[Number($("sch-speed").value)];
        if (sv === "max") { body.collect_rate_mode = "maximum"; }
        else { body.collect_rate_mode = "target"; body.collect_target_kbps = sv; }
      }
      try { applySchedConfig(await api("/api/scheduler/config", {method: "PUT", body: JSON.stringify(body)}));
        toast("Schedule saved."); previewTargets(); } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }

    // -- Markets (analysis-first dashboard) --------------------------------- //
