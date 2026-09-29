/* The data-drive countdown (R86, 2026-09-29).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 *
 * Loaded by BOTH the app and the unlock screen: a drive can be pulled while either is up.
 * It asks /api/system/data-volume once; only an install whose data folder sits on a drive
 * the first-launch step marked answers watched:true, and only then does it keep polling
 * (every 2 s, loopback, no database). The server owns the clock: the seconds shown are the
 * server's own count, so a slow tab never shows a deadline the server does not hold.
 */
(function () {
  "use strict";
  var URL = "/api/system/data-volume";
  var box = null;
  var timer = null;

  function tr(s, vars) {
    var i = window.OOI18N;
    if (!i) return vars ? s.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] == null ? m : String(vars[k]); }) : s;
    return vars ? i.tf(s, vars) : i.t(s);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function ensureBox() {
    if (box) return box;
    // A modal <dialog>: the app's own dialogs (the welcome, the consent popup) sit in the
    // browser's top layer, where no z-index reaches, so a plain overlay drew BEHIND them
    // (seen in Chromium, 2026-09-29). Opened last, this one is on top of all of them.
    box = el("dialog", "dv-overlay");
    box.id = "data-volume-overlay";
    box.setAttribute("role", "alertdialog");
    box.setAttribute("aria-live", "assertive");
    box.style.cssText = "border:0;padding:0;background:transparent;max-width:calc(100vw - 32px)";
    // Esc must not dismiss it: the drive is still gone.
    box.addEventListener("cancel", function (ev) { ev.preventDefault(); });
    var card = el("div", "dv-card");
    card.style.cssText =
      "max-width:34rem;width:100%;background:var(--panel,#1b1f24);color:var(--fg,#e8e6e3);" +
      "border:1px solid var(--line,#444);border-radius:10px;padding:20px;line-height:1.5";
    var title = el("h2", "dv-title", "");
    // Focus lands on the title, never on «Close now»: an Enter meant for the page behind
    // must not close the app.
    title.tabIndex = -1;
    title.autofocus = true;
    card.appendChild(title);
    card.appendChild(el("p", "dv-count", ""));
    card.appendChild(el("p", "dv-body", ""));
    var cav = el("p", "card-caveat dv-caveat", "");
    cav.style.color = "var(--caveat,#eab44e)";
    card.appendChild(cav);
    card.appendChild(el("p", "dv-note", ""));
    var btn = el("button", "dv-close", "");
    btn.type = "button";
    btn.addEventListener("click", closeNow);
    card.appendChild(btn);
    box.appendChild(card);
    document.body.appendChild(box);
    try { box.showModal(); } catch (e) { box.setAttribute("open", ""); }
    return box;
  }

  function q(cls) { return box.querySelector("." + cls); }

  function render(s) {
    if (!s || s.phase === "ok" || !s.watched) {
      if (box) { box.remove(); box = null; }
      return;
    }
    ensureBox();
    // Something else closed it (a page-wide Esc handler did, in Chromium): the drive is
    // still gone, so it comes back.
    if (!box.open) { try { box.showModal(); } catch (e) { box.setAttribute("open", ""); } }
    var n = s.seconds_left == null ? "" : s.seconds_left;
    q("dv-title").textContent = tr("The drive holding your data was disconnected");
    q("dv-caveat").textContent = tr(
      "Anything written in the last moments before the drive was removed may be lost; the database itself stays consistent.");
    q("dv-note").textContent = tr("The disconnection was recorded for diagnostics.");
    var closeBtn = q("dv-close");
    closeBtn.textContent = tr("Close now");
    closeBtn.hidden = !(s.phase === "reconnect" || s.phase === "shutdown");
    if (s.phase === "reconnect") {
      q("dv-count").textContent = tr("Reconnect it within {n} s.", { n: n });
      q("dv-body").textContent = tr("Collection is paused until it is back.");
    } else if (s.phase === "shutdown") {
      q("dv-count").textContent = tr("The app will close in {n} s to protect your data.", { n: n });
      q("dv-body").textContent = tr("Reconnecting the drive now still restarts the app instead.");
    } else if (s.phase === "restarting") {
      q("dv-count").textContent = tr("The drive is back. The app is restarting to reopen your data.");
      q("dv-body").textContent = "";
      waitForRestart();
    } else {
      q("dv-count").textContent = tr("The app is closing. Reconnect the drive, then start the app again.");
      q("dv-body").textContent = "";
    }
  }

  function poll() {
    fetch(URL, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || !s.watched) { stop(); return; }
        render(s);
      })
      .catch(function () { /* the server is restarting or has closed: keep the last message */ });
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function waitForRestart() {
    stop();
    var tries = 0;
    var t = setInterval(function () {
      tries += 1;
      fetch("/api/health", { cache: "no-store" })
        .then(function (r) { if (r.ok) { clearInterval(t); location.href = "/"; } })
        .catch(function () {});
      if (tries > 150) clearInterval(t);
    }, 2000);
  }

  function closeNow() {
    fetch(URL + "/close-now", { method: "POST" }).then(poll).catch(function () {});
  }

  function start() {
    fetch(URL, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || !s.watched) return;   // an install without a marked drive: nothing to watch
        render(s);
        timer = setInterval(poll, 2000);
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
