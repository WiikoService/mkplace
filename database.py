import os
from async_lru import alru_cache
from config import (
    USERS_JSON,
    REQUESTS_JSON,
    SERVICE_CENTERS_JSON,
    DELIVERY_TASKS_JSON,
    DATA_DIR,
    PAYMENT_JSON
)
import logging
import aiofiles
import orjson
from asyncio import Lock
import shutil

logger = logging.getLogger(__name__)

# Блокировки для атомарных операций
save_lock = Lock()
backup_lock = Lock()

def ensure_data_dir():
    """Проверка и создание директории данных"""
    os.makedirs(DATA_DIR, exist_ok=True)

async def ensure_json_file(filename):
    """Создает JSON файл, если он не существует"""
    if not os.path.exists(filename):
        async with save_lock:
            async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                await f.write(orjson.dumps({}).decode('utf-8'))

async def create_backup(filename):
    """Создает резервную копию файла"""
    async with backup_lock:
        if os.path.exists(filename):
            backup_name = f"{filename}.bak"
            shutil.copy2(filename, backup_name)

# Базовые функции с оптимизированным кешированием
@alru_cache(maxsize=32, ttl=30)
async def load_json(filename):
    """Загружает JSON с кешированием и автоматическим созданием файла"""
    await ensure_json_file(filename)
    try:
        async with aiofiles.open(filename, 'r', encoding='utf-8') as file:
            content = await file.read()
            return orjson.loads(content)
    except (FileNotFoundError, orjson.JSONDecodeError) as e:
        logger.warning(f"Error loading {filename}: {e}")
        return {}

async def save_json(data, filename):
    """Атомарное сохранение JSON с резервной копией"""
    async with save_lock:
        await create_backup(filename)
        load_json.cache_clear()
        try:
            async with aiofiles.open(filename, 'w', encoding='utf-8') as file:
                await file.write(orjson.dumps(data).decode('utf-8'))
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            raise

# Специализированные функции загрузки
@alru_cache(maxsize=32, ttl=120)  # Реже изменяемые данные
async def load_users():
    return await load_json(USERS_JSON)

@alru_cache(maxsize=64, ttl=20)  # Часто изменяемые данные
async def load_requests():
    return await load_json(REQUESTS_JSON)

@alru_cache(maxsize=16, ttl=300)  # Очень редко изменяемые данные
async def load_service_centers():
    return await load_json(SERVICE_CENTERS_JSON)

@alru_cache(maxsize=64, ttl=20)  # Часто изменяемые данные
async def load_delivery_tasks():
    return await load_json(DELIVERY_TASKS_JSON)

@alru_cache(maxsize=32, ttl=60)  # Средняя частота изменений
async def load_payment():
    return await load_json(PAYMENT_JSON)

# Специализированные функции сохранения
async def save_users(users_data):
    load_users.cache_clear()
    await save_json(users_data, USERS_JSON)

async def save_requests(requests_data):
    load_requests.cache_clear()
    await save_json(requests_data, REQUESTS_JSON)

async def save_service_centers(service_centers_data):
    load_service_centers.cache_clear()
    await save_json(service_centers_data, SERVICE_CENTERS_JSON)

async def save_delivery_tasks(delivery_tasks):
    load_delivery_tasks.cache_clear()
    await save_json(delivery_tasks, DELIVERY_TASKS_JSON)

async def save_payment(payment_data):
    load_payment.cache_clear()
    await save_json(payment_data, PAYMENT_JSON)

# Чат-история с отдельной логикой
async def ensure_chat_history_file():
    if not os.path.exists(CHAT_HISTORY_FILE):
        async with save_lock:
            async with aiofiles.open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
                await f.write(orjson.dumps({}).decode('utf-8'))

@alru_cache(maxsize=32, ttl=10)  # Быстрое обновление чата
async def load_chat_history():
    await ensure_chat_history_file()
    try:
        async with aiofiles.open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            return orjson.loads(content)
    except Exception as e:
        logger.error(f"Chat history load error: {e}")
        return {}

async def save_chat_history(chat_history):
    async with save_lock:
        load_chat_history.cache_clear()
        try:
            async with aiofiles.open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
                await f.write(orjson.dumps(chat_history).decode('utf-8'))
        except Exception as e:
            logger.error(f"Chat history save error: {e}")
