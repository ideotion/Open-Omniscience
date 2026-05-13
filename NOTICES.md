# Third-Party Notices and Attributions

This file contains notices and attributions for third-party software and libraries used by Open Omniscience.

---

## 📜 HTTrack Web Crawler

**Project:** HTTrack (https://www.httrack.com/)
**License:** GNU General Public License Version 3 (GPLv3)
**Source:** https://github.com/xroche/httrack
**Our Use:** External dependency (command-line tool and optional C library)

### Description

Open Omniscience uses HTTrack as an **external dependency** for web crawling and website mirroring capabilities. HTTrack is a free (GPLv3) and easy-to-use offline browser utility.

### Compliance

Open Omniscience complies with HTTrack's GPLv3 license by:

1. ✅ **Using GPLv3 License**: Open Omniscience is licensed under GNU GPLv3, which is compatible with HTTrack's license
2. ✅ **Providing Source Code**: All Open Omniscience source code is available under GPLv3
3. ✅ **Attribution**: Proper attribution is given to HTTrack in this file and in the project documentation
4. ✅ **No Modifications to HTTrack**: Open Omniscience does not modify or distribute HTTrack source code

### Usage in Open Omniscience

Open Omniscience interacts with HTTrack in two ways:

1. **Command-Line Interface**: The `pillar1/src/httrack_wrapper.py` module calls HTTrack as an external command-line tool
2. **Optional C Library**: The wrapper can optionally load HTTrack's C library (`libhttrack.so`, `httrack.dll`, etc.) for direct integration

### Installation

To use Open Omniscience with HTTrack functionality:

```bash
# On Debian/Ubuntu
sudo apt-get install httrack

# On Fedora/RHEL
sudo dnf install httrack

# On macOS (using Homebrew)
brew install httrack

# Or download from official website
wget https://www.httrack.com/page/2/en/index.html
```

### HTTrack License Text

HTTrack is licensed under the GNU General Public License Version 3. The full text of the GPLv3 license can be found in the [LICENSE](LICENSE) file of this project, which is the same license used by HTTrack.

---

## 📦 Python Dependencies

Open Omniscience uses various Python packages, each with their own licenses. The following is a summary of the main dependencies and their licenses:

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

- All Python dependencies are **separate works** and are not modified by Open Omniscience
- Each dependency maintains its own license
- Open Omniscience's GPLv3 license does not affect the licenses of these dependencies
- Users must comply with each dependency's individual license when using them

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

1. **HTTrack**: Ensure HTTrack is installed and accessible in your system PATH
2. **Python Dependencies**: Run `pip list` to see all installed packages and their licenses
3. **Source Code**: All Open Omniscience source code is available in this repository

---

## 📞 Contact

For questions about third-party licenses or compliance:
- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Last Updated:** June 2025
