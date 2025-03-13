import os

# Telegram API
TELEGRAM_API_TOKEN = "8161286312:AAEJP6NfLW9koP7_EiOnBnsF3T6Ck3OPUF8" # 7921991483:AAHM8c918j5B9rGKiegUsZCt1N89vtePJP4
ADMIN_IDS = [8195693077] # 6213103612
DELIVERY_IDS = [] # 7843162799
SC_IDS = [993108283]

# Пути к файлам
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")

# Убедимся, что директории существуют
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

# Пути к JSON файлам
USERS_JSON = os.path.join(DATA_DIR, "users.json")
REQUESTS_JSON = os.path.join(DATA_DIR, "requests.json")
SERVICE_CENTERS_JSON = os.path.join(DATA_DIR, "service_centers.json")
DELIVERY_TASKS_JSON = os.path.join(DATA_DIR, "delivery_tasks.json")

# Состояния для ConversationHandler
CREATE_REQUEST_LOCATION, ADMIN_PANEL, REGISTER, CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS, ASSIGN_REQUEST, CREATE_DELIVERY_TASK, ENTER_NAME, ENTER_PHONE = range(9)

# Статусы заказов
ORDER_STATUS_NEW = 'Новая'
ORDER_STATUS_ASSIGNED_TO_SC = 'Назначена в СЦ'
ORDER_STATUS_DELIVERY_TO_CLIENT = 'Доставщик в пути. К клиенту'
ORDER_STATUS_DELIVERY_TO_SC = 'Доставщик в пути. К СЦ'
ORDER_STATUS_IN_SC = 'В СЦ'
ORDER_STATUS_READY = 'Готов к выдаче'
ORDER_STATUS_COMPLETED = 'Завершен'
