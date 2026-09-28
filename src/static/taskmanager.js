/* Open Omniscience — the /tasks page's script, moved out of an inline <script> in taskmanager.html
   so the CSP can drop script-src 'unsafe-inline' (Q1127 = a, 0.5 row I). It loads at the
   same point in the page as the inline block did, so it runs in the same order. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // Reuse the SPA's translations: most task-manager strings are keyed; genuinely new
  // redesign strings fall back to English (keyable later — i18n gate stays 100%).
  function t(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
  // setLang is ASYNC (it fetches the locale). The whole-document apply() below used to
  // run straight after it, against a still-empty map: it recorded the English <title>
  // as the original and left it English, and nothing walked <head> again, because
  // setLang's own apply() and the walker's observer both start at document.body. So the
  // tab read "Task manager · FOOS" in every language (2026-09-26 click-through O4).
  // Awaiting it makes this pass the one that translates the title.
  function applyLang() {
    try {
      var lang = localStorage.getItem("oo.lang");
      var I = window.OOI18N;
      if (!I) return;
      Promise.resolve(lang && I.setLang ? I.setLang(lang) : null)
        .then(function () { if (I.apply) I.apply(document); })
        .catch(function () { /* locale unreadable: English fallback */ });
    } catch (e) { /* private mode / engine absent: English fallback */ }
  }
  // The app's LOOK, read from the one place the app keeps it: localStorage "oo.ui", a
  // JSON blob with .theme and .accent (app-shell.js getUi/applyUi). This page read an
  // "oo.theme" key that nothing has ever written, so it rendered Ink under a Paper or a
  // Solar app (2026-09-27 re-walk T-8). The theme is mapped the way applyThemeAttr maps
  // it: "system" follows the OS preference (light -> the Light theme, dark -> Ink), "ink"
  // or nothing is the :root palette, anything else is its own data-theme. Re-applied
  // when another tab changes the look (the storage listener below) and when the OS
  // flips light/dark under "system".
  var _lightQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  function applyAppLook() {
    var ui = {};
    try { ui = JSON.parse(localStorage.getItem("oo.ui") || "{}") || {}; } catch (e) { ui = {}; }
    var theme = ui.theme || "ink";
    // The theme cull (Q1123 = b): the same retired -> survivor map as app-shell.js's
    // RETIRED_THEMES, so a pick the app has not re-saved yet still lands on its survivor.
    var RETIRED_THEMES = { slate: "ink", arctic: "ink", mist: "light" };
    if (RETIRED_THEMES[theme]) theme = RETIRED_THEMES[theme];
    var eff = theme === "system" ? (_lightQuery && _lightQuery.matches ? "light" : "")
      : theme === "ink" ? "" : theme;
    var r = document.documentElement;
    if (eff) r.setAttribute("data-theme", eff); else r.removeAttribute("data-theme");
    if (ui.accent) r.style.setProperty("--accent", ui.accent); else r.style.removeProperty("--accent");
  }
  applyAppLook();
  if (_lightQuery && _lightQuery.addEventListener) {
    _lightQuery.addEventListener("change", applyAppLook);
  }

  // The SPA's _sizeText (app-core.js), for this page (2026-09-26 click-through P8): the
  // unit is one keyed frame per unit, so a locale writes it its own way and on its own
  // side of the number; the number is formatted for the UI language with Latin digits;
  // the result rides in a first-strong isolate so an Arabic line cannot reorder it; and
  // a no-break space keeps the number on its unit's line. The value is unchanged:
  // binary steps of 1024 under the SI-style names.
  function fmtBytes(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    var TF = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : function (s, o) { return s.replace("{n}", o.n); };
    var v = Number(n), i = 0;
    while (v >= 1024 && i < 4) { v /= 1024; i++; }
    // The app's one number convention (a decimal POINT in every locale, as fmtNum and
    // app-core.js's _sizeText write it); only the unit's written form is translated.
    var dec = i === 0 ? 0 : 1, num = v.toFixed(dec);
    var s = i === 0 ? TF("{n} B", { n: num })
      : i === 1 ? TF("{n} KB", { n: num })
      : i === 2 ? TF("{n} MB", { n: num })
      : i === 3 ? TF("{n} GB", { n: num })
      : TF("{n} TB", { n: num });
    return "\u2068" + s.replace(/ /g, "\u00a0") + "\u2069";
  }
  function fmtRate(bps) {
    var TF = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : function (s, o) { return s.replace("{rate}", o.rate); };
    return bps == null ? "—" : TF("{rate}/s", { rate: fmtBytes(bps) });
  }
  function tf(s, v) {
    if (window.OOI18N && OOI18N.tf) return OOI18N.tf(s, v);
    return String(s).replace(/\{(\w+)\}/g, function (m, k) { return (v && v[k] != null) ? String(v[k]) : m; });
  }
  // The app's ruled number formatter (fmtNum in app-markets.js: Latin digits, a decimal
  // POINT and a narrow no-break space between thousands in every locale). This page does
  // not load the SPA bundle, so the function is copied, not imported; KEEP THE TWO IN STEP
  // -- tests/clickthrough_b17_node_test.js runs both over the same values. Every count on
  // this page goes through it, as the in-app window's do (click-through B17, T5).
  function fmtNum(v, maxDec) {
    if (v == null || !isFinite(v)) return "—";
    var a = Math.abs(v);
    var dec = maxDec != null ? maxDec : (a >= 1000 ? 1 : a >= 100 ? 1 : a >= 1 ? 2 : 3);
    var s = v.toFixed(dec).replace(/\.?0+$/, function (m) { return m.indexOf(".") !== -1 ? "" : m; });
    var parts = s.split(".");
    var grouped = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
    return parts[1] ? grouped + "." + parts[1] : grouped;
  }
  // A duration as the locale writes it (click-through B17, T7): each unit is a keyed frame
  // ("{n} s", "{n} min", "{n} h"), as the in-app window's _fmtDur writes them, so a locale
  // spells the unit its own way and on its own side of the number.
  function fmtDur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 90) return "~" + tf("{n} s", { n: fmtNum(Math.max(1, s), 0) });
    if (s < 5400) return "~" + tf("{n} min", { n: fmtNum(Math.round(s / 60), 0) });
    return "~" + tf("{n} h", { n: fmtNum(s / 3600, 1) });
  }
  // A relative time as the locale writes it (click-through B19, Q3): the span is a keyed
  // unit frame, the direction a keyed frame around it ("in {t}", "{t} ago"), so neither
  // the English "in"/"ago" nor a welded "7m" reaches another language.
  function fmtRel(iso) {
    if (!iso) return "—";
    var d = new Date(iso), s = Math.round((Date.now() - d.getTime()) / 1000);
    if (isNaN(s)) return "—";
    var fut = s < 0; s = Math.abs(s);
    var v = s < 60 ? tf("{n} s", { n: fmtNum(s, 0) })
      : s < 3600 ? tf("{n} min", { n: fmtNum(Math.round(s / 60), 0) })
      : tf("{n} h", { n: fmtNum(Math.round(s / 3600), 0) });
    return fut ? tf("in {t}", { t: v }) : tf("{t} ago", { t: v });
  }
  // The exact moment in the APP's language, as the SPA's fmtDateTime (app-shell.js) writes
  // it -- the browser's own locale is not the language the operator chose (B19, Q3).
  function fmtLocal(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso || "";
    try {
      var lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : undefined;
      return new Intl.DateTimeFormat(lang,
        { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
    } catch (e) { return d.toLocaleString(); }
  }

  async function api(path, opts) {
    var res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
    var text = await res.text(), data;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (res.status === 503 && data && data.locked) { location.replace("/unlock"); throw new Error("locked"); }
    if (!res.ok) throw new Error((data && data.detail) || res.status + " " + res.statusText);
    return data;
  }
  function toast(msg, kind) {
    var c = $("tm-conn");
    if (c) { c.textContent = msg; c.className = "muted" + (kind === "err" ? " err-line" : ""); setTimeout(refresh, 400); }
  }

  // ---- which job kind belongs to which Processes group ---- //
  var isDl = function (k) { return k === "wiki-dump" || k === "osm-map"; };
  var isLocal = function (k) { return k === "reindex" || k === "keyword-fold" || k === "search-reindex"; };
  var dlKey = function (j) { return j.id.slice(j.id.indexOf(":") + 1); };
  var reorderEp = function (k) { return k === "osm-map" ? "/api/jobs/osm/reorder" : "/api/jobs/dumps/reorder"; };
  // Processes are grouped like Windows groups apps/background/services.
  var GROUPS = [
    { id: "collect", title: "Collection", kinds: ["collect"] },
    { id: "download", title: "Downloads", kinds: ["wiki-dump", "osm-map"] },
    { id: "ai", title: "AI & analysis", kinds: ["llm", "analytics", "index"] },
    { id: "network", title: "Network", kinds: ["fetch"] }
  ];
  function groupOf(kind) {
    for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].kinds.indexOf(kind) >= 0) return GROUPS[i].id;
    return "ai"; // any future background task lands under AI & analysis by default
  }

  var _jobs = null;

  // THE THIRD OWNER of the Intl language-name constructor (test_alpha3_display_surfaces):
  // this page loads neither app-map.js's `ooLangName` nor the reader's `langName`. A CLDR
  // answer that merely ECHOES the code is not a name, and is refused here: the caller
  // then keeps the server's English sentence rather than print "simple Wikipedia".
  var _langDN = {};
  function langName(code) {
    var src = String(code == null ? "" : code).trim();
    if (!src) return "";
    var ui = "en";
    try { ui = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en"; } catch (e) { ui = "en"; }
    try {
      if (!_langDN[ui]) _langDN[ui] = new Intl.DisplayNames([ui], { type: "language" });
      var name = _langDN[ui].of(src);
      return (name && name.toLowerCase() !== src.toLowerCase()) ? name : "";
    } catch (e) { return ""; }
  }
  // A job's percent as a WHOLE number (click-through B17, T5), as the in-app window's
  // _jobPct draws it: the fold and the re-index publish one decimal ("86.8%"), which says
  // nothing the exact count beside it does not; and it never reads 100 while work is
  // left, so 99.5 and up stays 99 until the count is full.
  function jobPct(p) {
    var done = Number(p.done) || 0, total = Number(p.total) || 0;
    if (total > 0 && done >= total) return 100;
    var raw = (typeof p.percent === "number" && isFinite(p.percent)) ? p.percent
      : (total > 0 ? 100 * done / total : 0);
    return Math.min(99, Math.max(0, Math.round(raw)));
  }
  // A job label carrying a value arrives as a keyed FRAME plus its values (`label_i18n` /
  // `label_vars`, beside the unchanged English `label` -- src/api/jobs.py), and is written
  // here exactly as the in-app window's _jobLabel writes it (click-through B17, T11): a
  // number through fmtNum, `language` (a CODE) as the name in the UI language, anything
  // else as data in an isolate. A fixed label is still a key: t(). A language this page
  // cannot name keeps the server's English sentence whole. A value that is itself
  // {i18n, vars} is a keyed phrase, written by these same rules (click-through B19).
  function jobLabel(j) {
    if (!j.label_i18n) return t(j.label || "");
    var vars = j.label_vars || {}, out = {};
    for (var k in vars) {
      if (!Object.prototype.hasOwnProperty.call(vars, k)) continue;
      var x = vars[k];
      if (typeof x === "number") out[k] = fmtNum(x, 0);
      else if (x && typeof x === "object" && x.i18n)
        out[k] = jobLabel({ label: x.i18n, label_i18n: x.i18n, label_vars: x.vars || {} });
      else if (k === "language") {
        var name = langName(x);
        if (!name) return t(j.label || "");
        out[k] = name;
      } else out[k] = "\u2068" + String(x == null ? "" : x) + "\u2069";
    }
    return tf(j.label_i18n, out);
  }

  // A job's detail line ("model {model}") arrives with its keyed frame beside the English
  // (`detail_i18n` / `detail_vars`) and is written by jobLabel's rules; a fixed line is
  // still a key (click-through B19, Q5).
  function jobDetail(j) {
    return j.detail_i18n
      ? jobLabel({ label: j.detail, label_i18n: j.detail_i18n, label_vars: j.detail_vars || {} })
      : t(j.detail || "");
  }

  // WHY a download is not moving (S04-08's S5, Q1014): who paused it, or the failure
  // verbatim. The same causes app-core.js's _jobWhy draws in the in-app window -- this
  // page is where the top-bar task-manager button lands, so a cause drawn only there
  // would leave the operator's own window as silent as before.
  function jobWhy(j) {
    if (!isDl(j.kind)) return "";
    var line = "";
    if (j.state === "paused") {
      if (j.paused_by === "airplane") line = t("Paused by airplane mode. Resume asks to go online first.");
      else if (j.paused_by === "operator") line = t("Paused by you.");
      else if (j.paused_by === "restart") line = t("Paused when the app stopped mid-download; the partial file is kept.");
    } else if (j.state === "failed" && j.error) {
      // The keyed label frame app-core.js's _jobWhy uses (ooLabelText), so zh/ja take
      // their full-width colon with no Latin space after it (re-walk O-5).
      line = tf("{prefix}: {text}", { prefix: "\u0001", text: "\u0002" })
        .replace("\u0001", function () { return t("Failed"); })
        .replace("\u0002", function () { return String(j.error); });
    }
    return line ? '<div class="muted" style="font-size:11px">' + esc(line) + "</div>" : "";
  }

  function jobRow(j, queuedKeysByKind) {
    var pill = j.state === "running" ? "ok" : (j.state === "failed" ? "err" : "warn");
    var prog = "";
    if (j.progress && j.progress.total) {
      var pct = jobPct(j.progress);
      // A count names WHAT it counts ("12 / 40 keywords"), the unit keyed x12 as the
      // in-app window's _jobRow draws it; "12 / 40" alone was the keyword fold's row
      // (click-through B16, V10).
      var what = j.progress.unit && j.progress.unit !== "bytes" ? " " + esc(t(j.progress.unit)) : "";
      // Bytes by the unit the producer publishes, as the in-app _jobRow reads it: a model
      // pull's bytes are not a download KIND here and printed "1288490188 / 4831838208"
      // (click-through B17, T5). A row with no unit is a download's bytes or a task's count.
      var bytes = j.progress.unit ? j.progress.unit === "bytes" : isDl(j.kind);
      var unit = bytes ? (fmtBytes(j.progress.done) + " / " + fmtBytes(j.progress.total))
                       : (fmtNum(j.progress.done, 0) + " / " + fmtNum(j.progress.total, 0) + what);
      prog = '<div class="cap-bar" role="progressbar" aria-valuenow="' + pct + '" aria-valuemin="0" aria-valuemax="100"><i style="width:' + pct + '%"></i></div>' +
             '<div class="muted" style="font-size:11px">' + unit + " · " + pct + '%</div>';
    } else if (j.elapsed_s != null) {
      prog = '<div class="muted" style="font-size:11px">' + esc(tf("running for {t}", { t: fmtDur(j.elapsed_s) })) + "</div>";
    }
    var acts = [];
    if (j.id === "collect:current")
      acts.push('<button class="tbtn danger" title="' + esc(t("Stopping collection engages the network kill switch — the app goes offline.")) + '" data-tm="cancel" data-id="' + esc(j.id) + '">' + esc(t("Stop")) + "</button>");
    if (isDl(j.kind) && j.state === "running")
      acts.push('<button class="tbtn" data-tm="cancel" data-id="' + esc(j.id) + '">' + esc(t("Pause")) + "</button>");
    if (isDl(j.kind) && j.state === "queued") {
      var k = dlKey(j), keys = queuedKeysByKind[j.kind] || [], idx = keys.indexOf(k);
      if (idx > 0) acts.push('<button class="tbtn" title="' + esc(t("Move earlier in the queue")) + '" data-tm="move" data-dir="-1" data-key="' + esc(k) + '" data-kind="' + esc(j.kind) + '">↑</button>');
      if (idx >= 0 && idx < keys.length - 1) acts.push('<button class="tbtn" title="' + esc(t("Move later in the queue")) + '" data-tm="move" data-dir="1" data-key="' + esc(k) + '" data-kind="' + esc(j.kind) + '">↓</button>');
      acts.push('<button class="tbtn" data-tm="cancel" data-id="' + esc(j.id) + '">' + esc(t("Cancel")) + "</button>");
    }
    if (isDl(j.kind) && (j.state === "paused" || j.state === "failed"))
      acts.push('<button class="tbtn" data-tm="resume" data-id="' + esc(j.id) + '">' + esc(t("Resume")) + "</button>");
    // The local DB-writer jobs (re-index, keyword fold, search re-index) draw the controls
    // the server lists in `actions` for their state, as the in-app window's _jobRow does.
    // "cancel" on a RUNNING job is the same pause and is not drawn twice; on a stopped
    // keyword fold it discards the saved cursor (jobs.py).
    if (isLocal(j.kind)) {
      var a = Array.isArray(j.actions) ? j.actions : [];
      if (a.indexOf("pause") >= 0)
        acts.push('<button class="tbtn" data-tm="cancel" data-id="' + esc(j.id) + '">' + esc(t("Pause")) + "</button>");
      if (a.indexOf("resume") >= 0)
        acts.push('<button class="tbtn" data-tm="resume" data-local="1" data-id="' + esc(j.id) + '">' + esc(t("Resume")) + "</button>");
      if (a.indexOf("cancel") >= 0 && a.indexOf("pause") < 0 && j.kind === "keyword-fold")
        acts.push('<button class="tbtn" data-tm="cancel" data-id="' + esc(j.id) + '">' + esc(t("Cancel")) + "</button>");
    }
    var qpos = j.queue_position ? ' <span class="muted">#' + fmtNum(j.queue_position, 0) + " " + esc(t("in queue")) + "</span>" : "";
    // A fixed job label is keyed x12; one carrying a value arrives as a frame (jobLabel).
    return '<div class="job"><span class="pill ' + pill + '">' + esc(t(j.state)) + '</span><span class="label">' + esc(jobLabel(j)) + "</span>" + qpos +
           '<span class="acts">' + acts.join("") + "</span>" +
           (j.detail ? '<div class="detail">' + esc(jobDetail(j)) + "</div>" : "") +
           '<div style="flex-basis:100%">' + prog + jobWhy(j) + "</div></div>";
  }

  // ---- Processes: a unified, grouped live list of EVERYTHING happening ---- //
  function renderProcesses(data, act) {
    _jobs = data;
    var jobs = (data.jobs || []).filter(function (j) { return j.state !== "done"; });
    var queued = jobs.filter(function (j) { return j.state === "queued"; })
                     .sort(function (a, b) { return (a.queue_position || 0) - (b.queue_position || 0); });
    var queuedKeysByKind = {};
    queued.forEach(function (j) { if (isDl(j.kind)) (queuedKeysByKind[j.kind] = queuedKeysByKind[j.kind] || []).push(dlKey(j)); });
    // The collect job carries the honest pass phase in its label already (backend).
    var byGroup = {};
    jobs.forEach(function (j) { (byGroup[groupOf(j.kind)] = byGroup[groupOf(j.kind)] || []).push(j); });
    var html = "";
    GROUPS.forEach(function (g) {
      var rows = byGroup[g.id];
      if (!rows || !rows.length) return;
      html += '<div class="vsect">' + esc(t(g.title)) + ' <span class="count">' + fmtNum(rows.length, 0) + "</span></div>" +
              rows.map(function (j) { return jobRow(j, queuedKeysByKind); }).join("");
    });
    if (!html) {
      html = '<div class="muted" style="padding:6px 0">' +
        esc(t("Nothing active right now — running jobs (a collection pass, downloads, the fetch on the wire, LLM work) appear here.")) + "</div>";
    }
    $("jobs-body").innerHTML = html;
  }

  // ---- Queue: the reorderable DOWNLOAD queue + a read-only collection preview ---- //
  function renderQueue(data, act) {
    var jobs = (data.jobs || []).filter(function (j) { return j.state !== "done"; });
    var queued = jobs.filter(function (j) { return j.state === "queued"; })
                     .sort(function (a, b) { return (a.queue_position || 0) - (b.queue_position || 0); });
    var queuedKeysByKind = {};
    queued.forEach(function (j) { if (isDl(j.kind)) (queuedKeysByKind[j.kind] = queuedKeysByKind[j.kind] || []).push(dlKey(j)); });
    var qHtml = '<div class="vsect">' + esc(t("Queue")) + "</div>" + (queued.length
      ? queued.map(function (j) { return jobRow(j, queuedKeysByKind); }).join("")
      : '<div class="muted" style="padding:4px 0">' + esc(t("The queue is empty — downloads waiting their turn appear here, in order; use the arrows to reorder them.")) + "</div>");
    // Read-only "Up next" preview of the COLLECTION order (NOT a reorderable queue:
    // it is re-randomised every pass, stratified by language + tag). Reuses the plan
    // the activity poll already fetched (window._act).
    var plan = (act && act.plan) || (window._act && window._act.plan) || {};
    var ups = plan.next_targets || [];
    if (ups.length) {
      var more = Math.max(0, (plan.planned_total || 0) - ups.length);
      // A FULL vertical list (P2-12), numbered, not a wrapped chip cloud — it reads
      // as the actual upcoming order. The trailing "+N more" is the honest remainder
      // the backend didn't enumerate, never a fabricated row.
      qHtml += '<div class="vsect">' + esc(t("Up next this pass")) + "</div>" +
        '<ol class="tm-upnext">' + ups.map(function (d) { return "<li>" + esc(d) + "</li>"; }).join("") +
        (more ? '<li class="muted">+' + fmtNum(more, 0) + " " + esc(t("more")) + "</li>" : "") + "</ol>" +
        '<div class="vnote">' + esc(t("Order is re-randomised every pass — stratified by language and tag, not a fixed queue.")) + "</div>";
      // The ACTUAL strata the pass interleaves by (#5): real counts per language & tag.
      var st = plan.strata || {};
      var stratHtml = function (rows) {
        return (rows || []).map(function (x) {
          var bucket = String(x.key || "").charAt(0) === "·";
          var label = bucket ? esc(t(x.key === "·untagged" ? "untagged" : "unknown")) : esc(x.key);
          return '<span class="cap-chip' + (bucket ? " muted" : "") + '">' + label +
            '<span class="muted"> ·' + fmtNum(x.n, 0) + "</span></span>";
        }).join("");
      };
      if ((st.languages || []).length) {
        qHtml += '<div class="vrow"><span class="vk">' + esc(t("Languages")) +
          '</span><span class="vv cap-chips">' + stratHtml(st.languages) + "</span></div>";
      }
      if ((st.tags || []).length) {
        qHtml += '<div class="vrow"><span class="vk">' + esc(t("Tags")) +
          '</span><span class="vv cap-chips">' + stratHtml(st.tags) + "</span></div>";
      }
    }
    $("queue-body").innerHTML = qHtml;
  }

  // ---- Schedule — the scheduler's own facts, AIRPLANE-AWARE ---- //
  function renderSchedule(a) {
    var el = $("sched-body");
    if (!a) { el.innerHTML = '<div class="muted">' + esc(t("No collection scheduled or running right now — when collection is on, the schedule appears here.")) + "</div>"; return; }
    var s = a.settings || {}, pg = a.progress, offline = a.online === false;
    var row = function (k, v) { return '<div class="vr"><span>' + k + "</span><b>" + v + "</b></div>"; };
    var sect = function (x) { return '<div class="vsect">' + x + "</div>"; };
    // Airplane mode is the truth: a pass winding down while offline is NOT
    // "collection in progress" — show it as paused, in the engaged-airplane colour.
    var state = offline ? '<span class="pill err">' + esc(t("paused — airplane mode")) + "</span>"
              : a.active ? '<span class="pill ok">' + esc(t("running — collection in progress")) + "</span>"
              : a.running ? '<span class="pill ok">' + esc(t("running")) + "</span>"
              : '<span class="pill">' + esc(t("stopped")) + "</span>";
    var now;
    if (pg && pg.total && !offline) {
      var pct = Math.round(100 * Math.min(pg.done, pg.total) / pg.total);
      now = row(t("Current pass"), esc(pg.current || "…")) +
        '<div class="cap-bar"><div class="cap-fill" style="width:' + pct + '%"></div><span class="cap-txt">' + fmtNum(pg.done, 0) + "/" + fmtNum(pg.total, 0) + " · " + pct + '%</span></div>';
    } else if (offline && a.active) {
      now = row(t("Current pass"), '<span class="muted">' + esc(t("winding down — airplane mode engaged")) + "</span>");
    } else if (a.active) {
      var _ph = { collecting: t("Collecting articles"),
                  background: t("Background tasks (markets · calendars · checks)"),
                  briefing: t("Building the briefing") }[a.phase];
      now = row(t("Current pass"), '<span class="muted">' + esc(_ph || t("Collecting articles")) + "</span>");
    } else { now = row(t("Current pass"), '<span class="muted">' + esc(t("idle — no pass in flight")) + "</span>"); }
    var cadence = s.continuous
      ? '<span title="' + esc(t("Continuous: passes run back-to-back with only a short gap while online. Going offline stops the loop.")) + '">' + esc(t("continuous (back-to-back passes)")) + "</span>"
      : "<b>" + (s.interval_minutes != null ? esc(String(s.interval_minutes)) : "—") + "</b> " + esc(t("minutes between passes"));
    var next = offline ? row(t("Next pass"), '<span class="muted">' + esc(t("not while airplane mode is engaged")) + "</span>")
      : !a.running ? row(t("Next pass"), '<span class="muted">' + esc(t("not scheduled — collection is stopped")) + "</span>")
      : a.active ? row(t("Next pass"), '<span class="muted">' + esc(t("a pass is running now")) + "</span>")
      : a.next_run ? row(t("Next pass"), '<span title="' + esc(fmtLocal(a.next_run)) + '">' + esc(fmtRel(a.next_run)) + "</span>")
      : row(t("Next pass"), '<span class="muted">' + esc(t("scheduled — timing not yet known")) + "</span>");
    var last = a.last_run ? row(t("Last run"), '<span title="' + esc(fmtLocal(a.last_run)) + '">' + esc(fmtRel(a.last_run)) + "</span>")
                          : row(t("Last run"), '<span class="muted">' + esc(t("no run yet")) + "</span>");
    // No "Mode" row and no mode after the current domain: the scheduler mode was
    // RETIRED (Q1020 = a, b45bed19) and neither the settings, the activity nor the
    // pass progress carries one, so both read as an empty value (2026-09-27 re-walk T-5).
    el.innerHTML = sect(t("Collection")) + '<div class="vr"><span>' + esc(t("State")) + "</span><b>" + state + "</b></div>" + now +
      sect(t("Schedule")) + '<div class="vr"><span>' + esc(t("Cadence")) + "</span><b>" + cadence + "</b></div>" + next + last +
      '<div class="vnote">' + esc(t("These are the scheduler’s own facts — the schedule is managed in Settings. Times are relative; hover for the exact local moment and the method.")) + "</div>";
  }

  // ---- Performance — live hardware charts (rolling buffers, diffed rates) ---- //
  var PERF_N = 60; // ~ last 2-6 min depending on the adaptive poll interval
  var _perf = { cpu: [], memPct: [], disk: [], net: [] };
  var _lastSample = null; // {at, io, net} for rate diffs
  var _memMax = 1; // running max RSS so the memory sparkline is self-scaling
  function _push(arr, v) { arr.push(v); if (arr.length > PERF_N) arr.shift(); }
  function sparkSvg(vals, opts) {
    opts = opts || {};
    var w = 200, h = 46, n = vals.length;
    if (n < 2) return '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none"></svg>';
    var max = opts.max != null ? opts.max : Math.max.apply(null, vals.concat([1e-9]));
    if (max <= 0) max = 1;
    var col = opts.color || "var(--accent, #4a9eff)";
    var step = w / (PERF_N - 1), x0 = w - step * (n - 1), pts = [];
    for (var i = 0; i < n; i++) {
      var x = x0 + step * i, y = h - 2 - (h - 4) * Math.min(1, vals[i] / max);
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
    }
    var area = "M" + x0.toFixed(1) + "," + h + " L" + pts.join(" L") + " L" + w + "," + h + " Z";
    return '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" role="img" aria-label="' + esc(opts.label || "") + '">' +
      '<path d="' + area + '" fill="' + col + '" opacity="0.14"/>' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + col + '" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>';
  }
  function perfCard(title, value, sub, vals, opts) {
    return '<div class="perf-card"><div class="pt">' + esc(title) + '</div><div class="pv">' + esc(value) +
      '</div><div class="ps">' + esc(sub || "") + "</div>" + sparkSvg(vals, opts) + "</div>";
  }
  function recordSample(v) {
    var p = (v && v.process) || {}, sc = (v && v.scraping) || {};
    var now = Date.now() / 1000;
    var io = (p.io_read_bytes || 0) + (p.io_write_bytes || 0);
    var net = sc.bytes_total || 0;
    var diskRate = 0, netRate = 0;
    if (_lastSample) {
      var dt = Math.max(0.5, now - _lastSample.at);
      diskRate = Math.max(0, (io - _lastSample.io) / dt);
      netRate = Math.max(0, (net - _lastSample.net) / dt);
    }
    _lastSample = { at: now, io: io, net: net };
    if (p.cpu_percent != null) _push(_perf.cpu, p.cpu_percent);
    if (p.rss_bytes != null) { _memMax = Math.max(_memMax, p.rss_bytes); _push(_perf.memPct, p.rss_bytes); }
    _push(_perf.disk, diskRate);
    _push(_perf.net, netRate);
    return { diskRate: diskRate, netRate: netRate };
  }
  // A count and its noun as ONE keyed frame chosen by the count (click-through B19, Q6).
  function nounCount(n, one, many) { return tf(Number(n) === 1 ? one : many, { n: fmtNum(Number(n), 0) }); }
  function renderPerformance(v, rates) {
    var p = (v && v.process) || {}, sc = (v && v.scraping) || {};
    var cur = _perf.cpu.length ? _perf.cpu[_perf.cpu.length - 1] : null;
    var grid = '<div class="perf-grid">' +
      perfCard(t("CPU"), (p.cpu_percent == null ? "—" : fmtNum(p.cpu_percent, 1) + "%"),
               (p.cpu_cores ? nounCount(p.cpu_cores, "{n} core", "{n} cores") : "")
                 + (p.num_threads != null ? (p.cpu_cores ? " · " : "") + nounCount(p.num_threads, "{n} thread", "{n} threads") : ""),
               _perf.cpu, { max: 100, color: "var(--accent, #4a9eff)", label: t("CPU") }) +
      perfCard(t("Memory"), fmtBytes(p.rss_bytes),
               t("resident set size"), _perf.memPct, { max: _memMax, color: "var(--ok, #2ecc71)", label: t("Memory") }) +
      perfCard(t("Network ↓"), fmtRate(rates && rates.netRate),
               t("this app’s own fetches") + " · " + fmtBytes(sc.bytes_total) + " · " + fmtNum(sc.fetches_total || 0, 0) + "×",
               _perf.net, { color: "var(--warn, #d9a441)", label: t("Network ↓") }) +
      perfCard(t("Disk I/O"), fmtRate(rates && rates.diskRate),
               t("read + write"), _perf.disk, { color: "#b07be0", label: t("Disk I/O") }) +
      "</div>";
    var note = '<div class="vnote">' + esc(t("Measured from THIS process via the OS, plus the app’s own fetch bytes (it cannot attribute system-wide network to a process). Rates are diffed between samples.")) + "</div>";
    $("vitals-body").innerHTML = grid + note;
  }

  // ---- History — recent online sessions (completed collection passes) ---- //
  // Framed as "online sessions" (P2-12): each completed pass IS a session the app
  // ran while online; honest ok/error verdicts, no fabrication.
  async function renderHistory() {
    var el = $("hist-body");
    var d;
    try { d = await api("/api/jobs/history?limit=25"); } catch (e) { el.innerHTML = '<div class="muted">' + esc(t("Could not load history.")) + "</div>"; return; }
    var runs = (d && d.runs) || [];
    if (!runs.length) { el.innerHTML = '<div class="vsect">' + esc(t("Online sessions")) + "</div><div class=\"muted\" style=\"padding:4px 0\">" + esc(t("No completed sessions yet — each finished collection pass (a session while online) appears here with its result.")) + "</div>"; return; }
    var rows = runs.map(function (r) {
      var ok = r.ok !== false && !r.error;
      var res = r.result || {};
      var stored = res.articles_stored != null ? res.articles_stored : (res.tally && res.tally.stored) || 0;
      var when = r.finished_at || r.started_at;
      var dur = res.duration_s != null ? fmtDur(res.duration_s) : "—";
      var pill = ok ? '<span class="pill ok">' + esc(t("ok")) + "</span>" : '<span class="pill err">' + esc(t("error")) + "</span>";
      // No mode segment: since Q1020 = a every run is the press lane and no run report
      // carries a mode, so reading one printed an empty "· ·" (2026-09-27 re-walk T-5).
      var detail = ok ? (fmtNum(stored, 0) + " " + esc(t("articles")) + " · " + dur)
                      : esc(String(r.error || t("failed")).slice(0, 160));
      return '<div class="job"><span>' + pill + '</span><span class="label">' + esc(fmtRel(when)) +
             ' <span class="muted" title="' + esc(fmtLocal(when)) + '" style="font-weight:400">' + esc(fmtLocal(when)) + "</span></span>" +
             '<div class="detail">' + detail + "</div></div>";
    }).join("");
    el.innerHTML = '<div class="vsect">' + esc(t("Online sessions")) + ' <span class="count">' + fmtNum(runs.length, 0) + "</span></div>" + rows;
  }

  // ---- the persistent summary strip ---- //
  function renderSummary(v, act, rates) {
    var p = (v && v.process) || {};
    var offline = act && act.online === false;
    // Keep the status-bar airplane control in sync with the real network state.
    _tmOnline = act ? (act.online !== false) : null; paintAir();
    var active = act && act.active;
    var nJobs = _jobs ? (_jobs.jobs || []).filter(function (j) { return j.state === "running"; }).length : 0;
    var stateCls, stateTxt;
    if (offline) { stateCls = "off"; stateTxt = t("Airplane mode"); }
    else if (active) { stateCls = "on"; stateTxt = t("Online · collecting"); }
    else if (act && act.running) { stateCls = "idle"; stateTxt = t("Online · idle"); }
    else { stateCls = "idle"; stateTxt = t("Idle"); }
    function metric(label, val) {
      return '<span class="tm-metric"><b>' + esc(val) + '</b><span class="ml">' + esc(label) + "</span></span>";
    }
    $("tm-summary").innerHTML =
      '<span class="tm-state ' + stateCls + '"><span class="tm-dot"></span>' + esc(stateTxt) + "</span>" +
      metric(t("CPU"), p.cpu_percent == null ? "—" : fmtNum(p.cpu_percent, 1) + "%") +
      metric(t("Memory"), fmtBytes(p.rss_bytes)) +
      metric(t("Network ↓"), fmtRate(rates && rates.netRate)) +
      metric(t("active"), fmtNum(nJobs, 0));
  }
  // The tab row sticks right under the strip (the .tm-tabs rule reads --tm-sum-h). The
  // strip's height is not a constant -- it wraps at phone width and when a language's
  // labels run long -- so it is measured, and re-measured whenever it changes size.
  (function stickTabsUnderSummary() {
    var sum = $("tm-summary"); if (!sum) return;
    var set = function () {
      document.documentElement.style.setProperty("--tm-sum-h", Math.ceil(sum.getBoundingClientRect().height) + "px");
    };
    set();
    if (window.ResizeObserver) new ResizeObserver(set).observe(sum);
    else window.addEventListener("resize", set);
  })();

  // ---- controls (POST the same endpoints the in-app window used) ---- //
  window.TM = {
    cancel: async function (id) {
      try { var r = await api("/api/jobs/" + encodeURIComponent(id) + "/cancel", { method: "POST" }); toast(r.detail ? t(r.detail) : t("Cancelled.")); }
      catch (e) { toast(e.message, "err"); }
    },
    // A download's resume RE-OPENS A FETCH, so it passes the app's ONE consent popup first
    // (invariant #14), exactly as the in-app window's jobResume does. That popup lives in
    // the app, so offline -- or when the state cannot be read -- this page hands the
    // resume over as "/?resume=<id>", the way its airplane button hands over going online,
    // and posts nothing itself. Online, the POST goes straight through as before. A LOCAL
    // job (`local`: re-index, keyword fold, search re-index) opens no connection and asks
    // nothing.
    resume: async function (id, local) {
      if (!local) {
        var online = null;
        try { online = (await api("/api/system/network")).online === true; } catch (e) { online = null; }
        if (online !== true) { location.href = "/?resume=" + encodeURIComponent(id); return; }
      }
      try { var r = await api("/api/jobs/" + encodeURIComponent(id) + "/resume", { method: "POST" }); toast(r.detail ? t(r.detail) : t("Resumed.")); }
      catch (e) { toast(e.message, "err"); }
    },
    move: async function (key, dir, kind) {
      var jobs = (_jobs && _jobs.jobs) || [];
      var qJobs = jobs.filter(function (j) { return j.state === "queued" && j.kind === kind; })
                      .sort(function (a, b) { return (a.queue_position || 0) - (b.queue_position || 0); });
      var q = qJobs.map(dlKey);
      var i = q.indexOf(key);
      if (i < 0 || i + dir < 0 || i + dir >= q.length) return;
      var tmp = q[i]; q[i] = q[i + dir]; q[i + dir] = tmp;
      // OPTIMISTIC: renumber the cached jobs + repaint NOW so the row visibly moves
      // immediately (the backend POST + next refresh reconcile it).
      q.forEach(function (k, idx) {
        for (var n = 0; n < qJobs.length; n++) { if (dlKey(qJobs[n]) === k) { qJobs[n].queue_position = idx + 1; break; } }
      });
      if (_jobs) { renderProcesses(_jobs, window._act); renderQueue(_jobs, window._act); }
      try { await api(reorderEp(kind), { method: "POST", body: JSON.stringify({ keys: q }) }); refresh(); }
      catch (e) { toast(e.message, "err"); refresh(); }
    }
  };
  // The job rows' controls carry data-tm="cancel|resume|move" (they were
  // inline TM.…(…) click handlers; Q1127 = a). One delegated listener runs them.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-tm]");
    if (!b) return;
    var act = b.getAttribute("data-tm"), id = b.getAttribute("data-id");
    if (act === "cancel") window.TM.cancel(id);
    else if (act === "resume") window.TM.resume(id, b.getAttribute("data-local") === "1");
    else if (act === "move") window.TM.move(b.getAttribute("data-key"), Number(b.getAttribute("data-dir")), b.getAttribute("data-kind"));
  });

  // ---- tabs ---- //
  var PANELS = ["processes", "performance", "queue", "schedule", "history"];
  var _panel = "processes";
  function selectPanel(name) {
    _panel = name;
    PANELS.forEach(function (n) { var p = $("p-" + n); if (p) p.hidden = n !== name; });
    Array.prototype.forEach.call($("tm-tabs").children, function (b) {
      var on = b.getAttribute("data-panel") === name;
      b.classList.toggle("active", on); b.setAttribute("aria-selected", on ? "true" : "false");
    });
    if (name === "history") renderHistory();
  }
  Array.prototype.forEach.call($("tm-tabs").children, function (b) {
    b.addEventListener("click", function () { selectPanel(b.getAttribute("data-panel")); });
  });

  // ---- adaptive refresh: fast while something is live, slow when idle ---- //
  var _busy = false;
  // The last vitals + rates painted, so a language switch repaints from them (below).
  var _lastVitals = null, _lastRates = null, _painted = false;
  async function refresh() {
    if (_busy) return; _busy = true;
    var live = false, jobs = null, act = window._act || null, v = null;
    try { jobs = await api("/api/jobs"); live = (jobs.jobs || []).some(function (j) { return j.state === "running"; }); } catch (e) { /* transient */ }
    try { act = await api("/api/scheduler/activity"); window._act = act; live = live || !!act.active; } catch (e) { /* keep last */ }
    try { v = await api("/api/system/vitals"); } catch (e) { /* keep last */ }
    var rates = recordSample(v);
    _lastVitals = v; _lastRates = rates; _painted = true;
    if (jobs) { renderProcesses(jobs, act); renderQueue(jobs, act); }
    renderSchedule(act);
    renderPerformance(v, rates);
    renderSummary(v, act, rates);
    if (_panel === "history") renderHistory();
    var c = $("tm-conn"); if (c && !/err/.test(c.className)) c.textContent = t("Live");
    _busy = false;
    return live;
  }
  function loop() {
    refresh().then(function (live) {
      setTimeout(loop, document.hidden ? 15000 : (live ? 2500 : 6000));
    });
  }

  // ---- status bar: IDENTICAL to the app's top bar (maintainer 2026-06-20) ---- //
  // The 12 UI locales as [code, flag, native] — native name is the identifier
  // (invariant #15), the flag a visual cue. A flag button + popup menu mirrors the
  // app's #lang-switch; picking one calls OOI18N.setLang (the i18n engine translates).
  var TM_LANGS = [
    ["en", "🇬🇧", "English"], ["fr", "🇫🇷", "Français"], ["es", "🇪🇸", "Español"], ["de", "🇩🇪", "Deutsch"],
    ["zh", "🇨🇳", "中文"], ["hi", "🇮🇳", "हिन्दी"], ["ar", "🇸🇦", "العربية"], ["bn", "🇧🇩", "বাংলা"],
    ["ru", "🇷🇺", "Русский"], ["pt", "🇵🇹", "Português"], ["id", "🇮🇩", "Bahasa Indonesia"], ["ja", "🇯🇵", "日本語"]
  ];
  function _langCur() { try { return (window.OOI18N && OOI18N.current && OOI18N.current()) || "en"; } catch (e) { return "en"; } }
  function _paintLangButton() {
    var row = TM_LANGS.filter(function (l) { return l[0] === _langCur(); })[0] || TM_LANGS[0];
    var f = $("lang-flag"), k = $("lang-code");
    if (f) f.textContent = row[1];
    if (k) k.textContent = row[0].toUpperCase();
  }
  function toggleLangMenu(ev) {
    ev.stopPropagation();
    var menu = $("lang-menu"); if (!menu) return;
    if (!menu.hidden) { menu.hidden = true; return; }
    var cur = _langCur();
    menu.innerHTML = TM_LANGS.map(function (l) {
      var on = l[0] === cur;
      return '<div role="menuitem" tabindex="0" data-lang="' + l[0] + '"' +
        ' style="display:flex;align-items:center;gap:9px;padding:7px 12px;border-radius:7px;cursor:pointer' + (on ? ";font-weight:700" : "") + '"' +
        ">" +
        '<span aria-hidden="true">' + l[1] + "</span><span>" + esc(l[2]) + "</span>" +
        (on ? '<span style="margin-inline-start:auto">✓</span>' : "") + "</div>";
    }).join("");
    Array.prototype.forEach.call(menu.children, function (d) {
      d.addEventListener("click", function () { pickLang(d.getAttribute("data-lang")); });
    });
    var r = $("lang-switch").getBoundingClientRect(), rtl = document.documentElement.dir === "rtl";
    menu.style.top = (r.bottom + 6) + "px";
    menu.style.left = rtl ? r.left + "px" : "";
    menu.style.right = rtl ? "" : (window.innerWidth - r.right) + "px";
    menu.hidden = false;
    var closer = function (e) { if (!menu.contains(e.target)) { menu.hidden = true; document.removeEventListener("click", closer, true); } };
    document.addEventListener("click", closer, true);
  }
  async function pickLang(code) {
    var menu = $("lang-menu"); if (menu) menu.hidden = true;
    try { if (window.OOI18N && OOI18N.setLang) await OOI18N.setLang(code); } catch (e) {}
    _paintLangButton();
  }
  // A language picked in ANOTHER tab -- the app's own menu, usually, since this page is
  // opened beside it -- reaches this one through the `storage` event, which fires only in
  // the origin's OTHER tabs. Without it this page kept the language it opened with until
  // a reload. Compared with the page's own <html lang>, not with OOI18N.current(): that
  // reads the same shared key, which already holds the new value when the event lands.
  window.addEventListener("storage", function (e) {
    if (e.key === "oo.ui") { applyAppLook(); return; }   // a theme picked in the app (T-8)
    if (e.key !== "oo.lang" || !e.newValue || e.newValue === document.documentElement.lang) return;
    pickLang(e.newValue);
  });
  (function wireChrome() {
    var ls = $("lang-switch"); if (ls) ls.addEventListener("click", toggleLangMenu);
    var o = $("tm-omni");      // the search bar routes to the app (search/palette live there)
    if (o) {
      var go = function () { location.href = "/"; };
      o.addEventListener("click", go);
      o.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    }
    _paintLangButton();
  })();
  // Airplane: ENGAGING airplane is the safe direction (no consent) and can happen
  // from anywhere; GOING ONLINE crosses the network and must pass the ONE consent
  // popup, which lives in the app — so when offline the button routes back to "/".
  // State repainted by renderSummary from /api/scheduler/activity; the plane glyph
  // FILLS when offline (invariant #14), exactly like the app.
  var _tmOnline = null;
  // AI-install egress window, mirrored from the app. This page is a first-class
  // surface an operator sits on WHILE a long install runs, so it must not be a
  // screen where their own network exposure is invisible -- and the plain offline
  // hover below is simply FALSE while a window is open. Every string here is one
  // the app already keys, so this costs no new translation.
  var _tmEgress = null;
  function paintAir() {
    var b = $("net-toggle"), plane = $("net-plane"); if (!b) return;
    var egressOpen = !!(_tmEgress && _tmEgress.open);
    if (_tmOnline === false) {
      if (plane) plane.setAttribute("fill", "currentColor");
      b.style.color = "var(--err)";
      b.title = egressOpen
        ? t("Offline (airplane mode), except the AI install you allowed — collection stays stopped. Click to go fully online.")
        : t("Offline (airplane mode) — click to go online in the app; you'll be asked to confirm first.");
    } else {
      if (plane) plane.setAttribute("fill", "none");
      b.style.color = "";
      // Q1126 = a (S04-13 S5). Was "stops all collection.", which is TRUE and
      // WEAKER than what the switch actually does: the kill switch refuses every
      // new network request process-wide, not only the collector's. The main UI has
      // carried the stronger claim at app-core.js:652 for as long as both have
      // existed, so two surfaces described one mechanism differently and the
      // task manager's version under-promised the operator's own protection.
      // Aligned to the same KEY, which is already translated in all twelve locales.
      //
      // No third state is needed HERE, unlike the offline branch above: the
      // AI-install egress window only exists while the kill switch is ENGAGED, so
      // the online title can never be painted while that exemption is open.
      b.title = t("Online — click to go offline (airplane mode); every new network request will be refused.");
    }
  }
  // The airplane hover is PAINTED, not markup, so the i18n DOM walker cannot reach
  // it: `t()` is evaluated once, at paint time, and the result is an attribute value
  // that no longer matches a key. On first load that is already correct (a French
  // session paints French -- Chromium-verified), but a LIVE language switch left the
  // title frozen in whatever locale the tab opened with.
  //
  // The app has always handled this for its own copy of the same button
  // (app-core.js re-calls _paintNetwork from an `oo:langchange` listener, with the
  // reason written above it); this page simply never registered. That is the
  // recorded frozen-locale class on a render-once surface, and the recorded remedy
  // is a listener rather than memory -- so here it is. Found while verifying
  // Q1126 = a in a browser, on the string that ruling is about; it changes no copy
  // and adds no key, and it is what makes "re-translated x12" true on BOTH paths.
  //
  // The same listener repaints the rest of the page's painted text from what it already
  // holds -- never a fetch. The summary strip, the panels and the health pill are built
  // with t() at paint time too, so after ar -> zh they stayed Arabic until the next poll
  // (2.3 s measured, up to 15 s; click-through T5). The <title> is re-walked here as well:
  // setLang's own apply() starts at document.body, so without this the tab title kept
  // the language the page opened in (O4).
  document.addEventListener("oo:langchange", function () {
    paintAir();
    try { if (window.OOI18N && OOI18N.apply) OOI18N.apply(document.head); } catch (e) { /* title only */ }
    repaintFromCache();
  });
  function repaintFromCache() {
    if (_painted) {
      var act = window._act || null;
      if (_jobs) { renderProcesses(_jobs, act); renderQueue(_jobs, act); }
      renderSchedule(act);
      renderPerformance(_lastVitals, _lastRates);
      renderSummary(_lastVitals, act, _lastRates);
      var c = $("tm-conn"); if (c && !/err/.test(c.className)) c.textContent = t("Live");
    }
    paintHealth();
  }
  // Same direction-aware flash + toast as the app (maintainer 2026-06-21: the
  // airplane button must give identical visual feedback everywhere). #net-flash +
  // its .go-on/.go-off keyframes live in the shared app.css.
  function flashNet(online) {
    var f = document.getElementById("net-flash");
    if (!f) { f = document.createElement("div"); f.id = "net-flash"; document.body.appendChild(f); }
    f.classList.remove("go-on", "go-off"); void f.offsetWidth;  // restart the animation
    f.classList.add(online ? "go-on" : "go-off");
  }
  (function wireAir() {
    var b = $("net-toggle"); if (!b) return;
    b.addEventListener("click", async function () {
      if (_tmOnline === false) { location.href = "/"; return; }   // go online → the app's consent popup
      try {
        await api("/api/system/network", { method: "POST", body: JSON.stringify({ online: false }) });
        _tmOnline = false; paintAir(); flashNet(false);
        toast(t("Offline — every new network request is refused. One in-flight request may finish."), "err");
        refresh();
      }
      catch (e) { toast(e.message, "err"); }
    });
  })();
  // The health + AI pills mirror the app's (the AI pill reads just "AI", no model
  // count, per B4 2026-07-24; both route into the app on click — the full
  // start-or-install logic lives there, this standalone page just links back).
  // The pill paints from the last READING, so a language switch can repaint it without
  // asking the backend again (T5). Null until the first answer: "checking…" stays.
  var _healthState = null;   // "healthy" | "degraded" | "offline"
  function paintHealth() {
    var el = $("health"); if (!el || !_healthState) return;
    var label = _healthState === "healthy" ? t("healthy")
      : _healthState === "degraded" ? t("degraded") : t("offline");
    // The dot carries the state's class, as the app's own pill does (app-core.js
    // _paintHealth: dot ok / dot err). Without one, app.css's bare .dot is --muted, so
    // the dot was grey beside "healthy" and beside "offline" alike (2026-09-27 re-walk T-6).
    var cls = { healthy: "ok", degraded: "warn", offline: "err" }[_healthState] || "";
    el.innerHTML = '<span class="dot ' + cls + '"></span> ' + esc(label);
  }
  async function loadHealth() {
    var el = $("health"); if (!el) return;
    try { var h = await api("/api/health"); var ok = h && (h.status === "healthy" || h.status === "ok" || h.ok === true || h.healthy === true);  // /api/health answers status "healthy"
      _healthState = ok ? "healthy" : "degraded";
    } catch (e) { _healthState = "offline"; }
    paintHealth();
  }
  async function loadLlm() {
    var el = $("llm"); if (!el) return;
    el.style.cursor = "pointer"; el.onclick = function () { location.href = "/"; };
    try { var h = await api("/api/llm/health");
      el.className = (h && h.available) ? "pill ok" : "pill warn";
      el.textContent = "AI";
    } catch (e) { el.className = "pill"; el.textContent = "AI"; }
  }

  // Mirror the app's egress bar. Read-only: "Close now" lives in the app, so this
  // page states the exposure without duplicating the control. Rendered only on a
  // real change, because an aria-live region announces on every mutation and this
  // banner can be up for the length of a multi-GB download.
  var _tmEgressHtml = "";
  function paintEgress(st) {
    _tmEgress = st || null;
    var bar = $("egress-window-bar");
    paintAir();  // the offline hover is false while a window is open
    if (!bar) return;
    if (!(st && st.open)) { bar.hidden = true; bar.innerHTML = ""; _tmEgressHtml = ""; return; }
    // MEASURED collector state, never our own assumption; null means we could not
    // read it and we say so.
    var coll = st.collector_running;
    var collLine = coll === false
      ? t("Collection is stopped — no source is being contacted.")
      : coll === true
        ? t("Warning: the collector is running.")
        : t("The collector's state could not be read just now.");
    var html = '<span aria-hidden="true">⬤</span>' +
      '<span class="egress-msg"><b>' + esc(t("The AI install is allowed online.")) + '</b> ' +
      '<span class="egress-sub">' + esc(collLine) + ' ' +
      esc(t("Which hosts the installer contacts is not restricted, and it does not use your proxy or Tor.")) +
      '</span></span>';
    bar.hidden = false;
    if (_tmEgressHtml === html) return;
    _tmEgressHtml = html;
    bar.innerHTML = html;
  }
  async function loadEgress() {
    try { paintEgress(await api("/api/system/egress-window")); }
    catch (e) { /* transient: leave the bar as it is */ }
  }

  applyLang();
  _paintLangButton();
  loadHealth(); loadLlm(); loadEgress();
  setInterval(function () { loadHealth(); loadLlm(); loadEgress(); }, 15000);  // health/LLM/egress poll, low-frequency
  selectPanel("processes");
  loop();
})();
