"""
Скрипт массового импорта документов из папки import_docs/.
Сканирует файлы, создаёт записи в БД и копирует их в uploads/documents/.

Использование:
    python import_scripts/batch_import.py

Файлы должны быть в папке:
    import_docs/
        DOC-2025-001_Название_документа.pdf
        DOC-2025-002_Чертеж_вала.docx

Формат имени файла:
    DOC-YYYY-NNNN_Название_документа.расширение

Если doc_id не указан в имени — генерируется автоматически.
"""
import os
import sys
import asyncio
import re
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.repository import DocumentDatabase
from services.file_service import FileService
from config import Config


# Типы документов по расширениям и ключевым словам в имени
DOC_TYPE_RULES = {
    "чертеж": "Чертеж",
    "чертёж": "Чертеж",
    "техпроцесс": "Техпроцесс",
    "спецификация": "Спецификация",
    "инструкция": "Инструкция",
    "схема": "Схема",
    "расчет": "Расчет",
    "расчёт": "Расчет",
}

TECH_PROCESS_RULES = {
    "токар": "Токарная",
    "фрезер": "Фрезерная",
    "сверлил": "Сверлильная",
    "шлифова": "Шлифовальная",
    "свар": "Сварочная",
    "сборк": "Сборочная",
    "термич": "Термическая",
    "гальван": "Гальваническая",
}


def guess_doc_type(filename: str) -> str:
    """Определение типа документа по имени файла."""
    name_lower = filename.lower()
    for keyword, doc_type in DOC_TYPE_RULES.items():
        if keyword in name_lower:
            return doc_type
    # По расширению
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.dwg':
        return 'Чертеж'
    return 'Документ'


def guess_tech_process(filename: str) -> str:
    """Определение техпроцесса по имени файла."""
    name_lower = filename.lower()
    for keyword, tech_process in TECH_PROCESS_RULES.items():
        if keyword in name_lower:
            return tech_process
    return ''


def guess_title(filename: str) -> str:
    """Извлечение названия из имени файла."""
    # Убираем doc_id если есть
    name = re.sub(r'^DOC-\d{4}-\d{4}_', '', filename)
    # Убираем расширение
    name = os.path.splitext(name)[0]
    # Заменяем подчеркивания на пробелы
    name = name.replace('_', ' ').replace('-', ' ').strip()
    return name


def parse_doc_id(filename: str) -> str:
    """Извлечение doc_id из имени файла."""
    match = re.match(r'(DOC-\d{4}-\d{4})', filename)
    if match:
        return match.group(1)
    return ''


async def import_files():
    """Массовый импорт файлов из import_docs/ в базу данных."""
    import_dir = Path("import_docs")
    upload_dir = Path(Config.UPLOAD_DIR)

    if not import_dir.exists():
        print(f"❌ Папка {import_dir} не найдена. Создаю...")
        import_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Поместите файлы документов в папку {import_dir} и запустите скрипт снова.")
        return

    upload_dir.mkdir(parents=True, exist_ok=True)

    # Получаем список файлов
    files = list(import_dir.iterdir())
    files = [f for f in files if f.is_file() and f.suffix.lower() in Config.ALLOWED_EXTENSIONS]

    if not files:
        print(f"📁 В папке {import_dir} нет файлов с расширениями {Config.ALLOWED_EXTENSIONS}")
        print(f"   Поместите файлы в папку и запустите скрипт снова.")
        return

    # Инициализация БД
    db = DocumentDatabase()
    await db.initialize()

    print(f"\n{'='*60}")
    print(f"📥 Начинаю импорт {len(files)} файлов...")
    print(f"{'='*60}\n")

    imported = 0
    skipped = 0
    errors = 0

    for file_path in files:
        filename = file_path.name
        print(f"📄 Обрабатываю: {filename}")

        try:
            # Чтение файла
            file_size = file_path.stat().st_size
            if file_size > Config.MAX_FILE_SIZE:
                print(f"   ⚠️  Превышен размер ({file_size / 1024 / 1024:.1f} МБ > {Config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ). Пропускаю.")
                skipped += 1
                continue

            with open(file_path, "rb") as f:
                file_content = f.read()

            # Определение метаданных
            doc_id = parse_doc_id(filename)
            title = guess_title(filename)
            doc_type = guess_doc_type(filename)
            tech_process = guess_tech_process(filename)

            # Проверка на дубликат по doc_id
            if doc_id:
                existing = await db.get_document_by_id(doc_id)
                if existing:
                    print(f"   ⚠️  Документ {doc_id} уже существует. Обновляю файл...")
                    # Обновляем файл
                    file_path_saved = FileService.save_file(file_content, filename)
                    if file_path_saved:
                        await db.update_document(doc_id, {
                            "file_path": file_path_saved,
                            "file_name": filename,
                        }, user="batch_import")
                    skipped += 1
                    continue

            # Добавление документа
            data = {
                "title": title,
                "doc_type": doc_type,
                "tech_process": tech_process if tech_process else None,
                "file_name": filename,
                "tags": f"{doc_type}, imported",
            }
            if doc_id:
                data["doc_id"] = doc_id
            if tech_process:
                data["tech_process"] = tech_process

            doc = await db.add_document(
                data=data,
                file_content=file_content,
                user="batch_import"
            )

            if doc:
                print(f"   ✅ Импортирован: {doc.doc_id} — {title}")
                print(f"      📂 Тип: {doc_type} | 🔧 {tech_process or 'Не указан'} | 📎 {filename}")
                imported += 1
            else:
                print(f"   ❌ Ошибка при добавлении в БД")
                errors += 1

        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            errors += 1

    # Статистика
    print(f"\n{'='*60}")
    print(f"📊 ИТОГИ ИМПОРТА:")
    print(f"   ✅ Импортировано: {imported}")
    print(f"   ⏭️  Пропущено: {skipped}")
    print(f"   ❌ Ошибок: {errors}")
    print(f"   📦 Всего файлов: {len(files)}")
    print(f"{'='*60}")

    await db.close()


if __name__ == "__main__":
    asyncio.run(import_files())