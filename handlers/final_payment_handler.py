import random
import json
import os
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardRemove
from telegram.ext import CallbackContext, ConversationHandler

from handlers.delivery_sc_handler import DeliverySCHandler
from config import (
    CREATE_REQUEST_PHOTOS, ENTER_CONFIRMATION_CODE, 
    WAITING_FINAL_PAYMENT, ORDER_STATUS_SC_TO_CLIENT,
    DEBUG, ADMIN_IDS, PAYMENT_API_URL, SMS_TOKEN
)
from database import load_requests, save_requests, load_delivery_tasks, save_delivery_tasks, load_users
from smsby import SMSBY
import aiohttp
from logging_decorator import log_method_call
import logging

logger = logging.getLogger(__name__)


class FinalPaymentHandler(DeliverySCHandler):
    """Обработчик для процесса финальной оплаты при доставке товара клиенту"""

    @log_method_call
    async def handle_deliver_to_client(self, update: Update, context: CallbackContext):
        """
        Обработка нажатия кнопки 'Сдать товар клиенту' с генерацией кода подтверждения
        и отправкой SMS клиенту
        """
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            context.user_data['current_request'] = request_id
            # Загружаем данные
            requests_data = await load_requests()
            users_data = await load_users()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена.")
                return ConversationHandler.END
            request = requests_data[request_id]
            client_id = str(request.get('user_id'))  # Преобразуем в строку
            client_data = users_data.get(client_id, {})
            client_phone = client_data.get('phone')
            # Обновляем статус заявки
            requests_data[request_id]['status'] = ORDER_STATUS_SC_TO_CLIENT
            await save_requests(requests_data)
            # Обновляем статус задачи доставки
            await self._update_delivery_task_status(request_id, ORDER_STATUS_SC_TO_CLIENT)
            # Генерируем код подтверждения
            confirmation_code = ''.join(random.choices('0123456789', k=4))
            context.user_data['client_confirmation_code'] = confirmation_code
            requests_data[request_id]['confirmation_code'] = confirmation_code
            await save_requests(requests_data)
            # Определяем режим отправки кода (тестовый или боевой)
            if DEBUG:
                # В тестовом режиме отправляем код доставщику
                await query.edit_message_text(
                    f"🔢 Тестовый режим: код подтверждения для клиента: {confirmation_code}\n\n"
                    f"Попросите клиента ввести этот код в боте."
                )
                if client_id:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                    )
            else:
                # В боевом режиме отправляем SMS
                if client_phone:
                    try:
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
                                phone=client_phone.replace('+', ''),
                                message=sms_message,
                                alphaname_id=alphaname_id
                            )
                            if 'code' in sms_response:
                                # Сохраняем данные SMS
                                requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                                requests_data[request_id]['confirmation_code'] = sms_response['code']
                                await save_requests(requests_data)
                                # Уведомляем клиента
                                await context.bot.send_message(
                                    chat_id=int(client_id),
                                    text="📱 Вам отправлен SMS с кодом подтверждения. Введите его в боте:"
                                )
                                # Уведомляем доставщика
                                await query.edit_message_text(
                                    "✅ Код подтверждения отправлен клиенту по SMS.\n"
                                    "Ожидайте подтверждения от клиента."
                                )
                            else:
                                raise Exception("Не удалось отправить SMS")
                        else:
                            raise Exception("Нет доступных альфа-имен для отправки SMS")
                    except Exception:
                        # В случае ошибки отправляем код через бота
                        await query.edit_message_text(
                            f"❌ Не удалось отправить SMS. Используйте код: {confirmation_code}\n\n"
                            f"Попросите клиента ввести этот код в боте."
                        )
                else:
                    # Если нет телефона, отправляем код через бота
                    await query.edit_message_text(
                        f"❌ Не найден телефон клиента. Используйте код: {confirmation_code}\n\n"
                        f"Попросите клиента ввести этот код в боте."
                    )
                    if client_id:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                        )
            # Уведомляем администраторов
            await self._notify_admins_about_delivery(context, update.effective_user.first_name, request_id)
            return ENTER_CONFIRMATION_CODE
        except Exception:
            await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    @log_method_call
    async def _update_delivery_task_status(self, request_id, status):
        """Обновление статуса задачи доставки"""
        delivery_tasks = await load_delivery_tasks()
        for _, task in delivery_tasks.items():
            if task.get('request_id') == request_id:
                task['status'] = status
                break
        await save_delivery_tasks(delivery_tasks)

    @log_method_call
    async def _notify_client_about_delivery(self, context, client_id, request_id, requests_data):
        """Уведомление клиента о прибытии доставщика с товаром"""
        await context.bot.send_message(
            chat_id=int(client_id),
            text=f"🚚 Доставщик прибыл с вашим устройством и скоро передаст его вам.\n"
                f"Адрес доставки: {requests_data[request_id].get('location_display', 'указанный в заявке')}"
        )
        # Отправляем фотографии товара, если они есть
        photos = requests_data[request_id].get('sc_pickup_photos', [])
        for photo_path in photos:
            if os.path.exists(photo_path):
                with open(photo_path, 'rb') as photo_file:
                    await context.bot.send_photo(
                        chat_id=int(client_id),
                        photo=photo_file,
                        caption=f"Фото вашего устройства после ремонта"
                    )

    @log_method_call
    async def _notify_admins_about_delivery(self, context, delivery_name, request_id):
        """Уведомление администраторов о начале доставки клиенту"""
        admin_message = (
            f"🚚 Доставщик {delivery_name} прибыл к клиенту для передачи товара\n"
            f"Заявка: #{request_id}\n"
            f"Статус: {ORDER_STATUS_SC_TO_CLIENT}"
        )
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=int(admin_id),
                text=admin_message
            )

    @log_method_call
    async def _send_sms_confirmation(self, context, client_data, request_id, confirmation_code, requests_data):
        """Отправка SMS с кодом подтверждения клиенту"""
        try:
            # Определяем режим работы (тестовый или боевой)
            if DEBUG:
                # В тестовом режиме отправляем код ДОСТАВЩИКУ, а клиент его вводит
                delivery_id = requests_data[request_id].get('assigned_delivery')
                if delivery_id:
                    await context.bot.send_message(
                        chat_id=delivery_id,
                        text=f"Ваш код подтверждения для заявки #{request_id}: {confirmation_code}\n\nПродиктуйте его клиенту для подтверждения."
                    )
                    # Сообщаем клиенту, что нужно ввести код от доставщика
                    await context.bot.send_message(
                        chat_id=client_data['user_id'],
                        text=f"Доставщик получит код подтверждения. Пожалуйста, введите код, который вам сообщит доставщик:"
                    )
                return True
            else:
                # В боевом режиме отправляем SMS с кодом КЛИЕНТУ
                if 'phone' in client_data and client_data['phone']:
                    try:
                        phone = client_data['phone'].replace('+', '')
                        # Инициализируем SMS-клиент
                        sms_client = SMSBY(SMS_TOKEN, 'by')
                        # Получаем список существующих объектов пароля
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
                            raise Exception("Нет доступных объектов пароля для отправки SMS")
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
                                    chat_id=client_data['user_id'],
                                    text=f"📲 Вам отправлен SMS с кодом подтверждения. Пожалуйста, введите его здесь:"
                                )
                                # Уведомляем ДОСТАВЩИКА, что нужно ждать подтверждения
                                delivery_id = requests_data[request_id].get('assigned_delivery')
                                if delivery_id:
                                    await context.bot.send_message(
                                        chat_id=delivery_id,
                                        text=f"🕒 Ожидайте, пока клиент введёт код подтверждения из SMS."
                                    )
                                return True
                            else:
                                raise Exception("Не удалось отправить SMS")
                        else:
                            raise Exception("Нет доступных альфа-имен для отправки SMS")
                    except Exception:
                        # Если SMS не удалось отправить, используем код из интерфейса
                        await context.bot.send_message(
                            chat_id=client_data['user_id'],
                            text=f"Не удалось отправить SMS с кодом подтверждения. Используйте код: {confirmation_code}\n\nПожалуйста, введите его здесь:"
                        )
                        # Уведомляем доставщика, что клиент будет вводить код
                        delivery_id = requests_data[request_id].get('assigned_delivery')
                        if delivery_id:
                            await context.bot.send_message(
                                chat_id=delivery_id,
                                text=f"🕒 Ожидайте, пока клиент введёт код подтверждения."
                            )
                        return True
                else:
                    # У клиента нет телефона, используем код из интерфейса
                    await context.bot.send_message(
                        chat_id=client_data['user_id'],
                        text=f"Ваш код подтверждения: {confirmation_code}\n\nПожалуйста, введите его здесь:"
                    )
                    # Уведомляем доставщика, что клиент будет вводить код
                    delivery_id = requests_data[request_id].get('assigned_delivery')
                    if delivery_id:
                        await context.bot.send_message(
                            chat_id=delivery_id,
                            text=f"🕒 Ожидайте, пока клиент введёт код подтверждения."
                        )
                    return True
        except Exception:
            # При ошибке возвращаем False, чтобы использовать код вручную
            return False

    @log_method_call
    async def _create_payment(self, request_id: str, amount: float, description: str) -> dict:
        """Создание платежа через API"""
        payment_data = {
            'amount': amount,
            'description': description
        }
        try:
            async with aiohttp.ClientSession() as session:
                payment_request_data = {'payment_request': json.dumps(payment_data)}
                async with session.post(
                    PAYMENT_API_URL,
                    data=payment_request_data,
                    timeout=10
                ) as response:
                    status = response.status
                    if status != 200:
                        response_text = await response.text()
                        raise Exception(f"HTTP error {status}: {response_text}")
                    # Получаем заголовки ответа
                    content_type = response.headers.get('Content-Type', 'unknown')
                    # Логируем ответ для отладки
                    response_body = await response.text()
                    # Пытаемся разобрать JSON
                    try:
                        result = json.loads(response_body)
                    except json.JSONDecodeError as e:
                        raise Exception(f"Ошибка формата ответа: {e}")
                    # Проверяем ожидаемые поля
                    if not result.get('order_id') or not result.get('payment_url'):
                        raise Exception(f"Invalid API response: {result}")
                    return result
        except Exception as e:
            logger.error(f"❌ Ошибка при создании платежа: {str(e)}")
            raise

    @log_method_call
    async def handle_client_confirmation_code(self, update: Update, context: CallbackContext):
        """Проверка кода подтверждения от клиента и создание платежа если необходимо"""
        try:
            entered_code = update.message.text.strip()
            request_id = context.user_data.get('current_request')
            if not request_id:
                await update.message.reply_text("❌ Не найдена активная заявка.")
                return ConversationHandler.END
            # Загружаем данные
            requests_data = await load_requests()
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
            request = requests_data[request_id]
            client_id = str(request.get('user_id'))  # Преобразуем в строку
            expected_code = request.get('confirmation_code')
            # Проверяем, кто вводит код - клиент или доставщик
            user_id = str(update.effective_user.id)
            # Если код вводит клиент
            if client_id and user_id == client_id:
                if entered_code == expected_code:
                    # Рассчитываем оставшуюся сумму к оплате
                    final_price = Decimal(request.get('final_price', '0'))
                    repair_price = Decimal(request.get('repair_price', '0'))
                    delivery_cost = Decimal('20') + (repair_price * Decimal('0.3'))
                    amount_to_pay = final_price - delivery_cost + Decimal('20') if final_price > delivery_cost else Decimal('0')
                    if amount_to_pay > Decimal('0'):
                        try:
                            # Создаем платеж
                            result = await self._create_payment(
                                request_id=request_id,
                                amount=float(amount_to_pay),
                                description=f"Оплата ремонта по заявке #{request_id}"
                            )
                            # Сохраняем данные платежа
                            request['final_payment_order_id'] = result['order_id']
                            await save_requests(requests_data)
                            # Отправляем кнопку оплаты клиенту
                            keyboard = [
                                [InlineKeyboardButton("✅ Оплатить", url=result['payment_url'])],
                                [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_final_payment_{request_id}")],
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"💳 Пожалуйста, оплатите оставшуюся сумму: {amount_to_pay:.2f} BYN\n"
                                    f"После оплаты нажмите кнопку 'Проверить оплату'",
                                reply_markup=reply_markup
                            )
                            # Уведомляем доставщика
                            delivery_id = request.get('assigned_delivery')
                            if delivery_id:
                                await context.bot.send_message(
                                    chat_id=int(delivery_id),
                                    text=f"🔄 Клиент подтвердил получение и должен оплатить {amount_to_pay:.2f} BYN. Ожидайте завершения оплаты."
                                )
                            return WAITING_FINAL_PAYMENT
                        except Exception as e:
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"❌ Не удалось создать платеж: {str(e)}"
                            )
                            return ConversationHandler.END
                    else:
                        # Если оплата не требуется, запрашиваем фотографии у доставщика
                        return await self._request_delivery_photos(update, context, request_id, request)
                else:
                    await update.message.reply_text("❌ Неверный код подтверждения. Попробуйте еще раз.")
                    return ENTER_CONFIRMATION_CODE
            else:
                await update.message.reply_text("❌ Только клиент может ввести код подтверждения.")
                return ENTER_CONFIRMATION_CODE
        except Exception as e:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    @log_method_call
    async def _request_delivery_photos(self, update, context, request_id, request):
        """Запрос фотографий у доставщика после подтверждения клиентом"""
        delivery_id = request.get('assigned_delivery')
        # Уведомляем клиента об успешном подтверждении
        await update.message.reply_text(
            "✅ Код подтверждения верный! Доставщик сделает фотографии передачи товара."
        )
        # Уведомляем доставщика о необходимости сделать фотографии
        if delivery_id:
            await context.bot.send_message(
                chat_id=int(delivery_id),
                text="✅ Клиент подтвердил получение. Сделайте фотографии передачи товара и отправьте их."
            )
        context.user_data['awaiting_delivery_photos'] = True
        return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def check_final_payment(self, update: Update, context: CallbackContext):
        """Проверка финальной оплаты клиентом"""
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            logger.info(f"📊 Проверка статуса финального платежа для заявки #{request_id}")
            requests_data = await load_requests()
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
            # Проверяем статус платежа
            status_data = {'payment_status_order_id': order_id}
            logger.info(f"📤 Отправляем запрос статуса финального платежа: {status_data}")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PAYMENT_API_URL,
                    data=status_data,
                    timeout=10
                ) as response:
                    status = response.status
                    # Получаем текстовый ответ
                    response_text = await response.text()
                    # Изучаем заголовки ответа
                    content_type = response.headers.get('Content-Type', 'unknown')
                    if status != 200:
                        raise Exception(f"HTTP error {status}: {response_text}")
                    # Пытаемся разобрать JSON, независимо от Content-Type
                    try:
                        result = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        raise Exception(f"Ошибка формата ответа при проверке платежа: {e}")
                    # Проверяем ожидаемые поля в ответе
                    logger.info(f"🔑 Ключи в ответе: {list(result.keys())}")
                    # Проверяем статус платежа по информации от банка
                    if (result.get('errorCode') == '0' and 
                        result.get('orderStatus') == 2 and 
                        result.get('paymentAmountInfo', {}).get('paymentState') == 'DEPOSITED'):
                        # Платеж успешен
                        request['status'] = "Доставлено клиенту"
                        request['payment_status'] = "paid"
                        await save_requests(requests_data)
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
                        # Платеж не завершен или отклонен
                        error_message = result.get('errorMessage', 'Неизвестная ошибка')
                        payment_state = result.get('paymentAmountInfo', {}).get('paymentState', 'Неизвестно')
                        order_status = result.get('orderStatus', 'Неизвестно')
                        status_message = f"Статус: {payment_state}, Код: {order_status}, Сообщение: {error_message}"
                        # Формируем новое сообщение с обновленными кнопками
                        new_message = (
                            f"⏳ Платеж не завершен: {error_message}\n"
                            f"Статус: {payment_state}, Код: {order_status}\n\n"
                            "Возможно, операция еще обрабатывается. Проверьте еще раз через несколько секунд."
                        )
                        keyboard = [
                            [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_final_payment_{request_id}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        # Проверяем, изменилось ли содержимое сообщения
                        current_text = query.message.text if query.message.text else ""
                        current_markup = query.message.reply_markup if query.message.reply_markup else InlineKeyboardMarkup([])
                        if current_text != new_message or current_markup != reply_markup:
                            try:
                                await query.edit_message_text(new_message, reply_markup=reply_markup)
                            except Exception:
                                # Если не удалось отредактировать, отправляем новое
                                await context.bot.send_message(
                                    chat_id=query.message.chat_id,
                                    text=new_message,
                                    reply_markup=reply_markup
                                )
                        else:
                            # Отправляем уведомление пользователю
                            await context.bot.answer_callback_query(
                                callback_query_id=query.id,
                                text="Статус платежа не изменился. Попробуйте проверить позже."
                            )
                        return WAITING_FINAL_PAYMENT
        except Exception:
            error_message = f"❌ Ошибка при проверке финального платежа: {str(e)}"
            logger.error(error_message)
            logger.exception(e)  # Выводим полный стектрейс
            # Формируем сообщение об ошибке
            keyboard = [
                [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_final_payment_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(
                    f"❌ Ошибка при проверке платежа: {str(e)}",
                    reply_markup=reply_markup
                )
            except Exception as edit_error:
                # Если не удалось отредактировать, отправляем новое
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Ошибка при проверке платежа: {str(e)}",
                    reply_markup=reply_markup
                )
            return WAITING_FINAL_PAYMENT

    @log_method_call
    async def cancel_final_payment(self, update: Update, context: CallbackContext):
        """Обработка отмены финального платежа"""
        query = update.callback_query
        await query.answer()
        try:
            request_id = query.data.split('_')[-1]
            delivery_id = None
            # Загружаем данные заявки
            requests_data = await load_requests()
            if request_id in requests_data:
                request = requests_data[request_id]
                delivery_id = request.get('assigned_delivery')
            # Сообщаем клиенту об отмене
            await query.edit_message_text(
                "❌ Оплата отменена. Вы можете оплатить заказ наличными доставщику."
            )
            # Уведомляем доставщика
            if delivery_id:
                await context.bot.send_message(
                    chat_id=int(delivery_id),
                    text=f"⚠️ Клиент отменил онлайн-оплату для заявки #{request_id}. Возможно, клиент предпочитает оплатить наличными."
                )
            return ConversationHandler.END
        except Exception:
            await query.edit_message_text("❌ Произошла ошибка при отмене платежа.")
            return ConversationHandler.END

    @log_method_call
    async def handle_delivery_photo(self, update: Update, context: CallbackContext):
        """Обработка фотографий при доставке клиенту"""
        try:
            # Инициализируем список для фотографий, если его нет
            if 'delivery_photos' not in context.user_data:
                context.user_data['delivery_photos'] = []
            photo = update.message.photo[-1]  # Берем самое большое изображение
            file = await context.bot.get_file(photo.file_id)
            # Путь для сохранения фото
            request_id = context.user_data.get('current_request')
            photo_filename = f"delivery_to_client_{request_id}_{len(context.user_data['delivery_photos'])}.jpg"
            photo_path = os.path.join("photos", photo_filename)
            # Скачиваем фото
            await file.download_to_drive(photo_path)
            context.user_data['delivery_photos'].append(photo_path)
            # Уведомляем доставщика
            await update.message.reply_text(
                f"✅ Фото #{len(context.user_data['delivery_photos'])} сохранено!\n\n"
                f"Отправьте еще фотографии или нажмите\n\n/DONE"
            )
            return CREATE_REQUEST_PHOTOS
        except Exception:
            await update.message.reply_text("❌ Произошла ошибка при сохранении фото. Попробуйте еще раз.")
            return CREATE_REQUEST_PHOTOS

    @log_method_call
    async def handle_delivery_photos_done(self, update: Update, context: CallbackContext):
        """Завершение процесса доставки после отправки фотографий"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('delivery_photos', [])
            if not photos:
                await update.message.reply_text("❌ Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            # Загружаем данные
            requests_data = await load_requests()
            delivery_tasks = await load_delivery_tasks()
            if request_id not in requests_data:
                await update.message.reply_text("❌ Заявка не найдена.")
                return ConversationHandler.END
            # Обновляем статус и сохраняем фотографии
            request = requests_data[request_id]
            request['status'] = "Доставлено клиенту"
            request['delivery_photos'] = photos
            await save_requests(requests_data)
            # Обновляем статус задачи доставки
            for _, task in delivery_tasks.items():
                if task.get('request_id') == request_id:
                    task['status'] = "Завершено"
                    await save_delivery_tasks(delivery_tasks)
                    break
            # Отправляем уведомления всем участникам
            await self._send_completion_notifications(update, context, request_id, photos)
            # Очищаем контекст
            context.user_data.pop('current_request', None)
            context.user_data.pop('delivery_photos', None)
            context.user_data.pop('awaiting_delivery_photos', None)
            return ConversationHandler.END
        except Exception:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return ConversationHandler.END

    @log_method_call
    async def _send_completion_notifications(self, update, context, request_id, photos):
        """Отправка уведомлений о завершении доставки всем участникам"""
        # Загружаем данные
        requests_data = await load_requests()
        if request_id not in requests_data:
            return
        request = requests_data[request_id]
        client_id = request.get('user_id')
        # Сообщение для администраторов
        admin_message = (
            f"✅ Доставка завершена!\n"
            f"Заявка: #{request_id}\n"
            f"Доставщик: {update.effective_user.first_name}\n\n"
            f"Фотографии передачи товара:"
        )
        # Отправляем уведомления администраторам
        for admin_id in ADMIN_IDS:
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
        # Уведомляем клиента
        if client_id:
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
        # Уведомляем доставщика
        await update.message.reply_text(
            "✅ Доставка успешно завершена! Фотографии отправлены администраторам.\n\n"
            "Спасибо за вашу работу!",
            reply_markup=ReplyKeyboardRemove()
        )
