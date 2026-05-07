# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism**

---

**Author:** Ideotion

**Fork of:** [HTTrack](https://www.httrack.com/) (Open-Source Web Scraper)

---

## 🌟 Mission

Open Omniscience is an **ethically impeccable**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.

This project is a **Linux-based application** and is built as a fork of HTTrack, leveraging its robust crawling capabilities while adding advanced features for ethical scraping, duplicate detection, and data management.

---

## ⚠️ Disclaimer

**Open Omniscience** is a tool designed for **ethical, legal, and responsible** data aggregation and analysis. Users must:

- Comply with all applicable laws and regulations in their jurisdiction.
- Respect the terms of service and `robots.txt` directives of all scraped websites.
- Use the platform for **non-commercial, non-malicious** purposes only.
- Ensure that any use of scraped data adheres to **copyright and fair use** principles.

The maintainers of Open Omniscience **do not endorse or assume responsibility** for any misuse of this tool. By using this software, you agree to use it in compliance with all relevant laws and ethical guidelines.

---

## 🚀 Getting Started

### Prerequisites
- **Operating System:** Linux
- **Python:** 3.10+
- **Dependencies:** `requests`, `beautifulsoup4`, `pyyaml`, `sqlalchemy`, `fastapi`, `uvicorn`

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/ideotion/Open-Omniscience
   cd Open-Omniscience
   ```

2. Set up a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Initialize the database:
   ```bash
   python src/database/init_db.py
   ```

4. Start the application:
   ```bash
   uvicorn src.api.main:app --reload
   ```

5. Access the GUI at `http://localhost:8000`

---

## 📁 Project Structure
```
Open-Omniscience/
├── README.md            # Project documentation
├── ETHICS.md            # Ethical guidelines and compliance
├── LICENSE              # MIT License
├── requirements.txt     # Python dependencies
├── configs/
│   ├── sources.yml       # News sources configuration
│   └── settings.yaml     # User preferences and rate limits
├── src/
│   ├── scraper/          # Web scraping logic
│   │   └── scraper.py    # Pure Python scraper (requests + BeautifulSoup)
│   ├── ingestor/         # Data ingestion pipeline
│   ├── database/         # Database models and ORM (SQLAlchemy + SQLite)
│   ├── api/              # FastAPI backend for the GUI
│   └── frontend/         # React-based GUI
├── data/                # Local storage for scraped data (SQLite)
├── audit/               # Audit logs and compliance tracking
└── tests/               # Unit and integration tests
```

---

## 🛠️ Configuration

### Sources
Edit `configs/sources.yml` to add, remove, or modify news sources. Example:
```yaml
sources:
  - name: "BBC News"
    domain: "bbc.com"
    rss_url: "https://feeds.bbci.co.uk/news/rss.xml"
    rate_limit_ms: 2000
    enabled: true
    tags: ["news", "uk"]
```

### Rate Limiting
- Default: 1 request per second per source.
- Adjustable in `configs/settings.yaml`.

---

## 🔍 Features

### Phase 1 (MVP)
- **Global Scraping:** Ingest articles from 100+ predefined sources.
- **Ethical Scraping:** Respects `robots.txt` and rate limits.
- **Duplicate Detection:** URL canonicalization + content hashing.
- **SQLite Database:** Portable, no server setup required.
- **Advanced Search:** Full-text search with filters (date, source, language).
- **Export:** CSV, JSON, and SQLite dump.
- **GUI:** Modern, responsive web interface (React + FastAPI).

### Phase 2 (Future)
- AI-powered analysis (sentiment, topic modeling).
- Real-time monitoring and alerts.
- Collaborative tagging and shared datasets.

---

## 📜 Ethical Guidelines
See [ETHICS.md](ETHICS.md) for detailed ethical scraping protocols, compliance checklists, and do-not-scrape lists.

---

## 🤝 Contributing
This repository is currently **private** during the MVP development phase. Contributions will be opened in the future. Stay tuned!

---

## 📄 License
This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.
