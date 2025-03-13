# Вспомогательные функции, которые могут понадобиться в разных частях приложенияimport os
import os
from config import PHOTOS_DIR
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

def ensure_photos_dir():
    if not os.path.exists(PHOTOS_DIR):
        os.makedirs(PHOTOS_DIR)

async def notify_admin(bot, request_id, requests_data, admin_ids):
    request = requests_data[request_id]
    location = request.get('location', {})
    
    if isinstance(location, dict) and 'latitude' in location and 'longitude' in location:
        latitude = location['latitude']
        longitude = location['longitude']
        location_link = f"https://yandex.ru/maps?whatshere%5Bpoint%5D={longitude}%2C{latitude}&"
    else:
        location_link = "Местоположение не указано"

    message = (
        f"Новая заявка #{request_id}\n"
        f"Клиент: {request.get('user_name', 'Неизвестный')}\n"
        f"Описание: {request.get('description', 'Нет описания')}\n"
        f"Статус: {request.get('status', 'Не указан')}\n"
        f"Местоположение: {location_link}\n"
    )
    keyboard = [[InlineKeyboardButton("Привязать к СЦ", callback_data=f"assign_sc_{request_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=message, reply_markup=reply_markup)
        except Exception as e:
            print(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

            
async def notify_delivery(bot, delivery_id, task_id, request_id, sc_name):
    message = (
        f"Новая задача доставки!\n\n"
        f"Задача №: {task_id}\n"
        f"Заявка №: {request_id}\n"
        f"СЦ: {sc_name}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("Просмотреть задачу", callback_data=f"view_task_{task_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await bot.send_message(chat_id=delivery_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        print(f"Не удалось отправить уведомление доставщику {delivery_id}: {e}")

async def notify_client(bot, client_id, message, reply_markup=None):
    try:
        await bot.send_message(chat_id=client_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error notifying client {client_id}: {e}")