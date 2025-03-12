import logging
import os
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from src.config import (
    ASSIGN_REQUEST, CREATE_REQUEST_DESC, CREATE_REQUEST_LOCATION,
    CREATE_REQUEST_PHOTOS, ENTER_NAME, ENTER_PHONE, TELEGRAM_API_TOKEN,
    ADMIN_IDS, DELIVERY_IDS, PHOTOS_DIR
)
from src.handlers.user_handler import UserHandler
from src.handlers.client_handler import ClientHandler
from src.handlers.admin_handler import AdminHandler
from src.handlers.delivery_handler import DeliveryHandler

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    # Создание директорий для данных
    os.makedirs(PHOTOS_DIR, exist_ok=True)

    # Создание экземпляров обработчиков
    user_handler = UserHandler()
    client_handler = ClientHandler()
    admin_handler = AdminHandler()
    delivery_handler = DeliveryHandler()

    # Создание приложения
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", user_handler.start))

    # Обработчик регистрации
    application.add_handler(MessageHandler(filters.CONTACT, user_handler.handle_contact))

    # Обработчик создания заявки
    create_request_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Создать заявку$"), client_handler.create_request)],
        states={
            CREATE_REQUEST_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_handler.handle_request_desc)],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(filters.PHOTO, client_handler.handle_request_photos),
                CommandHandler("done", client_handler.handle_request_photos_done)
            ],
            CREATE_REQUEST_LOCATION: [
                MessageHandler(filters.LOCATION, client_handler.handle_request_location),
                MessageHandler(filters.Regex("^Ввести адрес вручную$"), lambda u, c: client_handler.handle_request_location(u, c))
            ],
            CREATE_REQUEST_LOCATION + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_handler.handle_request_manual_location)]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    application.add_handler(create_request_conv_handler)

    # Обработчик просмотра заявок пользователя
    application.add_handler(MessageHandler(filters.Regex("^Мои заявки$"), client_handler.show_user_requests))

    # Обработчик просмотра всех заявок (для админа)
    application.add_handler(MessageHandler(filters.Regex("^Просмотр заявок$"), admin_handler.show_all_requests))

    # Обработчик профиля доставщика
    delivery_profile_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Профиль доставщика$"), delivery_handler.show_delivery_profile)],
        states={
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, delivery_handler.enter_name)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delivery_handler.enter_phone)]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    application.add_handler(delivery_profile_conv_handler)

    # Обработчик задач доставки
    application.add_handler(MessageHandler(filters.Regex("^Мои задания$"), delivery_handler.show_delivery_tasks))

    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(admin_handler.handle_assign_sc, pattern="^assign_sc_"))
    application.add_handler(CallbackQueryHandler(admin_handler.handle_assign_sc_confirm, pattern="^assign_sc_confirm_"))
    application.add_handler(CallbackQueryHandler(admin_handler.handle_create_delivery, pattern="^create_delivery_"))
    application.add_handler(CallbackQueryHandler(delivery_handler.handle_accept_delivery, pattern="^accept_delivery_"))
    application.add_handler(CallbackQueryHandler(delivery_handler.handle_delivered_to_client, pattern="^delivered_to_client_"))
    application.add_handler(CallbackQueryHandler(delivery_handler.handle_delivered_to_sc, pattern="^delivered_to_sc_"))

    # Запуск бота
    application.run_polling()


if __name__ == "__main__":
    main()
