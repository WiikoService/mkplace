import logging

from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from config import (
    ASSIGN_REQUEST, CREATE_REQUEST_DESC, CREATE_REQUEST_LOCATION,
    CREATE_REQUEST_PHOTOS, ENTER_CONFIRMATION_CODE, TELEGRAM_API_TOKEN,
    ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK, SC_IDS,
    CREATE_REQUEST_CATEGORY, CREATE_REQUEST_DATA, CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION, DATA_DIR,
    SC_MANAGEMENT_ADD_NAME, SC_MANAGEMENT_ADD_ADDRESS, SC_MANAGEMENT_ADD_PHONE
)
from handlers.user_handler import UserHandler
from handlers.client_handler import ClientHandler
from handlers.admin_handler import AdminHandler
from handlers.delivery_handler import DeliveryHandler
from handlers.sc_handler import SCHandler
from handlers.admin_sc_management_handler import SCManagementHandler
from handlers.sc_item_handler import SCItemHandler

from database import ensure_data_dir
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
    sc_item_handler = SCItemHandler()
    sc_management_handler = SCManagementHandler()

    # Создание приложения
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", user_handler.start))

    # Обработчик регистрации
    application.add_handler(MessageHandler(filters.CONTACT, user_handler.handle_contact))

    # Обработчики для СЦ (должны быть зарегистрированы ДО обработчиков клиента)
    application.add_handler(MessageHandler(
        filters.Text(["Мои заявки"]) & filters.User(user_id=SC_IDS),
        sc_handler.show_sc_requests
    ))

    # Обработчики для выбора заявки СЦ и действий с ней
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_request_select,
        pattern="^sc_request_"
    ))
    
    # Обработчик для чата с клиентом
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_chat_start,
        pattern="^sc_chat_"
    ))
    
    # Обработчик для добавления комментария
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_comment,
        pattern="^sc_comment_"
    ))
    
    # Обработчик для возврата к списку заявок
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_back_to_list,
        pattern="^sc_back_to_list$"
    ))
    
    # Обработчик для текста сообщения в чате
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(user_id=SC_IDS),
        sc_handler.handle_chat_message,
        block=False
    ))
    
    # Обработчик для текста комментария
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(user_id=SC_IDS),
        sc_handler.handle_comment_text,
        block=False
    ))
    
    # Обработчики для клиента (регистрируются ПОСЛЕ обработчиков СЦ)
    application.add_handler(MessageHandler(
        filters.Text(["Мои заявки"]) & ~filters.User(user_id=SC_IDS),
        client_handler.show_client_requests
    ))
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
        filters.Regex("^Управление СЦ$") & filters.User(user_id=ADMIN_IDS),
        sc_management_handler.show_sc_management
    ))
    application.add_handler(MessageHandler(
        filters.Regex("^Список СЦ$") & filters.User(user_id=ADMIN_IDS),
        sc_management_handler.view_service_centers
    ))
    application.add_handler(MessageHandler(
        filters.Regex("^Админская панель$") & filters.User(user_id=ADMIN_IDS),
        user_handler.show_admin_menu
    ))

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

    # Обработчики для приемки товара СЦ (перемещены в sc_item_handler)
    application.add_handler(CallbackQueryHandler(
        sc_item_handler.handle_item_acceptance,
        pattern="^accept_item_|^reject_item_"  # Изменяем паттерн, чтобы он не конфликтовал
    ))

    application.add_handler(MessageHandler(
        filters.PHOTO & filters.User(user_id=SC_IDS),
        sc_item_handler.handle_photo_upload
    ))

    application.add_handler(CommandHandler(
        "done", 
        sc_item_handler.handle_photos_done, 
        filters.User(user_id=SC_IDS)
    ))

    # Добавление обработчиков меню для разных ролей
    application.add_handler(MessageHandler(filters.Regex("^Меню клиента$"), user_handler.show_client_menu))

    # Обработчик добавления СЦ
    application.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^Добавить СЦ$") & filters.User(user_id=ADMIN_IDS),
                sc_management_handler.handle_add_sc_start
            )
        ],
        states={
            SC_MANAGEMENT_ADD_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    sc_management_handler.handle_add_sc_name
                )
            ],
            SC_MANAGEMENT_ADD_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    sc_management_handler.handle_add_sc_address
                )
            ],
            SC_MANAGEMENT_ADD_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    sc_management_handler.handle_add_sc_phone
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", sc_management_handler.cancel)]
    ))
    
    # Обработчик удаления СЦ
    application.add_handler(MessageHandler(
        filters.Regex("^Удалить СЦ$") & filters.User(user_id=ADMIN_IDS),
        sc_management_handler.handle_delete_sc
    ))
    
    # Обработчики для подтверждения удаления СЦ
    application.add_handler(CallbackQueryHandler(
        sc_management_handler.handle_delete_sc_confirm,
        pattern="^delete_sc_[0-9]+"
    ))
    
    application.add_handler(CallbackQueryHandler(
        sc_management_handler.handle_delete_sc_final,
        pattern="^delete_sc_confirmed_[0-9]+|delete_sc_cancel$"
    ))

    # Установка данных бота
    application.bot_data["admin_ids"] = ADMIN_IDS
    application.bot_data["delivery_ids"] = DELIVERY_IDS

    # Убедимся, что директории существуют
    ensure_photos_dir()
    ensure_data_dir()
    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()
