import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from config import (
    ASSIGN_REQUEST, CREATE_REQUEST_DESC, CREATE_REQUEST_LOCATION,
    CREATE_REQUEST_PHOTOS, ENTER_CONFIRMATION_CODE, TELEGRAM_API_TOKEN,
    ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK, SC_IDS, CREATE_REQUEST_CATEGORY
)
from handlers.user_handler import UserHandler
from handlers.client_handler import ClientHandler
from handlers.admin_handler import AdminHandler
from handlers.delivery_handler import DeliveryHandler
from handlers.sc_handler import SCHandler

from utils import ensure_photos_dir

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    # Создание экземпляров обработчиков
    user_handler = UserHandler()
    client_handler = ClientHandler()
    admin_handler = AdminHandler()
    delivery_handler = DeliveryHandler()
    sc_handler = SCHandler()

    # Создание приложения
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", user_handler.start))

    # Обработчик регистрации
    application.add_handler(MessageHandler(filters.CONTACT, user_handler.handle_contact))

    # Обработчики для клиента
    application.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^Создать заявку$"), client_handler.create_request)
        ],
        states={
            CREATE_REQUEST_CATEGORY: [
                CallbackQueryHandler(client_handler.handle_category)
            ],
            CREATE_REQUEST_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_handler.handle_request_desc)
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(filters.PHOTO, client_handler.handle_request_photos),
                CommandHandler("done", client_handler.done_photos)
            ],
            CREATE_REQUEST_LOCATION: [
                MessageHandler(filters.LOCATION, client_handler.handle_request_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_handler.handle_request_location)
            ]
        },
        fallbacks=[CommandHandler("cancel", client_handler.cancel_request)]
    ))
    application.add_handler(MessageHandler(filters.Regex("^Мои заявки$"), client_handler.show_client_requests))
    application.add_handler(MessageHandler(filters.Regex("^Мой профиль$"), client_handler.show_client_profile))

    # Обработчики для администратора
    application.add_handler(MessageHandler(filters.Regex("^Просмотр заявок$"), admin_handler.view_requests))
    application.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^Привязать к СЦ$") & filters.User(user_id=ADMIN_IDS),
                admin_handler.assign_request
            ),
            CallbackQueryHandler(
                admin_handler.handle_assign_sc,
                pattern="^assign_sc_(?!confirm)"  # Исключаем паттерн с confirm
            )
        ],
        states={
            ASSIGN_REQUEST: [
                CallbackQueryHandler(
                    admin_handler.handle_assign_sc_confirm,
                    pattern="^assign_sc_confirm_"
                )
            ],
            CREATE_DELIVERY_TASK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    admin_handler.handle_create_delivery_input
                )
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ))
    application.add_handler(MessageHandler(
        filters.Regex("^Список СЦ$") & filters.User(user_id=ADMIN_IDS), 
        admin_handler.view_service_centers
    ))
    # Обработчики для доставщика
    delivery_handler = DeliveryHandler()

    application.add_handler(MessageHandler(
        filters.Text(["Меню доставщика"]) & filters.User(user_id=DELIVERY_IDS),
        user_handler.show_delivery_menu
    ))

    application.add_handler(MessageHandler(
        filters.Text(["Доступные задания"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_handler.show_available_tasks
    ))

    application.add_handler(MessageHandler(
        filters.Text(["Мои задания"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_handler.show_my_tasks
    ))

    application.add_handler(MessageHandler(
        filters.Text(["Мой профиль"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_handler.show_delivery_profile
    ))

    # Обработчики для СЦ
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_item_acceptance,
        pattern="^(accept|reject)_item_"
    ))

    application.add_handler(MessageHandler(
        filters.PHOTO & filters.User(user_id=SC_IDS),
        sc_handler.handle_photo_upload
    ))

    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(
        delivery_handler.accept_delivery,
        pattern="^accept_delivery_"
    ))

    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_handler.handle_confirm_pickup,
                pattern="^confirm_pickup_"
            )
        ],
        states={
            ENTER_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    delivery_handler.handle_confirmation_code
                )
            ]
        },
        fallbacks=[]
    ))

    delivery_photos_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_handler.handle_delivered_to_sc,
                pattern=r"delivered_to_sc_\d+"
            )
        ],
        states={
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(filters.PHOTO, delivery_handler.handle_delivery_photo),
                CommandHandler("done", delivery_handler.handle_delivery_photos_done)
            ]
        },
        fallbacks=[]
    )

    application.add_handler(delivery_photos_handler)

    application.add_handler(CallbackQueryHandler(
        delivery_handler.handle_client_confirmation,
        pattern="^client_(confirm|deny)_"
    ))

    application.add_handler(MessageHandler(
        filters.Text(["Передать в СЦ"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_handler.handle_transfer_to_sc
    ))

    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_reject_request,
        pattern="^reject_request_"
    ))

    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_block_user,
        pattern="^block_user_"
    ))

    # Добавление обработчиков меню для разных ролей
    application.add_handler(MessageHandler(filters.Regex("^Меню клиента$"), user_handler.show_client_menu))
    application.add_handler(MessageHandler(filters.Regex("^Админская панель$"), user_handler.show_admin_menu))

    # Установка данных бота
    application.bot_data["admin_ids"] = ADMIN_IDS
    application.bot_data["delivery_ids"] = DELIVERY_IDS

    # Убедимся, что директория для фотографий существует
    ensure_photos_dir()
    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()
