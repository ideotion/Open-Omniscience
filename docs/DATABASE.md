# Database Configuration for Open Omniscience

**⚠️ EARLY CONCEPT RELEASE - NOT FUNCTIONAL ⚠️**

**Originally Forked From:** [HTTrack](https://www.httrack.com/) - This project was initially a fork of HTTrack website copier

> ⚠️ **IMPORTANT NOTICE**: Open Omniscience is currently in an **early concept release** that is **completely unusable**. The database configuration described below is **part of a conceptual framework only** and **does not work** in the current state. **Do not attempt to set up or use these database configurations** - they are not functional.

Open Omniscience is intended to support both **SQLite** (default) and **PostgreSQL** for data storage **when it becomes functional**. This guide covers the intended setup, configuration, and optimization for both.

---

## 🗃️ SQLite (Default - Conceptual)

### Pros (Intended):
- **Zero configuration**: Would work out of the box *if implemented*
- **Portable**: Single file (`data/open_omniscience.db`) *if implemented*
- **No server required**: Ideal for local development and small-scale use *if implemented*

### Cons (Intended):
- **Limited scalability**: Not ideal for >10GB of data *if implemented*
- **No concurrent writes**: SQLite locks the entire database during writes *if implemented*

### Setup (Conceptual):
**⚠️ DO NOT ATTEMPT - This is conceptual only**

1. Ensure the `data/` directory exists:
   ```bash
   # DO NOT RUN - This is conceptual only
   mkdir -p data/
   ```
2. The database would be automatically created when you run the scraper or API for the first time *if the software was functional*.

### Configuration (Conceptual):
- Database file location: `data/open_omniscience.db` *if implemented*
- To change the location, modify `DATABASE_URL` in `src/database/models.py` *if implemented*:
  ```python
  # DO NOT USE - This is conceptual only
  DATABASE_URL = "sqlite:///path/to/your/database.db"
  ```

### Performance Tips:
- **Vacuum regularly**: Run `VACUUM` to reclaim space:
  ```bash
  sqlite3 data/open_omniscience.db "VACUUM;"
  ```
- **Enable WAL mode**: Improves read/write concurrency:
  ```python
  engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
  ```
- **Limit database size**: SQLite works best with databases <10GB. For larger datasets, use PostgreSQL.

---

## 🐘 PostgreSQL

### Pros:
- **Scalable**: Handles terabytes of data efficiently.
- **Concurrent access**: Supports multiple readers/writers.
- **Advanced features**: Full-text search, JSON support, etc.

### Cons:
- **Requires setup**: Needs a PostgreSQL server.
- **More complex**: Requires separate installation and configuration.

### Setup:

#### 1. Install PostgreSQL
- **Debian-based Linux (Ubuntu, Debian, etc.)**:
  ```bash
  sudo apt update
  sudo apt install postgresql postgresql-contrib
  ```

#### 2. Create a Database and User
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

#### 3. Configure Open Omniscience
Set the `DATABASE_URL` environment variable before running the application:
```bash
export DATABASE_URL="postgres://open_omniscience:your_password@localhost:5432/open_omniscience"
```
Or modify `src/database/models.py`:
```python
DATABASE_URL = "postgres://open_omniscience:your_password@localhost:5432/open_omniscience"
```

#### 4. Initialize the Database
Run the Alembic migrations:
```bash
cd src/database
alembic upgrade head
```

### Configuration Options:
| Option | Description | Example |
|--------|-------------|---------|
| `host` | PostgreSQL server host | `localhost` or `192.168.1.100` |
| `port` | PostgreSQL server port | `5432` |
| `user` | Database username | `open_omniscience` |
| `password` | Database password | `your_password` |
| `dbname` | Database name | `open_omniscience` |

Full connection string:
```
postgres://user:password@host:port/dbname
```

### Performance Tips:
- **Indexes**: Open Omniscience automatically creates indexes for `hash`, `canonical_url`, and `source_id`. For large datasets, consider adding more indexes (e.g., for `published_at`).
- **Connection Pooling**: Use `SQLAlchemy`'s connection pooling:
  ```python
  engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
  ```
- **Vacuum and Analyze**: Regularly run `VACUUM ANALYZE` to optimize performance:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "VACUUM ANALYZE;"
  ```
- **Partitioning**: For very large datasets (>100GB), consider partitioning the `articles` table by `published_at` or `source_id`.

---

## 🔄 Migrations

Open Omniscience uses **Alembic** for database migrations. This allows you to update the schema without losing data.

### Setup:
1. Install Alembic:
   ```bash
   pip install alembic
   ```
2. Initialize Alembic (if not already done):
   ```bash
   cd src/database
   alembic init migrations
   ```
3. Update `alembic.ini` to point to your database:
   ```ini
   sqlalchemy.url = sqlite:///../../data/open_omniscience.db
   ```
   Or for PostgreSQL:
   ```ini
   sqlalchemy.url = postgres://open_omniscience:your_password@localhost:5432/open_omniscience
   ```

### Creating a Migration:
1. Modify the models in `src/database/models.py`.
2. Generate a migration:
   ```bash
   alembic revision --autogenerate -m "Your migration message"
   ```
3. Apply the migration:
   ```bash
   alembic upgrade head
   ```

### Rolling Back:
To revert a migration:
```bash
alembic downgrade -1
```

---

## 📊 Database Schema

### Tables:

#### `sources`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | STRING(100) | Name of the source (e.g., "BBC News") |
| `domain` | STRING(255) | Domain of the source (e.g., "bbc.com") |
| `rss_url` | STRING(500) | URL of the RSS feed (if available) |
| `rate_limit_ms` | INTEGER | Delay between requests in milliseconds |
| `enabled` | BOOLEAN | Whether the source is active for scraping |
| `priority` | INTEGER | Priority level (1 = high, 3 = low) |
| `tags` | STRING(500) | Comma-separated list of tags |

#### `articles`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `url` | STRING(1000) | Original URL of the article |
| `canonical_url` | STRING(1000) | Canonicalized URL (for duplicate detection) |
| `source_id` | INTEGER | Foreign key to `sources` |
| `title` | STRING(500) | Title of the article |
| `content` | TEXT | Full text content of the article |
| `published_at` | DATETIME | Publication date/time (ISO format) |
| `language` | STRING(10) | Language code (e.g., "en", "fr") |
| `hash` | STRING(64) | SHA-256 hash of the content (for duplicate detection) |
| `created_at` | DATETIME | Timestamp when the article was ingested |

> The columns above are the core fields; the live schema (`src/database/models.py`)
> and the Alembic migrations under `migrations/versions/` are the source of truth.
> `articles` also carries provenance/analysis fields (author, word_count, region,
> country, sentiment) and a compressed-content column.

#### Other tables (see models / migrations for full columns)

| Table | Purpose |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Source grouping + geo/robots metadata |
| `commodity_prices` | Observed price points (symbol, date, price, currency, **unit**, market, source) — charts + price↔news correlation |
| `market_extraction_rules` | Per-source rule (CSS selector / attribute / regex) locating one instrument's price on one page; category financial/stock/commodity |
| `keywords` | Distinct keyword/entity term (normalized, language, `is_entity`/`entity_type`, **`extractor`** provenance) |
| `keyword_mentions` | One per (article, keyword): count + first char offset + denormalised `observed_on`/`country`/`city` — powers Insights trends, associations, context, map |
| `wiki_pages` | A tracked Wikipedia page in one language edition; holds **one** compressed full-text baseline |
| `wiki_revisions` | One tracked edit: **diff + signed byte delta** + flags/tags (not a re-copy), optional ORES scores, honest large-edit flag + reasons |
| `article_analyses` | Derived LLM results (summary/translation) with model + prompt provenance |
| `keyword_categories`, `external_sources`, `article_links`, … | Keyword categorisation + link/source-relationship tracking |

### Indexes:
- `idx_article_hash`: Unique index on `hash` (for duplicate detection).
- `idx_article_canonical_url`: Index on `canonical_url` (for URL lookups).
- `idx_article_source_id`: Index on `source_id` (for source-based queries).
- `idx_article_content`: Index on `content` (for full-text search).

---

## 🔍 Full-Text Search

For advanced full-text search, consider the following:

### SQLite:
SQLite has built-in full-text search (FTS) capabilities. To enable:
1. Create a virtual table:
   ```python
   from sqlalchemy import text
   session.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(title, content)"))
   ```
2. Insert data into the FTS table (trigger-based or manually).

### PostgreSQL:
PostgreSQL has excellent full-text search support. Example query:
```python
from sqlalchemy import func
results = session.query(Article).filter(
    func.to_tsvector('english', Article.content).match('your & search & query')
).all()
```

---

## 📉 Monitoring and Maintenance

### SQLite:
- **Check database size**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Check table sizes**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```

### PostgreSQL:
- **Check database size**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT pg_size_pretty(pg_database_size('open_omniscience'));"
  ```
- **Check table sizes**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT table_name, pg_size_pretty(pg_total_relation_size(table_name)) FROM information_schema.tables WHERE table_schema='public';"
  ```
- **Monitor connections**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT * FROM pg_stat_activity;"
  ```

---

## 🚨 Troubleshooting

### Common Issues:

#### SQLite:
- **"Database is locked"**:
  - SQLite only allows one writer at a time. Ensure no other process is writing to the database.
  - Use WAL mode (see [Performance Tips](#performance-tips)).

- **"Too many open files"**:
  - SQLite opens a new connection for each thread. Limit the number of threads or use connection pooling.

#### PostgreSQL:
- **"Connection refused"**:
  - Ensure PostgreSQL is running:
    ```bash
    sudo systemctl status postgresql
    ```
  - Check the connection string (host, port, username, password).

- **"Permission denied"**:
  - Verify the user has permissions on the database:
    ```sql
    GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO open_omniscience;
    ```

- **"Relation does not exist"**:
  - Run the migrations:
    ```bash
    alembic upgrade head
    ```

---

## 📌 Best Practices

1. **Backup Regularly**:
   - **SQLite**: Copy the `open_omniscience.db` file.
   - **PostgreSQL**: Use `pg_dump`:
     ```bash
     pg_dump -U open_omniscience -d open_omniscience > open_omniscience_backup.sql
     ```

2. **Test Migrations**:
   - Always test migrations on a backup of your database before applying to production.

3. **Monitor Performance**:
   - Use tools like `pgAdmin` (PostgreSQL) or `sqlite3` CLI to monitor query performance.

4. **Optimize Queries**:
   - Use `EXPLAIN ANALYZE` (PostgreSQL) or `.explain()` (SQLite) to analyze slow queries.

5. **Limit Data Retention**:
   - Regularly archive or delete old articles to keep the database manageable.
   - Example: Delete articles older than 1 year:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
**© 2026 Ideotion. All rights reserved.**