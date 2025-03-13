from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import CallbackContext, ConversationHandler
from handlers.base_handler import BaseHandler
from services.user import UserService
from services.request import RequestService
from services.notification_service import NotificationService
from config import CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS, CREATE_REQUEST_LOCATION, PHOTOS_DIR
from utils import save_photo


class ClientHandler(BaseHandler):
    def __init__(self):
        self.user_service = UserService()
        self.request_service = RequestService()
        self.notification_service = NotificationService()

    async def create_request(self, update: Update, context: CallbackContext):
        """Начало создания заявки"""
        await update.message.reply_text("Опишите проблему:")
        return CREATE_REQUEST_DESC

    async def handle_request_desc(self, update: Update, context: CallbackContext):
        """Обработка описания проблемы"""
        context.user_data["description"] = update.message.text
        await update.message.reply_text("Теперь пришлите фотографии проблемы. Когда закончите, отправьте /done")
        context.user_data["photos"] = []
        return CREATE_REQUEST_PHOTOS

    async def handle_request_photos(self, update: Update, context: CallbackContext):
        """Обработка фотографий проблемы"""
        photo_path = await save_photo(update.message, PHOTOS_DIR)
        if photo_path:
            context.user_data["photos"].append(photo_path)
            await update.message.reply_text(f"Фото #{len(context.user_data['photos'])} загружено. Отправьте еще или /done для завершения.")
        return CREATE_REQUEST_PHOTOS

    async def handle_request_photos_done(self, update: Update, context: CallbackContext):
        """Завершение загрузки фотографий"""
        if not context.user_data.get("photos"):
            await update.message.reply_text("Вы не загрузили ни одной фотографии. Пожалуйста, загрузите хотя бы одно фото.")
            return CREATE_REQUEST_PHOTOS
        keyboard = [
            [KeyboardButton("Отправить местоположение", request_location=True)],
            [KeyboardButton("Ввести адрес вручную")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        await update.message.reply_text("Теперь укажите местоположение:", reply_markup=reply_markup)
        return CREATE_REQUEST_LOCATION

    async def handle_request_location(self, update: Update, context: CallbackContext):
        """Обработка местоположения"""
        if update.message.location:
            context.user_data["location"] = {
                "latitude": update.message.location.latitude,
                "longitude": update.message.location.longitude
            }
        else:
            await update.message.reply_text("Пожалуйста, введите адрес:")
            return CREATE_REQUEST_LOCATION + 1  # Следующее состояние для ввода адреса вручную
        return await self.create_request_final(update, context)

    async def handle_request_manual_location(self, update: Update, context: CallbackContext):
        """Обработка адреса, введенного вручную"""
        context.user_data["location"] = update.message.text
        return await self.create_request_final(update, context)

    async def create_request_final(self, update: Update, context: CallbackContext):
        """Завершение создания заявки"""
        user_id = str(update.effective_user.id)
        user = await self.user_service.get_user(user_id)
        request = await self.request_service.create_request(
            user_id=user_id,
            description=context.user_data["description"],
            photos=context.user_data["photos"],
            location=context.user_data["location"],
            user_name=user.name if user else "Неизвестный пользователь"
        )
        await update.message.reply_text(
            f"Заявка #{request.id} создана. Администратор уведомлен.", 
            reply_markup=ReplyKeyboardRemove()
        )
        # Уведомление администраторов
        await self.notification_service.notify_about_new_request(update.get_bot(), request.id, request.to_dict())
        # Отправка фотографий администраторам
        from config import ADMIN_IDS
        for admin_id in ADMIN_IDS:
            for photo_path in context.user_data["photos"]:
                try:
                    with open(photo_path, 'rb') as photo:
                        await update.get_bot().send_photo(chat_id=admin_id, photo=photo)
                except Exception as e:
                    print(f"Ошибка при отправке фото администратору {admin_id}: {e}")
        
        # Отображение меню клиента после создания заявки
        await self.show_client_menu(update, context)
        return ConversationHandler.END

    async def show_user_requests(self, update: Update, context: CallbackContext):
        """Отображение заявок пользователя"""
        user_id = str(update.effective_user.id)
        requests = await self.request_service.get_user_requests(user_id)
        if not requests:
            await update.message.reply_text("У вас пока нет заявок.")
            return
        for request in requests:
            message = (
                f"Заявка #{request.id}\n"
                f"Описание: {request.description}\n"
                f"Статус: {request.status}\n"
            )
            await update.message.reply_text(message)
