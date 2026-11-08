# axe-core (vendored) — a11y audit engine for the ui_walk browser harness

- **Version:** 4.14.0 · **License:** MPL-2.0 (`LICENSE` alongside; MPL-2.0 is
  GPL-3.0-compatible via its secondary-license clause)
- **Upstream:** https://github.com/dequelabs/axe-core (npm tarball
  `axe-core-4.14.0.tgz`, fetched from registry.npmjs.org and verified against the
  registry's own attested digests — sha1 `a9819d3932a8198fbe935d8cbd8afcdfecbcf31d`,
  integrity `sha512-9WTZxEjs…` — before extraction, 2026-11-08; 4.13.0 was vendored the
  same way on 2026-08-20)
- **Pin:** `configs/external_artifacts.yml` → `vendored-axe-core`
  (sha256 `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`)

**What this is for:** `PlaywrightUiWalkDriver.run_axe()` injects this file into the
page under test (the 0.3-gate-row-8 browser walk's a11y axis). It is TEST/HARNESS
tooling only — deliberately under `scripts/vendor/`, **never** `src/static/` (nothing
here is served by the app, and the app itself gains no dependency on it). Vendored
locally per the local-first/no-CDN posture: the harness must never fetch tooling over
the network at run time.
