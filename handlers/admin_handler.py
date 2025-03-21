import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, ConversationHandler
from .base_handler import BaseHandler
from database import (
    load_delivery_tasks, load_requests, load_service_centers,
    load_users, save_delivery_tasks, save_requests, save_users
)
from config import (
    ASSIGN_REQUEST, ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK,
    ORDER_STATUS_ASSIGNED_TO_SC
)
from utils import notify_delivery
logger = logging.getLogger(__name__)

#  TODO: Согласование цены


class AdminHandler(BaseHandler):

    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        """Обработка выбора заявки для привязки к СЦ"""
        query = update.callback_query
        await query.answer()
        try:
            parts = query.data.split('_')
            logger.info(f"Callback data parts: {parts}")
            if len(parts) < 3:
                await query.edit_message_text("Неверный формат данных")
                return ConversationHandler.END
            if 'confirm' in parts:
                request_id = parts[3]
            else:
                request_id = parts[2]
            logger.info(f"Processing request_id: {request_id}")
            requests_data = load_requests()
            logger.info(f"Available requests: {list(requests_data.keys())}")
            if request_id not in requests_data:
                await query.edit_message_text(f"Заявка #{request_id} не найдена")
                return ConversationHandler.END
            service_centers = load_service_centers()
            if not service_centers:
                await query.edit_message_text("Нет доступных сервисных центров.")
                return ConversationHandler.END
            keyboard = []
            for sc_id, sc_data in service_centers.items():
                callback_data = f"assign_sc_confirm_{request_id}_{sc_id}"
                logger.info(f"Creating button with callback_data: {callback_data}")
                keyboard.append([
                    InlineKeyboardButton(
                        f"{sc_data['name']} - {sc_data.get('address', 'Адрес не указан')}", 
                        callback_data=callback_data
                    )
                ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Выберите сервисный центр для заявки #{request_id}:",
                reply_markup=reply_markup
            )
            return ASSIGN_REQUEST
        except Exception as e:
            logger.error(f"Error in handle_assign_sc: {e}")
            await query.edit_message_text(f"Произошла ошибка при обработке заявки: {str(e)}")
            return ConversationHandler.END

    async def handle_assign_sc_confirm(self, update: Update, context: CallbackContext):
        """Подтверждение привязки заявки к СЦ"""
        query = update.callback_query
        await query.answer()
        logger.info(f"Received callback query in handle_assign_sc_confirm: {query.data}")
        try:
            parts = query.data.split('_')
            logger.info(f"Parts: {parts}")
            if len(parts) < 5:
                logger.error(f"Invalid data format: {query.data}")
                await query.edit_message_text("Неверный формат данных")
                return ConversationHandler.END
            request_id = parts[3]
            sc_id = parts[4]
            logger.info(f"Request ID: {request_id}, SC ID: {sc_id}")
            requests_data = load_requests()
            logger.info(f"Loaded requests: {list(requests_data.keys())}")
            service_centers = load_service_centers()
            logger.info(f"Loaded service centers: {list(service_centers.keys())}")
            if request_id not in requests_data:
                logger.error(f"Request {request_id} not found")
                await query.edit_message_text(f"Заявка #{request_id} не найдена")
                return ConversationHandler.END
            if sc_id not in service_centers:
                logger.error(f"Service center {sc_id} not found")
                await query.edit_message_text(f"Сервисный центр с ID {sc_id} не найден")
                return ConversationHandler.END
            sc_data = service_centers[sc_id]
            requests_data[request_id].update({
                'assigned_sc': sc_id,
                'status': ORDER_STATUS_ASSIGNED_TO_SC
            })
            save_requests(requests_data)
            logger.info(f"Updated request {request_id} with SC {sc_id}")
            new_text = f"Заявка #{request_id} привязана к СЦ {sc_data['name']}."
            await query.edit_message_text(new_text)
            logger.info(f"Message updated for request {request_id}")
            task_id, task_data = await self.create_delivery_task(update, context, request_id, sc_data['name'])
            logger.info(f"Request {request_id} successfully assigned to SC {sc_id} and delivery task {task_id} created")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in handle_assign_sc_confirm: {e}")
            await query.edit_message_text(f"Произошла ошибка при привязке заявки к СЦ: {str(e)}")
            return ConversationHandler.END

    async def update_delivery_info(self, context: CallbackContext, chat_id: int, message_id: int, request_id: str, delivery_info: dict):
        """Обновление информации о доставщике"""
        new_text = (
            f"Заявка #{request_id} принята доставщиком:\n"
            f"Имя: {delivery_info['name']}\n"
            f"Телефон: +{delivery_info['phone']}"
        )
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=new_text
        )

    async def create_delivery_task(self, update: Update, context: CallbackContext, request_id: str, sc_name: str):
        """Создание задачи доставки"""
        logger.info(f"Creating delivery task for request {request_id} to SC {sc_name}")
        delivery_tasks = load_delivery_tasks() or {}
        task_id = str(len(delivery_tasks) + 1)
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        client_id = request.get('user_id')
        client_data = load_users().get(str(client_id), {})
        # Извлекаем фотографии из заявки
        delivery_photos = request.get('photos', [])
        delivery_task = {
            'task_id': task_id,
            'request_id': request_id,
            'status': 'Новая',
            'sc_name': sc_name,
            'client_address': request.get('location', 'Адрес не указан'),
            'client_name': client_data.get('name', 'Имя не указано'),
            'client_phone': client_data.get('phone', 'Телефон не указан'),
            'description': request.get('description', 'Описание отсутствует'),
            'latitude': request.get('latitude'),
            'longitude': request.get('longitude'),
            'delivery_photos': delivery_photos,  # Добавляем фотографии
            'assigned_delivery_id': None
        }
        delivery_tasks[task_id] = delivery_task
        save_delivery_tasks(delivery_tasks)
        await notify_delivery(context.bot, DELIVERY_IDS, delivery_task, detailed=True)
        return task_id, delivery_task

    async def notify_deliveries(self, context: CallbackContext, task_data: dict):
        """Отправка уведомлений доставщикам о новой задаче"""
        message = (
            f"🆕 Новая задача доставки!\n\n"
            f"Заявка: #{task_data['request_id']}\n"
            f"Сервисный центр: {task_data['sc_name']}\n"
            f"Адрес клиента: {task_data['client_address']}\n"
            f"Клиент: {task_data['client_name']}\n"
            f"Телефон: {task_data['client_phone']}\n"
            f"Описание: {task_data['description']}"
        )        
        keyboard = [[
            InlineKeyboardButton(
                "Принять задачу", 
                callback_data=f"accept_delivery_{task_data['request_id']}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)        
        for delivery_id in DELIVERY_IDS:
            try:
                await context.bot.send_message(
                    chat_id=delivery_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                logger.info(f"Notification sent to delivery {delivery_id}")
            except Exception as e:
                logger.error(f"Error sending notification to delivery {delivery_id}: {e}")

    async def handle_accept_delivery(self, update: Update, context: CallbackContext):
        """Обработка принятия задачи доставщиком"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) >= 3:
            task_id = parts[2]
        else:
            await query.edit_message_text("Неверный формат данных")
            return
        delivery_tasks = load_delivery_tasks()
        if task_id in delivery_tasks:
            delivery_task = delivery_tasks[task_id]
            delivery_task['status'] = 'Принято'
            delivery_task['delivery_id'] = query.from_user.id
            save_delivery_tasks(delivery_tasks)
            # Обновляем сообщение о заявке
            requests_data = load_requests()
            request_id = delivery_task['request_id']
            if request_id in requests_data:
                request = requests_data[request_id]
                user = load_users().get(str(query.from_user.id), {})
                delivery_name = user.get('name', 'Неизвестный доставщик')
                delivery_phone = user.get('phone', 'Номер не указан')
                new_text = f"{query.message.text}\n\n_Задание взял доставщик: {delivery_name} - +{delivery_phone}_"
                for admin_id in ADMIN_IDS:
                    try:
                        message_id = request.get('message_id')
                        if message_id:
                            await context.bot.edit_message_text(
                                chat_id=admin_id,
                                message_id=message_id,
                                text=new_text,
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        print(f"Ошибка при обновлении сообщения для админа {admin_id}: {e}")
            await query.edit_message_text(f"Вы приняли задачу доставки #{task_id}")
        else:
            await query.edit_message_text(f"Задача доставки #{task_id} не найдена")

    async def view_requests(self, update: Update, context: CallbackContext):
        """Просмотр активных заявок"""
        requests_data = load_requests()
        if not requests_data:
            await update.message.reply_text("Нет активных заявок.")
        else:
            reply = "Активные заявки:\n\n"
            for req_id, req in requests_data.items():
                reply += f"Заявка #{req_id}\n"
                reply += f"Статус: {req.get('status', 'Не указан')}\n"
                reply += f"Описание: {req.get('description', 'Нет описания')[:50]}...\n"
                reply += f"Район: {req.get('district', 'Не указан')}\n\n"
            await update.message.reply_text(reply)

    async def assign_request(self, update: Update, context: CallbackContext):
        """Начало процесса привязки заявки к СЦ"""
        requests_dict = load_requests()
        if not requests_dict:
            await update.message.reply_text("Нет активных заявок для привязки.")
            return ConversationHandler.END
        keyboard = []
        for req_id, req_data in requests_dict.items():
            if not req_data.get('assigned_sc'):
                status = req_data.get('status', 'Статус не указан')
                desc = req_data.get('description', 'Нет описания')[:30] + '...'
                button_text = f"Заявка #{req_id} - {status} - {desc}"
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"assign_sc_{req_id}"
                )])
        if not keyboard:
            await update.message.reply_text("Нет заявок, требующих привязки к СЦ.")
            return ConversationHandler.END
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите заявку для привязки к сервисному центру:",
            reply_markup=reply_markup
        )
        return ASSIGN_REQUEST

    async def view_service_centers(self, update: Update, context: CallbackContext):
        """Просмотр списка сервисных центров"""
        service_centers = load_service_centers()
        logger.info(f"Loaded service centers: {service_centers}")
        if not service_centers:
            await update.message.reply_text("Список СЦ пуст.")
        else:
            reply = "Список сервисных центров:\n\n"
            for sc_id, sc_data in service_centers.items():
                reply += f"ID: {sc_id}\n"
                reply += f"Название: {sc_data['name']}\n"
                reply += f"Адрес: {sc_data.get('address', 'Не указан')}\n"
                reply += "-------------------\n"        
            await update.message.reply_text(reply)

    async def handle_create_delivery(self, update: Update, context: CallbackContext):
        """Обработчик создания задачи доставки"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 3:
            await query.edit_message_text("Неверный формат данных")
            return
        request_id = parts[2]
        sc_id = parts[3]
        service_centers = load_service_centers()
        if sc_id not in service_centers:
            await query.edit_message_text("Сервисный центр не найден")
            return
        service_center = service_centers[sc_id]
        task_id, task_data = await self.create_delivery_task(update, context, request_id, service_center['name'])
        await query.edit_message_text(
            f"Задача доставки #{task_id} для заявки #{request_id} создана.\n"
            f"Доставщики уведомлены."
        )

    async def handle_create_delivery_menu(self, update: Update, context: CallbackContext):
        """Обработчик кнопки создания задачи доставки из меню"""
        await update.message.reply_text("Введите номер заявки для создания задачи доставки:")
        return CREATE_DELIVERY_TASK

    async def handle_create_delivery_input(self, update: Update, context: CallbackContext):
        """Обработчик ввода номера заявки для создания задачи доставки"""
        request_id = update.message.text.strip()
        requests_data = load_requests()
        if request_id not in requests_data:
            await update.message.reply_text(f"Заявка #{request_id} не найдена")
            return ConversationHandler.END
        request = requests_data[request_id]
        if not request.get('assigned_sc'):
            await update.message.reply_text("Заявка должна быть сначала привязана к сервисному центру")
            return ConversationHandler.END
        service_centers = load_service_centers()
        sc_id = request['assigned_sc']
        sc_name = next((sc['name'] for sc in service_centers if str(sc['id']) == str(sc_id)), None)
        if not sc_name:
            await update.message.reply_text("Сервисный центр не найден")
            return ConversationHandler.END
        task_id, task_data = await self.create_delivery_task(update, context, request_id, sc_name)
        await update.message.reply_text(f"Задача доставки #{task_id} создана. Доставщики уведомлены.")
        return ConversationHandler.END

    async def handle_reject_request(self, update: Update, context: CallbackContext):
        """Обработка отклонения заявки"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        keyboard = [
            [
                InlineKeyboardButton("Да, заблокировать", callback_data=f"block_user_{request_id}_confirm"),
                InlineKeyboardButton("Нет", callback_data=f"block_user_{request_id}_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        requests_data = load_requests()
        request = requests_data.get(request_id)
        if request:
            request['status'] = 'Отклонена'
            save_requests(requests_data)
            await query.edit_message_text(
                f"Заявка #{request_id} отклонена.\n\nЗаблокировать клиента {request.get('user_name', 'Неизвестный')}?",
                reply_markup=reply_markup
            )
            await context.bot.send_message(
                chat_id=request['user_id'],
                text=f"Ваша заявка #{request_id} была отклонена администратором."
            )

    async def handle_block_user(self, update: Update, context: CallbackContext):
        """Обработка блокировки пользователя"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        request_id = parts[2]
        action = parts[3]
        if action == 'cancel':
            await query.edit_message_text(f"Заявка #{request_id} отклонена. Клиент не заблокирован.")
            return
        requests_data = load_requests()
        request = requests_data.get(request_id)
        if request and action == 'confirm':
            users_data = load_users()
            user_id = request['user_id']
            if user_id in users_data:
                users_data[user_id]['blocked'] = True
                save_users(users_data)
                await query.edit_message_text(
                    f"Заявка #{request_id} отклонена.\n"
                    f"Клиент {request.get('user_name', 'Неизвестный')} заблокирован."
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Ваш аккаунт был заблокирован администратором."
                )

    async def handle_create_delivery_from_sc(self, update: Update, context: CallbackContext):
        """Обработка создания задачи доставки по запросу от СЦ"""
        query = update.callback_query
        await query.answer()
        
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        
        if request_id not in requests_data:
            await query.edit_message_text(f"Заявка #{request_id} не найдена")
            return
        
        request = requests_data[request_id]
        sc_id = request.get('assigned_sc')
        
        if not sc_id:
            await query.edit_message_text("Ошибка: СЦ не назначен для этой заявки")
            return
        
        service_centers = load_service_centers()
        sc_data = service_centers.get(sc_id, {})
        sc_name = sc_data.get('name', 'Неизвестный СЦ')
        
        # Создаем задачу доставки с пометкой, что это доставка из СЦ клиенту
        delivery_tasks = load_delivery_tasks() or {}
        task_id = str(len(delivery_tasks) + 1)
        
        delivery_task = {
            'task_id': task_id,
            'request_id': request_id,
            'status': 'Новая',
            'type': 'sc_to_client',  # Добавляем тип доставки
            'sc_name': sc_name,
            'sc_id': sc_id,
            'client_address': request.get('location', 'Адрес не указан'),
            'client_name': request.get('client_name', 'Имя не указано'),
            'client_phone': request.get('client_phone', 'Телефон не указан'),
            'description': request.get('description', 'Описание отсутствует'),
            'latitude': request.get('latitude'),
            'longitude': request.get('longitude'),
            'assigned_delivery_id': None
        }
        
        delivery_tasks[task_id] = delivery_task
        save_delivery_tasks(delivery_tasks)
        
        # Уведомляем доставщиков
        delivery_message = (
            f"🆕 Новая задача доставки из СЦ клиенту!\n\n"
            f"Заявка: #{request_id}\n"
            f"Забрать из: {sc_name}\n"
            f"Адрес клиента: {delivery_task['client_address']}\n"
            f"Клиент: {delivery_task['client_name']}\n"
            f"Телефон: {delivery_task['client_phone']}\n"
            f"Описание: {delivery_task['description']}"
        )
        
        keyboard = [[
            InlineKeyboardButton(
                "Принять задачу", 
                callback_data=f"accept_delivery_from_sc_{task_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for delivery_id in DELIVERY_IDS:
            try:
                await context.bot.send_message(
                    chat_id=delivery_id,
                    text=delivery_message,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления доставщику {delivery_id}: {e}")
        
        await query.edit_message_text(
            f"✅ Задача доставки #{task_id} создана и отправлена доставщикам.\n"
            f"Заявка: #{request_id}"
        )
