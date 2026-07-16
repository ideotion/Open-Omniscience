# Consent gate — implementation notes (technical)

> *Note FR :* document technique destiné aux développeurs/mainteneurs (le reste de
> `docs/` est en anglais). Les **documents juridiques** de ce dossier sont en français ;
> ce fichier décrit le **mécanisme d'acceptation** et ce qui reste à câbler.

This note documents the **explicit first-run acceptance mechanism** for the legal
document set (`docs/legal/`), what is **already wired**, and the **remaining TODOs** —
chiefly the web-GUI modal, which cannot be browser-verified in this environment.

## What "acceptance" records

A small, local, network-free record (same pattern as `src.config.app_settings`):

- **Module:** [`src/legal/consent.py`](../../src/legal/consent.py) (+ package
  [`src/legal/__init__.py`](../../src/legal/__init__.py)).
- **Stored at:** `data_dir()/legal_consent.json` (the per-user data dir from
  `src.paths`). Never transmitted to the Éditeur — consistent with the no-telemetry
  posture.
- **Record shape:**
  ```json
  {
    "schema": "oo-legal-consent-1",
    "version": "0.draft",
    "accepted_at": "2026-06-20T12:34:56.789012+00:00",
    "actor": "web",
    "documents": ["mentions_legales", "cgu", "confidentialite", "charte_usage"]
  }
  ```
- **Version awareness:** `CONSENT_DOC_VERSION` is the single knob. Bump it whenever the
  documents change substantially → `needs_acceptance()` returns `True` again and the user
  is re-prompted. **It MUST match the `Version :` field of the `docs/legal/*.md`
  documents.**

### Public API of `src.legal.consent`

| Symbol | Purpose |
|---|---|
| `CONSENT_DOC_VERSION` | Current document-set version (keep in sync with the docs). |
| `LEGAL_DOCUMENTS` | The four documents (id, title, repo path). |
| `consent_path()` | Path to the local record. |
| `load_consent()` | The record or `None` (never raises). |
| `is_accepted(version=…)` / `needs_acceptance(version=…)` | Status checks. |
| `record_consent(version=…, actor=…)` | Write the record (ISO-8601 UTC timestamp). |
| `consent_status(version=…)` | Serialisable status for the API/CLI. |
| `notice_text(version=…)` | A short, non-blocking console notice. |

## What is already wired

1. **CLI (implemented, isolated):** in [`src/api/main.py`](../../src/api/main.py):
   - `open-omniscience terms` → prints the documents + the local acceptance status.
   - `open-omniscience accept-terms` → prints the notice and records explicit acceptance
     (asks the user to type `j'accepte`/`accept`; `--yes` to skip the prompt).
   - These run **only when invoked deliberately**, never during `serve`.
2. **Startup notice (implemented, non-blocking):** `_serve()` prints `notice_text()` once
   when `needs_acceptance()` is `True`, then starts normally. It **never blocks** the
   server (a blocking `tty` prompt would break the desktop launcher / `curl | bash`
   bootstrap / headless runs). Wrapped in `try/except` so it can never fail startup.
3. **HTTP API (implemented, testable):** [`src/api/legal.py`](../../src/api/legal.py),
   wired in `src/api/_wiring.py`:
   - `GET /api/legal/consent` → `consent_status()` (required?, version, accepted_at,
     documents with URLs).
   - `POST /api/legal/consent` body `{"version": "<current>"}` → records acceptance;
     returns the new status. A version mismatch returns **400** (a stale acceptance can
     never be recorded as current).

## TODO — web GUI blocking modal (browser-unverified)

The backend is ready; the SPA needs a small first-load modal. It was **not** injected
into `index.html` here because it touches the boot path and **cannot be browser-verified**
in this environment (project rule: browser-unverifiable UI ships flagged, not on faith).

**Recommended wiring** (add to the SPA boot, after the app shell mounts):

```js
// First-run legal consent gate. Blocks the UI until the user accepts.
async function ensureLegalConsent() {
  const r = await fetch('/api/legal/consent');
  const s = await r.json();
  if (!s.required) return;            // already accepted this version
  // Build a blocking modal (re-use the app's <dialog> + focus-trap conventions):
  //  - title + the "draft, not legal advice" line
  //  - links to each s.documents[i] (label = .title, href = .url or a local route)
  //  - a single REQUIRED checkbox "J'ai lu et j'accepte ces documents"
  //  - an "Accepter" button, disabled until the checkbox is ticked
  // On accept:
  await fetch('/api/legal/consent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: s.current_version }),
  });
  // then remove the modal and let the app proceed.
}
```

Checklist for that PR:
- [ ] Re-use the existing `<dialog>` + `_trapTab` focus-trap + Esc conventions (a consent
      modal should trap focus and be keyboard-accessible).
- [ ] Serve the documents to the modal — either link to the GitHub URLs from
      `consent_status().documents[].url`, or add a tiny local route that renders the
      `docs/legal/*.md` files (preferred for offline-first; the app already renders Help
      docs locally).
- [ ] i18n: the modal **chrome** strings go through the app's i18n engine; the legal
      **documents themselves stay French** (they are the legal text).
- [ ] Click-through across themes/breakpoints (no headless harness here).

## TODO — optional hard block of the server (opt-in)

Today the server **starts** even if consent is pending (it only prints a notice). If a
deployment wants to **refuse to serve** until accepted, gate it behind an env flag so the
default (launcher / headless) flows are never broken — e.g. in `_serve()`:

```python
import os
from src.legal.consent import needs_acceptance
if os.getenv("OO_REQUIRE_CONSENT") == "1" and needs_acceptance():
    raise SystemExit(
        "Refusing to start: accept the terms first with `open-omniscience accept-terms` "
        "(or set OO_REQUIRE_CONSENT=0)."
    )
```

This is intentionally **left as a documented option**, not the default, because hard-blocking
the web entrypoint could strand a desktop-launcher or `curl | bash` user with no console.

## Finalizing for release

1. ✅ **Done (2026-07-16).** `Version : 1.0-draft` / `Date d'entrée en vigueur :
   2026-07-16` are now set in all four documents (French originals + all 11 translated
   copies), matching `CONSENT_DOC_VERSION` in `src/legal/consent.py`. The `-draft` suffix
   is intentional — it stays until step 3 below is done; bump to a plain `"1.0"` (in
   the docs **and** `CONSENT_DOC_VERSION` together) once a qualified professional has
   signed off.
2. ✅ **Done.** `CONSENT_DOC_VERSION` already reads `"1.0-draft"`, matching step 1.
3. ⬜ **Still open.** Have a qualified professional review the documents (they remain
   drafts — see the banner on each). Two known open items for that review, both flagged
   inline: (a) `MENTIONS_LEGALES.md` §2 — the Éditeur has **deliberately chosen not to**
   disclose their real identity to GitHub (the LCEN Art. 1-1, II anonymity precondition),
   so the clause was rewritten (2026-07-16) around a different, **untested "outside LCEN
   scope" argument** instead (local software, no live public service operated by the
   Éditeur) — this position is explicitly flagged as unconfirmed by counsel and carries a
   residual risk (a possible LCEN penal sanction for incomplete mentions légales if a court
   ever disagreed with the scope argument); a lawyer should assess whether to keep this
   position, harden its wording, or accept the residual risk as-is; (b) the handful of
   remaining `[À VÉRIFIER: …]` legal-citation placeholders (Code de la consommation
   articles, Bruxelles I bis articles, GDPR Art. 85 French-transposition article) —
   best-effort citations were filled in from research, flagged for professional
   confirmation, not guaranteed correct.
4. ⬜ **Still open.** Land the web-modal PR above.

## Tests

- [`tests/test_legal_consent.py`](../../tests/test_legal_consent.py) covers the core
  (record/load/needs-acceptance/version bump, ISO-8601 timestamp, status) and the HTTP
  endpoints (status, accept, version-mismatch 400) via `TestClient` — no browser needed.
