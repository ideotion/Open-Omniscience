/* Open Omniscience — the /investigate page's script, moved out of an inline <script> in investigate.html
   so the CSP can drop script-src 'unsafe-inline' (Q1127 = a, 0.5 row I). It loads at the
   same point in the page as the inline block did, so it runs in the same order. */
"use strict";
// Follow the Console's appearance (same-origin localStorage), not just the OS:
// the chosen theme's light/dark family + the custom accent carry over here.
try {
  const ui = JSON.parse(localStorage.getItem("oo.ui") || "{}");
  const lightish = ["light", "paper", "dawn", "mint"];
  // The theme cull (Q1123 = b): app-shell.js's retired -> survivor map.
  const RETIRED_THEMES = { slate: "ink", arctic: "ink", mist: "light" };
  const theme = RETIRED_THEMES[ui.theme] || ui.theme;
  if (theme && theme !== "system")
    document.documentElement.dataset.mode = lightish.includes(theme) ? "light" : "dark";
  if (ui.accent) document.documentElement.style.setProperty("--accent", ui.accent);
} catch { /* default to the OS preference */ }
const Q = new URLSearchParams(location.search);
const VIEW = Q.get("view") || "";
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return r.json();
}
const panel = (title, bodyHtml, srcNote) =>
  `<section class="panel"><h2>${esc(title)}</h2>${bodyHtml}` +
  (srcNote ? `<div class="src">data: ${esc(srcNote)}</div>` : "") + `</section>`;
// A suggestion is an action the user could do manually, parameters visible.
const suggestion = (label, href, what) =>
  `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}<span class="what">${esc(what)}</span></a>`;
const caveatBlock = text =>
  `<div class="caveat"><b>Caveat (from the Lead):</b> ${esc(text)}</div>`;

// ---------------------------------------------------------------- promise --- //
async function viewPromise() {
  const articleId = Q.get("article_id"), date = Q.get("date"), title = Q.get("title") || "";
  document.getElementById("ttl").textContent = `Promise due — ${date}`;
  let html = caveatBlock(
    "A mentioned future date is not always a promise (it may be a citation or a schedule " +
    "note) — read the snippet; candidate tags are unconfirmed extractions.");

  // Panel 1: the original article + its date tags (provenance snippets).
  let tagsHtml = '<p class="muted">No date tags found.</p>';
  try {
    const tags = await api(`/api/article-dates/article/${articleId}`);
    const list = tags.tags || tags.dates || tags.items || (Array.isArray(tags) ? tags : []);
    if (list.length) {
      tagsHtml = "<table><tr><th>Date</th><th>Status</th><th>Snippet (provenance)</th></tr>" +
        list.map(t => `<tr><td>${esc(t.mentioned_on || t.date)}</td><td>${esc(t.status)}</td>` +
                      `<td>${esc(t.snippet || "")}</td></tr>`).join("") + "</table>";
    }
  } catch (e) { tagsHtml = `<p class="err">${esc(e.message)}</p>`; }
  html += panel("The original article",
    `<p><a href="/api/articles/${esc(articleId)}/view" target="_blank" rel="noopener">` +
    `${esc(title) || "Open the stored copy"}</a> <span class="muted">(offline stored copy)</span></p>` +
    tagsHtml, `/api/article-dates/article/${esc(articleId)}`);

  // Panel 2: coverage since the promised date, seeded by the article's title words.
  const terms = title.split(/\s+/).filter(w => w.length > 3).slice(0, 4).join(" ");
  let follow = '<p class="muted">No stored coverage on these terms since the promised date.</p>';
  try {
    const r = await api(`/api/articles?query=${encodeURIComponent(terms)}` +
                        `&start_date=${encodeURIComponent(date)}&limit=10`);
    if ((r.results || []).length) {
      follow = "<table><tr><th>Published</th><th>Title</th><th>Source</th></tr>" +
        r.results.map(a => `<tr><td>${esc((a.published_at || "").slice(0,10))}</td>` +
          `<td><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener">${esc(a.title)}</a></td>` +
          `<td>${esc(a.source || "")}</td></tr>`).join("") + "</table>";
    }
  } catch (e) { follow = `<p class="err">${esc(e.message)}</p>`; }
  html += panel(`Coverage since ${date} (query: “${terms}”)`, follow,
    "Boolean FTS search over your corpus, pre-filled — edit it in the main app");

  html += panel("Go deeper (each opens the main app with the parameters shown)",
    `<div class="suggest">
       ${suggestion("Search variants", "/#search", `your query: ${terms}`)}
       ${suggestion("Open the World map", "/#timemap", `window around ${date}`)}
       ${suggestion("Add to briefing draft", "/#home", "pin the original + follow-ups")}
       ${suggestion("Log to custody", "/#custody", `article ${articleId}: signed, hash-chained entry`)}
     </div>`);
  return html;
}

// --------------------------------------------------------------- edit-war --- //
async function viewEditWar() {
  const pageId = Q.get("page_id"), title = Q.get("title") || "", wiki = Q.get("wiki") || "";
  document.getElementById("ttl").textContent = `Edit burst — ${wiki}:${title}`;
  let html = caveatBlock(
    "A burst measures editing activity, not wrongdoing — releases, vandalism cleanup and " +
    "genuine news all cause bursts. Read the diffs.");

  let changes = '<p class="muted">No flagged tracked edits stored for this wiki.</p>';
  try {
    const r = await api(`/api/wiki/changes?flagged_only=false&wiki=${encodeURIComponent(wiki)}&limit=100`);
    const rows = (r.changes || r.items || []).filter(c =>
      String(c.page_id ?? "") === String(pageId) || (c.title === title));
    if (rows.length) {
      changes = "<table><tr><th>When</th><th>Editor</th><th>Δ bytes</th><th>Comment</th><th>Flags</th></tr>" +
        rows.slice(0, 40).map(c => `<tr><td>${esc((c.timestamp || "").slice(0,16))}</td>` +
          `<td>${esc(c.editor || "")}${c.editor_anon ? " (anon)" : ""}</td>` +
          `<td>${esc(c.delta_bytes ?? "")}</td><td>${esc((c.comment || "").slice(0,80))}</td>` +
          `<td>${esc(c.flag_reasons || (c.flagged ? "flagged" : ""))}</td></tr>`).join("") + "</table>";
    }
  } catch (e) { changes = `<p class="err">${esc(e.message)}</p>`; }
  html += panel("Stored revisions of this page (window of the burst)", changes,
    `/api/wiki/changes — your locally tracked copy, with per-edit provenance`);

  html += panel("Go deeper",
    `<div class="suggest">
       ${suggestion("Open the Wikipedia tab", "/#wiki", `page: ${wiki}:${title} — diffs & baselines`)}
       ${suggestion("Search your corpus", "/#search", `query: "${title}" — is news driving the burst?`)}
       ${suggestion("Open the World map", "/#timemap", "the burst window in context")}
     </div>`);
  return html;
}

// ----------------------------------------------------------- quiet-region --- //
async function viewQuietRegion() {
  const country = Q.get("country") || "", recent = Q.get("recent_7d"),
        priorW = Q.get("prior_weekly");
  document.getElementById("ttl").textContent = `Region gone quiet — ${country}`;
  let html = caveatBlock(
    "This measures YOUR corpus, not the region: a dead feed or a source outage looks " +
    "identical to real silence. Check the sources first.");

  html += panel("The signal",
    `<span class="num">${esc(recent)}</span> articles in the last 7 days
     <span class="muted">(prior weekly rate ≈ ${esc(priorW)})</span>`,
    "stored-article counts per country — collection volume, nothing else");

  let cov = '<p class="muted">Coverage summary unavailable.</p>';
  try {
    const r = await api("/api/database/coverage");
    const thin = (r.thin || []).map(esc).join(", ");
    const missing = (r.missing || []).length;
    cov = `<p>Catalog-wide: <b>${esc(r.covered ?? "?")}</b> countries covered, ` +
          `<b>${missing}</b> with no source at all.` +
          (thin ? ` Thin coverage: ${thin}.` : "") + `</p>`;
  } catch (e) { cov = `<p class="err">${esc(e.message)}</p>`; }
  html += panel("Where this fits in your overall coverage", cov, "/api/database/coverage");

  html += panel("Go deeper",
    `<div class="suggest">
       ${suggestion("Check the sources", "/#sources", `filter: ${country} — enabled? last fetch ok?`)}
       ${suggestion("Scrape now", "/#ingest", "run the scheduler once and watch the live activity")}
       ${suggestion("World coverage view", "/#database", "the country map of your catalog")}
       ${suggestion("Add sources from the catalog", "/#sources", `catalog candidates for ${country}`)}
     </div>`);
  return html;
}

// ------------------------------------------------------------------ boot --- //
const VIEWS = { "promise": viewPromise, "edit-war": viewEditWar, "quiet-region": viewQuietRegion };
// SHORT browser-tab titles per view (maintainer-ruled 2026-06-10): the tab
// must say its intent at a glance, and stay short for narrow tab strips.
const TAB_TITLES = { "promise": "Promise due", "edit-war": "Edit war", "quiet-region": "Quiet region" };
(async () => {
  // "FOOS" = Free Open OmniScience (alpha working name -- maintainer-ruled
  // 2026-06-10; a proper rename may come later). Short, for narrow tab strips.
  document.title = (TAB_TITLES[VIEW] || "Investigate") + " · FOOS";
  const main = document.getElementById("main");
  const fn = VIEWS[VIEW];
  if (!fn) {
    main.innerHTML = `<div class="panel"><h2>Unknown investigation view</h2>
      <p>“${esc(VIEW)}” is not a known recipe. Known: ${Object.keys(VIEWS).map(esc).join(", ")}.</p>
      <p><a href="/">Back to the main app</a></p></div>`;
    return;
  }
  try { main.innerHTML = await fn(); }
  catch (e) { main.innerHTML = `<div class="panel"><h2 class="err">Could not load</h2><p>${esc(e.message)}</p></div>`; }
})();
