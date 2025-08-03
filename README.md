# BluRay Converter

Automated system for converting BluRay movies to MKV format using distributed processing between Synology NAS and Mac mini.

## Overview

This system automatically detects new BluRay movies on your NAS, converts them to MKV format on a Mac mini worker, and notifies you via Telegram when complete. It's designed for Plex media servers that don't natively support BDMV format.

## Architecture

- **NAS Services** (Synology): File watching, task management, web UI, Telegram notifications
- **Mac Services** (Mac mini): Video processing, BDMV analysis, FFmpeg conversion

## Quick Start

1. **NAS Setup**:
   ```bash
   cd nas-services
   cp .env.example .env
   # Edit .env with your configuration
   ./scripts/deploy-nas.sh
   ```

2. **Mac Setup**:
   ```bash
   cd mac-services
   cp .env.example .env
   # Edit .env with your configuration
   ./scripts/deploy-mac.sh
   ```

3. **Usage**:
   - Copy BluRay movies to `/volume1/video/Кино/BluRayRAW/`
   - System automatically processes them at 3 AM or via web UI
   - Converted files appear in `/volume1/video/Кино/BluRayProcessed/`

## Features

- ✅ Automatic BluRay detection and conversion
- ✅ Lossless remux (no quality loss)
- ✅ Web management interface
- ✅ Telegram notifications and bot commands
- ✅ Distributed processing architecture
- ✅ Error handling and retry logic
- ✅ Complete Docker containerization

## Documentation

- [Setup Instructions](docs/SETUP.md)
- [User Guide](docs/USAGE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Requirements

- Synology NAS with Docker support
- Mac mini with Apple Silicon and Docker Desktop
- Local network connectivity between devices
- FFmpeg support
- Telegram bot token (optional)

## Directory Structure

```
/volume1/video/Кино/
├── BluRayRAW/          # Input: Place BluRay movies here
├── BluRayProcessed/    # Output: Converted MKV files
└── BluRayTemp/         # Temporary processing files
```

## Web Interface

Access the management interface at `http://your-nas-ip:8080` to:
- View processing queue
- Monitor conversion progress  
- Manually trigger scans
- View processing history and statistics

## License

This project is for educational and personal use only.