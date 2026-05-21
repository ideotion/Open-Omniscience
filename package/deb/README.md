# Open-Omniscience Debian Package

This directory contains the Debian package (.deb) for Open-Omniscience, allowing for easy installation on Debian-based systems (Ubuntu, Debian, etc.).

## Package Information

- **Package Name**: open-omniscience
- **Version**: 0.02-1
- **Architecture**: all
- **Maintainer**: Open-Omniscience Team <team@ideotion.com>
- **Dependencies**: python3, python3-venv, python3-pip, git, curl

## Installation

### Method 1: Direct Download and Install

```bash
# Download the .deb package
wget https://github.com/ideotion/Open-Omniscience/raw/0.02/package/deb/open-omniscience_0.02-1_all.deb

# Install the package
sudo dpkg -i open-omniscience_0.02-1_all.deb

# Fix any missing dependencies
sudo apt-get install -f
```

### Method 2: Clone Repository and Install

```bash
# Clone the repository
git clone --branch 0.02 https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Install the package
sudo dpkg -i package/deb/open-omniscience_0.02-1_all.deb

# Fix any missing dependencies
sudo apt-get install -f
```

## Post-Installation

After installation:

1. The package installs all files to `/opt/open-omniscience/`
2. The post-installation script automatically runs the `install` script
3. All dependencies (Python, Git, etc.) are automatically installed
4. A symlink is created at `/usr/local/bin/open-omniscience` for easy access

## Starting Open-Omniscience

```bash
# Navigate to the installation directory
cd /opt/open-omniscience

# Start the application (development mode)
source venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# OR start with Gunicorn (production mode)
source venv/bin/activate
pip install gunicorn
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
```

## With LLM Support

To enable LLM features, you need to install Ollama separately:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama server
ollama serve &

# Download a model
ollama pull gemma4:e2b

# Start Open-Omniscience with LLM enabled
cd /opt/open-omniscience
source venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Configuration

The main configuration file is located at `/opt/open-omniscience/.env`. Edit this file to customize your installation:

```bash
# Database configuration
DATABASE_URL=sqlite:///./data/open_omniscience.db

# Server configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# LLM configuration
LLM_ENABLED=true
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=gemma4:e2b
```

## Uninstallation

To remove Open-Omniscience:

```bash
# Stop the application
pkill -f uvicorn
pkill -f gunicorn

# Remove the package
sudo dpkg -r open-omniscience

# Remove data (optional - this will delete all your data!)
sudo rm -rf /opt/open-omniscience
```

## Troubleshooting

### Python not found
Ensure Python 3.8+ is installed:
```bash
sudo apt-get install python3 python3-pip python3-venv
```

### pip not found
```bash
sudo apt-get install python3-pip
```

### Module not found errors
Activate the virtual environment and install dependencies:
```bash
cd /opt/open-omniscience
source venv/bin/activate
pip install -r requirements-core.txt
```

### Port already in use
Check what's using port 8000 and either stop it or change the port in `.env`:
```bash
ss -tulnp | grep 8000
```

## Files Included

- `/opt/open-omniscience/` - Main application directory
- `/opt/open-omniscience/venv/` - Python virtual environment
- `/opt/open-omniscience/api/` - API source code
- `/opt/open-omniscience/installer/` - Installation scripts
- `/opt/open-omniscience/docs/` - Documentation
- `/usr/local/bin/open-omniscience` - Symlink for easy access

## Support

For support, please:
1. Check the [official documentation](https://github.com/ideotion/Open-Omniscience)
2. Review the [troubleshooting guide](https://github.com/ideotion/Open-Omniscience/blob/0.02/docs/TROUBLESHOOTING.md)
3. Open an issue on [GitHub](https://github.com/ideotion/Open-Omniscience/issues)

---

*Last updated: 2025-05-21*
