import json
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from telegram.error import BadRequest
from .base_handler import BaseHandler
from database import load_delivery_tasks, load_requests, load_service_centers, load_users, save_delivery_tasks, save_requests
from config import ASSIGN_REQUEST, ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK, ORDER_STATUS_ASSIGNED_TO_SC
from utils import notify_admin, notify_delivery
logger = logging.getLogger(__name__)

class AdminHandler(BaseHandler):


    async def handle_assign_sc(self, update: Update, context: CallbackContext):
        """Обработка выбора заявки для привязки к СЦ"""
        query = update.callback_query
        await query.answer()
    
        try:
            parts = query.data.split('_')
            logger.info(f"Callback data parts: {parts}")
            
            if len(parts) < 3:
                await query.edit_message_text("Неверный формат данных")
                return ConversationHandler.END

            # Проверяем, является ли это подтверждением
            if 'confirm' in parts:
                request_id = parts[3]  # Берем ID заявки после 'confirm'
            else:
                request_id = parts[2]  # Берем ID заявки напрямую
            
            logger.info(f"Processing request_id: {request_id}")
            
            requests_data = load_requests()
            logger.info(f"Available requests: {list(requests_data.keys())}")
            
            if request_id not in requests_data:
                await query.edit_message_text(f"Заявка #{request_id} не найдена")
                return ConversationHandler.END

            service_centers = load_service_centers()
            if not service_centers:
                await query.edit_message_text("Нет доступных сервисных центров.")
                return ConversationHandler.END
    
            keyboard = []
            for sc_id, sc_data in service_centers.items():
                callback_data = f"assign_sc_confirm_{request_id}_{sc_id}"
                logger.info(f"Creating button with callback_data: {callback_data}")
                keyboard.append([
                    InlineKeyboardButton(
                        f"{sc_data['name']} - {sc_data.get('address', 'Адрес не указан')}", 
                        callback_data=callback_data
                    )
                ])
    
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Выберите сервисный центр для заявки #{request_id}:",
                reply_markup=reply_markup
            )
            return ASSIGN_REQUEST
        
        except Exception as e:
            logger.error(f"Error in handle_assign_sc: {e}")
            await query.edit_message_text(f"Произошла ошибка при обработке заявки: {str(e)}")
            return ConversationHandler.END


    async def handle_assign_sc_confirm(self, update: Update, context: CallbackContext):
        """Подтверждение привязки заявки к СЦ"""
        query = update.callback_query
        await query.answer()

        logger.info(f"Received callback query: {query.data}")

        try:
            parts = query.data.split('_')
            if len(parts) < 5:
                logger.error(f"Invalid data format: {query.data}")
                await query.edit_message_text("Неверный формат данных")
                return

            request_id = parts[3]
            sc_id = parts[4]

            requests_data = load_requests()
            service_centers = load_service_centers()

            if request_id not in requests_data:
                logger.error(f"Request {request_id} not found")
                await query.edit_message_text(f"Заявка #{request_id} не найдена")
                return

            if sc_id not in service_centers:
                logger.error(f"Service center {sc_id} not found")
                await query.edit_message_text(f"Сервисный центр с ID {sc_id} не найден")
                return

            sc_data = service_centers[sc_id]
            requests_data[request_id].update({
                'assigned_sc': sc_id,
                'status': ORDER_STATUS_ASSIGNED_TO_SC
            })
            save_requests(requests_data)

            new_text = f"Заявка #{request_id} привязана к СЦ {sc_data['name']}."
            await query.edit_message_text(new_text)

            task_id = await self.create_delivery_task(update, context, request_id, sc_data['name'])
            logger.info(f"Request {request_id} successfully assigned to SC {sc_id} and delivery task {task_id} created")

        except Exception as e:
            logger.error(f"Error in handle_assign_sc_confirm: {e}")
            await query.edit_message_text("Произошла ошибка при привязке заявки к СЦ")


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
            for delivery_id in DELIVERY_IDS:
                await notify_delivery(context.bot, delivery_id, task_id, request_id, sc_name)
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
        """Начало процесса привязки заявки к СЦ"""
        try:
            requests_dict = load_requests()
            if not requests_dict:
                await update.message.reply_text("Нет активных заявок для привязки.")
                return ConversationHandler.END

            keyboard = []
            for req_id, req_data in requests_dict.items():
                if not req_data.get('assigned_sc'):  # Показываем только неназначенные заявки
                    status = req_data.get('status', 'Статус не указан')
                    desc = req_data.get('description', 'Нет описания')[:30] + '...'
                    button_text = f"Заявка #{req_id} - {status} - {desc}"
                    keyboard.append([InlineKeyboardButton(
                        button_text, 
                        callback_data=f"assign_sc_{req_id}"
                    )])

            if not keyboard:
                await update.message.reply_text("Нет заявок, требующих привязки к СЦ.")
                return ConversationHandler.END

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Выберите заявку для привязки к сервисному центру:",
                reply_markup=reply_markup
            )
            return ASSIGN_REQUEST
        
        except Exception as e:
            logger.error(f"Error in assign_request: {e}")
            await update.message.reply_text("Произошла ошибка при загрузке заявок.")
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
        
        service_center = await self.service_center_service.get_service_center(sc_id)
        if not service_center:
            await query.edit_message_text("Сервисный центр не найден")
            return
        
        task_id = await self.create_delivery_task(update, context, request_id, service_center.name)
        
        await query.edit_message_text(
            f"Задача доставки #{task_id} для заявки #{request_id} создана.\n"
            f"Доставщики уведомлены."
        )


    async def handle_create_delivery_menu(self, update: Update, context: CallbackContext):
        """Обработчик кнопки создания задачи доставки из меню"""
        await update.message.reply_text("Введите номер заявки для создания задачи доставки:")
        return CREATE_DELIVERY_TASK


    async def handle_create_delivery_input(self, update: Update, context: CallbackContext):
        """Обработчик ввода номера заявки для создания задачи доставки"""
        request_id = update.message.text.strip()
        requests_data = load_requests()
        
        if request_id not in requests_data:
            await update.message.reply_text(f"Заявка #{request_id} не найдена")
            return ConversationHandler.END
        
        request = requests_data[request_id]
        if not request.get('assigned_sc'):
            await update.message.reply_text("Заявка должна быть сначала привязана к сервисному центру")
            return ConversationHandler.END
        
        service_centers = load_service_centers()
        sc_id = request['assigned_sc']
        sc_name = next((sc['name'] for sc in service_centers if str(sc['id']) == str(sc_id)), None)
        
        if not sc_name:
            await update.message.reply_text("Сервисный центр не найден")
            return ConversationHandler.END
        
        task_id = await self.create_delivery_task(update, context, request_id, sc_name)
        await update.message.reply_text(f"Задача доставки #{task_id} создана. Доставщики уведомлены.")
        return ConversationHandler.END
