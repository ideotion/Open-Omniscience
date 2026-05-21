# Open-Omniscience Installation Guide

**Version:** 0.02  
**Last Updated:** 2025-05-21  
**Platform:** Debian-based Linux (Ubuntu, Debian, etc.), macOS, Windows (WSL2)

This guide provides comprehensive instructions for installing Open-Omniscience on your system using direct Python installation.

## 🚀 Quick Start

The fastest way to install Open-Omniscience is with our unified installation script:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install.sh | bash
```

This script will:
- ✅ Automatically detect your Debian-based system
- ✅ Install all required dependencies (Python, Git, etc.)
- ✅ Clone the Open-Omniscience repository
- ✅ Set up the virtual environment
- ✅ Install all Python packages
- ✅ Configure the environment automatically
- ✅ Create a desktop launcher
- ✅ Optionally install Ollama for LLM support

**After installation:**
- Open-Omniscience will be running at: **http://localhost:8000**
- Application launcher created in your OS app menu
- All dependencies installed and configured

For advanced users who need manual installation options, see the sections below.

---

## 📋 Prerequisites

### Supported Operating Systems
- **Linux:** Debian 11+, Ubuntu 20.04+, and derivatives
- **macOS:** 10.15+ (Catalina and later)
- **Windows:** 10/11 with WSL2 (Windows Subsystem for Linux 2)

### Minimum System Requirements
- **CPU:** 2 cores
- **RAM:** 4 GB
- **Storage:** 20 GB free disk space
- **Python:** 3.8 or higher

### Recommended System Requirements
- **CPU:** 4+ cores
- **RAM:** 8+ GB
- **Storage:** 50 GB+ free disk space
- **Python:** 3.10 or higher

---

## 🛠️ Manual Installation

If you prefer to install manually or want more control over the process, follow these steps:

### Step 1: Install System Dependencies

#### Ubuntu/Debian
```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3 python3-pip python3-venv git curl wget

# Verify installation
python3 --version
pip3 --version
```

#### CentOS/RHEL
```bash
# Update package lists
sudo yum update -y

# Install required packages
sudo yum install -y python3 python3-pip git curl wget

# Verify installation
python3 --version
pip3 --version
```

#### macOS
```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required packages
brew install python git

# Verify installation
python3 --version
pip3 --version
```

#### Windows (WSL2)
```powershell
# Install WSL2 (if not already installed)
wsl --install

# Install Ubuntu from Microsoft Store
# Open Ubuntu terminal and run:
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl wget
```

### Step 2: Clone the Repository

```bash
# Clone the Open-Omniscience repository
git clone --branch 0.02 https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
```

### Step 3: Set Up Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
# Linux/macOS:
source venv/bin/activate

# Windows (in WSL2):
source venv/bin/activate
```

### Step 4: Install Python Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install core dependencies
pip install -r requirements.txt

# For LLM features (optional)
pip install -r requirements.txt
```

### Step 5: Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration (optional)
nano .env  # or use your preferred editor
```

Default configuration uses SQLite, which requires no additional setup. For PostgreSQL, see the [Database Configuration](#database-configuration) section.

### Step 6: Install Ollama (Optional - for LLM Features)

```bash
# Install Ollama for local LLM support
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama server
ollama serve &

# Verify installation
ollama --version
```

### Step 7: Start Open-Omniscience

#### For Development
```bash
# Start with auto-reload
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### For Production
```bash
# Install Gunicorn
pip install gunicorn

# Start with Gunicorn (4 workers)
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
```

### Step 8: Verify Installation

Open your browser and navigate to: **http://localhost:8000**

You should see the Open-Omniscience interface.

---

## ⚙️ Configuration

### Environment Variables

Edit the `.env` file to customize your installation:

```bash
# Database configuration
DATABASE_URL=sqlite:///./data/open_omniscience.db

# Server configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
SERVER_DEBUG=false

# LLM configuration (if using Ollama)
LLM_ENABLED=true
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=gemma4:e2b
AUTO_DOWNLOAD_MODELS=false

# Scraping configuration
SCRAPING_RATE_LIMIT_MS=1000
SCRAPING_USER_AGENT="OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"
SCRAPING_RESPECT_ROBOTS_TXT=true
```

### Database Configuration

#### SQLite (Default)
No configuration needed. The application will automatically create a SQLite database at `data/open_omniscience.db`.

#### PostgreSQL (Recommended for Production)

1. Install PostgreSQL:
```bash
# Ubuntu/Debian
sudo apt install -y postgresql postgresql-contrib

# CentOS/RHEL
sudo yum install -y postgresql-server postgresql-contrib
```

2. Create database and user:
```bash
sudo -u postgres psql -c "CREATE DATABASE open_omniscience;"
sudo -u postgres psql -c "CREATE USER omniscience WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO omniscience;"
```

3. Update `.env` file:
```bash
DATABASE_URL=postgresql+psycopg2://omniscience:your_secure_password@localhost/open_omniscience
```

---

## 🚀 Using the GUI Installer

For a graphical installation experience, run the GUI installer:

```bash
# Navigate to the installer directory
cd Open-Omniscience/installer

# Run the GUI installer
python3 gui_installer.py
```

The GUI installer provides:
- Step-by-step visual installation
- System requirements check
- Automatic dependency installation
- Configuration options
- Progress tracking

---

## 📚 Post-Installation Steps

### Create Desktop Launcher (Optional)

To create a desktop shortcut for easy access:

```bash
# Create desktop file
mkdir -p ~/.local/share/applications

cat > ~/.local/share/applications/open-omniscience.desktop << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Open-Omniscience
Comment=Ethical Global Intelligence Platform
Exec=bash -c "cd $HOME/open-omniscience && source venv/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload & xdg-open http://localhost:8000"
Icon=$HOME/open-omniscience/docs/open-omniscience-icon.png
Terminal=true
Categories=Development;Journalism;Research;Utility;
StartupWMClass=Open-Omniscience
EOF

# Make executable
chmod +x ~/.local/share/applications/open-omniscience.desktop

# Update desktop database
update-desktop-database ~/.local/share/applications
```

### Set Up as a System Service (Optional)

To run Open-Omniscience as a background service:

```bash
# Create systemd service file
sudo nano /etc/systemd/system/open-omniscience.service
```

Add the following content:
```ini
[Unit]
Description=Open-Omniscience
After=network.target

[Service]
User=your_username
WorkingDirectory=/home/your_username/open-omniscience
Environment="PATH=/home/your_username/open-omniscience/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/home/your_username/open-omniscience/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable open-omniscience
sudo systemctl start open-omniscience
```

---

## 🔧 Troubleshooting

### Common Issues

#### Python not found
- Ensure Python 3.8+ is installed
- On some systems, you may need to use `python3` explicitly

#### pip not found
- Install pip: `sudo apt install python3-pip` (Ubuntu/Debian)
- Or: `sudo yum install python3-pip` (CentOS/RHEL)

#### Module not found errors
- Activate the virtual environment: `source venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

#### Port already in use
- Check what's using port 8000: `ss -tulnp | grep 8000`
- Either stop the conflicting service or change the port in `.env`

#### Permission errors
- Ensure you have write permissions in the installation directory
- Try running with `sudo` if needed (not recommended for production)

### Getting Help

- Check the [FAQ](FAQ.md)
- Review the [Troubleshooting Guide](TROUBLESHOOTING.md)
- Open an issue on [GitHub](https://github.com/ideotion/Open-Omniscience/issues)

---

## 📖 Next Steps

1. **Explore the interface** - Navigate through the application
2. **Configure your settings** - Customize the configuration in `.env`
3. **Set up LLM models** - If using LLM features, download models with `ollama pull`
4. **Start collecting data** - Begin using the scraping and data collection features
5. **Review documentation** - Check out the other guides in the `docs/` directory

---

## 🔗 Additional Resources

- [Official Documentation](https://github.com/ideotion/Open-Omniscience)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
- [LLM Setup Guide](docs/LLM_SETUP_GUIDE.md)
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [API Documentation](docs/API_DOCUMENTATION.md)

---

*Last updated: 2025-05-21*
