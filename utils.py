# Вспомогательные функции, которые могут понадобиться в разных частях приложенияimport os
import os
from config import PHOTOS_DIR
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import logging
from typing import Union

logger = logging.getLogger(__name__)

def ensure_photos_dir():
    if not os.path.exists(PHOTOS_DIR):
        os.makedirs(PHOTOS_DIR)

async def notify_admin(bot, request_id, requests_data, admin_ids):
    request = requests_data[request_id]
    location = request.get('location', None)
    if isinstance(location, dict) and 'latitude' in location and 'longitude' in location:
        latitude = location['latitude']
        longitude = location['longitude']
        location_link = f"https://yandex.ru/maps?whatshere%5Bpoint%5D={longitude}%2C{latitude}&"
        location_display = f"Ссылка на карту: {location_link}"
    else:
        # Если координаты отсутствуют, используем текстовое представление местоположения
        location_display = request.get('location_display', 'Местоположение не указано')
    message = (
        f"Новая заявка #{request_id}\n\n"
        f"Клиент: {request.get('user_name', 'Неизвестный')}\n"
        f"Описание: {request.get('description', 'Нет описания')}\n"
        f"Статус: {request.get('status', 'Не указан')}\n"
        f"Местоположение: {location_display}\n"
        f"Желаемая дата: {request.get('desired_date', 'Не указана')}\n"
    )
    keyboard = [
        [InlineKeyboardButton("Привязать к СЦ", callback_data=f"assign_sc_{request_id}")],
        [InlineKeyboardButton("Отклонить заявку", callback_data=f"reject_request_{request_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=message, reply_markup=reply_markup)
        except Exception as e:
            print(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

            
async def notify_delivery(
    bot, 
    delivery_ids: Union[list, str], 
    task_data: dict,
    detailed: bool = False
):
    """
    Универсальный метод отправки уведомлений доставщикам
    """
    message = f"🆕 Новая задача доставки!\n\n"
    message += f"Заявка: #{task_data['request_id']}\n"
    message += f"СЦ: {task_data['sc_name']}\n\n"
    
    if detailed:
        message += f"Адрес клиента: {task_data.get('client_address', 'Не указан')}\n"
        message += f"Клиент: {task_data.get('client_name', 'Не указан')}\n"
        message += f"Телефон: {task_data.get('client_phone', 'Не указан')}\n"
        message += f"Описание: {task_data.get('description', 'Нет описания')}\n"
        message += f"Желаемая дата: {task_data.get('desired_date', 'Не указана')}\n"
    
    keyboard = [[
        InlineKeyboardButton(
            "Принять задачу", 
            callback_data=f"accept_delivery_{task_data['request_id']}"
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if isinstance(delivery_ids, str):
        delivery_ids = [delivery_ids]
    
    for delivery_id in delivery_ids:
        try:
            # Отправляем сообщение
            await bot.send_message(
                chat_id=delivery_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление отправлено доставщику {delivery_id}")

            # Отправляем фотографии, если они есть
            if 'delivery_photos' in task_data and task_data['delivery_photos']:
                for photo_path in task_data['delivery_photos']:
                    with open(photo_path, 'rb') as photo:
                        await bot.send_photo(chat_id=delivery_id, photo=photo)
                        logger.info(f"Фото отправлено доставщику {delivery_id} для заявки {task_data['request_id']}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления доставщику {delivery_id}: {e}")

async def notify_client(bot, client_id, message, reply_markup=None):
    try:
        await bot.send_message(chat_id=client_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error notifying client {client_id}: {e}")