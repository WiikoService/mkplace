from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext, ConversationHandler
from handlers.base_handler import BaseHandler
from database import load_users, save_users, load_service_centers
from config import ADMIN_IDS, DELIVERY_IDS, REGISTER

class UserHandler(BaseHandler):

    async def start(self, update: Update, context: CallbackContext):
        """
        Маршрутизация по ролям
        """
        user_id = str(update.message.from_user.id)
        users_data = load_users()

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
            else:
                await update.message.reply_text(
                    "Пожалуйста, зарегистрируйтесь. Нажмите кнопку ниже, чтобы поделиться контактом.",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Отправить контакт", request_contact=True)]], one_time_keyboard=True)
                )
                return REGISTER

    async def handle_contact(self, update: Update, context: CallbackContext):
        contact = update.message.contact
        user_id = str(update.message.from_user.id)
        users_data = load_users()
        phone_number = contact.phone_number
        
        # Если номер начинается с +, удаляем его для согласованности формата
        if phone_number.startswith('+'):
            phone_number = phone_number[1:]
        
        # Проверяем, не является ли этот номер номером сервисного центра
        service_centers = load_service_centers()
        sc_id = None
        sc_name = None
        
        for center_id, center_data in service_centers.items():
            center_phone = center_data.get('phone', '')
            if center_phone.startswith('+'):
                center_phone = center_phone[1:]
                
            if center_phone == phone_number:
                sc_id = center_id
                sc_name = center_data.get('name')
                break
        
        # Определяем роль пользователя
        role = "client"  # По умолчанию
        if int(user_id) in ADMIN_IDS:
            role = "admin"
        elif int(user_id) in DELIVERY_IDS:
            role = "delivery"
        elif sc_id:  # Если нашли соответствующий СЦ
            role = "sc"
        
        # Создаем базовые данные пользователя
        user_data = {
            "phone": phone_number,
            "name": contact.first_name,
            "role": role
        }
        
        # Если это представитель СЦ, добавляем данные СЦ
        if role == "sc":
            if sc_id:
                user_data["sc_id"] = sc_id
                user_data["sc_name"] = sc_name
                message = f"Спасибо, {contact.first_name}! Вы зарегистрированы как представитель СЦ '{sc_name}'."
            else:
                message = "Вы зарегистрированы как представитель СЦ. Администратор назначит вам конкретный СЦ."
        else:
            message = f"Спасибо, {contact.first_name}! Вы успешно зарегистрированы."
        
        # Сохраняем данные пользователя
        users_data[user_id] = user_data
        save_users(users_data)
        
        await update.message.reply_text(message)
        
        # Показываем соответствующее меню
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
            ["Просмотр заявок", "Привязать к СЦ"],
            ["Создать задачу доставки", "Управление СЦ"], # управление СЦ: добавть, удалить, список
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
            ["Мои заявки", "Отправить в доставку"],
            ["Связаться с администратором"],
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню СЦ:", reply_markup=reply_markup)
