import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import ADMIN_IDS, ORDER_STATUS_IN_SC, CREATE_REQUEST_PHOTOS
from handlers.sc_handler import SCHandler
from database import (
    load_requests, save_requests, load_delivery_tasks, save_delivery_tasks
)
from utils import notify_client
import logging
from logging_decorator import log_method_call



class SCItemHandler(SCHandler):
    """Обработчик для управления приёмкой товаров в сервисном центре"""

    @log_method_call
    async def handle_item_acceptance(self, update: Update, context: CallbackContext):
        """Обработка принятия товара СЦ"""
        query = update.callback_query
        await query.answer()
        # Правильно разбираем callback_data
        parts = query.data.split('_')
        action = parts[0]  # accept или reject
        request_id = parts[-1]
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("Заявка не найдена.")
            return ConversationHandler.END
        if action == "accept":
            await query.edit_message_text(
                "Пожалуйста, сделайте фото товара.\n"
                "Когда закончите, нажмите\n\n/DONE"
            )
            context.user_data['awaiting_photo_sc'] = request_id
            return CREATE_REQUEST_PHOTOS
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
            return ConversationHandler.END

    @log_method_call
    async def handle_photo_upload(self, update: Update, context: CallbackContext):
        """Обработка загрузки фото товара"""
        request_id = context.user_data.get('awaiting_photo_sc')
        if not request_id:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END
        requests_data = await load_requests()
        if request_id not in requests_data:
            await update.message.reply_text("Заявка не найдена.")
            return ConversationHandler.END
        # Сохраняем фото
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/sc_acceptance_{request_id}_{len(context.user_data.get('sc_photos', []))}.jpg"
        await photo_file.download_to_drive(photo_path)        
        # Сохраняем путь к фото в контексте
        if 'sc_photos' not in context.user_data:
            context.user_data['sc_photos'] = [] 
        context.user_data['sc_photos'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Когда закончите, нажмите\n\n/DONE")
        return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def handle_photos_done(self, update: Update, context: CallbackContext):
        """Завершение загрузки фотографий СЦ"""
        try:
            # Проверка наличия request_id в контексте
            request_id = context.user_data.get('awaiting_photo_sc')
            if not request_id:
                await update.message.reply_text("Ошибка: сессия устарела. Начните заново.")
                return ConversationHandler.END
            # Проверка наличия фотографий
            photos = context.user_data.get('sc_photos', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            # Загрузка данных
            requests_data = await load_requests()
            # Проверка существования заявки
            if request_id not in requests_data:
                await update.message.reply_text("Ошибка: заявка не найдена.")
                return ConversationHandler.END
            # Обновление данных заявки
            request_data = requests_data[request_id]
            request_data.update({
                'status': ORDER_STATUS_IN_SC,
                'sc_acceptance_photos': photos
            })
            await save_requests(requests_data)
            # Обновление задач доставки
            delivery_tasks = await load_delivery_tasks()
            for task in delivery_tasks.values():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_IN_SC
                    break
            await save_delivery_tasks(delivery_tasks)
            # Уведомление клиента
            client_id = request_data.get('user_id')
            if client_id:
                await notify_client(
                    context.bot,
                    client_id,
                    "Ваш товар принят Сервисным Центром и готов к диагностике."
                )
            # Уведомление администраторов
            for admin_id in ADMIN_IDS:
                # Сначала отправляем фотографии
                for photo_path in photos:
                    if not os.path.exists(photo_path):
                        continue
                    with open(photo_path, 'rb') as photo_file:
                        await context.bot.send_photo(
                            chat_id=admin_id,
                            photo=photo_file,
                            caption=f"Фото товара по заявке #{request_id}"
                        )
                # Затем отправляем текстовое сообщение
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"✅ Товар по заявке #{request_id} принят СЦ\nСтатус: {ORDER_STATUS_IN_SC}"
                )
            # Уведомление доставщика
            delivery_id = request_data.get('assigned_delivery')
            await context.bot.send_message(
                chat_id=int(delivery_id),
                text=f"✅ Товар по заявке #{request_id} успешно передан в СЦ.\n"
                        f"Статус: {ORDER_STATUS_IN_SC}"
            )
            # Очистка контекста
            context.user_data.pop('awaiting_photo_sc', None)
            context.user_data.pop('sc_photos', None)
            await update.message.reply_text("✅ Товар принят в работу.")
            return ConversationHandler.END
        except Exception:
            await update.message.reply_text("⚠️ Произошла критическая ошибка при загрузке фото. Обратитесь к администратору.")
            return ConversationHandler.END

    @log_method_call
    async def handle_reject_reason(self, update: Update, context: CallbackContext):
        """Обработка причины отказа в приеме товара"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("Заявка не найдена.")
            return
        # Обновляем статус заявки
        requests_data[request_id]['status'] = "Отказано в приёмке СЦ"
        await save_requests(requests_data)
        # Уведомляем клиента
        client_id = requests_data[request_id]['user_id']
        await notify_client(
            context.bot,
            client_id,
            "СЦ отказал в приёмке вашего товара. Пожалуйста, свяжитесь с администратором."
        )
        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"СЦ отказал в приёмке товара по заявке #{request_id}"
            )
        await query.edit_message_text("Отказ в приёмке товара зарегистрирован.")
