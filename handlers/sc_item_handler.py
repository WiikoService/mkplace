from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import ADMIN_IDS, ORDER_STATUS_IN_SC, CREATE_REQUEST_PHOTOS
from handlers.sc_handler import SCHandler
from database import load_requests, save_requests, load_delivery_tasks, save_delivery_tasks
from utils import notify_client
import logging

logger = logging.getLogger(__name__)

class SCItemHandler(SCHandler):
    """Обработчик для управления приёмкой товаров в сервисном центре"""
    
    async def handle_item_acceptance(self, update: Update, context: CallbackContext):
        """Обработка принятия товара СЦ"""
        query = update.callback_query
        await query.answer()
        logger.info("Обработка принятия товара. Получен запрос от: %s", query.from_user.id)
        logger.info("Callback data: %s", query.data)
        # Правильно разбираем callback_data
        parts = query.data.split('_')
        action = parts[0]  # accept или reject
        request_id = parts[-1]
        logger.info("Действие: %s, ID заявки: %s", action, request_id)
        requests_data = load_requests()
        if request_id not in requests_data:
            logger.error("Заявка не найдена: %s", request_id)
            await query.edit_message_text("Заявка не найдена.")
            return ConversationHandler.END
        if action == "accept":
            logger.info("Принятие товара по заявке: %s", request_id)
            await query.edit_message_text(
                "Пожалуйста, сделайте фото товара и отправьте его в чат.\n"
                "Когда закончите, отправьте /done"
            )
            context.user_data['awaiting_photo_sc'] = request_id
            logger.info("Установлен awaiting_photo_sc: %s", request_id)
            return CREATE_REQUEST_PHOTOS
        elif action == "reject":
            logger.info("Отказ в приёмке товара по заявке: %s", request_id)
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
            return ConversationHandler.END

    async def handle_photo_upload(self, update: Update, context: CallbackContext):
        """Обработка загрузки фото товара"""
        logger.info("Получено фото от пользователя: %s", update.effective_user.id)
        request_id = context.user_data.get('awaiting_photo_sc')
        logger.info("awaiting_photo_sc из контекста: %s", request_id)
        if not request_id:
            logger.error("Ошибка: заявка не найдена в контексте")
            await update.message.reply_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END
        requests_data = load_requests()
        if request_id not in requests_data:
            logger.error("Заявка не найдена в базе: %s", request_id)
            await update.message.reply_text("Заявка не найдена.")
            return ConversationHandler.END
        logger.info("Получено фото для заявки: %s", request_id)
        # Сохраняем фото
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/sc_acceptance_{request_id}_{len(context.user_data.get('sc_photos', []))}.jpg"
        await photo_file.download_to_drive(photo_path)        
        # Сохраняем путь к фото в контексте
        if 'sc_photos' not in context.user_data:
            context.user_data['sc_photos'] = [] 
        context.user_data['sc_photos'].append(photo_path)
        logger.info("Фото добавлено для заявки: %s, путь: %s", request_id, photo_path)
        await update.message.reply_text("Фото добавлено. Отправьте /done когда закончите.")
        return CREATE_REQUEST_PHOTOS

    async def handle_photos_done(self, update: Update, context: CallbackContext):
        """Завершение загрузки фотографий СЦ"""
        try:
            request_id = context.user_data.get('awaiting_photo_sc')
            photos = context.user_data.get('sc_photos', [])
            if not photos:
                logger.warning("Необходимо добавить хотя бы одно фото для заявки: %s", request_id)
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            logger.info("Завершение загрузки фотографий для заявки: %s", request_id)
            # Обновляем статус заявки и сохраняем фото
            requests_data = load_requests()
            requests_data[request_id].update({
                'status': ORDER_STATUS_IN_SC,
                'sc_acceptance_photos': photos
            })
            save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            delivery_tasks = load_delivery_tasks()
            for task in delivery_tasks.values():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_IN_SC
                    break
            save_delivery_tasks(delivery_tasks)
            # Уведомляем клиента
            client_id = requests_data[request_id]['user_id']
            await notify_client(
                context.bot,
                client_id,
                "Ваш товар принят Сервисным Центром и готов к диагностике."
            )
            logger.info("Клиент уведомлён о принятии товара по заявке: %s", request_id)
            # Уведомляем админа
            for admin_id in ADMIN_IDS:
                for photo_path in photos:
                    with open(photo_path, 'rb') as photo_file:
                        await context.bot.send_photo(
                            chat_id=admin_id,
                            photo=photo_file,
                            caption=f"Товар по заявке #{request_id} принят СЦ"
                        )
            logger.info("Администраторы уведомлены о принятии товара по заявке: %s", request_id)
            # Очищаем данные контекста
            del context.user_data['awaiting_photo_sc']
            del context.user_data['sc_photos']
            await update.message.reply_text("✅ Товар принят в работу.")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при завершении приемки товара: {e}")
            await update.message.reply_text("Произошла ошибка при обработке приемки.")
            return ConversationHandler.END

    async def handle_reject_reason(self, update: Update, context: CallbackContext):
        """Обработка причины отказа в приеме товара"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        logger.info("Обработка причины отказа для заявки: %s", request_id)
        if request_id not in requests_data:
            logger.error("Заявка не найдена: %s", request_id)
            await query.edit_message_text("Заявка не найдена.")
            return
        # Обновляем статус заявки
        requests_data[request_id]['status'] = "Отказано в приёмке СЦ"
        save_requests(requests_data)
        # Уведомляем клиента
        client_id = requests_data[request_id]['user_id']
        await notify_client(
            context.bot,
            client_id,
            "СЦ отказал в приёмке вашего товара. Пожалуйста, свяжитесь с администратором."
        )
        logger.info("Клиент уведомлён об отказе в приёмке товара по заявке: %s", request_id)
        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"СЦ отказал в приёмке товара по заявке #{request_id}"
            )
        await query.edit_message_text("Отказ в приёмке товара зарегистрирован.") 