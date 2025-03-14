import json
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import ADMIN_IDS, ENTER_NAME, ENTER_PHONE, DELIVERY_MENU
from handlers.base_handler import BaseHandler
from database import load_delivery_tasks, load_users, load_requests, save_delivery_tasks, save_requests, save_users
from utils import notify_client
import logging

logger = logging.getLogger(__name__)


class DeliveryHandler(BaseHandler):

    async def show_delivery_profile(self, update: Update, context: CallbackContext):
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
        user_id = str(update.effective_user.id)
        phone = update.message.text
        
        users_data = load_users()
        users_data[user_id]['phone'] = phone
        save_users(users_data)
        
        await update.message.reply_text("Спасибо. Ваш профиль обновлен.")
        return await self.show_delivery_profile(update, context)


    async def show_delivery_tasks(self, update: Update, context: CallbackContext):
        delivery_id = str(update.effective_user.id)
        delivery_tasks = load_delivery_tasks()
        
        my_tasks = [task for task in delivery_tasks 
                    if isinstance(task, dict) and 
                    str(task.get('assigned_delivery_id')) == delivery_id]

        if not my_tasks:
            await update.message.reply_text("У вас пока нет активных заданий.")
            return

        for task in my_tasks:
            status = task.get('status', 'Статус не указан')
            request_id = task.get('request_id', 'Не указан')
            sc_name = task.get('sc_name', 'Не указан')
            
            keyboard = []
            
            # Добавляем кнопки в зависимости от статуса задачи
            if status == 'Доставщик в пути к клиенту':
                keyboard.append([InlineKeyboardButton(
                    "Подтвердить получение", 
                    callback_data=f"confirm_pickup_{request_id}"
                )])
            elif status == 'Доставщик везет в СЦ':
                keyboard.append([InlineKeyboardButton(
                    "Доставлено в СЦ", 
                    callback_data=f"delivered_to_sc_{request_id}"
                )])
                
            message = f"Задача доставки #{request_id}\n"
            message += f"Статус: {status}\n"
            message += f"Сервисный центр: {sc_name}\n"
            
            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message)


    async def handle_task_callback(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()

        task_id = query.data.split('_')[-1]
        # Здесь вы можете загрузить детали задачи и отобразить их
        task_details = f"Детали задачи №{task_id}\n..."  # Замените это на реальные данные
        await query.edit_message_text(text=task_details)


    async def accept_delivery(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
    
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
    
        if request_id in requests_data:
            requests_data[request_id]['status'] = 'Доставщик в пути к клиенту'
            requests_data[request_id]['assigned_delivery'] = str(query.from_user.id)
            save_requests(requests_data)
    
            # Обновляем задачу доставки
            for task in delivery_tasks:
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = 'Доставщик в пути к клиенту'
                    task['assigned_delivery_id'] = str(query.from_user.id)
                    break
            save_delivery_tasks(delivery_tasks)
    
            # Получаем координаты клиента
            latitude = requests_data[request_id].get('latitude')
            longitude = requests_data[request_id].get('longitude')
    
            # Создаем кнопки
            keyboard = [
                [InlineKeyboardButton("Подтвердить получение", callback_data=f"confirm_pickup_{request_id}")]
            ]
    
            # Добавляем кнопку с ссылкой на Яндекс.Карты, если координаты доступны
            if latitude and longitude:
                map_url = f"https://yandex.ru/maps?rtext=~{latitude}%2C{longitude}&rtt=auto"
                keyboard.append([InlineKeyboardButton("Открыть карту", url=map_url)])
    
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
            admin_message += f"Статус: Доставщик в пути к клиенту"
    
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    print(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
    
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")


    async def handle_confirm_pickup(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        
        if request_id in requests_data:
            # Обновляем статус заявки
            requests_data[request_id]['status'] = 'Ожидает подтверждения клиента'
            save_requests(requests_data)
            
            # Обновляем задачу доставки
            for task in delivery_tasks:
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = 'Ожидает подтверждения клиента'
                    break
            save_delivery_tasks(delivery_tasks)
            
            # Уведомляем клиента
            client_id = requests_data[request_id].get('user_id')  # Изменено с 'client_id' на 'user_id'
            if client_id:
                keyboard = [
                    [InlineKeyboardButton("Да, забрал", callback_data=f"client_confirm_{request_id}")],
                    [InlineKeyboardButton("Нет, не забрал", callback_data=f"client_deny_{request_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                try:
                    await context.bot.send_message(
                        chat_id=client_id,
                        text=f"Доставщик сообщает, что забрал ваш предмет по заявке №{request_id}. Подтверждаете?",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    print(f"Ошибка при отправке сообщения клиенту: {e}")
            else:
                print(f"ID клиента не найден для заявки {request_id}")
            
            await query.edit_message_text(
                f"Вы подтвердили получение предмета по заявке №{request_id}. Ожидаем подтверждения клиента."
            )
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")


    async def handle_client_confirmation(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        
        try:
            action, request_id = query.data.split('_')[1:]
            requests_data = load_requests()
            delivery_tasks = load_delivery_tasks()
            
            if request_id in requests_data:
                if action == 'confirm':
                    new_status = 'Доставщик везет в СЦ'
                    message = f"Клиент подтвердил получение. Вы можете везти предмет в СЦ по заявке №{request_id}."
                else:
                    new_status = 'Ошибка подтверждения'
                    message = f"Клиент не подтвердил получение предмета по заявке №{request_id}. Свяжитесь с клиентом для уточнения."
                
                requests_data[request_id]['status'] = new_status
                save_requests(requests_data)
                
                # Обновляем задачу доставки
                updated_tasks = []
                for task in delivery_tasks:
                    if isinstance(task, dict) and task.get('request_id') == request_id:
                        task['status'] = new_status
                    updated_tasks.append(task)
                save_delivery_tasks(updated_tasks)
                
                # Уведомляем доставщика
                delivery_id = requests_data[request_id].get('assigned_delivery')
                if delivery_id:
                    await context.bot.send_message(chat_id=delivery_id, text=message)
                
                await query.edit_message_text(
                    f"Спасибо за подтверждение. Статус заявки №{request_id}: {new_status}"
                )
            else:
                await query.edit_message_text("Произошла ошибка. Заявка не найдена.")
        except Exception as e:
            await query.edit_message_text("Произошла ошибка при обработке подтверждения.")


    async def handle_delivered_to_sc(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        
        if request_id in requests_data:
            requests_data[request_id]['status'] = 'В Сервисном Центре'
            save_requests(requests_data)
            
            await query.edit_message_text(f"Отличная работа! Заказ №{request_id} отдан в Сервисный Центр.")
            
            # Уведомляем клиента
            client_id = requests_data[request_id]['user_id']
            await notify_client(context.bot, client_id, f"Ваш предмет ремонта находится в Сервисном Центре. Ожидайте обратной связи!")
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")


    async def update_delivery_messages(self, bot: Bot, task_id: int, task_data: dict):
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
        logger.info("Вызван метод show_my_tasks")
        
        try:
            delivery_id = str(update.effective_user.id)
            
            with open('delivery_tasks.json', 'r', encoding='utf-8') as f:
                delivery_tasks = json.load(f)
            
            my_tasks = {
                task_id: task for task_id, task in delivery_tasks.items()
                if str(task.get('assigned_delivery_id')) == delivery_id
            }
            
            if not my_tasks:
                await update.message.reply_text("У вас пока нет активных заданий.")
                return
            
            for task_id, task in my_tasks.items():
                status = task.get('status', 'Статус не указан')
                keyboard = []
                
                if status == 'Доставщик в пути к клиенту':
                    keyboard.append([InlineKeyboardButton(
                        "Подтвердить получение", 
                        callback_data=f"confirm_pickup_{task['request_id']}"
                    )])
                elif status == 'Доставщик везет в СЦ':
                    keyboard.append([InlineKeyboardButton(
                        "Доставлено в СЦ", 
                        callback_data=f"delivered_to_sc_{task['request_id']}"
                    )])
                
                message = (
                    f"📦 Задача доставки #{task_id}\n"
                    f"Статус: {status}\n"
                    f"Сервисный центр: {task['sc_name']}\n"
                    f"Адрес клиента: {task['client_address']}\n"
                    f"Клиент: {task['client_name']}\n"
                    f"Телефон: {task['client_phone']}\n"
                    f"Описание: {task['description'][:100]}..."
                )
                
                if keyboard:
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(message, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(message)
                
        except Exception as e:
            logger.error(f"Ошибка при показе моих заданий: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заданий.")
