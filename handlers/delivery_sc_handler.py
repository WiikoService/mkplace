from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ORDER_STATUS_PICKUP_FROM_SC,
    ORDER_STATUS_SC_TO_CLIENT,
    CREATE_REQUEST_PHOTOS,
    ENTER_SC_CONFIRMATION_CODE, 
    ORDER_STATUS_DELIVERY_TO_SC,
    ORDER_STATUS_CLIENT_REJECTED,
    ORDER_STATUS_WAITING_SC,
    ORDER_STATUS_IN_SC,
    ORDER_STATUS_READY,
    ORDER_STATUS_PICKUP_FROM_SC,
    ENTER_CONFIRMATION_CODE,
    ADMIN_IDS,
    DEBUG,
    SMS_TOKEN, WAITING_FINAL_PAYMENT, PAYMENT_API_URL
)
from handlers.delivery_handler import DeliveryHandler
from database import (
    load_requests, save_requests,
    load_delivery_tasks, save_delivery_tasks,
    load_users, load_service_centers
)
from utils import notify_client
import logging
import time
import random
import os
from smsby import SMSBY
import aiohttp
import json
from decimal import Decimal

logger = logging.getLogger(__name__)

class DeliverySCHandler(DeliveryHandler):
    """Обработчик для доставки из СЦ"""

    async def handle_pickup_from_sc(self, update: Update, context: CallbackContext):
        """Начало процесса подтверждения получения от СЦ"""
        query = update.callback_query
        await query.answer()
        
        try:
            request_id = query.data.split('_')[-1]
            context.user_data['current_request'] = request_id
            
            # Проверяем существование заявки
            requests_data = load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return ConversationHandler.END
                
            # Генерируем код подтверждения
            confirmation_code = ''.join(random.choices('0123456789', k=4))
            context.user_data['sc_confirmation_code'] = confirmation_code
            requests_data[request_id]['confirmation_code'] = confirmation_code
            save_requests(requests_data)
            
            # Отправляем код СЦ
            sc_id = requests_data[request_id].get('assigned_sc')
            users_data = load_users()
            sc_user_id = next(
                (uid for uid, data in users_data.items() 
                 if data.get('sc_id') == sc_id and data.get('role') == 'sc'),
                None
            )
            
            if sc_user_id:
                await context.bot.send_message(
                    chat_id=int(sc_user_id),
                    text=f"🔑 Код подтверждения для передачи товара: {confirmation_code}"
                )
            
            await query.edit_message_text(
                "Введите код подтверждения, полученный от СЦ:"
            )
            return ENTER_SC_CONFIRMATION_CODE
        except Exception as e:
            logger.error(f"Ошибка при начале процесса получения от СЦ: {e}")
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def check_sc_confirmation_code(self, update: Update, context: CallbackContext):
        """Проверка кода подтверждения от СЦ"""
        try:
            entered_code = update.message.text.strip()
            request_id = context.user_data.get('current_request')
            
            if not request_id:
                await update.message.reply_text("❌ Не найдена активная заявка.")
                return ConversationHandler.END
                
            # Загружаем данные
            requests_data = load_requests()
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
                
            expected_code = requests_data[request_id].get('confirmation_code')
            
            if entered_code != expected_code:
                await update.message.reply_text("❌ Неверный код. Попробуйте еще раз:")
                return ENTER_SC_CONFIRMATION_CODE
                
            # Код верный - переходим к фотографиям
            await update.message.reply_text(
                "✅ Код подтвержден! Теперь сделайте фотографии товара.\n"
                "Когда закончите, нажмите /done"
            )
            context.user_data['photos_from_sc'] = []
            return CREATE_REQUEST_PHOTOS
        except Exception as e:
            logger.error(f"Ошибка при проверке кода подтверждения от СЦ: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def handle_sc_pickup_photo(self, update: Update, context: CallbackContext):
        """Обработка фото при заборе из СЦ"""
        try:
            if 'photos_from_sc' not in context.user_data:
                context.user_data['photos_from_sc'] = []
                
            photo = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            
            # Сохраняем фото с понятным именем
            request_id = context.user_data['current_request']
            photo_path = f"photos/sc_pickup_{request_id}_{len(context.user_data['photos_from_sc'])}.jpg"
            
            await photo_file.download_to_drive(photo_path)
            context.user_data['photos_from_sc'].append(photo_path)
            
            await update.message.reply_text(
                f"✅ Фото #{len(context.user_data['photos_from_sc'])} сохранено.\n"
                "Отправьте еще фото или нажмите /done"
            )
            return CREATE_REQUEST_PHOTOS
        except Exception as e:
            logger.error(f"Ошибка при обработке фото из СЦ: {e}")
            await update.message.reply_text("❌ Произошла ошибка при сохранении фото. Попробуйте еще раз.")
            return CREATE_REQUEST_PHOTOS

    async def handle_sc_pickup_photos_done(self, update: Update, context: CallbackContext):
        """Завершение процесса фотографирования при получении из СЦ"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('photos_from_sc', [])
            
            if not photos:
                await update.message.reply_text("❌ Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
                
            # Загружаем данные
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
                
            # Обновляем статус и сохраняем фотографии
            request = requests_data[request_id]
            request['status'] = ORDER_STATUS_SC_TO_CLIENT
            request['sc_pickup_photos'] = photos
            save_requests(requests_data)
            
            # Обновляем задачу доставки
            for task_id, task in delivery_tasks.items():
                if task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_SC_TO_CLIENT
                    save_delivery_tasks(delivery_tasks)
                    break
                    
            # Отправляем уведомления администраторам
            admin_message = (
                f"✅ Доставщик {update.effective_user.first_name} забрал товар из СЦ\n"
                f"Заявка: #{request_id}\n"
                f"Статус: {ORDER_STATUS_SC_TO_CLIENT}\n\n"
                f"Фотографии получения товара:"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=int(admin_id),
                        text=admin_message
                    )
                    
                    # Отправляем фотографии
                    media_group = []
                    for photo_path in photos:
                        if os.path.exists(photo_path):
                            media_group.append(InputMediaPhoto(
                                media=open(photo_path, 'rb'),
                                caption=f"Заявка #{request_id}"
                            ))
                    if media_group:
                        await context.bot.send_media_group(
                            chat_id=int(admin_id),
                            media=media_group
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")
                    
            # Уведомляем клиента
            client_id = request.get('user_id')
            if client_id:
                try:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"🚚 Доставщик забрал ваш товар из СЦ и направляется к вам.\n"
                            f"Адрес доставки: {request.get('location_display', 'указанный в заявке')}"
                    )
                    
                    # Отправляем фотографии клиенту
                    for photo_path in photos:
                        if os.path.exists(photo_path):
                            with open(photo_path, 'rb') as photo_file:
                                await context.bot.send_photo(
                                    chat_id=int(client_id),
                                    photo=photo_file,
                                    caption=f"Фото вашего устройства после ремонта"
                                )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту {client_id}: {e}")
                    
            # Создаем кнопку "Сдать товар клиенту"
            keyboard = [[
                InlineKeyboardButton(
                    "📦 Сдать товар клиенту", 
                    callback_data=f"deliver_to_client_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Отправляем доставщику сообщение с адресом клиента и кнопкой
            client_address = request.get('location_display', 'Адрес не указан')
            client_name = request.get('user_name', 'Не указано')
            await update.message.reply_text(
                f"✅ Фотографии добавлены.\n\n"
                f"Теперь вы можете доставить товар клиенту по адресу:\n"
                f"👤 {client_name}\n"
                f"📍 {client_address}\n\n"
                f"Когда прибудете к клиенту, нажмите кнопку 'Сдать товар клиенту'",
                reply_markup=reply_markup
            )
            
            # Очищаем данные контекста
            context.user_data.pop('photos_from_sc', None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при завершении фотографирования из СЦ: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def _send_confirmation_code(self, context, recipient_id, code, request_id):
        """Отправка кода подтверждения с учетом режима работы"""
        try:
            if DEBUG:
                # В тестовом режиме отправляем код в чат
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=f"Тестовый режим. Код подтверждения: {code}"
                )
            else:
                # В боевом режиме отправляем SMS
                users_data = load_users()
                user_phone = users_data.get(str(recipient_id), {}).get('phone')
                if user_phone:
                    phone = user_phone.replace('+', '')
                    logger.info(f"Отправка SMS на номер: {phone}")
                    
                    # Инициализируем SMS-клиент
                    sms_client = SMSBY(SMS_TOKEN, 'by')
                    
                    # Получаем список существующих объектов пароля
                    logger.info("Получение списка существующих объектов пароля...")
                    password_objects = sms_client.get_password_objects()
                    logger.info(f"Доступные объекты пароля: {password_objects}")
                    
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
                        logger.error("Не найдены доступные объекты пароля")
                        raise Exception("Нет доступных объектов пароля для отправки SMS")
                        
                    logger.info(f"Используем объект пароля: {password_object}")
                    
                    # Получаем доступные альфа-имена
                    alphanames = sms_client.get_alphanames()
                    logger.info(f"Доступные альфа-имена: {alphanames}")
                    
                    if alphanames:
                        alphaname_id = next(iter(alphanames.keys()))
                        sms_message = f"Код подтверждения для заявки #{request_id}: %CODE%"
                        logger.info(f"Отправка SMS с сообщением: {sms_message}")
                        
                        sms_response = sms_client.send_sms_message_with_code(
                            password_object_id=password_object['id'],  # Используем ID объекта
                            phone=phone,
                            message=sms_message,
                            alphaname_id=alphaname_id
                        )
                        logger.info(f"Ответ отправки SMS: {sms_response}")
                        
                        if 'code' in sms_response:
                            # Сохраняем код в данных заявки
                            requests_data = load_requests()
                            if request_id in requests_data:
                                requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                                requests_data[request_id]['confirmation_code'] = sms_response['code']
                                save_requests(requests_data)
                            
                            # Сообщаем получателю, что код отправлен по SMS
                            await context.bot.send_message(
                                chat_id=recipient_id,
                                text=f"📲 Вам отправлен SMS с кодом подтверждения. Пожалуйста, введите его здесь:"
                            )
                            return True
                        else:
                            logger.error(f"Ошибка отправки SMS: нет кода в ответе")
                            raise Exception("Не удалось отправить SMS")
                    else:
                        logger.error(f"Ошибка: нет доступных альфа-имен")
                        raise Exception("Нет доступных альфа-имен для отправки SMS")
                else:
                    logger.error(f"У пользователя {recipient_id} не указан номер телефона")
                    raise Exception("Нет номера телефона для отправки SMS")
        except Exception as e:
            logger.error(f"Ошибка при отправке кода подтверждения: {e}")
            # Fallback - отправляем код в чат
            await context.bot.send_message(
                chat_id=recipient_id,
                text=f"Не удалось отправить SMS. Код подтверждения: {code}"
            )
            return False

    async def handle_deliver_to_client(self, update: Update, context: CallbackContext):
        """Обработка нажатия кнопки 'Сдать товар клиенту'"""
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            context.user_data['current_request'] = request_id
            
            # Загружаем данные
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена.")
                return ConversationHandler.END 
                
            request = requests_data[request_id]
            client_id = request.get('user_id')
            client_data = users_data.get(str(client_id), {})
            
            # Проверяем, нужно ли клиенту оплатить оставшуюся сумму
            payment_required = False
            final_price = Decimal(request.get('final_price', '0'))
            repair_price = Decimal(request.get('repair_price', '0'))
            delivery_cost = Decimal(request.get('delivery_cost', '0'))
            
            # Если клиент еще не оплатил полную стоимость (30% от repair_price + 20)
            if final_price > 0 and repair_price > 0:
                expected_payment = (repair_price * Decimal('0.3')) + Decimal('20')
                if final_price >= expected_payment:
                    payment_required = True
                    
            # Обновляем статус заявки
            requests_data[request_id]['status'] = ORDER_STATUS_SC_TO_CLIENT
            save_requests(requests_data)
            
            # Обновляем статус задачи доставки
            task_updated = False
            for task_id, task in delivery_tasks.items():
                if task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_SC_TO_CLIENT
                    task_updated = True
                    break
            if not task_updated:
                logger.error(f"Не найдена задача доставки для заявки {request_id}")
            save_delivery_tasks(delivery_tasks)
            
            # Получаем фотографии товара
            photos = requests_data[request_id].get('sc_pickup_photos', [])
            
            # Уведомляем клиента
            if client_id:
                try:
                    # Отправляем сообщение клиенту
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"🚚 Доставщик прибыл с вашим устройством и скоро передаст его вам.\n"
                            f"Адрес доставки: {requests_data[request_id].get('location_display', 'указанный в заявке')}"
                    )
                    
                    # Отправляем фотографии клиенту
                    for photo_path in photos:
                        if os.path.exists(photo_path):
                            with open(photo_path, 'rb') as photo_file:
                                await context.bot.send_photo(
                                    chat_id=int(client_id),
                                    photo=photo_file,
                                    caption=f"Фото вашего устройства после ремонта"
                                )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту {client_id}: {e}")
                    
            # Уведомляем администраторов
            admin_message = (
                f"🚚 Доставщик {update.effective_user.first_name} прибыл к клиенту для передачи товара\n"
                f"Заявка: #{request_id}\n"
                f"Статус: {ORDER_STATUS_SC_TO_CLIENT}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=int(admin_id),
                        text=admin_message
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")
                    
            # Генерируем код подтверждения
            confirmation_code = ''.join(random.choices('0123456789', k=4))
            requests_data[request_id]['confirmation_code'] = confirmation_code
            save_requests(requests_data)
            
            # ЧЕТКО РАЗДЕЛЯЕМ ЛОГИКУ ТЕСТОВОГО И БОЕВОГО РЕЖИМОВ
            
            # В тестовом режиме отправляем код доставщику
            if DEBUG:
                await query.edit_message_text(
                    f"🔢 Тестовый режим: код подтверждения для клиента: {confirmation_code}\n\n"
                    f"Попросите клиента ввести этот код в боте."
                )
                # Отправляем клиенту инструкцию
                if client_id:
                    try:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке инструкции клиенту {client_id}: {e}")
                return ENTER_CONFIRMATION_CODE
            
            # В боевом режиме отправляем SMS клиенту
            else:
                if client_id and client_data.get('phone'):
                    # Используем общий метод для отправки кода
                    sms_sent = await self._send_confirmation_code(
                        context, 
                        int(client_id), 
                        confirmation_code, 
                        request_id
                    )
                    
                    if sms_sent:
                        # Уведомляем доставщика
                        await query.edit_message_text(
                            "📲 Клиенту отправлен SMS с кодом подтверждения.\n\n"
                            "Ожидайте, пока клиент введёт код из SMS."
                        )
                    else:
                        # Если SMS не удалось отправить, используем код из интерфейса
                        await query.edit_message_text(
                            f"❌ Не удалось отправить SMS. Используйте код: {confirmation_code}\n\n"
                            f"Попросите клиента ввести этот код в боте."
                        )
                        
                        if client_id:
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                            )
                    return ENTER_CONFIRMATION_CODE
                else:
                    # Если у клиента нет телефона, используем код из интерфейса
                    await query.edit_message_text(
                        f"🔢 Код подтверждения для клиента: {confirmation_code}\n\n"
                        f"Попросите клиента ввести этот код в боте."
                    )
                    
                    if client_id:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                        )
                    
                    return ENTER_CONFIRMATION_CODE
        except Exception as e:
            logger.error(f"Ошибка при обработке сдачи товара клиенту: {e}")
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def handle_client_confirmation_code(self, update: Update, context: CallbackContext):
        """Проверка кода подтверждения от клиента"""
        try:
            entered_code = update.message.text.strip()
            request_id = context.user_data.get('current_request')
            
            if not request_id:
                await update.message.reply_text("❌ Не найдена активная заявка.")
                return ConversationHandler.END
                
            # Загружаем данные
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
                
            request = requests_data[request_id]
            client_id = request.get('user_id')
            expected_code = request.get('confirmation_code')
            
            # Проверяем, кто вводит код - клиент или доставщик
            user_id = str(update.effective_user.id)
            
            # Если код вводит клиент
            if client_id and user_id == str(client_id):
                if entered_code == expected_code:
                    # Проверяем, требуется ли оплата
                    final_price = Decimal(request.get('final_price', '0'))
                    repair_price = Decimal(request.get('repair_price', '0'))
                    delivery_cost = Decimal(request.get('delivery_cost', '0'))
                    
                    if final_price > 0:
                        # Создаем платеж для клиента
                        payment_data = {
                            'amount': float(final_price),
                            'description': f"Оплата ремонта по заявке #{request_id}"
                        }
                        
                        try:
                            async with aiohttp.ClientSession() as session:
                                payment_request_data = {'payment_request': json.dumps(payment_data)}
                                async with session.post(
                                    PAYMENT_API_URL,
                                    data=payment_request_data,
                                    timeout=10
                                ) as response:
                                    if response.status != 200:
                                        response_text = await response.text()
                                        raise Exception(f"HTTP error {response.status}: {response_text}")
                                        
                                    result = await response.json()
                                    
                                    if not result.get('order_id') or not result.get('payment_url'):
                                        raise Exception(f"Invalid API response: {result}")
                                        
                                    # Сохраняем данные платежа
                                    request['final_payment_order_id'] = result['order_id']
                                    save_requests(requests_data)
                                    
                                    # Отправляем кнопку оплаты клиенту
                                    keyboard = [
                                        [InlineKeyboardButton("✅ Оплатить", url=result['payment_url'])],
                                        [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_final_payment_{request_id}")]
                                    ]
                                    reply_markup = InlineKeyboardMarkup(keyboard)
                                    
                                    await context.bot.send_message(
                                        chat_id=int(client_id),
                                        text=f"💳 Пожалуйста, оплатите оставшуюся сумму: {final_price:.2f} BYN\n"
                                            f"После оплаты нажмите кнопку 'Проверить оплату'",
                                        reply_markup=reply_markup
                                    )
                                    
                                    # Уведомляем доставщика
                                    delivery_id = request.get('assigned_delivery')
                                    if delivery_id:
                                        await context.bot.send_message(
                                            chat_id=int(delivery_id),
                                            text=f"🔄 Клиент подтвердил получение и должен оплатить {final_price:.2f} BYN. Ожидайте завершения оплаты."
                                        )
                                    
                                    return WAITING_FINAL_PAYMENT
                                    
                        except Exception as e:
                            logger.error(f"Ошибка при создании платежа: {e}")
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"❌ Не удалось создать платеж: {str(e)}"
                            )
                            return ConversationHandler.END
                    else:
                        # Если оплата не требуется, запрашиваем фотографии у доставщика
                        delivery_id = request.get('assigned_delivery')
                        if delivery_id:
                            await context.bot.send_message(
                                chat_id=int(delivery_id),
                                text="✅ Клиент подтвердил получение. Сделайте фотографии передачи товара и отправьте их."
                            )
                        
                        context.user_data['awaiting_delivery_photos'] = True
                        return CREATE_REQUEST_PHOTOS
                else:
                    await update.message.reply_text("❌ Неверный код подтверждения. Попробуйте еще раз.")
                    return ENTER_CONFIRMATION_CODE
                    
            # Если код вводит доставщик (в тестовом режиме)
            elif user_id == str(request.get('assigned_delivery')):
                if entered_code == expected_code:
                    # В тестовом режиме доставщик вводит код, который знает клиент
                    await update.message.reply_text(
                        "✅ Код подтверждения верный! Ожидайте, пока клиент подтвердит получение."
                    )
                    return ConversationHandler.END
                else:
                    await update.message.reply_text("❌ Неверный код подтверждения. Попробуйте еще раз.")
                    return ENTER_CONFIRMATION_CODE
            else:
                await update.message.reply_text("❌ Только клиент или доставщик могут ввести код подтверждения.")
                return ENTER_CONFIRMATION_CODE
                
        except Exception as e:
            logger.error(f"Ошибка при проверке кода подтверждения: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def handle_delivery_photos(self, update: Update, context: CallbackContext):
        """Обработка фотографий при передаче товара клиенту"""
        try:
            if 'delivery_photos' not in context.user_data:
                context.user_data['delivery_photos'] = []
                
            photo = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            
            # Создаем уникальное имя файла
            request_id = context.user_data.get('current_request')
            timestamp = int(time.time())
            photo_path = f"photos/delivery_{request_id}_{timestamp}_{len(context.user_data['delivery_photos'])}.jpg"
            
            await photo_file.download_to_drive(photo_path)
            context.user_data['delivery_photos'].append(photo_path)
            
            await update.message.reply_text(
                f"✅ Фото #{len(context.user_data['delivery_photos'])} сохранено.\n"
                "Отправьте еще фото или нажмите /done"
            )
            return CREATE_REQUEST_PHOTOS
        except Exception as e:
            logger.error(f"Ошибка при обработке фото доставки: {e}")
            await update.message.reply_text("❌ Произошла ошибка при сохранении фото. Попробуйте еще раз.")
            return CREATE_REQUEST_PHOTOS

    async def handle_delivery_photos_done(self, update: Update, context: CallbackContext):
        """Завершение процесса фотографирования при передаче товара клиенту"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('delivery_photos', [])
            
            if not photos:
                await update.message.reply_text("❌ Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
                
            # Загружаем данные
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
                
            # Обновляем статус и сохраняем фотографии
            request = requests_data[request_id]
            request['status'] = "Доставлено клиенту"
            request['delivery_photos'] = photos
            save_requests(requests_data)
            
            # Обновляем задачу доставки
            for task_id, task in delivery_tasks.items():
                if task.get('request_id') == request_id:
                    task['status'] = "Завершено"
                    save_delivery_tasks(delivery_tasks)
                    break
                    
            # Отправляем уведомления администраторам
            admin_message = (
                f"✅ Доставка завершена!\n"
                f"Заявка: #{request_id}\n"
                f"Доставщик: {update.effective_user.first_name}\n\n"
                f"Фотографии передачи товара:"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=int(admin_id),
                        text=admin_message
                    )
                    
                    # Отправляем фотографии
                    media_group = []
                    for photo_path in photos:
                        if os.path.exists(photo_path):
                            media_group.append(InputMediaPhoto(
                                media=open(photo_path, 'rb'),
                                caption=f"Заявка #{request_id}"
                            ))
                    if media_group:
                        await context.bot.send_media_group(
                            chat_id=int(admin_id),
                            media=media_group
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")
                    
            # Уведомляем клиента
            client_id = request.get('user_id')
            if client_id:
                try:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"✅ Ваша заявка #{request_id} успешно завершена!\n\n"
                            f"Спасибо, что воспользовались нашими услугами!"
                    )
                    
                    # Отправляем кнопку для оценки сервиса
                    keyboard = [[
                        InlineKeyboardButton(
                            "🌟 Оценить качество обслуживания", 
                            callback_data=f"rate_service_{request_id}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text="Пожалуйста, оцените наш сервис:",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту {client_id}: {e}")
                    
            # Уведомляем доставщика
            await update.message.reply_text(
                "✅ Доставка успешно завершена! Фотографии отправлены администраторам.\n\n"
                "Спасибо за вашу работу!",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Очищаем контекст
            context.user_data.pop('current_request', None)
            context.user_data.pop('delivery_photos', None)
            context.user_data.pop('awaiting_delivery_photos', None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при завершении доставки: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def handle_final_payment_check(self, update: Update, context: CallbackContext):
        """Проверка оплаты клиентом оставшейся суммы"""
        query = update.callback_query
        await query.answer()
        
        try:
            request_id = query.data.split('_')[-1]
            requests_data = load_requests()
            
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return ConversationHandler.END
                
            request = requests_data[request_id]
            order_id = request.get('final_payment_order_id')
            client_id = request.get('user_id')
            delivery_id = request.get('assigned_delivery')
            
            if not order_id:
                await query.edit_message_text("❌ Информация о платеже не найдена")
                return ConversationHandler.END
            try:
                # Проверяем статус платежа
                status_data = {'payment_status_order_id': order_id}
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        PAYMENT_API_URL,
                        data=status_data,
                        timeout=10
                    ) as response:
                        if response.status != 200:
                            response_text = await response.text()
                            raise Exception(f"HTTP error {response.status}: {response_text}")
                        result = await response.json()
                        # Проверяем успешность платежа
                        if (result.get('errorCode') == '0' and 
                            result.get('orderStatus') == 2 and 
                            result.get('paymentAmountInfo', {}).get('paymentState') == 'DEPOSITED'):
                            # Платеж успешен
                            request['status'] = "Доставлено клиенту"
                            request['payment_status'] = "paid"
                            save_requests(requests_data)
                            # Уведомляем клиента
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"✅ Оплата принята. Заявка #{request_id} успешно завершена!"
                            )
                            # Уведомляем доставщика
                            if delivery_id:
                                await context.bot.send_message(
                                    chat_id=int(delivery_id),
                                    text=f"✅ Клиент успешно оплатил заказ. Сделайте фотографии передачи товара и отправьте их."
                                )
                            context.user_data['awaiting_delivery_photos'] = True
                            return CREATE_REQUEST_PHOTOS
                        else:
                            # Платеж не завершен
                            error_message = result.get('errorMessage', 'Неизвестная ошибка')
                            payment_state = result.get('paymentAmountInfo', {}).get('paymentState', 'Неизвестно')
                            order_status = result.get('orderStatus', 'Неизвестно')
                            # Отправляем кнопки для повторной проверки
                            keyboard = [
                                [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_final_payment_{request_id}")],
                                [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_final_payment_{request_id}")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await query.edit_message_text(
                                f"⏳ Платеж не завершен: {error_message}\n"
                                f"Статус: {payment_state}, Код: {order_status}\n\n"
                                "Попробуйте проверить еще раз через несколько секунд.",
                                reply_markup=reply_markup
                            )
                            return WAITING_FINAL_PAYMENT
            except Exception as e:
                logger.error(f"Ошибка при проверке платежа: {e}")
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_final_payment_{request_id}")],
                    [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_final_payment_{request_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Ошибка при проверке платежа: {str(e)}",
                    reply_markup=reply_markup
                )
                return WAITING_FINAL_PAYMENT
        except Exception as e:
            logger.error(f"Ошибка при обработке проверки платежа: {e}")
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    async def handle_delivered_to_client(self, update: Update, context: CallbackContext):
        """Обработка доставки товара клиенту из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            # Обновляем статус в заявке
            request = requests_data.get(request_id)
            if request:
                request['status'] = "Доставлено клиенту"
                save_requests(requests_data)
            # Обновляем статус в задаче доставки
            for task in delivery_tasks.values():
                if task.get('request_id') == request_id:
                    task['status'] = "Завершено"
                    save_delivery_tasks(delivery_tasks)
                    break
            await query.edit_message_text(
                "✅ Доставка завершена. Спасибо за работу!"
            )
            # После обновления статуса и уведомления администраторов
            # отправляем кнопку для начала диалога оценки
            client_id = requests_data[request_id].get('user_id')
            if client_id:
                try:
                    # Отправляем сообщение об успешной доставке
                    await context.bot.send_message(
                        chat_id=client_id,
                        text=f"✅ Ваша заявка #{request_id} успешно выполнена!"
                    )
                    # Отправляем кнопку для запуска диалога оценки
                    keyboard = [[InlineKeyboardButton(
                        "🌟 Оценить качество обслуживания", 
                        callback_data=f"rate_service_{request_id}"
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=client_id,
                        text="Пожалуйста, оцените наш сервис:",
                        reply_markup=reply_markup
                    )
                    logger.info(f"Запрос на оценку отправлен клиенту {client_id} для заявки {request_id}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке запроса на оценку клиенту: {e}")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при обработке доставки клиенту: {e}")
            await query.edit_message_text("Произошла ошибка при обновлении статуса")
            return ConversationHandler.END

    async def accept_delivery_from_sc(self, update: Update, context: CallbackContext):
        """Обработка принятия заказа доставщиком из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        delivery_id = str(update.effective_user.id)
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            # Проверяем существование заявки
            request = requests_data.get(request_id)
            if not request:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            # Находим задачу доставки
            task_id = None
            task = None
            for t_id, t_data in delivery_tasks.items():
                if t_data.get('request_id') == request_id:
                    task_id = t_id
                    task = t_data
                    break
            # Проверяем, не взял ли уже кто-то заказ
            if task.get('assigned_delivery_id'):
                await query.edit_message_text("❌ Заказ уже принят другим доставщиком")
                return
            # Обновляем данные задачи
            task.update({
                'assigned_delivery_id': delivery_id,
                'status': ORDER_STATUS_PICKUP_FROM_SC,
                'accepted_at': int(time.time())
            })
            # Обновляем статус заявки
            request['status'] = ORDER_STATUS_PICKUP_FROM_SC
            request['assigned_delivery'] = delivery_id
            # Сохраняем изменения
            save_delivery_tasks(delivery_tasks)
            save_requests(requests_data)
            # Уведомляем СЦ
            sc_id = request.get('assigned_sc')
            if sc_id:
                for user_id, user_data in users_data.items():
                    if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                        try:
                            delivery_user = users_data.get(delivery_id, {})
                            await context.bot.send_message(
                                chat_id=int(user_id),
                                text=(
                                    f"🚚 Доставщик принял заказ #{request_id}\n"
                                    f"Доставщик: {delivery_user.get('name')} - "
                                    f"{delivery_user.get('phone')}\n"
                                    f"Статус: Доставщик в пути в СЦ"
                                )
                            )
                        except Exception as e:
                            logger.error(f"Ошибка уведомления СЦ: {e}")
            # Уведомляем других доставщиков
            await self.update_delivery_messages(context.bot, task_id, task)
            # Отвечаем доставщику
            await query.edit_message_text(
                f"✅ Вы приняли заказ №{request_id}. Статус: Доставщик в пути в СЦ"
            )
        except Exception as e:
            logger.error(f"Ошибка при принятии заказа: {e}")
            await query.edit_message_text("❌ Произошла ошибка при принятии заказа")

    async def handle_get_sc_confirmation(self, update: Update, context: CallbackContext):
        """Обработка запроса кода подтверждения от СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        delivery_id = str(update.effective_user.id)
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            # Проверяем, что доставщик действительно назначен на эту задачу
            task = None
            for t_id, t_data in delivery_tasks.items():
                if (t_data.get('request_id') == request_id and 
                    t_data.get('delivery_type') == 'sc_to_client' and
                    t_data.get('assigned_delivery_id') == delivery_id):
                    task = t_data
                    break
            if not task:
                await query.edit_message_text("❌ Ошибка: вы не назначены на эту доставку")
                return ConversationHandler.END            
            # Генерируем код подтверждения
            confirmation_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
            context.user_data['sc_confirmation_code'] = confirmation_code
            context.user_data['current_request'] = request_id
            # Отправляем код СЦ
            request = requests_data.get(request_id)
            if request:
                sc_id = request.get('assigned_sc')
                if sc_id:
                    for user_id, user_data in users_data.items():
                        if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                            try:
                                delivery_user = users_data.get(delivery_id, {})
                                await context.bot.send_message(
                                    chat_id=int(user_id),
                                    text=(
                                        f"🚚 Доставщик прибыл за заказом #{request_id}\n"
                                        f"Доставщик: {delivery_user.get('name')} - "
                                        f"{delivery_user.get('phone')}\n"
                                        f"Код подтверждения: {confirmation_code}"
                                    )
                                )
                            except Exception as e:
                                logger.error(f"Ошибка уведомления СЦ: {e}")            
            # Обновляем статус задачи
            task['status'] = 'Ожидает подтверждение СЦ'
            delivery_tasks[t_id] = task
            save_delivery_tasks(delivery_tasks)
            # Обновляем статус заявки
            if request:
                request['status'] = 'Ожидает подтверждение СЦ'
                save_requests(requests_data)
            await query.edit_message_text(
                f"✅ Код подтверждения отправлен СЦ.\n"
                "Введите код, полученный от СЦ:"
            )
            return ENTER_SC_CONFIRMATION_CODE
        except Exception as e:
            logger.error(f"Ошибка при получении кода подтверждения: {e}")
            await query.edit_message_text("❌ Произошла ошибка при получении кода подтверждения")
            return ConversationHandler.END

    async def show_available_sc_tasks(self, update: Update, context: CallbackContext):
        """Показать доступные задания доставки из СЦ"""
        try:
            delivery_tasks = load_delivery_tasks()
            available_tasks = {}
            for task_id, task in delivery_tasks.items():
                if (task.get('delivery_type') == 'sc_to_client' and 
                    not task.get('assigned_delivery_id')):
                    available_tasks[task_id] = task  
            if not available_tasks:
                await update.message.reply_text("На данный момент нет доступных задач доставки из СЦ.")
                return
            for task_id, task in available_tasks.items():
                keyboard = [[
                    InlineKeyboardButton(
                        "Принять заказ",
                        callback_data=f"accept_sc_delivery_{task['request_id']}"
                    )
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                message = (
                    f"📦 Задача доставки #{task_id} из СЦ\n\n"
                    f"1️⃣ Забрать из СЦ:\n"
                    f"🏢 {task.get('sc_name', 'Не указан')}\n"
                    f"📍 {task.get('sc_address', 'Не указан')}\n\n"
                    f"2️⃣ Доставить клиенту:\n"
                    f"👤 {task.get('client_name', 'Не указан')}\n"
                    f"📍 {task.get('client_address', 'Не указан')}\n"
                    f"📱 {task.get('client_phone', 'Не указан')}\n\n"
                    f"📝 Описание: {task.get('description', '')[:100]}..."
                )
                await update.message.reply_text(message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при показе доступных заданий из СЦ: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")