# Markets: financial, stock-exchange, and commodity/rare-earth intelligence

Open Omniscience ships a **curated, worldwide catalog of market sources** so it is
ready to ingest financial-market coverage out of the box, and a Markets tab that
turns *configured* pages into a real, chartable price series correlated with news.

This document explains what's pre-packaged, what isn't, and why — because the
honest boundary here matters more than a long feature list.

## What is pre-packaged (ready to run as-is)

`configs/markets_sources.yml` is seeded automatically alongside the news catalog
(`configs/sources.yml`) on first launch and via **Sources & Database → Seed
starter sources**. It contains ~110 curated entries identified by stable primary
domain:

- **Stock & securities exchanges** worldwide (Americas, Europe, Asia-Pacific,
  Middle East, Africa) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE India, SGX, ASX, B3, Tadawul, JSE, and many more.
- **Commodity / metals / energy / derivatives exchanges** — CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (rare-earth & industrial-silicon futures), MCX,
  Eurex, MGEX.
- **Commodity & rare-earth price/data sources** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Financial news & data publishers** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin, and others.

These are ordinary **sources**: they feed the unified corpus through the same
ethical fetcher (robots.txt fail-closed, rate-limited). Each carries a
`source_type` (`stock_exchange` / `commodity` / `financial`), region, country and
tags, so you can filter them in **Sources & Database** and attach price rules in
**Markets**.

> RSS feeds are intentionally left blank for these entries (a wrong feed URL is
> just noise). Ingest them with the recursive crawler, or add a verified RSS feed
> per source from the Sources tab.

## Getting real price numbers

A price series is only produced where you tell the app **exactly where the number
is** — there is no magic page-reading, by design. Two honest paths:

### 1. Per-page extraction rules (Markets tab)

Add a rule (source, symbol, page URL, **CSS selector**, optional attribute /
value-regex, currency, unit), then press **Test**. Test fetches the page once and
shows the *exact* value found — or the *exact* reason it didn't match — so you can
tune the selector with real feedback. Matching rules store one `CommodityPrice`
per day, which the inline charts and price↔news correlation read.

Templates to copy: `configs/market_rules.example.yml`.

**Caveat (read this):** most exchange/quote pages render prices with JavaScript,
so the number is *not* in the static HTML the fetcher receives and a selector will
find nothing. This is why working selectors are **not** pre-shipped — guessing
them would mean fabricated numbers. Server-rendered pages (many official/statistical
sites, some data tables) work well; heavily client-rendered quote widgets do not.

### 2. Official CSV feeds (recommended — reliable, ships with a catalog)

For trustworthy numeric history, import a machine-readable CSV series from an
official source. This is the reliable path and the app ships a starter catalog
(`configs/commodity_feeds.yml`) you can import in one click from
**Markets → Official price feeds**, or via the API:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Primary provider — FRED** (Federal Reserve Bank of St. Louis): a stable,
no-API-key CSV endpoint, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
which **redistributes the World Bank "Pink Sheet" commodity series** (the
"Global price of …" IDs — copper `PCOPPUSDM`, brent `POILBREUSDM`, etc.) and
**EIA** energy series (`DCOILWTICO`, `DHHNGSP`, …). First column is the date,
second the value; missing values (`.`) are skipped, never stored as zero. Import
is idempotent per `(symbol, market, date)`.

**Comparable sources** you can add as a custom feed (URL + optional column names):
- **World Bank** Commodity Markets ("Pink Sheet"): the `.xlsx` is at
  <https://www.worldbank.org/en/research/commodity-markets>; the same series in
  clean CSV come via the FRED feeds above.
- **U.S. EIA** energy open data: <https://www.eia.gov/opendata/>
- **IMF** Primary Commodity Prices: <https://www.imf.org/en/Research/commodity-prices>
- **USGS** mineral commodity data (rare earths): <https://www.usgs.gov/centers/national-minerals-information-center>

The default column mapping is column 1 = date, column 2 = value (the FRED
convention); name `date_column` / `value_column` explicitly for other layouts.

There is also a direct file-upload path for a CSV you already have:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> If a provider renames or retires a series, the import fails **loudly** (HTTP
> error / no usable rows) rather than inventing data — fix the URL in
> `configs/commodity_feeds.yml` or use a custom feed.

## Why no auto-extracted prices on day one?

Because a number with no verifiable origin is worse than no number. Everything in
this tool is built so that a figure shown to the user came from a real
measurement: a selector that actually matched, or a CSV that was actually
imported. The catalog gets you the *sources* instantly; you decide, per page, when
a price is trustworthy enough to record.
