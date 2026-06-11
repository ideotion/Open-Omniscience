# Bundled fonts

These typefaces are **bundled in the repository on purpose** (maintainer ruling,
2026-06-11): fonts don't evolve, so shipping them means one less thing to
download and one less thing to worry about — the UI looks identical on every
machine, fully offline, with zero font-related network requests, ever.

All families are licensed under the **SIL Open Font License 1.1** (the `OFL-*.txt`
file next to each family is its verbatim license). They were fetched from the
upstream-maintained copies in <https://github.com/google/fonts> (`ofl/` tree)
and losslessly repackaged from TTF to WOFF2 with `fonttools` — no glyph or
metric was altered.

| File | Family | Weights | Notes |
| --- | --- | --- | --- |
| `Cantarell-Regular.woff2`, `Cantarell-Bold.woff2` | Cantarell | 400, 700 | GNOME's humanist UI sans. (The upstream variable build with Thin–ExtraBold lives at GNOME GitLab; the widely distributed build is regular/bold only.) |
| `Inter-Variable.woff2` | Inter | variable 100–900 | UI workhorse; true Thin at weight 100. |
| `Outfit-Variable.woff2` | Outfit | variable 100–900 | Geometric modern sans; very light thin cuts. |
| `Manrope-Variable.woff2` | Manrope | variable 200–800 | Rounded modern sans. |
| `JetBrainsMono-Variable.woff2` | JetBrains Mono | variable 100–800 | The app's monospace (code, terminal theme). |
| `SourceSerif4-Variable.woff2` | Source Serif 4 | variable 200–900 | Reading serif (Sepia/Paper themes). |

How they are used:

- `index.html` declares one `@font-face` per file (local URLs under
  `/static/fonts/`, `font-display: swap` so text never blocks on a font).
- Some themes pair with a font (Arctic→Inter, Cyber→Outfit, Mint→Manrope,
  Sepia/Paper→Source Serif 4, Terminal→mono); the **Typeface** picker in
  Settings → Appearance overrides any theme's choice.
- Every stack ends in system fallbacks, so a missing file can never blank the UI,
  and scripts a family doesn't cover (e.g. Arabic, CJK) fall through to the
  system fonts that do.

GPL compatibility: the OFL is a free license; using OFL fonts alongside
GPL-3.0-or-later application code is fine (the fonts are aggregated assets,
not derived code, and keep their own license texts here).
