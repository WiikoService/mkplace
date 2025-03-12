from typing import List, Optional, Dict, Any
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from src.config import ADMIN_IDS, DELIVERY_IDS
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    async def notify_admins(self, bot: Bot, message: str, reply_markup=None) -> None:
        """Отправка уведомления всем администраторам"""
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=message, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")

    async def notify_delivery(self, bot: Bot, message: str, reply_markup=None) -> None:
        """Отправка уведомления всем доставщикам"""
        for delivery_id in DELIVERY_IDS:
            try:
                await bot.send_message(chat_id=delivery_id, text=message, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления доставщику {delivery_id}: {e}")

    async def notify_user(self, bot: Bot, user_id: str, message: str, reply_markup=None) -> None:
        """Отправка уведомления конкретному пользователю"""
        try:
            await bot.send_message(chat_id=user_id, text=message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def notify_about_new_request(self, bot: Bot, request_id: str, request_data: Dict[str, Any]) -> None:
        """Уведомление администраторов о новой заявке"""
        message = f"Новая заявка #{request_id}\n"
        message += f"Клиент: {request_data.get('user_name', 'Неизвестный')}\n"
        message += f"Описание: {request_data.get('description', 'Нет описания')}\n"
        message += f"Статус: {request_data.get('status', 'Новая')}\n"

        location_link = request_data.get('location_link', 'Местоположение не указано')
        message += f"Местоположение: {location_link}\n"
        keyboard = [[InlineKeyboardButton("Привязать к СЦ", callback_data=f"assign_sc_{request_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.notify_admins(bot, message, reply_markup)

    async def notify_about_delivery_task(self, bot: Bot, task_id: str, task_data: Dict[str, Any]) -> None:
        """Уведомление доставщиков о новой задаче доставки"""
        message = f"Новая задача доставки #{task_id}\n"
        message += f"Заявка: #{task_data.get('request_id', 'Не указана')}\n"
        message += f"СЦ: {task_data.get('sc_name', 'Не указан')}\n"
        message += f"Статус: {task_data.get('status', 'Ожидает')}"
        keyboard = [[InlineKeyboardButton("Принять", callback_data=f"accept_delivery_{task_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.notify_delivery(bot, message, reply_markup)
