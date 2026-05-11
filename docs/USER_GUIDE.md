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
6. [Using Local LLM Features](#-using-local-llm-features)
7. [Exporting Data](#-exporting-data)
8. [Ethical Guidelines](#-ethical-guidelines)
9. [Troubleshooting](#-troubleshooting)
10. [FAQ](#-faq)

---

## 🌟 Introduction

Open Omniscience is an **open-source global intelligence platform** designed to help journalists, researchers, and analysts **aggregate, search, and analyze news articles** from around the world. It prioritizes **ethical scraping**, **data integrity**, and **user privacy**.

### Key Features:
- **Scrape 1900+ news sources** (RSS and HTML).
- **Advanced search** with Boolean operators, filters, and pagination.
- **Visualize data** with interactive charts.
- **Export data** in CSV, JSON, or SQLite formats.
- **Audit logging** for transparency and compliance.
- **Local LLM Support** for text generation, analysis, translation, and synthesis.

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

## 🤖 Using Local LLM Features

Open Omniscience includes **Local LLM Support** for advanced text processing. All LLM operations happen **locally on your machine**, ensuring **full data privacy**.

### Accessing LLM Features
1. Click the **🧠 (brain) icon** in the header of any page.
2. This opens the **Local LLM Dashboard** with all available features.

### Available LLM Capabilities

#### 📝 Text Generation
Generate text based on prompts using local language models.

**How to use:**
1. Navigate to the **Generate** tab in the LLM interface.
2. Select a model (e.g., Llama 3 8B).
3. Enter your prompt.
4. Adjust settings (temperature, max tokens).
5. Click **Generate**.

**Use cases:**
- Content creation
- Brainstorming ideas
- Drafting articles

#### 💬 Chat Completion
Have interactive conversations with the LLM.

**How to use:**
1. Navigate to the **Chat** tab.
2. Select a model.
3. Type your message and press Enter.
4. The LLM will respond, maintaining conversation context.

**Use cases:**
- Q&A sessions
- Decision support
- Interactive analysis

#### 🔍 Text Extraction
Extract structured information from text.

**Available extraction types:**
- **General** - Clean text extraction
- **Entities** - Named entities (people, organizations, locations)
- **Keywords** - Key terms and phrases
- **Summary** - Concise summaries
- **Metadata** - Author, date, title, source
- **Quotes** - Direct quotes with speakers
- **Links** - URLs and references

**How to use:**
1. Navigate to the **Extract** tab.
2. Paste or upload your text.
3. Select extraction type.
4. Click **Extract**.

#### 🌍 Translation
Translate text between languages.

**Supported languages:** English, French, Spanish, German, Italian, Portuguese, Russian, Chinese, Japanese, Arabic, Hindi, and more.

**How to use:**
1. Navigate to the **Translate** tab.
2. Select source and target languages.
3. Enter text to translate.
4. Click **Translate**.

#### 📊 Text Analysis
Analyze text for various characteristics.

**Available analysis types:**
- **Sentiment** - Positive/negative/neutral sentiment
- **Tone** - Formal, casual, urgent, sarcastic, etc.
- **Bias** - Political, gender, racial biases
- **Readability** - Reading ease, grade level
- **Emotion** - Joy, anger, sadness, etc.
- **Comprehensive** - All analysis types combined
- **Disinformation** - Potential misleading content

**How to use:**
1. Navigate to the **Analyze** tab.
2. Paste your text.
3. Select analysis type.
4. Click **Analyze**.

#### 🔗 Synthesis
Combine information from multiple sources.

**Available synthesis types:**
- **Summary** - Concise summary of all sources
- **Comparison** - Compare sources, find similarities/differences
- **Timeline** - Create chronological timeline
- **Report** - Comprehensive report with structure
- **FAQ** - Generate frequently asked questions

**How to use:**
1. Navigate to the **Synthesize** tab.
2. Add multiple text sources.
3. Select synthesis type.
4. Click **Synthesize**.

### Managing Models

#### View Available Models
1. Navigate to the **Models** tab.
2. See all **pre-configured models** (9 models available).
3. Check which models are **downloaded** on your system.

#### Download a Model
1. Navigate to the **Models** tab.
2. Click **Download** next to the model you want.
3. Wait for the download to complete (can take several minutes).
4. The model will be available for use.

#### Remove a Model
1. Navigate to the **Models** tab.
2. Click **Remove** next to the downloaded model.
3. Confirm the removal.

> **⚠️ Note:** Models can be large (2-40GB). Ensure you have enough disk space.

### LLM Settings

#### Configuration Options
- **Auto-download models** - Automatically download required models
- **Model library path** - Where to store downloaded models
- **Ollama base URL** - Custom Ollama server URL
- **Timeout** - Request timeout in seconds
- **Max tokens** - Maximum tokens to generate

#### Changing Settings
1. Navigate to the **Settings** tab in the LLM interface.
2. Adjust the settings as needed.
3. Click **Save**.

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

## Article Intelligence Tools

Open Omniscience includes powerful article intelligence tools for advanced analysis.

### Keyword Analysis

Extract and analyze keywords from articles with comprehensive metadata.

**Via API:**
POST /api/analysis/keywords/extract?article_id=1

**Use Cases:**
- Identify main topics in an article
- Track keyword positions for narrative analysis
- Count term frequencies for content analysis

---

### Article Similarity

Calculate how similar two articles are using multiple algorithms.

**Via API:**
POST /api/analysis/articles/similarity?article_id1=1&article_id2=2&method=cosine

**Available Methods:**
- cosine (default) - Most accurate, uses TF-IDF
- jaccard - Fast, set-based comparison
- euclidean - Geometric distance
- manhattan - Sum of absolute differences

**Interpretation:**
- 0.0 - 0.3: Very different articles
- 0.3 - 0.6: Somewhat similar
- 0.6 - 0.8: Quite similar
- 0.8 - 1.0: Very similar or identical

**Use Cases:**
- Detect duplicate or syndicated content
- Find related articles
- Identify articles covering the same event

---

### Group Articles by Similarity

Automatically cluster similar articles together.

**Via API:**
POST /api/analysis/articles/group?article_ids=1,2,3,4,5&threshold=0.7

**Parameters:**
- article_ids: Comma-separated list of article IDs to group
- threshold: Similarity threshold (0.0-1.0), default: 0.7
- method: Similarity method, default: cosine

**Use Cases:**
- Story clustering - find all articles about the same event
- Duplicate detection - group near-identical articles
- Topic organization - categorize articles by content

---

### Source Similarity Analysis

Analyze how frequently different news sources publish similar content.

**Via API:**
GET /api/analysis/sources/similarity?source_ids=1,2,3&time_range_days=30&similarity_threshold=0.5

**Parameters:**
- source_ids: Comma-separated list of source IDs to analyze
- time_range_days: Time range in days, default: 30
- similarity_threshold: Threshold for high similarity, default: 0.5

**Use Cases:**
- Detect coordinated messaging
- Identify syndication
- Find sources with similar editorial focus
- Monitor source relationships over time

---

### Practical Examples for Investigative Journalism

#### Example 1: Find All Articles About a Breaking Story
1. Search for articles containing keywords
2. Group similar articles to find the main story
3. Extract keywords from the main cluster

#### Example 2: Detect Coordinated Messaging
Analyze similarity between political news sources to find sources that publish very similar content, which could indicate coordinated messaging or syndication.

#### Example 3: Track a Developing Story
Extract keywords from articles about a topic, compare with previous articles, and group recent articles to see how the story is evolving.

#### Example 4: Content Analysis Workflow
1. Get articles from a specific source
2. Extract keywords from each article
3. Find cross-article keywords (keywords appearing in multiple articles)
4. Calculate similarity between articles to find related stories
5. Group articles by similarity to organize your research

---

### Understanding the Results

#### Similarity Scores
- 0.0 - 0.3: Articles are about different topics
- 0.3 - 0.6: Articles share some common themes or keywords
- 0.6 - 0.8: Articles are quite similar, likely about the same event
- 0.8 - 1.0: Articles are very similar or identical

#### Cluster Analysis
- Cluster Size: Number of articles in the group
- Average Similarity: How similar the articles are to each other
- Use larger thresholds (0.8+) for tighter clusters
- Use smaller thresholds (0.5-0.7) for broader groupings

#### Source Similarity
- High Similarity Percentage: Percentage of article pairs above the threshold
- Average Similarity: Overall similarity across all comparisons
- Look for outliers: Sources with unusually high similarity to others
