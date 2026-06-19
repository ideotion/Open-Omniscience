# Offline IP-geolocation data

The country-level IP→country table that `src/geo/ip_geo.py` reads goes here as
`dbip_country_lite.csv` (or `.csv.gz`).

It is **not committed** — it is generated on a machine **with network**, because the
DB-IP download is blocked in the CI/dev sandbox (403). Until it exists, the geolocator
honestly returns `level="unavailable"` and **never fabricates a location**.

## Generate it

```sh
python scripts/build_ip_geo.py --month YYYY-MM
# then set IP_GEO_AS_OF = "YYYY-MM" in src/geo/ip_geo.py
```

## Source & license

- **DB-IP IP-to-Country Lite** — <https://db-ip.com/db/download/ip-to-country-lite>
- License: **Creative Commons Attribution 4.0 (CC BY 4.0)** — attribution to DB-IP.com
  is **mandatory** and is carried in `src/geo/ip_geo.ATTRIBUTION` and shown by the map.
- Format: CSV rows of `start_ip,end_ip,country_code` (ISO 3166-1 alpha-2), monthly.
- **Verify** the exact current license + file size on the page above before bundling.

The **city-level** DB is larger and is a one-time *consented download into `data_dir()`*
(never bundled, never fetched at boot) — see `ip_geo._city_db_path()`.
"""
