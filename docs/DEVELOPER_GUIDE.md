# Open Omniscience Developer Guide

**Version:** 0.2.0
**Last Updated:** May 7, 2026

This guide is for **developers** who want to **extend, customize, or contribute** to Open Omniscience. It covers:
- Architecture overview
- Code structure
- Development setup
- Adding new features
- Testing
- Deployment

---

## 📖 Table of Contents
1. [Architecture Overview](#-architecture-overview)
2. [Development Setup](#-development-setup)
3. [Code Structure](#-code-structure)
4. [Adding New Features](#-adding-new-features)
5. [Testing](#-testing)
6. [Database Migrations](#-database-migrations)
7. [Deployment](#-deployment)
8. [Contribution Guidelines](#-contribution-guidelines)
9. [API Documentation](#-api-documentation)

---

## 🏗️ Architecture Overview

Open Omniscience follows a **modular, layered architecture**:

```
┌───────────────────────────────────────────────────────┐
│                        Frontend                          │
│  (React + Recharts)                                      │
│  - index.html                                           │
│  - script.js (vanilla JS for now, React migration planned)│
│  - style.css                                            │
└───────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────┐
│                        Backend                           │
│  (FastAPI + SQLAlchemy)                                  │
│  - src/api/main.py (API endpoints)                       │
│  - src/database/models.py (ORM models)                  │
│  - src/utils/logging_config.py (logging)                │
└───────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────┐
│                      Scraping Layer                       │
│  (requests + BeautifulSoup + feedparser)                 │
│  - src/scraper/scraper.py (main scraper)                 │
│  - src/ingestor/url_utils.py (URL processing)            │
│  - src/ingestor/import.py (bulk import)                   │
└───────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────┐
│                        Data Storage                       │
│  (SQLite or PostgreSQL)                                  │
│  - data/open_omniscience.db (SQLite)                     │
│  - PostgreSQL (configurable)                            │
└───────────────────────────────────────────────────────┘
```

### Key Components:
| Component | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | HTML5, CSS3, JavaScript (Recharts) | User interface for search, visualization, and export. |
| **Backend** | FastAPI, SQLAlchemy | REST API, database ORM, and business logic. |
| **Scraper** | Python (requests, BeautifulSoup, feedparser) | Fetch and parse articles from news sources. |
| **Database** | SQLite (default), PostgreSQL | Store articles, sources, and metadata. |
| **Audit Logs** | CSV, Markdown | Track scraping activities for compliance. |

---

## 💻 Development Setup

### Prerequisites
- **Python:** 3.10+
- **Git:** Latest version
- **Node.js:** (Optional) For frontend development (future React migration).
- **PostgreSQL:** (Optional) For production databases.

### Step-by-Step Setup

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

#### 4. Install Development Dependencies
```bash
pip install pytest pytest-mock black flake8 isort
```

#### 5. Set Up Pre-Commit Hooks (Optional)
Install `pre-commit` to automate code formatting and linting:
```bash
pip install pre-commit
pre-commit install
```
This will run `black`, `flake8`, and `isort` on every commit.

#### 6. Initialize the Database
For **SQLite** (default):
```bash
mkdir -p data/
```
For **PostgreSQL**:
1. Install PostgreSQL (see [DATABASE.md](DATABASE.md)).
2. Create a database and user.
3. Set the `DATABASE_URL` environment variable.
4. Run the migrations:
   ```bash
   cd src/database
   alembic upgrade head
   ```

#### 7. Start the Development Server
```bash
uvicorn src.api.main:app --reload
```
- The GUI will be available at `http://localhost:8000`.
- The API will be available at `http://localhost:8000/api/`.

---

## 🗂️ Code Structure

```
Open-Omniscience/
├── configs/               # Configuration files
│   ├── sources.yml        # News sources
│   └── settings.yaml      # User preferences (future)
├── src/
│   ├── scraper/           # Scraping logic
│   │   └── scraper.py     # Main scraper class
│   ├── ingestor/          # Data ingestion
│   │   ├── url_utils.py   # URL canonicalization, hashing
│   │   └── import.py      # Bulk data import (CSV/JSON)
│   ├── database/          # Database layer
│   │   ├── models.py      # SQLAlchemy models
│   │   └── migrations/    # Alembic migrations
│   ├── api/               # FastAPI backend
│   │   └── main.py        # API endpoints
│   ├── utils/             # Utilities
│   │   └── logging_config.py # Centralized logging
│   └── static/            # Frontend assets
│       ├── index.html     # HTML template
│       ├── script.js      # Frontend JavaScript
│       └── style.css      # Frontend styles
├── data/                 # SQLite database (ignored in Git)
├── audit/                # Audit logs (ignored in Git)
├── tests/                # Tests
│   ├── test_scraper.py   # Scraper tests
│   └── test_api.py       # API tests (future)
├── docs/                 # Documentation
│   ├── USER_GUIDE.md     # User guide
│   ├── DEVELOPER_GUIDE.md # This file
│   └── DATABASE.md       # Database guide
├── .gitignore            # Git ignore rules
├── requirements.txt      # Python dependencies
├── README.md             # Project overview
└── ETHICS.md             # Ethical guidelines
```

---

## ✨ Adding New Features

### 1. Adding a New News Source
1. Edit `configs/sources.yml`:
   ```yaml
   - name: "New Source"
     domain: "newsource.com"
     rss_url: "https://newsource.com/rss"
     rate_limit_ms: 2000
     enabled: true
     priority: 2
     tags: ["news"]
   ```
2. Test the source:
   ```bash
   python -c "from src.scraper.scraper import Scraper; s = Scraper(); print(s.scrape_source({'name': 'New Source', 'domain': 'newsource.com', 'rss_url': 'https://newsource.com/rss', 'rate_limit_ms': 2000, 'enabled': True}))"
   ```

### 2. Adding a New API Endpoint
1. Edit `src/api/main.py`:
   ```python
   @app.get("/api/new-endpoint")
   async def new_endpoint():
       return {"message": "Hello, World!"}
   ```
2. Test the endpoint:
   ```bash
   curl http://localhost:8000/api/new-endpoint
   ```

### 3. Adding a New Database Model
1. Edit `src/database/models.py`:
   ```python
   class NewModel(Base):
       __tablename__ = "new_table"
       id = Column(Integer, primary_key=True)
       name = Column(String(100))
   ```
2. Create a migration:
   ```bash
   cd src/database
   alembic revision --autogenerate -m "Add new table"
   alembic upgrade head
   ```

### 4. Adding a New Frontend Feature
1. Edit `src/static/index.html` to add new UI elements.
2. Edit `src/static/script.js` to add new functionality.
3. Edit `src/static/style.css` to style the new elements.

---

## 🧪 Testing

### Running Tests
```bash
pytest tests/
```
- Tests are located in the `tests/` directory.
- Use `pytest-mock` for mocking dependencies.

### Writing Tests
Example test for the scraper (`tests/test_scraper.py`):
```python
from src.scraper.scraper import Scraper

def test_scraper_initialization():
    scraper = Scraper()
    assert len(scraper.sources) > 0
```

Example test for the API (`tests/test_api.py`):
```python
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_search_articles():
    response = client.get("/api/articles?query=test")
    assert response.status_code == 200
    assert "results" in response.json()
```

### Test Coverage
Aim for **>80% test coverage** for critical components (scraper, API, database). Use `pytest-cov` to check coverage:
```bash
pip install pytest-cov
pytest --cov=src tests/
```

---

## 🗃️ Database Migrations

Open Omniscience uses **Alembic** for database migrations. This allows you to modify the schema without losing data.

### Creating a Migration
1. Modify the models in `src/database/models.py`.
2. Generate a migration:
   ```bash
   cd src/database
   alembic revision --autogenerate -m "Your migration message"
   ```
3. Review the generated migration in `src/database/migrations/versions/`.
4. Apply the migration:
   ```bash
   alembic upgrade head
   ```

### Rolling Back
To revert a migration:
```bash
alembic downgrade -1
```

### Migration Tips
- **Always test migrations** on a backup of your database.
- **Avoid destructive changes** (e.g., dropping columns) without a backup plan.
- **Use `op.batch_alter_table`** for large tables to avoid locking.

---

## 🚀 Deployment

### Local Deployment (Development)
```bash
uvicorn src.api.main:app --reload
```
- `--reload`: Automatically restarts the server on code changes.
- Access at `http://localhost:8000`.

### Production Deployment
For production, use a **ASGI server** like `uvicorn` with `gunicorn`:

#### 1. Install Gunicorn
```bash
pip install gunicorn
```

#### 2. Create a `main_prod.py` (Optional)
```python
from src.api.main import app

if __name__ == "__main__":
    app()
```

#### 3. Run with Gunicorn
```bash
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 src.api.main:app
```
- `-w 4`: 4 worker processes (adjust based on CPU cores).
- `-b 0.0.0.0:8000`: Bind to all network interfaces on port 8000.

#### 4. Use a Reverse Proxy (Recommended)
For HTTPS and better performance, use **Nginx** or **Apache** as a reverse proxy.

**Example Nginx Configuration:**
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
- Restart Nginx:
  ```bash
  sudo systemctl restart nginx
  ```

#### 5. Use a Process Manager (Optional)
Use **systemd** or **supervisord** to manage the Gunicorn process.

**Example systemd Service (`/etc/systemd/system/openomniscience.service`):**
```ini
[Unit]
Description=Open Omniscience
After=network.target

[Service]
User=youruser
Group=yourgroup
WorkingDirectory=/path/to/Open-Omniscience
ExecStart=/path/to/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 src.api.main:app
Restart=always

[Install]
WantedBy=multi-user.target
```
- Enable and start the service:
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable openomniscience
  sudo systemctl start openomniscience
  ```

### Docker Deployment (Future)
A `Dockerfile` and `docker-compose.yml` will be added in a future release.

---

## 🤝 Contribution Guidelines

We welcome contributions from the community! Please follow these guidelines to ensure a smooth collaboration.

### 1. Fork the Repository
- Fork [Open-Omniscience](https://github.com/ideotion/Open-Omniscience) on GitHub.
- Clone your fork locally.

### 2. Create a Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 3. Follow the Code Style
- **Python**: Follow [PEP 8](https://peps.python.org/pep-0008/).
- **JavaScript**: Follow [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript).
- **CSS**: Use consistent indentation (2 spaces) and avoid `!important`.
- **Use `black` for Python formatting**:
  ```bash
  black src/ tests/
  ```
- **Use `isort` for Python imports**:
  ```bash
  isort src/ tests/
  ```
- **Use `flake8` for linting**:
  ```bash
  flake8 src/ tests/
  ```

### 4. Write Tests
- Add tests for new features in the `tests/` directory.
- Ensure all tests pass:
  ```bash
  pytest tests/
  ```

### 5. Document Your Changes
- Update the **README.md** if your changes affect users.
- Update the **documentation** in `docs/` if relevant.
- Add **docstrings** to new functions/classes.
- Add **comments** for complex logic.

### 6. Commit Your Changes
- Use **descriptive commit messages**:
  ```
  git commit -m "Add support for Boolean search queries"
  ```
- Reference any related issues:
  ```
  git commit -m "Fix scraper rate limiting (closes #123)"
  ```

### 7. Push to Your Fork
```bash
git push origin feature/your-feature-name
```

### 8. Open a Pull Request
- Open a PR from your fork to the `main` branch of `ideotion/Open-Omniscience`.
- Include a **clear description** of your changes.
- Reference any **related issues**.
- Wait for **code review** and address any feedback.

### Pull Request Template
```markdown
## Description
[Brief description of the changes]

## Related Issues
- Closes #[issue-number]

## Changes Made
- [ ] Added new feature
- [ ] Fixed bug
- [ ] Improved performance
- [ ] Updated documentation

## Testing
- [ ] All existing tests pass
- [ ] New tests added
- [ ] Manually tested

## Screenshots (if applicable)
[Add screenshots for UI changes]
```

---

## 📡 API Documentation

### Endpoints

| Method | Endpoint | Description | Parameters |
|--------|----------|-------------|------------|
| `GET` | `/api/articles` | Search and filter articles. | `query`, `source`, `language`, `tags`, `start_date`, `end_date`, `limit`, `offset` |
| `GET` | `/api/articles/export` | Export articles in CSV/JSON. | `format` (csv/json), `query`, `source`, `language`, `tags`, `start_date`, `end_date` |
| `GET` | `/api/sources` | List all available sources. | None |
| `GET` | `/` | Serve the GUI. | None |

### Example Requests

#### Search Articles
```bash
curl "http://localhost:8000/api/articles?query=climate AND change&source=BBC News&limit=10"
```

#### Export Articles as CSV
```bash
curl "http://localhost:8000/api/articles/export?format=csv&query=climate" -o articles.csv
```

#### List Sources
```bash
curl "http://localhost:8000/api/sources"
```

### Response Formats

#### `/api/articles`
```json
{
    "total": 100,
    "limit": 10,
    "offset": 0,
    "results": [
        {
            "id": 1,
            "title": "Climate Change Impact",
            "url": "https://example.com/climate-change",
            "canonical_url": "https://example.com/climate-change",
            "source": "BBC News",
            "published_at": "2026-05-07T12:00:00Z",
            "language": "en",
            "content": "The impact of climate change is...",
            "hash": "a1b2c3d4..."
        }
    ]
}
```

#### `/api/sources`
```json
[
    {
        "id": 1,
        "name": "BBC News",
        "domain": "bbc.com",
        "rss_url": "http://feeds.bbci.co.uk/news/rss.xml",
        "rate_limit_ms": 1000,
        "enabled": true,
        "priority": 1,
        "tags": ["news", "uk"]
    }
]
```

---

## 📚 Additional Resources
- [Open Omniscience GitHub](https://github.com/ideotion/Open-Omniscience)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://www.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Recharts Documentation](https://recharts.org/)

---
**© 2026 Ideotion. All rights reserved.**