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

The document list is paginated (8 documents per page); buttons use document titles, falling back to IDs when a title is missing. The Back button returns to the current list page. A document card remains viewable when its file is missing, but downloading is offered only when the file exists on the server.

At startup, the bot scans the top level of `IMPORT_DIR` for `.docx`, `.pdf`, `.dwg`, and `.xlsx` files. Duplicate imports are skipped, and existing records with missing paths can be relinked when the corresponding file is present. Files must remain available on the server for download.

Free-form queries use the configured LLM with retrieved document context when available. If the LLM request fails or times out, the bot falls back to a basic search response; it does not retry the same LLM request automatically.

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
│   ├── vk_api.py               # VK API client and file transfers
│   └── file_service.py         # File validation and storage
├── handlers/
│   ├── __init__.py
│   └── vk_callback.py          # Callback endpoint and text commands
├── import_docs/                # Files indexed during startup
├── uploads/documents/          # Uploaded files
├── utils/
│   ├── __init__.py
│   ├── logger.py               # Logging
│   └── validators.py           # Data validation
```

## How the bot works

1. **Startup (`main.py`)** — loads configuration, checks required VK settings, initializes the database and services, checks LM Studio, repairs known file paths, and imports supported files from `IMPORT_DIR`.
2. **VK Callback (`handlers/vk_callback.py`)** — validates the callback request and secret. For a `message_new` event, it schedules message processing and acknowledges the callback with `ok`.
3. **Message routing** — `process_message` distinguishes uploads, keyboard payloads, commands, list navigation, and free-form text. Button actions and text commands are routed to their respective handlers.
4. **Document search (`services/document_service.py`)** — searches the database and removes duplicate folder-import entries. Smart search may ask the LLM for synonyms when the initial result set is small.
5. **LLM response (`services/llm_service.py`)** — free-form questions are sent to the configured OpenAI-compatible endpoint with context from up to five matched documents. If the LLM is unavailable or times out, the bot returns a fallback response; the next user request can try the LLM again.
6. **Document delivery (`services/vk_api.py`)** — for a downloadable file, the bot reads the local bytes, requests a VK upload URL, uploads the file, saves it with `docs.save`, then sends the attachment with `messages.send`.
7. **Shutdown** — closes the VK and LLM HTTP sessions and database resources.

The main responsibilities are separated: `main.py` starts services; `handlers/` handles VK events and user state; `services/` contains document, file, LLM, and VK API logic; `database/repository.py` stores and searches records.

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

# Folder scanned for documents on startup
IMPORT_DIR=import_docs
```

`VK_ACCESS_TOKEN` must be a community token with permissions for messages and documents. `VK_CALLBACK_SECRET` must match the Callback API secret key, and `VK_CONFIRMATION_CODE` must match the confirmation code shown by VK for this Callback server. Do not publish the filled-in `.env` or add it to Git.
The bot indexes supported files from `IMPORT_DIR` on startup. The configured `LLM_API_URL` must be reachable from the bot server; use `localhost` only when LM Studio runs on that same machine.
For VK credential and connection troubleshooting, see [Possible VK API errors](#possible-vk-api-errors).

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

## Possible VK API errors

Document sending makes sequential VK calls: `docs.getMessagesUploadServer` → file upload → `docs.save` → `messages.send`. The client uses a 20-second HTTP timeout and does **not** retry failed requests automatically.

| What you see | Likely meaning | What to check |
|---|---|---|
| `15 Access denied` on `docs.getMessagesUploadServer` | VK rejected the active token for this method; this is an access/scope error, not a connection timeout. | Verify that the running process uses the newly issued token, the token belongs to the intended community, and its Documents permission is enabled. Process environment variables override `.env`; restart the bot after updating the token. Never share the token in logs or chat. |
| Connection timeout, DNS, SSL, or connector error | The server could not complete an HTTPS request to VK or its upload host in time. | Check outbound HTTPS, DNS, firewall/proxy settings, server logs, and VK service availability. Retry the request after connectivity is restored. |
| HTTP error while uploading or saving a document | VK or the upload endpoint returned an unsuccessful HTTP response. | Use the logged exception to identify whether the failure occurred during the API call, file upload, save, or message send. Check network stability and retry once the endpoint is available. |
| Document card is visible but there is no download option | The record exists, but its file is not present at the recorded server path. | Restore the file to the server or place it back in the configured import/upload directory; a database record alone cannot recreate missing file contents. |

VK API errors include the method and VK error code in the server log. Network exceptions are logged by the message handler. There is no automatic retry or guaranteed delivery after a transient failure.

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
- Allowed extensions: .docx, .pdf, .dwg, .xlsx
- Callback secret verification and protection of data-modifying commands at the application level
- Fallback to JSON storage when the database is unavailable
- Graceful shutdown on termination

## Fault Tolerance

- When the database is unavailable, JSON storage is used (`fallback_db.json`)
- When the LLM is unavailable — basic search via SQL
- Timeout handling for LLM requests (120 sec)
- VK API requests and file uploads use a 20-second HTTP timeout; failed requests are not retried automatically
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

Список документов разбит на страницы по 8 записей; в кнопках отображаются названия документов, а при отсутствии названия — ID. Кнопка «Назад» возвращает на текущую страницу списка. Карточку можно открыть и для документа без файла, но кнопка скачивания показывается только если файл доступен на сервере.

При запуске бот просматривает файлы верхнего уровня `IMPORT_DIR` с расширениями `.docx`, `.pdf`, `.dwg` и `.xlsx`. Повторный импорт тех же файлов пропускается; существующие записи с потерянным путём к файлу могут быть связаны с найденным файлом. Для скачивания файлы должны оставаться доступными на сервере.

Свободные запросы при настроенной LLM обрабатываются с контекстом найденных документов. Если запрос к LLM завершается ошибкой или таймаутом, бот использует базовый ответ по результатам поиска; автоматического повтора того же запроса к LLM нет.

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
│   ├── vk_api.py               # Клиент VK API и передача файлов
│   └── file_service.py         # Проверка и хранение файлов
├── handlers/
│   ├── __init__.py
│   └── vk_callback.py          # Callback endpoint и текстовые команды
├── import_docs/                # Файлы для индексации при запуске
├── uploads/documents/          # Загруженные файлы
├── utils/
│   ├── __init__.py
│   ├── logger.py               # Логирование
│   └── validators.py           # Валидация данных
```

## Как работает бот: поток обработки

1. **Запуск (`main.py`)** — загружает конфигурацию, проверяет обязательные настройки VK, инициализирует базу и сервисы, проверяет LM Studio, восстанавливает известные пути к файлам и импортирует поддерживаемые документы из `IMPORT_DIR`.
2. **Callback VK (`handlers/vk_callback.py`)** — проверяет входящий запрос и секрет. Для события `message_new` запускает обработку сообщения в отдельной задаче и подтверждает Callback ответом `ok`.
3. **Маршрутизация сообщения** — `process_message` различает загрузку файла, действия кнопок, команды, навигацию по списку и обычный текст. Действия кнопок и команды передаются соответствующим обработчикам.
4. **Поиск документов (`services/document_service.py`)** — ищет записи в базе и удаляет дубликаты импортов из папки. Умный поиск может запросить у LLM синонимы, если первоначально найдено мало документов.
5. **Ответ LLM (`services/llm_service.py`)** — свободный вопрос отправляется в настроенный OpenAI-совместимый API вместе с контекстом до пяти найденных документов. При недоступности или таймауте LLM бот формирует резервный ответ; следующий запрос пользователя может снова обратиться к LLM.
6. **Отправка документа (`services/vk_api.py`)** — бот читает файл с сервера, запрашивает у VK адрес загрузки, загружает файл, сохраняет через `docs.save`, затем отправляет вложение методом `messages.send`.
7. **Завершение** — закрываются HTTP-сессии VK и LLM и ресурсы базы данных.

Зоны ответственности разделены: `main.py` запускает сервисы; `handlers/` обрабатывает события VK и состояние диалога; `services/` содержит логику документов, файлов, LLM и VK API; `database/repository.py` сохраняет записи и выполняет поиск.

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

# Папка, из которой документы индексируются при запуске
IMPORT_DIR=import_docs
```

`VK_ACCESS_TOKEN` должен быть токеном сообщества с разрешениями на сообщения и документы. `VK_CALLBACK_SECRET` должен совпадать с секретным ключом Callback API, а `VK_CONFIRMATION_CODE` — с кодом подтверждения, показанным VK для этого Callback-сервера. Не публикуйте заполненный `.env` и не добавляйте его в Git.
При запуске бот индексирует поддерживаемые файлы из `IMPORT_DIR`. Адрес `LLM_API_URL` должен быть доступен с сервера бота; `localhost` подходит только если LM Studio запущена на той же машине.
Подробные рекомендации по токену и ошибкам соединения приведены в разделе [Возможные ошибки VK API](#возможные-ошибки-vk-api).

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

## Возможные ошибки VK API

Отправка документа выполняется последовательными запросами VK: `docs.getMessagesUploadServer` → загрузка файла → `docs.save` → `messages.send`. Для запросов и загрузки действует HTTP-таймаут 20 секунд; автоматического повтора неудачных запросов нет.

| Что наблюдается | Что это обычно означает | Что проверить |
|---|---|---|
| `15 Access denied` при `docs.getMessagesUploadServer` | VK отклонил активный токен для этого метода; это отказ доступа/прав, а не таймаут соединения. | Убедитесь, что процесс использует новый токен, токен создан для нужного сообщества и у него включено разрешение «Документы». Переменные окружения процесса имеют приоритет над `.env`; после обновления токена перезапустите бота. Не публикуйте токен в логах или переписке. |
| Таймаут, ошибка DNS, SSL или подключения | Сервер не смог вовремя выполнить HTTPS-запрос к VK или серверу загрузки. | Проверьте исходящий HTTPS, DNS, firewall/proxy, логи сервера и доступность VK. После восстановления связи повторите запрос. |
| HTTP-ошибка при загрузке или сохранении документа | VK или сервер загрузки вернул неуспешный HTTP-ответ. | По исключению в серверном логе определите этап сбоя: API-вызов, загрузка файла, сохранение или отправка сообщения. Проверьте сеть и повторите запрос после восстановления сервиса. |
| Карточка документа есть, но скачать файл нельзя | Запись есть в базе, но файла нет по сохранённому серверному пути. | Верните файл на сервер или в настроенную папку импорта/загрузки: одной записи базы недостаточно, чтобы восстановить содержимое. |

Ошибки VK API содержат в серверном логе название метода и код VK. Сетевые исключения логируются обработчиком сообщения. Автоматических повторов и гарантированной доставки при временном сбое нет.

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
- Допустимые расширения: .docx, .pdf, .dwg, .xlsx
- Проверка Callback-секрета и защита команд изменения данных на уровне приложения
- Fallback на JSON-хранилище при недоступности БД
- Graceful shutdown при завершении

## Отказоустойчивость

- При недоступности БД используется JSON-хранилище (`fallback_db.json`)
- При недоступности LLM — базовый поиск через SQL
- Обработка таймаутов при запросах к LLM (120 сек)
- Для запросов к VK API и загрузки файлов действует HTTP-таймаут 20 секунд; автоматических повторов нет
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