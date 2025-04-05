import os
from datetime import datetime, timedelta
import json

from telegram.ext import CallbackContext, ConversationHandler
from telegram import (
    Bot, Update, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery
)

from config import (
    ADMIN_IDS, CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS,
    CREATE_REQUEST_LOCATION, PHOTOS_DIR, CREATE_REQUEST_CATEGORY,
    CREATE_REQUEST_DATA, CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION,
    CREATE_REQUEST_COMMENT, RATING_SERVICE, FEEDBACK_TEXT, ORDER_STATUS_DELIVERY_TO_SC
)
from database import load_requests, load_users, save_requests, DATA_DIR, load_delivery_tasks
from utils import notify_admin, get_address_from_coords, format_location_for_display, prepare_location_for_storage
import logging

logger = logging.getLogger(__name__)


class ClientHandler:
    category = [  # TODO: определить список категорий
        'Ремонт телефонов', 'Ремонт телевизоров',
        'Ремонт обуви', 'Ремонт одежды', 'Ремонт мебели',
        'Ремонт техники', 'Прочее'
    ]

    async def create_request(self, update: Update, context: CallbackContext):
        """Создание заявки."""
        user_id = str(update.effective_user.id)
        users_data = load_users()
        user = users_data.get(user_id, {})
        if user.get('blocked'):
            await update.message.reply_text(
                "Извините, но вы не можете создавать заявки, так как ваш аккаунт заблокирован."
            )
            return ConversationHandler.END
        keyboard = [
            [InlineKeyboardButton(
                self.category[i], callback_data=f"category_{i}")
                ] for i in range(len(self.category))]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите категорию:", reply_markup=reply_markup)
        return CREATE_REQUEST_CATEGORY

    async def handle_category(self, update: Update, context: CallbackContext):
        """Обработка выбора категории"""
        query = update.callback_query
        await query.answer()
        category_index = int(query.data.split('_')[1])
        context.user_data["category"] = self.category[category_index]
        await query.edit_message_text(text=f"Вы выбрали категорию: {context.user_data['category']}")
        await query.message.reply_text("Подробно опишите проблему:")
        return CREATE_REQUEST_DESC

    async def handle_request_desc(self, update: Update, context: CallbackContext):
        """Обработка описания проблемы."""
        context.user_data["description"] = update.message.text
        await update.message.reply_text(
            "Описание проблемы сохранено.\n"
            "Теперь пришлите фотографии проблемы. Когда закончите, отправьте /done"
        )
        context.user_data["photos"] = []
        return CREATE_REQUEST_PHOTOS

    async def handle_request_photos(self, update: Update, context: CallbackContext):
        """Обработка фотографий заявки."""
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_name = f"{update.effective_user.id}_{len(context.user_data['photos'])}.jpg"
        file_path = os.path.join(PHOTOS_DIR, file_name)
        await file.download_to_drive(file_path)
        context.user_data["photos"].append(file_path)
        return CREATE_REQUEST_PHOTOS

    async def done_photos(self, update: Update, context: CallbackContext):
        """Обработка завершения фотографий заявки"""
        keyboard = [
            [KeyboardButton(text="Отправить местоположение", request_location=True)],
            [KeyboardButton(text="Ввести адрес вручную")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(
            "Отлично! Теперь отправьте свое местоположение или выберите 'Ввести адрес вручную':",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_LOCATION

    async def handle_request_location(self, update: Update, context: CallbackContext):
        """Обработка местоположения заявки."""
        try:
            if update.message.location:
                # Получаем координаты
                latitude = update.message.location.latitude
                longitude = update.message.location.longitude
                
                # Получаем адрес по координатам
                address = get_address_from_coords(latitude, longitude)
                
                # Сохраняем все данные
                context.user_data["location"] = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "address": address,
                    "type": "coordinates"
                }
                
                # Показываем кнопки с датами
                return await self.show_date_buttons(update.message)
                
            elif update.message.text == "Ввести адрес вручную":
                await update.message.reply_text(
                    "Пожалуйста, введите адрес:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return CREATE_REQUEST_ADDRESS
                
        except Exception as e:
            logger.error(f"Error handling location: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке местоположения. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_LOCATION

    async def show_date_buttons(self, message):
        """Показывает инлайн-кнопки с датами"""
        keyboard = []
        current_date = datetime.now()
        
        # Добавляем кнопки для следующих 7 дней
        for i in range(7):
            date = current_date + timedelta(days=i)
            date_display = date.strftime("%d.%m.%Y")  # Формат для отображения
            date_value = date.strftime("%d.%m.%Y")    # Формат для callback_data
            keyboard.append([
                InlineKeyboardButton(
                    f"📅 {date_display}",
                    callback_data=f"select_date_{date_value}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "Выберите желаемую дату:",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_DATA

    async def handle_request_address(self, update: Update, context: CallbackContext):
        """Обработка ввода адреса вручную."""
        try:
            address = update.message.text.strip()
            if not address:
                await update.message.reply_text("Пожалуйста, введите корректный адрес.")
                return CREATE_REQUEST_ADDRESS
                
            context.user_data["location"] = {
                "address": address,
                "type": "manual"
            }
            
            # Показываем кнопки с датами
            return await self.show_date_buttons(update.message)
            
        except Exception as e:
            logger.error(f"Error handling address: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке адреса. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_ADDRESS

    async def handle_date_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора даты из инлайн-кнопок"""
        query = update.callback_query
        await query.answer()
        
        # Получаем выбранную дату из callback_data (формат "дд.мм.гггг")
        selected_date = query.data.split('_', 2)[2]
        # Сохраняем дату в формате "дд.мм.гггг" для последующего использования
        context.user_data["selected_date"] = selected_date
        
        # Создаем клавиатуру с временными интервалами
        keyboard = []
        current_hour = 9  # Начинаем с 9 утра
        while current_hour <= 20:  # До 20:00
            time_str = f"{current_hour:02d}:00"
            keyboard.append([
                InlineKeyboardButton(
                    f"🕐 {time_str}",
                    callback_data=f"select_time_{time_str}"
                )
            ])
            current_hour += 1
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите удобное время:",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_DATA

    async def handle_time_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора времени"""
        query = update.callback_query
        await query.answer()
        
        # Получаем выбранное время (формат "ЧЧ:ММ")
        selected_time = query.data.split('_', 2)[2]
        
        # Получаем сохраненную дату (формат "дд.мм.гггг")
        selected_date = context.user_data.get("selected_date")
        
        if not selected_date:
            await query.edit_message_text(
                "Ошибка: не найдена выбранная дата. Пожалуйста, начните заново."
            )
            return ConversationHandler.END
        
        try:
            # Комбинируем дату и время
            date_obj = datetime.strptime(selected_date, "%d.%m.%Y")
            time_obj = datetime.strptime(selected_time, "%H:%M")
            
            # Создаем финальную дату с выбранным временем
            final_datetime = date_obj.replace(
                hour=time_obj.hour,
                minute=time_obj.minute
            )
            context.user_data["desired_date"] = final_datetime
            
            # Очищаем временные данные
            if "selected_date" in context.user_data:
                del context.user_data["selected_date"]
            
            await query.message.delete()
            # Передаем query вместо query.message
            return await self.show_confirmation(query, context)
        except ValueError as e:
            logger.error(f"Ошибка обработки даты/времени: {e}")
            await query.edit_message_text(
                "Произошла ошибка при обработке времени. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_DATA

    async def show_confirmation(self, update: Update, context: CallbackContext):
        """Показ сводки данных и запрос комментария."""
        try:
            message = update.message if hasattr(update, 'message') else update.callback_query.message
            
            # Получаем данные из контекста
            category = context.user_data.get("category", "Не указана")
            description = context.user_data.get("description", "Не указано")
            desired_date = context.user_data.get("desired_date", "Не указана")
            location = context.user_data.get("location", {})
            
            # Форматируем местоположение
            location_str = format_location_for_display(location)
            
            summary = (
                f"📝 Проверьте данные заявки:\n\n"
                f"🔹 Категория: {category}\n"
                f"🔹 Описание: {description}\n"
                f"🔹 Адрес: {location_str}\n"
                f"🔹 Дата и время: {desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else 'Не указана'}\n\n"
                "Добавьте комментарий к заявке или нажмите 'Пропустить':"
            )
            
            keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_comment")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if isinstance(update, CallbackQuery):
                try:
                    await update.edit_message_text(summary, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    await update.message.reply_text(summary, reply_markup=reply_markup)
            else:
                await message.reply_text(summary, reply_markup=reply_markup)
            
            return CREATE_REQUEST_COMMENT
            
        except Exception as e:
            logger.error(f"Error in show_confirmation: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при отображении подтверждения. Пожалуйста, начните заново."
            )
            return ConversationHandler.END

    async def skip_comment(self, update: Update, context: CallbackContext):
        """Пропуск комментария"""
        query = update.callback_query
        await query.answer()
        context.user_data["comment"] = "Не указано"
        
        # Получаем и форматируем местоположение
        location = context.user_data.get("location", {})
        if isinstance(location, dict):
            if location.get("type") == "coordinates":
                address = location.get("address", "Адрес не определен")
                location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
            else:
                location_str = location.get("address", "Адрес не указан")
        else:
            location_str = str(location)
        
        # Форматируем дату
        desired_date = context.user_data.get("desired_date")
        date_str = desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else "Не указана"
        
        summary = (
            "📝 Итоговые данные заявки:\n\n"
            f"Категория: {context.user_data.get('category', 'Не указана')}\n"
            f"Описание: {context.user_data.get('description', 'Не указано')}\n"
            f"Адрес: {location_str}\n"
            f"Дата: {date_str}\n"
            f"Комментарий: {context.user_data.get('comment', 'Не указано')}\n\n"
            "Подтвердите создание заявки или начните заново."
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_request")],
            [InlineKeyboardButton("🔄 Изменить", callback_data="restart_request")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(summary, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error editing message in skip_comment: {e}")
            # Fallback - отправляем новое сообщение
            await query.message.reply_text(summary, reply_markup=reply_markup)
        
        return CREATE_REQUEST_CONFIRMATION

    async def handle_request_comment(self, update: Update, context: CallbackContext):
        """Обработка комментария клиента"""
        try:
            context.user_data["comment"] = update.message.text
            
            # Получаем и форматируем местоположение
            location = context.user_data.get("location", {})
            if isinstance(location, dict):
                if location.get("type") == "coordinates":
                    address = location.get("address", "Адрес не определен")
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get("address", "Адрес не указан")
            else:
                location_str = str(location)
            
            # Форматируем дату
            desired_date = context.user_data.get("desired_date")
            date_str = desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else "Не указана"
            
            summary = (
                "📝 Итоговые данные заявки:\n\n"
                f"Категория: {context.user_data.get('category', 'Не указана')}\n"
                f"Описание: {context.user_data.get('description', 'Не указано')}\n"
                f"Адрес: {location_str}\n"
                f"Дата: {date_str}\n"
                f"Комментарий: {context.user_data.get('comment', 'Не указано')}\n\n"
                "Подтвердите создание заявки или начните заново."
            )
            
            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_request")],
                [InlineKeyboardButton("🔄 Изменить", callback_data="restart_request")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(summary, reply_markup=reply_markup)
            return CREATE_REQUEST_CONFIRMATION
            
        except Exception as e:
            logger.error(f"Error in handle_request_comment: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке комментария. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_COMMENT

    async def handle_request_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения или отмены заявки."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm_request": 
            return await self.create_request_final(query, context)
        elif query.data == "restart_request":
            await query.message.reply_text("Начинаем заново.")
            return await self.create_request(update, context)

    async def create_request_final(self, query: CallbackQuery, context: CallbackContext):
        """Финальная обработка заявки."""
        try:
            requests_data = load_requests()
            request_id = str(len(requests_data) + 1)
            user_id = str(query.from_user.id)
            users_data = load_users()
            user_name = users_data.get(user_id, {}).get('name', 'Неизвестный пользователь')
            
            # Получаем и форматируем местоположение
            location = context.user_data.get("location", {})
            location_display = format_location_for_display(location)
            
            # Создаем ссылку на карту для координат
            location_link = ""
            if isinstance(location, dict) and location.get("type") == "coordinates":
                lat = location.get("latitude")
                lon = location.get("longitude")
                if lat and lon:
                    location_link = f"https://yandex.ru/maps/?pt={lon},{lat}&z=16&l=map"
            
            desired_date = context.user_data.get("desired_date")
            desired_date_str = desired_date.strftime("%H:%M %d.%m.%Y") if desired_date else "Не указана"
            
            # Сохраняем заявку
            requests_data[request_id] = {
                "id": request_id,
                "user_id": user_id,
                "user_name": user_name,
                "category": context.user_data.get("category"),
                "description": context.user_data.get("description"),
                "photos": context.user_data.get("photos", []),
                "location": prepare_location_for_storage(location),
                "location_display": location_display,
                "location_link": location_link,
                "status": "Новая",
                "assigned_sc": None,
                "desired_date": desired_date_str,
                "comment": context.user_data.get("comment", "")
            }
            
            save_requests(requests_data)
            
            # Уведомляем пользователя
            await query.message.reply_text(
                f"✅ Заявка #{request_id} создана\n"
                "Администратор уведомлен.", 
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Уведомляем администраторов
            await notify_admin(context.bot, request_id, requests_data, ADMIN_IDS)
            
            # Отправляем фотографии администраторам
            for admin_id in ADMIN_IDS:
                for photo_path in context.user_data.get("photos", []):
                    try:
                        with open(photo_path, 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=admin_id, 
                                photo=photo,
                                caption=f"Фото к заявке #{request_id}"
                            )
                    except Exception as e:
                        logger.error(f"Error sending photo to admin {admin_id}: {e}")
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in create_request_final: {e}")
            await query.message.reply_text(
                "Произошла ошибка при создании заявки. Пожалуйста, попробуйте еще раз."
            )
            return ConversationHandler.END

    async def cancel_request(self, update: Update, context: CallbackContext):
        """Отмена создания заявки."""
        await update.message.reply_text("Создание заявки отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

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
        
        # Фильтруем заявки пользователя
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
        
        # Сортируем заявки по дате создания (новые сверху)
        sorted_requests = sorted(
            user_requests.items(),
            key=lambda x: x[1].get('timestamp', ''),
            reverse=True
        )
        
        # Отправляем каждую заявку отдельным сообщением с кнопками
        for req_id, req_data in sorted_requests:
            status = req_data.get('status', 'Неизвестно')
            description = req_data.get('description', 'Без описания')
            category = req_data.get('category', 'Не указана')
            location = req_data.get('location', {})
            
            # Обрабатываем location
            if isinstance(location, dict):
                address = location.get('address', 'Адрес не указан')
                if location.get("type") == "coordinates":
                    address = "📍 Геолокация"
            else:
                address = str(location)
            
            # Формируем сообщение
            message = (
                f"🔹 <b>Заявка #{req_id}</b>\n"
                f"📋 <b>Категория:</b> {category}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"📍 <b>Адрес:</b> {address}\n"
                f"📊 <b>Статус:</b> {status}\n"
            )
            
            # Добавляем дату создания, если есть
            if 'timestamp' in req_data:
                message += f"📅 <b>Дата создания:</b> {req_data['timestamp']}\n"
            
            keyboard = []
            
            # Добавляем кнопку "Открыть спор" для заявок со статусом "Доставлено клиенту"
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
        """
        Отображение доступных документов для клиента
        TODO: можно реализовать логику отображения документов для клиента
        """
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
        # Создаем клавиатуру со звездами для оценки в столбик для удобства
        keyboard = [
            [InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_5_{request_id}")],
            [InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_4_{request_id}")],
            [InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_3_{request_id}")],
            [InlineKeyboardButton("⭐⭐", callback_data=f"rate_2_{request_id}")],
            [InlineKeyboardButton("⭐", callback_data=f"rate_1_{request_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌟 Пожалуйста, оцените качество обслуживания:",
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
        # Сохраняем рейтинг в файл
        self._save_rating(rating)
        # Если оценка меньше 4, запрашиваем обратную связь
        if rating < 4:
            await query.edit_message_text(
                f"Спасибо за оценку!\n\n"
                f"Мы стремимся стать лучше. Пожалуйста, расскажите, что мы могли бы улучшить:"
            )
            # Добавляем логирование
            logger.info(f"Запрошена обратная связь после оценки {rating} для заявки {request_id}")
            return FEEDBACK_TEXT
        else:
            # Для хороших оценок просто благодарим
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
            # Добавляем логирование
            logger.info(f"Получен отзыв: {feedback_text}")
            # Сохраняем отзыв
            self._save_feedback(feedback_text)
            logger.info("Отзыв сохранен успешно")
            # Отправляем подтверждение
            await update.message.reply_text(
                "✅ Спасибо за ваш отзыв! Мы учтем ваши комментарии для улучшения нашего сервиса."
            )
            # Завершаем ConversationHandler
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Ошибка при обработке отзыва: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении отзыва. Пожалуйста, попробуйте еще раз."
            )
            return FEEDBACK_TEXT

    def _save_rating(self, rating): # TODO: переписать в database.py
        """Сохраняет оценку в JSON-файл"""
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        # Загружаем существующие данные или создаем новые
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                feedback_data = {'ratings': [], 'reviews': []}
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            feedback_data = {'ratings': [], 'reviews': []}
        # Добавляем новую оценку
        feedback_data['ratings'].append({
            'rating': rating,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        # Сохраняем данные
        try:
            with open(feedback_file, 'w', encoding='utf-8') as f:
                json.dump(feedback_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении оценки: {e}")

    def _save_feedback(self, feedback_text): # TODO: переписать в database.py
        """Сохраняет отзыв в JSON-файл"""
        feedback_file = os.path.join(DATA_DIR, 'feedback.json')
        # Загружаем существующие данные
        try:
            if os.path.exists(feedback_file):
                with open(feedback_file, 'r', encoding='utf-8') as f:
                    feedback_data = json.load(f)
            else:
                feedback_data = {'ratings': [], 'reviews': []}
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла обратной связи: {e}")
            feedback_data = {'ratings': [], 'reviews': []}
        # Добавляем новый отзыв
        feedback_data['reviews'].append({
            'id': len(feedback_data['reviews']) + 1,
            'text': feedback_text,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        # Сохраняем данные
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
        # Извлекаем рейтинг
        data_parts = query.data.split('_')
        rating = int(data_parts[1])
        request_id = data_parts[2]
        # Сохраняем рейтинг в файл
        self._save_rating(rating)
        # Сохраняем данные для следующего шага
        context.user_data['current_rating'] = rating
        context.user_data['current_request_id'] = request_id
        # Добавляем визуализацию звезд
        stars = "⭐" * rating
        # Если оценка меньше 4, запрашиваем обратную связь
        if rating < 4:
            await query.edit_message_text(
                f"Спасибо за оценку {stars}!\n\n"
                f"Мы стремимся стать лучше. Пожалуйста, расскажите, что мы могли бы улучшить:"
            )
            logger.info(f"Запрошена обратная связь после оценки {rating} для заявки {request_id}")
            return FEEDBACK_TEXT
        else:
            # Для хороших оценок просто благодарим
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
            delivery_tasks = load_delivery_tasks()
            users_data = load_users()
            
            if request_id not in requests_data:
                await query.edit_message_text("❌ Заявка не найдена")
                return
            
            request = requests_data[request_id]
            
            if action == 'confirm':
                # Клиент подтвердил получение
                request['status'] = ORDER_STATUS_DELIVERY_TO_SC
                request['client_confirmed'] = True
                save_requests(requests_data)
                
                # Уведомляем доставщика
                delivery_id = request.get('assigned_delivery')
                if delivery_id:
                    await context.bot.send_message(
                        chat_id=delivery_id,
                        text=f"✅ Клиент подтвердил получение товара по заявке #{request_id}"
                    )
                
                await query.edit_message_text("✅ Вы подтвердили получение товара доставщиком.")
                
            elif action == 'deny':
                # Клиент отказался от получения
                if 'deny_count' not in request:
                    request['deny_count'] = 1
                else:
                    request['deny_count'] += 1
                    
                if request['deny_count'] >= 2:
                    # При втором отказе отклоняем заявку
                    request['status'] = 'Отклонена'
                    await query.edit_message_text("❌ Заявка отклонена по вашему запросу.")
                    
                    # Уведомляем администратора
                    for admin_id in ADMIN_IDS:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"⚠️ Клиент отказался от товара по заявке #{request_id}. Заявка отклонена."
                        )
                else:
                    # При первом отказе уведомляем администратора
                    request['status'] = 'Требуется проверка'
                    await query.edit_message_text("❌ Вы отказались от получения товара. Администратор уведомлен.")
                    
                    # Отправляем уведомление администратору с кнопкой "Связаться с клиентом"
                    keyboard = [[
                        InlineKeyboardButton(
                            "📞 Связаться с клиентом",
                            callback_data=f"contact_client_{request_id}"
                        )]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    for admin_id in ADMIN_IDS:
                        # Отправляем фотографии администратору
                        pickup_photos = request.get('pickup_photos', [])
                        if pickup_photos:
                            for photo_path in pickup_photos[:1]:  # Отправляем только первое фото
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
