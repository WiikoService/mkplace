from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from src.handlers.base_handler import BaseHandler
from src.services.user import UserService
from src.services.delivery import DeliveryService
from src.services.notification_service import NotificationService
from src.config import ENTER_NAME, ENTER_PHONE, ORDER_STATUS_IN_SC, ORDER_STATUS_DELIVERY_TO_SC


class DeliveryHandler(BaseHandler):
    def __init__(self):
        self.user_service = UserService()
        self.delivery_service = DeliveryService()
        self.notification_service = NotificationService()

    async def show_delivery_profile(self, update: Update, context: CallbackContext):
        """Отображение профиля доставщика"""
        user_id = str(update.effective_user.id)
        user = await self.user_service.get_user(user_id)
        if not user:
            await update.message.reply_text("Пользователь не найден")
            return ConversationHandler.END
        if not user.name:
            await update.message.reply_text("Пожалуйста, введите ваше имя:")
            return ENTER_NAME
        if not user.phone:
            await update.message.reply_text("Пожалуйста, введите ваш номер телефона:")
            return ENTER_PHONE
        reply = f"Ваш профиль доставщика:\n\n"
        reply += f"Имя: {user.name}\n"
        reply += f"Телефон: {user.phone}\n"
        reply += f"Роль: {user.role}\n"
        await update.message.reply_text(reply)
        return ConversationHandler.END

    async def enter_name(self, update: Update, context: CallbackContext):
        """Ввод имени доставщика"""
        user_id = str(update.effective_user.id)
        name = update.message.text
        await self.user_service.create_or_update_user(user_id=user_id, name=name)
        await update.message.reply_text("Спасибо. Теперь, пожалуйста, введите ваш номер телефона:")
        return ENTER_PHONE

    async def enter_phone(self, update: Update, context: CallbackContext):
        """Ввод телефона доставщика"""
        user_id = str(update.effective_user.id)
        phone = update.message.text
        await self.user_service.create_or_update_user(user_id=user_id, phone=phone)
        await update.message.reply_text("Спасибо! Ваш профиль обновлен.")
        return await self.show_delivery_menu(update, context)

    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        """Отображение задач доставки"""
        user_id = str(update.effective_user.id)
        tasks = await self.delivery_service.get_delivery_tasks(user_id)
        if not tasks:
            # Показываем доступные задачи
            available_tasks = await self.delivery_service.get_available_tasks()
            if not available_tasks:
                await update.message.reply_text("Нет доступных задач доставки.")
                return
            await update.message.reply_text("Ваши текущие задачи отсутствуют. Доступные задачи:")
            for task in available_tasks:
                message = (
                    f"Задача #{task.task_id}\n"
                    f"Заявка: #{task.request_id}\n"
                    f"СЦ: {task.sc_name}\n"
                    f"Клиент: {task.client_name or 'Неизвестный'}\n"
                    f"Адрес: {task.client_address}\n"
                    f"Описание: {task.description or 'Нет описания'}\n"
                )
                keyboard = [[InlineKeyboardButton("Принять", callback_data=f"accept_delivery_{task.task_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text("Ваши текущие задачи:")
            for task in tasks:
                message = (
                    f"Задача #{task.task_id}\n"
                    f"Заявка: #{task.request_id}\n"
                    f"СЦ: {task.sc_name}\n"
                    f"Клиент: {task.client_name or 'Неизвестный'}\n"
                    f"Адрес: {task.client_address}\n"
                    f"Статус: {task.status}\n"
                )
                keyboard = []
                if task.status == "Принято":
                    keyboard.append([InlineKeyboardButton("Доставлено клиенту", callback_data=f"delivered_to_client_{task.task_id}")])
                elif task.status == ORDER_STATUS_DELIVERY_TO_SC:
                    keyboard.append([InlineKeyboardButton("Доставлено в СЦ", callback_data=f"delivered_to_sc_{task.task_id}")])
                if keyboard:
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(message, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(message)

    async def handle_accept_delivery(self, update: Update, context: CallbackContext):
        """Обработка принятия задачи доставки"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 3:
            await query.edit_message_text("Неверный формат данных")
            return
        task_id = parts[2]
        delivery_id = str(query.from_user.id)
        task = await self.delivery_service.accept_task(task_id, delivery_id)
        if not task:
            await query.edit_message_text("Не удалось принять задачу. Возможно, она уже принята другим доставщиком.")
            return
        # Уведомляем клиента
        from src.services.request import RequestService
        request_service = RequestService()
        request = await request_service.get_request(task.request_id)
        if request:
            user = await self.user_service.get_user(delivery_id)
            delivery_name = user.name if user else "Доставщик"
            await self.notification_service.notify_user(
                update.get_bot(),
                request.user_id,
                f"Доставщик {delivery_name} принял вашу заявку #{request.id} и скоро будет у вас."
            )
        # Уведомляем других доставщиков
        await self.update_delivery_messages(update.get_bot(), task_id, task.to_dict())
        await query.edit_message_text(
            f"Вы приняли задачу #{task_id}.\n"
            f"Заявка: #{task.request_id}\n"
            f"СЦ: {task.sc_name}\n"
            f"Клиент: {task.client_name or 'Неизвестный'}\n"
            f"Адрес: {task.client_address}\n"
        )

    async def handle_delivered_to_client(self, update: Update, context: CallbackContext):
        """Обработка доставки клиенту"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 4:
            await query.edit_message_text("Неверный формат данных")
            return
        task_id = parts[3]
        task = await self.delivery_service.update_task_status(task_id, ORDER_STATUS_DELIVERY_TO_SC)
        if not task:
            await query.edit_message_text("Не удалось обновить статус задачи")
            return
        # Уведомляем клиента
        from src.services.request import RequestService
        request_service = RequestService()
        request = await request_service.get_request(task.request_id)
        if request:
            await self.notification_service.notify_user(
                update.get_bot(),
                request.user_id,
                f"Ваша заявка #{request.id} принята доставщиком и будет доставлена в сервисный центр {task.sc_name}."
            )
        keyboard = [[InlineKeyboardButton("Доставлено в СЦ", callback_data=f"delivered_to_sc_{task_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Отлично! Теперь доставьте устройство в сервисный центр {task.sc_name}.",
            reply_markup=reply_markup
        )

    async def handle_delivered_to_sc(self, update: Update, context: CallbackContext):
        """Обработка доставки в сервисный центр"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 4:
            await query.edit_message_text("Неверный формат данных")
            return
        task_id = parts[3]
        task = await self.delivery_service.update_task_status(task_id, ORDER_STATUS_IN_SC)
        if not task:
            await query.edit_message_text("Не удалось обновить статус задачи")
            return
        # Уведомляем клиента
        from src.services.request import RequestService
        request_service = RequestService()
        request = await request_service.get_request(task.request_id)
        if request:
            await self.notification_service.notify_user(
                update.get_bot(),
                request.user_id,
                f"Ваше устройство по заявке #{request.id} доставлено в сервисный центр {task.sc_name}. Ожидайте обратной связи!"
            )
        await query.edit_message_text(f"Отличная работа! Заказ №{task.request_id} доставлен в Сервисный Центр.")

    async def update_delivery_messages(self, bot: Bot, task_id: str, task_data: dict):
        """Обновление сообщений для других доставщиков"""
        from src.config import DELIVERY_IDS
        for delivery_id in DELIVERY_IDS:
            if delivery_id != int(task_data.get('assigned_to', '0')):
                message = f"Задача доставки #{task_id} принята другим доставщиком.\n"
                message += f"Заявка: #{task_data['request_id']}\n"
                message += f"СЦ: {task_data['sc_name']}\n"
                message += f"Статус: {task_data['status']}"
                try:
                    await bot.send_message(chat_id=delivery_id, text=message)
                except Exception as e:
                    print(f"Ошибка при отправке уведомления доставщику {delivery_id}: {e}")
