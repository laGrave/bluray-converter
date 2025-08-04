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
10. [Обслуживание и мониторинг](#обслуживание-и-мониторинг)

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

## Настройка сети

### Конфигурация IP
Оба устройства должны находиться в одной локальной сети со статическими IP адресами:

```bash
# Пример конфигурации сети
NAS IP:      192.168.1.50
Mac mini IP: 192.168.1.100
Роутер:      192.168.1.1
```

### Требования к портам
Убедитесь, что эти порты доступны:

| Сервис | Порт | Протокол | Направление |
|---------|------|----------|-------------|
| NAS API | 8080 | HTTP | Mac → NAS |
| NAS Web UI | 8081 | HTTP | Браузер → NAS |
| Mac Worker | 8000 | HTTP | NAS → Mac |
| SMB Share | 445 | SMB | Mac → NAS |

### Настройка брандмауэра
На Synology NAS убедитесь, что эти порты открыты в настройках брандмауэра.

## Настройка NAS (Synology)

### 1. Включение необходимых сервисов

#### SSH доступ
1. Перейдите в **Панель управления** → **Терминал и SNMP**
2. Установите галочку **Включить службу SSH**
3. Установите порт 22 (по умолчанию)

#### Пакет Docker
1. Откройте **Центр пакетов**
2. Найдите и установите **Docker**
3. Дождитесь завершения установки

### 2. Создание структуры директорий

Подключитесь через SSH и создайте необходимые директории:

```bash
# Подключение к NAS
ssh admin@192.168.1.50

# Создание базовой структуры директорий
sudo mkdir -p /volume1/video/Кино/BluRayRAW
sudo mkdir -p /volume1/video/Кино/BluRayProcessed  
sudo mkdir -p /volume1/video/Кино/BluRayTemp

# Установка правильных прав доступа
sudo chown -R admin:users /volume1/video/Кино/
sudo chmod -R 775 /volume1/video/Кино/
```

### 3. Создание SMB пользователя

1. Перейдите в **Панель управления** → **Пользователи и группы**
2. Создайте нового пользователя: `bluray-worker`
3. Установите надежный пароль
4. Предоставьте доступ к общей папке `video`

### 4. Настройка SMB шары

1. Перейдите в **Панель управления** → **Общая папка**
2. Найдите папку `video` (или создайте новую)
3. Включите службу SMB
4. Установите права доступа для пользователя `bluray-worker`

## Настройка Mac mini

### 1. Установка Docker Desktop

Скачайте и установите Docker Desktop для Mac:
```bash
# Скачайте с: https://docs.docker.com/desktop/install/mac-install/
# Или установите через Homebrew
brew install --cask docker
```

Запустите Docker Desktop и убедитесь, что он работает.

### 2. Установка инструментов командной строки

```bash
xcode-select --install
```

### 3. Проверка поддержки FFmpeg

Docker установит FFmpeg, но можете протестировать локально:
```bash
# Установка FFmpeg локально (необязательно)
brew install ffmpeg

# Тест поддержки BluRay
ffmpeg -formats | grep -i bluray
```

## Конфигурация

### 1. Клонирование репозитория

На обоих устройствах (NAS и Mac mini):
```bash
# Клонирование проекта
git clone https://github.com/user/bluray-converter.git
cd bluray-converter
```

### 2. Настройка NAS сервисов

```bash
cd nas-services
cp .env.example .env
nano .env
```

Отредактируйте файл `.env`:
```bash
# Конфигурация сети
MAC_MINI_IP=192.168.1.100
MAC_MINI_PORT=8000
NAS_IP=192.168.1.50
NAS_PORT=8080
WEB_UI_PORT=8081

# Пути к директориям фильмов
MOVIES_BASE_PATH=/volume1/video/Кино
BLURAY_RAW_FOLDER=BluRayRAW
BLURAY_PROCESSED_FOLDER=BluRayProcessed
BLURAY_TEMP_FOLDER=BluRayTemp

# Конфигурация SMB  
SMB_USERNAME=bluray-worker
SMB_SHARE_NAME=video

# Telegram Bot (по желанию)
TELEGRAM_BOT_TOKEN=ваш_токен_бота_здесь
TELEGRAM_CHAT_ID=ваш_chat_id_здесь

# Планирование
SCAN_SCHEDULE="0 3 * * *"  # Ежедневно в 3 утра
SCHEDULER_ENABLED=true

# База данных
DB_CLEANUP_DAYS=60

# Логирование
LOG_LEVEL=INFO
```

### 3. Настройка Mac сервисов

```bash
cd mac-services  
cp .env.example .env
nano .env
```

Отредактируйте файл `.env`:
```bash
# Конфигурация сети
NAS_IP=192.168.1.50
NAS_API_PORT=8080
WORKER_PORT=8000

# Конфигурация SMB
SMB_USERNAME=bluray-worker
SMB_PASSWORD=ваш_надежный_пароль_здесь

# Точка монтирования
MOUNT_POINT=/mnt/nas

# Конфигурация FFmpeg
FFMPEG_THREADS=0  # Автоопределение ядер CPU
FFMPEG_PRESET=slow  # Компромисс качество/скорость

# Обработка
MAX_CONCURRENT_TASKS=1
TEMP_CLEANUP=true

# Логирование
LOG_LEVEL=INFO
```

### 4. Настройка Telegram бота (по желанию)

1. Создайте бота с @BotFather в Telegram
2. Получите токен бота
3. Найдите свой chat ID, отправив сообщение боту и проверив:
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

## Развертывание

### 1. Развертывание NAS сервисов

На Synology NAS:
```bash
cd bluray-converter
./scripts/deploy-nas.sh
```

Этот скрипт:
- Проверит конфигурацию
- Создаст необходимые директории
- Соберет Docker образы
- Запустит все сервисы
- Выполнит проверки состояния

### 2. Развертывание Mac Worker

На Mac mini:
```bash
cd bluray-converter
./scripts/deploy-mac.sh
```

Этот скрипт:
- Проверит среду macOS
- Протестирует подключение к NAS
- Соберет worker контейнер
- Запустит worker сервис
- Протестирует монтирование SMB

### 3. Проверка развертывания

Запустите тест подключения:
```bash
./scripts/test-connection.sh
```

Это протестирует:
- Сетевое подключение
- API endpoints
- SMB доступ
- Docker сервисы
- End-to-end workflow

## Тестирование

### 1. Проверка состояния сервисов

```bash
# Проверка NAS сервисов
curl http://192.168.1.50:8080/api/health

# Проверка Mac worker
curl http://192.168.1.100:8000/api/health

# Проверка Web UI
open http://192.168.1.50:8081
```

### 2. Тест ручного сканирования

```bash
# Запуск сухого прогона сканирования
curl -X POST http://192.168.1.50:8080/api/tasks/scan \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

### 3. Тест SMB монтирования

На Mac mini:
```bash
# Тест SMB монтирования
./scripts/deploy-mac.sh mount-test
```

## Первый запуск

### 1. Подготовка тестового BluRay

Поместите папку BluRay фильма в директорию raw:
```
/volume1/video/Кино/BluRayRAW/
└── Тестовый Фильм (2023)/
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

### 2. Запуск обработки

Через Web UI:
1. Откройте http://192.168.1.50:8081
2. Нажмите "Сканировать директорию"
3. Следите за прогрессом

Через API:
```bash
curl -X POST http://192.168.1.50:8080/api/tasks/scan
```

### 3. Мониторинг прогресса

```bash
# Проверка статуса задач
curl http://192.168.1.50:8080/api/tasks

# Просмотр логов
cd nas-services && docker-compose logs -f
cd mac-services && docker-compose logs -f worker
```

## Обслуживание и мониторинг

### Статус сервисов
```bash
# Статус NAS сервисов
cd nas-services && docker-compose ps

# Статус Mac worker  
cd mac-services && docker-compose ps

# Просмотр последних логов
./scripts/deploy-nas.sh logs
./scripts/deploy-mac.sh logs
```

### Обслуживание базы данных
Система автоматически очищает старые записи, но можно запустить вручную:
```bash
curl -X POST http://192.168.1.50:8080/api/maintenance/cleanup
```

### Ротация логов
Логи автоматически ротируются, но можно очистить вручную:
```bash
./scripts/reset-system.sh logs
```

## Обновление системы

### Получение последних изменений
```bash
git pull origin main
```

### Пересборка и перезапуск
```bash
# На NAS
./scripts/deploy-nas.sh

# На Mac mini  
./scripts/deploy-mac.sh
```

## Соображения безопасности

### Безопасность сети
- Держите оба устройства в частной сети
- Используйте надежные пароли для SMB доступа
- Рассмотрите VPN для удаленного доступа

### Права на файлы
- Обеспечьте правильные права на директории
- Используйте выделенные учетные записи пользователей
- Регулярно проверяйте логи доступа

### Безопасность Docker
- Держите Docker в актуальном состоянии
- Используйте не-root пользователей в контейнерах
- Ограничьте возможности контейнеров

## Настройка производительности

### Оптимизация Mac mini
```bash
# Увеличение потоков FFmpeg в .env
FFMPEG_THREADS=8  # Установите по количеству ядер CPU

# Используйте более быстрый preset для скорости
FFMPEG_PRESET=fast
```

### Оптимизация NAS
```bash
# Увеличение частоты сканирования для быстрого обнаружения
SCAN_SCHEDULE="*/15 * * * *"  # Каждые 15 минут

# Настройка уровней логирования для производительности
LOG_LEVEL=WARNING
```

## Резервное копирование и восстановление

### Резервное копирование конфигурации
```bash
# Резервное копирование конфигурационных файлов
tar -czf bluray-converter-config.tar.gz \
  nas-services/.env \
  mac-services/.env \
  nas-services/volumes/db/
```

### Полный сброс системы
```bash
# Полный сброс системы
./scripts/reset-system.sh

# Восстановление из резервной копии и повторное развертывание
./scripts/deploy-nas.sh
./scripts/deploy-mac.sh
```

## Следующие шаги

После успешной установки:
1. Изучите [USAGE.md](USAGE.md) для ежедневных операций
2. Проверьте [TROUBLESHOOTING.md](TROUBLESHOOTING.md) для распространенных проблем
3. Следите за системой в течение первых нескольких циклов обработки
4. Настройте регулярные резервные копии вашей конфигурации

---

**Нужна помощь?** Проверьте руководство по решению проблем или просмотрите вывод теста подключения для подробной диагностики.