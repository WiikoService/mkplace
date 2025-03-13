from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext, ConversationHandler
from handlers.base_handler import BaseHandler
from database import load_users, save_users
from config import ADMIN_IDS, DELIVERY_IDS, REGISTER

class UserHandler(BaseHandler):

    async def start(self, update: Update, context: CallbackContext):
        user_id = str(update.message.from_user.id)
        users_data = load_users()

        if user_id in users_data:
            role = users_data[user_id]["role"]
            if role == "admin":
                return await self.show_admin_menu(update, context)
            elif role == "delivery":
                return await self.show_delivery_menu(update, context)
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

        if user_id not in users_data:
            users_data[user_id] = {}

        users_data[user_id] = ({
            "phone": contact.phone_number,
            "name": contact.first_name,
            "role": users_data[user_id].get("role", "client")  # Сохраняем существующую роль или устанавливаем "client" по умолчанию
        })
        save_users(users_data)
        
        await update.message.reply_text(f"Спасибо, {contact.first_name}! Вы успешно зарегистрированы.")
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
            ["Создать задачу доставки", "Список СЦ"],
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Админская панель:", reply_markup=reply_markup)
    
    async def show_delivery_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Мои задания", "Мой профиль"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню доставщика:", reply_markup=reply_markup)

    