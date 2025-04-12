import os
import json
import logging
from datetime import datetime

from telegram.ext import CallbackContext, ConversationHandler
from telegram import (
    Bot, Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
from database import load_delivery_tasks, save_delivery_tasks
from config import (
    ADMIN_IDS, RATING_SERVICE, FEEDBACK_TEXT, ORDER_STATUS_DELIVERY_TO_SC
)
from database import load_requests, load_users, DATA_DIR, save_requests
import logging

logger = logging.getLogger(__name__)


class ClientHandler:
    async def show_client_menu(self, update: Update, context: CallbackContext):
        keyboard = [
            ["Создать заявку", "Мои заявки"],
            ["Мой профиль", "Документы"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню клиента:", reply_markup=reply_markup)

    async def show_client_profile(self, update: Update, context: CallbackContext):
        """Отображение профиля клиента."""
        user_id = str(update.message.from_user.id)
        users_data = load_users()
        user = users_data.get(user_id, {})
        reply = "Ваш профиль:\n\n"
        reply += f"Имя: {user.get('name', 'Не указано')}\n"
        reply += f"Телефон: {user.get('phone', 'Не указан')}\n"
        if not user.get('name') or not user.get('phone'):
            reply += "\nДля полной регистрации, пожалуйста, нажмите кнопку 'Регистрация'."
            keyboard = [[KeyboardButton("Регистрация", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(reply, reply_markup=reply_markup)
        else:
            await update.message.reply_text(reply)

    async def show_client_requests(self, update: Update, context: CallbackContext):
        """Показать заявки клиента с кнопками под каждой заявкой"""
        user_id = str(update.effective_user.id)
        requests_data = load_requests()
        user_requests = {
            req_id: req_data for req_id, req_data in requests_data.items()
            if req_data.get('user_id') == user_id
        }
        if not user_requests:
            await update.message.reply_text(
                "У вас пока нет заявок.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        sorted_requests = sorted(
            user_requests.items(),
            key=lambda x: x[1].get('timestamp', ''),
            reverse=True
        )
        for req_id, req_data in sorted_requests:
            status = req_data.get('status', 'Неизвестно')
            description = req_data.get('description', 'Без описания')
            category = req_data.get('category', 'Не указана')
            location = req_data.get('location', {})   
            if isinstance(location, dict):
                address = location.get('address', 'Адрес не указан')
                if location.get("type") == "coordinates":
                    address = "📍 Геолокация"
            else:
                address = str(location)
            message = (
                f"🔹 <b>Заявка #{req_id}</b>\n"
                f"📋 <b>Категория:</b> {category}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"📍 <b>Адрес:</b> {address}\n"
                f"📊 <b>Статус:</b> {status}\n"
            )
            if 'timestamp' in req_data:
                message += f"📅 <b>Дата создания:</b> {req_data['timestamp']}\n"
            keyboard = []
            if status == "Доставлено клиенту":
                keyboard.append([
                    InlineKeyboardButton(
                        "🗣 Открыть спор",
                        callback_data=f"start_dispute_{req_id}"
                    )
                ])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    async def show_documents(self, update: Update, context: CallbackContext):
        """Отображение доступных документов для клиента"""
        documents = [
            "Пользовательское соглашение",
            "Политика конфиденциальности",
            "Инструкция по использованию сервиса"
        ]
        message = "Доступные документы (ТЕСТОВАЯ ИНФОРМАЦИЯ):\n\n"
        for doc in documents:
            message += f"• {doc}\n"
        message += "\nДля получения конкретного документа, пожалуйста, обратитесь к администратору."
        await update.message.reply_text(message)

    async def notify_admin(self, bot: Bot, request_id: int, request_data: dict):
        for admin_id in ADMIN_IDS:
            message = f"Новая заявка #{request_id}\n"
            message += f"Описание: {request_data[request_id]['description'][:50]}...\n"
            message += f"Статус: {request_data[request_id]['status']}"
            await bot.send_message(chat_id=admin_id, text=message)

    async def request_service_rating(self, update: Update, context: CallbackContext):
        """Запрос оценки обслуживания у клиента"""
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        keyboard = [
            [InlineKeyboardButton("🌟🌟🌟🌟🌟", callback_data=f"rate_5_{request_id}")],
            [InlineKeyboardButton("🌟🌟🌟🌟", callback_data=f"rate_4_{request_id}")],
            [InlineKeyboardButton("🌟🌟🌟", callback_data=f"rate_3_{request_id}")],
            [InlineKeyboardButton("🌟🌟", callback_data=f"rate_2_{request_id}")],
            [InlineKeyboardButton("🌟", callback_data=f"rate_1_{request_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Пожалуйста, оцените качество обслуживания:",
            reply_markup=reply_markup
        )
        return RATING_SERVICE

    async def handle_rating(self, update: Update, context: CallbackContext):
        """Обработка выбранной оценки"""
        query = update.callback_query
        await query.answer()
        data_parts = query.data.split('_')
        rating = int(data_parts[1])
        request_id = data_parts[2]
        self._save_rating(rating)
        if rating < 4:
            await query.edit_message_text(
                f"Спасибо за оценку!\n\n"
                f"Мы стараемся стать лучше. Пожалуйста, расскажите, что мы могли бы улучшить:"
            )
            logger.info(f"Запрошена обратная связь после оценки {rating} для заявки {request_id}")
            return FEEDBACK_TEXT
        else:
            await query.edit_message_text(
                f"Благодарим за высокую оценку!\n\n"
                f"Мы рады, что вы остались довольны нашим обслуживанием."
            )
            logger.info(f"Получена высокая оценка {rating} для заявки {request_id}")
            return ConversationHandler.END

    async def handle_feedback(self, update: Update, context: CallbackContext):
        """Обработка текстовой обратной связи"""
        try:
            feedback_text = update.message.text.strip()
            if not feedback_text:
                await update.message.reply_text(
                    "❌ Пожалуйста, введите текст отзыва."
                )
                return FEEDBACK_TEXT
            logger.info(f"Получен отзыв: {feedback_text}")
            self._save_feedback(feedback_text)
            logger.info("Отзыв сохранен успешно")
            await update.message.reply_text(
                "✅ Спасибо за ваш отзыв! Мы учтем ваши комментарии для улучшения нашего сервиса."
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при обработке отзыва: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении отзыва. Пожалуйста, попробуйте еще раз."
            )
            return FEEDBACK_TEXT

    def _save_rating(self, rating):
        """Сохраняет оценку в JSON-файл"""
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                feedback_data = {'ratings': [], 'reviews': []}
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            feedback_data = {'ratings': [], 'reviews': []}
        feedback_data['ratings'].append({
            'rating': rating,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        try:
            with open(feedback_file, 'w', encoding='utf-8') as f:
                json.dump(feedback_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении оценки: {e}")

    def _save_feedback(self, feedback_text):
        """Сохраняет отзыв в JSON-файл"""
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                feedback_data = {'ratings': [], 'reviews': []}
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            feedback_data = {'ratings': [], 'reviews': []}
        feedback_data['reviews'].append({
            'id': len(feedback_data['reviews']) + 1,
            'text': feedback_text,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        try:
            with open(feedback_file, 'w', encoding='utf-8') as f:
                json.dump(feedback_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении отзыва: {e}")

    async def cancel_operation(self, update: Update, context: CallbackContext):
        """Отмена операции оценки"""
        await update.message.reply_text("Операция отменена.")
        return ConversationHandler.END

    async def start_rating_conversation(self, update: Update, context: CallbackContext):
        """Запускает ConversationHandler для оценки"""
        query = update.callback_query
        await query.answer()
        data_parts = query.data.split('_')
        rating = int(data_parts[1])
        request_id = data_parts[2]
        self._save_rating(rating)
        context.user_data['current_rating'] = rating
        context.user_data['current_request_id'] = request_id
        stars = "🌟" * rating
        if rating < 4:
            await query.edit_message_text(
                f"Спасибо за оценку {stars}!\n\n"
                f"Мы стремимся стать лучше. Пожалуйста, расскажите, что мы могли бы улучшить:"
            )
            logger.info(f"Запрошена обратная связь после оценки {rating} для заявки {request_id}")
            return FEEDBACK_TEXT
        else:
            await query.edit_message_text(
                f"Благодарим за высокую оценку {stars}!\n\n"
                f"Мы рады, что вы остались довольны нашим обслуживанием."
            )
            logger.info(f"Получена высокая оценка {rating} для заявки {request_id}")
            return ConversationHandler.END

    async def handle_client_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения/отказа клиента о получении товара"""
        query = update.callback_query
        await query.answer()
        try:
            action, request_id = query.data.split('_')[1:]
            requests_data = load_requests()
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            request = requests_data[request_id]
            if action == 'confirm':
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                request['client_confirmed'] = True
                save_requests(requests_data)
                delivery_id = request.get('assigned_delivery')
                if delivery_id:
                    await context.bot.send_message(
                        chat_id=delivery_id,
                        text=f"✅ Клиент подтвердил получение товара по заявке #{request_id}"
                    )
                await query.edit_message_text("✅ Вы подтвердили получение товара доставщиком.")
            elif action == 'deny':
                if 'deny_count' not in request:
                    request['deny_count'] = 1
                else:
                    request['deny_count'] += 1
                if request['deny_count'] >= 2:
                    request['status'] = 'Отклонена'
                    await query.edit_message_text("❌ Заявка отклонена по вашему запросу.")
                    for admin_id in ADMIN_IDS:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"⚠️ Клиент отказался от товара по заявке #{request_id}. Заявка отклонена."
                        )
                else:
                    request['status'] = 'Требуется проверка'
                    await query.edit_message_text("❌ Вы отказались от получения товара. Администратор уведомлен.")
                    keyboard = [[
                        InlineKeyboardButton(
                            "📞 Связаться с клиентом",
                            callback_data=f"contact_client_{request_id}"
                        )]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    for admin_id in ADMIN_IDS:
                        pickup_photos = request.get('pickup_photos', [])
                        if pickup_photos:
                            for photo_path in pickup_photos[:1]:
                                if os.path.exists(photo_path):
                                    with open(photo_path, 'rb') as photo_file:
                                        await context.bot.send_photo(
                                            chat_id=admin_id,
                                            photo=photo_file,
                                            caption=f"⚠️ Клиент отказался от товара по заявке #{request_id}",
                                            reply_markup=reply_markup
                                        )
                                break
                        else:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=f"⚠️ Клиент отказался от товара по заявке #{request_id}",
                                reply_markup=reply_markup
                            )
                save_requests(requests_data)
        except Exception as e:
            logger.error(f"Ошибка при обработке подтверждения клиента: {e}")
            await query.edit_message_text("Произошла ошибка при обработке вашего запроса.")
