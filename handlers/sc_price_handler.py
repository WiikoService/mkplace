from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from config import ADMIN_IDS, ENTER_REPAIR_PRICE, CONFIRMATION
from database import load_requests, save_requests, load_users, load_service_centers, save_chat_history
import logging
from datetime import datetime

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
                f"Вы указали стоимость: {price} BYN\nПодтвердите или измените:",
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
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена")
            return CONFIRMATION
        request = requests_data[request_id]
        request['final_price'] = price
        request['price_status'] = 'pending_client_approval'  # Добавляем статус ожидания подтверждения клиентом
        await save_requests(requests_data)
        # Отправляем запрос на подтверждение цены клиенту
        await self._request_client_approval(update, context, request_id, price)
        await query.edit_message_text(f"✅ Окончательная стоимость {price} BYN отправлена клиенту на подтверждение")
        return CONFIRMATION

    async def change_price(self, update: Update, context: CallbackContext):
        """Запрашивает повторный ввод цены"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("💰 Введите новую стоимость ремонта (целое число):")
        return ENTER_REPAIR_PRICE

    async def _request_client_approval(self, update: Update, context: CallbackContext, request_id: str, price: int):
        """Отправляет запрос клиенту на подтверждение цены"""
        requests_data = await load_requests()
        request = requests_data.get(request_id)
        if not request:
            return
        # Формируем сообщение для клиента
        client_id = request.get('user_id')
        service_centers = await load_service_centers()
        sc_id = request.get('assigned_sc')
        sc_data = service_centers.get(sc_id, {})
        sc_name = sc_data.get('name', 'Неизвестный СЦ')
        if client_id:
            client_message = (
                f"💰 Сервисный центр установил окончательную стоимость ремонта\n\n"
                f"Заявка: #{request_id}\n"
                f"СЦ: {sc_name}\n"
                f"Стоимость: {price} BYN\n\n"
                f"Пожалуйста, подтвердите согласие с указанной стоимостью."
            )    
            # Кнопки для подтверждения/отказа
            keyboard = [
                [InlineKeyboardButton("✅ Согласен", callback_data=f"sc_final_approve_price_{request_id}")],
                [InlineKeyboardButton("❌ Не согласен", callback_data=f"sc_final_reject_price_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=client_message,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки запроса на подтверждение цены клиенту {client_id}: {e}")

    async def handle_sc_final_price_approval(self, update: Update, context: CallbackContext):
        """Обработка подтверждения окончательной цены ремонта клиентом"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        # Обновляем данные заявки
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена")
            return
        request = requests_data[request_id]
        price = request.get('final_price')
        if not price:
            await query.edit_message_text("❌ Данные о цене не найдены")
            return
        # Обновляем статус цены и заявки
        request['price_status'] = 'approved_by_client'
        request['status'] = 'Ремонт завершен, ожидает доставки'
        await save_requests(requests_data)
        # Уведомляем админа и СЦ
        await self._notify_admin_and_sc_approval(context, request_id, price, True)
        # Уведомляем клиента - просто сообщение о подтверждении, без дальнейших действий
        await query.edit_message_text(
            f"✅ Вы подтвердили стоимость ремонта {price} BYN для заявки #{request_id}.\n"
            f"Сервисный центр приступит к подготовке устройства к доставке.\n"
            f"Оплата будет произведена при получении."
        )
        # Важно: не возвращаем никакого состояния, чтобы не перехватывать сообщения

    async def handle_sc_final_price_rejection(self, update: Update, context: CallbackContext):
        """Обработка отклонения окончательной цены ремонта клиентом и открытие чата с СЦ"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        # Обновляем данные заявки
        requests_data = await load_requests()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена")
            return
        request = requests_data[request_id]
        price = request.get('final_price')
        if not price:
            await query.edit_message_text("❌ Данные о цене не найдены")
            return
        # Обновляем статус цены
        request['price_status'] = 'rejected_by_client'
        request['status'] = 'Цена не согласована'
        await save_requests(requests_data)
        # Уведомляем админа и СЦ
        await self._notify_admin_and_sc_approval(context, request_id, price, False)
        # Готовим данные для чата
        sc_id = request.get('assigned_sc')
        users_data = await load_users()
        client_id = str(update.effective_user.id)
        # Ищем пользователя СЦ
        sc_user_id = None
        for user_id, user_data in users_data.items():
            if user_data.get('role') == 'sc' and str(user_data.get('sc_id')) == str(sc_id):
                sc_user_id = user_id
                break
        if not sc_user_id:
            await query.edit_message_text(
                f"❌ Вы отклонили стоимость ремонта {price} BYN для заявки #{request_id}.\n"
                f"Сервисный центр уведомлен о вашем решении и вскоре свяжется с вами для согласования окончательной стоимости."
            )
            return
        # Сохраняем данные чата в контексте пользователя
        context.user_data['active_client_chat'] = {
            'request_id': request_id,
            'sc_user_id': sc_user_id,
            'last_active': datetime.now().timestamp()
        }
        # Отправляем сообщение о несогласии в чат
        timestamp = datetime.now().strftime("%H:%M %d.%m.%Y")
        disagreement_message = f"Система: Клиент не согласен с предложенной окончательной стоимостью ремонта {price} BYN."
        # Сохраняем в историю чата
        await save_chat_history(
            request_id, 
            [{
                'sender': 'system',
                'message': disagreement_message,
                'timestamp': timestamp
            }]
        )
        # Отправляем сообщение СЦ
        try:
            await context.bot.send_message(
                chat_id=int(sc_user_id),
                text=f"📩 *Системное уведомление по заявке #{request_id}:*\n"
                     f"{disagreement_message}\n\n"
                     f"❗️ Клиент не согласен с окончательной стоимостью ремонта {price} BYN и ожидает обсуждения."
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения СЦ {sc_user_id}: {e}")
        # Уведомляем клиента и открываем чат
        await query.edit_message_text(
            f"❌ Вы отклонили окончательную стоимость ремонта {price} BYN для заявки #{request_id}.\n"
            f"Сервисный центр уведомлен о вашем решении.\n\n"
            f"Сейчас вы можете оставить дополнительный комментарий о причинах несогласия с ценой:"
        )
        return 'HANDLE_CLIENT_REPLY'

    async def _notify_admin_and_sc_approval(self, context: CallbackContext, request_id: str, price: int, approved: bool):
        """Уведомляет админа и СЦ о подтверждении/отклонении цены клиентом"""
        requests_data = load_requests()
        request = requests_data.get(request_id)
        if not request:
            return   
        status_text = "подтвердил" if approved else "отклонил"
        # Сообщение для админа
        admin_message = (
            f"{'✅' if approved else '❌'} Клиент {status_text} окончательную стоимость ремонта\n\n"
            f"Заявка: #{request_id}\n"
            f"Стоимость: {price} BYN\n"
            f"Описание: {request.get('description', 'Нет описания')}"
        )
        # Отправляем администраторам
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=admin_message
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        # Отправляем уведомление СЦ
        sc_id = request.get('assigned_sc')
        users_data = await load_users()
        # Получаем данные клиента
        client_id = request.get('user_id')
        client_data = users_data.get(client_id, {})
        client_name = client_data.get('name', 'Не указано')
        client_phone = client_data.get('phone', 'Не указан')
        # Формируем детальное сообщение для СЦ, аналогичное администраторскому
        sc_message = (
            f"{'✅' if approved else '❌'} Клиент {status_text} окончательную стоимость ремонта\n\n"
            f"Заявка: #{request_id}\n"
            f"Клиент: {client_name}\n"
            f"Телефон: {client_phone}\n"
            f"Стоимость: {price} BYN\n"
            f"Описание: {request.get('description', 'Нет описания')}"
        )
        # Если цена отклонена, добавляем инструкции
        if not approved:
            sc_message += "\n\nНеобходимо связаться с клиентом для обсуждения стоимости. Клиент ожидает, что вы свяжетесь с ним."
        for user_id, user_data in users_data.items():
            if user_data.get('role') == 'sc' and str(user_data.get('sc_id')) == str(sc_id):
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=sc_message
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления СЦ {user_id}: {e}")
