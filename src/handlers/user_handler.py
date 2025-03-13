from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext, ConversationHandler
from handlers.base_handler import BaseHandler
from services.user import UserService
from config import REGISTER


class UserHandler(BaseHandler):
    def __init__(self):
        self.user_service = UserService()

    async def start(self, update: Update, context: CallbackContext):
        """Обработка команды /start"""
        user_id = str(update.message.from_user.id)
        user = await self.user_service.get_user(user_id)
        if user:
            if user.role == "admin":
                return await self.show_admin_menu(update, context)
            elif user.role == "delivery":
                return await self.show_delivery_menu(update, context)
            else:
                return await self.show_client_menu(update, context)
        else:
            # Создаем нового пользователя с определением роли
            user = await self.user_service.create_or_update_user(
                user_id=user_id,
                name=update.message.from_user.first_name
            )
            if user.role == "admin":
                return await self.show_admin_menu(update, context)
            elif user.role == "delivery":
                return await self.show_delivery_menu(update, context)
            else:
                await update.message.reply_text(
                    "Пожалуйста, зарегистрируйтесь. Нажмите кнопку ниже, чтобы поделиться контактом.",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Отправить контакт", request_contact=True)]], one_time_keyboard=True)
                )
                return REGISTER

    async def handle_contact(self, update: Update, context: CallbackContext):
        """Обработка полученного контакта при регистрации"""
        contact = update.message.contact
        user_id = str(update.message.from_user.id)
        await self.user_service.create_or_update_user(
            user_id=user_id,
            name=contact.first_name,
            phone=contact.phone_number
        )
        await update.message.reply_text(f"Спасибо, {contact.first_name}! Вы успешно зарегистрированы.")
        return await self.show_client_menu(update, context)

    async def show_client_menu(self, update: Update, context: CallbackContext):
        """Отображение меню клиента"""
        keyboard = [
            ["Создать заявку", "Мои заявки"],
            ["Мой профиль", "Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню клиента:", reply_markup=reply_markup)

    async def show_admin_menu(self, update: Update, context: CallbackContext):
        """Отображение меню администратора"""
        keyboard = [
            ["Просмотр заявок", "Привязать к СЦ"],
            ["Создать задачу доставки", "Список СЦ"],
            ["Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Админская панель:", reply_markup=reply_markup)

    async def show_delivery_menu(self, update: Update, context: CallbackContext):
        """Отображение меню доставщика"""
        keyboard = [
            ["Мои задания", "Профиль доставщика"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню доставщика:", reply_markup=reply_markup)
