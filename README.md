# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism with Local LLM Support**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.02 (with Local LLM Support)
**License:** [MIT](LICENSE)

![Open Omniscience Logo](https://via.placeholder.com/150?text=Open+Omniscience)

---

## 🌟 Mission

Open Omniscience is an **ethically oriented**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.
- **NEW:** Analyze, translate, and synthesize content using **local LLM capabilities**

This project is a **Linux-based application** built as a fork of [HTTrack](https://www.httrack.com/), leveraging its robust crawling capabilities while adding advanced features for **ethical scraping**, **duplicate detection**, **data management**, and now **AI-powered analysis**.

---

## ⚠️ Disclaimer

**Open Omniscience** is a tool designed for **ethical, legal, and responsible** data aggregation and analysis. By using this software, you agree to comply with the following:

1. **Respect all applicable laws** in your jurisdiction, including copyright and data protection regulations.
2. **Adhere to `robots.txt` directives** and terms of service of all scraped websites.
3. **Use the platform for non-commercial, non-malicious purposes only**.
4. **Ensure ethical use** as outlined in [ETHICS.md](ETHICS.md).
5. **All LLM processing happens locally** - no data is sent to external services.

The maintainers of Open Omniscience **do not endorse or assume responsibility** for any misuse of this tool.

---

## 🚀 Getting Started

### Quick Start with Docker (Recommended)

The fastest way to get started is using Docker:

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience

# Copy and configure environment file
cp .env.example .env
# Edit .env with your settings (optional)

# Start the application (without LLM)
docker-compose up -d --build

# OR start with LLM support (requires more resources)
docker-compose -f docker-compose.yml -f docker-compose.llm.yml up -d --build

# Access the application
# Open http://localhost:8000 in your browser
```

### One-Line Installation (Development)

For development environments:

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience

# Set up virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# For LLM support (optional)
pip install -r requirements-llm.txt

# Initialize the database
mkdir -p data audit logs
python -c "import sys; sys.path.insert(0, 'src'); from database.models import Base, engine; Base.metadata.create_all(engine); print('Database initialized')"

# Start the application
uvicorn api.main:app --reload

# Access at http://localhost:8000
```

---

## 🤖 Local LLM Support (NEW!)

Open Omniscience now includes **comprehensive local LLM support** for text processing, enabling advanced analysis capabilities while maintaining full data privacy.

### 🎯 LLM Capabilities

| Capability | Description | Endpoint | Use Cases |
|------------|-------------|----------|----------|
| **Text Generation** | Generate text from prompts | `POST /api/llm/generate` | Content creation, brainstorming |
| **Chat Completion** | Multi-turn conversations | `POST /api/llm/chat` | Interactive Q&A, decision support |
| **Text Extraction** | Extract structured information | `POST /api/llm/extract` | Entity extraction, summarization |
| **Translation** | Translate between languages | `POST /api/llm/translate` | Multilingual content processing |
| **Text Analysis** | Comprehensive text analysis | `POST /api/llm/analyze` | Sentiment, bias, readability |
| **Synthesis** | Combine multiple sources | `POST /api/llm/synthesize` | Summaries, comparisons, reports |
| **Batch Processing** | Process multiple items | `POST /api/llm/batch` | Efficient bulk operations |

### 📚 Supported Models

We support 9 pre-configured open-source models via [Ollama](https://ollama.com):

| Model | Size | VRAM Required | Best For | Default |
|-------|------|---------------|----------|---------|
| `phi3:3.8b` | 2.3GB | 3GB | Lightweight tasks | ❌ |
| `bart-large` | 1.4GB | 3GB | Translation, summarization | ❌ |
| `mistral:7b` | 4.1GB | 5GB | General purpose | ❌ |
| **`llama3:8b`** | **4.7GB** | **5GB** | **All tasks** | ✅ |
| `gemma:7b` | 4.8GB | 5GB | CPU-optimized | ❌ |
| `qwen2.5:7b` | 4.8GB | 5GB | Multilingual | ❌ |
| `llava:7b` | 4.5GB | 6GB | Multimodal (text + vision) | ❌ |
| `llama3:70b` | 40GB | 42GB | High capability | ❌ |

### 🚀 LLM Quick Start

#### Option 1: Automated Setup (Recommended)

```bash
# Run the setup script to install Ollama and download default models
python scripts/setup_llm.py --all

# This will:
# 1. Install Ollama
# 2. Start Ollama server
# 3. Download the default model (llama3:8b)
```

#### Option 2: Manual Setup

```bash
# 1. Install Ollama
# Linux/macOS:
curl -fsSL https://ollama.com/install.sh | sh

# Windows (PowerShell as admin):
irm https://ollama.com/install.ps1 | iex

# 2. Start Ollama server
ollama serve

# 3. Download a model
ollama pull llama3:8b

# 4. Install Python dependencies
pip install -r requirements-llm.txt

# 5. Start Open Omniscience
uvicorn api.main:app --reload
```

#### Verify Installation

```bash
# Check LLM service health
curl http://localhost:8000/api/llm/health

# List available models
curl http://localhost:8000/api/llm/models

# Get capabilities
curl http://localhost:8000/api/llm/capabilities
```

### 📖 LLM Usage Examples

#### Text Generation

```bash
curl -X POST http://localhost:8000/api/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What are the key trends in investigative journalism in 2024?", "temperature": 0.7}'
```

#### Translation

```bash
curl -X POST http://localhost:8000/api/llm/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, how are you?", "target_language": "fr", "source_language": "en"}'
```

#### Text Extraction

```bash
curl -X POST http://localhost:8000/api/llm/extract \
  -H "Content-Type: application/json" \
  -d '{"content": "Apple Inc. was founded by Steve Jobs in 1976...", "extraction_type": "entities"}'
```

#### Text Analysis

```bash
curl -X POST http://localhost:8000/api/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "This product is amazing and works perfectly!", "analysis_type": "sentiment"}'
```

For more details, see [LLM_README.md](LLM_README.md)

---

## 🏗️ Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Open Omniscience                          │
├─────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │   Crawler   │    │   Database  │    │   API Server    │  │
│  │  (HTTrack)  │    │  (SQLite/   │    │   (FastAPI)     │  │
│  │             │    │  PostgreSQL)│    │                 │  │
│  └──────┬──────┘    └──────┬──────┘    └────────┬────────┘  │
│         │                  │                   │            │
│         ▼                  ▼                   ▼            │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    LLM Service Layer                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │  │
│  │  │  LLMService │  │ ModelManager│  │   Ollama API     │  │  │
│  │  │             │  │             │  │  (External)       │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Web Crawler** | HTTrack | Website scraping and mirroring |
| **Backend** | Python 3.8+ | Core application logic |
| **API Framework** | FastAPI | REST API endpoints |
| **Database** | SQLite / PostgreSQL | Data storage |
| **LLM Runtime** | Ollama | Local LLM execution |
| **LLM Models** | Llama, Mistral, Phi, Qwen, Gemma | Text processing |
| **Frontend** | HTML5, CSS, JavaScript | User interface |
| **Containerization** | Docker | Deployment and portability |

---

## 📦 Installation

### Prerequisites

- **Operating System:** Linux (recommended), macOS, or Windows (WSL)
- **Python:** 3.8+ (required for LLM support)
- **Dependencies:** See [requirements.txt](requirements.txt)
- **LLM Dependencies:** See [requirements-llm.txt](requirements-llm.txt)
- **Database:** SQLite (default) or PostgreSQL (recommended for production)
- **Docker:** Optional, for containerized deployment
- **Ollama:** Required for LLM features (optional for core functionality)

### Development Setup

#### 1. Clone the Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience
```

#### 2. Set Up Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\activate   # Windows
```

#### 3. Install Dependencies
```bash
# Core dependencies
pip install -r requirements.txt

# LLM dependencies (optional)
pip install -r requirements-llm.txt
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
   export DATABASE_URL="postgresql://open_omniscience:your_password@localhost:5432/open_omniscience"
   ```

#### 5. Start the Application
```bash
# Without LLM support
uvicorn api.main:app --reload

# With LLM support (requires Ollama running)
uvicorn api.main:app --reload
```

### Docker Setup

#### Standard Deployment (without LLM)
```bash
docker-compose up -d --build
```

#### LLM-Enabled Deployment
```bash
# Start with both standard and LLM services
docker-compose -f docker-compose.yml -f docker-compose.llm.yml up -d --build

# OR use the dedicated LLM Dockerfile
docker build -t open-omniscience-llm -f Dockerfile.llm .
docker run -p 8000:8000 -p 11434:11434 open-omniscience-llm
```

---

## 🎯 Features

### Core Features

#### Web Scraping & Crawling
- **HTTrack Integration**: Robust website mirroring capabilities
- **Ethical Scraping**: Respects `robots.txt` and rate limits
- **Duplicate Detection**: Identifies and filters duplicate content
- **Multi-Source Aggregation**: Combines data from diverse sources
- **Incremental Updates**: Resumes interrupted downloads, updates existing mirrors

#### Data Management
- **Unified Database**: Centralized storage for all scraped content
- **Advanced Search**: Full-text search with Boolean operators
- **Metadata Extraction**: Automatic extraction of titles, authors, dates, etc.
- **Content Deduplication**: Prevents storage of duplicate articles
- **Data Export**: Export data in various formats (JSON, CSV, etc.)

#### Analysis & Processing
- **Keyword Analysis**: Identify and track keywords across sources
- **Link Analysis**: Analyze link structures and relationships
- **Source Management**: Configure and manage news sources
- **Category Classification**: Automatic categorization of content

### LLM-Powered Features (NEW!)

#### Text Processing
- **Text Generation**: Create content based on prompts
- **Chat Completion**: Interactive conversations with context memory
- **Text Extraction**: Extract entities, keywords, summaries, metadata, quotes, links
- **Translation**: Translate text between 11+ languages
- **Text Analysis**: Comprehensive analysis including:
  - Sentiment analysis (positive/negative/neutral)
  - Tone detection (formal, casual, urgent, sarcastic)
  - Bias detection (political, gender, racial)
  - Readability metrics (Flesch reading ease, grade level)
  - Emotion analysis (joy, anger, sadness, etc.)
  - Disinformation risk assessment

#### Information Synthesis
- **Summarization**: Create concise summaries from multiple sources
- **Comparison**: Identify similarities and differences between sources
- **Timeline Creation**: Generate chronological timelines from unstructured text
- **Report Generation**: Create comprehensive reports with structured output
- **FAQ Generation**: Generate frequently asked questions and answers

#### Batch Processing
- **Efficient Multi-Item Processing**: Process multiple texts in a single request
- **Error Handling**: Graceful handling of failures for individual items
- **Status Tracking**: Track progress and results for each item

---

## 🔌 API Documentation

### Base URL
```
http://localhost:8000
```

### Core API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sources` | List all configured sources |
| POST | `/api/sources` | Add a new source |
| GET | `/api/sources/{id}` | Get source details |
| PUT | `/api/sources/{id}` | Update a source |
| DELETE | `/api/sources/{id}` | Delete a source |
| GET | `/api/articles` | Search and list articles |
| GET | `/api/articles/{id}` | Get article details |
| GET | `/api/keywords` | List and analyze keywords |
| GET | `/api/links` | Analyze link structures |
| GET | `/api/export` | Export data in various formats |

### LLM API Endpoints

All LLM endpoints are prefixed with `/api/llm`:

| Method | Endpoint | Description | Parameters |
|--------|----------|-------------|------------|
| GET | `/api/llm/health` | Check LLM service health | - |
| GET | `/api/llm/models` | List available models and status | - |
| GET | `/api/llm/capabilities` | List supported capabilities | - |
| POST | `/api/llm/generate` | Generate text from prompt | prompt, model_id, temperature, max_tokens |
| POST | `/api/llm/chat` | Chat completion | messages, model_id, temperature, max_tokens |
| POST | `/api/llm/extract` | Extract structured information | content, extraction_type, model_id |
| POST | `/api/llm/translate` | Translate text | text, target_language, source_language, model_id |
| POST | `/api/llm/analyze` | Analyze text | text, analysis_type, model_id |
| POST | `/api/llm/synthesize` | Synthesize information | sources, synthesis_type, model_id |
| POST | `/api/llm/batch` | Batch process multiple items | items, operation, model_id, options |

### Request Examples

#### Search Articles
```bash
curl "http://localhost:8000/api/articles?q=investigation&limit=10"
```

#### Generate Text
```bash
curl -X POST http://localhost:8000/api/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize the latest trends in AI", "temperature": 0.7}'
```

#### Extract Entities
```bash
curl -X POST http://localhost:8000/api/llm/extract \
  -H "Content-Type: application/json" \
  -d '{"content": "Apple was founded by Steve Jobs...", "extraction_type": "entities"}'
```

#### Translate Text
```bash
curl -X POST http://localhost:8000/api/llm/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "target_language": "fr", "source_language": "en"}'
```

For complete API documentation, see [API Documentation](docs/API.md) (if available) or explore the interactive API docs at `/docs` when the server is running.

---

## 📊 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/open_omniscience.db` | Database connection URL |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | CORS allowed origins |
| `OLLAMA_HOST` | `0.0.0.0` | Ollama server host |
| `OLLAMA_ORIGINS` | `*` | Ollama CORS origins |
| `DOWNLOAD_DEFAULT_MODELS` | `false` | Auto-download default models |
| `AUTO_DOWNLOAD_MODELS` | `true` | Auto-download models on first use |
| `MAX_CONTEXT_LENGTH` | `8192` | Maximum context length for LLM |
| `MAX_TOKENS` | `4096` | Maximum tokens to generate |

### Configuration Files

- `configs/settings.yaml` - Main application settings
- `configs/sources.yml` - News source configurations
- `.env` - Environment variables (not committed to repo)

---

## 🛡️ Security

### Best Practices

1. **Data Privacy**: All LLM processing happens locally - no data leaves your system
2. **Rate Limiting**: Built-in rate limiting prevents API abuse
3. **Input Validation**: All inputs are validated and sanitized
4. **CORS**: Configurable CORS settings for secure cross-origin requests
5. **HTTPS**: Recommended for production deployments

### Security Features

- **Sanitization**: All user inputs are sanitized to prevent XSS
- **Rate Limiting**: Prevents brute force and DoS attacks
- **Authentication**: Can be added for sensitive endpoints
- **Audit Logging**: Comprehensive logging for security auditing

---

## 📈 Performance

### System Requirements

#### Minimum (Core Features Only)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB
- **OS:** Linux, macOS, or Windows (WSL)

#### Recommended (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 models)
- **GPU:** NVIDIA with 8GB VRAM (recommended for better performance)
- **OS:** Linux (recommended), macOS, or Windows (WSL)

#### High-End (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM
- **OS:** Linux

### Performance Optimizations

- **Model Caching**: Downloaded models are persisted for reuse
- **GPU Acceleration**: Automatic GPU utilization when available
- **Batch Processing**: Efficient handling of multiple items
- **Connection Pooling**: Database connection pooling
- **Response Caching**: (Planned) Caching for repeated queries

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests (`pytest`)
5. Commit your changes (`git commit -m 'Add some feature'`)
6. Push to the branch (`git push origin feature/your-feature`)
7. Open a Pull Request

### Code Standards

- Follow PEP 8 style guide
- Use type hints
- Write comprehensive docstrings
- Add tests for new functionality
- Keep commits atomic and well-described

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **HTTrack**: For the robust web crawling foundation
- **Ollama**: For the excellent local LLM runtime
- **Meta, Mistral AI, Microsoft, Alibaba, Google**: For the open-source models
- **FastAPI**: For the excellent API framework
- **All Contributors**: For their valuable contributions and feedback

---

## 📚 Additional Documentation

- [LLM_README.md](LLM_README.md) - Detailed LLM documentation
- [LLM_IMPLEMENTATION_SUMMARY.md](LLM_IMPLEMENTATION_SUMMARY.md) - Implementation details
- [FRONTEND_LLM_SUMMARY.md](FRONTEND_LLM_SUMMARY.md) - Frontend integration guide
- [COMPLETE_IMPLEMENTATION_REPORT.md](COMPLETE_IMPLEMENTATION_REPORT.md) - Full implementation report
- [DATABASE.md](docs/DATABASE.md) - Database setup guide
- [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) - Development guide
- [USER_GUIDE.md](docs/USER_GUIDE.md) - User guide
- [ETHICS.md](ETHICS.md) - Ethical guidelines
- [SECURITY.md](SECURITY.md) - Security best practices

---

## 🆘 Support

- **GitHub Issues**: Report bugs and request features
- **Discussions**: Ask questions and share ideas
- **Documentation**: Check the docs first!
- **Email**: contact@ideotion.com

---

## 📅 Changelog

### Version 0.02 (Current)
- **NEW:** Local LLM support with comprehensive text processing capabilities
- **NEW:** 9 pre-configured open-source models
- **NEW:** 10+ API endpoints for LLM operations
- **NEW:** Docker support for LLM deployment
- **NEW:** Automated setup scripts
- **NEW:** Comprehensive test suite for LLM features
- Updated API version to 0.02
- Enhanced documentation with LLM guides

### Version 0.2.0 (Previous)
- Initial MVP release
- Core web scraping and data management
- Basic API endpoints
- SQLite and PostgreSQL support

For detailed changelog, see [ChangeLog](ChangeLog) or [GitHub Releases](https://github.com/ideotion/Open-Omniscience/releases).

---

**© 2024 Ideotion. All rights reserved.**

*Built with ❤️ for investigative journalism and ethical data analysis.*
