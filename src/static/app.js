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
      setTimeout(() => n.remove(), onClick ? 8000 : 5000);
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
    // The visible step order. "encryption" + "sources" are deferred placeholders
    // (shown but inert) so the next slice slots its real UI straight in.
    const _GW_STEPS = ["lang", "encryption", "sources", "finish"];
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
    }
    function openGuide() {
      const dlg = $("guide-wizard"); if (!dlg) return;
      _gwIdx = 0; _gwPaint();
      if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      else dlg.setAttribute("open", "");
      if (window.OOI18N && OOI18N.apply) OOI18N.apply(dlg);  // translate freshly-shown chrome
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
      if (next) next.onclick = () => { if (_gwIdx < _GW_STEPS.length - 1) { _gwIdx++; _gwPaint(); } };
      if (back) back.onclick = () => { if (_gwIdx > 0) { _gwIdx--; _gwPaint(); } };
      if (fin) fin.onclick = () => closeGuide(true);
      if (close) close.onclick = () => closeGuide(true);   // X also completes the one-time guide
      if (stay) stay.onclick = () => closeGuide(true);
      // The ONLY path to the network from the wizard: close, then run the existing
      // first-run flow — which itself calls ensureOnline (the ONE consent popup).
      // The wizard never POSTs /api/system/network; the finish note states this.
      if (go) go.onclick = async () => {
        const note = $("gw-finish-note");
        if (note) note.textContent = _gwT("You'll confirm before anything connects.");
        closeGuide(true);
        // The "corpus is empty" bubble is retired (2026-06-17): going online routes
        // through toggleNetwork() -> ensureOnline (the ONE consent popup, invariant
        // #14); once online the background collector runs continuously on its own
        // (only airplane mode stops it). No manual seed/ingest step or progress card.
        if (typeof toggleNetwork === "function") toggleNetwork();
      };
      const dlg = $("guide-wizard");
      if (dlg) dlg.addEventListener("cancel", () => closeGuide(true));   // Esc completes it too
    })();

    async function toggleNetwork() {
      const btn = $("net-toggle");
      const goingOnline = btn.classList.contains("off");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        if (goingOnline) {
          // EVERY transition to online is consented (maintainer-ruled).
          if (!await ensureOnline(t("Allow network requests again"))) return;
        } else {
          const r = await api("/api/system/network", {method:"POST", body: JSON.stringify({online:false})});
          _paintNetwork(r.online);
        }
        const online = !$("net-toggle").classList.contains("off");
        let f = document.getElementById("net-flash");
        if (!f) { f = document.createElement("div"); f.id = "net-flash"; document.body.appendChild(f); }
        // Direction-aware flash (§3): go-on = live accent, go-off = calm/grounded.
        f.classList.remove("go-on", "go-off"); void f.offsetWidth;
        f.classList.add(online ? "go-on" : "go-off");
        toast(online ? t("Back online — network requests allowed again.")
                     : t("Offline — every new network request is refused. One in-flight request may finish."),
              online ? "ok" : "err");
      } catch (e) { toast(e.message, "err"); }
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
      btn.classList.toggle("off", !online);
      document.body.classList.toggle("net-offline", !online);
      // Onboarding coachmark: invite once when we first learn we're offline;
      // retire it for good once the user is online (they've learned the switch).
      if (online) { _coachChecked = true; dismissNetCoach(true); }
      else if (!_coachChecked) { _coachChecked = true; maybeShowNetCoach(); }
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
      } else {                                              // else float above it
        left = b.left; top = b.top - gap - h; side = "bottom";
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
          arrow.style.top = (h - 6) + "px";
          arrow.style.left = Math.max(8, Math.min(b.left + b.width / 2 - left - 5, w - 16)) + "px";
          arrow.style.transform = "rotate(-45deg)";
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
    async function ensureOnline(reason) {
      try {
        const nm = await api("/api/system/network");
        _paintNetwork(nm.online);
        if (nm.online) return true;
      } catch (_e) { /* fall through to consent — flipping online still asks */ }
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
        ok.onclick = async () => {
          try {
            const r = await api("/api/system/network", {method:"POST", body: JSON.stringify({online:true})});
            _paintNetwork(r.online);
            done(true);
          } catch (e) { toast(e.message, "err"); done(false); }
        };
        cancel.onclick = () => done(false);
        dlg.oncancel = () => done(false); // Esc = stay offline
        dlg.showModal();
      });
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
    function _ensureVitalsPoll() {
      if (_vitalsShouldRun() && !_vitalsTimer) {
        _pollVitals();
        _vitalsTimer = setInterval(() => { if (!document.hidden) _pollVitals(); }, 2000);
      } else if (!_vitalsShouldRun() && _vitalsTimer) {
        clearInterval(_vitalsTimer); _vitalsTimer = null; _vitalsPrev = null;
      }
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
        nowHtml = row("Now collecting", a.running
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
          prog = `<div class="cap-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>` +
                 `<div class="muted" style="font-size:11px">${_fmtBytes(j.progress.done)} / ${_fmtBytes(j.progress.total)} · ${pct}%</div>`;
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
        const qpos = j.queue_position ? ` <span class="muted">#${j.queue_position} ${esc(t("in queue"))}</span>` : "";
        return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;flex-wrap:wrap">` +
          `<span class="pill ${pill}">${esc(t(j.state))}</span><b style="font-size:12.5px">${esc(j.label)}</b>${qpos}` +
          `<span style="margin-inline-start:auto;display:flex;gap:4px">${acts.join("")}</span>` +
          `<div style="flex-basis:100%">${prog}</div></div>`;
    }
    async function _renderJobs() {
      const elA = $("jobs-body"), elQ = $("queue-body");
      if (!elA && !elQ) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      try { _jobsData = await api("/api/jobs"); }
      catch { if (elA) elA.innerHTML = ""; if (elQ) elQ.innerHTML = ""; return; }
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
        elQ.innerHTML = `<div class="vsect">${esc(t("Queue"))}</div>` + (queued.length
          ? queued.map(j => _jobRow(j, queuedKeysByKind, t)).join("")
          : `<div class="muted" style="font-size:12px;padding:2px 0 6px">${esc(t("The queue is empty — downloads waiting their turn appear here, in order; use the arrows to reorder them."))}</div>`);
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
      const queued = jobs.filter(j => j.state === "queued" && j.kind === kind)
                         .sort((a, b) => (a.queue_position || 0) - (b.queue_position || 0))
                         .map(_dlKey);
      const i = queued.indexOf(key);
      if (i < 0 || i + dir < 0 || i + dir >= queued.length) return;
      [queued[i], queued[i + dir]] = [queued[i + dir], queued[i]];
      try { await api(_reorderEndpoint(kind), {method: "POST", body: JSON.stringify({keys: queued})}); _renderJobs(); }
      catch (e) { toast(e.message, "err"); }
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
        `<div class="vnote">${esc(t("These are the scheduler’s own facts — the schedule is managed in Settings. Times are relative; hover for the exact local moment and the method."))}</div>`;
    }
    // The arbitration ASK (ruled): a new heavy task while one runs is offered
    // a choice, never silently piled up. Dumps queue automatically (real
    // queue); collect/import ask proceed-or-wait.
    async function arbitrate(actionLabel) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      let d; try { d = await api("/api/jobs"); } catch { return true; }
      // Parallel across kinds is the DEFAULT (maintainer-amended): a wiki
      // dump downloading never blocks or nags article collection — only a
      // real DB-writer collision asks.
      if (!d.db_writers_busy) return true;
      const busy = (d.busy_with || []).join(", ");
      return confirm(`${t("Another network task is running:")} ${busy}\n\n${t("Start anyway? (Cancel waits — the running task keeps the bandwidth and the database writer to itself.)")} ${actionLabel}`);
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
    // Esc closes the task manager; Tab is trapped inside it (OO-D13-001).
    function vitalsKey(e) {
      if (e.key === "Escape") { e.preventDefault(); if (_vitalsOpen) toggleVitals(); return; }
      if (_vitalsOpen) _trapTab($("vitals-pop"), e);
    }

    async function api(path, opts={}) {
      _bumpInflight(1);
      try {
        const res = await fetch(path, {
          headers: {"Content-Type": "application/json"}, ...opts,
        });
        const text = await res.text();
        let data; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
        if (res.status === 503 && data && data.locked) { location.replace("/unlock"); throw new Error(data.detail); }
        if (!res.ok) throw new Error((data && data.detail) || res.status + " " + res.statusText);
        return data;
      } finally { _bumpInflight(-1); }
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
      {id:"timemap",  label:"Temporal map",       grp:"Investigate"},
      {id:"wiki",     label:"Wikipedia",          grp:"Investigate"},
      {id:"law",      label:"World law",          grp:"Investigate"},
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
    const TAB_LOADERS = {
      home: loadHome,
      search: buildSearchTimeScope,   // mount the ooTimeScope date-range control once
      indices: loadIndices,
      markets: loadMarkets,
      insights: loadInsights,
      timemap: loadTimemap,
      law: loadLaw,
      agenda: loadAgenda,
      library: () => { loadCoverage(); },    // stats handled by the live poller (startLive)
      custody: loadCustody,
      integrity: loadIntegrity,
      settings: loadSettings,
      help: loadDocs,
    };
    const _loaded = new Set();

    function showTab(name, push = true) {
      if (name === "database") name = "library";  // legacy #database deep-links
      if (name === "ingest") {  // Collect moved into Settings → Collect (content-first §6)
        showTab("settings", push);
        try { _setSubtabs.select("collect"); } catch (e) { showSetCat("collect"); }
        return;
      }
      if (name === "sources") {  // Sources moved into Settings → Sources (content-first §6)
        showTab("settings", push);
        try { _setSubtabs.select("sources"); } catch (e) { showSetCat("sources"); }
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
      if (TAB_LOADERS[name] && !_loaded.has(name)) { _loaded.add(name); TAB_LOADERS[name](); }
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

    // -- Appearance / customization (local-only, never transmitted) --------- //
    const UI_KEY = "oo.ui";
    const UI_DEFAULTS = {theme:"ink", accent:"", density:"comfortable", font:100, face:"", sidebar:"expanded", hidden:[]};
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
      r.style.fontSize = (ui.font || 100) + "%";
      if (ui.sidebar === "collapsed") r.setAttribute("data-sidebar", "collapsed"); else r.removeAttribute("data-sidebar");
      // Module visibility: hide chosen tools (and any group left entirely empty).
      const hidden = new Set(ui.hidden || []);
      document.querySelectorAll(".nav-item[data-tab]").forEach(b => {
        b.style.display = hidden.has(b.dataset.tab) ? "none" : "";
      });
      document.querySelectorAll(".nav-group").forEach(g => {
        const any = [...g.querySelectorAll(".nav-item[data-tab]")].some(b => b.style.display !== "none");
        g.style.display = any ? "" : "none";
      });
    }
    function setTheme(t)   { const u = getUi(); u.theme = t;   saveUi(u); applyUi(u); buildDrawer(); syncThemeSelect(); }
    function setAccent(a)  { const u = getUi(); u.accent = a;  saveUi(u); applyUi(u); buildDrawer(); }
    function setDensity(d) { const u = getUi(); u.density = d; saveUi(u); applyUi(u); buildDrawer(); }
    function setFace(f)    { const u = getUi(); u.face = f;    saveUi(u); applyUi(u); buildDrawer(); }
    function setFont(v)    { const u = getUi(); u.font = +v;   saveUi(u); applyUi(u); $("dr-font-val").textContent = v + "%"; }
    function setSidebar(s) { const u = getUi(); u.sidebar = s; saveUi(u); applyUi(u); buildDrawer(); }
    function toggleSidebar(){ setSidebar(getUi().sidebar === "collapsed" ? "expanded" : "collapsed"); }
    function toggleModule(id, show) {
      const u = getUi(); const set = new Set(u.hidden || []);
      show ? set.delete(id) : set.add(id);
      u.hidden = [...set]; saveUi(u); applyUi(u);
    }
    function resetUi() { localStorage.removeItem(UI_KEY); applyUi(getUi()); buildDrawer(); syncThemeSelect();
      toast("Appearance reset to defaults."); }
    function syncThemeSelect() { const t = getUi().theme; const sel = $("set-theme");
      const lightish = ["light", "paper", "mist", "dawn", "mint"];
      if (sel) sel.value = (t === "system" ? "system" : lightish.includes(t) ? "light" : "dark"); }

    // Appearance now lives in Settings → Appearance (the old drawer is gone).
    // openDrawer() is kept as the single "take me to appearance" entry point so the
    // command palette and any deep link still work; closeDrawer() is a safe no-op.
    function openDrawer()  { showTab("settings"); (_setSubtabs || {select: showSetCat}).select("appearance"); }
    function closeDrawer() { /* drawer removed — appearance is a Settings section */ }

    // Settings sections (Appearance · General · Wikipedia · Data · Safety).
    function showSetCat(cat) {
      // Button/ARIA state is owned by the ooSubtabs component; this callback
      // switches the panel + does the section's one-time setup.
      document.querySelectorAll("#tab-settings .set-view").forEach(v =>
        v.style.display = (v.id === "set-" + cat) ? "" : "none");
      if (cat !== "collect") stopSchedRatePoll();   // stop the live download-rate poll when leaving Collect
      if (cat === "appearance") buildDrawer();      // (re)paint theme/accent/module state
      if (cat === "guis" && window.OOGUIs && OOGUIs.renderGallery) OOGUIs.renderGallery();  // alternative-interfaces gallery

      if (cat === "agenda" && !AG.cals.length) loadAgenda();  // calendars/directory live here now
      if (cat === "collect") loadScheduler();         // the moved Collect tab's onShow
      if (cat === "sources") { loadManagedSources(); loadCandidates(); }  // moved Sources onShow
      if (cat === "models") { loadLlmModels(); loadLlmPrompts(); loadLlmHealth(); }  // LLM-management subtab (Q6) — also re-check the pill
      if (cat === "keywords") loadKeywordExplorer();  // Item AC: explore keywords by tag, hide, apply baseline tags
      if (cat === "wikipedia") loadWiki();            // moved Wikipedia tracking onShow (dumps load via loadSettings)
      if (cat === "stats") { loadStatAgencies(); loadStatFigures(); }  // official-statistics directory + figures (Group N)
      if (cat === "offlinemap") loadOsmMap();         // OSM offline-map region downloads (Group M)
      if (cat === "safety") { loadAtRestState(); onUninstallMode(); }  // at-rest attestation + uninstall preview
      if (cat === "data") modelsBackupStatus();        // the opt-in LLM-models companion backup (PR 6)
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
      $("dr-font").value = ui.font; $("dr-font-val").textContent = ui.font + "%";
      const hidden = new Set(ui.hidden || []);
      $("dr-modules").innerHTML = NAV.filter(n => !LOCKED.has(n.id)).map(n =>
        `<label><input type="checkbox" ${hidden.has(n.id) ? "" : "checked"}
           onchange="toggleModule('${n.id}', this.checked)"> ${esc(n.label)}</label>`).join("");
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
        {grp:"Actions", label:"Download a backup", sub:"Library", run:() => downloadBackup()},
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
          items.forEach(it => out.push({grp,
            label: it.term + (it.frequency ? ` (${it.frequency})` : ""),
            sub: t("opens its corpus window"),
            run: () => openCorpus(it.normalized_term)}));
        } else if (g.kind === "sources") {
          const grp = head(t("Sources"), g);
          items.forEach(it => out.push({grp, label: it.name, sub: it.domain || "",
            run: () => showTab("sources")}));
        } else if (g.kind === "wiki") {
          const grp = head(t("Wikipedia"), g);
          items.forEach(it => out.push({grp, label: it.title, sub: it.wiki || "",
            run: () => showTab("wiki")}));
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
        // Ruled: Enter -> the corpus/analysis window (default), with the Boolean
        // Search tab still one item away (nothing lost while capability migrated).
        live.unshift({grp: t("Search"), label: `${t("Run the full Boolean search for")} “${raw}”`,
          sub: "", run: () => { showTab("search"); setTimeout(() => { $("q").value = raw; doSearch(); }, 60); }});
        live.unshift({grp: t("Search"), label: `${t("Analysis")}: “${raw}”`,
          sub: "↵", run: () => openAnalysisFor(raw)});
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
      articles: "Articles", sources: "Sources", source_groups: "Source groups",
      keywords: "Keywords", commodity_prices: "Commodity prices",
      external_sources: "External sources", article_links: "Article links",
      article_analyses: "Article analyses", mentioned_dates: "Mentioned dates",
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
      loadHomeTrends();
      refreshDraftCount();
    }
    // Home "Trending now" glance (UI rethink, Home → helicopter view). Compact +
    // REDUNDANT by design: the past-week RISING keywords (the disclosed window-vs-
    // baseline RATE — never a score), each a chip that deep-links to its own
    // analysis window; a small honest sparkline rides along (dashChartSvg: line
    // when dense, Item-Y bars when sparse). The panel HIDES when nothing is
    // trending yet (Home is never blank-and-silent — the Briefing still renders);
    // "More in Insights →" deep-links to the canonical Trends view. Reuses
    // /api/insights/trending-windows + dashChartSvg; no new backend, no new poll.
    async function loadHomeTrends() {
      const panel = $("home-trends-panel"), box = $("home-trends");
      if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/insights/trending-windows?limit=4&series_top=4");
        const wk = (d.windows || []).find(w => w.label === "7d") || (d.windows || [])[0];
        const terms = (wk && wk.terms) || [];
        if (!terms.length) { if (panel) panel.hidden = true; box.innerHTML = ""; return; }
        if (panel) panel.hidden = false;
        const cards = terms.map(x => {
          const spark = Array.isArray(x.series)
            ? dashChartSvg(x.series.map(p => ({observed_on: p.date, price: p.count})), "")
            : "";
          return `<div style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
            <div style="display:flex;align-items:baseline;gap:6px">
              <a href="#" onclick='openAnalysisFor(${esc(JSON.stringify(x.term))});return false' title="${esc(t("Open this keyword's own analysis window"))}">${esc(x.term)}</a>
              <span class="muted" style="font-size:12px">↑${esc(String(x.growth))}× · ${esc(String(x.recent))}</span>
            </div>${spark}</div>`;
        }).join("");
        box.innerHTML = `<div style="display:flex;gap:8px;flex-wrap:wrap">${cards}</div>`
          + `<div class="hint muted" style="font-size:11px;margin-top:6px">${esc(d.caveat || "")}</div>`;
      } catch (e) { if (panel) panel.hidden = true; box.innerHTML = ""; }
    }
    // Live Home (the at-a-glance strip + briefing self-update; no Refresh button).
    // Only runs while Home is the active, visible tab (the LIVE registry). Cheap:
    // stats are server-cached ~30 s; the briefing feed re-renders ONLY when its
    // generated_at actually changes, so the user's card triage is never reset.
    async function refreshHomeLive() {
      try { const s = await api("/api/database/stats"); renderHomeStats(s.counts); } catch (e) {}
      try { const sc = await api("/api/scheduler/status"); renderHomeStatus(sc.running); } catch (e) {}
      try {
        const data = await api("/api/briefing");
        if (data.generated_at !== _lastBriefGen) renderBriefing(data);
      } catch (e) {}
      loadHomeTrends();
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
      if (!data.buckets || !data.buckets.length) {
        feed.innerHTML = `<div class="card">
          <h4>No Leads yet — that's expected on a young corpus</h4>
          <p class="sum">Leads are computed from YOUR collected material; an empty feed means the
          signals haven't accumulated, never that the engine is gone. As the corpus grows you'll see:
          <b>Rising now</b> (terms accelerating vs their own baseline), <b>Overtold/Undertold</b>,
          <b>framing splits</b>, <b>promises due</b> (a mentioned future date arrives),
          <b>edit-war bursts</b> on tracked Wikipedia pages, <b>regions gone quiet</b>,
          and <b>source candidates</b> from offline discovery.</p>
          <div class="acts">
            <button class="secondary tiny" onclick="showTab('ingest')">Collect now</button>
            <button class="secondary tiny" onclick="api('/api/briefing/refresh',{method:'POST'}).then(loadHome)">Recompute briefing</button>
          </div></div>`;
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
      const famTabs = `<button class="active" data-tab="__all">${esc(t("All Leads"))}</button>`
        + data.buckets.map((b, bi) =>
            `<button data-tab="${bi}"><span class="fam-dot" style="background:${famHue(bi)}"></span>${esc(b.label)}</button>`).join("");
      feed.innerHTML = (data.buckets.length > 1
        ? `<nav class="tabs home-fam" id="home-fam-subtabs">${famTabs}</nav>` : "") + html;
      // "All" is the default; selecting a family shows only that bucket.
      if (data.buckets.length > 1) ooSubtabs($("home-fam-subtabs"), selectHomeFamily, {initial: "__all"});
      applyMethodsToggle();
    }
    function selectHomeFamily(key) {
      document.querySelectorAll("#briefing-feed .brief-bucket").forEach(el => {
        el.style.display = (key === "__all" || el.dataset.fam === key) ? "" : "none";
      });
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
    function cardHtml(c) {
      const sig = c.signal || {};
      const sigLine = (sig.metric != null && sig.value != null)
        ? `<div class="sig">${esc(sig.metric)} = ${esc(sig.value)}${c.n != null ? " · n=" + c.n : ""}</div>` : "";
      const evid = (c.evidence || []).filter(e => e && (e.url || e.title)).map(e => {
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
        : `<button class="ghost tiny" onclick="dismissCard('${c.id}')">Dismiss</button>`;
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
      // "Why am I seeing this?" (evidence-tiered cards): a plain-language sentence
      // first, the exact arithmetic underneath. Labels and the plain sentence are
      // CONSTANT English strings -> the i18n engine translates them; values are
      // numbers/symbols only (language-neutral).
      let whyBlock = "";
      if (c.trigger && c.trigger.plain) {
        const rows = (c.trigger.math || []).map(r =>
          `<tr><td>${esc(r.label)}</td><td class="why-val">${esc(r.value)}</td></tr>`).join("");
        whyBlock = `<details class="why">
          <summary>Why am I seeing this?</summary>
          <p class="why-plain">${esc(c.trigger.plain)}</p>
          ${rows ? `<div class="why-mathlabel">The exact math</div><table class="why-math">${rows}</table>` : ""}
        </details>`;
      }
      // EVERY card is clickable (maintainer 2026-06-16): the card body opens the
      // unified analysis window over the card's article selection (never the
      // standalone /investigate new tab — that stays as the explicit "Open
      // investigation ↗" button below). Clicks on inner controls are ignored.
      const _aq = cardAnalyzeQuery(c);
      // Set-based cards (echo / convergence) carry their EXACT article set: open the
      // analysis window over precisely those ids. Keyword/topic/whole-corpus cards
      // fall back to the query (which reproduces their selection via the same search).
      const _aIds = (Array.isArray(c.article_ids) && c.article_ids.length) ? c.article_ids : null;
      const _aOpen = _aIds
        ? `openAnalysisForIds(${esc(JSON.stringify(_aIds))}, ${esc(JSON.stringify(_aq))})`
        : `openAnalysisFor(${esc(JSON.stringify(_aq))})`;
      const cardOpen = _aq
        ? ` style="cursor:pointer" title="Open in analysis — the article selection behind this Lead" onclick="if(!event.target.closest('button,a,details,summary,input,label'))${_aOpen}"`
        : "";
      // The CAVEAT is visible by default (informed-consent mandate: never hidden
      // behind a calm-UI toggle). Only the verbose Method/math stays in the
      // toggled .mc block below. Matches the corpus-tier .tier-caveat pattern.
      const caveatLine = c.caveat ? `<p class="card-caveat">${esc(c.caveat)}</p>` : "";
      return `<div class="card bk-${esc(c.bucket)}" data-card="${c.id}"${cardOpen}>
        <span class="chip">${esc(c.type.replace(/_/g,' '))}</span>
        <h4>${esc(c.title)}</h4>
        <p class="sum">${esc(c.summary)}</p>
        ${caveatLine}
        ${sigLine}
        ${evidBlock}
        ${whyBlock}
        ${weatherBox}
        <div class="mc" hidden><b>Method:</b> ${esc(c.method)}</div>
        <div class="acts">
          ${recipeBtn}
          ${weatherBtn}
          <button class="secondary tiny" onclick="addToDraft('${c.id}')">+ Add to draft</button>
          ${collapseBtn}
          ${dismiss}
        </div></div>`;
    }

    function toggleMethods() {
      localStorage.setItem("oo.brief.methods", $("brief-methods").checked ? "1" : "0");
      applyMethodsToggle();
    }
    function applyMethodsToggle() {
      const on = localStorage.getItem("oo.brief.methods") === "1";
      const box = $("brief-methods"); if (box) box.checked = on;
      document.querySelectorAll("#briefing-feed .mc").forEach(el => el.hidden = !on);
    }

    async function dismissCard(id) {
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
    function extLink(url, label, cls, style) {
      const u = safeUrl(url);
      return `<a${cls ? ` class="${cls}"` : ""}${style ? ` style="${style}"` : ""} href="${esc(u)}" rel="noopener" `
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
          rows.push(`<div>${esc(t("Known source in your catalog:"))} <b>${esc(d.known_source.name)}</b>${d.known_source.country ? ` <span class="muted">(${esc(String(d.known_source.country).toUpperCase())})</span>` : ""}</div>`);
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
          dim("Transparency", `${esc(tr.country||"?")} · ${esc(tr.language||"?")} · ownership: ${(tr.ownership_tags||[]).join(", ")||"—"} · leaning: ${(tr.leaning_tags||[]).join(", ")||"—"}`, tr.method, tr.caveat) +
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
      } catch (e) { toast("Import failed: " + e.message, "err"); }
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
    function agSubs() { try { return new Set(JSON.parse(localStorage.getItem("oo.agenda.subs") || "null") || []); } catch (_e) { return new Set(); } }
    function agSaveSubs(set) { localStorage.setItem("oo.agenda.subs", JSON.stringify([...set])); }
    // Per-machine EXCLUDED feed families (ruled 2026-06-15: "remove = reversible
    // unsubscribe, never delete-from-catalog"). Excluded folders keep their honest
    // verdicts in the directory (anti-hiding) but contribute no imported events.
    function agExcluded() { try { return new Set(JSON.parse(localStorage.getItem("oo.agenda.excluded") || "null") || []); } catch (_e) { return new Set(); } }
    function agSaveExcluded(set) { localStorage.setItem("oo.agenda.excluded", JSON.stringify([...set])); }

    // An imported feed event (already cross-feed deduped server-side) mapped into
    // the agenda's event shape, flagged as the IMPORTED provenance class so it is
    // filterable and never silently blended with curated events.
    function mapImportedToAgenda(e) {
      const d = e.date || "";
      return {
        title: e.title, category: "imported", country: null, tags: [],
        confirmed: true,                       // an ICS VEVENT carries a concrete date
        next_occurrence: d,
        month: d.length >= 7 ? +d.slice(5, 7) : null,
        day: d.length >= 10 ? +d.slice(8, 10) : null,
        calendar: e.family, family_name: e.family_name, family_names: e.family_names,
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
        month: d.length >= 7 ? +d.slice(5, 7) : null,
        day: d.length >= 10 ? +d.slice(8, 10) : null,
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
        ]);
        const excl = agExcluded();
        const imported = (imp.events || []).map(mapImportedToAgenda).filter(e => !excl.has(e.calendar));
        const deduced = (ded.events || []).map(mapDeducedToAgenda).filter(e => !excl.has(e.calendar));
        AG.events = ev.events.concat(imported, deduced); AG.caveat = ev.caveat; AG.cals = fac.calendars;
        // Imported + deduced events are each their own filterable category (distinct
        // provenance classes, like DDG-discovered sources) — a chip only when present.
        AG.categories = (fac.categories || []).concat(
          imported.length ? ["imported"] : [], deduced.length ? ["deduced"] : []);
        AG.meta = Object.fromEntries(fac.calendars.map(c => [c.key, c]));
        // First run: subscribe to all calendars so the agenda isn't empty.
        if (localStorage.getItem("oo.agenda.subs") == null) agSaveSubs(new Set(fac.calendars.map(c => c.key)));
        $("agenda-country").innerHTML = '<option value="">all</option>' + fac.countries.map(x => `<option value="${esc(x)}">${agFlag(x)} ${esc(x)}</option>`).join("");
        $("agenda-tag").innerHTML = '<option value="">all</option>' + fac.tags.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
        if (!_agViewTabs) _agViewTabs = ooSubtabs($("agenda-views"), agendaSetView);
        renderAgendaCatChips();
        renderAgenda();
      } catch (e) { box.innerHTML = `<div class="muted">Could not load agenda: ${esc(e.message)}</div>`; }
      loadFeedDir();   // the bundled directory (no network: it reads the catalog)
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
      renderImported();
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
      const excl = agExcluded();
      let fams = _feedDirFiltered();
      const total = fams.length;
      fams = fams.slice(0, 40);
      $("feeddir-status").textContent =
        `${_feedDir.total_feeds} feeds · ${_feedDir.families.length} folders · ${_feedDir.checked} checked`;
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
    async function verifyFeedBatch(btn) {
      btn.disabled = true;
      try {
        const r = await api("/api/events/feeds/verify-batch?limit=25", {method: "POST"});
        toast(`Checked ${r.checked} — ${r.ok} reachable · ${r.remaining_unchecked} left`, "ok");
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; loadFeedDir(); }
    }
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
        renderImported(); renderUserCalendars(); _agendaMaybeReload();
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
        renderImported(); renderUserCalendars(); _agendaMaybeReload();
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
      renderUserCalendars(); renderImported(); _agendaMaybeReload();
    }
    async function renderImported() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let data; try { data = await api("/api/events/imported"); } catch { return; }
      if (!data.count) { $("feeddir-imported").innerHTML = ""; return; }
      const today = new Date().toISOString().slice(0, 10);
      const next = data.events.filter(e => e.date >= today).slice(0, 30);
      $("feeddir-imported").innerHTML = `<h3 style="margin-bottom:6px">Imported events</h3>` +
        next.map(e => {
          const folders = e.family_count > 1 ? ` +${e.family_count - 1}` : "";
          const srcs = e.source_count > 1 ? ` · ${e.source_count}×` : "";
          return `<div class="vr"><span>${esc(e.date)} · ${esc(e.title)}</span>` +
            `<b class="muted" title="${esc((e.family_names || [e.family_name]).join(', '))}">${esc(e.family_name)}${folders}${srcs}</b></div>`;
        }).join("") +
        `<div class="hint">${data.count}${data.occurrences > data.count ? ` / ${data.occurrences}` : ""} · <span>The same event carried by several feeds is shown once, listing every source; a date disagreement stays visible as separate entries.</span></div>`;
    }

    function renderAgendaCals() {
      const subs = agSubs();
      $("agenda-cals").innerHTML = AG.cals.map(c =>
        `<button class="ag-cal${subs.has(c.key) ? " on" : ""}" data-k="${esc(c.key)}" onclick="toggleCalSub(this)"
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
        <div class="ag-body"><div>${titleEl} <span class="pill">${esc(e.category)}</span> ${e.country&&e.country!=='INT'?`<span class="pill">${esc(e.country)}</span>`:""} ${conf}${alsoIn}${imp}</div>
          ${variants}
          <div class="hint">${tags} ${e.note?"· "+esc(e.note):""}${src}</div></div></div>`;
    }
    // -- Agenda views: MONTH grid (the ruled default) + the original list ----- //
    // The tab shows DATA only (maintainer principle 2026-06-11): calendar
    // subscriptions and the feed directory live in Settings -> Agenda.
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
      let m = AGV.m + d, y = AGV.y;
      if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
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

    async function loadLaw() {
      try {
        const s = await api("/api/law/status");
        const jur = Object.entries(s.jurisdictions || {});
        $("law-status").innerHTML =
          `<div class="stat"><div class="n">${s.documents}</div><div class="k">laws</div></div>` +
          `<div class="stat"><div class="n">${s.tracked}</div><div class="k">with baseline</div></div>` +
          `<div class="stat"><div class="n">${s.changes}</div><div class="k">changes</div></div>` +
          `<div class="stat"><div class="n">${s.flagged}</div><div class="k">flagged</div></div>` +
          `<div class="stat"><div class="n">${jur.length}</div><div class="k">jurisdictions</div></div>`;
      } catch (e) { $("law-status").innerHTML = '<div class="muted">Status unavailable.</div>'; }
      loadLawChanges(); loadLawDocs();
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
      const fo = $("law-flagged-only") ? $("law-flagged-only").checked : true;
      try {
        const d = await api("/api/law/changes?flagged_only=" + fo);
        if (!d.changes || !d.changes.length) { box.innerHTML = '<div class="muted">No tracked changes yet.</div>'; return; }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` + d.changes.map(ch =>
          `<div class="panel" style="background:var(--panel2); margin-top:8px">
            <b>${esc(ch.jurisdiction.toUpperCase())}</b> · ${esc(ch.title)}
            <span class="pill ${ch.flagged?'warn':''}">${ch.delta_bytes>0?'+':''}${ch.delta_bytes} bytes</span>
            ${(ch.flag_reasons||[]).length?'<span class="hint">'+ch.flag_reasons.map(esc).join(', ')+'</span>':''}
            <div class="hint" style="margin-top:4px">${ch.observed_at?fmtDateTime(ch.observed_at):''} ·
              <a href="/api/law/documents/${ch.document_id}/view" target="_blank" rel="noopener" title="offline stored copy + history">open reader</a> ·
              ${extLink(ch.official_url, "official source ↗", "muted")}</div>
            ${renderDiff(ch.diff)}
          </div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load changes.</div>'; }
    }
    async function loadLawDocs() {
      try {
        const d = await api("/api/law/documents");
        const t = $("law-docs");
        t.innerHTML = "<thead><tr><th>Jurisdiction</th><th>Title</th><th>Category</th><th>Tracked</th><th>Changes</th><th></th></tr></thead><tbody>" +
          d.documents.map(x =>
            `<tr><td>${esc(x.jurisdiction.toUpperCase())}</td><td>${esc(x.title)}</td><td>${esc(x.category)}</td>
              <td>${x.has_baseline?'<span class="pill ok">yes</span>':'<span class="pill">no</span>'}</td>
              <td>${x.revisions}${x.flagged?` (${x.flagged} flagged)`:''}</td>
              <td><a href="/api/law/documents/${x.id}/view" target="_blank" rel="noopener" title="offline stored copy + history">reader</a>
                · ${extLink(x.official_url||x.url, "official ↗", "muted")}</td></tr>`).join("") +
          "</tbody>";
      } catch (e) { /* table optional */ }
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
      } catch (e) { toast("Tracking failed: " + e.message, "err"); if (st) loadLaw(); }
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
      const flushPara = (buf) => { if (buf.length) out.push("<p>" + buf.map(inline).join(" ") + "</p>"); };
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
          out.push("<blockquote>" + q.map(inline).join("<br>") + "</blockquote>"); continue; }
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

    async function loadHealth() {
      try {
        const h = await api("/api/health");
        $("version").textContent = "v" + h.version;
        $("health").innerHTML = '<span class="dot ok"></span> healthy';
      } catch (e) {
        $("health").innerHTML = '<span class="dot err"></span> offline';
      }
    }

    // -- Settings tab ------------------------------------------------------- //
    // Local UI preferences. DEFAULT_LIMIT feeds the search; the theme is applied by
    // the appearance engine above (applyUi / applyThemeAttr).
    let DEFAULT_LIMIT = 50;
    const _media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

    async function loadLlmModels() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("llm-models-box");
      if (!box) return;
      let d;
      try { d = await api("/api/llm/models"); }
      catch (e) { box.innerHTML = `<p class="muted">${esc(t("Model info unavailable:"))} ${esc(e.message)}</p>`; return; }
      if (!d.available) {
        box.innerHTML = `<p class="muted">${esc(t("Ollama isn't running. Start it (or install it) to use the LLM features; once running, your installed models appear here."))}</p>`;
        return;
      }
      const FIT = {fits:["✓ fits","ok"], tight:["~ tight","warn"], too_large:["✗ too large","err"], unknown:["?","muted"]};
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
      const cat = (d.catalog || []).map(m => {
        const [lbl, cls] = FIT[m.fit] || FIT.unknown;
        return `<tr><td><code>${esc(m.tag)}</code></td><td>${esc(m.size)}</td>` +
          `<td class="${cls === 'ok' ? '' : cls}"><span class="pill ${cls === 'err' ? 'err' : (cls === 'warn' ? 'warn' : 'ok')}">${esc(lbl)}</span></td>` +
          `<td class="muted">${esc(m.note)}</td>` +
          `<td><button class="tiny" onclick="pullModel(${esc(JSON.stringify(m.tag))})">${esc(t("Pull"))}</button></td></tr>`;
      }).join("");
      box.innerHTML = `<p class="muted">${esc(ram)}.</p>` + installed +
        `<h3 style="margin:14px 0 4px">${esc(t("Suggested models"))} <span class="muted" style="font-weight:400">(${esc(t("as of"))} ${esc(d.catalog_as_of)} — ${esc(t("newer likely exist"))})</span></h3>` +
        `<table><tr><th>${esc(t("Model"))}</th><th>${esc(t("Size"))}</th><th>${esc(t("Your hardware"))}</th><th>${esc(t("Note"))}</th><th></th></tr>${cat}</table>` +
        `<div class="hint">${esc(t("Hardware fit is advisory — it informs your choice, it doesn't decide. Pull any model from the full library below."))}</div>`;
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
    // Pull a model: a NETWORK action over CLEARNET via the Ollama process (NOT this
    // app's Tor proxy), so it passes the ONE consent popup (ensureOnline, invariant
    // #14) and is refused under airplane mode (the backend OllamaClient enforces the
    // kill switch too). Streams Ollama's REAL NDJSON progress (invariant #20 — never
    // a fabricated bar); degrades to a status line, never throws.
    async function pullModel(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!tag) return;
      if (!await ensureOnline(t("Pull a local model (downloads over the clear internet via Ollama)"))) return;
      const prog = $("llm-pull-progress");
      if (prog) prog.textContent = t("Starting…") + " " + tag;
      try {
        const resp = await fetch("/api/llm/pull", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({model: tag}),
        });
        if (!resp.ok || !resp.body) {
          if (prog) prog.textContent = t("Pull failed.") + " (" + resp.status + ")";
          return;
        }
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const {done, value} = await reader.read();
          if (done) break;
          buf += dec.decode(value, {stream: true});
          const lines = buf.split("\n");
          buf = lines.pop();   // keep the partial last line for the next chunk
          for (const line of lines) {
            if (!line.trim()) continue;
            let o; try { o = JSON.parse(line); } catch { continue; }
            if (o.error) { if (prog) prog.textContent = t("Pull failed:") + " " + o.error; return; }
            const pct = (o.total && o.completed) ? " — " + Math.round(100 * o.completed / o.total) + "%" : "";
            if (prog) prog.textContent = tag + ": " + (o.status || "") + pct;
          }
        }
        if (prog) prog.textContent = t("Pulled") + " " + tag;
        const el = $("llm-pull-tag"); if (el) el.value = "";
        loadLlmModels();
      } catch (e) { if (prog) prog.textContent = t("Pull failed:") + " " + e.message; }
    }

    // --- LLM behaviour & prompts (Settings → Models) --------------------------- //
    // The three editable system prompts + keep-alive. An empty box = the built-in
    // default (shown as the placeholder). The exact prompt used is recorded with every
    // result, so customising never breaks provenance. Saved via PUT /api/settings.
    let _llmPromptDefaults = {summary: "", translate: "", synthesis: ""};
    async function loadLlmPrompts() {
      if (!$("llm-keep-alive")) return;
      let d;
      try { d = await api("/api/llm/prompts"); }
      catch (e) { return; }   // optional surface; the models box already reports Ollama state
      $("llm-keep-alive").value = d.keep_alive || "";
      $("llm-keep-alive").placeholder = d.keep_alive_default || "30m";
      const P = d.prompts || {};
      _llmPromptDefaults = {
        summary: (P.summary && P.summary.default) || "",
        translate: (P.translate && P.translate.default) || "",
        synthesis: (P.synthesis && P.synthesis.default) || "",
      };
      for (const k of ["summary", "translate", "synthesis"]) {
        const ta = $("llm-prompt-" + k); if (!ta) continue;
        ta.value = (P[k] && P[k].current) || "";         // "" = using the default
        ta.placeholder = _llmPromptDefaults[k];          // show what the default is
      }
    }
    function resetLlmPrompt(k) {
      // Reset = clear the override so the built-in default is used (the default shows
      // as the placeholder). We never silently bake the default text in as a "custom".
      const ta = $("llm-prompt-" + k); if (ta) ta.value = "";
    }
    async function saveLlmBehaviour(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("llm-behaviour-status");
      const body = {
        llm_keep_alive: ($("llm-keep-alive").value || "").trim() || "30m",
        llm_prompt_summary: $("llm-prompt-summary").value,
        llm_prompt_translate: $("llm-prompt-translate").value,
        llm_prompt_synthesis: $("llm-prompt-synthesis").value,
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

    async function loadSettings() {
      try {
        const s = await api("/api/settings");
        $("set-limit").value = s.default_result_limit;
        DEFAULT_LIMIT = s.default_result_limit;
        const disabled = new Set(s.recipes_disabled || []);
        document.querySelectorAll(".recipe-toggle").forEach(cb => {
          cb.checked = !disabled.has(cb.value);
        });
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
        $("backup-status").innerHTML = st.backup_supported
          ? `Backend <span class="pill ok">${esc(st.backend)}</span> — backup &amp; restore available.`
          : `Backend <span class="pill warn">${esc(st.backend)}</span> — file backup/restore is SQLite-only; use the backend's native dump tool.`;
        document.querySelectorAll("#backup-panel .danger, #backup-panel button.secondary")
          .forEach(b => { b.disabled = !st.backup_supported; });
        $("vacuum-reclaim").textContent =
          (st.reclaimable_bytes == null) ? "—" : _fmtBytes(st.reclaimable_bytes);
      } catch (e) { $("backup-status").textContent = "Backup status unavailable: " + e.message; }
      loadKeywordFilter();
      loadV2Batches();
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
      } catch (e) { toast("Save failed: " + e.message, "err"); }
    }

    async function saveSettings() {
      const body = {
        theme: $("set-theme").value,
        default_result_limit: Number($("set-limit").value),
        recipes_disabled: Array.from(document.querySelectorAll(".recipe-toggle"))
          .filter(cb => !cb.checked).map(cb => cb.value),
      };
      try {
        const s = await api("/api/settings", {method: "PUT", body: JSON.stringify(body)});
        DEFAULT_LIMIT = s.default_result_limit;
        setTheme({dark:"ink", light:"light", system:"system"}[$("set-theme").value] || "ink");
        toast("Preferences saved.");
      } catch (e) { toast("Save failed: " + e.message, "err"); }
    }

    async function vacuumNow() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
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

    // ---- Backup v2: one signed archive; restore = MERGE with a preview ---- //
    let _v2Token = null;
    async function v2Backup(plaintext) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("v2-backup-result");
      const pass = $("v2-pass").value;
      if (!plaintext && !pass) { out.textContent = t("Choose a passphrase first (or use the deliberate unencrypted option)."); return; }
      out.textContent = t("Building the archive…");
      try {
        const r = await fetch("/api/backup/v2", {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(plaintext ? {plaintext: true} : {passphrase: pass})});
        if (!r.ok) { const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || r.statusText); }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const m = cd.match(/filename="?([^";]+)"?/);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = m ? m[1] : "open-omniscience-backup";
        document.body.appendChild(a); a.click(); a.remove();
        out.textContent = t("Backup downloaded.") + " " + _fmtBytes(blob.size);
      } catch (e) { out.textContent = t("Backup failed:") + " " + e.message; }
    }
    // Local LLM models — an OPT-IN companion backup (models live outside the corpus,
    // so they are a SEPARATE artifact; restore is additive + bit-identical). PR 6.
    async function modelsBackupStatus() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("models-bk-status"); if (!el) return;
      try {
        const d = await api("/api/backup/models");
        el.textContent = d.store_present
          ? `${d.models.length} ${t("model(s)")} · ${_fmtBytes(d.total_bytes)} · ${d.store}`
          : t("No local Ollama model store found.");
      } catch (e) { el.textContent = e.message; }
    }
    async function modelsBackupExport(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn) btn.disabled = true;
      try {
        const r = await fetch("/api/backup/models/export", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: "{}"});
        if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || r.statusText); }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || ""; const m = cd.match(/filename="?([^";]+)"?/);
        const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : "open-omniscience-models.oomodels";
        document.body.appendChild(a); a.click(); a.remove();
        toast(t("Models backup downloaded.") + " " + _fmtBytes(blob.size));
      } catch (e) { toast(t("Models backup failed:") + " " + e.message, "err"); }
      finally { if (btn) btn.disabled = false; }
    }
    async function modelsBackupImport(input) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const f = input.files && input.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      toast(t("Restoring models…"));
      try {
        const r = await fetch("/api/backup/models/import", {method: "POST", body: fd});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || r.statusText);
        toast(t("Models restored:") + ` +${d.blobs_added} · ${d.blobs_skipped} ${t("already present")}`);
        modelsBackupStatus();
      } catch (e) { toast(t("Models restore failed:") + " " + e.message, "err"); }
      finally { input.value = ""; }
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
    async function v2Preview() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const f = $("v2-restore-file").files[0];
      const out = $("v2-commit-result");
      if (!f) { out.textContent = t("Choose a backup file first."); return; }
      out.textContent = t("Previewing — nothing is changed yet…");
      const fd = new FormData();
      fd.append("file", f); fd.append("passphrase", $("v2-restore-pass").value || "");
      try {
        const r = await fetch("/api/backup/v2/restore/preview", {method: "POST", body: fd});
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || r.statusText);
        _v2Token = body.commit_token;
        $("v2-preview").style.display = "";
        const ver = body.verification || {};
        const sig = body.signature_state || "?";
        $("v2-verify").innerHTML =
          `<span class="pill ${ver.ok ? "ok" : "warn"}">${esc(ver.ok ? t("verification passed") : t("verification FAILED — merge will be refused"))}</span> ` +
          `<span class="muted">${esc(t("signature:"))} ${esc(sig)} · ${esc(t("archive schema:"))} ${esc(body.artifact_schema_rev || "?")}</span>`;
        $("v2-plan").innerHTML = _v2PlanTable(body.plan);
        $("v2-apply-btn").disabled = !ver.ok;
        out.textContent = "";
      } catch (e) { out.textContent = t("Preview failed:") + " " + e.message; $("v2-preview").style.display = "none"; }
    }
    async function v2Apply() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("v2-commit-result");
      if (!_v2Token) { out.textContent = t("Preview first."); return; }
      out.textContent = t("Merging… a safety snapshot is taken first.");
      const fd = new FormData(); fd.append("token", _v2Token);
      try {
        const r = await fetch("/api/backup/v2/restore/commit", {method: "POST", body: fd});
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || r.statusText);
        _v2Token = null; $("v2-preview").style.display = "none";
        out.innerHTML = body.committed
          ? `<span class="pill ok">${esc(t("Merge applied."))}</span> <span class="muted">${esc(t("batch"))} ${esc(String(body.batch_id))} · ${esc(t("snapshot:"))} ${esc(body.pre_restore_snapshot || "—")}</span>`
          : `<span class="pill warn">${esc(t("Merge refused:"))} ${esc(body.refused || "?")}</span>`;
        loadV2Batches();
      } catch (e) { out.textContent = t("Merge failed:") + " " + e.message; }
    }
    async function v2Discard() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_v2Token) { try { await api(`/api/backup/v2/restore/preview/${encodeURIComponent(_v2Token)}`, {method: "DELETE"}); } catch (_e) {} }
      _v2Token = null; $("v2-preview").style.display = "none";
      $("v2-commit-result").textContent = t("Preview discarded; nothing was changed.");
    }
    async function loadV2Batches() {
      try {
        const d = await api("/api/backup/v2/batches");
        const rows = (d.batches || []).slice(0, 10).map(b =>
          `<div>#${esc(String(b.id))} · ${esc(b.imported_at || "?")} · ${esc(b.artifact_kind || "?")} · ${esc((b.origin_fingerprint || "?").slice(0, 12))} · ${esc(b.status || "?")}</div>`);
        $("v2-batches").innerHTML = rows.join("") || "—";
      } catch (_e) { /* panel stays at dash */ }
    }

    function downloadBackup() {
      // Stream the snapshot straight to disk via a normal navigation download.
      window.open("/api/database/backup", "_blank");
      toast("Preparing backup download…");
    }

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
      } catch (e) { toast("Save failed: " + e.message, "err"); }
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
        toast("Save failed: " + e.message, "err");
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

    async function encryptedBackup() {
      const pass = $("enc-pass").value;
      if (!pass) { toast("Enter a passphrase first.", "err"); return; }
      try {
        const res = await fetch("/api/safety/backup/encrypted",
          {method: "POST", headers: {"Content-Type": "application/json"},
           body: JSON.stringify({passphrase: pass})});
        if (!res.ok) { const d = await res.json().catch(() => ({}));
          throw new Error(d.detail || res.statusText); }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "open-omniscience-backup.ooenc";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        $("enc-pass").value = "";
        toast("Encrypted backup downloaded.");
      } catch (e) { toast("Backup failed: " + e.message, "err"); }
    }
    // encryptedRestore() (destructive replace-restore) was REMOVED 2026-06-13:
    // restore is additive-only via the merge restore (the signed backup artifact).
    async function panicWipe() {
      if (!confirm("PANIC WIPE: irreversibly delete the corpus, keys and caches on this machine?\n\n" +
                   "This cannot be undone. Type-confirm follows.")) return;
      if (prompt('To confirm, type WIPE in capitals:') !== "WIPE") {
        toast("Panic wipe cancelled.", "err"); return; }
      try {
        const r = await api("/api/safety/panic", {method: "POST", body: JSON.stringify({confirm: true})});
        $("panic-result").innerHTML =
          `<span class="pill warn">wiped</span> ${r.files_wiped}/${r.files_seen} files. ` +
          `Restart the app. <span class="muted">${esc(r.limit)}</span>`;
        toast("Local data wiped. Restart the app.", "warn");
      } catch (e) { toast("Panic wipe failed: " + e.message, "err"); }
    }

    // Resolve {mode, remove_folder, wipe_data} from the picker. Data is removed only in
    // 'secure' or an explicit 'custom' opt-in — never minimal/full (maintainer-ruled).
    function _uninstallSel() {
      const mode = (($("uninstall-mode") || {}).value) || "minimal";
      const remove_folder = mode === "custom"
        ? !!(($("uninstall-folder") || {}).checked)
        : (mode === "full" || mode === "secure");
      const wipe_data = mode === "custom"
        ? !!(($("uninstall-data") || {}).checked)
        : (mode === "secure");
      return {mode, remove_folder, wipe_data};
    }

    // Show the Customize checkboxes + a live preview of the EXACT paths a mode removes
    // (informed consent before anything irreversible). Deletes nothing — GET only.
    async function onUninstallMode() {
      const sel = _uninstallSel();
      const cust = $("uninstall-custom"); if (cust) cust.style.display = sel.mode === "custom" ? "" : "none";
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
    async function uninstallBackupFirst() {
      const pass = prompt("Choose a passphrase to encrypt the backup (you'll need it to restore):");
      if (!pass) { toast("Backup cancelled — nothing removed.", "err"); return false; }
      try {
        const res = await fetch("/api/safety/backup/encrypted",
          {method: "POST", headers: {"Content-Type": "application/json"},
           body: JSON.stringify({passphrase: pass})});
        if (!res.ok) { const d = await res.json().catch(() => ({}));
          throw new Error(d.detail || res.statusText); }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "open-omniscience-backup.ooenc";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        toast("Backup downloaded — save it somewhere safe, then click Uninstall again.", "ok");
        return true;
      } catch (e) { toast("Backup failed: " + e.message, "err"); return false; }
    }

    async function uninstallApp() {
      const sel = _uninstallSel();
      // Only the data-wiping modes risk losing the corpus — offer a backup there first.
      if (sel.wipe_data) {
        const backFirst = confirm("This mode WIPES your data and keys — IRREVERSIBLE.\n\n" +
          "Create an encrypted backup first?\n\nOK = back up now (then click Uninstall again)\n" +
          "Cancel = continue WITHOUT a backup");
        if (backFirst) { await uninstallBackupFirst(); return; }
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
            remove_folder: sel.remove_folder, wipe_data: sel.wipe_data})});
        if (!r.scheduled) { $("uninstall-result").textContent = r.note || "Nothing to remove."; return; }
        $("uninstall-result").innerHTML =
          `<span class="pill warn">uninstalling</span> ${esc(r.note || "")} ` +
          `<span class="muted">This page will stop responding.</span>`;
        toast("Uninstalling — the app is stopping.", "warn");
      } catch (e) { toast("Uninstall failed: " + e.message, "err"); }
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
      } catch (e) { st.textContent = "First run failed: " + e.message; btn.disabled = false; }
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

    async function loadDbStats() {
      const el = $("db-stats");
      try {
        const s = await api("/api/database/stats");
        const entries = Object.entries(s.counts || {});
        const keys = entries.map(([k]) => k).join(",");
        if (DB_KEYS !== keys) {                       // (re)build grid with stable number nodes
          DB_KEYS = keys;
          el.innerHTML = entries.length
            ? entries.map(([k]) =>
                `<div class="stat"><div class="n" id="db-n-${k}" data-v="0">0</div><div class="k">${esc(k)}</div></div>`).join("")
            : '<div class="muted">No tables yet.</div>';
        }
        for (const [k, v] of entries) {
          const n = document.getElementById("db-n-" + k);
          if (n) animateCount(n, v);
        }
        $("db-file").innerHTML = s.file
          ? `Backend <span class="pill">${esc(s.backend)}</span> · on disk ` +
            `<strong>${humanBytes(s.file.bytes)}</strong> ` +
            `<span class="muted">(${esc(s.file.path)})</span>`
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
      library:  {ms: 4000, fn: () => { loadDbStats(); if ((++_covTick % 4) === 1) loadCoverage(); }},
      ingest:   {ms: 5000, fn: () => refreshSchedulerLive()},
      insights: {ms: 6000, fn: () => loadInsights()},
      wiki:     {ms: 6000, fn: () => refreshWikiLive()},
    };
    let _live = null;
    function startLive(name) {
      stopLive();
      const spec = LIVE[name];
      if (!spec) return;
      spec.fn();
      _live = {name, timer: setInterval(() => { if (!document.hidden) spec.fn(); }, spec.ms)};
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

    async function loadCoverage() {
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
    }

    async function seedDefaults() {
      try {
        const r = await api("/api/sources/seed-defaults", {method: "POST"});
        toast(`Seeded ${r.seeded.created} new source(s) (${r.seeded.skipped} already present).`);
        loadSources(); loadManagedSources(); loadDbStats(); loadCoverage();
      } catch (e) { toast("Seed failed: " + e.message, "err"); }
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
      } catch (e) { toast("Add failed: " + e.message, "err"); }
    }

    // -- Sources: management table ------------------------------------------ //
    // Source-management list state: filters + sort + paging.
    const SRC = {offset: 0, limit: 50, sort: "name", order: "asc"};

    function srcQuery() {
      const p = new URLSearchParams();
      const map = {q: "src-search", country: "src-country", language: "src-language",
                   source_type: "src-type", tag: "src-tag"};
      for (const [k, id] of Object.entries(map)) { const v = $(id).value.trim(); if (v) p.set(k, v); }
      const en = $("src-enabled").value; if (en) p.set("enabled", en);
      p.set("sort", SRC.sort); p.set("order", SRC.order);
      p.set("limit", SRC.limit); p.set("offset", SRC.offset);
      return p;
    }

    function applySrcFilters() { SRC.offset = 0; loadManagedSources(); }
    function clearSrcFilters() {
      ["src-search","src-country","src-language","src-type","src-tag"].forEach(id => $(id).value = "");
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
      return `<tr>
        <td>${esc(s.name)}<div class="muted" style="font-size:12px">${tags}</div></td>
        <td>${esc(s.domain)}${s.rss_url?' <span class="pill ok" title="has RSS feed">rss</span>':''}</td>
        <td class="muted">${esc(s.source_type || "—")}</td>
        <td class="muted" title="${esc((s.country || "").toUpperCase())}">${esc(s.country_name || s.country || "—")}</td>
        <td class="muted">${esc(s.language || "—")}</td>
        <td><select class="tiny" style="width:auto;padding:3px"
              onchange="updateSource(${s.id},{priority:Number(this.value)})">${prio}</select></td>
        <td class="muted">${s.article_count!=null?s.article_count:'—'}</td>
        <td><input type="checkbox" style="width:auto" ${s.enabled?"checked":""}
              onchange="updateSource(${s.id},{enabled:this.checked})"></td>
        <td><button class="tiny danger" onclick="deleteSource(${s.id}, ${esc(JSON.stringify(s.name))})">Delete</button></td>
      </tr>`;
    }

    function srcFilterTag(tag) { $("src-tag").value = tag; applySrcFilters(); }

    // Jump from the Database coverage view to the matching sources.
    function openSourcesForKeyword(code, tag) {
      clearSrcFilters();
      if (code && code !== "(none)") $("src-country").value = code;
      if (tag) $("src-tag").value = tag;
      showTab("sources"); applySrcFilters();
    }

    async function updateSource(id, body) {
      try { await api("/api/sources/" + id, {method: "PUT", body: JSON.stringify(body)});
        toast("Source updated."); }
      catch (e) { toast("Update failed: " + e.message, "err"); loadManagedSources(); }
    }

    async function deleteSource(id, name) {
      if (!confirm(`Delete source "${name}"? This also removes its stored articles.`)) return;
      try { await api("/api/sources/" + id, {method: "DELETE"});
        toast("Source deleted."); loadManagedSources(); loadSources(); loadDbStats(); }
      catch (e) { toast("Delete failed: " + e.message, "err"); }
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
      } catch (e) { $("imp-result").textContent = ""; toast("Import failed: " + e.message, "err"); }
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
      } catch (e) { $("ingest-result").textContent = ""; toast("Ingest failed: " + e.message, "err"); }
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
      } catch (e) { $("ingest-result").textContent = ""; toast("Ingest failed: " + e.message, "err"); }
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
          const meta = [s.language, s.country, s.source_type].filter(Boolean).map(esc).join(" · ");
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
      } catch (e) { $("bi-status").textContent = ""; toast("Batch ingest failed: " + e.message, "err"); }
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

    async function loadScheduler() {
      try { renderSchedStatus(await api("/api/scheduler/status")); }
      catch (e) { $("sched-status").textContent = "Scheduler status unavailable: " + e.message; }
      try { applySchedConfig(await api("/api/scheduler/config")); }
      catch (e) { /* config panel stays at defaults */ }
      previewTargets();
      loadBatchPicker();
      startSchedRatePoll();
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
        toast("Scheduler started."); } catch (e) { toast("Start failed: " + e.message, "err"); }
    }
    async function schedulerStop() {
      try { renderSchedStatus(await api("/api/scheduler/stop", {method: "POST"}));
        toast("Scheduler stopped."); } catch (e) { toast("Stop failed: " + e.message, "err"); }
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
      } catch (e) { toast("Run now failed: " + e.message, "err"); }
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
        toast("Schedule saved."); previewTargets(); } catch (e) { toast("Save failed: " + e.message, "err"); }
    }

    // -- Markets (analysis-first dashboard) --------------------------------- //
    let MKT_SERIES = [];
    const MKT_PRICES = {};            // symbol -> [{observed_on, price, currency, unit}]
    let _mktConfigLoaded = false;

    // -- Indices board (world stock-exchange indices) ----------------------- //
    async function loadIndices() { loadIndicesBoard(); }

    let _idxCards = [];              // last-loaded index board cards
    let _idxCat = "__all";           // current continent facet ("__all" or a continent)
    let _idxTags = new Set();         // active tag facets (AND-filter, none = no tag filter)
    let _idxCatTabs = null;           // the continent ooSubtabs handle
    const _idxCompare = new Map();    // symbol -> {name, currency, unit} selected for the overlay (Slice 3)
    let _idxView = "cards";           // "cards" | "families" (Slice 6 — twin parity; default = no regression)
    let _idxScope = {from: null, to: null};  // families-view time window
    let _idxTimeScope = null;          // the ooTimeScope handle (families view)
    let _idxSeriesLoaded = false;      // full per-symbol series fetched (lazy, for families)
    // Continent display order (data-driven: only those actually present render).
    const IDX_CONTINENTS = ["Africa", "Asia", "Europe", "North America", "South America", "Oceania", "Global"];

    async function loadIndicesBoard() {
      const el = $("idx-board");
      el.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const b = await api("/api/markets/board?category=index");
        $("idx-note").textContent = b.note || "";
        _idxCards = b.cards || [];
        renderIndicesBoard();
      } catch (e) { el.innerHTML = `<div class="muted">Could not load indices: ${esc(e.message)}</div>`; }
    }

    function _idxContinent(c) { return c.continent || "Other"; }

    // Group the index cards by CONTINENT into vsect sections (the primary
    // category axis — the direct analog of the commodities board's category
    // grouping, so the two boards stay near-identical, invariant #18 + the
    // twin-board ruling), build the continent subtabs + the secondary tag-chip
    // facet, then apply the active filters.
    function renderIndicesBoard() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("idx-board");
      if (!_idxCards.length) { el.innerHTML = '<div class="muted">No index catalog found.</div>'; }
      const byCont = {};
      for (const c of _idxCards) (byCont[_idxContinent(c)] || (byCont[_idxContinent(c)] = [])).push(c);
      // Present continents in the declared order, then any unexpected ones, then "Other".
      const ordered = IDX_CONTINENTS.filter(k => byCont[k]);
      const extra = Object.keys(byCont).filter(k => k !== "Other" && !IDX_CONTINENTS.includes(k)).sort();
      const present = [...ordered, ...extra, ...(byCont["Other"] ? ["Other"] : [])];
      // Board CONTENT depends on the view (Slice 6 — twin parity): FAMILIES = one
      // multi-series graph per continent (windowed by the time-scope), CARDS = the
      // per-index spark cards (default; unchanged — no regression).
      if (_idxView === "families") {
        if (!_idxTimeScope) buildIdxTimeScope();   // build once, after the series load
        renderIdxFamilies();
      } else if (_idxCards.length) {
        el.innerHTML = present.map(cont =>
          `<div class="idx-cat" data-cat="${esc(cont)}" style="display:contents">` +
          `<div class="vsect" style="grid-column:1/-1">${esc(t(cont))}</div>` +
          byCont[cont].map(idxCard).join("") + `</div>`
        ).join("");
      } else {
        el.innerHTML = '<div class="muted">No index catalog found.</div>';
      }
      const tsRow = $("idx-timescope-row");
      if (tsRow) tsRow.style.display = (_idxView === "families") ? "" : "none";
      _renderIdxViewToggle(t);
      // Continent SUB-TABS (universal subtab grammar, invariant #18): "All"
      // default lens + one tab per present continent. Skip the nav when only
      // one continent is present (a lone tab adds nothing — Home does the same).
      const catNav = $("indices-cats");
      if (catNav) {
        if (present.length > 1) {
          catNav.style.display = "";
          catNav.innerHTML = `<button class="active" data-tab="__all">${esc(t("All"))}</button>`
            + present.map(cont => `<button data-tab="${esc(cont)}">${esc(t(cont))}</button>`).join("");
          _idxCatTabs = ooSubtabs(catNav, selectIndexCat, {initial: _idxCat && present.includes(_idxCat) ? _idxCat : "__all"});
        } else { catNav.style.display = "none"; catNav.innerHTML = ""; _idxCatTabs = null; _idxCat = "__all"; }
      }
      // Secondary TAG facet: distinct tags as toggle chips (AND-filter). Off by
      // default; clicking narrows within the chosen continent. Honest empty
      // states are handled by applyIndexFilters (hides emptied sections).
      const tagRow = $("indices-tags");
      if (tagRow) {
        const tags = [...new Set(_idxCards.flatMap(c => c.tags || []))].sort();
        // Drop any stale active tag no longer present in the data.
        _idxTags = new Set([..._idxTags].filter(x => tags.includes(x)));
        tagRow.innerHTML = tags.length > 1
          ? `<span class="muted" style="font-size:12px;margin-right:4px">${esc(t("Tags"))}:</span>`
            + tags.map(tag =>
                `<button type="button" class="chip${_idxTags.has(tag) ? " on" : ""}" data-tag="${esc(tag)}"
                   onclick="toggleIndexTag(${esc(JSON.stringify(tag))})">${esc(tag)}</button>`).join("")
          : "";
      }
      if (_idxView !== "families") applyIndexFilters();   // cards-view filtering only
      renderIdxCompareBar();
    }
    // The Cards/Families view toggle (Slice 6) — mirrors the commodities toggle so
    // the two boards stay near-identical; default Cards (no regression).
    function _renderIdxViewToggle(t) {
      const tog = $("idx-viewtoggle"); if (!tog) return;
      tog.innerHTML = `<span class="muted" style="font-size:12px;margin-right:2px">${esc(t("View"))}:</span>`
        + [["cards", "Cards"], ["families", "Families"]].map(([k, lbl]) =>
            `<button type="button" class="chip${_idxView === k ? " on" : ""}" data-view="${k}"
               onclick="setIdxView(${esc(JSON.stringify(k))})">${esc(t(lbl))}</button>`).join("");
    }

    function selectIndexCat(key) {
      _idxCat = key;
      // In FAMILIES view the continent subtab re-renders the family graphs (the
      // card-level applyIndexFilters is meaningless there); otherwise it filters
      // the cards. Re-rendering (not hiding) keeps the ooChart widths correct.
      if (_idxView === "families") renderIdxFamilies();
      else applyIndexFilters();
    }
    function toggleIndexTag(tag) {
      if (_idxTags.has(tag)) _idxTags.delete(tag); else _idxTags.add(tag);
      document.querySelectorAll("#indices-tags .chip").forEach(b =>
        b.classList.toggle("on", _idxTags.has(b.dataset.tag)));
      // Families view filters the family MEMBERS by tag (re-render); cards view
      // hides individual cards.
      if (_idxView === "families") renderIdxFamilies();
      else applyIndexFilters();
    }

    // -- Multi-series compare overlay (Slice 3) ----------------------------- //
    // The user accumulates several indices, then opens ONE ooChart overlay of
    // their real price series with Absolute/Indexed/Log scale controls — "the
    // possibility to aggregate several curves onto the same graph" (maintainer
    // 2026-06-17). No fabricated data: each curve is the symbol's stored series
    // fetched from /api/commodities/{symbol}/prices.
    function toggleIdxCompare(symbol, name, currency, unit) {
      if (_idxCompare.has(symbol)) _idxCompare.delete(symbol);
      else _idxCompare.set(symbol, {name: name || symbol, currency: currency || "", unit: unit || ""});
      renderIndicesBoard();   // reflect the comparing state on the cards + the bar
    }
    function clearIdxCompare() { _idxCompare.clear(); renderIndicesBoard(); }
    function renderIdxCompareBar() {
      const bar = $("idx-compare-bar"); if (!bar) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const n = _idxCompare.size;
      if (n < 1) { bar.style.display = "none"; bar.innerHTML = ""; return; }
      bar.style.display = "";
      const names = [..._idxCompare.values()].map(v => esc(v.name)).join(" · ");
      // Need at least 2 series for a meaningful overlay; with 1 selected, invite a second.
      const ready = n >= 2;
      bar.innerHTML =
        `<span class="muted" style="font-size:12px">${esc(t("Comparing"))}: <b>${names}</b></span>`
        + `<button type="button" class="tiny${ready ? "" : " secondary"}"${ready ? "" : " disabled"}
             title="${esc(t("Overlay the selected series on one graph"))}"
             onclick="openIdxComparison()">${esc(t("Compare"))} (${n}) ↗</button>`
        + `<button type="button" class="tiny secondary" onclick="clearIdxCompare()">${esc(t("Clear"))}</button>`
        + (ready ? "" : ` <span class="hint muted" style="font-size:11px">${esc(t("Pick at least two."))}</span>`);
    }
    async function openIdxComparison() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_idxCompare.size < 2) return;
      const entries = [..._idxCompare.entries()];
      // Fetch every selected symbol's FULL stored series (cached by fetchPrices).
      const seriesList = [];
      for (const [symbol, meta] of entries) {
        const pts = await fetchPrices(symbol);
        if (!pts || !pts.length) continue;
        seriesList.push({
          label: meta.name || symbol,
          unit: meta.unit ? `${meta.currency || ""}/${meta.unit}`.replace(/^\//, "") : (meta.currency || ""),
          points: pts.map(p => ({t: p.observed_on, v: p.price})),
        });
      }
      if (seriesList.length < 2) { toast(t("Not enough stored data to compare these yet."), "err"); return; }
      chartEnlarge(t("Index comparison"), seriesList,
        t("End-of-day values from official sources on a shared time axis."), {scales: true});
    }

    // -- Indices FAMILIES view (Slice 6 — twin-board parity) ---------------- //
    // Bring the commodities board's family-stacked graphs + time-range control to
    // the Indices board so the two boards are near-identical (maintainer: "very
    // similar … nearly identical, only the data they show is different"). One
    // multi-series ooChart per CONTINENT, windowed by an ooTimeScope, reusing the
    // SAME renderFamilyGraphs + windowPricesRange + dashChartSvg helpers. Cards
    // view is untouched (sparks) — no regression.
    function setIdxView(v) {
      _idxView = v;
      const row = $("idx-timescope-row"); if (row) row.style.display = (v === "families") ? "" : "none";
      if (v === "families" && !_idxSeriesLoaded) { loadIdxFullSeries().then(renderIndicesBoard); return; }
      renderIndicesBoard();
    }
    async function loadIdxFullSeries() {
      // Lazily fetch every index's FULL stored series (cached by fetchPrices), so
      // the families view + time-scope window real data — not the truncated spark.
      await Promise.all((_idxCards || []).map(c => fetchPrices(c.symbol)));
      _idxSeriesLoaded = true;
    }
    function idxDataSpan() {
      let min = null, max = null;
      for (const c of (_idxCards || [])) {
        for (const p of (MKT_PRICES[c.symbol] || [])) {
          const d = p.observed_on; if (!d) continue;
          if (min === null || d < min) min = d;
          if (max === null || d > max) max = d;
        }
      }
      return {min, max};
    }
    function buildIdxTimeScope() {
      const box = $("idx-timescope"); if (!box) return;
      const span = idxDataSpan();
      if (!span.min || !span.max) { _idxTimeScope = ooTimeScope(box, {}); return; }
      const def = mktDefaultWindow(span);   // reuse: last year of data, anchored to max
      _idxScope = {from: def.from, to: def.to};
      _idxTimeScope = ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => { _idxScope = {from, to}; renderIdxFamilies(); },
      });
    }
    // Build one family per VISIBLE continent (respecting the continent subtab +
    // tag chips), each member windowed to the active range.
    function idxFamilies() {
      const tags = [..._idxTags];
      const byCont = {};
      for (const c of (_idxCards || [])) {
        if (_idxCat !== "__all" && (c.continent || "Other") !== _idxCat) continue;
        if (tags.length && !tags.every(x => (c.tags || []).includes(x))) continue;
        const cont = c.continent || "Other";
        (byCont[cont] || (byCont[cont] = [])).push(c);
      }
      const order = [...IDX_CONTINENTS, "Other"];
      const present = Object.keys(byCont).sort((a, b) => order.indexOf(a) - order.indexOf(b));
      return present.map(cont => ({
        key: cont, label: cont,
        series: byCont[cont].map(c => {
          const pts = windowPricesRange(MKT_PRICES[c.symbol] || [], _idxScope.from, _idxScope.to);
          return {label: c.name || c.symbol, unit: c.currency || "",
                  points: pts.map(p => ({t: p.observed_on, v: p.price}))};
        }),
      }));
    }
    function renderIdxFamilies() {
      const el = $("idx-board"); if (!el) return;
      renderFamilyGraphs(el, idxFamilies(), {});
    }

    // Apply BOTH facets: the continent subtab hides whole sections; the tag
    // chips hide individual cards (AND across active tags); a section whose
    // cards are all tag-hidden is itself hidden so no empty header shows.
    function applyIndexFilters() {
      const tags = [..._idxTags];
      document.querySelectorAll("#idx-board .idx-card").forEach(card => {
        const ct = (card.dataset.tags || "").split("|").filter(Boolean);
        card.style.display = tags.every(x => ct.includes(x)) ? "" : "none";
      });
      document.querySelectorAll("#idx-board .idx-cat").forEach(sec => {
        const visMatch = _idxCat === "__all" || sec.dataset.cat === _idxCat;
        const anyCard = [...sec.querySelectorAll(".idx-card")].some(c => c.style.display !== "none");
        sec.style.display = (visMatch && anyCard) ? "contents" : "none";
      });
    }

    function _num(n) { return n == null ? "—" : Number(n).toLocaleString(undefined, {maximumFractionDigits: 2}); }

    function idxSpark(pts, chg) {
      if (!pts || pts.length < 2) return '<div class="idx-spark-empty muted">no series yet</div>';
      const w = 280, h = 42, n = pts.length, vals = pts.map(p => p[1]);
      const min = Math.min(...vals), max = Math.max(...vals), rng = (max - min) || 1;
      const x = i => (i / (n - 1)) * w, y = v => h - ((v - min) / rng) * (h - 6) - 3;
      const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
      const col = chg == null ? "var(--muted)" : (chg >= 0 ? "var(--ok)" : "var(--err)");
      return `<svg class="idx-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
    }

    function idxCard(c) {
      const t2 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const has = !!c.latest;
      const chg = c.change_pct;
      const cls = chg == null ? "flat" : (chg >= 0 ? "up" : "down");
      const chgTxt = chg == null ? "" : `${chg >= 0 ? "▲" : "▼"} ${Math.abs(chg).toFixed(2)}%`;
      // With stored data the card opens the SAME interactive ooChart detail the
      // commodity board uses (invariant #16: full-resolution series fetched from
      // /api/commodities/{symbol}/prices, never the truncated spark). Empty
      // catalog entries stay inert until a first import.
      const open = has
        ? ` style="cursor:pointer" title="open detailed chart"
            onclick="indexDetail(${esc(JSON.stringify(c.symbol))}, ${esc(JSON.stringify(c.name || c.symbol))}, ${esc(JSON.stringify(c.currency || ""))})"`
        : "";
      // The GRAPH is a first-class entry into the analysis WINDOW (ledger
      // MARKETS item 4): an "Analyse ↗" affordance opens the index's corpus
      // coverage via openAnalysisFor (the same universal opener — no duplicate).
      // The card body keeps its indexDetail price chart (the Desk lesson: never
      // silently lose a tool); stopPropagation in the footer keeps the two paths
      // distinct. No symbol→family seed exists for indices, so the term is the
      // index's REAL name — never a fabricated family. The price × article
      // timeline OVERLAY is remaining; this slice opens the window on the name.
      const idxQ = c.name || c.symbol;
      // Carry the facet values so the continent subtab + tag chips can filter
      // without a re-fetch (data-tags is '|'-joined for a simple includes test).
      const facets = ` data-continent="${esc(c.continent || "Other")}" data-tags="${esc((c.tags || []).join("|"))}"`;
      // Slice 3: a compare toggle adds this index to the multi-series overlay
      // (only meaningful with a stored series — gated on `has`). The card body's
      // indexDetail click is preserved (stopPropagation keeps the two distinct).
      const cmp = _idxCompare.has(c.symbol);
      const cmpBtn = has
        ? ` · <button class="tiny${cmp ? "" : " secondary"}" type="button"
              title="${esc(t2(cmp ? "Remove from the comparison overlay" : "Add to the comparison overlay"))}"
              onclick="event.stopPropagation(); toggleIdxCompare(${esc(JSON.stringify(c.symbol))}, ${esc(JSON.stringify(c.name || c.symbol))}, ${esc(JSON.stringify(c.currency || ""))}, ${esc(JSON.stringify(c.unit || ""))})">${cmp ? "✓ " + esc(t2("Comparing")) : "＋ " + esc(t2("Compare"))}</button>`
        : "";
      return `<div class="idx-card${cmp ? " comparing" : ""}" data-symbol="${esc(c.symbol)}"${facets}${open}>
        <div class="idx-top">
          <div class="idx-id"><div class="idx-name">${esc(c.name)}</div>
            <div class="idx-mkt muted">${esc(c.market || "")}</div></div>
          <div class="idx-quote"><div class="idx-num">${_num(has ? c.latest.price : null)}</div>
            <div class="idx-chg ${cls}">${chgTxt}</div></div>
        </div>
        ${idxSpark(c.spark, chg)}
        ${has && c.spark && c.spark.length >= 2
          ? `<div class="idx-range hint muted"><span>${esc(c.spark[0][0])}</span><span>${esc(c.spark[c.spark.length - 1][0])}</span></div>`
          : ""}
        <div class="idx-foot muted" onclick="event.stopPropagation()">${has ? `as of ${esc(c.latest.observed_on)}` : "no data yet — click Load"}
          · ${esc(c.currency || "")} · ${extLink(c.url, "source")}
          · <button class="tiny secondary" type="button"
              title="${esc(t2("Open this in the analysis window — its corpus coverage"))}"
              onclick="openAnalysisFor(${esc(JSON.stringify(idxQ))})">${esc(t2("Analyse"))} ↗</button>${cmpBtn}</div>
      </div>`;
    }

    // Per-feed TRANSPORT-AWARE verdicts (ruled 2026-06-12): "refused over Tor"
    // is not "robots disallows" is not "dead series". Failures are listed with
    // their honest note, and ONLY honestly-retryable ones get the Retry button.
    function _renderFeedVerdicts(elId, r, category) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $(elId); if (!el) return;
      const fails = (r.results || []).filter(x => x.status !== "imported");
      if (!fails.length) { el.innerHTML = ""; return; }
      const rows = fails.map(x =>
        `<div><span class="pill warn">${esc(x.verdict || x.status)}</span> <b>${esc(x.symbol || x.key)}</b>` +
        ` <span class="muted">— ${esc(x.verdict_note || x.detail || "")}</span></div>`).join("");
      const retry = (r.retryable_failed_keys || []);
      const btn = retry.length
        ? `<button class="secondary tiny" style="margin-top:4px" onclick="retryFailedFeeds('${esc(category||"")}', '${esc(retry.join(","))}', '${esc(elId)}')">` +
          esc(t("Retry failed feeds")) + ` (${retry.length})</button>`
        : "";
      el.innerHTML = rows + btn;
    }
    async function retryFailedFeeds(category, keys, elId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ensureOnline === "function" &&
          !await ensureOnline(t("Fetch market and index data from the official feeds"))) return;
      const el = $(elId); if (el) el.textContent = t("Retrying failed feeds…");
      try {
        const q = category ? `?category=${encodeURIComponent(category)}&keys=` : "?keys=";
        const r = await api(`/api/markets/feeds/import-all${q}${encodeURIComponent(keys)}`, {method: "POST"});
        toast(`${t("Retry finished:")} ${r.points_imported} ${t("new point(s);")} ${r.failed} ${t("still failing.")}`);
        _renderFeedVerdicts(elId, r, category);
      } catch (e) { if (el) el.textContent = e.message; }
    }
    async function loadIndicesData(btn) {
      btn.disabled = true;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) { btn.disabled = false; return; }
      const st = $("idx-status");
      st.textContent = "Importing index feeds (official end-of-day CSVs; may take a moment)…";
      try {
        const r = await api("/api/markets/feeds/import-all?category=index", {method: "POST"});
        st.textContent = `Imported ${r.points_imported} point(s) across ${r.feeds} feed(s)${r.failed ? `, ${r.failed} failed` : ""}.`;
        _renderFeedVerdicts("idx-verdicts", r, "index");
        // Degrade loudly (maintainer hit "only Dow + S&P arrive"): name each
        // failing feed and the exact refusal, instead of a silent count.
        const bad = (r.results || []).filter(x => x.status !== "imported");
        $("idx-note").innerHTML = bad.length
          ? `<b>Feeds that did not deliver:</b> ` + bad.map(x =>
              `${esc(x.key || x.symbol)} <span class="muted">(${esc(x.detail || x.status)})</span>`).join(" · ")
          : "";
        await loadIndicesBoard();
        toast("Indices updated.");
      } catch (e) { st.textContent = ""; toast("Load failed: " + e.message, "err"); }
      finally { btn.disabled = false; }
    }

    async function loadMarkets() { loadDashboard(); }

    async function fetchPrices(symbol) {
      if (MKT_PRICES[symbol]) return MKT_PRICES[symbol];
      try { const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`); MKT_PRICES[symbol] = d.prices || []; }
      catch { MKT_PRICES[symbol] = []; }
      return MKT_PRICES[symbol];
    }

    async function loadDashboard() {
      const status = $("mkt-dash-status");
      try {
        const d = await api("/api/markets/series");
        MKT_SERIES = d.series || [];
        if (!MKT_SERIES.length) {
          $("mkt-dashboard").innerHTML = `<div class="muted">No market data yet. Click “Load / refresh market data” to import official price feeds (EUR/USD, crude oil, metals, gold).</div>`;
          status.textContent = ""; return;
        }
        status.textContent = `${MKT_SERIES.length} series`;
        await Promise.all(MKT_SERIES.map(s => fetchPrices(s.symbol)));
        // (Re)build the time-range control from the freshly loaded data span,
        // defaulting the window to the last year (or all if <1y). It calls
        // renderDashboard() on every change; render once now for the default.
        buildMktTimeScope();
        renderDashboard();
      } catch (e) { status.textContent = "Could not load series: " + e.message; }
    }

    // The commodities board is windowed by ABSOLUTE dates [from,to] (the
    // ooTimeScope control), not a trailing `days` count. Within the window the
    // FULL-RESOLUTION series is kept (invariant #16) — never thinned; sparse
    // windows render as honest dots downstream (dashChartSvg).
    let _mktScope = {from: null, to: null};   // current window (ISO YYYY-MM-DD)
    let _mktTimeScope = null;                  // the ooTimeScope handle
    function windowPricesRange(points, from, to) {
      if (!points.length) return points;
      if (!from && !to) return points;
      return points.filter(p =>
        (!from || p.observed_on >= from) && (!to || p.observed_on <= to));
    }
    // The data span across ALL loaded commodity series (oldest → newest point),
    // used to bound the control. Indices are excluded (not commodities).
    function mktDataSpan() {
      let min = null, max = null;
      for (const s of MKT_SERIES) {
        if (s.category === "index") continue;
        const pts = MKT_PRICES[s.symbol] || [];
        for (const p of pts) {
          const d = p.observed_on;
          if (!d) continue;
          if (min === null || d < min) min = d;
          if (max === null || d > max) max = d;
        }
      }
      return {min, max};
    }
    // Default window = the last 1 year of the data (or the whole span if the
    // data covers less than a year). Anchored to the data's max, never "now".
    function mktDefaultWindow(span) {
      if (!span.min || !span.max) return {from: span.min, to: span.max};
      const maxD = new Date(span.max + "T00:00:00Z");
      const yearAgo = new Date(maxD); yearAgo.setUTCFullYear(maxD.getUTCFullYear() - 1);
      const from = yearAgo.toISOString().slice(0, 10);
      return {from: from > span.min ? from : span.min, to: span.max};
    }
    function buildMktTimeScope() {
      const box = $("mkt-timescope");
      if (!box) return;
      const span = mktDataSpan();
      if (!span.min || !span.max) { _mktTimeScope = ooTimeScope(box, {}); return; }
      const def = mktDefaultWindow(span);
      _mktScope = {from: def.from, to: def.to};
      _mktTimeScope = ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => { _mktScope = {from, to}; renderDashboard(); },
      });
    }

    // Smart number formatting (maintainer-ruled, app-wide): significant digits
    // scaled to the magnitude — never a raw float tail like 3654.015384615385.
    // Thin-space thousands grouping (locale-neutral, SI style).
    function fmtNum(v, maxDec) {
      if (v == null || !isFinite(v)) return "—";
      const a = Math.abs(v);
      const dec = maxDec != null ? maxDec : (a >= 1000 ? 1 : a >= 100 ? 1 : a >= 1 ? 2 : 3);
      const s = v.toFixed(dec).replace(/\.?0+$/, m => m.includes(".") ? "" : m);
      const [int, frac] = s.split(".");
      const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
      return frac ? `${grouped}.${frac}` : grouped;
    }

    // Detailed per-card chart (maintainer-ruled, invariant #16): the FULL series
    // within the visible window — never downsampled, never silently widened to
    // the whole history. Labelled axes + DISCRETE horizontal gridlines so a
    // crossing reads off in X and Y. Honest sparsity: a connecting line ONLY
    // when the window is dense enough (lineMin=8); fewer points render as
    // discrete dots with n + the early-corpus caveat — never a curve faked
    // through a handful of points.
    // Item Y (ruled 2026-06-15, amends invariant #16): app-wide, n<10 datapoints
    // render as a BAR graph (not dots), n>=10 as the full-resolution line. Shared by
    // BOTH chart renderers (dashChartSvg + ooChart).
    const _SPARSE_BAR_MAX = 10;
    // --- chart accessibility (audit PR G) -------------------------------- //
    // <svg>/<canvas> charts are opaque to screen readers. Give each a role="img"
    // + a translated aria-label SUMMARY, and a visually-hidden data table so the
    // actual series is readable. Aria text is built from t9() fragments (a dynamic
    // attribute value is never matched by the i18n engine's exact-key lookup, so it
    // must be pre-translated here).
    function _chartAria(label, n, a, b, lo, hi) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return t9("Chart, {label}: {n} points, {a} to {b}, {lo} to {hi}")
        .replace("{label}", label || t9("Value")).replace("{n}", String(n))
        .replace("{a}", String(a)).replace("{b}", String(b))
        .replace("{lo}", String(lo)).replace("{hi}", String(hi));
    }
    function _chartSrTable(rows, label) {
      // rows: [{date, value}]; capped so a dense series can't bloat the DOM (the
      // aria-label already states the true n; a truncated table ends with an
      // ellipsis row). Visually hidden (.sr-only) — no visual change.
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const CAP = 500;
      const body = rows.slice(0, CAP).map(
        r => `<tr><td>${esc(String(r.date))}</td><td>${esc(String(r.value))}</td></tr>`).join("");
      const more = rows.length > CAP ? '<tr><td colspan="2">…</td></tr>' : "";
      const cap = label ? `${t9("Chart data")} — ${esc(String(label))}` : esc(t9("Chart data"));
      return `<table class="sr-only"><caption>${cap}</caption>`
        + `<thead><tr><th>${esc(t9("Date"))}</th><th>${esc(t9("Value"))}</th></tr></thead>`
        + `<tbody>${body}${more}</tbody></table>`;
    }

    function dashChartSvg(points, unit, opts) {
      opts = opts || {};
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!points.length) {
        return `<div class="muted" style="padding:18px 0;font-size:12px">${esc(t9("not enough points in this window"))}</div>`;
      }
      const w = 300, h = 120, padL = 44, padR = 8, padT = 8, padB = 18;
      const n = points.length, lineMode = n >= _SPARSE_BAR_MAX;
      const ys = points.map(p => p.price), minY = Math.min(...ys), maxY = Math.max(...ys), span = (maxY - minY) || 1;
      const plotW = w - padL - padR;
      // Shared time axis (Slice 4 — maintainer "graph timescales should be coherent
      // between all sources"): when opts.t0/t1 (ISO dates) are given, every point is
      // placed at its TRUE calendar position on that ONE window, so a March point
      // sits at the same x on EVERY card of the board (coherent timescales, honest
      // gaps). Without it, the index-based mapping is byte-for-byte identical to
      // before (Home sparklines, trend windows — additive, no regression).
      const _ms = (d) => Date.parse(String(d).length <= 7 ? String(d) + "-01T00:00:00Z" : String(d) + "T00:00:00Z");
      const sa = opts.t0 ? _ms(opts.t0) : NaN, sb = opts.t1 ? _ms(opts.t1) : NaN;
      const shared = isFinite(sa) && isFinite(sb) && sb > sa;
      const X = i => padL + plotW * (n < 2 ? 0.5 : i/(n-1));
      const Xp = (p, i) => {
        if (!shared) return X(i);
        const m = _ms(p.observed_on);
        if (!isFinite(m)) return X(i);
        return Math.max(padL, Math.min(w - padR, padL + plotW * ((m - sa) / (sb - sa))));
      };
      const Y = v => padT + (h - padT - padB) * (1 - (v - minY)/span);
      const up = points[n-1].price >= points[0].price;
      const col = up ? 'var(--ok)' : 'var(--err)';
      // 3 discrete horizontal gridlines at min / mid / max, each labelled.
      const grid = [minY, minY + span/2, maxY].map(v =>
        `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${w-padR}" y2="${Y(v).toFixed(1)}"
           stroke="var(--border)" stroke-dasharray="2 4" stroke-width="0.6"></line>
         <text x="${padL-4}" y="${(Y(v)+3).toFixed(1)}" text-anchor="end" font-size="8.5"
           fill="var(--muted)">${fmtNum(v)}</text>`).join("");
      // X ticks: in SHARED mode the ticks are the WINDOW endpoints (start/mid/end of
      // the plot at fixed positions) so every card reads the SAME coherent time
      // legend; otherwise first / middle / last point dates (YYYY-MM, de-duplicated).
      const xticks = shared
        ? [[padL, "start", opts.t0], [padL + plotW / 2, "middle", new Date((sa + sb) / 2).toISOString()],
           [w - padR, "end", opts.t1]].map(([x, anc, lab]) =>
            `<text x="${x.toFixed(1)}" y="${h-5}" text-anchor="${anc}"
               font-size="8.5" fill="var(--muted)">${esc(String(lab).slice(0,7))}</text>`).join("")
        : [...new Set([0, Math.floor((n-1)/2), n-1])].map(i =>
            `<text x="${X(i).toFixed(1)}" y="${h-5}" text-anchor="${i===0?'start':i===n-1?'end':'middle'}"
               font-size="8.5" fill="var(--muted)">${esc(points[i].observed_on.slice(0,7))}</text>`).join("");
      // The series itself: a line when dense (n>=10), otherwise honest BARS (Item Y).
      // Bars anchor to the window-MIN — which the gridlines above already LABEL — so a
      // price-LEVEL difference stays visible and honest (NEVER a fabricated zero
      // baseline). A 2px cap is drawn at the true value so a flush min / equal / single
      // point stays visible (the cap marks the value, never an invented height).
      const baseY = Y(minY);
      const slot = (w - padL - padR) / Math.max(n, 1);
      const bw = Math.max(3, Math.min(slot * 0.62, 22));
      const body = lineMode
        ? `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${
            points.map((p, i) => `${Xp(p, i).toFixed(1)},${Y(p.price).toFixed(1)}`).join(" ")}"></polyline>
           <circle cx="${Xp(points[n-1], n-1).toFixed(1)}" cy="${Y(points[n-1].price).toFixed(1)}" r="2.4" fill="${col}"></circle>`
        : points.map((p, i) => {
            const cx = Xp(p, i), by = Y(p.price);
            const x0 = Math.max(padL, cx - bw / 2), x1 = Math.min(w - padR, cx + bw / 2);
            const bwc = Math.max(1, x1 - x0).toFixed(1);
            return `<rect x="${x0.toFixed(1)}" y="${by.toFixed(1)}" width="${bwc}" height="${Math.max(0, baseY - by).toFixed(1)}" fill="${col}" opacity="0.72"></rect>`
                 + `<rect x="${x0.toFixed(1)}" y="${(by - 0.5).toFixed(1)}" width="${bwc}" height="2" fill="${col}"></rect>`;
          }).join("");
      // Item Y: the sparse "dots shown / no curve interpolated" caveat is removed
      // app-wide; only the datapoint count is kept.
      const caveat = lineMode ? "" :
        `<div class="hint muted" style="margin-top:1px">n=${n}</div>`;
      // The legend reads the SHARED window when coherent (so every card states the
      // same span), else this series' own first→last dates.
      const range = shared ? `${opts.t0} → ${opts.t1}`
        : (n >= 2 ? `${points[0].observed_on} → ${points[n-1].observed_on}` : points[0].observed_on);
      // a11y: a translated summary + a visually-hidden data table (audit PR G).
      const aria = _chartAria(unit || "", n, points[0].observed_on.slice(0, 7),
        points[n - 1].observed_on.slice(0, 7), fmtNum(minY), fmtNum(maxY));
      const srTable = _chartSrTable(
        points.map(p => ({date: p.observed_on, value: fmtNum(p.price)})), unit || "");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="display:block" role="img" aria-label="${esc(aria)}">
        ${grid}
        ${body}${xticks}</svg>${srTable}
        <div class="hint" style="display:flex;justify-content:space-between;margin-top:2px">
          <span><span style="display:inline-block;width:14px;height:0;border-top:2px solid ${col};vertical-align:middle"></span>
            ${esc(unit || "")}</span><span>${range}</span></div>${caveat}`;
    }

    // -- Family-stacked graphs (Slice 5) ------------------------------------ //
    // "In the 'all' subtab … stacking all curves into family graphs … as much
    // data but with fewer graphs" (maintainer 2026-06-17). One multi-series
    // ooChart per group (category / continent) replaces N small cards. INDEXED by
    // default so different-magnitude members of a family (gold vs copper, a 5000-pt
    // index vs a 130 OECD index) co-move honestly on one axis — the hover always
    // shows the REAL value, and a VISIBLE caveat states "relative, not absolute".
    // Each group is wrapped with data-cat so the SAME continent/category subtabs
    // filter the family graphs too. Reuses the ONE ooChart toolkit (invariant #16).
    // groups: [{key, label, series:[{label, unit, points:[{t,v}]}]}]; shared [t0,t1].
    function renderFamilyGraphs(host, groups, opts) {
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const live = groups.filter(g => g.series.some(s => (s.points || []).length));
      if (!live.length) { host.innerHTML = `<div class="muted">${esc(t("No data in this window yet."))}</div>`; return; }
      const cav = `<div class="card-caveat">${esc(t("Indexed to 100 at the window start — relative moves, not absolute levels; the hover shows the real value."))}</div>`;
      host.innerHTML = live.map(g =>
        `<div class="fam-block mkt-cat" data-cat="${esc(g.key)}">
           <div class="vsect" style="grid-column:1/-1">${esc(t(g.label))} <span class="muted">· ${g.series.filter(s => (s.points || []).length).length} ${esc(t("series"))}</span></div>
           <div class="fam-chart" style="grid-column:1/-1"></div>
         </div>`).join("") + cav;
      // ooChart renders imperatively into a live element, so instantiate after the
      // containers exist (in group order — the hosts match `live` 1:1).
      host.querySelectorAll(".fam-chart").forEach((el, i) => {
        const g = live[i]; if (!g) return;
        ooChart(el, g.series.filter(s => (s.points || []).length),
          {height: 200, indexed: opts.indexed !== false, logY: !!opts.logY});
      });
    }

    // Category display order + labels for the grouped Commodities board.
    const MKT_CATS = [
      ["energy", "Energy"], ["strategic", "Strategic & nuclear"], ["metals", "Base metals"],
      ["precious", "Precious metals"], ["construction", "Construction materials"],
      ["agriculture", "Agriculture & cereals"], ["fx", "Currencies"], ["custom", "Custom"],
    ];
    // Curated commodity SYMBOL → corpus search query (the "symbol→family seed
    // table", maintainer-ruled). Maps a price-feed symbol to the best plain
    // search term for that commodity's coverage in the corpus. Only symbols
    // whose raw code/name is a poor query are listed; everything unmapped falls
    // back to the series display name (s.name) — never an invented commodity.
    const COMMODITY_QUERY = {
      WTI: "oil", BRENT: "oil", NATGAS: "natural gas", NATGAS_EU: "natural gas",
      LNG_ASIA: "liquefied natural gas", COAL: "coal", URANIUM: "uranium",
      COPPER: "copper", ALUMINUM: "aluminium", NICKEL: "nickel", ZINC: "zinc",
      IRON_ORE: "iron ore", TIN: "tin", LEAD: "lead",
      GOLD: "gold", SILVER: "silver",
      CORN: "maize corn", WHEAT: "wheat", RICE: "rice", SOYBEANS: "soybeans",
      SUGAR: "sugar", COFFEE: "coffee", COCOA: "cocoa", COTTON: "cotton",
      RUBBER: "rubber", LOGS: "timber logs", SAWNWOOD: "sawnwood timber",
      EURUSD: "euro dollar exchange rate",
    };
    let _mktCatTabs = null;        // the commodities category ooSubtabs handle
    let _mktView = "cards";         // "cards" | "families" (Slice 5; default = no regression)
    function selectCommodityCat(key) {
      // Button/ARIA state is owned by the ooSubtabs component (universal
      // grammar, invariant #18); this callback only filters which category
      // section is visible. "__all" (the default lens) shows everything. The
      // family blocks carry the same .mkt-cat/data-cat, so this filters BOTH
      // the cards view and the families view.
      document.querySelectorAll("#mkt-dashboard .mkt-cat").forEach(el => {
        el.style.display = (key === "__all" || el.dataset.cat === key) ? "" : "none";
      });
    }
    function setMktView(v) { _mktView = v; renderDashboard(); }
    // Build one family per present category: its member series windowed to the
    // shared range, ready for renderFamilyGraphs (Slice 5).
    function commodityFamilies(present, seriesFor, from, to) {
      return present.map(([k, label]) => ({
        key: k === "__other" ? "__other" : k,
        label,
        series: seriesFor(k).map(s => {
          const pts = windowPricesRange(MKT_PRICES[s.symbol] || [], from, to);
          const last = pts.length ? pts[pts.length - 1] : null;
          return {
            label: s.name || s.symbol,
            unit: last ? `${last.currency}/${last.unit}` : "",
            points: pts.map(p => ({t: p.observed_on, v: p.price})),
          };
        }),
      }));
    }
    function renderDashboard() {
      if (!MKT_SERIES.length) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Window by ABSOLUTE dates [from,to] from the ooTimeScope control (no
      // longer a trailing `days` count).
      const from = _mktScope.from, to = _mktScope.to;
      // SHARED time axis (Slice 4): every card on the board is drawn against the
      // SAME [t0,t1] window so the timescales are coherent across all sources (a
      // monthly World-Bank series and a daily FRED series align on one calendar
      // axis). Falls back to the full data span when no window is set.
      const _span = mktDataSpan();
      const axT0 = from || _span.min, axT1 = to || _span.max;
      // Indices are NOT commodities (maintainer-ruled): they live in the
      // Indices tab; the board shows everything else, grouped by category.
      // The category comes straight from the series data (s.category), not a
      // guessed symbol map — never misfile an index as a commodity.
      const series = MKT_SERIES.filter(s => s.category !== "index");
      const byCat = {};
      for (const s of series) (byCat[s.category] || (byCat[s.category] = [])).push(s);
      // Category list is DATA-DRIVEN: only the categories actually present
      // among the loaded commodities (never an empty tab), in the declared
      // MKT_CATS display order; any unmapped category falls under "Other".
      const present = MKT_CATS.filter(([k]) => byCat[k]);
      const mappedKeys = new Set(MKT_CATS.map(([k]) => k));
      const otherCats = Object.keys(byCat).filter(k => !mappedKeys.has(k));
      if (otherCats.length) present.push(["__other", "Other"]);
      const sectionKey = ([k]) => k === "__other" ? "__other" : k;
      const seriesFor = k => k === "__other"
        ? otherCats.reduce((acc, c) => acc.concat(byCat[c]), []) : byCat[k];
      // FAMILIES view (Slice 5): one multi-series graph per category instead of N
      // cards — "as much data but with fewer graphs". Default stays Cards (the
      // existing per-card grid below), so there is no regression.
      if (_mktView === "families") {
        renderFamilyGraphs($("mkt-dashboard"), commodityFamilies(present, seriesFor, from, to), {});
        _renderMktViewToggle(t);
        _renderCommodityCatTabs(present, sectionKey, t);
        return;
      }
      $("mkt-dashboard").innerHTML = present.map(([k, label]) =>
        `<div class="mkt-cat" data-cat="${esc(sectionKey([k]))}" style="display:contents">` +
        `<div class="vsect" style="grid-column:1/-1">${esc(t(label))}</div>` +
        seriesFor(k).map(s => {
          const all = MKT_PRICES[s.symbol] || [];
          // RESPECT the window (invariant #16): never silently expand a narrow
          // window to the full history, never downsample within it. A sparse
          // window renders as honest dots (handled in dashChartSvg), so the
          // smallest scale no longer dumps the entire series — it shows exactly
          // the FULL-RESOLUTION points that fall in [from,to].
          const pts = windowPricesRange(all, from, to);
          const last = pts.length ? pts[pts.length-1] : (all.length ? all[all.length-1] : null);
          const first = pts.length ? pts[0] : null;
          let change = "";
          if (first && last && first.price) {
            const pct = (last.price - first.price) / first.price * 100;
            change = `<span class="pill ${pct>=0?'ok':'err'}">${pct>=0?'+':''}${pct.toFixed(1)}%</span>`;
          }
          const lv = last ? `${fmtNum(last.price)} <span class="muted">${esc(last.currency)}/${esc(last.unit)}</span>` : '—';
          // The TITLE is its own clickable affordance: it investigates the
          // commodity's coverage in the corpus via the analysis window
          // (openAnalysisFor — the universal corpora object). stopPropagation
          // keeps the card's own chartSymbol click (the price detail) intact;
          // the query comes from the curated COMMODITY_QUERY seed map, else the
          // series display name. The caveat is the maintainer's binding rule:
          // this surfaces co-occurrence in the corpus, NEVER causation.
          const q = COMMODITY_QUERY[s.symbol] || s.name || s.symbol;
          // Carry the commodity identity so the analysis window's Price subtab can
          // overlay this commodity's price curve with the term's corpus coverage.
          const cOpts = esc(JSON.stringify({commodity: {symbol: s.symbol, name: s.name, unit: last ? `${last.currency}/${last.unit}` : ""}}));
          // The GRAPH is a first-class entry into the analysis WINDOW (ledger
          // MARKETS item 4): a clear "Analyse ↗" affordance UNDER the chart opens
          // the commodity's keyword-family corpus via openAnalysisFor (the same
          // opener the title ⊞ already uses — NOT a duplicate opener). The card
          // body keeps its chartSymbol price detail + correlation (the Desk
          // lesson: never silently lose a tool); stopPropagation keeps the two
          // paths distinct. The term is the curated COMMODITY_QUERY family seed,
          // else the real series name/symbol — never a fabricated family. The
          // window's Price subtab OVERLAYS the price curve with the term's corpus
          // coverage timeline (the commodity identity rides along in cOpts, below).
          return `<div class="stat" style="cursor:pointer" title="open detail + correlation"
              onclick="chartSymbol(${esc(JSON.stringify(s.symbol))}, ${esc(JSON.stringify(last?last.unit:''))})">
            <div style="display:flex;justify-content:space-between;align-items:baseline">
              <button type="button" title="${esc(s.name || s.symbol)}"
                style="background:none;border:none;padding:0;margin:0;font:inherit;font-weight:700;color:var(--accent);cursor:pointer;text-decoration:none"
                onclick="event.stopPropagation(); openAnalysisFor(${esc(JSON.stringify(q))}, ${cOpts})">${esc(s.symbol)} ⊞</button> ${change}</div>
            <div class="muted" style="font-size:12px;margin:2px 0 6px">${lv}</div>
            ${dashChartSvg(pts, last ? `${last.currency}/${last.unit}` : "", {t0: axT0, t1: axT1})}
            <div style="margin-top:4px"><button class="tiny secondary" type="button"
                title="${esc(t("Open this in the analysis window — its corpus coverage"))}"
                onclick="event.stopPropagation(); openAnalysisFor(${esc(JSON.stringify(q))}, ${cOpts})">${esc(t("Analyse"))} ↗</button></div></div>`;
        }).join("") + `</div>`
      ).join("");
      _renderMktViewToggle(t);
      _renderCommodityCatTabs(present, sectionKey, t);
    }
    // The Cards/Families view toggle (Slice 5) — only meaningful with >1 category;
    // default Cards (no regression). Reuses the chip grammar.
    function _renderMktViewToggle(t) {
      const tog = $("mkt-viewtoggle");
      if (!tog) return;
      tog.innerHTML = `<span class="muted" style="font-size:12px;margin-right:2px">${esc(t("View"))}:</span>`
        + [["cards", "Cards"], ["families", "Families"]].map(([k, lbl]) =>
            `<button type="button" class="chip${_mktView === k ? " on" : ""}" data-view="${k}"
               onclick="setMktView(${esc(JSON.stringify(k))})">${esc(t(lbl))}</button>`).join("");
    }
    // Category SUB-TABS (universal subtab grammar, invariant #18): the nav from the
    // categories actually present, with an "All" default lens (like Home families).
    // Skip the nav entirely when only one category is present. Shared by BOTH the
    // cards view and the families view (the .mkt-cat data-cat filter works in both).
    function _renderCommodityCatTabs(present, sectionKey, t) {
      const catNav = $("commodities-cats");
      if (!catNav) return;
      if (present.length > 1) {
        catNav.style.display = "";
        catNav.innerHTML =
          `<button class="active" data-tab="__all">${esc(t("All"))}</button>`
          + present.map(([k, label]) =>
              `<button data-tab="${esc(sectionKey([k]))}">${esc(t(label))}</button>`).join("");
        _mktCatTabs = ooSubtabs(catNav, selectCommodityCat, {initial: "__all"});
      } else {
        catNav.style.display = "none";
        catNav.innerHTML = "";
        _mktCatTabs = null;
        selectCommodityCat("__all");
      }
    }

    async function loadMarketData(btn) {
      btn.disabled = true;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) { btn.disabled = false; return; }
      const status = $("mkt-dash-status");
      status.textContent = "Importing official feeds… (downloads CSVs, may take a moment)";
      try {
        const r = await api("/api/markets/feeds/import-all", {method: "POST"});
        status.textContent = `Imported ${r.points_imported} point(s) across ${r.feeds} feeds${r.failed?`, ${r.failed} failed`:""}.`;
        _renderFeedVerdicts("mkt-verdicts", r, "");
        for (const k in MKT_PRICES) delete MKT_PRICES[k];
        await loadDashboard();
        if (_mktConfigLoaded) loadFeeds();
        toast("Market data loaded.");
      } catch (e) { status.textContent = ""; toast("Load failed: " + e.message, "err"); }
      finally { btn.disabled = false; }
    }

    function toggleMktConfig() {
      const el = $("mkt-config"), open = el.style.display === "none";
      el.style.display = open ? "" : "none";
      $("mkt-config-caret").textContent = open ? "▾" : "▸";
      if (open && !_mktConfigLoaded) { _mktConfigLoaded = true; loadMarketConfig(); }
    }

    async function loadMarketConfig() {
      try {
        const sources = await api("/api/sources");
        $("mkt-source").innerHTML = sources.map(s =>
          `<option value="${s.id}">${esc(s.name)} (${esc(s.domain)})</option>`).join("")
          || '<option value="">(no sources — add one first)</option>';
      } catch (e) { /* leave as-is */ }
      loadFeeds(); loadRules();
    }

    async function loadRules() {
      try {
        const d = await api("/api/markets/rules");
        const t = $("mkt-rules");
        t.innerHTML = "<tr><th>Symbol</th><th>Category</th><th>Source</th><th>Last status</th><th></th></tr>" +
          (d.rules.length ? d.rules.map(r => `<tr>
            <td><strong>${esc(r.symbol)}</strong></td><td class="muted">${esc(r.category)}</td>
            <td class="muted">${esc(r.source_name||"")}</td>
            <td class="muted" style="font-size:12px;max-width:240px">${esc(r.last_status||"never run")}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="runMarketRule(${r.id})" title="Fetch once and apply the rule">Test</button>
              <button class="tiny secondary" onclick="chartSymbol(${esc(JSON.stringify(r.symbol))}, ${esc(JSON.stringify(r.unit||''))})">Chart</button>
              <button class="tiny danger" onclick="deleteMarketRule(${r.id})">Delete</button></td></tr>`).join("")
            : `<tr><td colspan="5" class="muted">No extraction rules. Feeds cover most needs; add a rule below to scrape a price off a specific page.</td></tr>`);
      } catch (e) { /* rules optional */ }
    }

    // -- Official CSV feeds ------------------------------------------------- //
    async function loadFeeds() {
      try {
        const d = await api("/api/markets/feeds");
        const t = $("feed-table");
        if (!d.feeds.length) { t.innerHTML = `<tr><td class="muted">No feeds configured.</td></tr>`; return; }
        t.innerHTML = "<tr><th>Series</th><th>Symbol</th><th>Unit</th><th>Stored</th><th></th></tr>" +
          d.feeds.map(f => `<tr>
            <td>${esc(f.name)}<div class="muted" style="font-size:12px">${esc(f.market||"")}</div></td>
            <td><strong>${esc(f.symbol)}</strong></td>
            <td class="muted">${esc(f.currency)}/${esc(f.unit)}</td>
            <td class="muted">${f.points}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="importFeed(${esc(JSON.stringify(f.key))})">Import</button>
              <button class="tiny secondary" onclick="chartSymbol(${esc(JSON.stringify(f.symbol))}, ${esc(JSON.stringify(f.unit))})">Chart</button>
            </td></tr>`).join("");
      } catch (e) { /* feeds optional */ }
    }

    async function importFeed(key) {
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) return;
      toast("Importing feed… (downloads a CSV, may take a moment)");
      try {
        const r = await api(`/api/markets/feeds/${encodeURIComponent(key)}/import`, {method: "POST"});
        toast(`Imported ${r.imported} new point(s) for ${r.symbol} (${r.skipped_existing} already had).`);
        delete MKT_PRICES[r.symbol]; loadFeeds(); loadDashboard();
      } catch (e) { toast("Import failed: " + e.message, "err"); }
    }

    async function importCustomFeed() {
      const body = {
        url: $("feed-url").value.trim(),
        symbol: $("feed-symbol").value.trim(),
        unit: $("feed-unit").value.trim() || "t",
        currency: $("feed-currency").value.trim() || "USD",
        market: $("feed-market").value.trim() || null,
        date_column: $("feed-datecol").value.trim() || null,
        value_column: $("feed-valcol").value.trim() || null,
      };
      if (!body.url || !body.symbol) { toast("URL and symbol are required.", "err"); return; }
      $("feed-result").textContent = "Downloading and importing…";
      try {
        const r = await api("/api/markets/feeds/import-url", {method: "POST", body: JSON.stringify(body)});
        $("feed-result").innerHTML = `<span class="pill ok">imported</span> ${r.imported} new point(s) for ` +
          `${esc(r.symbol)} (${r.skipped_existing} already present, ${r.received} in feed).`;
        toast("Feed imported."); delete MKT_PRICES[body.symbol]; loadFeeds(); loadDashboard();
      } catch (e) { $("feed-result").textContent = ""; toast("Import failed: " + e.message, "err"); }
    }

    async function addMarketRule() {
      const body = {
        source_id: Number($("mkt-source").value),
        symbol: $("mkt-symbol").value.trim(),
        label: $("mkt-label").value.trim() || null,
        url: $("mkt-url").value.trim(),
        selector: $("mkt-selector").value.trim(),
        attribute: $("mkt-attr").value.trim() || null,
        value_regex: $("mkt-regex").value.trim() || null,
        currency: $("mkt-currency").value.trim() || "USD",
        unit: $("mkt-unit").value.trim() || "kg",
        market: $("mkt-market").value.trim() || null,
        category: "commodity",
      };
      if (!body.source_id || !body.symbol || !body.url || !body.selector) {
        toast("Source, symbol, URL and selector are required.", "err"); return;
      }
      try {
        await api("/api/markets/rules", {method: "POST", body: JSON.stringify(body)});
        toast("Rule added.");
        ["mkt-symbol","mkt-label","mkt-url","mkt-selector","mkt-attr","mkt-regex","mkt-market"]
          .forEach(id => $(id).value = "");
        loadRules();
      } catch (e) { toast("Add failed: " + e.message, "err"); }
    }

    async function runMarketRule(id) {
      toast("Fetching and applying rule…");
      try {
        const o = await api(`/api/markets/rules/${id}/run`, {method: "POST"});
        if (o.status === "stored_price")
          toast(`Stored ${o.value} for ${o.symbol} (${o.observed_on}).`);
        else if (o.status === "duplicate_price")
          toast(`Already had a point for ${o.symbol} today (${o.value}).`, "warn");
        else
          toast(`${o.status}: ${o.reason || ""}`, "err");
        delete MKT_PRICES[o.symbol]; loadRules(); loadDashboard();
      } catch (e) { toast("Run failed: " + e.message, "err"); }
    }

    async function deleteMarketRule(id) {
      if (!confirm("Delete this rule? Stored price history is kept.")) return;
      try { await api(`/api/markets/rules/${id}`, {method: "DELETE"}); toast("Rule deleted."); loadRules(); }
      catch (e) { toast("Delete failed: " + e.message, "err"); }
    }

    // ===== THE chart toolkit (maintainer-ruled: ONE component for every =====
    // chart surface). Honesty rules built in: the FULL series renders within
    // the visible window -- never downsampled, never thinned; SPARSE series
    // render as honest POINTS with n shown and an early-corpus caveat (a line
    // only when density supports it; no interpolation faking a curve).
    // Interactions: wheel = time zoom (cursor-anchored), drag = pan,
    // hover = crosshair readout, click = pin exact X/Y, dblclick = reset,
    // legend chips toggle series.
    function ooChart(el, seriesList, opts = {}) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      el.innerHTML = "";
      const W = Math.max(320, Math.min(el.clientWidth || 680, opts.maxWidth || 900));
      const H = opts.height || 220, padL = 52, padR = 10, padT = 10, padB = 24;
      const wrap = document.createElement("div");
      const cv = document.createElement("canvas");
      const dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr; cv.height = H * dpr;
      cv.style.cssText = `width:${W}px;height:${H}px;display:block;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:crosshair;touch-action:none`;
      const legend = document.createElement("div");
      legend.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;font-size:12px;margin-top:4px;align-items:center";
      const readout = document.createElement("div");
      readout.className = "hint"; readout.style.minHeight = "18px";
      wrap.appendChild(cv); wrap.appendChild(legend); wrap.appendChild(readout); el.appendChild(wrap);

      const toMs = (x) => {
        if (typeof x === "number") return x;
        const wk = /^(\d{4})-W(\d{2})$/.exec(x);   // ISO week -> its Monday
        if (wk) {
          const jan4 = Date.UTC(+wk[1], 0, 4);
          const dow = (new Date(jan4).getUTCDay() + 6) % 7;
          return jan4 - dow * 864e5 + (+wk[2] - 1) * 7 * 864e5;
        }
        if (/^\d{4}-\d{2}$/.test(x)) return Date.parse(x + "-01");
        return Date.parse(x);
      };
      const all = seriesList.map((s, i) => ({
        label: s.label || `#${i + 1}`, unit: s.unit || "",
        color: s.color || ["var(--accent)", "var(--ok)", "var(--warn)", "var(--err)"][i % 4],
        pts: (s.points || []).map(p => ({t: toMs(p.t), v: +p.v})).filter(p => isFinite(p.t) && isFinite(p.v))
              .sort((a, b) => a.t - b.t),
        hidden: false,
      })).filter(s => s.pts.length);
      if (!all.length) { el.innerHTML = `<div class="muted">${esc(t9("no data points yet"))}</div>`; return; }
      const tMin = Math.min(...all.map(s => s.pts[0].t)), tMax = Math.max(...all.map(s => s.pts[s.pts.length - 1].t));
      const span0 = Math.max(tMax - tMin, 1);
      let t0 = tMin, t1 = tMax, pinned = null, pinnedS = null;
      const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
      const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n) || "#888";
      const fmtV = (v) => (typeof fmtNum === "function") ? fmtNum(v) : String(v);
      const fmtT = (ms) => new Date(ms).toISOString().slice(0, 10);
      // a11y (audit PR G): the canvas is opaque to screen readers — give it a
      // role + translated summary, and a visually-hidden per-series data table.
      const allV = all.flatMap(s => s.pts.map(p => p.v));
      cv.setAttribute("role", "img");
      cv.setAttribute("aria-label", _chartAria(
        all.map(s => s.label).join(", "), allV.length, fmtT(tMin), fmtT(tMax),
        fmtV(Math.min(...allV)), fmtV(Math.max(...allV))));
      const srWrap = document.createElement("div");
      srWrap.className = "sr-only";
      srWrap.innerHTML = all.map(
        s => _chartSrTable(s.pts.map(p => ({date: fmtT(p.t), value: fmtV(p.v)})), s.label)).join("");
      wrap.appendChild(srWrap);
      const plotW = W - padL - padR, plotH = H - padT - padB;
      const Xof = (ms) => padL + plotW * ((ms - t0) / Math.max(t1 - t0, 1));
      // Indexed mode (opts.indexed, maintainer-ruled 2026-06-17): each series is
      // rebased to 100 at its first value in the VISIBLE window, so series of
      // DIFFERENT units (e.g. article coverage + a commodity price) co-move on ONE
      // shared axis WITHOUT conflating magnitudes — an honest RELATIVE view (the
      // hover still shows the REAL value/unit). _base is set per draw on the
      // persistent series so visible() copies and the hover inherit it. When
      // opts.indexed is off, pv() is the identity, so every existing chart is
      // byte-for-byte unchanged.
      const pv = (s, p) => (opts.indexed && s._base) ? (p.v / s._base * 100) : p.v;
      // Log-Y mode (opts.logY, maintainer-ruled 2026-06-17 markets revamp): the
      // y-axis maps log10(value) so series spanning orders of magnitude (a 5000-pt
      // index next to a 130 OECD index) read together; labels + hover still show
      // the REAL value (vtInv back-transforms the gridline value). Identity when
      // off, so every existing chart is byte-for-byte unchanged (the same additive
      // contract as opts.indexed). zeroBase is ignored under logY (log(0) is -∞).
      const LOGEPS = 1e-9;
      const vt = (v) => opts.logY ? Math.log10(Math.max(v, LOGEPS)) : v;   // value -> axis space
      const vtInv = (d) => opts.logY ? Math.pow(10, d) : d;                // axis space -> value (labels)

      function visible() {
        return all.filter(s => !s.hidden).map(s => ({...s, vis: s.pts.filter(p => p.t >= t0 && p.t <= t1)}));
      }
      function draw() {
        ctx.clearRect(0, 0, W, H);
        if (opts.indexed) for (const s of all) {        // rebase each series to 100 at its first visible value
          const vis = s.pts.filter(p => p.t >= t0 && p.t <= t1);
          const fnz = vis.find(p => p.v !== 0);
          s._base = fnz ? fnz.v : (vis.length ? (vis[0].v || 1) : 1);
        }
        const vs = visible();
        const ys = vs.flatMap(s => s.vis.map(p => vt(pv(s, p))));
        if (!ys.length) { readout.textContent = t9("no points in this window — zoom out (double-click)"); return; }
        const yMin = (opts.zeroBase && !opts.logY) ? Math.min(0, ...ys) : Math.min(...ys);
        const yMax = Math.max(...ys), ySpan = (yMax - yMin) || 1;
        const Yof = (v) => padT + plotH * (1 - (v - yMin) / ySpan);
        ctx.font = "10px sans-serif"; ctx.fillStyle = cssVar("--muted"); ctx.strokeStyle = cssVar("--border");
        for (let g = 0; g <= 3; g++) {                     // discrete gridlines, labelled
          const v = yMin + ySpan * g / 3, y = Yof(v);
          ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
          ctx.setLineDash([]); ctx.textAlign = "right"; ctx.fillText(fmtV(vtInv(v)), padL - 4, y + 3);
        }
        const nTicks = Math.max(2, Math.min(6, Math.floor(plotW / 110)));
        ctx.textAlign = "center";
        for (let g = 0; g <= nTicks; g++) {
          const ms = t0 + (t1 - t0) * g / nTicks;
          ctx.fillText(fmtT(ms), Math.min(Math.max(Xof(ms), padL + 28), W - padR - 28), H - 8);
        }
        for (const s of vs) {
          if (!s.vis.length) continue;
          const n = s.vis.length, pxPer = plotW / Math.max(n - 1, 1);
          const barMode = n < _SPARSE_BAR_MAX;              // Item Y: n<10 -> bars, n>=10 -> line
          ctx.strokeStyle = s.color.startsWith("var(") ? cssVar(s.color.slice(4, -1)) : s.color;
          ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 1.8;
          if (barMode) {
            // Bars anchor to the plot baseline Yof(yMin): true ZERO for zeroBase
            // (count) series, else the window-MIN which the gridlines LABEL (price
            // levels) — never a fabricated zero. Bars sit at their TRUE time x; a 2px
            // cap marks the value so a flush/equal/single point stays visible.
            const baseY = Yof(yMin);
            const bw = Math.max(3, Math.min(plotW / (n * 1.5), 26));
            for (const p of s.vis) {
              const x = Xof(p.t), y = Yof(vt(pv(s, p)));
              ctx.globalAlpha = 0.72; ctx.fillRect(x - bw / 2, y, bw, Math.max(0, baseY - y));
              ctx.globalAlpha = 1;    ctx.fillRect(x - bw / 2, y - 1, bw, 2);
            }
          } else {
            ctx.beginPath();
            s.vis.forEach((p, i) => { const x = Xof(p.t), y = Yof(vt(pv(s, p))); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
            ctx.stroke();
            if (pxPer > 9) {                                 // honest dots on a roomy line
              for (const p of s.vis) { ctx.beginPath(); ctx.arc(Xof(p.t), Yof(vt(pv(s, p))), 2, 0, 7); ctx.fill(); }
            }
          }
        }
        if (pinned) {
          const x = Xof(pinned.t), y = Yof(vt(opts.indexed && pinnedS ? pv(pinnedS, pinned) : pinned.v));
          ctx.strokeStyle = cssVar("--muted"); ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke(); ctx.setLineDash([]);
          ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.stroke();
        }
        legend.innerHTML = vs.map((s) => {
          const i = all.indexOf(all.find(a => a.label === s.label));
          return `<span style="cursor:pointer;${s.hidden ? "opacity:.4" : ""}" onclick="this._oo&&this._oo()" data-oo-leg="${i}">` +
            `<span style="display:inline-block;width:14px;height:0;border-top:3px solid ${s.color};vertical-align:middle;margin-inline-end:4px"></span>` +
            `${esc(s.label)} <span class="muted">n=${s.vis.length}${s.unit ? " \u00b7 " + esc(s.unit) : ""}</span></span>`;
        }).join("");
        legend.querySelectorAll("[data-oo-leg]").forEach(elm => {
          elm._oo = () => { all[+elm.dataset.ooLeg].hidden = !all[+elm.dataset.ooLeg].hidden; draw(); };
        });
      }
      function nearest(ev) {
        const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left;
        const ms = t0 + (t1 - t0) * (mx - padL) / plotW;
        let best = null;
        for (const s of visible()) for (const p of s.vis) {
          const d = Math.abs(p.t - ms);
          if (!best || d < best.d) best = {d, p, s};
        }
        return best;
      }
      cv.addEventListener("wheel", (ev) => {
        ev.preventDefault();
        const r = cv.getBoundingClientRect();
        const anchor = t0 + (t1 - t0) * ((ev.clientX - r.left) - padL) / plotW;
        const f = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
        t0 = Math.max(tMin, anchor - (anchor - t0) * f);
        t1 = Math.min(tMax, anchor + (t1 - anchor) * f);
        if (t1 - t0 < 3600e3) { const c = (t0 + t1) / 2; t0 = c - 1800e3; t1 = c + 1800e3; }
        draw();
      }, {passive: false});
      let dragX = null, dragT = null;
      cv.addEventListener("pointerdown", (ev) => { dragX = ev.clientX; dragT = [t0, t1]; cv.setPointerCapture(ev.pointerId); });
      cv.addEventListener("pointermove", (ev) => {
        if (dragX != null) {
          const dt = (dragX - ev.clientX) / plotW * (dragT[1] - dragT[0]);
          const span = dragT[1] - dragT[0];
          t0 = Math.max(tMin, Math.min(dragT[0] + dt, tMax - span));
          t1 = t0 + span; draw(); return;
        }
        const b = nearest(ev);
        if (b) {
          const ix = opts.indexed && b.s._base ? ` \u00b7 idx ${Math.round(pv(b.s, b.p))}` : "";
          readout.textContent = `${b.s.label}: ${fmtV(b.p.v)}${b.s.unit ? " " + b.s.unit : ""}${ix} \u00b7 ${fmtT(b.p.t)}`;
        }
      });
      cv.addEventListener("pointerup", (ev) => {
        if (dragX != null && Math.abs(ev.clientX - dragX) < 4) {
          const b = nearest(ev);
          pinned = b ? b.p : null; pinnedS = b ? b.s : null;
          if (b) readout.innerHTML = `<b>${esc(b.s.label)}: ${fmtV(b.p.v)}${b.s.unit ? " " + esc(b.s.unit) : ""} \u00b7 ${fmtT(b.p.t)}</b> <span class="muted">${esc(t9("(pinned — click empty space or re-click to move)"))}</span>`;
          draw();
        }
        dragX = null;
      });
      cv.addEventListener("dblclick", () => { t0 = tMin; t1 = tMax; pinned = null; pinnedS = null; draw(); });
      draw();
      return {redraw: draw};
    }

    function sparkSvg(points) {
      if (!points.length) return '<div class="muted">No price points stored yet — use “Test” to fetch one.</div>';
      const w = 680, h = 180, pad = 34;
      const ys = points.map(p => p.price);
      const minY = Math.min(...ys), maxY = Math.max(...ys), spanY = (maxY - minY) || 1;
      const X = i => pad + (w - 2*pad) * (points.length < 2 ? 0.5 : i/(points.length-1));
      const Y = v => h - pad - (h - 2*pad) * ((v - minY)/spanY);
      const line = points.map((p,i) => `${X(i).toFixed(1)},${Y(p.price).toFixed(1)}`).join(" ");
      const dots = points.map((p,i) =>
        `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.price).toFixed(1)}" r="2.5" fill="var(--accent)"></circle>`).join("");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:${w}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px">
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${line}"></polyline>${dots}
        <text x="${pad}" y="16" fill="var(--muted)" font-size="11">${maxY}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11">${minY}</text>
        <text x="${w-pad}" y="${h-8}" fill="var(--muted)" font-size="11" text-anchor="end">${esc(points[points.length-1].observed_on)}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11" dx="40">${esc(points[0].observed_on)}</text>
      </svg>`;
    }

    async function chartSymbol(symbol, unit) {
      const el = $("mkt-chart");
      el.innerHTML = `<div class="muted">Loading ${esc(symbol)}…</div>`;
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`);
        el.innerHTML = `<h2 style="margin:0 0 8px;font-size:14px;color:var(--muted)">${esc(symbol)} — ${d.count} point(s)
            <button class="tiny secondary" onclick="correlateSymbol(${esc(JSON.stringify(symbol))})" title="Correlate price change vs news volume">Correlate with news</button></h2>` +
          `<div id="mkt-chart-oo"></div><div id="mkt-corr" class="hint" style="margin-top:8px"></div>`;
        ooChart($("mkt-chart-oo"), [{label: symbol, unit: unit || (d.prices[0] && d.prices[0].unit) || "",
          points: d.prices.map(p => ({t: p.observed_on, v: p.price}))}], {height: 230});
      } catch (e) {
        el.innerHTML = `<div class="note err">Chart unavailable: ${esc(e.message)} ` +
          `<span class="muted">(commodity analysis endpoints require the [analysis] extra)</span></div>`;
      }
    }

    // Indices detail — the SAME interactive ooChart the commodity board uses
    // (invariant #16). Indices are stored as CommodityPrice rows, so the full,
    // un-thinned series comes from /api/commodities/{symbol}/prices (never the
    // truncated board spark). Mirrors chartSymbol; renders into #idx-chart.
    async function indexDetail(symbol, name, currency) {
      const el = $("idx-chart"); if (!el) return;
      el.innerHTML = `<div class="muted">Loading ${esc(name || symbol)}…</div>`;
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`);
        el.innerHTML = `<h2 style="margin:0 0 8px;font-size:14px;color:var(--muted)">${esc(name || symbol)} — ${d.count} point(s)</h2>` +
          `<div id="idx-chart-oo"></div>`;
        ooChart($("idx-chart-oo"), [{label: name || symbol,
          unit: currency || (d.prices[0] && d.prices[0].currency) || "",
          points: d.prices.map(p => ({t: p.observed_on, v: p.price}))}], {height: 230});
        el.scrollIntoView({behavior: "smooth", block: "nearest"});
      } catch (e) {
        el.innerHTML = `<div class="note err">Chart unavailable: ${esc(e.message)}</div>`;
      }
    }

    async function correlateSymbol(symbol) {
      // Correlate the symbol's daily price change against article volume for the
      // current search query (if any). Honest output: real coefficient/p-value/n.
      const q = $("q").value.trim();
      $("mkt-chart").innerHTML = `<div class="muted">Correlating ${esc(symbol)} with news…</div>`;
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/correlation` +
          (q ? "?query=" + encodeURIComponent(q) : ""));
        let body;
        if (d.insufficient_data) {
          body = `<span class="pill warn">insufficient data</span> only ${d.n} overlapping day(s) — need more price + article history.`;
        } else {
          const sig = d.significant ? '<span class="pill ok">significant</span>' : '<span class="pill">not significant</span>';
          body = `<div>method <strong>${esc(d.method)}</strong>, n=${d.n}, ` +
            `coefficient <strong>${d.coefficient.toFixed(3)}</strong>, p=${d.p_value.toExponential(2)} ${sig}</div>`;
        }
        $("mkt-chart").innerHTML =
          `<h2 style="margin:0 0 8px;font-size:14px;color:var(--muted)">${esc(symbol)} vs news${q?` — “${esc(q)}”`:""}</h2>` +
          body + `<div class="hint" style="margin-top:6px">${esc(d.caveat || "")}</div>`;
      } catch (e) {
        $("mkt-chart").innerHTML = `<div class="note err">Correlation unavailable: ${esc(e.message)}</div>`;
      }
    }

    // ===== Universal subtab component (keystone, maintainer-ruled 2026-06-13) ==
    // ONE navigation grammar everywhere: a <nav class="tabs"> of buttons each
    // carrying data-tab="KEY". Click OR arrow-keys/Home/End select; the component
    // owns the visible state (.active + role=tab/aria-selected + roving tabindex),
    // labels are plain DOM text (auto-translated ×12), and titled buttons get the
    // hover-bubble convention for free. onSelect(key) does the per-surface panel
    // switch. Returns { select, paint } for programmatic switching (e.g. opening a
    // modal on a given tab). Reused by Insights, Settings and the corpus window.
    function ooSubtabs(nav, onSelect, opts) {
      if (!nav) return null;
      opts = opts || {};
      const btns = Array.prototype.slice.call(nav.querySelectorAll("[data-tab]"));
      if (!btns.length) return null;
      nav.setAttribute("role", "tablist");
      btns.forEach(b => { b.setAttribute("role", "tab"); if (!b.getAttribute("type")) b.type = "button"; });
      function paint(key) {            // visuals + a11y only — never fires onSelect
        let hit = null;
        btns.forEach(b => {
          const on = b.dataset.tab === key;
          b.classList.toggle("active", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
          b.tabIndex = on ? 0 : -1;
          if (on) hit = b;
        });
        return hit;
      }
      function select(key, focus) {    // the canonical switch: paint + callback
        const b = paint(key);
        if (!b) return false;
        if (focus) b.focus();
        if (typeof onSelect === "function") onSelect(key);
        return true;
      }
      if (!nav._ooWired) {
        nav._ooWired = true;
        nav.addEventListener("click", e => {
          const b = e.target.closest("[data-tab]");
          if (b && nav.contains(b)) select(b.dataset.tab);
        });
        nav.addEventListener("keydown", e => {
          const i = btns.indexOf(document.activeElement);
          if (i < 0) return;
          let j = i;
          if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % btns.length;
          else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + btns.length) % btns.length;
          else if (e.key === "Home") j = 0;
          else if (e.key === "End") j = btns.length - 1;
          else return;
          e.preventDefault();
          select(btns[j].dataset.tab, true);
        });
      }
      // Initial state: sync ARIA/roving-tabindex to the HTML-marked active button
      // WITHOUT firing onSelect (each surface already renders its default panel),
      // unless opts.initial explicitly asks to switch+fire.
      if (opts.initial !== undefined) select(opts.initial);
      else paint((btns.filter(b => b.classList.contains("active"))[0] || btns[0]).dataset.tab);
      return { select: select, paint: paint };
    }

    // ooTimeScope — ONE reusable time-range control (maintainer UX: "dates +
    // a visual range bar", NOT 5 buttons). Renders into `container`:
    //   (a) From / To <input type=date> fields,
    //   (b) a horizontal track with the selected span + two draggable handles,
    //   (c) quick presets (1M·6M·1Y·5Y·All) as one-click SHORTCUTS.
    // The three stay in sync; onChange({from,to}) fires (ISO YYYY-MM-DD) on any
    // change. Exposes { set(from,to), get() }. Pure DOM + CSS, no deps,
    // deterministic. Drag math mirrors the temporal-map slider helpers
    // (value↔pixel over [min,max], here in days since epoch). Wired to Markets
    // now; reusable later (Insights / agenda / corpus windows).
    const _TS_DAY = 86400000;
    function _tsParse(iso) {                       // ISO date -> integer days since epoch (UTC)
      if (!iso) return null;
      const t = Date.parse(iso + "T00:00:00Z");
      return isFinite(t) ? Math.round(t / _TS_DAY) : null;
    }
    function _tsIso(days) {                        // integer days since epoch -> ISO date
      return new Date(days * _TS_DAY).toISOString().slice(0, 10);
    }
    // Quick-preset spans in CALENDAR units, anchored to the data's max date.
    // "All" = the full [min,max] span. Labels are keyed for ×12 translation.
    const _TS_PRESETS = [
      ["1M", d => { const x = new Date(d * _TS_DAY); x.setUTCMonth(x.getUTCMonth() - 1); return Math.round(x.getTime() / _TS_DAY); }],
      ["6M", d => { const x = new Date(d * _TS_DAY); x.setUTCMonth(x.getUTCMonth() - 6); return Math.round(x.getTime() / _TS_DAY); }],
      ["1Y", d => { const x = new Date(d * _TS_DAY); x.setUTCFullYear(x.getUTCFullYear() - 1); return Math.round(x.getTime() / _TS_DAY); }],
      ["5Y", d => { const x = new Date(d * _TS_DAY); x.setUTCFullYear(x.getUTCFullYear() - 5); return Math.round(x.getTime() / _TS_DAY); }],
      ["All", () => null],   // sentinel: clamp to min
    ];
    function ooTimeScope(container, opts) {
      if (!container) return null;
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const min = _tsParse(opts.min), max = _tsParse(opts.max);
      // Degrade loudly if the span is unusable (no/identical bounds).
      if (min == null || max == null || max <= min) {
        container.innerHTML = `<span class="hint muted">${esc(t("not enough data for a time range"))}</span>`;
        return { set: () => {}, get: () => ({from: opts.from || null, to: opts.to || null}) };
      }
      let from = _tsParse(opts.from); let to = _tsParse(opts.to);
      if (from == null) from = min; if (to == null) to = max;
      const clamp = v => Math.max(min, Math.min(max, v));
      from = clamp(from); to = clamp(to);
      if (from > to) { const s = from; from = to; to = s; }

      container.classList.add("ts");
      container.innerHTML =
        `<div class="ts-dates">
           <label>${esc(t("From"))} <input type="date" class="ts-from"></label>
           <label>${esc(t("To"))} <input type="date" class="ts-to"></label>
         </div>
         <div class="ts-bar" tabindex="-1">
           <div class="ts-track"></div><div class="ts-sel"></div>
           <div class="ts-handle ts-h-from" role="slider" tabindex="0"
                aria-label="${esc(t("From"))}"></div>
           <div class="ts-handle ts-h-to" role="slider" tabindex="0"
                aria-label="${esc(t("To"))}"></div>
         </div>
         <div class="ts-presets">` +
        _TS_PRESETS.map(([k]) =>
          `<button type="button" data-preset="${esc(k)}">${esc(t(k))}</button>`).join("") +
        `</div>`;

      const inFrom = container.querySelector(".ts-from");
      const inTo   = container.querySelector(".ts-to");
      const bar    = container.querySelector(".ts-bar");
      const sel    = container.querySelector(".ts-sel");
      const hFrom  = container.querySelector(".ts-h-from");
      const hTo    = container.querySelector(".ts-h-to");
      // date inputs carry the absolute bounds so the native picker is bounded.
      const minIso = _tsIso(min), maxIso = _tsIso(max);
      [inFrom, inTo].forEach(el => { el.min = minIso; el.max = maxIso; });

      function frac(v) { return (v - min) / (max - min); }     // value -> 0..1
      function paint() {
        inFrom.value = _tsIso(from); inTo.value = _tsIso(to);
        const a = frac(from) * 100, b = frac(to) * 100;
        sel.style.left = a + "%"; sel.style.width = (b - a) + "%";
        hFrom.style.left = a + "%"; hTo.style.left = b + "%";
        [[hFrom, from], [hTo, to]].forEach(([h, v]) => {
          h.setAttribute("aria-valuemin", minIso);
          h.setAttribute("aria-valuemax", maxIso);
          h.setAttribute("aria-valuenow", _tsIso(v));
        });
      }
      function fire() {
        if (typeof opts.onChange === "function") opts.onChange({from: _tsIso(from), to: _tsIso(to)});
      }
      function setRange(a, b, notify) {
        a = clamp(a); b = clamp(b);
        if (a > b) { const s = a; a = b; b = s; }
        const changed = a !== from || b !== to;
        from = a; to = b; paint();
        if (notify && changed) fire();
      }
      // x pixel within the bar -> value in [min,max] (mirrors sliderToT).
      function pxToVal(clientX) {
        const r = bar.getBoundingClientRect();
        const f = r.width ? Math.max(0, Math.min(1, (clientX - r.left) / r.width)) : 0;
        return Math.round(min + f * (max - min));
      }

      // -- pointer drag (mouse + touch via Pointer Events) ------------------ //
      let dragging = null;   // "from" | "to" | null
      function onDown(which, e) {
        dragging = which; e.preventDefault();
        (which === "from" ? hFrom : hTo).focus();
        try { e.target.setPointerCapture(e.pointerId); } catch (_) {}
      }
      function onMove(e) {
        if (!dragging) return;
        const v = pxToVal(e.clientX);
        if (dragging === "from") setRange(v, to, true); else setRange(from, v, true);
      }
      function onUp() { dragging = null; }
      hFrom.addEventListener("pointerdown", e => onDown("from", e));
      hTo.addEventListener("pointerdown", e => onDown("to", e));
      bar.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      // Click on the track (not a handle) moves the NEARER handle there.
      bar.addEventListener("pointerdown", e => {
        if (e.target.classList.contains("ts-handle")) return;
        const v = pxToVal(e.clientX);
        if (Math.abs(v - from) <= Math.abs(v - to)) setRange(v, to, true);
        else setRange(from, v, true);
      });

      // -- keyboard on handles (a11y plus) ---------------------------------- //
      function onKey(which, e) {
        let step = 0;
        if (e.key === "ArrowLeft" || e.key === "ArrowDown") step = -1;
        else if (e.key === "ArrowRight" || e.key === "ArrowUp") step = 1;
        else if (e.key === "PageDown") step = -30;
        else if (e.key === "PageUp") step = 30;
        else if (e.key === "Home") { which === "from" ? setRange(min, to, true) : setRange(from, from, true); e.preventDefault(); return; }
        else if (e.key === "End") { which === "from" ? setRange(to, to, true) : setRange(from, max, true); e.preventDefault(); return; }
        else return;
        e.preventDefault();
        if (which === "from") setRange(from + step, to, true); else setRange(from, to + step, true);
      }
      hFrom.addEventListener("keydown", e => onKey("from", e));
      hTo.addEventListener("keydown", e => onKey("to", e));

      // -- date inputs ------------------------------------------------------ //
      inFrom.addEventListener("change", () => { const v = _tsParse(inFrom.value); if (v != null) setRange(v, to, true); else paint(); });
      inTo.addEventListener("change",   () => { const v = _tsParse(inTo.value);   if (v != null) setRange(from, v, true); else paint(); });

      // -- presets (one-click shortcuts; from = max - span, to = max) ------- //
      container.querySelector(".ts-presets").addEventListener("click", e => {
        const b = e.target.closest("[data-preset]");
        if (!b) return;
        const def = _TS_PRESETS.find(([k]) => k === b.dataset.preset);
        if (!def) return;
        const startFn = def[1];
        const start = startFn(max);                 // null sentinel => "All"
        setRange(start == null ? min : start, max, true);
      });

      paint();
      return {
        set: (a, b) => setRange(_tsParse(a) ?? from, _tsParse(b) ?? to, false),
        get: () => ({from: _tsIso(from), to: _tsIso(to)}),
      };
    }

    // ---- ooTimeScope reuse for keyword-trend surfaces (Insights Explore +
    // the corpus window). The /api/insights/trend endpoint returns the FULL
    // bucketed series (no date params), so the window is applied CLIENT-SIDE by
    // FILTERING the already-fetched points — never refetched, never thinned
    // (invariant #16: the full-resolution series within the window is kept and
    // handed to the existing ooChart renderer UNCHANGED). The bucket key may be
    // YYYY-MM-DD (day), YYYY-MM (month) or YYYY-Www (ISO week); _trendBucketMs
    // mirrors ooChart's own toMs so the filter agrees with the renderer. ------ //
    function _trendBucketMs(key) {
      const wk = /^(\d{4})-W(\d{2})$/.exec(key);   // ISO week -> its Monday (UTC)
      if (wk) {
        const jan4 = Date.UTC(+wk[1], 0, 4);
        const dow = (new Date(jan4).getUTCDay() + 6) % 7;
        return jan4 - dow * 864e5 + (+wk[2] - 1) * 7 * 864e5;
      }
      if (/^\d{4}-\d{2}$/.test(key)) return Date.parse(key + "-01");
      return Date.parse(key);
    }
    function _trendBucketIso(key) {
      const ms = _trendBucketMs(key);
      return isFinite(ms) ? new Date(ms).toISOString().slice(0, 10) : null;
    }
    // Span (oldest -> newest bucket) as ISO dates, to bound the ooTimeScope.
    function _trendSpan(points) {
      let min = null, max = null;
      for (const p of (points || [])) {
        const iso = _trendBucketIso(p.date);
        if (!iso) continue;
        if (min === null || iso < min) min = iso;
        if (max === null || iso > max) max = iso;
      }
      return {min, max};
    }
    // Keep only buckets whose start falls in [from,to] (ISO YYYY-MM-DD); the
    // points keep their original resolution — no downsampling, ever.
    function _windowTrendPoints(points, from, to) {
      if (!from && !to) return points || [];
      const fromMs = from ? Date.parse(from) : -Infinity;
      const toMs = to ? Date.parse(to) : Infinity;
      return (points || []).filter(p => {
        const ms = _trendBucketMs(p.date);
        return isFinite(ms) && ms >= fromMs && ms <= toMs;
      });
    }
    // Default window = the last 1 year anchored to the data's MAX (never "now"),
    // or the whole span if it covers less than a year — mirrors mktDefaultWindow.
    function _trendDefaultWindow(span) {
      if (!span.min || !span.max) return {from: span.min, to: span.max};
      const maxD = new Date(span.max + "T00:00:00Z");
      const yearAgo = new Date(maxD); yearAgo.setUTCFullYear(maxD.getUTCFullYear() - 1);
      const from = yearAgo.toISOString().slice(0, 10);
      return {from: from > span.min ? from : span.min, to: span.max};
    }
    // Build (or rebuild) an ooTimeScope over a trend point series in `box`.
    // `redraw(windowedPoints)` re-renders the chart from the CLIENT-FILTERED
    // full-resolution points (invariant #16 — never downsampled/thinned; the
    // existing ooChart renderer is handed the windowed points unchanged).
    // ooTimeScope itself degrades loudly ("not enough data for a time range")
    // when the span is unusable. Returns the initial {from,to} so the caller's
    // first paint matches the control.
    function _buildTrendScope(box, points, redraw) {
      if (!box) return {from: null, to: null};
      const span = _trendSpan(points);
      if (!span.min || !span.max || span.min === span.max) {
        ooTimeScope(box, {});           // honest "not enough data" message
        return {from: null, to: null};  // caller paints the full (tiny) series
      }
      const def = _trendDefaultWindow(span);
      ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => redraw(_windowTrendPoints(points, from, to)),
      });
      return def;
    }

    let _insSubtabs = null, _setSubtabs = null, _corpusSubtabs = null;

    // -- Insights (keyword & entity analytics) ------------------------------ //
    const _insLoaded = new Set();

    function showInsightCat(cat) {
      // Button/ARIA state is owned by the ooSubtabs component (universal grammar);
      // this callback only switches the panel + lazy-loads the section once.
      document.querySelectorAll("#tab-insights .ins-view").forEach(v =>
        v.style.display = (v.id === "ins-" + cat) ? "" : "none");
      if (!_insLoaded.has(cat)) {
        _insLoaded.add(cat);
        if (cat === "trends") loadTrends();
        if (cat === "map") loadMap();
        if (cat === "sources") loadCitedSources();
        if (cat === "families") loadFamilies();
        if (cat === "supergroups") loadSuperGroups();
        if (cat === "convergence") loadConvergences();
        if (cat === "watches") loadWatches();
      }
    }

    // -- Corpus landscape: super-families by semantic kind (the "zoom out") --- //
    const _KIND_GROUPS = [
      {key: "person",   label: "People",  match: k => k === "person"},
      {key: "org",      label: "Orgs",    match: k => k === "org"},
      {key: "location", label: "Places",  match: k => k === "location"},
      {key: "entity",   label: "Other entities", match: k => !["person", "org", "location", "term"].includes(k)},
      {key: "term",     label: "Themes",  match: k => k === "term"},
    ];
    let _landscapeLoaded = false;
    async function loadLandscape(force) {
      if (_landscapeLoaded && !force) return;
      const box = $("ins-landscape");
      box.innerHTML = '<div class="muted" style="margin-top:8px">Loading…</div>';
      try {
        const d = await api("/api/insights/top?group=true&limit=200");
        _landscapeLoaded = true;
        const fams = d.terms || [];
        if (!fams.length) { box.innerHTML = '<div class="muted" style="margin-top:8px">No families yet — index the corpus.</div>'; return; }
        const cols = _KIND_GROUPS.map(g => {
          const items = fams.filter(f => g.match(f.kind)).slice(0, 16);
          if (!items.length) return "";
          const max = Math.max(...items.map(f => f.mentions), 1);
          const chips = items.map(f => {
            const scale = 0.82 + 0.5 * (f.mentions / max);     // size by prominence
            const fam = f.variants > 1;
            return `<button class="ls-chip" style="font-size:${(11.5*scale).toFixed(1)}px"
              title="${fam ? `family of ${f.variants}: ${esc((f.members||[]).map(m=>m.term).join(', '))} · ` : ""}${f.mentions} mentions — click to zoom in"
              onclick="pickTerm(${esc(JSON.stringify(f.term))})">${esc(f.term)}${fam ? `<span class="muted"> ·${f.variants}</span>` : ""}</button>`;
          }).join("");
          return `<div class="ls-col"><div class="ls-h">${g.label} <span class="muted">${items.length}</span></div><div class="ls-chips">${chips}</div></div>`;
        }).join("");
        box.innerHTML = `<div class="ls-grid">${cols}</div>`;
      } catch (e) { box.innerHTML = `<div class="muted" style="margin-top:8px">Could not load: ${esc(e.message)}</div>`; }
    }

    // -- Keyword families: review + manual merge/split ---------------------- //
    async function loadFamilies() {
      const list = $("fam-list");
      list.innerHTML = '<div class="muted">Loading…</div>';
      const kind = $("fam-kind").value;
      try {
        const [top, ov] = await Promise.all([
          api(`/api/insights/top?group=true&limit=80${kind ? "&kind=" + encodeURIComponent(kind) : ""}`),
          api("/api/insights/family/overrides"),
        ]);
        const fams = top.terms.filter(f => f.kind !== "term");
        list.innerHTML = fams.length ? fams.map(f => {
          const norms = JSON.stringify((f.members || []).map(m => m.normalized));
          const chips = (f.members || []).map(m =>
            `<button class="fam-chip" data-norm="${esc(m.normalized)}" data-kind="${esc(f.kind)}"
               onclick="familySplit(this)" title="split this form out">${esc(m.term)}${f.variants > 1 ? " ✕" : ""}</button>`).join("");
          return `<div class="fam-row">
            <input type="checkbox" class="fam-pick" data-norms="${esc(norms)}" data-kind="${esc(f.kind)}" data-label="${esc(f.term)}" aria-label="${esc(f.term)}">
            <div class="fam-body"><div><b>${esc(f.term)}</b> <span class="pill">${esc(f.kind)}</span>
              ${f.manual ? '<span class="pill ok">manual</span>' : ""}
              <span class="muted">· ${f.mentions} mentions</span></div>
              <div class="fam-chips">${chips}</div></div></div>`;
        }).join("") : '<div class="muted">No entity families yet — index the corpus first.</div>';
        renderFamOverrides(ov);
      } catch (e) { list.innerHTML = `<div class="muted">Could not load families: ${esc(e.message)}</div>`; }
    }

    function renderFamOverrides(ov) {
      const box = $("fam-overrides");
      if (!ov.families || !ov.families.length) { box.innerHTML = ""; return; }
      box.innerHTML = `<h2 style="font-size:13px;margin:0 0 6px">Your manual overrides</h2>` +
        ov.families.map(f => `<div class="fam-ov">
          <span>${f.split ? "split" : "merge"}: <b>${esc(f.label || f.family_key)}</b>
            <span class="muted">${esc((f.members || []).join(", "))}</span></span>
          <button class="ghost tiny" data-members="${esc(JSON.stringify(f.members || []))}" onclick="familyResetGroup(this)">reset</button>
        </div>`).join("");
    }

    async function familySplit(btn) {
      try {
        await api("/api/insights/family/split", {method: "POST",
          body: JSON.stringify({normalized: btn.dataset.norm, kind: btn.dataset.kind})});
        toast("Split out."); loadFamilies();
      } catch (e) { toast("Split failed: " + e.message, "err"); }
    }

    async function familyMerge() {
      const picks = [...document.querySelectorAll(".fam-pick:checked")];
      if (picks.length < 2) { toast("Tick at least two families to merge.", "err"); return; }
      const norms = picks.flatMap(p => JSON.parse(p.dataset.norms));
      const label = prompt("Name for the merged family:", picks[0].dataset.label || "");
      if (label === null) return;
      try {
        const r = await api("/api/insights/family/merge", {method: "POST",
          body: JSON.stringify({normalized: norms, label: label.trim() || undefined, kind: picks[0].dataset.kind})});
        $("fam-status").textContent = `Merged ${r.merged.length} forms into “${r.label}”.`;
        toast("Merged."); loadFamilies();
      } catch (e) { toast("Merge failed: " + e.message, "err"); }
    }

    async function familyResetGroup(btn) {
      const members = JSON.parse(btn.dataset.members);
      try {
        for (const n of members) await api("/api/insights/family/override?normalized=" + encodeURIComponent(n), {method: "DELETE"});
        toast("Override cleared."); loadFamilies();
      } catch (e) { toast("Reset failed: " + e.message, "err"); }
    }

    // -- Super-groups: groups of families ----------------------------------- //
    async function loadSuperGroups() {
      const box = $("sg-list");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const [sgs, top, rings] = await Promise.all([
          api("/api/insights/supergroups"),
          api("/api/insights/top?group=true&limit=200"),
          api("/api/insights/rings"),
        ]);
        $("sg-family-options").innerHTML = (top.terms || []).map(f =>
          `<option value="${esc(f.normalized)}">${esc(f.term)} (${f.mentions})</option>`).join("");
        $("sg-ring-options").innerHTML = (rings.rings || []).map(r =>
          `<option value="${esc(r.id)}">${esc(r.id)} — ${esc((r.languages || []).join("/"))}</option>`).join("");
        box.innerHTML = sgs.supergroups.length ? sgs.supergroups.map(sgCard).join("")
          : '<div class="muted">No super-groups yet. Create one above, then add families or rings to it.</div>';
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    function sgCard(g) {
      const chips = g.members.length ? g.members.map(m => {
        const isRing = !!m.ring_id;
        const inner = isRing
          ? `⊕ ${esc(m.ring_id)} <span class="muted">ring·${(m.ring_members || []).length}</span>`
          : esc(m.normalized);
        const tip = isRing ? esc((m.ring_members || []).join(" · ")) : "remove from this group";
        return `<button class="fam-chip" data-sg="${g.id}" data-norm="${esc(m.normalized)}" onclick="sgRemoveMember(this)"
           title="${tip}">${inner} <span class="muted">${m.mentions}</span> ✕</button>`;
      }).join("")
        : '<span class="muted">No members yet — add a family or a ring below.</span>';
      return `<div class="sg-card">
        <div class="sg-head"><b>${esc(g.name)}</b>
          <span class="muted">· ${g.count} member${g.count === 1 ? "" : "s"} · ${g.mentions} mentions</span>
          <button class="ghost tiny" style="margin-left:auto" data-sg="${g.id}" data-name="${esc(g.name)}"
            onclick="deleteSuperGroup(this)">delete</button></div>
        <div class="fam-chips" style="margin-top:6px">${chips}</div>
        <div class="row" style="margin-top:8px">
          <div style="flex:2"><input class="sg-fam-in" list="sg-family-options" placeholder="add a family…"
            data-sg="${g.id}" onkeydown="if(event.key==='Enter')sgAddMember(this)"></div>
          <div style="flex:0 0 auto;align-self:end"><button class="secondary"
            onclick="sgAddMember(this.closest('.row').querySelector('.sg-fam-in'))">Add family</button></div>
          <div style="flex:2"><input class="sg-ring-in" list="sg-ring-options" placeholder="add a ring (one concept, many languages)…"
            data-sg="${g.id}" onkeydown="if(event.key==='Enter')sgAddRing(this)"></div>
          <div style="flex:0 0 auto;align-self:end"><button class="secondary"
            onclick="sgAddRing(this.closest('.row').querySelector('.sg-ring-in'))">Add ring</button></div>
        </div></div>`;
    }

    async function createSuperGroup() {
      const name = $("sg-name").value.trim();
      if (!name) { toast("Name the super-group.", "err"); return; }
      try {
        await api("/api/insights/supergroups", {method: "POST", body: JSON.stringify({name})});
        $("sg-name").value = ""; toast("Super-group created."); loadSuperGroups();
      } catch (e) { toast("Create failed: " + e.message, "err"); }
    }

    async function sgAddMember(input) {
      const sg = input.dataset.sg, norm = input.value.trim();
      if (!norm) return;
      try {
        await api(`/api/insights/supergroups/${sg}/members`, {method: "POST", body: JSON.stringify({normalized: [norm]})});
        toast("Added."); loadSuperGroups();
      } catch (e) { toast("Add failed: " + e.message, "err"); }
    }

    async function sgAddRing(input) {
      const sg = input.dataset.sg, ring = input.value.trim();
      if (!ring) return;
      try {
        await api(`/api/insights/supergroups/${sg}/members`, {method: "POST", body: JSON.stringify({rings: [ring]})});
        toast("Ring added."); loadSuperGroups();
      } catch (e) { toast("Add ring failed: " + e.message, "err"); }
    }

    async function sgRemoveMember(btn) {
      try {
        await api(`/api/insights/supergroups/${btn.dataset.sg}/members?normalized=` + encodeURIComponent(btn.dataset.norm), {method: "DELETE"});
        loadSuperGroups();
      } catch (e) { toast("Remove failed: " + e.message, "err"); }
    }

    async function deleteSuperGroup(btn) {
      if (!confirm(`Delete super-group "${btn.dataset.name}"? (keyword data is untouched)`)) return;
      try {
        await api(`/api/insights/supergroups/${btn.dataset.sg}`, {method: "DELETE"});
        toast("Deleted."); loadSuperGroups();
      } catch (e) { toast("Delete failed: " + e.message, "err"); }
    }

    // -- Keyword explorer (Item AC: explore by tag, hide, apply baseline tags) ---- //
    async function loadKeywordExplorer() {
      const box = $("kx-facets");
      if (!box) return;
      box.innerHTML = '<div class="muted">Loading…</div>';
      $("kx-keywords").innerHTML = "";
      try {
        const f = await api("/api/insights/keyword-tags/facets");
        box.innerHTML = (f.axes || ["type", "topic"]).map(ax => {
          const tags = (f.facets && f.facets[ax]) || [];
          const chips = tags.length ? tags.map(t =>
            `<button class="fam-chip" data-ax="${esc(ax)}" data-tag="${esc(t.tag)}" onclick="kxShowTag(this)">${esc(t.tag)} <span class="muted">${t.keywords}</span></button>`).join("")
            : '<span class="muted">none yet — click “Apply baseline tags” above</span>';
          return `<div style="margin-bottom:8px"><b>${esc(ax)}</b><div class="fam-chips" style="margin-top:4px">${chips}</div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    async function kxShowTag(btn) {
      const ax = btn.dataset.ax, tag = btn.dataset.tag;
      const box = $("kx-keywords");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const r = await api(`/api/insights/keyword-tags/keywords?axis=${encodeURIComponent(ax)}&tag=${encodeURIComponent(tag)}&limit=200`);
        box.innerHTML = `<div class="muted" style="margin:6px 0">${r.total} keyword(s) tagged ${esc(ax)}=${esc(tag)}</div>` +
          (r.keywords || []).map(k =>
            `<div style="display:flex;gap:8px;align-items:center;padding:3px 0;border-bottom:1px solid var(--line)">
               <span style="flex:1">${esc(k.term)} <span class="muted">${esc(k.language || "?")} · ${k.articles}a/${k.mentions}m · ${esc(k.source)}</span></span>
               <button class="ghost tiny" data-norm="${esc(k.normalized)}" onclick="kxHide(this)">Hide</button>
             </div>`).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    async function kxHide(btn) {
      try {
        await api("/api/insights/exclude", {method: "POST", body: JSON.stringify({term: btn.dataset.norm})});
        btn.textContent = "hidden"; btn.disabled = true;
      } catch (e) { toast("Hide failed: " + e.message, "err"); }
    }

    async function kxBackfill() {
      try {
        toast("Applying baseline tags…");
        const r = await api("/api/insights/keyword-tags/backfill?limit=0", {method: "POST"});
        toast(`Tagged ${r.tagged_keywords} keyword(s) (${r.tags_added} tags).`);
        loadKeywordExplorer();
      } catch (e) { toast("Backfill failed: " + e.message, "err"); }
    }

    // -- Most-cited sources (corpus-wide co-citation) ----------------------- //
    async function loadCitedSources() {
      const box = $("cs-list");
      const by = $("cs-by").value;
      const win = $("cs-window").value.trim();
      const min = Math.max(1, parseInt($("cs-min").value, 10) || 2);
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        let url = `/api/links/top-cited?by=${by}&min_citations=${min}&limit=60`;
        if (win) url += `&window_days=${encodeURIComponent(win)}`;
        const d = await api(url);
        if (!d.items.length) {
          box.innerHTML = `<div class="muted">No source cited by ≥${min} article(s) yet. Ingest more, or lower the threshold. (Links are indexed from article text on ingest.)</div>`;
          return;
        }
        const max = Math.max(...d.items.map(i => i.citations), 1);
        box.innerHTML = d.items.map(it => {
          const label = by === "domain" ? it.domain : (it.link_text || it.domain || it.sample_url || it.normalized_url);
          const key = by === "domain" ? `domain=${encodeURIComponent(it.domain)}` : `url=${encodeURIComponent(it.normalized_url)}`;
          const sub = by === "domain" ? "" : `<div class="cs-url muted">${esc(it.sample_url || it.normalized_url)}</div>`;
          return `<div class="cs-row"><div class="cs-head" data-key="${esc(key)}" onclick="expandCitedSource(this)">
            <div class="cs-bar" style="width:${(it.citations/max*100).toFixed(1)}%"></div>
            <div class="cs-main"><span class="cs-label">${esc(label || "—")}</span>${sub}</div>
            <span class="cs-count">${it.citations}</span></div>
            <div class="cs-arts"></div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    async function expandCitedSource(head) {
      const tgt = head.parentElement.querySelector(".cs-arts");
      const key = head.dataset.key;
      if (head.classList.contains("open")) { head.classList.remove("open"); tgt.innerHTML = ""; return; }
      head.classList.add("open");
      tgt.innerHTML = '<div class="muted" style="padding:6px 0">Assembling citing articles…</div>';
      try {
        const d = await api(`/api/links/articles-by-link?${key}&limit=200`);
        if (!d.articles.length) { tgt.innerHTML = '<div class="muted" style="padding:6px 0">No stored articles.</div>'; return; }
        tgt.innerHTML = `<div class="cs-arts-h muted">${d.count} article(s) cite this${d.count>d.articles.length?` (showing ${d.articles.length})`:""}:</div>` +
          d.articles.map(a => `<div class="cs-art">
            <a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="offline stored copy">${esc(a.title || a.url)}</a>
            <span class="muted"> — ${esc(a.source || "")}${a.published_at?" · "+esc(a.published_at.slice(0,10)):""}</span>
            ${a.url?` · ${extLink(a.url, "source ↗", "muted")}`:""}</div>`).join("");
      } catch (e) { tgt.innerHTML = `<div class="muted" style="padding:6px 0">Could not load: ${esc(e.message)}</div>`; }
    }

    // Convergence (read-only, additive): clusters of articles converging on the
    // same PLACE within a time window on the MENTIONED event date. Independence is
    // measured by DISTINCT SOURCES, never article count; shared-origin links flag
    // possible false-triangulation (sources echoing one citation). The method +
    // caveat come FROM the API and are shown VISIBLE by default (informed consent —
    // co-occurrence is never causation). No score: only the counts the API returns.
    async function loadConvergences() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("cv-list"), meth = $("cv-method");
      const wEl = $("cv-window");
      const w = wEl ? (Math.max(1, parseInt(wEl.value, 10) || 7)) : 7;
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (meth) meth.textContent = "";
      try {
        const d = await api("/api/insights/convergences?window_days=" + w + "&limit=20");
        const clusters = d.clusters || [];
        if (!clusters.length) {
          // Honest empty state: state the gate (≥min_articles AND ≥min_sources).
          box.innerHTML = `<div class="muted">` + esc(
            t("No convergences yet. A cluster needs at least {a} articles AND at least {s} sources sharing a place within the window.")
              .replace("{a}", String(d.min_articles)).replace("{s}", String(d.min_sources))) + `</div>`;
          if (meth && d.caveat) meth.textContent = d.caveat;
          return;
        }
        const rows = clusters.map(c => {
          const place = esc(c.place || "—") + (c.place_country ? ` <span class="muted">(${esc(c.place_country)})</span>` : "");
          const win = esc((c.window_start || "").slice(0, 10)) + " → " + esc((c.window_end || "").slice(0, 10));
          const srcNames = (c.source_names || []).map(esc).join(", ");
          const srcShown = srcNames.length > 160 ? srcNames.slice(0, 160) + "…" : srcNames;
          // Title is clickable -> the exact converging article set (function exists).
          const head = `<div class="cs-main"><span class="cs-label" style="cursor:pointer;text-decoration:underline"
              onclick="openAnalysisForIds(${esc(JSON.stringify(c.article_ids || []))}, ${esc(JSON.stringify(c.place || ""))})">${place}</span>
            <div class="cs-url muted">${win}</div></div>`;
          const counts = `<span class="muted">${c.n_articles} ${esc(t("articles"))} · ${c.distinct_sources} ${esc(t("sources"))}</span>`;
          const srcLine = srcShown ? `<div class="muted" style="font-size:11px;margin-top:2px">${srcShown}</div>` : "";
          // VISIBLE shared-origin warning when sources may echo one citation.
          const warn = (c.shared_origin_links > 0)
            ? `<div class="hint" style="color:var(--caveat);margin-top:2px">${esc(
                t("⚠ {n} shared-origin links — sources may echo one citation, not independent confirmation.")
                  .replace("{n}", String(c.shared_origin_links)))}</div>`
            : "";
          return `<div class="cs-row" style="display:block;padding:8px 0;border-bottom:1px solid var(--border)">
            <div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px">${head}${counts}</div>
            ${srcLine}${warn}</div>`;
        }).join("");
        const total = d.clusters_total != null ? d.clusters_total : clusters.length;
        const more = (total > clusters.length)
          ? `<div class="muted" style="margin-top:8px">${esc(
              t("Showing {n} of {t} clusters.").replace("{n}", String(clusters.length)).replace("{t}", String(total)))}</div>`
          : "";
        box.innerHTML = rows + more;
        // Method + caveat VISIBLE by default (never behind a toggle).
        if (meth) {
          const parts = [];
          if (d.method) parts.push(d.method);
          if (d.caveat) parts.push(d.caveat);
          meth.textContent = parts.join(" — ");
        }
      } catch (e) {
        // Additive panel — degrade quietly, never throw.
        box.innerHTML = `<div class="muted">${esc(t("Could not load") + ": " + e.message)}</div>`;
      }
    }

    // -- Watches (ruling #3): saved local conditions that fire a Lead card. English
    // strings here (matching the keyword-explorer/stats sub-features) so i18n stays
    // 100% with zero new keys; the engine + honesty live in the (tested) backend.
    async function loadWatches() {
      const box = $("wt-list"); if (!box) return;
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/watches");
        const ws = d.watches || [];
        if (!ws.length) { box.innerHTML = `<div class="muted">No watches yet — add one above. The engine runs after every collection pass.</div>`; return; }
        box.innerHTML = ws.map(w => {
          const last = w.last_matched_at ? fmtDateTime(w.last_matched_at) : "never";
          const hist = (w.history || []).map(h =>
            `<li>${esc(fmtDateTime(h.matched_at))}: <b>${h.n_articles}</b> articles (${h.new_articles} new)`
            + (h.article_ids && h.article_ids.length ? ` · <a href="#" onclick="openAnalysisForIds(${JSON.stringify(h.article_ids)}, ${JSON.stringify('Watch: ' + w.name)});return false">open set ↗</a>` : "")
            + `</li>`).join("");
          return `<div class="card" style="padding:10px;margin-bottom:8px">
            <div class="row" style="align-items:center;justify-content:space-between;gap:8px">
              <div><b>${esc(w.name)}</b> <span class="muted">— “${esc(w.query)}”</span>
                <span class="pill ${w.enabled ? 'ok' : ''}">${w.enabled ? 'on' : 'off'}</span></div>
              <div style="flex:0 0 auto">
                <button class="secondary" onclick="toggleWatch(${w.id}, ${!w.enabled})">${w.enabled ? 'Disable' : 'Enable'}</button>
                <button class="secondary" onclick="editWatch(${w.id})">Edit</button>
                <button class="secondary" onclick="deleteWatch(${w.id})">Delete</button>
              </div>
            </div>
            <div class="hint" style="margin-top:4px">≥ ${w.threshold} articles within ${w.window_days} day(s) · last fired: ${esc(last)}</div>
            ${hist ? `<ul class="hint" style="margin:6px 0 0 16px">${hist}</ul>` : ""}
          </div>`;
        }).join("") + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load watches: ${esc(e.message)}</div>`; }
    }
    async function createWatch() {
      const name = ($("wt-name").value || "").trim();
      const query = ($("wt-query").value || "").trim();
      const threshold = parseInt($("wt-threshold").value || "3", 10);
      const window_days = parseInt($("wt-window").value || "7", 10);
      const msg = $("wt-msg");
      if (!query) { if (msg) msg.textContent = "Enter a condition (search query) first."; return; }
      try {
        await api("/api/watches", { method: "POST", body: JSON.stringify({ name, query, threshold, window_days }) });
        $("wt-name").value = ""; $("wt-query").value = "";
        if (msg) msg.textContent = "Watch added. It runs after every collection pass, or use “Check now”.";
        loadWatches();
      } catch (e) { if (msg) msg.innerHTML = `<span class="note err">Could not add: ${esc(e.message)}</span>`; }
    }
    async function toggleWatch(id, enabled) {
      try { await api("/api/watches/" + id, { method: "PATCH", body: JSON.stringify({ enabled }) }); loadWatches(); }
      catch (e) { toast("Could not update watch: " + e.message, "err"); }
    }
    async function editWatch(id) {
      // Minimal inline edit via prompts (the panel is browser-unverified; keep it simple).
      const q = prompt("New condition (search query) — leave blank to keep:");
      const th = prompt("Min articles to fire (leave blank to keep):");
      const wd = prompt("Window in days (leave blank to keep):");
      const body = {};
      if (q && q.trim()) body.query = q.trim();
      if (th && th.trim()) body.threshold = parseInt(th, 10);
      if (wd && wd.trim()) body.window_days = parseInt(wd, 10);
      if (!Object.keys(body).length) return;
      try { await api("/api/watches/" + id, { method: "PATCH", body: JSON.stringify(body) }); loadWatches(); }
      catch (e) { toast("Could not edit watch: " + e.message, "err"); }
    }
    async function deleteWatch(id) {
      if (!confirm("Delete this watch and its history?")) return;
      try { await api("/api/watches/" + id, { method: "DELETE" }); loadWatches(); }
      catch (e) { toast("Could not delete watch: " + e.message, "err"); }
    }
    async function evaluateWatches() {
      const msg = $("wt-msg");
      if (msg) msg.textContent = "Checking…";
      try {
        const d = await api("/api/watches/evaluate", { method: "POST" });
        if (msg) msg.textContent = d.count ? `${d.count} watch(es) fired — see Home, or the history below.` : "No watches fired (no new matching articles).";
        loadWatches();
      } catch (e) { if (msg) msg.innerHTML = `<span class="note err">Check failed: ${esc(e.message)}</span>`; }
    }

    let _insStatusBuilt = false;
    async function loadInsights() {
      try {
        const s = await api("/api/insights/status");
        if (!_insStatusBuilt) {
          _insStatusBuilt = true;
          $("ins-status").innerHTML =
            `<span class="pill" id="ins-pill"><span id="ins-n-indexed" data-v="0">0</span>/` +
            `<span id="ins-n-total" data-v="0">0</span> articles indexed</span> · ` +
            `<span id="ins-n-keywords" data-v="0">0</span> keywords ` +
            `(<span id="ins-n-entities" data-v="0">0</span> entities) · ` +
            `<span id="ins-n-mentions" data-v="0">0</span> mentions ` +
            `<span id="ins-remaining" class="muted"></span>`;
        }
        animateCount($("ins-n-indexed"), s.indexed_articles);
        animateCount($("ins-n-total"), s.total_articles);
        animateCount($("ins-n-keywords"), s.keywords);
        animateCount($("ins-n-entities"), s.entities);
        animateCount($("ins-n-mentions"), s.mentions);
        $("ins-pill").className = "pill " + (s.remaining === 0 ? "ok" : "warn");
        $("ins-remaining").innerHTML = s.remaining ? `· <strong>${s.remaining.toLocaleString()}</strong> to index` : "";
        if (s.remaining > 0 && !_indexing) autoIndexInsights();  // background top-up; no button (§6)
      } catch (e) { if (!_insStatusBuilt) $("ins-status").textContent = "Status unavailable: " + e.message; }
      loadLandscape();
    }

    // Insights indexing follows ingest automatically (the index_article hook
    // runs at ingest); this SILENT background top-up clears any legacy backlog of
    // not-yet-indexed articles when Insights is viewed — no button, the user
    // never thinks about it (UI_SHELL_REDESIGN §6). Best-effort + bounded; the
    // visible "N to index" count ticks down to 0 on its own.
    let _indexing = false;
    async function autoIndexInsights() {
      if (_indexing) return;
      _indexing = true;
      try {
        let guard = 0;
        for (;;) {
          const r = await api("/api/insights/reindex?limit=300", {method: "POST"});
          const rem = $("ins-remaining");
          if (rem) rem.innerHTML = r.remaining ? `· <strong>${r.remaining.toLocaleString()}</strong> to index` : "";
          if (r.remaining === 0 || r.indexed === 0 || ++guard > 500) break;
        }
      } catch (_e) { /* silent: background indexing is best-effort */ }
      finally { _indexing = false; }
    }

    // ---- T10 slice 1: the corpora window (keyword-click entry) ---- //
    let _corpusTerm = null, _corpusTab = "trend";
    async function openCorpus(term) {
      _corpusTerm = term;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      $("corpus-title").textContent = term;
      $("corpus-n").textContent = "";
      document.getElementById("corpus-win").showModal();
      (_corpusSubtabs || {select: corpusTab}).select(_corpusTab);
    }
    // Return the relocatable mind-map kit (#mm-kit) to its Insights home anchor.
    // Called BEFORE any corpus tab overwrites #corpus-body, so the shared
    // component (its DOM + live SVG/pan-zoom handlers) is never destroyed.
    function _mmKitHome() {
      const kit = $("mm-kit"), home = $("mm-kit-home");
      if (kit && home && kit.parentNode !== home.parentNode) {
        home.parentNode.insertBefore(kit, home.nextSibling);
      }
    }
    async function corpusTab(which) {
      _corpusTab = which;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      // Button/ARIA state is owned by the ooSubtabs component.
      _mmKitHome();   // restore the shared mind-map kit before clearing the body
      const el = $("corpus-body"); el.innerHTML = `<div class="muted">…</div>`;
      try {
        if (which === "trend") {
          const tr = await api(`/api/insights/trend?term=${encodeURIComponent(_corpusTerm)}`);
          if (!tr.resolved) { el.innerHTML = `<div class="muted">${esc(t("No indexed mentions yet."))}</div>`; return; }
          $("corpus-n").textContent = `${tr.total} ${t("mentions in")} ${tr.articles} ${t("articles")}`;
          // The trend endpoint returns the FULL bucketed series (no date params),
          // so the ooTimeScope window is applied CLIENT-SIDE by FILTERING the
          // already-fetched points — never refetched, never thinned (invariant #16).
          el.innerHTML = `<div style="margin-bottom:8px"><div class="hint">${esc(t("Time range"))}</div>
            <div id="corpus-timescope"></div></div><div id="corpus-chart"></div>`;
          const allPts = tr.points || [];
          const label = tr.resolved.term;
          const draw = (pts) => ooChart($("corpus-chart"), [{label, unit: "mentions",
            points: pts.map(pt => ({t: pt.date, v: pt.count}))}], {height: 200, zeroBase: true});
          const def = _buildTrendScope($("corpus-timescope"), allPts, draw);
          draw(_windowTrendPoints(allPts, def.from, def.to));
        } else if (which === "articles") {
          const ctx = await api(`/api/insights/context?term=${encodeURIComponent(_corpusTerm)}&limit=25`);
          const ms = ctx.mentions || [];
          el.innerHTML = ms.length ? ms.map(m =>
            `<div class="note" style="max-width:none;margin-bottom:6px">
               <div class="muted" style="font-size:12px">${esc(m.source || "")}${m.observed_on ? " · " + esc(m.observed_on) : ""}
                 ${m.article_id ? `· <a href="/api/articles/${m.article_id}/view" target="_blank" rel="noopener">${esc(t("open"))}</a>` : ""}</div>
               <div style="font-size:13px">${esc(m.snippet || m.title || "")}</div></div>`).join("")
            : `<div class="muted">${esc(t("No indexed mentions yet."))}</div>`;
        } else if (which === "mindmap") {
          // Reuse the EXACT Insights associations mind-map (renderMindmap →
          // renderGraph): same radial renderer, same in-map controls
          // (levels / cloud / period / text-size / enlarge). We RELOCATE the
          // shared #mm-kit into this pane (no fork, no duplicate IDs), then
          // point it at THIS window's corpus term. The mind-map's own Period
          // control honours the date window (the corpus Trend's ooTimeScope is
          // a client-side filter on a different series, so we don't pretend to
          // couple them — the mind-map carries its own honest window control).
          el.innerHTML = `<div id="corpus-mm-host"></div>`;
          const kit = $("mm-kit");
          if (kit) $("corpus-mm-host").appendChild(kit);
          await renderMindmap(_corpusTerm);
        } else if (which === "links") {
          const d = await api(`/api/links/shared?term=${encodeURIComponent(_corpusTerm)}`);
          const rows = d.shared || [];
          el.innerHTML =
            `<div class="hint">${esc(t("Shared outbound links among the member articles — a shared origin means agreement is ONE path, not independent confirmation."))}</div>` +
            (rows.length ? rows.map(r =>
              `<div class="note" style="max-width:none;margin-bottom:6px">
                 <div style="font-size:12.5px;word-break:break-all"><b>${r.cited_by_articles}×</b> ${esc(r.url)}</div>
                 <div class="muted" style="font-size:12px">${esc(t("citing sources:"))} ${r.citing_sources} — ${esc(r.note)}</div>
               </div>`).join("")
             : `<div class="muted">${esc(t("No outbound link is shared by more than one member article."))}</div>`);
        } else if (which === "sentiment") {
          // Reuse the EXACT Insights framing renderer (loadFraming → /api/framing)
          // by CALLING it into a fresh host — no DOM relocation, Insights untouched.
          // The endpoint is keyed on the FTS query, so we point it at _corpusTerm.
          // Its d.caveat carries the English-only VADER disclosure (audit B1),
          // rendered VISIBLY by loadFraming (the same keyed disclosure the
          // Insights framing surface shows). /api/framing takes no date params,
          // so this is honest full-corpus — we do NOT fake a time-scope window.
          el.innerHTML = `<h2 style="margin:2px 0 6px;font-size:13px">${esc(t("How outlets frame this"))} <span class="muted">${esc(t("(VADER tone)"))}</span></h2>
            <div id="corpus-sentiment-host"></div>`;
          await loadFraming(_corpusTerm, "corpus-sentiment-host");
        } else if (which === "keywords") {
          // Reuse the EXACT Insights associations data (/api/insights/associations,
          // the SAME endpoint q.associations that powers the mind-map graph) by
          // rendering it as a ranked TABLE into a fresh host — the Sentiment
          // pattern (function-call into a host, no DOM relocation). The Mindmap
          // sub-tab shows the SAME relatives as a radial GRAPH (how they relate,
          // visually); this answers "which terms define this corpus, with numbers".
          // /api/insights/associations exposes no date params, so this is honest
          // full-corpus — we do NOT fake a time-scope window (cf. Sentiment).
          el.innerHTML = `<div id="corpus-keywords-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusKeywords(_corpusTerm, "corpus-keywords-host");
        } else if (which === "sources") {
          // SOURCE-DESCRIPTION sub-tab: WHICH sources feed this corpus, with the
          // catalog metadata they assert — descriptive provenance, NOT the
          // competitive/angle analysis (a later, corpus-only tab) and NOT tone
          // (Sentiment owns that). Reuses /api/insights/corpus-sources for the
          // corpus's DISTINCT sources + their REAL per-corpus article count, then
          // enriches client-side from the bulk /api/sources catalog (no new
          // backend, no fork). The function-call-into-a-fresh-host pattern
          // (Sentiment/Keywords), never DOM relocation. No time-scope here:
          // /api/insights/corpus-sources does honest full-corpus over the matched
          // articles (it exposes date params but we don't fake a window control).
          el.innerHTML = `<div id="corpus-sources-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusSources(_corpusTerm, "corpus-sources-host");
        } else if (which === "competitive") {
          // SOURCE-COMPETITIVE sub-tab (corpus-only, the flagship's LAST design
          // facet): how each source APPROACHES this concept, side by side —
          // VOLUME (exact article count), TONE (VADER mean + label), TIMING
          // (first→last span), EMPHASIS (each outlet's distinctive terms). It is
          // a DESCRIPTIVE comparison of DIVERGENCE, never a ranking, a winner or
          // a credibility verdict — no composite score. Built by JOINING two
          // EXISTING endpoints per source (no new backend, no fork): volume +
          // timing + mean tone from /api/insights/corpus-sources, tone label +
          // emphasised terms from /api/framing. n=1 ⇒ "nothing to compare". The
          // function-call-into-a-fresh-host pattern (Sentiment/Sources). No
          // time-scope: neither endpoint takes date params — honest full-corpus.
          el.innerHTML = `<div id="corpus-competitive-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusCompetitive(_corpusTerm, "corpus-competitive-host");
        }
      } catch (e) { el.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    // Source-description sub-tab: the distinct sources behind this corpus, each
    // with its REAL per-corpus article count (from /api/insights/corpus-sources,
    // the same data the source-coverage view uses) PLUS the catalog metadata the
    // source ASSERTS — domain, country, region, language, tags (from the bulk
    // /api/sources list, merged by domain). Two-class honesty: every metadata
    // field here is catalog/source-ASSERTED (set from the catalog, ccTLD or the
    // operator), NEVER text-deduced — stated as such; we never fabricate a
    // "description" the model does not store (Source has no free-text bio), so a
    // source with no catalog facts on file reads "no catalog metadata on file".
    // No score, no ranking — descriptive provenance, not credibility.
    async function renderCorpusSources(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let cs, cat;
      try {
        // corpus-sources keys on the FTS query (like Sentiment's framing call),
        // so we point it at this window's term to get THIS corpus's sources.
        [cs, cat] = await Promise.all([
          api(`/api/insights/corpus-sources?query=${encodeURIComponent(term)}&limit=200`),
          api(`/api/sources/?limit=1000`).catch(() => []),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const rows = (cs && cs.sources) || [];
      if (!rows.length) {
        host.innerHTML = `<div class="muted">${esc(t("No sources for this corpus yet."))}</div>`;
        return;
      }
      // Index the catalog metadata by domain (+ name fallback) for client-side merge.
      const byDom = {}, byName = {};
      (Array.isArray(cat) ? cat : []).forEach(s => {
        if (s.domain) byDom[s.domain.toLowerCase()] = s;
        if (s.name) byName[s.name] = s;
      });
      const fmt = (n) => (n || 0).toLocaleString();
      const chips = (arr) => (arr || []).filter(Boolean)
        .map(x => `<span class="pill" style="font-size:11px">${esc(x)}</span>`).join(" ");
      const cards = rows.map(r => {
        const meta = byDom[(r.domain || "").toLowerCase()] || byName[r.name] || {};
        const facts = [];
        if (meta.country) facts.push(`${esc(t("Country"))}: ${esc(meta.country.toUpperCase())}`);
        if (meta.region) facts.push(`${esc(t("Region"))}: ${esc(meta.region)}`);
        if (meta.language) facts.push(`${esc(t("Language"))}: ${esc(meta.language)}`);
        if (meta.source_type) facts.push(`${esc(t("Type"))}: ${esc(meta.source_type)}`);
        const tags = (meta.tags && meta.tags.length) ? chips(meta.tags) : "";
        const hasMeta = facts.length || tags;
        // Source name → the EXISTING integrity source-profile view (reuse), keyed
        // by the source name/domain it already accepts. No invented destination.
        const nameLink = `<a href="#" class="csrc-prof" data-src="${esc(r.domain || r.name)}"
            title="${esc(t("Open this source's profile (measured dimensions, no composite score)."))}">${esc(r.name || r.domain || "—")}</a>`;
        return `<div class="note" style="max-width:none;margin-bottom:8px">
          <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
            <b style="font-size:13px">${nameLink}</b>
            <span class="muted" style="font-size:12px">${esc(r.domain || "")}</span>
            <span style="margin-inline-start:auto;font-size:12px">${fmt(r.articles)} ${esc(t("articles"))}</span>
          </div>
          ${facts.length ? `<div class="muted" style="font-size:12px;margin-top:3px">${facts.join(" · ")}</div>` : ""}
          ${tags ? `<div style="margin-top:4px">${tags}</div>` : ""}
          ${hasMeta ? "" : `<div class="muted" style="font-size:12px;margin-top:3px">${esc(t("No catalog metadata on file."))}</div>`}
        </div>`;
      }).join("");
      host.innerHTML =
        `<div class="hint">${esc(t("The distinct sources behind this corpus, with their per-corpus article count. Country, region, language and tags are stated by the source catalog (asserted, not deduced from text); article counts are exact. No score, no ranking — coverage, not credibility."))}</div>` +
        cards +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(cs.n_articles)} ${esc(t("articles"))}${cs.capped ? ` · ${esc(t("(scoped to the top matched articles)"))}` : ""}. ${esc(cs.caveat || "")}</div>`;
      // Source name → the existing source-profile view (reuse loadProfile).
      host.querySelectorAll(".csrc-prof").forEach(a =>
        a.addEventListener("click", (e) => {
          e.preventDefault();
          const inp = $("prof-source");
          if (inp) { inp.value = a.dataset.src; showTab("integrity"); loadProfile(); }
        }));
    }

    // Source-competitive sub-tab (corpus-only, the flagship's LAST design facet):
    // how each source APPROACHES this concept, side by side. It JOINS two EXISTING
    // endpoints per source (no new backend, no fork):
    //   • VOLUME + TIMING + mean tone  ← /api/insights/corpus-sources
    //     (sources[]: name, domain, articles, mean_tone, first, last)
    //   • TONE label + EMPHASISED terms ← /api/framing
    //     (framing[]: source, tone_label, avg_tone, article_count, top_terms[])
    // Every column is a REAL value — exact article counts, real publication dates,
    // the source's own VADER mean/label, that outlet's distinctive terms. There is
    // NO composite score, NO "leader", NO ranking-as-quality: rows are ordered by
    // VOLUME only (the most-covering source first — an ordering, not a verdict).
    // It is a DESCRIPTIVE comparison of DIVERGENCE. n=1 ⇒ "nothing to compare"
    // (the ledger's "n=1 has no competition"). Tone carries the VADER English-only
    // disclosure (audit B1), reused from the framing/Sentiment surface, VISIBLE.
    // Neither endpoint takes date params, so this is honest full-corpus — we do
    // NOT fake a time-scope window (cf. Sentiment/Keywords/Sources).
    async function renderCorpusCompetitive(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let cs, fr;
      try {
        // Both endpoints key on the FTS query (like Sentiment/Sources), so we point
        // them at THIS window's term. Framing needs the [analysis] extra; if it is
        // absent we still show volume/timing and say tone/emphasis is unavailable.
        [cs, fr] = await Promise.all([
          api(`/api/insights/corpus-sources?query=${encodeURIComponent(term)}&limit=200`),
          api(`/api/framing?query=${encodeURIComponent(term)}`).catch(() => null),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const rows = (cs && cs.sources) || [];
      if (!rows.length) {
        host.innerHTML = `<div class="muted">${esc(t("No sources for this corpus yet."))}</div>`;
        return;
      }
      if (rows.length === 1) {
        // The ledger's "n=1 has no competition" — honest single-source state.
        host.innerHTML =
          `<div class="muted">${esc(t("Only one source in this corpus — nothing to compare."))}</div>`;
        return;
      }
      // Index framing per source (by name; tone label + emphasised terms live there).
      const byName = {};
      ((fr && fr.framing) || []).forEach(f => { if (f.source) byName[f.source] = f; });
      const fmt = (n) => (n || 0).toLocaleString();
      // Relative timing readout vs the WHOLE corpus span (real dates, never a score):
      // the corpus's earliest/latest publication across these sources.
      const firsts = rows.map(r => r.first).filter(Boolean).sort();
      const lasts = rows.map(r => r.last).filter(Boolean).sort();
      const corpusFirst = firsts[0] || null, corpusLast = lasts[lasts.length - 1] || null;
      const day = (s) => (s || "").slice(0, 10);
      const tonePill = (label, val) => {
        if (val == null) return `<span class="muted">—</span>`;
        const cls = label === "positive" ? "ok" : label === "negative" ? "err" : "";
        const lab = label === "positive" ? t("Positive") : label === "negative" ? t("Negative")
          : label === "neutral" ? t("Neutral") : (label || "");
        return `<span class="pill ${cls}">${esc(lab)} ${val.toFixed(2)}</span>`;
      };
      const chips = (arr) => (arr || []).slice(0, 6).filter(Boolean)
        .map(x => `<span class="pill" style="font-size:11px">${esc(x)}</span>`).join(" ");
      // The "not a ranking / not credibility" disclosure — VISIBLE, with the long
      // form in the #oo-tip hover (informed-consent layering). Plus the VADER
      // English-only disclosure carried by the framing/corpus-sources caveat.
      const notRanking = t("Descriptive comparison — how these sources DIFFER, never a ranking or a credibility judgement. Rows are ordered by volume only (most-covering first); there is no winner and no composite score.");
      const body = rows.map(r => {
        const f = byName[r.name] || {};
        const emphasis = (f.top_terms && f.top_terms.length) ? chips(f.top_terms)
          : `<span class="muted" style="font-size:12px">${fr ? esc(t("No distinctive terms.")) : esc(t("Needs the [analysis] extra."))}</span>`;
        // Tone: prefer the framing label+avg; fall back to the corpus-sources mean
        // (same VADER number) when framing has no row for this outlet — real value.
        const toneVal = (f.avg_tone != null) ? f.avg_tone : r.mean_tone;
        const toneLbl = f.tone_label || null;
        const span = (r.first && r.last)
          ? `${esc(day(r.first))} → ${esc(day(r.last))}`
          : `<span class="muted">—</span>`;
        return `<tr style="border-bottom:1px solid var(--line)">
          <td style="padding:5px 8px"><b style="font-size:13px">${esc(r.name || r.domain || "—")}</b>
            ${r.domain ? `<div class="muted" style="font-size:11px">${esc(r.domain)}</div>` : ""}</td>
          <td style="text-align:right;padding:5px 8px">${fmt(r.articles)}</td>
          <td style="padding:5px 8px">${tonePill(toneLbl, toneVal)}</td>
          <td style="padding:5px 8px;white-space:nowrap;font-size:12px">${span}</td>
          <td style="padding:5px 8px">${emphasis}</td>
        </tr>`;
      }).join("");
      host.innerHTML =
        `<div class="hint" title="${esc(t("How each source APPROACHES this concept, side by side: volume (exact article count), tone (VADER mean + label), timing (first→last publication span) and the outlet's distinctive emphasised terms. A microscope on divergence, not a verdict — no source is ranked above another, no quality is judged, no composite score is computed."))}">${esc(notRanking)}</div>` +
        `<table style="width:100%;border-collapse:collapse;font-size:13px">
           <thead><tr style="border-bottom:1px solid var(--line)">
             <th style="text-align:start;padding:5px 8px">${esc(t("Source"))}</th>
             <th style="text-align:right;padding:5px 8px"
                 title="${esc(t("How many articles in this corpus come from this source — an exact count, never a score."))}">${esc(t("Volume"))}</th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("Mean VADER tone for this source's coverage, with the label. VADER is an ENGLISH-lexicon method — tone for non-English coverage is unreliable or absent. A real value, never a verdict."))}">${esc(t("Tone"))} <span class="muted" style="font-weight:normal">${esc(t("(VADER tone)"))}</span></th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("The first → last publication date for this source's coverage in the corpus — real dates, never a score."))}">${esc(t("Timing"))}</th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("This outlet's most distinctive terms when covering the concept (from framing). Descriptive emphasis, not a judgement."))}">${esc(t("Emphasis"))}</th>
           </tr></thead>
           <tbody>${body}</tbody>
         </table>` +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(cs.n_articles)} ${esc(t("articles"))}` +
          `${(corpusFirst && corpusLast) ? ` · ${esc(day(corpusFirst))} → ${esc(day(corpusLast))}` : ""}` +
          `${cs.capped ? ` · ${esc(t("(scoped to the top matched articles)"))}` : ""}. ` +
          `${esc(cs.caveat || "")} ${esc((fr && fr.caveat) || "")}</div>`;
    }

    // Keyword-analysis sub-tab: a ranked TABLE of the corpus's co-occurring
    // keywords with REAL per-keyword numbers from /api/insights/associations
    // (the same data the mind-map plots). No composite score — each column is a
    // raw value; PMI carries the endpoint's own method + caveat. A row click
    // opens that keyword as its own corpus (the existing openCorpus entry).
    let _ckwSort = "pmi";
    async function renderCorpusKeywords(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let d;
      try {
        d = await api(`/api/insights/associations?term=${encodeURIComponent(term)}&limit=100`);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const pairs = (d.pairs || []).slice();
      if (!pairs.length) {
        host.innerHTML = `<div class="muted">${esc(t("No keywords indexed for this corpus yet."))}</div>`;
        return;
      }
      const sorters = {
        pmi: (a, b) => (b.pmi - a.pmi) || (b.cooccur - a.cooccur),
        cooccur: (a, b) => (b.cooccur - a.cooccur) || (b.pmi - a.pmi),
        n_b: (a, b) => (b.n_b - a.n_b) || (b.cooccur - a.cooccur),
      };
      pairs.sort(sorters[_ckwSort] || sorters.pmi);
      const nA = d.n_articles_with_term || 0;
      const fmt = (n) => (n || 0).toLocaleString();
      // Headers carry honest method/caveat in the #oo-tip hover (translated title).
      const th = (key, label, title) =>
        `<th data-sort="${key}" role="button" tabindex="0" style="cursor:pointer;text-align:right;padding:4px 8px;white-space:nowrap"
            title="${esc(title)}">${esc(label)}${_ckwSort === key ? " ▾" : ""}</th>`;
      host.innerHTML =
        `<div class="hint">${esc(t("Keywords that co-occur with this corpus, ranked. Real per-keyword counts — no composite score."))} ${esc(d.method || "")} ${esc(d.caveat || "")}</div>` +
        `<table style="width:100%;border-collapse:collapse;font-size:13px">
           <thead><tr style="border-bottom:1px solid var(--line)">
             <th style="text-align:start;padding:4px 8px">${esc(t("Keyword"))}</th>
             ${th("cooccur", t("In this corpus"), t("Distinct articles in this corpus that mention BOTH the corpus term and this keyword. A real count, never a score."))}
             ${th("n_b", t("Total articles"), t("Distinct articles across the whole corpus that mention this keyword. A real count, never a score."))}
             ${th("pmi", t("Association"), t("Pointwise mutual information with the corpus term — association strength, not causation. PMI on small samples is noisy; read it beside the counts."))}
           </tr></thead>
           <tbody>${pairs.map(p => {
             const members = (p.members && p.members.length > 1) ? p.members.join(", ") : "";
             const titleAttr = members ? ` title="${esc(t("Entity family:"))} ${esc(members)}"` : "";
             return `<tr class="ckw-row" data-term="${esc(p.normalized || p.term)}" style="cursor:pointer;border-bottom:1px solid var(--line)">
               <td style="padding:4px 8px"><span${titleAttr}>${esc(p.term)}</span>${p.kind ? ` <span class="muted" style="font-size:11px">${esc(p.kind)}</span>` : ""}</td>
               <td style="text-align:right;padding:4px 8px">${fmt(p.cooccur)}</td>
               <td style="text-align:right;padding:4px 8px">${fmt(p.n_b)}</td>
               <td style="text-align:right;padding:4px 8px">${(p.pmi != null ? p.pmi.toFixed(2) : "—")}</td>
             </tr>`;
           }).join("")}</tbody>
         </table>` +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(nA)} ${esc(t("articles mention the corpus term."))} ${d.grouped ? esc(t("Surface variants are merged into entity families.")) : ""} ${esc(t("Click a row to open that keyword as its own corpus."))}</div>`;
      // Row click → that keyword's corpus window (reuse the existing entry).
      host.querySelectorAll(".ckw-row").forEach(tr =>
        tr.addEventListener("click", () => openCorpus(tr.dataset.term)));
      // Header click/Enter → re-sort (honest defaults first; PMI by default).
      host.querySelectorAll("th[data-sort]").forEach(h => {
        const go = () => { _ckwSort = h.dataset.sort; renderCorpusKeywords(term, hostId); };
        h.addEventListener("click", go);
        h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      });
    }

    function pickTerm(t) { $("ins-term").value = t; (_insSubtabs || {select: showInsightCat}).select("explore"); exploreTerm(); }

    function trendSvg(points) {
      if (!points.length) return '<div class="muted">No mentions over time yet — index the corpus first.</div>';
      const w = 680, h = 140, pad = 30, ys = points.map(p => p.count), maxY = Math.max(...ys, 1);
      const X = i => pad + (w - 2*pad) * (points.length < 2 ? 0.5 : i/(points.length-1));
      const Y = v => h - pad - (h - 2*pad) * (v / maxY);
      const line = points.map((p, i) => `${X(i).toFixed(1)},${Y(p.count).toFixed(1)}`).join(" ");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:${w}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px">
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${line}"></polyline>
        <text x="${pad}" y="14" fill="var(--muted)" font-size="11">${maxY}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11">${esc(points[0].date)}</text>
        <text x="${w-pad}" y="${h-8}" fill="var(--muted)" font-size="11" text-anchor="end">${esc(points[points.length-1].date)}</text>
      </svg>`;
    }

    // Interactive, force-directed mind-map: drag to pan, scroll to zoom, drag a node
    // to pin it, click a node to recenter (re-query). Vanilla — a tiny spring layout
    // over an SVG viewBox, no dependencies. Respects prefers-reduced-motion (settles
    // synchronously, no animation). _mmRAF holds the running animation handle.
    let _mmRAF = null, _mmLevel = "keyword", _mmTerm = null, _mmViewMode = "map", _mmGraph = null;
    function _mmWindowQS() {
      const w = $("mm-window").value;
      if (w === "custom") {
        const a = $("mm-start").value, b = $("mm-end").value;
        return (a ? `&start=${a}` : "") + (b ? `&end=${b}` : "");
      }
      return w ? `&days=${w}` : "";
    }
    function mmWindowChange() {
      $("mm-custom").style.display = $("mm-window").value === "custom" ? "" : "none";
      mmReload();
    }
    function mmView(v) {
      _mmViewMode = v;
      document.querySelectorAll("#mm-views button").forEach(b =>
        b.classList.toggle("active", b.dataset.view === v));
      if (_mmGraph) renderGraph(_mmGraph);
    }
    function mmExpand() {
      const host = $("ins-mindmap");
      host.classList.toggle("mm-big");
      $("mm-expand").textContent = host.classList.contains("mm-big") ? "⛶ Reduce" : "⛶ Enlarge";
      if (_mmGraph) renderGraph(_mmGraph);
    }
    function mmReload() {
      if (_mmLevel === "keyword" && !_mmTerm) { if (_mmGraph) renderGraph(_mmGraph); return; }
      mmLevel(_mmLevel);
    }
    async function mmLevel(level) {
      _mmLevel = level;
      document.querySelectorAll("#mm-levels button").forEach(b =>
        b.classList.toggle("active", b.dataset.level === level));
      const host = $("ins-mindmap");
      if (level === "keyword") {
        if (!_mmTerm) { host.innerHTML = '<div class="muted">Pick a keyword above to see its relatives (two hops).</div>'; return; }
        host.innerHTML = '<div class="muted">Loading…</div>';
        try {
          const g = await api(`/api/insights/graph?level=keyword&term=${encodeURIComponent(_mmTerm)}&hops=2${_mmWindowQS()}`);
          renderGraph(g);
        } catch (e) { host.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
        return;
      }
      host.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const g = await api(`/api/insights/graph?level=${level}${_mmWindowQS()}`);
        renderGraph(g);
      } catch (e) { host.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
    }
    // Adapter: the keyword view comes from the layered endpoint (2 hops + window).
    async function renderMindmap(center, _pairs) {
      _mmTerm = center; _mmLevel = "keyword";
      document.querySelectorAll("#mm-levels button").forEach(b =>
        b.classList.toggle("active", b.dataset.level === "keyword"));
      try {
        const g = await api(`/api/insights/graph?level=keyword&term=${encodeURIComponent(center)}&hops=2${_mmWindowQS()}`);
        renderGraph(g);
      } catch (e) { $("ins-mindmap").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
    }
    function mmLegend(g) {
      const sw = (c) => `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${c};vertical-align:-1px"></span>`;
      const items = [];
      const kinds = new Set(g.nodes.map(n => n.center ? "center" : (n.hop === 2 ? "hop2" : n.kind)));
      if (kinds.has("center")) items.push(`${sw("var(--ok)")} <span>seed term</span>`);
      if (kinds.has("keyword")) items.push(`${sw("var(--accent)")} <span>relative</span>`);
      if (kinds.has("hop2")) items.push(`${sw("var(--muted)")} <span>relative of a relative</span>`);
      if (kinds.has("family")) items.push(`${sw("var(--warn)")} <span>family</span>`);
      if (kinds.has("supergroup")) items.push(`${sw("var(--ok)")} <span>super-group</span>`);
      return items.join(" &nbsp;·&nbsp; ");
    }
    function renderGraph(g) {
      _mmGraph = g;
      if (_mmRAF) { cancelAnimationFrame(_mmRAF); _mmRAF = null; }
      const host = $("ins-mindmap");
      if (!g.nodes || g.nodes.length < 2) { host.innerHTML = '<div class="muted">No strong associations yet.</div>'; return; }
      const big = host.classList.contains("mm-big");
      const W = big ? 1200 : 680, H = big ? 760 : 460;
      const scale = (Number($("mm-size").value) || 100) / 100;
      const maxSize = Math.max(...g.nodes.map(n => n.size || 1), 1);
      const fsOf = (n) => ((n.center ? 17 : 9 + 9 * Math.sqrt((n.size || 1) / maxSize)) * scale);

      // ---- layout: mind-map rules (center → arms → ALWAYS outward) -------- //
      const nodes = g.nodes.slice(0, 60).map(n => ({...n, fs: fsOf(n)}));
      const byId = {}; nodes.forEach(n => byId[n.id] = n);
      let treeEdges = [];
      if (_mmViewMode === "cloud") {
        // Word cloud: weight-ordered spiral from the centre, no edges.
        const sorted = [...nodes].sort((a, b) => (b.size || 1) - (a.size || 1));
        sorted.forEach((n, i) => {
          const ang = i * 2.39996, r = 16 * Math.sqrt(i);   // golden-angle spiral
          n.x = W / 2 + r * Math.cos(ang) * 1.6;
          n.y = H / 2 + r * Math.sin(ang);
        });
      } else if (g.level === "keyword") {
        const center = nodes.find(n => n.center) || nodes[0];
        center.x = W / 2; center.y = H / 2;
        const arms = nodes.filter(n => !n.center && n.hop !== 2);
        const leaves = nodes.filter(n => n.hop === 2);
        const parentOf = {};
        for (const e of g.edges) {
          if (byId[e.b] && byId[e.b].hop === 2 && byId[e.a] && !byId[e.a].center) {
            if (!(e.b in parentOf) || e.weight > parentOf[e.b].w) parentOf[e.b] = {p: e.a, w: e.weight};
          }
        }
        const R1 = Math.min(W, H) * 0.30, R2 = Math.min(W, H) * 0.46;
        arms.forEach((n, i) => {
          n.ang = (i / arms.length) * 2 * Math.PI - Math.PI / 2;
          n.x = W / 2 + R1 * Math.cos(n.ang); n.y = H / 2 + R1 * Math.sin(n.ang);
          treeEdges.push({a: center, b: n, w: 2});
        });
        const kids = {};
        leaves.forEach(n => {
          const p = byId[(parentOf[n.id] || {}).p] || arms[0];
          (kids[p.id] = kids[p.id] || []).push(n);
          n._p = p;
        });
        for (const pid in kids) {
          const p = byId[pid], ks = kids[pid];
          const span = (2 * Math.PI / Math.max(arms.length, 1)) * 0.8;
          ks.forEach((n, j) => {
            const a = p.ang + span * ((j + 1) / (ks.length + 1) - 0.5);
            n.x = W / 2 + R2 * Math.cos(a); n.y = H / 2 + R2 * Math.sin(a);
            treeEdges.push({a: p, b: n, w: 1});
          });
        }
      } else {
        // family / super-group: concentric rings by weight rank (outward =
        // lighter), each node linked only to its single strongest neighbour.
        const sorted = [...nodes].sort((a, b) => (b.size || 1) - (a.size || 1));
        sorted.forEach((n, i) => {
          if (i === 0) { n.x = W / 2; n.y = H / 2; return; }
          const ring = i <= 8 ? 1 : i <= 24 ? 2 : 3;
          const start = ring === 1 ? 0 : ring === 2 ? 8 : 24;
          const count = ring === 1 ? Math.min(8, sorted.length - 1) : ring === 2 ? Math.min(16, sorted.length - 9) : sorted.length - 25;
          const ang = ((i - start) / Math.max(count, 1)) * 2 * Math.PI - Math.PI / 2 + ring * 0.3;
          const R = Math.min(W, H) * (0.16 + 0.15 * ring);
          n.x = W / 2 + R * Math.cos(ang) * 1.25; n.y = H / 2 + R * Math.sin(ang);
        });
        const best = {};
        for (const e of g.edges) {
          if (!byId[e.a] || !byId[e.b]) continue;
          if (!(e.a in best) || e.weight > best[e.a].w) best[e.a] = {o: e.b, w: e.weight};
          if (!(e.b in best) || e.weight > best[e.b].w) best[e.b] = {o: e.a, w: e.weight};
        }
        const seen = new Set();
        for (const id in best) {
          const key = [id, best[id].o].sort().join("|");
          if (!seen.has(key)) { seen.add(key); treeEdges.push({a: byId[id], b: byId[best[id].o], w: best[id].w}); }
        }
      }

      host.innerHTML =
        `<div class="hint" id="mm-legend">${mmLegend(g)}</div>` +
        `<svg id="mm-svg" viewBox="0 0 ${W} ${H}" width="100%" style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;touch-action:none;cursor:grab"><g id="mm-view"></g></svg>` +
        `<div class="hint">Drag to pan · scroll to zoom (far out goes up a level) · click a word to dive in. <b>Font size = shared-article volume.</b> ${_mmViewMode === "map" ? "Branches grow outward from the centre; each leaf hangs off its strongest relative." : "Cloud view: weight-ordered, no links."} ${esc(g.method || "")} ${esc(g.caveat || "")}</div>`;
      const svg = $("mm-svg"), view = $("mm-view");
      const maxW = Math.max(...treeEdges.map(e => e.w || 1), 1);
      view.innerHTML =
        treeEdges.map(e => `<line stroke="var(--border)" stroke-width="${(0.8 + 2.2 * (e.w || 1) / maxW).toFixed(1)}"
            x1="${e.a.x.toFixed(1)}" y1="${e.a.y.toFixed(1)}" x2="${e.b.x.toFixed(1)}" y2="${e.b.y.toFixed(1)}"></line>`).join("") +
        nodes.map((n, i) => {
          const col = n.center ? "var(--ok)"
            : n.kind === "supergroup" ? "var(--ok)"
            : n.kind === "family" ? "var(--warn)"
            : n.hop === 2 ? "var(--muted)" : "var(--accent)";
          const fam = (n.members || []).length > 1;
          const title = fam ? `<title>${esc((n.members || []).join(", "))}</title>` : "";
          return `<g class="mm-node" data-i="${i}" style="cursor:pointer" transform="translate(${n.x.toFixed(1)},${n.y.toFixed(1)})">${title}` +
            `<text text-anchor="middle" dominant-baseline="central" font-size="${n.fs.toFixed(1)}" font-weight="${n.center ? 700 : 500}" fill="${col}">${esc(n.label)}</text></g>`;
        }).join("");

      // -- pan / zoom (level-up on far zoom-out) + click-to-dive ------------- //
      let vb = {x: 0, y: 0, w: W, h: H};
      const applyVB = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      const ptVB = (e) => { const m2 = svg.getScreenCTM().inverse(); const p = svg.createSVGPoint();
        p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(m2); };
      svg.addEventListener("wheel", (e) => { e.preventDefault(); const p = ptVB(e);
        const sc = Math.min(3, Math.max(0.34, vb.w * Math.exp(e.deltaY * 0.0015) / W)) * W / vb.w;
        vb.x = p.x - (p.x - vb.x) * sc; vb.y = p.y - (p.y - vb.y) * sc; vb.w *= sc; vb.h *= sc; applyVB();
        if (vb.w / W >= 2.7) {
          if (_mmLevel === "keyword") mmLevel("family");
          else if (_mmLevel === "family") mmLevel("supergroup");
        }
      }, {passive: false});
      let drag = null;
      svg.addEventListener("pointerdown", (e) => {
        const gEl = e.target.closest && e.target.closest(".mm-node");
        if (gEl) drag = {type: "node", i: +gEl.dataset.i, sx: e.clientX, sy: e.clientY, moved: false};
        else { const r = svg.getBoundingClientRect();
          drag = {type: "pan", x0: vb.x, y0: vb.y, cx: e.clientX, cy: e.clientY, sx: vb.w / r.width, sy: vb.h / r.height}; }
        svg.setPointerCapture(e.pointerId);
      });
      svg.addEventListener("pointermove", (e) => { if (!drag) return;
        if (drag.type === "node") { if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 4) drag.moved = true; }
        else { vb.x = drag.x0 - (e.clientX - drag.cx) * drag.sx; vb.y = drag.y0 - (e.clientY - drag.cy) * drag.sy; applyVB(); }
      });
      svg.addEventListener("pointerup", (e) => {
        if (drag && drag.type === "node" && !drag.moved) {
          const n = nodes[drag.i];
          if (!n.center) {
            if (n.kind === "supergroup") mmLevel("family");
            else { $("ins-term").value = n.label; pickTerm(n.label); }
          }
        }
        drag = null; try { svg.releasePointerCapture(e.pointerId); } catch (_e) {}
      });
    }

    async function exploreTerm() {
      const term = $("ins-term").value.trim();
      if (!term) { toast("Enter a keyword or entity.", "err"); return; }
      $("ins-trend").innerHTML = '<div class="muted">Loading…</div>';
      $("ins-mindmap").innerHTML = ""; $("ins-context").innerHTML = ""; $("ins-framing").innerHTML = "";
      try {
        const [tr, assoc, ctx] = await Promise.all([
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(term)),
          api("/api/insights/associations?term=" + encodeURIComponent(term)),
          api("/api/insights/context?term=" + encodeURIComponent(term)),
        ]);
        if (!tr.resolved) { $("ins-trend").innerHTML = `<div class="note err">No indexed mentions of “${esc(term)}”. Index the corpus, or try another term.</div>`; return; }
        const r = tr.resolved;
        const t8 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        $("ins-trend").innerHTML =
          `<div style="margin-bottom:6px">Resolved to <strong>${esc(r.term)}</strong> ` +
          `<span class="pill">${esc(r.kind)}</span> · ${tr.total} mentions in ${tr.articles} articles ` +
          `<button class="tiny secondary" onclick="openCorpus(${esc(JSON.stringify(r.term))})" title="Open this keyword as a corpus window: trend, member articles, and shared outbound links (the sources' sources).">⊞ Corpus</button></div>` +
          `<div style="margin-bottom:8px"><div class="hint">${esc(t8("Time range"))}</div>` +
          `<div id="ins-trend-scope"></div></div>` +
          `<div id="ins-trend-oo"></div>`;
        // FULL bucketed series fetched once; the ooTimeScope window FILTERS it
        // client-side (invariant #16 — never thinned; ooChart unchanged).
        const allPts = tr.points || [];
        const insDraw = (pts) => ooChart($("ins-trend-oo"), [{label: r.term, unit: "mentions",
          points: pts.map(pt => ({t: pt.date, v: pt.count}))}],
          {height: 180, zeroBase: true, lineMin: 8});
        const insDef = _buildTrendScope($("ins-trend-scope"), allPts, insDraw);
        insDraw(_windowTrendPoints(allPts, insDef.from, insDef.to));
        renderMindmap(r.term, assoc.pairs);
        loadFraming(r.term);
        $("ins-context").innerHTML = (ctx.mentions || []).length
          ? ctx.mentions.map(m => `<div class="note" style="max-width:none;margin-bottom:6px">
               <div style="font-size:12px" class="muted">${esc(m.source||"")}${m.country?" · "+esc(m.country):""}${m.city?" · "+esc(m.city):""}${m.observed_on?" · "+esc(m.observed_on):""}
                 ${m.article_id?`· <a href="/api/articles/${m.article_id}/view" target="_blank" rel="noopener" title="offline stored copy">open</a>`:""}${m.url?`· ${extLink(m.url, "source ↗", "muted")}`:""}</div>
               <div>${esc(m.snippet)}</div></div>`).join("")
          : '<div class="muted">No context snippets.</div>';
      } catch (e) { $("ins-trend").innerHTML = ""; toast("Explore failed: " + e.message, "err"); }
    }

    function termListHtml(terms, extra) {
      if (!terms.length) return '<div class="muted">Nothing yet — index the corpus.</div>';
      return terms.map(t => `<div style="padding:4px 0;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:6px">
        <button class="tiny danger" title="exclude this keyword" style="margin:0;padding:0 6px"
          onclick='excludeKeyword(${esc(JSON.stringify(t.term))})'>✕</button>
        <a href="#" onclick='pickTerm(${esc(JSON.stringify(t.term))});return false'>${esc(t.term)}</a>
        <span class="pill">${esc(t.kind)}</span> <span class="muted">${extra(t)}</span></div>`).join("");
    }

    async function excludeKeyword(term) {
      try {
        await api("/api/insights/exclude", {method: "POST", body: JSON.stringify({term})});
        toast(`Excluded “${term}”. Manage exclusions in Settings.`);
        loadTrends(); if ($("ins-term").value.trim()) exploreTerm();
      } catch (e) { toast("Exclude failed: " + e.message, "err"); }
    }

    async function loadTrends() {
      const wd = $("trd-window").value, bd = $("trd-base").value, kind = $("trd-kind").value, cc = $("trd-country").value.trim();
      const qp = (extra) => `kind=${encodeURIComponent(kind)}${cc?"&country="+encodeURIComponent(cc):""}${extra||""}`;
      try {
        const [rising, top] = await Promise.all([
          api(`/api/insights/trending?window_days=${wd}&baseline_days=${bd}&${qp()}`),
          api(`/api/insights/top?days=${wd}&${qp()}`),
        ]);
        $("trd-rising").innerHTML = termListHtml(rising.terms, t => `↑${t.growth}× (recent ${t.recent}, prior ${t.prior})`);
        $("trd-top").innerHTML = termListHtml(top.terms, t => `${t.mentions} mentions · ${t.articles} articles`);
        $("trd-method").textContent = rising.method ? "Rising = " + rising.method : "";
      } catch (e) { toast("Trends failed: " + e.message, "err"); }
      loadTrendWindows();
    }

    // The three preset windows side by side (24h · week · month) — the ruled
    // Trends redesign (2026-06-16). Reads /api/insights/trending-windows (no
    // controls; fixed presets); each column reuses termListHtml. Honest n + the
    // early-corpus caveat travel from the API. Additive to the single-window view.
    let _trendWindowsData = null;  // last /trending-windows payload (the enlarge dialog reads its series)
    async function loadTrendWindows() {
      const box = $("trd-windows"); if (!box) return;
      const LABELS = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      try {
        // series_top=5: the top rising terms of each window carry a daily series
        // (from /trending-windows, reusing trend()'s day buckets) so each renders a
        // small honest sparkline (dashChartSvg: line when dense, Item-Y bars when
        // sparse — never an interpolated curve). The rest stay a plain list.
        const d = await api("/api/insights/trending-windows?limit=8&series_top=5");
        _trendWindowsData = d;  // stash so enlargeTrend(wi,ti) needs no extra fetch
        box.innerHTML = (d.windows || []).map((w, wi) => {
          const head = `<h2 style="font-size:13px">${esc(LABELS[w.label] || w.label)} <span class="muted">· n=${w.count}</span></h2>`;
          const terms = w.terms || [];
          if (!terms.length) {
            return `<div style="flex:1;min-width:240px">${head}<div class="muted">${esc(t("No rising keywords in this window yet."))}</div></div>`;
          }
          // Map over ALL terms (index ti preserved so enlargeTrend can index back
          // into _trendWindowsData), rendering a sparkline only for those carrying
          // a series; the rest fall through to the plain list below.
          const spark = terms.map((x, ti) => {
            if (!Array.isArray(x.series)) return "";
            // {date,count} -> dashChartSvg's {observed_on,price}; it handles the empty
            // + sparse cases honestly (no fabricated points).
            const pts = x.series.map(p => ({observed_on: p.date, price: p.count}));
            return `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
              <div style="display:flex;align-items:baseline;gap:6px">
                <a href="#" onclick='pickTerm(${esc(JSON.stringify(x.term))});return false'>${esc(x.term)}</a>
                <span class="muted" style="font-size:12px">↑${esc(String(x.growth))}× · ${esc(String(x.recent))} recent</span>
                <button class="ghost tiny" style="margin-inline-start:auto" onclick="enlargeTrend(${wi},${ti})" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
              </div>${dashChartSvg(pts, "")}</div>`;
          }).join("");
          const rest = terms.filter(x => !Array.isArray(x.series));
          const restList = rest.length ? termListHtml(rest, t2 => `↑${t2.growth}× · ${t2.recent} recent`) : "";
          return `<div style="flex:1;min-width:240px">${head}${spark}${restList}</div>`;
        }).join("") || `<div class="muted">${esc(t("No rising keywords in this window yet."))}</div>`;
        const note = $("trd-windows-note"); if (note) note.textContent = d.caveat || "";
      } catch (e) { /* additive panel — leave the single-window view intact on error */ }
    }

    // Click-to-enlarge a Trends sparkline into the interactive ooChart (invariant
    // #16: full-resolution, wheel-zoom / drag-pan / hover-readout / legend; Item-Y
    // bars when n<10). The daily series is already in the trending-windows payload
    // (_trendWindowsData) — no extra fetch. Global: reached from an inline onclick.
    function enlargeTrend(wi, ti) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _trendWindowsData;
      const w = d && d.windows && d.windows[wi];
      const x = w && (w.terms || [])[ti];
      if (!x || !Array.isArray(x.series)) return;   // defensive: nothing to enlarge
      const LABELS = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      const title = x.term + " — " + (LABELS[w.label] || w.label);
      const points = x.series.map(p => ({t: p.date, v: p.count}));
      chartEnlarge(title, [{label: x.term, unit: t("mentions"), points}], d.caveat || "");
    }

    // Reusable interactive-chart enlarge dialog (Item 1, Group E). Renders the
    // given ooChart series into the modal <dialog> (native showModal traps focus,
    // OO-D13-001). The caveat shows VISIBLE by default (informed consent). ooChart
    // is drawn AFTER showModal so the dialog has layout width for the canvas.
    function chartEnlarge(title, seriesList, caveat, opts) {
      opts = opts || {};
      const dlg = $("chart-enlarge"); if (!dlg) return;
      const ttl = $("chart-enlarge-title"); if (ttl) ttl.textContent = title || "";
      const note = $("chart-enlarge-note");
      if (note) { note.textContent = caveat || ""; note.style.display = caveat ? "" : "none"; }
      const body = $("chart-enlarge-body"); if (!body) return;
      body.innerHTML = "";
      if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      if (opts.scales) {
        // Scale controls (maintainer markets revamp Slice 3: "change the graph
        // scales"): Absolute (raw values) ↔ Indexed (rebase each series to 100 at
        // the window start, so different-magnitude series co-move WITHOUT
        // conflating magnitudes) ↔ Log (log10 y-axis). Re-renders the SAME ooChart
        // with the proven opts.indexed / opts.logY (the hover always shows the REAL
        // value). One shared #chart-enlarge dialog — no new modal DOM.
        const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
        const SCALES = [["absolute", "Absolute"], ["indexed", "Indexed (=100)"], ["log", "Log"]];
        let mode = "absolute";
        const ctl = document.createElement("div");
        ctl.className = "mkt-scalerow";
        ctl.innerHTML = `<span class="muted" style="font-size:12px;margin-right:2px">${esc(t9("Scale"))}:</span>`
          + SCALES.map(([k, lbl]) =>
              `<button type="button" class="chip${k === mode ? " on" : ""}" data-scale="${k}">${esc(t9(lbl))}</button>`).join("");
        const hint = document.createElement("div");
        hint.className = "hint muted"; hint.style.cssText = "font-size:11.5px;margin:2px 0 4px";
        const host = document.createElement("div");
        body.appendChild(ctl); body.appendChild(hint); body.appendChild(host);
        const HINTS = {
          absolute: t9("Raw values on a shared time axis — series of very different magnitudes may flatten."),
          indexed: t9("Each series rebased to 100 at the window start — relative moves, not absolute levels."),
          log: t9("Log scale (base 10) — equal ratios are equal distances; the hover shows the real value."),
        };
        const render = () => {
          hint.textContent = HINTS[mode] || "";
          ooChart(host, seriesList, {height: 360, maxWidth: 880, indexed: mode === "indexed", logY: mode === "log"});
        };
        ctl.addEventListener("click", (e) => {
          const b = e.target.closest("[data-scale]"); if (!b) return;
          mode = b.dataset.scale;
          ctl.querySelectorAll("[data-scale]").forEach(x => x.classList.toggle("on", x.dataset.scale === mode));
          render();
        });
        render();
        return;
      }
      ooChart(body, seriesList, {height: 360, maxWidth: 880});
    }

    // World map: equirectangular projection, viewBox-based zoom/pan (no deps).
    const MAP_W = 720, MAP_H = 360;
    let MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H};
    const lon2x = lon => (Number(lon) + 180) / 360 * MAP_W;
    const lat2y = lat => (90 - Number(lat)) / 180 * MAP_H;

    function applyVB() {
      const svg = document.getElementById("oo-map");
      if (svg) svg.setAttribute("viewBox", `${MAP_VB.x} ${MAP_VB.y} ${MAP_VB.w} ${MAP_VB.h}`);
    }
    function zoomMap(f) {
      const cx = MAP_VB.x + MAP_VB.w/2, cy = MAP_VB.y + MAP_VB.h/2;
      MAP_VB.w = Math.min(MAP_W, Math.max(40, MAP_VB.w * f));
      MAP_VB.h = Math.min(MAP_H, Math.max(20, MAP_VB.h * f));
      MAP_VB.x = cx - MAP_VB.w/2; MAP_VB.y = cy - MAP_VB.h/2;
      applyVB();
    }
    function resetMap() { MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H}; applyVB(); }

    function buildMapSvg(cities) {
      const placed = cities.filter(c => c.lat != null && c.lon != null);
      // graticule every 30 degrees
      let grid = "";
      for (let lon = -180; lon <= 180; lon += 30)
        grid += `<line x1="${lon2x(lon)}" y1="0" x2="${lon2x(lon)}" y2="${MAP_H}" stroke="var(--border)" stroke-width="0.3"/>`;
      for (let lat = -90; lat <= 90; lat += 30)
        grid += `<line x1="0" y1="${lat2y(lat)}" x2="${MAP_W}" y2="${lat2y(lat)}" stroke="var(--border)" stroke-width="0.3"/>`;
      const maxM = Math.max(1, ...placed.map(c => (c.top||[]).reduce((s,t)=>s+t.mentions,0)));
      const dots = placed.map(c => {
        const x = lon2x(c.lon).toFixed(1), y = lat2y(c.lat).toFixed(1);
        const m = (c.top||[]).reduce((s,t)=>s+t.mentions,0);
        const r = (1.5 + 4*Math.sqrt(m/maxM)).toFixed(1);
        const terms = (c.top||[]).map(t=>t.term+" "+t.mentions).join(", ");
        return `<g><circle cx="${x}" cy="${y}" r="${r}" fill="var(--accent)" fill-opacity="0.75">
            <title>${esc(c.name)}${c.country?" ("+esc(c.country)+")":""}: ${esc(terms)}</title></circle>
          <text x="${x}" y="${(y-Number(r)-1).toFixed(1)}" fill="var(--fg)" font-size="4" text-anchor="middle">${esc(c.name)}</text></g>`;
      }).join("");
      if (!placed.length)
        return `<div class="muted">No placed cities yet. Index the corpus (sources need a city), or generate the full gazetteer (scripts/build_city_gazetteer.py).</div>`;
      return `<svg id="oo-map" viewBox="0 0 ${MAP_W} ${MAP_H}" width="100%" style="max-width:${MAP_W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:grab">
        ${grid}${dots}</svg>`;
    }

    function wireMapDrag() {
      const svg = document.getElementById("oo-map");
      if (!svg) return;
      let dragging = false, sx = 0, sy = 0;
      svg.addEventListener("mousedown", e => { dragging = true; sx = e.clientX; sy = e.clientY; svg.style.cursor = "grabbing"; });
      window.addEventListener("mouseup", () => { dragging = false; if (svg) svg.style.cursor = "grab"; });
      svg.addEventListener("mousemove", e => {
        if (!dragging) return;
        const rect = svg.getBoundingClientRect();
        MAP_VB.x -= (e.clientX - sx) * MAP_VB.w / rect.width;
        MAP_VB.y -= (e.clientY - sy) * MAP_VB.h / rect.height;
        sx = e.clientX; sy = e.clientY; applyVB();
      });
    }

    async function loadMap() {
      const days = $("map-days").value, kind = $("map-kind").value;
      try {
        const d = await api(`/api/insights/map?days=${days}&kind=${encodeURIComponent(kind)}`);
        const rowsFor = (areas, label) => areas.length
          ? "<tr><th>" + label + "</th><th>Top keywords</th></tr>" + areas.map(a =>
              `<tr><td><strong>${esc(a.code||a.name)}</strong>${a.country&&a.name?` <span class="muted">${esc(a.country)}</span>`:""}</td><td>` +
              a.top.map(t => `<span class="pill" style="cursor:pointer" onclick='pickTerm(${esc(JSON.stringify(t.term))})'>${esc(t.term)} ${t.mentions}</span>`).join(" ") +
              `</td></tr>`).join("")
          : `<tr><td class="muted">No data — index the corpus (sources need a country/city).</td></tr>`;
        $("map-svg").innerHTML = buildMapSvg(d.cities || []);
        MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H}; wireMapDrag();
        $("map-countries").innerHTML = rowsFor(d.countries, "Country");
        $("map-cities").innerHTML = rowsFor(d.cities, "City");
      } catch (e) { toast("Map failed: " + e.message, "err"); }
    }

    // -- Temporal map: space-time signals on the world map + a time slider -- //
    // Reuses the equirectangular projection (lon2x/lat2y, MAP_W/MAP_H) with its
    // own viewBox so it pans/zooms independently of the Insights map.
    const TMAP_KINDS = {
      disaster:{c:"#e5484d", l:"Disaster"}, conflict:{c:"#d6731f", l:"Conflict"},
      milestone:{c:"#7aa2f7", l:"Milestone"}, civic:{c:"#3fb950", l:"Civic"},
      space:{c:"#bf7af0", l:"Space"}, science:{c:"#1fb8c4", l:"Science"},
      climate:{c:"#2da44e", l:"Climate"}, sport:{c:"#e3b341", l:"Sport"},
      economic:{c:"#c9a227", l:"Economic"}, political:{c:"#8b949e", l:"Political"},
      technology:{c:"#58a6ff", l:"Technology"}, hazard:{c:"#f85149", l:"Hazard (live)"},
      article:{c:"#a371f7", l:"Article"},
    };
    const kindColor = k => (TMAP_KINDS[k] || {c:"var(--muted)"}).c;

    let TMAP = {signals: [], range: null, caveat: ""};
    let TMAP_FOCUS = null;                       // fractional year in focus
    let TMAP_OFF = new Set();                     // kinds toggled off
    let TMAP_VB = {x:0, y:0, w:MAP_W, h:MAP_H};
    let _tmapVisible = [], _tmapPlay = null, TMAP_OUTLINE = null;
    // Mention layer: PLACES the corpus's articles mention (When/Where/Who, T12),
    // from /api/insights/where. Geographic only (no per-mention date), so it is a
    // static overlay independent of the time slider. OFF by default (the temporal
    // map's own signals stay the primary view; the user opts in). _tmapWhere holds
    // the endpoint payload verbatim so the method+caveat travel with the data.
    let _tmapMentionsOn = false, _tmapWhere = null;
    let _tmapDrag = false, _tmapDragSX = 0, _tmapDragSY = 0, _tmapMouseupWired = false, _tmapPrefsLoaded = false;

    // Remember the user's layers/window across sessions (local only, like agenda subs).
    const TMAP_PREFS = "oo.timemap.prefs";
    function tmapSavePrefs() {
      try { localStorage.setItem(TMAP_PREFS, JSON.stringify({
        articles: !!($("tmap-articles") && $("tmap-articles").checked),
        mentions: !!($("tmap-mentions") && $("tmap-mentions").checked),
        hazards: !!($("tmap-hazards") && $("tmap-hazards").checked),
        window: $("tmap-window") ? $("tmap-window").value : "25",
      })); } catch { /* storage may be disabled — preferences just won't persist */ }
    }
    function tmapRestorePrefs() {
      let p; try { p = JSON.parse(localStorage.getItem(TMAP_PREFS) || "null"); } catch { p = null; }
      if (!p) return;
      if ($("tmap-articles")) $("tmap-articles").checked = !!p.articles;
      if ($("tmap-mentions")) $("tmap-mentions").checked = !!p.mentions;
      if ($("tmap-hazards")) $("tmap-hazards").checked = !!p.hazards;
      if ($("tmap-window") && p.window != null) $("tmap-window").value = String(p.window);
    }
    function onTmapWindowChange() { tmapSavePrefs(); renderTimemap(); }
    const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

    function fmtYear(t) {                          // fractional year -> "Sep 2001"
      if (t == null) return "—";
      const y = Math.floor(t), doy = Math.round((t - y) * 365);
      const d = new Date(2001, 0, 1); d.setDate(doy + 1);
      return `${MON[d.getMonth()]} ${y < 0 ? "" : ""}${y}`;
    }
    function fmtDate(s) {                          // a signal's ISO date -> "Oct 24, 79"
      const m = /^(\-?\d+)-(\d{2})-(\d{2})/.exec(s.date || "");
      if (!m) return s.date || "";
      return `${MON[+m[2]-1]} ${+m[3]}, ${+m[1]}`;
    }

    function applyTmapVB() {
      const svg = document.getElementById("oo-tmap");
      if (svg) svg.setAttribute("viewBox", `${TMAP_VB.x} ${TMAP_VB.y} ${TMAP_VB.w} ${TMAP_VB.h}`);
    }
    function wireTmapWheel() {                     // Google-Maps-style wheel zoom
      const svg = document.getElementById("oo-tmap");
      if (!svg || svg._wheelWired) return;
      svg._wheelWired = true;
      svg.addEventListener("wheel", (e) => {
        e.preventDefault();
        const m = svg.getScreenCTM().inverse(); const p = svg.createSVGPoint();
        p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(m);
        const f = Math.exp(e.deltaY * 0.0015);
        const w = Math.min(MAP_W, Math.max(MAP_W * 0.03, TMAP_VB.w * f));
        const sc = w / TMAP_VB.w;
        TMAP_VB.x = q.x - (q.x - TMAP_VB.x) * sc;
        TMAP_VB.y = q.y - (q.y - TMAP_VB.y) * sc;
        TMAP_VB.w = w; TMAP_VB.h *= sc;
        applyTmapVB(); renderTimemap();
      }, {passive: false});
    }
    function zoomTmap(f) {
      const cx = TMAP_VB.x + TMAP_VB.w/2, cy = TMAP_VB.y + TMAP_VB.h/2;
      TMAP_VB.w = Math.min(MAP_W, Math.max(30, TMAP_VB.w * f));
      TMAP_VB.h = Math.min(MAP_H, Math.max(15, TMAP_VB.h * f));
      TMAP_VB.x = cx - TMAP_VB.w/2; TMAP_VB.y = cy - TMAP_VB.h/2;
      applyTmapVB(); renderTimemap();             // re-render to toggle labels (semantic zoom)
    }
    function resetTmap() { TMAP_VB = {x:0, y:0, w:MAP_W, h:MAP_H}; applyTmapVB(); renderTimemap(); }

    function wireTmapDrag() {
      const svg = document.getElementById("oo-tmap");
      if (!svg) return;
      // svg-bound listeners die with the element when the next render replaces it; the
      // window-level mouseup is attached exactly ONCE (drag state is module-level) so it
      // can't accumulate across the many re-renders that 'play' triggers.
      svg.addEventListener("mousedown", e => {
        _tmapDrag = true; _tmapDragSX = e.clientX; _tmapDragSY = e.clientY; svg.style.cursor = "grabbing"; });
      svg.addEventListener("mousemove", e => {
        if (!_tmapDrag) return;
        const r = svg.getBoundingClientRect();
        TMAP_VB.x -= (e.clientX - _tmapDragSX) * TMAP_VB.w / r.width;
        TMAP_VB.y -= (e.clientY - _tmapDragSY) * TMAP_VB.h / r.height;
        _tmapDragSX = e.clientX; _tmapDragSY = e.clientY; applyTmapVB();
      });
      if (!_tmapMouseupWired) {
        _tmapMouseupWired = true;
        window.addEventListener("mouseup", () => {
          _tmapDrag = false;
          const s = document.getElementById("oo-tmap"); if (s) s.style.cursor = "grab";
        });
      }
    }

    let TMAP_SPAN_OVERRIDE = null;                 // [a,b] fractional years (user-set)
    function dateToT(iso) {                        // YYYY-MM-DD -> fractional year
      const d = new Date(iso + "T00:00:00Z");
      if (isNaN(d)) return null;
      const y = d.getUTCFullYear(), start = Date.UTC(y, 0, 1);
      return y + (d.getTime() - start) / (Date.UTC(y + 1, 0, 1) - start);
    }
    function tToDate(t) {                          // fractional year -> YYYY-MM-DD
      const y = Math.floor(t), start = Date.UTC(y, 0, 1);
      const ms = start + (t - y) * (Date.UTC(y + 1, 0, 1) - start);
      return new Date(ms).toISOString().slice(0, 10);
    }
    function onTmapSpanChange() {                  // re-map the slider onto a period
      const a = $("tmap-span-a").value, b = $("tmap-span-b").value;
      TMAP_SPAN_OVERRIDE = (a && b && a < b) ? [dateToT(a), dateToT(b)] : null;
      $("tmap-slider").value = 1000; onTmapSlide(); buildTmapStrip();
    }
    function onTmapDate() {                        // precise manual focus
      const t = dateToT($("tmap-date").value);
      if (t == null) return;
      $("tmap-slider").value = tToSlider(t); onTmapSlide();
    }
    function tmapExpand() {
      $("tmap-wrap").classList.toggle("mm-big");
      $("tmap-expand").textContent = $("tmap-wrap").classList.contains("mm-big") ? "🗗" : "⛶";
      renderTimemap();
    }
    function tmapSpan() {                          // [min,max] fractional years, padded
      if (TMAP_SPAN_OVERRIDE) return TMAP_SPAN_OVERRIDE;
      const r = TMAP.range || {};
      if (r.min == null) return [2000, 2030];
      const pad = Math.max(1, (r.max - r.min) * 0.02);
      return [r.min - pad, r.max + pad];
    }
    function sliderToT(v) { const [a, b] = tmapSpan(); return a + (v/1000) * (b - a); }
    function tToSlider(t) { const [a, b] = tmapSpan(); return b > a ? Math.round((t-a)/(b-a)*1000) : 1000; }

    function onTmapSlide() {
      TMAP_FOCUS = sliderToT(+$("tmap-slider").value);
      $("tmap-focus-label").textContent = fmtYear(TMAP_FOCUS);
      if (TMAP_FOCUS > 1583 && TMAP_FOCUS < 9999) $("tmap-date").value = tToDate(TMAP_FOCUS);
      renderTimemap();
    }

    function toggleTmapKind(k) {
      if (TMAP_OFF.has(k)) TMAP_OFF.delete(k); else TMAP_OFF.add(k);
      buildTmapLegend(); renderTimemap();
    }
    function buildTmapLegend() {
      const counts = (TMAP.range && TMAP.range.by_kind) || {};
      const present = Object.keys(TMAP_KINDS).filter(k => counts[k]);
      $("tmap-legend").innerHTML = present.map(k => {
        const off = TMAP_OFF.has(k);
        return `<button class="tiny" onclick="toggleTmapKind('${k}')" title="show/hide"
          style="border-color:${kindColor(k)};opacity:${off?0.4:1};display:inline-flex;align-items:center;gap:5px">
          <span style="width:9px;height:9px;border-radius:50%;background:${kindColor(k)};display:inline-block"></span>
          ${esc(TMAP_KINDS[k].l)} <span class="muted">${counts[k]}</span></button>`;
      }).join("") || `<span class="muted">No signals to show.</span>`;
      buildTmapMentionLegend();                    // append the mention-layer caveat line (never overwrites the kinds)
    }

    // ----- Mention layer: places the corpus's articles MENTION (T12) -------- //
    // Reuses the temporal map's equirectangular projection (lon2x/lat2y) and its
    // render loop — no second projection. Fed by GET /api/insights/where verbatim,
    // so the endpoint's method + "Deduced from text, never confirmed." caveat travel
    // with the data. Marker AREA scales with the article SPREAD (honest: r∝√spread),
    // never a fabricated score. Places with null lat/lon are NOT plotted; their count
    // is surfaced. OFF by default (the map's own signals stay primary; the user opts in).
    let _tmapWhereMapped = [];                      // the plotted subset (for click indexing)

    async function toggleTmapMentions() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      _tmapMentionsOn = !_tmapMentionsOn;
      const btn = $("tmap-mentions-toggle");
      if (btn) {                                     // FILL=state cue, like the kind chips
        btn.setAttribute("aria-pressed", _tmapMentionsOn ? "true" : "false");
        btn.style.borderColor = _tmapMentionsOn ? "var(--accent)" : "";
        btn.style.color = _tmapMentionsOn ? "var(--accent)" : "";
      }
      if (_tmapMentionsOn && _tmapWhere == null) {   // lazy fetch, only when first switched on
        if (btn) btn.disabled = true;
        try {
          // Both city + country (kind omitted = both); bounded by the endpoint (limit ≤ 500).
          _tmapWhere = await api("/api/insights/where?limit=500");
        } catch (e) {
          _tmapWhere = null; _tmapMentionsOn = false;
          if (btn) { btn.classList.remove("active"); btn.setAttribute("aria-pressed", "false"); }
          toast(t("Could not load mentioned places: ") + e.message, "err");
        } finally { if (btn) btn.disabled = false; }
      }
      buildTmapLegend(); renderTimemap();
    }

    function buildTmapMentionLegend() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const el = $("tmap-legend"); if (!el) return;
      if (!_tmapMentionsOn) return;
      const w = _tmapWhere;
      const placed = w ? (w.placed || 0) : 0;
      const unmapped = w ? Math.max(0, (w.count || 0) - placed) : 0;
      // The "deduced, never confirmed" caveat is VISIBLE on the layer (informed consent),
      // with the endpoint's long-form method in the hover bubble (invariant #17 layering).
      const caveat = (w && w.caveat) || "Deduced from text, never confirmed.";
      let line;
      if (!w) {
        line = `<span class="muted">${esc(t("Loading mentioned places…"))}</span>`;
      } else if (!placed) {
        line = `<span class="muted">${esc(t("No mapped mentions in your corpus yet."))}</span>`;
      } else {
        line = `<span style="display:inline-flex;align-items:center;gap:5px">
            <span style="width:9px;height:9px;border-radius:50%;background:var(--accent);opacity:0.55;display:inline-block"></span>
            <strong>${placed}</strong> ${esc(t("mentioned places"))}</span>
          <span class="warn" title="${esc(w.method || caveat)}">— ${esc(t(caveat))}</span>`
          + (unmapped ? ` <span class="muted" title="${esc(t("These places have no known coordinate, so they are not drawn on the map."))}">· ${unmapped} ${esc(t("places not mapped (no coordinates)"))}</span>` : "");
      }
      el.insertAdjacentHTML("beforeend",
        `<div style="flex-basis:100%;margin-top:4px;font-size:12px">${line}</div>`);
    }

    function buildTmapMentionLayer() {
      _tmapWhereMapped = [];
      if (!_tmapMentionsOn || !_tmapWhere || !Array.isArray(_tmapWhere.places)) return "";
      // Plot EVERY returned place with a coordinate (the endpoint already bounds the set).
      _tmapWhereMapped = _tmapWhere.places.filter(p => p.lat != null && p.lon != null);
      if (!_tmapWhereMapped.length) return "";
      const labels = TMAP_VB.w < MAP_W * 0.55;       // same semantic-zoom rule as the signals
      const maxArts = Math.max(1, ..._tmapWhereMapped.map(p => +p.articles || 0));
      const markers = _tmapWhereMapped.map((p, i) => {
        const x = lon2x(p.lon).toFixed(1), y = lat2y(p.lat).toFixed(1);
        // AREA ∝ article spread ⇒ radius ∝ √spread (honest; no composite score).
        const r = (1.6 + 4.0 * Math.sqrt((+p.articles || 0) / maxArts)).toFixed(1);
        const lab = labels ? `<text x="${x}" y="${(+y - +r - 1).toFixed(1)}" fill="var(--fg)"
          font-size="3.2" text-anchor="middle" opacity="0.8">${esc((p.name || "").slice(0, 40))}</text>` : "";
        return `<g style="cursor:pointer" onclick="showTmapWhereDetail(${i})">
          <circle cx="${x}" cy="${y}" r="${(+r + 3).toFixed(1)}" fill="transparent" stroke="none"></circle>
          <circle cx="${x}" cy="${y}" r="${r}" fill="var(--accent)" fill-opacity="0.45"
            stroke="var(--accent)" stroke-width="0.5"><title>${esc(p.name || "")}${p.country ? " (" + esc(p.country.toUpperCase()) + ")" : ""} — ${(+p.articles || 0)} ${esc("articles")}, ${(+p.mentions || 0)} ${esc("mentions")}</title></circle>${lab}</g>`;
      }).join("");
      return `<g class="tmap-mentions">${markers}</g>`;
    }

    function showTmapWhereDetail(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const p = _tmapWhereMapped[i]; if (!p) return;
      const caveat = (_tmapWhere && _tmapWhere.caveat) || "Deduced from text, never confirmed.";
      const method = (_tmapWhere && _tmapWhere.method) || "";
      const cov = (p.name || "").trim();
      $("tmap-detail").innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="width:11px;height:11px;border-radius:50%;background:var(--accent);opacity:0.55;display:inline-block"></span>
          <strong>${esc(p.name || "")}</strong>
          ${p.country ? `<span class="pill">${esc(p.country.toUpperCase())}</span>` : ""}
          <span class="pill">${esc(p.kind === "country" ? t("country") : t("city"))}</span>
          <span class="pill warn" title="${esc(t("A place name extracted from article text, placed at a gazetteer coordinate."))}">${esc(t("mentioned · deduced"))}</span>
        </div>
        <div class="muted" style="margin-top:5px;font-size:13px">
          <strong>${(+p.articles || 0)}</strong> ${esc(t("articles mention it"))}
          · <strong>${(+p.mentions || 0)}</strong> ${esc(t("total mentions"))}
          · ${(+p.lat).toFixed(2)}, ${(+p.lon).toFixed(2)}
        </div>
        <div class="hint" style="margin-top:5px" title="${esc(method)}">${esc(t(caveat))}</div>
        <div class="row" style="margin-top:7px;gap:8px">
          ${cov ? `<button class="tiny secondary" onclick="tmapFindCoverage(${esc(JSON.stringify(cov))})">${esc(t("Find coverage in your corpus"))}</button>` : ""}
        </div>
      </div>`;
    }

    function stopTmapPlay() {                       // also called by showTab when leaving the tab
      if (_tmapPlay) { clearInterval(_tmapPlay); _tmapPlay = null; }
      const btn = $("tmap-play"); if (btn) btn.textContent = "▶ play";
    }
    function toggleTmapPlay() {
      if (_tmapPlay) { stopTmapPlay(); return; }
      const btn = $("tmap-play"); if (btn) btn.textContent = "❚❚ pause";
      _tmapPlay = setInterval(() => {
        const speed = Number($("tmap-speed").value) || 1;   // user-tweakable sweep speed
        const s = $("tmap-slider"); let v = +s.value + 6 * speed;
        if (v >= 1000) { v = 1000; stopTmapPlay(); }
        s.value = v; onTmapSlide();
      }, 120);
    }

    function buildTmapStrip() {                    // density-over-time orientation strip
      const [a, b] = tmapSpan(), W = 1000, H = 22, N = 80;
      const bins = new Array(N).fill(0);
      TMAP.signals.forEach(s => {
        if (TMAP_OFF.has(s.kind)) return;
        const i = Math.min(N-1, Math.max(0, Math.floor((s.t - a)/(b - a) * N)));
        bins[i]++;
      });
      const max = Math.max(1, ...bins);
      const bars = bins.map((c, i) => c ? `<rect x="${(i/N*W).toFixed(1)}" y="${(H-2 - (H-4)*Math.sqrt(c/max)).toFixed(1)}"
        width="${(W/N-1).toFixed(1)}" height="${((H-2)-(H-2 - (H-4)*Math.sqrt(c/max))).toFixed(1)}"
        fill="var(--accent)" fill-opacity="0.6"/>` : "").join("");
      const cx = TMAP_FOCUS == null ? W : (TMAP_FOCUS - a)/(b - a) * W;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" onclick="stripClick(event)"
        style="height:22px;background:var(--panel2);border:1px solid var(--border);border-radius:5px;cursor:crosshair">
        ${bars}<line x1="${cx.toFixed(1)}" y1="0" x2="${cx.toFixed(1)}" y2="${H}" stroke="var(--fg)" stroke-width="2"/></svg>`;
    }
    function stripClick(ev) {
      const svg = ev.currentTarget, r = svg.getBoundingClientRect();
      const v = Math.round((ev.clientX - r.left)/r.width * 1000);
      $("tmap-slider").value = Math.min(1000, Math.max(0, v)); onTmapSlide();
    }

    // Real coastlines, only if the offline outline asset has been generated
    // (scripts/build_world_outline.py). Never fabricated — absent -> graticule only.
    function buildTmapCoast() {
      if (!TMAP_OUTLINE || !TMAP_OUTLINE.rings) return "";
      const paths = TMAP_OUTLINE.rings.map(ring => {
        let d = "", prevLon = null;
        ring.forEach(([lon, lat]) => {
          const cmd = (prevLon == null || Math.abs(lon - prevLon) > 180) ? "M" : "L";  // break across the dateline
          d += `${cmd}${lon2x(lon).toFixed(1)} ${lat2y(lat).toFixed(1)}`;
          prevLon = lon;
        });
        return `<path d="${d}Z" fill="var(--panel3)" fill-opacity="0.5" stroke="var(--border)" stroke-width="0.3"/>`;
      }).join("");
      return paths;
    }

    function buildTmapSvg() {
      const win = +$("tmap-window").value, focus = TMAP_FOCUS;
      const labels = TMAP_VB.w < MAP_W * 0.55;     // semantic zoom: labels only when zoomed in
      const coast = buildTmapCoast();
      let grid = "";
      for (let lon = -180; lon <= 180; lon += 30)
        grid += `<line x1="${lon2x(lon)}" y1="0" x2="${lon2x(lon)}" y2="${MAP_H}" stroke="var(--border)" stroke-width="0.3"/>`;
      for (let lat = -90; lat <= 90; lat += 30)
        grid += `<line x1="0" y1="${lat2y(lat)}" x2="${MAP_W}" y2="${lat2y(lat)}" stroke="var(--border)" stroke-width="0.3"/>`;

      _tmapVisible = TMAP.signals.filter(s =>
        !TMAP_OFF.has(s.kind) && (win === 0 || focus == null || Math.abs(s.t - focus) <= win));
      const dots = _tmapVisible.map((s, i) => {
        const x = lon2x(s.lon).toFixed(1), y = lat2y(s.lat).toFixed(1);
        const dist = focus == null ? 0 : Math.abs(s.t - focus);
        const span = win || (tmapSpan()[1] - tmapSpan()[0]) || 1;
        const op = Math.max(0.15, 1 - (dist/span) * 0.8);
        const future = focus != null && s.t > focus + 0.001;
        const mag = +s.magnitude || 0;
        const r = (mag ? 1.8 + mag*0.7 : (s.confirmed ? 3 : 2.4)).toFixed(1);
        const col = kindColor(s.kind);
        const ring = future || !s.confirmed
          // fill="transparent" (not "none"): the whole disc stays a hit target —
          // hollow rings were clickable only on their 1px edge (live test 2026-06-11).
          ? `fill="transparent" stroke="${col}" stroke-width="1.1" stroke-dasharray="${future?'2 1.5':''}"`
          : `fill="${col}" fill-opacity="0.82" stroke="var(--bg)" stroke-width="0.4"`;
        const lab = labels ? `<text x="${x}" y="${(+y - +r - 1).toFixed(1)}" fill="var(--fg)"
          font-size="3.4" text-anchor="middle" opacity="${op.toFixed(2)}">${esc((s.title||"").slice(0,42))}</text>` : "";
        return `<g opacity="${op.toFixed(2)}" style="cursor:pointer" onclick="showTmapDetail(${i})">
          <circle cx="${x}" cy="${y}" r="${(+r + 3.5).toFixed(1)}" fill="transparent" stroke="none"></circle>
          <circle cx="${x}" cy="${y}" r="${r}" ${ring}><title>${esc(s.title)} — ${esc(fmtDate(s))}</title></circle>${lab}</g>`;
      }).join("");

      const mentions = buildTmapMentionLayer();    // static place-mention overlay (sets _tmapWhereMapped)

      // With no curated signals AND the mention layer off, there is nothing to map.
      // But once the user opts into mentions, keep the map so the overlay can render.
      if (!TMAP.signals.length && !mentions)
        return `<div class="muted">No signals with both a place and a date yet. Curated anchors ship by default;
          index a geocoded corpus, enable live hazards, or install the events agenda to add more.</div>`;
      return `<svg id="oo-tmap" viewBox="0 0 ${MAP_W} ${MAP_H}" width="100%"
        style="max-width:${MAP_W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:grab">
        ${coast}${grid}${dots}${mentions}</svg>`;
    }

    // The honest seed of "convergence": other signals close in BOTH place and time.
    // It is co-occurrence only — never a claim of connection or cause. The reader judges.
    const TMAP_NEAR_DEG = 15;                      // ~1500 km at the equator
    function tmapNearby(s) {
      const win = +$("tmap-window").value || 25;   // reuse the chosen time window (else ±25y)
      const out = [];
      _tmapVisible.forEach((o, idx) => {
        if (o === s) return;
        const dt = Math.abs(o.t - s.t);
        const dlon = Math.abs(o.lon - s.lon), dlat = Math.abs(o.lat - s.lat);
        if (dt <= win && dlon <= TMAP_NEAR_DEG && dlat <= TMAP_NEAR_DEG)
          out.push({idx, o, score: dt/(win||1) + Math.hypot(dlon, dlat)/TMAP_NEAR_DEG});
      });
      return out.sort((a, b) => a.score - b.score).slice(0, 6);
    }

    // Close the space-time loop: jump to a corpus search for this place/subject.
    function tmapFindCoverage(q) {
      showTab("search");
      const i = $("q"); if (i) i.value = q;
      if (typeof doSearch === "function") doSearch();
    }

    function showTmapDetail(i) {
      const s = _tmapVisible[i]; if (!s) return;
      const url = s.url ? safeUrl(s.url) : null;
      const cov = (s.place || s.title || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
      const geo = s.geocode === "country" ? `<span class="pill warn" title="country-level stand-in point, not the exact spot">≈ country</span>`
                : s.geocode === "city" ? `<span class="pill" title="placed at a known city">city</span>` : "";
      const conf = s.source === "corpus-mention" ? `<span class="pill warn" title="a date extracted from article text">mentioned · extracted</span>`
                 : s.confirmed ? `<span class="pill ok">confirmed</span>` : `<span class="pill warn">unconfirmed / scheduled</span>`;
      $("tmap-detail").innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="width:11px;height:11px;border-radius:50%;background:${kindColor(s.kind)};display:inline-block"></span>
          <strong>${esc(s.title)}</strong>
          <span class="pill">${esc(TMAP_KINDS[s.kind]?.l || s.kind)}</span> ${conf} ${geo}
        </div>
        <div class="muted" style="margin-top:5px;font-size:13px">
          ${esc(fmtDate(s))}${s.place?` · ${esc(s.place)}`:""}${s.country?` (${esc(s.country.toUpperCase())})`:""}
          · ${(+s.lat).toFixed(2)}, ${(+s.lon).toFixed(2)} · <span title="data source">${esc(s.source)}</span>
        </div>
        ${s.note?`<div class="hint" style="margin-top:5px">${esc(s.note)}</div>`:""}
        <div class="row" style="margin-top:7px;gap:8px">
          ${url?extLink(url, "Official / reference source ↗", "tiny secondary", "text-decoration:none;align-self:center"):""}
          ${cov?`<button class="tiny secondary" onclick="tmapFindCoverage(${esc(JSON.stringify(cov))})">Find coverage in your corpus</button>`:""}
        </div>
        ${(() => {
          const near = tmapNearby(s);
          if (!near.length) return "";
          const items = near.map(n => `<button class="tiny secondary" style="margin:2px 3px 0 0"
            onclick="showTmapDetail(${n.idx})" title="${esc(fmtDate(n.o))}${n.o.place?' · '+esc(n.o.place):''}">
            <span style="width:8px;height:8px;border-radius:50%;background:${kindColor(n.o.kind)};display:inline-block;margin-right:4px"></span>
            ${esc((n.o.title||'').slice(0,38))} <span class="muted">${n.o.year}</span></button>`).join("");
          return `<div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px">
            <div style="font-size:12px"><strong>Near in space &amp; time</strong>
              <span class="warn" title="These signals are merely close in place and time within your current window.">— co-occurrence, not a connection or cause. You judge.</span></div>
            <div style="margin-top:4px">${items}</div></div>`;
        })()}
      </div>`;
    }

    function renderTimemap() {
      $("tmap-strip").innerHTML = buildTmapStrip();
      const svg = buildTmapSvg();                  // sets _tmapVisible
      const note = (TMAP.signals.length && !_tmapVisible.length)
        ? `<div class="hint" style="margin-top:6px">No signals fall in this time window — widen the <b>Window</b> or move the slider.</div>` : "";
      $("tmap-svg").innerHTML = svg + note;
      applyTmapVB(); wireTmapDrag(); wireTmapWheel();
    }

    async function loadTimemap() {
      if (!_tmapPrefsLoaded) { _tmapPrefsLoaded = true; tmapRestorePrefs(); }  // restore once, before reading controls
      const hz = $("tmap-hazards") && $("tmap-hazards").checked;
      const arts = $("tmap-articles") && $("tmap-articles").checked;
      const ment = $("tmap-mentions") && $("tmap-mentions").checked;
      tmapSavePrefs();
      $("tmap-status").textContent = "Loading…";
      if (TMAP_OUTLINE == null) {                 // best-effort, once: real coastlines if the asset exists
        try { const o = await fetch("/static/world_outline.json"); TMAP_OUTLINE = o.ok ? await o.json() : false; }
        catch { TMAP_OUTLINE = false; }            // absent -> graticule fallback, no error
      }
      try {
        const d = await api(`/api/timemap?limit=4000${hz?"&hazards=true":""}${arts?"&articles=true":""}${ment?"&mentions=true":""}`);
        TMAP = {signals: d.signals || [], range: d.range || null, caveat: d.caveat || ""};
        const r = TMAP.range || {};
        $("tmap-status").innerHTML = `${TMAP.signals.length} signals · ${r.min!=null?Math.floor(r.min):"?"}–${r.max!=null?Math.ceil(r.max):"?"}`
          + ((d.failures && d.failures.length) ? ` · <span class="warn" title="${esc(d.failures.join('; '))}">${d.failures.length} source(s) unavailable</span>` : "");
        // Fallback so the honest framing never silently disappears (audit 0.0.9).
        $("tmap-caveat").textContent = TMAP.caveat ||
          "Signals are placed where their source/extracted location says; co-occurrence in space and time is not causation.";
        if (TMAP_FOCUS == null || TMAP_FOCUS < tmapSpan()[0] || TMAP_FOCUS > tmapSpan()[1]) {
          $("tmap-slider").value = 1000; TMAP_FOCUS = sliderToT(1000);   // start "now-ish" (latest)
        }
        $("tmap-focus-label").textContent = fmtYear(TMAP_FOCUS);
        buildTmapLegend(); renderTimemap();
      } catch (e) {
        $("tmap-status").innerHTML = `<span class="err">Could not load: ${esc(e.message)}</span>`;
      }
    }

    // -- Wikipedia change-tracking ------------------------------------------ //
    let _wikiLangsLoaded = false;
    async function loadWikiLanguages() {
      if (_wikiLangsLoaded) return;
      try {
        const d = await api("/api/wiki/languages");
        const sel = $("wiki-lang"); if (!sel) return;
        const cur = sel.value || "en";
        sel.innerHTML = "";
        // ONE flat list (invariant #1, amended 2026-06-16: no continent optgroups);
        // the native name (autonym) leads as the identifier (invariant #15).
        (d.languages || []).forEach(l => {
          const o = document.createElement("option");
          o.value = l.code; o.textContent = `${l.autonym} — ${l.name} (${l.code})`;
          sel.appendChild(o);
        });
        sel.value = cur; if (!sel.value) sel.value = "en";
        _wikiLangsLoaded = true;
      } catch (e) { /* keep the en default */ }
    }

    async function loadWiki() {
      loadWikiLanguages();
      try { renderWikiStatus(await api("/api/wiki/status")); }
      catch (e) { if (!_wikiStatusBuilt) $("wiki-status").textContent = "Status unavailable: " + e.message; }
      loadWikiPages(); loadWikiChanges();
    }

    async function loadWikiDumps() {
      loadReadableDumps();  // keep the local-reader edition list in step
      try {
        const d = await api("/api/wiki/dumps");
        const t = $("dump-table");
        if (!d.downloads.length) { t.innerHTML = `<tr><td class="muted">No offline downloads.</td></tr>`; return; }
        t.innerHTML = "<tr><th>Edition</th><th>Progress</th><th>Status</th><th></th></tr>" +
          d.downloads.map(e => `<tr>
            <td><strong>${esc(e.wiki)}</strong> <span class="muted">${esc(e.kind)}</span></td>
            <td>${humanBytes(e.downloaded_bytes)}${e.total_bytes?` / ${humanBytes(e.total_bytes)} (${e.percent}%)`:""}</td>
            <td><span class="pill ${e.status==='done'?'ok':e.status==='error'?'err':e.status==='downloading'?'':'warn'}">${esc(e.status)}</span>${e.error?` <span class="muted">${esc(e.error)}</span>`:""}</td>
            <td style="white-space:nowrap">
              ${e.status==='downloading'?`<button class="tiny secondary" onclick="pauseDump(${esc(JSON.stringify(e.key))})">Pause</button>`:
                (e.status!=='done'?`<button class="tiny secondary" onclick="startDump(${esc(JSON.stringify(e.wiki))})">Resume</button>`:"")}
              <button class="tiny danger" onclick="deleteDump(${esc(JSON.stringify(e.key))})">Delete</button>
            </td></tr>`).join("");
      } catch (e) { /* dumps optional */ }
    }

    function dumpSelected() {                      // multi-select (maintainer 2026-06-11)
      return [...$("dump-lang").selectedOptions].map(o => o.value).filter(Boolean);
    }
    async function probeDump() {
      const w = dumpSelected()[0] || "en";
      $("dump-estimate").textContent = "Checking size…";
      try {
        const d = await api(`/api/wiki/dumps/probe?wiki=${encodeURIComponent(w)}`);
        $("dump-estimate").textContent = d.size_bytes ? `≈ ${humanBytes(d.size_bytes)} for ${d.wiki}` : "size unknown";
      } catch (e) { $("dump-estimate").textContent = "size check failed"; }
    }

    async function startDump(wiki) {
      // Several selected editions download sequentially (one polite queue).
      const picks = wiki ? [wiki] : dumpSelected();
      if (picks.length > 1) {
        for (const code of picks) await startDump(code);
        return;
      }
      const w = picks[0] || "en";
      if (!wiki && !confirm(`Download the ${w} current-text dump? This can be very large (tens of GB for big editions).`)) return;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Download a Wikipedia dump"))) return;
      try { await api("/api/wiki/dumps/start", {method:"POST", body: JSON.stringify({wiki: w})});
        toast("Download started."); loadWikiDumps();
        // refresh progress a few times
        let n=0; const poll=setInterval(()=>{ loadWikiDumps(); if(++n>40) clearInterval(poll); }, 3000);
      } catch (e) { toast("Start failed: " + e.message, "err"); }
    }
    async function pauseDump(key) {
      try { await api("/api/wiki/dumps/pause?key="+encodeURIComponent(key), {method:"POST"}); loadWikiDumps(); }
      catch (e) { toast("Pause failed: " + e.message, "err"); }
    }
    async function deleteDump(key) {
      if (!confirm("Delete this download and its file?")) return;
      try { await api("/api/wiki/dumps?key="+encodeURIComponent(key), {method:"DELETE"}); loadWikiDumps(); }
      catch (e) { toast("Delete failed: " + e.message, "err"); }
    }

    // -- Offline map: OSM region downloads (Group M) ------------------------- //
    // Mirrors the Wikipedia dump UI: a zero-network catalogue picker (size = a
    // DATED estimate, exact size read on download) + a resumable download-job
    // table. Starting a download is a NETWORK action, so it passes the ONE consent
    // popup (ensureOnline, invariant #14) and is refused while airplane mode is on
    // (the backend's guarded factory enforces the kill switch too).
    async function loadOsmMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sel = $("osm-region"); if (!sel) return;
      try {
        const d = await api("/api/geo/regions");
        sel.innerHTML = (d.regions || []).map(r =>
          `<option value="${esc(r.code)}">${esc(r.name)} · ~${humanBytes(r.size_estimate_bytes)} · ${esc(r.continent)}</option>`
        ).join("") || `<option value="">${esc(t("No regions."))}</option>`;
        const note = $("osm-size-note"), asof = $("osm-size-asof");
        if (note && asof && d.size_estimate_as_of) { asof.textContent = d.size_estimate_as_of; note.hidden = false; }
      } catch (e) { sel.innerHTML = `<option value="">${esc(t("Could not load regions."))}</option>`; }
      loadOsmDownloads();
    }
    async function loadOsmDownloads() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tbl = $("osm-dl-table"); if (!tbl) return;
      try {
        const d = await api("/api/geo/downloads");
        if (!d.downloads.length) { tbl.innerHTML = `<tr><td class="muted">${esc(t("No offline downloads."))}</td></tr>`; return; }
        tbl.innerHTML = `<tr><th>${esc(t("Region"))}</th><th>${esc(t("Progress"))}</th><th>${esc(t("Status"))}</th><th></th></tr>` +
          d.downloads.map(e => `<tr>
            <td><strong>${esc(e.name || e.code)}</strong></td>
            <td>${humanBytes(e.downloaded_bytes)}${e.total_bytes?` / ${humanBytes(e.total_bytes)} (${e.percent}%)`:(e.size_estimate_bytes?` <span class="muted">~${humanBytes(e.size_estimate_bytes)}</span>`:"")}</td>
            <td><span class="pill ${e.status==='done'?'ok':e.status==='error'?'err':e.status==='downloading'?'':'warn'}">${esc(e.status)}</span>${e.error?` <span class="muted">${esc(e.error)}</span>`:""}</td>
            <td style="white-space:nowrap">
              ${e.status==='downloading'?`<button class="tiny secondary" onclick="pauseOsm(${esc(JSON.stringify(e.key))})">${esc(t("Pause"))}</button>`:
                (e.status!=='done'?`<button class="tiny secondary" onclick="resumeOsm(${esc(JSON.stringify(e.code))})">${esc(t("Resume"))}</button>`:"")}
              <button class="tiny danger" onclick="deleteOsm(${esc(JSON.stringify(e.key))})">${esc(t("Delete"))}</button>
            </td></tr>`).join("");
      } catch (e) { /* downloads optional — degrade quietly */ }
    }
    async function startOsmDownload(code) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = code || $("osm-region").value;
      if (!c) return;
      // A user-initiated (not resume) start confirms the heavy download first.
      if (!code && !confirm(t("Download this offline map region? These can be very large (several GB to tens of GB)."))) return;
      // Every offline->online transition passes the ONE consent popup (invariant #14).
      if (!await ensureOnline(t("Download an offline map region"))) return;
      try {
        await api("/api/geo/downloads/start", {method:"POST", body: JSON.stringify({code: c})});
        toast(t("Download started.")); loadOsmDownloads();
        let n=0; const poll=setInterval(()=>{ loadOsmDownloads(); if(++n>40) clearInterval(poll); }, 3000);
      } catch (e) { toast("Start failed: " + e.message, "err"); }
    }
    function resumeOsm(code) { startOsmDownload(code); }
    async function pauseOsm(key) {
      try { await api("/api/geo/downloads/pause?key="+encodeURIComponent(key), {method:"POST"}); loadOsmDownloads(); }
      catch (e) { toast("Pause failed: " + e.message, "err"); }
    }
    async function deleteOsm(key) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Delete this download and its file?"))) return;
      try { await api("/api/geo/downloads?key="+encodeURIComponent(key), {method:"DELETE"}); loadOsmDownloads(); }
      catch (e) { toast("Delete failed: " + e.message, "err"); }
    }

    // -- Official statistics producers (Group N): the curated directory + the --- //
    //    one-click "register as DISABLED controversial sources" action.          //
    //    Descriptive only: NO figures, NO score; every producer is a STANCED      //
    //    source by ruling (the "controversial" pill states it, never a verdict).  //
    //    home URLs open the LOCAL link-preview first (extLink, invariant #6/#6e). //
    async function loadStatAgencies() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("stat-agencies"); if (!box) return;
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const d = await api("/api/stats/agencies");
        const ags = d.agencies || [];
        const cov = $("stat-coverage");
        if (cov) {
          // Honest coverage line: how many continents have at least one national producer.
          const n = (d.continents_covered || []).length;
          cov.textContent = t("Continents covered: {n}").replace("{n}", n)
            + " · " + (ags.length) + " " + t("producers");
        }
        if (!ags.length) { box.innerHTML = `<div class="muted">${esc(t("No producers listed."))}</div>`; return; }
        // The API already orders international-first, then by region, then name —
        // render in that order (no client re-sort needed). Scope is labelled, not raw.
        const scope = (s) => s === "international" ? t("International")
          : s === "national" ? t("National") : (s || "");
        const rows = ags.map(a => `<tr>
            <td><strong>${esc(a.name)}</strong>${a.acronym ? ` <span class="muted">(${esc(a.acronym)})</span>` : ""}</td>
            <td>${esc(scope(a.scope))}</td>
            <td>${a.country ? esc(String(a.country).toUpperCase()) : "<span class=\"muted\">—</span>"}</td>
            <td>${esc(a.region || "")}</td>
            <td>${a.home_url ? extLink(a.home_url, a.home_url) : ""}</td>
            <td><span class="pill warn">${esc(t("controversial"))}</span></td>
          </tr>`).join("");
        box.innerHTML = `<table>
          <tr><th>${esc(t("Name"))}</th><th>${esc(t("Scope"))}</th><th>${esc(t("Country"))}</th>`
          + `<th>${esc(t("Region"))}</th><th>${esc(t("Official site"))}</th><th></th></tr>${rows}</table>`;
        // The API caveat travels with the data, visible by default (informed consent).
        if (d.caveat) box.innerHTML += `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>`;
      } catch (e) {
        box.innerHTML = `<div class="muted">${esc(t("Could not load the statistics directory."))}</div>`;
      }
    }
    async function ingestStatSources() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const msg = $("stat-ingest-msg"), btn = $("stat-ingest-btn");
      if (!confirm(t("Register all official-statistics producers as DISABLED sources? They are added controversial and NOT scraped."))) return;
      if (btn) btn.disabled = true;
      if (msg) msg.textContent = t("Registering…");
      try {
        // LOCAL DB write — the endpoint opens ZERO external sockets, so this works in
        // airplane mode and never needs the network-consent gate (no ensureOnline).
        const d = await api("/api/stats/sources/ingest", { method: "POST" });
        const n = (x) => (x || 0).toLocaleString();
        if (msg) {
          msg.innerHTML = `<b>${n(d.created)}</b> ${esc(t("created"))} · ${n(d.skipped_existing)} ${esc(t("already present"))}`
            + (d.skipped_no_domain ? ` · ${n(d.skipped_no_domain)} ${esc(t("skipped (no domain)"))}` : "")
            + (d.caveat ? `<div class="muted" style="margin-top:5px">${esc(d.caveat)}</div>` : "");
        }
        toast(t("Statistics producers registered."), "ok");
      } catch (e) {
        if (msg) msg.innerHTML = `<span class="note err">${esc(t("Could not register the producers."))}: ${esc(e.message)}</span>`;
        else toast(t("Could not register the producers."), "err");
      } finally { if (btn) btn.disabled = false; }
    }

    // -- Official figures (Group N): consented fetch · vintaged store · triangulation.
    // English-only strings here (matching the keyword-explorer / diagnostics Settings
    // sub-features) so i18n stays 100% with zero new keys; the BACKEND enforces the
    // honesty contract (no score, gaps as null, side-by-side never averaged).
    function _statfigFmt(v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString(); }
    async function fetchStatFigure() {
      const src = $("statfig-source").value;
      const series = ($("statfig-series").value || "").trim();
      const country = ($("statfig-country").value || "").trim() || "all";
      const msg = $("statfig-msg"), btn = $("statfig-fetch");
      if (!series) { if (msg) msg.textContent = "Enter an indicator or dataset id first."; return; }
      // The fetch egresses over the configured transport -> the ONE consent popup.
      if (typeof ensureOnline === "function" && !await ensureOnline("Fetch official statistics figures")) return;
      const body = src === "worldbank"
        ? { source: "worldbank", indicator: series, country }
        : { source: "eurostat", dataset: series };
      if (btn) btn.disabled = true;
      if (msg) msg.textContent = "Fetching…";
      try {
        const d = await api("/api/stats/figures/fetch", { method: "POST", body: JSON.stringify(body) });
        if (msg) msg.innerHTML = `<b>${(d.fetched || 0).toLocaleString()}</b> fetched · `
          + `${(d.stored || 0).toLocaleString()} stored · ${(d.duplicate || 0).toLocaleString()} already had this vintage · `
          + `${(d.gaps || 0).toLocaleString()} published gaps`
          + (d.caveat ? `<div class="muted" style="margin-top:5px">${esc(d.caveat)}</div>` : "");
        $("statfig-view-series").value = series;
        loadStatFigures();
      } catch (e) {
        // Honest verdicts: 409 = airplane mode refusal, 502 = transport/endpoint failure.
        if (msg) msg.innerHTML = `<span class="note err">Fetch failed: ${esc(e.message)}</span>`;
      } finally { if (btn) btn.disabled = false; }
    }
    async function loadStatFigures() {
      const box = $("statfig-table"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const qs = series ? "?series_id=" + encodeURIComponent(series) : "";
        const d = await api("/api/stats/figures" + qs);
        const figs = d.figures || [];
        if (!figs.length) { box.innerHTML = `<div class="muted">No stored figures yet — fetch some above.</div>`; return; }
        const rows = figs.map(f => `<tr>
            <td>${esc(f.agency)}</td><td>${esc(f.series_id)}</td><td>${esc(f.ref_area)}</td>
            <td>${esc(f.time_period)}</td><td style="text-align:right">${_statfigFmt(f.value)}</td>
            <td>${esc(f.unit || "")}</td><td>${esc(f.adjustment || "")}</td><td>${esc(f.base_year || "")}</td>
          </tr>`).join("");
        box.innerHTML = `<div class="hint">${(d.shown||figs.length)} of ${(d.count||figs.length).toLocaleString()} shown · latest vintage</div>
          <table><tr><th>Agency</th><th>Series</th><th>Area</th><th>Period</th><th style="text-align:right">Value</th>`
          + `<th>Unit</th><th>SA/NSA</th><th>Base yr</th></tr>${rows}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load figures: ${esc(e.message)}</div>`; }
    }
    async function triangulateStatSeries() {
      const box = $("statfig-tri"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      if (!series) { box.innerHTML = `<div class="muted">Enter a series id above to triangulate.</div>`; return; }
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/stats/triangulate?series_id=" + encodeURIComponent(series));
        const cells = d.cells || [];
        if (!cells.length) { box.innerHTML = `<div class="muted">No producers stored for "${esc(series)}" yet.</div>`; return; }
        const cellHtml = cells.map(c => {
          const cols = c.producers.map(p => `${esc(p.agency)}: <b>${_statfigFmt(p.value)}</b>${p.unit ? " " + esc(p.unit) : ""}`).join(" &nbsp;·&nbsp; ");
          const cmp = c.comparability || {};
          const flag = cmp.comparable
            ? `<span class="pill ok">comparable</span>`
            : `<span class="pill warn">not comparable — differs on ${esc((cmp.differs_on||[]).join(", "))}</span>`;
          return `<tr><td>${esc(c.ref_area)}</td><td>${esc(c.time_period)}</td><td>${c.n_producers}</td><td>${cols}</td><td>${flag}</td></tr>`;
        }).join("");
        box.innerHTML = `<table><tr><th>Area</th><th>Period</th><th>#</th><th>Producers (side by side)</th><th>Comparability</th></tr>${cellHtml}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not triangulate: ${esc(e.message)}</div>`; }
    }

    // -- Read a page from a downloaded dump (T14: local, zero network) ------- //
    async function loadReadableDumps() {
      const sel = $("dumpread-wiki"); if (!sel) return;
      try {
        const d = await api("/api/wiki/dumps/readable");
        const cur = sel.value;
        sel.innerHTML = (d.wikis || []).map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join("")
          || `<option value="">—</option>`;
        if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
      } catch (e) { /* reader box is optional */ }
    }
    async function dumpReadPage() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const wiki = $("dumpread-wiki").value.trim();
      const title = $("dumpread-title").value.trim();
      const out = $("dumpread-out");
      if (!wiki) { out.innerHTML = `<div class="note err">${esc(t("No readable dump yet — download a multistream dump above; its index rides along automatically."))}</div>`; return; }
      if (!title) { out.innerHTML = `<div class="note err">${esc(t("Enter a page title."))}</div>`; return; }
      out.textContent = t("Loading…");
      try {
        const d = await api(`/api/wiki/dumps/page?wiki=${encodeURIComponent(wiki)}&title=${encodeURIComponent(title)}`);
        if (!d.found) {
          let msg;
          if (d.reason === "title-not-in-index") {
            msg = `${t("This title is not in the dump's index.")} <span class="muted">(${d.index_lines_scanned} ${t("index lines scanned")}, ${d.scan_seconds}s)</span>`;
          } else if (d.reason === "no-multistream-dump" || d.reason === "no-index") {
            msg = esc(t("No readable dump for this edition: the multistream file or its index is missing."))
              + (d.legacy_file_present ? " " + esc(t("An older single-stream file exists but cannot be random-accessed — re-download to enable reading.")) : "");
          } else {
            msg = esc(d.reason || "unreadable");
          }
          out.innerHTML = `<div class="note err">${msg}</div>`;
          return;
        }
        const meta = [
          d.match === "case-insensitive" ? t("Found via case-insensitive match.") : "",
          d.rev_timestamp ? `${t("dump revision of")} ${esc(d.rev_timestamp.slice(0,10))}` : "",
          `${d.index_lines_scanned} ${t("index lines scanned")} · ${d.scan_seconds}s`
        ].filter(Boolean).join(" · ");
        out.innerHTML = `<div class="card">
          <h4>${esc(d.title)} <span class="muted" style="font-weight:normal">(${esc(d.wiki)})</span></h4>
          <div class="muted small" title="${esc(d.method || "")}">${meta}</div>
          <div class="muted small">${esc(t("Raw wikitext (unrendered), extracted locally from your downloaded dump — no network call."))}</div>
          <pre style="max-height:420px;overflow:auto;white-space:pre-wrap;margin-top:6px">${esc(d.wikitext)}</pre>
        </div>`;
      } catch (e) { out.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    async function loadWikiPages() {
      try {
        const d = await api("/api/wiki/pages");
        const t = $("wiki-pages");
        t.innerHTML = "<tr><th>Edition</th><th>Title</th><th>Watchlist</th><th>Checked</th><th>Edits</th><th>Flagged</th><th></th></tr>" +
          (d.pages.length ? d.pages.map(p => `<tr>
            <td><strong>${esc(p.wiki)}</strong></td>
            <td>${esc(p.title)}${p.missing
                ? ' <span class="pill err" title="The wiki reports no page with this exact title — check the spelling, or paste the article URL.">page not found</span>'
                : ""}${(p.wiki_categories || []).slice(0, 3).map(c =>
                  ` <span class="pill" style="font-size:10px">${esc(c)}</span>`).join("")}</td>
            <td class="muted">${esc(p.category||"")}</td>
            <td class="muted" style="font-size:12px">${p.last_checked_at?esc(p.last_checked_at.slice(0,16).replace("T"," ")):"never"}</td>
            <td>${p.revisions}</td><td class="muted">${p.flagged}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="trackWikiPage(${p.id})">Track</button>
              <button class="tiny danger" onclick="deleteWikiPage(${p.id}, ${esc(JSON.stringify(p.title))})">Delete</button>
            </td></tr>`).join("")
            : `<tr><td colspan="7" class="muted">No watched pages yet. Add one above.</td></tr>`);
      } catch (e) { toast("Wiki pages: " + e.message, "err"); }
    }

    async function addWikiPage() {
      const body = { wiki: $("wiki-lang").value.trim() || "en", title: $("wiki-title").value.trim(),
                     category: $("wiki-cat").value.trim() || null };
      if (!body.title) { toast("Enter an article title.", "err"); return; }
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Add a watched Wikipedia page (fetches its current revision)"))) return;
      try { await api("/api/wiki/pages", {method:"POST", body: JSON.stringify(body)});
        toast("Page added to watchlist."); $("wiki-title").value=""; loadWikiPages(); loadWiki(); }
      catch (e) { toast("Add failed: " + e.message, "err"); }
    }

    async function deleteWikiPage(id, title) {
      if (!confirm(`Stop watching "${title}"? Its stored revisions are removed.`)) return;
      try { await api("/api/wiki/pages/"+id, {method:"DELETE"}); toast("Removed."); loadWiki(); }
      catch (e) { toast("Delete failed: " + e.message, "err"); }
    }

    const _ores = () => $("wiki-ores").checked ? "true" : "false";

    async function trackWikiPage(id) {
      toast("Fetching revisions… (ethical: UA + maxlag + rate-limited)");
      try {
        const r = await api(`/api/wiki/pages/${id}/track?ores=${_ores()}`, {method:"POST"});
        toast(r.baseline ? "Baseline captured." : `Stored ${r.new} new edit(s), ${r.flagged} flagged.`);
        loadWiki();
      } catch (e) { toast("Track failed: " + e.message, "err"); }
    }

    async function trackWikiNow() {
      $("wiki-progress").textContent = "Tracking watched pages…";
      try {
        const r = await api(`/api/wiki/track-now?ores=${_ores()}`, {method:"POST"});
        $("wiki-progress").textContent = `${r.pages} page(s): ${r.new_revisions} new edit(s), ${r.flagged} flagged.`;
        toast("Tracking complete."); loadWiki();
      } catch (e) { $("wiki-progress").textContent=""; toast("Track now failed: " + e.message, "err"); }
    }

    async function loadWikiChanges() {
      const flagged = $("wiki-flagged-only").checked ? "true" : "false";
      const w = $("wiki-filter-lang").value.trim();
      try {
        const d = await api(`/api/wiki/changes?flagged_only=${flagged}&limit=80` + (w?"&wiki="+encodeURIComponent(w):""));
        const t = $("wiki-changes");
        t.innerHTML = "<tr><th>When</th><th>Edition · Page</th><th>Editor</th><th>Δ bytes</th><th>Reasons</th><th>ORES</th><th></th></tr>" +
          (d.changes.length ? d.changes.map(c => `<tr>
            <td class="muted" style="font-size:12px">${c.timestamp?esc(c.timestamp.slice(0,16).replace("T"," ")):"—"}</td>
            <td><strong>${esc(c.wiki)}</strong> · ${esc(c.title)}</td>
            <td class="muted">${esc(c.editor||"—")}${c.editor_anon?' <span class="pill warn">anon</span>':''}</td>
            <td class="${(c.delta_bytes||0)<0?'':''}" style="color:${(c.delta_bytes||0)<0?'var(--err)':'var(--ok)'}">${c.delta_bytes==null?'—':(c.delta_bytes>0?'+':'')+c.delta_bytes}</td>
            <td>${(c.flag_reasons||[]).map(r=>`<span class="pill warn">${esc(r)}</span>`).join(" ")}</td>
            <td class="muted">${c.ores_damaging!=null?'dmg '+c.ores_damaging.toFixed(2):'—'}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="viewWikiDiff(${c.id})">Diff</button>
              <a class="tiny" href="${esc(c.diff_url)}" target="_blank" rel="noopener">live</a></td></tr>`).join("")
            : `<tr><td colspan="7" class="muted">No changes yet. Add pages and press “Track now”.</td></tr>`);
      } catch (e) { toast("Wiki changes: " + e.message, "err"); }
    }

    async function viewWikiDiff(id) {
      const el = $("wiki-diff");
      el.innerHTML = '<div class="muted">Loading diff…</div>';
      try {
        const d = await api("/api/wiki/revisions/"+id);
        const lines = (d.diff||"(no stored diff)").split("\n").map(l => {
          const cls = l.startsWith("+") ? "ok" : l.startsWith("-") ? "err" : "muted";
          return `<div style="color:var(--${cls});white-space:pre-wrap;font-size:13px">${esc(l)}</div>`;
        }).join("");
        el.innerHTML = `<div class="note" style="max-width:none">
          <div class="muted" style="font-size:12px;margin-bottom:6px">${esc(d.wiki)} · ${esc(d.title)} · rev ${d.revid}
            · <a href="${esc(d.diff_url)}" target="_blank" rel="noopener">view on Wikipedia</a></div>${lines}</div>`;
      } catch (e) { el.innerHTML=""; toast("Diff: " + e.message, "err"); }
    }

    // --- Search-tab time-range control (ooTimeScope reuse) ----------------- //
    // There is no lightweight corpus-span endpoint exposed to the chrome, so the
    // absolute bounds default to [today-5y, today] (a sensible bounded range).
    // The SELECTED window defaults to the WHOLE span (min..max) so a fresh search
    // excludes nothing; searchTimeScopeParams only forwards a bound the user has
    // narrowed off min/max. Built once on first Search-tab open (idempotent).
    let _searchTimeScope = null;
    let _searchTsBounds = {min: null, max: null};
    function buildSearchTimeScope() {
      const box = $("search-timescope");
      if (!box || _searchTimeScope) return;
      const today = new Date();
      const max = today.toISOString().slice(0, 10);
      const lo = new Date(today); lo.setUTCFullYear(today.getUTCFullYear() - 5);
      const min = lo.toISOString().slice(0, 10);
      _searchTsBounds = {min, max};
      // Default window = the full span; re-run the search live on change (matches
      // how the omnibar/other live filters behave — the user sees results update).
      _searchTimeScope = ooTimeScope(box, {
        min, max, from: min, to: max,
        onChange: () => { if (_loaded.has("search")) doSearch(); },
      });
    }

    // The Search-tab date filter is the SAME ooTimeScope control used app-wide
    // (Markets/Insights/corpus window) — periods are first-class. The control's
    // from/to feed the UNCHANGED backend params start_date / end_date (YYYY-MM-DD,
    // accepted by /api/articles + /api/articles/export). A bound is sent ONLY when
    // the user has narrowed it off the absolute min/max — so a plain search never
    // silently excludes articles outside the default window.
    function searchTimeScopeParams(p) {
      if (!_searchTimeScope) return;
      const sel = _searchTimeScope.get();   // {from,to} ISO, or {null,null} on unusable span
      if (sel && sel.from && sel.from > _searchTsBounds.min) p.set("start_date", sel.from);
      if (sel && sel.to && sel.to < _searchTsBounds.max) p.set("end_date", sel.to);
    }
    function searchParams() {
      const p = new URLSearchParams();
      const q = $("q").value.trim(); if (q) p.set("query", q);
      const src = $("f-source").value.trim(); if (src) p.set("source", src);
      const lang = $("f-lang").value.trim(); if (lang) p.set("language", lang);
      searchTimeScopeParams(p);
      return p;
    }
    // The SAME params, built from the analysis window's own Advanced inputs — so the
    // window's exports describe exactly the article set it is analysing (the Search-tab
    // capabilities are absorbed here, toward the one-search-entry goal).
    function anQuery() { return ($("an-adv-query").value || "").trim(); }
    // The EXACT article set behind a clicked card (maintainer-ruled 2026-06-16). When
    // set, the analysis window's corpus IS precisely these articles — every subtab
    // passes article_ids, and the backend's _resolve_corpus prefers them over a
    // search. null = the normal omnibar/Advanced search path.
    let _anIds = null;
    let _anCommodity = null;   // {symbol,name,unit} when seeded by a commodity click (Price subtab)
    let _anLastParams = null;  // last analysis params — for the lazily-rendered Trend subtab
    let _anSubtabs = null;     // ooSubtabs handle for the analysis window (to fall back off Price)
    function anParams() {
      const p = new URLSearchParams();
      if (_anIds && _anIds.length) { p.set("article_ids", _anIds.join(",")); return p; }
      const q = anQuery(); if (q) p.set("query", q);
      const src = $("an-adv-source").value.trim(); if (src) p.set("source", src);
      const lang = $("an-adv-lang").value.trim(); if (lang) p.set("language", lang);
      if ($("an-adv-from").value) p.set("start_date", $("an-adv-from").value);
      if ($("an-adv-to").value) p.set("end_date", $("an-adv-to").value);
      return p;
    }
    // Open the analysis window over an EXACT article set (a set-based card's precise
    // selection — echo / convergence). The corpus is exactly these ids, not a re-run
    // search. The Advanced tab can refine FROM here (which clears the fixed set).
    function openAnalysisForIds(ids, label) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _anIds = Array.isArray(ids) ? ids.slice(0, 5000) : null;
      _anCommodity = null;   // a fixed article set, not a commodity overlay
      $("an-adv-query").value = ""; $("an-adv-source").value = "";
      $("an-adv-lang").value = ""; $("an-adv-from").value = ""; $("an-adv-to").value = "";
      $("an-query").textContent = label ? `“${label}”` : t("(the selected article set)");
      $("an-adv-note").textContent = t("Showing the exact article set behind this Lead.");
      showTab("analyze");
      loadAnalysis(anParams());
    }

    // --- Analysis window (Group F): analytics over the articles a search matched.
    // Keywords (article-set aggregate) + the matches themselves; keyword chips
    // open their own analysis (the keyword corpus window). Counts, never a verdict.
    // Open the analysis window seeded with an explicit query (the omnibar Enter
    // path — ruled: Enter -> a corpus-of-articles window, not the Search tab).
    function openAnalysisFor(query, opts) {
      _anIds = null;   // a fresh query, not a fixed article set
      // A commodity click carries {commodity:{symbol,name,unit}} so the Price
      // subtab can overlay the price curve with this term's corpus coverage.
      _anCommodity = (opts && opts.commodity) || null;
      const q = (query || "").trim();
      $("an-adv-query").value = q;
      $("an-adv-source").value = ""; $("an-adv-lang").value = "";
      $("an-adv-from").value = ""; $("an-adv-to").value = "";
      $("an-query").textContent = q ? `“${q}”` : "(all articles matching your filters)";
      $("an-adv-note").textContent = "";
      showTab("analyze");
      loadAnalysis(anParams());
    }
    function openAnalysis() {
      _anCommodity = null;   // the search-driven path is not a commodity overlay
      const qtxt = $("q").value.trim();
      $("an-query").textContent = qtxt ? `“${qtxt}”` : "(all articles matching your filters)";
      // Prefill the Advanced tab from the current search, so it reflects what is
      // being analyzed and the user can refine from there (toward folding in Search).
      $("an-adv-query").value = qtxt;
      $("an-adv-source").value = $("f-source").value.trim();
      $("an-adv-lang").value = $("f-lang").value.trim();
      // Carry only a NARROWED window over to the analysis Advanced inputs (the
      // ooTimeScope feeds start_date/end_date the same way; a bound left at the
      // absolute min/max means "all", so it stays blank here).
      const _ts = _searchTimeScope && _searchTimeScope.get();
      $("an-adv-from").value = (_ts && _ts.from && _ts.from > _searchTsBounds.min) ? _ts.from : "";
      $("an-adv-to").value = (_ts && _ts.to && _ts.to < _searchTsBounds.max) ? _ts.to : "";
      $("an-adv-note").textContent = "";
      showTab("analyze");
      loadAnalysis(searchParams());
    }
    // Advanced tab: refine the analyzed article set in-place. loadAnalysis re-runs
    // EVERY subtab from the params, so this is the whole wiring.
    function anRunAdvanced() {
      _anIds = null;   // refining via Advanced search replaces any fixed article set
      _anCommodity = null;   // a refined search is no longer the commodity overlay
      const tt = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const p = new URLSearchParams();
      const q = $("an-adv-query").value.trim(); if (q) p.set("query", q);
      const src = $("an-adv-source").value.trim(); if (src) p.set("source", src);
      const lang = $("an-adv-lang").value.trim(); if (lang) p.set("language", lang);
      if ($("an-adv-from").value) p.set("start_date", $("an-adv-from").value);
      if ($("an-adv-to").value) p.set("end_date", $("an-adv-to").value);
      $("an-query").textContent = q ? `“${q}”` : "(all articles matching your filters)";
      $("an-adv-note").textContent = tt("Analysis updated — see the other tabs.");
      loadAnalysis(p);
    }
    function anSelectTab(key) {
      document.querySelectorAll("#tab-analyze .an-panel").forEach(el =>
        el.style.display = (el.id === "an-" + key) ? "" : "none");
      if (key === "trend") renderAnTrend(_anLastParams);   // lazy: only fetch when the Trend tab is shown
      if (key === "related") renderAnRelated(_anLastParams);   // lazy: coordination/related computed on show
    }

    // --- Commodity price × coverage overlay (Markets item, Group G) --------- //
    // Shown ONLY when the analysis window was seeded by a commodity click (the
    // card title ⊞ / Analyse ↗ pass {commodity:{symbol,name,unit}}). The Price
    // subtab overlays the commodity PRICE curve with the corpus COVERAGE (article
    // volume) timeline on a SHARED time axis — "what and when to deduce why and
    // how". The non-causation principle still governs the design; the repeated
    // on-graph "never causation" caveat was removed (maintainer 2026-06-17).
    // Reuses existing endpoints (no new backend).
    function _toggleAnPrice() {
      const on = !!(_anCommodity && _anCommodity.symbol);
      const btn = $("an-price-tab");
      if (btn) btn.style.display = on ? "" : "none";
      if (on) { renderAnPrice(); return; }
      // Hidden now: if the Price tab was the active one, fall back to Keywords.
      const panel = $("an-price");
      if (panel) {
        if (panel.style.display !== "none" && _anSubtabs) _anSubtabs.select("keywords");
        panel.innerHTML = "";
      }
    }
    async function renderAnPrice() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("an-price"); if (!el || !_anCommodity) return;
      const c = _anCommodity;
      el.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      const term = anQuery() || c.name || c.symbol;
      try {
        // Price (the commodity's own series) + corpus coverage (this term's article
        // volume over time). Either may be absent — degrade loudly, never fake.
        const [pd, td] = await Promise.all([
          api(`/api/commodities/${encodeURIComponent(c.symbol)}/prices`).catch(() => null),
          api(`/api/insights/trend?bucket=week&term=${encodeURIComponent(term)}`).catch(() => null),
        ]);
        const prices = (pd && pd.prices) || [];
        const vol = (td && td.resolved) ? (td.points || []) : [];
        const unit = c.unit || (prices[0] ? `${prices[0].currency}/${prices[0].unit}` : "");
        const head = `<div class="hint"><b>${esc(t("Price × coverage"))}</b> — ${esc(c.name || c.symbol)}</div>`;
        const note = vol.length
          ? `<div class="hint muted" style="font-size:11px;margin-top:4px">${esc(t("Articles"))}: ${td.total} · ${vol.length}×</div>`
          : `<div class="muted" style="font-size:12px;margin:6px 0">${esc(t("No corpus coverage to overlay yet."))}</div>`;
        el.innerHTML = head + commodityOverlaySvg(prices, vol, unit) + note;
      } catch (e) { el.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    // A self-contained, deterministic dual-axis SVG (does NOT touch ooChart). The
    // PRICE reads its OWN left axis (line + real sample dots so the true n is
    // honest), the COVERAGE its OWN right axis (bars, 0-based) — each on its own
    // LABELLED scale, so magnitudes are never conflated (no fabricated shared
    // baseline). Shared time X so spikes line up. Empty/sparse degrade honestly.
    function commodityOverlaySvg(prices, vol, priceUnit) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const P = (prices || []).map(p => ({t: Date.parse(p.observed_on), v: +p.price}))
        .filter(p => isFinite(p.t) && isFinite(p.v)).sort((a, b) => a.t - b.t);
      const V = (vol || []).map(p => ({t: Date.parse(p.date), v: +p.count}))
        .filter(p => isFinite(p.t) && isFinite(p.v)).sort((a, b) => a.t - b.t);
      if (!P.length && !V.length) return `<div class="muted">${esc(t9("no data points yet"))}</div>`;
      const W = 660, H = 230, padL = 54, padR = 50, padT = 16, padB = 28;
      const allT = P.concat(V).map(p => p.t);
      const tMin = Math.min(...allT), tMax = Math.max(...allT), tSpan = (tMax - tMin) || 1;
      const X = ms => padL + (W - padL - padR) * (ms - tMin) / tSpan;
      const pv = P.map(p => p.v);
      const pMin = P.length ? Math.min(...pv) : 0, pMax = P.length ? Math.max(...pv) : 1;
      const pSpan = (pMax - pMin) || 1;
      const vMax = V.length ? Math.max(...V.map(p => p.v), 1) : 1;
      const Yp = v => padT + (H - padT - padB) * (1 - (v - pMin) / pSpan);
      const Yv = v => padT + (H - padT - padB) * (1 - v / vMax);
      const baseY = H - padB;
      const fmt = (typeof fmtNum === "function") ? fmtNum : (x => String(x));
      // Coverage bars (RIGHT axis) drawn first so the price line sits on top.
      const slot = (W - padL - padR) / Math.max(V.length, 1);
      const bw = Math.max(2, Math.min(slot * 0.6, 16));
      const bars = V.map(p => {
        const cx = X(p.t), by = Yv(p.v), x0 = Math.max(padL, cx - bw / 2);
        return `<rect x="${x0.toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, baseY - by).toFixed(1)}" fill="var(--muted)" fill-opacity="0.30"></rect>`;
      }).join("");
      // Price line + real sample dots (LEFT axis): dots keep the true n honest.
      const line = P.length >= 2
        ? `<polyline fill="none" stroke="var(--accent)" stroke-width="1.6" points="${P.map(p => `${X(p.t).toFixed(1)},${Yp(p.v).toFixed(1)}`).join(" ")}"></polyline>` : "";
      const dots = P.map(p => `<circle cx="${X(p.t).toFixed(1)}" cy="${Yp(p.v).toFixed(1)}" r="1.5" fill="var(--accent)"></circle>`).join("");
      const leftAxis = P.length ? [pMin, pMin + pSpan / 2, pMax].map(v =>
        `<text x="${(padL - 5).toFixed(1)}" y="${(Yp(v) + 3).toFixed(1)}" text-anchor="end" font-size="8.5" fill="var(--accent)">${fmt(v)}</text>`).join("") : "";
      const rightAxis = V.length ? [0, vMax].map(v =>
        `<text x="${(W - padR + 5).toFixed(1)}" y="${(Yv(v) + 3).toFixed(1)}" text-anchor="start" font-size="8.5" fill="var(--muted)">${fmt(v)}</text>`).join("") : "";
      const dts = [tMin, (tMin + tMax) / 2, tMax].map((ms, i) =>
        `<text x="${X(ms).toFixed(1)}" y="${(H - 6).toFixed(1)}" text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}" font-size="8.5" fill="var(--muted)">${new Date(ms).toISOString().slice(0, 7)}</text>`).join("");
      const aria = `${t9("Price × coverage")}: ${P.length} price, ${V.length} coverage`;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px" role="img" aria-label="${esc(aria)}">`
        + (P.length ? `<text x="${padL}" y="11" font-size="8.5" fill="var(--accent)">${esc(t9("Price"))} ${esc(priceUnit || "")}</text>` : "")
        + (V.length ? `<text x="${W - padR}" y="11" text-anchor="end" font-size="8.5" fill="var(--muted)">${esc(t9("Articles"))}</text>` : "")
        + bars + line + dots + leftAxis + rightAxis + dts + `</svg>`;
    }

    // --- Combined time-aligned TREND overlay (Analysis window; maintainer-ruled
    // 2026-06-17). ONE chart for a keyword + its related keywords/tags (all article
    // COUNTS = a shared unit, so an honest shared axis), with an INDEXED mode (each
    // series rebased to 100 at the window start) that ALSO overlays commodity PRICE
    // series of a DIFFERENT unit WITHOUT conflating magnitudes — plus the precise
    // dual-axis price×coverage panel. The shared axis is TIME. Counts only / no
    // score; the design respects co-occurrence ≠ causation, but the on-graph caveat
    // text was removed (maintainer 2026-06-17). Lazy: rendered on tab-show, cached.
    const _anTrend = { key: null, term: null, counts: [], suggested: [], picked: {}, mode: "counts" };
    function commoditiesForTerm(term, related) {
      // Reverse of the COMMODITY_QUERY seed: suggest a commodity when its family
      // word appears in the analyzed term or its related terms (e.g. a "Middle East"
      // corpus whose associations include "oil" -> WTI/BRENT). Deterministic
      // whole-word match; never fabricates a link.
      const hay = (" " + (term || "") + " " + (related || []).join(" ") + " ").toLowerCase();
      const out = [];
      for (const sym of Object.keys(COMMODITY_QUERY)) {
        const words = COMMODITY_QUERY[sym].toLowerCase().split(/\s+/).filter(w => w.length > 2);
        if (words.some(w => hay.includes(" " + w) || hay.includes(w + " "))) out.push(sym);
      }
      return out.slice(0, 8);
    }
    async function renderAnTrend(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-trend"); if (!host) return;
      const term = (p && p.get && p.get("query")) || anQuery() || "";
      if (_anTrend.key === term && _anTrend.counts.length) { drawAnTrend(); return; }   // cached on this term
      if (!term) { host.innerHTML = `<div class="muted">${esc(t("Open the analysis from a keyword or a search to see its combined trend."))}</div>`; return; }
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anTrend.key = term; _anTrend.term = term; _anTrend.counts = []; _anTrend.suggested = []; _anTrend.picked = {}; _anTrend.mode = "counts";
      try {
        const [main, assoc] = await Promise.all([
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(term)).catch(() => null),
          api("/api/insights/associations?term=" + encodeURIComponent(term) + "&limit=8").catch(() => null),
        ]);
        const series = [];
        if (main && main.resolved && (main.points || []).length)
          series.push({ label: term, unit: t("articles"), color: "var(--accent)", points: main.points.map(pt => ({ t: pt.date, v: pt.count })) });
        // Related keywords are corpora too: overlay each one's own coverage series.
        const rel = ((assoc && assoc.nodes) || []).map(n => n.label || n.id)
          .filter(x => x && x.toLowerCase() !== term.toLowerCase()).slice(0, 4);
        const palette = ["var(--ok)", "var(--warn)", "#6ea8fe", "#c084fc"];
        const relTrends = await Promise.all(rel.map(rt =>
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(rt)).catch(() => null)));
        relTrends.forEach((rd, i) => {
          if (rd && rd.resolved && (rd.points || []).length)
            series.push({ label: rel[i], unit: t("articles"), color: palette[i % palette.length], points: rd.points.map(pt => ({ t: pt.date, v: pt.count })) });
        });
        _anTrend.counts = series;
        _anTrend.suggested = commoditiesForTerm(term, rel);
        if (_anCommodity && _anCommodity.symbol && _anTrend.suggested.indexOf(_anCommodity.symbol) < 0)
          _anTrend.suggested.unshift(_anCommodity.symbol);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      drawAnTrend();
    }
    function anTrendSetMode(m) { _anTrend.mode = m; drawAnTrend(); }
    async function anTrendPick(sym) {
      if (!sym) return;
      if (_anTrend.picked[sym]) { delete _anTrend.picked[sym]; drawAnTrend(); return; }
      try {
        const pd = await api("/api/commodities/" + encodeURIComponent(sym) + "/prices").catch(() => null);
        const prices = (pd && pd.prices) || [];
        _anTrend.picked[sym] = { prices, unit: prices[0] ? (prices[0].currency + "/" + prices[0].unit) : "" };
      } catch (e) { _anTrend.picked[sym] = { prices: [], unit: "" }; }
      if (_anTrend.mode === "counts") _anTrend.mode = "indexed";   // a price cannot share the counts axis
      drawAnTrend();
    }
    function drawAnTrend() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-trend"); if (!host) return;
      const counts = _anTrend.counts || [];
      if (!counts.length) { host.innerHTML = `<div class="muted">${esc(t("No coverage to chart for this term yet."))}</div>`; return; }
      const picks = Object.keys(_anTrend.picked);
      const indexed = _anTrend.mode === "indexed";
      // Counts always; commodity PRICE series only in indexed mode (different unit).
      const list = counts.slice();
      if (indexed) for (const sym of picks) {
        const c = _anTrend.picked[sym];
        const pts = (c.prices || []).map(p => ({ t: p.observed_on, v: +p.price })).filter(p => isFinite(p.v));
        if (pts.length) list.push({ label: sym, unit: c.unit || t("price"), color: "var(--err)", points: pts });
      }
      const seg = (m, lbl) => `<button class="ghost tiny${_anTrend.mode === m ? " on" : ""}" onclick="anTrendSetMode('${m}')">${esc(lbl)}</button>`;
      const modeRow = `<div class="row" style="gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:6px">`
        + `<span class="muted" style="font-size:11px">${esc(t("View"))}:</span>` + seg("counts", t("Counts")) + seg("indexed", t("Indexed")) + `</div>`;
      const chip = (sym) => `<button class="chip${_anTrend.picked[sym] ? " on" : ""}" onclick="anTrendPick('${sym}')"`
        + `${_anTrend.picked[sym] ? ' style="border-color:var(--accent)"' : ''}>${esc(sym)}</button>`;
      const suggRow = `<div class="row" style="gap:5px;align-items:center;flex-wrap:wrap;margin-bottom:6px">`
        + `<span class="muted" style="font-size:11px">${esc(t("Overlay a commodity"))}:</span>`
        + _anTrend.suggested.map(chip).join(" ")
        + ` <select onchange="anTrendPick(this.value);this.value=''" style="width:auto;font-size:12px">`
        + `<option value="">${esc(t("more…"))}</option>`
        + Object.keys(COMMODITY_QUERY).map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("")
        + `</select></div>`;
      const caveat = indexed
        ? t("Indexed to 100 at the window start — relative movement, not absolute levels. Hover shows the real value.")
        : t("Article counts on a shared time axis.");
      host.innerHTML = modeRow + suggRow + `<div id="an-trend-chart"></div>`
        + `<p class="card-caveat" style="margin-top:6px">${esc(caveat)}</p>`
        + (_anTrend.mode === "counts" && picks.length ? `<p class="hint muted" style="margin:4px 0 0">${esc(t("Switch to Indexed to overlay commodity prices honestly (different units)."))}</p>` : "")
        + `<div id="an-trend-dual" style="margin-top:10px"></div>`;
      ooChart($("an-trend-chart"), list, { height: 240, indexed: indexed, zeroBase: !indexed });
      // Precise dual-axis (2 series): the first picked commodity's price × this
      // term's coverage, each on its OWN real-unit scale (the shipped overlay).
      const dual = $("an-trend-dual");
      if (picks.length && counts.length) {
        const c = _anTrend.picked[picks[0]];
        const cov = (counts[0].points || []).map(p => ({ date: p.t, count: p.v }));
        dual.innerHTML = `<div class="hint"><b>${esc(t("Dual-axis"))}</b> — ${esc(picks[0])} · ${esc(t("Price × coverage"))} `
          + `<span class="muted">${esc(t("each on its own real-unit scale"))}</span></div>` + commodityOverlaySvg(c.prices, cov, c.unit);
      } else dual.innerHTML = "";
    }

    // --- Related & coordination (Analysis window; maintainer-ruled 2026-06-17):
    // make the coordination "scan" AMBIENT in analysis (not a manual tab) AND let the
    // user BRANCH related articles into a NEW corpus for associated research. Computed
    // automatically when the Related subtab opens (lazy, cached per corpus). Surfaces
    // near-identical clusters as "N near-identical copies across M sources = one voice"
    // — independence by DISTINCT SOURCES, structural only, NO score; the non-collusion +
    // absence-is-not-absence caveat is visible. Each cluster branches via
    // openAnalysisForIds (the exact-set spawn) = a fresh corpus = associated research.
    const _anRelated = { key: null };
    let _anRelatedClusters = [];
    let _anRelatedLinks = [];
    async function renderAnRelated(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-related"); if (!host) return;
      const key = (p && p.toString && p.toString()) || "";
      if (_anRelated.key === key && host.dataset.done === "1") return;   // cached on this corpus
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anRelated.key = key; host.dataset.done = "";
      const qs = p ? p.toString() : "";
      try {
        // Two independence-honest "related" lenses over the corpus: near-identical
        // copies (text) AND shared outbound origins (citation). Both reuse existing
        // endpoints; each cluster/origin BRANCHES into a fresh corpus.
        const [cd, ld] = await Promise.all([
          api("/api/insights/corpus-coordination?" + qs).catch(() => null),
          api("/api/links/corpus?" + qs).catch(() => null),
        ]);
        _anRelatedClusters = (cd && cd.clusters) || [];
        _anRelatedLinks = (ld && ld.items) || [];
        let html = `<div class="row" style="gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">`
          + `<button class="secondary tiny" onclick="branchSelectedRelated()">${esc(t("Branch selected into a new corpus →"))}</button>`
          + ` <span id="an-rel-selcount" class="muted" style="font-size:11px"></span></div>`
          + `<div class="hint"><b>${_anRelatedClusters.length}</b> ${esc(t("Near-identical clusters"))}`
          + ` <span class="muted">· ${esc((cd && cd.method) || "")}</span></div>`;
        if (!_anRelatedClusters.length) {
          html += `<div class="muted" style="margin:6px 0 2px">`
            + `${esc(t("No near-identical clusters detected in this corpus — not proof there is no coordination, only that none was found at this threshold."))}</div>`;
        } else {
          html += _anRelatedClusters.map((c, i) => {
            const voice = c.single_source
              ? t("{n} near-identical copies from one source = one voice").replace("{n}", c.size)
              : t("{n} near-identical copies across {m} sources = effectively one voice").replace("{n}", c.size).replace("{m}", c.distinct_sources);
            const ex = (c.members || []).slice(0, 6).map((m) =>
              `<li><a href="/api/articles/${m.id}/view" target="_blank" rel="noopener">${esc(m.title || t("(untitled)"))}</a>`
              + ` <span class="muted">· ${esc(m.source || "")}</span></li>`).join("");
            const more = c.size > 6 ? `<li class="muted">+${c.size - 6} ${esc(t("more"))}</li>` : "";
            return `<div class="card" style="padding:10px;margin-top:8px">`
              + `<div class="row" style="justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">`
              + `<span style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="an-rel-pick" data-kind="c" data-idx="${i}" onchange="anRelUpdateSel()" aria-label="${esc(t("Select for branching"))}"><b>${esc(voice)}</b></span>`
              + `<button class="secondary tiny" onclick="branchFromRelated(${i})" title="${esc(t("Open these articles as a new analysis corpus"))}">${esc(t("Branch into a new corpus →"))}</button></div>`
              + `<details style="margin-top:6px"><summary class="muted" style="cursor:pointer">${esc(t("Show all"))}</summary>`
              + `<ul style="margin:6px 0 0">${ex}${more}</ul></details></div>`;
          }).join("") + `<p class="card-caveat" style="margin-top:8px">${esc((cd && cd.caveat) || "")}</p>`;
        }
        // --- Shared origins: articles citing the SAME outbound page (one origin,
        // not independent confirmation — the anti-false-triangulation lens). ---
        html += `<div class="hint" style="margin-top:16px"><b>${_anRelatedLinks.length}</b> ${esc(t("Shared origins"))}`
          + ` <span class="muted">· ${esc(t("articles in this corpus citing the same outbound page"))}</span></div>`;
        if (!_anRelatedLinks.length) {
          html += `<div class="muted" style="margin:6px 0 2px">${esc(t("No outbound page is cited by 2+ articles in this corpus yet."))}</div>`;
        } else {
          html += _anRelatedLinks.map((it, i) => {
            const label = it.domain || it.link_text || it.normalized_url;
            return `<div class="card" style="padding:10px;margin-top:8px">`
              + `<div class="row" style="justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">`
              + `<span style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="an-rel-pick" data-kind="o" data-idx="${i}" onchange="anRelUpdateSel()" aria-label="${esc(t("Select for branching"))}">`
              + `<span>${extLink(it.sample_url || it.normalized_url, esc(label), "", "")} `
              + `<span class="muted">· ${it.citations}× ${esc(t("cited"))}</span></span></span>`
              + `<button class="secondary tiny" onclick="branchFromOrigin(${i})" title="${esc(t("Open every article citing this origin as a new corpus"))}">${esc(t("Branch into a new corpus →"))}</button></div></div>`;
          }).join("")
            + `<p class="card-caveat" style="margin-top:8px">${esc((ld && ld.caveat) || t("Several articles citing the same page are not independent confirmation — one origin, several echoes."))}</p>`;
        }
        host.innerHTML = html;
        host.dataset.done = "1";
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    function branchFromRelated(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = _anRelatedClusters[i];
      if (!c || !c.article_ids || !c.article_ids.length) return;
      openAnalysisForIds(c.article_ids, t("Near-identical cluster") + " · " + c.size);
    }
    // Branch every article that cites one shared outbound origin into a fresh corpus
    // (the "sources' sources" trail). Fetches the citing-article ids on click.
    async function branchFromOrigin(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const it = _anRelatedLinks[i]; if (!it) return;
      try {
        const d = await api("/api/links/articles-by-link?url=" + encodeURIComponent(it.normalized_url || it.sample_url));
        const ids = (d.articles || []).map((a) => a.id);
        if (!ids.length) { if (typeof toast === "function") toast(t("No articles cite this origin.")); return; }
        openAnalysisForIds(ids, (it.domain || t("Shared origin")) + " · " + ids.length);
      } catch (e) { if (typeof toast === "function") toast(e.message); }
    }
    // Multi-select branch: union the SELECTED clusters' + origins' article sets into
    // ONE fresh corpus (associated research over a hand-picked combination).
    function anRelUpdateSel() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const n = document.querySelectorAll("#an-related .an-rel-pick:checked").length;
      const el = $("an-rel-selcount");
      if (el) el.textContent = n ? t("{n} selected").replace("{n}", n) : "";
    }
    async function branchSelectedRelated() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const picks = Array.from(document.querySelectorAll("#an-related .an-rel-pick:checked"));
      if (!picks.length) { if (typeof toast === "function") toast(t("Select one or more rows to branch.")); return; }
      const ids = new Set();
      const originIdx = [];
      for (const cb of picks) {
        if (cb.dataset.kind === "c") {
          const c = _anRelatedClusters[+cb.dataset.idx];
          (c && c.article_ids || []).forEach((id) => ids.add(id));
        } else { originIdx.push(+cb.dataset.idx); }
      }
      try {
        const lists = await Promise.all(originIdx.map((i) => {
          const it = _anRelatedLinks[i];
          return it ? api("/api/links/articles-by-link?url=" + encodeURIComponent(it.normalized_url || it.sample_url)).catch(() => null) : null;
        }));
        for (const d of lists) (d && d.articles || []).forEach((a) => ids.add(a.id));
      } catch (e) { /* origins are best-effort; cluster ids still branch */ }
      const arr = Array.from(ids);
      if (!arr.length) { if (typeof toast === "function") toast(t("No articles in the selected rows.")); return; }
      openAnalysisForIds(arr, t("Selected related") + " · " + arr.length);
    }

    // Self-contained radial mind-map for the analysis window. Distinct from the
    // Insights renderGraph() (which owns _mm* state + a force/zoom canvas): this
    // draws ONE static, deterministic SVG into the container it is handed — no
    // shared globals, no animation loop. Maintainer mind-map rules: centre →
    // arms → ALWAYS outward; first-ring neighbours on a circle; edges centre→
    // neighbour only (radial, no cross-tangle); never interpolate fake structure.
    // Consumes the /api/insights/graph shape: nodes {id,label,size,center}, edges
    // {a,b,weight}, plus level/method/caveat. Font size scales with node size.
    // In-map controls (mind-map rules): a Cloud SECOND view, a text-size control and
    // ⛶ Enlarge. State is kept so the controls re-render from the same graph.
    const _anMM = { graph: null, cloud: false, scale: 100, big: false };
    function anMMset(patch) { Object.assign(_anMM, patch); if (_anMM.graph) renderAnMindmap(_anMM.graph); }
    function renderAnMindmap(graph, hostEl) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = hostEl || $("an-mindmap");
      if (!host) return;
      if (graph) _anMM.graph = graph;
      const g = _anMM.graph || {};
      const all = (g.nodes || []);
      const controls = `<div class="row" style="gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap">`
        + `<button class="ghost tiny${_anMM.cloud ? "" : " on"}" onclick="anMMset({cloud:false})">Map</button>`
        + `<button class="ghost tiny${_anMM.cloud ? " on" : ""}" onclick="anMMset({cloud:true})">Cloud</button>`
        + `<label class="hint" style="display:flex;align-items:center;gap:4px">${esc(t("Text size"))}`
        + ` <input type="range" min="60" max="180" value="${_anMM.scale}" oninput="anMMset({scale:+this.value})" style="width:90px"></label>`
        + `<button class="ghost tiny" onclick="anMMset({big:!_anMM.big})" title="${esc(t("Enlarge the mindmap"))}">⛶</button></div>`;
      if (all.length < 2) {
        host.innerHTML = controls + `<div class="muted">${esc(t("No strong associations yet."))}</div>`;
        return;
      }
      const center = all.find((n) => n.center) || all[0];
      const neighbours = all.filter((n) => n.id !== center.id)
        .sort((a, b) => (b.size || 1) - (a.size || 1)).slice(0, 24);
      const scale = (_anMM.scale || 100) / 100, big = _anMM.big;
      const W = big ? 1100 : 680, H = big ? 720 : 460, cx = W / 2, cy = H / 2;
      const R = Math.min(W, H) * 0.36;
      const maxSize = Math.max(center.size || 1, ...neighbours.map((n) => n.size || 1), 1);
      const fsOf = (n) => ((n.id === center.id ? 17 : 9 + 9 * Math.sqrt((n.size || 1) / maxSize)) * scale);
      let edges = "";
      if (_anMM.cloud) {
        // Word cloud SECOND view: golden-angle spiral by size, no edges.
        [center, ...neighbours].sort((a, b) => (b.size || 1) - (a.size || 1)).forEach((n, i) => {
          const ang = i * 2.39996, r = 15 * Math.sqrt(i);
          n._x = cx + r * Math.cos(ang) * 1.5; n._y = cy + r * Math.sin(ang);
        });
      } else {
        // Radial tree: centre → arms → ALWAYS outward (deterministic, no cross-tangle).
        center._x = cx; center._y = cy;
        neighbours.forEach((n, i) => {
          const ang = (i / neighbours.length) * 2 * Math.PI - Math.PI / 2;
          n._x = cx + R * Math.cos(ang); n._y = cy + R * Math.sin(ang);
        });
        edges = neighbours.map((n) =>
          `<line stroke="var(--border)" stroke-width="1.4" x1="${cx}" y1="${cy}"`
          + ` x2="${n._x.toFixed(1)}" y2="${n._y.toFixed(1)}"></line>`).join("");
      }
      const drawNode = (n) => {
        const col = n.id === center.id ? "var(--ok)" : "var(--accent)";
        const fam = (n.members || []).length > 1;
        const title = fam ? `<title>${esc((n.members || []).join(", "))}</title>` : "";
        return `<g transform="translate(${n._x.toFixed(1)},${n._y.toFixed(1)})">${title}`
          + `<text text-anchor="middle" dominant-baseline="central" font-size="${fsOf(n).toFixed(1)}"`
          + ` font-weight="${n.id === center.id ? 700 : 500}" fill="${col}">${esc(n.label || n.id)}</text></g>`;
      };
      const nodesSvg = drawNode(center) + neighbours.map(drawNode).join("");
      const desc = _anMM.cloud
        ? t("Word cloud: keywords sized by shared-article volume; no links.")
        : t("Radial map: the seed keyword at the centre, its strongest relatives outward.");
      host.innerHTML = controls
        + `<svg viewBox="0 0 ${W} ${H}" width="100%" style="background:var(--panel2);`
        + `border:1px solid var(--border);border-radius:8px">${edges}${nodesSvg}</svg>`
        + `<div class="hint muted" style="margin-top:6px">${esc(desc)} `
        + `<b>${esc(t("Font size = shared-article volume."))}</b> ${esc(g.method || "")} ${esc(g.caveat || "")}</div>`;
    }
    // Inline near-dup annotation (maintainer-ruled: "1 voice" inline in lists, PR 3):
    // badge article-row links that are near-identical COPIES (= effectively one voice,
    // not independent corroboration) so echo is never mistaken for confirmation.
    // NON-BLOCKING (the list renders first) + reuses corpus-coordination; reuses the
    // Related subtab's cache when present so it adds no extra fetch in the common path.
    // Best-effort: any failure leaves the list exactly as rendered. Reusable across any
    // host whose article links are /api/articles/{id}/view.
    async function annotateArticleDups(params, host) {
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const key = params ? params.toString() : "";
      try {
        let clusters;
        if (_anRelated && _anRelated.key === key && _anRelatedClusters && _anRelatedClusters.length) {
          clusters = _anRelatedClusters;            // reuse the Related cache (no extra fetch)
        } else {
          const d = await api("/api/insights/corpus-coordination?" + key).catch(() => null);
          clusters = (d && d.clusters) || [];
        }
        if (!clusters.length) return;
        const sizeById = {};
        for (const c of clusters) for (const id of (c.article_ids || [])) sizeById[id] = c.size;
        let flagged = 0;
        host.querySelectorAll("a[href]").forEach((a) => {
          const m = (a.getAttribute("href") || "").match(/\/api\/articles\/(\d+)\/view/);
          if (!m || a.dataset.dupBadged) return;
          const sz = sizeById[+m[1]];
          if (!sz) return;
          a.dataset.dupBadged = "1";
          const b = document.createElement("span");
          b.className = "pill"; b.style.marginInlineStart = "6px"; b.style.cursor = "default";
          b.textContent = "≈" + sz;
          b.title = t("One of {n} near-identical copies = effectively one voice. Open Related to inspect the cluster.").replace("{n}", sz);
          a.after(b);
          flagged++;
        });
        if (flagged) {
          const note = document.createElement("div");
          note.className = "card-caveat"; note.style.marginTop = "6px";
          note.textContent = t("{n} of these are near-identical copies — fewer independent voices than the count suggests (see Related).").replace("{n}", flagged);
          host.appendChild(note);
        }
      } catch (e) { /* annotation is best-effort, never breaks the list */ }
    }
    async function loadAnalysis(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const kw = $("an-keywords"), arts = $("an-articles");
      kw.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      arts.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anLastParams = p; _anTrend.key = null; _anRelated.key = null;   // a new analysis run -> the lazy subtabs refetch on next show
      if ($("an-trend") && $("an-trend").style.display !== "none") setTimeout(() => renderAnTrend(p), 0);
      if ($("an-related") && $("an-related").style.display !== "none") setTimeout(() => renderAnRelated(p), 0);
      _toggleAnPrice();   // commodity overlay: show + render the Price subtab, or hide it
      try {
        const d = await api("/api/insights/corpus-keywords?" + p.toString());
        if (!d.terms || !d.terms.length) {
          kw.innerHTML = `<div class="muted">${esc(t("No keywords indexed across the matched articles yet."))}</div>`;
        } else {
          const chips = d.terms.map((term) =>
            `<button class="chip" onclick="openCorpus(${esc(JSON.stringify(term.term))})"`
            + ` title="${esc(t("Open this keyword's own analysis window"))}">${esc(term.term)}`
            + ` <span class="muted">${term.articles}</span></button>`).join(" ");
          // Audit-07 B1 disclosure: our extractor splits on spaces/punctuation and does
          // NOT segment CJK, so CJK keywords are unreliable. Surface it exactly when CJK
          // terms are present (visible by default + the long form in the hover bubble).
          const cjk = d.terms.some((tm) => /[぀-ヿ㐀-䶿一-鿿가-힯]/.test(tm.term));
          const cjkNote = cjk ? ` · <span class="note err" title="${esc(t("Keyword extraction splits on spaces and punctuation; it does NOT segment Chinese, Japanese or Korean, so the CJK keyword aggregates shown here are unreliable."))}">${esc(t("CJK not segmented — unreliable"))}</span>` : "";
          kw.innerHTML = `<div class="hint"><b>${d.terms.length}</b> ${esc(t("Keywords"))}`
            + ` · <span class="muted">${esc(d.caveat || "")}</span>${cjkNote}</div>`
            + `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">${chips}</div>`;
        }
      } catch (e) { kw.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Mindmap: a deterministic radial keyword-association graph seeded on the
      // TOP keyword of the matched set (KEYWORDS ARE CORPORA). Self-contained
      // renderer — never touches the Insights mind-map state. Window params pass
      // through (the /graph endpoint accepts start/end/days, like _mmWindowQS).
      const mm = $("an-mindmap");
      mm.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const dk = await api("/api/insights/corpus-keywords?" + p.toString());
        const top = (dk.terms && dk.terms.length) ? dk.terms[0].term : null;
        if (!top) {
          mm.innerHTML = `<div class="muted">${esc(t("No strong associations yet."))}</div>`;
        } else {
          const gp = new URLSearchParams();
          gp.set("level", "keyword"); gp.set("term", top); gp.set("hops", "2");
          for (const k of ["days", "start", "end"]) { const v = p.get(k); if (v) gp.set(k, v); }
          const g = await api("/api/insights/graph?" + gp.toString());
          renderAnMindmap(g, mm);
        }
      } catch (e) { mm.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      try {
        const p2 = new URLSearchParams(p); p2.set("limit", "100");
        const d = await api("/api/articles?" + p2.toString());
        const rows = (d.results || []).map((a) =>
          `<tr><td><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener">`
          + `${esc(a.title) || '<span class="muted">(untitled)</span>'}</a></td>`
          + `<td>${esc(a.source || "")}</td><td class="muted">${esc((a.published_at || "").slice(0, 10))}</td>`
          + `<td>${a.url ? extLink(a.url, "source ↗", "muted") : ""}</td></tr>`).join("");
        arts.innerHTML = `<div class="hint">${(d.total || 0).toLocaleString()} ${esc(t("Articles"))}</div>`
          + `<table style="margin-top:6px"><tr><th>${esc(t("Title"))}</th><th>${esc(t("Source"))}</th>`
          + `<th>${esc(t("Published"))}</th><th></th></tr>${rows}</table>`;
        annotateArticleDups(p, arts);   // inline "1 voice" near-dup badges (non-blocking, PR 3)
      } catch (e) { arts.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // When/Where/Who deduced across the matched articles (counts, never confirmed).
      try {
        const d = await api("/api/insights/corpus-www?" + p.toString());
        const li = (arr, fmt) => (arr && arr.length) ? arr.map(fmt).join("") : `<li class="muted">—</li>`;
        const who = li(d.who && d.who.entities, (e) =>
          `<li>${esc(e.name)} <span class="muted">· ${esc(e.class || "")} · ${e.articles}</span></li>`);
        const where = li(d.where && d.where.places, (pl) =>
          `<li>${esc(pl.name)}${pl.country ? ` <span class="muted">(${esc(String(pl.country).toUpperCase())})</span>` : ""}`
          + ` <span class="muted">· ${pl.articles}</span></li>`);
        $("an-www").innerHTML = `<div class="hint muted">${esc(d.caveat || "")}</div>`
          + `<div style="display:flex;gap:28px;flex-wrap:wrap;margin-top:8px">`
          + `<div style="min-width:200px"><div class="vsect">${esc(t("Who"))}</div><ul style="margin:4px 0">${who}</ul></div>`
          + `<div style="min-width:200px"><div class="vsect">${esc(t("Where"))}</div><ul style="margin:4px 0">${where}</ul></div></div>`;
      } catch (e) { $("an-www").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Links: outbound URLs SHARED by 2+ of the matched articles (shared-origin
      // structure; convergence is corroboration only when paths are independent).
      try {
        const d = await api("/api/links/corpus?" + p.toString());
        const rows = (d.items || []).map((it) =>
          `<tr><td>${extLink(it.sample_url || it.normalized_url, esc(it.domain || it.link_text || it.normalized_url), "", "")}</td>`
          + `<td style="text-align:right;font-variant-numeric:tabular-nums">${it.citations}</td></tr>`).join("");
        $("an-links").innerHTML = `<div class="hint muted">${esc(d.caveat || "")}</div>`
          + (rows
            ? `<table class="data" style="margin-top:8px"><thead><tr><th>${esc(t("Link"))}</th>`
              + `<th style="text-align:right">${esc(t("Cited by"))}</th></tr></thead><tbody>${rows}</tbody></table>`
            : `<div class="muted" style="margin-top:8px">${esc(t("No links shared by 2+ matched articles."))}</div>`);
      } catch (e) { $("an-links").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Sentiment: distribution of the STORED per-article VADER tone over the set,
      // with the English-lexicon limitation disclosed (non-English scores unreliable).
      try {
        const d = await api("/api/insights/corpus-sentiment?" + p.toString());
        const cav = `<div class="hint muted">${esc(d.caveat || "")}</div>`;
        if (!d.n_scored) {
          $("an-sentiment").innerHTML = cav
            + `<div class="muted" style="margin-top:8px">${esc(t("No tone scores in this set."))}</div>`;
        } else {
          const lab = d.labels || {};
          const LK = { positive: "Positive", neutral: "Neutral", negative: "Negative" };
          const keys = ["positive", "neutral", "negative"].filter((k) => k in lab)
            .concat(Object.keys(lab).filter((k) => !(k in LK)));
          const rows = keys.map((k) => {
            const pct = Math.round((100 * lab[k]) / d.n_scored);
            return `<div style="display:flex;justify-content:space-between;max-width:320px">`
              + `<span>${esc(LK[k] ? t(LK[k]) : k)}</span><span class="muted">${lab[k]} · ${pct}%</span></div>`;
          }).join("");
          const engPct = Math.round((100 * d.english_scored) / d.n_scored);
          $("an-sentiment").innerHTML = cav + `<div style="margin-top:8px">${rows}</div>`
            + `<div class="muted" style="margin-top:8px">${esc(t("Mean tone"))}: ${d.mean_score}`
            + ` · n=${d.n_scored}/${d.n_articles} · ${esc(t("English-scored (reliable)"))}: ${d.english_scored} (${engPct}%)</div>`;
        }
      } catch (e) { $("an-sentiment").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Sources: how each source covers the matched set -- volume, mean tone, span.
      // Coverage, never credibility; no ranking (ordered by volume only).
      try {
        const d = await api("/api/insights/corpus-sources?" + p.toString());
        const rows = (d.sources || []).map((s) => {
          const span = (s.first && s.last) ? `${String(s.first).slice(0, 10)} – ${String(s.last).slice(0, 10)}` : "—";
          const tone = (s.mean_tone === null || s.mean_tone === undefined) ? "—" : s.mean_tone;
          return `<tr><td>${esc(s.name || s.domain || "")}</td>`
            + `<td style="text-align:right;font-variant-numeric:tabular-nums">${s.articles}</td>`
            + `<td style="text-align:right;font-variant-numeric:tabular-nums">${tone}</td>`
            + `<td class="muted">${esc(span)}</td></tr>`;
        }).join("");
        $("an-sources").innerHTML = `<div class="hint muted">${esc(d.caveat || "")}</div>`
          + (rows
            ? `<table class="data" style="margin-top:8px"><thead><tr><th>${esc(t("Source"))}</th>`
              + `<th style="text-align:right">${esc(t("Articles"))}</th>`
              + `<th style="text-align:right">${esc(t("Mean tone"))}</th><th>${esc(t("Span"))}</th></tr></thead>`
              + `<tbody>${rows}</tbody></table>`
            : `<div class="muted" style="margin-top:8px">${esc(t("No sources in this set."))}</div>`);
      } catch (e) { $("an-sources").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    async function doSearch() {
      const p = searchParams(); p.set("limit", String(DEFAULT_LIMIT));
      try {
        const data = await api("/api/articles?" + p.toString());
        $("search-meta").textContent = `${data.total} result(s)` + (data.total > data.results.length ?
          ` (showing ${data.results.length})` : "");
        const t = $("results");
        t.innerHTML = "<tr><th>Title</th><th>Source</th><th>Published</th><th>Lang</th><th></th></tr>" +
          (data.results.length ? data.results.map(a =>
            `<tr><td><div>${esc(a.title) || '<span class="muted">(untitled)</span>'}</div>
                 <div class="muted" style="font-size:12px">${esc((a.content||"").slice(0,160))}…</div></td>
             <td>${esc(a.source)}</td><td class="muted">${esc((a.published_at||"").slice(0,10))}</td>
             <td>${esc(a.language||"")}</td>
             <td><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="offline stored copy">open</a>
                 ${a.url ? `· ${extLink(a.url, "source ↗", "muted")}` : ""}
                 <button class="secondary tiny" style="margin-top:4px"
                   onclick="summarize(${a.id}, this)">Summarize</button>
                 <button class="secondary tiny" style="margin-top:4px"
                   onclick="translateArticle(${a.id}, this)">Translate</button>
                 <div class="summary muted" style="font-size:12px;margin-top:4px"></div></td></tr>`
          ).join("") : `<tr><td colspan="5" class="muted">No matches.</td></tr>`);
        annotateArticleDups(p, t);   // inline "1 voice" near-dup badges (non-blocking, reuses the helper)
      } catch (e) { toast("Search failed: " + e.message, "err"); }
    }

    function exportResults(fmt, p) {
      const params = p || searchParams(); params.set("format", fmt);
      window.open("/api/articles/export?" + params.toString(), "_blank");
    }

    async function synthesizeResults(btn, qArg, mountId) {
      // RM-12: one bounded synthesis call across the current results (max 20).
      // qArg/mountId let the analysis window reuse this with its OWN query + a panel.
      const q = (qArg != null ? qArg : $("q").value.trim());
      if (!q) { toast("Run a search first.", "err"); return; }
      btn.disabled = true; btn.textContent = "Synthesizing…";
      try {
        const r = await api("/api/llm/synthesize",
          {method: "POST", body: JSON.stringify({query: q, output_language: _uiLangName()})});
        let box = $(mountId || "synth-result");
        if (!box) {
          box = document.createElement("div");
          box.id = "synth-result"; box.className = "card";
          $("results").parentNode.insertBefore(box, $("results"));
        }
        box.className = "card"; box.style.display = "";
        box.innerHTML = `<span class="chip">synthesis · ${esc(r.model)} · ` +
          `${r.member_count} articles${r.truncated ? " (top 20 of more)" : ""}</span>` +
          `<p style="white-space:pre-wrap">${esc(r.result)}</p>` +
          `<div class="hint">${esc(r.caveat)} Members: ${r.member_ids.map(i =>
            `<a href="/api/articles/${i}/view" target="_blank" rel="noopener">#${i}</a>`).join(" ")}</div>`;
      } catch (e) { toast("Synthesis failed: " + e.message, "err"); }
      finally { btn.disabled = false; btn.textContent = "Synthesize results"; }
    }

    // --- Bulk summarize / translate over the matched set (local model) --------- //
    // Unlike Synthesize (ONE combined output), this runs the local model over EACH
    // matched article and stores a per-article result — kept forever, never replacing
    // a prior one (the reader shows the latest + folds the rest). Honest streaming
    // progress (invariant #20). Ollama is loopback (no egress), but airplane mode
    // still refuses it — surfaced loudly. These rows are NEVER keyword-indexed.
    let _bulkAbort = null;
    // The current UI language as an ENGLISH name the model reliably understands
    // ("French", not "Français") — the v2 language pin: summaries/synthesis come back
    // in the user's language. Translate carries its own explicit target instead.
    const _LANG_EN = {en:"English",fr:"French",de:"German",es:"Spanish",pt:"Portuguese",
      ru:"Russian",ar:"Arabic",zh:"Chinese",ja:"Japanese",hi:"Hindi",bn:"Bengali",id:"Indonesian"};
    function _uiLangName() {
      const code = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
      return _LANG_EN[code] || "English";
    }
    function _bulkParams(ctx) { return ctx === "an" ? anParams() : searchParams(); }
    function bulkLlm(op, ctx) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search");
      if (!mount) return;
      const p = _bulkParams(ctx);
      const hasSel = p.get("article_ids") || p.get("query") || p.get("source")
        || p.get("language") || p.get("start_date") || p.get("end_date");
      if (!hasSel) { toast(t("Run a search first."), "err"); return; }
      const isTr = op === "translate";
      const heading = isTr ? t("Translate all matched articles") : t("Summarize all matched articles");
      const tgt = isTr
        ? `<label class="muted" style="margin-inline-end:4px" for="bulk-tgt-${ctx}">${esc(t("Into"))}</label>`
          + `<input id="bulk-tgt-${ctx}" value="English" style="max-width:150px">`
        : "";
      mount.style.display = "";
      mount.innerHTML = `<div class="card">
        <div style="font-weight:600;margin-bottom:4px">${esc(heading)}</div>
        <div class="hint" style="margin-bottom:8px">${esc(t("Runs a local model over each article — this can take a while. Each result is stored with its model and date; nothing leaves your machine, and keyword analysis is never affected."))}</div>
        <div class="row" style="gap:12px;align-items:center;flex-wrap:wrap">
          ${tgt}
          <label style="display:flex;align-items:center;gap:5px"><input type="checkbox" id="bulk-skip-${ctx}" checked> ${esc(t("Skip articles already done"))}</label>
          <button class="primary" id="bulk-start-${ctx}" onclick="bulkLlmRun('${op}','${ctx}')">${esc(t("Start"))}</button>
          <button class="ghost tiny" onclick="bulkLlmStop('${ctx}')">${esc(t("Cancel"))}</button>
        </div>
        <div id="bulk-prog-${ctx}" class="hint" style="margin-top:8px"></div>
      </div>`;
    }
    function bulkLlmStop(ctx) {
      if (_bulkAbort) { try { _bulkAbort.abort(); } catch (e) { /* already done */ } _bulkAbort = null; }
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search");
      if (mount) mount.style.display = "none";
    }
    async function bulkLlmRun(op, ctx) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const prog = $("bulk-prog-" + ctx), startBtn = $("bulk-start-" + ctx);
      const p = _bulkParams(ctx);
      const skipEl = $("bulk-skip-" + ctx);
      const body = { op, skip_existing: !!(skipEl && skipEl.checked) };
      const ids = p.get("article_ids");
      if (ids) { body.article_ids = ids.split(",").map(Number).filter((n) => n); }
      else {
        if (p.get("query")) body.query = p.get("query");
        if (p.get("source")) body.source = p.get("source");
        if (p.get("language")) body.language = p.get("language");
        if (p.get("start_date")) body.start_date = p.get("start_date");
        if (p.get("end_date")) body.end_date = p.get("end_date");
      }
      if (op === "translate") { const e = $("bulk-tgt-" + ctx); body.target_language = (e && e.value.trim()) || "English"; }
      else { body.output_language = _uiLangName(); }   // summaries come back in the UI language (v2 pin)
      if (startBtn) startBtn.disabled = true;
      if (prog) prog.textContent = t("Starting…");
      _bulkAbort = ("AbortController" in window) ? new AbortController() : null;
      let done = 0, storedN = 0, skippedN = 0, failedN = 0, total = 0;
      const tally = () => `(${storedN} ${t("stored")} · ${skippedN} ${t("skipped")} · ${failedN} ${t("failed")})`;
      try {
        const resp = await fetch("/api/llm/bulk", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body), signal: _bulkAbort ? _bulkAbort.signal : undefined,
        });
        if (!resp.ok || !resp.body) {
          let detail = "HTTP " + resp.status;
          try { const j = await resp.json(); if (j.detail) detail = j.detail; } catch (e) { /* keep status */ }
          if (prog) prog.innerHTML = `<span class="note err">${esc(detail)}</span>`;
          if (startBtn) startBtn.disabled = false; return;
        }
        const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
        for (;;) {
          const { done: fin, value } = await reader.read();
          if (fin) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\n"); buf = lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            let o; try { o = JSON.parse(line); } catch (e) { continue; }
            if (o.event === "start") {
              total = o.total;
              if (prog) prog.textContent = t("Processing") + " 0/" + total + (o.capped ? " " + t("(capped)") : "") + "…";
            } else if (o.event === "item") {
              done++;
              if (o.status === "stored") storedN++;
              else if (o.status === "skipped") skippedN++;
              else if (o.status === "failed") failedN++;
              if (prog) prog.textContent = t("Processing") + " " + done + "/" + total + "… " + tally();
            } else if (o.event === "done") {
              if (o.aborted) {
                if (prog) prog.innerHTML = `<span class="note err">${esc(t("Stopped:"))} ${esc(o.reason || "")}</span> ${tally()}`;
              } else {
                if (prog) prog.innerHTML = `<b>${esc(t("Done."))}</b> ${tally()} `
                  + `<span class="muted">${esc(t("Open an article to read its summary or translation."))}</span>`;
              }
            }
          }
        }
      } catch (e) {
        if (e && e.name === "AbortError") { if (prog) prog.textContent = t("Cancelled."); }
        else if (prog) prog.innerHTML = `<span class="note err">${esc(e.message)}</span>`;
      } finally {
        if (startBtn) startBtn.disabled = false; _bulkAbort = null;
        loadLlmHealth();   // an LLM run is a fresh signal of whether Ollama is up
      }
    }

    async function loadCandidates() {
      try {
        const r = await api("/api/sources/candidates?status=candidate&limit=50");
        const panel = $("candidates-panel"), list = $("candidates-list");
        if (!panel || !list) return;
        if (!r.count) { panel.style.display = "none"; return; }
        panel.style.display = "";
        list.innerHTML = "<table><tr><th>Domain</th><th>Channel</th><th>Evidence</th><th>First seen</th><th></th></tr>" +
          r.candidates.map(c => {
            const ev = c.channel === "citation"
              ? `cited by ${esc(c.evidence.distinct_citing_articles)} of your articles`
              : `catalog entry for ${esc((c.evidence.country || "").toUpperCase())} (you have ${esc(c.evidence.your_sources_there)} there)`;
            return `<tr><td>${esc(c.domain)}</td><td>${esc(c.channel)}</td><td>${ev}</td>` +
              `<td>${esc((c.first_seen || "").slice(0, 10))}</td>` +
              `<td><button class="secondary tiny" onclick="candidateAct(${c.id}, 'promote')">Promote (disabled)</button> ` +
              `<button class="ghost tiny" onclick="candidateAct(${c.id}, 'dismiss')">Dismiss</button></td></tr>`;
          }).join("") + "</table>";
      } catch (e) { /* candidates are optional surface; stay quiet */ }
    }
    async function candidateAct(id, action) {
      try {
        const r = await api(`/api/sources/candidates/${id}/${action}`, {method: "POST"});
        toast(action === "promote"
          ? `Promoted ${r.promoted} (created disabled — enable it below when ready).`
          : `Dismissed ${r.dismissed}.`);
        loadCandidates(); loadManagedSources();
      } catch (e) { toast(`${action} failed: ` + e.message, "err"); }
    }

    async function exportMethods(qArg) {
      // RM-07: the *how* behind the current search, as a downloadable document.
      const q = (qArg != null ? qArg : $("q").value.trim());
      if (!q) { toast("Run a search first — the appendix records the query.", "err"); return; }
      try {
        const r = await api("/api/reports/methods",
          {method: "POST", body: JSON.stringify({query: q})});
        const blob = new Blob([r.markdown], {type: "text/markdown"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "methods-appendix.md";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(a.href);
        toast(`Methods appendix downloaded (${r.article_count} articles).`);
      } catch (e) { toast("Methods export failed: " + e.message, "err"); }
    }

    // The LLM pill. The local model is refused under airplane mode (we boot offline),
    // so a once-at-boot check goes stale "offline". This re-checks on: boot, going
    // online (_paintNetwork), opening Settings → Models, after any LLM action, when the
    // tab regains focus, and on click — so it tracks a model that started/stopped later.
    async function loadLlmHealth() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("llm");
      if (!el) return;
      el.style.cursor = "pointer";
      el.onclick = loadLlmHealth;   // assignment (not addEventListener) so it never stacks
      try {
        const h = await api("/api/llm/health");
        if (h.available) {
          el.className = "pill ok";
          el.textContent = `LLM ✓ (${h.installed_models.length} models)`;
          el.title = t("Local model — click to re-check");
        } else {
          el.className = "pill warn";
          el.textContent = t("LLM offline");
          el.title = (h.detail ? h.detail + " — " : "") + t("Local model — click to re-check");
        }
      } catch (e) { el.textContent = "LLM —"; el.title = t("Local model — click to re-check"); }
    }

    async function summarize(id, btn) {
      const cell = btn.parentElement.querySelector(".summary");
      cell.textContent = "Summarizing locally…";
      try {
        const r = await api(`/api/llm/articles/${id}/summarize`,
          {method: "POST", body: JSON.stringify({output_language: _uiLangName()})});
        // LLM output is a model artifact — fluent, and capable of being wrong. Carry a
        // constant verify-against-the-source note (B1 disclosure; auto-translated x12 by
        // the i18n observer). Data is esc()'d (innerHTML).
        cell.innerHTML = `“${esc(r.result)}” <span class="muted">— ${esc(r.model)}</span>`
          + `<div class="hint muted">Generated by a local model — verify against the stored article.</div>`;
      } catch (e) { cell.textContent = ""; toast("Summarize: " + e.message, "err"); }
      loadLlmHealth();   // success or failure both tell us if Ollama is reachable now
    }

    async function translateArticle(id, btn) {
      const cell = btn.parentElement.querySelector(".summary");
      cell.textContent = "Translating locally…";
      try {
        const r = await api(`/api/llm/articles/${id}/translate`,
          {method: "POST", body: JSON.stringify({target_language: "English"})});
        cell.innerHTML = `<span class="muted">[${esc(r.source_language || "?")}→${esc(r.target_language)}]</span> `
          + `${esc(r.result)} <span class="muted">— ${esc(r.model)}</span>`
          + `<div class="hint muted">Generated by a local model — verify against the stored article.</div>`;
      } catch (e) { cell.textContent = ""; toast("Translate: " + e.message, "err"); }
      loadLlmHealth();
    }

    // Framing comparison — moved into Insights, scoped to the explored term.
    // elId lets a second surface (the corpus window's Sentiment sub-tab) REUSE
    // this exact renderer + its English-only VADER disclosure (d.caveat) by
    // pointing it at a fresh host, instead of relocating the Insights DOM.
    async function loadFraming(term, elId) {
      const el = $(elId || "ins-framing");
      el.innerHTML = "<span class='muted'>Comparing how outlets frame this…</span>";
      try {
        const d = await api("/api/framing?query=" + encodeURIComponent(term));
        if (!d.framing || !d.framing.length) {
          el.innerHTML = "<span class='muted'>Not enough coverage to compare framing for this term.</span>"; return;
        }
        const rows = d.framing.map(f =>
          `<tr><td>${esc(f.source)}</td>
               <td><span class="pill ${f.tone_label==='positive'?'ok':f.tone_label==='negative'?'err':''}">${esc(f.tone_label)} ${f.avg_tone.toFixed(2)}</span></td>
               <td class="muted">${f.article_count}</td>
               <td class="muted" style="font-size:12px">${(f.top_terms||[]).slice(0,6).map(esc).join(", ")}</td></tr>`
        ).join("");
        el.innerHTML = `<table><tr><th>Outlet</th><th>Tone (VADER)</th><th>#</th><th>Emphasised terms</th></tr>${rows}</table>
          <div class="hint">${esc(d.caveat||"")}</div>`;
      } catch (e) {
        el.innerHTML = "<span class='muted'>Framing unavailable (needs the [analysis] extra installed).</span>";
      }
    }

    async function exportEvidence(qArg) {
      const q = (qArg != null ? qArg : $("q").value.trim());
      if (!q) { toast("Enter a search query to scope the evidence bundle.", "err"); return; }
      try {
        const bundle = await api("/api/reports/evidence",
          {method: "POST", body: JSON.stringify({query: q, case_name: q})});
        const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "evidence-bundle.json"; a.click();
        toast(`Signed bundle: ${bundle.manifest.item_count} item(s), verify with scripts/verify_evidence.py`);
      } catch (e) { toast("Evidence export: " + e.message, "err"); }
    }

    // -- Chain of custody --------------------------------------------------- //
    function renderCustodyStatus(s) {
      const id = s.signer || {};
      const trunc = (h) => h ? esc(h.slice(0, 16)) + "…" : "—";
      const pqcPill = s.pqc_effective
        ? '<span class="pill ok">hybrid (Ed25519 + ML-DSA)</span>'
        : (s.pqc_enabled && !s.pqc_available
            ? '<span class="pill warn">requested, library not installed</span>'
            : '<span class="pill">Ed25519 only</span>');
      const otsPill = s.ots_effective
        ? '<span class="pill ok">OpenTimestamps (Bitcoin)</span>'
        : (s.anchoring_mode === "opentimestamps" && !s.ots_available
            ? '<span class="pill warn">requested, library not installed</span>'
            : '<span class="pill">local-only</span>');
      $("custody-status").innerHTML =
        `Signing: ${pqcPill} &nbsp; Timestamps: ${otsPill} &nbsp;` +
        `<span class="pill ${s.key_protection==='aes256gcm-scrypt'?'ok':'warn'}" ` +
        `title="Set OO_KEY_PASSPHRASE to encrypt keys at rest">keys: ${esc(s.key_protection)}</span>` +
        `<div class="muted" style="font-size:12px;margin-top:4px">` +
        `Ed25519 pub ${trunc(id.ed25519_pub)}` +
        (id.ml_dsa_pub ? ` · ${esc(id.ml_dsa_variant)} pub ${trunc(id.ml_dsa_pub)}` : "") + `</div>`;
    }

    function applyCustodyToggles(s) {
      $("cust-pqc").checked = !!s.pqc_enabled;
      $("cust-ots").checked = s.anchoring_mode === "opentimestamps";
      $("cust-autolog").checked = !!s.auto_log_on_ingest;
      $("cust-actor").value = s.default_actor || "";
      $("cust-ots-warn").style.display = $("cust-ots").checked ? "block" : "none";
    }

    async function loadCustody() {
      try {
        const s = await api("/api/custody/settings");
        renderCustodyStatus(s); applyCustodyToggles(s);
      } catch (e) { $("custody-status").textContent = "Custody settings unavailable: " + e.message; }
    }

    async function saveCustody() {
      const body = {
        pqc_enabled: $("cust-pqc").checked,
        anchoring_mode: $("cust-ots").checked ? "opentimestamps" : "local",
        auto_log_on_ingest: $("cust-autolog").checked,
        default_actor: $("cust-actor").value.trim() || null,
      };
      try {
        const s = await api("/api/custody/settings", {method: "PUT", body: JSON.stringify(body)});
        renderCustodyStatus(s); applyCustodyToggles(s);
        if (s.pqc_enabled && !s.pqc_available)
          toast("PQC requested, but the 'pqc' extra is not installed — signing stays Ed25519-only.", "warn");
        else if (s.anchoring_mode === "opentimestamps" && !s.ots_available)
          toast("OpenTimestamps requested, but the 'timestamping' extra is not installed.", "warn");
        else toast("Custody settings saved.");
      } catch (e) { toast("Save failed: " + e.message, "err"); }
    }

    function custItem() {
      const id = $("cust-item").value.trim();
      if (!id) { toast("Enter an item id (e.g. article:42).", "err"); return null; }
      return id;
    }

    async function viewChain() {
      const id = custItem(); if (!id) return;
      try {
        const d = await api("/api/custody/" + encodeURIComponent(id));
        const t = $("cust-entries");
        t.innerHTML = "<tr><th>#</th><th>Action</th><th>Actor</th><th>Time</th><th>Sig</th></tr>" +
          d.entries.map(e =>
            `<tr><td>${e.seq}</td><td>${esc(e.action)}</td><td>${esc(e.actor||"—")}</td>
             <td class="muted" style="font-size:12px">${esc((e.timestamp&&e.timestamp.asserted_time||e.timestamp&&e.timestamp.kind)||"—")}</td>
             <td><span class="pill">${esc(e.signature&&e.signature.algorithm||"?")}</span></td></tr>`).join("");
        $("cust-result").textContent = `${d.entry_count} custody entr${d.entry_count===1?"y":"ies"}.`;
      } catch (e) { $("cust-entries").innerHTML = ""; toast("View chain: " + e.message, "err"); }
    }

    async function verifyChain() {
      const id = custItem(); if (!id) return;
      try {
        const d = await api("/api/custody/" + encodeURIComponent(id) + "/verify");
        $("cust-result").innerHTML = d.verified
          ? '<span class="pill ok">verified</span> chain intact, signatures valid.'
          : '<span class="pill err">FAILED</span> ' + esc((d.issues||[]).join("; "));
      } catch (e) { toast("Verify: " + e.message, "err"); }
    }

    async function exportCustody() {
      const id = $("cust-item").value.trim();
      try {
        const bundle = await api("/api/custody/export" + (id ? "?item_id=" + encodeURIComponent(id) : ""));
        const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "custody-bundle.json"; a.click();
        toast(`Bundle: ${bundle.entry_count} entr${bundle.entry_count===1?"y":"ies"} — verify with scripts/verify_custody.py`);
      } catch (e) { toast("Export: " + e.message, "err"); }
    }

    async function anchorRoot() {
      const root = $("cust-root").value.trim();
      if (!root) { toast("Enter a Merkle root (hex).", "err"); return; }
      const provider = $("cust-ots").checked ? "opentimestamps" : "local";
      try {
        const r = await api("/api/custody/anchor",
          {method: "POST", body: JSON.stringify({merkle_root: root, provider})});
        $("cust-result").innerHTML = `Anchored via <span class="pill ok">${esc(r.provider)}</span> — ${esc(r.detail)}`;
      } catch (e) { toast("Anchor: " + e.message, "err"); }
    }

    $("cust-ots").addEventListener("change", () =>
      $("cust-ots-warn").style.display = $("cust-ots").checked ? "block" : "none");

    $("q").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

    // Apply the saved look immediately (before any network) so there is no flash.
    applyUi(getUi()); buildDrawer();

    // Re-check the local LLM when the tab regains focus — covers starting/stopping
    // Ollama in another window without a constant poll (event-driven, cheap loopback).
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && _netOnline !== false) loadLlmHealth();
    });

    // Global shortcuts: Ctrl/⌘-K opens the command palette; Escape closes overlays.
    document.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
      else if (e.key === "Escape") { closePalette(); closeDrawer(); document.body.classList.remove("nav-open"); }
    });

    // Initial load: always-on essentials; per-tab data loads lazily on first view.
    // Settings is loaded eagerly so the default result limit + theme seed apply
    // app-wide (mark it loaded so opening the tab doesn't refetch).
    _loaded.add("settings");
    loadSettings().then(doSearch);
    if (_media) _media.addEventListener("change", () => {
      if (getUi().theme === "system") applyThemeAttr("system");
    });
    loadHealth(); loadLlmHealth(); loadSources(); checkEmptyCorpus();
    // Keep the background-activity chip live app-wide (e.g. a scheduled scrape that
    // the user didn't trigger from the current tab). Adaptive: fast while a scrape
    // is active, backing off when idle; paused while the tab is hidden (audit PR G).
    _adaptivePoll(_pollActivity);
    // Dismiss the vitals popover on Escape or an outside click.
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && _vitalsOpen) toggleVitals(); });

    // -- Easter egg (opt-in, documented, harmless) -------------------------- //
    // Type the Konami code (↑↑↓↓←→←→ B A) to surface a random attributed journalism
    // quote / sourced fun fact. Only fires on the deliberate sequence, never during a
    // task, and never in evidence/exports — personality without intrusion.
    (function () {
      const seq = ["ArrowUp","ArrowUp","ArrowDown","ArrowDown","ArrowLeft","ArrowRight","ArrowLeft","ArrowRight","b","a"];
      let pos = 0, alt = false;
      document.addEventListener("keydown", (e) => {
        const t = e.target && e.target.tagName;
        if (t === "INPUT" || t === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
        pos = (e.key.toLowerCase() === seq[pos].toLowerCase()) ? pos + 1 : 0;
        if (pos !== seq.length) return;
        pos = 0; alt = !alt;
        api("/api/personality/random?kind=" + (alt ? "fact" : "quote")).then(r => {
          const it = r.item; if (!it) return;
          const msg = it.kind === "fact"
            ? `${it.text}${it.source ? `  — ${it.source}` : ""}`
            : `"${it.text}"  — ${it.author || "Unknown"}${it.attribution === "disputed" ? " (attribution disputed)" : ""}`;
          toast(msg, "ok");
        }).catch(() => {});
      });
    })();
    document.addEventListener("click", (e) => {
      if (!_vitalsOpen) return;
      const pop = $("vitals-pop"), chip = $("activity");
      if (pop && !pop.contains(e.target) && chip && !chip.contains(e.target)) toggleVitals();
    });
    ensureDocList();   // so the command palette can offer docs before Help is opened
    // -- External-link guard (maintainer ruling 2026-06-10): the app ALWAYS --- //
    // asks before opening an external link. Capture-phase + delegated, so it
    // covers every anchor — static or rendered later. Loopback links are exempt.
    // ---- the hover-for-information enhancer (one delegated listener; the ----
    // bubble re-reads the live translated title, so language switches apply.
    (function ooTipInit() {
      const tip = document.createElement("div"); tip.id = "oo-tip";
      tip.setAttribute("role", "tooltip"); document.body.appendChild(tip);
      const mark = (root) => {
        (root.querySelectorAll ? root.querySelectorAll("[title]") : []).forEach((el) => {
          if ((el.getAttribute("title") || "").trim()) el.classList.add("oo-tip-target");
        });
      };
      mark(document);
      new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) { if (n.hasAttribute && n.hasAttribute("title")) mark({querySelectorAll: () => [n]}); mark(n); }
      }))).observe(document.body, {childList: true, subtree: true});
      let cur = null, hideT = null;
      function show(el, x, y) {
        const text = el.getAttribute("title") || el.dataset.ooTip || "";
        if (!text.trim()) return;
        el.dataset.ooTip = text; el.removeAttribute("title");  // suppress the native double bubble
        cur = el; tip.textContent = text;
        tip.style.left = Math.min(x + 12, window.innerWidth - 346) + "px";
        tip.style.top = Math.min(y + 14, window.innerHeight - tip.offsetHeight - 12) + "px";
        tip.classList.add("show");
      }
      function hide() {
        if (cur && cur.dataset.ooTip != null) { cur.setAttribute("title", cur.dataset.ooTip); }
        cur = null; tip.classList.remove("show");
      }
      document.addEventListener("mouseover", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        clearTimeout(hideT);
        if (el && el !== cur) { hide(); show(el, e.clientX, e.clientY); }
        else if (!el) hideT = setTimeout(hide, 80);
      }, true);
      document.addEventListener("focusin", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        if (el) { const r = el.getBoundingClientRect(); hide(); show(el, r.left, r.bottom); }
      }, true);
      document.addEventListener("focusout", () => hide(), true);
      let pressT = null;  // touch: long-press opens the same bubble (title never did)
      document.addEventListener("touchstart", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        if (!el) { hide(); return; }
        const t = e.touches[0];
        pressT = setTimeout(() => show(el, t.clientX, t.clientY), 450);
      }, {passive: true});
      document.addEventListener("touchend", () => { clearTimeout(pressT); hideT = setTimeout(hide, 2600); }, {passive: true});
    })();

    document.addEventListener("click", function _externalLinkGuard(e) {
      const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a || !/^https?:/i.test(a.href)) return;
      let host = "";
      try { host = new URL(a.href).hostname; } catch { return; }
      if (host === "127.0.0.1" || host === "localhost" || host === location.hostname) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Open this external link in your browser?") + "\n\n" + a.href + "\n\n" +
                   t("This leaves the app and contacts an outside server.")))
        { e.preventDefault(); e.stopImmediatePropagation(); }
    }, true);
    // Honour a deep-link like /#sources on first load; otherwise land on Home.
    // showTab itself maps legacy aliases (#database -> #library) and falls back.
    showTab((location.hash || "#home").slice(1), false);  // initial render: replace, don't push

    // Wire the universal subtab grammar on every multi-section surface (one
    // component, three surfaces). No opts.initial: each surface keeps its
    // HTML-default panel; the component just adopts ARIA + keyboard + click.
    _insSubtabs = ooSubtabs($("ins-subtabs"), showInsightCat);
    _setSubtabs = ooSubtabs($("set-subtabs"), showSetCat);
    _corpusSubtabs = ooSubtabs($("corpus-subtabs"), corpusTab);
    // Closing the corpus window returns the shared mind-map kit to Insights
    // (so the Insights Explore mind-map is never left empty after a relocation).
    $("corpus-win").addEventListener("close", _mmKitHome);
    ooSubtabs($("tm-subtabs"), tmSelectTab);  // the task-manager window (Tasks / System)
    _anSubtabs = ooSubtabs($("an-subtabs"), anSelectTab);  // the analysis window (Keywords / Articles)