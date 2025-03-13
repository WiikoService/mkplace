from telegram import Update
from telegram.ext import CallbackContext

class BaseHandler:
    def __init__(self):
        pass

    async def handle(self, update: Update, context: CallbackContext):
        raise NotImplementedError("Subclasses must implement this method")