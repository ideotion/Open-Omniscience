#!/bin/bash
# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com


# Open Omniscience Staging Deployment Script
# This script deploys the application to a staging environment using direct Python installation

set -e

# Configuration
APP_NAME="Open Omniscience"
ENVIRONMENT="staging"
BRANCH="0.03"
LOG_FILE="/tmp/open-omniscience-staging-deploy-$(date +%Y%m%d-%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Check if running as root
if [ "$(id -u)" -eq 0 ]; then
    error "This script should NOT be run as root. Use a regular user."
    exit 1
fi

# Check if python3 is available
if ! command -v python3 &> /dev/null; then
    error "Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Check if git is available
if ! command -v git &> /dev/null; then
    error "Git is not installed. Please install Git first."
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    error "pip is not installed. Please install pip first."
    exit 1
fi

# Function to check if a process is running
is_process_running() {
    local process_name=$1
    if pgrep -f "$process_name" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Function to wait for service health
wait_for_health() {
    local service_name=$1
    local max_attempts=30
    local attempt=1
    
    log "Waiting for $service_name to be healthy..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
            success "$service_name is healthy!"
            return 0
        fi
        
        if [ $((attempt % 5)) -eq 0 ]; then
            log "Still waiting for $service_name... (attempt $attempt/$max_attempts)"
        fi
        
        sleep 2
        attempt=$((attempt + 1))
    done
    
    error "$service_name did not become healthy after $max_attempts attempts"
    return 1
}

# Main deployment function
deploy() {
    log "Starting $APP_NAME staging deployment..."
    
    # Step 1: Pull latest changes
    log "Step 1/5: Pulling latest changes from branch $BRANCH..."
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    success "Latest changes pulled successfully"
    
    # Step 2: Create directories
    log "Step 2/5: Creating required directories..."
    mkdir -p data audit logs
    success "Directories created"
    
    # Step 3: Install Python dependencies
    log "Step 3/5: Installing Python dependencies..."
    if [ ! -d "venv" ]; then
        log "Creating virtual environment..."
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    pip install --upgrade pip
    pip install -q -r requirements.txt
    success "Python dependencies installed"
    
    # Step 4: Start services
    log "Step 4/5: Starting services..."
    # Start with Gunicorn in background
    nohup venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app > /tmp/open-omniscience-staging.log 2>&1 &
    success "Services started"
    
    # Step 5: Wait for health checks
    log "Step 5/5: Waiting for services to become healthy..."
    wait_for_health "Open-Omniscience"
    success "All services are healthy"
    
    # Verify deployment
    log "Verifying deployment..."
    verify_deployment
    
    success "$APP_NAME staging deployment completed successfully!"
    echo ""
    echo "=========================================="
    echo "Deployment Summary"
    echo "=========================================="
    echo ""
    echo "Application: $APP_NAME"
    echo "Environment: $ENVIRONMENT"
    echo "Branch: $BRANCH"
    echo ""
    echo "Access Points:"
    echo "  - Web Interface: http://localhost:8000"
    echo "  - API: http://localhost:8000/api/"
    echo ""
    echo "Commands:"
    echo "  - View logs: tail -f /tmp/open-omniscience-staging.log"
    echo "  - Stop: pkill -f gunicorn"
    echo "  - Restart: pkill -f gunicorn && nohup venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app > /tmp/open-omniscience-staging.log 2>&1 &"
    echo ""
    echo "=========================================="
}

# Function to verify deployment
verify_deployment() {
    log "Verifying application health..."
    
    # Check if web service is running
    if ! is_process_running "gunicorn"; then
        error "Web service is not running"
        return 1
    fi
    
    # Test API endpoint
    log "Testing API endpoint..."
    local max_attempts=10
    local attempt=1
    local api_healthy=false
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8000/api/sources > /dev/null 2>&1; then
            api_healthy=true
            break
        fi
        sleep 3
        attempt=$((attempt + 1))
    done
    
    if [ "$api_healthy" = false ]; then
        error "API endpoint is not responding after $max_attempts attempts"
        return 1
    fi
    
    success "API endpoint is responding"
    return 0
}

# Function to run tests
run_tests() {
    log "Running tests..."
    
    source venv/bin/activate
    
    # Run Python tests
    if [ -f "requirements.txt" ]; then
        log "Installing test dependencies..."
        pip install -q pytest pytest-mock 2>&1 | tail -5 || true
        
        log "Running pytest..."
        if python -m pytest tests/ -v --tb=short 2>&1 | tee -a "$LOG_FILE"; then
            success "All tests passed"
        else
            warning "Some tests failed. Check $LOG_FILE for details."
        fi
    else
        warning "No requirements.txt found, skipping Python tests"
    fi
    
    # Test API endpoints
    log "Testing API endpoints..."
    
    local endpoints=(
        "/api/sources"
        "/api/articles"
        "/api/articles?limit=1"
    )
    
    for endpoint in "${endpoints[@]}"; do
        log "Testing $endpoint..."
        if curl -s "http://localhost:8000$endpoint" > /dev/null 2>&1; then
            success "$endpoint - OK"
        else
            error "$endpoint - FAILED"
        fi
    done
}

# Function to monitor performance
monitor_performance() {
    log "Monitoring performance..."
    
    # Check process resource usage
    log "Process resource usage:"
    ps aux | grep -E "gunicorn|uvicorn|python" | grep -v grep | awk '{print $2, $3, $4, $11}' || true
    
    # Check disk usage
    log "Disk usage:"
    df -h . 2>/dev/null | tail -1 || true
    
    # Check log files
    log "Log files:"
    ls -lh audit/ logs/ 2>/dev/null || true
}

# Function to show status
show_status() {
    log "Current status:"
    if is_process_running "gunicorn"; then
        echo "  ✅ Gunicorn is running"
        ps aux | grep gunicorn | grep -v grep
    else
        echo "  ❌ Gunicorn is not running"
    fi
    echo ""
    
    log "Service logs (last 10 lines):"
    tail -10 /tmp/open-omniscience-staging.log 2>/dev/null || echo "  No log file found"
}

# Main menu
main() {
    echo ""
    echo "=========================================="
    echo "$APP_NAME Staging Deployment"
    echo "=========================================="
    echo ""
    echo "Options:"
    echo "  1. Deploy to staging"
    echo "  2. Verify deployment"
    echo "  3. Run tests"
    echo "  4. Monitor performance"
    echo "  5. Show status"
    echo "  6. Stop services"
    echo "  7. Restart services"
    echo "  8. View logs"
    echo "  9. Exit"
    echo ""
    
    read -p "Select an option (1-9): " option
    
    case $option in
        1)
            deploy
            ;;
        2)
            verify_deployment
            ;;
        3)
            run_tests
            ;;
        4)
            monitor_performance
            ;;
        5)
            show_status
            ;;
        6)
            log "Stopping services..."
            pkill -f gunicorn
            success "Services stopped"
            ;;
        7)
            log "Restarting services..."
            pkill -f gunicorn
            sleep 2
            nohup venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app > /tmp/open-omniscience-staging.log 2>&1 &
            success "Services restarted"
            ;;
        8)
            log "Viewing logs (press Ctrl+C to exit)..."
            tail -f /tmp/open-omniscience-staging.log
            ;;
        9)
            log "Exiting..."
            exit 0
            ;;
        *)
            error "Invalid option: $option"
            ;;
    esac
    
    echo ""
    main
}

# Start main menu
main
