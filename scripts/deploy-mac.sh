#!/bin/bash
# BluRay Converter - Mac Deployment Script  
# Deploys and starts worker service on Mac mini (Apple Silicon)

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
MAC_SERVICES_DIR="$PROJECT_ROOT/mac-services"
ENV_FILE="$MAC_SERVICES_DIR/.env"
MOUNT_POINT="/tmp/bluray-converter-nas"

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
    
    # Check if we're on macOS
    if [[ "$(uname)" != "Darwin" ]]; then
        error "This script is designed for macOS only."
        exit 1
    fi
    
    # Check for Apple Silicon
    if [[ "$(uname -m)" == "arm64" ]]; then
        success "Running on Apple Silicon (ARM64)"
    else
        warning "Not running on Apple Silicon. FFmpeg performance may be suboptimal."
    fi
    
    # Check if Docker Desktop is installed
    if ! command -v docker &> /dev/null; then
        error "Docker Desktop is not installed. Please install Docker Desktop for Mac."
        echo "Download from: https://docs.docker.com/desktop/install/mac-install/"
        exit 1
    fi
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        error "Docker Desktop is not running. Please start Docker Desktop."
        exit 1
    fi
    
    # Check if docker-compose is available
    if ! docker compose version &> /dev/null && ! command -v docker-compose &> /dev/null; then
        error "Docker Compose is not available."
        exit 1
    fi
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/bluray-converter-spec.md" ]]; then
        error "Script must be run from the project root or scripts directory."
        exit 1
    fi
    
    # Check if FFmpeg is available (will be installed in Docker)
    if command -v ffmpeg &> /dev/null; then
        local ffmpeg_version=$(ffmpeg -version 2>&1 | head -n1)
        success "FFmpeg found locally: $ffmpeg_version"
    else
        log "FFmpeg will be installed in Docker container"
    fi
    
    # Check available disk space
    local available_space=$(df -h "$HOME" | awk 'NR==2 {print $4}')
    log "Available disk space: $available_space"
    
    success "Prerequisites check passed"
}

# Function to validate environment file
validate_environment() {
    log "Validating environment configuration..."
    
    if [[ ! -f "$ENV_FILE" ]]; then
        error "Environment file not found: $ENV_FILE"
        echo "Please copy .env.example to .env and configure it:"
        echo "  cp $MAC_SERVICES_DIR/.env.example $ENV_FILE"
        echo "  nano $ENV_FILE"
        exit 1
    fi
    
    # Check required variables
    source "$ENV_FILE"
    required_vars=(
        "NAS_IP"
        "NAS_API_PORT"
        "WORKER_PORT"
        "SMB_USERNAME"
        "SMB_PASSWORD"
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

# Function to test NAS connectivity
test_nas_connectivity() {
    log "Testing NAS connectivity..."
    
    # Test basic network connectivity
    if ping -c 1 -W 5 "$NAS_IP" &> /dev/null; then
        success "NAS ($NAS_IP) is reachable"
    else
        error "NAS ($NAS_IP) is not reachable. Check network connection."
        exit 1
    fi
    
    # Test NAS API
    local nas_api_url="http://$NAS_IP:$NAS_API_PORT/api/health"
    if curl -s --connect-timeout 10 "$nas_api_url" | grep -q "healthy"; then
        success "NAS API is responding"
    else
        warning "NAS API is not responding. Make sure NAS services are running."
    fi
    
    # Test SMB share accessibility
    log "Testing SMB share accessibility..."
    if command -v smbutil &> /dev/null; then
        # Try to list SMB shares
        if smbutil view "//$NAS_IP" 2>/dev/null | grep -q "video\|share"; then
            success "SMB shares are accessible"
        else
            warning "SMB shares may not be accessible or configured correctly"
        fi
    fi
}

# Function to setup SMB mount point
setup_mount_point() {
    log "Setting up SMB mount point..."
    
    # Create mount point directory
    mkdir -p "$MOUNT_POINT"
    
    # Check if already mounted
    if mount | grep -q "$MOUNT_POINT"; then
        log "NAS is already mounted at $MOUNT_POINT"
        return
    fi
    
    success "Mount point prepared: $MOUNT_POINT"
}

# Function to test SMB mounting
test_smb_mount() {
    log "Testing SMB mount functionality..."
    
    # This is a test mount - actual mounting happens in the Docker container
    local test_mount_point="/tmp/bluray-test-mount"
    mkdir -p "$test_mount_point"
    
    # Try to mount temporarily for testing
    if mount -t smbfs "//$SMB_USERNAME:$SMB_PASSWORD@$NAS_IP/video" "$test_mount_point" 2>/dev/null; then
        success "SMB mount test successful"
        # Unmount test mount
        umount "$test_mount_point" 2>/dev/null || true
        rmdir "$test_mount_point" 2>/dev/null || true
    else
        warning "SMB mount test failed. Check credentials and share configuration."
        warning "This may still work within the Docker container."
    fi
}

# Function to create necessary directories
create_directories() {
    log "Creating necessary directories..."
    
    # Create volume directories
    mkdir -p "$MAC_SERVICES_DIR/volumes/logs"
    
    success "Directories created successfully"
}

# Function to build and start services
deploy_services() {
    log "Building and starting Mac worker service..."
    
    cd "$MAC_SERVICES_DIR"
    
    # Pull latest images
    log "Pulling latest base images..."
    if command -v docker-compose &> /dev/null; then
        docker-compose pull
    else
        docker compose pull
    fi
    
    # Build services
    log "Building worker service (this may take a while for ARM64)..."
    if command -v docker-compose &> /dev/null; then
        docker-compose build --no-cache
    else
        docker compose build --no-cache
    fi
    
    # Start services
    log "Starting worker service..."
    if command -v docker-compose &> /dev/null; then
        docker-compose up -d
    else
        docker compose up -d
    fi
    
    success "Worker service started successfully"
}

# Function to wait for services to be ready
wait_for_services() {
    log "Waiting for worker service to be ready..."
    
    local max_attempts=30
    local attempt=0
    
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -s "http://localhost:${WORKER_PORT:-8000}/api/health" | grep -q "healthy"; then
            success "Worker service is ready"
            break
        fi
        
        ((attempt++))
        if [[ $attempt -eq $max_attempts ]]; then
            error "Worker service failed to start within timeout"
            show_logs
            exit 1
        fi
        
        echo -n "."
        sleep 2
    done
}

# Function to show service status
show_status() {
    log "Service status:"
    
    cd "$MAC_SERVICES_DIR"
    if command -v docker-compose &> /dev/null; then
        docker-compose ps
    else
        docker compose ps
    fi
    
    echo
    log "Access points:"
    echo "  Worker API: http://localhost:${WORKER_PORT:-8000}/api"
    echo "  Health Check: http://localhost:${WORKER_PORT:-8000}/api/health"
}

# Function to show logs
show_logs() {
    log "Recent service logs:"
    cd "$MAC_SERVICES_DIR"
    if command -v docker-compose &> /dev/null; then
        docker-compose logs --tail=50
    else
        docker compose logs --tail=50
    fi
}

# Function to run post-deployment tests
run_tests() {
    log "Running post-deployment tests..."
    
    # Test worker API endpoints
    local worker_url="http://localhost:${WORKER_PORT:-8000}/api"
    
    # Health check
    if curl -s "$worker_url/health" | grep -q "healthy"; then
        success "✓ Worker health check passed"
    else
        error "✗ Worker health check failed"
    fi
    
    # Test FFmpeg availability in container
    log "Testing FFmpeg in container..."
    local container_name=$(docker-compose ps -q worker 2>/dev/null || docker compose ps -q worker 2>/dev/null)
    if [[ -n "$container_name" ]]; then
        if docker exec "$container_name" ffmpeg -version &>/dev/null; then
            success "✓ FFmpeg is available in container"
        else
            error "✗ FFmpeg is not available in container"
        fi
    fi
    
    # Test connectivity to NAS from container  
    log "Testing NAS connectivity from container..."
    if [[ -n "$container_name" ]]; then
        if docker exec "$container_name" ping -c 1 "$NAS_IP" &>/dev/null; then
            success "✓ Container can reach NAS"
        else
            warning "✗ Container cannot reach NAS"
        fi
    fi
}

# Function to show usage instructions
show_usage() {
    cat << EOF

${GREEN}=== BluRay Converter Mac Worker Deployment Complete ===${NC}

The Mac worker service is now running on port ${WORKER_PORT:-8000}

Service capabilities:
  - BluRay BDMV analysis and processing
  - FFmpeg-based video conversion (remux)
  - SMB mounting for NAS access
  - Webhook status reporting to NAS

Next steps:
1. Verify that NAS services are running and can reach this Mac
2. Test the complete workflow by placing a BluRay in the NAS raw folder
3. Monitor logs to ensure proper communication between services

Useful commands:
  - View logs: cd $MAC_SERVICES_DIR && docker-compose logs -f worker
  - Restart service: cd $MAC_SERVICES_DIR && docker-compose restart
  - Stop service: cd $MAC_SERVICES_DIR && docker-compose down
  - Update service: cd $MAC_SERVICES_DIR && docker-compose pull && docker-compose up -d

System Information:
  - Architecture: $(uname -m)
  - Available Memory: $(system_profiler SPHardwareDataType | grep "Memory:" | awk '{print $2 " " $3}')
  - Available Storage: $(df -h "$HOME" | awk 'NR==2 {print $4}')

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
             Mac Worker Deployment Script
EOF
    echo -e "${NC}"
    
    check_prerequisites
    validate_environment
    test_nas_connectivity
    setup_mount_point
    test_smb_mount
    create_directories
    deploy_services
    wait_for_services
    show_status
    run_tests
    show_usage
    
    success "Mac worker deployment completed successfully!"
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
    "mount-test")
        test_smb_mount
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
  mount-test - Test SMB mounting
  help       - Show this help message

EOF
        exit 0
        ;;
esac

# Run main deployment
main "$@"