import json
import asyncio
import aiofiles
from async_lru import alru_cache
from typing import Dict, Any, Optional
import os
import logging

logger = logging.getLogger(__name__)


class JsonStorage:
    """Класс для асинхронной работы с JSON-файлами с кэшированием и блокировками"""

    _instances = {}  # Словарь для хранения экземпляров по пути к файлу

    @classmethod
    def get_instance(cls, file_path: str) -> 'JsonStorage':
        """Получение единственного экземпляра хранилища для каждого файла"""
        if file_path not in cls._instances:
            cls._instances[file_path] = cls(file_path)
        return cls._instances[file_path]

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lock = asyncio.Lock()
        self._cache = {}
        self._cache_valid = False
        # Создаем директорию, если она не существует
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    @alru_cache(maxsize=1)
    async def load(self) -> Dict[str, Any]:
        """Загрузка данных из JSON-файла с кэшированием"""
        if self._cache_valid:
            return self._cache
        try:
            # Проверяем существование файла
            if not os.path.exists(self.file_path):
                # Создаем пустой файл
                async with aiofiles.open(self.file_path, 'w', encoding='utf-8') as file:
                    await file.write('{}')
                return {}
            async with aiofiles.open(self.file_path, 'r', encoding='utf-8') as file:
                content = await file.read()
                if not content:
                    return {}
                data = json.loads(content)
                self._cache = data
                self._cache_valid = True
                return data
        except json.JSONDecodeError:
            logger.error(f"Ошибка декодирования JSON в файле {self.file_path}")
            return {}
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных из {self.file_path}: {e}")
            return {}

    async def save(self, data: Dict[str, Any]) -> None:
        """Сохранение данных в JSON-файл с блокировкой"""
        async with self.lock:
            try:
                async with aiofiles.open(self.file_path, 'w', encoding='utf-8') as file:
                    await file.write(json.dumps(data, ensure_ascii=False, indent=4))
                self._cache = data
                self._cache_valid = True
                # Инвалидация кэша для метода load
                self.load.cache_invalidate()
            except Exception as e:
                logger.error(f"Ошибка при сохранении данных в {self.file_path}: {e}")

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Получение элемента по ключу"""
        data = await self.load()
        return data.get(key)

    async def set(self, key: str, value: Dict[str, Any]) -> None:
        """Установка значения по ключу"""
        data = await self.load()
        data[key] = value
        await self.save(data)

    async def delete(self, key: str) -> None:
        """Удаление элемента по ключу"""
        data = await self.load()
        if key in data:
            del data[key]
            await self.save(data)

    async def clear_cache(self) -> None:
        """Очистка кэша"""
        self._cache_valid = False
        self.load.cache_clear()
