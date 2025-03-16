from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import SC_IDS, ADMIN_IDS, ORDER_STATUS_IN_SC
from handlers.base_handler import BaseHandler
from database import load_requests, save_requests, load_users
from utils import notify_client
import logging

logger = logging.getLogger(__name__)

class SCHandler(BaseHandler):
    
    async def handle_item_acceptance(self, update: Update, context: CallbackContext):
        """Обработка принятия товара СЦ"""
        query = update.callback_query
        await query.answer()
        action, request_id = query.data.split('_')[1:]
        requests_data = load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("Заявка не найдена.")
            return
        if action == "accept":
            # Запрашиваем фото товара
            await query.edit_message_text(
                "Пожалуйста, сделайте фото товара и отправьте его в чат для подтверждения приёмки."
            )
            context.user_data['awaiting_photo_sc'] = request_id
            context.user_data['acceptance_message_id'] = query.message.message_id
        elif action == "reject":
            keyboard = [[
                InlineKeyboardButton(
                    "Указать причину отказа",
                    callback_data=f"reject_reason_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Пожалуйста, укажите причину отказа в приёме товара:",
                reply_markup=reply_markup
            )

    async def handle_photo_upload(self, update: Update, context: CallbackContext):
        """Обработка загрузки фото товара"""
        request_id = context.user_data.get('awaiting_photo_sc')
        if not request_id:
            return
        requests_data = load_requests()
        if request_id not in requests_data:
            await update.message.reply_text("Заявка не найдена.")
            return
        # Сохраняем фото
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/sc_acceptance_{request_id}.jpg"
        await photo_file.download_to_drive(photo_path)
        # Обновляем статус заявки
        requests_data[request_id]['status'] = ORDER_STATUS_IN_SC
        requests_data[request_id]['sc_acceptance_photo'] = photo_path
        save_requests(requests_data)
        # Уведомляем клиента
        client_id = requests_data[request_id]['user_id']
        await notify_client(
            context.bot,
            client_id,
            "Ваш товар принят Сервисным Центром и готов к диагностике."
        )
        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            with open(photo_path, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file,
                    caption=f"Товар по заявке #{request_id} принят СЦ"
                )
        # Очищаем данные контекста
        del context.user_data['awaiting_photo_sc']
        await update.message.reply_text("Фото загружено, товар принят в работу.")
