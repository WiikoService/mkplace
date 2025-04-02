from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    ENTER_CONFIRMATION_CODE
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

logger = logging.getLogger(__name__)

class DeliverySCHandler(DeliveryHandler):
    """Обработчик для доставки из СЦ"""

    async def handle_pickup_from_sc(self, update: Update, context: CallbackContext):
        """Обработка подтверждения забора товара из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            # Обновляем статус в заявке
            request = requests_data.get(request_id)
            if request:
                request['status'] = ORDER_STATUS_SC_TO_CLIENT
                save_requests(requests_data)
            # Обновляем статус в задаче доставки
            for task in delivery_tasks.values():
                if task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_SC_TO_CLIENT
                    save_delivery_tasks(delivery_tasks)
                    break
            await query.edit_message_text(
                "✅ Статус обновлен. Теперь доставьте товар клиенту."
            )
        except Exception as e:
            logger.error(f"Ошибка при обработке забора из СЦ: {e}")
            await query.edit_message_text("Произошла ошибка при обновлении статуса")

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

    async def handle_sc_pickup_photo(self, update: Update, context: CallbackContext):
        """Обработка фото при заборе из СЦ"""
        if 'photos_from_sc' not in context.user_data:
            context.user_data['photos_from_sc'] = []
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_path = f"photos/from_sc_{len(context.user_data['photos_from_sc'])}_{context.user_data['current_request']}.jpg"
        await photo_file.download_to_drive(photo_path)
        context.user_data['photos_from_sc'].append(photo_path)
        await update.message.reply_text("Фото добавлено. Отправьте /done когда закончите.")
        return CREATE_REQUEST_PHOTOS

    async def handle_sc_pickup_photos_done(self, update: Update, context: CallbackContext):
        """Завершение добавления фото при заборе из СЦ"""
        try:
            request_id = context.user_data.get('current_request')
            photos = context.user_data.get('photos_from_sc', [])
            if not photos:
                await update.message.reply_text("Необходимо добавить хотя бы одно фото!")
                return CREATE_REQUEST_PHOTOS
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            # Обновляем статус и сохраняем фото
            requests_data[request_id].update({
                'status': ORDER_STATUS_SC_TO_CLIENT,
                'sc_pickup_photos': photos
            })
            save_requests(requests_data)
            # Обновляем статус в delivery_tasks
            for task in delivery_tasks.values():
                if task.get('request_id') == request_id:
                    task['status'] = ORDER_STATUS_SC_TO_CLIENT
                    break
            save_delivery_tasks(delivery_tasks)
            # Уведомляем клиента
            client_id = requests_data[request_id].get('user_id')
            if client_id:
                await notify_client(
                    context.bot,
                    client_id,
                    "Доставщик забрал ваш товар из СЦ и направляется к вам."
                )
            keyboard = [[
                InlineKeyboardButton(
                    "✅ Доставлено клиенту",
                    callback_data=f"delivered_to_client_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ Товар получен из СЦ. Теперь доставьте его клиенту.",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при завершении фотографирования из СЦ: {e}")
            await update.message.reply_text("Произошла ошибка при обработке фотографий")
            return ConversationHandler.END

    async def handle_sc_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения получения товара из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            # Находим задачу доставки
            task = None
            for t in delivery_tasks.values():
                if t.get('request_id') == request_id and t.get('is_sc_to_client'):
                    task = t
                    break
            if not task:
                await query.edit_message_text("❌ Задача доставки не найдена")
                return ConversationHandler.END
            # Генерируем код подтверждения
            confirmation_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
            context.user_data['confirmation_code'] = confirmation_code
            context.user_data['current_request'] = request_id
            # Отправляем код СЦ
            sc_id = requests_data[request_id].get('assigned_sc')
            users_data = load_users()
            sc_user_id = None
            for user_id, user_data in users_data.items():
                if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                    sc_user_id = user_id
                    break
            if sc_user_id:
                await context.bot.send_message(
                    chat_id=sc_user_id,
                    text=f"Код подтверждения для передачи товара доставщику: {confirmation_code}"
                )
                await query.edit_message_text(
                    "Введите код подтверждения, полученный от СЦ:"
                )
                return ENTER_CONFIRMATION_CODE
            else:
                await query.edit_message_text("❌ Не удалось отправить код подтверждения СЦ")
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при подтверждении получения из СЦ: {e}")
            await query.edit_message_text("Произошла ошибка при обработке подтверждения")
            return ConversationHandler.END

    async def handle_accept_sc_delivery(self, update: Update, context: CallbackContext):
        """Обработка принятия доставки из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        delivery_id = str(update.effective_user.id)
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            # Находим задачу доставки
            task = None
            task_id = None
            for t_id, t_data in delivery_tasks.items():
                if (t_data.get('request_id') == request_id and 
                    t_data.get('delivery_type') == 'sc_to_client'):
                    task = t_data
                    task_id = t_id
                    break
            if task.get('assigned_delivery_id'):
                await query.edit_message_text("❌ Заказ уже принят другим доставщиком")
                return ConversationHandler.END
            task.update({
                'assigned_delivery_id': delivery_id,
                'status': 'Принят доставщиком',
                'accepted_at': int(time.time())
            })
            delivery_tasks[task_id] = task
            save_delivery_tasks(delivery_tasks)
            request = requests_data.get(request_id)
            if request:
                request.update({
                    'status': 'Принят доставщиком',
                    'assigned_delivery': delivery_id
                })
                save_requests(requests_data)
            # Создаем клавиатуру с кнопкой для получения кода подтверждения
            keyboard = [[
                InlineKeyboardButton(
                    "🔄 Забрать заказ",
                    callback_data=f"get_sc_confirmation_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)            
            await query.edit_message_text(
                f"✅ Вы приняли заказ #{request_id} для доставки из СЦ.\n"
                "Нажмите кнопку 'Забрать заказ', когда будете готовы получить код подтверждения:",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при принятии доставки из СЦ: {e}")
            await query.edit_message_text("❌ Произошла ошибка при принятии заказа")
            return ConversationHandler.END

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

    async def handle_sc_pickup_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения получения товара из СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        try:
            requests_data = load_requests()
            # Генерируем код подтверждения
            confirmation_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
            context.user_data['sc_confirmation_code'] = confirmation_code
            context.user_data['current_request'] = request_id
            # Отправляем код СЦ
            request = requests_data.get(request_id)
            sc_id = request.get('assigned_sc')
            users_data = load_users()
            for user_id, user_data in users_data.items():
                if user_data.get('role') == 'sc' and user_data.get('sc_id') == sc_id:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=f"Код подтверждения для передачи товара доставщику: {confirmation_code}"
                    )
                    break
            await query.edit_message_text(
                "Введите код подтверждения, полученный от СЦ:"
            )
            return ENTER_SC_CONFIRMATION_CODE
        except Exception as e:
            logger.error(f"Ошибка при подтверждении получения из СЦ: {e}")
            await query.edit_message_text("Произошла ошибка при обработке подтверждения")
            return ConversationHandler.END

    async def check_sc_confirmation_code(self, update: Update, context: CallbackContext):
        """Проверка кода подтверждения от СЦ"""
        entered_code = update.message.text.strip()
        request_id = context.user_data.get('current_request')
        correct_code = context.user_data.get('sc_confirmation_code')
        if entered_code != correct_code:
            await update.message.reply_text("❌ Неверный код. Попробуйте еще раз:")
            return ENTER_SC_CONFIRMATION_CODE
        try:
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            # Обновляем статусы
            request = requests_data.get(request_id)
            if request:
                request['status'] = 'Доставщик забрал из СЦ'
                save_requests(requests_data)
            # Находим и обновляем задачу доставки
            for task in delivery_tasks.values():
                if (task.get('request_id') == request_id and 
                    task.get('delivery_type') == 'sc_to_client'):
                    task['status'] = 'Доставщик забрал из СЦ'
                    break
            save_delivery_tasks(delivery_tasks)
            await update.message.reply_text(
                "✅ Код подтвержден. Сделайте фото товара для подтверждения получения."
            )
            # Очищаем данные подтверждения
            if 'sc_confirmation_code' in context.user_data:
                del context.user_data['sc_confirmation_code']
            return CREATE_REQUEST_PHOTOS
        except Exception as e:
            logger.error(f"Ошибка при проверке кода подтверждения СЦ: {e}")
            await update.message.reply_text("Произошла ошибка при проверке кода")
            return ConversationHandler.END
