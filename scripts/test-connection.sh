#!/bin/bash
# BluRay Converter - Connection Test Script
# Tests network connectivity between NAS and Mac mini

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

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

# Function to load environment variables
load_env() {
    # Try to load from nas-services first
    if [[ -f "$PROJECT_ROOT/nas-services/.env" ]]; then
        source "$PROJECT_ROOT/nas-services/.env"
        success "Loaded NAS environment configuration"
    fi
    
    # Also try to load mac-services env if exists
    if [[ -f "$PROJECT_ROOT/mac-services/.env" ]]; then
        source "$PROJECT_ROOT/mac-services/.env"
        success "Loaded Mac environment configuration"
    fi
    
    # Check if we have required variables
    if [[ -z "$NAS_IP" && -z "$MAC_MINI_IP" ]]; then
        error "No environment configuration found. Please configure .env files first."
        exit 1
    fi
}

# Function to test basic network connectivity
test_network_connectivity() {
    log "Testing basic network connectivity..."
    
    local targets=()
    [[ -n "$NAS_IP" ]] && targets+=("$NAS_IP (NAS)")
    [[ -n "$MAC_MINI_IP" ]] && targets+=("$MAC_MINI_IP (Mac mini)")
    
    for target in "${targets[@]}"; do
        local ip=$(echo "$target" | cut -d' ' -f1)
        local name=$(echo "$target" | cut -d' ' -f2-)
        
        if ping -c 3 -W 5 "$ip" &> /dev/null; then
            success "$name is reachable"
        else
            error "$name is NOT reachable"
        fi
    done
}

# Function to test API endpoints
test_api_endpoints() {
    log "Testing API endpoints..."
    
    # Test NAS API
    if [[ -n "$NAS_IP" && -n "$NAS_PORT" ]]; then
        local nas_api_url="http://$NAS_IP:$NAS_PORT/api/health"
        if curl -s --connect-timeout 10 "$nas_api_url" | grep -q "healthy"; then
            success "NAS API is responding"
        else
            error "NAS API is not responding at $nas_api_url"
        fi
    fi
    
    # Test Mac worker API
    if [[ -n "$MAC_MINI_IP" && -n "$WORKER_PORT" ]]; then
        local mac_api_url="http://$MAC_MINI_IP:$WORKER_PORT/api/health"
        if curl -s --connect-timeout 10 "$mac_api_url" | grep -q "healthy"; then
            success "Mac worker API is responding"
        else
            error "Mac worker API is not responding at $mac_api_url"
        fi
    fi
}

# Function to test SMB connectivity
test_smb_connectivity() {
    log "Testing SMB connectivity..."
    
    if [[ -z "$NAS_IP" ]]; then
        warning "NAS_IP not configured, skipping SMB test"
        return
    fi
    
    # Test if SMB port is open
    if nc -z -w5 "$NAS_IP" 445 2>/dev/null; then
        success "SMB port (445) is open on NAS"
        
        # Try to list SMB shares if smbutil is available (macOS)
        if command -v smbutil &> /dev/null; then
            if smbutil view "//$NAS_IP" 2>/dev/null | grep -q "share\|video"; then
                success "SMB shares are accessible"
            else
                warning "SMB shares may not be properly configured"
            fi
        fi
    else
        error "SMB port (445) is not accessible on NAS"
    fi
}

# Function to test Docker services
test_docker_services() {
    log "Testing Docker services..."
    
    # Test NAS services
    if [[ -d "$PROJECT_ROOT/nas-services" ]]; then
        cd "$PROJECT_ROOT/nas-services"
        if command -v docker-compose &> /dev/null; then
            local nas_status=$(docker-compose ps --services --filter status=running 2>/dev/null | wc -l)
        else
            local nas_status=$(docker compose ps --services --filter status=running 2>/dev/null | wc -l)
        fi
        
        if [[ $nas_status -gt 0 ]]; then
            success "NAS services are running ($nas_status containers)"
        else
            warning "NAS services are not running"
        fi
    fi
    
    # Test Mac services
    if [[ -d "$PROJECT_ROOT/mac-services" ]]; then
        cd "$PROJECT_ROOT/mac-services"
        if command -v docker-compose &> /dev/null; then
            local mac_status=$(docker-compose ps --services --filter status=running 2>/dev/null | wc -l)
        else
            local mac_status=$(docker compose ps --services --filter status=running 2>/dev/null | wc -l)
        fi
        
        if [[ $mac_status -gt 0 ]]; then
            success "Mac services are running ($mac_status containers)"
        else
            warning "Mac services are not running"
        fi
    fi
}

# Function to test end-to-end workflow
test_workflow() {
    log "Testing end-to-end workflow..."
    
    # Test scan endpoint
    if [[ -n "$NAS_IP" && -n "$NAS_PORT" ]]; then
        local scan_url="http://$NAS_IP:$NAS_PORT/api/tasks/scan"
        local scan_payload='{"dry_run": true, "source": "connection_test"}'
        
        if curl -s -X POST "$scan_url" -H "Content-Type: application/json" -d "$scan_payload" | grep -q "scan"; then
            success "Scan endpoint is working"
        else
            warning "Scan endpoint may have issues"
        fi
    fi
    
    # Test task retrieval
    if [[ -n "$MAC_MINI_IP" && -n "$WORKER_PORT" ]]; then
        local process_url="http://$MAC_MINI_IP:$WORKER_PORT/api/process"
        local process_payload='{"dry_run": true}'
        
        if curl -s -X POST "$process_url" -H "Content-Type: application/json" -d "$process_payload" 2>/dev/null | grep -q "no.*task\|mock"; then
            success "Worker process endpoint is working"
        else
            warning "Worker process endpoint may have issues"
        fi
    fi
}

# Function to test file system paths
test_file_paths() {
    log "Testing file system paths..."
    
    if [[ -n "$MOVIES_BASE_PATH" ]]; then
        local paths=(
            "$MOVIES_BASE_PATH"
            "$MOVIES_BASE_PATH/$BLURAY_RAW_FOLDER"
            "$MOVIES_BASE_PATH/$BLURAY_PROCESSED_FOLDER"  
            "$MOVIES_BASE_PATH/$BLURAY_TEMP_FOLDER"
        )
        
        for path in "${paths[@]}"; do
            if [[ -d "$path" ]]; then
                success "Directory exists: $path"
                
                # Check permissions
                if [[ -w "$path" ]]; then
                    success "Directory is writable: $path"
                else
                    warning "Directory is not writable: $path"
                fi
            else
                warning "Directory does not exist: $path"
            fi
        done
    else
        warning "MOVIES_BASE_PATH not configured"
    fi
}

# Function to test Telegram integration
test_telegram() {
    log "Testing Telegram integration..."
    
    if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
        if curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe" | grep -q '"ok":true'; then
            success "Telegram bot token is valid"
            
            if [[ -n "$TELEGRAM_CHAT_ID" ]]; then
                local test_message="🧪 BluRay Converter connection test - $(date)"
                if curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
                    -d "chat_id=$TELEGRAM_CHAT_ID" \
                    -d "text=$test_message" | grep -q '"ok":true'; then
                    success "Telegram message sent successfully"
                else
                    warning "Failed to send Telegram message"
                fi
            else
                warning "TELEGRAM_CHAT_ID not configured"
            fi
        else
            error "Telegram bot token is invalid"
        fi
    else
        warning "Telegram not configured (optional)"
    fi
}

# Function to generate system report
generate_report() {
    log "Generating system report..."
    
    local report_file="/tmp/bluray-converter-report-$(date +%Y%m%d-%H%M%S).txt"
    
    cat > "$report_file" << EOF
BluRay Converter System Report
Generated: $(date)
Host: $(hostname)
OS: $(uname -a)

=== Configuration ===
NAS_IP: ${NAS_IP:-"Not set"}
MAC_MINI_IP: ${MAC_MINI_IP:-"Not set"}
NAS_PORT: ${NAS_PORT:-"Not set"}
WORKER_PORT: ${WORKER_PORT:-"Not set"}
MOVIES_BASE_PATH: ${MOVIES_BASE_PATH:-"Not set"}

=== Network Tests ===
EOF

    # Run network tests and append to report
    {
        echo "Ping tests:"
        [[ -n "$NAS_IP" ]] && (ping -c 1 "$NAS_IP" &>/dev/null && echo "✓ NAS reachable" || echo "✗ NAS unreachable")
        [[ -n "$MAC_MINI_IP" ]] && (ping -c 1 "$MAC_MINI_IP" &>/dev/null && echo "✓ Mac reachable" || echo "✗ Mac unreachable")
        
        echo -e "\nAPI tests:"
        [[ -n "$NAS_IP" && -n "$NAS_PORT" ]] && (curl -s "http://$NAS_IP:$NAS_PORT/api/health" | grep -q "healthy" && echo "✓ NAS API healthy" || echo "✗ NAS API unhealthy")
        [[ -n "$MAC_MINI_IP" && -n "$WORKER_PORT" ]] && (curl -s "http://$MAC_MINI_IP:$WORKER_PORT/api/health" | grep -q "healthy" && echo "✓ Mac API healthy" || echo "✗ Mac API unhealthy")
        
        echo -e "\nDocker status:"
        command -v docker >/dev/null && echo "✓ Docker available" || echo "✗ Docker not available"
        docker info &>/dev/null && echo "✓ Docker running" || echo "✗ Docker not running"
        
    } >> "$report_file"
    
    success "Report generated: $report_file"
    echo "View report: cat $report_file"
}

# Main function
main() {
    echo -e "${BLUE}"
    cat << "EOF"
 ____  _       ____             ____                          _            
| __ )| |_   _|  _ \ __ _ _   _ / ___|___  _ ____   _____ _ __| |_ ___ _ __ 
|  _ \| | | | | |_) / _` | | | | |   / _ \| '_ \ \ / / _ \ '__| __/ _ \ '__|
| |_) | | |_| |  _ < (_| | |_| | |__| (_) | | | \ V /  __/ |  | ||  __/ |   
|____/|_|\__,_|_| \_\__,_|\__, |\____\___/|_| |_|\_/ \___|_|   \__\___|_|   
                          |___/                                            
             Connection Test Script
EOF
    echo -e "${NC}"
    
    load_env
    test_network_connectivity
    test_api_endpoints
    test_smb_connectivity
    test_docker_services
    test_workflow
    test_file_paths
    test_telegram
    generate_report
    
    echo
    success "Connection tests completed!"
    echo "Review the full report for detailed results."
}

# Handle script arguments
case "${1:-}" in
    "network")
        load_env
        test_network_connectivity
        exit 0
        ;;
    "api")
        load_env
        test_api_endpoints
        exit 0
        ;;
    "smb")
        load_env
        test_smb_connectivity
        exit 0
        ;;
    "docker")
        test_docker_services
        exit 0
        ;;
    "workflow")
        load_env
        test_workflow
        exit 0
        ;;
    "telegram")
        load_env
        test_telegram
        exit 0
        ;;
    "help"|"-h"|"--help")
        cat << EOF
Usage: $0 [test_type]

Test types:
  (no args) - Run all tests
  network   - Test basic network connectivity
  api       - Test API endpoints
  smb       - Test SMB connectivity
  docker    - Test Docker services
  workflow  - Test end-to-end workflow
  telegram  - Test Telegram integration
  help      - Show this help message

EOF
        exit 0
        ;;
esac

# Run main test suite
main "$@"