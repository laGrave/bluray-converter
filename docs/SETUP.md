# BluRay Converter - Руководство по установке

Полное руководство по установке и настройке системы BluRay Converter.

## Содержание

1. [Обзор](#обзор)
2. [Предварительные требования](#предварительные-требования)
3. [Настройка сети](#настройка-сети)
4. [Настройка NAS (Synology)](#настройка-nas-synology)
5. [Настройка Mac mini](#настройка-mac-mini)
6. [Конфигурация](#конфигурация)
7. [Развертывание](#развертывание)
8. [Тестирование](#тестирование)
9. [Первый запуск](#первый-запуск)
10. [Решение проблем](#решение-проблем)

## Обзор

Система BluRay Converter состоит из двух основных компонентов:
- **NAS Сервисы** (Synology): Мониторинг директорий, управление задачами, веб-интерфейс
- **Mac Worker** (Apple Silicon): Обработка видео с помощью FFmpeg

### Архитектура
```
┌─────────────┐    Сеть       ┌──────────────┐
│   Synology  │◄─────────────►│   Mac mini   │
│     NAS     │   SMB/HTTP    │ Apple Silicon│
│             │               │              │
│ • Watcher   │               │ • FFmpeg     │
│ • API       │               │ • Worker     │
│ • Web UI    │               │ • Processor  │
│ • Scheduler │               │              │
└─────────────┘               └──────────────┘
```

## Предварительные требования

### Требования к оборудованию
- **Synology NAS**: Любая модель с поддержкой Docker (DSM 7.0+)
- **Mac mini**: Apple Silicon (M1/M2/M3) рекомендуется для оптимальной производительности
- **Сеть**: Локальная сеть 1 Гбит/с между устройствами

### Требования к программному обеспечению

#### На NAS (Synology)
- DSM 7.0 или новее
- Установленный пакет Docker
- Включенный SSH доступ
- Минимум 2GB свободной RAM
- 10GB свободного места для Docker образов

#### На Mac mini
- macOS 12.0 (Monterey) или новее
- Docker Desktop для Mac
- Command Line Tools для Xcode
- Минимум 8GB RAM (рекомендуется 16GB)
- 50GB+ свободного места для временных файлов

## Network Setup

### IP Configuration
Both devices should be on the same local network with static IP addresses:

```bash
# Example network configuration
NAS IP:      192.168.1.50
Mac mini IP: 192.168.1.100
Router:      192.168.1.1
```

### Port Requirements
Ensure these ports are available:

| Service | Port | Protocol | Direction |
|---------|------|----------|-----------|
| NAS API | 8080 | HTTP | Mac → NAS |
| NAS Web UI | 8081 | HTTP | Browser → NAS |
| Mac Worker | 8000 | HTTP | NAS → Mac |
| SMB Share | 445 | SMB | Mac → NAS |

### Firewall Configuration
On Synology NAS, ensure these ports are open in the firewall settings.

## NAS (Synology) Setup

### 1. Enable Required Services

#### SSH Access
1. Go to **Control Panel** → **Terminal & SNMP**
2. Check **Enable SSH service**
3. Set port to 22 (default)

#### Docker Package
1. Open **Package Center**
2. Search and install **Docker**
3. Wait for installation to complete

### 2. Create Directory Structure

Connect via SSH and create the required directories:

```bash
# Connect to NAS
ssh admin@192.168.1.50

# Create base directory structure
sudo mkdir -p /volume1/video/Кино/BluRayRAW
sudo mkdir -p /volume1/video/Кино/BluRayProcessed  
sudo mkdir -p /volume1/video/Кино/BluRayTemp

# Set proper permissions
sudo chown -R admin:users /volume1/video/Кино/
sudo chmod -R 775 /volume1/video/Кино/
```

### 3. Create SMB User

1. Go to **Control Panel** → **User & Group**
2. Create new user: `bluray-worker`
3. Set a secure password
4. Grant access to `video` shared folder

### 4. Configure SMB Share

1. Go to **Control Panel** → **Shared Folder**
2. Find the `video` share (or create one)
3. Enable SMB service
4. Set permissions for `bluray-worker` user

## Mac mini Setup

### 1. Install Docker Desktop

Download and install Docker Desktop for Mac:
```bash
# Download from: https://docs.docker.com/desktop/install/mac-install/
# Or install via Homebrew
brew install --cask docker
```

Start Docker Desktop and ensure it's running.

### 2. Install Command Line Tools

```bash
xcode-select --install
```

### 3. Verify FFmpeg Support

Docker will install FFmpeg, but you can test locally:
```bash
# Install FFmpeg locally (optional)
brew install ffmpeg

# Test BluRay support
ffmpeg -formats | grep -i bluray
```

## Configuration

### 1. Clone the Repository

On both NAS and Mac mini:
```bash
# Clone the project
git clone https://github.com/user/bluray-converter.git
cd bluray-converter
```

### 2. Configure NAS Services

```bash
cd nas-services
cp .env.example .env
nano .env
```

Edit the `.env` file:
```bash
# Network Configuration
MAC_MINI_IP=192.168.1.100
MAC_MINI_PORT=8000
NAS_IP=192.168.1.50
NAS_PORT=8080
WEB_UI_PORT=8081

# Movie Directory Paths
MOVIES_BASE_PATH=/volume1/video/Кино
BLURAY_RAW_FOLDER=BluRayRAW
BLURAY_PROCESSED_FOLDER=BluRayProcessed
BLURAY_TEMP_FOLDER=BluRayTemp

# SMB Configuration  
SMB_USERNAME=bluray-worker
SMB_SHARE_NAME=video

# Telegram Bot (Optional)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Scheduling
SCAN_SCHEDULE="0 3 * * *"  # Daily at 3 AM
SCHEDULER_ENABLED=true

# Database
DB_CLEANUP_DAYS=60

# Logging
LOG_LEVEL=INFO
```

### 3. Configure Mac Services

```bash
cd mac-services  
cp .env.example .env
nano .env
```

Edit the `.env` file:
```bash
# Network Configuration
NAS_IP=192.168.1.50
NAS_API_PORT=8080
WORKER_PORT=8000

# SMB Configuration
SMB_USERNAME=bluray-worker
SMB_PASSWORD=your_secure_password_here

# Mount Point
MOUNT_POINT=/mnt/nas

# FFmpeg Configuration
FFMPEG_THREADS=0  # Auto-detect CPU cores
FFMPEG_PRESET=slow  # Quality vs speed trade-off

# Processing
MAX_CONCURRENT_TASKS=1
TEMP_CLEANUP=true

# Logging
LOG_LEVEL=INFO
```

### 4. Telegram Bot Setup (Optional)

1. Create a bot with @BotFather on Telegram
2. Get your bot token
3. Find your chat ID by messaging the bot and checking:
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

## Deployment

### 1. Deploy NAS Services

On the Synology NAS:
```bash
cd bluray-converter
./scripts/deploy-nas.sh
```

This script will:
- Validate configuration
- Create necessary directories
- Build Docker images
- Start all services
- Run health checks

### 2. Deploy Mac Worker

On the Mac mini:
```bash
cd bluray-converter
./scripts/deploy-mac.sh
```

This script will:
- Validate macOS environment
- Test NAS connectivity
- Build worker container
- Start worker service
- Test SMB mounting

### 3. Verify Deployment

Run the connection test:
```bash
./scripts/test-connection.sh
```

This will test:
- Network connectivity
- API endpoints
- SMB access
- Docker services
- End-to-end workflow

## Testing

### 1. Service Health Check

```bash
# Check NAS services
curl http://192.168.1.50:8080/api/health

# Check Mac worker
curl http://192.168.1.100:8000/api/health

# Check Web UI
open http://192.168.1.50:8081
```

### 2. Manual Scan Test

```bash
# Trigger a dry-run scan
curl -X POST http://192.168.1.50:8080/api/tasks/scan \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

### 3. SMB Mount Test

On Mac mini:
```bash
# Test SMB mounting
./scripts/deploy-mac.sh mount-test
```

## First Run

### 1. Prepare Test BluRay

Place a BluRay movie folder in the raw directory:
```
/volume1/video/Кино/BluRayRAW/
└── Test Movie (2023)/
    └── BDMV/
        ├── PLAYLIST/
        │   ├── 00000.mpls
        │   └── 00001.mpls
        ├── STREAM/
        │   ├── 00000.m2ts
        │   └── 00001.m2ts
        └── CLIPINF/
            ├── 00000.clpi
            └── 00001.clpi
```

### 2. Trigger Processing

Via Web UI:
1. Open http://192.168.1.50:8081
2. Click "Scan Directory"
3. Monitor the progress

Via API:
```bash
curl -X POST http://192.168.1.50:8080/api/tasks/scan
```

### 3. Monitor Progress

```bash
# Check task status
curl http://192.168.1.50:8080/api/tasks

# View logs
cd nas-services && docker-compose logs -f
cd mac-services && docker-compose logs -f worker
```

## Monitoring and Maintenance

### Service Status
```bash
# NAS services status
cd nas-services && docker-compose ps

# Mac worker status  
cd mac-services && docker-compose ps

# View recent logs
./scripts/deploy-nas.sh logs
./scripts/deploy-mac.sh logs
```

### Database Maintenance
The system automatically cleans up old records, but you can trigger it manually:
```bash
curl -X POST http://192.168.1.50:8080/api/maintenance/cleanup
```

### Log Rotation
Logs are automatically rotated, but you can clear them manually:
```bash
./scripts/reset-system.sh logs
```

## Updating the System

### Pull Latest Changes
```bash
git pull origin main
```

### Rebuild and Restart
```bash
# On NAS
./scripts/deploy-nas.sh

# On Mac mini  
./scripts/deploy-mac.sh
```

## Security Considerations

### Network Security
- Keep both devices on a private network
- Use strong passwords for SMB access
- Consider VPN for remote access

### File Permissions
- Ensure proper directory permissions
- Use dedicated user accounts
- Regularly audit access logs

### Docker Security
- Keep Docker updated
- Use non-root users in containers
- Limit container capabilities

## Performance Tuning

### Mac mini Optimization
```bash
# Increase FFmpeg threads in .env
FFMPEG_THREADS=8  # Set to CPU core count

# Use faster preset for speed over quality
FFMPEG_PRESET=fast
```

### NAS Optimization
```bash
# Increase scan frequency for faster detection
SCAN_SCHEDULE="*/15 * * * *"  # Every 15 minutes

# Adjust log levels for performance
LOG_LEVEL=WARNING
```

## Backup and Recovery

### Configuration Backup
```bash
# Backup configuration files
tar -czf bluray-converter-config.tar.gz \
  nas-services/.env \
  mac-services/.env \
  nas-services/volumes/db/
```

### Full System Reset
```bash
# Complete system reset
./scripts/reset-system.sh

# Restore from backup and redeploy
./scripts/deploy-nas.sh
./scripts/deploy-mac.sh
```

## Next Steps

After successful setup:
1. Review [USAGE.md](USAGE.md) for daily operations
2. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues
3. Monitor the system for the first few processing cycles
4. Set up regular backups of your configuration

---

**Need Help?** Check the troubleshooting guide or review the connection test output for detailed diagnostics.