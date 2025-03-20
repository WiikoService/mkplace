from telegram import Update
from telegram.ext import CallbackContext

# TODO: сделать базовый конструктор и передавать простейшие аргументы


class BaseHandler:
    """Базовый класс для всех обработчиков"""
    def __init__(self):
        pass

    async def handle(self, update: Update, context: CallbackContext):
        raise NotImplementedError("Subclasses must implement this method")
