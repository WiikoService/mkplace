from datetime import datetime

from telegram import (
    Bot, Update, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from telegram.ext import CallbackContext, ConversationHandler
from config import (
    ADMIN_IDS, CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS,
    CREATE_REQUEST_LOCATION, PHOTOS_DIR, CREATE_REQUEST_CATEGORY,
    CREATE_REQUEST_DATA, CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION,
    DATA_DIR, USERS_JSON, REQUESTS_JSON
)
from database import load_requests, load_users, save_requests
import os

from utils import notify_admin

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
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text(
            "Отлично! Теперь отправьте свое местоположение или выберите 'Ввести адрес вручную':",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_LOCATION

    async def handle_request_location(self, update: Update, context: CallbackContext):
        """Обработка местоположения заявки."""
        if update.message.location:
            context.user_data["location"] = {
                "latitude": update.message.location.latitude,
                "longitude": update.message.location.longitude,
                "type": "coordinates"
            }
            await update.message.reply_text(
                "Теперь введите желаемую дату и время в формате 00:00 01.03.2025:"
            )
            return CREATE_REQUEST_DATA
        elif update.message.text == "Ввести адрес вручную":
            await update.message.reply_text("Пожалуйста, введите адрес:")
            return CREATE_REQUEST_ADDRESS
        else:
            context.user_data["location"] = {
                "address": update.message.text,
                "type": "manual"
            }
            await update.message.reply_text(
                "Теперь введите желаемую дату и время в формате 00:00 01.03.2025:"
            )
            return CREATE_REQUEST_DATA

    async def handle_request_address(self, update: Update, context: CallbackContext):
        """Обработка ввода адреса вручную."""
        context.user_data["location"] = update.message.text
        await update.message.reply_text(
            "Адрес сохранен.\n"
            "Теперь введите желаемую дату и время в формате 00:00 01.03.2025:"
        )
        return CREATE_REQUEST_DATA

    async def handle_desired_date(self, update: Update, context: CallbackContext):
        """Обработка желаемой даты и времени."""
        desired_date_str = update.message.text
        try:
            desired_date = datetime.strptime(desired_date_str, "%H:%M %d.%m.%Y")
            context.user_data["desired_date"] = desired_date
            await update.message.reply_text("Желаемая дата и время сохранены.")
            return await self.show_confirmation(update, context)  # Переход к подтверждению
        except ValueError:
            await update.message.reply_text("Неверный формат. Пожалуйста, введите дату в формате 00:00 01.03.2025")
            return CREATE_REQUEST_DATA

    async def show_confirmation(self, update: Update, context: CallbackContext):
        """Показ сводки данных и запрос подтверждения."""
        category = context.user_data.get("category", "Не указана")
        description = context.user_data.get("description", "Не указано")
        location = context.user_data.get("location", "Не указано")
        desired_date = context.user_data.get("desired_date", "Не указана")

        if isinstance(location, dict):
            if location.get("type") == "coordinates":
                location_str = f"Широта: {location.get('latitude', 'N/A')}, Долгота: {location.get('longitude', 'N/A')}"
            else:
                location_str = location.get("address", "Адрес не указан")
        else:
            location_str = location

        summary = (
            f"Категория: {category}\n"
            f"Описание: {description}\n"
            f"Адрес: {location_str}\n"
            f"Желаемая дата и время: {desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else 'Не указана'}\n\n"
            "Подтвердите создание заявки или начните заново."
        )
        keyboard = [
            [InlineKeyboardButton("Подтвердить", callback_data="confirm_request")],
            [InlineKeyboardButton("Изменить", callback_data="restart_request")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(summary, reply_markup=reply_markup)
        return CREATE_REQUEST_CONFIRMATION


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
        requests_data = load_requests()
        request_id = str(len(requests_data) + 1)
        user_id = str(query.from_user.id)
        users_data = load_users()
        user_name = users_data.get(user_id, {}).get('name', 'Неизвестный пользователь')
        location = context.user_data["location"]
        
        if isinstance(location, dict):
            if location.get("type") == "coordinates":
                latitude = location["latitude"]
                longitude = location["longitude"]
                location_display = f"Координаты: {latitude}, {longitude}"
                location_link = f"https://yandex.ru/maps?whatshere%5Bpoint%5D={longitude}%2C{latitude}&"
            else:
                location_display = location.get("address", "Адрес не указан")
                location_link = "Адрес введен вручную"
        else:
            location_display = location
            location_link = "Адрес введен вручную"

        desired_date = context.user_data.get("desired_date")
        desired_date_str = desired_date.strftime("%H:%M %d.%m.%Y")
        
        requests_data[request_id] = {
            "id": request_id,
            "user_id": user_id,
            "user_name": user_name,
            "description": context.user_data["description"],
            "photos": context.user_data["photos"],
            "location": location,
            "location_display": location_display,
            "location_link": location_link,
            "status": "Новая",
            "assigned_sc": None,
            "desired_date": desired_date_str
        }
        save_requests(requests_data)
        await query.message.reply_text(
            f"Заявка #{request_id} создана.\n"
            "Администратор уведомлен.", reply_markup=ReplyKeyboardRemove())
        await notify_admin(context.bot, request_id, requests_data, ADMIN_IDS)
        for admin_id in ADMIN_IDS:
            for photo_path in context.user_data["photos"]:
                with open(photo_path, 'rb') as photo:
                    await context.bot.send_photo(chat_id=admin_id, photo=photo)
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
        reply += f"Роль: {user.get('role', 'Клиент')}\n"
        if not user.get('name') or not user.get('phone'):
            reply += "\nДля полной регистрации, пожалуйста, нажмите кнопку 'Регистрация'."
            keyboard = [[KeyboardButton("Регистрация", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(reply, reply_markup=reply_markup)
        else:
            await update.message.reply_text(reply)

    async def show_client_requests(self, update: Update, context: CallbackContext):
        """Отображение заявок клиента."""
        user_id = str(update.effective_user.id)
        requests_data = load_requests()
        user_requests = [req for req in requests_data.values() if req["user_id"] == user_id]
        if not user_requests:
            await update.message.reply_text("У вас пока нет заявок.")
        else:
            reply = "Ваши заявки:\n\n"
            for req in user_requests:
                reply += f"Заявка #{req['id']}\n"
                reply += f"Статус: {req['status']}\n"
                reply += f"Описание: {req['description'][:50]}...\n"
                
                location = req.get('location', {})
                if isinstance(location, dict):
                    if location.get("type") == "coordinates":
                        reply += f"Адрес: {location['latitude']}, {location['longitude']}\n"
                    else:
                        reply += f"Адрес: {location.get('address', 'Не указан')}\n"
                else:
                    reply += f"Адрес: {location}\n"
                
                reply += "\n"
            
            await update.message.reply_text(reply)

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
        message = "Доступные документы:\n\n"
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
