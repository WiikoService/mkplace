import os
from datetime import datetime, timedelta
import locale
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from config import (
    CREATE_REQUEST_DESC, CREATE_REQUEST_PHOTOS, CREATE_REQUEST_LOCATION,
    PHOTOS_DIR, CREATE_REQUEST_CATEGORY, CREATE_REQUEST_DATA,
    CREATE_REQUEST_ADDRESS, CREATE_REQUEST_CONFIRMATION, CREATE_REQUEST_COMMENT,
    WAITING_PAYMENT, ORDER_STATUS_DELIVERY_TO_SC
)
from database import load_requests, load_users, save_requests, load_service_centers, load_delivery_tasks, save_delivery_tasks
from utils import notify_admin, get_address_from_coords, format_location_for_display, prepare_location_for_storage
import logging
from handlers.client_handler import ClientHandler


import time
from decimal import Decimal, getcontext
import aiohttp
from config import ORDER_STATUS_DELIVERY_TO_SC, PAYMENT_API_URL, DEBUG, ADMIN_IDS, WAITING_PAYMENT_CONF



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


getcontext().prec = 6

class PrePaymentHandler(ClientHandler):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def create_payment(self, update: Update, context: CallbackContext, request_id, request):
        """Создание платежа после подтверждения цены"""
        query = update.callback_query
        
        # Рассчитываем стоимость доставки
        repair_price = Decimal(request.get('repair_price', '0'))
        delivery_cost = Decimal('20') + (repair_price * Decimal('0.3'))
        
        # Создаем платеж - отправляем запрос в платежный API
        payment_data = {
            'amount': float(delivery_cost),
            'description': request.get('description', '')
        }
        self.logger.info(f"💲 Подготовка данных платежа для заявки #{request_id}: {payment_data}")
        
        try:
            async with aiohttp.ClientSession() as session:
                # Исправляем формат отправки данных
                payment_request_data = {'payment_request': json.dumps(payment_data)}
                self.logger.info(f"📤 Отправляем запрос на создание платежа: {payment_request_data}")
                
                async with session.post(
                    PAYMENT_API_URL,
                    data=payment_request_data,
                    timeout=10
                ) as response:
                    status = response.status
                    self.logger.info(f"📥 Статус HTTP-ответа: {status}")
                    
                    if status != 200:
                        response_text = await response.text()
                        self.logger.error(f"❌ Ошибка HTTP: {status}, ответ: {response_text}")
                        raise Exception(f"HTTP error {status}: {response_text}")
                    
                    # Получаем заголовки ответа
                    content_type = response.headers.get('Content-Type', 'unknown')
                    self.logger.info(f"🔍 Content-Type ответа при создании платежа: {content_type}")
                    
                    # Логируем ответ для отладки
                    response_body = await response.text()
                    self.logger.info(f"📄 Ответ сервера при создании платежа: {response_body}")
                    
                    # Пытаемся разобрать JSON, независимо от Content-Type
                    try:
                        result = json.loads(response_body)
                        self.logger.info(f"✅ Успешно получен JSON при создании платежа: {result}")
                    except json.JSONDecodeError as e:
                        self.logger.error(f"❌ Ошибка парсинга JSON: {e}, тело ответа: {response_body}")
                        raise Exception(f"Ошибка формата ответа: {e}")
                    
                    # Проверяем ожидаемые поля
                    self.logger.info(f"🔑 Ключи в ответе: {list(result.keys())}")
                    
                    # Теперь result содержит разобранный JSON, независимо от Content-Type
                    
                    if not result.get('order_id') or not result.get('payment_url'):
                        self.logger.error(f"❌ Неверный ответ API: {result}")
                        raise Exception(f"Invalid API response: {result}")
                    
                    # Сохраняем order_id и стоимость в заявке для дальнейшей проверки
                    request['payment_order_id'] = result['order_id']
                    request['delivery_cost'] = str(delivery_cost)
                    
                    # Загружаем и сохраняем обновленные данные
                    requests_data = load_requests()
                    requests_data[request_id] = request
                    save_requests(requests_data)
                    
                    self.logger.info(f"💾 Сохранен order_id: {result['order_id']} для заявки #{request_id}")
                    
                    # Отправляем кнопку оплаты
                    keyboard = [
                        [InlineKeyboardButton("✅ Оплатить", url=result['payment_url'])],
                        [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{request_id}")],
                        [InlineKeyboardButton("❌ Отменить", callback_data=f"payment_cancel_{request_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        f"💳 Перейдите по ссылке для оплаты:\n"
                        f"Сумма к оплате: {delivery_cost:.2f} руб.\n"
                        f"Описание услуги: {request.get('description', '')}\n\n"
                        "После оплаты нажмите кнопку 'Проверить оплату'",
                        reply_markup=reply_markup
                    )
                    return WAITING_PAYMENT
                    
        except Exception as e:
            error_message = f"❌ Ошибка при создании платежа: {str(e)}"
            self.logger.error(error_message)
            self.logger.exception(e)  # Выводим полный стектрейс
            await query.edit_message_text(f"❌ Не удалось создать платеж: {str(e)}")
            return ConversationHandler.END

    async def create_delivery_task(self, update: Update, context: CallbackContext, request_id, request):
        """Создание задачи доставки после оплаты"""
        query = update.callback_query
        
        # Загружаем необходимые данные
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        service_centers = load_service_centers()
        
        # Получаем СЦ
        sc_id = request.get('assigned_sc')
        sc_data = service_centers.get(sc_id, {})
        
        # Создаем задачу доставки
        new_task_id = str(len(delivery_tasks) + 1)
        delivery_cost = Decimal(request.get('delivery_cost', '0'))
        new_task = {
            'task_id': new_task_id,
            'request_id': request_id,
            'status': 'Новая',
            'sc_name': sc_data.get('name', 'Не указан'),
            'sc_address': sc_data.get('address', 'Не указан'),
            'client_name': request.get('user_name', 'Не указан'),
            'client_address': request.get('location', {}).get('address', 'Не указан'),
            'client_phone': request.get('user_phone', 'Не указан'),
            'description': request.get('description', ''),
            'delivery_type': 'client_to_sc',
            'is_sc_to_client': False,
            'desired_date': request.get('desired_date', ''),
            'delivery_cost': str(delivery_cost)
        }
        # Сохраняем задачу
        delivery_tasks[new_task_id] = new_task
        save_delivery_tasks(delivery_tasks)
        # Обновляем статус заявки
        requests_data[request_id]['status'] = ORDER_STATUS_DELIVERY_TO_SC
        save_requests(requests_data)
        
        # Отправляем подтверждение
        await query.edit_message_text(
            f"✅ Оплата принята для заявки #{request_id}\n"
            f"Стоимость доставки: {delivery_cost:.2f} руб.\n\n"
            f"Создана задача доставки #{new_task_id}\n"
            f"Тип: Доставка от клиента в СЦ\n"
            f"СЦ: {sc_data.get('name', 'Не указан')}\n"
            f"Адрес клиента: {request.get('location', {}).get('address', 'Не указан')}"
        )
        return ConversationHandler.END

    async def handle_payment_cancel(self, update: Update, context: CallbackContext):
        """Обработка отмены оплаты"""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('payment_order_id', None)
        context.user_data.pop('delivery_cost', None)
        await query.edit_message_text("❌ Оплата отменена. Вы можете попробовать позже.")
        return ConversationHandler.END

    async def check_payment_status(self, update: Update, context: CallbackContext):
        """Проверка статуса платежа"""
        query = update.callback_query
        await query.answer()
        
        # Получаем ID заявки из callback_data
        request_id = query.data.split('_')[-1]
        self.logger.info(f"📊 Проверка статуса платежа для заявки #{request_id}")
        
        requests_data = load_requests()
        
        if request_id not in requests_data:
            self.logger.error(f"❌ Заявка #{request_id} не найдена при проверке статуса платежа")
            await query.edit_message_text("❌ Заявка не найдена")
            return ConversationHandler.END
        
        request = requests_data[request_id]
        order_id = request.get('payment_order_id')
        
        if not order_id:
            self.logger.error(f"❌ payment_order_id не найден в заявке #{request_id}")
            await query.edit_message_text("❌ Информация о платеже не найдена")
            return ConversationHandler.END
        
        try:
            # Отправляем запрос на проверку статуса платежа
            status_data = {'payment_status_order_id': order_id}
            self.logger.info(f"📤 Отправляем запрос статуса платежа: {status_data}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PAYMENT_API_URL,
                    data=status_data,
                    timeout=10
                ) as response:
                    status = response.status
                    self.logger.info(f"📥 Статус HTTP-ответа: {status}")
                    
                    # Получаем текстовый ответ
                    response_text = await response.text()
                    self.logger.info(f"📄 Ответ сервера проверки платежа: {response_text}")
                    
                    # Изучаем заголовки ответа
                    content_type = response.headers.get('Content-Type', 'unknown')
                    self.logger.info(f"🔍 Content-Type ответа: {content_type}")
                    
                    if status != 200:
                        self.logger.error(f"❌ Ошибка HTTP: {status}, ответ: {response_text}")
                        raise Exception(f"HTTP error {status}: {response_text}")
                    
                    # Пытаемся разобрать JSON, независимо от Content-Type
                    try:
                        result = json.loads(response_text)
                        self.logger.info(f"✅ Успешно разобран JSON ответа: {result}")
                    except json.JSONDecodeError as e:
                        self.logger.error(f"❌ Ошибка парсинга JSON: {e}, текст ответа: {response_text}")
                        raise Exception(f"Ошибка формата ответа при проверке платежа: {e}")
                    
                    # Проверяем ожидаемые поля в ответе
                    self.logger.info(f"🔑 Ключи в ответе: {list(result.keys())}")
                    
                    # Проверяем статус платежа по информации от банка
                    if (result.get('errorCode') == '0' and 
                        result.get('orderStatus') == 2 and 
                        result.get('paymentAmountInfo', {}).get('paymentState') == 'DEPOSITED'):
                        self.logger.info(f"💰 Платеж для заявки #{request_id} успешен! Создаем задачу доставки.")
                        # Платеж успешен, создаем задачу доставки
                        return await self.create_delivery_task(update, context, request_id, request)
                    else:
                        # Платеж не завершен или отклонен
                        error_message = result.get('errorMessage', 'Неизвестная ошибка')
                        payment_state = result.get('paymentAmountInfo', {}).get('paymentState', 'Неизвестно')
                        order_status = result.get('orderStatus', 'Неизвестно')
                        status_message = f"Статус: {payment_state}, Код: {order_status}, Сообщение: {error_message}"
                        
                        self.logger.info(f"⏳ Платеж для заявки #{request_id} не завершен: {status_message}")
                        
                        # Отправляем обновленные кнопки
                        keyboard = [
                            [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_payment_{request_id}")],
                            [InlineKeyboardButton("❌ Отменить", callback_data=f"payment_cancel_{request_id}")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await query.edit_message_text(
                            f"⏳ Платеж не завершен: {status_message}\n\n"
                            "Возможно, операция еще обрабатывается. Проверьте еще раз через несколько секунд.",
                            reply_markup=reply_markup
                        )
                        return WAITING_PAYMENT
                    
        except Exception as e:
            error_message = f"❌ Ошибка при проверке статуса платежа: {str(e)}"
            self.logger.error(error_message)
            self.logger.exception(e)  # Выводим полный стектрейс
            
            # Отправляем кнопку для повторной проверки
            keyboard = [
                [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_payment_{request_id}")],
                [InlineKeyboardButton("❌ Отменить", callback_data=f"payment_cancel_{request_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"❌ Не удалось проверить статус платежа: {str(e)}",
                reply_markup=reply_markup
            )
            return WAITING_PAYMENT
