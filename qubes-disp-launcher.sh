#!/bin/bash

# ============================================================================
# Open-Omniscience Qubes Disposable VM Launcher
# ============================================================================
#
# Version: 1.0.0
# Compatibility: Qubes OS R4.1+ with Debian Trixie (12)
#
# This script provides a convenient way to launch disposable VMs for
# Open-Omniscience testing and development, with full support for:
#   - Temporary VMs (default-dvm) with pre-configured environments
#   - No python-venv persistence issues (uses system Python)
#   - Automatic cleanup after use
#   - Qubes-specific constraints and security
#
# Usage:
#   ./qubes-disp-launcher.sh [COMMAND] [OPTIONS]
#
# Commands:
#   start       Start a new disposable VM with Open-Omniscience
#   run         Run a command in a disposable VM
#   exec        Execute a Python script in a disposable VM
#   shell       Open a shell in a disposable VM
#   clean       Clean up disposable VMs
#   list        List active disposable VMs
#
# ============================================================================

set -euo pipefail

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
REPO_BRANCH="0.03_Qubes"

# Installation directories
INSTALL_DIR="/opt/open-omniscience"

# Template for disposable VMs
DISP_TEMPLATE="open-omniscience-disp-template"

# Default NetVM
NETVM="sys-whonix"

# VM naming
DISP_PREFIX="open-omniscience-disp"

# ============================================================================
# Utility Functions
# ============================================================================

# Logging
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
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check if running in Qubes OS
check_qubes() {
    if ! command -v qvm-ls &> /dev/null; then
        error "This script must be run in Qubes OS"
        exit 1
    fi
}

# Check if template exists
check_disp_template() {
    if ! qvm-ls 2>/dev/null | grep -q "^${DISP_TEMPLATE}\s"; then
        error "Disposable template '$DISP_TEMPLATE' not found"
        error "Please run the main installer first:"
        error "  sudo ./qubes-installer.sh"
        exit 1
    fi
}

# Check if NetVM exists
check_netvm() {
    if ! qvm-ls 2>/dev/null | grep -q "^${NETVM}\s"; then
        error "NetVM '$NETVM' not found"
        exit 1
    fi
}

# Generate a unique VM name
generate_vm_name() {
    local timestamp
    timestamp=$(date +%s%N)
    echo "${DISP_PREFIX}-${timestamp:0:8}"
}

# Create a disposable VM
create_disp_vm() {
    local vm_name="$1"
    
    info "Creating disposable VM: $vm_name"
    
    # Create VM from template
    if ! qvm-create --label "black" --template "$DISP_TEMPLATE" "$vm_name" 2>&1; then
        error "Failed to create disposable VM"
        return 1
    fi
    
    # Set network
    if ! qvm-prefs "$vm_name" netvm "$NETVM" 2>/dev/null; then
        warning "Failed to set NetVM for $vm_name"
    fi
    
    # Set as disposable
    if ! qvm-prefs "$vm_name" template "$DISP_TEMPLATE" 2>/dev/null; then
        warning "Failed to set template for $vm_name"
    fi
    
    success "Created disposable VM: $vm_name"
    return 0
}

# Run command in disposable VM
run_in_disp_vm() {
    local vm_name="$1"
    shift
    local command="$*"
    
    info "Running in $vm_name: $command"
    
    # Use qvm-run with --skip-prepare and --no-wait for disposables
    if ! qvm-run -u "$vm_name" --skip-prepare --no-wait "$command" 2>&1; then
        error "Failed to run command in $vm_name"
        return 1
    fi
    
    return 0
}

# Clean up a disposable VM
cleanup_disp_vm() {
    local vm_name="$1"
    
    info "Cleaning up disposable VM: $vm_name"
    
    # Shutdown VM
    if qvm-ls 2>/dev/null | grep -q "^${vm_name}\s.*Running"; then
        if ! qvm-shutdown "$vm_name" 2>/dev/null; then
            warning "Failed to shutdown $vm_name"
        fi
    fi
    
    # Remove VM
    if ! qvm-remove "$vm_name" 2>&1; then
        error "Failed to remove $vm_name"
        return 1
    fi
    
    success "Cleaned up disposable VM: $vm_name"
    return 0
}

# List disposable VMs
list_disp_vms() {
    info "Active disposable VMs:"
    
    local found=false
    for vm in $(qvm-ls 2>/dev/null | grep "^${DISP_PREFIX}-" | awk '{print $1}'); do
        local status
        status=$(qvm-ls 2>/dev/null | grep "^${vm}\s" | awk '{print $2}')
        echo "  $vm ($status)"
        found=true
    done
    
    if [ "$found" = false ]; then
        info "  No disposable VMs found"
    fi
}

# ============================================================================
# Command Functions
# ============================================================================

# Start command
cmd_start() {
    local vm_name
    vm_name=$(generate_vm_name)
    
    check_qubes
    check_disp_template
    check_netvm
    
    info "Starting disposable VM for Open-Omniscience"
    
    if ! create_disp_vm "$vm_name"; then
        exit 1
    fi
    
    # Start the VM
    if ! qvm-start "$vm_name" 2>&1; then
        error "Failed to start $vm_name"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Wait for VM to be ready
    info "Waiting for VM to be ready..."
    sleep 5
    
    # Run Open-Omniscience
    info "Starting Open-Omniscience in $vm_name"
    
    if ! run_in_disp_vm "$vm_name" "cd $INSTALL_DIR && python3 -m src.main"; then
        warning "Open-Omniscience may have failed to start"
    fi
    
    success "Disposable VM started: $vm_name"
    info "To connect: qvm-run -u $vm_name 'cd $INSTALL_DIR && python3 -m src.main'"
    info "To cleanup: ./qubes-disp-launcher.sh clean $vm_name"
}

# Run command
cmd_run() {
    local vm_name
    vm_name=$(generate_vm_name)
    
    if [ $# -lt 1 ]; then
        error "Usage: ./qubes-disp-launcher.sh run COMMAND [ARGS...]"
        exit 1
    fi
    
    check_qubes
    check_disp_template
    check_netvm
    
    info "Creating disposable VM to run command"
    
    if ! create_disp_vm "$vm_name"; then
        exit 1
    fi
    
    # Start the VM
    if ! qvm-start "$vm_name" 2>&1; then
        error "Failed to start $vm_name"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Wait for VM to be ready
    sleep 3
    
    # Run the command
    if ! run_in_disp_vm "$vm_name" "$*"; then
        error "Command failed"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Clean up
    cleanup_disp_vm "$vm_name"
    
    success "Command executed successfully"
}

# Exec command (run Python script)
cmd_exec() {
    local vm_name
    vm_name=$(generate_vm_name)
    
    if [ $# -lt 1 ]; then
        error "Usage: ./qubes-disp-launcher.sh exec SCRIPT [ARGS...]"
        exit 1
    fi
    
    check_qubes
    check_disp_template
    check_netvm
    
    local script="$1"
    shift
    
    info "Creating disposable VM to execute Python script: $script"
    
    if ! create_disp_vm "$vm_name"; then
        exit 1
    fi
    
    # Start the VM
    if ! qvm-start "$vm_name" 2>&1; then
        error "Failed to start $vm_name"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Wait for VM to be ready
    sleep 3
    
    # Run the script
    if ! run_in_disp_vm "$vm_name" "cd $INSTALL_DIR && python3 $script $*"; then
        error "Script execution failed"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Clean up
    cleanup_disp_vm "$vm_name"
    
    success "Script executed successfully"
}

# Shell command
cmd_shell() {
    local vm_name
    vm_name=$(generate_vm_name)
    
    check_qubes
    check_disp_template
    check_netvm
    
    info "Creating disposable VM with shell access"
    
    if ! create_disp_vm "$vm_name"; then
        exit 1
    fi
    
    # Start the VM
    if ! qvm-start "$vm_name" 2>&1; then
        error "Failed to start $vm_name"
        cleanup_disp_vm "$vm_name"
        exit 1
    fi
    
    # Wait for VM to be ready
    sleep 3
    
    success "Disposable VM ready: $vm_name"
    info "Starting shell in $vm_name"
    info "Type 'exit' to quit and auto-cleanup"
    
    # Open shell
    qvm-run -u "$vm_name" --skip-prepare xterm
    
    # Clean up after shell exits
    cleanup_disp_vm "$vm_name"
}

# Clean command
cmd_clean() {
    if [ $# -lt 1 ]; then
        # Clean all disposable VMs
        info "Cleaning all disposable VMs"
        
        for vm in $(qvm-ls 2>/dev/null | grep "^${DISP_PREFIX}-" | awk '{print $1}'); do
            cleanup_disp_vm "$vm"
        done
    else
        # Clean specific VMs
        for vm in "$@"; do
            if [[ "$vm" == ${DISP_PREFIX}* ]]; then
                cleanup_disp_vm "$vm"
            else
                error "Not a disposable VM: $vm"
            fi
        done
    fi
}

# List command
cmd_list() {
    check_qubes
    list_disp_vms
}

# ============================================================================
# Main
# ============================================================================

# Show help
show_help() {
    cat << EOF
Open-Omniscience Qubes Disposable VM Launcher v1.0.0

Usage: ./qubes-disp-launcher.sh COMMAND [OPTIONS]

Commands:
  start              Start a new disposable VM with Open-Omniscience
  run COMMAND        Run a command in a disposable VM
  exec SCRIPT        Execute a Python script in a disposable VM
  shell              Open a shell in a disposable VM
  clean [VM...]      Clean up disposable VMs (all or specified)
  list               List active disposable VMs
  help               Show this help message

Description:
  This script provides convenient access to Open-Omniscience in
  disposable VMs, which are automatically cleaned up after use.
  
  Disposable VMs are ideal for:
    - Testing and development
    - One-off tasks
    - Security-sensitive operations
    - Temporary analysis

Examples:
  # Start Open-Omniscience in a disposable VM
  ./qubes-disp-launcher.sh start
  
  # Run a command
  ./qubes-disp-launcher.sh run "python3 -c 'print(hello)'"
  
  # Execute a Python script
  ./qubes-disp-launcher.sh exec src/scripts/analyze.py input.txt
  
  # Open a shell
  ./qubes-disp-launcher.sh shell
  
  # List disposable VMs
  ./qubes-disp-launcher.sh list
  
  # Clean up all disposable VMs
  ./qubes-disp-launcher.sh clean
  
  # Clean up specific VM
  ./qubes-disp-launcher.sh clean open-omniscience-disp-12345678

Notes:
  - Disposable VMs are automatically removed after use
  - All changes in disposable VMs are lost when cleaned up
  - For persistent storage, use the main installer (qubes-installer.sh)
  - Requires Qubes OS R4.1+ with Debian Trixie (12)

EOF
}

# Parse arguments and execute command
if [ $# -lt 1 ]; then
    show_help
    exit 1
fi

command="$1"
shift

case "$command" in
    start)
        cmd_start "$@"
        ;;
    run)
        cmd_run "$@"
        ;;
    exec)
        cmd_exec "$@"
        ;;
    shell)
        cmd_shell "$@"
        ;;
    clean)
        cmd_clean "$@"
        ;;
    list)
        cmd_list "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        error "Unknown command: $command"
        show_help
        exit 1
        ;;
esac
