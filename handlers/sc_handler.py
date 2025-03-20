from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import SC_IDS, ADMIN_IDS, ORDER_STATUS_IN_SC, CREATE_REQUEST_PHOTOS
from handlers.base_handler import BaseHandler
from database import load_requests, save_requests, load_users, load_delivery_tasks, save_delivery_tasks
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
            logger.info('set_sc_requests set_sc_requests set_sc_requests')
            # Получаем информацию о текущем пользователе
            user_id = str(update.effective_user.id)
            users_data = load_users()
            current_user = users_data.get(user_id, {})

            # Проверяем, что пользователь принадлежит к СЦ
            if current_user.get('role') != 'sc' or 'sc_id' not in current_user:
                await update.effective_message.reply_text("❌ Доступ запрещен!")
                return ConversationHandler.END

            sc_id = current_user['sc_id']

            # Загружаем и фильтруем заявки
            requests_data = load_requests()
            sc_requests = {
                req_id: req 
                for req_id, req in requests_data.items() 
                if str(req.get('assigned_sc')) == sc_id
            }

            if not sc_requests:
                await update.effective_message.reply_text("📭 Нет активных заявок для вашего сервисного центра")
                return ConversationHandler.END

            # Сохраняем заявки в контекст
            context.user_data['sc_requests'] = sc_requests

            # Создаем клавиатуру
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
