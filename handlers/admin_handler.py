import logging
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, CallbackQuery
from telegram.ext import CallbackContext, ConversationHandler
from .base_handler import BaseHandler
from database import (
    load_delivery_tasks, load_requests, load_service_centers,
    load_users, save_delivery_tasks, save_requests, save_users
)
from config import (
    ASSIGN_REQUEST, ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK,
    ORDER_STATUS_ASSIGNED_TO_SC, ORDER_STATUS_PICKUP_FROM_SC, ORDER_STATUS_NEW
)
from utils import notify_delivery
from datetime import datetime
import os
from config import DATA_DIR
from handlers.user_handler import UserHandler


#  TODO: Согласование цены


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

class AdminHandler(BaseHandler):
    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        """Обработка нажатия кнопки 'Привязать к СЦ'"""
        logger.info("🛠️ START handle_assign_sc")
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            logger.debug(f"📝 Processing request {request_id}")
            requests_data = load_requests()
            logger.debug(f"📦 Loaded {len(requests_data)} requests")
            request = requests_data.get(request_id)
            logger.debug(f"📄 Request data found: {request is not None}")
            if not request:
                logger.error(f"❌ Request {request_id} not found")
                await query.edit_message_text("Заявка не найдена")
                return
            # Формируем сообщение для СЦ
            logger.debug("📝 Forming message text")
            try:
                message_text = (
                    f"📦 Заявка #{request_id}\n"
                    f"👤 Клиент: {request.get('user_name', 'Не указан')}\n"
                    f"📱 Телефон: {request.get('user_phone', 'Не указан')}\n"
                    f"📍 Адрес: {request.get('location', 'Не указан')}\n"
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

    async def handle_send_to_sc(self, update: Update, context: CallbackContext):
        """Обработка рассылки СЦ"""
        logger.info("🛠️ START handle_send_to_sc")
        try:
            query = update.callback_query
            await query.answer()
            rid = query.data.split('_')[-1]
            logger.debug(f"📩 Processing request {rid}")
            # Загрузка данных
            requests_data = load_requests()
            logger.debug(f"📥 Loaded {len(requests_data)} requests")
            if rid not in requests_data:
                logger.error(f"🚫 Request {rid} not found")
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[rid]
            logger.debug(f"📄 Request data: {json.dumps(request, indent=2, ensure_ascii=False)}")
            # Поиск СЦ
            users_data = load_users()
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
                    # Отправка упрощенного сообщения
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            f"📦 Новая заявка #{rid}\n\n"
                            f"📝 Описание: {request.get('description', 'Не указано')}"
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
        """Отправка заявки всем СЦ"""
        query = update.callback_query
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            request = requests_data[request_id]
            users_data = load_users()
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
        request = requests_data.get(request_id)
        if not request:
            await query.edit_message_text("❌ Заявка не найдена")
            return ConversationHandler.END
        # Проверяем текущий статус
        current_status = request.get('status')
        if current_status not in ['Ожидает доставку']:
            await query.edit_message_text(
                f"❌ Неверный статус заявки #{request_id}: {current_status}"
            )
            return ConversationHandler.END
        try:
            # Создаем задачу доставки
            delivery_tasks = load_delivery_tasks()
            task_id = str(len(delivery_tasks) + 1)
            sc_id = request.get('assigned_sc')
            service_centers = load_service_centers()
            sc_data = service_centers.get(sc_id, {})
            delivery_task = {
                'task_id': task_id,
                'request_id': request_id,
                'status': ORDER_STATUS_NEW,
                'sc_name': sc_data.get('name'),
                'sc_address': sc_data.get('address'),
                'client_name': request.get('user_name'),
                'client_address': request.get('location_display'),
                'client_phone': request.get('user_phone'),
                'description': request.get('description'),
                'is_sc_to_client': True
            }
            delivery_tasks[task_id] = delivery_task
            save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            request['status'] = ORDER_STATUS_NEW
            requests_data[request_id] = request
            save_requests(requests_data)
            # Уведомляем доставщиков
            await notify_delivery(context.bot, DELIVERY_IDS, delivery_task, detailed=True)
            await query.edit_message_text(
                f"✅ Задача доставки #{task_id} создана и отправлена доставщикам.\n"
                f"Заявка: #{request_id}"
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка создания задачи доставки: {e}")
            await query.edit_message_text(
                f"❌ Ошибка при создании задачи доставки: {str(e)}"
            )
            return ConversationHandler.END

    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        """Показ списка заявок для создания задачи доставки"""
        try:
            requests_data = load_requests()
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

    async def handle_create_sc_delivery(self, update: Update, context: CallbackContext):
        """Обработка создания задачи доставки из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        request = requests_data.get(request_id)
        if not request:
            await query.edit_message_text("❌ Заявка не найдена")
            return ConversationHandler.END
        try:
            delivery_tasks = load_delivery_tasks()
            task_id = str(len(delivery_tasks) + 1)
            sc_id = request.get('assigned_sc')
            service_centers = load_service_centers()
            sc_data = service_centers.get(sc_id, {})
            # Создаем специальную задачу доставки из СЦ
            delivery_task = {
                'task_id': task_id,
                'request_id': request_id,
                'status': 'Ожидает доставщика',
                'sc_name': sc_data.get('name'),
                'sc_address': sc_data.get('address'),
                'client_name': request.get('user_name'),
                'client_address': request.get('location_display'),
                'client_phone': request.get('user_phone'),
                'description': request.get('description'),
                'is_sc_to_client': True,
                'delivery_type': 'sc_to_client'
            }
            delivery_tasks[task_id] = delivery_task
            save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            request['status'] = 'Ожидает доставщика'
            requests_data[request_id] = request
            save_requests(requests_data)
            # Уведомляем доставщиков с новым форматом сообщения
            await notify_delivery(context.bot, DELIVERY_IDS, delivery_task)
            await query.edit_message_text(
                f"✅ Задача доставки из СЦ #{task_id} создана и отправлена доставщикам.\n"
                f"Заявка: #{request_id}"
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при создании задачи доставки из СЦ: {e}")
            await query.edit_message_text("❌ Произошла ошибка при создании задачи")
            return ConversationHandler.END

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
        message += f"Средняя оценка: {avg_rating:.1f} ⭐\n\n"
        message += "Распределение оценок:\n"
        for rating in range(5, 0, -1):
            count = rating_distribution[rating]
            stars = "⭐" * rating
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

    async def show_new_requests(self, update: Update, context: CallbackContext):
        """Показывает список новых заявок для назначения СЦ"""
        logger.info("🔍 Показ новых заявок для назначения СЦ")
        try:
            requests_data = load_requests()
            # Фильтруем только новые заявки
            new_requests = {
                rid: req for rid, req in requests_data.items() 
                if req.get('status') == 'Новая'
            }
            if not new_requests:
                await update.message.reply_text("📭 Нет новых заявок для назначения.")
                return
            logger.debug(f"📋 Найдено {len(new_requests)} новых заявок")
            # Отправляем каждую заявку отдельным сообщением с кнопками
            for request_id, request in new_requests.items():
                try:
                    # Формируем сообщение
                    message_text = (
                        f"📦 Заявка #{request_id}\n"
                        f"👤 Клиент: {request.get('user_name', 'Не указан')}\n"
                        f"📱 Телефон: {request.get('user_phone', 'Не указан')}\n"
                        f"📍 Адрес: {request.get('location', 'Не указан')}\n"
                        f"📝 Описание: {request.get('description', 'Нет описания')}\n"
                    )
                    # Добавляем дату, если она есть
                    if isinstance(request.get('desired_date'), datetime):
                        message_text += f"🕒 Желаемая дата: {request['desired_date'].strftime('%d.%m.%Y %H:%M')}"
                    else:
                        message_text += f"🕒 Желаемая дата: {request.get('desired_date', 'Не указана')}"
                    # Создаем клавиатуру с двумя кнопками
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "📨 Разослать СЦ",
                                callback_data=f"send_to_sc_{request_id}"
                            ),
                            InlineKeyboardButton(
                                "❌ Отклонить",
                                callback_data=f"reject_request_{request_id}"
                            )
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    # Отправляем сообщение
                    await update.message.reply_text(
                        text=message_text,
                        reply_markup=reply_markup
                    )
                    # Если есть фотографии, отправляем их
                    photos = request.get('photos', [])
                    if photos:
                        media_group = []
                        for photo in photos:
                            if isinstance(photo, str):
                                if os.path.exists(photo):
                                    with open(photo, 'rb') as photo_file:
                                        media_group.append(InputMediaPhoto(photo_file.read()))
                                else:
                                    media_group.append(InputMediaPhoto(photo))
                        if media_group:
                            await update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"❌ Ошибка при обработке заявки {request_id}: {e}")
                    continue
            logger.info("✅ Успешно показаны все новые заявки")
        except Exception as e:
            logger.error(f"🔥 Ошибка при показе новых заявок: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке заявок")

    async def view_request_chat(self, update: Update, context: CallbackContext):
        """Показывает чат заявки по её номеру"""
        if not context.user_data.get('waiting_for_request_id'):
            await update.message.reply_text("Пожалуйста, введите номер заявки:")
            context.user_data['waiting_for_request_id'] = True
            return 'WAITING_REQUEST_ID'
        request_id = update.message.text.strip()
        chat_file = os.path.join(DATA_DIR, 'chat_sc_client.json')
        try:
            if os.path.exists(chat_file):
                with open(chat_file, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
            else:
                await update.message.reply_text("❌ Файл чата не найден")
                return ConversationHandler.END
            if request_id in chat_data:
                messages = chat_data[request_id]
                if not messages:
                    await update.message.reply_text(f"❌ В чате заявки #{request_id} пока нет сообщений")
                    return ConversationHandler.END
                # Формируем сообщение с историей чата
                chat_history = f"💬 История чата заявки #{request_id}:\n\n"
                for msg in messages:
                    sender = "👤 Клиент" if msg['sender'] == 'client' else "🏢 СЦ"
                    chat_history += f"{sender} ({msg['timestamp']}):\n{msg['message']}\n\n"
                # Добавляем кнопку возврата в админское меню
                keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_admin")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                # Разбиваем длинное сообщение на части, если оно превышает лимит Telegram
                if len(chat_history) > 4000:
                    parts = [chat_history[i:i+4000] for i in range(0, len(chat_history), 4000)]
                    for i, part in enumerate(parts):
                        if i == len(parts) - 1:
                            await update.message.reply_text(part, reply_markup=reply_markup)
                        else:
                            await update.message.reply_text(part)
                else:
                    await update.message.reply_text(chat_history, reply_markup=reply_markup)
            else:
                await update.message.reply_text(f"❌ Чат для заявки #{request_id} не найден")
        except Exception as e:
            logger.error(f"Ошибка при просмотре чата: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке чата")
        finally:
            context.user_data.pop('waiting_for_request_id', None)
            return ConversationHandler.END

    async def handle_price_approval(self, update: Update, context: CallbackContext):
        """Обработка согласования цены с клиентом"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            repair_price = request.get('repair_price', 'Не указана')
            # Формируем сообщение для клиента
            client_message = (
                f"💰 Сервисный центр предложил предварительную стоимость ремонта:\n"
                f"Сумма: {repair_price} руб.\n\n"
                f"Вы согласны с предварительной стоимостью?"
            )
            # Создаем клавиатуру для клиента
            keyboard = [
                [
                    InlineKeyboardButton("✅ Согласен", callback_data=f"client_approve_price_{request_id}"),
                    InlineKeyboardButton("❌ Не согласен", callback_data=f"client_reject_price_{request_id}")
                ]
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
                    f"Сумма: {repair_price} руб."
                )
            else:
                await query.edit_message_text("❌ Ошибка: не удалось найти ID клиента")
        except Exception as e:
            logger.error(f"Ошибка при отправке запроса на согласование цены: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")
