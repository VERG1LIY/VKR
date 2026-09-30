"""
Настройка логирования для приложения.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(name: str = "docbot") -> logging.Logger:
    """
    Настройка и получение логгера.

    Args:
        name: Имя логгера.

    Returns:
        Настроенный логгер.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    # Формат логов
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Вывод в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Вывод в файл
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass  # Если нет папки logs, просто пишем в консоль

    return logger


# Глобальный логгер
logger = setup_logger()