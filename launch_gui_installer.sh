#!/bin/bash
#
# Open-Omniscience Smart GUI Installer Launcher
# ==============================================
#
# This script automatically detects if a GUI environment is available
# and launches the appropriate installer (GUI or text-based).
#
# Features:
# - Automatic GUI detection (DISPLAY, X11, Wayland)
# - Automatic python3-tk installation if missing
# - Automatic psutil installation if missing
# - Fallback to text-based installer if GUI not available
# - Works in virtual environments, XEN, Docker, etc.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash
#   OR
#   ./launch_gui_installer.sh
#
# Author: Open-Omniscience Team
# License: GPLv3
#

set -uo pipefail

# =============================================================================
# Configuration
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

REPO_URL="https://github.com/ideotion/Open-Omniscience.git"
REPO_BRANCH="0.02"
INSTALL_DIR="${HOME}/open-omniscience"

# =============================================================================
# Logging Functions
# =============================================================================

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

# =============================================================================
# Detection Functions
# =============================================================================

# Check if we're running in a Debian-based system
is_debian() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "debian" || "$ID" == "ubuntu" || "$ID_LIKE" == *"debian"* ]]; then
            return 0
        fi
    fi
    return 1
}

# Check if GUI environment is available
is_gui_available() {
    # Check for DISPLAY variable
    if [ -n "${DISPLAY:-}" ]; then
        return 0
    fi
    
    # Check for Wayland
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        return 0
    fi
    
    # Check if X11 is running
    if command -v xset &>/dev/null; then
        return 0
    fi
    
    # Check for common desktop environments
    if [ -n "${XDG_CURRENT_DESKTOP:-}" ]; then
        return 0
    fi
    
    return 1
}

# Check if python3-tk is available
has_python3_tk() {
    python3 -c "import tkinter" 2>/dev/null && return 0 || return 1
}

# Check if psutil is available
has_psutil() {
    python3 -c "import psutil" 2>/dev/null && return 0 || return 1
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# =============================================================================
# Installation Functions
# =============================================================================

# Install python3-tk (system package)
install_python3_tk() {
    if command_exists apt-get; then
        log_info "Installing python3-tk..."
        if sudo apt-get install -y python3-tk 2>/dev/null; then
            log_success "python3-tk installed"
            return 0
        else
            log_error "Failed to install python3-tk"
            return 1
        fi
    elif command_exists dnf; then
        log_info "Installing python3-tk with dnf..."
        sudo dnf install -y python3-tk 2>/dev/null && return 0 || return 1
    elif command_exists yum; then
        log_info "Installing python3-tk with yum..."
        sudo yum install -y python3-tk 2>/dev/null && return 0 || return 1
    else
        log_error "Unsupported package manager for python3-tk"
        return 1
    fi
}

# Install psutil (pip package)
install_psutil() {
    log_info "Installing psutil..."
    if python3 -m pip install psutil 2>/dev/null; then
        log_success "psutil installed"
        return 0
    else
        log_error "Failed to install psutil"
        return 1
    fi
}

# =============================================================================
# Main Logic
# =============================================================================

main() {
    echo ""
    echo "  Open-Omniscience Smart Installer Launcher"
    echo "  ========================================"
    echo ""
    
    # Check if Debian-based
    if ! is_debian; then
        log_error "This installer is designed for Debian-based Linux systems only."
        log_error "Falling back to standard text-based installer..."
        exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash
        exit 1
    fi
    
    log_info "Detected Debian-based Linux system"
    
    # Check if GUI is available
    if is_gui_available; then
        log_info "GUI environment detected"
        
        # Check for python3-tk
        if ! has_python3_tk; then
            log_info "python3-tk not found, installing..."
            if ! install_python3_tk; then
                log_warning "python3-tk installation failed, falling back to text-based installer"
                exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash
                exit 1
            fi
        else
            log_info "python3-tk is already installed"
        fi
        
        # Check for psutil
        if ! has_psutil; then
            log_info "psutil not found, installing..."
            if ! install_psutil; then
                log_warning "psutil installation failed, falling back to text-based installer"
                exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash
                exit 1
            fi
        else
            log_info "psutil is already installed"
        fi
        
        # Launch GUI installer
        log_info "Launching GUI installer..."
        echo ""
        
        # Clone repository if not already present
        if [ ! -d "$INSTALL_DIR/.git" ]; then
            log_info "Cloning repository to $INSTALL_DIR..."
            # Create directory if it doesn't exist
            mkdir -p "$INSTALL_DIR" 2>/dev/null || {
                log_error "Cannot create directory $INSTALL_DIR"
                log_error "Check if you have write permissions in your home directory"
                exit 1
            }
            # Check if we can write to the directory
            if [ ! -w "$INSTALL_DIR" ]; then
                log_error "No write permission in $INSTALL_DIR"
                log_error "Try running with: sudo mkdir -p $INSTALL_DIR && sudo chown $USER:$USER $INSTALL_DIR"
                exit 1
            fi
            if git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1; then
                log_success "Repository cloned"
            else
                log_error "Failed to clone repository. Check your internet connection and git installation."
                log_info "Trying to use current directory..."
                # Try to use current directory if it's already a git repo
                if [ -d ".git" ]; then
                    INSTALL_DIR="$(pwd)"
                    log_info "Using current directory: $INSTALL_DIR"
                else
                    log_error "Cannot proceed without repository"
                    log_info "You can manually clone the repository first:"
                    log_info "  git clone --branch 0.02 --depth 1 https://github.com/ideotion/Open-Omniscience.git ~/open-omniscience"
                    exit 1
                fi
            fi
        else
            log_info "Repository already exists at $INSTALL_DIR"
        fi
        
        cd "$INSTALL_DIR"
        python3 installer/gui_installer.py
        
    else
        log_info "No GUI environment detected"
        log_info "Falling back to text-based installer..."
        echo ""
        exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash
    fi
}

# Run main
main "$@"
