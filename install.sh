#!/bin/bash
# Installation Options
# ============================================================================

# Default to minimal installation
INSTALL_TYPE="minimal"
INSTALL_TORCH="false"
INSTALL_OLLAMA="false"

# Feature descriptions
show_installation_options() {
    clear
    echo -e "$LOGO"
    echo ""
    log_header "=========================================="
    log_header "  Open-Omniscience Installation Options"
    log_header "=========================================="
    echo ""
    
    echo "Please select your installation type:"
    echo ""
    
    log_header "📦 Option 1: Minimal Installation (RECOMMENDED)"
    echo "   Download Size: ~50-100 MB"
    echo "   Disk Space: ~300-500 MB"
    echo "   Memory: 2GB+"
    echo ""
    echo "   ✅ Core web scraping and data management"
    echo "   ✅ API server and web interface"
    echo "   ✅ Basic analysis features"
    echo "   ✅ SQLite database support"
    echo "   ❌ NO Local LLM support (torch, transformers)"
    echo "   ❌ NO Deepfake detection"
    echo "   ❌ NO Advanced AI features"
    echo ""
    
    log_header "🤖 Option 2: Full Installation (Advanced)"
    echo "   Download Size: ~2-5 GB"
    echo "   Disk Space: ~10-20 GB"
    echo "   Memory: 8GB+ (16GB recommended)"
    echo ""
    echo "   ✅ All minimal features"
    echo "   ✅ Local LLM support"
    echo "   ✅ Deepfake detection"
    echo "   ✅ Advanced AI analysis"
    echo "   ✅ All machine learning models"
    echo ""
    
    log_header "⚙️  Option 3: Custom Installation"
    echo "   Choose which large packages to install"
    echo ""
    
    echo "Enter your choice [1-3] (Default: 1): "
    read -r choice
    
    case "$choice" in
        2|2)
            INSTALL_TYPE="full"
            INSTALL_TORCH="true"
            INSTALL_OLLAMA="true"
            ;;
        3|3)
            INSTALL_TYPE="custom"
            custom_installation_menu
            ;;
        *)
            INSTALL_TYPE="minimal"
            INSTALL_TORCH="false"
            INSTALL_OLLAMA="false"
            ;;
    esac
}

custom_installation_menu() {
    clear
    echo -e "$LOGO"
    echo ""
    log_header "=========================================="
    log_header "  Custom Installation Options"
    log_header "=========================================="
    echo ""
    
    echo "Select which large packages to install:"
    echo ""
    
    # Torch option
    echo "1. PyTorch (torch) - Required for deep learning"
    echo "   Size: ~500-800 MB"
    echo "   Enables: Deepfake detection, advanced AI features"
    echo "   Install? [y/N]: "
    read -r answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        INSTALL_TORCH="true"
    fi
    echo ""
    
    # Ollama option
    echo "2. Ollama - Local LLM runtime"
    echo "   Size: ~50-100 MB (plus model downloads)"
    echo "   Enables: Local LLM text processing"
    echo "   Install? [y/N]: "
    read -r answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        INSTALL_OLLAMA="true"
    fi
    echo ""
    
    if [[ "$INSTALL_TORCH" == "true" || "$INSTALL_OLLAMA" == "true" ]]; then
        INSTALL_TYPE="custom"
    else
        INSTALL_TYPE="minimal"
    fi
}
=======
# ============================================================================
# Installation Options
# ============================================================================

# Default to minimal installation
INSTALL_TYPE="minimal"
INSTALL_TORCH="false"
INSTALL_OLLAMA="false"

# Check if we're in an interactive terminal
is_interactive() {
    if [ -t 0 ]; then
        return 0  # Interactive
    else
        return 1  # Non-interactive
    fi
}

# Feature descriptions
show_installation_options() {
    # Check for environment variables first (non-interactive mode)
    if [[ "${INSTALL_OPTION:-}" == "2" || "${FULL_INSTALL:-false}" == "true" ]]; then
        INSTALL_TYPE="full"
        INSTALL_TORCH="true"
        INSTALL_OLLAMA="true"
        return
    elif [[ "${INSTALL_OPTION:-}" == "3" ]]; then
        INSTALL_TYPE="custom"
        INSTALL_TORCH="${INSTALL_TORCH:-false}"
        INSTALL_OLLAMA="${INSTALL_OLLAMA:-false}"
        return
    fi
    
    # Interactive mode
    if is_interactive; then
        clear
        echo -e "$LOGO"
        echo ""
        log_header "=========================================="
        log_header "  Open-Omniscience Installation Options"
        log_header "=========================================="
        echo ""
        
        echo "Please select your installation type:"
        echo ""
        
        log_header "📦 Option 1: Minimal Installation (RECOMMENDED)"
        echo "   Download Size: ~50-100 MB"
        echo "   Disk Space: ~300-500 MB"
        echo "   Memory: 2GB+"
        echo ""
        echo "   ✅ Core web scraping and data management"
        echo "   ✅ API server and web interface"
        echo "   ✅ Basic analysis features"
        echo "   ✅ SQLite database support"
        echo "   ❌ NO Local LLM support (torch, transformers)"
        echo "   ❌ NO Deepfake detection"
        echo "   ❌ NO Advanced AI features"
        echo ""
        
        log_header "🤖 Option 2: Full Installation (Advanced)"
        echo "   Download Size: ~2-5 GB"
        echo "   Disk Space: ~10-20 GB"
        echo "   Memory: 8GB+ (16GB recommended)"
        echo ""
        echo "   ✅ All minimal features"
        echo "   ✅ Local LLM support"
        echo "   ✅ Deepfake detection"
        echo "   ✅ Advanced AI analysis"
        echo "   ✅ All machine learning models"
        echo ""
        
        log_header "⚙️  Option 3: Custom Installation"
        echo "   Choose which large packages to install"
        echo ""
        
        echo -n "Enter your choice [1-3] (Default: 1): "
        read -r choice
        
        case "$choice" in
            2|2)
                INSTALL_TYPE="full"
                INSTALL_TORCH="true"
                INSTALL_OLLAMA="true"
                ;;
            3|3)
                INSTALL_TYPE="custom"
                custom_installation_menu
                ;;
            *)
                INSTALL_TYPE="minimal"
                INSTALL_TORCH="false"
                INSTALL_OLLAMA="false"
                ;;
        esac
    else
        # Non-interactive mode - use defaults or environment variables
        log_info "Running in non-interactive mode. Using minimal installation."
        log_info "To select a different installation type, use:"
        log_info "  Option 2 (Full):   INSTALL_OPTION=2 curl ... | bash"
        log_info "  Option 3 (Custom): INSTALL_OPTION=3 INSTALL_TORCH=true INSTALL_OLLAMA=true curl ... | bash"
        echo ""
        
        # Check for FULL_INSTALL environment variable for backward compatibility
        if [[ "${FULL_INSTALL:-false}" == "true" ]]; then
            INSTALL_TYPE="full"
            INSTALL_TORCH="true"
            INSTALL_OLLAMA="true"
        fi
    fi
}

custom_installation_menu() {
    # Check for environment variables first
    if [[ "${INSTALL_TORCH:-}" == "true" || "${INSTALL_OLLAMA:-}" == "true" ]]; then
        INSTALL_TYPE="custom"
        return
    fi
    
    if is_interactive; then
        clear
        echo -e "$LOGO"
        echo ""
        log_header "=========================================="
        log_header "  Custom Installation Options"
        log_header "=========================================="
        echo ""
        
        echo "Select which large packages to install:"
        echo ""
        
        # Torch option
        echo "1. PyTorch (torch) - Required for deep learning"
        echo "   Size: ~500-800 MB"
        echo "   Enables: Deepfake detection, advanced AI features"
        echo -n "   Install? [y/N]: "
        read -r answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            INSTALL_TORCH="true"
        fi
        echo ""
        
        # Ollama option
        echo "2. Ollama - Local LLM runtime"
        echo "   Size: ~50-100 MB (plus model downloads)"
        echo "   Enables: Local LLM text processing"
        echo -n "   Install? [y/N]: "
        read -r answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            INSTALL_OLLAMA="true"
        fi
        echo ""
        
        if [[ "$INSTALL_TORCH" == "true" || "$INSTALL_OLLAMA" == "true" ]]; then
            INSTALL_TYPE="custom"
        else
            INSTALL_TYPE="minimal"
        fi
    else
        # Non-interactive custom mode
        INSTALL_TYPE="custom"
        INSTALL_TORCH="${INSTALL_TORCH:-false}"
        INSTALL_OLLAMA="${INSTALL_OLLAMA:-false}"
    fi
}Open-Omniscience - Debian 13 Installer
# =========================================
# This script provides a simple, clean installation of Open-Omniscience
# for Debian 13 (Trixie) ONLY.
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

# Open-Omniscience Eye Logo
LOGO="
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
"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
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

log_header() {
    echo -e "${CYAN}$1${NC}"
}

# ============================================================================
# Installation Options
# ============================================================================

# Default to minimal installation
INSTALL_TYPE="minimal"
INSTALL_TORCH="false"
INSTALL_OLLAMA="false"

# Feature descriptions
show_installation_options() {
    clear
    echo -e "$LOGO"
    echo ""
    log_header "=========================================="
    log_header "  Open-Omniscience Installation Options"
    log_header "=========================================="
    echo ""
    
    echo "Please select your installation type:"
    echo ""
    
    log_header "📦 Option 1: Minimal Installation (RECOMMENDED)"
    echo "   Download Size: ~50-100 MB"
    echo "   Disk Space: ~300-500 MB"
    echo "   Memory: 2GB+"
    echo ""
    echo "   ✅ Core web scraping and data management"
    echo "   ✅ API server and web interface"
    echo "   ✅ Basic analysis features"
    echo "   ✅ SQLite database support"
    echo "   ❌ NO Local LLM support (torch, transformers)"
    echo "   ❌ NO Deepfake detection"
    echo "   ❌ NO Advanced AI features"
    echo ""
    
    log_header "🤖 Option 2: Full Installation (Advanced)"
    echo "   Download Size: ~2-5 GB"
    echo "   Disk Space: ~10-20 GB"
    echo "   Memory: 8GB+ (16GB recommended)"
    echo ""
    echo "   ✅ All minimal features"
    echo "   ✅ Local LLM support"
    echo "   ✅ Deepfake detection"
    echo "   ✅ Advanced AI analysis"
    echo "   ✅ All machine learning models"
    echo ""
    
    log_header "⚙️  Option 3: Custom Installation"
    echo "   Choose which large packages to install"
    echo ""
    
    echo "Enter your choice [1-3] (Default: 1): "
    read -r choice
    
    case "$choice" in
        2|2)
            INSTALL_TYPE="full"
            INSTALL_TORCH="true"
            INSTALL_OLLAMA="true"
            ;;
        3|3)
            INSTALL_TYPE="custom"
            custom_installation_menu
            ;;
        *)
            INSTALL_TYPE="minimal"
            INSTALL_TORCH="false"
            INSTALL_OLLAMA="false"
            ;;
    esac
}

custom_installation_menu() {
    clear
    echo -e "$LOGO"
    echo ""
    log_header "=========================================="
    log_header "  Custom Installation Options"
    log_header "=========================================="
    echo ""
    
    echo "Select which large packages to install:"
    echo ""
    
    # Torch option
    echo "1. PyTorch (torch) - Required for deep learning"
    echo "   Size: ~500-800 MB"
    echo "   Enables: Deepfake detection, advanced AI features"
    echo "   Install? [y/N]: "
    read -r answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        INSTALL_TORCH="true"
    fi
    echo ""
    
    # Ollama option
    echo "2. Ollama - Local LLM runtime"
    echo "   Size: ~50-100 MB (plus model downloads)"
    echo "   Enables: Local LLM text processing"
    echo "   Install? [y/N]: "
    read -r answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        INSTALL_OLLAMA="true"
    fi
    echo ""
    
    if [[ "$INSTALL_TORCH" == "true" || "$INSTALL_OLLAMA" == "true" ]]; then
        INSTALL_TYPE="custom"
    else
        INSTALL_TYPE="minimal"
    fi
}

# ============================================================================
# Cleanup Functions
# ============================================================================

# Remove previous installation
cleanup_previous() {
    log_info "Checking for previous installations..."
    
    # Remove old installation directory
    if [ -d "$INSTALL_DIR" ]; then
        log_info "Found previous installation at $INSTALL_DIR"
        log_info "Removing old installation..."
        rm -rf "$INSTALL_DIR"
        log_success "Previous installation removed"
    fi
    
    # Remove old desktop launcher
    if [ -f "$HOME/.local/share/applications/open-omniscience.desktop" ]; then
        log_info "Removing old desktop launcher..."
        rm -f "$HOME/.local/share/applications/open-omniscience.desktop"
    fi
    
    # Remove old symlinks
    if [ -f "/usr/local/bin/open-omniscience" ]; then
        log_info "Removing old symlink..."
        run_with_sudo rm -f "/usr/local/bin/open-omniscience"
    fi
}

# ============================================================================
# Environment Detection
# ============================================================================

# Check if running on Debian 13
check_debian() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "debian" ]]; then
            log_error "This installer is for Debian 13 only."
        fi
        if [[ "$VERSION_ID" != "13" && "$VERSION_ID" != *"13"* ]]; then
            log_warning "This installer is designed for Debian 13 (Trixie). You are running $VERSION_ID."
            read -p "Continue anyway? [y/N]: " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_error "Installation aborted. Please use Debian 13."
            fi
        fi
        log_info "Detected Debian $VERSION_ID"
    else
        log_error "Cannot determine OS. This installer is for Debian 13 only."
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
    
    # Install Ollama if requested
    if [[ "$INSTALL_OLLAMA" == "true" ]]; then
        log_info "Installing Ollama..."
        if ! command -v ollama &>/dev/null; then
            if ! curl -fsSL https://ollama.com/install.sh | sh 2>/dev/null; then
                log_warning "Failed to install Ollama. LLM features will not be available."
                INSTALL_OLLAMA="false"
            else
                log_success "Ollama installed"
            fi
        else
            log_info "Ollama already installed"
        fi
    fi
    
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
    else
        log_info "Virtual environment already exists, updating..."
        # Update existing virtual environment
        source venv/bin/activate
        pip install --upgrade pip
        deactivate
    fi
    
    # Activate and install dependencies
    log_info "Activating virtual environment..."
    source "$INSTALL_DIR/venv/bin/activate"
    
    log_info "Upgrading pip..."
    pip install --upgrade pip
    
    log_info "Installing Python dependencies..."
    
    # Always install minimal requirements
    if [ -f "requirements-minimal.txt" ]; then
        if ! pip install -r requirements-minimal.txt 2>/dev/null; then
            log_error "Failed to install minimal Python dependencies"
        fi
    else
        log_error "requirements-minimal.txt not found in repository"
    fi
    
    # Install additional packages based on selection
    if [[ "$INSTALL_TYPE" == "full" ]]; then
        log_info "Installing full dependencies (this may take a while)..."
        if [ -f "requirements.txt" ]; then
            if ! pip install -r requirements.txt 2>/dev/null; then
                log_warning "Failed to install some full dependencies. Core functionality should still work."
            fi
        fi
    elif [[ "$INSTALL_TYPE" == "custom" ]]; then
        # Install torch if requested
        if [[ "$INSTALL_TORCH" == "true" ]]; then
            log_info "Installing PyTorch..."
            if ! pip install torch>=2.2.0 2>/dev/null; then
                log_warning "Failed to install PyTorch. Deep learning features will not be available."
                INSTALL_TORCH="false"
            else
                log_success "PyTorch installed"
            fi
        fi
        
        # Install transformers and other ML packages if torch is installed
        if [[ "$INSTALL_TORCH" == "true" ]]; then
            log_info "Installing ML packages..."
            pip install transformers==4.40.0 onnx==1.16.0 onnxruntime>=1.20.0 2>/dev/null || \
                log_warning "Failed to install some ML packages"
        fi
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
Icon=$INSTALL_DIR/package/deb/open-omniscience.svg
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

# Show feature summary
show_feature_summary() {
    echo ""
    log_header "=========================================="
    log_header "  Installation Summary"
    log_header "=========================================="
    echo ""
    
    echo "Installation Type: $INSTALL_TYPE"
    echo ""
    
    log_success "✅ Core Features:"
    echo "   - Web scraping and data ingestion"
    echo "   - API server and web interface"
    echo "   - Basic analysis and search"
    echo "   - SQLite database support"
    echo ""
    
    if [[ "$INSTALL_TORCH" == "true" ]]; then
        log_success "✅ AI Features:"
        echo "   - Deepfake detection"
        echo "   - Advanced machine learning"
        echo "   - Image and audio analysis"
    else
        log_warning "❌ AI Features: Not installed (requires PyTorch)"
    fi
    echo ""
    
    if [[ "$INSTALL_OLLAMA" == "true" ]]; then
        log_success "✅ LLM Features:"
        echo "   - Local LLM text processing"
        echo "   - Text generation and analysis"
        echo "   - Translation capabilities"
        echo ""
        log_info "To use LLM features, you need to download models:"
        echo "   ollama pull gemma4:e2b"
    else
        log_warning "❌ LLM Features: Not installed (requires Ollama)"
    fi
    echo ""
}

# ============================================================================
# Main Installation
# ============================================================================

main() {
    echo ""
    echo -e "$LOGO"
    echo ""
    echo "  Open-Omniscience - Debian 13 Installer"
    echo "  =================================="
    echo ""
    
    # Show installation options
    show_installation_options
    
    # Cleanup previous installations
    cleanup_previous
    
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
    
    # Show feature summary
    show_feature_summary
    
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
    log_warning "If the virtual environment doesn't activate properly, you may need to restart your terminal or system."
    echo ""
}

# Run main
main "$@"
