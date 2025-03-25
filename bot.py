import logging

from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from config import (
    ASSIGN_REQUEST, CREATE_REQUEST_DESC, CREATE_REQUEST_LOCATION,
    CREATE_REQUEST_PHOTOS, ENTER_CONFIRMATION_CODE, TELEGRAM_API_TOKEN,
    ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK,
    CREATE_REQUEST_CATEGORY, CREATE_REQUEST_DATA, CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION, DATA_DIR,
    SC_MANAGEMENT_ADD_NAME, SC_MANAGEMENT_ADD_ADDRESS, SC_MANAGEMENT_ADD_PHONE, CREATE_REQUEST_COMMENT,
    ENTER_SC_CONFIRMATION_CODE
)
from handlers.user_handler import UserHandler
from handlers.client_handler import ClientHandler
from handlers.admin_handler import AdminHandler
from handlers.delivery_handler import DeliveryHandler
from handlers.sc_handler import SCHandler
from handlers.sc_item_handler import SCItemHandler
from handlers.admin_sc_management_handler import SCManagementHandler
from handlers.delivery_sc_handler import DeliverySCHandler

from database import ensure_data_dir
from utils import ensure_photos_dir

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
    sc_management_handler = SCManagementHandler()
    sc_item_handler = SCItemHandler()
    delivery_sc_handler = DeliverySCHandler()

    # Создание приложения
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Регистрация обработчиков
    register_client_handlers(application, client_handler, user_handler)
    register_admin_handlers(application, admin_handler, user_handler, sc_management_handler)
    register_delivery_handlers(application, delivery_handler, user_handler, delivery_sc_handler)
    register_sc_handlers(application, sc_handler, sc_item_handler)
    register_callbacks(application, delivery_handler, admin_handler, user_handler, sc_management_handler, delivery_sc_handler)

    # Обработчики команд (общие для всех)
    application.add_handler(CommandHandler("start", user_handler.start))
    application.add_handler(MessageHandler(filters.CONTACT, user_handler.handle_contact))

    # Установка данных бота
    application.bot_data["admin_ids"] = ADMIN_IDS
    application.bot_data["delivery_ids"] = DELIVERY_IDS

    # Убедимся, что директории существуют
    ensure_photos_dir()
    ensure_data_dir()

    # Запуск бота
    application.run_polling()


def register_client_handlers(application, client_handler, user_handler):

    # Обработчик меню клиента
    application.add_handler(
        MessageHandler(
            filters.Regex("^Меню клиента$"),
            user_handler.show_client_menu
        )
    )

    application.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^Создать заявку$"),
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
                MessageHandler(filters.PHOTO, client_handler.handle_request_photos),
                CommandHandler("done", client_handler.done_photos)
            ],
            CREATE_REQUEST_LOCATION: [
                MessageHandler(
                    filters.LOCATION | filters.TEXT,
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
                CallbackQueryHandler(
                    client_handler.handle_date_selection,
                    pattern="^select_date_"
                ),
                CallbackQueryHandler(
                    client_handler.handle_time_selection,
                    pattern="^select_time_"
                )
            ],
            CREATE_REQUEST_COMMENT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_request_comment
                ),
                CallbackQueryHandler(
                    client_handler.skip_comment,
                    pattern="^skip_comment$"
                )
            ],
            CREATE_REQUEST_CONFIRMATION: [
                CallbackQueryHandler(client_handler.handle_request_confirmation)
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ))
    application.add_handler(MessageHandler(filters.Regex("^Мои заявки$"), client_handler.show_client_requests))
    application.add_handler(MessageHandler(filters.Regex("^Мой профиль$"), client_handler.show_client_profile))


def register_admin_handlers(application, admin_handler, user_handler, sc_management_handler):

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
        allow_reentry=True,
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

    # Обработчик для кнопки меню "Создать задачу доставки"
    application.add_handler(MessageHandler(
        filters.Text(["Создать задачу доставки"]), 
        admin_handler.show_delivery_tasks
    ))

    # ConversationHandler для процесса создания задачи доставки
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                admin_handler.handle_create_delivery_from_sc,
                pattern="^create_delivery_"
            )
        ],
        states={
            CREATE_DELIVERY_TASK: [
                CallbackQueryHandler(
                    admin_handler.handle_create_delivery_from_sc,
                    pattern="^create_delivery_"
                )
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ))

    # В регистрации обработчиков админа
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_create_sc_delivery,
        pattern="^create_sc_delivery_"
    ))


def register_delivery_handlers(application, delivery_handler, user_handler, delivery_sc_handler):
    # Обработчики для доставщика

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

    application.add_handler(MessageHandler(
        filters.Text(["Передать в СЦ"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_handler.handle_transfer_to_sc
    ))

    application.add_handler(CallbackQueryHandler(
        delivery_sc_handler.handle_pickup_from_sc,
        pattern="^picked_up_from_sc_"
    ))

    application.add_handler(CallbackQueryHandler(
        delivery_sc_handler.handle_delivered_to_client,
        pattern="^delivered_to_client_"
    ))

    # Обработчики для доставки из СЦ
    application.add_handler(MessageHandler(
        filters.Text(["Доступные задания из СЦ"]) & filters.User(user_id=DELIVERY_IDS),
        delivery_sc_handler.show_available_sc_tasks
    ))

    sc_delivery_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_sc_handler.handle_accept_sc_delivery,
                pattern="^accept_sc_delivery_"
            )
        ],
        states={
            ENTER_SC_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    delivery_sc_handler.check_sc_confirmation_code
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO,
                    delivery_sc_handler.handle_sc_pickup_photo
                ),
                CommandHandler(
                    "done",
                    delivery_sc_handler.handle_sc_pickup_photos_done
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', delivery_handler.cancel_delivery)
        ]
    )

    application.add_handler(sc_delivery_handler)


def register_sc_handlers(application, sc_handler, sc_item_handler):
    # Обработчики для СЦ

    application.add_handler(MessageHandler(filters.Regex("^Меню СЦ$"), sc_handler.show_sc_menu))

    # Сначала регистрируем ConversationHandler для фотографий
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

    # Затем регистрируем обработчики для отказа
    application.add_handler(CallbackQueryHandler(
        sc_item_handler.handle_item_acceptance,
        pattern="^reject_item_"
    ))

    application.add_handler(CallbackQueryHandler(
        sc_item_handler.handle_reject_reason,
        pattern="^reject_reason_"
    ))

    # Обработчик списка заявок
    application.add_handler(
        MessageHandler(filters.Text("Заявки центра"), sc_handler.set_sc_requests)
    )

    # Обработчик выбора заявки
    application.add_handler(
        CallbackQueryHandler(
            sc_handler.choose_requests,
            pattern=r"^sc_request_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            sc_handler.handle_back_to_list,
            pattern="^sc_back_to_list$"
        )
    )

    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.sc_to_user_chat,
                pattern=r"^sc_chat_"
            )
        ],
        states={
            'HANDLE_SC_CHAT': [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sc_handler.handle_sc_chat),
                CallbackQueryHandler(
                    sc_handler.close_chat,
                    pattern=r"^close_chat_"
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', sc_handler.close_chat)
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    ))

    # Чат клиента
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.handle_client_reply,
                pattern=r"^client_reply_"
            )
        ],
        states={
            'HANDLE_CLIENT_REPLY': [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    sc_handler.handle_client_message
                ),
                CallbackQueryHandler(
                    sc_handler.handle_client_reply,
                    pattern=r"^client_reply_"
                ),
                CallbackQueryHandler(
                    sc_handler.cancel_client_chat,
                    pattern=r"^cancel_chat_"
                ),
                CallbackQueryHandler(
                    sc_handler.close_chat,
                    pattern=r"^close_chat_"
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', sc_handler.close_chat),
            MessageHandler(filters.ALL, lambda u,c: None)
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        },
        allow_reentry=True
    ))

    # Обработчик закрытия чата
    application.add_handler(CallbackQueryHandler(
        sc_handler.close_chat,
        pattern=r"^close_chat_"
    ))

    application.add_handler(CallbackQueryHandler(
        sc_handler.show_chat_history,
        pattern=r"^chat_history_"
    ))

    application.add_handler(MessageHandler(
        filters.Text(["Отправить в доставку"]),
        sc_handler.assign_to_delivery
    ))
    
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.handle_sc_delivery_request,
                pattern="^sc_delivery_"
            )
        ],
        states={
            ASSIGN_REQUEST: [
                CallbackQueryHandler(
                    sc_handler.handle_sc_delivery_request,
                    pattern="^sc_delivery_"
                )
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ))

    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.sc_comment,
                pattern=r"^sc_comment_"
            )
        ],
        states={
            'HANDLE_SC_COMMENT': [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sc_handler.save_comment),
            ]
        },
        fallbacks=[],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    ))

    # Добавляем обработчик для связи с администратором
    application.add_handler(MessageHandler(
        filters.Text(["Связаться с администратором"]),
        sc_handler.call_to_admin
    ))

    # Добавляем обработчик для отображения документов
    application.add_handler(MessageHandler(
        filters.Text(["Документы"]),
        sc_handler.docs
    ))


def register_callbacks(application, delivery_handler, admin_handler, user_handler, sc_management_handler, delivery_sc_handler):
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

    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_reject_request,
        pattern="^reject_request_"
    ))

    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_block_user,
        pattern="^block_user_"
    ))

    # Обновляем регистрацию обработчиков
    application.add_handler(CallbackQueryHandler(
        delivery_sc_handler.handle_pickup_from_sc,
        pattern="^picked_up_from_sc_"
    ))
    application.add_handler(CallbackQueryHandler(
        delivery_sc_handler.handle_delivered_to_client,
        pattern="^delivered_to_client_"
    ))
    application.add_handler(CallbackQueryHandler(
        delivery_sc_handler.accept_delivery_from_sc,
        pattern="^accept_sc_delivery_"
    ))

    # Добавляем ConversationHandler для обработки фото из СЦ
    sc_photo_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_sc_handler.handle_sc_confirmation,
                pattern="^sc_confirm_"
            )
        ],
        states={
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO,
                    delivery_sc_handler.handle_sc_pickup_photo
                ),
                CommandHandler("done", delivery_sc_handler.handle_sc_pickup_photos_done)
            ],
            ENTER_SC_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    delivery_sc_handler.check_sc_confirmation_code
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", delivery_handler.cancel_delivery)]
    )
    application.add_handler(sc_photo_conv_handler)


if __name__ == '__main__':
    main()
