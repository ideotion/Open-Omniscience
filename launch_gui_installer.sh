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
# - Automatic Python virtual environment creation and activation
# - Prefer Python 3.12 for compatibility, fall back to 3.13 if needed
# - Uses --no-hardlinks for Qubes OS compatibility
# - Fallback to text-based installer if GUI not available
# - Works in virtual environments, XEN, Qubes OS, etc.
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

# Check if we're running in a supported Linux system (Debian, Ubuntu, Alpine, Qubes OS, etc.)
is_supported() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        # Support Debian, Ubuntu, and Debian-like systems (including Qubes OS)
        if [[ "$ID" == "debian" || "$ID" == "ubuntu" || ("${ID_LIKE:-}" == *"debian"*) ]]; then
            return 0
        fi
        # Support Alpine Linux (used in some Qubes OS VMs)
        if [[ "$ID" == "alpine" ]]; then
            return 0
        fi
        # Support Qubes OS explicitly
        if [[ "$ID" == "qubes" || "${ID_LIKE:-}" == *"qubes"* ]]; then
            return 0
        fi
    fi
    # If we can't determine, assume supported (for maximum compatibility)
    return 0
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
# Python Version Detection
# =============================================================================

# Get the best available Python command for venv creation
# Prefer Python 3.12 for compatibility, fall back to 3.13 or default python3
get_python_cmd() {
    if command_exists python3.12; then
        echo "python3.12"
    elif command_exists python3.11; then
        echo "python3.11"
    else
        echo "python3"
    fi
}

# Get the pip command for the selected Python version
get_pip_cmd() {
    local py_cmd=$(get_python_cmd)
    echo "${py_cmd} -m pip"
}

# Get the venv module command for the selected Python version
get_venv_cmd() {
    local py_cmd=$(get_python_cmd)
    echo "${py_cmd} -m venv"
}

# =============================================================================
# Virtual Environment Functions
# =============================================================================

# Create Python virtual environment
create_venv() {
    local venv_path="$INSTALL_DIR/venv"
    local py_cmd=$(get_python_cmd)
    local venv_cmd=$(get_venv_cmd)
    local pip_cmd=$(get_pip_cmd)
    
    log_info "Using Python: $py_cmd"
    
    if [ ! -d "$venv_path" ]; then
        log_info "Creating Python virtual environment at $venv_path..."
        if $venv_cmd "$venv_path"; then
            log_success "Virtual environment created"
        else
            log_error "Failed to create virtual environment with $py_cmd"
            return 1
        fi
    else
        log_info "Virtual environment already exists at $venv_path"
    fi
    
    # Activate the virtual environment and install dependencies
    log_info "Activating virtual environment and installing dependencies..."
    source "$venv_path/bin/activate"
    
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        if $pip_cmd install --upgrade pip && $pip_cmd install -r "$INSTALL_DIR/requirements.txt"; then
            log_success "Dependencies installed"
        else
            log_error "Failed to install dependencies"
            return 1
        fi
    else
        log_error "requirements.txt not found in $INSTALL_DIR"
        return 1
    fi
    
    return 0
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
    
    # Check if running on a supported Linux system
    if ! is_supported; then
        log_warning "This installer is designed for Debian-based Linux systems (including Qubes OS)."
        log_warning "Your system may not be fully supported, but continuing anyway..."
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
        
        # Clone repository if not already present
        if [ ! -d "$INSTALL_DIR/.git" ]; then
            log_info "Cloning repository to $INSTALL_DIR..."
            if git clone --branch "$REPO_BRANCH" --depth 1 --no-hardlinks "$REPO_URL" "$INSTALL_DIR" 2>&1; then
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
                    log_info "  git clone --branch 0.02 --depth 1 --no-hardlinks https://github.com/ideotion/Open-Omniscience.git ~/open-omniscience"
                    exit 1
                fi
            fi
        else
            log_info "Repository already exists at $INSTALL_DIR"
        fi
        
        cd "$INSTALL_DIR"
        
        # Ensure requirements.txt exists as a real file (not symlink) in the install directory
        if [ -L "requirements.txt" ] || [ ! -f "requirements.txt" ]; then
            log_info "Ensuring requirements.txt exists as a real file..."
            if [ -f "configs/python/requirements.txt" ]; then
                rm -f "requirements.txt"
                cp -f "configs/python/requirements.txt" "requirements.txt"
                log_success "Copied requirements.txt to install directory"
            else
                log_error "configs/python/requirements.txt not found! Cannot proceed."
                exit 1
            fi
        fi
        
        # Create and activate the Python virtual environment
        if ! create_venv; then
            log_error "Failed to create or activate virtual environment"
            exit 1
        fi
        
        # Set an environment variable to tell the GUI installer that we've already cloned
        export OPEN_OMNISCIENCE_ALREADY_CLONED=1
        
        # Use the modern GUI installer
        python3 installer/gui_installer.py
        
    else
        log_info "No GUI environment detected"
        log_error "This installer requires a GUI environment (X11/Wayland/DISPLAY)."
        log_error "Please run this installer from a graphical terminal or desktop environment."
        log_error "Alternatively, use the text-based installation method:"
        log_error "  curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install | bash"
        exit 1
    fi
}

# Run main
main "$@"
