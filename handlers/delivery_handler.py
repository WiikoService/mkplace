from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ADMIN_IDS, ENTER_NAME, ENTER_PHONE,
    ENTER_CONFIRMATION_CODE, SMS_TOKEN,
    ORDER_STATUS_DELIVERY_TO_SC, ORDER_STATUS_DELIVERY_TO_CLIENT,
    ORDER_STATUS_CLIENT_REJECTED, ORDER_STATUS_WAITING_SC, CREATE_REQUEST_PHOTOS,
    ORDER_STATUS_PICKUP_FROM_SC, ORDER_STATUS_SC_TO_CLIENT, DEBUG
)
from database import load_delivery_tasks, load_users, load_requests, save_delivery_tasks, save_requests, save_users, load_service_centers

import random
import os
from datetime import datetime

from smsby import SMSBY

from logging_decorator import log_method_call
import logging

logger = logging.getLogger(__name__)

class DeliveryHandler:

    @log_method_call
    async def show_delivery_profile(self, update: Update, context: CallbackContext):
        """Отображение профиля доставщика."""
        user_id = str(update.effective_user.id)
        users_data = await load_users()
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
        users_data = await load_users()
        if user_id not in users_data:
            users_data[user_id] = {}
        users_data[user_id]['name'] = name
        await save_users(users_data)
        await update.message.reply_text("Спасибо. Теперь, пожалуйста, введите ваш номер телефона:")
        return ENTER_PHONE

    async def enter_phone(self, update: Update, context: CallbackContext):
        """Ввод номера телефона доставщика."""
        user_id = str(update.effective_user.id)
        phone = update.message.text
        users_data = await load_users()
        users_data[user_id]['phone'] = phone
        await save_users(users_data)
        await update.message.reply_text("Спасибо. Ваш профиль обновлен.")
        return await self.show_delivery_profile(update, context)

    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        """Отображение заданий доставщика."""
        try:
            delivery_id = str(update.effective_user.id)
            delivery_tasks = await load_delivery_tasks()
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
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    @log_method_call
    async def handle_task_callback(self, update: Update, context: CallbackContext):
        """Обработка нажатий на кнопки в заданиях доставщика."""
        query = update.callback_query
        await query.answer()
        task_id = query.data.split('_')[-1]
        # Здесь вы можете загрузить детали задачи и отобразить их
        task_details = f"Детали задачи №{task_id}\n..."  # Замените это на реальные данные
        await query.edit_message_text(text=task_details)

    @log_method_call
    async def accept_delivery(self, update: Update, context: CallbackContext):
        """Принятие задачи доставщиком."""
        query = update.callback_query
        await query.answer()
        try:
            # Получаем ID заявки из callback_data
            request_id = query.data.split('_')[-1]
            # Загружаем данные
            requests_data = await load_requests()
            delivery_tasks = await load_delivery_tasks()
            # Находим задачу с указанным request_id
            task_id = None
            task_data = None
            for task_key, task in delivery_tasks.items():
                if task.get('request_id') == request_id and task.get('status') == 'Новая':
                    task_id = task_key
                    task_data = task
                    break
            # Проверяем, что задача найдена
            if not task_id or not task_data:
                await query.edit_message_text("❌ Задача доставки не найдена или уже принята другим доставщиком.")
                return
            # Получаем информацию о доставщике
            user_id = str(update.effective_user.id)
            user_name = update.effective_user.first_name
            # Проверяем тип доставки с защитой от None
            is_sc_to_client = task_data.get('is_sc_to_client', False)
            delivery_type = task_data.get('delivery_type', '')
            # Обновляем статус задачи
            task_data['status'] = 'В процессе'
            task_data['assigned_delivery_id'] = user_id
            task_data['assigned_delivery_name'] = user_name
            delivery_tasks[task_id] = task_data
            await save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            if request_id in requests_data:
                if is_sc_to_client or delivery_type == 'sc_to_client':
                    requests_data[request_id]['status'] = ORDER_STATUS_PICKUP_FROM_SC
                else:
                    requests_data[request_id]['status'] = ORDER_STATUS_DELIVERY_TO_SC
                requests_data[request_id]['assigned_delivery'] = user_id
                await save_requests(requests_data)
            # Формируем сообщение и клавиатуру для доставщика
            if is_sc_to_client or delivery_type == 'sc_to_client':
                # Доставка из СЦ клиенту
                message = (
                    f"✅ Вы приняли заказ #{task_id}\n"
                    f"Тип: 📤 Доставка ИЗ СЦ КЛИЕНТУ\n\n"
                    f"1️⃣ Забрать из СЦ:\n"
                    f"🏢 {task_data.get('sc_name', 'Не указан')}\n"
                    f"📍 {task_data.get('sc_address', 'Не указан')}\n"
                    f"☎️ {task_data.get('sc_phone', 'Не указан')}\n\n"
                    f"2️⃣ Доставить клиенту:\n"
                    f"👤 {task_data.get('client_name', 'Не указан')}\n"
                    f"📍 {task_data.get('client_address', 'Не указан')}\n"
                    f"📱 {task_data.get('client_phone', 'Не указан')}\n\n"
                    f"📋 Инструкции:\n"
                    f"1. Заберите товар из СЦ\n"
                    f"2. Подтвердите получение из СЦ кнопкой 'Забрал из СЦ'\n"
                    f"3. Доставьте товар клиенту\n"
                    f"4. Получите код подтверждения от клиента"
                )
                keyboard = [[
                    InlineKeyboardButton(
                        "✅ Забрал из СЦ",
                        callback_data=f"sc_delivery_accept_{task_id}"
                    )
                ]]
            else:
                # Доставка от клиента в СЦ
                message = (
                    f"✅ Вы приняли заказ #{task_id}\n"
                    f"Тип: 📥 Доставка ОТ КЛИЕНТА В СЦ\n\n"
                    f"1️⃣ Забрать у клиента:\n"
                    f"👤 {task_data.get('client_name', 'Не указан')}\n"
                    f"📍 {task_data.get('client_address', 'Не указан')}\n"
                    f"📱 {task_data.get('client_phone', 'Не указан')}\n\n"
                    f"2️⃣ Доставить в СЦ:\n"
                    f"🏢 {task_data.get('sc_name', 'Не указан')}\n"
                    f"📍 {task_data.get('sc_address', 'Не указан')}\n"
                    f"☎️ {task_data.get('sc_phone', 'Не указан')}\n\n"
                    f"📋 Инструкции:\n"
                    f"1. Заберите товар у клиента\n"
                    f"2. Подтвердите получение от клиента кнопкой 'Получено от клиента'\n"
                    f"3. Доставьте товар в СЦ\n"
                    f"4. Получите код подтверждения от СЦ"
                )
                keyboard = [[
                    InlineKeyboardButton(
                        "✅ Получено от клиента", 
                        callback_data=f"confirm_pickup_{request_id}"
                    )
                ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup)
            # Уведомляем всех остальных доставщиков
            await self.update_delivery_messages(context.bot, task_id, task_data)
            # Уведомляем клиента или СЦ в зависимости от типа доставки
            if request_id in requests_data:  # Добавляем проверку на существование заявки
                if is_sc_to_client or delivery_type == 'sc_to_client':
                    # Уведомляем клиента, что заказ принят в доставку из СЦ
                    client_id = requests_data[request_id].get('user_id')
                    if client_id:
                        client_message = (
                            f"🚚 Доставщик принял ваш заказ №{request_id} и направляется в сервисный центр.\n"
                            f"Скоро ваше устройство будет у вас!"
                        )
                        await context.bot.send_message(
                            chat_id=client_id,
                            text=client_message
                        )
                else:
                    # Уведомляем клиента, что заказ принят в доставку от клиента в СЦ
                    client_id = requests_data[request_id].get('user_id')
                    if client_id:
                        client_message = (
                            f"🚚 Доставщик принял ваш заказ №{request_id} и направляется к вам.\n"
                            f"Ожидайте доставщика по адресу: {task_data.get('client_address', 'указанному в заказе')}."
                        )
                        await context.bot.send_message(
                            chat_id=client_id,
                            text=client_message
                        )
            # Уведомляем администраторов
            users_data = await load_users()
            user = users_data.get(str(query.from_user.id), {})
            delivery_name = user.get('name', user_name)
            delivery_phone = user.get('phone', 'Номер не указан')
            admin_message = (
                f"✅ Заказ №{request_id} принят доставщиком.\n"
                f"Доставщик: {delivery_name} - {delivery_phone}\n"
                f"Тип: {'Доставка из СЦ клиенту' if is_sc_to_client or delivery_type == 'sc_to_client' else 'Доставка от клиента в СЦ'}\n"
                f"Статус: {requests_data.get(request_id, {}).get('status', 'Неизвестно')}"
            )
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message
                )
        except Exception as e:
            await query.edit_message_text("❌ Произошла ошибка при принятии задания. Пожалуйста, попробуйте еще раз.")

    @log_method_call
    async def handle_confirm_pickup(self, update: Update, context: CallbackContext):
        """
        Обработка подтверждения(отказа) передачи предмета клиентом
        Отправка смс клиенту с кодом подтверждения
        """
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = await load_requests()
        if request_id in requests_data:
            # Сохраняем request_id в контексте для последующего использования
            context.user_data['current_request'] = request_id
            # Запрашиваем фотографии у доставщика
            await query.edit_message_text(
                "Пожалуйста, сделайте фотографии товара перед получением. "
                "Когда закончите, нажмите\n\n/DONE"
            )
            return CREATE_REQUEST_PHOTOS
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")

    @log_method_call
    async def handle_client_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения/отказа клиента о получении товара"""
        query = update.callback_query
        await query.answer()
        try:
            action, request_id = query.data.split('_')[1:]
            requests_data = await load_requests()
            users_data = await load_users()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            client_id = request.get('user_id')
            client_data = users_data.get(str(client_id), {})
            if action == 'confirm':
                # Клиент подтвердил получение товара доставщиком
                await query.edit_message_text("✅ Вы подтвердили получение товара доставщиком. Ожидайте код подтверждения.")
                # Сохраняем ID запроса и клиента в контексте
                context.user_data['current_request'] = request_id
                context.user_data['client_id'] = client_id
                # Генерируем код подтверждения
                confirmation_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
                requests_data[request_id]['confirmation_code'] = confirmation_code
                await save_requests(requests_data)
                # Определяем режим работы (тестовый или боевой)
                if DEBUG:
                    # В тестовом режиме отправляем код ДОСТАВЩИКУ, а клиент его вводит
                    delivery_id = request.get('assigned_delivery')
                    if delivery_id:
                        await context.bot.send_message(
                            chat_id=delivery_id,
                            text=f"Ваш код подтверждения для заявки #{request_id}: {confirmation_code}\n\nПродиктуйте его клиенту для подтверждения."
                        )
                        # Сообщаем клиенту, что нужно ввести код от доставщика
                        await context.bot.send_message(
                            chat_id=client_id,
                            text=f"Доставщик получит код подтверждения. Пожалуйста, введите код, который вам сообщит доставщик:"
                        )
                    # Устанавливаем состояние для ожидания кода ОТ КЛИЕНТА
                    context.user_data['awaiting_confirmation_code'] = request_id
                    context.user_data['current_request'] = request_id
                    return ENTER_CONFIRMATION_CODE
                else:
                    # В боевом режиме отправляем SMS с кодом КЛИЕНТУ
                    if 'phone' in client_data and client_data['phone']:
                        try:
                            phone = client_data['phone'].replace('+', '')
                            # Инициализируем SMS-клиент
                            sms_client = SMSBY(SMS_TOKEN, 'by')
                            # Получаем список существующих объектов пароля
                            password_objects = sms_client.get_password_objects()
                            # Выбираем подходящий объект пароля
                            password_object = None
                            if password_objects and 'result' in password_objects and password_objects['result']:
                                # Сортируем объекты пароля по дате создания (новые сначала)
                                sorted_objects = sorted(
                                    password_objects['result'], 
                                    key=lambda x: x['d_create'], 
                                    reverse=True
                                )
                                # Берем первый подходящий объект пароля типа 'numbers'
                                password_object = next(
                                    (obj for obj in sorted_objects if obj['type_id'] == 'numbers'),
                                    None
                                )
                                if not password_object:
                                    # Если нет объектов типа 'numbers', берем первый доступный
                                    password_object = sorted_objects[0]
                            if not password_object:
                                raise Exception("Нет доступных объектов пароля для отправки SMS")
                            logger.info(f"Используем объект пароля: {password_object}")
                            # Получаем доступные альфа-имена
                            alphanames = sms_client.get_alphanames()
                            if alphanames:
                                alphaname_id = next(iter(alphanames.keys()))
                                sms_message = f"Код подтверждения для заявки #{request_id}: %CODE%"
                                sms_response = sms_client.send_sms_message_with_code(
                                    password_object_id=password_object['id'],  # Используем ID объекта
                                    phone=phone,
                                    message=sms_message,
                                    alphaname_id=alphaname_id
                                )
                                if 'code' in sms_response:
                                    # Сохраняем код в данных заявки
                                    requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                                    requests_data[request_id]['confirmation_code'] = sms_response['code']
                                    await save_requests(requests_data)
                                    # Сообщаем КЛИЕНТУ, чтобы он ввёл код из SMS
                                    await context.bot.send_message(
                                        chat_id=client_id,
                                        text=f"📲 Вам отправлен SMS с кодом подтверждения. Пожалуйста, введите его здесь:"
                                    )
                                    # Уведомляем ДОСТАВЩИКА, что нужно ждать подтверждения
                                    delivery_id = request.get('assigned_delivery')
                                    if delivery_id:
                                        await context.bot.send_message(
                                            chat_id=delivery_id,
                                            text=f"🕒 Ожидайте, пока клиент введёт код подтверждения из SMS."
                                        )
                                    # Устанавливаем состояние для ожидания кода ОТ КЛИЕНТА
                                    context.user_data['awaiting_confirmation_code'] = request_id
                                    context.user_data['current_request'] = request_id
                                    context.user_data['client_id'] = client_id
                                    logger.info(f"Код подтверждения для заявки #{request_id}: {requests_data[request_id]['confirmation_code']}")
                                    return ENTER_CONFIRMATION_CODE
                                else:
                                    raise Exception("Не удалось отправить SMS")
                            else:
                                raise Exception("Нет доступных альфа-имен для отправки SMS")
                        except Exception as e:
                            # Если SMS не удалось отправить, используем код из интерфейса
                            await context.bot.send_message(
                                chat_id=client_id,
                                text=f"Не удалось отправить SMS с кодом подтверждения. Используйте код: {confirmation_code}\n\nПожалуйста, введите его здесь:"
                            )
                            # Уведомляем доставщика, что клиент будет вводить код
                            delivery_id = request.get('assigned_delivery')
                            if delivery_id:
                                await context.bot.send_message(
                                    chat_id=delivery_id,
                                    text=f"🕒 Ожидайте, пока клиент введёт код подтверждения."
                                )
                            # Устанавливаем состояние для ожидания кода ОТ КЛИЕНТА
                            context.user_data['awaiting_confirmation_code'] = request_id
                            context.user_data['current_request'] = request_id
                            context.user_data['client_id'] = client_id
                            return ENTER_CONFIRMATION_CODE
                    else:
                        # У клиента нет телефона, используем код из интерфейса
                        await context.bot.send_message(
                            chat_id=client_id,
                            text=f"Ваш код подтверждения: {confirmation_code}\n\nПожалуйста, введите его здесь:"
                        )
                        # Уведомляем доставщика, что клиент будет вводить код
                        delivery_id = request.get('assigned_delivery')
                        if delivery_id:
                            await context.bot.send_message(
                                chat_id=delivery_id,
                                text=f"🕒 Ожидайте, пока клиент введёт код подтверждения."
                            )
                            # Устанавливаем состояние для ожидания кода ОТ КЛИЕНТА
                            context.user_data['awaiting_confirmation_code'] = request_id
                            context.user_data['current_request'] = request_id
                            context.user_data['client_id'] = client_id
                            return ENTER_CONFIRMATION_CODE
            elif action == 'deny':
                # Проверяем, было ли это уведомление от администратора
                if request.get('status') == 'Требуется проверка':
                    # Если это повторный отказ после проверки администратором, отклоняем заявку
                    request['status'] = ORDER_STATUS_CLIENT_REJECTED
                    await save_requests(requests_data)
                    # Уведомляем администратора об отклонении заявки
                    admin_message = (
                        f"❌ Клиент отказался от получения товара после проверки\n\n"
                        f"Заявка: #{request_id}\n"
                        f"Статус: Отклонена\n"
                        f"Описание: {request.get('description', 'Нет описания')}"
                    )
                    for admin_id in ADMIN_IDS:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message
                        )
                    await query.edit_message_text("❌ Вы отказались от получения товара. Заявка отклонена.")
                else:
                    # Первичный отказ - отправляем на проверку администратору
                    request['status'] = 'Требуется проверка'
                    await save_requests(requests_data)
                    # Уведомляем администратора
                    admin_message = (
                        f"⚠️ Клиент отказался от получения товара\n\n"
                        f"Заявка: #{request_id}\n"
                        f"Статус: Требуется проверка\n"
                        f"Описание: {request.get('description', 'Нет описания')}"
                    )
                    # Создаем клавиатуру для администратора
                    keyboard = [[
                        InlineKeyboardButton(
                            "📞 Связаться с клиентом",
                            callback_data=f"contact_client_{request_id}"
                        )]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    # Отправляем фотографии администратору
                    pickup_photos = request.get('pickup_photos', [])
                    if pickup_photos:
                        for photo_path in pickup_photos[:1]:  # Отправляем только первое фото
                            if os.path.exists(photo_path):
                                with open(photo_path, 'rb') as photo_file:
                                    await context.bot.send_photo(
                                        chat_id=ADMIN_IDS[0],
                                        photo=photo_file,
                                        caption=admin_message,
                                        reply_markup=reply_markup
                                    )
                                break
                    else:
                        for admin_id in ADMIN_IDS:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=admin_message,
                                reply_markup=reply_markup
                            )
                    await query.edit_message_text("❌ Вы отказались от получения товара. Администратор уведомлен.")
        except Exception as e:
            await query.edit_message_text("❌ Произошла ошибка при обработке вашего запроса.")

    @log_method_call
    async def pickup_client_code_confirmation(self, update: Update, context: CallbackContext):
        """Обработка проверки кода подтверждения, вводимого клиентом"""
        try:
            entered_code = update.message.text.strip()
            request_id = context.user_data.get('current_request')
            # Проверяем, что код вводит клиент, а не доставщик
            user_id = str(update.effective_user.id)
            client_id = context.user_data.get('client_id')
            if not client_id or user_id != str(client_id):
                # Если код пытается ввести не клиент
                await update.message.reply_text("⚠️ Только клиент должен вводить код подтверждения.")
                return ENTER_CONFIRMATION_CODE
            if not request_id:
                await update.message.reply_text("❌ Ошибка: не найдена активная заявка.")
                return ConversationHandler.END
            requests_data = await load_requests()
            if request_id not in requests_data:
                await update.message.reply_text("❌ Ошибка: заявка не найдена.")
                return ConversationHandler.END
            request = requests_data[request_id]
            expected_code = request.get('confirmation_code')
            if not expected_code:
                await update.message.reply_text("❌ Ошибка: код подтверждения не найден.")
                return ConversationHandler.END
            if entered_code == expected_code:
                # Код подтверждения верный
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                request['client_confirmed'] = True
                await save_requests(requests_data)
                # Обновляем статус в delivery_tasks
                delivery_tasks = await load_delivery_tasks()
                for _, task in delivery_tasks.items():
                    if isinstance(task, dict) and task.get('request_id') == request_id:
                        task['status'] = ORDER_STATUS_DELIVERY_TO_SC
                        await save_delivery_tasks(delivery_tasks)
                        break
                # Уведомляем клиента
                await update.message.reply_text(
                    f"✅ Код подтвержден. Доставщик отправляется с товаром в СЦ."
                )
                # Отправляем сообщение доставщику
                delivery_id = request.get('assigned_delivery')
                if delivery_id:
                    # Получаем данные СЦ
                    sc_id = request.get('assigned_sc')
                    service_centers = await load_service_centers()
                    sc_data = service_centers.get(sc_id, {})
                    await context.bot.send_message(
                        chat_id=delivery_id,
                        text=f"✅ Клиент подтвердил получение товара по заявке #{request_id}!\n\n"
                             f"Вы можете отправляться с товаром в СЦ.\n\n"
                             f"Адрес СЦ для доставки:\n"
                             f"🏢 {sc_data.get('name', 'Не указан')}\n"
                             f"📍 {sc_data.get('address', 'Не указан')}"
                    )
                # Уведомляем администратора
                for admin_id in ADMIN_IDS:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"✅ Доставщик получил товар от клиента по заявке #{request_id} и направляется в СЦ."
                    )
                # Очищаем данные контекста
                context.user_data.pop('awaiting_confirmation_code', None)
                context.user_data.pop('current_request', None)
                context.user_data.pop('client_id', None)
                return ConversationHandler.END
            else:
                # Неверный код
                await update.message.reply_text(
                    "❌ Неверный код подтверждения. Пожалуйста, проверьте код и попробуйте снова."
                )
                return ENTER_CONFIRMATION_CODE
        except Exception:
            await update.message.reply_text("❌ Произошла ошибка при проверке кода.")
            return ConversationHandler.END

    @log_method_call
    async def handle_delivered_to_sc(self, update: Update, context: CallbackContext):
        """Обработка передачи предмета в Сервисный Центр."""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        await query.edit_message_text(
            "Пожалуйста, сделайте фото товара перед передачей в СЦ. "
            "Когда закончите, нажмите\n\n/DONE"
        )
        context.user_data['photos_to_sc'] = []
        context.user_data['current_request'] = request_id
        return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def handle_delivery_photo(self, update: Update, context: CallbackContext):
        """Обработка фотографий от доставщика"""
        if 'photos_to_sc' not in context.user_data:
            return
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/delivery_to_sc_{len(context.user_data['photos_to_sc'])}_{context.user_data['current_request']}.jpg"
        await photo_file.download_to_drive(photo_path)
        context.user_data['photos_to_sc'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Когда закончите, нажмите\n\n/DONE")
        return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def handle_delivery_photos_done(self, update: Update, context: CallbackContext):
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('photos_to_sc', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            requests_data = await load_requests()
            delivery_tasks = await load_delivery_tasks()
            users_data = await load_users()
            # Обновляем статус и сохраняем фото
            requests_data[request_id].update({
                'status': ORDER_STATUS_WAITING_SC,
                'delivery_photos': photos
            })
            await save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            for task in delivery_tasks.values():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_WAITING_SC
                    break
            await save_delivery_tasks(delivery_tasks)
            sc_id = requests_data[request_id].get('assigned_sc')
            if not sc_id:
                return
            # Находим telegram_id пользователя СЦ
            sc_telegram_id = None
            for user_id, user_data in users_data.items():
                if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                    sc_telegram_id = int(user_id)
                    break
            if not sc_telegram_id:
                await update.message.reply_text("Ошибка: не удалось найти контакт СЦ")
                return
            # Уведомляем СЦ
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
            # Сначала отправляем фотографии
            for photo_path in photos:
                if os.path.exists(photo_path):
                    with open(photo_path, 'rb') as photo_file:
                        await context.bot.send_photo(
                            chat_id=sc_telegram_id,
                            photo=photo_file,
                            caption=f"Фото товара по заявке #{request_id}"
                        )
            # Затем отправляем текстовое сообщение с кнопками
            await context.bot.send_message(
                chat_id=sc_telegram_id,
                text=sc_message,
                reply_markup=reply_markup
            )
            context.user_data.pop('photos_to_sc', None)
            context.user_data.pop('current_request', None)
            await update.message.reply_text("✅ Фотографии загружены и отправлены в СЦ")
            return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text("Произошла ошибка при обработке фотографий")
            return ConversationHandler.END

    @log_method_call
    async def update_delivery_messages(self, bot, task_id, task_data):
        """Обновляет сообщения для других доставщиков"""
        # Получаем ID доставщика, который взял заказ
        assigned_delivery_id = task_data.get('assigned_delivery_id', '')
        # Формируем сообщение об обновлении
        message = f"Заказ #{task_id} был принят другим доставщиком и больше не доступен."
        # Отправляем сообщение другим доставщикам
        from config import DELIVERY_IDS
        for delivery_id in DELIVERY_IDS:
            if str(delivery_id) != str(assigned_delivery_id):
                await bot.send_message(
                    chat_id=int(delivery_id), 
                    text=message
                )

    @log_method_call
    async def show_available_tasks(self, update: Update, context: CallbackContext):
        """Показать доступные задания доставки"""
        try:
            delivery_tasks = await load_delivery_tasks()
            available_tasks = {}
            # Получаем текущую дату в формате DD.MM.YYYY
            today = datetime.now().strftime("%d.%m.%Y")
            # Фильтруем задачи по статусу и дате
            for task_id, task in delivery_tasks.items():
                if (task.get('status') == 'Новая' and 
                    task.get('desired_date', '').split()[-1] == today):
                    available_tasks[task_id] = task
            if not available_tasks:
                await update.message.reply_text(
                    f"На сегодня ({today}) нет доступных заданий доставки."
                )
                return
            # Отправляем заголовок с текущей датой
            await update.message.reply_text(
                f"📦 Доступные задания на сегодня ({today}):"
            )
            # Отправляем каждую задачу отдельным сообщением
            for task_id, task in available_tasks.items():
                # Определяем тип доставки
                is_sc_to_client = task.get('is_sc_to_client', False)
                delivery_type = task.get('delivery_type', '')   
                if is_sc_to_client or delivery_type == 'sc_to_client':
                    delivery_type_display = "📤 Доставка ИЗ СЦ КЛИЕНТУ"
                    # Извлекаем время доставки
                    delivery_time = task.get('desired_date', '').split()[0] if task.get('desired_date') else 'Не указано'
                    keyboard = [[
                        InlineKeyboardButton(
                            "Принять заказ",
                            callback_data=f"accept_delivery_{task.get('request_id', '')}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    # Для доставки из СЦ клиенту
                    message = (
                        f"📦 Задача #{task_id}\n"
                        f"Тип: {delivery_type_display}\n"
                        f"Время: {delivery_time}\n\n"
                        f"1️⃣ Забрать из СЦ:\n"
                        f"🏢 {task.get('sc_name', 'Не указан')}\n"
                        f"📍 {task.get('sc_address', 'Не указан')}\n"
                        f"☎️ {task.get('sc_phone', 'Не указан')}\n\n"
                        f"2️⃣ Доставить клиенту:\n"
                        f"👤 {task.get('client_name', 'Не указан')}\n"
                        f"📍 {task.get('client_address', 'Не указан')}\n"
                        f"📱 {task.get('client_phone', 'Не указан')}\n\n"
                        f"📝 Описание: {task.get('description', '')[:100]}..."
                    )
                else:
                    delivery_type_display = "📥 Доставка ОТ КЛИЕНТА В СЦ"
                    # Извлекаем время доставки
                    delivery_time = task.get('desired_date', '').split()[0] if task.get('desired_date') else 'Не указано'
                    keyboard = [[
                        InlineKeyboardButton(
                            "Принять заказ",
                            callback_data=f"accept_delivery_{task.get('request_id', '')}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    # Для доставки от клиента в СЦ
                    message = (
                        f"📦 Задача #{task_id}\n"
                        f"Тип: {delivery_type_display}\n"
                        f"Время: {delivery_time}\n\n"
                        f"1️⃣ Забрать у клиента:\n"
                        f"👤 {task.get('client_name', 'Не указан')}\n"
                        f"📍 {task.get('client_address', 'Не указан')}\n"
                        f"📱 {task.get('client_phone', 'Не указан')}\n\n"
                        f"2️⃣ Доставить в СЦ:\n"
                        f"🏢 {task.get('sc_name', 'Не указан')}\n"
                        f"📍 {task.get('sc_address', 'Не указан')}\n"
                        f"☎️ {task.get('sc_phone', 'Не указан')}\n\n"
                        f"📝 Описание: {task.get('description', '')[:100]}..."
                    )
                await update.message.reply_text(message, reply_markup=reply_markup)
        except Exception as e:
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    @log_method_call
    async def show_my_tasks(self, update: Update, context: CallbackContext):
        """Показать мои активные задания"""
        try:
            delivery_tasks = await load_delivery_tasks()
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
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    @log_method_call
    async def handle_confirmation_code(self, update: Update, context: CallbackContext):
        """Обработка ввода кода подтверждения"""
        entered_code = update.message.text.strip()
        request_id = context.user_data.get('current_request')
        if not request_id:
            await update.message.reply_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END
        requests_data = await load_requests()
        delivery_tasks = await load_delivery_tasks()
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
            await save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            for task_id, task in delivery_tasks.items():
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task.update({
                        'status': ORDER_STATUS_DELIVERY_TO_SC,
                        'assigned_delivery_id': delivery_id
                    })
                    break
            await save_delivery_tasks(delivery_tasks)
            # Отправляем адрес СЦ
            sc_id = request.get('assigned_sc')
            service_centers = await load_service_centers()
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

    @log_method_call
    async def handle_transfer_to_sc(self, update: Update, context: CallbackContext):
        """Обработка передачи товара в СЦ"""
        try:
            delivery_id = str(update.effective_user.id)
            delivery_tasks = await load_delivery_tasks()
            requests_data = await load_requests()
            active_tasks = {
                task_id: task for task_id, task in delivery_tasks.items()
                if isinstance(task, dict) and
                str(task.get('assigned_delivery_id')) == delivery_id and
                task.get('status') == ORDER_STATUS_DELIVERY_TO_SC
            }
            if not active_tasks:
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
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")

    @log_method_call
    async def cancel_delivery(self, update: Update, context: CallbackContext):
        """
        Отмена текущей операции доставки
        TODO: Сделаать очистку в цикле
        """
        keys_to_remove = {
            'photos_to_sc',
            'photos_from_sc',
            'current_request',
            'confirmation_code'
        }
        # Очищаем только нужные ключи, если они существуют
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        # Выбираем способ ответа в зависимости от типа update
        reply_method = (
            update.callback_query.edit_message_text 
            if update.callback_query 
            else update.message.reply_text
        )
        await reply_method("❌ Операция отменена. Вернитесь в меню доставщика.")
        return ConversationHandler.END

    @log_method_call
    async def handle_pickup_photo(self, update: Update, context: CallbackContext):
        """Обработка фотографий при получении товара"""
        if 'pickup_photos' not in context.user_data:
            context.user_data['pickup_photos'] = []
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/pickup_{len(context.user_data['pickup_photos'])}_{context.user_data['current_request']}.jpg"
        await photo_file.download_to_drive(photo_path)
        context.user_data['pickup_photos'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Когда закончите, нажмите\n\n/DONE")
        return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def handle_pickup_photos_done(self, update: Update, context: CallbackContext):
        """Завершение процесса фотографирования при получении товара"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('pickup_photos', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            requests_data = await load_requests()
            if request_id in requests_data:
                # Сохраняем фотографии в данных заявки
                requests_data[request_id]['pickup_photos'] = photos
                await save_requests(requests_data)
                # Отправляем уведомление администратору
                for admin_id in ADMIN_IDS:
                    # Отправляем первое фото с текстом
                    if photos and os.path.exists(photos[0]):
                        with open(photos[0], 'rb') as photo_file:
                            await context.bot.send_photo(
                                chat_id=admin_id,
                                photo=photo_file,
                                caption=f"Доставщик сделал фотографии товара по заявке #{request_id}"
                            )
                # Отправляем фотографии клиенту для подтверждения
                client_id = requests_data[request_id].get('user_id')
                if client_id:
                    # Получаем данные СЦ
                    sc_id = requests_data[request_id].get('assigned_sc')
                    service_centers = await load_service_centers()
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
        except Exception as e:
            await update.message.reply_text("Произошла ошибка при обработке фотографий")
            return ConversationHandler.END
