from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from config import ADMIN_IDS, ENTER_REPAIR_PRICE, CONFIRMATION
from database import load_requests, save_requests, load_users, load_service_centers
import logging

logger = logging.getLogger(__name__)

class SCPriceHandler:

    async def start_price_confirmation(self, update: Update, context: CallbackContext):
        """Начинает процесс подтверждения цены"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        context.user_data['current_request_id'] = request_id
        await query.edit_message_text("💰 Введите окончательную стоимость ремонта (целое число):")
        return ENTER_REPAIR_PRICE

    async def handle_price_input(self, update: Update, context: CallbackContext):
        """Обрабатывает ввод цены"""
        try:
            price = int(update.message.text.strip())
            if price <= 0:
                raise ValueError("Цена должна быть положительным числом")
            request_id = context.user_data.get('current_request_id')
            if not request_id:
                await update.message.reply_text("❌ Ошибка: не найдена текущая заявка")
                return CONFIRMATION
            # Сохраняем цену во временные данные
            context.user_data['final_price'] = price
            context.user_data['price_request_id'] = request_id
            # Запрашиваем подтверждение
            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_price_{request_id}")],
                [InlineKeyboardButton("❌ Изменить", callback_data=f"change_price_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Вы указали стоимость: {price} руб.\nПодтвердите или измените:",
                reply_markup=reply_markup
            )
            return CONFIRMATION
        except ValueError as e:
            await update.message.reply_text("❌ Пожалуйста, введите корректное целое число (например: 2500)")
            return ENTER_REPAIR_PRICE

    async def confirm_price(self, update: Update, context: CallbackContext):
        """Подтверждает введенную цену"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        price = context.user_data.get('final_price')
        if not price or request_id != context.user_data.get('price_request_id'):
            await query.edit_message_text("❌ Ошибка: данные о цене не найдены")
            return CONFIRMATION
        # Обновляем данные заявки
        requests_data = load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена")
            return CONFIRMATION
        request = requests_data[request_id]
        request['final_price'] = price
        save_requests(requests_data)
        # Отправляем уведомления
        await self._notify_admin_and_client(update, context, request_id, price)
        await query.edit_message_text(f"✅ Окончательная стоимость {price} руб. подтверждена и сохранена")
        return CONFIRMATION

    async def change_price(self, update: Update, context: CallbackContext):
        """Запрашивает повторный ввод цены"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        await query.edit_message_text("💰 Введите новую стоимость ремонта (целое число):")
        return ENTER_REPAIR_PRICE

    async def _notify_admin_and_client(self, update: Update, context: CallbackContext, request_id: str, price: int):
        """Отправляет уведомления администраторам и клиенту"""
        requests_data = load_requests()
        request = requests_data.get(request_id)
        if not request:
            return
        users_data = load_users()
        service_centers = load_service_centers()
        # Получаем данные СЦ
        sc_id = request.get('assigned_sc')
        sc_data = service_centers.get(sc_id, {})
        sc_name = sc_data.get('name', 'Неизвестный СЦ')
        # Формируем сообщение для администраторов
        admin_message = (
            f"💰 Подтверждена окончательная стоимость ремонта\n\n"
            f"Заявка: #{request_id}\n"
            f"СЦ: {sc_name}\n"
            f"Стоимость: {price} руб.\n"
            f"Описание: {request.get('description', 'Нет описания')}"
        )
        # Отправляем уведомления администраторам
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=admin_message
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        # Формируем сообщение для клиента
        client_id = request.get('user_id')
        if client_id:
            client_message = (
                f"💰 Сервисный центр подтвердил окончательную стоимость ремонта\n\n"
                f"Заявка: #{request_id}\n"
                f"Стоимость: {price} руб.\n"
            )
            try:
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=client_message
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления клиенту {client_id}: {e}")
