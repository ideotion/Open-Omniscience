# Open-Omniscience Unified Documentation

**Version:** 0.03  
**Last Updated:** 2025-06-18  
**Single Source of Truth for All Users**

> 🎯 **UNIFIED DOCUMENTATION**: This single file replaces the need for separate Qubes and regular Linux documentation. All installation methods and usage patterns are covered here, with smart adaptation to your environment.

---

## 🌟 Quick Start (All Platforms)

### 🚀 Single Command Installation (Recommended)

```bash
# This single command works for ALL environments:
# - Regular Debian/Ubuntu (with or without GUI)
# - Qubes OS (automatically detected)
# - Headless servers
# - Various architectures

curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

**The installer will:**
1. ✅ **Ask if you're using Qubes OS** (required - Qubes is undetectable by design)
2. ✅ Detect if you have a GUI environment
3. ✅ Adapt the installation method based on your answers
4. ✅ Install all dependencies automatically
5. ✅ Configure everything properly for your environment
6. ✅ Provide clear next steps

**Important:** Since Qubes OS is designed to be undetectable from within VMs for security, the installer **always asks** you about Qubes OS. This is by design and ensures security.

---

## 🎯 Installation Methods

### 💬 User Prompts (Required for Qubes OS)

**Important:** Qubes OS is designed to be **undetectable from within VMs** for security reasons. Therefore, the installer **always asks** you about Qubes OS rather than trying to auto-detect it.

You will be asked:

```
Note: Qubes OS is designed to be undetectable from within VMs for security
Are you installing on Qubes OS [y/N]: 
Do you have a GUI environment available [y/N]: 
Proceed with installation [Y/n]: 
```

**For Qubes OS users:** You **must** answer "yes" to the first question to get the multi-VM installation.

**For regular Linux users:** Just press Enter (accepts "no" by default) for all questions.

### 🔄 Environment Adaptation

Based on your answers, the installer adapts:

| Your Answer | Installation Type | What Happens |
|-------------|------------------|--------------|
| **Qubes OS: Yes** | Multi-VM architecture | Creates 4 isolated VMs with proper configuration |
| **Qubes OS: No** | Standard installation | Installs on current system |
| **GUI: Yes** | With desktop launcher | Creates application menu entry |
| **GUI: No** | Headless mode | No desktop integration |

---

## 📋 Installation Details by Environment

### 🖥️ Regular Linux (Debian/Ubuntu/etc.)

#### With GUI Environment
```bash
# Automatic installation with GUI
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash

# What happens:
# 1. Detects Debian-based system
# 2. Installs python3-tk for GUI
# 3. Creates virtual environment
# 4. Installs all dependencies
# 5. Creates desktop launcher
# 6. Starts the application
```

#### Without GUI (Headless Server)
```bash
# Automatic installation without GUI
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash

# What happens:
# 1. Detects headless environment
# 2. Skips GUI dependencies
# 3. Creates virtual environment
# 4. Installs all dependencies
# 5. Provides manual start instructions
```

### 🛡️ Qubes OS (R4.1+)

#### Automatic Qubes Installation
```bash
# In dom0 or any AppVM with network access:
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash

# What happens:
# 1. Detects Qubes OS environment
# 2. Checks for Debian 12 template (installs if needed)
# 3. Creates 4 isolated VMs:
#    - open-omniscience-api (Blue) - HTTP API & coordination
#    - open-omniscience-db (Green) - PostgreSQL database (no network)
#    - open-omniscience-scraper (Yellow) - Web scraping workers
#    - open-omniscience-ai (Red) - LLM integration
# 4. Installs Open-Omniscience in each VM
# 5. Configures proper network isolation
# 6. Provides Qubes-specific next steps
```

#### Manual Qubes Setup (If Needed)
```bash
# 1. Clone repository in any AppVM
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# 2. Run unified installer
sudo ./UNIFIED_INSTALL.sh

# 3. Follow the prompts
```

---

## 🏗️ Architecture Overview

### Regular Linux Architecture
```
┌─────────────────────────────────────────────────────────┐
│                    Your Computer                          │
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

### Qubes OS Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        Qubes OS Environment                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │
│  │   API VM     │    │  Scraper VM  │    │   DB VM      │         │
│  │  (Blue)      │◄──►│  (Yellow)    │    │  (Green)     │         │
│  │              │    │              │    │              │         │
│  │  FastAPI    │    │  Scraper    │    │ PostgreSQL  │         │
│  │  Nginx      │    │  Worker     │    │  Database    │         │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘         │
│         │                     │                     │               │
│         ▼                     ▼                     ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Qubes RPC Communication                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │                                         │
│                         ▼                                         │
│              ┌───────────────────────────┐                         │
│              │    sys-whonix ProxyVM     │                         │
│              │  (Network Access Gateway) │                         │
│              └───────────────────────────┘                         │
│                                                                      │
│  ┌──────────────┐                                                   │
│  │   AI VM      │                                                   │
│  │  (Red)       │                                                   │
│  │              │                                                   │
│  │  LLM Models │                                                   │
│  │  Ollama     │                                                   │
│  └──────────────┘                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎛️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/open_omniscience.db` | Database connection URL |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | CORS allowed origins |
| `OLLAMA_HOST` | `0.0.0.0` | Ollama server host |
| `MAX_CONTEXT_LENGTH` | `8192` | Maximum context length for LLM |
| `MAX_TOKENS` | `4096` | Maximum tokens to generate |

### Configuration Files

- `configs/settings.yaml` - Main application settings
- `configs/sources.yml` - News source configurations
- `configs/models.yml` - LLM model configurations
- `.env` - Environment variables (not committed to repo)

---

## 🚀 Usage

### Starting the Application

#### Regular Linux
```bash
# Navigate to installation directory
cd ~/open-omniscience

# Activate virtual environment
source venv/bin/activate

# Start the application
uvicorn api.main:app --reload

# Access at: http://localhost:8000
```

#### Qubes OS
```bash
# Start all VMs
qvm-start open-omniscience-api
qvm-start open-omniscience-db
qvm-start open-omniscience-scraper
qvm-start open-omniscience-ai

# Access the API (from any VM with network access)
qvm-run -u open-omniscience-api curl http://localhost:8000

# Or use the API from your regular VM
curl http://localhost:8000
```

### Common Commands

| Command | Description |
|---------|-------------|
| `uvicorn api.main:app --reload` | Start with auto-reload (development) |
| `uvicorn api.main:app --host 0.0.0.0 --port 8000` | Start for external access |
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
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

### Skip LLM Installation
```bash
# For minimal installation without LLM features
export OPEN_OMNISCIENCE_SKIP_LLM=true
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

### Skip Desktop Launcher
```bash
# For headless servers
export OPEN_OMNISCIENCE_SKIP_LAUNCHER=true
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

---

## 🛠️ Troubleshooting

### Common Issues

#### Installation Fails with Permission Denied
**Solution:** Run with sudo or as root (especially on Qubes OS)
```bash
sudo ./UNIFIED_INSTALL.sh
```

#### Qubes OS: Template Not Found
**Solution:** Install Debian 12 template first
```bash
# In dom0
sudo qubesctl state.sls qvm.template-debian-12
```

#### GUI Dependencies Missing
**Solution:** Install manually
```bash
# Debian/Ubuntu
sudo apt-get install python3-tk

# Fedora/RHEL
sudo dnf install python3-tkinter
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
bash -x ./UNIFIED_INSTALL.sh

# Or with specific debug
DEBUG=true ./UNIFIED_INSTALL.sh
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
- **OS:** Debian-based Linux (Ubuntu, Debian, etc.)

### Recommended (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 models)
- **GPU:** NVIDIA with 8GB VRAM (recommended)
- **OS:** Debian-based Linux (Ubuntu, Debian, etc.)

### Qubes OS Specific
- **Qubes Version:** R4.1+
- **Template:** Debian 12 (Trixie)
- **Memory:** 8GB RAM (16GB recommended for AI)
- **Disk Space:** 20GB free space across VMs

### High-End (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM
- **OS:** Debian-based Linux (Ubuntu, Debian, etc.)

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
uvicorn api.main:app --reload
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
- **NEW:** Unified installer that adapts to any environment
- **NEW:** Single documentation file for all users
- **NEW:** Automatic Qubes OS detection
- **NEW:** Smart environment adaptation
- **FIXED:** Version inconsistencies across repository
- **FIXED:** Syntax error in Qubes installer
- **UPDATED:** All documentation to reference version 0.03

### Version 0.02 (Previous)
- Initial LLM support with comprehensive text processing
- 40 pre-configured models (Gemma 4, Llama 4, Phi-4, Qwen 3, etc.)
- Direct Python deployment for maximum portability

---

## 🎉 Summary

**Open-Omniscience is now simpler than ever!**

✅ **One installer** for all environments  
✅ **One documentation file** for all users  
✅ **Automatic detection** of your setup  
✅ **Smart adaptation** to Qubes or regular Linux  
✅ **Clear guidance** every step of the way  

**Just run:**
```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

**And you're done!** The installer handles everything automatically.

---

*Unified Documentation v0.03 | Last Updated: 2025-06-18 | Open-Omniscience Team*