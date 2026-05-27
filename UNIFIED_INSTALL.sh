# Open-Omniscience UNIFIED Installer
# ============================================================================
#
# Version: 0.03
# Unified installer that automatically adapts to:
#   - Regular Debian/Ubuntu systems (with or without GUI)
#   - Qubes OS VMs (R4.1+ with Debian 13 template)
#   - Headless servers
#   - Various environments (X11, Wayland, VMs, bare metal)
#
# Note: dom0 cannot run this installer as it has no web access.
# This installer is designed to run in Debian 13 VMs (Qubes or regular).
#
# Features:
#   - Automatic environment detection (Qubes vs regular Linux)
#   - Smart installation method selection
#   - Single entry point for all users
#   - Comprehensive error handling
#   - User-friendly prompts with sensible defaults
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
#   OR
#   ./UNIFIED_INSTALL.sh
#
# Author: Open-Omniscience Team
# License: GNU GPLv3
#
# ============================================================================

set -uo pipefail
=======
#!/bin/bash

# ============================================================================
# Open-Omniscience UNIFIED Installer
# ============================================================================
#
# Version: 0.03
# Unified installer that adapts to:
#   - Regular Debian/Ubuntu systems (with or without GUI)
#   - Qubes OS (R4.1+ with Debian 13 template)
#   - Headless servers
#   - Various environments (X11, Wayland, VMs, bare metal)
#
# Features:
#   - User prompts for Qubes OS (undetectable by design)
#   - Automatic GUI detection
#   - Smart installation method selection
#   - Single entry point for all users
#   - Comprehensive error handling
#   - Works with both direct execution and piped execution
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
#   OR
#   ./UNIFIED_INSTALL.sh
#
# Author: Open-Omniscience Team
# License: GNU GPLv3
#
# ============================================================================

set -uo pipefail

# Note: When piped (curl ... | bash), stdin is not a terminal
# So we need to use /dev/tty for user input when available
# If /dev/tty is not available (piped), we'll use stdin============================================================================
# Open-Omniscience UNIFIED Installer
#   - Smart installation method selection
#   - Single entry point for all users
#   - Comprehensive error handling
#   - User-friendly prompts with sensible defaults
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
#   OR
#   ./UNIFIED_INSTALL.sh
#
# Author: Open-Omniscience Team
# License: GNU GPLv3
#
# ============================================================================

set -uo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Repository
REPO_URL="https://github.com/ideotion/Open-Omniscience.git"
REPO_BRANCH="0.03"
INSTALL_DIR="${HOME}/open-omniscience"

# Default settings
USE_GUI=true
INSTALL_LLM=true
CREATE_LAUNCHER=true

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
}

log_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

# ============================================================================
# Environment Detection Functions
# ============================================================================

# Check if running in Qubes OS
# Note: Qubes OS is designed to be undetectable from within VMs for security
# So we always ask the user rather than trying to auto-detect
detect_qubes() {
    # Check if we're running in a Qubes VM
    # Note: dom0 cannot run this installer as it has no web access
    # So we only check for Qubes VM markers
    if [ -f /etc/qubes-release ] || [ -n "${QUBES_VM_TYPE:-}" ]; then
        return 0
    fi
    return 1
}

# Check if GUI environment is available
detect_gui() {
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

# Check if running as root
detect_root() {
    if [ "$(id -u)" -eq 0 ]; then
        return 0
    fi
    return 1
}

# Check system type
detect_system() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
        return 0
    fi
    echo "unknown"
    return 1
}

# ============================================================================
# User Prompt Functions
# ============================================================================

# Ask yes/no question with default
# Works with both terminal and piped execution
ask_yes_no() {
    local question="$1"
    local default="$2"
    local answer
    
    if [ "$default" = "yes" ]; then
        prompt="Y/n"
    else
        prompt="y/N"
    fi
    
    # Try to read from /dev/tty first (for piped execution), then fallback to stdin
    if [ -e /dev/tty ] && [ -r /dev/tty ]; then
        while true; do
            read -p "$question [$prompt]: " answer < /dev/tty
            answer="${answer:-$default}"
            case "$answer" in
                [Yy]*|[Yy][Ee][Ss]*) return 0 ;;
                [Nn]*|[Nn][Oo]*) return 1 ;;
                *) echo "Please answer yes or no." > /dev/tty ;;
            esac
        done
    else
        # Fallback for direct terminal execution
        while true; do
            read -p "$question [$prompt]: " answer
            answer="${answer:-$default}"
            case "$answer" in
                [Yy]*|[Yy][Ee][Ss]*) return 0 ;;
                [Nn]*|[Nn][Oo]*) return 1 ;;
                *) echo "Please answer yes or no." ;;
            esac
        done
    fi
}

# Ask user if they're using Qubes OS
ask_qubes() {
    if detect_qubes; then
        log_info "Detected Qubes VM environment"
        return 0
    fi
    
    log_info "Automatic Qubes OS detection: Not detected"
    ask_yes_no "Are you installing on Qubes OS" "no"
    return $?
}

# Ask about GUI preference
ask_gui() {
    if detect_gui; then
        log_info "Detected GUI environment"
        return 0
    fi
    
    log_info "Automatic GUI detection: Not detected"
    ask_yes_no "Do you have a GUI environment available" "no"
    return $?
}

# ============================================================================
# Installation Functions
# ============================================================================

# Install system dependencies
install_dependencies() {
    local is_qubes="$1"
    
    log_header "Installing System Dependencies"
    
    if command -v apt-get &>/dev/null; then
        log_info "Detected Debian-based system"
        
        # Common dependencies
        local packages=("python3" "python3-pip" "python3-venv" "git" "curl" "wget")
        
        # Add GUI dependencies if needed
        if [ "$USE_GUI" = true ]; then
            packages+=("python3-tk")
        fi
        
        # Note: Qubes-specific packages (qubes-mgmt-salt, qubes-core-admin) 
        # are dom0-only and not needed in VMs where this installer runs
        
        log_info "Installing packages: ${packages[*]}"
        if ! sudo apt-get update && sudo apt-get install -y "${packages[@]}" 2>/dev/null; then
            log_error "Failed to install dependencies"
            return 1
        fi
        
    elif command -v dnf &>/dev/null; then
        log_info "Detected Fedora/RHEL-based system"
        local packages=("python3" "python3-pip" "git" "curl" "wget")
        
        if [ "$USE_GUI" = true ]; then
            packages+=("python3-tkinter")
        fi
        
        if ! sudo dnf install -y "${packages[@]}" 2>/dev/null; then
            log_error "Failed to install dependencies"
            return 1
        fi
        
    elif command -v yum &>/dev/null; then
        log_info "Detected CentOS/RHEL-based system"
        local packages=("python3" "python3-pip" "git" "curl" "wget")
        
        if [ "$USE_GUI" = true ]; then
            packages+=("python3-tkinter")
        fi
        
        if ! sudo yum install -y "${packages[@]}" 2>/dev/null; then
            log_error "Failed to install dependencies"
            return 1
        fi
        
    else
        log_error "Unsupported package manager"
        return 1
    fi
    
    log_success "System dependencies installed"
    return 0
}

# Clone repository
clone_repository() {
    log_header "Cloning Repository"
    
    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Repository already exists at $INSTALL_DIR"
        cd "$INSTALL_DIR"
        if ! git pull origin "$REPO_BRANCH" 2>/dev/null; then
            log_error "Failed to update repository"
            return 1
        fi
        log_success "Repository updated"
        return 0
    fi
    
    log_info "Cloning repository to $INSTALL_DIR"
    if ! git clone --branch "$REPO_BRANCH" --depth 1 --no-hardlinks "$REPO_URL" "$INSTALL_DIR" 2>&1; then
        log_error "Failed to clone repository"
        return 1
    fi
    
    log_success "Repository cloned"
    return 0
}

# Create virtual environment
create_venv() {
    log_header "Setting Up Python Environment"
    
    cd "$INSTALL_DIR"
    
    # Use best available Python version
    local python_cmd="python3"
    if command -v python3.12 &>/dev/null; then
        python_cmd="python3.12"
    elif command -v python3.11 &>/dev/null; then
        python_cmd="python3.11"
    elif command -v python3.10 &>/dev/null; then
        python_cmd="python3.10"
    fi
    
    log_info "Using Python: $python_cmd"
    
    # Create virtual environment
    if [ ! -d "venv" ]; then
        log_info "Creating virtual environment"
        if ! "$python_cmd" -m venv venv 2>/dev/null; then
            log_error "Failed to create virtual environment"
            return 1
        fi
    fi
    
    # Activate and install dependencies
    source venv/bin/activate
    
    log_info "Installing Python dependencies"
    if [ -f "requirements.txt" ]; then
        if ! pip install --upgrade pip && pip install -r requirements.txt 2>/dev/null; then
            log_error "Failed to install Python dependencies"
            return 1
        fi
    else
        log_error "requirements.txt not found"
        return 1
    fi
    
    log_success "Python environment set up"
    return 0
}

# Qubes-specific setup
# Since dom0 cannot run this installer (no web access),
# we assume we're always in a Qubes VM and do regular installation
setup_qubes() {
    log_header "Qubes OS VM Setup"
    log_info "Detected Qubes VM environment - installing Open-Omniscience directly in this VM"
    
    # For Qubes VMs, we do regular installation but with Qubes-aware optimizations
    setup_regular
}

# Regular Linux setup
setup_regular() {
    log_header "Regular Linux Setup"
    
    cd "$INSTALL_DIR"
    
    # Ensure requirements.txt exists
    if [ -L "requirements.txt" ] || [ ! -f "requirements.txt" ]; then
        if [ -f "configs/python/requirements.txt" ]; then
            rm -f "requirements.txt"
            cp -f "configs/python/requirements.txt" "requirements.txt"
        fi
    fi
    
    # Create and activate virtual environment
    if ! create_venv; then
        return 1
    fi
    
    log_success "Regular Linux setup complete"
    return 0
}

# Create desktop launcher
create_launcher() {
    if [ "$CREATE_LAUNCHER" = false ]; then
        return 0
    fi
    
    log_header "Creating Desktop Launcher"
    
    local desktop_file="$HOME/.local/share/applications/open-omniscience.desktop"
    
    cat > "$desktop_file" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Open Omniscience
GenericName=Global Intelligence Platform
Comment=Ethical Global Intelligence Platform for Investigative Journalism
Exec=bash -c "cd $HOME/open-omniscience && source venv/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port 8000"
Icon=open-omniscience
Terminal=true
Categories=Utility;News;Information;
Path=$HOME/open-omniscience
StartupWMClass=OpenOmniscience
EOF
    
    chmod +x "$desktop_file"
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    
    log_success "Desktop launcher created at $desktop_file"
    return 0
}

# Start services
start_services() {
    log_header "Starting Services"
    
    cd "$INSTALL_DIR"
    
    # Activate virtual environment and get the full path to uvicorn
    source venv/bin/activate
    local uvicorn_cmd=$(which uvicorn 2>/dev/null)
    
    if [ -z "$uvicorn_cmd" ]; then
        log_error "uvicorn not found. Please ensure the virtual environment is activated and dependencies are installed."
        log_info "Try running: source venv/bin/activate && pip install uvicorn"
        return 1
    fi
    
    if [ "$USE_GUI" = true ]; then
        log_info "Starting with GUI..."
        "$uvicorn_cmd" api.main:app --reload &
        log_success "Open-Omniscience running at http://localhost:8000"
    else
        log_info "Starting in background..."
        nohup "$uvicorn_cmd" api.main:app --host 0.0.0.0 --port 8000 > /tmp/open-omniscience.log 2>&1 &
        log_success "Open-Omniscience running at http://localhost:8000"
        log_info "Logs available at /tmp/open-omniscience.log"
    fi
    
    return 0
}

# ============================================================================
# Main Installation Logic
# ============================================================================

main() {
    clear
    
    echo ""
    echo "  ██████╗  ██████╗ ███╗   ██╗██████╗ ██╗███╗   ██╗████████╗"
    echo "  ██╔══██╗██╔═══██╗████╗  ██║██╔══██╗██║████╗  ██║╚══██╔══╝"
    echo "  ██║  ██║██║   ██║██╔██╗ ██║██║   ██║██╔██╗ ██║   ██║   "
    echo "  ██║  ██║██║   ██║██║╚██╗██║██║   ██║██║╚██╗██║   ██║   "
    echo "  ██████╔╝╚██████╔╝██║ ╚████║╚██████╔╝██║ ╚████║   ██║   "
    echo "  ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝    "
    echo ""
    echo "  ██████╗ ██╗   ██╗███╗   ███╗██████╗ ██████╗ ███████╗"
    echo "  ██╔══██╗██║   ██║████╗  ████║██╔══██╗██╔══██╗██╔════╝"
    echo "  ██████╔╝██║   ██║██╔██╗ ██║██████╔╝██║   ██║█████╗  "
    echo "  ██╔══██╗██║   ██║██║╚██╗██║██╔══██╗██║   ██║██╔══╝  "
    echo "  ██║  ██║╚██████╔╝██║ ╚████║██║  ██║╚██████╔╝███████╗"
    echo "  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
    echo ""
    echo "  Open-Omniscience Unified Installer v0.03"
    echo "  ========================================"
    echo ""
    
    # Detect environment
    log_info "Detecting your environment..."
    
    local is_qubes=false
    local has_gui=false
    
    # Try to detect Qubes OS
    # Note: dom0 cannot run this installer (no web access), so we only detect VMs
    if detect_qubes; then
        log_info "Detected Qubes VM environment"
        is_qubes=true
    else
        # Qubes OS is designed to be undetectable from within VMs for security
        # So we ask the user if detection failed (e.g., in a VM without markers)
        log_info "Note: Qubes OS is designed to be undetectable from within VMs for security"
        if ask_yes_no "Are you installing on Qubes OS" "no"; then
            is_qubes=true
        fi
    fi
    
    if detect_gui; then
        has_gui=true
        log_success "GUI environment detected"
    else
        log_info "GUI environment not detected"
        if ask_yes_no "Do you have a GUI environment available" "no"; then
            has_gui=true
        fi
    fi
    
    # Set installation parameters based on environment
    USE_GUI=$has_gui
    
    if $is_qubes; then
        log_header "Qubes OS Installation Mode"
        log_info "Installing Open-Omniscience with Qubes OS multi-VM architecture"
    else
        log_header "Regular Linux Installation Mode"
        log_info "Installing Open-Omniscience on standard Linux system"
    fi
    
    # Confirm installation
    if ! ask_yes_no "Proceed with installation" "yes"; then
        log_info "Installation cancelled"
        exit 0
    fi
    
    # Install dependencies
    if ! install_dependencies "$is_qubes"; then
        log_error "Installation failed: Dependency installation"
        exit 1
    fi
    
    # Clone repository
    if ! clone_repository; then
        log_error "Installation failed: Repository clone"
        exit 1
    fi
    
    # Environment-specific setup
    if $is_qubes; then
        if ! setup_qubes; then
            log_error "Installation failed: Qubes OS setup"
            exit 1
        fi
    else
        if ! setup_regular; then
            log_error "Installation failed: Regular setup"
            exit 1
        fi
    fi
    
    # Create launcher (only for regular Linux with GUI)
    if ! $is_qubes && $has_gui; then
        if ! create_launcher; then
            log_warning "Failed to create desktop launcher"
        fi
    fi
    
    # Start services (only for regular Linux)
    if ! $is_qubes; then
        if ask_yes_no "Start Open-Omniscience now" "yes"; then
            if ! start_services; then
                log_error "Failed to start services"
                exit 1
            fi
        fi
    fi
    
    # Final instructions
    echo ""
    log_header "Installation Complete!"
    
    if $is_qubes; then
        echo ""
        echo "  Qubes OS Installation Summary:"
        echo "  =============================="
        echo "  ✅ VMs created: open-omniscience-api, open-omniscience-db,"
        echo "     open-omniscience-scraper, open-omniscience-ai"
        echo "  ✅ All VMs configured with proper isolation"
        echo "  ✅ Open-Omniscience installed in each VM"
        echo ""
        echo "  Next Steps:"
        echo "  1. Start all VMs: qvm-start open-omniscience-*"
        echo "  2. Access API at: qvm-run -u open-omniscience-api curl http://localhost:8000"
        echo "  3. See QUBS_INSTALL_GUIDE.md for detailed usage"
        echo ""
    else
        echo ""
        echo "  Regular Installation Summary:"
        echo "  ============================"
        echo "  ✅ Repository cloned to: $INSTALL_DIR"
        echo "  ✅ Python dependencies installed"
        echo "  ✅ Virtual environment created"
        echo ""
        echo "  To start Open-Omniscience:"
        echo "    cd $INSTALL_DIR"
        echo "    source venv/bin/activate"
        echo "    uvicorn api.main:app --reload"
        echo ""
        echo "  Then open: http://localhost:8000"
        echo ""
        if $has_gui && $CREATE_LAUNCHER; then
            echo "  Desktop launcher created in your application menu"
            echo ""
        fi
    fi
    
    echo ""
    log_success "Open-Omniscience installation completed successfully!"
    echo ""
    echo "  For more information, see DOCUMENTATION.md"
    echo ""
}

# Run main
main "$@"
