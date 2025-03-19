import json
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ADMIN_IDS, ENTER_NAME, ENTER_PHONE, DELIVERY_MENU,
    ENTER_CONFIRMATION_CODE, SMS_TOKEN,
    ORDER_STATUS_DELIVERY_TO_SC, ORDER_STATUS_DELIVERY_TO_CLIENT,
    ORDER_STATUS_CLIENT_REJECTED, ORDER_STATUS_WAITING_SC, CREATE_REQUEST_PHOTOS,
    DATA_DIR, USERS_JSON, REQUESTS_JSON, DELIVERY_TASKS_JSON
)
from handlers.base_handler import BaseHandler
from database import load_delivery_tasks, load_users, load_requests, save_delivery_tasks, save_requests, save_users, load_service_centers
from utils import notify_client
import logging
import random
import requests
from telegram.error import BadRequest

from smsby import SMSBY

# TODO: сделать смс - отдельным методом (не срочно) ИЛИ сделать отдельным потоком

logger = logging.getLogger(__name__)


class DeliveryHandler(BaseHandler):

    async def show_delivery_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Доступные задания", "Мои задания"],
            ["Передать в СЦ", "Мой профиль"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню доставщика:", reply_markup=reply_markup)

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
            # Проверяем, не была ли задача уже принята
            if requests_data[request_id].get('assigned_delivery'):
                await query.edit_message_text("Эта задача уже принята другим доставщиком.")
                return

            # Обновляем данные заявки
            requests_data[request_id]['assigned_delivery'] = str(query.from_user.id)
            requests_data[request_id]['status'] = 'Принято доставщиком'
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

            # Формируем новый текст сообщения
            message_text = (
                f"Заявка #{request_id}\n"
                f"Статус: Принято доставщиком\n"
                f"Доставщик: {delivery_name}\n"
                f"Телефон: +{delivery_phone}"
            )

            try:
                # Обновляем сообщение с новой информацией
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=None  # Убираем кнопки после принятия заказа
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise e

            # Уведомляем администраторов
            admin_message = (
                f"Заказ #{request_id} принят доставщиком.\n"
                f"Доставщик: {delivery_name} - +{delivery_phone}\n"
                f"Статус: Доставщик в пути к клиенту"
            )
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode='Markdown'
                )
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")

# уведомление СЦ
    async def handle_confirm_pickup(self, update: Update, context: CallbackContext):
        """
        Обработка подтверждения(отказа) передачи предмета клиентом
        Отправка смс клиенту с кодом подтверждения
        TODO: сделать смс - отдельным методом (не срочно)
        """
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        users_data = load_users()
        if request_id in requests_data:
            requests_data[request_id]['status'] = 'Ожидает подтверждения клиента'
            # обновляем статус задачи
            for task in delivery_tasks:
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = 'Ожидает подтверждения клиента'
                    break
            save_delivery_tasks(delivery_tasks)
            client_id = requests_data[request_id].get('user_id')
            client_data = users_data.get(str(client_id), {})
            if client_id:
                try:
                    keyboard = [
                        [InlineKeyboardButton("Да, забрал", callback_data=f"client_confirm_{request_id}")],
                        [InlineKeyboardButton("Нет, не забрал", callback_data=f"client_deny_{request_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=client_id,
                        text=f"Доставщик сообщает, что забрал ваш предмет по заявке №{request_id}. Подтверждаете?",
                        reply_markup=reply_markup
                    )
                    """
                    # Отправка SMS с кодом
                    if 'phone' in client_data:
                        try:
                            phone = client_data['phone'].replace('+', '')
                            logger.info(f"Отправка SMS на номер: {phone}")
                            sms_client = SMSBY(SMS_TOKEN, 'by')
                            logger.info("Создание объекта пароля...")
                            password_response = sms_client.create_password_object('numbers', 4)
                            logger.info(f"Ответ создания пароля: {password_response}")
                            if 'result' in password_response and 'password_object_id' in password_response['result']:
                                password_object_id = password_response['result']['password_object_id']
                                logger.info(f"ID объекта пароля: {password_object_id}")
                                alphanames = sms_client.get_alphanames()
                                logger.info(f"Доступные альфа-имена: {alphanames}")
                                if alphanames:
                                    alphaname_id = next(iter(alphanames.keys()))
                                    sms_message = f"Код подтверждения для заявки #{request_id}: %CODE%"
                                    logger.info(f"Отправка SMS с сообщением: {sms_message}")
                                    sms_response = sms_client.send_sms_message_with_code(
                                        password_object_id=password_object_id,
                                        phone=phone,
                                        message=sms_message,
                                        alphaname_id=alphaname_id  # альфа-имя
                                    )
                                    logger.info(f"Ответ отправки SMS: {sms_response}")
                                else:
                                    logger.error("Нет доступных альфа-имен")
                                    raise Exception("Нет доступных альфа-имен для отправки SMS")
                                if 'code' in sms_response:
                                    requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                                    requests_data[request_id]['confirmation_code'] = sms_response['code']
                                    save_requests(requests_data)
                                    await context.bot.send_message(
                                        chat_id=client_id,
                                        text=f"На ваш номер телефона отправлен код подтверждения. Пожалуйста, введите его:"
                                    )
                                    context.user_data['current_request'] = request_id
                                    return ENTER_CONFIRMATION_CODE
                                else:
                                    logger.error(f"Ошибка отправки SMS: нет кода в ответе")
                                    raise Exception("Не удалось отправить SMS")
                            else:
                                logger.error(f"Ошибка создания пароля: {password_response}")
                                raise Exception("Не удалось создать объект пароля")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке SMS: {str(e)}")
                            await context.bot.send_message(
                                chat_id=client_id,
                                text="Извините, возникла проблема с отправкой SMS. Пожалуйста, используйте кнопки подтверждения выше."
                            )
                            """
                    await query.edit_message_text(
                        f"Вы подтвердили получение предмета по заявке №{request_id}. "
                        "Ожидаем подтверждения клиента."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления: {str(e)}")
                    await query.edit_message_text("Произошла ошибка при отправке уведомления клиенту.")
                    return ConversationHandler.END
            else:
                await query.edit_message_text("ID клиента не найден для заявки.")
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

# добавить уведомление клиенту
    async def handle_delivery_photos_done(self, update: Update, context: CallbackContext):
        """Завершение отправки фотографий и уведомление СЦ"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('photos_to_sc', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
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
                    sc_name = task.get('sc_name')  # Получаем имя СЦ из задачи
                    break
            save_delivery_tasks(delivery_tasks)
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
            
            # Загружаем пользователей и находим sc_id по sc_name
            users_data = load_users()
            sc_id = None
            
            for user_id, user_info in users_data.items():
                if user_info.get('sc_name') == sc_name:
                    sc_id = user_id
                    break
            
            if sc_id:
                try:
                    media_group = [InputMediaPhoto(open(photo, 'rb')) for photo in photos]
                    await context.bot.send_media_group(chat_id=sc_id, media=media_group)
                    await context.bot.send_message(
                        chat_id=sc_id,
                        text=sc_message,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления СЦ {sc_id}: {e}")
            
            # Очищаем данные
            del context.user_data['photos_to_sc']
            del context.user_data['current_request']
            await update.message.reply_text("✅ Фотографии загружены, ожидаем подтверждения от СЦ.")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Ошибка при завершении загрузки фото: {e}")
            await update.message.reply_text("Произошла ошибка при обработке фотографий.")
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
        """Показать доступные задания"""
        logger.info("Вызван метод show_available_tasks")
        try:
            delivery_tasks = load_delivery_tasks()
            logger.info(f"Loaded delivery tasks: {delivery_tasks}")
            if not delivery_tasks:
                await update.message.reply_text("На данный момент нет доступных задач доставки.")
                return
            available_tasks = {
                task_id: task for task_id, task in delivery_tasks.items() 
                if task.get('status') == "Новая" and not task.get('assigned_delivery_id')
            }
            logger.info(f"Available tasks: {available_tasks}")
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
            delivery_id = str(update.effective_user.id)
            delivery_tasks = load_delivery_tasks()
            logger.info(f"Проверка задач для доставщика {delivery_id}")
            logger.info(f"Все задачи: {delivery_tasks}")
            active_tasks = {
                task_id: task for task_id, task in delivery_tasks.items()
                if isinstance(task, dict) and 
                str(task.get('assigned_delivery_id')) == delivery_id and
                task.get('status') in [ORDER_STATUS_DELIVERY_TO_CLIENT, ORDER_STATUS_DELIVERY_TO_SC]
            }
            if not active_tasks:
                logger.info(f"Нет активных задач для доставщика {delivery_id}. Текущие задачи: {delivery_tasks}")
                await update.message.reply_text("У вас пока нет активных заданий.")
                return
            for task_id, task in active_tasks.items():
                status = task.get('status', 'Статус не указан')
                keyboard = []
                if status == ORDER_STATUS_DELIVERY_TO_SC:
                    keyboard.append([InlineKeyboardButton(
                        "Передать в СЦ", 
                        callback_data=f"delivered_to_sc_{task['request_id']}"
                    )])
                message = (
                    f"📦 Задача доставки #{task_id}\n"
                    f"Заявка: #{task['request_id']}\n"
                    f"Статус: {status}\n"
                    f"СЦ: {task.get('sc_name', 'Не указан')}\n"
                    f"Описание: {task.get('description', '')[:100]}..."
                )
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
