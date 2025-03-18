from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.base_handler import BaseHandler
from database import (
    load_requests, save_requests, load_users, load_service_centers, save_users
)
import logging

logger = logging.getLogger(__name__)

class SCHandler(BaseHandler):

    async def show_sc_requests(self, update: Update, context: CallbackContext):
        """Показать список заявок, привязанных к данному СЦ"""
        user_id = str(update.effective_user.id)
        logger.info(f"Вызов метода show_sc_requests для пользователя {user_id}")
        
        # Добавим проверку типа сообщения
        if not update.message:
            logger.error("update.message отсутствует")
            return
        
        users_data = load_users()
        logger.info(f"Данные пользователя: {users_data.get(user_id, {})}")
        
        # Проверяем роль пользователя
        if user_id not in users_data or users_data[user_id].get('role') != 'sc':
            logger.error(f"Пользователь {user_id} не является сотрудником СЦ")
            await update.message.reply_text("Ошибка: у вас нет прав доступа к заявкам СЦ.")
            return
        
        sc_id = users_data[user_id].get('sc_id')
        logger.info(f"Найден SC_ID: {sc_id}")
        
        if not sc_id:
            # Существующий код автоматического назначения SC по номеру телефона
            service_centers = load_service_centers()
            user_phone = users_data[user_id].get('phone', '')
            
            for center_id, center_data in service_centers.items():
                center_phone = center_data.get('phone', '')
                if center_phone and user_phone:  # Проверяем, что номера не пустые
                    # Нормализуем номера телефонов
                    center_phone = center_phone.replace('+', '').replace('-', '').replace(' ', '')
                    user_phone = user_phone.replace('+', '').replace('-', '').replace(' ', '')
                    
                    if center_phone == user_phone:
                        sc_id = center_id
                        users_data[user_id]['sc_id'] = sc_id
                        save_users(users_data)
                        logger.info(f"Автоматически назначен SC_ID: {sc_id} для пользователя {user_id}")
                        break
        
        if not sc_id:
            logger.error(f"Пользователь {user_id} не привязан к СЦ")
            await update.message.reply_text("Ошибка: Вы не привязаны к конкретному СЦ. Обратитесь к администратору.")
            return
        
        # Загружаем заявки
        requests_data = load_requests()
        if not isinstance(requests_data, dict):
            logger.error(f"Неверный формат данных заявок: {type(requests_data)}")
            await update.message.reply_text("Ошибка при загрузке заявок.")
            return
        
        sc_requests = []
        for req_id, req_data in requests_data.items():
            if isinstance(req_data, dict) and req_data.get('assigned_sc') == sc_id:
                sc_requests.append((req_id, req_data))
        
        logger.info(f"Найдено {len(sc_requests)} заявок для СЦ {sc_id}")
        
        if not sc_requests:
            await update.message.reply_text("У вас пока нет назначенных заявок.")
            return
        
        # Создаем инлайн клавиатуру
        keyboard = []
        for req_id, req_data in sc_requests:
            status = req_data.get('status', 'Статус неизвестен')
            category = req_data.get('category', 'Категория не указана')
            button_text = f"#{req_id} - {category} - {status}"
            callback_data = f"sc_request_{req_id}"
            
            # Проверяем длину callback_data
            if len(callback_data) > 64:
                logger.warning(f"callback_data слишком длинный: {len(callback_data)} символов")
                callback_data = callback_data[:64]
            
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await update.message.reply_text(
                "Список ваших заявок:",
                reply_markup=reply_markup
            )
            logger.info("Сообщение с клавиатурой успешно отправлено")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения с клавиатурой: {e}")
            await update.message.reply_text(f"Ошибка при отображении заявок: {str(e)}")
    
    async def handle_request_select(self, update: Update, context: CallbackContext):
        """Обработка выбора заявки из списка"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 3:
            await query.edit_message_text("Ошибка в формате данных.")
            return
        request_id = parts[2]
        requests_data = load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("Заявка не найдена.")
            return
        request = requests_data[request_id]
        # Детали заявки
        client_id = request.get('user_id')
        users_data = load_users()
        client_name = users_data.get(client_id, {}).get('name', 'Неизвестный клиент')
        client_phone = users_data.get(client_id, {}).get('phone', 'Телефон не указан')
        # Выводим информацию о заявке
        message = (
            f"Заявка #{request_id}\n"
            f"Клиент: {client_name}\n"
            f"Телефон: {client_phone}\n"
            f"Категория: {request.get('category', 'Не указана')}\n"
            f"Описание: {request.get('description', 'Не указано')}\n"
            f"Статус: {request.get('status', 'Не указан')}\n"
        )
        # Создаем клавиатуру действий
        keyboard = [
            [InlineKeyboardButton("Открыть чат с клиентом", callback_data=f"sc_chat_{request_id}")],
            [InlineKeyboardButton("Добавить комментарий", callback_data=f"sc_comment_{request_id}")],
            [InlineKeyboardButton("Назад к списку", callback_data="sc_back_to_list")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def handle_chat_start(self, update: Update, context: CallbackContext):
        """Начало чата с клиентом"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        # Сохраняем ID заявки в контексте пользователя
        context.user_data['current_chat_request'] = request_id
        # Загружаем данные о заявке
        requests_data = load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("Заявка не найдена.")
            return
        client_id = requests_data[request_id].get('user_id')
        users_data = load_users()
        client_name = users_data.get(client_id, {}).get('name', 'Клиент')
        await query.edit_message_text(
            f"Чат с клиентом {client_name} (заявка #{request_id})\n"
            "Введите сообщение для клиента. Для выхода из чата нажмите /exit"
        )
        # Устанавливаем флаг, что ожидается сообщение для чата
        context.user_data['awaiting_chat_message'] = True
    
    async def handle_chat_message(self, update: Update, context: CallbackContext):
        """Обработка сообщения в чате с клиентом"""
        # Проверяем, ожидается ли сообщение для чата
        if not context.user_data.get('awaiting_chat_message'):
            return
        request_id = context.user_data.get('current_chat_request')
        if not request_id:
            await update.message.reply_text("Ошибка: чат не инициализирован.")
            context.user_data['awaiting_chat_message'] = False
            return
        message_text = update.message.text
        if message_text == '/exit':
            await update.message.reply_text("Чат завершен.")
            context.user_data['awaiting_chat_message'] = False
            context.user_data.pop('current_chat_request', None)
            # Возвращаем пользователя в основное меню СЦ
            keyboard = [
                ["Мои заявки", "Отправить в доставку"],
                ["Связаться с администратором"],
                ["Документы"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Меню СЦ:", reply_markup=reply_markup)
            return
        # Отправляем сообщение клиенту
        requests_data = load_requests()
        if request_id not in requests_data:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            context.user_data['awaiting_chat_message'] = False
            return
        client_id = requests_data[request_id].get('user_id')
        sc_name = "Сервисный центр"
        # Получаем имя СЦ
        user_id = str(update.effective_user.id)
        users_data = load_users()
        if user_id in users_data and users_data[user_id].get('role') == 'sc':
            sc_id = users_data[user_id].get('sc_id')
            if sc_id:
                service_centers = load_service_centers()
                sc_name = service_centers.get(sc_id, {}).get('name', sc_name)
        # Формируем сообщение для клиента
        client_message = (
            f"Сообщение от {sc_name} по заявке #{request_id}:\n\n"
            f"{message_text}"
        )
        # Отправляем сообщение клиенту
        try:
            await context.bot.send_message(chat_id=client_id, text=client_message)
            await update.message.reply_text("✅ Сообщение отправлено клиенту.")
            # Обновляем историю сообщений в заявке
            if 'messages' not in requests_data[request_id]:
                requests_data[request_id]['messages'] = []
            
            requests_data[request_id]['messages'].append({
                'from': 'sc',
                'text': message_text,
                'timestamp': str(update.message.date)
            })
            save_requests(requests_data)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения клиенту: {e}")
            await update.message.reply_text("Ошибка при отправке сообщения клиенту.")
    
    async def handle_comment(self, update: Update, context: CallbackContext):
        """Обработка добавления комментария к заявке"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        context.user_data['awaiting_comment'] = request_id
        await query.edit_message_text(
            f"Введите комментарий для заявки #{request_id}. Для отмены нажмите /cancel"
        )
    
    async def handle_comment_text(self, update: Update, context: CallbackContext):
        """Обработка текста комментария"""
        request_id = context.user_data.get('awaiting_comment')
        if not request_id:
            return
        comment_text = update.message.text
        if comment_text == '/cancel':
            await update.message.reply_text("Добавление комментария отменено.")
            context.user_data.pop('awaiting_comment', None)
            return
        # Добавляем комментарий к заявке
        requests_data = load_requests()
        if request_id not in requests_data:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            context.user_data.pop('awaiting_comment', None)
            return
        # Добавляем комментарий в заявку
        if 'comments' not in requests_data[request_id]:
            requests_data[request_id]['comments'] = []
        requests_data[request_id]['comments'].append({
            'from': 'sc',
            'text': comment_text,
            'timestamp': str(update.message.date)
        })
        save_requests(requests_data)
        await update.message.reply_text(f"✅ Комментарий добавлен к заявке #{request_id}")
        context.user_data.pop('awaiting_comment', None)
    
    async def handle_back_to_list(self, update: Update, context: CallbackContext):
        """Возврат к списку заявок"""
        query = update.callback_query
        await query.answer()
        # Вызываем метод просмотра списка заявок
        await query.delete_message()
        await self.show_sc_requests(update, context)
