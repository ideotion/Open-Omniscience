/* app-evidence.js — the review before a signed evidence bundle is saved, and the message after
   (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S5; R4's shape: what the file holds, listed)

   The "Export signed evidence" buttons (the Search tab's and the analysis window's) used to
   download at once and say "Signed bundle: N item(s)" in a toast that vanished. They now open
   a review first: how many articles and sources, what the file holds, that it is PLAINTEXT
   and what its signature does and does not prove, and which key signs. Saving is one more
   click. Afterwards the same dialog lists what was saved and the key to hand the recipient.

   THE REVIEW IS READ-ONLY. Its numbers come from POST /api/reports/evidence/plan, which
   creates no key, writes nothing and makes no network call: looking costs nothing.

   The renderers are pure (payload, t, tf) -> HTML so tests/evidence_review_node_test.js
   drives them in node; only openEvidenceReview, evidenceSave and _evidenceWire touch the DOM
   or the network (loopback).
*/
    let _evScope = null;      // the selection the dialog was opened on
    let _evPlan = null;       // the plan payload, so a language switch redraws without a fetch
    let _evDone = null;       // {filename, bytes, count, pub} once saved
    let _evWired = false;
    let _evSeq = 0;

    function _evT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _evTf() {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf;
      return (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
    }

    // What the file holds, one line each: the JSON keys are file structure (shown as code,
    // never translated, like a file name); the words beside them are the explanation.
    function evidenceMembersHtml(plan, t, tf) {
      // the field names are code: a left-to-right run, isolated so an RTL sentence does not
      // reorder them around its own punctuation
      const fields = "\u2066" + (plan.item_fields || []).join(", ") + "\u2069";
      return `<ul class="claim-members">`
        + `<li><code>manifest</code> <span class="muted">${esc(t("the bundle version, when it was made, how many articles, and the Merkle root that covers them"))}</span></li>`
        + `<li><code>manifest.items</code> <span class="muted">${esc(tf("one entry per article, with {fields}", {fields}))}</span></li>`
        + `<li><code>signature</code>, <code>public_key</code> <span class="muted">${esc(t("the signature over the manifest and the public key that made it"))}</span></li>`
        + `</ul>`;
    }

    function evidenceReviewHtml(plan, t, tf) {
      const signer = plan.signer || {};
      const method = t("The file is one signed JSON document: the articles you selected as provenance entries (where each came from and the SHA-256 of its text), bound together by a Merkle root and signed with this install's evidence key, so anyone can check that nothing was changed.");
      return `<p class="claim-method">${esc(method)}</p>`
        + `<p><b>${esc(tf("Articles: {n}", {n: plan.articles}))}</b> · ${esc(tf("Sources: {n}", {n: plan.sources}))}</p>`
        + `<h4>${esc(t("What the file holds"))}</h4>` + evidenceMembersHtml(plan, t, tf)
        + `<p class="card-caveat">${esc(t("Plaintext: the file is not encrypted. It lists each article's address, title and date, and anyone who has the file can read them. The articles' text is not in it, only its SHA-256."))}</p>`
        + `<p class="card-caveat">${esc(signer.exists
          ? t("It is signed with this install's evidence key. That proves this install made it, and the same key on every bundle you send links all of them to this install.")
          : t("This install has no evidence key yet. One is created on this machine when you save, and stays here. It proves this install made a bundle, and links every bundle it signs."))}</p>`;
    }

    // The message after saving: what was saved, what the file holds, the key to hand over.
    function evidenceDoneHtml(plan, done, t, tf, fmtBytes) {
      return `<p>${esc(tf("Saved {file}: {n} articles, {size}.", {file: "⁨" + done.filename + "⁩", n: done.count, size: fmtBytes(done.bytes)}))}</p>`
        + `<h4>${esc(t("What the file holds"))}</h4>` + evidenceMembersHtml(plan, t, tf)
        + `<p>${esc(t("Signing key (Ed25519), to give the recipient some other way:"))} <code class="claim-key">${esc(done.pub || "")}</code></p>`
        + `<p class="hint">${esc(t("Anyone can check the file offline with scripts/verify_evidence.py, which needs only the file and the key."))}</p>`;
    }

    function _evPaint() {
      const t = _evT(), tf = _evTf();
      const body = $("evidence-body"), save = $("evidence-save"), close = $("evidence-close");
      if (!body || !_evPlan) return;
      const fmt = (typeof _fmtBytes === "function") ? _fmtBytes : ((n) => String(n));
      body.innerHTML = _evDone ? evidenceDoneHtml(_evPlan, _evDone, t, tf, fmt) : evidenceReviewHtml(_evPlan, t, tf);
      if (save) save.hidden = !!_evDone;
      if (close) close.textContent = _evDone ? t("Close") : t("Cancel");
    }

    async function evidenceSave() {
      const t = _evT(), tf = _evTf();
      const status = $("evidence-status"), save = $("evidence-save");
      if (!_evScope || !_evPlan) return;
      if (save) save.disabled = true;
      if (status) status.textContent = t("Writing and signing the bundle…");
      try {
        const bundle = await api("/api/reports/evidence", {method: "POST", body: JSON.stringify(_evScope)});
        const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"});
        const day = String((bundle.manifest || {}).generated_at || "").slice(0, 10);
        const filename = "evidence-bundle" + (day ? "-" + day : "") + ".json";
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename; a.click();
        _evDone = {filename, bytes: blob.size, count: (bundle.manifest || {}).item_count, pub: bundle.public_key};
        if (status) status.textContent = "";
        _evPaint();
      } catch (e) {
        if (status) status.textContent = t("The bundle could not be written:") + " " + ((e && e.message) || String(e));
      } finally {
        if (save) save.disabled = false;
      }
    }

    function _evidenceWire() {
      if (_evWired) return;
      _evWired = true;
      const on = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
      on("evidence-save", () => evidenceSave());
      on("evidence-close", () => { const d = $("evidence-review"); if (d && d.open) d.close(); });
      document.addEventListener("oo:langchange", () => { const d = $("evidence-review"); if (d && d.open) _evPaint(); });
    }

    // The two "Export signed evidence" buttons land here with their selection (a query, or
    // the analysed article ids). No selection: the same refusal the direct export gave.
    async function openEvidenceReview(sel) {
      const t = _evT();
      if (!sel) { toast(t("Enter a search query to scope the evidence bundle."), "err"); return; }
      _evidenceWire();
      const seq = ++_evSeq;
      let plan;
      try {
        plan = await api("/api/reports/evidence/plan", {method: "POST", body: JSON.stringify(sel)});
      } catch (e) {
        toast(_failMsg("Evidence export: {error}", e), "err");
        return;
      }
      if (seq !== _evSeq) return;
      _evScope = sel; _evPlan = plan; _evDone = null;
      const status = $("evidence-status"); if (status) status.textContent = "";
      _evPaint();
      const d = $("evidence-review");
      if (d && !d.open) d.showModal();
    }
