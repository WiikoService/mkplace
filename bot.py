import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from config import *
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

def register_handlers(application):
    """Регистрирует обработчики бота"""
    # Инициализация обработчиков
    user_handler = UserHandler()
    client_handler = ClientHandler()
    admin_handler = AdminHandler()
    delivery_handler = DeliveryHandler()
    sc_handler = SCHandler()
    sc_item_handler = SCItemHandler()
    sc_management_handler = SCManagementHandler()
    
    # === БАЗОВЫЕ ОБРАБОТЧИКИ ===
    application.add_handler(CommandHandler("start", user_handler.start))
    application.add_handler(MessageHandler(filters.CONTACT, user_handler.handle_contact))
    
    # === ОБРАБОТЧИКИ КЛИЕНТА ===
    register_client_handlers(application, client_handler)
    
    # === ОБРАБОТЧИКИ СЦ ===
    register_sc_handlers(application, sc_handler, sc_item_handler)
    
    # === ОБРАБОТЧИКИ АДМИНА ===
    register_admin_handlers(application, admin_handler, sc_management_handler)
    
    # === ОБРАБОТЧИКИ ДОСТАВЩИКА ===
    register_delivery_handlers(application, delivery_handler)
    

def register_client_handlers(application, client_handler):
    """Регистрирует обработчики для клиента"""
    
    # Обработчик создания заявки
    application.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^Создать заявку$") & filters.ChatType.PRIVATE,
                client_handler.create_request
            )
        ],
        states={
            CREATE_REQUEST_CATEGORY: [
                CallbackQueryHandler(client_handler.handle_category)
            ],
            CREATE_REQUEST_DESC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_request_desc
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO,
                    client_handler.handle_request_photos
                ),
                CommandHandler(
                    "done",
                    client_handler.done_photos
                )
            ],
            CREATE_REQUEST_LOCATION: [
                MessageHandler(
                    filters.LOCATION,
                    client_handler.handle_request_location
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_request_location
                )
            ],
            CREATE_REQUEST_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_request_address
                )
            ],
            CREATE_REQUEST_DATA: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_desired_date
                )
            ],
            CREATE_REQUEST_CONFIRMATION: [
                CallbackQueryHandler(
                    client_handler.handle_request_confirmation
                )
            ]
        },
        fallbacks=[
            CommandHandler(
                "cancel",
                client_handler.cancel_request
            )
        ]
    ))
    
    # Просмотр заявок клиента
    application.add_handler(MessageHandler(
        filters.Text(["Мои заявки"]),
        client_handler.show_client_requests
    ))
    
    # Просмотр профиля клиента
    application.add_handler(MessageHandler(
        filters.Regex("^Мой профиль$"),
        client_handler.show_client_profile
    ))


def register_sc_handlers(application, sc_handler, sc_item_handler):
    """Регистрирует обработчики для сервисного центра"""
    
    # Просмотр заявок СЦ
    application.add_handler(MessageHandler(
        filters.Text(["Мои заявки"]) & filters.User(user_id=sc_handler.get_sc_ids()),
        sc_handler.show_sc_requests
    ))
    
    # Обработка выбора заявки
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_request_select,
        pattern="^sc_request_"
    ))
    
    # Начало чата с клиентом
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_chat_start,
        pattern="^sc_chat_"
    ))
    
    # Обработка комментариев
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_comment,
        pattern="^sc_comment_"
    ))
    
    # Возврат к списку заявок
    application.add_handler(CallbackQueryHandler(
        sc_handler.handle_back_to_list,
        pattern="^sc_back_to_list$"
    ))
    
    # Приемка товара
    sc_photos_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_item_handler.handle_item_acceptance,
                pattern="^accept_item_"
            )
        ],
        states={
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(filters.PHOTO, sc_item_handler.handle_photo_upload),
                CommandHandler("done", sc_item_handler.handle_photos_done)
            ]
        },
        fallbacks=[]
    )
    application.add_handler(sc_photos_handler)
    
    # Обработка отказа в приемке
    application.add_handler(CallbackQueryHandler(
        sc_item_handler.handle_item_acceptance,
        pattern="^reject_item_"
    ))
    
    # Обработка причины отказа
    application.add_handler(CallbackQueryHandler(
        sc_item_handler.handle_reject_reason,
        pattern="^reject_reason_"
    ))
    
    # Загрузка фото
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        sc_item_handler.handle_photo_upload
    ))
    
    # Завершение загрузки фото
    application.add_handler(CommandHandler(
        "done",
        sc_item_handler.handle_photos_done,
        filters.ChatType.PRIVATE
    ))


def register_admin_handlers(application, admin_handler, sc_management_handler):
    """Регистрирует обработчики для администратора"""
    # Просмотр заявок
    application.add_handler(MessageHandler(filters.Regex("^Просмотр заявок$"), admin_handler.view_requests))
    # Привязка заявки к СЦ
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
    
    # Управление СЦ
    application.add_handler(MessageHandler(filters.Regex("^Управление СЦ$"), sc_management_handler.show_sc_management))
    
    # Удаление СЦ
    application.add_handler(MessageHandler(filters.Regex("^Удалить СЦ$"), sc_management_handler.handle_delete_sc))
    application.add_handler(CallbackQueryHandler(sc_management_handler.handle_delete_sc_confirm, pattern="^delete_sc_[0-9]+"))
    application.add_handler(CallbackQueryHandler(sc_management_handler.handle_delete_sc_final, pattern="^delete_sc_confirmed_[0-9]+|delete_sc_cancel$"))

def register_delivery_handlers(application, delivery_handler):
    """Регистрирует обработчики для доставщика"""
    application.add_handler(MessageHandler(filters.Text(["Меню доставщика"]), delivery_handler.show_delivery_menu))
    application.add_handler(MessageHandler(filters.Text(["Доступные задания"]), delivery_handler.show_available_tasks))
    application.add_handler(MessageHandler(filters.Text(["Мои задания"]), delivery_handler.show_my_tasks))
    application.add_handler(MessageHandler(filters.Text(["Мой профиль"]), delivery_handler.show_delivery_profile))
    application.add_handler(CallbackQueryHandler(delivery_handler.accept_delivery, pattern=r"^accept_delivery_\d+$"))

    # Обработчик подтверждения получения доставки
    application.add_handler(CallbackQueryHandler(delivery_handler.accept_delivery, pattern=r"^confirm_pickup_\d+$"))
    application.add_handler(CallbackQueryHandler(delivery_handler.handle_delivered_to_sc, pattern=r"^delivered_to_sc_\d+$"))

def main():
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()
    register_handlers(application)
    ensure_photos_dir()
    ensure_data_dir()
    application.run_polling()

if __name__ == '__main__':
    main()
