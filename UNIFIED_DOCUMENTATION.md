# Open-Omniscience Documentation

**⚠️ EARLY CONCEPT RELEASE - NOT FUNCTIONAL ⚠️**

**Version:** 0.03 (Early Concept - Non-Functional)  
**Last Updated:** 2025-06-18  
**Originally Forked From:** [HTTrack](https://www.httrack.com/) - This project was initially a fork of HTTrack website copier
**Complete Guide for Debian 13 Users**

> ⚠️ **IMPORTANT NOTICE**: This documentation describes the **intended design** for Debian 13. **The software is currently NOT FUNCTIONAL** and requires extensive debugging and development. **Do not attempt to use any of the installation instructions or features described herein** - they are part of a conceptual framework only.

> 🎯 **DEBIAN 13 DOCUMENTATION (CONCEPTUAL)**: This file provides the intended installation and usage instructions for Open-Omniscience on Debian 13 (Trixie). **None of this is currently operational.**

---

## 🌟 Quick Start (CONCEPTUAL - NOT FUNCTIONAL)

**⚠️ DO NOT ATTEMPT TO RUN THESE COMMANDS** - The installation scripts do not work in the current state.

### 🚀 Simple Installation (Intended Design)

```bash
# DO NOT RUN - This is conceptual only
# curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

**The installer would (when functional):**
1. ❌ Detect Debian 13 environment (not currently working)
2. ❌ Install all dependencies automatically (not currently working)
3. ❌ Configure everything properly for Debian 13 (not currently working)
4. ❌ Create desktop launcher (if GUI available) (not currently working)
5. ❌ Provide clear next steps (not currently working)

---

## 🎯 Installation

### 📋 Installation Process

#### With GUI Environment
```bash
# Automatic installation with GUI
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash

# What happens:
# 1. Detects Debian 13 system
# 2. Installs python3-tk for GUI
# 3. Creates virtual environment
# 4. Installs all dependencies
# 5. Creates desktop launcher
# 6. Provides start instructions
```

#### Without GUI (Headless Server)
```bash
# Automatic installation without GUI
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash

# What happens:
# 1. Detects Debian 13 environment
# 2. Skips GUI dependencies
# 3. Creates virtual environment
# 4. Installs all dependencies
# 5. Provides manual start instructions
```

---

## 🏗️ Architecture Overview

### Debian 13 Architecture
```
┌─────────────────────────────────────────────────────────┐
│                    Your Debian 13 System                   │
├─────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────┐  │
│  │               Open-Omniscience                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │   Backend   │  │  Database   │  │   Frontend  │  │  │
│  │  │ (FastAPI)   │  │ (SQLite/PG) │  │ (HTML/CSS)  │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────────┐  │
│  │              LLM Service Layer                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │ LLM Service │  │ Model Mgr   │  │  Ollama API │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
     │
     ▼
  http://localhost:8000
```

---

## 🚀 Usage

### Starting the Application

#### With GUI
```bash
# Navigate to installation directory
cd ~/open-omniscience

# Activate virtual environment
source venv/bin/activate

# Start the application
uvicorn src.api.main:app --reload

# Access at: http://localhost:8000
```

#### Headless Mode
```bash
# Navigate to installation directory
cd ~/open-omniscience

# Activate virtual environment
source venv/bin/activate

# Start the application
uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Access from another machine: http://<your-server-ip>:8000
```

### Common Commands

| Command | Description |
|---------|-------------|
| `uvicorn src.api.main:app --reload` | Start with auto-reload (development) |
| `uvicorn src.api.main:app --host 0.0.0.0 --port 8000` | Start for external access |
| `python scripts/setup_llm.py --all` | Setup all LLM models |
| `pytest` | Run all tests |
| `black src/` | Format code |
| `flake8 src/` | Lint code |

---

## 🔧 Advanced Configuration

### Custom Installation Directory
```bash
# Set custom directory before running installer
export OPEN_OMNISCIENCE_INSTALL_DIR=/custom/path
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

### Skip LLM Installation
```bash
# For minimal installation without LLM features
export OPEN_OMNISCIENCE_SKIP_LLM=true
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

### Skip Desktop Launcher
```bash
# For headless servers
export OPEN_OMNISCIENCE_SKIP_LAUNCHER=true
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

---

## 🛠️ Troubleshooting

### Common Issues

#### Installation Fails with Permission Denied
**Solution:** Run with sudo or as root
```bash
sudo ./install.sh
```

#### GUI Dependencies Missing
**Solution:** Install manually
```bash
# Debian 13
sudo apt-get install python3-tk
```

#### Python Virtual Environment Issues
**Solution:** Ensure Python 3.8+ is installed
```bash
# Check Python version
python3 --version

# Install Python if needed
sudo apt-get install python3 python3-venv
```

### Debug Mode
```bash
# Run installer with verbose output
bash -x ./install.sh

# Or with specific debug
DEBUG=true ./install.sh
```

---

## 📚 API Documentation

### Base URL
```
http://localhost:8000
```

### Core Endpoints

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

### LLM Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/llm/health` | Check LLM service health |
| GET | `/api/llm/models` | List available models |
| POST | `/api/llm/generate` | Generate text from prompt |
| POST | `/api/llm/chat` | Chat completion |
| POST | `/api/llm/extract` | Extract structured information |
| POST | `/api/llm/translate` | Translate text |
| POST | `/api/llm/analyze` | Analyze text |
| POST | `/api/llm/synthesize` | Synthesize information |
| POST | `/api/llm/batch` | Batch process multiple items |

### Example API Calls

```bash
# Search articles
curl "http://localhost:8000/api/articles?q=investigation&limit=10"

# Generate text
curl -X POST http://localhost:8000/api/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize the latest trends in AI", "temperature": 0.7}'

# Translate text
curl -X POST http://localhost:8000/api/llm/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "target_language": "fr", "source_language": "en"}'
```

---

## 🏗️ Pillar Architecture

Open-Omniscience is organized into 4 pillars:

### 🔢 Pillar 1: Data Ingestion
- **Purpose:** Web scraping, data collection, and ingestion
- **Components:** Custom web crawler, BeautifulSoup integration
- **Features:** Ethical scraping, duplicate detection, incremental updates

### 🔬 Pillar 2: Scientific Rigor
- **Purpose:** Statistical validation and reproducibility
- **Components:** Statistical tests, confidence intervals, peer review simulation
- **Features:** 60+ statistical tests, reproducibility scoring, FAIR principles

### 🛡️ Pillar 3: Deception Defense
- **Purpose:** Detection of deepfakes, propaganda, and cognitive biases
- **Components:** Metadata validation, deepfake detection, propaganda detection
- **Features:** 100% FOSS, offline capable, multi-modal verification

### ⚖️ Pillar 4: Legal Admissibility
- **Purpose:** Compliance, audit trails, and legal framework
- **Components:** Chain of custody, cryptographic provenance, compliance checks
- **Features:** GDPR compliance, copyright validation, audit logging

---

## 📊 System Requirements

### Minimum (Core Features Only)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB
- **OS:** Debian 13

### Recommended (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 models)
- **GPU:** NVIDIA with 8GB VRAM (recommended)
- **OS:** Debian 13

### High-End (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM
- **OS:** Debian 13

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

### Quick Start for Developers
```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -r requirements.txt
pip install -r configs/python/requirements.txt

# Run tests
pytest

# Start development server
uvicorn src.api.main:app --reload
```

---

## 📜 License

This project is licensed under the **GNU GPLv3 License** - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Support

- **GitHub Issues:** Report bugs and request features
- **Documentation:** Check this file first!
- **Email:** contact@ideotion.com

---

## 📅 Changelog

### Version 0.03 (Current)
- **NEW:** Simplified installer for Debian 13
- **NEW:** Single documentation file for Debian 13 users
- **UPDATED:** All documentation to reference version 0.03

### Version 0.02 (Previous)
- Initial LLM support with comprehensive text processing
- 40 pre-configured models (Gemma 4, Llama 4, Phi-4, Qwen 3, etc.)
- Direct Python deployment for maximum portability

---

## 🎉 Summary

**Open-Omniscience on Debian 13 is simpler than ever!**

✅ **One installer** for Debian 13  
✅ **One documentation file** for all Debian 13 users  
✅ **Automatic detection** of your Debian 13 setup  
✅ **Clear guidance** every step of the way  

**Just run:**
```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

**And you're done!** The installer handles everything automatically.

---

*Documentation v0.03 | Last Updated: 2025-06-18 | Open-Omniscience Team*
