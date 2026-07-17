# Testing the first-launch legal **decline = uninstall** path

The first launch shows the legal documents (between the language step and the
passphrase). **Accepting** records consent and continues to the passphrase.
**Declining** triggers a **SECURE uninstall**: it removes the virtualenv, the
desktop launchers, the app folder, **and wipes the data dir and signing keys**
via crypto-erase (destroys the SQLCipher salt/header + on-disk key material,
then deletes — see `src/safety/crypto_erase.py`), optionally followed by a
full free-space overwrite pass.

> ⚠️ **This is irreversible and destructive.** Test it ONLY in a throwaway VM or
> container — **never** against a machine that holds a real corpus or keys.
> `perform_decline_uninstall()` calls `request_uninstall(confirm=True,
> remove_folder=True, wipe_data=True)`, which is the same secure mode as
> Settings → Safety → Uninstall (Secure).

## What it removes / keeps
- **Removed**: `<repo>/.venv`, desktop/app-menu launchers, the app folder
  (`remove_folder`), and the data dir + keys (`wipe_data`).
- **Kept**: an audit log at `~/.open-omniscience-uninstall.log` (it lives in
  `$HOME`, so it survives even a secure wipe — it records exactly what was
  removed and any failures).

## Dry run first (non-destructive)
Before declining for real, confirm the exact paths the secure uninstall would
touch — this previews the plan and removes **nothing**:

```
curl -s http://127.0.0.1:8000/api/safety/uninstall/plan | python3 -m json.tool
```

Check that `wipe_data_dir` and `app_folder` point at the throwaway VM's paths
(not anything you care about) before proceeding.

## Steps (throwaway VM)
1. In a clean VM/container, clone the repo and run `./install.sh --unattended`
   (or the normal interactive install), then launch the app.
2. Open `http://127.0.0.1:8000`. On a **fresh** store the flow is:
   **language → legal documents → passphrase**. Stop at the legal step.
3. Click **Decline**. A confirm panel asks you to type the literal word
   **`UNINSTALL`** (ASCII, never localized — `DECLINE_CONFIRM_WORD`) and confirm.
   - API equivalent: `POST /api/legal/decline {"confirm": true, "word": "UNINSTALL"}`.
     A wrong/empty `word` or `confirm:false` is rejected (no uninstall).
4. The server schedules a detached watcher and stops (the deletion runs after the
   process exits). The browser shows the terminal overlay ("close this window").

## Verify
- `<repo>/.venv` is gone; the launchers are gone; the app folder is gone.
- The data dir (`~/.local/share/open-omniscience` by default) is gone.
- `~/.open-omniscience-uninstall.log` exists and lists what was removed.

## Accept path (sanity)
Re-provision the VM (or use a second one), reach the legal step, tick **I accept**
and **Accept**. Consent is recorded (`CONSENT_DOC_VERSION`) and the flow advances
to the create-passphrase step — the app installs normally, nothing is removed.

## Outstanding (not blocking the test)
- Versions are finalized (`Version : 1.0` / `Date d'entrée en vigueur : 2026-07-16` in
  every document, French + all 11 translations), matching `CONSENT_DOC_VERSION` in
  `src/legal/consent.py`. No remaining `[À COMPLÉTER]`/`[À VÉRIFIER]` bracket markers —
  the meta-explanatory sentence about that bracket convention, and a dangling
  SIREN/SIRET/VAT placeholder in `MENTIONS_LEGALES.md`, were both removed outright
  (2026-07-17, maintainer decision) rather than kept as a "deliberately left as-is"
  note. The only live follow-through is bumping `CONSENT_DOC_VERSION` (and the
  `Version`/`Date` fields) whenever the documents next change substantially.
- The 11 non-French translations are AI-drafted and flagged for native review
  (the French text is authoritative).
