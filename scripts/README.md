# Open-Omniscience Debug Tools

This directory contains debugging and diagnostic tools for Open-Omniscience installation and runtime issues.

## 🔍 debug_install.sh

The main debugging script that checks your system for common installation issues.

### Usage

```bash
# Make it executable (if not already)
chmod +x scripts/debug_install.sh

# Run it from the repository root
bash scripts/debug_install.sh
```

### What It Checks

1. **System Information** - OS, architecture, kernel
2. **Python Installation** - Version, venv support
3. **Required Commands** - git, curl, wget
4. **Repository Status** - Branch, commit
5. **Virtual Environment** - Existence, uvicorn, fastapi, sqlalchemy
6. **Port Availability** - 8000 (app), 11434 (Ollama)
7. **Systemd Service** - Service file, enabled status, running status
8. **Journal Logs** - Recent Open-Omniscience logs
9. **Import Test** - Tests if the main application can be imported

### Color Coding

- 🟢 **GREEN** - Success/Passed
- 🟡 **YELLOW** - Warning/Not optimal
- 🔴 **RED** - Error/Failed
- 🔵 **BLUE** - Information

### Common Issues Detected

- Missing Python or wrong version
- Missing python3-venv package
- Missing git, curl, or wget
- Virtual environment not created
- uvicorn not installed in venv
- Port 8000 already in use
- Systemd service not enabled or running
- Import errors in the application

### Quick Fixes

The script provides actionable fixes for each issue detected. For example:

```
Fix: sudo apt install python3-venv
Fix: python3 -m venv venv
Fix: source venv/bin/activate && pip install uvicorn[standard]
```

## 🐛 When to Use This Tool

Use `debug_install.sh` when:

1. The installation script fails
2. The service won't start
3. You get import errors
4. Ports are already in use
5. Systemd service fails to start
6. You're unsure what's wrong with your setup

## 📝 Example Output

```
==========================================
Open-Omniscience Installation Debug Tool
==========================================

[INFO] === System Information ===
OS: Debian GNU/Linux 12 (bookworm)
Architecture: x86_64
Kernel: 6.1.0-18-amd64

[INFO] === Python Check ===
Python version: 3.11.2
[SUCCESS] Python version is supported
[SUCCESS] python3-venv is available

[INFO] === Required Commands Check ===
[SUCCESS] git is installed: /usr/bin/git
[SUCCESS] curl is installed: /usr/bin/curl
[SUCCESS] wget is installed: /usr/bin/wget

... (more checks)

[INFO] === Summary ===

If you're experiencing issues:
1. Make sure Python 3.8-3.13 is installed
2. Install python3-venv: sudo apt install python3-venv
3. Create venv: python3 -m venv venv
4. Activate venv: source venv/bin/activate
5. Install dependencies: pip install -r requirements.txt
6. Explicitly install uvicorn: pip install uvicorn[standard]
7. Test startup: uvicorn src.api.main:app --host 0.0.0.0 --port 8000

For Python 3.13, use: pip install -r requirements-python313.txt
```

## 🔧 Additional Debugging Tips

### Check Journal Logs

```bash
# View recent logs
journalctl -u open-omniscience -n 50 --no-pager

# Follow logs in real-time
journalctl -u open-omniscience -f
```

### Test Manual Startup

```bash
cd ~/open-omniscience
source venv/bin/activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Check Port Usage

```bash
# Check what's using port 8000
sudo lsof -i :8000
sudo ss -tulnp | grep 8000

# Kill process on port 8000
sudo kill $(sudo lsof -t -i :8000)
```

### Test Imports

```bash
cd ~/open-omniscience
source venv/bin/activate
python -c "from src.api.main import app; print('Import successful')"
```

### Check Python Version Compatibility

```bash
# Check if your Python version is supported
python3 -c "import sys; assert sys.version_info >= (3, 8) and sys.version_info < (3, 14)"

# If using Python 3.13, install compatible versions
pip install -r requirements-python313.txt
```

## 📚 Python 3.13 Compatibility

Python 3.13 is fully supported, but requires specific minimum versions of some packages:

- SQLAlchemy >= 2.0.25
- Alembic >= 1.13.0
- Cryptography >= 42.0.0
- PyYAML >= 6.0.1

These are already specified in `requirements-python313.txt`.

## 🎯 Quick Start for Clean Debian VM

```bash
# 1. Install prerequisites
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl wget

# 2. Install Open-Omniscience
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash

# 3. If issues, run debug tool
bash scripts/debug_install.sh

# 4. Start manually if needed
cd ~/open-omniscience
source venv/bin/activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```
