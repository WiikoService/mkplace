import time
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import CallbackContext, ConversationHandler
from config import ORDER_STATUS_IN_SC, SC_ASSIGN_REQUESTS, ADMIN_IDS
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
        """Обработчик выбора заявки"""
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
        # Формируем сообщение с кнопкой ответа
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✉️ Ответить", callback_data=f"client_reply_{request_id}")
        ]])
        try:
            # Отправляем сообщение клиенту с кнопкой
            await context.bot.send_message(
                chat_id=int(client_id),
                text=f"📩 *Сообщение от СЦ по заявке #{request_id}:*\n{message.text}",
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
        
        # Очищаем предыдущий контекст чата
        context.user_data.pop('active_client_chat', None)
        
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        request_data = requests_data.get(request_id, {})
        
        # Оптимизированный поиск SC
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
        
        # Инициализация нового контекста с timestamp
        context.user_data['active_client_chat'] = {
            'request_id': request_id,
            'sc_user_id': sc_user_id,
            'last_active': time.time()
        }
        
        # Отправляем инструкцию с новым callback_data
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
        
        # Проверка актуальности контекста
        if not chat_data or time.time() - chat_data.get('last_active', 0) > 300:
            await message.reply_text("❌ Сессия устарела. Начните новый диалог.")
            context.user_data.pop('active_client_chat', None)
            return ConversationHandler.END
        
        request_id = chat_data['request_id']
        sc_user_id = chat_data['sc_user_id']
        
        try:
            # Отправка сообщения
            await context.bot.send_message(
                chat_id=int(sc_user_id),
                text=f"📩 *Ответ клиента по заявке #{request_id}:*\n{message.text}",
                parse_mode='Markdown'
            )
            
            # Обновление истории
            self.save_chat_history(
                request_id,
                'client',
                message.text,
                datetime.now().strftime("%H:%M %d-%m-%Y")
            )
            
            # Обновление времени активности
            context.user_data['active_client_chat']['last_active'] = time.time()
            
            # Кнопки ответа и выхода
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
        save_chat_history(chat_history)  # Функция сохранения

    async def close_chat(self, update: Update, context: CallbackContext):
        """Закрытие чата"""
        query = update.callback_query
        await query.answer()
        # Очищаем данные чата
        context.user_data.pop('active_chat', None)
        await query.edit_message_text("Чат закрыт")
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
        
        # Сохраняем данные для использования в следующем шаге
        context.user_data['current_request_id'] = request_id
        context.user_data['comment_message_id'] = query.message.message_id  # ID сообщения для редактирования
        
        await query.edit_message_text("✍️ Введите комментарий для заявки:")
        return 'HANDLE_SC_COMMENT'

    async def save_comment(self, update: Update, context: CallbackContext):
        """Сохраняет комментарий в заявку"""
        user_comment = update.message.text
        request_id = context.user_data.get('current_request_id')
        message_id = context.user_data.get('comment_message_id')

        # Только сохранение комментария
        requests_data = load_requests()
        if request_id in requests_data:
            requests_data[request_id]['comment'] = user_comment
            save_requests(requests_data)

            # Формируем сообщение с обновленной информацией
            request_data = requests_data[request_id]
            message_text = (
                f"📌 Заявка #{request_id}\n"
                f"🔧 Статус: {request_data['status']}\n"
                f"👤 Клиент: {request_data['user_name']}\n"
                f"📞 Телефон: {request_data.get('client_phone', 'не указан')}\n"
                f"📝 Описание: {request_data['description']}\n"
                f"🏠 Адрес: {request_data['location_display']}\n"
                f"💬 Комментарий СЦ: {user_comment}"
            )

            keyboard = [
                [InlineKeyboardButton("💬 Чат с клиентом", callback_data=f"sc_chat_{request_id}")],
                [InlineKeyboardButton("📝 Комментарий", callback_data=f"sc_comment_{request_id}")],
                [InlineKeyboardButton("🔙 Вернуться к списку", callback_data="sc_back_to_list")]
            ]

            # Пытаемся обновить оригинальное сообщение
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=message_id,
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении сообщения: {e}")
                # Если не удалось обновить, отправляем новое
                await update.message.reply_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            # Отправляем подтверждение
            await update.message.reply_text("✅ Комментарий успешно сохранен!")
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
        """Обработка выбора заявки для отправки в доставку"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        # Уведомляем администраторов
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        keyboard = [[
            InlineKeyboardButton(
                "Создать задачу доставки", 
                callback_data=f"create_delivery_{request_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        admin_message = (
            f"🔄 Запрос на доставку от СЦ\n\n"
            f"Заявка: #{request_id}\n"
            f"Описание: {request.get('description', 'Нет описания')}\n"
            f"Статус: {request.get('status', 'Статус не указан')}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        await query.edit_message_text(
            f"✅ Заявка #{request_id} отправлена на рассмотрение администраторам."
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

    async def cancel_client_chat(self, update: Update, context: CallbackContext):
        """Отмена чата клиентом"""
        query = update.callback_query
        await query.answer()
        
        # Очищаем контекст чата
        context.user_data.pop('active_client_chat', None)
        
        await query.edit_message_text("✅ Отправка сообщения отменена")
        return ConversationHandler.END


