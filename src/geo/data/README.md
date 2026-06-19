# Offline IP-geolocation data

`dbip_country_lite.csv.gz` — the bundled country-level IP→country table that
`src/geo/ip_geo.py` reads (binary-searched, IPv4 + IPv6).

## Source & license

- **DB-IP IP-to-Country Lite** — <https://db-ip.com/db/download/ip-to-country-lite>
- License: **Creative Commons Attribution 4.0 (CC BY 4.0)** — attribution to DB-IP.com
  is **mandatory** and is carried in `src/geo/ip_geo.ATTRIBUTION` and shown by the map.
- Format: rows of `start_ip,end_ip,country_code` (ISO 3166-1 alpha-2).
- **Vintage:** see `IP_GEO_AS_OF` in `src/geo/ip_geo.py` (a freshness test pins it within
  a sane window, like the model catalog).

The official db-ip.com download is rate-limited / 403 from CI, so the bundled file is
sourced from the DB-IP **CC BY 4.0 mirror** in
[`sapics/ip-location-db`](https://github.com/sapics/ip-location-db) (`dbip-country/`,
identical format). Re-geolocation against a fresher table is a **new vintage**, never an
overwrite.

## Refresh it

```sh
python scripts/build_ip_geo.py --mirror          # from the sapics CC BY 4.0 mirror
python scripts/build_ip_geo.py --month YYYY-MM    # from db-ip.com (needs network access)
# then set IP_GEO_AS_OF = "YYYY-MM" in src/geo/ip_geo.py
```

The **city-level** DB is larger and is a one-time *consented download into `data_dir()`*
(never bundled, never fetched at boot) — see `ip_geo._city_db_path()`.
