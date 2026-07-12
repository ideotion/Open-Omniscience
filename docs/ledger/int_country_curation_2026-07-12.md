# `int`/`eu` country curation for transnational sources — S5.5 (2026-07-12)

Follow-up to B12 (the "Global" region for `int`/`eu`): individual International sources still
lacked a `country:` field, so they were invisible to the regional-balance report. An Explore
agent swept `configs/sources.yml` for **unambiguous** intergovernmental / transnational bodies
that had no country; every candidate was then HAND-VERIFIED against its domain (the
wrong-country-is-worse-than-none rule). Applied deterministically; a differing local value is
never overwritten.

## Applied (22)

`country: int` — UN system, Bretton Woods, and regional/global IGOs whose feed IS the org's own:

ASEAN News · African Union News (au.int) · Organization of American States (OAS) News ·
Shanghai Cooperation Organisation (SCO) News · IAEA News (iaea.org) · WTO News ·
European Court of Human Rights (ECtHR) News (Council of Europe, 46 states) · World Bank Data
Blog · World Bank - Agriculture · FAO News · World Food Programme (WFP) News · UNFCCC News ·
World Meteorological Organization (WMO) News · UNESCO - Ethics of AI · UNESCO - Lucha contra la
Desinformación (en Español) · UN-Water · UNICEF Water Scarcity · UNEP Water Scarcity · OPEC News
(opec.org) · IMF Blog

`country: eu` — EU institutions (both `int` and `eu` map to the "Global" region; `eu` is the
more precise code):

European Commission Press Corner (ec.europa.eu) · EU Sanctions Map (sanctionsmap.eu)

## Dropped (hand-verification caught it)

- **G7/G20 News** — the domain is `g7uk.com`, the UK's rotating-presidency site: a NATIONAL
  source, not a permanent transnational body. Tagging it `int` would be a wrong country. Left
  uncountried (honest).

## Excluded by the sweep as ambiguous (recorded, not applied)

- EU Robotics, EU DisinfoLab — research networks / think tanks associated with EU institutions,
  not the intergovernmental bodies themselves.

Applied by `scripts` (textual insert, no reformat); guarded so an entry that already carries a
country is never touched. Populating the many other individual `int` sources remains an ongoing
data-curation step.
