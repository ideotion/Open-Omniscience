# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.2.0 (MVP)
**License:** [MIT](LICENSE)

![Open Omniscience Logo](https://via.placeholder.com/150?text=Open+Omniscience)

---

## 🌟 Mission

Open Omniscience is an **ethically impeccable**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.

This project is a **Linux-based application** built as a fork of [HTTrack](https://www.httrack.com/), leveraging its robust crawling capabilities while adding advanced features for **ethical scraping**, **duplicate detection**, and **data management**.

---

## ⚠️ Disclaimer

**Open Omniscience** is a tool designed for **ethical, legal, and responsible** data aggregation and analysis. By using this software, you agree to comply with the following:

1. **Respect all applicable laws** in your jurisdiction, including copyright and data protection regulations.
2. **Adhere to `robots.txt` directives** and terms of service of all scraped websites.
3. **Use the platform for non-commercial, non-malicious purposes only**.
4. **Ensure ethical use** as outlined in [ETHICS.md](ETHICS.md).

The maintainers of Open Omniscience **do not endorse or assume responsibility** for any misuse of this tool.

---

## 🚀 Getting Started

### Prerequisites
- **Operating System:** Linux (recommended), macOS, or Windows (WSL)
- **Python:** 3.10+
- **Dependencies:** See [requirements.txt](requirements.txt)
- **Database:** SQLite (default) or PostgreSQL (recommended for production)

### Installation

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
For **SQLite** (default):
```bash
mkdir -p data/
# The database will be created automatically on first run
```

For **PostgreSQL** (recommended for production):
1. Install PostgreSQL (see [DATABASE.md](docs/DATABASE.md)).
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
- The GUI will be available at `http://localhost:8000`.
- The API will be available at `http://localhost:8000/api/`.

---

## 📁 Project Structure
```
Open-Omniscience/
├── README.md               # Project documentation
├── ETHICS.md               # Ethical guidelines and compliance
├── LICENSE                 # MIT License
├── requirements.txt        # Python dependencies
├── configs/
│   ├── sources.yml         # News sources configuration
│   └── settings.yaml       # User preferences and rate limits
├── src/
│   ├── scraper/            # Web scraping logic
│   │   └── scraper.py      # Pure Python scraper (requests + BeautifulSoup + feedparser)
│   ├── ingestor/           # Data ingestion pipeline
│   │   ├── url_utils.py    # URL canonicalization and hashing
│   │   └── import.py       # Bulk data import (CSV/JSON)
│   ├── database/           # Database models and ORM (SQLAlchemy + SQLite/PostgreSQL)
│   │   ├── models.py       # Database models
│   │   └── migrations/      # Alembic migrations
│   ├── api/                # FastAPI backend for the GUI
│   │   └── main.py         # API endpoints and static file serving
│   ├── utils/              # Utility modules
│   │   └── logging_config.py # Centralized logging
│   └── static/             # Frontend assets
│       ├── index.html      # HTML5 frontend
│       ├── script.js       # Frontend JavaScript
│       └── style.css       # Frontend styles
├── data/                  # Local storage for scraped data (SQLite)
├── audit/                 # Audit logs and compliance tracking
├── tests/                 # Unit and integration tests
└── docs/                  # Documentation
    ├── USER_GUIDE.md      # User guide (WIP)
    ├── DEVELOPER_GUIDE.md  # Developer guide (WIP)
    └── DATABASE.md        # Database setup and configuration
```

---

## 🛠️ Configuration

### Sources
Edit `configs/sources.yml` to add, remove, or modify news sources. Example:
```yaml
sources:
  - name: "BBC News"
    domain: "bbc.com"
    rss_url: "http://feeds.bbci.co.uk/news/rss.xml"
    rate_limit_ms: 1000  # 1 second between requests
    enabled: true
    priority: 1          # 1 = high, 3 = low
    tags: ["news", "uk"]
```

### Rate Limiting
- Default: **1 request per second per domain** (adjustable in `sources.yml`).
- Global rate limiting: **100 requests/hour** for the API (adjustable in `main.py`).

### Database
- **SQLite**: Default, portable, no setup required.
- **PostgreSQL**: Recommended for production. See [DATABASE.md](docs/DATABASE.md).

---

## 🔍 Features

### ✅ Phase 1 (MVP - Complete)
| Feature | Description |
|---------|-------------|
| **Global Scraping** | Ingest articles from **100+ predefined sources** (RSS and HTML). |
| **Ethical Scraping** | Respects `robots.txt`, rate limits, and User-Agent identification. |
| **Duplicate Detection** | URL canonicalization + content hashing (SHA-256). |
| **SQLite/PostgreSQL** | Portable (SQLite) or scalable (PostgreSQL) storage. |
| **Advanced Search** | Full-text search with **Boolean operators** (AND, OR, NOT), filters (date, source, language, tags), and pagination. |
| **Export** | CSV, JSON, and SQLite dump. |
| **GUI** | Modern, responsive web interface with **visualizations** (Recharts). |
| **Audit Logging** | Detailed logs for all scraping activities (`audit/` directory). |
| **Parallel Scraping** | Multi-threaded scraping for improved performance. |
| **Error Handling** | Retries failed requests with exponential backoff. |

### 🚧 Phase 2 (Future)
| Feature | Status | Description |
|---------|--------|-------------|
| **AI-Powered Analysis** | Planned | Sentiment analysis, topic modeling, and entity extraction. |
| **Real-Time Monitoring** | Planned | Alerts for new articles matching saved queries. |
| **Collaborative Tagging** | Planned | Shared datasets and community tagging. |
| **API Authentication** | Planned | User accounts and API keys for rate limiting. |
| **Plugin System** | Planned | Custom scrapers, analyzers, and exporters. |

---

## 📜 Ethical Guidelines
Open Omniscience is committed to **ethical, legal, and responsible** data aggregation. See [ETHICS.md](ETHICS.md) for:
- **Munich Charter** principles for journalism.
- **Compliance checklist** for scraping.
- **Do Not Scrape List** (paywalled, social media, sensitive data).
- **Audit and accountability** requirements.
- **Privacy and data protection** policies.

> **⚠️ Important:** Violating these guidelines may result in **legal consequences** and **revocation of access**.

---

## 🤝 Contributing
We welcome contributions from the community! Please read our [Contribution Guidelines](CONTRIBUTING.md) before getting started.

### How to Contribute:
1. **Fork the repository** and create a feature branch.
2. **Follow the code style** (PEP 8 for Python, ESLint for JavaScript).
3. **Write tests** for new features.
4. **Document your changes** in the code and README.
5. **Submit a pull request** with a clear description.

### Areas for Contribution:
- **New Sources**: Add more news sources to `sources.yml`.
- **Scraping Improvements**: Better HTML/RSS parsing, anti-blocking measures.
- **UI/UX**: Improve the frontend (React, charts, accessibility).
- **Performance**: Optimize database queries, scraping speed.
- **Documentation**: Improve guides, tutorials, and examples.
- **Testing**: Add more unit/integration tests.

---

## 📄 License
This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments
- **HTTrack**: For the inspiration and initial crawling logic.
- **FastAPI**: For the high-performance backend.
- **SQLAlchemy**: For the flexible ORM.
- **Recharts**: For the beautiful visualizations.
- **All Contributors**: For their time, feedback, and support.

---

## 📞 Contact
- **GitHub Issues**: [https://github.com/ideotion/Open-Omniscience/issues](https://github.com/ideotion/Open-Omniscience/issues)
- **Email**: `contact@ideotion.org`
- **Website**: [https://ideotion.org](https://ideotion.org)

---
**© 2026 Ideotion. All rights reserved.**