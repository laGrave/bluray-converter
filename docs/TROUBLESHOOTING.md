# BluRay Converter - Руководство по решению проблем

Распространенные проблемы и их решения для системы конвертации BluRay дисков.

## Содержание

1. [Быстрая диагностика](#быстрая-диагностика)
2. [Проблемы сети](#проблемы-сети)
3. [Проблемы Docker](#проблемы-docker)
4. [Проблемы SMB](#проблемы-smb)
5. [Проблемы FFmpeg](#проблемы-ffmpeg)
6. [Проблемы с правами доступа](#проблемы-с-правами-доступа)
7. [Проблемы базы данных](#проблемы-базы-данных)
8. [Проблемы Telegram](#проблемы-telegram)
9. [Проблемы Web UI](#проблемы-web-ui)
10. [Проблемы производительности](#проблемы-производительности)

## Быстрая диагностика

### Первые шаги при любой проблеме

```bash
# 1. Запустите комплексную диагностику
./scripts/test-connection.sh

# 2. Проверьте статус сервисов
./scripts/deploy-nas.sh status
./scripts/deploy-mac.sh status

# 3. Посмотрите логи
./scripts/deploy-nas.sh logs
./scripts/deploy-mac.sh logs
```

### Индикаторы проблем
- 🔴 **Сервисы не запускаются** → Проблемы Docker или конфигурации
- 🟡 **Задачи зависают в статусе "pending"** → Проблемы связи NAS-Mac
- 🟠 **Задачи падают с ошибкой** → Проблемы FFmpeg или файловой системы
- 🔵 **Web UI недоступен** → Проблемы сети или Nginx

## Проблемы сети

### NAS и Mac mini не видят друг друга

**Симптомы:**
- Ошибки подключения в логах
- Задачи не отправляются на Mac
- API недоступны

**Диагностика:**
```bash
# Проверьте ping между устройствами
ping 192.168.1.50  # IP NAS
ping 192.168.1.100 # IP Mac mini

# Проверьте доступность портов
nc -z 192.168.1.50 8080  # NAS API
nc -z 192.168.1.100 8000 # Mac Worker
```

**Решения:**
1. **Статические IP адреса**: Убедитесь, что у обоих устройств статические IP
2. **Firewall**: Проверьте настройки брандмауэра на NAS
3. **Роутер**: Перезагрузите роутер, если проблемы с локальной сетью

### Медленная сеть

**Симптомы:**
- Долгая передача файлов
- Таймауты при обработке

**Решения:**
```bash
# Проверьте скорость сети
iperf3 -s  # На одном устройстве
iperf3 -c 192.168.1.50  # На другом

# Используйте проводное подключение
# Проверьте загрузку сети другими приложениями
```

## Проблемы Docker

### Docker не запускается на NAS

**Симптомы:**
```
ERROR: Couldn't connect to Docker daemon
```

**Решения:**
1. **Перезапустите Docker:**
   ```bash
   sudo synopkg stop Docker
   sudo synopkg start Docker
   ```

2. **Проверьте ресурсы:**
   - Минимум 2GB RAM
   - Минимум 10GB свободного места

3. **Права доступа:**
   ```bash
   sudo usermod -aG docker admin
   ```

### Контейнеры не запускаются

**Симптомы:**
- Статус "Exited" у контейнеров
- Ошибки в `docker-compose ps`

**Диагностика:**
```bash
# Посмотрите детальные логи
docker-compose logs service_name

# Проверьте конфигурацию
docker-compose config
```

**Решения:**
1. **Очистите и пересоберите:**
   ```bash
   ./scripts/reset-system.sh containers
   ./scripts/deploy-nas.sh
   ```

2. **Проверьте .env файлы:**
   - Все обязательные переменные заполнены
   - Нет лишних пробелов
   - Правильные IP адреса

### Docker на Mac mini

**Проблема:** Docker Desktop не запускается

**Решения:**
1. **Перезапустите Docker Desktop**
2. **Увеличьте ресурсы Docker:**
   - Memory: минимум 4GB
   - Disk: минимум 50GB
3. **Обновите Docker Desktop до последней версии**

## Проблемы SMB

### Mac не может подключиться к NAS

**Симптомы:**
- Ошибки монтирования в логах worker
- "Mount failed" в Mac логах

**Диагностика:**
```bash
# Проверьте доступность SMB порта
nc -z 192.168.1.50 445

# Проверьте SMB службу на NAS
smbutil view //192.168.1.50
```

**Решения:**
1. **Проверьте учетные данные SMB:**
   ```bash
   # В mac-services/.env
   SMB_USERNAME=правильный_пользователь
   SMB_PASSWORD=правильный_пароль
   ```

2. **Настройки SMB на NAS:**
   - Control Panel → File Services → SMB
   - Включите SMB service
   - Минимальная версия SMB: SMB2

3. **Права доступа к папке:**
   - Пользователь должен иметь RW доступ к shared folder

### Проблемы с русскими именами файлов

**Симптомы:**
- Файлы с русскими именами не обрабатываются
- Ошибки кодировки в логах

**Решения:**
```bash
# Настройте правильную кодировку в Docker
# Добавьте в docker-compose.yml:
environment:
  - LANG=ru_RU.UTF-8
  - LC_ALL=ru_RU.UTF-8
```

## Проблемы FFmpeg

### FFmpeg не найден

**Симптомы:**
```
ERROR: ffmpeg not found in container
```

**Решения:**
1. **Пересоберите контейнер:**
   ```bash
   cd mac-services
   docker-compose build --no-cache worker
   ```

2. **Проверьте Dockerfile:** Убедитесь, что FFmpeg устанавливается

### Ошибки при обработке BDMV

**Симптомы:**
- "Invalid BDMV structure"
- "No playlist found"
- Пустые выходные файлы

**Диагностика:**
```bash
# Проверьте структуру BluRay
ls -la "/volume1/video/Кино/BluRayRAW/Movie (2023)/BDMV/"
# Должны быть папки: PLAYLIST, STREAM, CLIPINF

# Проверьте права доступа
ls -la "/volume1/video/Кино/BluRayRAW/Movie (2023)/"
```

**Решения:**
1. **Правильная структура BDMV:**
   ```
   Movie (2023)/
   └── BDMV/
       ├── PLAYLIST/    # Обязательно
       ├── STREAM/      # Обязательно  
       └── CLIPINF/     # Желательно
   ```

2. **Проверьте размер плейлистов:**
   - Основной фильм обычно самый большой .mpls файл

### Медленная обработка FFmpeg

**Симптомы:**
- Очень долгая конвертация
- Высокая загрузка CPU

**Решения:**
```bash
# Настройте количество потоков в .env
FFMPEG_THREADS=8  # Количество ядер CPU

# Используйте более быстрый preset
FFMPEG_PRESET=fast  # Вместо slow
```

## Проблемы с правами доступа

### Ошибки доступа к файлам

**Симптомы:**
- "Permission denied"
- "Cannot create directory"
- Файлы не перемещаются

**Диагностика:**
```bash
# Проверьте права на директории
ls -la /volume1/video/Кино/
ls -la /volume1/video/Кино/BluRayRAW/
```

**Решения:**
```bash
# Исправьте права доступа
sudo chown -R admin:users /volume1/video/Кино/
sudo chmod -R 775 /volume1/video/Кино/

# Для отдельных папок:
sudo chmod 775 /volume1/video/Кино/BluRayRAW/
sudo chmod 775 /volume1/video/Кино/BluRayProcessed/
sudo chmod 775 /volume1/video/Кино/BluRayTemp/
```

### Docker контейнеры не могут писать

**Решения:**
1. **Проверьте пользователя в контейнере**
2. **Используйте правильные права в docker-compose:**
   ```yaml
   volumes:
     - /volume1/video:/volume1/video:rw
   ```

## Проблемы базы данных

### База данных повреждена

**Симптомы:**
- "Database is locked"
- "Database disk image is malformed"
- API возвращает ошибки базы

**Решения:**
```bash
# Остановите сервисы
cd nas-services && docker-compose down

# Создайте бэкап поврежденной БД
cp volumes/db/tasks.db volumes/db/tasks.db.backup

# Попробуйте восстановить
sqlite3 volumes/db/tasks.db ".recover" | sqlite3 volumes/db/tasks_recovered.db

# Или полный сброс
./scripts/reset-system.sh database
```

### Задачи дублируются

**Симптомы:**
- Одинаковые фильмы появляются несколько раз
- Повторная обработка уже готовых фильмов

**Решения:**
```bash
# Очистите дубликаты через API
curl -X POST http://192.168.1.50:8080/api/maintenance/cleanup

# Или полный сброс базы
./scripts/reset-system.sh database
```

## Проблемы Telegram

### Бот не отвечает

**Симптомы:**
- Команды боту не работают
- Нет уведомлений

**Диагностика:**
```bash
# Проверьте токен бота
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"
```

**Решения:**
1. **Проверьте настройки в .env:**
   ```bash
   TELEGRAM_BOT_TOKEN=правильный_токен
   TELEGRAM_CHAT_ID=правильный_chat_id
   ```

2. **Получите правильный chat_id:**
   ```bash
   # Отправьте сообщение боту, затем:
   curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates" | grep -o '"id":[0-9]*'
   ```

### Уведомления не приходят

**Решения:**
1. **Убедитесь, что уведомления включены:**
   ```bash
   TELEGRAM_NOTIFICATIONS=true
   ```

2. **Проверьте доступ к интернету с NAS**

## Проблемы Web UI

### Web UI недоступен

**Симптомы:**
- Страница не загружается
- 502 Bad Gateway
- Connection refused

**Диагностика:**
```bash
# Проверьте статус nginx
docker-compose ps web-ui

# Проверьте порт
nc -z localhost 8081
```

**Решения:**
1. **Перезапустите web-ui сервис:**
   ```bash
   cd nas-services
   docker-compose restart web-ui
   ```

2. **Проверьте порт в .env:**
   ```bash
   WEB_UI_PORT=8081  # Должен быть свободен
   ```

### API недоступно из браузера

**Симптомы:**
- CORS ошибки
- API запросы не работают

**Решения:**
1. **Проверьте nginx конфигурацию**
2. **Убедитесь, что API сервис запущен:**
   ```bash
   curl http://localhost:8080/api/health
   ```

## Проблемы производительности

### Медленная обработка

**Симптомы:**
- Конвертация занимает очень много времени
- Высокая загрузка системы

**Решения:**
1. **Оптимизируйте FFmpeg:**
   ```bash
   # В mac-services/.env
   FFMPEG_THREADS=0      # Автоопределение
   FFMPEG_PRESET=medium  # Баланс скорость/качество
   ```

2. **Мониторинг ресурсов:**
   ```bash
   # На Mac mini
   htop
   iostat -x 1
   
   # Проверьте свободное место
   df -h
   ```

### Переполнение диска

**Симптомы:**
- "No space left on device"
- Обработка останавливается

**Решения:**
```bash
# Очистите временные файлы
./scripts/reset-system.sh temp

# Переместите готовые файлы из Processed
mv "/volume1/video/Кино/BluRayProcessed/*.mkv" "/volume1/video/Movies/"

# Удалите старые исходники после успешной конвертации
```

## Аварийное восстановление

### Полный сброс системы

Если ничего не помогает:
```bash
# 1. Полный сброс
./scripts/reset-system.sh --force

# 2. Пересоздание
./scripts/deploy-nas.sh
./scripts/deploy-mac.sh

# 3. Тест
./scripts/test-connection.sh
```

### Восстановление из бэкапа

```bash
# Восстановите конфигурацию
tar -xzf bluray-converter-config.tar.gz

# Пересоздайте сервисы
./scripts/deploy-nas.sh
./scripts/deploy-mac.sh
```

## Получение помощи

### Сбор информации для диагностики

```bash
# Создайте полный отчет
./scripts/test-connection.sh > system-report.txt

# Добавьте логи
./scripts/deploy-nas.sh logs >> system-report.txt
./scripts/deploy-mac.sh logs >> system-report.txt

# Информация о системе
uname -a >> system-report.txt
docker version >> system-report.txt
```

### Полезные команды для отладки

```bash
# Мониторинг в реальном времени
docker-compose logs -f

# Подключение к контейнеру
docker exec -it container_name bash

# Проверка сети внутри контейнера
docker exec container_name ping 192.168.1.50

# Просмотр процессов
docker exec container_name ps aux
```

---

**Совет:** Большинство проблем решается перезапуском сервисов и проверкой сетевого подключения. Всегда начинайте с `./scripts/test-connection.sh`.