from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext


class BaseHandler:
    """Базовый класс для всех обработчиков"""

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
