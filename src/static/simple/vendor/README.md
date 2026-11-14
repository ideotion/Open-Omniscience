# Vendored libraries for simple mode

Unmodified upstream files, served locally (never a CDN), pinned in `SHA256SUMS` and in
`configs/external_artifacts.yml`. Simple mode is invariant #34 (ruling R682).

| File | Package | Version | Licence | Upstream path |
|---|---|---|---|---|
| `preact.min.umd.js` | preact | 10.29.8 | MIT (`preact.LICENSE.txt`) | `dist/preact.min.umd.js` |
| `hooks.umd.js` | preact (hooks) | 10.29.8 | MIT (`preact.LICENSE.txt`) | `hooks/dist/hooks.umd.js` |
| `htm.umd.js` | htm | 3.1.1 | Apache-2.0 (`htm.LICENSE.txt`) | `dist/htm.umd.js` |

Taken from the npm registry tarballs (`npm pack preact@10.29.8 htm@3.1.1`). To upgrade: replace
the three files from the new tarballs, update `SHA256SUMS`, this table and the registry entry,
and run `tests/test_simple_mode.py`. The `sourceMappingURL` comments are upstream's; the map
files are not shipped, so a browser's developer tools may report them missing.

**Provenance check, 2026-11-13.** The two tarballs were downloaded from registry.npmjs.org and their
sha512 matched the registry's published `dist.integrity`; the three vendored files and both licence
texts are byte-identical (`cmp`) to the files at the upstream paths above.

| Tarball | Registry `dist.integrity` |
|---|---|
| `preact-10.29.8.tgz` | `sha512-ej2aVZ+vZ8WO7tvlQWRM9N63A0KzF9q4mWJfDUHgYaIofWY9hu74QdnQrjoPMmZi2/nZ5gN0bJCQF49xQqx09Q==` |
| `htm-3.1.1.tgz` | `sha512-983Vyg8NwUE7JkZ6NmOqpCZ+sh1bKv2iYTlUkzlWmA5JD2acKoxd4KVxbMmxX/85mtfdnDmTFoNKcg5DGAvxNQ==` |
