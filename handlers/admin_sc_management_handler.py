import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from .admin_handler import AdminHandler
from database import load_service_centers, save_service_centers
from config import SC_MANAGEMENT_ADD_NAME, SC_MANAGEMENT_ADD_ADDRESS, SC_MANAGEMENT_ADD_PHONE

logger = logging.getLogger(__name__)


class SCManagementHandler(AdminHandler):
    """Обработчик для управления сервисными центрами"""

    async def show_sc_management(self, update: Update, context: CallbackContext):
        """Показать меню управления СЦ"""
        keyboard = [
            ["Добавить СЦ", "Список СЦ"],
            ["Удалить СЦ", "Админская панель"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Управление сервисными центрами:", reply_markup=reply_markup)

    async def handle_add_sc_start(self, update: Update, context: CallbackContext):
        """Начало процесса добавления СЦ"""
        await update.message.reply_text("Введите название сервисного центра:")
        return SC_MANAGEMENT_ADD_NAME

    async def handle_add_sc_name(self, update: Update, context: CallbackContext):
        """Обработка ввода названия СЦ"""
        sc_name = update.message.text.strip()
        if not sc_name:
            await update.message.reply_text("Название не может быть пустым. Введите название:")
            return SC_MANAGEMENT_ADD_NAME
        context.user_data['sc_name'] = sc_name
        await update.message.reply_text("Введите адрес сервисного центра:")
        return SC_MANAGEMENT_ADD_ADDRESS

    async def handle_add_sc_address(self, update: Update, context: CallbackContext):
        """Обработка ввода адреса СЦ"""
        sc_address = update.message.text.strip()
        if not sc_address:
            await update.message.reply_text("Адрес не может быть пустым. Введите адрес:")
            return SC_MANAGEMENT_ADD_ADDRESS
        context.user_data['sc_address'] = sc_address
        await update.message.reply_text("Введите номер телефона сервисного центра:")
        return SC_MANAGEMENT_ADD_PHONE

    async def handle_add_sc_phone(self, update: Update, context: CallbackContext):
        """Обработка ввода телефона СЦ"""
        sc_phone = update.message.text.strip()
        if not sc_phone:
            await update.message.reply_text("Номер телефона не может быть пустым. Введите телефон:")
            return SC_MANAGEMENT_ADD_PHONE
        sc_name = context.user_data.get('sc_name')
        sc_address = context.user_data.get('sc_address')
        service_centers = load_service_centers() or {}
        # Создаем новый ID для СЦ
        sc_id = str(len(service_centers) + 1)
        # Добавляем новый СЦ
        service_centers[sc_id] = {
            'id': sc_id,
            'name': sc_name,
            'address': sc_address,
            'phone': sc_phone
        }
        save_service_centers(service_centers)
        await update.message.reply_text(
            f"Сервисный центр успешно добавлен:\n"
            f"ID: {sc_id}\n"
            f"Название: {sc_name}\n"
            f"Адрес: {sc_address}\n"
            f"Телефон: {sc_phone}"
        )
        # Очищаем данные пользователя
        if 'sc_name' in context.user_data:
            del context.user_data['sc_name']
        if 'sc_address' in context.user_data:
            del context.user_data['sc_address']
        return ConversationHandler.END

    async def handle_delete_sc(self, update: Update, context: CallbackContext):
        """Начало процесса удаления СЦ"""
        service_centers = load_service_centers()
        if not service_centers:
            await update.message.reply_text("Список сервисных центров пуст.")
            return ConversationHandler.END
        keyboard = []
        for sc_id, sc_data in service_centers.items():
            keyboard.append([
                InlineKeyboardButton(
                    f"{sc_data['name']} - {sc_data.get('address', 'Адрес не указан')}",
                    callback_data=f"delete_sc_{sc_id}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите сервисный центр для удаления:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END  # Здесь мы завершаем диалог, так как дальше будет обрабатывать callback

    async def handle_delete_sc_confirm(self, update: Update, context: CallbackContext):
        """Подтверждение удаления СЦ"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if len(parts) < 3:
            await query.edit_message_text("Неверный формат данных")
            return
        sc_id = parts[2]
        service_centers = load_service_centers()
        if sc_id not in service_centers:
            await query.edit_message_text("Сервисный центр не найден")
            return
        sc_name = service_centers[sc_id]['name']
        # Создаем клавиатуру для подтверждения
        keyboard = [
            [
                InlineKeyboardButton("Да, удалить", callback_data=f"delete_sc_confirmed_{sc_id}"),
                InlineKeyboardButton("Отмена", callback_data="delete_sc_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Вы уверены, что хотите удалить сервисный центр '{sc_name}'?",
            reply_markup=reply_markup
        )

    async def handle_delete_sc_final(self, update: Update, context: CallbackContext):
        """Финальное подтверждение удаления СЦ"""
        query = update.callback_query
        await query.answer()
        parts = query.data.split('_')
        if "cancel" in parts:
            await query.edit_message_text("Удаление отменено.")
            return
        if len(parts) < 4:
            await query.edit_message_text("Неверный формат данных")
            return
        sc_id = parts[3]
        service_centers = load_service_centers()
        if sc_id not in service_centers:
            await query.edit_message_text("Сервисный центр не найден")
            return
        sc_name = service_centers[sc_id]['name']
        # Удаляем СЦ
        del service_centers[sc_id]
        save_service_centers(service_centers)
        await query.edit_message_text(f"Сервисный центр '{sc_name}' успешно удален.")

    async def cancel(self, update: Update, context: CallbackContext):
        """Отмена операции"""
        if 'sc_name' in context.user_data:
            del context.user_data['sc_name']
        await update.message.reply_text("Операция отменена.")
        return ConversationHandler.END
