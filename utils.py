# Вспомогательные функции, которые могут понадобиться в разных частях приложенияimport os
import os
from config import PHOTOS_DIR
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import logging
from typing import Union
from geopy.geocoders import Nominatim
import httpx
import json
from urllib.parse import quote

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


async def notify_delivery(bot, delivery_ids, task, detailed=False):
    """Отправка уведомления доставщикам"""
    message = ""
    keyboard = None
    
    if task.get('delivery_type') == 'sc_to_client':
        # Формат для доставки из СЦ клиенту
        message = (
            "🆕 Новая задача доставки из СЦ!\n\n"
            f"Заявка: #{task.get('request_id')}\n"
            f"1️⃣ Забрать из СЦ:\n"
            f"🏢 {task.get('sc_name')}\n"
            f"📍 {task.get('sc_address')}\n\n"
            f"2️⃣ Доставить клиенту:\n"
            f"👤 {task.get('client_name')}\n"
            f"📍 {task.get('client_address')}\n"
            f"📱 {task.get('client_phone')}\n"
            f"📝 Описание: {task.get('description')}"
        )
        
        keyboard = [[
            InlineKeyboardButton(
                "Принять заказ из СЦ",
                callback_data=f"accept_sc_delivery_{task['request_id']}"
            )
        ]]
    else:
        # Существующий формат для доставки от клиента
        message = (
            "🆕 Новая задача доставки!\n\n"
            f"Заявка: #{task.get('request_id')}\n"
            f"1️⃣ Забрать у клиента:\n"
            f"👤 {task.get('client_name')}\n"
            f"📍 {task.get('client_address')}\n"
            f"📱 {task.get('client_phone')}\n\n"
            f"2️⃣ Доставить в СЦ:\n"
            f"🏢 {task.get('sc_name')}\n"
            f"📝 Описание: {task.get('description')}"
        )
        
        keyboard = [[
            InlineKeyboardButton(
                "Принять заказ",
                callback_data=f"accept_delivery_{task['request_id']}"
            )
        ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for delivery_id in delivery_ids:
        try:
            await bot.send_message(
                chat_id=delivery_id,
                text=message,
                reply_markup=reply_markup
            )
            logger.info(f"Уведомление отправлено доставщику {delivery_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления доставщику {delivery_id}: {e}")


async def notify_client(bot, client_id, message, reply_markup=None):
    try:
        await bot.send_message(chat_id=client_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error notifying client {client_id}: {e}")


async def get_address_from_coords(latitude, longitude):
    """
    Улучшенный метод определения адреса с проверкой дополнительных полей.
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={latitude}&lon={longitude}&zoom=20&addressdetails=1&accept-language=ru"
        headers = {"User-Agent": "mkplace_bot/1.0"}
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"Полный ответ Nominatim: {data}")  # Для отладки
                if "display_name" in data:
                    return data["display_name"]
                if "address" in data:
                    components = []
                    # Основные компоненты адреса
                    for key in ["road", "house_number", "house", "suburb", "city", "town", "village"]:
                        if key in data["address"]:
                            components.append(data["address"][key])
                    # Если нет номера дома, добавляем ориентир
                    if not any(k in data["address"] for k in ["house_number", "house"]):
                        for landmark_key in ["building", "amenity", "shop"]:
                            if landmark_key in data["address"]:
                                components.append(f"({data['address'][landmark_key]})")
                                break
                    return ", ".join(filter(None, components)) if components else None
    except Exception as e:
        logger.error(f"Ошибка получения адреса: {e}")
    return None

def format_location_for_display(location):
    """Форматирует местоположение для отображения пользователю"""
    if not location:
        return "Местоположение не указано"
    return str(location)

def prepare_location_for_storage(location_data):
    """
    Подготавливает местоположение для сохранения в БД.
    Возвращает строку с адресом или координатами.
    """
    if isinstance(location_data, dict):
        # Если уже пришел dict (например, из callback), берем адрес или формируем из координат
        if 'address' in location_data:
            return location_data['address']
        elif 'latitude' in location_data and 'longitude' in location_data:
            return f"{location_data['latitude']}, {location_data['longitude']}"
        return str(location_data)
        
    if hasattr(location_data, 'latitude') and hasattr(location_data, 'longitude'):
        # Это объект Location из Telegram
        return f"{location_data.latitude}, {location_data.longitude}"
    
    # Ручной ввод адреса (строка) или другой формат
    return str(location_data)
