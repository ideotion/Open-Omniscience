# Third-Party Notices and Attributions

**⚠️ EARLY CONCEPT RELEASE - SOFTWARE NOT FUNCTIONAL ⚠️**

**Originally Forked From:** [HTTrack](https://www.httrack.com/) - This project was initially a fork of HTTrack website copier

> ⚠️ **IMPORTANT NOTICE**: Open Omniscience is currently in an **early concept release** that is **completely unusable**. The software **does not work** and requires **extensive debugging and development** before it can be used. The third-party dependencies listed below are part of the intended design for when the project becomes functional.

This file contains notices and attributions for third-party software and libraries **intended to be used** by Open Omniscience **when it becomes functional**.

---

## 📦 Python Dependencies (Intended)

Open Omniscience is intended to use various Python packages, each with their own licenses **when implemented**. The following is a summary of the main dependencies and their licenses:

| Package | License | Purpose |
|---------|---------|---------|
| FastAPI | BSD-3-Clause | Web API framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| SQLAlchemy | MIT | Database ORM |
| Requests | Apache-2.0 | HTTP requests |
| BeautifulSoup4 | MIT | HTML parsing |
| Feedparser | BSD-3-Clause | RSS/Atom parsing |
| Pydantic | MIT | Data validation |
| SlowAPI | BSD-3-Clause | Rate limiting |
| Prometheus Client | Apache-2.0 | Metrics monitoring |
| Bleach | Apache-2.0 | HTML sanitization |
| Passlib | BSD-3-Clause | Password hashing |

### Compliance Notes

- All Python dependencies would be **separate works** and would not be modified by Open Omniscience *when implemented*
- Each dependency maintains its own license
- Open Omniscience's GPLv3 license would not affect the licenses of these dependencies *when implemented*
- Users would need to comply with each dependency's individual license when using them *when the software is functional*

---

## 📄 Fonts and Icons

| Resource | License | Source |
|----------|---------|--------|
| Project Icon | MIT (original) | Included in project |

---

## 📝 Data Sources

Open Omniscience aggregates data from various news sources. Users are responsible for:

1. Respecting the **copyright** of scraped content
2. Complying with **terms of service** of each website
3. Following **robots.txt** directives
4. Adhering to **ethical scraping** guidelines (see [ETHICS.md](ETHICS.md))

**Note:** The GPLv3 license of Open Omniscience does **not** apply to the data scraped using the software. Users are solely responsible for ensuring their use of scraped data complies with all applicable laws and regulations.

---

## 🔍 Verification

To verify compliance with third-party licenses:

1. **Python Dependencies**: Run `pip list` to see all installed packages and their licenses
2. **Source Code**: All Open Omniscience source code is available in this repository

---

## 📞 Contact

For questions about third-party licenses or compliance:
- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Last Updated:** June 2025
