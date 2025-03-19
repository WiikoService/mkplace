from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from config import SC_IDS, ADMIN_IDS, ORDER_STATUS_IN_SC, CREATE_REQUEST_PHOTOS
from handlers.base_handler import BaseHandler
from database import load_requests, save_requests, load_users, load_delivery_tasks, save_delivery_tasks
from utils import notify_client
import logging

logger = logging.getLogger(__name__)


class SCHandler(BaseHandler):

    async def cancel(self, update: Update, context: CallbackContext):
        """Отмена операции"""
        await update.message.reply_text("Операция отменена.")
        return ConversationHandler.END
