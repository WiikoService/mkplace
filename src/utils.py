import os
import uuid
from datetime import datetime
import logging
from typing import List, Optional
from telegram import Bot, Update, Message

logger = logging.getLogger(__name__)


async def save_photo(message: Message, photos_dir: str) -> Optional[str]:
    """Сохраняет фото из сообщения и возвращает путь к файлу"""
    try:
        # Создаем директорию, если она не существует
        os.makedirs(photos_dir, exist_ok=True)
        # Получаем фото с наилучшим качеством
        photo = message.photo[-1]
        file_id = photo.file_id
        # Генерируем уникальное имя файла
        file_name = f"{uuid.uuid4()}.jpg"
        file_path = os.path.join(photos_dir, file_name)
        # Скачиваем и сохраняем фото
        file = await message.bot.get_file(file_id)
        await file.download_to_drive(file_path)
        return file_path
    except Exception as e:
        logger.error(f"Ошибка при сохранении фото: {e}")
        return None

def format_datetime(dt: datetime) -> str:
    """Форматирует дату и время в удобный для отображения формат"""
    return dt.strftime("%d.%m.%Y %H:%M")

def get_next_id(current_ids: List[str]) -> str:
    """Генерирует следующий ID на основе существующих"""
    if not current_ids:
        return "1"
    try:
        # Пытаемся преобразовать все ID в числа и найти максимальное
        numeric_ids = [int(id_str) for id_str in current_ids if id_str.isdigit()]
        if numeric_ids:
            return str(max(numeric_ids) + 1)
        else:
            return "1"
    except Exception:
        # Если не удалось преобразовать в числа, генерируем UUID
        return str(uuid.uuid4())
