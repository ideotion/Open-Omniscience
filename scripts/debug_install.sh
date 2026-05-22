#!/bin/bash
# Open-Omniscience Installation Debug Tool
# ========================================
# This script helps debug installation issues on Debian-based systems
# Usage: bash scripts/debug_install.sh

set -uo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

echo ""
echo "=========================================="
echo "Open-Omniscience Installation Debug Tool"
echo "=========================================="
echo ""

# Check if running as root
if [ "$(id -u)" -eq 0 ]; then
    log_warning "Running as root - some checks may not be accurate"
fi

# 1. Check System Information
log_info "=== System Information ==="
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
echo "Architecture: $(uname -m)"
echo "Kernel: $(uname -r)"
echo ""

# 2. Check Python
log_info "=== Python Check ==="
if command -v python3 &>/dev/null; then
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    echo "Python version: $PYTHON_VERSION"
    
    # Check if it's a supported version
    if python3 -c "import sys; assert sys.version_info >= (3, 8) and sys.version_info < (3, 14)" 2>/dev/null; then
        log_success "Python version is supported"
    else
        log_error "Python version is NOT supported (need 3.8-3.13)"
    fi
    
    # Check python3-venv
    if python3 -m venv --help &>/dev/null; then
        log_success "python3-venv is available"
    else
        log_error "python3-venv is NOT installed"
        log_info "Fix: sudo apt install python3-venv"
    fi
else
    log_error "Python 3 is NOT installed"
    log_info "Fix: sudo apt install python3"
fi
echo ""

# 3. Check Required Commands
log_info "=== Required Commands Check ==="
for cmd in git curl wget; do
    if command -v $cmd &>/dev/null; then
        log_success "$cmd is installed: $(command -v $cmd)"
    else
        log_error "$cmd is NOT installed"
        log_info "Fix: sudo apt install $cmd"
    fi
done
echo ""

# 4. Check Repository
log_info "=== Repository Check ==="
if [ -d ".git" ]; then
    log_success "Repository found"
    echo "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    echo "Commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
else
    log_error "Not in a repository directory"
    log_info "Fix: git clone https://github.com/ideotion/Open-Omniscience.git"
fi
echo ""

# 5. Check Virtual Environment
log_info "=== Virtual Environment Check ==="
if [ -d "venv" ]; then
    log_success "Virtual environment found"
    
    # Check if uvicorn is installed
    if "venv/bin/uvicorn" --version &>/dev/null; then
        log_success "uvicorn is installed in venv: $(venv/bin/uvicorn --version)"
    else
        log_error "uvicorn is NOT installed in venv"
        log_info "Fix: source venv/bin/activate && pip install uvicorn[standard]"
    fi
    
    # Check if fastapi is installed
    if "venv/bin/python" -c "import fastapi; print(fastapi.__version__)" &>/dev/null; then
        log_success "fastapi is installed in venv"
    else
        log_error "fastapi is NOT installed in venv"
        log_info "Fix: source venv/bin/activate && pip install fastapi"
    fi
    
    # Check if sqlalchemy is installed
    if "venv/bin/python" -c "import sqlalchemy; print(sqlalchemy.__version__)" &>/dev/null; then
        log_success "sqlalchemy is installed in venv"
    else
        log_error "sqlalchemy is NOT installed in venv"
        log_info "Fix: source venv/bin/activate && pip install sqlalchemy"
    fi
else
    log_error "Virtual environment NOT found"
    log_info "Fix: python3 -m venv venv"
fi
echo ""

# 6. Check Port Availability
log_info "=== Port Check ==="
for port in 8000 11434; do
    if command -v ss &>/dev/null; then
        if ss -tuln | grep -q ":$port "; then
            log_error "Port $port is in use"
            log_info "Fix: sudo lsof -i :$port && sudo kill <PID>"
        else
            log_success "Port $port is available"
        fi
    elif command -v netstat &>/dev/null; then
        if netstat -tuln | grep -q ":$port "; then
            log_error "Port $port is in use"
        else
            log_success "Port $port is available"
        fi
    else
        log_warning "Cannot check port $port (no ss or netstat)"
    fi
done
echo ""

# 7. Check Systemd Service (if applicable)
log_info "=== Systemd Service Check ==="
if command -v systemctl &>/dev/null; then
    SERVICE_FILE="/etc/systemd/system/open-omniscience.service"
    if [ -f "$SERVICE_FILE" ]; then
        log_success "Systemd service file found"
        
        # Check if service is enabled
        if systemctl is-enabled open-omniscience &>/dev/null; then
            log_success "Service is enabled"
        else
            log_warning "Service is NOT enabled"
            log_info "Fix: sudo systemctl enable open-omniscience"
        fi
        
        # Check if service is running
        if systemctl is-active open-omniscience &>/dev/null; then
            log_success "Service is running"
        else
            log_warning "Service is NOT running"
            log_info "Fix: sudo systemctl start open-omniscience"
        fi
        
        # Check service status
        log_info "Service status:"
        systemctl status open-omniscience --no-pager 2>&1 | head -10 || true
    else
        log_info "Systemd service file NOT found"
        log_info "This is normal if you haven't created a systemd service"
    fi
else
    log_info "systemctl not available (not a systemd system)"
fi
echo ""

# 8. Check Journal Logs (if applicable)
log_info "=== Recent Logs Check ==="
if command -v journalctl &>/dev/null; then
    log_info "Recent open-omniscience logs:"
    journalctl -u open-omniscience -n 20 --no-pager 2>&1 || echo "No logs found"
else
    log_info "journalctl not available"
fi
echo ""

# 9. Test Import
log_info "=== Import Test ==="
if [ -d "venv" ]; then
    log_info "Testing imports..."
    if "venv/bin/python" -c "from src.api.main import app; print('Import successful')" 2>&1; then
        log_success "Main application imports successfully"
    else
        log_error "Main application import FAILED"
        log_info "This is likely the root cause of startup issues"
    fi
else
    log_info "Cannot test imports - no venv found"
fi
echo ""

# 10. Summary
log_info "=== Summary ==="
echo ""
echo "If you're experiencing issues:"
echo "1. Make sure Python 3.8-3.13 is installed"
echo "2. Install python3-venv: sudo apt install python3-venv"
echo "3. Create venv: python3 -m venv venv"
echo "4. Activate venv: source venv/bin/activate"
echo "5. Install dependencies: pip install -r requirements.txt"
echo "6. Explicitly install uvicorn: pip install uvicorn[standard]"
echo "7. Test startup: uvicorn src.api.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "For Python 3.13, use: pip install -r requirements-python313.txt"
echo ""
