# Open Omniscience User Guide

**Version:** 0.2.0
**Last Updated:** May 7, 2026

This guide will help you **install, configure, and use** Open Omniscience for investigative journalism, research, and data analysis.

---

## 📖 Table of Contents
1. [Introduction](#-introduction)
2. [Installation](#-installation)
3. [Configuration](#-configuration)
4. [Using the GUI](#-using-the-gui)
5. [Advanced Search](#-advanced-search)
6. [Exporting Data](#-exporting-data)
7. [Ethical Guidelines](#-ethical-guidelines)
8. [Troubleshooting](#-troubleshooting)
9. [FAQ](#-faq)

---

## 🌟 Introduction

Open Omniscience is an **open-source global intelligence platform** designed to help journalists, researchers, and analysts **aggregate, search, and analyze news articles** from around the world. It prioritizes **ethical scraping**, **data integrity**, and **user privacy**.

### Key Features:
- **Scrape 100+ news sources** (RSS and HTML).
- **Advanced search** with Boolean operators, filters, and pagination.
- **Visualize data** with interactive charts.
- **Export data** in CSV, JSON, or SQLite formats.
- **Audit logging** for transparency and compliance.

---

## 💻 Installation

### Prerequisites
- **Operating System:** Linux (recommended), macOS, or Windows (WSL).
- **Python:** 3.10 or higher.
- **Hardware:** At least 4GB RAM and 10GB free disk space (for large datasets).

### Step-by-Step Installation

#### 1. Clone the Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience
```

#### 2. Set Up a Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\activate   # Windows
```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Initialize the Database
For **SQLite** (default, no setup required):
```bash
mkdir -p data/
```
The database (`data/open_omniscience.db`) will be created automatically on first run.

For **PostgreSQL** (recommended for production):
1. Install PostgreSQL (see [DATABASE.md](DATABASE.md)).
2. Create a database and user:
   ```bash
   sudo -u postgres psql
   ```
   In the PostgreSQL shell:
   ```sql
   CREATE DATABASE open_omniscience;
   CREATE USER open_omniscience WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO open_omniscience;
   \q
   ```
3. Set the `DATABASE_URL` environment variable:
   ```bash
   export DATABASE_URL="postgres://open_omniscience:your_password@localhost:5432/open_omniscience"
   ```
4. Run the migrations:
   ```bash
   cd src/database
   alembic upgrade head
   ```

#### 5. Start the Application
```bash
uvicorn src.api.main:app --reload
```
- Open your browser and navigate to `http://localhost:8000`.
- The GUI will load automatically.

---

## ⚙️ Configuration

### Configuring News Sources
Edit `configs/sources.yml` to:
- **Add/remove sources**.
- **Adjust rate limits** (e.g., `rate_limit_ms: 2000` for 2 seconds between requests).
- **Enable/disable sources** (`enabled: true/false`).
- **Set priorities** (`priority: 1` for high-priority sources).

Example:
```yaml
sources:
  - name: "BBC News"
    domain: "bbc.com"
    rss_url: "http://feeds.bbci.co.uk/news/rss.xml"
    rate_limit_ms: 1000
    enabled: true
    priority: 1
    tags: ["news", "uk"]
```

> **⚠️ Note:** Always check `robots.txt` for a domain before adding it. See [ETHICS.md](../ETHICS.md) for the **Do Not Scrape List**.

### Adjusting Rate Limits
- **Per-source rate limits**: Set in `sources.yml` (e.g., `rate_limit_ms: 2000`).
- **Global API rate limits**: Set in `src/api/main.py` (e.g., `@limiter.limit("100/hour")`).

### Changing the Database
To switch from SQLite to PostgreSQL (or vice versa):
1. Update `DATABASE_URL` in `src/database/models.py` or set the environment variable:
   ```bash
   export DATABASE_URL="postgres://user:password@localhost:5432/dbname"
   ```
2. Run the migrations:
   ```bash
   cd src/database
   alembic upgrade head
   ```

---

## 🖥️ Using the GUI

### Overview
The GUI is a **responsive web interface** that allows you to:
- Search and filter articles.
- Visualize data with charts.
- Export results.
- Configure settings.

### Layout
1. **Header**: Title, subtitle, and settings/theme buttons.
2. **Search Section**: Form to search and filter articles.
3. **Analytics Section**: Visualizations (articles by source, articles over time).
4. **Results Section**: Table of search results with pagination.

### Search Form
| Field | Description | Example |
|-------|-------------|---------|
| **Search Query** | Keywords to search in article content. Supports **Boolean operators** (AND, OR, NOT) and **exact phrases** (`"phrase"`). | `climate AND change NOT politics` |
| **Source** | Filter by news source. | `BBC News` |
| **Language** | Filter by language code. | `en` (English), `fr` (French) |
| **Tags** | Filter by source tags (comma-separated). | `news, geopolitical` |
| **Start Date** | Filter by start date (YYYY-MM-DD). | `2026-05-01` |
| **End Date** | Filter by end date (YYYY-MM-DD). | `2026-05-07` |

### Buttons
| Button | Description |
|--------|-------------|
| **Search** | Execute the search query. |
| **Export CSV** | Export results as a CSV file. |
| **Export JSON** | Export results as a JSON file. |
| **Clear** | Reset all filters. |
| **Settings** | Open the settings modal. |
| **Theme Toggle** | Switch between light/dark mode. |

### Pagination
- Use **Previous** and **Next** buttons to navigate through results.
- The current page and total pages are displayed in the middle.

---

## 🔍 Advanced Search

### Boolean Operators
Open Omniscience supports **Boolean operators** for advanced queries:

| Operator | Example | Description |
|----------|---------|-------------|
| `AND` | `climate AND change` | Articles containing **both** "climate" **and** "change". |
| `OR` | `climate OR weather` | Articles containing **either** "climate" **or** "weather". |
| `NOT` | `climate NOT politics` | Articles containing "climate" **but not** "politics". |
| `" "` | `"climate change"` | Articles containing the **exact phrase** "climate change". |

### Examples
| Query | Description |
|-------|-------------|
| `climate AND change` | Articles about climate change. |
| `climate OR weather` | Articles about climate or weather. |
| `climate NOT politics` | Articles about climate but not politics. |
| `"climate change" AND (impact OR effect)` | Articles about the impact or effect of climate change. |
| `source:BBC AND language:en` | Articles from BBC in English. |

---

## 📤 Exporting Data

### Export Formats
| Format | Description | Use Case |
|--------|-------------|----------|
| **CSV** | Comma-separated values. | Spreadsheet analysis (Excel, Google Sheets). |
| **JSON** | JavaScript Object Notation. | Programmatic analysis, APIs. |
| **SQLite** | Direct database export. | Backup, migration, or local analysis. |

### How to Export
1. **Apply your search filters** (query, source, date, etc.).
2. Click **Export CSV** or **Export JSON**. 
3. The file will download automatically with a name like `articles_2026-05-07.csv`.

> **⚠️ Note:** Exports are limited to **50 requests/hour** to prevent abuse.

---

## 📜 Ethical Guidelines

Open Omniscience is committed to **ethical, legal, and responsible** data aggregation. As a user, you must:

### ✅ Do:
- **Respect `robots.txt`**: Always check [https://{domain}/robots.txt](https://{domain}/robots.txt) before scraping.
- **Use rate limiting**: Default is **1 request per second per domain**. Adjust for sensitive sites.
- **Attribute sources**: Always credit the original source when sharing data.
- **Comply with laws**: Respect copyright, GDPR, and other regulations in your jurisdiction.

### ❌ Do Not:
- **Scrape paywalled content** (e.g., `nytimes.com`, `ft.com`).
- **Scrape social media** (e.g., `facebook.com`, `twitter.com`).
- **Scrape private/sensitive data** (e.g., medical records, government databases).
- **Use for spam/harassment**: Open Omniscience is for **research and journalism only**. 
- **Violate terms of service**: Respect the terms of all scraped websites.

### 📋 Compliance Checklist
Before scraping a new source, ask yourself:
- [ ] Is the domain **not** in the [Do Not Scrape List](../ETHICS.md#do-not-scrape-list)?
- [ ] Does `robots.txt` allow scraping?
- [ ] Is the source **publicly accessible** (no paywall or authentication)?
- [ ] Are rate limits **configured appropriately**?
- [ ] Is the User-Agent **identifiable** (e.g., `OpenOmniscience/1.0`)?

> **📌 Tip:** When in doubt, **do not scrape**. Use official APIs or manual methods instead.

---

## 🚨 Troubleshooting

### Common Issues

#### 1. Database Not Found
**Error:**
```
sqlite3.OperationalError: unable to open database file
```
**Solution:**
- Ensure the `data/` directory exists:
  ```bash
  mkdir -p data/
  ```
- Check file permissions:
  ```bash
  chmod 755 data/
  ```

#### 2. Missing Dependencies
**Error:**
```
ModuleNotFoundError: No module named 'fastapi'
```
**Solution:**
Install the missing dependencies:
```bash
pip install -r requirements.txt
```

#### 3. Port Already in Use
**Error:**
```
OSError: [Errno 98] Address already in use
```
**Solution:**
- Find and kill the process using port 8000:
  ```bash
  lsof -i :8000
  kill -9 <PID>
  ```
- Use a different port:
  ```bash
  uvicorn src.api.main:app --reload --port 8001
  ```

#### 4. Scraping Blocked by `robots.txt`
**Error:**
```
Scraping blocked by robots.txt for {source}
```
**Solution:**
- Check the domain's `robots.txt` file (e.g., `https://example.com/robots.txt`).
- If the domain disallows scraping, **remove it from `sources.yml`**. 
- If you believe the domain should be scrapable, **open an issue** on GitHub.

#### 5. Rate Limit Exceeded
**Error:**
```
Too many requests. Please wait and try again.
```
**Solution:**
- Wait **1 hour** before trying again.
- Reduce the number of requests by:
  - Increasing `rate_limit_ms` in `sources.yml`.
  - Scraping fewer sources at once.

#### 6. PostgreSQL Connection Failed
**Error:**
```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection to server at "localhost" (::1) failed
```
**Solution:**
- Ensure PostgreSQL is running:
  ```bash
  sudo systemctl status postgresql
  ```
- Verify the connection string in `DATABASE_URL`:
  ```bash
  echo $DATABASE_URL
  ```
- Test the connection manually:
  ```bash
  psql -U open_omniscience -d open_omniscience
  ```

---

## ❓ FAQ

### Q: Can I scrape any website?
**A:** No. You must comply with `robots.txt`, terms of service, and copyright laws. See [ETHICS.md](../ETHICS.md) for the **Do Not Scrape List**.

### Q: How do I add a new news source?
**A:**
1. Edit `configs/sources.yml`.
2. Add a new entry with `name`, `domain`, `rss_url` (if available), `rate_limit_ms`, and `enabled: true`.
3. Test the source by running the scraper:
   ```bash
   python src/scraper/scraper.py
   ```

### Q: Can I use Open Omniscience for commercial purposes?
**A:** The **MIT License** allows commercial use, but you must:
- Comply with all **ethical guidelines** (no scraping paywalled/sensitive data).
- **Attribute** Open Omniscience in your project.
- **Not use it for spam, harassment, or illegal activities**.

### Q: How do I update Open Omniscience?
**A:**
```bash
git pull origin main
pip install -r requirements.txt
```
If using PostgreSQL, run migrations:
```bash
cd src/database
alembic upgrade head
```

### Q: Can I contribute to Open Omniscience?
**A:** Yes! See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

### Q: How do I report a bug or request a feature?
**A:** Open an issue on [GitHub](https://github.com/ideotion/Open-Omniscience/issues).

### Q: Is my data private?
**A:** Yes. Open Omniscience **does not** collect or transmit your data. All data remains on your local machine.

### Q: Can I use Open Omniscience offline?
**A:** Yes! Once installed, Open Omniscience works **entirely offline** (except for scraping live websites).

---

## 📚 Additional Resources
- [ETHICS.md](../ETHICS.md): Ethical guidelines and compliance.
- [DATABASE.md](../docs/DATABASE.md): Database setup and configuration.
- [DEVELOPER_GUIDE.md](../docs/DEVELOPER_GUIDE.md): Guide for developers.
- [GitHub Repository](https://github.com/ideotion/Open-Omniscience): Source code and issues.
- [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions): Community Q&A.

---
**© 2026 Ideotion. All rights reserved.**