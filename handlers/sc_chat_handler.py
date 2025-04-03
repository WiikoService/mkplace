import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.ext import CallbackContext, ConversationHandler
from handlers.sc_handler import SCHandler
from database import load_requests, load_chat_history, save_chat_history, load_users
import logging
import os

logger = logging.getLogger(__name__)


class SCChatHandler(SCHandler):
    """Обработчик для управления чатом между СЦ и клиентом"""

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
        
        # Кнопки Inline для сохранения функциональности
        inline_keyboard = [
            [InlineKeyboardButton("❌ Закрыть чат", callback_data=f"close_chat_{request_id}")],
            [InlineKeyboardButton("📨 История переписки", callback_data=f"chat_history_{request_id}")]
        ]
        
        # Добавляем обычную клавиатуру для предотвращения конфликтов
        reply_keyboard = [
            ["❌ Закрыть чат"], 
            ["📨 История переписки"]
        ]
        reply_markup_keyboard = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        
        await query.edit_message_text(
            text=f"💬 Чат по заявке #{request_id}\n"
                 "Отправьте сообщение для клиента:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard)
        )
        
        # Отправляем дополнительное сообщение с клавиатурой
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Используйте клавиатуру ниже для управления чатом:",
            reply_markup=reply_markup_keyboard
        )
        
        return 'HANDLE_SC_CHAT'

    async def handle_sc_chat(self, update: Update, context: CallbackContext):
        """Обработка сообщений от СЦ"""
        message = update.message
        
        # Проверяем, не была ли нажата одна из кнопок клавиатуры
        if message.text == "❌ Закрыть чат":
            context.user_data.pop('active_chat', None)
            await message.reply_text("Чат закрыт", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        
        if message.text == "📨 История переписки":
            chat_data = context.user_data.get('active_chat', {})
            request_id = chat_data.get('request_id')
            if request_id:
                await self.show_chat_history_keyboard(update, context, request_id)
            return 'HANDLE_SC_CHAT'
        
        # Получаем данные чата
        chat_data = context.user_data.get('active_chat', {})
        request_id = chat_data.get('request_id')
        client_id = chat_data['participants']['client_id']
        timestamp = datetime.now().strftime("%H:%M %d-%m-%Y")
        
        # Формируем кнопку ответа
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✉️ Ответить", callback_data=f"client_reply_{request_id}")
        ]])
        
        try:
            # Проверяем, отправлено ли фото
            if message.photo:
                # Получаем фото с наилучшим качеством (последнее в списке)
                photo = message.photo[-1]
                photo_file = await context.bot.get_file(photo.file_id)
                
                # Создаем уникальное имя файла
                file_name = f"chat_sc_{request_id}_{timestamp.replace(':', '-').replace(' ', '_')}.jpg"
                photo_path = f"photos/{file_name}"
                
                # Скачиваем и сохраняем фото
                await photo_file.download_to_drive(photo_path)
                
                # Отправляем фото клиенту
                caption = f"📷 *Фото от СЦ по заявке #{request_id}*"
                if message.caption:
                    caption += f"\n{message.caption}"
                    
                await context.bot.send_photo(
                    chat_id=int(client_id),
                    photo=open(photo_path, 'rb'),
                    caption=caption,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                
                # Сохраняем в историю
                self.save_chat_history(
                    request_id,
                    'sc',
                    f"[ФОТО: {photo_path}]" + (f" с комментарием: {message.caption}" if message.caption else ""),
                    timestamp,
                    photo_path=photo_path
                )
                
                await message.reply_text("✅ Фото доставлено")
                
            else:  # Это текстовое сообщение
                # Отправляем текст клиенту
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=f"📩 *Сообщение от СЦ по заявке #{request_id}:*\n{message.text}",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                
                # Сохраняем в историю
                self.save_chat_history(
                    request_id,
                    'sc',
                    message.text,
                    timestamp
                )
                
                await message.reply_text("✅ Сообщение доставлено")
                
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
        
        # Добавляем обычную клавиатуру для клиента
        reply_keyboard = [
            ["❌ Отменить отправку"]
        ]
        reply_markup_keyboard = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        
        # Inline-кнопка для совместимости
        inline_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_chat_{request_id}")]
        ])
        
        await query.message.reply_text(
            "💬 Режим ответа активирован. Отправьте сообщение:",
            reply_markup=inline_markup
        )
        
        # Отправляем дополнительное сообщение с клавиатурой
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Используйте клавиатуру ниже для управления:",
            reply_markup=reply_markup_keyboard
        )
        
        return 'HANDLE_CLIENT_REPLY'

    async def handle_client_message(self, update: Update, context: CallbackContext):
        """Обработка сообщений от клиента"""
        message = update.message
        
        # Проверяем, не была ли нажата кнопка отмены
        if message.text == "❌ Отменить отправку":
            context.user_data.pop('active_client_chat', None)
            await message.reply_text("✅ Отправка сообщения отменена", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        
        # Проверяем валидность сессии
        chat_data = context.user_data.get('active_client_chat')
        if not chat_data or time.time() - chat_data.get('last_active', 0) > 300:
            await message.reply_text("❌ Сессия устарела. Начните новый диалог.", reply_markup=ReplyKeyboardRemove())
            context.user_data.pop('active_client_chat', None)
            return ConversationHandler.END
        
        request_id = chat_data['request_id']
        sc_user_id = chat_data['sc_user_id']
        timestamp = datetime.now().strftime("%H:%M %d-%m-%Y")
        
        try:
            # Обработка фото
            if message.photo:
                # Получаем фото с наилучшим качеством
                photo = message.photo[-1]
                photo_file = await context.bot.get_file(photo.file_id)
                
                # Создаем уникальное имя файла
                file_name = f"chat_client_{request_id}_{timestamp.replace(':', '-').replace(' ', '_')}.jpg"
                photo_path = f"photos/{file_name}"
                
                # Скачиваем и сохраняем фото
                await photo_file.download_to_drive(photo_path)
                
                # Отправляем фото в СЦ
                caption = f"📷 *Фото от клиента по заявке #{request_id}*"
                if message.caption:
                    caption += f"\n{message.caption}"
                    
                await context.bot.send_photo(
                    chat_id=int(sc_user_id),
                    photo=open(photo_path, 'rb'),
                    caption=caption,
                    parse_mode='Markdown'
                )
                
                # Сохраняем в историю
                self.save_chat_history(
                    request_id,
                    'client',
                    f"[ФОТО: {photo_path}]" + (f" с комментарием: {message.caption}" if message.caption else ""),
                    timestamp,
                    photo_path=photo_path
                )
                
            else:  # Это текстовое сообщение
                # Отправляем текст в СЦ
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
                    timestamp
                )
            
            # Обновляем временную метку активности
            context.user_data['active_client_chat']['last_active'] = time.time()
            
            # Показываем кнопки для продолжения общения
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

    def save_chat_history(self, request_id, sender, message, timestamp, photo_path=None):
        """Сохранение истории переписки"""
        chat_history = load_chat_history()
        entry = {
            'sender': sender,
            'message': message,
            'timestamp': timestamp
        }
        
        # Если есть фото, добавляем его путь
        if photo_path:
            entry['photo_path'] = photo_path
        
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
        
        # Удаляем клавиатуру
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Чат закрыт",
            reply_markup=ReplyKeyboardRemove()
        )
        
        return ConversationHandler.END

    async def cancel_client_chat(self, update: Update, context: CallbackContext):
        """Отмена чата клиентом"""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('active_client_chat', None)
        await query.edit_message_text("✅ Отправка сообщения отменена")
        
        # Удаляем клавиатуру
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Операция отменена",
            reply_markup=ReplyKeyboardRemove()
        )
        
        return ConversationHandler.END

    async def show_chat_history(self, update: Update, context: CallbackContext):
        """Показывает историю переписки по заявке"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        await self._show_chat_history(update, context, request_id, is_callback=True)

    async def show_chat_history_keyboard(self, update: Update, context: CallbackContext, request_id):
        """Показывает историю переписки по заявке через клавиатуру"""
        await self._show_chat_history(update, context, request_id, is_callback=False)

    async def _show_chat_history(self, update: Update, context: CallbackContext, request_id, is_callback=True):
        """Универсальный метод для отображения истории чата"""
        chat_history = load_chat_history().get(request_id, [])
        
        if not chat_history:
            if is_callback:
                await update.callback_query.message.reply_text("История переписки пуста.")
            else:
                await update.message.reply_text("История переписки пуста.")
            return
        
        history_text = f"📜 История переписки по заявке #{request_id}:\n\n"
        photo_entries = []
        
        for entry in chat_history:
            sender = "СЦ" if entry['sender'] == 'sc' else "Клиент"
            timestamp = entry.get('timestamp', '(время не указано)')
            
            # Проверяем, содержит ли сообщение фото
            if 'photo_path' in entry:
                photo_entries.append({
                    'sender': sender,
                    'message': entry['message'],
                    'timestamp': timestamp,
                    'photo_path': entry['photo_path']
                })
                history_text += f"👤 {sender} ({timestamp}): [Отправлено фото]\n\n"
            else:
                history_text += f"👤 {sender} ({timestamp}):\n{entry['message']}\n\n"
        
        # Отправляем текстовую историю
        if is_callback:
            await update.callback_query.message.reply_text(history_text)
        else:
            await update.message.reply_text(history_text)
        
        # Отправляем фотографии отдельными сообщениями
        for photo_entry in photo_entries:
            try:
                photo_path = photo_entry['photo_path']
                if os.path.exists(photo_path):
                    if is_callback:
                        await update.callback_query.message.reply_photo(
                            photo=open(photo_path, 'rb'),
                            caption=f"👤 {photo_entry['sender']} ({photo_entry['timestamp']})"
                        )
                    else:
                        await update.message.reply_photo(
                            photo=open(photo_path, 'rb'),
                            caption=f"👤 {photo_entry['sender']} ({photo_entry['timestamp']})"
                        )
                else:
                    logger.warning(f"Файл не найден: {photo_path}")
            except Exception as e:
                logger.error(f"Ошибка при отправке фото: {str(e)}") 