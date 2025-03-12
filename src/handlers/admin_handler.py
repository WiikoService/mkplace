import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from src.handlers.base_handler import BaseHandler
from src.services.user import UserService
from src.services.request import RequestService
from src.services.service_center import ServiceCenterService
from src.services.delivery import DeliveryService
from src.services.notification_service import NotificationService
from src.config import ASSIGN_REQUEST, CREATE_DELIVERY_TASK

logger = logging.getLogger(__name__)


class AdminHandler(BaseHandler):
    def __init__(self):
        self.user_service = UserService()
        self.request_service = RequestService()
        self.service_center_service = ServiceCenterService()
        self.delivery_service = DeliveryService()
        self.notification_service = NotificationService()

    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        """Обработка запроса на привязку заявки к сервисному центру"""
        query = update.callback_query
        await query.answer()
        logger.info(f"Получен callback query: {query.data}")
        parts = query.data.split('_')
        if len(parts) < 3:
            logger.error(f"Неверный формат данных: {query.data}")
            await query.edit_message_text("Неверный формат данных")
            return
        request_id = parts[2]
        request = await self.request_service.get_request(request_id)
        service_centers = await self.service_center_service.get_all_service_centers()
        if not request:
            logger.error(f"Заявка {request_id} не найдена")
            await query.edit_message_text(f"Заявка #{request_id} не найдена")
            return
        # Создаем клавиатуру с доступными сервисными центрами
        keyboard = []
        for sc_id, sc in service_centers.items():
            keyboard.append([InlineKeyboardButton(sc.name, callback_data=f"assign_sc_confirm_{request_id}_{sc_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выберите сервисный центр:", reply_markup=reply_markup)

    async def handle_assign_sc_confirm(self, update: Update, context: CallbackContext):
        """Подтверждение привязки заявки к сервисному центру"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 5:
            await query.edit_message_text("Неверный формат данных")
            return
        request_id = parts[3]
        sc_id = parts[4]
        service_center = await self.service_center_service.get_service_center(sc_id)
        if not service_center:
            await query.edit_message_text("Сервисный центр не найден")
            return
        # Привязываем заявку к сервисному центру
        request = await self.request_service.assign_to_service_center(request_id, sc_id, service_center.name)
        if not request:
            await query.edit_message_text("Заявка не найдена")
            return
        # Уведомляем клиента
        await self.notification_service.notify_user(
            update.get_bot(),
            request.user_id,
            f"Ваша заявка #{request_id} привязана к сервисному центру {service_center.name}."
        )
        # Предлагаем создать задачу доставки
        keyboard = [[InlineKeyboardButton("Создать задачу доставки", callback_data=f"create_delivery_{request_id}_{sc_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Заявка #{request_id} успешно привязана к СЦ {service_center.name}.\n"
            f"Хотите создать задачу доставки?",
            reply_markup=reply_markup
        )

    async def handle_create_delivery(self, update: Update, context: CallbackContext):
        """Обработка запроса на создание задачи доставки"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 4:
            await query.edit_message_text("Неверный формат данных")
            return
        request_id = parts[2]
        sc_id = parts[3]
        service_center = await self.service_center_service.get_service_center(sc_id)
        if not service_center:
            await query.edit_message_text("Сервисный центр не найден")
            return
        # Создаем задачу доставки
        task = await self.delivery_service.create_delivery_task(request_id, service_center.name)
        if not task:
            await query.edit_message_text("Не удалось создать задачу доставки")
            return
        # Уведомляем доставщиков
        await self.notification_service.notify_about_delivery_task(update.get_bot(), task.task_id, task.to_dict())
        await query.edit_message_text(
            f"Задача доставки #{task.task_id} для заявки #{request_id} создана.\n"
            f"Доставщики уведомлены."
        )

    async def show_all_requests(self, update: Update, context: CallbackContext):
        """Отображение всех заявок"""
        requests = await self.request_service.get_all_requests()
        if not requests:
            await update.message.reply_text("Заявок пока нет.")
            return
        for request_id, request in requests.items():
            message = (
                f"Заявка #{request.id}\n"
                f"Клиент: {request.user_name or 'Неизвестный'}\n"
                f"Описание: {request.description}\n"
                f"Статус: {request.status}\n"
            )
            keyboard = [[InlineKeyboardButton("Привязать к СЦ", callback_data=f"assign_sc_{request.id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup)
