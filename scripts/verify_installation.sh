#!/bin/bash
#
# Open-Omniscience Installation Verification Script
# ================================================
#
# This script verifies that all components of Open-Omniscience are properly installed
# and functioning correctly.
#
# Usage: ./scripts/verify_installation.sh
#    or: bash scripts/verify_installation.sh
#
# Author: Open-Omniscience Team
# License: GPLv3
#

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# =============================================================================
# Utility Functions
# =============================================================================

# Print colored messages
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((WARNINGS++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1" >&2
    ((FAILED++))
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if command works
command_works() {
    "$1" >/dev/null 2>&1
}

# Print header
print_header() {
    echo ""
    echo "  ██████╗ ██████╗  ██████╗ ███╗   ██╗███████╗██╗   ██╗███╗   ██╗"
    echo "  ██╔══██╗██╔══██╗██╔═══██╗████╗  ██║██╔════╝██║   ██║████╗  ██║"
    echo "  ██████╔╝██████╔╝██║   ██║██╔██╗ ██║█████╗  ██║   ██║██╔██╗ ██║"
    echo "  ██╔═══╝ ██╔══██╗██║   ██║██║╚██╗██║██╔══╝  ╚██╗ ██╔╝██║╚██╗██║"
    echo "  ██║     ██║  ██║╚██████╔╝██║ ╚████║███████╗ ╚████╔╝ ██║ ╚████║"
    echo "  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝  ╚═══╝  ╚═╝  ╚═══╝"
    echo ""
    echo "  Open-Omniscience Installation Verification"
    echo "  =========================================="
    echo ""
}

# Print summary
print_summary() {
    echo ""
    echo "  =========================================="
    echo "  Verification Summary"
    echo "  =========================================="
    echo ""
    echo -e "  ${GREEN}Passed:   $PASSED${NC}"
    echo -e "  ${YELLOW}Warnings: $WARNINGS${NC}"
    echo -e "  ${RED}Failed:   $FAILED${NC}"
    echo ""
    
    if [ $FAILED -eq 0 ]; then
        echo -e "  ${GREEN}Overall Status: ALL CHECKS PASSED${NC}"
        echo ""
        echo "  Open-Omniscience is ready to use!"
        echo ""
        echo "  To start the application:"
        echo "    docker-compose up -d --build"
        echo ""
        echo "  Access at: http://localhost:8000"
        echo ""
        return 0
    else
        echo -e "  ${RED}Overall Status: SOME CHECKS FAILED${NC}"
        echo ""
        echo "  Please review the failures above and fix them."
        echo "  Some features may not work correctly."
        echo ""
        return 1
    fi
}

# =============================================================================
# Verification Functions
# =============================================================================

verify_docker() {
    log_info "Checking Docker..."
    
    if ! command_exists docker; then
        log_error "Docker is not installed"
        return 1
    fi
    
    if ! command_works "docker --version"; then
        log_error "Docker is installed but not working"
        return 1
    fi
    
    VERSION=$(docker --version 2>/dev/null)
    log_success "Docker: $VERSION"
    
    # Check if Docker daemon is running
    if ! command_works "docker info"; then
        log_error "Docker daemon is not running"
        return 1
    fi
    
    log_success "Docker daemon is running"
    return 0
}

verify_docker_compose() {
    log_info "Checking Docker Compose..."
    
    if ! command_exists docker-compose; then
        log_error "Docker Compose is not installed"
        return 1
    fi
    
    if ! command_works "docker-compose --version"; then
        log_error "Docker Compose is installed but not working"
        return 1
    fi
    
    VERSION=$(docker-compose --version 2>/dev/null)
    log_success "Docker Compose: $VERSION"
    return 0
}

verify_git() {
    log_info "Checking Git..."
    
    if ! command_exists git; then
        log_error "Git is not installed"
        return 1
    fi
    
    if ! command_works "git --version"; then
        log_error "Git is installed but not working"
        return 1
    fi
    
    VERSION=$(git --version 2>/dev/null)
    log_success "Git: $VERSION"
    return 0
}

verify_python() {
    log_info "Checking Python..."
    
    if ! command_exists python3; then
        log_error "Python 3 is not installed"
        return 1
    fi
    
    if ! command_works "python3 --version"; then
        log_error "Python 3 is installed but not working"
        return 1
    fi
    
    VERSION=$(python3 --version 2>/dev/null)
    log_success "Python: $VERSION"
    
    # Check Python version
    if ! python3 -c "import sys; assert sys.version_info >= (3, 8)" 2>/dev/null; then
        log_error "Python 3.8 or higher is required"
        return 1
    fi
    
    log_success "Python version is compatible (>= 3.8)"
    return 0
}

verify_pip() {
    log_info "Checking pip..."
    
    if ! command_works "python3 -m pip --version"; then
        log_error "pip is not working"
        return 1
    fi
    
    VERSION=$(python3 -m pip --version 2>/dev/null)
    log_success "pip: $VERSION"
    return 0
}

verify_repository() {
    log_info "Checking repository..."
    
    if [ ! -d ".git" ]; then
        log_error "Not in a Git repository"
        return 1
    fi
    
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    REMOTE=$(git config --get remote.origin.url 2>/dev/null || echo "unknown")
    
    log_success "Repository: $BRANCH"
    log_success "Remote: $REMOTE"
    return 0
}

verify_python_dependencies() {
    log_info "Checking Python dependencies..."
    
    # Check if virtual environment exists
    if [ ! -d "venv" ]; then
        log_warning "Virtual environment not found (venv directory missing)"
        return 0
    fi
    
    # Activate virtual environment
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
    
    # Check core dependencies
    local missing_deps=0
    
    for dep in fastapi sqlalchemy beautifulsoup4 requests httpx python-dotenv; do
        if ! python3 -c "import $dep" 2>/dev/null; then
            log_error "Missing dependency: $dep"
            missing_deps=$((missing_deps + 1))
        fi
    done
    
    if [ $missing_deps -eq 0 ]; then
        log_success "All core Python dependencies are installed"
    fi
    
    return 0
}

verify_llm_dependencies() {
    log_info "Checking LLM dependencies..."
    
    # Activate virtual environment if available
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
    
    # Check LLM dependencies
    local missing_llm_deps=0
    
    for dep in ollama sentence-transformers; do
        if ! python3 -c "import $dep" 2>/dev/null; then
            log_warning "Missing LLM dependency: $dep (LLM features will be limited)"
            missing_llm_deps=$((missing_llm_deps + 1))
        fi
    done
    
    if [ $missing_llm_deps -eq 0 ]; then
        log_success "All LLM Python dependencies are installed"
    fi
    
    return 0
}

verify_ollama() {
    log_info "Checking Ollama..."
    
    if ! command_exists ollama; then
        log_warning "Ollama is not installed (LLM features will be limited)"
        return 0
    fi
    
    if ! command_works "ollama --version"; then
        log_warning "Ollama is installed but not working (LLM features will be limited)"
        return 0
    fi
    
    VERSION=$(ollama --version 2>/dev/null)
    log_success "Ollama: $VERSION"
    
    # Check if Ollama server is running
    if command_works "curl -s http://localhost:11434/api/tags"; then
        log_success "Ollama server is running"
    else
        log_warning "Ollama server is not running (start with: ollama serve)"
    fi
    
    return 0
}

verify_docker_images() {
    log_info "Checking Docker images..."
    
    # Check if images are built or available
    if command_works "docker images | grep -q open-omniscience"; then
        log_success "Open-Omniscience Docker images are available"
    else
        log_warning "Open-Omniscience Docker images not built yet"
        log_info "  Run: docker-compose build"
    fi
    
    return 0
}

verify_environment_files() {
    log_info "Checking environment configuration..."
    
    # Check for .env file
    if [ ! -f ".env" ]; then
        log_warning ".env file not found (copy from .env.example)"
    else
        log_success ".env file exists"
    fi
    
    # Check for data directories
    for dir in data audit logs; do
        if [ ! -d "$dir" ]; then
            log_warning "Directory missing: $dir"
        else
            log_success "Directory exists: $dir"
        fi
    done
    
    # Check for configs
    if [ ! -d "configs" ]; then
        log_warning "configs directory not found"
    else
        log_success "configs directory exists"
    fi
    
    return 0
}

verify_port_availability() {
    log_info "Checking port availability..."
    
    # Check if port 8000 is available
    if command_works "nc -z localhost 8000" 2>/dev/null; then
        log_warning "Port 8000 is already in use"
    else
        log_success "Port 8000 is available"
    fi
    
    # Check if port 11434 is available (Ollama default)
    if command_works "nc -z localhost 11434" 2>/dev/null; then
        log_warning "Port 11434 is already in use"
    else
        log_success "Port 11434 is available"
    fi
    
    return 0
}

# =============================================================================
# Main Verification
# =============================================================================

main() {
    print_header
    
    # Run all verification checks
    verify_docker
    verify_docker_compose
    verify_git
    verify_python
    verify_pip
    verify_repository
    verify_python_dependencies
    verify_llm_dependencies
    verify_ollama
    verify_docker_images
    verify_environment_files
    verify_port_availability
    
    # Print summary
    print_summary
    
    # Exit with appropriate code
    if [ $FAILED -gt 0 ]; then
        exit 1
    fi
}

# Run main function
main "$@"
