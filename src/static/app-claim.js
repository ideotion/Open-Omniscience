/* app-claim.js — the Claim Workspace, slice 1 (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S1)

   The reader pastes a CLAIM and the app walks it through the local corpus in visible
   steps (the design of record: FUTURE_DEVELOPMENTS.md A1, the action plan's A-2):
     ① related articles, ② grouped by independence, ③ who said what, when,
     ④ corroboration offers (each naming its host and what the request reveals, fetched
     only behind the one online consent), ⑤ what's missing, ⑥ the trail exported as a
     ZIP signed with the custody key, and a bundle someone sent checked.

   A TRAIL, NEVER A VERDICT. Every step prints its method sentence on the page, not in a
   hover: the method IS the lesson. A path with nothing joining it is "no shared origin
   found", which is absence of evidence and is said so; nothing is scored, and no model
   writes any of it.

   ONE ENTRY POINT, OPENED BY AN EXPLICIT COMMAND (Q608 = a: Enter in the omnibar opens the
   analysis window, so the workspace is the omnibar's second row, never its first), plus the
   Search tab's "Check as a claim" button and the palette's page list. The tab is kept off
   the sidebar, like the analysis window.

   The renderers are pure (payload, t, tf) -> HTML so tests/claim_workspace_node_test.js
   drives them in node; only claimRun, claimWeather, claimExport, claimVerify and
   _claimWire touch the DOM or the network (loopback, except ④'s consented fetch).
*/
    let _claimLast = null;      // the last payload, so a language switch redraws without a fetch
    let _claimWired = false;
    let _claimSeq = 0;

    const _CLAIM_JOIN_LABELS = {
      same_source: (t) => t("Same source"),
      near_identical: (t) => t("Near-identical text"),
      shared_link: (t) => t("Cite the same page"),
      same_wire: (t) => t("Attribute the same news wire"),
    };

    function _claimT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _claimTf() {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf;
      return (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
    }

    // The article's reference in this trail: its position in step ①'s list. The same
    // number is used in every step, so "#3" in a path is "#3" in the timeline.
    function claimRef(pos) { return "#" + pos; }

    function _claimStep(num, title, method, body, extraCls) {
      return `<section class="claim-step${extraCls ? " " + extraCls : ""}">`
        + `<h3><span class="claim-num" aria-hidden="true">${num}</span> ${esc(title)}</h3>`
        + (method ? `<p class="claim-method">${esc(method)}</p>` : "")
        + body + `</section>`;
    }

    function _claimFacts(facts) {
      return `<div class="living-facts">` + facts.map((f) =>
        `<div class="living-fact"><div class="muted">${esc(f[0])}</div>`
        + `<div class="living-fact-v">${esc(String(f[1]))}</div></div>`).join("") + `</div>`;
    }

    function _claimArticleLink(a, t) {
      const title = a.title || t("(untitled)");
      return `<a href="/api/articles/${encodeURIComponent(a.id)}/view" target="_blank" rel="noopener">${esc(title)}</a>`;
    }

    function claimRelatedHtml(ws, t, tf) {
      const r = ws.related || {};
      const q = ws.query || {};
      let body = "";
      if (!q.text) {
        body += `<p class="hint">${esc(t("The claim has no words the index can search for. Type the words to search for in the box above."))}</p>`;
        return _claimStep("①", t("Related articles in your corpus"), null, body);
      }
      body += `<p class="claim-query"><span class="muted">${esc(q.derived ? t("Words searched, taken from the claim:") : t("Words searched, as you typed them:"))}</span> <code>${esc(q.text)}</code></p>`;
      if (ws.cross_language && typeof _omniCrossNote === "function") {
        const note = _omniCrossNote(ws.cross_language);
        if (note) body += `<p class="hint">${esc(note.replace(/^ · /, ""))}</p>`;
      }
      body += _claimFacts([
        [t("Articles matched"), r.at_index_cap ? tf("at least {n}", {n: r.total}) : r.total],
        [t("Read for this trail"), r.shown],
      ]);
      if (r.total > r.shown) {
        body += `<p class="hint">${esc(tf("The trail reads the {shown} best matches, in the index's relevance order. The other matches are not read; the Search tab lists them all.", {shown: r.shown}))}</p>`;
      }
      if (!(r.articles || []).length) {
        return _claimStep("①", t("Related articles in your corpus"),
          t("Full-text search over your corpus, with the Search tab's grammar and its cross-language expansion. With no words of your own, the claim's content words are joined with OR, so an article carrying more of them ranks higher. The list is a relevance ranking, not a sample."),
          body);
      }
      body += `<ol class="claim-list">` + r.articles.map((a) =>
        `<li value="${esc(a.position)}">${_claimArticleLink(a, t)}`
        + ` <span class="muted">${esc(a.source || "")}${a.published_at ? " · " + esc(String(a.published_at).slice(0, 10)) : ""}</span>`
        + (a.language ? " " + ooLangCell(a.language, {cls: "claim-pill"}) : "")
        + `</li>`).join("") + `</ol>`;
      return _claimStep("①", t("Related articles in your corpus"),
        t("Full-text search over your corpus, with the Search tab's grammar and its cross-language expansion. With no words of your own, the claim's content words are joined with OR, so an article carrying more of them ranks higher. The list is a relevance ranking, not a sample."),
        body);
    }

    function claimIndependenceHtml(ws, t, tf) {
      const ind = ws.independence || {};
      const posOf = {};
      ((ws.related || {}).articles || []).forEach((a) => { posOf[a.id] = a.position; });
      // In step ①'s order, so "#2 #3 #4" reads as the list it points back at.
      const refs = (ids) => ids.map((id) => posOf[id]).sort((a, b) => (a == null) - (b == null) || a - b)
        .map((pos) => claimRef(pos != null ? pos : "?")).join(" ");
      const method = t("Articles are joined into one path when they come from the same source, share near-identical text, cite the same outbound page, or attribute the same news wire. Echoes of one origin are one path, however many outlets carry them.");
      if (!ind.n_articles) {
        return _claimStep("②", t("Grouped by independence"), method,
          `<p class="hint">${esc(t("No related article, so there is nothing to group."))}</p>`);
      }
      let body = _claimFacts([
        [t("Paths"), ind.n_paths],
        [t("Paths joining several articles"), ind.n_joined_paths],
        [t("Articles with no shared origin found"), ind.n_unjoined],
        [t("Sources"), ind.n_sources],
      ]);
      body += `<p class="card-caveat">${esc(t("No shared origin found is absence of evidence, never proof of independence: two articles can share an origin that neither states. The wire attribution is read from the text and can be wrong."))}</p>`;
      const joined = (ind.paths || []).filter((p) => !p.unjoined);
      joined.forEach((p) => {
        body += `<div class="claim-path"><div class="claim-path-head"><b>${esc(tf("Path {n}", {n: p.path}))}</b>`
          + ` <span class="muted">${esc(ooLabelText(t("Articles"), String(p.n_articles)))} · ${esc(ooLabelText(t("Sources"), String(p.n_sources)))}</span>`
          + ` <span class="claim-refs">${esc(refs(p.article_ids))}</span></div>`
          + `<ul class="claim-joins">` + (p.joins || []).map((j) =>
            `<li><span class="claim-join-kind">${esc(_CLAIM_JOIN_LABELS[j.kind] ? _CLAIM_JOIN_LABELS[j.kind](t) : j.kind)}</span>`
            + (j.detail ? ` <span class="claim-join-detail">${esc(j.detail)}</span>` : "")
            + ` <span class="claim-refs">${esc(refs(j.article_ids))}</span></li>`).join("")
          + `</ul></div>`;
      });
      const lone = (ind.paths || []).filter((p) => p.unjoined);
      if (lone.length) {
        body += `<div class="claim-path"><div class="claim-path-head"><b>${esc(t("No shared origin found"))}</b>`
          + ` <span class="claim-refs">${esc(refs(lone.map((p) => p.article_ids[0])))}</span></div>`
          + `<p class="hint">${esc(t("Each of these is a path of its own because nothing we can measure joins it to another one."))}</p></div>`;
      }
      return _claimStep("②", t("Grouped by independence"), method, body);
    }

    function claimTimelineHtml(ws, t, tf) {
      const rows = ws.timeline || [];
      const method = t("The trail in publication order, with the sentence of each article that carries the most of the claim's words. The earliest article is the first one your corpus holds, not necessarily where the claim began.");
      if (!rows.length) {
        return _claimStep("③", t("Who said what, when"), method,
          `<p class="hint">${esc(t("No related article, so there is no timeline."))}</p>`);
      }
      const posOf = {};
      ((ws.related || {}).articles || []).forEach((a) => { posOf[a.id] = a.position; });
      let body = `<div class="claim-table-wrap"><table class="claim-timeline"><thead><tr>`
        + `<th>${esc(t("Date"))}</th><th>${esc(t("Source"))}</th><th>${esc(t("Path"))}</th><th>${esc(t("What it said"))}</th></tr></thead><tbody>`;
      rows.forEach((r) => {
        const badges = [];
        if (r.first_in_corpus) badges.push(`<span class="claim-badge">${esc(t("first in your corpus"))}</span>`);
        if (r.wire) badges.push(`<span class="claim-badge">${esc(tf("attributes {wire}", {wire: r.wire}))}</span>`);
        const said = r.said
          ? `<q class="claim-said">${esc(r.said)}</q>`
          : `<span class="muted">${esc(t("No sentence carries the claim's words; the title is shown."))}</span>`;
        body += `<tr><td class="claim-date">${r.published_at ? esc(String(r.published_at).slice(0, 10)) : esc(t("undated"))}</td>`
          + `<td>${esc(r.source || "?")}${r.country ? " " + ooCountryCell(r.country, {cls: "claim-pill"}) : ""}</td>`
          + `<td>${r.path != null ? esc(String(r.path)) : ""}</td>`
          + `<td><div>${esc(claimRef(posOf[r.id] != null ? posOf[r.id] : "?"))} ${_claimArticleLink(r, t)} ${badges.join(" ")}</div>${said}</td></tr>`;
      });
      body += `</tbody></table></div>`;
      return _claimStep("③", t("Who said what, when"), method, body);
    }

    function _claimSilentHtml(label, block, cell, t) {
      if (!block) return "";
      const items = block.items || [];
      if (!block.total) {
        return `<p><b>${esc(label)}</b> <span class="muted">${esc(t("none silent: every one your corpus holds speaks in this trail"))}</span></p>`;
      }
      return `<p><b>${esc(ooLabelText(label, String(block.total)))}</b> `
        + items.map((it) => `<span class="claim-silent">${cell(it.key)} <span class="muted">(${esc(String(it.corpus_sources))})</span></span>`).join(" ")
        + (block.total > items.length ? ` <span class="muted">…</span>` : "") + `</p>`;
    }

    const _CLAIM_DISCRIMINATORS = {
      no_related: (tf, v) => tf("No article in your corpus matches these words. Try other words for the claim, or collect sources that cover its subject, its region and its language.", v),
      one_path: (tf, v) => tf("Every article here joins into one path. A report that does not share its origin would be a second path.", v),
      no_primary_record: (tf, v) => tf("The trail holds no primary record, such as official statistics or a law text. The record a figure or a rule comes from would tell the claim apart better than more reporting.", v),
      one_language: (tf, v) => tf("The trail is in one language. Reporting in another language would show whether the claim travels beyond one press.", v),
      short_window: (tf, v) => tf("The trail's dated articles all fall within two days. Later reporting would show whether the claim held up or was corrected.", v),
      undated: (tf, v) => tf("Articles without a publication date: {n}. They sit at the end of the timeline.", v),
      figure_source: (tf, v) => tf("The claim states figures ({figures}). The dataset or document they come from would tell the claim apart better than reports repeating them.", v),
    };

    function claimMissingHtml(ws, t, tf) {
      const m = ws.missing || {};
      const method = t("What your corpus holds that this trail is silent on, counted over the sources your corpus has articles from, and the kinds of evidence that would tell the claim apart. Silence here is silence in your corpus, not in the world.");
      let body = `<h4>${esc(t("Silent in this trail"))}</h4>`;
      body += `<p class="hint">${esc(t("In brackets: how many of your corpus's sources that one covers."))}</p>`;
      body += _claimSilentHtml(t("Countries"), m.countries, (k) => ooCountryCell(k), t);
      body += _claimSilentHtml(t("Languages"), m.languages, (k) => ooLangCell(k), t);
      body += _claimSilentHtml(t("Source types"), m.source_types, (k) => esc(t(k)), t);
      const disc = m.would_discriminate || [];
      body += `<h4>${esc(t("What would tell the claim apart"))}</h4>`;
      if (!disc.length) {
        body += `<p class="hint">${esc(t("Nothing this workspace measures points at a gap. That is not a confirmation: it measures a few things only."))}</p>`;
      } else {
        body += `<ul class="claim-disc">` + disc.map((d) => {
          const frame = _CLAIM_DISCRIMINATORS[d.code];
          if (!frame) return "";
          const f = d.fact || {};
          const vars = {days: f.days, n: f.n, figures: ooListJoin(f.figures || [])};
          return `<li>${esc(frame(tf, vars))}</li>`;
        }).join("") + `</ul>`;
      }
      return _claimStep("⑤", t("What's missing"), method, body);
    }

    // ④ -- what the request would tell the host (A7, the metadata shadow). One sentence,
    // shown on the offer AND in the consent popup, so it is read before the click.
    function claimShadowText(op, tf) {
      // The coordinates, not only the place name: they are what the host is sent, and for a
      // country they are its stand-in city, which "near France" would hide.
      return tf("Asking {host} tells it this machine's IP address, the point {lat}, {lon} (for {place}) and the dates {start} to {end}: together, which place and period you are looking into.",
        {host: op.host, lat: op.lat, lon: op.lon, place: op.place || "?", start: op.window_start, end: op.window_end});
    }

    function claimCorroborationHtml(ws, t, tf) {
      const co = ws.corroboration || {};
      const offers = co.offers || [];
      const method = t("Independent data the trail's articles could be checked against. Today that is weather: when an article of the trail names a weather event such as a drought or a flood together with a place, the app offers the reanalysis for that place and those dates. Nothing is fetched until you ask, and each offer names the host it would ask and what the request tells it.");
      let body = "";
      if (!offers.length) {
        body += `<p class="hint">${esc(((ws.related || {}).shown)
          ? t("No offer: no article of this trail names a weather event together with a place.")
          : t("No related article, so there is nothing to check."))}</p>`;
      } else {
        const posOf = {};
        ((ws.related || {}).articles || []).forEach((a) => { posOf[a.id] = a.position; });
        offers.forEach((op, i) => {
          const refs = (op.article_ids || []).map((id) => claimRef(posOf[id] != null ? posOf[id] : "?")).join(" ");
          body += `<div class="claim-offer">`
            + `<div class="claim-path-head"><b>${esc(t(op.rule_label || op.rule))}</b> · ${esc(op.place || "?")}`
            + (op.place_country ? " " + ooCountryCell(op.place_country, {cls: "claim-pill"}) : "")
            + ` <span class="muted">${esc(tf("{start} to {end}", {start: op.window_start, end: op.window_end}))}</span>`
            + ` <span class="claim-refs">${esc(refs)}</span></div>`;
          const notes = [];
          if (op.window_narrowed) {
            notes.push(tf("The dates span more than the archive answers in one request, so the window is the latest 366 days. It covers {n} of the {total} articles.", {n: op.n_in_window, total: op.n_articles}));
          }
          if (op.geocode === "country") {
            notes.push(t("The article names no point for this place, so the point stands in for the country: its largest city in the gazetteer."));
          }
          notes.forEach((n) => { body += `<p class="hint">${esc(n)}</p>`; });
          body += `<p class="claim-shadow">${esc(claimShadowText(op, tf))}</p>`
            + `<p class="claim-request"><span class="muted">${esc(t("The exact request:"))}</span> <code>${esc(op.request_url)}</code></p>`
            + `<div class="claim-actions"><button type="button" class="secondary" data-claim-wx="${i}">`
            + esc(op.cached ? t("Show the slice held on this machine") : tf("Ask {host}", {host: op.host}))
            + `</button></div><div class="claim-wx" id="claim-wx-${i}"></div></div>`;
        });
        if (co.total > offers.length) {
          body += `<p class="hint">${esc(tf("{shown} of {total} offers are listed.", {shown: offers.length, total: co.total}))}</p>`;
        }
      }
      if (co.skipped_no_coords) {
        body += `<p class="hint">${esc(tf("Weather events named at a place with no known point: {n}. They get no offer.", {n: co.skipped_no_coords}))}</p>`;
      }
      body += `<p class="card-caveat">${esc(t("Weather is the only independent data wired so far: official statistics and climate reports are not checked here. A reanalysis is a model estimate for a grid cell, and a match is corroboration, never proof."))}</p>`;
      return _claimStep("④", t("Corroboration offers"), method, body);
    }

    function claimExportHtml(ws, t, tf) {
      const method = t("The trail is written as one ZIP: the trail as drawn here, each article with the SHA-256 of its text, the sources, the licence lines that apply, and what a reader of the file can learn from it. A signature by this install's custody key covers all of it, so anyone can check that nothing was changed.");
      const n = (ws.related || {}).shown || 0;
      if (!n) {
        return _claimStep("⑥", t("Export the trail, signed"), method,
          `<p class="hint">${esc(t("No related article, so there is no trail to export."))}</p>`);
      }
      const held = ((ws.corroboration || {}).offers || []).filter((o) => o.cached).length;
      const members = [
        ["README.md", t("what this is and how to verify it")],
        ["trail.json", t("the trail as drawn here")],
        ["articles/", n === 1 ? tf("{n} file", {n}) : tf("{n} files, one per article", {n})],
        ["sources.json", t("the sources those articles came from")],
      ];
      if (held) members.push(["corroboration/", held === 1 ? t("1 weather slice already held on this machine")
        : tf("{n} weather slices already held on this machine", {n: held})]);
      members.push(["ATTRIBUTION.md", t("the licence lines that apply")],
        ["WHAT-A-READER-CAN-SEE.md", t("what someone holding the file can learn")],
        ["manifest.json", t("every file's SHA-256")], ["SIGNATURE.json", t("the signature and the key that made it")]);
      const body = `<p class="card-caveat">${esc(t("Plaintext: the bundle is not encrypted. Anyone who has the file can read the claim, the trail and the articles' text."))}</p>`
        + `<p class="card-caveat">${esc(t("It is signed with this install's custody key. That proves this install made it, and the same key on every bundle you send links all of them to this install."))}</p>`
        + `<h4>${esc(t("What the file holds"))}</h4><ul class="claim-members">`
        + members.map((m) => `<li><code>${esc(m[0])}</code> <span class="muted">${esc(m[1])}</span></li>`).join("") + `</ul>`
        + `<label class="claim-check"><input type="checkbox" id="claim-export-text" checked> ${esc(t("Include each article's full text"))}</label>`
        + `<p class="hint">${esc(t("Left out, each article carries its metadata and the SHA-256 of its text, not the text."))}</p>`
        + `<p class="hint">${esc(t("The trail is walked again when you export, so an article collected since this page was drawn is included."))}</p>`
        + `<div class="claim-actions"><button type="button" id="claim-export">${esc(t("Export the signed trail"))}</button>`
        + ` <span id="claim-export-status" class="hint" role="status"></span></div>`
        + `<div id="claim-export-out"></div>`
        + `<h4>${esc(t("Check a bundle"))}</h4>`
        + `<label class="claim-check">${esc(t("A trail bundle someone sent you:"))} <input type="file" id="claim-verify-file" accept=".zip,application/zip"></label>`
        + `<div id="claim-verify-out"></div>`;
      return _claimStep("⑥", t("Export the trail, signed"), method, body);
    }

    // The completion message lists what the file holds (R4's shape), with the key that
    // signed it, so the reader can hand the key over separately.
    function claimExportDoneHtml(rep, t, tf) {
      const names = rep.members || [];
      const nArt = names.filter((m) => m.startsWith("articles/")).length;
      const nWx = names.filter((m) => m.startsWith("corroboration/")).length;
      const lines = [];
      let artDone = false, wxDone = false;
      names.forEach((m) => {
        if (m.startsWith("articles/")) {
          if (!artDone) lines.push(`<li><code>articles/</code> <span class="muted">${esc(_claimFiles(nArt, tf))}</span></li>`);
          artDone = true;
        } else if (m.startsWith("corroboration/")) {
          if (!wxDone) lines.push(`<li><code>corroboration/</code> <span class="muted">${esc(_claimFiles(nWx, tf))}</span></li>`);
          wxDone = true;
        } else {
          lines.push(`<li><code>${esc(m)}</code></li>`);
        }
      });
      const pub = ((rep.identity || {}).ed25519_pub) || "";
      return `<p>${esc(tf("Saved {file}: {n} articles, {size}.", {file: "\u2068" + rep.filename + "\u2069", n: rep.articles, size: _fmtBytes(rep.bytes)}))}</p>`
        + `<ul class="claim-members">${lines.join("")}</ul>`
        + `<p class="hint">${esc(rep.full_text ? t("Each article's full text is in the file.") : t("The articles' text is left out; each carries the SHA-256 of its text."))}</p>`
        + `<p>${esc(t("Signing key (Ed25519), to give the recipient some other way:"))} <code class="claim-key">${esc(pub)}</code></p>`
        + `<p class="hint">${esc(t("Anyone can check the file with scripts/verify_claim_trail.py, or with Check a bundle here."))}</p>`;
    }

    // "1 files" otherwise: the app has no plural framework, so the singular is its own key.
    function _claimFiles(n, tf) { return n === 1 ? tf("{n} file", {n}) : tf("{n} files", {n}); }

    function claimVerifyHtml(res, t, tf) {
      if (res.verified) {
        const pub = ((res.identity || {}).ed25519_pub) || "";
        return `<p class="note ok">${esc(tf("Verified: all {n} files match the manifest, and the signature is valid.", {n: res.members}))}</p>`
          + `<p>${esc(t("Signed by the key:"))} <code class="claim-key">${esc(pub)}</code></p>`
          + `<p class="hint">${esc(t("This proves the file was not changed since that key signed it. It proves who signed it only if that key matches the one the sender gave you some other way."))}</p>`;
      }
      const probs = res.problems || (res.issues || []).map((i) => ({code: "", detail: i}));
      return `<p class="note err">${esc(t("Not verified. The problems found:"))}</p>`
        + `<ul>${probs.map((pr) => `<li>${esc(_claimProblemText(pr, t, tf))}</li>`).join("")}</ul>`;
    }

    // The checker's findings, worded here: the server sends a code and the file it names.
    const _CLAIM_PROBLEMS = {
      not_zip: (t, tf, p) => t("This is not a ZIP file."),
      no_manifest: (t, tf, p) => t("The manifest or the signature file is missing."),
      unreadable_manifest: (t, tf, p) => t("The manifest or the signature file cannot be read."),
      unknown_schema: (t, tf, p) => tf("Unknown bundle format: {detail}", {detail: p.detail}),
      member_missing: (t, tf, p) => tf("Missing file: {member}", {member: p.member}),
      member_altered: (t, tf, p) => tf("Changed since it was signed: {member}", {member: p.member}),
      member_extra: (t, tf, p) => tf("A file the manifest does not list: {member}", {member: p.member}),
      merkle_mismatch: (t, tf, p) => t("The Merkle root does not match the files listed."),
      signature: (t, tf, p) => tf("The signature does not verify: {detail}", {detail: p.detail}),
    };

    function _claimProblemText(pr, t, tf) {
      const f = _CLAIM_PROBLEMS[pr.code];
      return f ? f(t, tf, pr) : String(pr.detail || pr.code || "");
    }

    // The whole trail, in step order, as the design draws it.
    function claimWorkspaceHtml(ws, t, tf) {
      return claimRelatedHtml(ws, t, tf)
        + claimIndependenceHtml(ws, t, tf)
        + claimTimelineHtml(ws, t, tf)
        + claimCorroborationHtml(ws, t, tf)
        + claimMissingHtml(ws, t, tf)
        + claimExportHtml(ws, t, tf);
    }

    // What the reader did on the drawn trail (a weather slice shown, a bundle saved or
    // checked), kept so a language switch redraws it rather than dropping it.
    let _claimWx = {};
    let _claimExportRep = null;
    let _claimVerifyRes = null;
    let _claimParams = null;    // the claim and words the drawn trail was walked with

    function repaintClaimFromCache() {
      const box = $("claim-body");
      if (!box || !_claimLast) return;
      const t = _claimT(), tf = _claimTf();
      box.innerHTML = claimWorkspaceHtml(_claimLast, t, tf);
      const offers = ((_claimLast.corroboration || {}).offers) || [];
      Object.keys(_claimWx).forEach((i) => {
        const el = $("claim-wx-" + i);
        if (el && offers[i]) renderWeatherContext(el, _claimWx[i], _claimWxSig(offers[i]));
      });
      if (_claimExportRep && $("claim-export-out")) $("claim-export-out").innerHTML = claimExportDoneHtml(_claimExportRep, t, tf);
      if (_claimVerifyRes && $("claim-verify-out")) $("claim-verify-out").innerHTML = claimVerifyHtml(_claimVerifyRes, t, tf);
    }

    // The offer as the shared weather renderer reads it, minus the precision code: the
    // offer already says in words when its point stands in for a country.
    function _claimWxSig(op) { return Object.assign({}, op, {geocode: null}); }

    // ④ One offer's slice. A slice already held is served from this machine and asks
    // nothing; otherwise the ONE online consent comes first, with the offer's shadow line.
    async function claimWeather(i) {
      const t = _claimT(), tf = _claimTf();
      const op = (((_claimLast || {}).corroboration || {}).offers || [])[i];
      const box = $("claim-wx-" + i);
      if (!op || !box) return;
      if (!op.cached && !await ensureOnline(
        t("Fetch weather context for one place and time window (Open-Meteo)"),
        {shadow: claimShadowText(op, tf)})) return;
      box.textContent = t("Loading…");
      try {
        const d = await api("/api/weather/context", {method: "POST", body: JSON.stringify({
          lat: op.lat, lon: op.lon, start_date: op.window_start, end_date: op.window_end,
          variables: op.variables, label: op.rule_label,
        })});
        if (d && d.ok) { _claimWx[i] = d; op.cached = true; }
        renderWeatherContext(box, d, _claimWxSig(op));
      } catch (e) {
        box.innerHTML = `<div class="note err">${esc((e && e.message) || String(e))}</div>`;
      }
    }

    // ⑥ The server walks the SAME claim again and signs what it computed; the page only
    // saves the file it is handed.
    async function claimExport() {
      const t = _claimT(), tf = _claimTf();
      const status = $("claim-export-status"), out = $("claim-export-out"), btn = $("claim-export");
      if (!_claimParams || !status) return;
      const body = {claim: _claimParams.claim, full_text: !!($("claim-export-text") || {}).checked};
      if (_claimParams.query) body.query = _claimParams.query;
      try { body.ui_lang = OOI18N.current(); } catch (_e) { /* no engine: no narrowing */ }
      status.textContent = t("Writing and signing the bundle…");
      if (btn) btn.disabled = true;
      try {
        const rep = await api("/api/claims/trail-bundle", {method: "POST", body: JSON.stringify(body)});
        const bin = atob(rep.zip_base64);
        const bytes = new Uint8Array(bin.length);
        for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
        const url = URL.createObjectURL(new Blob([bytes], {type: "application/zip"}));
        const a = document.createElement("a");
        a.href = url; a.download = rep.filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        delete rep.zip_base64;
        _claimExportRep = rep;
        status.textContent = "";
        if (out) out.innerHTML = claimExportDoneHtml(rep, t, tf);
      } catch (e) {
        const msg = (e && e.message) || String(e);
        status.textContent = /Q823/.test(msg)
          ? t("This trail carries map data whose licence line waits on a decision (Q823), so it is not exported.")
          : t("The bundle could not be written:") + " " + msg;
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function claimVerify(file) {
      const t = _claimT(), tf = _claimTf();
      const out = $("claim-verify-out");
      if (!file || !out) return;
      out.textContent = t("Checking…");
      try {
        const res = await api("/api/claims/trail-bundle/verify", {
          method: "POST", body: file, headers: {"Content-Type": "application/zip"},
        });
        _claimVerifyRes = res;
        out.innerHTML = claimVerifyHtml(res, t, tf);
      } catch (e) {
        out.innerHTML = `<div class="note err">${esc((e && e.message) || String(e))}</div>`;
      }
    }

    async function claimRun() {
      const t = _claimT();
      const claim = ($("claim-text").value || "").trim();
      const query = ($("claim-query").value || "").trim();
      const status = $("claim-status");
      if (!claim) { status.textContent = t("Type or paste a claim first."); return; }
      const seq = ++_claimSeq;
      status.textContent = t("Walking the trail through your corpus…");
      const p = new URLSearchParams({claim});
      if (query) p.set("query", query);
      try { p.set("ui_lang", OOI18N.current()); } catch (_e) { /* no engine: no narrowing */ }
      try {
        const ws = await api("/api/claims/workspace?" + p.toString());
        if (seq !== _claimSeq) return;   // a newer run superseded this one
        _claimLast = ws;
        _claimParams = {claim, query};
        _claimWx = {}; _claimExportRep = null; _claimVerifyRes = null;
        status.textContent = "";
        repaintClaimFromCache();
      } catch (e) {
        if (seq !== _claimSeq) return;
        status.textContent = t("The trail could not be walked:") + " " + ((e && e.message) || String(e));
      }
    }

    function _claimWire() {
      if (_claimWired) return;
      _claimWired = true;
      const run = $("claim-run");
      if (run) run.addEventListener("click", () => claimRun());
      const txt = $("claim-text");
      // Ctrl/⌘-Enter walks the trail from the text box; a bare Enter is a new line.
      if (txt) txt.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); claimRun(); }
      });
      const q = $("claim-query");
      if (q) q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); claimRun(); } });
      // Steps ④ and ⑥ are redrawn with the trail, so their controls are reached by
      // delegation on the one container that stays.
      const body = $("claim-body");
      if (body) {
        body.addEventListener("click", (e) => {
          const wx = e.target.closest && e.target.closest("[data-claim-wx]");
          if (wx) { claimWeather(Number(wx.getAttribute("data-claim-wx"))); return; }
          if (e.target.closest && e.target.closest("#claim-export")) claimExport();
        });
        body.addEventListener("change", (e) => {
          if (e.target && e.target.id === "claim-verify-file" && e.target.files && e.target.files[0]) {
            claimVerify(e.target.files[0]);
          }
        });
      }
    }

    // Open the workspace on a claim (the omnibar row, the Search tab's button). An empty
    // text only opens it; a claim walks the trail straight away. The words box is cleared,
    // so a new claim never runs with the previous claim's words.
    function openClaimWorkspace(text) {
      showTab("claim");
      _claimWire();
      const claim = String(text || "").trim();
      if (!claim) { setTimeout(() => { const el = $("claim-text"); if (el) el.focus(); }, 30); return; }
      $("claim-text").value = claim;
      $("claim-query").value = "";
      claimRun();
    }

    // The Search tab's button: the search box's text as the claim.
    (function _claimSearchButton() {
      const wire = () => {
        const b = $("claim-from-search");
        if (b) b.addEventListener("click", () => openClaimWorkspace(($("q") && $("q").value) || ""));
      };
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
      else wire();
    })();
