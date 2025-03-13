import json
import os
from config import USERS_JSON, REQUESTS_JSON, SERVICE_CENTERS_JSON, DELIVERY_TASKS_JSON

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
    file_path = 'data/delivery_tasks.json'
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"Error decoding JSON from {file_path}. File might be empty or contain invalid JSON.")
        return {}
    except Exception as e:
        print(f"Error loading delivery tasks: {e}")
        return {}

def save_delivery_tasks(tasks):
    with open(DELIVERY_TASKS_JSON, 'w') as file:
        json.dump(tasks, file, indent=4)