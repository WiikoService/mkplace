import time
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ORDER_STATUS_IN_SC, SC_ASSIGN_REQUESTS, ADMIN_IDS,
    ORDER_STATUS_DELIVERY_TO_CLIENT, ORDER_STATUS_DELIVERY_TO_SC,
    ENTER_REPAIR_PRICE, CONFIRMATION, ORDER_STATUS_SC_TO_CLIENT
)
from handlers.base_handler import BaseHandler
from database import (
    load_requests, save_requests, load_users,
    load_delivery_tasks, save_delivery_tasks, load_chat_history,
    save_chat_history, load_service_centers
)
from utils import notify_client
import logging

logger = logging.getLogger(__name__)


class SCHandler(BaseHandler):

    async def show_sc_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Заявки центра", "Отправить в доставку"],
            ["Связаться с администратором"],
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню СЦ:", reply_markup=reply_markup)

    async def set_sc_requests(self, update: Update, context: CallbackContext):
        """Показывает список заявок сервисного центра"""
        try:
            user_id = str(update.effective_user.id)
            users_data = load_users()
            current_user = users_data.get(user_id, {})
            if current_user.get('role') != 'sc' or 'sc_id' not in current_user:
                await update.effective_message.reply_text("❌ Доступ запрещен!")
                return ConversationHandler.END
            sc_id = current_user['sc_id']
            requests_data = load_requests()
            sc_requests = {
                req_id: req
                for req_id, req in requests_data.items()
                if str(req.get('assigned_sc')) == sc_id
            }
            if not sc_requests:
                await update.effective_message.reply_text("📭 Нет активных заявок для вашего сервисного центра")
                return ConversationHandler.END
            context.user_data['sc_requests'] = sc_requests
            keyboard = [
                [InlineKeyboardButton(
                    f"Заявка #{req_id} - {req['description'][:20]}...",
                    callback_data=f"sc_request_{req_id}"
                )]
                for req_id, req in sc_requests.items()
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                "📋 Список заявок вашего сервисного центра:",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при показе заявок СЦ: {e}")
            await update.effective_message.reply_text("⚠️ Произошла ошибка при загрузке заявок")
            return ConversationHandler.END

    async def choose_requests(self, update: Update, context: CallbackContext):
        """
        Обработчик выбора заявки
        TODO: упростить или переработать отображение комментариев
        """
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        sc_requests = context.user_data.get('sc_requests', {})
        if request_id not in sc_requests:
            await query.edit_message_text("❌ Заявка не найдена")
            return
        request_data = sc_requests[request_id]
        message_text = (
            f"📌 Заявка #{request_id}\n"
            f"🔧 Статус: {request_data['status']}\n"
            f"👤 Клиент: {request_data['user_name']}\n"
            f"📞 Телефон: {request_data.get('client_phone', 'не указан')}\n"
            f"📝 Описание: {request_data['description']}\n"
            f"🏠 Адрес: {request_data['location_display']}"
        )
        # Добавляем комментарии, если они есть
        if 'comments' in request_data and request_data['comments']:
            message_text += "\n\n📋 Комментарии:\n"
            # Отображаем последние 3 комментария
            for comment in request_data['comments'][-3:]:
                message_text += f"- {comment['timestamp']} | {comment['user_name']}: {comment['text'][:50]}{'...' if len(comment['text']) > 50 else ''}\n"
            # Если комментариев больше 3, укажем об этом
            if len(request_data['comments']) > 3:
                message_text += f"(и еще {len(request_data['comments']) - 3} комментариев)\n"
        keyboard = [
            [InlineKeyboardButton("💬 Чат с клиентом", callback_data=f"sc_chat_{request_id}")],
            [InlineKeyboardButton("📝 Комментарий", callback_data=f"sc_comment_{request_id}")],
            [InlineKeyboardButton("🔙 Вернуться к списку", callback_data="sc_back_to_list")]
        ]
        await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_back_to_list(self, update: Update, context: CallbackContext):
        """Возвращает пользователя к списку заявок"""
        query = update.callback_query
        await query.answer()
        await self.set_sc_requests(update, context)

    async def sc_to_user_chat(self, update: Update, context: CallbackContext):
        """Инициализация чата с клиентом"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        context.user_data['active_chat'] = {
            'request_id': request_id,
            'chat_type': 'sc_to_client',
            'participants': {
                'sc_user_id': update.effective_user.id,
                'client_id': None
            }
        }
        requests_data = load_requests()
        request_data = requests_data.get(request_id, {})
        client_id = request_data.get('user_id')
        if not client_id:
            await query.message.reply_text("Ошибка: не найден ID клиента")
            return ConversationHandler.END
        # Сохраняем ID клиента в контексте
        context.user_data['active_chat']['participants']['client_id'] = client_id
        keyboard = [
            [InlineKeyboardButton("❌ Закрыть чат", callback_data=f"close_chat_{request_id}")],
            [InlineKeyboardButton("📨 История переписки", callback_data=f"chat_history_{request_id}")]
        ]
        await query.edit_message_text(
            text=f"💬 Чат по заявке #{request_id}\n"
                 "Отправьте сообщение для клиента:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return 'HANDLE_SC_CHAT'

    async def handle_sc_chat(self, update: Update, context: CallbackContext):
        """Обработка сообщений от СЦ"""
        message = update.message
        chat_data = context.user_data.get('active_chat', {})
        request_id = chat_data.get('request_id')
        client_id = chat_data['participants']['client_id']
        
        # Получаем данные заявки для форматирования адреса
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        
        # Форматируем адрес
        location = request.get('location', {})
        if isinstance(location, dict):
            if location.get('type') == 'coordinates':
                address = location.get('address', 'Адрес не определен')
                location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
            else:
                location_str = location.get('address', 'Адрес не указан')
        else:
            location_str = str(location)
        
        # Формируем сообщение с кнопкой ответа
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✉️ Ответить", callback_data=f"client_reply_{request_id}")
        ]])
        
        try:
            # Отправляем сообщение клиенту с кнопкой
            await context.bot.send_message(
                chat_id=int(client_id),
                text=f"📩 *Сообщение от СЦ по заявке #{request_id}:*\n"
                    f"📍 Адрес: {location_str}\n\n"
                    f"{message.text}",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            await message.reply_text("✅ Сообщение доставлено")
            # Сохраняем в историю
            self.save_chat_history(
                request_id,
                'sc',
                message.text,
                datetime.now().strftime("%H:%M %d-%m-%Y")
            )
        except Exception as e:
            logger.error(f"Ошибка отправки: {str(e)}")
            await message.reply_text("❌ Не удалось отправить сообщение")
        return 'HANDLE_SC_CHAT'

    async def handle_client_reply(self, update: Update, context: CallbackContext):
        """Обработка ответов клиента с очисткой контекста"""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('active_client_chat', None)
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        request_data = requests_data.get(request_id, {})
        sc_id = request_data.get('assigned_sc')
        users_data = load_users()
        sc_user_id = next(
            (uid for uid, u_data in users_data.items() 
            if str(u_data.get('sc_id')) == str(sc_id) and u_data.get('role') == 'sc'),
            None
        )
        if not sc_user_id:
            await query.message.reply_text("❌ Сервисный центр недоступен")
            return ConversationHandler.END
        context.user_data['active_client_chat'] = {
            'request_id': request_id,
            'sc_user_id': sc_user_id,
            'last_active': time.time()
        }
        await query.message.reply_text(
            "💬 Режим ответа активирован. Отправьте сообщение:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_chat_{request_id}")]
            ])
        )
        return 'HANDLE_CLIENT_REPLY'

    async def handle_client_message(self, update: Update, context: CallbackContext):
        """Обработка сообщений с валидацией контекста и кнопкой выхода"""
        message = update.message
        chat_data = context.user_data.get('active_client_chat')
        if not chat_data or time.time() - chat_data.get('last_active', 0) > 300:
            await message.reply_text("❌ Сессия устарела. Начните новый диалог.")
            context.user_data.pop('active_client_chat', None)
            return ConversationHandler.END
        request_id = chat_data['request_id']
        sc_user_id = chat_data['sc_user_id']
        try:
            await context.bot.send_message(
                chat_id=int(sc_user_id),
                text=f"📩 *Ответ клиента по заявке #{request_id}:*\n{message.text}",
                parse_mode='Markdown'
            )
            self.save_chat_history(
                request_id,
                'client',
                message.text,
                datetime.now().strftime("%H:%M %d-%m-%Y")
            )
            context.user_data['active_client_chat']['last_active'] = time.time()
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✉️ Отправить еще", 
                        callback_data=f"client_reply_{request_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Закрыть чат", 
                        callback_data=f"close_chat_{request_id}"
                    )
                ]
            ])
            await message.reply_text(
                "✅ Сообщение доставлено:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка: {str(e)}")
            await message.reply_text("❌ Ошибка отправки")
        return 'HANDLE_CLIENT_REPLY'

    def save_chat_history(self, request_id, sender, message, timestamp):
        """Сохранение истории переписки"""
        chat_history = load_chat_history()
        entry = {
            'sender': sender,
            'message': message,
            'timestamp': timestamp
        }
        if request_id not in chat_history:
            chat_history[request_id] = []
        chat_history[request_id].append(entry)
        save_chat_history(chat_history)

    async def close_chat(self, update: Update, context: CallbackContext):
        """Закрытие чата"""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('active_chat', None)
        await query.edit_message_text("Чат закрыт")
        return ConversationHandler.END

    async def cancel_client_chat(self, update: Update, context: CallbackContext):
        """Отмена чата клиентом"""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('active_client_chat', None)
        await query.edit_message_text("✅ Отправка сообщения отменена")
        return ConversationHandler.END

    async def show_chat_history(self, update: Update, context: CallbackContext):
        """Показывает историю переписки по заявке"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        chat_history = load_chat_history().get(request_id, [])
        if not chat_history:
            await query.message.reply_text("История переписки пуста.")
            return
        history_text = f"📜 История переписки по заявке #{request_id}:\n\n"
        for entry in chat_history:
            sender = "СЦ" if entry['sender'] == 'sc' else "Клиент"
            history_text += (
                f"👤 {sender} ({entry['timestamp']}):\n"
                f"{entry['message']}\n\n"
            )
        await query.message.reply_text(history_text)

    async def sc_comment(self, update: Update, context: CallbackContext):
        """Обработчик кнопки 'Комментарий' для ввода комментария"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        context.user_data['current_request_id'] = request_id
        context.user_data['comment_message_id'] = query.message.message_id
        await query.edit_message_text("✍️ Введите комментарий для заявки:")
        return 'HANDLE_SC_COMMENT'

    async def save_comment(self, update: Update, context: CallbackContext):
        """Отправляет комментарий на согласование администратору"""
        user_comment = update.message.text
        request_id = context.user_data.get('current_request_id')
        message_id = context.user_data.get('comment_message_id')
        requests_data = load_requests()
        if request_id in requests_data:
            request_data = requests_data[request_id]
            # Получаем данные СЦ
            user_id = str(update.effective_user.id)
            users_data = load_users()
            sc_user = users_data.get(user_id, {})
            sc_center_id = sc_user.get('sc_id')
            service_centers = load_service_centers()
            sc_data = service_centers.get(sc_center_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            # Формируем сообщение для администратора
            admin_message = (
                f"📝 Новый комментарий от СЦ требует согласования\n\n"
                f"Заявка: #{request_id}\n"
                f"СЦ: {sc_name}\n"
                f"Комментарий: {user_comment}\n"
                f"Описание заявки: {request_data.get('description', 'Нет описания')}"
            )
            # Создаем клавиатуру для администратора с комментарием в callback_data
            keyboard = [
                [
                    InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_comment_{request_id}_{user_comment}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_comment_{request_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Отправляем уведомление администраторам
            notification_sent = False
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=reply_markup
                    )
                    notification_sent = True
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
            if notification_sent:
                await update.message.reply_text(
                    "✅ Комментарий отправлен на согласование администратору.\n"
                    "Ожидайте подтверждения."
                )
            else:
                await update.message.reply_text(
                    "❌ Не удалось отправить комментарий на согласование.\n"
                    "Пожалуйста, попробуйте позже."
                )
        else:
            await update.message.reply_text("❌ Заявка не найдена")
        return ConversationHandler.END

    async def assign_to_delivery(self, update: Update, context: CallbackContext):
        """Назначить товар в доставку из СЦ"""
        users_data = load_users()
        user_id = str(update.effective_user.id)   
        requests_data = load_requests()
        if not requests_data:
            await update.message.reply_text("Нет активных заявок для отправки в доставку.")
            return ConversationHandler.END
        keyboard = []
        sc_id = users_data[user_id].get('sc_id')
        for req_id, req_data in requests_data.items():
            # Проверяем, что заявка принадлежит этому СЦ и находится в нужном статусе
            if (req_data.get('assigned_sc') == sc_id and 
                req_data.get('status') == ORDER_STATUS_IN_SC):
                desc = req_data.get('description', 'Нет описания')[:30] + '...'
                button_text = f"Заявка #{req_id} - {desc}"
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"sc_delivery_{req_id}"
                )])
        if not keyboard:
            await update.message.reply_text("Нет заявок, готовых к отправке в доставку.")
            return ConversationHandler.END
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите заявку для отправки в доставку:",
            reply_markup=reply_markup
        )
        return SC_ASSIGN_REQUESTS

    async def handle_sc_delivery_request(self, update: Update, context: CallbackContext):
        """Обработка выбора заявки для отправки в доставку из СЦ"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        # Проверяем статус
        current_status = request.get('status')
        if current_status in ['Ожидает доставку', ORDER_STATUS_DELIVERY_TO_CLIENT, ORDER_STATUS_DELIVERY_TO_SC]:
            await query.edit_message_text(
                f"❌ Заявка #{request_id} уже отправлена в доставку."
            )
            return ConversationHandler.END
        # Обновляем статус заявки
        request['status'] = 'Ожидает выбора даты доставки'
        requests_data[request_id] = request
        save_requests(requests_data)
        # Уведомляем клиента о необходимости выбрать дату доставки
        client_id = request.get('user_id')
        if client_id:
            keyboard = [[
                InlineKeyboardButton(
                        "📅 Выбрать дату доставки",
                        callback_data=f"select_delivery_date_{request_id}"
                    )
                ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=int(client_id),
                text=(
                    f"🔄 Сервисный центр готов отправить ваш заказ #{request_id} в доставку.\n"
                    "Пожалуйста, выберите удобную дату и время доставки."
                ),
                reply_markup=reply_markup
            )
        # Уведомляем СЦ
        await query.edit_message_text(
            f"✅ Заявка #{request_id} отправлена клиенту для выбора даты доставки.\n"
            "Ожидайте подтверждения от клиента."
        )
        return ConversationHandler.END

    async def handle_sc_date_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора даты доставки"""
        query = update.callback_query
        await query.answer()
        # Получаем выбранную дату из callback_data и сохраняем во временные данные
        selected_date_str = query.data.split('_', 3)[3]
        context.user_data["temp_delivery_date"] = selected_date_str
        # Создаем клавиатуру с временными интервалами
        keyboard = []
        current_hour = 9  # Начинаем с 9 утра
        while current_hour <= 20:  # До 20:00
            time_str = f"{current_hour:02d}:00"
            keyboard.append([
                InlineKeyboardButton(
                    f"🕐 {time_str}",
                    callback_data=f"sc_select_time_{time_str}"
                )
            ])
            current_hour += 1
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите удобное время доставки:",
            reply_markup=reply_markup
        )
        return 'SC_SELECT_DELIVERY_TIME'

    async def handle_sc_time_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора времени доставки"""
        query = update.callback_query
        await query.answer()
        selected_time = query.data.split('_', 3)[3]
        temp_date = context.user_data.get("temp_delivery_date")
        request_id = context.user_data.get('delivery_request_id')

        # Комбинируем дату и время
        date_obj = datetime.strptime(temp_date, "%H:%M %d.%m.%Y")
        time_obj = datetime.strptime(selected_time, "%H:%M")
        # Создаем финальную дату с выбранным временем
        final_datetime = date_obj.replace(
            hour=time_obj.hour,
            minute=time_obj.minute
        )
        # Получаем данные заявки
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        # Обновляем статус и добавляем дату доставки
        request['status'] = 'Ожидает доставку из СЦ'
        request['delivery_date'] = final_datetime.strftime("%H:%M %d.%m.%Y")
        requests_data[request_id] = request
        save_requests(requests_data)
        # Очищаем временные данные
        if "temp_delivery_date" in context.user_data:
            del context.user_data["temp_delivery_date"]
        # Уведомляем администраторов
        keyboard = [[
            InlineKeyboardButton(
                "Создать задачу доставки из СЦ", 
                callback_data=f"create_sc_delivery_{request_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        admin_message = (
                f"🔄 Запрос на доставку из СЦ\n\n"
            f"Заявка: #{request_id}\n"
            f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Дата доставки: {request['delivery_date']}\n"
                f"Статус: Ожидает доставку из СЦ"
        )
            # Отправляем уведомления админам
        notification_sent = False
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    reply_markup=reply_markup
                )
                notification_sent = True
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
            if notification_sent:
                await query.edit_message_text(
                    f"✅ Заявка #{request_id} отправлена на рассмотрение администраторам.\n"
                    f"Дата доставки: {request['delivery_date']}"
                )
            else:
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                requests_data[request_id] = request
                save_requests(requests_data)
        await query.edit_message_text(
                    f"❌ Не удалось отправить заявку #{request_id} в доставку. Попробуйте позже."
        )
            
        return ConversationHandler.END

    async def call_to_admin(self, update: Update, context: CallbackContext):
        """Связаться с администратором"""
        user_id = str(update.effective_user.id)
        users_data = load_users()
        service_centers = load_service_centers()
        # Получаем данные СЦ
        sc_id = users_data[user_id].get('sc_id')
        sc_data = service_centers.get(sc_id, {})
        if not sc_data:
            await update.message.reply_text("Ошибка: данные СЦ не найдены.")
            return
        # Формируем сообщение для администраторов
        admin_message = (
            f"📞 Запрос на связь от сервисного центра\n\n"
            f"🏢 СЦ: {sc_data.get('name')}\n"
            f"📍 Адрес: {sc_data.get('address')}\n"
            f"☎️ Телефон: {sc_data.get('phone')}\n"
            f"👤 Контактное лицо: {users_data[user_id].get('name')}"
        )
        # Отправляем уведомление всем администраторам
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        await update.message.reply_text(
            "✅ Запрос отправлен администраторам. Ожидайте ответа."
        )

    async def docs(self, update: Update, context: CallbackContext):
        """Отображение документов в разработке в целом"""
        await update.message.reply_text("📄 Этот раздел находится в разработке. Пожалуйста, следите за обновлениями!")

    async def cancel(self, update: Update, context: CallbackContext):
        """Отмена операции."""
        await update.message.reply_text("Операция отменена.")
        return ConversationHandler.END

    async def handle_request_notification(self, update: Update, context: CallbackContext):
        """Обработка уведомления о новой заявке"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]        
        try:
            user_id = update.effective_user.id
            requests_data = load_requests()
            request = requests_data.get(request_id)
            # Сохраняем ID заявки в контексте пользователя
            context.user_data['current_request'] = request_id
            # Добавляем флаг, что ожидаем ввод стоимости и время начала ожидания
            context.user_data['waiting_for_price'] = True
            context.user_data['price_entry_time'] = time.time()
            # Запрашиваем стоимость простым текстом без кнопок
            await query.edit_message_text(
                f"Вы приняли заявку #{request_id}.\n\n"
                f"Пожалуйста, укажите примерную стоимость ремонта (можно указать диапазон):"
            )            
        except Exception as e:
            await query.edit_message_text("Произошла ошибка при обработке запроса")

    async def handle_repair_price(self, update: Update, context: CallbackContext):
        """Обработка ввода стоимости ремонта"""       
        # Проверяем, что это обработчик для ввода стоимости
        if not context.user_data.get('waiting_for_price'):
            # Если не ожидаем ввод стоимости, то игнорируем сообщение
            return
        try:
            # Сохраняем оригинальный текст вместо преобразования в число
            price_text = update.message.text.strip()
            request_id = context.user_data.get('current_request')
            if not request_id:
                await update.message.reply_text("❌ Произошла ошибка, запрос не найден")
                context.user_data.pop('waiting_for_price', None)
                context.user_data.pop('price_entry_time', None)
                return
            # Сохраняем стоимость в контексте без преобразования в число
            context.user_data['repair_price_text'] = price_text
            # Сбрасываем флаг ожидания стоимости
            context.user_data.pop('waiting_for_price', None)
            context.user_data.pop('price_entry_time', None)
            # Получаем данные заявки
            requests_data = load_requests()
            request = requests_data.get(request_id)
            if not request:
                await update.message.reply_text("❌ Заявка не найдена")
                return
            # Формируем сообщение с информацией и кнопкой подтверждения
            message_text = (
                f"📦 Заявка #{request_id}\n"
                f"📝 Описание: {request.get('description', 'Нет описания')}\n"
                f"💰 Указанная стоимость: {price_text} руб.\n\n"
                f"Нажмите кнопку ниже, чтобы подтвердить принятие заявки с указанной стоимостью:"
            )
            keyboard = [[
                InlineKeyboardButton(
                    "✅ Принять с указанной стоимостью",
                    callback_data=f"accept_request_price_{request_id}"
                )
            ]]
            # Отправляем сообщение с кнопкой подтверждения
            await update.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await update.message.reply_text("❌ Пожалуйста, введите корректную стоимость")

    async def confirm_repair_price(self, update: Update, context: CallbackContext):
        """Подтверждение стоимости ремонта и принятие заявки"""           
        query = update.callback_query
        await query.answer()
        # Извлекаем ID заявки
        parts = query.data.split('_')
        if len(parts) < 4 or parts[0] != "accept" or parts[1] != "request" or parts[2] != "price":
            logger.error(f"Неверный формат callback_data: {query.data}")
            await query.edit_message_text("❌ Ошибка: неверный формат данных")
            return
        request_id = parts[3]
        price_text = context.user_data.get('repair_price_text')
        # Проверяем наличие стоимости
        if not price_text:
            await query.edit_message_text("❌ Произошла ошибка: стоимость ремонта не найдена")
            return
        # Получаем ID СЦ    
        sc_id = str(update.effective_user.id)
        try:
            # Получаем данные заявки
            requests_data = load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            # Получаем данные о сервисном центре
            users_data = load_users()
            sc_user = users_data.get(sc_id, {})
            sc_center_id = sc_user.get('sc_id')
            if not sc_center_id:
                await query.edit_message_text("❌ Ошибка: не удалось определить ваш сервисный центр")
                return
            # Обновляем статус заявки
            request = requests_data[request_id]
            request['status'] = 'Ожидает согласования цены'
            request['assigned_sc'] = sc_center_id
            request['repair_price'] = price_text
            request['accepted_at'] = int(time.time())
            # Сохраняем обновленные данные
            save_requests(requests_data)
            # Отправляем уведомление администраторам для согласования цены
            service_centers = load_service_centers()
            sc_data = service_centers.get(sc_center_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            keyboard = [[
                InlineKeyboardButton(
                    "Отправить на согласование клиенту",
                    callback_data=f"send_price_approval_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            admin_message = (
                f"🔄 Заявка принята СЦ и требует согласования цены\n\n"
                f"Заявка: #{request_id}\n"
                f"СЦ: {sc_name}\n"
                f"Стоимость ремонта: {price_text} руб.\n"
                f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Статус: Ожидает согласования цены"
            )
            # Отправляем уведомления админам
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
            # Отправляем подтверждение СЦ
            await query.edit_message_text(
                f"✅ Заявка #{request_id} принята с указанной стоимостью {price_text} руб.\n"
                f"Данные сохранены, ожидается согласование цены с клиентом."
            )
        except Exception as e:
            logger.error(f"Ошибка при обработке подтверждения: {e}")
            await query.edit_message_text(f"❌ Произошла ошибка: {str(e)}")

    async def create_return_delivery(self, update: Update, context: CallbackContext):
        """Создание задачи доставки из СЦ клиенту после ремонта"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            service_centers = load_service_centers()
            
            request = requests_data.get(request_id)
            if not request:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            
            # Получаем данные СЦ
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            
            # Форматируем адрес клиента
            location = request.get('location', {})
            if isinstance(location, dict):
                if location.get('type') == 'coordinates':
                    address = location.get('address', 'Адрес не определен')
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get('address', 'Адрес не указан')
            else:
                location_str = str(location)
            
            # Создаем задачу доставки ИЗ СЦ КЛИЕНТУ
            new_task_id = str(len(delivery_tasks) + 1)
            new_task = {
                'task_id': new_task_id,
                'request_id': request_id,
                'status': 'Новая',
                'sc_name': sc_data.get('name', 'Не указан'),
                'sc_address': sc_data.get('address', 'Не указан'),
                'client_name': request.get('user_name', 'Не указан'),
                'client_address': location_str,  # Используем отформатированный адрес
                'client_phone': request.get('user_phone', 'Не указан'),
                'description': request.get('description', ''),
                'delivery_type': 'sc_to_client',  # Вторая доставка - из СЦ
                'is_sc_to_client': True,  # Это доставка из СЦ
                'desired_date': request.get('desired_date', '')
            }
            
            delivery_tasks[new_task_id] = new_task
            save_delivery_tasks(delivery_tasks)
            
            # Обновляем статус заявки
            request['status'] = ORDER_STATUS_SC_TO_CLIENT  # Статус: готово к доставке клиенту
            save_requests(requests_data)
            
            await query.edit_message_text(
                f"✅ Создана задача доставки #{new_task_id}\n"
                f"Тип: Доставка из СЦ клиенту\n"
                f"СЦ: {sc_data.get('name', 'Не указан')}\n"
                f"Адрес клиента: {location_str}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при создании обратной доставки: {e}")
            await query.edit_message_text("❌ Произошла ошибка при создании задачи доставки")
