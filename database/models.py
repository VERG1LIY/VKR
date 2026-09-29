"""
Модели базы данных для системы документооборота.
Используется SQLAlchemy ORM.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    DateTime, ForeignKey, JSON, Index, BigInteger
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Document(Base):
    """Модель документа технической документации."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(50), unique=True, nullable=False, comment="Уникальный ID документа, например DOC-2024-001")
    title = Column(String(255), nullable=False, comment="Название документа")
    doc_type = Column(String(50), comment="Тип документа: Чертеж, Техпроцесс, Спецификация и т.д.")
    drawing_number = Column(String(100), comment="Номер чертежа по ЕСКД")
    version = Column(String(20), comment="Версия документа")
    tech_process = Column(String(100), comment="Техпроцесс: токарная, фрезерная, сборка...")
    status = Column(String(20), default="Активен", comment="Статус: Активен, Архивный, В работе, Отменен")
    file_path = Column(String(500), comment="Путь к файлу на диске")
    file_name = Column(String(255), comment="Оригинальное имя файла")
    tags = Column(Text, comment="Теги через запятую")
    description = Column(Text, comment="Описание документа")
    created_at = Column(DateTime, default=datetime.utcnow, comment="Дата создания")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="Дата обновления")
    created_by = Column(String(100), comment="Кто создал документ")
    metadata_json = Column(JSON, comment="Дополнительные поля в формате JSON")

    # Связь с историей изменений
    history = relationship("DocumentHistory", back_populates="document", cascade="all, delete-orphan")

    # Индексы для ускорения поиска
    __table_args__ = (
        Index("idx_doc_id", "doc_id"),
        Index("idx_status", "status"),
        Index("idx_tech_process", "tech_process"),
        Index("idx_doc_type", "doc_type"),
    )

    def __repr__(self):
        return f"<Document(doc_id='{self.doc_id}', title='{self.title}', status='{self.status}')>"

    def to_dict(self):
        """Преобразование модели в словарь."""
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type,
            "drawing_number": self.drawing_number,
            "version": self.version,
            "tech_process": self.tech_process,
            "status": self.status,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "tags": self.tags,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
            "metadata_json": self.metadata_json,
        }


class DocumentHistory(Base):
    """Модель истории изменений документов."""

    __tablename__ = "document_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(50), ForeignKey("documents.doc_id"), nullable=False, comment="ID документа")
    action = Column(String(50), nullable=False, comment="Действие: CREATE, UPDATE_STATUS, UPDATE_VERSION, DELETE")
    old_value = Column(Text, comment="Старое значение")
    new_value = Column(Text, comment="Новое значение")
    changed_at = Column(DateTime, default=datetime.utcnow, comment="Дата изменения")
    changed_by = Column(String(100), comment="Кто изменил")

    # Связь с документом
    document = relationship("Document", back_populates="history")

    def __repr__(self):
        return f"<DocumentHistory(doc_id='{self.doc_id}', action='{self.action}')>"


class User(Base):
    """Модель пользователя для авторизации."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, comment="Telegram ID пользователя")
    username = Column(String(100), comment="Имя пользователя в Telegram")
    full_name = Column(String(200), comment="Полное имя")
    role = Column(String(50), default="user", comment="Роль: admin, engineer, technologist")
    is_active = Column(Boolean, default=True, comment="Активен ли пользователь")
    created_at = Column(DateTime, default=datetime.utcnow, comment="Дата регистрации")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, username='{self.username}', role='{self.role}')>"


class VKUser(Base):
    """Пользователь VK, которому уже отправлялось стартовое приветствие."""

    __tablename__ = "vk_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vk_id = Column(BigInteger, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<VKUser(vk_id={self.vk_id})>"


