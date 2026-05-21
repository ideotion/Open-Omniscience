# Open-Omniscience Installation Guide

**Version:** 0.02  
**Last Updated:** 2026  
**Platform:** Debian-based Linux (Ubuntu, Debian, etc.)

This guide provides comprehensive instructions for installing Open-Omniscience on Debian-based Linux systems.

## 🚀 Quick Start

The fastest way to install Open-Omniscience is with our unified installation script:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install.sh | bash
```

This script will:
- ✅ Automatically detect your Debian-based system
- ✅ Install all required dependencies (Docker, Docker Compose, Git, etc.)
- ✅ Clone the Open-Omniscience repository
- ✅ Install Python dependencies in a virtual environment
- ✅ Configure the environment automatically
- ✅ Create a desktop launcher for easy access
- ✅ Optionally install Ollama for LLM support
- ✅ Start the services and verify everything works

## 📋 System Requirements

### Minimum Requirements (Core Features Only)
- **Operating System:** Debian-based Linux (Ubuntu 20.04+, Debian 10+)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB free disk space
- **Architecture:** x86_64, amd64, aarch64, arm64

### Recommended Requirements (With LLM Support)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB (for 3-4 LLM models)
- **GPU:** NVIDIA with 8GB+ VRAM (optional, for better LLM performance)

### High-End Requirements (Full LLM Capabilities)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ (for multiple large models)
- **GPU:** NVIDIA with 24GB+ VRAM

## 🛠️ Prerequisites

### Required Packages
The installer will automatically install these if missing:
- `curl` - For downloading files
- `git` - For cloning the repository
- `wget` - For downloading dependencies
- `ca-certificates` - For SSL/TLS support
- `gnupg` - For package verification
- `lsb-release` - For system information
- `software-properties-common` - For repository management

### Docker Requirements
- **Docker Engine** 20.10+
- **Docker Compose** 2.0+ (plugin or standalone)

## 📦 Installation Methods

### Method 1: Unified Install Script (Recommended)

```bash
# Download and run the unified installer
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install.sh | bash
```

**What this does:**
1. Checks system prerequisites
2. Installs basic system packages
3. Installs Docker and Docker Compose
4. Optionally installs Ollama for LLM support
5. Clones the Open-Omniscience repository
6. Installs Python dependencies
7. Configures the environment
8. Creates a desktop launcher
9. Starts the services
10. Verifies the installation

### Method 2: Manual Installation

If you prefer manual control over the installation process:

#### Step 1: Install System Dependencies

```bash
# Update package lists
sudo apt-get update

# Install basic packages
sudo apt-get install -y git curl wget ca-certificates gnupg lsb-release software-properties-common

# Install Python 3.8+ and venv
sudo apt-get install -y python3 python3-pip python3-venv python3-tk
```

#### Step 2: Install Docker

```bash
# Remove old Docker versions
sudo apt-get remove -y docker docker-engine docker.io containerd runc

# Install Docker using official script
curl -fsSL https://get.docker.com | sh

# Add current user to docker group (requires logout/login)
sudo usermod -aG docker $USER

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker
```

#### Step 3: Install Docker Compose

```bash
# Install Docker Compose plugin (recommended)
sudo apt-get install -y docker-compose-plugin

# OR install standalone docker-compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### Step 4: Clone Repository

```bash
# Clone the repository
git clone --branch 0.02 --depth 1 https://github.com/ideotion/Open-Omniscience.git ~/open-omniscience

# Navigate to the directory
cd ~/open-omniscience
```

#### Step 5: Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install core dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements-core.txt

# Optionally install LLM dependencies
pip install -r requirements-llm.txt
```

#### Step 6: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Create data directories
mkdir -p data audit logs

# Optionally configure settings
nano configs/settings.yaml
```

#### Step 7: Start Services

```bash
# Build and start containers
docker compose up -d --build

# Check if services are running
docker compose ps

# View logs
docker compose logs -f
```

### Method 3: GUI Installer

For users who prefer a graphical interface:

```bash
# First, ensure python3-tk is installed
sudo apt-get install -y python3-tk

# Then run the GUI installer
cd ~/open-omniscience
python3 installer/gui_installer.py
```

The GUI installer provides:
- Interactive 5-step wizard
- System requirements check with visual feedback
- Progress tracking and real-time logs
- Application launcher creation
- Automatic service startup

## 🎯 Post-Installation Setup

### Access the Application

After successful installation, access Open-Omniscience at:
```
http://localhost:8000
```

### Verify Installation

```bash
# Check if containers are running
docker compose ps

# Check application health
curl http://localhost:8000/api/health

# View application logs
docker compose logs web
```

### Install LLM Models (Optional)

If you installed Ollama for LLM support:

```bash
# Pull the default model
ollama pull gemma4:e2b

# List available models
ollama list

# Check Ollama status
curl http://localhost:11434/api/tags
```

### Configure LLM Support

To enable LLM features in Docker:

```bash
# Create a docker-compose.override.yml file
cat > docker-compose.override.yml << 'EOF'
version: '3.8'

services:
  web:
    environment:
      - OLLAMA_HOST=http://host.docker.internal:11434
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF

# Restart services
docker compose down && docker compose up -d --build
```

## 🔧 Troubleshooting

### Common Issues and Solutions

#### 1. Docker Permission Denied

**Symptom:** `Got permission denied while trying to connect to the Docker daemon socket`

**Solution:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, or restart
logout
```

#### 2. Port 8000 Already in Use

**Symptom:** `Address already in use` or `port is already allocated`

**Solution:**
```bash
# Find and kill the process using port 8000
sudo lsof -i :8000
sudo kill -9 <PID>

# Or change the port in docker-compose.yml
# Edit the ports section to use a different port
```

#### 3. Docker Compose Not Found

**Symptom:** `docker-compose: command not found`

**Solution:**
```bash
# Use docker compose plugin instead
sudo apt-get install -y docker-compose-plugin

# Or create a symlink
sudo ln -s /usr/bin/docker /usr/local/bin/docker-compose
```

#### 4. Python Dependencies Installation Failed

**Symptom:** `pip install failed` or `ModuleNotFoundError`

**Solution:**
```bash
# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install dependencies one by one
pip install fastapi uvicorn sqlalchemy
```

#### 5. Application Not Starting

**Symptom:** Container starts but application doesn't respond

**Solution:**
```bash
# Check container logs
docker compose logs web

# Check if the health endpoint works
curl http://localhost:8000/api/health

# If using SQLite, ensure the data directory is writable
chmod -R 755 data/
```

#### 6. Database Connection Issues

**Symptom:** `Database connection failed` or `sqlite3.OperationalError`

**Solution:**
```bash
# Ensure data directory exists and is writable
mkdir -p data
chmod 755 data

# Check database URL in .env file
nano .env

# Ensure DATABASE_URL points to a writable location
DATABASE_URL=sqlite:///./data/open_omniscience.db
```

### Debugging Commands

```bash
# Check all running containers
docker ps -a

# View container logs
docker compose logs

# Inspect container
docker inspect open-omniscience-web

# Test database connection
python3 -c "from src.database.models import engine; print('DB OK')"

# Test API endpoints
curl -v http://localhost:8000/api/health
curl -v http://localhost:8000/api/sources
```

## 📊 Verification Checklist

- [ ] Docker is installed and running (`docker --version`)
- [ ] Docker Compose is available (`docker compose version`)
- [ ] Repository is cloned to `~/open-omniscience`
- [ ] Python dependencies are installed (`pip list`)
- [ ] Data directories exist (`data/`, `audit/`, `logs/`)
- [ ] Configuration files exist (`configs/settings.yaml`, `.env`)
- [ ] Containers are running (`docker compose ps`)
- [ ] Application responds to health check (`curl http://localhost:8000/api/health`)
- [ ] Web interface is accessible at `http://localhost:8000`

## 🔄 Updating Open-Omniscience

```bash
# Navigate to installation directory
cd ~/open-omniscience

# Pull latest changes
git pull origin 0.02

# Update Python dependencies
source venv/bin/activate
pip install --upgrade -r requirements-core.txt

# Rebuild and restart containers
docker compose down
docker compose up -d --build
```

## 🏗️ Configuration Options

### Environment Variables

Create or edit `.env` file in the installation directory:

```bash
# Database configuration
DATABASE_URL=sqlite:///./data/open_omniscience.db

# Server configuration
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# LLM configuration (if using Ollama)
OLLAMA_HOST=http://localhost:11434
DOWNLOAD_DEFAULT_MODELS=false
AUTO_DOWNLOAD_MODELS=true
MAX_CONTEXT_LENGTH=8192
MAX_TOKENS=4096
```

### Settings Configuration

Edit `configs/settings.yaml`:

```yaml
database:
  url: sqlite:///./data/open_omniscience.db

scraping:
  rate_limit_ms: 1000
  user_agent: "OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"
  respect_robots_txt: true

llm:
  enabled: true
  ollama_host: "http://localhost:11434"
  default_model: "gemma4:e2b"
  auto_download: false

server:
  host: "0.0.0.0"
  port: 8000
  debug: false
```

## 🚨 Security Considerations

### Production Deployment

For production environments:

1. **Use HTTPS:** Set up a reverse proxy with SSL/TLS
2. **Use PostgreSQL:** Instead of SQLite for better performance and reliability
3. **Configure Authentication:** Add authentication for API endpoints
4. **Limit Origins:** Set `ALLOWED_ORIGINS` to specific domains only
5. **Use Docker Secrets:** For sensitive configuration

### Docker Security

```bash
# Run containers as non-root users (already configured in Dockerfile)
# Use read-only filesystems where possible
# Limit container capabilities
# Use health checks for monitoring
```

## 📚 Additional Resources

- **Documentation:** https://github.com/ideotion/Open-Omniscience
- **API Documentation:** http://localhost:8000/docs (after installation)
- **Issue Tracker:** https://github.com/ideotion/Open-Omniscience/issues
- **Discussions:** https://github.com/ideotion/Open-Omniscience/discussions

## 🎉 Next Steps

After successful installation:

1. **Access the web interface** at `http://localhost:8000`
2. **Configure news sources** through the admin interface
3. **Start scraping** to populate your database
4. **Explore LLM features** (if Ollama is installed)
5. **Check the documentation** for advanced usage

---

**© 2026 Ideotion. All rights reserved.**

*Built with ❤️ for investigative journalism and ethical data analysis.*
