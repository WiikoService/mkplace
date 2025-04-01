from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.base_handler import BaseHandler
from database import load_users, save_users, load_service_centers, load_requests, save_requests
from config import ADMIN_IDS, DELIVERY_IDS, REGISTER
import logging
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
            # Отправляем уведомление администраторам
            service_centers = load_service_centers()
            sc_id = request.get('assigned_sc')
            sc_data = service_centers.get(sc_id, {})
            sc_name = sc_data.get('name', 'Неизвестный СЦ')
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
                f"СЦ: {sc_name}\n"
                f"Стоимость ремонта: {repair_price} руб.\n"
                f"Описание: {request.get('description', 'Нет описания')}\n"
                f"Статус: Ожидает доставку"
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
