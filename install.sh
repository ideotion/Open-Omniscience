#!/bin/bash
# Open-Omniscience - Simple Debian Installer
# =========================================
# This script provides a simple, clean installation of Open-Omniscience
# for Debian-based systems ONLY.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
#   OR: ./install.sh
#
# Author: Open-Omniscience Team
# License: GNU GPLv3

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

REPO_URL="https://github.com/ideotion/Open-Omniscience.git"
REPO_BRANCH="0.03"
INSTALL_DIR="${HOME}/open-omniscience"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Logging Functions
# ============================================================================

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
    exit 1
}

# ============================================================================
# Environment Detection
# ============================================================================

# Check if running on Debian
check_debian() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "debian" ]]; then
            log_error "This installer is for Debian-based systems only."
        fi
        log_info "Detected Debian $VERSION_ID"
    else
        log_error "Cannot determine OS. This installer is for Debian-based systems only."
    fi
}

# Check if running as root
is_root() {
    [ "$(id -u)" -eq 0 ]
}

# Run command with sudo if not root
run_with_sudo() {
    if is_root; then
        "$@"
    else
        sudo "$@"
    fi
}

# ============================================================================
# Installation Functions
# ============================================================================

# Install system dependencies
install_dependencies() {
    log_info "Installing system dependencies..."
    
    run_with_sudo apt-get update -qq
    run_with_sudo apt-get install -y -qq \
        git \
        python3 \
        python3-pip \
        python3-venv \
        python3-tk \
        curl \
        wget
    
    log_success "System dependencies installed"
}

# Clone repository
clone_repository() {
    log_info "Cloning repository..."
    
    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Repository already exists at $INSTALL_DIR"
        cd "$INSTALL_DIR"
        if ! git fetch origin "$REPO_BRANCH" 2>/dev/null; then
            log_error "Failed to fetch repository"
        fi
        if ! git checkout "$REPO_BRANCH" 2>/dev/null; then
            log_error "Failed to checkout branch $REPO_BRANCH"
        fi
        if ! git pull origin "$REPO_BRANCH" 2>/dev/null; then
            log_error "Failed to update repository"
        fi
    else
        if ! git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1; then
            log_error "Failed to clone repository"
        fi
        cd "$INSTALL_DIR"
    fi
    
    log_success "Repository cloned to $INSTALL_DIR"
}

# Setup Python environment
setup_python() {
    log_info "Setting up Python environment..."
    
    cd "$INSTALL_DIR"
    
    # Create virtual environment
    if [ ! -d "venv" ]; then
        log_info "Creating virtual environment..."
        if ! python3 -m venv venv 2>/dev/null; then
            log_error "Failed to create virtual environment. Ensure python3-venv is installed."
        fi
    fi
    
    # Activate and install dependencies
    source venv/bin/activate
    
    log_info "Upgrading pip..."
    pip install --upgrade pip
    
    log_info "Installing Python dependencies..."
    if [ -f "requirements.txt" ]; then
        if ! pip install -r requirements.txt 2>/dev/null; then
            log_error "Failed to install Python dependencies"
        fi
    else
        log_error "requirements.txt not found in repository"
    fi
    
    log_success "Python environment set up"
}

# Create desktop launcher
create_launcher() {
    # Only create launcher if we have a GUI environment
    if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
        log_info "Creating desktop launcher..."
        
        mkdir -p "$HOME/.local/share/applications"
        
        cat > "$HOME/.local/share/applications/open-omniscience.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Open-Omniscience
GenericName=Global Intelligence Platform
Comment=Ethical Global Intelligence Platform for Investigative Journalism
Exec=bash -c "cd $INSTALL_DIR && source venv/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port 8000"
Icon=utilities-terminal
Terminal=true
Categories=Utility;News;Information;
Path=$INSTALL_DIR
StartupWMClass=OpenOmniscience
EOF
        
        chmod +x "$HOME/.local/share/applications/open-omniscience.desktop"
        
        # Update desktop database if available
        if command -v update-desktop-database &>/dev/null; then
            update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
        fi
        
        log_success "Desktop launcher created in your application menu"
    else
        log_info "No GUI environment detected. Skipping desktop launcher creation."
    fi
}

# ============================================================================
# Main Installation
# ============================================================================

main() {
    echo ""
    echo "  ██████╗  ██████╗ ███╗   ██╗██████╗ ██╗███╗   ██╗████████╗"
    echo "  ██╔══██╗██╔═══██╗████╗  ██║██╔══██╗██║████╗  ██║╚══██╔══╝"
    echo "  ██║  ██║██║   ██║██╔██╗ ██║██║   ██║██╔██╗ ██║   ██║   "
    echo "  ██║  ██║██║   ██║██║╚██╗██║██║   ██║██║╚██╗██║   ██║   "
    echo "  ██████╔╝╚██████╔╝██║ ╚████║╚██████╔╝██║ ╚████║   ██║   "
    echo "  ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   "
    echo ""
    echo "  Open-Omniscience - Debian Installer"
    echo "  =================================="
    echo ""
    
    # Check environment
    check_debian
    
    # Install dependencies
    install_dependencies
    
    # Clone repository
    clone_repository
    
    # Setup Python
    setup_python
    
    # Create desktop launcher
    create_launcher
    
    # Final message
    echo ""
    log_success "Installation Complete!"
    echo ""
    echo "  Open-Omniscience has been installed to: $INSTALL_DIR"
    echo ""
    echo "  To start Open-Omniscience:"
    echo "    cd $INSTALL_DIR"
    echo "    source venv/bin/activate"
    echo "    uvicorn api.main:app --reload"
    echo ""
    echo "  Then open: http://localhost:8000"
    echo ""
    echo "  For production deployment:"
    echo "    pip install gunicorn"
    echo "    gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app"
    echo ""
}

# Run main
main "$@"
