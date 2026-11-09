# VK Callback Bot for Document Management System of a Machine-Building Enterprise

An asynchronous VK community bot for managing technical documentation. Receives events via Callback API, stores data in an SQL database, and, when configured, uses a local LLM via LM Studio.

## Functional Capabilities

### Bot Commands
| Command | Description |
|---------|-------------|
| `помощь` | Commands and examples |
| `поиск <text>` | Search by title, description, and tags |
| `умный поиск <text>` | Search expanded with synonyms via LLM |
| `фильтр тип|статус|техпроцесс <value>` | Filter documents |
| `инфо <doc_id>` | Document card |
| `скачать <doc_id>` | Send a file from the archive |
| `список [page]` | List of documents |
| `статистика` | Archive summary |
| `статус <doc_id> <status>` | Change status (administrator) |
| `добавить Название | Тип | Номер | Версия | Техпроцесс | Теги | Описание` | Add a card (administrator) |

Commands are also accepted as `/search ...`, `/help`, etc. The user's first message receives a greeting with help; arbitrary text is processed via RAG.

## Tech Stack

- **Python 3.10+**
- **aiohttp** — Callback API server and asynchronous HTTP requests
- **VK API** — community messages and file sending
- **SQLAlchemy 2.0** — ORM for working with the database
- **SQLite/PostgreSQL** — via switching `DATABASE_URL` in `.env`
- **LM Studio** — local LLM (OpenAI-compatible API)
- **aiohttp** — asynchronous HTTP requests to the LLM

## Project Architecture

```
project/
├── .env                        # Environment variables
├── .gitignore
├── requirements.txt
├── main.py                     # HTTP Callback API server
├── config.py                   # Configuration
├── database/
│   ├── __init__.py
│   ├── models.py               # SQLAlchemy models
│   ├── repository.py           # Repository (CRUD + fallback)
│   └── init_test_data.sql      # Test data
├── services/
│   ├── __init__.py
│   ├── document_service.py     # Business logic
│   ├── llm_service.py          # LLM integration
│   └── file_service.py         # File handling
├── handlers/
│   ├── __init__.py
│   └── vk_callback.py          # Callback endpoint and text commands
├── utils/
│   ├── __init__.py
│   ├── logger.py               # Logging
│   └── validators.py           # Data validation
└── uploads/documents/          # Uploaded files
```

## Installation and Launch

### 1. Cloning the Repository
```bash
git clone <repository-url>
cd docbot
```

### 2. Creating a Virtual Environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Installing Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuring .env
Fill in `.env` or copy `.env.example` (`copy .env.example .env` on Windows, `cp .env.example .env` on Linux). Enter values for the VK fields from the community's Callback API settings:
```env
# VK community access key with message and document permissions
VK_ACCESS_TOKEN=community_token
# Callback API secret and confirmation string from community settings
VK_CALLBACK_SECRET=secret_string
VK_CONFIRMATION_CODE=confirmation_string
VK_API_VERSION=5.199
# Address the bot listens on (nginx proxies here via proxy_pass)
HOST=127.0.0.1
PORT=3000
# Path VK sends events to (must match the location in nginx)
VK_CALLBACK_PATH=/

# Database (SQLite by default)
DATABASE_URL=sqlite+aiosqlite:///documents.db

# For PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/docdb

# LM Studio API (local LLM)
LLM_API_URL=http://localhost:1234/v1
LLM_MODEL=qwen-3-4b

# Maximum file size (50MB)
MAX_FILE_SIZE=52428800

# Upload directory
UPLOAD_DIR=uploads/documents
```

`VK_ACCESS_TOKEN` must be a community token with permissions for messages and documents. `VK_CALLBACK_SECRET` must match the Callback API secret key, and `VK_CONFIRMATION_CODE` must match the confirmation code shown by VK for this Callback server. Do not publish the filled-in `.env` or add it to Git.

### 5. Launching LM Studio (optional, for AI features)
1. Download and install [LM Studio](https://lmstudio.ai/)
2. Load a model (e.g., `qwen-3-4b` or `mistral-7b`)
3. Start the local server: `http://localhost:1234/v1`
4. The bot works even without an LLM, using basic search

### 6. Configuring the Community Callback API
1. Deploy the application on a server with a permanent public HTTPS address.
2. Set up an HTTPS reverse proxy to `http://127.0.0.1:8080`.
3. In VK community management, enable messages and Callback API.
4. Specify the URL `https://your-domain/` or another `VK_CALLBACK_PATH` from `.env`, the API version from `VK_API_VERSION`, the secret, and the confirmation code. The server responds to the `confirmation` event with an HTTP body containing only `VK_CONFIRMATION_CODE`; to other events it responds with `ok`.
5. Enable the `message_new` event and allow receiving messages from users.
6. Configure nginx so that `proxy_pass http://127.0.0.1:3000/;` matches `HOST`, `PORT`, and `VK_CALLBACK_PATH`.

### 7. Launching the Bot
```bash
python main.py
```

Health check: `https://your-domain/health`. The Callback API must be externally accessible via HTTPS; the built-in server listens on HTTP and does not set up TLS itself.

### 8. Initializing Test Data (optional)
After the first launch, the database is created automatically.
To load test data, run the SQL script:
```bash
# If you use SQLite — the database is already created
# To load test data use:
sqlite3 documents.db < database/init_test_data.sql
```

## Database

### Table Structure

#### documents
| Field | Type | Description |
|-------|------|-------------|
| id | SERIAL | Primary key |
| doc_id | VARCHAR(50) | Unique document ID (DOC-2024-001) |
| title | VARCHAR(255) | Document title |
| doc_type | VARCHAR(50) | Type (Drawing, Tech process...) |
| drawing_number | VARCHAR(100) | Drawing number per ESKD |
| version | VARCHAR(20) | Document version |
| tech_process | VARCHAR(100) | Tech process |
| status | VARCHAR(20) | Status (Active, Archive...) |
| file_path | VARCHAR(500) | Path to file |
| file_name | VARCHAR(255) | File name |
| tags | TEXT | Tags separated by commas |
| description | TEXT | Description |
| created_at | TIMESTAMP | Creation date |
| updated_at | TIMESTAMP | Update date |
| created_by | VARCHAR(100) | Created by |
| metadata_json | JSONB | Additional fields |

#### document_history
| Field | Type | Description |
|-------|------|-------------|
| id | SERIAL | Primary key |
| doc_id | VARCHAR(50) | Document ID (FK) |
| action | VARCHAR(50) | Action |
| old_value | TEXT | Old value |
| new_value | TEXT | New value |
| changed_at | TIMESTAMP | Change date |
| changed_by | VARCHAR(100) | Changed by |

## Security

- All database queries use parameterized queries (SQLAlchemy)
- Maximum size of a file uploaded to the archive: 50 MB
- Allowed extensions: .docx, .pdf, .dwg
- Callback secret verification and protection of data-modifying commands at the application level
- Fallback to JSON storage when the database is unavailable
- Graceful shutdown on termination

## Fault Tolerance

- When the database is unavailable, JSON storage is used (`fallback_db.json`)
- When the LLM is unavailable — basic search via SQL
- Timeout handling for LLM requests (120 sec)
- Error and exception handling in all methods

## Usage Examples

### AI Search
```
User: умный поиск вал с шпоночным пазом
Bot: 
🔍 Ищу документы...
✅ Найдено 5 документов (включая 2 по синонимам)
💡 ИИ предлагает синонимы: вал приводной, вал-шестерня, шпонка
1. DOC-2024-001 — Вал приводной редуктора (Активен)
...
🏆 Наиболее релевантный: DOC-2024-001
```

### Adding a Document Card
```
User: добавить Вал редуктора | Чертеж | АБВГ.123.001 | 1.0 | Токарная | вал, редуктор | Вал приводной
Bot: Документ добавлен: DOC-2026-1234 — Вал редуктора
```

### Free-form Query
```
User: покажи чертежи по фрезеровке
Bot: 🔍 Анализирую запрос...
Найдено 3 чертежа, связанных с фрезерной обработкой:
...
```

## Environment Requirements

- Python 3.10 or higher
- For PostgreSQL: `pip install asyncpg`
- VK community with messages and Callback API enabled
- Public HTTPS domain and reverse proxy to the application port
- LM Studio (optional, for AI features)

---

# VK Callback-бот для системы документооборота машиностроительного предприятия

Асинхронный бот сообщества VK для управления технической документацией. Получает события через Callback API, хранит данные в SQL базе и при настройке использует локальную LLM через LM Studio.

## Функциональные возможности

### Команды бота
| Команда | Описание |
|---------|----------|
| `помощь` | Команды и примеры |
| `поиск <текст>` | Поиск по названию, описанию и тегам |
| `умный поиск <текст>` | Поиск с расширением синонимами через LLM |
| `фильтр тип|статус|техпроцесс <значение>` | Фильтрация документов |
| `инфо <doc_id>` | Карточка документа |
| `скачать <doc_id>` | Отправить файл из архива |
| `список [страница]` | Список документов |
| `статистика` | Сводка архива |
| `статус <doc_id> <статус>` | Изменить статус (администратор) |
| `добавить Название | Тип | Номер | Версия | Техпроцесс | Теги | Описание` | Добавить карточку (администратор) |

Команды также принимаются в виде `/search ...`, `/help` и т.п. Первое сообщение пользователя получает приветствие со справкой; произвольный текст обрабатывается через RAG.

## Технический стек

- **Python 3.10+**
- **aiohttp** — сервер Callback API и асинхронные HTTP-запросы
- **VK API** — сообщения сообщества и отправка файлов
- **SQLAlchemy 2.0** — ORM для работы с БД
- **SQLite/PostgreSQL** — через переключение `DATABASE_URL` в `.env`
- **LM Studio** — локальная LLM (OpenAI-совместимый API)
- **aiohttp** — асинхронные HTTP запросы к LLM

## Архитектура проекта

```
project/
├── .env                        # Переменные окружения
├── .gitignore
├── requirements.txt
├── main.py                     # HTTP-сервер Callback API
├── config.py                   # Конфигурация
├── database/
│   ├── __init__.py
│   ├── models.py               # SQLAlchemy модели
│   ├── repository.py           # Репозиторий (CRUD + fallback)
│   └── init_test_data.sql      # Тестовые данные
├── services/
│   ├── __init__.py
│   ├── document_service.py     # Бизнес-логика
│   ├── llm_service.py          # Работа с LLM
│   └── file_service.py         # Работа с файлами
├── handlers/
│   ├── __init__.py
│   └── vk_callback.py          # Callback endpoint и текстовые команды
├── utils/
│   ├── __init__.py
│   ├── logger.py               # Логирование
│   └── validators.py           # Валидация данных
└── uploads/documents/          # Загруженные файлы
```

## Установка и запуск

### 1. Клонирование репозитория
```bash
git clone <url-репозитория>
cd docbot
```

### 2. Создание виртуального окружения
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Настройка .env
Заполните `.env` или скопируйте `.env.example` (`copy .env.example .env` в Windows, `cp .env.example .env` в Linux). В VK-поля внесите значения из настроек Callback API сообщества:
```env
# Ключ доступа сообщества VK с правами на сообщения и документы
VK_ACCESS_TOKEN=токен_сообщества
# Секрет Callback API и строка подтверждения из настроек сообщества
VK_CALLBACK_SECRET=секретная_строка
VK_CONFIRMATION_CODE=строка_подтверждения
VK_API_VERSION=5.199
# Адрес, на котором слушает бот (nginx проксирует сюда через proxy_pass)
HOST=127.0.0.1
PORT=3000
# Путь, на который ВК шлёт события (должен совпадать с location в nginx)
VK_CALLBACK_PATH=/

# База данных (SQLite по умолчанию)
DATABASE_URL=sqlite+aiosqlite:///documents.db

# Для PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/docdb

# LM Studio API (локальная LLM)
LLM_API_URL=http://localhost:1234/v1
LLM_MODEL=qwen-3-4b

# Максимальный размер файла (50MB)
MAX_FILE_SIZE=52428800

# Директория для загрузок
UPLOAD_DIR=uploads/documents
```

`VK_ACCESS_TOKEN` должен быть токеном сообщества с разрешениями на сообщения и документы. `VK_CALLBACK_SECRET` должен совпадать с секретным ключом Callback API, а `VK_CONFIRMATION_CODE` — с кодом подтверждения, показанным VK для этого Callback-сервера. Не публикуйте заполненный `.env` и не добавляйте его в Git.

### 5. Запуск LM Studio (опционально, для работы с ИИ)
1. Скачайте и установите [LM Studio](https://lmstudio.ai/)
2. Загрузите модель (например, `qwen-3-4b` или `mistral-7b`)
3. Запустите локальный сервер: `http://localhost:1234/v1`
4. Бот будет работать и без LLM, используя базовый поиск

### 6. Настройка Callback API сообщества
1. Разверните приложение на сервере с постоянным публичным HTTPS-адресом.
2. Настройте reverse proxy с HTTPS на `http://127.0.0.1:8080`.
3. В управлении сообществом VK включите сообщения и Callback API.
4. Укажите URL `https://ваш-домен/` или другой `VK_CALLBACK_PATH` из `.env`, версию API из `VK_API_VERSION`, секрет и код подтверждения. На событие `confirmation` сервер отвечает телом HTTP-ответа, содержащим только `VK_CONFIRMATION_CODE`; на остальные события отвечает текстом `ok`.
5. Включите событие `message_new` и разрешите получение сообщений от пользователей.
6. Настройте nginx так, чтобы `proxy_pass http://127.0.0.1:3000/;` совпадал с `HOST`, `PORT` и `VK_CALLBACK_PATH`.

### 7. Запуск бота
```bash
python main.py
```

Проверка доступности: `https://ваш-домен/health`. Callback API должен быть доступен извне по HTTPS; встроенный сервер слушает HTTP и не настраивает TLS самостоятельно.

### 8. Инициализация тестовых данных (опционально)
После первого запуска база данных создаётся автоматически.
Для загрузки тестовых данных выполните SQL скрипт:
```bash
# Если используете SQLite — база уже создана
# Для загрузки тестовых данных используйте:
sqlite3 documents.db < database/init_test_data.sql
```

## База данных

### Структура таблиц

#### documents
| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL | Первичный ключ |
| doc_id | VARCHAR(50) | Уникальный ID документа (DOC-2024-001) |
| title | VARCHAR(255) | Название документа |
| doc_type | VARCHAR(50) | Тип (Чертеж, Техпроцесс...) |
| drawing_number | VARCHAR(100) | Номер чертежа по ЕСКД |
| version | VARCHAR(20) | Версия документа |
| tech_process | VARCHAR(100) | Техпроцесс |
| status | VARCHAR(20) | Статус (Активен, Архивный...) |
| file_path | VARCHAR(500) | Путь к файлу |
| file_name | VARCHAR(255) | Имя файла |
| tags | TEXT | Теги через запятую |
| description | TEXT | Описание |
| created_at | TIMESTAMP | Дата создания |
| updated_at | TIMESTAMP | Дата обновления |
| created_by | VARCHAR(100) | Кто создал |
| metadata_json | JSONB | Доп. поля |

#### document_history
| Поле | Тип | Описание |
|------|-----|----------|
| id | SERIAL | Первичный ключ |
| doc_id | VARCHAR(50) | ID документа (FK) |
| action | VARCHAR(50) | Действие |
| old_value | TEXT | Старое значение |
| new_value | TEXT | Новое значение |
| changed_at | TIMESTAMP | Дата изменения |
| changed_by | VARCHAR(100) | Кто изменил |

## Безопасность

- Все запросы к БД — через параметризованные запросы (SQLAlchemy)
- Максимальный размер загружаемого в архив файла: 50МБ
- Допустимые расширения: .docx, .pdf, .dwg
- Проверка Callback-секрета и защита команд изменения данных на уровне приложения
- Fallback на JSON-хранилище при недоступности БД
- Graceful shutdown при завершении

## Отказоустойчивость

- При недоступности БД используется JSON-хранилище (`fallback_db.json`)
- При недоступности LLM — базовый поиск через SQL
- Обработка таймаутов при запросах к LLM (120 сек)
- Обработка ошибок и исключений во всех методах

## Примеры использования

### Поиск с ИИ
```
User: умный поиск вал с шпоночным пазом
Bot: 
🔍 Ищу документы...
✅ Найдено 5 документов (включая 2 по синонимам)
💡 ИИ предлагает синонимы: вал приводной, вал-шестерня, шпонка
1. DOC-2024-001 — Вал приводной редуктора (Активен)
...
🏆 Наиболее релевантный: DOC-2024-001
```

### Добавление карточки документа
```
User: добавить Вал редуктора | Чертеж | АБВГ.123.001 | 1.0 | Токарная | вал, редуктор | Вал приводной
Bot: Документ добавлен: DOC-2026-1234 — Вал редуктора
```

### Свободный запрос
```
User: покажи чертежи по фрезеровке
Bot: 🔍 Анализирую запрос...
Найдено 3 чертежа, связанных с фрезерной обработкой:
...
```

## Требования к окружению

- Python 3.10 или выше
- Для PostgreSQL: `pip install asyncpg`
- Сообщество VK с включёнными сообщениями и Callback API
- Публичный HTTPS-домен и reverse proxy до порта приложения
- LM Studio (опционально, для работы с ИИ)