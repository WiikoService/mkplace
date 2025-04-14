import logging
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, CallbackQuery
from telegram.ext import CallbackContext, ConversationHandler
from database import (
    load_delivery_tasks, load_requests, load_service_centers,
    load_users, save_delivery_tasks, save_requests, save_users
)
from config import (
    ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK,
    ORDER_STATUS_PICKUP_FROM_SC, ORDER_STATUS_NEW, DEBUG
)
from utils import notify_client
from datetime import datetime
import os
from config import DATA_DIR
import time
from handlers.client_request_create import PrePaymentHandler
from datetime import timedelta
from logging_decorator import log_method_call
logger = logging.getLogger(__name__)

class AdminHandler:

    @log_method_call
    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        """Обработка нажатия кнопки 'Привязать к СЦ'"""
        logger.info("🛠️ START handle_assign_sc")
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            logger.debug(f"📝 Processing request {request_id}")
            requests_data = await load_requests()
            logger.debug(f"📦 Loaded {len(requests_data)} requests")
            request = requests_data.get(request_id)
            logger.debug(f"📄 Request data found: {request is not None}")
            if not request:
                logger.error(f"❌ Request {request_id} not found")
                await query.edit_message_text("Заявка не найдена")
                return
            # Форматируем местоположение
            location = request.get('location', {})
            if isinstance(location, dict):
                if location.get('type') == 'coordinates':
                    address = location.get('address', 'Адрес не определен')
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get('address', 'Адрес не указан')
            else:
                location_str = str(location)
            # Формируем сообщение для СЦ
            logger.debug("📝 Forming message text")
            try:
                message_text = (
                    f"📦 Заявка #{request_id}\n"
                    f"👤 Клиент: {request.get('user_name', 'Не указан')}\n"
                    f"📱 Телефон: {request.get('user_phone', 'Не указан')}\n"
                    f"📍 Адрес: {location_str}\n"
                    f"📝 Описание: {request.get('description', 'Нет описания')}\n"
                )
                # Безопасно добавляем дату
                if isinstance(request.get('desired_date'), datetime):
                    message_text += f"🕒 Желаемая дата: {request['desired_date'].strftime('%d.%m.%Y %H:%M')}"
                else:
                    message_text += f"🕒 Желаемая дата: {request.get('desired_date', 'Не указана')}"
                    
                logger.debug("📝 Message text formed successfully")
            except Exception as e:
                logger.error(f"❌ Error forming message text: {str(e)}")
                message_text = f"📦 Заявка #{request_id}"
            # Создаем клавиатуру
            keyboard = [[
                InlineKeyboardButton(
                    "📨 Разослать СЦ",
                    callback_data=f"send_to_sc_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            logger.debug("⌨️ Keyboard created")
            # Безопасно отправляем фото
            photos = request.get('photos', [])
            if photos:
                logger.debug(f"🖼️ Found {len(photos)} photos to send")
                try:
                    # Проверяем тип данных фото
                    valid_photos = []
                    for photo in photos:
                        if isinstance(photo, str):
                            valid_photos.append(InputMediaPhoto(photo))
                        else:
                            logger.warning(f"⚠️ Invalid photo type: {type(photo)}")
                    if valid_photos:
                        await query.message.reply_media_group(media=valid_photos)
                        logger.debug("🖼️ Photos sent successfully")
                except Exception as e:
                    logger.error(f"❌ Error sending photos: {str(e)}")
            # Редактируем сообщение
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info("✅ Successfully processed assign_sc request")
        except Exception as e:
            logger.error(f"🔥 Error in handle_assign_sc: {str(e)}")
            import traceback
            logger.error(f"🔥 Traceback: {traceback.format_exc()}")
            await query.edit_message_text("Произошла ошибка при обработке заявки")

    @log_method_call
    async def handle_send_to_sc(self, update: Update, context: CallbackContext):
        """Обработка рассылки СЦ"""
        logger.info("🛠️ START handle_send_to_sc")
        try:
            query = update.callback_query
            await query.answer()
            rid = query.data.split('_')[-1]
            logger.debug(f"📩 Processing request {rid}")
            # Загрузка данных
            requests_data = await load_requests()
            logger.debug(f"📥 Loaded {len(requests_data)} requests")
            if rid not in requests_data:
                logger.error(f"🚫 Request {rid} not found")
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[rid]
            # Проверяем, не была ли заявка уже принята
            if request.get('assigned_sc'):
                logger.info(f"Request {rid} already assigned to SC {request.get('assigned_sc')}")
                await query.edit_message_text("❌ Заявка уже принята другим сервисным центром")
                return
            # Форматируем местоположение
            location = request.get('location', {})
            if isinstance(location, dict):
                if location.get('type') == 'coordinates':
                    address = location.get('address', 'Адрес не определен')
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get('address', 'Адрес не указан')
            else:
                location_str = str(location)
            logger.debug(f"📄 Request data: {json.dumps(request, indent=2, ensure_ascii=False)}")
            # Поиск СЦ
            users_data = await load_users()
            sc_users = [
                (uid, u_data['sc_id']) 
                for uid, u_data in users_data.items() 
                if u_data.get('role') == 'sc' and u_data.get('sc_id')
            ]
            logger.debug(f"🔍 Found {len(sc_users)} SC users")
            if not sc_users:
                logger.warning("⚠️ No SC users available")
                await query.edit_message_text("❌ Нет доступных сервисных центров")
                return
            # Отправка уведомлений
            success_count = 0
            for uid, sc_id in sc_users:
                try:
                    logger.debug(f"✉️ Sending to SC {sc_id} (user {uid})")
                    # Отправка фото
                    if request.get('photos'):
                        media = []
                        for photo in request['photos']:
                            # Если путь к локальному файлу, открываем его
                            if photo.startswith('photos/') or photo.startswith('/'):
                                try:
                                    with open(photo, 'rb') as photo_file:
                                        media.append(InputMediaPhoto(photo_file.read()))
                                except Exception as e:
                                    logger.error(f"❌ Error opening photo file {photo}: {e}")
                                    continue
                            else:
                                # Если URL или file_id
                                media.append(InputMediaPhoto(photo))
                        if media:
                            await context.bot.send_media_group(
                                chat_id=uid,
                                media=media
                            )
                    # Отправка сообщения с форматированным адресом
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            f"📦 Новая заявка #{rid}\n\n"
                            f"👤 Клиент: {request.get('user_name', 'Не указан')}\n"
                            f"📱 Телефон: {request.get('user_phone', 'Не указан')}\n"
                            f"📍 Адрес: {location_str}\n"
                            f"📝 Описание: {request.get('description', 'Не указано')}\n"
                            f"🕒 Желаемая дата: {request.get('desired_date', 'Не указана')}"
                        ),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                "✅ Принять заявку", 
                                callback_data=f"sc_accept_{rid}"
                            )
                        ]])
                    )
                    success_count += 1
                    logger.debug(f"✅ Successfully sent to SC {sc_id}")
                except Exception as e:
                    logger.error(f"🚨 Error sending to SC {sc_id}: {str(e)}")
                    continue
            if success_count > 0:
                # Обновляем заявку
                requests_data[rid]['status'] = 'Отправлена в СЦ'
                save_requests(requests_data)
                await query.edit_message_text(f"✅ Заявка отправлена в {success_count} сервисных центров")
                logger.info(f"✅ Request sent to {success_count} service centers")
            else:
                logger.warning("📭 Failed to send to all SCs")
                await query.edit_message_text("❌ Не удалось отправить ни одному СЦ")
            logger.info("✅ FINISHED handle_send_to_sc")
        except Exception as e:
            logger.error(f"🔥 Error in handle_send_to_sc: {str(e)}")
            import traceback
            logger.error(f"🔥 Traceback: {traceback.format_exc()}")
            try:
                await query.edit_message_text("❌ Произошла ошибка при отправке заявки")
            except:
                pass

    @log_method_call
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

    @log_method_call
    async def create_delivery_task(self, update: Update, context: CallbackContext, request_id: str, sc_name: str):
        """Создание задачи доставки"""
        logger.info(f"Creating delivery task for request {request_id} to SC {sc_name}")
        delivery_tasks = await load_delivery_tasks() or {}
        task_id = str(len(delivery_tasks) + 1)
        requests_data = await load_requests()
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
        await save_delivery_tasks(delivery_tasks)
        await notify_client(context.bot, DELIVERY_IDS, delivery_task, detailed=True)
        return task_id, delivery_task

    @log_method_call
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

    @log_method_call
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
        delivery_tasks = await load_delivery_tasks()
        if task_id in delivery_tasks:
            delivery_task = delivery_tasks[task_id]
            delivery_task['status'] = 'Принято'
            delivery_task['delivery_id'] = query.from_user.id
            await save_delivery_tasks(delivery_tasks)
            # Обновляем сообщение о заявке
            requests_data = load_requests()
            request_id = delivery_task['request_id']
            if request_id in requests_data:
                request = requests_data[request_id]
                user = await load_users().get(str(query.from_user.id), {})
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

    @log_method_call
    async def view_requests(self, update: Update, context: CallbackContext):
        """Просмотр активных заявок"""
        requests_data = await load_requests()
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

    @log_method_call
    async def assign_request(self, update: Update, context: CallbackContext):
        """Отправка заявки всем СЦ"""
        query = update.callback_query
        request_id = query.data.split('_')[-1]
        try:
            requests_data = await load_requests()
            request = requests_data[request_id]
            users_data = await load_users()
            # Формируем сообщение для СЦ
            message = (
                f"📦 Новая заявка #{request_id}\n\n"
                f"Описание: {request.get('description')}\n"
                f"Адрес клиента: {request.get('location')}\n"
                f"Желаемая дата: {request.get('desired_date')}\n"
                f"Комментарий: {request.get('comment', 'Не указан')}"
            )
            keyboard = [[
                InlineKeyboardButton(
                    "Принять заявку",
                    callback_data=f"sc_accept_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Отправляем уведомление всем СЦ
            for user_id, user_data in users_data.items():
                if user_data.get('role') == 'sc':
                    # Отправляем фото, если они есть
                    if request.get('photos'):
                        media_group = []
                        for photo in request['photos']:
                            media_group.append(InputMediaPhoto(photo))
                        await context.bot.send_media_group(
                            chat_id=int(user_id),
                            media=media_group
                        )
                    # Отправляем описание с кнопкой
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=message,
                        reply_markup=reply_markup
                    )
            await query.edit_message_text("✅ Заявка отправлена всем СЦ")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при отправке заявки СЦ: {e}")
            await query.edit_message_text("❌ Произошла ошибка при отправке заявки")
            return ConversationHandler.END

    @log_method_call
    async def view_service_centers(self, update: Update, context: CallbackContext):
        """Просмотр списка сервисных центров"""
        service_centers = await load_service_centers()
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

    @log_method_call
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
        service_centers = await load_service_centers()
        if sc_id not in service_centers:
            await query.edit_message_text("Сервисный центр не найден")
            return
        service_center = service_centers[sc_id]
        task_id, task_data = await self.create_delivery_task(update, context, request_id, service_center['name'])
        await query.edit_message_text(
            f"Задача доставки #{task_id} для заявки #{request_id} создана.\n"
            f"Доставщики уведомлены."
        )

    @log_method_call
    async def handle_create_delivery_menu(self, update: Update, context: CallbackContext):
        """Обработчик кнопки создания задачи доставки из меню"""
        await update.message.reply_text("Введите номер заявки для создания задачи доставки:")
        return CREATE_DELIVERY_TASK

    @log_method_call
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
        requests_data = await load_requests()
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
                text=f"К сожалению, мы не можем найти подходящий сервисный центр, вы можете обратиться к нашему порталу с услугами для самостоятельного поиска мастерской:\ndombyta.by"
            )

    @log_method_call
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
        requests_data = await load_requests()
        request = requests_data.get(request_id)
        if request and action == 'confirm':
            users_data = await load_users()
            user_id = request['user_id']
            if user_id in users_data:
                users_data[user_id]['blocked'] = True
                await save_users(users_data)
                await query.edit_message_text(
                    f"Заявка #{request_id} отклонена.\n"
                    f"Клиент {request.get('user_name', 'Неизвестный')} заблокирован."
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Ваш аккаунт был заблокирован администратором."
                )

    @log_method_call
    async def handle_create_sc_delivery(self, update: Update, context: CallbackContext):
        """Обработка создания задачи доставки из СЦ"""
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            requests_data = await load_requests()
            delivery_tasks = await load_delivery_tasks()
            service_centers = await load_service_centers()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Ошибка: заявка не найдена.")
                return
            request = requests_data[request_id]
            # Получаем данные СЦ из service_centers по идентификатору assigned_sc
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Не указан')
            sc_address = sc_data.get('address', 'Не указан')
            # Создаем новую задачу доставки
            new_task_id = str(len(delivery_tasks) + 1)
            new_task = {
                "task_id": new_task_id,
                "request_id": request_id,
                "status": "Новая",
                "sc_name": sc_name,
                "sc_address": sc_address,
                "client_name": request.get('user_name', 'Не указан'),
                "client_address": request.get('location', 'Не указан'),
                "client_phone": request.get('user_phone', 'Не указан'),
                "description": request.get('description', 'Нет описания'),
                "delivery_type": "sc_to_client",  # Указываем тип доставки
                "is_sc_to_client": True,  # Флаг для доставки из СЦ
                "desired_date": request.get('desired_date', '')  # Копируем дату из заявки
            }
            delivery_tasks[new_task_id] = new_task
            await save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            requests_data[request_id]['status'] = ORDER_STATUS_PICKUP_FROM_SC
            await save_requests(requests_data)
            await query.edit_message_text(
                f"✅ Задача доставки #{new_task_id} создана.\n"
                f"Заявка: #{request_id}\n"
                f"Тип: Доставка из СЦ клиенту\n"
                f"СЦ: {sc_name}\n"
                f"Адрес СЦ: {sc_address}\n"
                f"Адрес клиента: {request.get('location', 'Не указан')}\n"
                f"Время доставки: {request.get('desired_date', '').split()[0]}\n"
                f"Доставщики могут принять задачу в разделе 'Доступные задания'"
            )
        except Exception as e:
            logger.error(f"Ошибка при создании задачи доставки: {e}")
            await query.edit_message_text("❌ Произошла ошибка при создании задачи доставки.")

    @log_method_call
    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        """Показ списка заявок для создания задачи доставки"""
        try:
            requests_data = await load_requests()
            available_requests = {}
            # Фильтруем заявки со статусом "Ожидает доставку"
            for request_id, request in requests_data.items():
                if request.get('status') == 'Ожидает доставку':
                    available_requests[request_id] = request
            if not available_requests:
                await update.message.reply_text("Нет заявок, ожидающих создания задачи доставки")
                return
            for request_id, request in available_requests.items():
                keyboard = [[
                    InlineKeyboardButton(
                        "Создать задачу доставки", 
                        callback_data=f"create_delivery_{request_id}"
                    )
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                message_text = (
                    f"📦 Заявка #{request_id}\n"
                    f"👤 Клиент: {request.get('user_name')}\n"
                    f"📱 Телефон: {request.get('user_phone')}\n"
                    f"📍 Адрес: {request.get('location_display')}\n"
                    f"Описание: {request.get('description', 'Нет описания')}"
                )
                await update.message.reply_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Ошибка при показе заявок для доставки: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заявок")

    @log_method_call
    async def show_feedback(self, update: Update, context: CallbackContext):
        """Показывает статистику обратной связи"""
        if isinstance(update.callback_query, CallbackQuery):
            query = update.callback_query
            await query.answer()
        else:
            query = None
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                message = "📊 Данные обратной связи отсутствуют."
                if query:
                    await query.edit_message_text(message)
                else:
                    await update.message.reply_text(message)
                return
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            message = "❌ Ошибка при загрузке данных обратной связи."
            if query:
                await query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return
        ratings = feedback_data.get('ratings', [])
        reviews = feedback_data.get('reviews', [])
        if not ratings and not reviews:
            message = "📊 Пока нет данных обратной связи."
            if query:
                await query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return
        # Подсчитываем статистику
        total_ratings = len(ratings)
        if total_ratings > 0:
            avg_rating = sum(r['rating'] for r in ratings) / total_ratings
            rating_distribution = {i: 0 for i in range(1, 6)}
            for r in ratings:
                rating_distribution[r['rating']] += 1
        else:
            avg_rating = 0
            rating_distribution = {i: 0 for i in range(1, 6)}
        # Формируем сообщение
        message = "📊 Статистика обратной связи:\n\n"
        message += f"Всего оценок: {total_ratings}\n"
        message += f"Средняя оценка: {avg_rating:.1f} 🌟\n\n"
        message += "Распределение оценок:\n"
        for rating in range(5, 0, -1):
            count = rating_distribution[rating]
            stars = "🌟" * rating
            message += f"{stars}: {count}\n"
        if reviews:
            message += f"\nВсего отзывов: {len(reviews)}"
        # Добавляем кнопки
        keyboard = []
        if reviews:
            keyboard.append([InlineKeyboardButton("📝 Показать отзывы", callback_data="show_reviews")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)

    @log_method_call
    async def show_reviews(self, update: Update, context: CallbackContext):
        """Показывает список отзывов"""
        query = update.callback_query
        await query.answer()
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                await query.edit_message_text("📊 Данные отзывов отсутствуют.")
                return
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            await query.edit_message_text("❌ Ошибка при загрузке данных отзывов.")
            return
        reviews = feedback_data.get('reviews', [])
        if not reviews:
            await query.edit_message_text("📝 Пока нет отзывов от клиентов.")
            return
        # Берем последние 10 отзывов
        recent_reviews = reviews[-10:]
        message = "📝 Последние отзывы клиентов:\n\n"
        for review in recent_reviews:
            date = review.get('timestamp', 'Нет даты')
            text = review.get('text', 'Нет текста')
            message += f"📅 {date}\n💬 {text}\n\n"
        # Добавляем кнопку возврата к статистике
        keyboard = [[InlineKeyboardButton("🔙 Назад к статистике", callback_data="back_to_stats")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    @log_method_call
    async def show_new_requests(self, update: Update, context: CallbackContext):
        """Показывает список новых заявок, отсортированных по дате создания (новые сверху)"""
        logger.info("🔍 Показ новых заявок для назначения СЦ")
        try:
            requests_data = await load_requests()
            users_data = await load_users()  # Загружаем данные пользователей
            # Фильтруем и сортируем заявки
            new_requests = sorted(
                (
                    (rid, req) for rid, req in requests_data.items()
                    if req.get('status') == 'Новая'
                ),
                key=lambda x: datetime.strptime(x[1]['created_at'], "%H:%M %d.%m.%Y"),
                reverse=True  # Сначала новые
            )
            if not new_requests:
                await update.message.reply_text("📭 Нет новых заявок для назначения.")
                return
            logger.debug(f"📋 Найдено {len(new_requests)} новых заявок")
            # Отправляем заявки по одной с медиа и кнопками
            for request_id, request in new_requests:
                try:
                    # Получаем телефон из профиля пользователя
                    user_id = request.get('user_id')
                    user_phone = users_data.get(user_id, {}).get('phone', 'Не указан')
                    # Формируем текст сообщения
                    message_text = (
                        f"📦 Заявка #{request_id}\n"
                        f"📅 Создана: {request['created_at']}\n"
                        f"👤 Клиент: {request.get('user_name', 'Не указан')}\n"
                        f"📱 Телефон: {user_phone}\n"  # Используем телефон из load_users()
                        f"📍 Адрес: {request.get('location', 'Не указан')}\n"  # Прямое обращение к location
                        f"📝 Описание: {request.get('description', 'Нет описания')}\n"
                        f"🕒 Желаемая дата: {request.get('desired_date', 'Не указана')}"
                    )
                    # Подготовка кнопок
                    keyboard = [
                        [
                            InlineKeyboardButton("📨 Разослать СЦ", callback_data=f"send_to_sc_{request_id}"),
                            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_request_{request_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    # Отправка фотографий (если есть)
                    photos = request.get('photos', [])
                    if photos:
                        try:
                            media_group = []
                            for photo in photos[:10]:  # Ограничение на 10 фото
                                try:
                                    if os.path.exists(photo):
                                        with open(photo, 'rb') as f:
                                            media_group.append(InputMediaPhoto(f.read()))
                                    else:
                                        media_group.append(InputMediaPhoto(photo))
                                except Exception as e:
                                    logger.error(f"Ошибка обработки фото {photo}: {e}")
                            if media_group:
                                await context.bot.send_media_group(
                                    chat_id=update.effective_chat.id,
                                    media=media_group
                                )
                        except Exception as e:
                            logger.error(f"Ошибка отправки медиагруппы: {e}")
                    # Отправка текста с кнопками
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message_text,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка обработки заявки {request_id}: {e}")
                    continue
            logger.info(f"✅ Успешно показано {len(new_requests)} заявок")
        except Exception as e:
            logger.error(f"🔥 Ошибка при показе заявок: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке заявок")

    @log_method_call
    async def view_request_chat(self, update: Update, context: CallbackContext):
        """Показывает чат заявки по её номеру с фото"""
        if not context.user_data.get('waiting_for_request_id'):
            await update.message.reply_text("Пожалуйста, введите номер заявки:")
            context.user_data['waiting_for_request_id'] = True
            return 'WAITING_REQUEST_ID'
        request_id = update.message.text.strip()
        chat_file = os.path.join(DATA_DIR, 'chat_sc_client.json')
        try:
            if not os.path.exists(chat_file):
                await update.message.reply_text("❌ Файл чата не найден")
                return ConversationHandler.EN
            with open(chat_file, 'r', encoding='utf-8') as f:
                chat_data = json.load(f)
            if request_id not in chat_data:
                await update.message.reply_text(f"❌ Чат для заявки #{request_id} не найден")
                return ConversationHandler.END
            messages = chat_data[request_id]
            if not messages:
                await update.message.reply_text(f"❌ В чате заявки #{request_id} пока нет сообщений")
                return ConversationHandler.END
            # Отправляем заголовок
            await update.message.reply_text(f"💬 История чата заявки #{request_id}:")
            # Обрабатываем каждое сообщение
            for msg in messages:
                sender = "👤 Клиент" if msg['sender'] == 'client' else "🏢 СЦ"
                timestamp = msg.get('timestamp', 'без даты')
                # Если есть фото
                if 'photo_path' in msg and os.path.exists(msg['photo_path']):
                    caption = f"{sender} ({timestamp}):\n{msg.get('message', '')}"
                    try:
                        with open(msg['photo_path'], 'rb') as photo_file:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo_file,
                                caption=caption[:1024]  # Ограничение длины подписи в Telegram
                            )
                    except Exception as photo_error:
                        logger.error(f"Ошибка отправки фото: {photo_error}")
                        await update.message.reply_text(
                            f"{sender} ({timestamp}): [Не удалось загрузить фото]\n"
                            f"{msg.get('message', '')}"
                        )
                else:
                    # Текстовое сообщение
                    message_text = f"{sender} ({timestamp}):\n{msg.get('message', '')}"
                    # Разбиваем длинные сообщения
                    if len(message_text) > 4000:
                        parts = [message_text[i:i+4000] for i in range(0, len(message_text), 4000)]
                        for part in parts:
                            await update.message.reply_text(part)
                    else:
                        await update.message.reply_text(message_text)
        except json.JSONDecodeError:
            await update.message.reply_text("❌ Ошибка чтения файла чата")
        except Exception as e:
            logger.error(f"Ошибка при просмотре чата: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке чата")
        finally:
            context.user_data.pop('waiting_for_request_id', None)
            return ConversationHandler.END

    @log_method_call
    async def handle_price_approval(self, update: Update, context: CallbackContext):
        """Обработка согласования цены с клиентом"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = await load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            repair_price = request.get('repair_price', 'Не указана')
            # Формируем сообщение для клиента
            client_message = (
                f"💰 Сервисный центр предложил предварительную стоимость ремонта:\n"
                f"Сумма: {repair_price} BYN\n\n"
                f"Вы согласны с предварительной стоимостью?"
            )
            # Создаем клавиатуру для клиента
            keyboard = [
                [InlineKeyboardButton("✅ Согласен", callback_data=f"client_initial_price_{request_id}")],
                [InlineKeyboardButton("❌ Не согласен", callback_data=f"client_initial_reject_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Отправляем сообщение клиенту
            client_id = request.get('user_id')
            if client_id:
                await context.bot.send_message(
                    chat_id=client_id,
                    text=client_message,
                    reply_markup=reply_markup
                )
                # Обновляем сообщение админу
                await query.edit_message_text(
                    f"✅ Запрос на согласование цены отправлен клиенту.\n"
                    f"Заявка: #{request_id}\n"
                    f"Сумма: {repair_price} BYN"
                )
            else:
                await query.edit_message_text("❌ Ошибка: не удалось найти ID клиента")
        except Exception as e:
            logger.error(f"Ошибка при отправке запроса на согласование цены: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    @log_method_call
    async def handle_client_price_approved(self, update: Update, context: CallbackContext):
        """Обработка подтверждения цены клиентом (точка входа)"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена")
            return ConversationHandler.END
        request = requests_data[request_id]
        # Устанавливаем флаг одобрения цены
        request['price_approved'] = True
        await save_requests(requests_data)
        logger.info(f"Клиент подтвердил цену для заявки #{request_id}")
        # Если в режиме отладки, сразу создаем задачу доставки
        if DEBUG:
            # Создаем задачу доставки напрямую через PrePaymentHandler
            logger.info(f"DEBUG режим: Создаем задачу доставки без оплаты для заявки #{request_id}")
            pre_payment_handler = PrePaymentHandler()
            # Устанавливаем фиксированную стоимость для отладки
            request['delivery_cost'] = '100.00'
            await save_requests(requests_data)
            return await pre_payment_handler.create_delivery_task(update, context, request_id, request)
        # В обычном режиме переходим к созданию платежа
        logger.info(f"Переходим к созданию платежа для заявки #{request_id}")
        pre_payment_handler = PrePaymentHandler()
        return await pre_payment_handler.create_payment(update, context, request_id, request)

    @log_method_call
    async def handle_comment_approval(self, update: Update, context: CallbackContext):
        """Обработка одобрения комментария от администратора"""
        query = update.callback_query
        await query.answer()
        # Получаем request_id и comment из callback_data
        parts = query.data.split('_')
        request_id = parts[2]
        comment = parts[3]  # Комментарий теперь в callback_data
        try:
            requests_data = await load_requests()
            request = requests_data[request_id]
            # Получаем данные СЦ
            sc_id = request.get('assigned_sc')
            service_centers = await load_service_centers()
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            # Сохраняем комментарий в заявку
            request['comment'] = comment
            # Обновляем данные заявки
            requests_data[request_id] = request
            await save_requests(requests_data)
            # Обновляем сообщение администратора
            await query.edit_message_text(
                f"✅ Комментарий от СЦ '{sc_name}' для заявки #{request_id} одобрен.\n"
                f"Комментарий: {comment}"
            )            
            # Уведомляем СЦ
            users_data = await load_users()
            sc_user_id = next(
                (uid for uid, u_data in users_data.items() 
                if str(u_data.get('sc_id')) == str(sc_id) and u_data.get('role') == 'sc'),
                None
            )
            if sc_user_id:
                await context.bot.send_message(
                    chat_id=int(sc_user_id),
                    text=f"✅ Ваш комментарий к заявке #{request_id} одобрен администратором."
                )
        except Exception as e:
            logger.error(f"Ошибка при одобрении комментария: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    @log_method_call
    async def handle_comment_rejection(self, update: Update, context: CallbackContext):
        """Обработка отклонения комментария от администратора"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = await load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            # Получаем данные СЦ
            sc_id = request.get('assigned_sc')
            service_centers = await load_service_centers()
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            # Обновляем сообщение администратора
            await query.edit_message_text(
                f"❌ Комментарий от СЦ '{sc_name}' для заявки #{request_id} отклонен.\n"
                f"Комментарий: {request.get('comment', 'Нет комментария')}"
            )            
            # Уведомляем СЦ
            users_data = await load_users()
            sc_user_id = next(
                (uid for uid, u_data in users_data.items() 
                if str(u_data.get('sc_id')) == str(sc_id) and u_data.get('role') == 'sc'),
                None
            )
            if sc_user_id:
                await context.bot.send_message(
                    chat_id=int(sc_user_id),
                    text=f"❌ Ваш комментарий к заявке #{request_id} отклонен администратором.\n"
                         "Пожалуйста, переформулируйте комментарий и попробуйте снова."
                )
        except Exception as e:
            logger.error(f"Ошибка при отклонении комментария: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    @log_method_call
    async def handle_admin_delivery_request(self, update: Update, context: CallbackContext):
        """Обработка запроса на доставку от администратора"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = await load_requests()
        delivery_tasks = await load_delivery_tasks()
        users_data = await load_users()
        service_centers = await load_service_centers()
        if request_id in requests_data:
            request = requests_data[request_id]
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            client_id = request.get('user_id')
            client_data = users_data.get(client_id, {})
            # Получаем текущую дату в формате DD.MM.YYYY
            today = datetime.now().strftime("%d.%m.%Y")
            # Проверяем, что дата доставки на сегодня
            if not request.get('desired_date', '').endswith(today):
                await query.edit_message_text(
                    "❌ Заявка не может быть доставлена сегодня.\n"
                    "Пожалуйста, проверьте дату доставки."
                )
                return
            # Создаем задачу доставки
            task_id = str(len(delivery_tasks) + 1)
            delivery_task = {
                'id': task_id,
                'request_id': request_id,
                'sc_id': sc_id,
                'sc_name': sc_data.get('name', 'Не указан'),
                'sc_address': sc_data.get('address', 'Не указан'),
                'client_id': client_id,
                'client_name': client_data.get('name', 'Не указан'),
                'client_phone': client_data.get('phone', 'Не указан'),
                'client_address': request.get('location', 'Не указан'),
                'description': request.get('description', 'Нет описания'),
                'status': ORDER_STATUS_NEW,
                'created_at': int(time.time()),
                'is_sc_to_client': False,
                'desired_date': request.get('desired_date', '')  # Копируем дату из заявки
            }
            delivery_tasks[task_id] = delivery_task
            await save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            request['status'] = ORDER_STATUS_NEW
            await save_requests(requests_data)
            await query.edit_message_text(
                f"✅ Задача доставки #{task_id} создана.\n"
                f"Заявка: #{request_id}\n"
                f"Время доставки: {request.get('desired_date', '').split()[0]}\n"
                f"Доставщики могут посмотреть доступные задания в соответствующем разделе."
            )
        else:
            await query.edit_message_text("❌ Заявка не найдена.")

    @log_method_call
    async def handle_contact_client(self, update: Update, context: CallbackContext):
        """Обработка запроса администратора на связь с клиентом"""
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            requests_data = await load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            client_id = request.get('user_id')
            if not client_id:
                await query.edit_message_text("❌ Не удалось найти клиента")
                return
            # Отправляем клиенту сообщение от администратора
            await context.bot.send_message(
                chat_id=client_id,
                text=f"Администратор хочет уточнить детали по заявке #{request_id}. Пожалуйста, подтвердите, забрал ли доставщик товар?"
            )
            # Создаем клавиатуру для клиента
            keyboard = [
                [InlineKeyboardButton("Да, забрал", callback_data=f"client_confirm_{request_id}")],
                [InlineKeyboardButton("Нет, не забрал", callback_data=f"client_deny_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=client_id,
                text="Подтвердите получение товара доставщиком:",
                reply_markup=reply_markup
            )
            await query.edit_message_text(f"✅ Запрос на подтверждение отправлен клиенту по заявке #{request_id}")
        except Exception as e:
            logger.error(f"Ошибка при связи с клиентом: {e}")
            await query.edit_message_text("❌ Произошла ошибка при отправке запроса клиенту")

    @log_method_call
    async def show_delivery_calendar(self, update: Update, context: CallbackContext):
        """Показывает календарь задач доставки"""
        logger.info("📅 Показ календаря задач доставки")
        try:
            delivery_tasks = await load_delivery_tasks()
            if not delivery_tasks:
                await update.message.reply_text("📭 Нет активных задач доставки.")
                return
                
            tasks_by_date = {}
            for task_id, task in delivery_tasks.items():
                desired_date = task.get('desired_date', '')
                if not desired_date:
                    continue
                try:
                    _, date_part = desired_date.split(' ')
                    date_obj = datetime.strptime(date_part, "%d.%m.%Y")
                    date_key = date_obj.strftime("%d.%m.%Y")
                    if date_key not in tasks_by_date:
                        tasks_by_date[date_key] = []
                    tasks_by_date[date_key].append((task_id, task))
                except (ValueError, IndexError) as e:
                    logger.error(f"Ошибка при обработке даты {desired_date}: {e}")
                    continue

            if not tasks_by_date:
                await update.message.reply_text("📭 Нет задач доставки с указанной датой.")
                return

            sorted_dates = sorted(tasks_by_date.keys(), 
                                key=lambda x: datetime.strptime(x, "%d.%m.%Y"))
            
            keyboard = []
            for date in sorted_dates:
                task_count = len(tasks_by_date[date])
                keyboard.append([
                    InlineKeyboardButton(
                        f"📅 {date} ({task_count})", 
                        callback_data=f"calendar_date_{date}"
                    )
                ])
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "📅 Выберите дату для просмотра задач доставки:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"🔥 Ошибка при показе календаря: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке календаря.")

    @log_method_call
    async def show_tasks_for_date(self, update: Update, context: CallbackContext):
        """Показывает задачи доставки на выбранную дату"""
        query = update.callback_query
        await query.answer()
        try:
            date_str = query.data.split('_')[2]
            delivery_tasks = await load_delivery_tasks()
            tasks_for_date = []
            # Собираем задачи для выбранной даты
            for task_id, task in delivery_tasks.items():
                if task.get('desired_date', '').endswith(date_str):
                    tasks_for_date.append((task_id, task))
            if not tasks_for_date:
                await query.edit_message_text(f"На {date_str} нет задач доставки.")
                return
            for task_id, task in tasks_for_date:
                # Определяем направление доставки
                if task.get('delivery_type') == 'sc_to_client':
                    from_location = task.get('sc_address', 'Адрес СЦ не указан')
                    to_location = task.get('client_address', 'Адрес клиента не указан')
                    delivery_direction = "🚗 СЦ → Клиент"
                else:  # client_to_sc или другие типы
                    from_location = task.get('client_address', 'Адрес клиента не указан')
                    to_location = task.get('sc_address', 'Адрес СЦ не указан')
                    delivery_direction = "🚙 Клиент → СЦ"
                # Формируем сообщение
                message_text = (
                    f"📌 Задача #{task_id} (Заявка #{task.get('request_id', '?')})\n"
                    f"📅 Дата: {task.get('desired_date', 'Не указана')}\n"
                    f"🔀 Тип: {delivery_direction}\n"
                    f"📍 Откуда: {from_location}\n"
                    f"🏁 Куда: {to_location}\n"
                    f"👤 Клиент: {task.get('client_name', 'Не указан')}\n"
                    f"📞 Телефон: {task.get('client_phone', 'Не указан')}\n"
                    f"📦 Описание: {task.get('description', 'Нет описания')}\n"
                    f"🔄 Статус: {task.get('status', 'Не указан')}"
                )
                # Кнопки управления
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Изменить дату", callback_data=f"reschedule_delivery_{task_id}"),
                        InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_delivery_{task_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=message_text,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Ошибка при показе задач на дату: {e}")
            await query.edit_message_text("❌ Произошла ошибка при загрузке задач.")

    @log_method_call
    async def reschedule_delivery(self, update: Update, context: CallbackContext):
        """Начинает процесс изменения даты доставки"""
        query = update.callback_query
        await query.answer()
        task_id = query.data.split('_')[2]
        context.user_data['reschedule_task_id'] = task_id
        # Показываем календарь для выбора новой даты
        keyboard = []
        current_date = datetime.now()
        for i in range(7):
            date = current_date + timedelta(days=i)
            date_display = date.strftime("%d.%m (%A)")
            date_value = date.strftime("%d.%m.%Y")
            keyboard.append([
                InlineKeyboardButton(
                    f"📅 {date_display}",
                    callback_data=f"select_new_date_{date_value}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите новую дату для задачи доставки:",
            reply_markup=reply_markup
        )

    @log_method_call
    async def select_new_delivery_date(self, update: Update, context: CallbackContext):
        """Обрабатывает выбор новой даты"""
        query = update.callback_query
        await query.answer()
        new_date = query.data.split('_')[3]
        context.user_data['new_delivery_date'] = new_date
        # Показываем доступное время
        keyboard = []
        for hour in range(9, 21):
            time_str = f"{hour:02d}:00"
            keyboard.append([
                InlineKeyboardButton(
                    f"🕒 {time_str}",
                    callback_data=f"select_new_time_{time_str}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите новое время для задачи доставки:",
            reply_markup=reply_markup
        )

    @log_method_call
    async def select_new_delivery_time(self, update: Update, context: CallbackContext):
        """Обрабатывает выбор нового времени и отправляет запрос на подтверждение клиенту"""
        query = update.callback_query
        await query.answer()
        logger.info(f"Начало обработки select_new_delivery_time для задачи {query.data}")
        try:
            new_time = query.data.split('_')[3]
            task_id = context.user_data.get('reschedule_task_id')
            new_date = context.user_data.get('new_delivery_date')
            logger.debug(f"Получены параметры: new_time={new_time}, task_id={task_id}, new_date={new_date}")
            if not task_id or not new_date:
                error_msg = "❌ Ошибка: данные задачи не найдены."
                logger.error(error_msg)
                await query.edit_message_text(error_msg)
                return
            # Загружаем данные
            delivery_tasks = await load_delivery_tasks()
            requests_data = await load_requests()
            logger.debug(f"Загружено {len(delivery_tasks)} задач доставки и {len(requests_data)} заявок")
            if task_id in delivery_tasks:
                # Получаем request_id из задачи доставки
                request_id = delivery_tasks[task_id].get('request_id')
                if not request_id or request_id not in requests_data:
                    error_msg = f"Не удалось найти связанную заявку для задачи {task_id}"
                    logger.error(error_msg)
                    await query.edit_message_text("❌ Ошибка: не найдены данные заявки.")
                    return
                # Получаем user_id из заявки
                user_id = requests_data[request_id].get('user_id')
                if not user_id:
                    error_msg = f"Не удалось найти user_id в заявке {request_id}"
                    logger.error(error_msg)
                    await query.edit_message_text("❌ Не удалось найти ID клиента для уведомления.")
                    return
                # Обновляем задачу доставки
                old_date = delivery_tasks[task_id]['desired_date']
                delivery_tasks[task_id]['desired_date'] = f"{new_time} {new_date}"
                delivery_tasks[task_id]['status'] = "Требует согласования"
                delivery_tasks[task_id]['previous_date'] = old_date
                delivery_tasks[task_id]['user_id'] = user_id  # Сохраняем user_id в задаче доставки
                save_delivery_tasks(delivery_tasks)
                logger.info(f"Задача {task_id} обновлена, старая дата: {old_date}, новая дата: {new_time} {new_date}")
                logger.debug(f"ID клиента для уведомления: {user_id}")
                try:
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Подтвердить", callback_data=f"delivery_confirm_{task_id}"),
                            InlineKeyboardButton("❌ Отклонить", callback_data=f"delivery_reject_{task_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    message_text = (
                        f"📅 Администратор предложил новую дату доставки:\n\n"
                        f"Новая дата: {new_time} {new_date}\n"
                        f"Предыдущая дата: {old_date}\n\n"
                        "Пожалуйста, подтвердите или отклоните изменение:"
                    )
                    logger.debug(f"Попытка отправить сообщение клиенту {user_id}")
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        reply_markup=reply_markup
                    )
                    logger.info(f"Уведомление успешно отправлено клиенту {user_id}")
                    await query.edit_message_text(
                        f"✅ Запрос на изменение даты отправлен клиенту. Новая дата: {new_time} {new_date}"
                    )
                except Exception as e:
                    error_msg = f"Не удалось уведомить клиента: {e}"
                    logger.error(error_msg)
                    await query.edit_message_text("❌ Не удалось отправить уведомление клиенту.")
            else:
                error_msg = f"Задача доставки {task_id} не найдена."
                logger.error(error_msg)
                await query.edit_message_text("❌ " + error_msg)
        except Exception as e:
            error_msg = f"Критическая ошибка в select_new_delivery_time: {e}"
            logger.error(error_msg, exc_info=True)
            await query.edit_message_text("❌ Произошла критическая ошибка. Пожалуйста, попробуйте позже.")

    @log_method_call
    async def back_to_calendar(self, update: Update, context: CallbackContext):
        """Возврат к календарю"""
        query = update.callback_query
        await query.answer()
        await self.show_delivery_calendar(query, context)
