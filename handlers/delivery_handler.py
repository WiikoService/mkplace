from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ADMIN_IDS, ENTER_NAME, ENTER_PHONE,
    ENTER_CONFIRMATION_CODE, SMS_TOKEN,
    ORDER_STATUS_DELIVERY_TO_SC, ORDER_STATUS_DELIVERY_TO_CLIENT,
    ORDER_STATUS_CLIENT_REJECTED, ORDER_STATUS_WAITING_SC, CREATE_REQUEST_PHOTOS,
    ORDER_STATUS_PICKUP_FROM_SC, ORDER_STATUS_SC_TO_CLIENT, ORDER_STATUS_IN_SC,
    ENTER_SC_CONFIRMATION_CODE
)
from handlers.base_handler import BaseHandler
from database import load_delivery_tasks, load_users, load_requests, save_delivery_tasks, save_requests, save_users, load_service_centers

import logging
import random
import requests
import os
import time

from smsby import SMSBY

from utils import notify_client

# TODO: сделать смс - отдельным методом (не срочно) ИЛИ сделать отдельным потоком

logger = logging.getLogger(__name__)


class DeliveryHandler(BaseHandler):

    async def show_delivery_profile(self, update: Update, context: CallbackContext):
        """Отображение профиля доставщика."""
        user_id = str(update.effective_user.id)
        users_data = load_users()
        user = users_data.get(user_id, {})
        if not user.get('name'):
            await update.message.reply_text("Пожалуйста, введите ваше имя:")
            return ENTER_NAME
        if not user.get('phone'):
            await update.message.reply_text("Пожалуйста, введите ваш номер телефона:")
            return ENTER_PHONE
        reply = f"Ваш профиль доставщика:\n\n"
        reply += f"Имя: {user['name']}\n"
        reply += f"Телефон: {user['phone']}\n"
        reply += f"Роль: {user.get('role', 'Доставщик')}\n"
        await update.message.reply_text(reply)
        return ConversationHandler.END

    async def enter_name(self, update: Update, context: CallbackContext):
        """Ввод имени доставщика."""
        user_id = str(update.effective_user.id)
        name = update.message.text
        users_data = load_users()
        if user_id not in users_data:
            users_data[user_id] = {}
        users_data[user_id]['name'] = name
        save_users(users_data)
        await update.message.reply_text("Спасибо. Теперь, пожалуйста, введите ваш номер телефона:")
        return ENTER_PHONE

    async def enter_phone(self, update: Update, context: CallbackContext):
        """Ввод номера телефона доставщика."""
        user_id = str(update.effective_user.id)
        phone = update.message.text
        users_data = load_users()
        users_data[user_id]['phone'] = phone
        save_users(users_data)
        await update.message.reply_text("Спасибо. Ваш профиль обновлен.")
        return await self.show_delivery_profile(update, context)

    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        """Отображение заданий доставщика."""
        try:
            delivery_id = str(update.effective_user.id)
            delivery_tasks = load_delivery_tasks()
            my_tasks = {
                task_id: task for task_id, task in delivery_tasks.items()
                if isinstance(task, dict) and 
                str(task.get('assigned_delivery_id')) == delivery_id
            }
            if not my_tasks:
                await update.message.reply_text("У вас пока нет активных заданий.")
                return
            for task_id, task in my_tasks.items():
                status = task.get('status', 'Статус не указан')
                request_id = task.get('request_id', 'Не указан')
                sc_name = task.get('sc_name', 'Не указан')
                keyboard = []
                if status == ORDER_STATUS_DELIVERY_TO_CLIENT:
                    keyboard.append([InlineKeyboardButton(
                        "Подтвердить получение", 
                        callback_data=f"confirm_pickup_{request_id}"
                    )])
                elif status == ORDER_STATUS_DELIVERY_TO_SC:
                    keyboard.append([InlineKeyboardButton(
                        "Доставлено в СЦ", 
                        callback_data=f"delivered_to_sc_{request_id}"
                    )])
                message = (
                    f"📦 Задача доставки #{task_id}\n"
                    f"Статус: {status}\n"
                    f"Сервисный центр: {sc_name}\n"
                    f"Адрес клиента: {task.get('client_address', 'Не указан')}\n"
                    f"Клиент: {task.get('client_name', 'Не указан')}\n"
                    f"Телефон: {task.get('client_phone', 'Не указан')}\n"
                    f"Описание: {task.get('description', '')[:100]}..."
                )
                if keyboard:
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(message, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(message)
        except Exception as e:
            logger.error(f"Ошибка при показе заданий: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    async def handle_task_callback(self, update: Update, context: CallbackContext):
        """Обработка нажатий на кнопки в заданиях доставщика."""
        query = update.callback_query
        await query.answer()
        task_id = query.data.split('_')[-1]
        # Здесь вы можете загрузить детали задачи и отобразить их
        task_details = f"Детали задачи №{task_id}\n..."  # Замените это на реальные данные
        await query.edit_message_text(text=task_details)

    async def accept_delivery(self, update: Update, context: CallbackContext):
        """Принятие задачи доставщиком."""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        if request_id in requests_data:
            requests_data[request_id]['status'] = 'Доставщик в пути к клиенту'
            requests_data[request_id]['assigned_delivery'] = str(query.from_user.id)
            save_requests(requests_data)
            for task in delivery_tasks:
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = 'Доставщик в пути к клиенту'
                    task['assigned_delivery_id'] = str(query.from_user.id)
                    break
            save_delivery_tasks(delivery_tasks)
            latitude = requests_data[request_id].get('latitude')
            longitude = requests_data[request_id].get('longitude')
            keyboard = [
                [InlineKeyboardButton("Подтвердить получение", callback_data=f"confirm_pickup_{request_id}")],
                [InlineKeyboardButton("Открыть карту", url=f"https://yandex.ru/maps?rtext=~{latitude}%2C{longitude}&rtt=auto")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message_text = f"Вы приняли заказ №{request_id}. Статус: Доставщик в пути к клиенту\n"
            if latitude and longitude:
                message_text += f"Координаты клиента: {latitude}, {longitude}"
            else:
                message_text += "Координаты клиента недоступны"
            await query.edit_message_text(message_text, reply_markup=reply_markup)
            # Уведомляем клиента
            client_id = requests_data[request_id].get('user_id')
            if client_id:
                await context.bot.send_message(
                    chat_id=client_id,
                    text=f"Доставщик принял ваш заказ №{request_id} и направляется к вам."
                )
            # Уведомляем администраторов
            user = load_users().get(str(query.from_user.id), {})
            delivery_name = user.get('name', 'Неизвестный доставщик')
            delivery_phone = user.get('phone', 'Номер не указан')
            admin_message = f"Заказ №{request_id} принят доставщиком.\n"
            admin_message += f"Доставщик: {delivery_name} - +{delivery_phone}\n"
            admin_message += "Статус: Доставщик в пути к клиенту"
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode='Markdown'
                )
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")

    async def handle_confirm_pickup(self, update: Update, context: CallbackContext):
        """
        Обработка подтверждения(отказа) передачи предмета клиентом
        Отправка смс клиенту с кодом подтверждения
        """
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        users_data = load_users()
        if request_id in requests_data:
            # Сохраняем request_id в контексте для последующего использования
            context.user_data['current_request'] = request_id
            
            # Запрашиваем фотографии у доставщика
            await query.edit_message_text(
                "Пожалуйста, сделайте фотографии товара перед получением. "
                "Когда закончите, отправьте /done"
            )
            return CREATE_REQUEST_PHOTOS
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")

    async def handle_client_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения(отказа) передачи предмета клиентом."""
        query = update.callback_query
        await query.answer()
        try:
            action, request_id = query.data.split('_')[1:]
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            if request_id in requests_data:
                if action == 'confirm':
                    new_status = ORDER_STATUS_DELIVERY_TO_SC
                    # Получаем delivery_id из requests
                    delivery_id = requests_data[request_id].get('assigned_delivery')
                    # Обновляем статус в requests
                    requests_data[request_id].update({
                        'status': new_status,
                        'assigned_delivery': delivery_id
                    })
                    save_requests(requests_data)
                    # Обновляем статус в delivery_tasks
                    task_updated = False
                    for task_id, task in delivery_tasks.items():
                        if isinstance(task, dict) and task.get('request_id') == request_id:
                            task.update({
                                'status': new_status,
                                'assigned_delivery_id': delivery_id
                            })
                            task_updated = True
                            logger.info(f"Обновлена задача {task_id}: {task}")
                            break
                    if not task_updated:
                        logger.error(f"Задача для заявки {request_id} не найдена в delivery_tasks")
                    save_delivery_tasks(delivery_tasks)
                    # Получаем данные СЦ
                    sc_id = requests_data[request_id].get('assigned_sc')
                    service_centers = load_service_centers()
                    sc_data = service_centers.get(sc_id, {})
                    if delivery_id:
                        delivery_message = (
                            f"✅ Клиент подтвердил получение по заявке #{request_id}\n"
                            f"Адрес СЦ для доставки:\n"
                            f"🏢 {sc_data.get('name', 'Название не указано')}\n"
                            f"📍 {sc_data.get('address', 'Адрес не указан')}"
                        )
                        await context.bot.send_message(
                            chat_id=delivery_id,
                            text=delivery_message
                        )
                        logger.info(f"Отправлено сообщение доставщику {delivery_id}")
                        
                        # Отправляем уведомление администратору
                        admin_message = (
                            f"✅ Клиент подтвердил получение товара доставщиком\n"
                            f"Заявка: #{request_id}\n"
                            f"Статус: {new_status}\n"
                            f"СЦ: {sc_data.get('name', 'Название не указано')}\n"
                            f"Адрес СЦ: {sc_data.get('address', 'Адрес не указан')}"
                        )
                        
                        # Отправляем фотографии администратору
                        pickup_photos = requests_data[request_id].get('pickup_photos', [])
                        if pickup_photos:
                            # Отправляем первое фото с текстом
                            if os.path.exists(pickup_photos[0]):
                                with open(pickup_photos[0], 'rb') as photo_file:
                                    await context.bot.send_photo(
                                        chat_id=ADMIN_IDS[0],
                                        photo=photo_file,
                                        caption=admin_message
                                    )
                            
                            # Отправляем остальные фото
                            for photo_path in pickup_photos[1:]:
                                if os.path.exists(photo_path):
                                    with open(photo_path, 'rb') as photo_file:
                                        await context.bot.send_photo(
                                            chat_id=ADMIN_IDS[0],
                                            photo=photo_file,
                                            caption=f"Фото товара по заявке #{request_id}"
                                        )
                        else:
                            # Если фото нет, отправляем только текст
                            for admin_id in ADMIN_IDS:
                                await context.bot.send_message(
                                    chat_id=admin_id,
                                    text=admin_message
                                )
                else:
                    new_status = ORDER_STATUS_CLIENT_REJECTED
                await query.edit_message_text(
                    f"Спасибо за подтверждение. Статус заявки №{request_id}: {new_status}"
                )
        except Exception as e:
            logger.error(f"Ошибка при обработке подтверждения клиента: {e}")
            await query.edit_message_text("Произошла ошибка при обработке подтверждения.")

    async def handle_delivered_to_sc(self, update: Update, context: CallbackContext):
        """Обработка передачи предмета в Сервисный Центр."""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        await query.edit_message_text(
            "Пожалуйста, сделайте фото товара перед передачей в СЦ. "
            "Когда закончите, отправьте /done"
        )
        context.user_data['photos_to_sc'] = []
        context.user_data['current_request'] = request_id
        return CREATE_REQUEST_PHOTOS

    async def handle_delivery_photo(self, update: Update, context: CallbackContext):
        """Обработка фотографий от доставщика"""
        if 'photos_to_sc' not in context.user_data:
            return
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/delivery_to_sc_{len(context.user_data['photos_to_sc'])}_{context.user_data['current_request']}.jpg"
        await photo_file.download_to_drive(photo_path)
        context.user_data['photos_to_sc'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Отправьте /done когда закончите.")
        return CREATE_REQUEST_PHOTOS

    async def handle_delivery_photos_done(self, update: Update, context: CallbackContext):
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('photos_to_sc', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            # Обновляем статус и сохраняем фото
            requests_data[request_id].update({
                'status': ORDER_STATUS_WAITING_SC,
                'delivery_photos': photos
            })
            save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            for task in delivery_tasks.values():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_WAITING_SC
                    break
            save_delivery_tasks(delivery_tasks)
            sc_id = requests_data[request_id].get('assigned_sc')
            if not sc_id:
                logger.error(f"СЦ не назначен для заявки {request_id}")
                return
            # Находим telegram_id пользователя СЦ
            sc_telegram_id = None
            for user_id, user_data in users_data.items():
                if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                    sc_telegram_id = int(user_id)
                    break
            if not sc_telegram_id:
                logger.error(f"Не найден telegram_id для СЦ {sc_id}")
                await update.message.reply_text("Ошибка: не удалось найти контакт СЦ")
                return
            # Уведомляем СЦ
            try:
                sc_message = (
                    f"🆕 Новый товар доставлен!\n"
                    f"Заявка: #{request_id}\n"
                    f"Описание: {requests_data[request_id].get('description', 'Нет описания')}\n"
                    f"Статус: Ожидает приёмки"
                )
                keyboard = [[
                    InlineKeyboardButton("Принять товар", callback_data=f"accept_item_{request_id}"),
                    InlineKeyboardButton("Отказать в приёме", callback_data=f"reject_item_{request_id}")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                # Отправляем текстовое сообщение
                await context.bot.send_message(
                    chat_id=sc_telegram_id,
                    text=sc_message,
                    reply_markup=reply_markup
                )
                # Отправляем фотографии
                for photo_path in photos:
                    if os.path.exists(photo_path):
                        with open(photo_path, 'rb') as photo_file:
                            await context.bot.send_photo(
                                chat_id=sc_telegram_id,
                                photo=photo_file,
                                caption=f"Фото товара по заявке #{request_id}"
                            )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления в СЦ: {str(e)}")
            context.user_data.pop('photos_to_sc', None)
            context.user_data.pop('current_request', None)
            await update.message.reply_text("✅ Фотографии загружены и отправлены в СЦ")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка в handle_delivery_photos_done: {str(e)}")
            await update.message.reply_text("Произошла ошибка при обработке фотографий")
            return ConversationHandler.END

    async def update_delivery_messages(self, bot: Bot, task_id: int, task_data: dict):
        """Обновление сообщений доставщикам."""
        from config import DELIVERY_IDS
        for delivery_id in DELIVERY_IDS:
            if delivery_id != task_data['assigned_to']:
                message = f"Задача доставки #{task_id} принята другим доставщиком.\n"
                message += f"Заявка: #{task_data['request_id']}\n"
                message += f"СЦ: {task_data['sc_name']}\n"
                message += f"Статус: {task_data['status']}"
                await bot.send_message(chat_id=delivery_id, text=message)

    async def show_available_tasks(self, update: Update, context: CallbackContext):
        """
        Показать доступные задания
        TODO: Упростить проверку доступных задач
        """
        try:
            delivery_tasks = load_delivery_tasks()
            if not delivery_tasks:
                await update.message.reply_text("На данный момент нет доступных задач доставки.")
                return
            available_tasks = {
                task_id: task for task_id, task in delivery_tasks.items() 
                if task.get('status') == "Новая" and not task.get('assigned_delivery_id')
            }
            if not available_tasks:
                await update.message.reply_text("На данный момент нет доступных задач доставки.")
                return
            for task_id, task in available_tasks.items():
                keyboard = [[
                    InlineKeyboardButton(
                        "Принять задачу", 
                        callback_data=f"accept_delivery_{task['request_id']}"
                    )
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                message = (
                    f"📦 Задача доставки #{task_id}\n"
                    f"Заявка: #{task['request_id']}\n"
                    f"Статус: {task['status']}\n"
                    f"Сервисный центр: {task['sc_name']}\n"
                    f"Адрес клиента: {task['client_address']}\n"
                    f"Клиент: {task['client_name']}\n"
                    f"Телефон: {task['client_phone']}\n"
                    f"Описание: {task['description'][:100]}..."
                )
                await update.message.reply_text(message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при показе доступных заданий: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    async def show_my_tasks(self, update: Update, context: CallbackContext):
        """Показать мои активные задания"""
        try:
            delivery_tasks = load_delivery_tasks()
            active_tasks = {}
            for task_id, task in delivery_tasks.items():
                if task.get('assigned_delivery_id') == str(update.effective_user.id):
                    active_tasks[task_id] = task
            if not active_tasks:
                await update.message.reply_text("У вас нет активных заданий")
                return
            for task_id, task in active_tasks.items():
                status = task.get('status')
                keyboard = []
                if task.get('is_sc_to_client'):
                    # Логика для доставки из СЦ клиенту
                    message = (
                        f"📦 Задача доставки #{task_id}\n"
                        f"Статус: {status}\n\n"
                        f"1️⃣ Забрать из СЦ:\n"
                        f"🏢 {task.get('sc_name', 'Не указан')}\n"
                        f"📍 {task.get('sc_address', 'Не указан')}\n\n"
                        f"2️⃣ Доставить клиенту:\n"
                        f"👤 {task.get('client_name', 'Не указан')}\n"
                        f"📍 {task.get('client_address', 'Не указан')}\n"
                        f"📱 {task.get('client_phone', 'Не указан')}\n"
                        f"📝 Описание: {task.get('description', '')[:100]}..."
                    )
                    if status == ORDER_STATUS_PICKUP_FROM_SC:
                        keyboard.append([InlineKeyboardButton(
                            "✅ Забрал из СЦ", 
                            callback_data=f"picked_up_from_sc_{task['request_id']}"
                        )])
                    elif status == ORDER_STATUS_SC_TO_CLIENT:
                        keyboard.append([InlineKeyboardButton(
                            "✅ Доставлено клиенту", 
                            callback_data=f"delivered_to_client_{task['request_id']}"
                        )])
                else:
                    # Логика для доставки от клиента в СЦ
                    message = (
                        f"📦 Задача доставки #{task_id}\n"
                        f"Статус: {status}\n\n"
                        f"1️⃣ Забрать у клиента:\n"
                        f"👤 {task.get('client_name', 'Не указан')}\n"
                        f"📍 {task.get('client_address', 'Не указан')}\n"
                        f"📱 {task.get('client_phone', 'Не указан')}\n\n"
                        f"2️⃣ Доставить в СЦ:\n"
                        f"🏢 {task.get('sc_name', 'Не указан')}\n"
                        f"📍 {task.get('sc_address', 'Не указан')}\n"
                        f"📝 Описание: {task.get('description', '')[:100]}..."
                    )
                    if status == ORDER_STATUS_DELIVERY_TO_SC:
                        keyboard.append([InlineKeyboardButton(
                            "✅ Доставлено в СЦ", 
                            callback_data=f"delivered_to_sc_{task['request_id']}"
                        )])
                    elif status == ORDER_STATUS_WAITING_SC:
                        # Пропускаем задачи, ожидающие приемку СЦ
                        continue
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                await update.message.reply_text(message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при показе заданий: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    async def handle_confirmation_code(self, update: Update, context: CallbackContext):
        """Обработка ввода кода подтверждения"""
        entered_code = update.message.text.strip()
        request_id = context.user_data.get('current_request')
        if not request_id:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        request = requests_data.get(request_id)
        if not request:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END
        if entered_code == request.get('confirmation_code'):
            delivery_id = str(update.effective_user.id)
            # Обновляем статус в requests
            request.update({
                'status': ORDER_STATUS_DELIVERY_TO_SC,
                'assigned_delivery': delivery_id
            })
            save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            for task_id, task in delivery_tasks.items():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task.update({
                        'status': ORDER_STATUS_DELIVERY_TO_SC,
                        'assigned_delivery_id': delivery_id
                    })
                    logger.info(f"Обновлена задача {task_id}: {task}")
                    break
            save_delivery_tasks(delivery_tasks)
            # Отправляем адрес СЦ
            sc_id = request.get('assigned_sc')
            service_centers = load_service_centers()
            sc_data = service_centers.get(sc_id, {})
            sc_message = (
                f"✅ Клиент подтвердил получение по заявке #{request_id}\n"
                f"Адрес СЦ для доставки:\n"
                f"🏢 {sc_data.get('name')}\n"
                f"📍 {sc_data.get('address')}"
            )
            await context.bot.send_message(chat_id=delivery_id, text=sc_message)
            await update.message.reply_text("Код подтвержден. Доставщик получил адрес СЦ.")
            return ConversationHandler.END
        else:
            await update.message.reply_text("Неверный код. Попробуйте еще раз:")
            return ENTER_CONFIRMATION_CODE

    async def handle_transfer_to_sc(self, update: Update, context: CallbackContext):
        """Обработка передачи товара в СЦ"""
        try:
            delivery_id = str(update.effective_user.id)
            delivery_tasks = load_delivery_tasks()
            requests_data = load_requests()
            logger.info(f"Проверка задач доставщика {delivery_id}")
            logger.info(f"Текущие задачи: {delivery_tasks}")
            active_tasks = {
                task_id: task for task_id, task in delivery_tasks.items()
                if isinstance(task, dict) and
                str(task.get('assigned_delivery_id')) == delivery_id and
                task.get('status') == ORDER_STATUS_DELIVERY_TO_SC
            }
            if not active_tasks:
                logger.info(f"Нет активных задач для доставщика {delivery_id}")
                await update.message.reply_text("У вас нет активных заданий для передачи в СЦ.")
                return
            for task_id, task in active_tasks.items():
                request_id = task.get('request_id')
                if request_id in requests_data:
                    keyboard = [[
                        InlineKeyboardButton(
                            "Передать в СЦ",
                            callback_data=f"delivered_to_sc_{request_id}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    message = (
                        f"📦 Задача доставки #{task_id}\n"
                        f"Заявка: #{request_id}\n"
                        f"Статус: {task['status']}\n"
                        f"Сервисный центр: {task['sc_name']}\n"
                        f"Описание: {task.get('description', '')[:100]}..."
                    )
                    await update.message.reply_text(message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при показе заданий для передачи в СЦ: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    async def cancel_delivery(self, update: Update, context: CallbackContext):
        """
        Отмена текущей операции доставки
        TODO: Сделаать очистку в цикле
        """
        try:
            # Очищаем данные контекста
            if 'photos_to_sc' in context.user_data:
                del context.user_data['photos_to_sc']
            if 'photos_from_sc' in context.user_data:
                del context.user_data['photos_from_sc']
            if 'current_request' in context.user_data:
                del context.user_data['current_request']
            if 'confirmation_code' in context.user_data:
                del context.user_data['confirmation_code']
            # Отправляем сообщение об отмене
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ Операция отменена. Вернитесь в меню доставщика."
                )
            else:
                await update.message.reply_text(
                    "❌ Операция отменена. Вернитесь в меню доставщика."
                )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при отмене доставки: {e}")
            await update.message.reply_text(
                "Произошла ошибка при отмене. Вернитесь в меню доставщика."
            )
            return ConversationHandler.END

    async def handle_pickup_photo(self, update: Update, context: CallbackContext):
        """Обработка фотографий при получении товара"""
        if 'pickup_photos' not in context.user_data:
            context.user_data['pickup_photos'] = []
            
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/pickup_{len(context.user_data['pickup_photos'])}_{context.user_data['current_request']}.jpg"
        await photo_file.download_to_drive(photo_path)
        context.user_data['pickup_photos'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Отправьте /done когда закончите.")
        return CREATE_REQUEST_PHOTOS

    async def handle_pickup_photos_done(self, update: Update, context: CallbackContext):
        """Завершение процесса фотографирования при получении товара"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('pickup_photos', [])
            
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
                
            requests_data = load_requests()
            if request_id in requests_data:
                # Сохраняем фотографии в данных заявки
                requests_data[request_id]['pickup_photos'] = photos
                save_requests(requests_data)
                
                # Отправляем фотографии клиенту для подтверждения
                client_id = requests_data[request_id].get('user_id')
                if client_id:
                    # Получаем данные СЦ
                    sc_id = requests_data[request_id].get('assigned_sc')
                    service_centers = load_service_centers()
                    sc_data = service_centers.get(sc_id, {})
                    
                    # Формируем сообщение с информацией о СЦ
                    sc_info = (
                        f"🏢 Сервисный центр: {sc_data.get('name', 'Название не указано')}\n"
                        f"📍 Адрес: {sc_data.get('address', 'Адрес не указан')}\n"
                        f"📱 Телефон: {sc_data.get('phone', 'Телефон не указан')}\n\n"
                    )
                    
                    await context.bot.send_message(
                        chat_id=client_id,
                        text=f"Доставщик сделал фотографии товара по заявке #{request_id}.\n\n{sc_info}Пожалуйста, подтвердите получение:"
                    )
                    
                    for photo_path in photos:
                        if os.path.exists(photo_path):
                            with open(photo_path, 'rb') as photo_file:
                                await context.bot.send_photo(
                                    chat_id=client_id,
                                    photo=photo_file,
                                    caption=f"Фото товара по заявке #{request_id}"
                                )
                    
                    keyboard = [
                        [InlineKeyboardButton("Да, забрал. С фото согласен.", callback_data=f"client_confirm_{request_id}")],
                        [InlineKeyboardButton("Нет, не забрал.", callback_data=f"client_deny_{request_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=client_id,
                        text="Подтверждаете получение товара?",
                        reply_markup=reply_markup
                    )
                
                # Очищаем данные контекста
                context.user_data.pop('pickup_photos', None)
                context.user_data.pop('current_request', None)
                
                await update.message.reply_text("✅ Фотографии загружены и отправлены клиенту для подтверждения")
                return ConversationHandler.END
            else:
                await update.message.reply_text("Ошибка: заявка не найдена")
                return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"Ошибка в handle_pickup_photos_done: {str(e)}")
            await update.message.reply_text("Произошла ошибка при обработке фотографий")
            return ConversationHandler.END
