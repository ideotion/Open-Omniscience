#!/bin/bash

# ============================================================================
# Open-Omniscience Qubes-OS Automated Installer
# ============================================================================
# 
# Version: 2.0.0
# Compatibility: Qubes OS R4.1+ with Debian Trixie (12)
# 
# This script provides FULLY AUTOMATED deployment of Open-Omniscience in Qubes OS
# with support for:
#   - Disposable VMs (default-dvm) with persistent TemplateVMs
#   - No python-venv in disposables (uses system Python or TemplateVM-based venv)
#   - Proper Qubes RPC communication between isolated VMs
#   - Network isolation (DB VM has no network access)
#   - Automatic VM creation, configuration, and service deployment
# 
# Usage:
#   sudo ./qubes-installer.sh [OPTIONS]
# 
# Options:
#   --help, -h          Show this help message
#   --dry-run, -n       Show what would be done without making changes
#   --clean, -c         Remove all Open-Omniscience VMs and data
#   --template, -t NAME Use specific template (default: debian-12)
#   --netvm, -N NAME    Use specific NetVM (default: sys-whonix)
#   --memory, -m SIZE   Base memory in MB (default: 2048)
#   --verbose, -v       Enable verbose output
# 
# ============================================================================

set -euo pipefail

# ============================================================================
# Global Configuration
# ============================================================================

# Script version
VERSION="2.0.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# ============================================================================
# Default Configuration (can be overridden by command-line options)
# ============================================================================

# Repository
REPO_URL="https://github.com/ideotion/Open-Omniscience.git"
REPO_BRANCH="0.02_Qubes"

# Installation directories
INSTALL_DIR="/opt/open-omniscience"
LOG_DIR="/var/log/open-omniscience"
DATA_DIR="/var/lib/open-omniscience"
CONFIG_DIR="/etc/open-omniscience"

# VM Names
API_VM="open-omniscience-api"
DB_VM="open-omniscience-db"
SCRAPER_VM="open-omniscience-scraper"
AI_VM="open-omniscience-ai"

# Template VM (must support Debian Trixie)
TEMPLATE_VM="debian-12"

# NetVM for external access
NETVM="sys-whonix"

# VM Labels (Qubes OS color coding)
API_VM_LABEL="blue"
DB_VM_LABEL="green"
SCRAPER_VM_LABEL="yellow"
AI_VM_LABEL="red"

# Default Memory (MB)
BASE_MEMORY=2048

# VM Resource Allocation (multipliers of BASE_MEMORY)
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

# ============================================================================
# State Tracking
# ============================================================================

DRY_RUN=false
CLEAN_MODE=false
VERBOSE_MODE=false

# ============================================================================
# Utility Functions
# ============================================================================

# Enhanced logging with timestamps
log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        "INFO")    echo -e "${BLUE}[$timestamp] [INFO]${NC} $message" ;;
        "SUCCESS") echo -e "${GREEN}[$timestamp] [SUCCESS]${NC} $message" ;;
        "WARNING") echo -e "${YELLOW}[$timestamp] [WARNING]${NC} $message" ;;
        "ERROR")   echo -e "${RED}[$timestamp] [ERROR]${NC} $message" >&2 ;;
        "HEADER")  echo -e "\n${CYAN}[$timestamp] ========================================${NC}" ;;
                    echo -e "${CYAN}[$timestamp] $message${NC}" ;;
                    echo -e "${CYAN}[$timestamp] ========================================${NC}" ;;
        "VERBOSE") 
            if [ "$VERBOSE_MODE" = true ]; then
                echo -e "${WHITE}[$timestamp] [VERBOSE]${NC} $message"
            fi
            ;;
        *)         echo -e "[$timestamp] [$level] $message" ;;
    esac
}

# Check if running in Qubes OS
check_qubes_environment() {
    if ! command -v qvm-ls &> /dev/null; then
        log "ERROR" "This script must be run in Qubes OS"
        log "ERROR" "Qubes-specific commands (qvm-ls) not found."
        exit 1
    fi
    
    if ! command -v qvm-run &> /dev/null; then
        log "ERROR" "qvm-run command not found. Please ensure Qubes tools are installed."
        exit 1
    fi
    
    log "INFO" "Detected Qubes OS environment"
    
    # Check Qubes version
    if command -v qubesctl &> /dev/null; then
        QUBES_VERSION=$(qubesctl --version 2>/dev/null | head -1 | awk '{print $2}')
        log "INFO" "Qubes OS version: $QUBES_VERSION"
    fi
}

# Check if running as root
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log "ERROR" "This script must be run as root (use sudo)"
        exit 1
    fi
    log "INFO" "Running as root user"
}

# Parse command-line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                show_help
                exit 0
                ;;
            --dry-run|-n)
                DRY_RUN=true
                log "INFO" "Dry run mode enabled - no changes will be made"
                shift
                ;;
            --clean|-c)
                CLEAN_MODE=true
                log "INFO" "Clean mode enabled - will remove Open-Omniscience VMs"
                shift
                ;;
            --template|-t)
                TEMPLATE_VM="$2"
                log "INFO" "Template VM set to: $TEMPLATE_VM"
                shift 2
                ;;
            --netvm|-N)
                NETVM="$2"
                log "INFO" "NetVM set to: $NETVM"
                shift 2
                ;;
            --memory|-m)
                BASE_MEMORY="$2"
                log "INFO" "Base memory set to: ${BASE_MEMORY}MB"
                shift 2
                ;;
            --verbose|-v)
                VERBOSE_MODE=true
                log "INFO" "Verbose mode enabled"
                shift
                ;;
            *)
                log "ERROR" "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Show help message
show_help() {
    cat << EOF
Open-Omniscience Qubes-OS Automated Installer v$VERSION

Usage: sudo ./qubes-installer.sh [OPTIONS]

Options:
  --help, -h          Show this help message and exit
  --dry-run, -n       Show what would be done without making changes
  --clean, -c         Remove all Open-Omniscience VMs and data
  --template, -t NAME Use specific template VM (default: debian-12)
  --netvm, -N NAME    Use specific NetVM (default: sys-whonix)
  --memory, -m SIZE   Base memory in MB (default: 2048)
  --verbose, -v       Enable verbose output

Description:
  This script automates the deployment of Open-Omniscience across multiple
  Qubes OS VMs with proper isolation and security constraints.
  
  It creates 4 VMs:
    - $API_VM (Blue): API server and coordination
    - $DB_VM (Green): PostgreSQL database (no network access)
    - $SCRAPER_VM (Yellow): Web scraping workers
    - $AI_VM (Red): AI/LLM integration

  Features:
    - Automatic VM creation and configuration
    - Support for disposable VMs (default-dvm)
    - No python-venv in disposables (uses system Python)
    - Proper Qubes RPC communication
    - Network isolation for database VM
    - Automatic dependency installation

Examples:
  # Install with defaults
  sudo ./qubes-installer.sh
  
  # Dry run to see what would happen
  sudo ./qubes-installer.sh --dry-run
  
  # Use a different template
  sudo ./qubes-installer.sh --template my-debian-12
  
  # Clean up (remove all Open-Omniscience VMs)
  sudo ./qubes-installer.sh --clean

EOF
}

# ============================================================================
# Qubes-Specific Functions
# ============================================================================

# Check if a VM exists
vm_exists() {
    local vm_name="$1"
    qvm-ls 2>/dev/null | grep -q "^${vm_name}\s" || return 1
    return 0
}

# Check if a VM is running
vm_running() {
    local vm_name="$1"
    qvm-ls 2>/dev/null | grep -q "^${vm_name}\s.*Running" || return 1
    return 0
}

# Check if template exists
check_template() {
    if ! vm_exists "$TEMPLATE_VM"; then
        log "ERROR" "Template VM '$TEMPLATE_VM' not found"
        log "ERROR" "Available templates:"
        qvm-ls --templates 2>/dev/null | sed 's/^/  /' || true
        log "ERROR" "Please install the Debian 12 template first:"
        log "ERROR" "  sudo qubesctl state.sls qvm.template-debian-12"
        exit 1
    fi
    log "INFO" "Template VM '$TEMPLATE_VM' found"
}

# Check if NetVM exists
check_netvm() {
    if [ -n "$NETVM" ] && ! vm_exists "$NETVM"; then
        log "ERROR" "NetVM '$NETVM' not found"
        log "ERROR" "Available VMs:"
        qvm-ls 2>/dev/null | sed 's/^/  /' || true
        exit 1
    fi
    log "INFO" "NetVM '$NETVM' found"
}

# Create a VM with proper error handling
create_vm() {
    local vm_name="$1"
    local vm_type="$2"
    local template="$3"
    local label="$4"
    local memory="$5"
    local maxmem="$6"
    local vcpus="$7"
    
    if vm_exists "$vm_name"; then
        log "INFO" "VM $vm_name already exists, skipping creation"
        return 0
    fi
    
    log "INFO" "Creating VM: $vm_name"
    log "VERBOSE" "  Type: $vm_type, Template: $template, Label: $label"
    log "VERBOSE" "  Memory: ${memory}MB, Max: ${maxmem}MB, VCPUs: $vcpus"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would create VM: $vm_name"
        return 0
    fi
    
    # Create the VM
    if ! qvm-create --label "$label" --template "$template" "$vm_name" 2>&1; then
        log "ERROR" "Failed to create VM $vm_name"
        return 1
    fi
    
    # Set memory and CPU
    qvm-mem "$vm_name" "$memory" 2>/dev/null || log "WARNING" "Failed to set memory for $vm_name"
    qvm-maxmem "$vm_name" "$maxmem" 2>/dev/null || log "WARNING" "Failed to set max memory for $vm_name"
    qvm-vcpus "$vm_name" "$vcpus" 2>/dev/null || log "WARNING" "Failed to set VCPUs for $vm_name"
    
    # Set VM to start automatically
    qvm-prefs "$vm_name" autostart True 2>/dev/null || log "WARNING" "Failed to set autostart for $vm_name"
    
    log "SUCCESS" "Created VM: $vm_name"
    return 0
}

# Configure VM network settings
configure_vm_network() {
    local vm_name="$1"
    local netvm="$2"
    local provides_network="$3"
    
    log "INFO" "Configuring network for $vm_name"
    log "VERBOSE" "  NetVM: ${netvm:-none}, Provides Network: $provides_network"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would configure network for $vm_name"
        return 0
    fi
    
    # Set netvm
    if [ -n "$netvm" ]; then
        if ! qvm-prefs "$vm_name" netvm "$netvm" 2>/dev/null; then
            log "WARNING" "Failed to set netvm for $vm_name"
        fi
    else
        # No network
        if ! qvm-prefs "$vm_name" netvm "" 2>/dev/null; then
            log "WARNING" "Failed to remove netvm for $vm_name"
        fi
    fi
    
    # Set provides_network
    if [ "$provides_network" = "true" ]; then
        if ! qvm-prefs "$vm_name" provides_network true 2>/dev/null; then
            log "WARNING" "Failed to set provides_network=true for $vm_name"
        fi
    else
        if ! qvm-prefs "$vm_name" provides_network false 2>/dev/null; then
            log "WARNING" "Failed to set provides_network=false for $vm_name"
        fi
    fi
    
    log "SUCCESS" "Network configured for $vm_name"
    return 0
}

# Execute command in VM with proper error handling
# Uses qvm-run with --skip-prepare and --no-wait for disposables
run_in_vm() {
    local vm_name="$1"
    shift
    local command="$*"
    
    log "VERBOSE" "Running in $vm_name: $command"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would run in $vm_name: $command"
        return 0
    fi
    
    # Check if VM exists
    if ! vm_exists "$vm_name"; then
        log "ERROR" "VM $vm_name does not exist"
        return 1
    fi
    
    # For AppVMs, use --skip-prepare and --no-wait to handle disposables
    # For TemplateVMs, we need to be more careful
    if qvm-ls 2>/dev/null | grep -q "^${vm_name}\s.*TemplateVM"; then
        # TemplateVM - run normally
        if ! qvm-run -u "$vm_name" "$command" 2>&1; then
            log "WARNING" "Failed to run command in $vm_name: $command"
            return 1
        fi
    else
        # AppVM - use --skip-prepare and --no-wait for disposable compatibility
        if ! qvm-run -u "$vm_name" --skip-prepare --no-wait "$command" 2>&1; then
            log "WARNING" "Failed to run command in $vm_name: $command"
            return 1
        fi
    fi
    
    log "SUCCESS" "Command executed in $vm_name"
    return 0
}

# Install packages in VM
# For disposables, we need to install in TemplateVM and ensure they're available
install_packages_in_vm() {
    local vm_name="$1"
    shift
    local packages=("$@")
    
    log "INFO" "Installing packages in $vm_name: ${packages[*]}"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would install packages in $vm_name: ${packages[*]}"
        return 0
    fi
    
    # Build package list
    local pkg_list=$(IFS=" "; echo "${packages[*]}")
    
    # Update package list and install
    local install_cmd="apt-get update && apt-get install -y $pkg_list"
    
    if ! run_in_vm "$vm_name" "$install_cmd"; then
        log "ERROR" "Failed to install packages in $vm_name"
        return 1
    fi
    
    log "SUCCESS" "Packages installed in $vm_name"
    return 0
}

# Setup Python environment in VM
# For disposables: install system-wide Python packages (no venv)
# For persistent VMs: create venv in TemplateVM
setup_python_in_vm() {
    local vm_name="$1"
    local use_venv="$2"  # true or false
    
    log "INFO" "Setting up Python in $vm_name (venv: $use_venv)"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would setup Python in $vm_name"
        return 0
    fi
    
    if [ "$use_venv" = "true" ]; then
        # Create virtual environment
        if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && python3 -m venv venv"; then
            log "ERROR" "Failed to create virtual environment in $vm_name"
            return 1
        fi
        
        # Upgrade pip
        if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && source venv/bin/activate && pip install --upgrade pip"; then
            log "WARNING" "Failed to upgrade pip in $vm_name"
        fi
        
        log "SUCCESS" "Virtual environment created in $vm_name"
    else
        # For disposables: install system-wide
        log "INFO" "Installing Python packages system-wide in $vm_name (disposable-compatible)"
        
        # Install pip if not present
        if ! run_in_vm "$vm_name" "apt-get install -y python3-pip"; then
            log "WARNING" "Failed to install python3-pip in $vm_name"
        fi
        
        # Upgrade pip system-wide
        if ! run_in_vm "$vm_name" "pip3 install --upgrade pip"; then
            log "WARNING" "Failed to upgrade pip in $vm_name"
        fi
        
        log "SUCCESS" "Python system environment configured in $vm_name"
    fi
    
    return 0
}

# Install Python requirements
install_python_requirements() {
    local vm_name="$1"
    local use_venv="$2"
    
    log "INFO" "Installing Python requirements in $vm_name"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would install Python requirements in $vm_name"
        return 0
    fi
    
    if [ "$use_venv" = "true" ]; then
        # Use venv
        if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && source venv/bin/activate && pip install -r requirements.txt"; then
            log "ERROR" "Failed to install requirements in $vm_name"
            return 1
        fi
    else
        # System-wide installation for disposables
        if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && pip3 install -r requirements.txt"; then
            log "ERROR" "Failed to install requirements in $vm_name"
            return 1
        fi
    fi
    
    log "SUCCESS" "Python requirements installed in $vm_name"
    return 0
}

# Clone or update repository in VM
setup_repository_in_vm() {
    local vm_name="$1"
    
    log "INFO" "Setting up repository in $vm_name"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would setup repository in $vm_name"
        return 0
    fi
    
    # Check if directory exists
    local check_cmd="test -d $INSTALL_DIR"
    if run_in_vm "$vm_name" "$check_cmd" 2>/dev/null; then
        # Repository exists, pull latest changes
        if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && git pull origin $REPO_BRANCH"; then
            log "WARNING" "Failed to pull latest changes in $vm_name"
        fi
    else
        # Clone fresh
        if ! run_in_vm "$vm_name" "git clone --branch $REPO_BRANCH $REPO_URL $INSTALL_DIR"; then
            log "ERROR" "Failed to clone repository in $vm_name"
            return 1
        fi
    fi
    
    # Checkout the Qubes branch
    if ! run_in_vm "$vm_name" "cd $INSTALL_DIR && git checkout $REPO_BRANCH"; then
        log "ERROR" "Failed to checkout branch $REPO_BRANCH in $vm_name"
        return 1
    fi
    
    log "SUCCESS" "Repository setup in $vm_name"
    return 0
}

# ============================================================================
# VM-Specific Setup Functions
# ============================================================================

# Setup Database VM (no network, persistent)
setup_db_vm() {
    log "HEADER" "Setting up Database VM ($DB_VM)"
    
    # Create VM
    if ! create_vm "$DB_VM" "AppVM" "$TEMPLATE_VM" "$DB_VM_LABEL" \
        "$DB_VM_MEMORY" "$DB_VM_MAXMEM" "$DB_VM_VCPUS"; then
        return 1
    fi
    
    # Configure network (NO network for DB VM)
    if ! configure_vm_network "$DB_VM" "" "false"; then
        return 1
    fi
    
    # Install PostgreSQL and dependencies
    if ! install_packages_in_vm "$DB_VM" \
        postgresql-15 \
        postgresql-contrib \
        python3 \
        python3-psycopg2 \
        sudo \
        openssl; then
        return 1
    fi
    
    # Setup repository
    if ! setup_repository_in_vm "$DB_VM"; then
        return 1
    fi
    
    # Setup Python (use venv since DB VM is persistent)
    if ! setup_python_in_vm "$DB_VM" "true"; then
        return 1
    fi
    
    # Install Python requirements
    if ! install_python_requirements "$DB_VM" "true"; then
        return 1
    fi
    
    # Configure PostgreSQL
    log "INFO" "Configuring PostgreSQL in $DB_VM"
    
    # Generate a secure password
    local db_password
    db_password=$(openssl rand -hex 16)
    
    # Initialize database cluster
    if ! run_in_vm "$DB_VM" "pg_createcluster 15 main --start"; then
        log "WARNING" "Failed to initialize PostgreSQL cluster"
    fi
    
    # Create user and database
    if ! run_in_vm "$DB_VM" "su - postgres -c \"psql -c \\\"CREATE USER omniscience WITH PASSWORD '$db_password';\\\"\""; then
        log "WARNING" "Failed to create database user"
    fi
    
    if ! run_in_vm "$DB_VM" "su - postgres -c \"psql -c \\\"CREATE DATABASE open_omniscience OWNER omniscience;\\\"\""; then
        log "WARNING" "Failed to create database"
    fi
    
    # Configure PostgreSQL to listen on all interfaces (for Qubes RPC)
    if ! run_in_vm "$DB_VM" "sed -i \"s/^#listen_addresses = 'localhost'/listen_addresses = '*'/\" /etc/postgresql/15/main/postgresql.conf"; then
        log "WARNING" "Failed to configure PostgreSQL listen addresses"
    fi
    
    # Configure pg_hba.conf to allow connections from other VMs
    # In Qubes, we use RPC, but we still need to allow local connections
    if ! run_in_vm "$DB_VM" "echo 'host    all             all             127.0.0.1/32            md5' >> /etc/postgresql/15/main/pg_hba.conf"; then
        log "WARNING" "Failed to configure pg_hba.conf"
    fi
    
    # Restart PostgreSQL
    if ! run_in_vm "$DB_VM" "systemctl restart postgresql@15-main"; then
        log "WARNING" "Failed to restart PostgreSQL"
    fi
    
    # Save database password to config file in VM
    if ! run_in_vm "$DB_VM" "mkdir -p $CONFIG_DIR && echo \"DB_PASSWORD=$db_password\" > $CONFIG_DIR/database.conf"; then
        log "WARNING" "Failed to save database configuration"
    fi
    
    # Create data directory
    if ! run_in_vm "$DB_VM" "mkdir -p $DATA_DIR && chown -R omniscience:omniscience $DATA_DIR"; then
        log "WARNING" "Failed to create data directory"
    fi
    
    log "SUCCESS" "Database VM setup complete"
    return 0
}

# Setup API VM (has network, persistent)
setup_api_vm() {
    log "HEADER" "Setting up API VM ($API_VM)"
    
    # Create VM
    if ! create_vm "$API_VM" "AppVM" "$TEMPLATE_VM" "$API_VM_LABEL" \
        "$API_VM_MEMORY" "$API_VM_MAXMEM" "$API_VM_VCPUS"; then
        return 1
    fi
    
    # Configure network
    if ! configure_vm_network "$API_VM" "$NETVM" "false"; then
        return 1
    fi
    
    # Install dependencies
    if ! install_packages_in_vm "$API_VM" \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        nginx \
        uvicorn \
        postgresql-client \
        sudo \
        openssl; then
        return 1
    fi
    
    # Setup repository
    if ! setup_repository_in_vm "$API_VM"; then
        return 1
    fi
    
    # Setup Python with venv (API VM is persistent)
    if ! setup_python_in_vm "$API_VM" "true"; then
        return 1
    fi
    
    # Install Python requirements
    if ! install_python_requirements "$API_VM" "true"; then
        return 1
    fi
    
    # Configure nginx
    log "INFO" "Configuring nginx in $API_VM"
    
    local nginx_config="server {
    listen 80;
    server_name localhost;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /static/ {
        alias ${INSTALL_DIR}/src/static/;
    }
}"
    
    if ! run_in_vm "$API_VM" "mkdir -p /etc/nginx/sites-available && echo '$nginx_config' > /etc/nginx/sites-available/open-omniscience"; then
        log "WARNING" "Failed to create nginx configuration"
    fi
    
    # Enable site
    if ! run_in_vm "$API_VM" "ln -sf /etc/nginx/sites-available/open-omniscience /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/default"; then
        log "WARNING" "Failed to enable nginx site"
    fi
    
    # Test nginx configuration
    if ! run_in_vm "$API_VM" "nginx -t"; then
        log "WARNING" "nginx configuration test failed"
    fi
    
    # Create systemd service for API
    log "INFO" "Creating systemd service for API"
    
    local api_service="[Unit]
Description=Open-Omniscience API Server
After=network.target

[Service]
User=user
WorkingDirectory=${INSTALL_DIR}
Environment=PATH=${INSTALL_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
    
    if ! run_in_vm "$API_VM" "echo '$api_service' > /etc/systemd/system/open-omniscience-api.service"; then
        log "WARNING" "Failed to create API service"
    fi
    
    # Reload systemd
    if ! run_in_vm "$API_VM" "systemctl daemon-reload"; then
        log "WARNING" "Failed to reload systemd"
    fi
    
    # Enable and start service
    if ! run_in_vm "$API_VM" "systemctl enable open-omniscience-api.service"; then
        log "WARNING" "Failed to enable API service"
    fi
    
    if ! run_in_vm "$API_VM" "systemctl start open-omniscience-api.service"; then
        log "WARNING" "Failed to start API service"
    fi
    
    # Configure Qubes RPC for API VM
    log "INFO" "Configuring Qubes RPC for API VM"
    
    # Create RPC configuration
    local rpc_config="[RPC]
# API VM can call DB VM for database operations
open-omniscience.db.query = open-omniscience-db + open-omniscience-db
open-omniscience.db.store = open-omniscience-db + open-omniscience-db

# API VM can call Scraper VM for scraping operations
open-omniscience.scrape.start = open-omniscience-scraper + open-omniscience-scraper
open-omniscience.scrape.status = open-omniscience-scraper + open-omniscience-scraper

# API VM can call AI VM for AI operations
open-omniscience.ai.analyze = open-omniscience-ai + open-omniscience-ai
open-omniscience.ai.generate = open-omniscience-ai + open-omniscience-ai"
    
    if ! run_in_vm "$API_VM" "mkdir -p $CONFIG_DIR && echo '$rpc_config' > $CONFIG_DIR/rpc.conf"; then
        log "WARNING" "Failed to create RPC configuration"
    fi
    
    log "SUCCESS" "API VM setup complete"
    return 0
}

# Setup Scraper VM (has network, can be disposable-compatible)
setup_scraper_vm() {
    log "HEADER" "Setting up Scraper VM ($SCRAPER_VM)"
    
    # Create VM
    if ! create_vm "$SCRAPER_VM" "AppVM" "$TEMPLATE_VM" "$SCRAPER_VM_LABEL" \
        "$SCRAPER_VM_MEMORY" "$SCRAPER_VM_MAXMEM" "$SCRAPER_VM_VCPUS"; then
        return 1
    fi
    
    # Configure network
    if ! configure_vm_network "$SCRAPER_VM" "$NETVM" "false"; then
        return 1
    fi
    
    # Install dependencies
    if ! install_packages_in_vm "$SCRAPER_VM" \
        python3 \
        python3-pip \
        git \
        curl \
        sudo \
        openssl \
        # Scraping dependencies
        python3-requests \
        python3-beautifulsoup4 \
        python3-lxml \
        python3-html5lib; then
        return 1
    fi
    
    # Setup repository
    if ! setup_repository_in_vm "$SCRAPER_VM"; then
        return 1
    fi
    
    # Setup Python - for scrapers, we can use system-wide to support disposables
    # But since this is a persistent VM, we'll use venv
    if ! setup_python_in_vm "$SCRAPER_VM" "true"; then
        return 1
    fi
    
    # Install Python requirements
    if ! install_python_requirements "$SCRAPER_VM" "true"; then
        return 1
    fi
    
    # Configure Qubes RPC for Scraper VM
    log "INFO" "Configuring Qubes RPC for Scraper VM"
    
    local rpc_config="[RPC]
# Scraper VM can be called by API VM
open-omniscience.scrape.start = * + @anyvm
open-omniscience.scrape.status = * + @anyvm"
    
    if ! run_in_vm "$SCRAPER_VM" "mkdir -p $CONFIG_DIR && echo '$rpc_config' > $CONFIG_DIR/rpc.conf"; then
        log "WARNING" "Failed to create RPC configuration"
    fi
    
    # Create systemd service for Scraper
    local scraper_service="[Unit]
Description=Open-Omniscience Scraper Worker
After=network.target

[Service]
User=user
WorkingDirectory=${INSTALL_DIR}
Environment=PATH=${INSTALL_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/src/qubes/vm/scraper_vm.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
    
    if ! run_in_vm "$SCRAPER_VM" "echo '$scraper_service' > /etc/systemd/system/open-omniscience-scraper.service"; then
        log "WARNING" "Failed to create Scraper service"
    fi
    
    # Reload systemd and enable service
    if ! run_in_vm "$SCRAPER_VM" "systemctl daemon-reload && systemctl enable open-omniscience-scraper.service"; then
        log "WARNING" "Failed to enable Scraper service"
    fi
    
    log "SUCCESS" "Scraper VM setup complete"
    return 0
}

# Setup AI VM (has network, persistent)
setup_ai_vm() {
    log "HEADER" "Setting up AI VM ($AI_VM)"
    
    # Create VM
    if ! create_vm "$AI_VM" "AppVM" "$TEMPLATE_VM" "$AI_VM_LABEL" \
        "$AI_VM_MEMORY" "$AI_VM_MAXMEM" "$AI_VM_VCPUS"; then
        return 1
    fi
    
    # Configure network
    if ! configure_vm_network "$AI_VM" "$NETVM" "false"; then
        return 1
    fi
    
    # Install dependencies
    if ! install_packages_in_vm "$AI_VM" \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        sudo \
        openssl; then
        return 1
    fi
    
    # Setup repository
    if ! setup_repository_in_vm "$AI_VM"; then
        return 1
    fi
    
    # Setup Python with venv
    if ! setup_python_in_vm "$AI_VM" "true"; then
        return 1
    fi
    
    # Install Python requirements
    if ! install_python_requirements "$AI_VM" "true"; then
        return 1
    fi
    
    # Configure Qubes RPC for AI VM
    log "INFO" "Configuring Qubes RPC for AI VM"
    
    local rpc_config="[RPC]
# AI VM can be called by API VM
open-omniscience.ai.analyze = * + @anyvm
open-omniscience.ai.generate = * + @anyvm"
    
    if ! run_in_vm "$AI_VM" "mkdir -p $CONFIG_DIR && echo '$rpc_config' > $CONFIG_DIR/rpc.conf"; then
        log "WARNING" "Failed to create RPC configuration"
    fi
    
    # Create systemd service for AI
    local ai_service="[Unit]
Description=Open-Omniscience AI Service
After=network.target

[Service]
User=user
WorkingDirectory=${INSTALL_DIR}
Environment=PATH=${INSTALL_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/src/qubes/vm/ai_vm.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
    
    if ! run_in_vm "$AI_VM" "echo '$ai_service' > /etc/systemd/system/open-omniscience-ai.service"; then
        log "WARNING" "Failed to create AI service"
    fi
    
    # Reload systemd and enable service
    if ! run_in_vm "$AI_VM" "systemctl daemon-reload && systemctl enable open-omniscience-ai.service"; then
        log "WARNING" "Failed to enable AI service"
    fi
    
    log "SUCCESS" "AI VM setup complete"
    return 0
}

# ============================================================================
# Disposable VM Support Functions
# ============================================================================

# Create a disposable template for Open-Omniscience
# This allows creating disposable VMs with pre-installed dependencies
setup_disposable_template() {
    local template_name="open-omniscience-disp-template"
    
    log "HEADER" "Setting up Disposable Template VM ($template_name)"
    
    if vm_exists "$template_name"; then
        log "INFO" "Disposable template $template_name already exists"
        return 0
    fi
    
    log "INFO" "Creating disposable template from $TEMPLATE_VM"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would create disposable template"
        return 0
    fi
    
    # Create TemplateVM from debian-12
    if ! qvm-create --label "black" --template "$TEMPLATE_VM" --template "$template_name" 2>&1; then
        log "ERROR" "Failed to create disposable template"
        return 1
    fi
    
    # Install common dependencies in template
    if ! install_packages_in_vm "$template_name" \
        python3 \
        python3-pip \
        git \
        curl \
        sudo \
        openssl; then
        return 1
    fi
    
    # Setup repository in template
    if ! setup_repository_in_vm "$template_name"; then
        return 1
    fi
    
    # Install Python requirements system-wide (for disposables)
    if ! run_in_vm "$template_name" "cd $INSTALL_DIR && pip3 install -r requirements.txt"; then
        log "ERROR" "Failed to install requirements in disposable template"
        return 1
    fi
    
    # Shutdown the template
    if ! qvm-shutdown "$template_name" 2>/dev/null; then
        log "WARNING" "Failed to shutdown disposable template"
    fi
    
    log "SUCCESS" "Disposable template setup complete"
    return 0
}

# Create a disposable VM for testing
create_disposable_vm() {
    local disp_vm="open-omniscience-disp-$$"
    
    log "INFO" "Creating disposable VM: $disp_vm"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would create disposable VM"
        return 0
    fi
    
    # Create disposable VM from template
    if ! qvm-create --label "black" --template "open-omniscience-disp-template" --dispvm "$TEMPLATE_VM" "$disp_vm" 2>&1; then
        log "ERROR" "Failed to create disposable VM"
        return 1
    fi
    
    # Set network
    if ! configure_vm_network "$disp_vm" "$NETVM" "false"; then
        return 1
    fi
    
    log "SUCCESS" "Disposable VM created: $disp_vm"
    log "INFO" "To use: qvm-run -u $disp_vm 'cd $INSTALL_DIR && python3 src/main.py'"
    
    return 0
}

# ============================================================================
# Cleanup Functions
# ============================================================================

# Remove a VM and all its data
remove_vm() {
    local vm_name="$1"
    
    if ! vm_exists "$vm_name"; then
        log "INFO" "VM $vm_name does not exist, skipping removal"
        return 0
    fi
    
    log "INFO" "Removing VM: $vm_name"
    
    if [ "$DRY_RUN" = true ]; then
        log "INFO" "[DRY RUN] Would remove VM: $vm_name"
        return 0
    fi
    
    # Shutdown VM first
    if vm_running "$vm_name"; then
        if ! qvm-shutdown "$vm_name" 2>/dev/null; then
            log "WARNING" "Failed to shutdown $vm_name, forcing removal"
        fi
    fi
    
    # Remove VM
    if ! qvm-remove "$vm_name" 2>&1; then
        log "ERROR" "Failed to remove VM $vm_name"
        return 1
    fi
    
    log "SUCCESS" "Removed VM: $vm_name"
    return 0
}

# Clean all Open-Omniscience VMs
clean_all() {
    log "HEADER" "Cleaning up Open-Omniscience VMs"
    
    local vms_to_remove=("$API_VM" "$DB_VM" "$SCRAPER_VM" "$AI_VM" "open-omniscience-disp-template")
    
    for vm in "${vms_to_remove[@]}"; do
        if remove_vm "$vm"; then
            log "INFO" "Successfully removed $vm"
        else
            log "ERROR" "Failed to remove $vm"
        fi
    done
    
    log "SUCCESS" "Cleanup complete"
}

# ============================================================================
# Verification Functions
# ============================================================================

# Verify installation
verify_installation() {
    log "HEADER" "Verifying Installation"
    
    local all_ok=true
    
    # Check VMs exist
    for vm in "$API_VM" "$DB_VM" "$SCRAPER_VM" "$AI_VM"; do
        if ! vm_exists "$vm"; then
            log "ERROR" "VM $vm does not exist"
            all_ok=false
        else
            log "SUCCESS" "VM $vm exists"
        fi
    done
    
    # Check VMs are running
    for vm in "$API_VM" "$DB_VM" "$SCRAPER_VM" "$AI_VM"; do
        if ! vm_running "$vm"; then
            log "WARNING" "VM $vm is not running"
            all_ok=false
        else
            log "SUCCESS" "VM $vm is running"
        fi
    done
    
    # Check network configuration
    if ! qvm-prefs "$DB_VM" 2>/dev/null | grep -q "netvm.*none"; then
        log "ERROR" "DB VM has network access (should have none)"
        all_ok=false
    else
        log "SUCCESS" "DB VM has no network access"
    fi
    
    # Check services
    if vm_exists "$API_VM"; then
        if ! run_in_vm "$API_VM" "systemctl is-active open-omniscience-api.service 2>/dev/null || true" | grep -q "active"; then
            log "WARNING" "API service is not active"
            all_ok=false
        else
            log "SUCCESS" "API service is active"
        fi
    fi
    
    if [ "$all_ok" = true ]; then
        log "SUCCESS" "All verification checks passed!"
    else
        log "ERROR" "Some verification checks failed"
        return 1
    fi
    
    return 0
}

# ============================================================================
# Main Installation Function
# ============================================================================

perform_installation() {
    log "HEADER" "Starting Open-Omniscience Qubes-OS Installation"
    
    # Check environment
    check_qubes_environment
    check_root
    check_template
    check_netvm
    
    # Show configuration
    log "HEADER" "Installation Configuration"
    log "INFO" "Repository: $REPO_URL (branch: $REPO_BRANCH)"
    log "INFO" "Template: $TEMPLATE_VM"
    log "INFO" "NetVM: $NETVM"
    log "INFO" "Installation directory: $INSTALL_DIR"
    log "INFO" ""
    log "INFO" "VM Configuration:"
    log "INFO" "  API VM: $API_VM (${API_VM_MEMORY}MB RAM, ${API_VM_VCPUS} VCPUs, label: $API_VM_LABEL)"
    log "INFO" "  DB VM: $DB_VM (${DB_VM_MEMORY}MB RAM, ${DB_VM_VCPUS} VCPUs, label: $DB_VM_LABEL)"
    log "INFO" "  Scraper VM: $SCRAPER_VM (${SCRAPER_VM_MEMORY}MB RAM, ${SCRAPER_VM_VCPUS} VCPUs, label: $SCRAPER_VM_LABEL)"
    log "INFO" "  AI VM: $AI_VM (${AI_VM_MEMORY}MB RAM, ${AI_VM_VCPUS} VCPUs, label: $AI_VM_LABEL)"
    
    # Create VMs
    log "HEADER" "Creating VMs"
    
    if ! setup_db_vm; then
        log "ERROR" "Failed to setup Database VM"
        return 1
    fi
    
    if ! setup_api_vm; then
        log "ERROR" "Failed to setup API VM"
        return 1
    fi
    
    if ! setup_scraper_vm; then
        log "ERROR" "Failed to setup Scraper VM"
        return 1
    fi
    
    if ! setup_ai_vm; then
        log "ERROR" "Failed to setup AI VM"
        return 1
    fi
    
    # Setup disposable template (optional)
    if ! setup_disposable_template; then
        log "WARNING" "Failed to setup disposable template (non-critical)"
    fi
    
    # Verify installation
    if ! verify_installation; then
        log "ERROR" "Installation verification failed"
        return 1
    fi
    
    log "HEADER" "Installation Complete!"
    log "SUCCESS" "Open-Omniscience has been successfully installed in Qubes OS"
    log "INFO" ""
    log "INFO" "Access your installation:"
    log "INFO" "  API: qvm-run -u $API_VM 'curl http://localhost'"
    log "INFO" "  DB: qvm-run -u $DB_VM 'psql -U omniscience -d open_omniscience'"
    log "INFO" "  Scraper: qvm-run -u $SCRAPER_VM 'systemctl status open-omniscience-scraper'"
    log "INFO" "  AI: qvm-run -u $AI_VM 'systemctl status open-omniscience-ai'"
    log "INFO" ""
    log "INFO" "To create a disposable VM for testing:"
    log "INFO" "  sudo ./qubes-installer.sh --create-disposable"
    log "INFO" ""
    log "INFO" "To clean up:"
    log "INFO" "  sudo ./qubes-installer.sh --clean"
    
    return 0
}

# ============================================================================
# Main Script Execution
# ============================================================================

main() {
    # Parse command-line arguments
    parse_arguments "$@"
    
    # Show header
    log "HEADER" "Open-Omniscience Qubes-OS Installer v$VERSION"
    log "INFO" "Compatible with Qubes OS R4.1+ and Debian Trixie (12)"
    log "INFO" ""
    
    # Handle clean mode
    if [ "$CLEAN_MODE" = true ]; then
        clean_all
        exit 0
    fi
    
    # Perform installation
    if ! perform_installation; then
        log "ERROR" "Installation failed"
        exit 1
    fi
    
    exit 0
}

# Execute main function with all arguments
main "$@"
