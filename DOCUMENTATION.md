# Open-Omniscience Documentation

**Version:** 0.03  
**Last Updated:** 2025-06-18  
**Master Documentation Index for Debian 13**

> 📚 **START HERE**: This is the master entry point for all Open-Omniscience documentation on Debian 13. Use the table of contents below to navigate to specific topics.

---

## 🌟 Quick Start Guide

### For Debian 13 Users (Recommended)
```bash
# Simple installation for Debian 13
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

**What this does:**
- ✅ Detects Debian 13 environment
- ✅ Installs required dependencies
- ✅ Creates virtual environment
- ✅ Installs all Python dependencies
- ✅ Configures environment automatically
- ✅ Creates desktop launcher (if GUI available)
- ✅ Open-Omniscience runs at: **http://localhost:8000**

### For Headless Servers (Debian 13)
```bash
# Installation on headless Debian 13 server
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

---

## 📖 Documentation Table of Contents

### 🏗️ Core Documentation
| Topic | File | Description | Priority |
|-------|------|-------------|----------|
| **Main Overview** | [`README.md`](README.md) | Complete platform overview, features, API | ⭐⭐⭐ |
| **Documentation** | [`UNIFIED_DOCUMENTATION.md`](UNIFIED_DOCUMENTATION.md) | Complete guide for Debian 13 | ⭐⭐⭐ |

### 🔧 Technical Documentation
| Topic | File | Description | Priority |
|-------|------|-------------|----------|
| **API Reference** | [`docs/API_DOCUMENTATION.md`](docs/API_DOCUMENTATION.md) | Complete API endpoints & usage | ⭐⭐⭐ |
| **Developer Guide** | [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Development setup & workflow | ⭐⭐⭐ |
| **User Guide** | [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | How to use the platform | ⭐⭐⭐ |
| **Database Setup** | [`docs/DATABASE.md`](docs/DATABASE.md) | Database configuration | ⭐⭐ |
| **LLM Setup** | [`docs/LLM_SETUP_GUIDE.md`](docs/LLM_SETUP_GUIDE.md) | Local LLM configuration | ⭐⭐⭐ |
| **Deployment** | [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) | Production deployment | ⭐⭐ |

### 🛡️ Compliance & Ethics
| Topic | File | Description | Priority |
|-------|------|-------------|----------|
| **Ethics** | [`docs/ETHICS.md`](docs/ETHICS.md) | Ethical guidelines | ⭐⭐⭐ |
| **Security** | [`docs/SECURITY.md`](docs/SECURITY.md) | Security practices | ⭐⭐⭐ |
| **Compliance** | [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) | Legal compliance | ⭐⭐ |
| **Notices** | [`docs/NOTICES.md`](docs/NOTICES.md) | Third-party notices | ⭐ |

### 📊 Architecture & Implementation
| Topic | File | Description | Priority |
|-------|------|-------------|----------|
| **Implementation** | [`docs/IMPLEMENTATION_SUMMARY.md`](docs/IMPLEMENTATION_SUMMARY.md) | Architecture overview | ⭐⭐ |
| **Changes** | [`docs/CHANGES.md`](docs/CHANGES.md) | Change history | ⭐ |

### 📦 Packaging
| Topic | File | Description | Priority |
|-------|------|-------------|----------|
| **Debian Package** | [`package/deb/README.md`](package/deb/README.md) | Debian 13 packaging | ⭐⭐ |
| **AppImage** | [`package/appimage/`](package/appimage/) | AppImage packaging | ⭐ |
| **Launcher** | [`package/launcher/README.md`](package/launcher/README.md) | Desktop launcher | ⭐ |

### 🏗️ Pillar Documentation

#### Pillar 1: Data Ingestion
- **File:** [`pillar1/README.md`](pillar1/README.md)
- **Description:** Web scraping, data collection, and ingestion
- **Priority:** ⭐⭐⭐

#### Pillar 2: Scientific Rigor
- **File:** [`pillar2/README.md`](pillar2/README.md)
- **Description:** Statistical validation, reproducibility scoring
- **Priority:** ⭐⭐⭐
- **Tests:** 101 tests, all passing

#### Pillar 3: Deception Defense
- **File:** [`pillar3/README.md`](pillar3/README.md)
- **Description:** Deepfake detection, propaganda detection, cognitive bias analysis
- **Priority:** ⭐⭐⭐
- **Features:** 100% FOSS, offline capable

#### Pillar 4: Legal Admissibility
- **File:** [`pillar4/README.md`](pillar4/README.md)
- **Description:** Compliance, audit trails, legal framework
- **Priority:** ⭐⭐

---

## 🎯 Installation Methods

### Method 1: Using the Install Script (Recommended)
```bash
# Download and run the Debian 13 installer
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
```

### Method 2: Manual Installation
```bash
# Clone the repository
git clone --branch 0.03 https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Install dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-tk git curl

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Start the application
uvicorn src.api.main:app --reload
```

### Method 3: Using Debian Package
```bash
# Download and install the .deb package
wget https://github.com/ideotion/Open-Omniscience/raw/0.03/package/deb/open-omniscience_0.03-1_all.deb
sudo dpkg -i open-omniscience_0.03-1_all.deb
sudo apt-get install -f
```

---

## 🚀 Usage Examples

### Starting the Application
```bash
# Navigate to installation directory
cd ~/open-omniscience

# Activate virtual environment
source venv/bin/activate

# Start development server
uvicorn src.api.main:app --reload

# Access at: http://localhost:8000
```

### Production Deployment
```bash
# Install Gunicorn
pip install gunicorn

# Start with Gunicorn
 gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 src.api.main:app
```

---

## 📊 System Requirements

### Minimum (Core Features Only)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB
- **OS:** Debian 13 (Trixie)

### Recommended (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 models)
- **GPU:** NVIDIA with 8GB VRAM (recommended)
- **OS:** Debian 13 (Trixie)

### High-End (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM
- **OS:** Debian 13 (Trixie)

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

---

## 🙏 Support

- **GitHub Issues:** Report bugs and request features
- **Documentation:** Check this file first!
- **Email:** contact@ideotion.com

---

## 📅 Version History

### Version 0.03 (Current)
- **NEW:** Simplified installation for Debian 13
- **NEW:** Unified documentation for Debian 13 users
- **UPDATED:** All documentation to reference version 0.03
- **REMOVED:** Qubes OS specific installation methods

### Version 0.02 (Previous)
- Initial LLM support with comprehensive text processing
- 40 pre-configured models (Gemma 4, Llama 4, Phi-4, Qwen 3, etc.)
- Direct Python deployment for maximum portability

---

*Documentation v0.03 | Last Updated: 2025-06-18 | Open-Omniscience Team | Target: Debian 13 (Trixie)*
