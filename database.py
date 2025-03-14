import json
import os
from config import USERS_JSON, REQUESTS_JSON, SERVICE_CENTERS_JSON, DELIVERY_TASKS_JSON
import logging

logger = logging.getLogger(__name__)

def load_json(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}  # Возвращаем пустой словарь, если файл не найден или пуст

def save_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

def load_users():
    return load_json(USERS_JSON)

def save_users(users_data):
    save_json(users_data, USERS_JSON)

def load_requests():
    return load_json(REQUESTS_JSON)

def save_requests(requests_data):
    save_json(requests_data, REQUESTS_JSON)

def load_service_centers():
    return load_json(SERVICE_CENTERS_JSON)

def save_service_centers(service_centers_data):
    save_json(service_centers_data, SERVICE_CENTERS_JSON)

def load_delivery_tasks():
    """Загрузка задач доставки с правильной кодировкой"""
    from config import DELIVERY_TASKS_JSON
    try:
        with open(DELIVERY_TASKS_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Error loading delivery tasks: {e}")
        return {}

def save_delivery_tasks(delivery_tasks):
    """Сохранение задач доставки с правильной кодировкой"""
    try:
        with open(DELIVERY_TASKS_JSON, 'w', encoding='utf-8') as f:
            json.dump(delivery_tasks, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving delivery tasks: {e}")
        raise