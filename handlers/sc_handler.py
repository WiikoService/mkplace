from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import CallbackContext, ConversationHandler
from config import ADMIN_IDS, ORDER_STATUS_IN_SC, CREATE_REQUEST_PHOTOS
from handlers.base_handler import BaseHandler
from database import (
    load_requests, save_requests, load_users,
    load_delivery_tasks, save_delivery_tasks, load_chat_history,
    save_chat_history
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
        # Формируем сообщение с кнопкой ответа
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
        """Обработка ответов клиента"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        request_data = requests_data.get(request_id, {})
        sc_id = request_data.get('assigned_sc')
        users_data = load_users()
        sc_user_id = None
        for user_id, user_data in users_data.items():
            if str(user_data.get('sc_id')) == str(sc_id) and user_data.get('role') == 'sc':
                sc_user_id = user_id
                break
        if not sc_user_id:
            await query.message.reply_text("❌ Сервисный центр не найден")
            return ConversationHandler.END
        # Сохраняем контекст чата для клиента
        context.user_data['active_client_chat'] = {
            'request_id': request_id,
            'sc_user_id': sc_user_id
        }
        await query.message.reply_text(
            "💬 Вы в режиме ответа СЦ. Отправьте ваше сообщение:",
            reply_markup=ReplyKeyboardRemove()
        )
        return 'HANDLE_CLIENT_REPLY'

    async def handle_client_message(self, update: Update, context: CallbackContext):
        """Пересылка сообщения клиента в СЦ"""
        message = update.message
        chat_data = context.user_data.get('active_client_chat', {})
        if not chat_data:
            await message.reply_text("❌ Сессия чата устарела")
            return ConversationHandler.END
        request_id = chat_data.get('request_id')
        sc_user_id = chat_data.get('sc_user_id')
        if not sc_user_id:
            await message.reply_text("❌ Чат недоступен")
            return ConversationHandler.END
        # Дополнительная проверка существования пользователя
        users_data = load_users()
        if sc_user_id not in users_data:
            await message.reply_text("❌ Сотрудник СЦ не найден")
            return ConversationHandler.END
        try:
            # Отправляем сообщение в СЦ
            await context.bot.send_message(
                chat_id=int(sc_user_id),
                text=f"📩 *Ответ клиента по заявке #{request_id}:*\n{message.text}",
                parse_mode='Markdown'
            )
            # Сохраняем в историю
            self.save_chat_history(
                request_id,
                'client',
                message.text,
                datetime.now().strftime("%H:%M %d-%m-%Y")
            )
            await message.reply_text("✅ Ответ отправлен в СЦ")
        except Exception as e:
            logger.error(f"Ошибка отправки: {str(e)}")
            await message.reply_text("❌ Не удалось отправить сообщение")
        return 'HANDLE_CLIENT_REPLY'

    def save_chat_history(self, request_id, sender, message, timestamp):
        """Сохранение истории переписки"""
        # Предположим, что есть функция загрузки/сохранения истории
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

    async def assign_to_delivery():
        """
        Назначить товар в доставку
        TODO: метод аналогричен админскому, назначаем доставку из СЦ
        """
        pass

    async def call_to_admin():
        """
        Связаться с админом

        надо подумать (не срочно)
        """
        pass

    async def docs():
        """
        отображение документов в разработке в целом
        """
        pass

    async def cancel(self, update: Update, context: CallbackContext):
        """Отмена операции."""
        await update.message.reply_text("Операция отменена.")
        return ConversationHandler.END
