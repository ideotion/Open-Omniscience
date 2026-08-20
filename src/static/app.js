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
