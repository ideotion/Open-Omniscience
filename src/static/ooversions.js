/* Open Omniscience - Global Intelligence Platform for Investigative Journalism
   Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

   ooVersionReader -- the ONE version reader (Q918 + its note, brief S05-07 S1).

   Q918's note is a requirement: the law reader must be "homogenous with other parts of
   the app's ability to track change, such as wikipedia articles". So there is no law
   widget and no wiki widget. There is this one component, in the ooSubtabs precedent
   (invariant #18: one helper, many surfaces), and every reader of versioned text mounts
   it over a `base` whose `/versions` and `/compare` routes return the same payload
   (src/law/versions.py, src/wiki/versions.py):

     version selector (from / to)  ·  side-by-side comparison  ·  part navigation
     (a law's provisions, a page's sections)  ·  permalink  ·  identifier  ·  licence
     ·  translation provenance  ·  language switch  ·  the "≈ AI-derived · unreliable"
     summary  ·  the dating of every version  ·  the method and the caveat, VISIBLE

   A disclosure one kind has and the other does not is absent from the row list, never
   drawn empty, and the same code draws it for both -- which is the whole point.

   It is used in two different pages: the SPA (Living sources) and the standalone law
   reader page. So it is self-contained: its own styles (theme variables with fallbacks),
   plain fetch when the SPA's api() is not there, its own escaping. The root carries
   data-i18n-dyn and every word is written through t(), because the DOM walker would
   otherwise take a diff line of somebody else's text for a key; a language switch
   (`oo:langchange`) repaints from the payloads held, never a request.

   «Add to corpus» (R52) is drawn only where the payload carries `corpus_add` (a Wikipedia
   page's versions, src/wiki/versions.py): one button per end of the comparison, POSTing
   `${base}/versions/{id}/add-to-corpus`, the outcome in words with the article one click
   away. A law payload has no such key, so nothing is offered there.

   No inline handlers: one delegated listener per mount (the CSP ratchet, row I). */
(function () {
  "use strict";

  const CSS = `
.ov{font:13px/1.5 system-ui,sans-serif}
.ov-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin:0 0 8px}
.ov-head b{font-size:14px}
.ov-pick{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:0 0 8px}
.ov-pick label{display:flex;flex-direction:column;gap:2px;font-size:12px;color:var(--muted,var(--mut,#888))}
.ov-pick select{max-width:340px}
.ov-end{display:flex;gap:6px;flex-wrap:wrap;align-items:flex-end;min-width:0}
.ov-added{margin:0 0 8px}
.ov-facts{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;margin:6px 0 10px;padding:8px 10px;border:1px solid var(--border,var(--line,#8884));border-radius:8px}
.ov-facts dt{color:var(--muted,var(--mut,#888))}
.ov-facts dd{margin:0;overflow-wrap:anywhere}
.ov-muted{color:var(--muted,var(--mut,#888))}
.ov-langs{display:flex;gap:6px;flex-wrap:wrap}
.ov-lang{border:1px solid var(--border,var(--line,#8884));border-radius:999px;padding:0 8px;background:none;color:inherit;cursor:pointer;font:inherit}
.ov-lang[aria-current="true"]{font-weight:700;border-color:var(--accent,#5ea0ff)}
.ov-ai{border-inline-start:3px solid var(--caveat,#c98a1b);padding:4px 10px;margin:0 0 10px}
.ov-ai-label{font-weight:600;color:var(--caveat,#c98a1b)}
.ov-parts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0 0 8px}
.ov-part{border:1px solid var(--border,var(--line,#8884));border-radius:6px;padding:0 6px;background:none;color:inherit;cursor:pointer;font:12px system-ui,sans-serif}
.ov-part[aria-pressed="true"]{border-color:var(--accent,#5ea0ff);font-weight:700}
.ov-part.changed{border-inline-start:3px solid var(--caveat,#c98a1b)}
.ov-part.added{border-inline-start:3px solid var(--ok,var(--add,#2ea043))}
.ov-part.removed{border-inline-start:3px solid var(--err,var(--del,#f85149))}
.ov-part.unchanged{opacity:.7}
.ov-grid{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--border,var(--line,#8884));border-radius:8px;overflow:auto;max-height:70vh}
.ov-grid>div{padding:1px 8px;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;unicode-bidi:plaintext;border-top:1px solid transparent}
.ov-grid .ov-h{position:sticky;top:0;background:var(--panel,var(--card,#141923));font:600 12px system-ui,sans-serif;border-bottom:1px solid var(--border,var(--line,#8884))}
.ov-grid .ov-n{color:var(--muted,var(--mut,#888));user-select:none;display:inline-block;min-width:2em;margin:0 .5em;font-variant-numeric:tabular-nums}
.ov-grid .del,.ov-grid .chg-l{background:color-mix(in srgb,var(--err,var(--del,#f85149)) 16%,transparent)}
.ov-grid .ins,.ov-grid .chg-r{background:color-mix(in srgb,var(--ok,var(--add,#2ea043)) 16%,transparent)}
.ov-grid .skip{grid-column:1/3;text-align:center;color:var(--muted,var(--mut,#888));font-family:system-ui,sans-serif}
.ov-grid .gap{background:color-mix(in srgb,var(--muted,#888) 6%,transparent)}
.ov-caveat{margin:8px 0 2px}
.ov-method{font-size:12px;margin:2px 0 0}
`;

  function _t() { return (window.OOI18N && window.OOI18N.t) ? window.OOI18N.t : ((s) => s); }
  function _tf() {
    return (window.OOI18N && window.OOI18N.tf) ? window.OOI18N.tf
      : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => (v[k] == null ? "" : v[k])));
  }
  function _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function _safeHref(u) { return /^https?:\/\//i.test(String(u || "")) || /^\/api\//.test(String(u || "")) ? String(u) : ""; }
  // A refusal throws an Error whose `detail` is the server's own (a named refusal such
  // as "not-held"), the same shape the SPA's api() throws.
  async function _fetchJson(url, init) {
    const r = await fetch(url, Object.assign({ headers: { Accept: "application/json" } }, init || {}));
    if (!r.ok) {
      let detail = r.status + "";
      try { const j = await r.json(); if (j && j.detail) detail = String(j.detail); } catch (_) { /* keep the status */ }
      const err = new Error(detail);
      err.detail = detail;
      throw err;
    }
    return r.json();
  }
  async function _get(url) {
    if (typeof window.api === "function") return window.api(url);
    return _fetchJson(url);
  }
  async function _post(url) {
    if (typeof window.api === "function") return window.api(url, { method: "POST" });
    return _fetchJson(url, { method: "POST" });
  }
  // "Could not load: <reason>" with the reader's own separator when the SPA provides it
  // (ooLabelText: the zh and ja colon is full-width), a plain one on the standalone page.
  function _fail(t, msg) {
    return typeof window.ooLabelText === "function" ? window.ooLabelText(t("Could not load"), msg) : t("Could not load") + ": " + msg;
  }
  function _style() {
    if (document.getElementById("ov-style")) return;
    const el = document.createElement("style");
    el.id = "ov-style";
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  //: The dating words, one per member of the closed vocabulary (src/law/versions.py
  //: DATINGS). A value outside it reads as "unrecorded", never as a stated date.
  function datingWords(v, t) {
    const words = {
      official: "as the document states it",
      observed: "dated by observation — this instance saw the text on this day; the source stated no date of its own",
      edit: "the edit's own timestamp, as the source records it",
      unrecorded: "recorded before this app tracked how the date was determined",
    };
    let out = t(words[v.dating] || words.unrecorded);
    if (v.partial) out += " · " + t("the source states only part of this date");
    return out;
  }

  //: What «Add to corpus» answered, in words (src/wiki/corpus.py:add_wiki_version_article).
  const ADD_SAID = {
    created: "Added to your corpus as its own article.",
    exists: "This version is already in your corpus.",
    same_text: "Your corpus already holds an article with exactly these words.",
    "skipped-empty-after-strip": "Nothing to add: no text is left once the wiki markup is removed.",
  };
  //: The add route's named refusals, in words; any other is the server's own message.
  const ADD_REFUSED = {
    "not-held": "This version is no longer held on this machine.",
    "text-not-held": "This version's text was not stored on this machine, so it cannot be added.",
  };

  function versionOption(v, t, tf) {
    const when = v.valid_from || "—";
    let s = when + " · " + t(v.label || "a revision");
    if (v.delta_bytes != null) s += " · " + tf("{n} bytes", { n: (v.delta_bytes > 0 ? "+" : "") + v.delta_bytes });
    if (!v.has_text) s += " · " + t("text not stored");
    return s;
  }

  function span(v, t, tf) {
    if (!v) return "";
    return v.valid_to
      ? tf("from {from} until {until}", { from: v.valid_from || "—", until: v.valid_to })
      : tf("from {from} (the newest held)", { from: v.valid_from || "—" });
  }

  function mount(host, base, opts) {
    if (!host) return null;
    _style();
    opts = opts || {};
    const st = { base, d: null, cmp: null, from: null, to: null, part: null, err: null, cmpErr: null, seq: 0,
      added: {}, addBusy: {}, addErr: {} };
    host.classList.add("ov");
    host.setAttribute("data-i18n-dyn", "");

    function byId(id) { return (st.d && st.d.versions || []).find((v) => String(v.id) === String(id)) || null; }

    function paintFacts(t, tf) {
      const d = st.d, to = byId(st.to);
      const rows = [];
      const row = (label, html) => rows.push(`<dt>${_esc(t(label))}</dt><dd>${html}</dd>`);
      if (to) row("Showing", `${_esc(span(to, t, tf))} <span class="ov-muted">(${_esc(datingWords(to, t))})</span>`);
      if (to && to.local_url) row("Permalink", `<a href="${_esc(_safeHref(to.local_url))}">${_esc(location.origin + to.local_url)}</a>`);
      if (to && to.external_url) row("Revision at the source", `<a class="ext" href="${_esc(_safeHref(to.external_url))}" target="_blank" rel="noopener noreferrer">${_esc(to.external_url)}</a>`);
      if (d.kind === "law") {
        const id = d.identifier;
        row("Identifier", id
          ? `${_esc(id.scheme)}: ${_esc(id.value)}` + (id.url
            ? ` · <a class="ext" href="${_esc(_safeHref(id.url))}" target="_blank" rel="noopener noreferrer">${_esc(id.url)}</a>`
            : ` <span class="ov-muted">(${_esc(t("no ELI or CELEX permalink for this identifier"))})</span>`)
          : `<span class="ov-muted">${_esc(t("not recorded yet — written on the next tracking pass"))}</span>`);
      }
      const lic = d.licence;
      row("Licence", lic
        ? (lic.url ? `<a class="ext" href="${_esc(_safeHref(lic.url))}" target="_blank" rel="noopener noreferrer">${_esc(t(lic.name))}</a>` : _esc(t(lic.name)))
        : `<span class="ov-muted">${_esc(t("Licence not recorded"))}</span>`);
      if (d.provenance) row("Provenance", _esc(t(d.provenance.phrase)) + (d.provenance.body ? ` <span class="ov-muted">(${_esc(d.provenance.body)})</span>` : ""));
      const langs = d.languages || [];
      if (langs.length > 1) {
        row("Language", `<span class="ov-langs">${langs.map((l) => l.id == null
          ? `<span class="ov-lang ov-muted" title="${_esc(t("This language version is not tracked on this machine."))}">${_esc(l.language)}</span>`
          : `<button type="button" class="ov-lang" data-ov-lang="${Number(l.id)}" aria-current="${l.current ? "true" : "false"}">${_esc(l.language)}</button>`).join("")}</span>`);
      }
      return `<dl class="ov-facts">${rows.join("")}</dl>`;
    }

    function paintAi(t) {
      const to = byId(st.to);
      if (!to || !to.summary) return "";  // absent, never an empty ≈ box (Q920)
      return `<div class="ov-ai"><span class="ov-ai-label">${_esc(t(to.summary.label))}</span> `
        + `“${_esc(to.summary.text)}” <span class="ov-muted">— ${_esc(to.summary.model)}</span></div>`;
    }

    function paintParts(t, tf) {
      const c = st.cmp;
      if (!c || c.method === "text-not-held") return "";
      if (!c.parts) return c.parts_reason ? `<p class="ov-muted">${_esc(t(c.parts_reason))}</p>` : "";
      const name = st.d.parts_name === "provisions" ? "Provisions" : "Sections";
      const counts = {};
      c.parts.forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });
      const summary = tf("{changed} changed · {added} added · {removed} removed · {unchanged} unchanged",
        { changed: counts.changed || 0, added: counts.added || 0, removed: counts.removed || 0, unchanged: counts.unchanged || 0 });
      return `<div class="ov-parts"><b>${_esc(t(name))}</b> <span class="ov-muted">${_esc(summary)}</span>`
        + `<button type="button" class="ov-part" data-ov-part="" aria-pressed="${st.part ? "false" : "true"}">${_esc(t("Whole text"))}</button>`
        + c.parts.map((p) => `<button type="button" class="ov-part ${_esc(p.status)}" data-ov-part="${_esc(p.address)}" aria-pressed="${st.part === p.address ? "true" : "false"}" title="${_esc(t(p.status))}">${_esc(p.label)}</button>`).join("")
        + `</div>`;
    }

    function paintGrid(t, tf) {
      if (st.cmpErr) return `<p class="ov-muted">${_esc(_fail(t, st.cmpErr))}</p>`;
      const c = st.cmp;
      if (!c) return `<p class="ov-muted">${_esc(t("Loading…"))}</p>`;
      if (c.method === "text-not-held") {
        return `<p class="ov-muted">${_esc(t("The text of this version was not stored, so it cannot be compared. It stays in the list so the history keeps every version."))}</p>`;
      }
      if (c.method === "too-large") return `<p class="ov-muted">${_esc(t("These texts are too large to compare on this machine; the comparison was not computed rather than approximated."))}</p>`;
      const a = byId(st.from), b = byId(st.to);
      const head = `<div class="ov-h">${_esc(t("From"))} · ${_esc(a ? a.valid_from || "—" : "—")}</div><div class="ov-h">${_esc(t("To"))} · ${_esc(b ? b.valid_from || "—" : "—")}</div>`;
      const cell = (cls, n, text) => `<div class="${cls}"><span class="ov-n">${n == null ? "" : n}</span>${_esc(text == null ? "" : text)}</div>`;
      const body = (c.rows || []).map((r) => {
        if (r.op === "skip") return `<div class="skip">${_esc(tf("{n} unchanged lines", { n: r.n }))}</div>`;
        if (r.op === "eq") return cell("", r.ln, r.l) + cell("", r.rn, r.r);
        if (r.op === "chg") return cell("chg-l", r.ln, r.l) + cell("chg-r", r.rn, r.r);
        if (r.op === "del") return cell("del", r.ln, r.l) + cell("gap", null, "");
        return cell("gap", null, "") + cell("ins", r.rn, r.r);
      }).join("");
      const tally = c.method === "identical"
        ? t("The two versions are identical.")
        : tf("Lines changed: {changed} · added: {added} · removed: {removed}", { changed: c.changed, added: c.added, removed: c.removed });
      const cut = c.truncated ? ` · ${_esc(tf("{n} more rows not shown", { n: c.omitted_rows }))}` : "";
      return `<p class="ov-muted">${_esc(tally)}${cut}</p><div class="ov-grid" role="table">${head}${body}</div>`;
    }

    // «Add to corpus» (R52) for ONE version: what the add answered, or what the payload
    // says the corpus already holds. Keyed by version id, so it survives a new pick and a
    // language switch (repainted from the result, never re-requested).
    function addDone(v) {
      if (!v) return null;
      if (st.added[v.id]) return st.added[v.id];
      const known = (st.d.corpus_add && st.d.corpus_add.articles) || {};
      return known[v.id] != null ? { status: "exists", article_id: known[v.id] } : null;
    }

    // Off while in flight, once the corpus holds the version, or when its text was never
    // stored; the hover then says why, as the line under the pickers does.
    function addButton(v, t) {
      if (!v || !st.d.corpus_add) return "";
      const done = addDone(v);
      const off = !v.has_text || done || st.addBusy[v.id];
      const why = !v.has_text ? t(ADD_REFUSED["text-not-held"])
        : (done && ADD_SAID[done.status]) ? t(ADD_SAID[done.status])
          : t("Adds this exact version to your corpus as its own article.");
      return `<button type="button" class="secondary tiny" data-ov-add="${_esc(String(v.id))}"${off ? " disabled" : ""} title="${_esc(why)}">${_esc(t("Add to corpus"))}</button>`;
    }

    // The outcome in words, the article one click away in the local reader (invariant #6).
    // `ends` pairs a label ("From", "To", or none for a page's only version) with a version.
    function addOutcomes(ends, t) {
      if (!st.d.corpus_add) return "";
      const seen = new Set();
      return ends.map(([label, v]) => {
        if (!v || seen.has(v.id)) return "";
        seen.add(v.id);
        const done = addDone(v), err = st.addErr[v.id];
        if (!done && !err) return "";
        let words;
        if (done) {
          words = _esc(ADD_SAID[done.status] ? t(ADD_SAID[done.status]) : String(done.status || ""));
          if (done.article_id != null) {
            words += ` <a href="/api/articles/${encodeURIComponent(done.article_id)}/view" target="_blank" rel="noopener">${_esc(t("Open it in the reader"))}</a>`;
          }
        } else {
          words = _esc(ADD_REFUSED[err.detail] ? t(ADD_REFUSED[err.detail]) : String(err.message || err));
        }
        return `<p class="ov-added${done ? "" : " ov-muted"}">${label ? `<b>${_esc(t(label))}</b> · ` : ""}${words}</p>`;
      }).join("");
    }

    async function addToCorpus(id) {
      const v = byId(id), base = st.base;
      if (!v || !v.has_text || addDone(v) || st.addBusy[v.id]) return;
      st.addBusy[v.id] = true;
      delete st.addErr[v.id];
      paint();
      try {
        const r = await _post(`${base}/versions/${encodeURIComponent(String(v.id))}/add-to-corpus`);
        if (base === st.base) st.added[v.id] = r;
      } catch (e) {
        if (base === st.base) st.addErr[v.id] = e;
      }
      if (base !== st.base) return;  // another page was opened meanwhile
      delete st.addBusy[v.id];
      paint();
    }

    function paint() {
      const t = _t(), tf = _tf();
      if (st.err) { host.innerHTML = `<p class="ov-muted">${_esc(_fail(t, st.err))}</p>`; return; }
      const d = st.d;
      if (!d) { host.innerHTML = `<p class="ov-muted">${_esc(t("Loading…"))}</p>`; return; }
      const versions = d.versions || [];
      const head = `<div class="ov-head"><b>${_esc(t("Versions"))}</b><span class="ov-muted">${_esc(tf("{n} of {total} versions listed, newest first", { n: versions.length, total: d.total }))}</span></div>`;
      if (versions.length < 2) {
        const only = versions[0];
        const add = addButton(only, t);
        host.innerHTML = head + `<p class="ov-muted">${_esc(t(versions.length
          ? "Only one version is held, so there is nothing to compare yet."
          : "No version is held yet."))}</p>`
          + (add ? `<div class="ov-pick">${add}</div>` + addOutcomes([[null, only]], t) : "")
          + (versions.length ? paintFacts(t, tf) : "")
          + `<p class="card-caveat ov-caveat">${_esc(t(d.caveat))}</p><p class="ov-muted ov-method">${_esc(t(d.method))}</p>`;
        return;
      }
      const opts2 = (sel) => versions.map((v) => `<option value="${_esc(String(v.id))}"${String(v.id) === String(sel) ? " selected" : ""}>${_esc(versionOption(v, t, tf))}</option>`).join("");
      const from = byId(st.from), to = byId(st.to);
      host.innerHTML = head
        + `<div class="ov-pick"><div class="ov-end"><label>${_esc(t("From"))}<select data-ov="from">${opts2(st.from)}</select></label>${addButton(from, t)}</div>`
        + `<div class="ov-end"><label>${_esc(t("To"))}<select data-ov="to">${opts2(st.to)}</select></label>${addButton(to, t)}</div>`
        + `<button type="button" class="secondary tiny" data-ov="swap" title="${_esc(t("Swap the two versions"))}">⇄</button></div>`
        + addOutcomes([["From", from], ["To", to]], t)
        + paintFacts(t, tf) + paintAi(t) + paintParts(t, tf) + paintGrid(t, tf)
        + `<p class="card-caveat ov-caveat">${_esc(t(d.caveat))}</p><p class="ov-muted ov-method">${_esc(t(d.method))}</p>`;
    }

    async function compare() {
      const seq = ++st.seq;
      st.cmp = null; st.cmpErr = null; paint();
      if (st.from == null || st.to == null) return;
      const q = `from=${encodeURIComponent(st.from)}&to=${encodeURIComponent(st.to)}` + (st.part ? `&part=${encodeURIComponent(st.part)}` : "");
      try {
        const c = await _get(`${st.base}/compare?${q}`);
        if (seq !== st.seq) return;  // a later pick won
        st.cmp = c;
      } catch (e) {
        if (seq !== st.seq) return;
        st.cmpErr = e && e.message ? e.message : String(e);
      }
      paint();
    }

    async function load(base) {
      if (base) st.base = base;
      st.added = {}; st.addBusy = {}; st.addErr = {};
      st.d = null; st.err = null; st.cmp = null; st.part = null; paint();
      try {
        st.d = await _get(`${st.base}/versions`);
      } catch (e) { st.err = e && e.message ? e.message : String(e); paint(); return; }
      // Default: the newest version against the one before it, both with text where
      // there are two such; the reader moves either end from there.
      const withText = st.d.versions.filter((v) => v.has_text);
      const pool = withText.length >= 2 ? withText : st.d.versions;
      st.to = pool[0] ? pool[0].id : null;
      st.from = pool[1] ? pool[1].id : null;
      // Ids are compared as strings: a law version's id is a number, a wiki version's
      // names its store ("t12", "l40"), and one comparison serves both.
      const pinned = opts.to != null ? byId(opts.to) : null;
      if (pinned) {
        st.to = pinned.id;
        const i = st.d.versions.findIndex((v) => v === pinned);
        const older = st.d.versions.slice(i + 1).find((v) => v.has_text) || st.d.versions[i + 1];
        if (older) st.from = older.id;
      }
      if (st.d.versions.length < 2) { paint(); return; }
      compare();
    }

    host.addEventListener("change", (e) => {
      const which = e.target && e.target.getAttribute && e.target.getAttribute("data-ov");
      if (which !== "from" && which !== "to") return;
      const picked = byId(e.target.value);
      if (!picked) return;
      st[which] = picked.id;
      st.part = null;
      compare();
    });
    host.addEventListener("click", (e) => {
      const el = e.target && e.target.closest ? e.target.closest("[data-ov],[data-ov-part],[data-ov-lang],[data-ov-add]") : null;
      if (!el || !host.contains(el)) return;
      if (el.hasAttribute("data-ov-add")) { addToCorpus(el.getAttribute("data-ov-add")); return; }
      if (el.getAttribute("data-ov") === "swap") {
        const f = st.from; st.from = st.to; st.to = f; st.part = null; compare(); return;
      }
      if (el.hasAttribute("data-ov-part")) { st.part = el.getAttribute("data-ov-part") || null; compare(); return; }
      if (el.hasAttribute("data-ov-lang")) {
        const id = Number(el.getAttribute("data-ov-lang"));
        if (typeof opts.onLanguage === "function") opts.onLanguage(id);
      }
    });
    document.addEventListener("oo:langchange", () => { if (host.isConnected) paint(); });

    load();
    return { load, repaint: paint, state: st };
  }

  window.ooVersionReader = mount;
  // The standalone reader page mounts itself from its own markup: no inline script.
  function autoMount() {
    document.querySelectorAll("[data-ov-base]").forEach((el) => {
      if (el._ovMounted) return;
      el._ovMounted = true;
      mount(el, el.getAttribute("data-ov-base"), {
        to: el.getAttribute("data-ov-to"),
        // Built from the numeric id alone, never from the attribute's text, so no
        // markup can steer the navigation off this machine's own law reader.
        onLanguage: (id) => {
          const n = Number(id);
          if (Number.isInteger(n) && n > 0) location.assign("/api/law/documents/" + n + "/view");
        },
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoMount);
  else autoMount();
})();
