# axe-core (vendored) — a11y audit engine for the ui_walk browser harness

- **Version:** 4.13.0 · **License:** MPL-2.0 (`LICENSE` alongside; MPL-2.0 is
  GPL-3.0-compatible via its secondary-license clause)
- **Upstream:** https://github.com/dequelabs/axe-core (npm tarball
  `axe-core-4.13.0.tgz`, fetched from registry.npmjs.org and verified against the
  registry's own attested digests — sha1 `f868ecb1bd61d982321760e51d841ab497ab86d0`,
  integrity `sha512-UzGt8zg7…` — before extraction, 2026-08-20)
- **Pin:** `configs/external_artifacts.yml` → `vendored-axe-core`
  (sha256 `c24f097bd2f451d4f933e8bc7d8d539f8672a2ebcb5cc9f9f3eec8ca9470a0c1`)

**What this is for:** `PlaywrightUiWalkDriver.run_axe()` injects this file into the
page under test (the 0.3-gate-row-8 browser walk's a11y axis). It is TEST/HARNESS
tooling only — deliberately under `scripts/vendor/`, **never** `src/static/` (nothing
here is served by the app, and the app itself gains no dependency on it). Vendored
locally per the local-first/no-CDN posture: the harness must never fetch tooling over
the network at run time.
