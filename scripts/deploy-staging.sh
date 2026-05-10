#!/bin/bash
# Open Omniscience Staging Deployment Script
# This script deploys the application to a staging environment

set -e

# Configuration
APP_NAME="Open Omniscience"
ENVIRONMENT="staging"
BRANCH="0.01"
DOCKER_COMPOSE_FILE="docker-compose.staging.yml"
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
    error "This script should NOT be run as root. Use a regular user with docker permissions."
    exit 1
fi

# Check if docker is available
if ! command -v docker &> /dev/null; then
    error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    error "docker-compose is not installed. Please install it first."
    exit 1
fi

# Check if git is available
if ! command -v git &> /dev/null; then
    error "Git is not installed. Please install Git first."
    exit 1
fi

# Function to check if a service is running
is_service_running() {
    local service_name=$1
    if docker-compose -f "$DOCKER_COMPOSE_FILE" ps | grep -q "$service_name.*Up"; then
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
        if docker-compose -f "$DOCKER_COMPOSE_FILE" ps | grep -q "$service_name.*healthy"; then
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
    log "Step 1/6: Pulling latest changes from branch $BRANCH..."
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    success "Latest changes pulled successfully"
    
    # Step 2: Create directories
    log "Step 2/6: Creating required directories..."
    mkdir -p data audit logs monitoring/grafana-provisioning/dashboards monitoring/grafana-provisioning/datasources
    success "Directories created"
    
    # Step 3: Build Docker images
    log "Step 3/6: Building Docker images..."
    docker-compose -f "$DOCKER_COMPOSE_FILE" build
    success "Docker images built successfully"
    
    # Step 4: Start services
    log "Step 4/6: Starting services..."
    docker-compose -f "$DOCKER_COMPOSE_FILE" up -d
    success "Services started"
    
    # Step 5: Wait for health checks
    log "Step 5/6: Waiting for services to become healthy..."
    wait_for_health "open-omniscience-web-staging"
    success "All services are healthy"
    
    # Step 6: Verify deployment
    log "Step 6/6: Verifying deployment..."
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
    echo "  - Metrics: http://localhost:8000/metrics"
    echo ""
    echo "Optional Services (if enabled):"
    echo "  - PostgreSQL: localhost:5433"
    echo "  - Redis: localhost:6380"
    echo "  - Traefik Dashboard: http://localhost:8081"
    echo "  - Prometheus: http://localhost:9090"
    echo "  - Grafana: http://localhost:3000"
    echo ""
    echo "Commands:"
    echo "  - View logs: docker-compose -f $DOCKER_COMPOSE_FILE logs -f"
    echo "  - Stop: docker-compose -f $DOCKER_COMPOSE_FILE down"
    echo "  - Restart: docker-compose -f $DOCKER_COMPOSE_FILE restart"
    echo ""
    echo "=========================================="
}

# Function to verify deployment
verify_deployment() {
    log "Verifying application health..."
    
    # Check if web service is running
    if ! is_service_running "open-omniscience-web-staging"; then
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
    
    # Test metrics endpoint
    log "Testing metrics endpoint..."
    attempt=1
    local metrics_healthy=false
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8000/metrics > /dev/null 2>&1; then
            metrics_healthy=true
            break
        fi
        sleep 3
        attempt=$((attempt + 1))
    done
    
    if [ "$metrics_healthy" = false ]; then
        warning "Metrics endpoint is not responding (Prometheus integration may not be working)"
    else
        success "Metrics endpoint is responding"
    fi
    
    return 0
}

# Function to run tests
run_tests() {
    log "Running tests..."
    
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
    
    # Check container resource usage
    log "Container resource usage:"
    docker stats --no-stream --format "table {{.Container}},{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}" 2>/dev/null || true
    
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
    docker-compose -f "$DOCKER_COMPOSE_FILE" ps
    echo ""
    
    log "Service logs (last 10 lines):"
    docker-compose -f "$DOCKER_COMPOSE_FILE" logs --tail=10
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
            docker-compose -f "$DOCKER_COMPOSE_FILE" down
            success "Services stopped"
            ;;
        7)
            log "Restarting services..."
            docker-compose -f "$DOCKER_COMPOSE_FILE" restart
            success "Services restarted"
            ;;
        8)
            log "Viewing logs (press Ctrl+C to exit)..."
            docker-compose -f "$DOCKER_COMPOSE_FILE" logs -f
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
