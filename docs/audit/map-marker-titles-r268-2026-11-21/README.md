# Map marker hovers reach touch readers too (row 268)

Gate row D's exit item puts every located datum on the map, and a located infobox address carries its
provenance in its hover: the address as written, the infobox field, the page and edition, the OpenStreetMap
object and the extract's date. That hover rode an SVG `<title>` child, which only a mouse reaches. The shared
bubble of invariant #17 (`#oo-tip`) marks elements with a `title` ATTRIBUTE and opens on hover, keyboard focus
and touch long-press, as the contested layer already does (row R, R9). Walked in Chromium on 2026-11-21.

## What changed

Every marker `src/static/app-map.js` draws now carries its hover in a `title` attribute, and none in a `<title>`
child:

* the Wikipedia page marker and the located infobox-address square (`_ooWikiLayer`, `_ooWikiAddrMarker`);
* the mentioned-place circles and the server-IP squares (two statements inside `ooMap`);
* the signal shapes (`_ooSigMarker`) and the Insights cities map (`buildMapSvg`).

`tests/map_marker_titles_r268_node_test.js` and `tests/wiki_map_layer_node_test.js` run each one from the
shipped source and fail if `app-map.js` builds a `<title>` child again; `tests/test_map_marker_titles_r268.py`
runs both.

## The walk

The app was booted on 127.0.0.1 from a seeded plaintext state. The two wiki lane answers
(`/api/wiki/lane/places`, `/api/wiki/lane/located-addresses`) are a FIXTURE routed in the browser: one page
(Rome) and two addresses, one whose extract is dated and one whose extract states no date. What is walked here is
the drawing and the bubble; the server's located-address path has its own tests. Scripts: `walk.js` (this
branch) and `before.js` (the same long-press on `main`'s `app-map.js`).

| Check | `main` before | This branch |
|---|---|---|
| Address square has a `title` attribute and is a bubble target | no (`<title>` child only) | yes, 3 of 3 markers, 0 `<title>` children |
| Mouse hover on the dated address | browser's native tooltip only | bubble: "2 Rue Fixture, Paris, from the adresse field of Salle Fixture (fr). Located at OpenStreetMap way/42, extract of 2026-10-01." |
| Mouse hover on the undated address | browser's native tooltip only | bubble ends "the extract states no date." |
| Touch long-press on the dated address (412 px phone) | bubble showed "Belgium — 51 sources", a country's hover, never the address | bubble shows the full provenance, as above |

Results: `walk.json`, `before-main.json`. Screenshots (each under 200 KB): `desktop-hover-dated-address.jpg`,
`desktop-hover-undated-address.jpg`, `desktop-hover-page.jpg`, `phone-long-press-dated-address.jpg`. No page
errors in either run.

## Not changed here

Keyboard focus: an SVG marker is not focusable, so the bubble's focus path does not reach it, as for the
contested areas. Other charts outside the map module (`app-library.js`, `app-insights.js`, `app-corpus.js`,
`app-analysis.js`) still use `<title>` children; they are named for a follow-up row.
