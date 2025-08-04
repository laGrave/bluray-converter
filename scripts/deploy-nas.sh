#!/bin/bash
# BluRay Converter - NAS Deployment Script
# Deploys and starts services on Synology NAS

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NAS_SERVICES_DIR="$PROJECT_ROOT/nas-services"
ENV_FILE="$NAS_SERVICES_DIR/.env"

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check if docker-compose is available
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        error "Docker Compose is not available. Please install Docker Compose."
        exit 1
    fi
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/bluray-converter-spec.md" ]]; then
        error "Script must be run from the project root or scripts directory."
        exit 1
    fi
    
    success "Prerequisites check passed"
}

# Function to validate environment file
validate_environment() {
    log "Validating environment configuration..."
    
    if [[ ! -f "$ENV_FILE" ]]; then
        error "Environment file not found: $ENV_FILE"
        echo "Please copy .env.example to .env and configure it:"
        echo "  cp $NAS_SERVICES_DIR/.env.example $ENV_FILE"
        echo "  nano $ENV_FILE"
        exit 1
    fi
    
    # Check required variables
    source "$ENV_FILE"
    required_vars=(
        "MAC_MINI_IP"
        "NAS_IP" 
        "NAS_PORT"
        "MOVIES_BASE_PATH"
        "BLURAY_RAW_FOLDER"
        "BLURAY_PROCESSED_FOLDER"
        "BLURAY_TEMP_FOLDER"
    )
    
    missing_vars=()
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        error "Missing required environment variables:"
        printf '%s\n' "${missing_vars[@]}"
        echo "Please configure them in $ENV_FILE"
        exit 1
    fi
    
    success "Environment validation passed"
}

# Function to create necessary directories
create_directories() {
    log "Creating necessary directories..."
    
    # Create volume directories
    mkdir -p "$NAS_SERVICES_DIR/volumes/db"
    mkdir -p "$NAS_SERVICES_DIR/volumes/logs"
    
    # Create movie directories (if they don't exist)
    if [[ -n "$MOVIES_BASE_PATH" ]]; then
        sudo mkdir -p "$MOVIES_BASE_PATH/$BLURAY_RAW_FOLDER"
        sudo mkdir -p "$MOVIES_BASE_PATH/$BLURAY_PROCESSED_FOLDER"
        sudo mkdir -p "$MOVIES_BASE_PATH/$BLURAY_TEMP_FOLDER"
        
        # Set proper permissions for movie directories
        sudo chmod 755 "$MOVIES_BASE_PATH"
        sudo chmod 775 "$MOVIES_BASE_PATH/$BLURAY_RAW_FOLDER"
        sudo chmod 775 "$MOVIES_BASE_PATH/$BLURAY_PROCESSED_FOLDER"
        sudo chmod 775 "$MOVIES_BASE_PATH/$BLURAY_TEMP_FOLDER"
    fi
    
    success "Directories created successfully"
}

# Function to test connectivity
test_connectivity() {
    log "Testing network connectivity..."
    
    # Test Mac mini connectivity
    if [[ -n "$MAC_MINI_IP" ]]; then
        if ping -c 1 -W 5 "$MAC_MINI_IP" &> /dev/null; then
            success "Mac mini ($MAC_MINI_IP) is reachable"
        else
            warning "Mac mini ($MAC_MINI_IP) is not reachable. Services may fail to communicate."
        fi
    fi
    
    # Test Telegram bot (if configured)
    if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
        if curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe" | grep -q '"ok":true'; then
            success "Telegram bot token is valid"
        else
            warning "Telegram bot token appears invalid or network issue"
        fi
    fi
}

# Function to build and start services
deploy_services() {
    log "Building and starting NAS services..."
    
    cd "$NAS_SERVICES_DIR"
    
    # Pull latest images
    log "Pulling latest base images..."
    if command -v docker-compose &> /dev/null; then
        docker-compose pull
    else
        docker compose pull
    fi
    
    # Build services
    log "Building services..."
    if command -v docker-compose &> /dev/null; then
        docker-compose build --no-cache
    else
        docker compose build --no-cache
    fi
    
    # Start services
    log "Starting services..."
    if command -v docker-compose &> /dev/null; then
        docker-compose up -d
    else
        docker compose up -d
    fi
    
    success "Services started successfully"
}

# Function to wait for services to be ready
wait_for_services() {
    log "Waiting for services to be ready..."
    
    local max_attempts=30
    local attempt=0
    
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -s "http://localhost:${NAS_PORT:-8080}/api/health" | grep -q "healthy"; then
            success "API service is ready"
            break
        fi
        
        ((attempt++))
        if [[ $attempt -eq $max_attempts ]]; then
            error "API service failed to start within timeout"
            show_logs
            exit 1
        fi
        
        echo -n "."
        sleep 2
    done
    
    # Check web UI
    if curl -s "http://localhost:${WEB_UI_PORT:-8081}" | grep -q "BluRay Converter"; then
        success "Web UI is ready"
    else
        warning "Web UI may not be fully ready"
    fi
}

# Function to show service status
show_status() {
    log "Service status:"
    
    cd "$NAS_SERVICES_DIR"
    if command -v docker-compose &> /dev/null; then
        docker-compose ps
    else
        docker compose ps
    fi
    
    echo
    log "Access points:"
    echo "  Web UI: http://$(hostname -I | awk '{print $1}'):${WEB_UI_PORT:-8081}"
    echo "  API: http://$(hostname -I | awk '{print $1}'):${NAS_PORT:-8080}/api"
    echo "  Health Check: http://$(hostname -I | awk '{print $1}'):${NAS_PORT:-8080}/api/health"
}

# Function to show logs
show_logs() {
    log "Recent service logs:"
    cd "$NAS_SERVICES_DIR"
    if command -v docker-compose &> /dev/null; then
        docker-compose logs --tail=50
    else
        docker compose logs --tail=50
    fi
}

# Function to run post-deployment tests
run_tests() {
    log "Running post-deployment tests..."
    
    # Test API endpoints
    local api_url="http://localhost:${NAS_PORT:-8080}/api"
    
    # Health check
    if curl -s "$api_url/health" | grep -q "healthy"; then
        success "✓ Health check passed"
    else
        error "✗ Health check failed"
    fi
    
    # Get tasks endpoint
    if curl -s "$api_url/tasks" | grep -q "\[\]"; then
        success "✓ Tasks API accessible"
    else
        warning "✗ Tasks API may have issues"
    fi
    
    log "Test scan (dry run)..."
    if curl -s -X POST "$api_url/tasks/scan" -H "Content-Type: application/json" -d '{"dry_run": true}' | grep -q "scan"; then
        success "✓ Scan endpoint working"
    else
        warning "✗ Scan endpoint may have issues"
    fi
}

# Function to show usage instructions
show_usage() {
    cat << EOF

${GREEN}=== BluRay Converter NAS Deployment Complete ===${NC}

The following services are now running:
  - API Server (Port ${NAS_PORT:-8080})
  - Web UI (Port ${WEB_UI_PORT:-8081})
  - Directory Watcher
  - Task Scheduler

Next steps:
1. Verify that Mac mini worker is deployed and running
2. Test the connection between NAS and Mac mini
3. Place a BluRay movie in: $MOVIES_BASE_PATH/$BLURAY_RAW_FOLDER
4. Check the Web UI for processing status

Useful commands:
  - View logs: cd $NAS_SERVICES_DIR && docker-compose logs -f
  - Restart services: cd $NAS_SERVICES_DIR && docker-compose restart
  - Stop services: cd $NAS_SERVICES_DIR && docker-compose down
  - Update services: cd $NAS_SERVICES_DIR && docker-compose pull && docker-compose up -d

EOF
}

# Main deployment function
main() {
    echo -e "${BLUE}"
    cat << "EOF"
 ____  _       ____             ____                          _            
| __ )| |_   _|  _ \ __ _ _   _ / ___|___  _ ____   _____ _ __| |_ ___ _ __ 
|  _ \| | | | | |_) / _` | | | | |   / _ \| '_ \ \ / / _ \ '__| __/ _ \ '__|
| |_) | | |_| |  _ < (_| | |_| | |__| (_) | | | \ V /  __/ |  | ||  __/ |   
|____/|_|\__,_|_| \_\__,_|\__, |\____\___/|_| |_|\_/ \___|_|   \__\___|_|   
                          |___/                                            
             NAS Deployment Script
EOF
    echo -e "${NC}"
    
    check_prerequisites
    validate_environment
    create_directories
    test_connectivity
    deploy_services
    wait_for_services
    show_status
    run_tests
    show_usage
    
    success "NAS deployment completed successfully!"
}

# Handle script arguments
case "${1:-}" in
    "logs")
        show_logs
        exit 0
        ;;
    "status")
        show_status
        exit 0
        ;;
    "test")
        run_tests
        exit 0
        ;;
    "help"|"-h"|"--help")
        cat << EOF
Usage: $0 [command]

Commands:
  (no args)  - Full deployment
  logs       - Show service logs
  status     - Show service status
  test       - Run deployment tests
  help       - Show this help message

EOF
        exit 0
        ;;
esac

# Run main deployment
main "$@"