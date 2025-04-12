import logging

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.getLogger('handlers').setLevel(logging.INFO)
logging.getLogger('utils').setLevel(logging.INFO)

# Отключаем шумные логи от библиотек
for lib in ['asyncio', 'httpcore', 'httpx', 'telegram', 'aiohttp']:
    logging.getLogger(lib).setLevel(logging.ERROR)

from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from config import (
    ASSIGN_REQUEST, CREATE_REQUEST_DESC, CREATE_REQUEST_LOCATION,
    CREATE_REQUEST_PHOTOS, ENTER_CONFIRMATION_CODE, TELEGRAM_API_TOKEN,
    ADMIN_IDS, DELIVERY_IDS, CREATE_DELIVERY_TASK,
    CREATE_REQUEST_CATEGORY, CREATE_REQUEST_DATA, CREATE_REQUEST_ADDRESS, 
    CREATE_REQUEST_CONFIRMATION,
    SC_MANAGEMENT_ADD_NAME, SC_MANAGEMENT_ADD_ADDRESS, SC_MANAGEMENT_ADD_PHONE, CREATE_REQUEST_COMMENT,
    ENTER_SC_CONFIRMATION_CODE, ENTER_REPAIR_PRICE, CONFIRMATION,
    RATING_SERVICE, FEEDBACK_TEXT,
    WAITING_PAYMENT,
    WAITING_FINAL_PAYMENT
)
from handlers.user_handler import UserHandler
from handlers.client_handler import ClientHandler
from handlers.admin_handler import AdminHandler
from handlers.delivery_handler import DeliveryHandler
from handlers.sc_handler import SCHandler
from handlers.sc_item_handler import SCItemHandler
from handlers.admin_sc_management_handler import SCManagementHandler
from handlers.delivery_sc_handler import DeliverySCHandler
from handlers.sc_chat_handler import SCChatHandler
from handlers.client_request_create import RequestCreator, PrePaymentHandler
from handlers.final_payment_handler import FinalPaymentHandler

from database import ensure_data_dir, load_users
from utils import ensure_photos_dir

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
    sc_chat_handler = SCChatHandler()
    request_creator = RequestCreator()
    pre_payment_handler = PrePaymentHandler()
    final_payment_handler = FinalPaymentHandler()
    # Создание приложения
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()
    # Регистрация обработчиков
    register_client_handlers(application, client_handler, user_handler, request_creator, 
                           delivery_handler, admin_handler, pre_payment_handler, final_payment_handler)
    register_admin_handlers(application, admin_handler, user_handler, sc_handler, sc_management_handler)
    register_delivery_handlers(application, delivery_handler, admin_handler, user_handler, 
                             delivery_sc_handler, final_payment_handler)
    register_sc_handlers(application, sc_handler, sc_item_handler, sc_chat_handler)
    register_callbacks(application, delivery_handler, admin_handler, delivery_sc_handler, client_handler)
    register_user_handlers(application, user_handler)
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

def register_client_handlers(application, client_handler, user_handler, request_creator, delivery_handler, admin_handler, pre_payment_handler, final_payment_handler):
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
                request_creator.create_request
            )
        ],
        states={
            CREATE_REQUEST_CATEGORY: [
                CallbackQueryHandler(request_creator.handle_category)
            ],
            CREATE_REQUEST_DESC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    request_creator.handle_request_desc
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(filters.PHOTO, request_creator.handle_request_photos),
                MessageHandler(filters.Regex("^Завершить отправку фото$"), request_creator.done_photos),
                CommandHandler("done", request_creator.done_photos)
            ],
            CREATE_REQUEST_LOCATION: [
                MessageHandler(
                    filters.LOCATION | filters.TEXT,
                    request_creator.handle_request_location
                )
            ],
            CREATE_REQUEST_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    request_creator.handle_request_address
                )
            ],
            CREATE_REQUEST_DATA: [
                CallbackQueryHandler(
                    request_creator.handle_date_selection,
                    pattern="^select_date_"
                ),
                CallbackQueryHandler(
                    request_creator.handle_time_selection,
                    pattern="^select_time_"
                )
            ],
            CREATE_REQUEST_COMMENT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    request_creator.handle_request_comment
                ),
                CallbackQueryHandler(
                    request_creator.skip_comment,
                    pattern="^skip_comment$"
                )
            ],
            CREATE_REQUEST_CONFIRMATION: [
                CallbackQueryHandler(request_creator.handle_request_confirmation)
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ))
    application.add_handler(CallbackQueryHandler(
        pre_payment_handler.handle_payment_cancel,
        pattern="^payment_cancel$"
    ))
    # Создаем ConversationHandler для процесса оплаты
    payment_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                admin_handler.handle_client_price_approved,
                pattern="^client_initial_price_"
            )
        ],
        states={
            WAITING_PAYMENT: [
                CallbackQueryHandler(
                    pre_payment_handler.check_payment_status,
                    pattern="^check_payment_"
                ),
                CallbackQueryHandler(
                    pre_payment_handler.handle_payment_cancel,
                    pattern="^payment_cancel_"
                )
            ]
        },
        fallbacks=[],
        name="payment_conversation"
    )
    application.add_handler(payment_conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^Мои заявки$"), client_handler.show_client_requests))
    application.add_handler(MessageHandler(filters.Regex("^Мой профиль$"), client_handler.show_client_profile))
    # Обработчик для полного процесса оценки
    rating_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                client_handler.request_service_rating,
                pattern=r"^rate_service_"
            ),
            CallbackQueryHandler(
                client_handler.start_rating_conversation,
                pattern=r"^rate_\d+_"
            )
        ],
        states={
            RATING_SERVICE: [
                CallbackQueryHandler(
                    client_handler.handle_rating,
                    pattern=r"^rate_\d+_"
                )
            ],
            FEEDBACK_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    client_handler.handle_feedback
                )
            ]
        },
        fallbacks=[
            CommandHandler("cancel", client_handler.cancel_operation)
        ],
        name="rating_conversation",
        persistent=False,
        allow_reentry=True
    )
    application.add_handler(rating_handler)
    # Обработчик документов для клиентов
    application.add_handler(MessageHandler(
        filters.Regex("^Документы$"),
        client_handler.show_documents
    ))
    # Добавляем ConversationHandler для обработки кода подтверждения после подтверждения клиентом
    client_confirmation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_handler.handle_client_confirmation,
                pattern="^client_confirm_"
            )
        ],
        states={
            ENTER_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{4}$'),
                    delivery_handler.pickup_client_code_confirmation
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", delivery_handler.cancel_delivery)]
    )
    application.add_handler(client_confirmation_handler)
    # Добавляем отдельный обработчик для отказа от получения товара
    application.add_handler(CallbackQueryHandler(
        delivery_handler.handle_client_confirmation,
        pattern="^client_deny_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_reject_request,
        pattern="^reject_request_"
    ))

def register_admin_handlers(application, admin_handler, user_handler, sc_handler, sc_management_handler):
    # Обработчики для администратора
    application.add_handler(MessageHandler(filters.Regex("^Просмотр заявок$"), admin_handler.view_requests))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_assign_sc,
        pattern="^assign_sc_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_send_to_sc,
        pattern="^send_to_sc_"
    ))
    # Обработчик календаря задач доставки
    application.add_handler(MessageHandler(
        filters.Regex("^Календарь$") & filters.User(user_id=ADMIN_IDS),
        admin_handler.show_delivery_calendar
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
    application.add_handler(
        MessageHandler(
            filters.Text(["Новые заявки"]) & filters.User(user_id=ADMIN_IDS),
            admin_handler.show_new_requests
        )
    )
    # Обработчик для кнопки меню "Создать задачу доставки"
    application.add_handler(MessageHandler(
        filters.Text(["Создать задачу доставки"]), 
        admin_handler.show_delivery_tasks
    ))
    # ConversationHandler для процесса создания задачи доставки
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                admin_handler.handle_create_sc_delivery,
                pattern="^create_delivery_"
            )
        ],
        states={
            CREATE_DELIVERY_TASK: [
                CallbackQueryHandler(
                    admin_handler.handle_create_sc_delivery,
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
    # Добавляем обработчики для обратной связи
    application.add_handler(
        MessageHandler(
            filters.Text(["Обратная связь"]) & filters.User(user_id=ADMIN_IDS),
            admin_handler.show_feedback
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin_handler.show_reviews,
            pattern="^show_reviews$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin_handler.show_feedback,
            pattern="^back_to_stats$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            user_handler.show_admin_menu,
            pattern="^back_to_admin$"
        )
    )
    # Добавляем обработчик просмотра чата
    chat_view_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Просмотр чата заявки$"), admin_handler.view_request_chat)],
        states={
            'WAITING_REQUEST_ID': [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handler.view_request_chat)
            ]
        },
        fallbacks=[]
    )
    application.add_handler(chat_view_handler)
    # Регистрация обработчиков для согласования цены
    application.add_handler(CallbackQueryHandler(admin_handler.handle_price_approval, pattern="^send_price_approval_"))
    application.add_handler(CallbackQueryHandler(user_handler.handle_client_price_approval, pattern="^client_initial_price_"))
    application.add_handler(CallbackQueryHandler(user_handler.handle_client_price_rejection, pattern="^client_initial_reject_"))
    # Регистрация обработчиков для комментариев
    application.add_handler(CallbackQueryHandler(admin_handler.handle_comment_approval, pattern="^approve_comment_"))
    application.add_handler(CallbackQueryHandler(admin_handler.handle_comment_rejection, pattern="^reject_comment_"))
    # Обработчик документов для СЦ
    application.add_handler(MessageHandler(
        filters.Regex("^Документы$"),
        sc_handler.docs
    ))

def register_delivery_handlers(application, delivery_handler, admin_handler, user_handler, delivery_sc_handler, final_payment_handler):
    # Группа обработчиков для доставщиков (только для пользователей из DELIVERY_IDS)
    delivery_user_filter = filters.User(user_id=DELIVERY_IDS)
    # Основное меню доставщика
    application.add_handler(MessageHandler(
        filters.Text(["Меню доставщика"]) & delivery_user_filter,
        user_handler.show_delivery_menu
    ))
    # Задачи доставки
    application.add_handler(MessageHandler(
        filters.Text(["Доступные задания"]) & delivery_user_filter,
        delivery_handler.show_available_tasks
    ))
    application.add_handler(MessageHandler(
        filters.Text(["Мои задания"]) & delivery_user_filter,
        delivery_handler.show_my_tasks
    ))
    application.add_handler(MessageHandler(
        filters.Text(["Мой профиль"]) & delivery_user_filter,
        delivery_handler.show_delivery_profile
    ))
    application.add_handler(MessageHandler(
        filters.Text(["Передать в СЦ"]) & delivery_user_filter,
        delivery_handler.handle_transfer_to_sc
    ))
    application.add_handler(MessageHandler(
        filters.Text(["Доступные задания из СЦ"]) & delivery_user_filter,
        delivery_sc_handler.show_available_sc_tasks
    ))
    # Обработчики callback-запросов для доставки
    application.add_handler(CallbackQueryHandler(
        delivery_handler.handle_client_confirmation,
        pattern="^client_deny_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_reject_request,
        pattern="^reject_request_"
    ))
    application.add_handler(CallbackQueryHandler(
        final_payment_handler._create_payment,
        pattern="^create_payment_"
    ))
    # ConversationHandler для подтверждения получения от клиента
    pickup_photos_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_handler.handle_confirm_pickup,
                pattern="^confirm_pickup_"
            )
        ],
        states={
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO & delivery_user_filter,
                    delivery_handler.handle_pickup_photo
                ),
                CommandHandler(
                    "done",
                    delivery_handler.handle_pickup_photos_done
                )
            ],
            ENTER_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{4}$') & delivery_user_filter,
                    delivery_handler.pickup_client_code_confirmation
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", delivery_handler.cancel_delivery)],
        name="pickup_photos_conversation"
    )
    application.add_handler(pickup_photos_handler)
    # ConversationHandler для доставки в СЦ
    delivery_photos_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_handler.handle_delivered_to_sc,
                pattern=r"delivered_to_sc_\d+"
            )
        ],
        states={
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO & delivery_user_filter,
                    delivery_handler.handle_delivery_photo
                ),
                CommandHandler(
                    "done",
                    delivery_handler.handle_delivery_photos_done
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", delivery_handler.cancel_delivery)],
        name="delivery_photos_conversation"
    )
    application.add_handler(delivery_photos_handler)
    # ConversationHandler для подтверждения от СЦ
    sc_confirmation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_sc_handler.handle_sc_pickup_confirmation,
                pattern="^request_sc_confirmation_"
            )
        ],
        states={
            ENTER_SC_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{4}$') & delivery_user_filter,
                    delivery_sc_handler.check_sc_confirmation_code
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO & delivery_user_filter,
                    delivery_sc_handler.handle_sc_photos_after_pickup
                ),
                CommandHandler(
                    "done",
                    delivery_sc_handler.handle_sc_photos_done
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', delivery_handler.cancel_delivery)
        ],
        name="sc_confirmation_conversation"
    )
    application.add_handler(sc_confirmation_handler)
    # ConversationHandler для доставки из СЦ
    sc_delivery_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                delivery_sc_handler.handle_accept_sc_delivery,
                pattern=r"^sc_delivery_accept_(\d+)$"
            ),
            CallbackQueryHandler(
                delivery_sc_handler.handle_get_sc_confirmation,
                pattern="^get_sc_confirmation_"
            ),
            CallbackQueryHandler(
                delivery_sc_handler.handle_pickup_from_sc,
                pattern="^pickedup_from_sc_"
            )
        ],
        states={
            ENTER_SC_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{4}$') & delivery_user_filter,
                    delivery_sc_handler.check_sc_confirmation_code
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO & delivery_user_filter,
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
        ],
        name="sc_delivery_conversation"
    )
    application.add_handler(sc_delivery_handler)
    # ConversationHandler для финальной оплаты
    final_payment_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                final_payment_handler.handle_deliver_to_client,
                pattern="^deliver_to_client_"
            )
        ],
        states={
            ENTER_CONFIRMATION_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{4}$') & delivery_user_filter,
                    final_payment_handler.handle_client_confirmation_code
                )
            ],
            WAITING_FINAL_PAYMENT: [
                CallbackQueryHandler(
                    final_payment_handler.check_final_payment,
                    pattern="^check_final_payment_"
                ),
                CallbackQueryHandler(
                    final_payment_handler.cancel_final_payment,
                    pattern="^cancel_final_payment_"
                )
            ],
            CREATE_REQUEST_PHOTOS: [
                MessageHandler(
                    filters.PHOTO & delivery_user_filter,
                    final_payment_handler.handle_delivery_photo
                ),
                CommandHandler(
                    "done",
                    final_payment_handler.handle_delivery_photos_done
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', delivery_handler.cancel_delivery)
        ],
        name="final_payment_conversation"
    )
    application.add_handler(final_payment_conv_handler)

def register_sc_handlers(application, sc_handler, sc_item_handler, sc_chat_handler):
    # Обработчики для СЦ
    application.add_handler(MessageHandler(filters.Regex("^Меню СЦ$"), sc_handler.show_sc_menu))
    # 1. Обработчик кнопки "Принять заявку" от СЦ - самый высокий приоритет
    application.add_handler(
        CallbackQueryHandler(
            sc_handler.handle_request_notification,
            pattern=r"^sc_accept_"
        ),
        group=0
    )
    # 2. Обработчик для ввода стоимости ремонта - только для сообщений не от доставщиков
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^\d+$") & 
            ~filters.User(user_id=DELIVERY_IDS) &
            filters.ChatType.PRIVATE,
            sc_handler.handle_repair_price
        ),
        group=1
    )
    # 3. Обработчик нажатия кнопки "Принять с указанной стоимостью"
    application.add_handler(
        CallbackQueryHandler(
            sc_handler.confirm_repair_price,
            pattern=r"^accept_request_price_"
        ),
        group=0
    )
    # Регистрация обработчиков для согласования итоговой цены ремонта клиентом
    application.add_handler(CallbackQueryHandler(
        sc_handler.price_handler.handle_sc_final_price_approval,
        pattern="^sc_final_approve_price_"
    ))
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.price_handler.handle_sc_final_price_rejection,
                pattern="^sc_final_reject_price_"
            )
        ],
        states={
            'HANDLE_CLIENT_REPLY': [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
                    sc_chat_handler.handle_client_message
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', sc_chat_handler.close_chat)
        ],
        allow_reentry=True
    ))
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
                sc_chat_handler.sc_to_user_chat,
                pattern=r"^sc_chat_"
            )
        ],
        states={
            'HANDLE_SC_CHAT': [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sc_chat_handler.handle_sc_chat),
                MessageHandler(filters.PHOTO, sc_chat_handler.handle_sc_chat),
                CallbackQueryHandler(
                    sc_chat_handler.close_chat,
                    pattern=r"^close_chat_"
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', sc_chat_handler.close_chat)
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    ))
    # Чат клиента
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_chat_handler.handle_client_reply,
                pattern=r"^client_reply_"
            ),
            CallbackQueryHandler(
                sc_chat_handler.handle_start_dispute,
                pattern=r"^start_dispute_"
            ),
            CallbackQueryHandler(
                sc_chat_handler.handle_close_dispute,
                pattern=r"^close_dispute_"
            )
        ],
        states={
            'HANDLE_CLIENT_REPLY': [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
                    sc_chat_handler.handle_client_message
                ),
                CallbackQueryHandler(
                    sc_chat_handler.handle_client_reply,
                    pattern=r"^client_reply_"
                ),
                CallbackQueryHandler(
                    sc_chat_handler.cancel_client_chat,
                    pattern=r"^cancel_chat_"
                ),
                CallbackQueryHandler(
                    sc_chat_handler.close_chat,
                    pattern=r"^close_chat_"
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', sc_chat_handler.close_chat),
            MessageHandler(filters.ALL, lambda u,c: None)
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        },
        allow_reentry=True
    ))
    # Обработчик закрытия чата
    application.add_handler(CallbackQueryHandler(
        sc_chat_handler.close_chat,
        pattern=r"^close_chat_"
    ))
    application.add_handler(CallbackQueryHandler(
        sc_chat_handler.show_chat_history,
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
    # Обработчики для выбора даты и времени доставки
    sc_delivery_date_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(sc_handler.handle_sc_delivery_request, pattern="^sc_delivery_")],
        states={
            'SC_SELECT_DELIVERY_DATE': [
                CallbackQueryHandler(sc_handler.handle_sc_date_selection, pattern="^sc_select_date_")
            ],
            'SC_SELECT_DELIVERY_TIME': [
                CallbackQueryHandler(sc_handler.handle_sc_time_selection, pattern="^sc_select_time_")
            ]
        },
        fallbacks=[CommandHandler('cancel', sc_handler.cancel)]
    )
    application.add_handler(sc_delivery_date_handler)
    # Регистрация обработчика для создания задачи доставки из СЦ к клиенту
    application.add_handler(CallbackQueryHandler(
        sc_handler.create_return_delivery,
        pattern="^create_return_delivery_"
    ))
    # Регистрация обработчиков для подтверждения цены
    application.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                sc_handler.price_handler.start_price_confirmation,
                pattern=r"^confirm_price_"
            )
        ],
        states={
            ENTER_REPAIR_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    sc_handler.price_handler.handle_price_input
                )
            ],
            CONFIRMATION: [
                CallbackQueryHandler(
                    sc_handler.price_handler.confirm_price,
                    pattern=r"^confirm_price_"
                ),
                CallbackQueryHandler(
                    sc_handler.price_handler.change_price,
                    pattern=r"^change_price_"
                )
            ]
        },
        fallbacks=[],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    ))

def register_callbacks(application, delivery_handler, admin_handler, delivery_sc_handler, client_handler):
    # Обработчики для календаря задач доставки
    application.add_handler(CallbackQueryHandler(
        admin_handler.show_tasks_by_date,
        pattern="^calendar_date_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.back_to_calendar,
        pattern="^back_to_calendar$"
    ))
    application.add_handler(CallbackQueryHandler(
        delivery_handler.accept_delivery,
        pattern=r"^accept_delivery_|^accept_sc_delivery_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_reject_request,
        pattern="^reject_request_"
    ))
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_block_user,
        pattern="^block_user_"
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
    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_contact_client,
        pattern="^contact_client_"
    ))

def register_user_handlers(application, user_handler):
    # Обработчики для выбора даты и времени доставки
    delivery_date_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                user_handler.handle_delivery_date_selection,
                pattern="^select_delivery_date_"
            )
        ],
        states={
            'SELECT_DELIVERY_TIME': [
                CallbackQueryHandler(
                    user_handler.handle_delivery_time_selection,
                    pattern="^select_delivery_time_"
                )
            ],
            'CONFIRM_DELIVERY_TIME': [
                CallbackQueryHandler(
                    user_handler.handle_delivery_time_confirmation,
                    pattern="^confirm_delivery_time_"
                )
            ]
        },
        fallbacks=[]
    )
    application.add_handler(delivery_date_handler)


if __name__ == '__main__':
    main()
