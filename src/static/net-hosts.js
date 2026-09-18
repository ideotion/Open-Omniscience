/*
 * Open Omniscience — the ONE table of hosts this app can reach, per lane.
 * GPL-3.0-or-later.
 *
 * Q1001 + Q1002 (ruled 2026-09-15). The consent popup's hover reads this table,
 * and so does `tests/test_security_endpoint_enumeration.py`, which pins it against
 * the "full set of endpoints the app can reach" table in docs/SECURITY.md. One
 * source of truth, never two lists: a PR that adds a host has to touch this file
 * and that document in the same diff, or the test reddens by name.
 *
 * THE LITERAL BELOW IS STRICT JSON ON PURPOSE. It is valid JS and valid JSON at
 * once, so the Python guard reads exactly what the browser parses — no quoting
 * convention to agree on, no transformation that could silently drop a row. That
 * is why there are no comments, no trailing commas and no bare keys inside it;
 * everything explanatory lives here, above it.
 *
 * NO PROSE IN THE TABLE. Every user-facing sentence is built by app-core.js
 * through OOI18N.t and ships x12, because a hover is a caveat surface and the
 * informed-consent non-negotiable puts every caveat in twelve locales. What the
 * table carries is LITERAL TOKENS ONLY — host names, config paths, settings keys —
 * plus `label`, which is deliberately three things at once: the row name in
 * docs/SECURITY.md, the i18n key, and the lane's identity in the guard. Because
 * `t(lane.label)` is a variable call site, the --max-unkeyed-t-calls ratchet
 * cannot see it; the guard asserts every label has a key in all twelve locales
 * instead, which is the stronger check and the reason the blind spot is safe.
 *
 * NO NETWORK. This file is data. It fetches nothing and calls nothing.
 *
 * Fields:
 *   id         stable machine name (never displayed)
 *   label      the SECURITY.md row name AND the i18n key (see above)
 *   hosts      the hosts this lane can reach, enumerated where enumerable
 *   hostsFrom  config files whose entries ARE the reach, when it is a class
 *   hostCount  distinct hosts across `hostsFrom` — pinned by the guard against
 *              the real files, so it can never quietly go stale
 *   trigger    "pass" | "ride-along" | "click" | "opt-in"
 *   setting    the settings key that switches this lane off, or null
 *   settingFrom which loopback settings payload that key lives in:
 *              "scheduler" | "safety" | "custody"
 *   settingOn  the exact value that means ON, when the key is not a boolean or a
 *              per-pass budget (the custody anchoring mode is the only one)
 *   noOptOut   true when the code reads a toggle that does not exist as a field,
 *              so the lane cannot be switched off today (recorded 2026-09-16)
 *   settingUnreachable
 *              true when the field DOES exist and is honoured by save_settings,
 *              but PUT /api/scheduler/config's request model does not declare it,
 *              so Pydantic drops it and the endpoint returns 200 having changed
 *              nothing. A different fact from noOptOut, and a worse one: the
 *              operator is told the opt-out succeeded (recorded 2026-09-16)
 *   fetcher    false when the lane does NOT use the ethical fetcher; the hover
 *              then says what it uses instead
 */
(function (root) {
  "use strict";

  const OO_NET_LANES = [
    {
      "id": "press",
      "label": "Press collection",
      "hosts": [],
      "hostsFrom": ["configs/sources.yml", "configs/academic_sources.yml", "configs/official_sources.yml", "configs/sources_spectrum.yml", "configs/markets_sources.yml"],
      "hostCount": 9033,
      "trigger": "pass",
      "setting": null,
      "fetcher": true
    },
    {
      "id": "discovery",
      "label": "Source discovery",
      "hosts": ["query.wikidata.org", "www.wikidata.org"],
      "trigger": "ride-along",
      "setting": "world_discovery_per_pass",
      "settingFrom": "scheduler",
      "fetcher": true
    },
    {
      "id": "wikipedia",
      "label": "Wikipedia / Wikimedia",
      "hosts": ["*.wikipedia.org", "stream.wikimedia.org", "wikimedia.org", "ores.wikimedia.org", "dumps.wikimedia.org"],
      "trigger": "ride-along",
      "setting": "wiki_lane_state",
      "settingFrom": "scheduler",
      "settingOn": "running",
      "fetcher": true
    },
    {
      "id": "osm",
      "label": "Maps / OpenStreetMap",
      "hosts": ["download.geofabrik.de", "planet.openstreetmap.org"],
      "trigger": "click",
      "setting": null,
      "fetcher": true
    },
    {
      "id": "law",
      "label": "Law",
      "hosts": [],
      "hostsFrom": ["configs/legal_sources.yml", "configs/legal_sources_generated.yml"],
      "hostCount": 260,
      "trigger": "ride-along",
      "setting": "auto_track_law",
      "settingFrom": "scheduler",
      "noOptOut": true,
      "fetcher": true
    },
    {
      "id": "statistics",
      "label": "Official statistics",
      "hosts": ["api.worldbank.org", "ec.europa.eu", "ourworldindata.org"],
      "trigger": "ride-along",
      "setting": "country_data_per_pass",
      "settingFrom": "scheduler",
      "fetcher": true
    },
    {
      "id": "markets",
      "label": "Markets & commodities",
      "hosts": ["fred.stlouisfed.org", "www.eia.gov", "www.imf.org", "www.worldbank.org"],
      "trigger": "ride-along",
      "setting": null,
      "noOptOut": true,
      "fetcher": true
    },
    {
      "id": "calendar",
      "label": "Calendars",
      "hosts": ["date.nager.at", "www.openholidaysapi.org", "www.officeholidays.com", "www.calendarlabs.com", "www.hebcal.com", "litcal.johnromanodorazio.com", "worldpublicholiday.com", "fosdem.org", "f1calendar.com", "www.matchesio.com", "www.rocketlaunch.live", "pirate.monkeyness.com", "raw.githubusercontent.com", "jonamarkin.github.io"],
      "trigger": "ride-along",
      "setting": "auto_import_calendars",
      "settingFrom": "scheduler",
      "noOptOut": true,
      "fetcher": true
    },
    {
      "id": "hazards",
      "label": "Hazard feeds",
      "hosts": ["earthquake.usgs.gov", "www.gdacs.org"],
      "trigger": "ride-along",
      "setting": "auto_track_signals",
      "settingFrom": "scheduler",
      "settingUnreachable": true,
      "fetcher": true
    },
    {
      "id": "keyword-rings",
      "label": "Keyword translations",
      "hosts": ["www.wikidata.org"],
      "trigger": "click",
      "setting": null,
      "fetcher": true
    },
    {
      "id": "weather",
      "label": "Weather",
      "hosts": ["archive-api.open-meteo.com"],
      "trigger": "click",
      "setting": null,
      "fetcher": true
    },
    {
      "id": "topic-discovery",
      "label": "Discover by topic",
      "hosts": ["html.duckduckgo.com"],
      "trigger": "opt-in",
      "setting": "discovery_external_enabled",
      "settingFrom": "safety",
      "fetcher": true
    },
    {
      "id": "ai",
      "label": "Local AI install & weights",
      "hosts": ["api.github.com", "objects.githubusercontent.com", "huggingface.co", "pypi.org"],
      "trigger": "click",
      "setting": null,
      "fetcher": false
    },
    {
      "id": "mail",
      "label": "Newsletter mailbox",
      "hosts": [],
      "trigger": "click",
      "setting": null,
      "fetcher": false
    },
    {
      "id": "custody",
      "label": "Chain of custody",
      "hosts": ["a.pool.opentimestamps.org", "b.pool.opentimestamps.org", "alice.btc.calendar.opentimestamps.org"],
      "trigger": "opt-in",
      "setting": "anchoring_mode",
      "settingFrom": "custody",
      "settingOn": "opentimestamps",
      "fetcher": false
    }
  ];

  root.OO_NET_LANES = OO_NET_LANES;
  if (typeof module === "object" && module.exports) { module.exports = { OO_NET_LANES }; }
})(typeof globalThis !== "undefined" ? globalThis : this);
