import json
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from telegram.error import BadRequest
from .base_handler import BaseHandler
from database import load_delivery_tasks, load_requests, load_service_centers, load_users, save_delivery_tasks, save_requests
from config import ASSIGN_REQUEST, ADMIN_IDS, DELIVERY_IDS
from utils import notify_admin, notify_delivery
logger = logging.getLogger(__name__)

class AdminHandler(BaseHandler):


    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
    
        logger.info(f"Received callback query: {query.data}")
    
        parts = query.data.split('_')
        if len(parts) < 3:
            logger.error(f"Invalid data format: {query.data}")
            await query.edit_message_text("Неверный формат данных")
            return
    
        request_id = parts[2]
    
        requests_data = load_requests()
        service_centers = load_service_centers()
    
        if request_id not in requests_data:
            logger.error(f"Request {request_id} not found")
            await query.edit_message_text(f"Заявка #{request_id} не найдена")
            return
    
        # Создаем клавиатуру с доступными сервисными центрами
        keyboard = []
        for sc in service_centers:
            keyboard.append([InlineKeyboardButton(sc['name'], callback_data=f"assign_sc_confirm_{request_id}_{sc['id']}")])
    
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Выберите сервисный центр для заявки #{request_id}:",
            reply_markup=reply_markup
        )


    async def handle_assign_sc_confirm(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()

        logger.info(f"Received callback query: {query.data}")

        parts = query.data.split('_')
        if len(parts) < 5:  # Проверяем, что есть все необходимые части
            logger.error(f"Invalid data format: {query.data}")
            await query.edit_message_text("Неверный формат данных")
            return

        request_id = parts[3]  # Изменено с parts[2] на parts[3]
        sc_id = parts[4]      # Изменено с parts[3] на parts[4]

        requests_data = load_requests()
        service_centers = load_service_centers()

        if request_id not in requests_data:
            logger.error(f"Request {request_id} not found")
            await query.edit_message_text(f"Заявка #{request_id} не найдена")
            return
    
        sc_name = next((sc['name'] for sc in service_centers if str(sc['id']) == str(sc_id)), None)
        if not sc_name:
            logger.error(f"Service center {sc_id} not found")
            await query.edit_message_text(f"Сервисный центр с ID {sc_id} не найден")
            return
    
        requests_data[request_id]['assigned_sc'] = sc_id
        requests_data[request_id]['status'] = 'Привязан к СЦ'
        save_requests(requests_data)
    
        new_text = f"Заявка #{request_id} привязана к СЦ {sc_name}."
        await query.edit_message_text(new_text)
    
        # Создаем задачу доставки
        await self.create_delivery_task(update, context, request_id, sc_name)
    
        logger.info(f"Request {request_id} successfully assigned to SC {sc_id}")


    async def update_delivery_info(self, context: CallbackContext, chat_id: int, message_id: int, request_id: str, delivery_info: dict):
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
        delivery_tasks = load_delivery_tasks()
        task_id = str(len(delivery_tasks) + 1)
        
        requests_data = load_requests()
        request = requests_data.get(request_id, {})
        
        delivery_task = {
            'task_id': task_id,
            'request_id': request_id,
            'status': 'Ожидает',
            'sc_name': sc_name,
            'client_address': request.get('location', 'Адрес не указан'),
            'client_name': request.get('name', 'Имя не указано'),
            'client_phone': request.get('phone', 'Телефон не указан'),
            'description': request.get('description', 'Описание отсутствует')
        }
        
        delivery_tasks[task_id] = delivery_task
        save_delivery_tasks(delivery_tasks)
        
        try:
            await self.notify_delivery(context.bot, task_id, delivery_task)
            logger.info(f"Delivery task {task_id} created and notified successfully")
        except Exception as e:
            logger.error(f"Failed to notify delivery for task {task_id}: {e}")
        
        return task_id


    async def notify_delivery(self, bot: Bot, task_id: str, task_data: dict):
        keyboard = [
            [InlineKeyboardButton("Принять", callback_data=f"accept_delivery_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for delivery_id in DELIVERY_IDS:
            message = f"Новая задача доставки #{task_id}\n"
            message += f"Заявка: #{task_data['request_id']}\n"
            message += f"СЦ: {task_data['sc_name']}\n"
            message += f"Статус: {task_data['status']}"
            await bot.send_message(chat_id=delivery_id, text=message, reply_markup=reply_markup)


    async def handle_accept_delivery(self, update: Update, context: CallbackContext):
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
                
                # Находим оригинальное сообщение о заявке и обновляем его
                for admin_id in ADMIN_IDS:
                    try:
                        # Предполагаем, что message_id сохранен в request
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
        await update.message.reply_text("Введите номер заявки для привязки к СЦ:")
        return ASSIGN_REQUEST


    async def handle_assign_request(self, update: Update, context: CallbackContext):
        request_id = update.message.text.strip()
        
        requests_data = load_requests()
        if request_id in requests_data:
            service_centers = load_service_centers()
            keyboard = []
            for sc in service_centers:
                keyboard.append([InlineKeyboardButton(sc['name'], 
                               callback_data=f"assign_sc_{request_id}_{sc['id']}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Выберите сервисный центр для заявки #{request_id}:", 
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(f"Заявка #{request_id} не найдена")
        
        return ConversationHandler.END


    async def view_service_centers(self, update: Update, context: CallbackContext):
        service_centers = load_service_centers()
        if not service_centers:
            await update.message.reply_text("Список СЦ пуст.")
        else:
            reply = "Список сервисных центров:\n\n"
            for sc in service_centers:
                reply += f"ID: {sc['id']}\n"
                reply += f"Название: {sc['name']}\n"
                reply += f"Адрес: {sc.get('address', 'Не указан')}\n"
                reply += "-------------------\n"
            await update.message.reply_text(reply)
