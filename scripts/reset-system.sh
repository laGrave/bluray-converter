#!/bin/bash
# BluRay Converter - System Reset Script
# Resets the entire system to clean state

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

# Function to confirm dangerous operation
confirm_reset() {
    echo -e "${RED}⚠️  WARNING: This will completely reset the BluRay Converter system!${NC}"
    echo
    echo "This operation will:"
    echo "  • Stop and remove all Docker containers"
    echo "  • Remove Docker images"
    echo "  • Clear the SQLite database"
    echo "  • Clear all logs"
    echo "  • Clear temporary files"
    echo
    echo -e "${YELLOW}Data in MOVIES_BASE_PATH will NOT be affected.${NC}"
    echo
    
    read -p "Are you sure you want to continue? (type 'RESET' to confirm): " confirmation
    if [[ "$confirmation" != "RESET" ]]; then
        echo "Operation cancelled."
        exit 0
    fi
    
    echo
    warning "Starting system reset in 5 seconds... Press Ctrl+C to cancel"
    sleep 5
}

# Function to stop and remove Docker containers
reset_docker_containers() {
    log "Stopping and removing Docker containers..."
    
    # Reset NAS services
    if [[ -d "$PROJECT_ROOT/nas-services" ]]; then
        cd "$PROJECT_ROOT/nas-services"
        
        if command -v docker-compose &> /dev/null; then
            docker-compose down --volumes --remove-orphans 2>/dev/null || true
            docker-compose rm -f -v 2>/dev/null || true
        else
            docker compose down --volumes --remove-orphans 2>/dev/null || true
            docker compose rm -f -v 2>/dev/null || true
        fi
        
        success "NAS containers stopped and removed"
    fi
    
    # Reset Mac services
    if [[ -d "$PROJECT_ROOT/mac-services" ]]; then
        cd "$PROJECT_ROOT/mac-services"
        
        if command -v docker-compose &> /dev/null; then
            docker-compose down --volumes --remove-orphans 2>/dev/null || true
            docker-compose rm -f -v 2>/dev/null || true
        else
            docker compose down --volumes --remove-orphans 2>/dev/null || true
            docker compose rm -f -v 2>/dev/null || true
        fi
        
        success "Mac containers stopped and removed"
    fi
}

# Function to remove Docker images
reset_docker_images() {
    log "Removing BluRay Converter Docker images..."
    
    # Find and remove bluray-converter images
    local images=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "(bluray|nas-services|mac-services)" | head -10)
    
    if [[ -n "$images" ]]; then
        echo "$images" | while read -r image; do
            if docker rmi "$image" 2>/dev/null; then
                success "Removed image: $image"
            else
                warning "Failed to remove image: $image"
            fi
        done
    else
        log "No BluRay Converter images found"
    fi
    
    # Prune unused images
    log "Pruning unused Docker images..."
    docker image prune -f 2>/dev/null || true
    
    success "Docker images cleaned up"
}

# Function to reset databases
reset_databases() {
    log "Resetting databases..."
    
    # Clear NAS database
    local nas_db_dir="$PROJECT_ROOT/nas-services/volumes/db"
    if [[ -d "$nas_db_dir" ]]; then
        rm -rf "$nas_db_dir"/*.db "$nas_db_dir"/*.db-journal 2>/dev/null || true
        success "NAS database cleared"
    fi
    
    # Recreate directory structure
    mkdir -p "$nas_db_dir"
    
    success "Database reset completed"
}

# Function to clear logs
reset_logs() {
    log "Clearing log files..."
    
    # Clear NAS logs
    local nas_logs_dir="$PROJECT_ROOT/nas-services/volumes/logs"
    if [[ -d "$nas_logs_dir" ]]; then
        rm -rf "$nas_logs_dir"/*.log "$nas_logs_dir"/*.log.* 2>/dev/null || true
        success "NAS logs cleared"
    fi
    
    # Clear Mac logs
    local mac_logs_dir="$PROJECT_ROOT/mac-services/volumes/logs"
    if [[ -d "$mac_logs_dir" ]]; then
        rm -rf "$mac_logs_dir"/*.log "$mac_logs_dir"/*.log.* 2>/dev/null || true
        success "Mac logs cleared"
    fi
    
    # Recreate directory structure
    mkdir -p "$nas_logs_dir" "$mac_logs_dir"
    
    success "Log files cleared"
}

# Function to clear temporary files
reset_temp_files() {
    log "Clearing temporary files..."
    
    # Load environment to get temp path
    if [[ -f "$PROJECT_ROOT/nas-services/.env" ]]; then
        source "$PROJECT_ROOT/nas-services/.env"
        
        if [[ -n "$MOVIES_BASE_PATH" && -n "$BLURAY_TEMP_FOLDER" ]]; then
            local temp_path="$MOVIES_BASE_PATH/$BLURAY_TEMP_FOLDER"
            if [[ -d "$temp_path" ]]; then
                # Only remove .mkv and .tmp files, not the directory itself
                find "$temp_path" -name "*.mkv" -delete 2>/dev/null || true
                find "$temp_path" -name "*.tmp" -delete 2>/dev/null || true
                find "$temp_path" -name "*.part" -delete 2>/dev/null || true
                success "Temporary conversion files cleared"
            fi
        fi
    fi
    
    # Clear system temp files
    rm -rf /tmp/bluray-converter-* 2>/dev/null || true
    rm -rf /tmp/bluray-test-mount 2>/dev/null || true
    
    success "Temporary files cleared"
}

# Function to reset network mounts
reset_mounts() {
    log "Unmounting network shares..."
    
    # Find and unmount any bluray-converter related mounts
    local mounts=$(mount | grep -E "(bluray|nas)" | awk '{print $3}' || true)
    
    if [[ -n "$mounts" ]]; then
        echo "$mounts" | while read -r mount_point; do
            if umount "$mount_point" 2>/dev/null; then
                success "Unmounted: $mount_point"
                rmdir "$mount_point" 2>/dev/null || true
            fi
        done
    fi
    
    success "Network mounts reset"
}

# Function to verify system state
verify_reset() {
    log "Verifying system reset..."
    
    # Check for running containers
    local running_containers=$(docker ps --format "{{.Names}}" | grep -E "(bluray|nas-services|mac-services)" | wc -l)
    if [[ $running_containers -eq 0 ]]; then
        success "✓ No BluRay Converter containers running"
    else
        warning "✗ Some containers may still be running"
    fi
    
    # Check for images
    local remaining_images=$(docker images --format "{{.Repository}}" | grep -E "(bluray|nas-services|mac-services)" | wc -l)
    if [[ $remaining_images -eq 0 ]]; then
        success "✓ No BluRay Converter images found"
    else
        warning "✗ Some images may still exist"
    fi
    
    # Check database files
    if [[ ! -f "$PROJECT_ROOT/nas-services/volumes/db/tasks.db" ]]; then
        success "✓ Database files cleared"
    else
        warning "✗ Database files may still exist"
    fi
    
    # Check log directories
    local log_files=$(find "$PROJECT_ROOT" -name "*.log" 2>/dev/null | wc -l)
    if [[ $log_files -eq 0 ]]; then
        success "✓ Log files cleared"
    else
        warning "✗ Some log files may still exist"
    fi
    
    success "System reset verification completed"
}

# Function to provide restart instructions
show_restart_instructions() {
    cat << EOF

${GREEN}=== System Reset Complete ===${NC}

The BluRay Converter system has been reset to a clean state.

To restart the system:

1. On NAS (Synology):
   cd $PROJECT_ROOT
   ./scripts/deploy-nas.sh

2. On Mac mini:
   cd $PROJECT_ROOT
   ./scripts/deploy-mac.sh

3. Test the connection between devices:
   ./scripts/test-connection.sh

${YELLOW}Remember to:${NC}
• Verify your .env configuration files are correct
• Ensure network connectivity between NAS and Mac mini
• Check that all required directories exist with proper permissions

EOF
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
             System Reset Script
EOF
    echo -e "${NC}"
    
    confirm_reset
    reset_docker_containers
    reset_docker_images
    reset_databases
    reset_logs
    reset_temp_files
    reset_mounts
    verify_reset
    show_restart_instructions
    
    echo
    success "System reset completed successfully!"
}

# Handle script arguments
case "${1:-}" in
    "containers")
        confirm_reset
        reset_docker_containers
        exit 0
        ;;
    "images")
        confirm_reset
        reset_docker_images
        exit 0
        ;;
    "database")
        confirm_reset
        reset_databases
        exit 0
        ;;
    "logs")
        reset_logs
        exit 0
        ;;
    "temp")
        reset_temp_files
        exit 0
        ;;
    "verify")
        verify_reset
        exit 0
        ;;
    "--force")
        # Skip confirmation for automated scripts
        reset_docker_containers
        reset_docker_images
        reset_databases
        reset_logs
        reset_temp_files
        reset_mounts
        verify_reset
        show_restart_instructions
        exit 0
        ;;
    "help"|"-h"|"--help")
        cat << EOF
Usage: $0 [component]

Components:
  (no args) - Full system reset (with confirmation)
  containers - Reset Docker containers only
  images     - Reset Docker images only
  database   - Reset database only
  logs       - Reset log files only
  temp       - Reset temporary files only
  verify     - Verify reset state
  --force    - Full reset without confirmation
  help       - Show this help message

WARNING: These operations are destructive and cannot be undone!

EOF
        exit 0
        ;;
esac

# Run main reset
main "$@"