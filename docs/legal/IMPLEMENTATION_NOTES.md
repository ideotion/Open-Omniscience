# Consent gate — implementation notes (technical)

> *Note FR :* document technique destiné aux développeurs/mainteneurs (le reste de
> `docs/` est en anglais). Les **documents juridiques** de ce dossier sont en français ;
> ce fichier décrit le **mécanisme d'acceptation** et ce qui reste à câbler.

This note documents the **explicit first-run acceptance mechanism** for the legal
document set (`docs/legal/`), what is **already wired**, and the **remaining TODOs**.

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
    "version": "1.0",
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
   - `GET /api/legal/documents?lang=` → the per-language document payload
     ([`src/legal/documents.py`](../../src/legal/documents.py): French canonical, falls
     back per-document when a translation is missing), `GET /api/legal/download` (a
     `.zip` of the four documents), `POST /api/legal/decline` (typed-confirmation
     `UNINSTALL` → the SECURE uninstall path).
4. **Web GUI first-launch gate (shipped 2026-06-21, commit `5aefbc01`; browser-
   unverified — code-verified + flagged, per the project's convention for UI that
   cannot be click-through tested in this environment):** [`src/static/unlock.html`](../../src/static/unlock.html)
   inserts a full-page **legal step** into the first-launch flow — language → **accept
   the legal documents** → passphrase (`showLegalStep(code)` → `view-legal`, gated in
   before the DB even exists via `/api/legal/` joining `ALLOWED_WHILE_LOCKED` in
   [`src/api/unlock.py`](../../src/api/unlock.py)). It reads the documents in the
   user's chosen UI language (French fallback), offers a Download (`.zip`), and gates
   on either **Accept** (records consent, advances to `legalToPassphrase()`) or
   **Decline** (a required typed-`UNINSTALL` confirmation panel, never a bare click) →
   the same SECURE uninstall as Settings → Safety → Uninstall. Chrome strings come
   from the `/api/legal/documents` payload itself (not the app's global i18n engine —
   deliberate, since this page runs before the SPA/i18n bundle loads); the legal
   documents themselves are served in the user's language via `docs/legal/<lang>/`.
   This supersedes the "recommended wiring" sketch that used to live in this section —
   the real implementation is a dedicated pre-app page, not an in-SPA `<dialog>`
   modal, which blocks *harder* (nothing of the app is reachable first) than a
   dismissable overlay would. `tests/test_legal_documents.py::
   test_unlock_first_launch_inserts_legal_step_before_passphrase` pins the wiring.
   **Still owed:** a human click-through across themes/breakpoints (no headless
   browser harness in this environment).

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

1. ✅ **Done (2026-07-16).** `Version : 1.0` / `Date d'entrée en vigueur : 2026-07-16` are
   set in all four documents (French originals + all 11 translated copies), matching
   `CONSENT_DOC_VERSION` in `src/legal/consent.py`.
2. ✅ **Done.** `CONSENT_DOC_VERSION` reads `"1.0"`, matching step 1.
3. ✅ **DECIDED, permanently (2026-07-16): no professional legal review — this is not a
   gate being waited on.** Open Omniscience is a free, non-commercial hobby project with
   no budget, so a lawyer will never review this document set; the top banner of every
   document says so explicitly, as a standing fact rather than a "pending" placeholder.
   This is a conscious trade-off, not an oversight — recorded here for anyone who later
   wonders why the banner doesn't say "awaiting review": (a) `MENTIONS_LEGALES.md` §2 —
   the Éditeur has **deliberately chosen not to** disclose their real identity to GitHub
   (the LCEN Art. 1-1, II anonymity precondition), so the clause instead argues a
   different, **best-effort, professionally-unconfirmed "outside LCEN scope" position**
   (local software, no live public service operated by the Éditeur) — accepted as-is,
   with its residual risk (a possible LCEN penal sanction for incomplete mentions légales
   if a court ever disagreed) knowingly carried rather than mitigated by counsel; (b) a
   handful of legal citations (Code de la consommation Art. L.224-25-1 to L.224-25-32,
   Bruxelles I bis Art. 17-19, GDPR Art. 85 / loi n° 78-17 Art. 80) were resolved to
   specific article numbers via research and no longer carry the `[À VÉRIFIER: …]`
   bracket in the documents — but they remain **best-effort, not professionally
   verified**, and will stay that way (a different, honest claim from "still bracketed
   as TBD" — the bracket is gone, the lawyer-verification gap is not, and won't close).
4. ✅ **Done (2026-06-21, commit `5aefbc01`).** The web-GUI first-launch gate landed as
   `src/static/unlock.html`'s `view-legal` step (see item 4 under "What is already
   wired" above) — code-verified + flagged, a human click-through across
   themes/breakpoints is still owed (no headless browser harness here).

## Tests

- [`tests/test_legal_consent.py`](../../tests/test_legal_consent.py) covers the core
  (record/load/needs-acceptance/version bump, ISO-8601 timestamp, status) and the HTTP
  endpoints (status, accept, version-mismatch 400) via `TestClient` — no browser needed.
- [`tests/test_legal_documents.py`](../../tests/test_legal_documents.py) covers the
  per-language document payload, download `.zip`, decline→uninstall (stubbed, no real
  uninstall), the locked-state allowlist, the unlock-flow wiring (language → legal step
  → passphrase), and — added 2026-07-17 — that no document in any of the 12 UI
  languages still carries an unresolved `[À COMPLÉTER]`/`[À VÉRIFIER]` bracket.
