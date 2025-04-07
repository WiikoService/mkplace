import os
from datetime import datetime, timedelta
import locale

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from config import (
    CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS, CREATE_REQUEST_LOCATION,
    PHOTOS_DIR, CREATE_REQUEST_CATEGORY, CREATE_REQUEST_DATA,
    CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION, CREATE_REQUEST_COMMENT
)
from database import load_requests, load_users, save_requests
from utils import notify_admin, get_address_from_coords, format_location_for_display, prepare_location_for_storage
import logging
from handlers.client_handler import ClientHandler
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


class RequestCreator(ClientHandler):
    category = [
        'Ремонт телефонов', 'Ремонт телевизоров',
        'Ремонт обуви', 'Ремонт одежды', 'Ремонт мебели',
        'Ремонт техники', 'Прочее'
    ]

    async def create_request(self, update: Update, context: CallbackContext):
        """Создание заявки."""
        user_id = str(update.effective_user.id)
        users_data = load_users()
        user = users_data.get(user_id, {})
        if user.get('blocked'):
            await update.message.reply_text(
                "Извините, но вы не можете создавать заявки, так как ваш аккаунт заблокирован."
            )
            return ConversationHandler.END
        keyboard = [
            [InlineKeyboardButton(
                self.category[i], callback_data=f"category_{i}")
                ] for i in range(len(self.category))]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите категорию:", reply_markup=reply_markup)
        return CREATE_REQUEST_CATEGORY

    async def handle_category(self, update: Update, context: CallbackContext):
        """Обработка выбора категории"""
        query = update.callback_query
        await query.answer()
        if query.data == 'approve':
            await query.edit_message_text(text="Заявка подтверждена")
            return ConversationHandler.END
        try:
            category_index = int(query.data.split('_')[1])
            context.user_data["category"] = self.category[category_index]
            await query.edit_message_text(text=f"Вы выбрали категорию: {context.user_data['category']}")
            await query.message.reply_text("Подробно опишите проблему:")
            return CREATE_REQUEST_DESC
        except (ValueError, IndexError):
            logger.error(f"Неверный формат callback_data: {query.data}")
            await query.edit_message_text(text="Произошла ошибка. Пожалуйста, попробуйте снова.")
            return ConversationHandler.END

    async def handle_request_desc(self, update: Update, context: CallbackContext):
        """Обработка описания проблемы."""
        context.user_data["description"] = update.message.text
        await update.message.reply_text(
            "Описание проблемы сохранено.\n"
            "Теперь пришлите фотографии проблемы (обязательно хотя бы одно фото).\n"
            "Когда закончите отправлять фото, нажмите\n\n/DONE"
        )
        context.user_data["photos"] = []
        return CREATE_REQUEST_PHOTOS

    async def handle_request_photos(self, update: Update, context: CallbackContext):
        """Обработка фотографий заявки."""
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_name = f"{update.effective_user.id}_{len(context.user_data['photos'])}.jpg"
        file_path = os.path.join(PHOTOS_DIR, file_name)
        await file.download_to_drive(file_path)
        context.user_data["photos"].append(file_path)
        await update.message.reply_text(
            "Фото сохранено! Можете отправить еще фото или нажмите\n\n/DONE"
        )
        return CREATE_REQUEST_PHOTOS

    async def done_photos(self, update: Update, context: CallbackContext):
        """Обработка завершения фотографий заявки"""
        if not context.user_data.get("photos") or len(context.user_data["photos"]) == 0:
            await update.message.reply_text(
                "Вы не отправили ни одной фотографии.\nПожалуйста, отправьте хотя бы одно фото.\n"
                "Когда закончите отправлять фото, нажмите:\n\n/DONE"
            )
            return CREATE_REQUEST_PHOTOS
            
        keyboard = [
            [KeyboardButton(text="Отправить местоположение", request_location=True)],
            [KeyboardButton(text="Ввести адрес вручную")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(
            f"Получено {len(context.user_data['photos'])} фото. Теперь отправьте свое местоположение или выберите 'Ввести адрес вручную':",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_LOCATION

    async def handle_request_location(self, update: Update, context: CallbackContext):
        """Обработка местоположения заявки."""
        try:
            if update.message.location:
                latitude = update.message.location.latitude
                longitude = update.message.location.longitude
                status_message = await update.message.reply_text(
                    "⏳ Определяю адрес по локации...",
                    reply_markup=ReplyKeyboardRemove()
                )
                address = await get_address_from_coords(latitude, longitude)
                try:
                    await status_message.delete()
                except:
                    pass
                context.user_data["location"] = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "address": address
                }
                return await self.show_date_buttons(update.message)
            elif update.message.text == "Ввести адрес вручную":
                await update.message.reply_text(
                    "Пожалуйста, введите адрес:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return CREATE_REQUEST_ADDRESS
        except Exception as e:
            logger.error(f"Error handling location: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке местоположения. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_LOCATION

    async def show_date_buttons(self, message):
        """Показывает инлайн-кнопки с датами с указанием дня недели на русском"""
        try:
            locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, 'ru_RU')
            except locale.Error:
                try:
                    locale.setlocale(locale.LC_TIME, 'Russian')
                except locale.Error:
                    pass
        keyboard = []
        current_date = datetime.now()
        for i in range(7):
            date = current_date + timedelta(days=i)
            date_display = date.strftime("%d.%m (%A)")
            date_value = date.strftime("%d.%m.%Y")
            keyboard.append([
                InlineKeyboardButton(
                    f"📅 {date_display}",
                    callback_data=f"select_date_{date_value}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "Выберите желаемую дату:",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_DATA

    async def handle_request_address(self, update: Update, context: CallbackContext):
        """Обработка ввода адреса вручную."""
        try:
            address = update.message.text.strip()
            if not address:
                await update.message.reply_text("Пожалуйста, введите корректный адрес.")
                return CREATE_REQUEST_ADDRESS
                
            context.user_data["location"] = {
                "address": address
            }
            return await self.show_date_buttons(update.message)
        except Exception as e:
            logger.error(f"Error handling address: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке адреса. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_ADDRESS

    async def handle_date_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора даты из инлайн-кнопок"""
        query = update.callback_query
        await query.answer()
        selected_date = query.data.split('_', 2)[2]
        context.user_data["selected_date"] = selected_date
        keyboard = []
        current_hour = 9
        while current_hour <= 20:
            time_str = f"{current_hour:02d}:00"
            keyboard.append([
                InlineKeyboardButton(
                    f"🕐 {time_str}",
                    callback_data=f"select_time_{time_str}"
                )
            ])
            current_hour += 1
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Выберите удобное время:",
            reply_markup=reply_markup
        )
        return CREATE_REQUEST_DATA

    async def handle_time_selection(self, update: Update, context: CallbackContext):
        """Обработка выбора времени"""
        query = update.callback_query
        await query.answer()
        selected_time = query.data.split('_', 2)[2]
        selected_date = context.user_data.get("selected_date")
        if not selected_date:
            await query.edit_message_text(
                "Ошибка: не найдена выбранная дата. Пожалуйста, начните заново."
            )
            return ConversationHandler.END
        try:
            date_obj = datetime.strptime(selected_date, "%d.%m.%Y")
            time_obj = datetime.strptime(selected_time, "%H:%M")
            final_datetime = date_obj.replace(
                hour=time_obj.hour,
                minute=time_obj.minute
            )
            context.user_data["desired_date"] = final_datetime
            if "selected_date" in context.user_data:
                del context.user_data["selected_date"]
            await query.message.delete()
            return await self.show_confirmation(query, context)
        except ValueError as e:
            logger.error(f"Ошибка обработки даты/времени: {e}")
            await query.edit_message_text(
                "Произошла ошибка при обработке времени. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_DATA

    async def show_confirmation(self, update: Update, context: CallbackContext):
        """Показ сводки данных и запрос комментария."""
        try:
            message = update.message if hasattr(update, 'message') else update.callback_query.message
            category = context.user_data.get("category", "Не указана")
            description = context.user_data.get("description", "Не указано")
            desired_date = context.user_data.get("desired_date", "Не указана")
            location = context.user_data.get("location", {})
            location_str = format_location_for_display(location)
            summary = (
                f"📝 Проверьте данные заявки:\n\n"
                f"Категория: {category}\n"
                f"Описание: {description}\n"
                f"Адрес: {location_str}\n"
                f"Дата и время: {desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else 'Не указана'}\n\n"
                "Добавьте комментарий к заявке или нажмите 'Пропустить':"
            )
            keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_comment")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if isinstance(update, CallbackQuery):
                try:
                    await update.edit_message_text(summary, reply_markup=reply_markup)
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    await update.message.reply_text(summary, reply_markup=reply_markup)
            else:
                await message.reply_text(summary, reply_markup=reply_markup)
            return CREATE_REQUEST_COMMENT
        except Exception as e:
            logger.error(f"Error in show_confirmation: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при отображении подтверждения. Пожалуйста, начните заново."
            )
            return ConversationHandler.END

    async def skip_comment(self, update: Update, context: CallbackContext):
        """Пропуск комментария"""
        query = update.callback_query
        await query.answer()
        context.user_data["comment"] = "Не указано"
        location = context.user_data.get("location", {})
        if isinstance(location, dict):
            if location.get("type") == "coordinates":
                address = location.get("address", "Адрес не определен")
                location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
            else:
                location_str = location.get("address", "Адрес не указан")
        else:
            location_str = str(location)
        desired_date = context.user_data.get("desired_date")
        date_str = desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else "Не указана"
        summary = (
            "📝 Итоговые данные заявки:\n\n"
            f"Категория: {context.user_data.get('category', 'Не указана')}\n"
            f"Описание: {context.user_data.get('description', 'Не указано')}\n"
            f"Адрес: {location_str}\n"
            f"Дата: {date_str}\n"
            f"Комментарий: {context.user_data.get('comment', 'Не указано')}\n\n"
            "Подтвердите создание заявки или начните заново."
        )
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_request")],
            [InlineKeyboardButton("🔄 Изменить", callback_data="restart_request")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(summary, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error editing message in skip_comment: {e}")
            await query.message.reply_text(summary, reply_markup=reply_markup)
        return CREATE_REQUEST_CONFIRMATION

    async def handle_request_comment(self, update: Update, context: CallbackContext):
        """Обработка комментария клиента"""
        try:
            context.user_data["comment"] = update.message.text
            location = context.user_data.get("location", {})
            if isinstance(location, dict):
                if location.get("type") == "coordinates":
                    address = location.get("address", "Адрес не определен")
                    location_str = f"{address} (координаты: {location.get('latitude')}, {location.get('longitude')})"
                else:
                    location_str = location.get("address", "Адрес не указан")
            else:
                location_str = str(location)
            desired_date = context.user_data.get("desired_date")
            date_str = desired_date.strftime('%H:%M %d.%m.%Y') if isinstance(desired_date, datetime) else "Не указана"
            summary = (
                "📝 Итоговые данные заявки:\n\n"
                f"Категория: {context.user_data.get('category', 'Не указана')}\n"
                f"Описание: {context.user_data.get('description', 'Не указано')}\n"
                f"Адрес: {location_str}\n"
                f"Дата: {date_str}\n"
                f"Комментарий: {context.user_data.get('comment', 'Не указано')}\n\n"
                "Подтвердите создание заявки или начните заново."
            )
            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_request")],
                [InlineKeyboardButton("🔄 Изменить", callback_data="restart_request")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(summary, reply_markup=reply_markup)
            return CREATE_REQUEST_CONFIRMATION
        except Exception as e:
            logger.error(f"Error in handle_request_comment: {e}")
            await update.message.reply_text(
                "Произошла ошибка при обработке комментария. Пожалуйста, попробуйте еще раз."
            )
            return CREATE_REQUEST_COMMENT

    async def handle_request_confirmation(self, update: Update, context: CallbackContext):
        """Обработка подтверждения или отмены заявки."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm_request": 
            return await self.create_request_final(query, context)
        elif query.data == "restart_request":
            await query.message.reply_text("Начинаем заново.")
            return await self.create_request(update, context)

    async def create_request_final(self, query: CallbackQuery, context: CallbackContext):
        """Финальная обработка заявки."""
        try:
            requests_data = load_requests()
            request_id = str(len(requests_data) + 1)
            user_id = str(query.from_user.id)
            users_data = load_users()
            user_name = users_data.get(user_id, {}).get('name', 'Неизвестный пользователь')
            location = context.user_data.get("location", {})
            location_display = format_location_for_display(location)
            location_link = ""
            if isinstance(location, dict) and location.get("type") == "coordinates":
                lat = location.get("latitude")
                lon = location.get("longitude")
                if lat and lon:
                    location_link = f"https://yandex.ru/maps/?pt={lon},{lat}&z=16&l=map"
            desired_date = context.user_data.get("desired_date")
            desired_date_str = desired_date.strftime("%H:%M %d.%m.%Y") if desired_date else "Не указана"
            requests_data[request_id] = {
                "id": request_id,
                "user_id": user_id,
                "user_name": user_name,
                "category": context.user_data.get("category"),
                "description": context.user_data.get("description"),
                "photos": context.user_data.get("photos", []),
                "location": prepare_location_for_storage(location),
                "location_display": location_display,
                "location_link": location_link,
                "status": "Новая",
                "assigned_sc": None,
                "desired_date": desired_date_str,
                "comment": context.user_data.get("comment", "")
            }
            save_requests(requests_data)
            await query.message.reply_text(
                f"✅ Заявка #{request_id} создана\n"
                "Администратор уведомлен."
            )
            await self.show_client_menu(query, context)
            await notify_admin(context.bot, request_id, requests_data, ADMIN_IDS)
            for admin_id in ADMIN_IDS:
                for photo_path in context.user_data.get("photos", []):
                    try:
                        with open(photo_path, 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=admin_id, 
                                photo=photo,
                                caption=f"Фото к заявке #{request_id}"
                            )
                    except Exception as e:
                        logger.error(f"Error sending photo to admin {admin_id}: {e}")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in create_request_final: {e}")
            await query.message.reply_text(
                "Произошла ошибка при создании заявки. Пожалуйста, попробуйте еще раз."
            )
            return ConversationHandler.END

    async def cancel_request(self, update: Update, context: CallbackContext):
        """Отмена создания заявки."""
        await update.message.reply_text("Создание заявки отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
