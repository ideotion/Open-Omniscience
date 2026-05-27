=======
set -euo pipefail

# Deprecation warning
echo "WARNING: This script (INSTALL-QUBES.sh) is deprecated."
echo "Please use qubes-installer.sh instead for full functionality."
echo "This script will continue to work but may not have all the latest features."
echo ""
=======
#!/bin/bash

# Open-Omniscience Qubes-OS Installer (LEGACY - DOUBLE DEPRECATED)
# Compatible with Debian Trixie (12) in Qubes OS R4.1+
# 
# ⚠️ DOUBLE DEPRECATED: This script is deprecated.
# Please use UNIFIED_INSTALL.sh instead for all new installations.
# 
# The unified installer automatically detects Qubes OS and provides the same
# multi-VM architecture with better error handling and user experience.
#
# Old recommendation: qubes-installer.sh (also deprecated)
# New recommendation: UNIFIED_INSTALL.sh
#
# This script automates the deployment of Open-Omniscience across multiple
# Qubes OS VMs for maximum security and isolation.

set -euo pipefail

# DEPRECATION WARNING
echo "⚠️  DEPRECATION NOTICE: This installer is deprecated."
echo "✅ Please use: curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash"
echo ""

# Configuration
# ========================================================================================================================================================
=======
set -euo pipefail

# Deprecation warning
echo "WARNING: This script (INSTALL-QUBES.sh) is deprecated."
echo "Please use qubes-installer.sh instead for full functionality."
echo "This script will continue to work but may not have all the latest features."
echo ""

# ============================================================================
# Configuration
# ========================================================================================================================================================
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
REPO_BRANCH="0.03_Qubes"

# Installation directories
INSTALL_DIR="/opt/open-omniscience"
LOG_DIR="/var/log/open-omniscience"
DATA_DIR="/var/lib/open-omniscience"
CONFIG_DIR="/etc/open-omniscience"

# VM Configuration
API_VM="open-omniscience-api"
DB_VM="open-omniscience-db"
SCRAPER_VM="open-omniscience-scraper"
AI_VM="open-omniscience-ai"

# VM Settings
API_VM_MEMORY=2048
API_VM_MAXMEM=4096
API_VM_VCPUS=2

DB_VM_MEMORY=1024
DB_VM_MAXMEM=2048
DB_VM_VCPUS=1

SCRAPER_VM_MEMORY=2048
SCRAPER_VM_MAXMEM=4096
SCRAPER_VM_VCPUS=2

AI_VM_MEMORY=4096
AI_VM_MAXMEM=8192
AI_VM_VCPUS=4

# Template (must exist in Qubes)
TEMPLATE_VM="debian-12"

# Labels
API_VM_LABEL="blue"
DB_VM_LABEL="green"
SCRAPER_VM_LABEL="yellow"
AI_VM_LABEL="red"

# Network settings
NETVM="sys-whonix"  # Use sys-firewall for non-Tor

# ============================================================================
# Utility Functions
# ============================================================================

# Logging functions
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

# Check if running in Qubes OS
check_qubes() {
    if ! command -v qvm-ls &> /dev/null; then
        error "This script must be run in Qubes OS"
        error "Qubes-specific commands (qvm-ls) not found."
        exit 1
    fi
    
    info "Detected Qubes OS environment"
}

# Check if running as root
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        error "This script must be run as root"
        exit 1
    fi
    
    info "Running as root user"
}

# Check if template exists
check_template() {
    if ! qvm-ls | grep -q "^${TEMPLATE_VM}\s"; then
        error "Template VM '${TEMPLATE_VM}' not found"
        error "Please create or install the Debian 12 template first:"
        error "  sudo qubesctl state.sls qvm.template-debian-12"
        exit 1
    fi
    
    info "Template VM '${TEMPLATE_VM}' found"
}

# Check if VM exists
vm_exists() {
    qvm-ls | grep -q "^$1\s"
}

# Create a VM
create_vm() {
    local vm_name=$1
    local vm_type=$2
    local template=$3
    local label=$4
    local memory=$5
    local maxmem=$6
    local vcpus=$7
    
    if vm_exists "$vm_name"; then
        info "VM $vm_name already exists, skipping creation"
        return 0
    fi
    
    info "Creating VM: $vm_name"
    info "  Type: $vm_type"
    info "  Template: $template"
    info "  Label: $label"
    info "  Memory: ${memory}MB"
    info "  Max Memory: ${maxmem}MB"
    info "  VCPUs: $vcpus"
    
    # Create the VM
    if ! qvm-create --label "$label" --template "$template" "$vm_name" 2>/dev/null; then
        error "Failed to create VM $vm_name"
        return 1
    fi
    
    # Set memory
    qvm-mem "$vm_name" "$memory" 2>/dev/null || warning "Failed to set memory for $vm_name"
    qvm-maxmem "$vm_name" "$maxmem" 2>/dev/null || warning "Failed to set max memory for $vm_name"
    qvm-vcpus "$vm_name" "$vcpus" 2>/dev/null || warning "Failed to set VCPUs for $vm_name"
    
    success "Created VM: $vm_name"
}

# Set VM network configuration
configure_vm_network() {
    local vm_name=$1
    local netvm=$2
    local provides_network=$3
    
    info "Configuring network for $vm_name"
    
    # Set netvm
    if [ -n "$netvm" ]; then
        qvm-prefs "$vm_name" netvm "$netvm" 2>/dev/null || warning "Failed to set netvm for $vm_name"
    fi
    
    # Set provides_network
    if [ "$provides_network" = "true" ]; then
        qvm-prefs "$vm_name" provides_network true 2>/dev/null || warning "Failed to set provides_network for $vm_name"
    else
        qvm-prefs "$vm_name" provides_network false 2>/dev/null || warning "Failed to set provides_network for $vm_name"
    fi
    
    success "Network configured for $vm_name"
}

# Install packages in a VM
install_packages() {
    local vm_name=$1
    shift
    local packages=("$@")
    
    info "Installing packages in $vm_name: ${packages[*]}"
    
    # Build package list
    local pkg_list=$(IFS=" "; echo "${packages[*]}")
    
    # Use qvm-run to install packages
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait \
        "apt-get update && apt-get install -y $pkg_list" 2>/dev/null; then
        warning "Failed to install packages in $vm_name"
        return 1
    fi
    
    success "Packages installed in $vm_name"
}

# Run command in VM
run_in_vm() {
    local vm_name=$1
    shift
    local command="$*"
    
    info "Running in $vm_name: $command"
    
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait "$command" 2>/dev/null; then
        warning "Failed to run command in $vm_name"
        return 1
    fi
    
    success "Command executed in $vm_name"
}

# Clone repository in VM
clone_repo() {
    local vm_name=$1
    
    info "Cloning repository in $vm_name"
    
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait \
        "git clone --branch $REPO_BRANCH $REPO_URL $INSTALL_DIR" 2>/dev/null; then
        error "Failed to clone repository in $vm_name"
        return 1
    fi
    
    success "Repository cloned in $vm_name"
}

# Setup Python environment
setup_python_env() {
    local vm_name=$1
    
    info "Setting up Python environment in $vm_name"
    
    # Create virtual environment
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait \
        "cd $INSTALL_DIR && python3 -m venv venv" 2>/dev/null; then
        error "Failed to create virtual environment in $vm_name"
        return 1
    fi
    
    # Install requirements
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait \
        "cd $INSTALL_DIR && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt" 2>/dev/null; then
        error "Failed to install Python requirements in $vm_name"
        return 1
    fi
    
    success "Python environment set up in $vm_name"
}

# ============================================================================
# VM Setup Functions
# ============================================================================

# Setup Database VM
setup_db_vm() {
    header "Setting up Database VM"
    
    # Create VM
    create_vm "$DB_VM" "AppVM" "$TEMPLATE_VM" "$DB_VM_LABEL" \
        "$DB_VM_MEMORY" "$DB_VM_MAXMEM" "$DB_VM_VCPUS" || return 1
    
    # Configure network (no network for DB VM)
    configure_vm_network "$DB_VM" "" "false" || return 1
    
    # Install PostgreSQL
    install_packages "$DB_VM" \
        postgresql-15 \
        postgresql-contrib \
        python3 \
        python3-psycopg2 \
        sudo || return 1
    
    # Clone repository
    clone_repo "$DB_VM" || return 1
    
    # Setup PostgreSQL
    info "Setting up PostgreSQL in $DB_VM"
    
    # Initialize database cluster
    run_in_vm "$DB_VM" "pg_createcluster 15 main --start" || warning "Failed to initialize PostgreSQL cluster"
    
    # Create user and database
    local db_password
    db_password=$(openssl rand -hex 16)
    run_in_vm "$DB_VM" "su - postgres -c \"psql -c \\\"CREATE USER omniscience WITH PASSWORD '$db_password';\\\"\"" || warning "Failed to create database user"
    run_in_vm "$DB_VM" "su - postgres -c \"psql -c \\\"CREATE DATABASE open_omniscience OWNER omniscience;\\\"\"" || warning "Failed to create database"
    
    # Configure PostgreSQL to listen on all interfaces
    run_in_vm "$DB_VM" "sed -i \"s/^#listen_addresses = 'localhost'/listen_addresses = '*'/\" /etc/postgresql/15/main/postgresql.conf" || warning "Failed to configure PostgreSQL"
    
    # Restart PostgreSQL
    run_in_vm "$DB_VM" "systemctl restart postgresql@15-main" || warning "Failed to restart PostgreSQL"
    
    success "Database VM setup complete"
}

# Setup API VM
setup_api_vm() {
    header "Setting up API VM"
    
    # Create VM
    create_vm "$API_VM" "AppVM" "$TEMPLATE_VM" "$API_VM_LABEL" \
        "$API_VM_MEMORY" "$API_VM_MAXMEM" "$API_VM_VCPUS" || return 1
    
    # Configure network
    configure_vm_network "$API_VM" "$NETVM" "false" || return 1
    
    # Install dependencies
    install_packages "$API_VM" \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        nginx \
        uvicorn \
        postgresql-client \
        sudo || return 1
    
    # Clone repository
    clone_repo "$API_VM" || return 1
    
    # Setup Python environment
    setup_python_env "$API_VM" || return 1
    
    # Configure nginx
    info "Configuring nginx in $API_VM"
    
    # Use a variable for the nginx config to avoid heredoc issues
    NGINX_CONFIG="server {
    listen 80;
    server_name localhost;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
    
    location /static/ {
        alias ${INSTALL_DIR}/src/static/;
    }
}"
    
    run_in_vm "$API_VM" "mkdir -p /etc/nginx/sites-available && echo \"$NGINX_CONFIG\" > /etc/nginx/sites-available/open-omniscience"
    
    # Enable site
    run_in_vm "$API_VM" "ln -sf /etc/nginx/sites-available/open-omniscience /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/default"
    
    # Test nginx configuration
    run_in_vm "$API_VM" "nginx -t"
    
    success "API VM setup complete"
}

# Setup Scraper VM
setup_scraper_vm() {
    header "Setting up Scraper VM"
    
    # Create VM
    create_vm "$SCRAPER_VM" "AppVM" "$TEMPLATE_VM" "$SCRAPER_VM_LABEL" \
        "$SCRAPER_VM_MEMORY" "$SCRAPER_VM_MAXMEM" "$SCRAPER_VM_VCPUS" || return 1
    
    # Configure network
    configure_vm_network "$SCRAPER_VM" "$NETVM" "false" || return 1
    
    # Install dependencies
    install_packages "$SCRAPER_VM" \
        python3 \
        python3-pip \
        git \
        curl \
        sudo \
        openssl || return 1
    
    # Clone repository
    clone_repo "$SCRAPER_VM" || return 1
    
    # Setup Python environment
    setup_python_env "$SCRAPER_VM" || return 1
    
    success "Scraper VM setup complete"
}

# Setup AI VM
setup_ai_vm() {
    header "Setting up AI VM"
    
    # Create VM
    create_vm "$AI_VM" "AppVM" "$TEMPLATE_VM" "$AI_VM_LABEL" \
        "$AI_VM_MEMORY" "$AI_VM_MAXMEM" "$AI_VM_VCPUS" || return 1
    
    # Configure network
    configure_vm_network "$AI_VM" "$NETVM" "false" || return 1
    
    # Install dependencies
    install_packages "$AI_VM" \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        sudo \
        openssl || return 1
    
    # Clone repository
    clone_repo "$AI_VM" || return 1
    
    # Setup Python environment
    setup_python_env "$AI_VM" || return 1
    
    success "AI VM setup complete"
}

# ============================================================================
# Main Execution
# ============================================================================

# Check environment
check_qubes
check_root
check_template

# Setup all VMs
setup_db_vm || { error "Failed to setup Database VM"; exit 1; }
setup_api_vm || { error "Failed to setup API VM"; exit 1; }
setup_scraper_vm || { error "Failed to setup Scraper VM"; exit 1; }
setup_ai_vm || { error "Failed to setup AI VM"; exit 1; }

success "Open-Omniscience Qubes-OS installation complete!"
