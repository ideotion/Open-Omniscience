#!/bin/bash
#
# Open-Omniscience Unified Installation Script
# ==========================================
#
# This script provides a fully automatic installation of Open-Omniscience
# with all prerequisites, dependencies, and configurations for Debian-based Linux systems.
#
# Usage: curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install.sh | bash
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

# Version
VERSION="0.02"
REPO_URL="https://github.com/ideotion/Open-Omniscience.git"
REPO_BRANCH="0.02"
INSTALL_DIR="${HOME}/open-omniscience"

# =============================================================================
# Open-Omniscience Logo
# =============================================================================
display_logo() {
    cat << 'EOF'

                                 .-=+*#%@@@@@@@@@@%#*+-:                                         

                            .-+#@@@@@@%%@@@@@@@@@%%%@@@@@@#+:                                   

                         -+%@@@#*=:.-*#*#@*-@=+@#*#*-.:-+*%@@@#=:                               

                      -*@@%+-.    +%+. *#.  @: .*#..=%+     :=#@@%+:                            

                   .+@%*-       :%+##+%*    @:   *%=*#+%-       :=#@%=                          

                 :#%+.         -@:   ##+****@#***+#@   .%=          -*%+.                       

               :*+.           .@:   :@.     @:     @-   .@:            -**.                     

             .=-              *#    *#      @:     *#    *#              .==                    

            :-                #%****@%******@#*****%@****%%                 =                   

             .=:              *#    *#      @:     +#    +#               --                    

               -*=.           :@.   -@      @:     %=   .@-            :++.                     

                 -##-          +%.   %*=+**#@#**+=*%    #*          .=%*.                       

                   :*@#=.       =%=+#*%#.   @:  .*@*#*=%+        :+%%=.                         

                      =#@@*=.    .*%- .#*   @:  +%. :%#:     :=#@@*:                            

                        .=#@@@#+-: .+#*=*@=.@--%#=*#+. .:=*%@@%*-                               

                            :+#@@@@@%**%@@@@@@@@@%**#%@@@@%*=.                                  

                                .-+*%@@@@@@@@@@@@@@@%#+=:                                       

                                       .::-----::.                                              
EOF
}

# =============================================================================
# Utility Functions
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

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

is_root() {
    [ "$(id -u)" -eq 0 ]
}

run_with_sudo() {
    if is_root; then
        "$@"
    else
        sudo "$@"
    fi
}

is_debian() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "debian" || "$ID" == "ubuntu" || "$ID_LIKE" == *"debian"* ]]; then
            return 0
        fi
    fi
    return 1
}

check_architecture() {
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64|aarch64|arm64)
            log_info "Supported architecture: $ARCH"
            return 0
            ;;
        *)
            log_warning "Unsupported architecture: $ARCH. Installation may fail."
            return 1
            ;;
    esac
}

# =============================================================================
# Pre-Installation Checks
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check for curl
    if ! command_exists curl; then
        log_error "curl is required but not installed. Please install curl first."
        exit 1
    fi
    
    # Check for bash
    if ! command_exists bash; then
        log_error "bash is required but not installed."
        exit 1
    fi
    
    # Check architecture
    check_architecture
    
    # Check if Debian-based
    if ! is_debian; then
        log_error "This installer is designed for Debian-based Linux systems only (Ubuntu, Debian, etc.)."
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# =============================================================================
# System Setup
# =============================================================================

setup_system() {
    log_info "Setting up Debian-based Linux system"
    
    # Check distribution
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO="$ID"
        DISTRO_VERSION="$VERSION_ID"
        log_info "Distribution: $DISTRO $DISTRO_VERSION"
    fi
    
    # Install basic packages
    log_info "Installing basic packages..."
    run_with_sudo apt-get update -qq
    run_with_sudo apt-get install -y -qq git curl wget ca-certificates gnupg lsb-release software-properties-common
    
    log_success "Basic packages installed"
}

# =============================================================================
# Install Python Dependencies
# =============================================================================

install_python_deps() {
    log_info "Installing Python dependencies..."
    
    # Check for Python 3.8+
    if ! command_exists python3; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Detected Python: $PYTHON_VERSION"
    
    # Check Python version
    if ! python3 -c "import sys; assert sys.version_info >= (3, 8)" 2>/dev/null; then
        log_error "Python 3.8 or higher is required"
        exit 1
    fi
    
    # Create virtual environment
    if [ ! -d "venv" ]; then
        log_info "Creating virtual environment..."
        # Check if python3-venv is available
        if ! python3 -m venv --help >/dev/null 2>&1; then
            # On Debian/Ubuntu, python3-venv package might be needed
            log_info "python3-venv not available, installing..."
            if command_exists apt-get; then
                PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
                PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
                # Try generic package first
                if run_with_sudo apt-get install -y python3-venv; then
                    log_success "Installed python3-venv"
                # Try version-specific package
                elif run_with_sudo apt-get install -y "python3.${PYTHON_MAJOR}${PYTHON_MINOR}-venv"; then
                    log_success "Installed python3.${PYTHON_MAJOR}${PYTHON_MINOR}-venv"
                else
                    log_error "Failed to install python3-venv automatically."
                    log_error "Please run manually: sudo apt install python3-venv"
                    exit 1
                fi
            else
                log_error "python3-venv is required but not installed."
                log_error "Please install it manually for your package manager."
                exit 1
            fi
        fi
        python3 -m venv venv
    fi
    
    # Activate and install dependencies
    cd "$INSTALL_DIR"
    source venv/bin/activate
    
    # Install core dependencies
    log_info "Installing core dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r requirements-core.txt
    
    # Install LLM dependencies
    if [ -f "requirements-llm.txt" ]; then
        log_info "Installing LLM dependencies..."
        pip install -r requirements-llm.txt
    fi
    
    log_success "All Python dependencies installed"
}

# =============================================================================
# Install Ollama (for LLM support)
# =============================================================================

install_ollama() {
    if command_exists ollama && ollama --version >/dev/null 2>&1; then
        log_info "Ollama is already installed: $(ollama --version)"
        return 0
    fi
    
    log_info "Installing Ollama for local LLM support..."
    
    curl -fsSL https://ollama.com/install.sh | sh
    
    # Verify installation
    if ! command_exists ollama || ! ollama --version >/dev/null 2>&1; then
        log_warning "Ollama installation may have failed or is not in PATH"
        return 1
    fi
    
    log_success "Ollama installed: $(ollama --version)"
    return 0
}

# =============================================================================
# Clone Repository
# =============================================================================

clone_repository() {
    if [ -d "$INSTALL_DIR" ]; then
        log_info "Repository already exists at $INSTALL_DIR"
        cd "$INSTALL_DIR"
        git fetch origin
        git checkout "$REPO_BRANCH"
        git pull origin "$REPO_BRANCH"
        return 0
    fi
    
    log_info "Cloning Open-Omniscience repository..."
    git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    
    if [ ! -d "$INSTALL_DIR" ]; then
        log_error "Failed to clone repository"
        exit 1
    fi
    
    cd "$INSTALL_DIR"
    log_success "Repository cloned to $INSTALL_DIR"
}

# =============================================================================
# Configure Environment
# =============================================================================

configure_environment() {
    log_info "Configuring environment..."
    
    # Copy example environment file
    if [ -f ".env.example" ] && [ ! -f ".env" ]; then
        cp .env.example .env
        log_info "Created .env from .env.example"
    fi
    
    # Create data directories
    for dir in data audit logs; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            log_info "Created directory: $dir"
        fi
    done
    
    # Set default configuration
    if [ ! -f "configs/settings.yaml" ]; then
        mkdir -p configs
        cat > configs/settings.yaml << 'EOF'
# Open-Omniscience Settings
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
EOF
        log_info "Created default settings.yaml"
    fi
    
    log_success "Environment configured"
}

# =============================================================================
# Create Desktop Launcher
# =============================================================================

create_desktop_launcher() {
    log_info "Creating desktop launcher..."
    
    # Create desktop file
    DESKTOP_FILE="$HOME/.local/share/applications/open-omniscience.desktop"
    
    # Create directory if it doesn't exist
    mkdir -p "$HOME/.local/share/applications"
    
    # Create the desktop file
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Open-Omniscience
GenericName=Investigative Journalism Platform
Comment=Ethical Global Intelligence Platform for Investigative Journalism
Exec=bash -c "cd $INSTALL_DIR && source venv/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload & xdg-open http://localhost:8000"
Icon=$INSTALL_DIR/docs/open-omniscience-icon.png
Terminal=true
Categories=Development;Journalism;Research;Utility;
StartupWMClass=Open-Omniscience
EOF
    
    # Make it executable
    chmod +x "$DESKTOP_FILE"
    
    # Update database
    if command_exists update-desktop-database; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    
    log_success "Desktop launcher created at $DESKTOP_FILE"
    log_info "You can now find 'Open-Omniscience' in your application menu"
}

# =============================================================================
# Start Services
# =============================================================================

start_services() {
    log_info "Starting Open-Omniscience services..."
    
    cd "$INSTALL_DIR"
    
    # Activate virtual environment
    source venv/bin/activate
    
    # Start the application
    if uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/open-omniscience.log 2>&1 & then
        log_success "Services started successfully!"
        
        # Wait for services to be ready
        log_info "Waiting for application to be ready..."
        for i in {1..30}; do
            if curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
                log_success "Application is ready at http://localhost:8000"
                return 0
            fi
            echo -n "."
            sleep 2
        done
        
        log_warning "Application may take longer to start. Check with: tail -f /tmp/open-omniscience.log"
        return 0
    else
        log_error "Failed to start services"
        log_info "Check logs with: tail -f /tmp/open-omniscience.log"
        return 1
    fi
}

# =============================================================================
# Verification
# =============================================================================

verify_installation() {
    log_info "Verifying installation..."
    
    local all_passed=true
    
    # Check Git
    if ! command_exists git || ! git --version >/dev/null 2>&1; then
        log_error "Git verification failed"
        all_passed=false
    else
        log_success "Git: $(git --version)"
    fi
    
    # Check Python
    if ! command_exists python3 || ! python3 -c "import sys; assert sys.version_info >= (3, 8)" 2>/dev/null; then
        log_error "Python verification failed"
        all_passed=false
    else
        log_success "Python: $(python3 --version)"
    fi
    
    # Check repository
    if [ ! -d ".git" ]; then
        log_error "Repository verification failed"
        all_passed=false
    else
        log_success "Repository: $(git rev-parse --abbrev-ref HEAD)"
    fi
    
    # Check Python dependencies
    if ! python3 -c "import fastapi; import sqlalchemy; import beautifulsoup4" 2>/dev/null; then
        log_error "Python dependencies verification failed"
        all_passed=false
    else
        log_success "Python dependencies: OK"
    fi
    
    # Check Ollama (optional)
    if command_exists ollama && ollama --version >/dev/null 2>&1; then
        log_success "Ollama: $(ollama --version)"
    else
        log_warning "Ollama: Not installed (LLM features will be limited)"
    fi
    
    if [ "$all_passed" = true ]; then
        log_success "All verification checks passed!"
        return 0
    else
        log_error "Some verification checks failed"
        return 1
    fi
}

# =============================================================================
# Main Installation
# =============================================================================

main() {
    echo ""
    display_logo
    echo "  Open-Omniscience v$VERSION Installer"
    echo "  ===================================="
    echo ""
    
    # Check prerequisites
    check_prerequisites
    
    # Setup for Debian-based Linux
    setup_system
    
    # Ask user if they want to install Ollama
    read -p "Do you want to install Ollama for LLM support? (Y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        install_ollama || log_warning "Ollama installation skipped or failed"
    else
        log_info "Skipping Ollama installation. You can install it later from https://ollama.com"
    fi
    
    # Clone repository
    clone_repository
    
    # Ensure we're in the install directory
    cd "$INSTALL_DIR"
    
    # Install Python dependencies
    install_python_deps
    
    # Configure environment
    configure_environment
    
    # Create desktop launcher
    create_desktop_launcher
    
    # Verify installation
    echo ""
    log_info "Running verification..."
    verify_installation
    
    # Final message
    echo ""
    display_logo
    echo "  Installation Complete!"
    echo ""
    echo "  Open-Omniscience has been installed to: $INSTALL_DIR"
    echo ""
    
    # Ask if user wants to launch the program
    read -p "Do you want to launch Open-Omniscience now? (Y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo ""
        log_info "Launching Open-Omniscience..."
        start_services
        
        # Check if it started successfully
        if pgrep -f "uvicorn.*api.main" > /dev/null 2>&1; then
            log_success "Open-Omniscience is running!"
            echo ""
            echo "  Access the application at: http://localhost:8000"
            echo ""
            
            # Ask if user wants to open in browser
            if command_exists xdg-open; then
                read -p "Do you want to open it in your browser? (Y/n): " -n 1 -r
                echo ""
                if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
                    xdg-open http://localhost:8000
                fi
            fi
        else
            log_warning "Open-Omniscience may not have started. Check with: tail -f /tmp/open-omniscience.log"
        fi
    else
        echo ""
        log_info "To start Open-Omniscience manually:"
        echo "    cd $INSTALL_DIR"
        echo "    source venv/bin/activate"
        echo "    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload"
        echo ""
        echo "  Then access at: http://localhost:8000"
    fi
    
    echo ""
    echo "  For LLM support (if Ollama installed):"
    echo "    ollama serve &"
    echo "    ollama pull gemma4:e2b"
    echo ""
    echo "  Documentation: https://github.com/ideotion/Open-Omniscience"
    echo ""
    echo "  GUI Installer: Run installer/gui_installer.py for a graphical installation"
    echo ""
}

# Run main function
main "$@"
