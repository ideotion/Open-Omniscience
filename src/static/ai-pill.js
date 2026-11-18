/* The AI pill's health vocabulary, shared by the app and the task manager (row 164, 2026-11-18).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 *
 * Both pages draw the same #llm pill from the same /api/llm/health answer. The app painted
 * the offline state as "pill warn ai-off" (red plus the diagonal bar in app.css) with a hover
 * naming the reason; the task manager painted plain "pill warn", so there the state was colour
 * alone and the reason was missing. One function now maps a health answer to the class and
 * hover both pages use, so the two cannot drift apart again.
 *
 * It covers what the health answer alone decides. The app's own transient states, a start it
 * just asked for and work in progress in this tab, stay in app-ai-tools.js, which knows them.
 *
 * No network: this file is a pure function of its arguments.
 */
(function () {
  "use strict";

  // h: the /api/llm/health answer, or null when the probe itself failed.
  // t: the translator (OOI18N.t). Returns { cls, title }.
  function ooAiPillState(h, t) {
    if (typeof t !== "function") t = function (s) { return s; };
    if (h && h.available) {
      return { cls: "pill ok", title: t("AI — click to open AI settings") };
    }
    if (h && h.hardware_practical === false) {
      // A state distinct from "offline": starting a backend would not fix this machine,
      // so the hover points at the disclosure and the override. `=== false` on purpose:
      // null means the probe could not decide and falls through to the offline copy.
      return {
        cls: "pill warn ai-off",
        title: (h.hardware_reason ? h.hardware_reason + " — " : "")
          + t("AI features are off by default on this hardware — open AI settings to override"),
      };
    }
    if (!h) {
      // The probe failed, so nothing is certainly serving: never the neutral pill.
      return { cls: "pill warn ai-off", title: t("AI — click to open AI settings") };
    }
    // `no_backend` means nothing at all answers, which is a fixed fact and so one keyed
    // sentence; `detail` is the client's own exception text and has no keyed twin yet.
    var why = h.no_backend
      ? t("No AI backend is reachable right now — neither Ollama nor vLLM answers.")
      : (h.detail || "");
    return {
      cls: "pill warn ai-off",
      title: (why ? why + " — " : "")
        + t("AI is offline — click to start it, or open AI settings to install one"),
    };
  }

  window.ooAiPillState = ooAiPillState;
})();
