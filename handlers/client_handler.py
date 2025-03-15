from telegram import Bot, Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import CallbackContext, ConversationHandler
from config import ADMIN_IDS, CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS, CREATE_REQUEST_LOCATION, PHOTOS_DIR
from database import load_requests, load_users, save_requests
import os

from utils import notify_admin

class ClientHandler:

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
        
        await update.message.reply_text("Опишите проблему:")
        return CREATE_REQUEST_DESC

    async def handle_request_desc(self, update: Update, context: CallbackContext):
        """Обработка описания заявки"""
        context.user_data["description"] = update.message.text
        await update.message.reply_text("Теперь пришлите фотографии проблемы. Когда закончите, отправьте /done")
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
                "longitude": update.message.location.longitude
            }
            return await self.create_request_final(update, context)
        elif update.message.text == "Ввести адрес вручную":
            await update.message.reply_text("Пожалуйста, введите адрес:")
            return CREATE_REQUEST_LOCATION
        else:
            context.user_data["location"] = update.message.text
            return await self.create_request_final(update, context)

    async def create_request_final(self, update: Update, context: CallbackContext):
        """Финальная обработка заявки."""
        requests_data = load_requests()
        request_id = str(len(requests_data) + 1)
        user_id = str(update.effective_user.id)
        users_data = load_users()
        user_name = users_data.get(user_id, {}).get('name', 'Неизвестный пользователь')
        location = context.user_data["location"]
        if isinstance(location, dict):
            latitude = location["latitude"]
            longitude = location["longitude"]
            location_link = f"https://yandex.ru/maps?whatshere%5Bpoint%5D={longitude}%2C{latitude}&"
        else:
            location_link = "Адрес введен вручную"
        requests_data[request_id] = {
            "id": request_id,
            "user_id": user_id,
            "user_name": user_name,
            "description": context.user_data["description"],
            "photos": context.user_data["photos"],
            "location": location,
            "location_link": location_link,
            "status": "Новая",
            "assigned_sc": None
        }
        save_requests(requests_data)
        await update.message.reply_text(f"Заявка #{request_id} создана. Администратор уведомлен.", reply_markup=ReplyKeyboardRemove())
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
        user_id = str(update.message.from_user.id)
        requests_data = load_requests()
        user_requests = [req for req in requests_data.values() if req["user_id"] == user_id]
        if not user_requests:
            await update.message.reply_text("У вас пока нет заявок.")
        else:
            reply = "Ваши заявки:\n\n"
            for req in user_requests:
                reply += f"Заявка #{req['id']}\n"
                reply += f"Статус: {req['status']}\n"
                reply += f"Описание: {req['description'][:50]}...\n\n"
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
