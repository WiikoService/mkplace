from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.base_handler import BaseHandler
from database import load_users, save_users, load_service_centers, load_requests, save_requests, load_delivery_tasks, save_delivery_tasks
from config import ADMIN_IDS, DELIVERY_IDS, REGISTER, ORDER_STATUS_DELIVERY_TO_SC
import logging
from datetime import datetime, timedelta
from telegram.ext import ConversationHandler

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class UserHandler(BaseHandler):

    async def start(self, update: Update, context: CallbackContext):
        """
        Маршрутизация по ролям и привязка к спискам
        Можно тестировать один id по двум ролям
        """
        user_id = str(update.message.from_user.id)
        users_data = load_users()
        sc_ids = [int(user_id) for user_id, data in users_data.items() 
                 if data.get("role") == "sc"]
        if user_id in users_data:
            role = users_data[user_id]["role"]
            if role == "admin":
                return await self.show_admin_menu(update, context)
            elif role == "delivery":
                return await self.show_delivery_menu(update, context)
            elif role == "sc":
                return await self.show_sc_menu(update, context)
            else:
                return await self.show_client_menu(update, context)
        else:
            if int(user_id) in ADMIN_IDS:
                users_data[user_id] = {"role": "admin", "name": update.message.from_user.first_name}
                save_users(users_data)
                return await self.show_admin_menu(update, context)
            elif int(user_id) in DELIVERY_IDS:
                users_data[user_id] = {"role": "delivery", "name": update.message.from_user.first_name}
                save_users(users_data)
                return await self.show_delivery_menu(update, context)
            elif int(user_id) in sc_ids:
                users_data[user_id] = {"role": "sc", "name": update.message.from_user.first_name}
                save_users(users_data)
                return await self.show_sc_menu(update, context)
            else:
                await update.message.reply_text(
                    "Пожалуйста, зарегистрируйтесь. Нажмите кнопку ниже, чтобы поделиться контактом.",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Отправить контакт", request_contact=True)]], one_time_keyboard=True, resize_keyboard=True)
                )
                return REGISTER

    async def handle_contact(self, update: Update, context: CallbackContext):
        contact = update.message.contact
        user_id = str(update.message.from_user.id)
        users_data = load_users()
        phone_number = contact.phone_number.lstrip('+')
        sc_id = None
        sc_name = None
        service_centers = load_service_centers()
        for center_id, center_data in service_centers.items():
            center_phone = center_data.get('phone', '').lstrip('+')
            if center_phone == phone_number:
                sc_id = center_id
                sc_name = center_data.get('name')
                break  # Нашли соответствие, прерываем цикл
        if int(user_id) in ADMIN_IDS:
            role = "admin"
        elif int(user_id) in DELIVERY_IDS:
            role = "delivery"
        elif sc_id:
            role = "sc"
        else:
            role = "client"
        # Обновляем данные пользователя
        users_data[user_id] = {
            "phone": phone_number,
            "name": contact.first_name,
            "role": role
        }
        # Привязываем к СЦ, если нашли соответствие
        if role == "sc" and sc_id:
            users_data[user_id]["sc_id"] = sc_id
            users_data[user_id]["sc_name"] = sc_name
        save_users(users_data)  # Сохраняем данные пользователя
        # Отправляем подтверждающее сообщение
        if role == "sc" and sc_id:
            await update.message.reply_text(f"Спасибо, {contact.first_name}! Вы зарегистрированы как представитель СЦ '{sc_name}'.")
            return await self.show_sc_menu(update, context)
        else:
            await update.message.reply_text(f"Спасибо, {contact.first_name}! Вы успешно зарегистрированы.")
        # Показываем соответствующее меню в зависимости от роли
        if role == "admin":
            return await self.show_admin_menu(update, context)
        elif role == "delivery":
            return await self.show_delivery_menu(update, context)
        elif role == "sc":
            return await self.show_sc_menu(update, context)
        else:
            return await self.show_client_menu(update, context)

    async def show_client_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Создать заявку", "Мои заявки"],
            ["Мой профиль", "Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню клиента:", reply_markup=reply_markup)

    async def show_admin_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Просмотр заявок", "Новые заявки"],
            ["Создать задачу доставки", "Управление СЦ"],  # управление СЦ: добавть, удалить, список
            ["Обратная связь", "Просмотр чата заявки"], # обратная связь: отзывы, статистика
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Админская панель:", reply_markup=reply_markup)

    async def show_delivery_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Доступные задания", "Мои задания"],
            ["Передать в СЦ", "Мой профиль"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню доставщика:", reply_markup=reply_markup)

    async def show_sc_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Заявки центра", "Отправить в доставку"],
            ["Связаться с администратором"],
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню СЦ:", reply_markup=reply_markup)

    async def handle_client_price_approval(self, update: Update, context: CallbackContext):
        """Обработка согласия клиента с предложенной ценой"""
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
            
            # Форматируем местоположение
            location = request.get('location', {})
            if isinstance(location, dict):
                if location.get('type') == 'coordinates':
                    address = location.get('address', 'Адрес не определен')
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get('address', 'Адрес не указан')
            else:
                location_str = str(location)
            
            # Обновляем статус заявки
            request['status'] = 'Ожидает доставку'
            request['price_approved'] = True
            save_requests(requests_data)
            
            # Отправляем подтверждение клиенту
            await query.edit_message_text(
                f"✅ Вы согласились с предложенной стоимостью ремонта:\n"
                f"Сумма: {repair_price} руб.\n\n"
                f"Заявка переведена в статус: Ожидает доставку"
            )
            
            # Создаем задачу доставки автоматически
            try:
                delivery_tasks = load_delivery_tasks()
                service_centers = load_service_centers()
                
                # Получаем данные СЦ
                sc_id = request.get('assigned_sc')
                sc_data = service_centers.get(sc_id, {})
                
                # Создаем задачу доставки ОТ КЛИЕНТА В СЦ
                new_task_id = str(len(delivery_tasks) + 1)
                new_task = {
                    'task_id': new_task_id,
                    'request_id': request_id,
                    'status': 'Новая',
                    'sc_name': sc_data.get('name', 'Не указан'),
                    'sc_address': sc_data.get('address', 'Не указан'),
                    'client_name': request.get('user_name', 'Не указан'),
                    'client_address': location_str,  # Используем отформатированный адрес
                    'client_phone': request.get('user_phone', 'Не указан'),
                    'description': request.get('description', ''),
                    'delivery_type': 'client_to_sc',
                    'is_sc_to_client': False,
                    'desired_date': request.get('desired_date', '')
                }
                
                delivery_tasks[new_task_id] = new_task
                save_delivery_tasks(delivery_tasks)
                
                # Обновляем статус заявки
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                save_requests(requests_data)
                
                # Отправляем уведомление администраторам
                admin_message = (
                    f"✅ Клиент подтвердил цену для заявки #{request_id}\n"
                    f"Создана задача доставки #{new_task_id}\n"
                    f"Тип: Доставка от клиента в СЦ\n"
                    f"СЦ: {sc_data.get('name', 'Не указан')}\n"
                    f"Адрес клиента: {location_str}"
                )
                
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
                        
            except Exception as e:
                logger.error(f"Ошибка при создании задачи доставки: {e}")
                # Отправляем уведомление администраторам о необходимости создать задачу вручную
                keyboard = [[
                    InlineKeyboardButton(
                        "Создать задачу доставки",
                        callback_data=f"create_delivery_{request_id}"
                    )
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                admin_message = (
                    f"✅ Клиент согласился с предложенной стоимостью\n\n"
                    f"Заявка: #{request_id}\n"
                    f"СЦ: {sc_data.get('name', 'Неизвестный СЦ')}\n"
                    f"Стоимость ремонта: {repair_price} руб.\n"
                    f"Описание: {request.get('description', 'Нет описания')}\n"
                    f"Адрес клиента: {location_str}\n"
                    f"Статус: Ожидает доставку\n\n"
                    f"❗ Автоматическое создание задачи доставки не удалось. Создайте задачу вручную."
                )
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка при обработке согласия с ценой: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    async def handle_client_price_rejection(self, update: Update, context: CallbackContext):
        """Обработка отказа клиента от предложенной цены"""
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
            
            # Форматируем местоположение
            location = request.get('location', {})
            if isinstance(location, dict):
                if location.get('type') == 'coordinates':
                    address = location.get('address', 'Адрес не определен')
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get('address', 'Адрес не указан')
            else:
                location_str = str(location)
            
            # Обновляем статус заявки
            request['status'] = 'Цена не согласована'
            request['price_approved'] = False
            save_requests(requests_data)
            
            # Отправляем сообщение клиенту
            await query.edit_message_text(
                f"❌ Вы отказались от предложенной стоимости ремонта:\n"
                f"Сумма: {repair_price} руб.\n\n"
                f"Заявка переведена в статус: Цена не согласована\n"
                f"Пожалуйста, свяжитесь с сервисным центром для обсуждения стоимости."
            )
            
            # Отправляем уведомление администраторам
            service_centers = load_service_centers()
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            admin_message = (
                f"❌ Клиент отказался от предложенной стоимости\n\n"
                f"Заявка: #{request_id}\n"
                f"СЦ: {sc_name}\n"
                f"Стоимость ремонта: {repair_price} руб.\n"
                f"Адрес клиента: {location_str}\n"
                f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Статус: Цена не согласована"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка при обработке отказа от цены: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    async def handle_client_price_rejection(self, update: Update, context: CallbackContext):
        """Обработка отказа клиента от предложенной цены"""
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
            # Обновляем статус заявки
            request['status'] = 'Цена не согласована'
            request['price_approved'] = False
            save_requests(requests_data)
            # Отправляем сообщение клиенту
            await query.edit_message_text(
                f"❌ Вы отказались от предложенной стоимости ремонта:\n"
                f"Сумма: {repair_price} руб.\n\n"
                f"Заявка переведена в статус: Цена не согласована\n"
                f"Пожалуйста, свяжитесь с сервисным центром для обсуждения стоимости."
            )
            # Отправляем уведомление администраторам
            service_centers = load_service_centers()
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
            admin_message = (
                f"❌ Клиент отказался от предложенной стоимости\n\n"
                f"Заявка: #{request_id}\n"
                f"СЦ: {sc_name}\n"
                f"Стоимость ремонта: {repair_price} руб.\n"
                f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Статус: Цена не согласована"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при обработке отказа от цены: {e}")
            await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    async def handle_delivery_date_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора даты доставки клиентом"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        # Сохраняем ID заявки в контексте
        context.user_data['delivery_request_id'] = request_id
        # Создаем клавиатуру с датами на ближайшую неделю
        keyboard = []
        current_date = datetime.now()
        # Форматируем текущую дату и добавляем кнопки для следующих 7 дней
        for i in range(3):
            date = current_date + timedelta(days=i)
            # Форматируем дату для отображения
            date_display = date.strftime("%d.%m (%A)")  # Добавляем день недели
            # Форматируем дату для callback_data
            date_value = date.strftime("%H:%M %d.%m.%Y")
            keyboard.append([
                InlineKeyboardButton(
                    f"📅 {date_display}",
                    callback_data=f"select_delivery_time_{date_value}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Выберите удобную дату доставки для заявки #{request_id}:",
            reply_markup=reply_markup
        )
        return 'SELECT_DELIVERY_TIME'

    async def handle_delivery_time_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора времени доставки клиентом"""
        query = update.callback_query
        await query.answer()
        selected_date_str = query.data.split('_', 3)[3]
        request_id = context.user_data.get('delivery_request_id')
        try:
            # Сохраняем выбранную дату
            context.user_data["temp_delivery_date"] = selected_date_str
            # Создаем клавиатуру с временными интервалами
            keyboard = []
            current_hour = 9  # Начинаем с 9 утра
            while current_hour <= 20:  # До 20:00
                time_str = f"{current_hour:02d}:00"
                keyboard.append([
                    InlineKeyboardButton(
                        f"🕐 {time_str}",
                        callback_data=f"confirm_delivery_time_{time_str}"
                    )
                ])
                current_hour += 1
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Выберите удобное время доставки:",
                reply_markup=reply_markup
            )
            return 'CONFIRM_DELIVERY_TIME'
        except Exception as e:
            logger.error(f"Ошибка при обработке выбора даты: {e}")
            await query.edit_message_text(
                "Произошла ошибка при обработке даты. Попробуйте еще раз."
            )
            return 'SELECT_DELIVERY_TIME'

    async def handle_delivery_time_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения времени доставки клиентом"""
        query = update.callback_query
        await query.answer()
        selected_time = query.data.split('_', 3)[3]
        temp_date = context.user_data.get("temp_delivery_date")
        request_id = context.user_data.get('delivery_request_id')
        
        try:
            # Комбинируем дату и время
            date_obj = datetime.strptime(temp_date, "%H:%M %d.%m.%Y")
            time_obj = datetime.strptime(selected_time, "%H:%M")
            # Создаем финальную дату с выбранным временем
            final_datetime = date_obj.replace(
                hour=time_obj.hour,
                minute=time_obj.minute
            )
            # Получаем данные заявки
            requests_data = load_requests()
            request = requests_data.get(request_id, {})
            # Обновляем статус и добавляем дату доставки
            request['status'] = 'Ожидает доставку из СЦ'
            request['delivery_date'] = final_datetime.strftime("%H:%M %d.%m.%Y")
            requests_data[request_id] = request
            save_requests(requests_data)
            # Очищаем временные данные
            if "temp_delivery_date" in context.user_data:
                del context.user_data["temp_delivery_date"]
            # Уведомляем администраторов
            keyboard = [[
                InlineKeyboardButton(
                    "Создать задачу доставки из СЦ", 
                    callback_data=f"create_sc_delivery_{request_id}"
                )
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            admin_message = (
                f"🔄 Запрос на доставку из СЦ\n\n"
                f"Заявка: #{request_id}\n"
                f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Дата доставки: {request['delivery_date']}\n"
                f"Статус: Ожидает доставку из СЦ"
            )
            # Отправляем уведомления админам
            notification_sent = False
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        reply_markup=reply_markup
                    )
                    notification_sent = True
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
            if notification_sent:
                await query.edit_message_text(
                    f"✅ Дата доставки для заявки #{request_id} установлена:\n"
                    f"{request['delivery_date']}\n\n"
                    "Администраторы уведомлены о необходимости создать задачу доставки."
                )
            else:
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                requests_data[request_id] = request
                save_requests(requests_data)
                await query.edit_message_text(
                    f"❌ Не удалось установить дату доставки для заявки #{request_id}. Попробуйте позже."
                )
        except ValueError as e:
            await query.edit_message_text(
                "Произошла ошибка при обработке времени. Попробуйте еще раз."
            )
            return 'SELECT_DELIVERY_TIME'            
        return ConversationHandler.END
