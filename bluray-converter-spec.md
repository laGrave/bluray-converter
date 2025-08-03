# Техническое задание: Система автоматической конвертации Blu-ray в MKV

## ВАЖНО: Контекст разработки для LLM

### Для разработчика (LLM):
Вы будете разрабатывать эту систему на Mac, который НЕ является целевыми устройствами (Synology NAS или Mac mini с Apple Silicon). Это означает:

1. **Вы НЕ сможете тестировать код локально** - нет доступа к Synology NAS или целевому Mac mini
2. **Ваша задача** - создать полностью готовую к развертыванию систему с детальными инструкциями
3. **Код должен быть максимально надежным** - у вас не будет возможности отладки на реальных устройствах
4. **Особое внимание уделите**:
   - Обработке ошибок и edge cases
   - Детальному логированию для диагностики
   - Проверке всех путей и конфигураций
   - Graceful обработке недоступности сервисов
   - Подробным комментариям в коде
   - Валидации всех входных данных

5. **Deliverables (что должно быть создано)**:
   - Полная структура проекта со всеми файлами
   - Docker-образы, которые будут работать на целевых устройствах
   - Скрипты развертывания с проверками окружения
   - Детальная документация по установке и отладке
   - Примеры конфигурационных файлов
   - Скрипты для диагностики проблем

6. **Предположения об окружении**:
   - Synology NAS имеет Docker, но ограниченные ресурсы
   - Mac mini имеет Docker Desktop для Mac (ARM архитектура Apple Silicon)
   - Сеть между устройствами - локальная, 1 Гбит/с
   - Пути на NAS начинаются с /volume1/

7. **Тестирование**:
   - Создайте unit-тесты где возможно
   - Добавьте mock-режим для проверки логики без реальных устройств
   - Включите dry-run режим для безопасного первого запуска

8. **Принятие решений**:
   - **Если возникают неоднозначности в реализации, выбирайте наиболее простой и надежный вариант, документируя принятое решение в коде**
   - При выборе между производительностью и надежностью - выбирайте надежность
   - Все предположения и решения должны быть задокументированы в комментариях

## 1. Контекст и описание проблемы

### 1.1 Исходная ситуация
У пользователя есть:
- **Synology NAS** - сетевое хранилище, где организован медиасервер Plex для просмотра фильмов
- **Mac mini с процессором Apple Silicon (M-series)** - компьютер в домашней сети, используемый как билд-сервер, простаивает 99% времени
- **Коллекция фильмов** в формате Blu-ray (структура папок BDMV)

### 1.2 Проблема
Plex не поддерживает нативное воспроизведение Blu-ray дисков в формате BDMV. Для просмотра через Plex фильмы нужно конвертировать в поддерживаемый формат MKV.

### 1.3 Решение
Создать автоматизированную систему, которая:
1. Обнаруживает новые Blu-ray фильмы на NAS
2. Автоматически конвертирует их в MKV без потери качества (remux)
3. Использует мощности простаивающего Mac mini для обработки
4. Уведомляет о статусе через Telegram
5. Предоставляет веб-интерфейс для управления

## 2. Архитектура системы

Система состоит из двух частей:
- **Управляющая часть на NAS** - обнаружение файлов, управление очередью, веб-интерфейс
- **Обрабатывающая часть на Mac mini** - выполнение ресурсоемкой конвертации

Взаимодействие происходит через REST API по локальной сети.

## 3. Детальное описание компонентов

### 3.1 Компоненты на NAS (Synology)
- **Watcher Service** - сканирует папку с Blu-ray фильмами, обнаруживает новые
- **API Service** - REST API для управления системой и приема webhook от Mac mini
- **Web UI** - веб-интерфейс для просмотра очереди и управления
- **Scheduler** - запускает сканирование по расписанию
- **SQLite DB** - хранит информацию о задачах и истории
- **Telegram Bot** - отправляет уведомления о процессе

### 3.2 Компоненты на Mac mini
- **Worker API** - принимает задачи от NAS
- **Processor** - выполняет конвертацию через FFmpeg

## 4. Структура папок на NAS
```
/volume1/video/Кино/
├── BluRayRAW/          # Сюда пользователь кладет Blu-ray фильмы для обработки
│   └── MovieName/      # Каждый фильм - отдельная папка
│       └── BDMV/       # Стандартная структура Blu-ray диска
├── BluRayProcessed/    # Сюда система кладет готовые MKV файлы
└── BluRayTemp/         # Временная папка для процесса конвертации
```

## 5. Процесс работы системы

### 5.1 Основной сценарий
1. **Пользователь** копирует Blu-ray фильм в папку BluRayRAW
2. **Система** автоматически (раз в сутки в 3:00) или по запросу сканирует папку
3. **При обнаружении нового фильма:**
   - Создается задача в очереди
   - Задача отправляется на Mac mini
   - Mac mini монтирует папки NAS через SMB
   - Анализирует BDMV структуру, находит основной фильм (самый длинный)
   - Конвертирует в MKV без перекодирования (remux) для сохранения качества
   - Сохраняет результат в BluRayTemp
   - Уведомляет NAS о завершении
4. **NAS получив уведомление:**
   - Перемещает готовый файл из BluRayTemp в BluRayProcessed
   - Удаляет исходник из BluRayRAW
   - Отправляет уведомление в Telegram
5. **Пользователь** вручную перемещает фильм из BluRayProcessed в основную библиотеку Plex

### 5.2 Обработка ошибок
- Если Mac mini недоступен: 3 попытки с интервалом 30 минут
- Если конвертация не удалась: 2 попытки, затем пометка как ошибка
- Все ошибки логируются и отправляются в Telegram

## 6. Детальные требования к функциональности

### 6.1 База данных (SQLite)
Таблицы:
- **tasks** - очередь задач
  - id, movie_name, status, created_at, updated_at, attempts
  - Статусы: pending, sent, processing, completed, failed, retrying
- **processing_history** - история всех обработок
- **errors** - подробные логи ошибок
- **statistics** - статистика по месяцам

Автоматическая очистка записей старше 60 дней.

### 6.2 Web UI функции
- Просмотр текущей очереди с прогрессом
- Ручной запуск сканирования папки
- Приоритетный запуск выбранного фильма
- Удаление/перезапуск задач
- Просмотр логов обработки
- Статистика обработанных фильмов
- Доступ только из локальной сети без авторизации

### 6.3 Telegram бот
Сообщения:
- "🎬 Начата обработка: MovieName"
- "✅ Успешно обработан: MovieName (время: 45 мин)"
- "❌ Ошибка обработки: MovieName - детали"

Команды:
- /queue - показать очередь
- /scan - запустить сканирование
- /cancel - отменить текущую обработку

### 6.4 Конфигурация через ENV файлы
```env
# nas-services/.env
MAC_MINI_IP=192.168.1.100
MAC_MINI_PORT=8000
NAS_IP=192.168.1.50
NAS_PORT=8080
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id
SCAN_SCHEDULE="0 3 * * *"  # cron формат

# Пути к папкам (можно изменять под свою структуру)
MOVIES_BASE_PATH=/volume1/video/Кино
BLURAY_RAW_FOLDER=BluRayRAW
BLURAY_PROCESSED_FOLDER=BluRayProcessed
BLURAY_TEMP_FOLDER=BluRayTemp

# SMB настройки для Mac mini
SMB_USERNAME=nas_user
SMB_SHARE_NAME=video
```

```env
# mac-services/.env
NAS_IP=192.168.1.50
NAS_API_PORT=8080
WORKER_PORT=8000

# Пути монтирования
MOUNT_POINT=/mnt/nas
SMB_USERNAME=nas_user
SMB_PASSWORD=secure_password

# FFmpeg настройки
FFMPEG_THREADS=0  # 0 = auto
FFMPEG_PRESET=slow
```

## 7. Технологический стек

### NAS сервисы:
- Python 3.11+
- FastAPI - для REST API
- SQLite - база данных
- APScheduler - планировщик задач
- python-telegram-bot - Telegram интеграция
- HTML/CSS/JavaScript + Alpine.js - веб-интерфейс
- Chart.js - графики статистики
- Docker + Docker Compose - контейнеризация

### Mac mini сервисы:
- Python 3.11+
- FastAPI - REST API сервер
- FFmpeg - конвертация видео
- smbprotocol или системный mount - доступ к NAS
- Docker + Docker Compose - контейнеризация

## 8. Структура проекта
```
blu-ray-converter/
├── nas-services/
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── watcher/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py              # Точка входа
│   │   ├── scanner.py           # Логика сканирования папок
│   │   ├── db_manager.py        # Работа с SQLite
│   │   └── mac_client.py        # Отправка задач на Mac
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py              # FastAPI приложение
│   │   ├── routes.py            # API endpoints
│   │   ├── webhook.py           # Обработка webhook от Mac
│   │   ├── file_manager.py      # Перемещение файлов
│   │   └── telegram_bot.py      # Telegram уведомления
│   ├── scheduler/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── scheduler.py         # Cron задачи
│   ├── web-ui/
│   │   ├── Dockerfile
│   │   ├── nginx.conf
│   │   ├── index.html           # Главная страница
│   │   ├── style.css            # Стили
│   │   ├── app.js               # Логика интерфейса
│   │   └── api.js               # Работа с API
│   └── volumes/
│       ├── db/                  # SQLite база
│       └── logs/                # Логи
│
├── mac-services/
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── worker/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py              # FastAPI сервер
│   │   ├── processor.py         # Основная логика обработки
│   │   ├── bdmv_analyzer.py     # Анализ Blu-ray структуры
│   │   ├── ffmpeg_wrapper.py    # Обертка для FFmpeg
│   │   └── nas_client.py        # Webhook обратно на NAS
│   └── volumes/
│       └── logs/                # Логи
│
├── scripts/
│   ├── deploy-nas.sh            # Развертывание на NAS
│   ├── deploy-mac.sh            # Развертывание на Mac
│   ├── test-connection.sh       # Проверка связи
│   └── reset-system.sh          # Сброс системы
│
└── docs/
    ├── SETUP.md                 # Инструкция по установке
    ├── USAGE.md                 # Руководство пользователя
    └── TROUBLESHOOTING.md       # Решение проблем
```

## 9. API спецификация

### NAS API endpoints:
```
GET  /api/tasks                 # Список всех задач
POST /api/tasks/scan            # Запустить сканирование
POST /api/tasks/{id}/restart    # Перезапустить задачу
DELETE /api/tasks/{id}          # Удалить задачу
POST /api/tasks/{id}/priority   # Поставить в начало очереди
GET  /api/logs                  # Получить логи
GET  /api/statistics            # Статистика обработки
POST /api/webhook/status        # Webhook для Mac mini
GET  /api/health                # Проверка работоспособности
```

### Mac mini API endpoints:
```
POST /api/process               # Получить и начать обработку задачи
GET  /api/health                # Проверка доступности
GET  /api/status/{task_id}      # Статус текущей обработки
```

## 10. Webhook спецификация

Mac mini → NAS при завершении:
```json
{
  "task_id": "123",
  "status": "completed",
  "temp_file": "MovieName.mkv",
  "source_folder": "MovieName",
  "processing_time": 2700,
  "file_size_mb": 45000
}
```

При ошибке:
```json
{
  "task_id": "123",
  "status": "failed",
  "error": "FFmpeg error: Invalid BDMV structure",
  "source_folder": "MovieName"
}
```

## 11. Инструкции по развертыванию

### 11.1 Подготовка NAS:
1. Включить SSH доступ в настройках
2. Установить Docker через Package Center
3. Создать shared folder для проекта

### 11.2 Развертывание на NAS:
```bash
# 1. Подключиться по SSH
ssh admin@nas-ip

# 2. Клонировать проект
git clone https://github.com/user/blu-ray-converter.git
cd blu-ray-converter/nas-services

# 3. Настроить конфигурацию
cp .env.example .env
nano .env  # Заполнить реальные значения

# 4. Запустить
./scripts/deploy-nas.sh
```

### 11.3 Развертывание на Mac mini:
```bash
# 1. Установить Docker Desktop для Mac
# 2. Клонировать проект
git clone https://github.com/user/blu-ray-converter.git
cd blu-ray-converter/mac-services

# 3. Настроить конфигурацию
cp .env.example .env
nano .env  # Заполнить реальные значения

# 4. Запустить
./scripts/deploy-mac.sh
```

## 12. Дополнительные требования

- Все контейнеры с `restart: always` для автозапуска
- Логирование с ротацией (максимум 100MB на файл)
- Graceful shutdown при остановке контейнеров
- Health checks для мониторинга состояния
- Возможность добавления других типов уведомлений (email, Discord)
- Обработка только одного фильма одновременно для стабильности

## 13. Требования к реализации

### 13.1 Особенности разработки
- Код должен быть написан с учетом невозможности локального тестирования
- Максимальная обработка ошибок и валидация данных
- Подробное логирование всех операций
- Использование переменных окружения для всех настроек
- Никаких hardcoded путей или IP-адресов

### 13.2 Mock-режим для тестирования
Реализовать возможность запуска в mock-режиме:
- Эмуляция файловой системы NAS
- Фейковая обработка видео (sleep вместо FFmpeg)
- Тестовые webhook вызовы
- Логирование всех операций в verbose режиме

### 13.3 Диагностические скрипты
Создать скрипты для проверки:
- `check-nas-connection.sh` - проверка доступности NAS
- `check-mac-connection.sh` - проверка связи с Mac mini
- `validate-config.sh` - валидация конфигурации
- `test-ffmpeg.sh` - проверка работы FFmpeg
- `test-telegram.sh` - проверка отправки сообщений

### 13.4 Документация по отладке
Создать TROUBLESHOOTING.md с решениями типичных проблем:
- Ошибки монтирования SMB
- Проблемы с правами доступа
- Ошибки сети между устройствами
- Проблемы с Docker на Synology
- Типичные ошибки FFmpeg

## 14. План пошаговой реализации

### Фаза 1: Инициализация проекта (30 минут)
1. Создать полную структуру папок согласно разделу 8
2. Инициализировать git репозиторий:
   ```bash
   git init
   git add .
   git commit -m "Initial project structure"
   ```
3. Создать все пустые файлы с базовыми заголовками
4. Создать README.md с описанием проекта
5. Коммит: `git commit -m "Add empty files with basic headers"`

### Git стратегия для всего проекта:
- Коммитить после каждой завершенной фазы
- Коммитить после реализации каждого значимого компонента
- Использовать понятные сообщения на английском языке
- Примеры коммитов:
  - `feat: Add database schema and models`
  - `feat: Implement BDMV analyzer`
  - `feat: Add FFmpeg wrapper with progress tracking`
  - `fix: Handle SMB connection timeout`
  - `docs: Add troubleshooting guide`

### Фаза 2: Базовая инфраструктура (1 час)
1. Создать docker-compose.yml для NAS и Mac
2. Написать Dockerfile для каждого сервиса
3. Создать .env.example файлы с описанием всех переменных
4. Реализовать базовые requirements.txt

### Фаза 3: База данных и модели (1.5 часа)
1. Создать схему SQLite в `nas-services/api/models.py`:
   ```python
   # Пример структуры
   CREATE TABLE tasks (
       id INTEGER PRIMARY KEY,
       movie_name TEXT NOT NULL,
       source_path TEXT NOT NULL,
       status TEXT NOT NULL,
       priority INTEGER DEFAULT 0,
       attempts INTEGER DEFAULT 0,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       processing_started_at TIMESTAMP,
       processing_completed_at TIMESTAMP,
       error_message TEXT
   );
   ```
2. Реализовать db_manager.py с методами:
   - create_task()
   - get_pending_tasks()
   - update_task_status()
   - get_task_history()
   - cleanup_old_records()

### Фаза 4: NAS Watcher Service (2 часа)
1. Реализовать scanner.py:
   ```python
   # Псевдокод для понимания логики
   def scan_directory():
       # Использовать пути из конфигурации
       base_path = os.getenv("MOVIES_BASE_PATH")
       raw_folder = os.getenv("BLURAY_RAW_FOLDER")
       raw_path = os.path.join(base_path, raw_folder)
       
       for folder in os.listdir(raw_path):
           if has_bdmv_structure(folder) and not is_processed(folder):
               create_task(folder)
   ```
2. Реализовать mac_client.py для отправки задач
3. Добавить обработку таймаутов и повторных попыток
4. Коммит: `git commit -m "feat: Implement NAS watcher service with configurable paths"`

### Фаза 5: Mac Worker Service (3 часа)
1. Реализовать bdmv_analyzer.py:
   ```python
   # Логика поиска основного плейлиста
   def find_main_playlist(bdmv_path):
       playlist_dir = os.path.join(bdmv_path, "BDMV/PLAYLIST")
       # Найти самый длинный .mpls файл
       # Вернуть путь к основному видео
   ```
2. Реализовать ffmpeg_wrapper.py:
   ```bash
   # Пример команды FFmpeg для remux
   ffmpeg -i bluray:"/path/to/BDMV" -c copy -map 0 output.mkv
   ```
3. Создать processor.py с основной логикой обработки

### Фаза 6: API и Webhook (2 часа)
1. Реализовать FastAPI endpoints на NAS
2. Создать webhook handler для приема статусов от Mac
3. Реализовать file_manager.py для перемещения файлов:
   ```python
   def move_processed_file(temp_file, final_name):
       # Использовать пути из конфигурации
       base_path = os.getenv("MOVIES_BASE_PATH")
       temp_folder = os.getenv("BLURAY_TEMP_FOLDER")
       processed_folder = os.getenv("BLURAY_PROCESSED_FOLDER")
       
       # Атомарное перемещение внутри NAS
       shutil.move(
           os.path.join(base_path, temp_folder, temp_file),
           os.path.join(base_path, processed_folder, final_name)
       )
   ```
4. Коммит: `git commit -m "feat: Add API endpoints and webhook handler"`

### Фаза 7: Telegram интеграция (1 час)
1. Реализовать telegram_bot.py с командами
2. Добавить отправку уведомлений
3. Реализовать inline кнопки для управления

### Фаза 8: Web UI (2 часа)
1. Создать простой интерфейс на HTML/CSS/JS
2. Использовать Alpine.js для реактивности
3. Добавить Chart.js для графиков
4. Реализовать real-time обновления через polling

### Фаза 9: Скрипты развертывания (1 час)
1. Создать deploy-nas.sh:
   ```bash
   #!/bin/bash
   # Проверка окружения
   # Docker compose up с проверкой
   # Инициализация БД
   # Проверка здоровья сервисов
   ```
2. Аналогично для Mac mini
3. Добавить скрипты диагностики

### Фаза 10: Документация и тестирование (1 час)
1. Написать SETUP.md с пошаговой инструкцией
2. Создать USAGE.md с примерами использования
3. Заполнить TROUBLESHOOTING.md
4. Добавить unit тесты для критичных функций

## 15. Критические детали реализации

### 15.1 Анализ BDMV структуры
```python
# Типичная структура Blu-ray:
# MovieName/
#   ├── BDMV/
#   │   ├── PLAYLIST/
#   │   │   ├── 00000.mpls  # Обычно меню
#   │   │   ├── 00001.mpls  # Основной фильм (самый длинный)
#   │   │   └── 00002.mpls  # Дополнения
#   │   └── STREAM/
#   │       ├── 00000.m2ts
#   │       └── 00001.m2ts
#   └── CERTIFICATE/

# Найти основной фильм по длительности
```

### 15.2 FFmpeg команды
```bash
# Для прямого remux без перекодирования:
ffmpeg -i "bluray:/path/to/BDMV" -c:v copy -c:a copy -c:s copy output.mkv

# Альтернатива через playlist:
ffmpeg -i "/path/to/BDMV/PLAYLIST/00001.mpls" -c copy output.mkv

# С прогрессом для отслеживания:
ffmpeg -progress pipe:1 -i input -c copy output.mkv
```

### 15.3 Обработка ошибок SMB монтирования
```python
# Mac должен монтировать NAS через SMB
# Пример подключения:
mount_command = f"mount -t smbfs //{NAS_USER}:{NAS_PASS}@{NAS_IP}/video /mnt/nas"

# Обязательно проверять доступность перед работой
if not os.path.exists("/mnt/nas/Кино/BluRayRAW"):
    raise Exception("NAS not mounted")
```

### 15.4 Валидация конфигурации
Все переменные окружения должны проверяться при старте:
- IP адреса в правильном формате
- Порты в диапазоне 1-65535
- Пути существуют и доступны
- Telegram токен валидный

## 16. Критерии готовности проекта

### Обязательные deliverables:
1. ✅ Полная структура проекта со всеми файлами
2. ✅ Работающие Docker контейнеры
3. ✅ Функциональный Web UI
4. ✅ Рабочая Telegram интеграция
5. ✅ Все скрипты развертывания
6. ✅ Полная документация
7. ✅ Обработка всех описанных error cases
8. ✅ Mock режим для тестирования

### Проверочный чеклист:
- [ ] Проект запускается одной командой
- [ ] Все конфигурации через ENV переменные
- [ ] Нет hardcoded значений
- [ ] Все ошибки логируются
- [ ] Graceful shutdown работает
- [ ] Health checks отвечают
- [ ] Документация покрывает все сценарии

## 17. Финальные инструкции для LLM

### Работа с Git:
1. **Инициализируйте Git репозиторий** в самом начале работы
2. **Создайте .gitignore** со стандартными исключениями:
   ```
   .env
   *.pyc
   __pycache__/
   .DS_Store
   volumes/db/*.db
   volumes/logs/*.log
   ```
3. **Коммитьте регулярно** с осмысленными сообщениями:
   - После каждой завершенной фазы
   - После реализации важных функций
   - При исправлении ошибок
   - Используйте префиксы: `feat:`, `fix:`, `docs:`, `refactor:`
4. **Примеры коммитов**:
   ```bash
   git commit -m "feat: Initial project structure"
   git commit -m "feat: Add SQLite database schema"
   git commit -m "feat: Implement BDMV analyzer with playlist detection"
   git commit -m "fix: Handle missing BDMV structure gracefully"
   git commit -m "docs: Add deployment instructions"
   ```

### Разработка:
1. **Начните с Фазы 1** и двигайтесь последовательно
2. **Создавайте все файлы** даже если они пока пустые
3. **Используйте конфигурацию** для всех путей и настроек
4. **Комментируйте код** подробно, особенно сложные места
5. **Тестируйте логику** через mock режим где возможно
6. **Не оптимизируйте преждевременно** - сначала рабочий код
7. **При сомнениях** выбирайте более надежный вариант
8. **Логируйте все** - это поможет при отладке на реальных устройствах

### Финальная проверка:
- Все пути берутся из ENV переменных
- Каждая фаза закоммичена в Git
- Mock режим позволяет проверить основную логику
- Документация описывает все настройки

Теперь вы можете начать реализацию. Удачи!