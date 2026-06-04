# Open Omniscience

**⚠️ EARLY CONCEPT RELEASE - NOT FUNCTIONAL ⚠️**

> **IMPORTANT:** This is an **early concept release** that is **completely unusable** in its current state. The application **does not work** and requires **extensive debugging and development** before it can be used. **Do not expect this to function** - this is a work in progress for future development.

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism with Local LLM Support**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.04 (Early Concept - Non-Functional)
**License:** [GNU GPLv3](LICENSE)
**Originally Forked From:** [HTTrack](https://www.httrack.com/) - This project was initially a fork of HTTrack website copier

![Open Omniscience Logo](https://via.placeholder.com/150?text=Open+Omniscience)

---

## ⚠️ CRITICAL WARNING: EARLY DEVELOPMENT STAGE

**THIS SOFTWARE IS NOT READY FOR USE.**

- ❌ **Does not work** in current state
- ❌ **Requires extensive debugging**
- ❌ **Completely unusable** for production or testing
- ❌ **No functionality guaranteed**
- ❌ **For development purposes only**


---

## 🌟 Mission

Open Omniscience is an **ethically oriented**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.
- **NEW:** Analyze, translate, and synthesize content using **local LLM capabilities**

This project is a **Debian-based Linux application** built on Python, leveraging robust crawling capabilities for **ethical scraping**, **duplicate detection**, **data management**, and now **AI-powered analysis**.

---

## ⚠️ Disclaimer

**Open Omniscience** is an **early concept release** that is **not functional** and **not ready for any use**. This project was initially forked from [HTTrack](https://www.httrack.com/), a website copier tool designed by Xavier Roche (kudos to him!).

### Early Development Status

**THIS SOFTWARE IS IN AN EARLY CONCEPT STAGE AND DOES NOT WORK.**

- This is **not a production-ready application**
- The codebase **requires extensive debugging and development**
- **No features are guaranteed to function**
- **Do not attempt to use this for any real-world purposes**
- This is a **development framework only**

### Legal & Ethical Disclaimer

When this software becomes functional, it will be designed for **ethical, legal, and responsible** data aggregation and analysis. By using this software, you agree to comply with the following:

1. **Respect all applicable laws** in your jurisdiction, including copyright and data protection regulations.
2. **Adhere to `robots.txt` directives** and terms of service of all scraped websites.
3. **Use the platform for non-commercial, non-malicious purposes only**.
4. **Ensure ethical use** as outlined in [ETHICS.md](docs/ETHICS.md).
5. **All LLM processing happens locally** - no data is sent to external services.

The maintainers of Open Omniscience **do not endorse or assume responsibility** for any misuse of this tool. **Currently, the maintainers cannot guarantee any functionality as the software is not yet operational.**

---

## 🚀 Getting Started

**⚠️ IMPORTANT: DO NOT ATTEMPT TO INSTALL**

The installation scripts and instructions below are **part of the conceptual framework only**. The software **will not work** if you attempt to install it. This section is provided for documentation purposes to show the intended design, but **no functionality is currently operational**.

### 🎯 Intended Installation (Conceptual - NOT FUNCTIONAL)

**This is a conceptual design for future Debian 13 installation:**

```bash
# DO NOT RUN - This will not work in current state
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

**What this would do (when functional):**
- ❌ **Detects Debian 13 environment** (not currently working)
- ❌ **Installs all dependencies** automatically (not currently working)
- ❌ **Configures everything** properly for Debian 13 (not currently working)
- ❌ **Creates desktop launcher** (if GUI available) (not currently working)
- ❌ **Provides clear next steps** (not currently working)

**Note:** Open-Omniscience **does not currently run** at http://localhost:8000 or any other address. The application is **not functional**.

### 📚 Documentation

**Complete guide for Debian 13 users:**
- [DOCUMENTATION.md](DOCUMENTATION.md) - Complete guide for Debian 13

This file covers installation, usage, troubleshooting, API reference, and architecture for Debian 13.

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

We support **40 pre-configured models** across multiple providers (Ollama, Hugging Face, etc.):

#### 🆕 Newest Models (2025-2026)
| Model | Size | VRAM Required | Best For | Provider |
|-------|------|---------------|----------|----------|
| `gemma4:9b` | 5.5GB | 6GB | Latest generation, reasoning | Google |
| `gemma4:27b` | 17GB | 18GB | High capability, reasoning | Google |
| `llama4:9b` | 5.2GB | 6GB | Next generation | Meta |
| `llama4:70b` | 40GB | 42GB | Flagship, state-of-the-art | Meta |
| `mistral-large-2` | 24GB | 26GB | Latest flagship | Mistral |
| `phi4` | 14GB | 15GB | Latest Phi, reasoning | Microsoft |
| `qwen3:8b` | 5GB | 6GB | Improved multilingual | Alibaba |
| `qwen3:72b` | 45GB | 48GB | High-capacity multilingual | Alibaba |

#### ⚡ Lightweight Models (<4GB)
| Model | Size | VRAM Required | Best For | Provider |
|-------|------|---------------|----------|----------|
| `tinyllama:1.1b` | 0.7GB | 1GB | Extremely lightweight | Community |
| `phi3:mini-4k` | 1.8GB | 2GB | Compact with 4K context | Microsoft |
| `phi3:small-8k` | 2.7GB | 3GB | 8K context | Microsoft |
| `gemma2:2b` | 1.4GB | 2GB | Ultra-lightweight | Google |
| `llama3.2:1b` | 0.6GB | 1GB | Compact | Meta |
| `llama3.2:3b` | 1.8GB | 2GB | Balanced | Meta |
| `qwen2.5:0.5b` | 0.6GB | 1GB | Ultra-lightweight multilingual | Alibaba |
| `qwen2.5:1.5b` | 1.8GB | 2GB | Compact multilingual | Alibaba |
| `bart-large` | 1.4GB | 3GB | Translation, summarization | Facebook |

#### 📊 Text Analysis Specialized
| Model | Size | VRAM Required | Best For | Provider |
|-------|------|---------------|----------|----------|
| `bert-base-uncased` | 0.5GB | 1GB | Classification, embeddings | Hugging Face |
| `distilbert-base-uncased` | 0.25GB | 0.5GB | Fast classification | Hugging Face |
| `roberta-base` | 0.5GB | 1GB | Robust analysis | Hugging Face |
| `all-mpnet-base-v2` | 0.4GB | 1GB | Semantic similarity | Hugging Face |
| `sentence-t5-base` | 0.5GB | 1GB | Sentence embeddings | Hugging Face |

#### 🌍 Translation Specialized
| Model | Size | VRAM Required | Best For | Languages | Provider |
|-------|------|---------------|----------|-----------|----------|
| `nllb-200-distilled-600m` | 1.1GB | 2GB | Translation | 200+ | Meta |
| `nllb-200-1.3b` | 2.5GB | 3GB | Translation | 200+ | Meta |
| `mbart-large-50-many-to-many` | 1.4GB | 3GB | Translation, summarization | 50 | Facebook |
| `t5-small` | 0.3GB | 0.5GB | Translation, summarization | Multiple | Google |
| `t5-base` | 0.9GB | 1GB | Translation, summarization | Multiple | Google |
| `t5-large` | 3GB | 4GB | High-quality translation | Multiple | Google |

#### 🎯 General Purpose (Original)
| Model | Size | VRAM Required | Best For | Default |
|-------|------|---------------|----------|---------|
| `phi3:3.8b` | 2.3GB | 3GB | Lightweight tasks | ❌ |
| `mistral:7b` | 4.1GB | 5GB | General purpose | ❌ |
| **`gemma4:e2b`** | **4.7GB** | **5GB** | **All tasks** | ✅ |
| `gemma:7b` | 4.8GB | 5GB | CPU-optimized | ❌ |
| `qwen2.5:7b` | 4.8GB | 5GB | Multilingual | ❌ |
| `llava:7b` | 4.5GB | 6GB | Multimodal (text + vision) | ❌ |
| `llama3:70b` | 40GB | 42GB | High capability | ❌ |
| `mistral-7b-instruct` | 4.1GB | 5GB | Instruction fine-tuned | ❌ |
| `llama3.2:11b` | 6.5GB | 7GB | High performance | ❌ |
| `llama3.2:90b` | 55GB | 58GB | Flagship | ❌ |
| `gemma2:9b` | 5GB | 6GB | Improved v1 | ❌ |
| `phi3:medium-16k` | 4.2GB | 5GB | 16K context | ❌ |

### 🚀 LLM Quick Start

#### Option 1: Automated Setup (Recommended)

```bash
# Run the setup script to install Ollama and download default models
python scripts/setup_llm.py --all

# This will:
# 1. Install Ollama
# 2. Start Ollama server
# 3. Download the default model (gemma4:e2b)
```

#### Option 2: Manual Setup

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Start Ollama server
ollama serve

# 3. Download a model
ollama pull gemma4:e2b

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Start Open Omniscience
uvicorn src.api.main:app --reload
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

For more details, see [LLM Setup Guide](docs/LLM_SETUP_GUIDE.md)

---

## 🏗️ Architecture

### Core Components

```
┌────────────────────────────────────────────────────────────────┐
│                      Open Omniscience                          │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌────────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │    Ingestion   │    │   Database  │    │   API Server    │  │
│  │(Beautifullsoup)│    │  (SQLite/   │    │   (FastAPI)     │  │
│  │                │    │  PostgreSQL)│    │                 │  │
│  └─────────┬──────┘    └──────┬──────┘    └────────┬────────┘  │
│            │                  │                    │           │
│            ▼                  ▼                    ▼           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    LLM Service Layer                    │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │   │
│  │  │  LLMService │  │ ModelManager│  │   Ollama API    │  │   │
│  │  │             │  │             │  │  (External)     │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Web Crawler** | Custom Python | Website scraping and mirroring |
| **Backend** | Python 3.8+ | Core application logic |
| **API Framework** | FastAPI | REST API endpoints |
| **Database** | SQLite / PostgreSQL | Data storage |
| **LLM Runtime** | Ollama | Local LLM execution |
| **LLM Models** | Llama, Mistral, Phi, Qwen, Gemma | Text processing |
| **Frontend** | HTML5, CSS, JavaScript | User interface |
| **Deployment** | Direct Python | Simple and portable deployment |
| **Platform** | Debian 13 | Primary supported platform |

---

## 📦 Installation

### Prerequisites

- **Operating System:** Debian 13 (Trixie)
- **Platform:** GUI environment recommended (X11 or Wayland)
- **Dependencies:** All dependencies are installed automatically by the installer

For advanced users who need manual installation options, see [DOCUMENTATION.md](DOCUMENTATION.md).

## 🎯 Features

### Core Features

#### Web Scraping & Crawling
- **Custom Web Crawler**: Robust website scraping and mirroring capabilities
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

For complete API documentation, see [API Documentation](#api-endpoints) (if available) or explore the interactive API docs at `/docs` when the server is running.

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
- **OS:** Debian 13

#### Recommended (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 models)
- **GPU:** NVIDIA with 8GB VRAM (recommended for better performance)
- **OS:** Debian 13

#### High-End (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM
- **OS:** Debian 13

### Performance Optimizations

- **Model Caching**: Downloaded models are persisted for reuse
- **GPU Acceleration**: Automatic GPU utilization when available
- **Batch Processing**: Efficient handling of multiple items
- **Connection Pooling**: Database connection pooling
- **Response Caching**: (Planned) Caching for repeated queries

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

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

This project is licensed under the GPLv3 License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Ollama**: For the excellent local LLM runtime
- **Meta, Mistral AI, Microsoft, Alibaba, Google**: For the open-source models
- **FastAPI**: For the excellent API framework
- **All Contributors**: For their valuable contributions and feedback

---


## 🏗️ Pillar 2: Scientific Rigor

**Pillar 2** implements comprehensive **Scientific Rigor** capabilities for Open-Omniscience, providing statistical validation, peer-review simulation, and reproducibility scoring.

### Overview

Pillar 2 consists of three fully implemented phases:

#### ✅ Phase 2.1: Statistical Validation Engine
Comprehensive statistical testing and confidence interval calculation:
- **Statistical Tests**: T-tests, chi-square, ANOVA, regression, correlation, non-parametric tests
- **Confidence Intervals**: Means, proportions, differences, variances, regression coefficients, odds ratios
- **Effect Sizes**: Cohen's d, eta-squared, Cramer's V
- **Tech Stack**: scipy, numpy, pandas, statsmodels (optional), pingouin (optional)

#### ✅ Phase 2.2: Peer-Review Simulation (Local)
Multi-model cross-validation using local LLMs:
- **Multi-model Reviews**: Get reviews from multiple local LLM models (Ollama)
- **Blind Reviews**: Hide metadata for unbiased reviews
- **Quality Scoring**: Automatic score (0-100), decision, and confidence extraction
- **Consensus Scoring**: Calculate agreement across models with pairwise comparisons
- **Tech Stack**: requests, Ollama (optional)

#### ✅ Phase 2.3: Reproducibility Scoring
Data lineage tracking and reproducibility assessment:
- **Reproducibility Scores**: Calculate scores (0-100) for data availability, method transparency, code availability, documentation
- **Grade Assignment**: Automatic letter grades (A+, A, B, C, D, F)
- **Data Lineage**: Track data from source to final analysis with hash-based integrity
- **Report Generation**: Generate comprehensive Markdown reports with FAIR principles checklist
- **Tech Stack**: pandas, json, hashlib

### Quick Start

```bash
# Navigate to Pillar 2 directory
cd pillar2

# Install dependencies
pip install -r requirements.txt

# Run all tests (101 tests)
PYTHONPATH=pillar2 python -m pytest tests/ -v

# Run demos
PYTHONPATH=pillar2 python examples/statistical_validation_demo.py
PYTHONPATH=pillar2 python examples/peer_review_demo.py
```

### Documentation

- [Pillar 2 README](pillar2/README.md) - Detailed documentation
- [API Documentation](pillar2/README.md#usage) - Usage examples
- [Reproducibility Template](pillar2/src/reports/reproducibility_template.md) - Report template

### Test Coverage

| Phase | Tests | Status |
|-------|-------|--------|
| 2.1 | 60 | ✅ All passing |

---

## 🛡️ Pillar 3: Deception Defense (FOSS)

**Pillar 3** implements comprehensive **Deception Defense** capabilities for Open-Omniscience, providing detection of deepfakes, propaganda, and cognitive biases using 100% open-source models that work completely offline.

### Overview

Pillar 3 consists of four phases, with all phases (3.1-3.4) fully implemented:

#### ✅ Phase 3.1: Multi-Modal Verification
Cross-media consistency checking and metadata validation:
- **Metadata Validation**: EXIF data extraction and validation for images, ID3 tags for audio, video metadata using OpenCV
- **Cross-Media Consistency**: Check consistency across images, audio, video, and text
- **Tampering Detection**: Detect stripped metadata, editing software signatures, GPS inconsistencies
- **Timestamp Analysis**: Verify timestamp consistency across multiple media items
- **Tech Stack**: Pillow, OpenCV, pydub, ffmpeg-python

#### ✅ Phase 3.2: Deepfake Detection
AI-generated media detection using artifact analysis:
- **Image Deepfake Detection**: Blurring detection, compression artifacts, face-specific artifacts, unnatural colors
- **Video Deepfake Detection**: Frame-by-frame analysis, temporal consistency, optical flow analysis, flickering detection
- **Audio Deepfake Detection**: Spectral anomaly detection, noise patterns, phase inconsistencies, temporal artifacts
- **Model Support**: ONNX Runtime (FaceForensics++, WildDeepfake), TensorFlow models
- **Tech Stack**: OpenCV, ONNX Runtime, TensorFlow (optional), librosa, pydub

#### ✅ Phase 3.3: Propaganda & Cognitive Bias Detection
Text-based manipulation detection:
- **Propaganda Detection**: 15+ propaganda techniques (appeal to emotion, bandwagon, false dilemma, etc.)
- **Loaded Language**: Emotional and manipulative term detection
- **Logical Fallacies**: False cause, hasty generalization, circular reasoning detection
- **Cognitive Bias Detection**: 20+ cognitive biases (confirmation, anchoring, framing, etc.)
- **Tech Stack**: spaCy, NLTK, VADER, TextBlob

#### ✅ Phase 3.4: Disinformation Campaign Tracking
Network analysis and bot detection:
- **Network Analysis**: Co-occurrence graph construction, community detection, centrality analysis
- **Bot Detection**: Behavioral analysis, content similarity, posting patterns, network-based detection
- **Narrative Tracking**: Temporal analysis of disinformation campaigns
- **Tech Stack**: NetworkX, igraph, python-louvain, leidenalg, scikit-learn

### Quick Start

```bash
# Navigate to Pillar 3 directory
cd pillar3

# Install dependencies
pip install -r requirements.txt

# Run tests
PYTHONPATH=pillar3 python -m pytest tests/ -v

# Run metadata validation demo
PYTHONPATH=pillar3 python examples/metadata_validation_demo.py

# Use in Python
from pillar3.src.analysis import MetadataValidator, DeepfakeDetector

validator = MetadataValidator()
result = validator.validate_image("photo.jpg")
print(f"Validation score: {result.score:.1f}/100")

detector = DeepfakeDetector()
result = detector.detect_image("suspect.jpg")
print(f"Deepfake confidence: {result.confidence:.2%}")
```

### Documentation

- [Pillar 3 README](pillar3/README.md) - Detailed documentation
- [PILLAR3_SUMMARY.md](pillar3/PILLAR3_SUMMARY.md) - Comprehensive implementation summary
- [requirements.txt](pillar3/requirements.txt) - Complete dependency list

### Current Status

| Phase | Status | Files | Lines of Code |
|-------|--------|-------|---------------|
| 3.1 Multi-Modal Verification | ✅ Complete | 2 files | ~2,500 |
| 3.2 Deepfake Detection | ✅ Complete | 1 file | ~700 |
| 3.3 Propaganda & Bias | 🔄 In Progress | 1 file | ~800 |
| 3.4 Campaign Tracking | 📅 Planned | 0 files | 0 |

### Key Features

✅ **100% FOSS** - All dependencies are open-source  
✅ **Offline Capable** - All functions work offline with no cloud dependencies  
✅ **Modular** - Clean, reusable components  
✅ **Well-Documented** - Complete documentation and examples  
✅ **Tested** - Comprehensive test suite foundation  

| 2.2 | 51 | ✅ All passing |
| 2.3 | 17 | ✅ All passing |
| **Total** | **101** | ✅ All passing |

### Key Features

✅ **100% FOSS** - All core dependencies are open-source  
✅ **Offline Capable** - All functions work offline (except optional Ollama API calls)  
✅ **Comprehensive** - 101 tests covering all functionality  
✅ **Modular** - Clean, reusable components  
✅ **Well-Documented** - Complete documentation and examples  

## 📚 Documentation

### 🎯 Start Here
**📖 [DOCUMENTATION.md](DOCUMENTATION.md)** - Unified documentation index with complete table of contents

This master documentation file provides a single entry point for all Open-Omniscience documentation, organized by user type and use case.

### 📖 Core Documentation
- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Master documentation index (RECOMMENDED STARTING POINT)

### 🔧 Technical Guides
- [docs/LLM_SETUP_GUIDE.md](docs/LLM_SETUP_GUIDE.md) - Local LLM setup, configuration, and usage
- [docs/DATABASE.md](docs/DATABASE.md) - Database setup guide
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) - Development guide (includes LLM development)
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) - User guide (includes LLM features)
- [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) - Complete API reference
- [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) - Production deployment guide

### 🛡️ Compliance & Ethics
- [CONTRIBUTING.md](docs/CONTRIBUTING.md) - Contribution guidelines
- [ETHICS.md](docs/ETHICS.md) - Ethical guidelines and compliance
- [SECURITY.md](docs/SECURITY.md) - Security practices and recommendations
- [docs/COMPLIANCE.md](docs/COMPLIANCE.md) - Legal compliance framework

---

## 🆘 Support

- **GitHub Issues**: Report bugs and request features
- **Discussions**: Ask questions and share ideas
- **Documentation**: Check the docs first!
- **Email**: contact@ideotion.com

---

## 📅 Changelog

### Version 0.04 (Current)
- Comprehensive debugging
- GUI complete redesign

### Version 0.03
- **NEW:** Local LLM support with comprehensive text processing capabilities
- **NEW:** 40 pre-configured models (Gemma 4, Llama 4, Phi-4, Qwen 3, NLLB, T5, BERT, etc.)
- **NEW:** 10+ API endpoints for LLM operations
- **NEW:** Direct Python deployment for maximum portability
- **NEW:** Automated setup scripts
- **NEW:** Comprehensive test suite for LLM features
- Updated API version to 0.03
- Enhanced documentation with LLM guides

### Version 0.2.0 (Previous)
- Initial MVP release
- Core web scraping and data management
- Basic API endpoints
- SQLite and PostgreSQL support

For detailed changelog, see [ChangeLog](ChangeLog) or [GitHub Releases](https://github.com/ideotion/Open-Omniscience/releases).

---

**© 2026 Ideotion. All rights reserved.**

*Built with ❤️ for investigative journalism and ethical data analysis.*
