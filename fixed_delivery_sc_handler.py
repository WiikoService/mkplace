"""
Исправленный метод handle_deliver_to_client для файла handlers/delivery_sc_handler.py
"""

async def handle_deliver_to_client(self, update: Update, context: CallbackContext):
    """Обработка нажатия кнопки 'Сдать товар клиенту'"""
    query = update.callback_query
    await query.answer()
    try:
        request_id = query.data.split('_')[-1]
        context.user_data['current_request'] = request_id
        # Загружаем данные
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        users_data = load_users()
        if request_id not in requests_data:
            await query.edit_message_text("❌ Заявка не найдена.")
            return ConversationHandler.END 
        request = requests_data[request_id]
        client_id = request.get('user_id')
        client_data = users_data.get(str(client_id), {})
        # Проверяем, нужно ли клиенту оплатить оставшуюся сумму
        payment_required = False
        final_price = Decimal(request.get('final_price', '0'))
        repair_price = Decimal(request.get('repair_price', '0'))
        delivery_cost = Decimal(request.get('delivery_cost', '0'))
        # Если клиент еще не оплатил полную стоимость (30% от repair_price + 20)
        if final_price > 0 and repair_price > 0:
            expected_payment = (repair_price * Decimal('0.3')) + Decimal('20')
            if final_price >= expected_payment:
                payment_required = True
        # Обновляем статус заявки
        requests_data[request_id]['status'] = ORDER_STATUS_SC_TO_CLIENT
        save_requests(requests_data)
        # Обновляем статус задачи доставки
        task_updated = False
        for task_id, task in delivery_tasks.items():
            if task.get('request_id') == request_id:
                task['status'] = ORDER_STATUS_SC_TO_CLIENT
                task_updated = True
                break
        if not task_updated:
            logger.error(f"Не найдена задача доставки для заявки {request_id}")
        save_delivery_tasks(delivery_tasks)
        # Получаем фотографии товара
        photos = requests_data[request_id].get('sc_pickup_photos', [])
        # Уведомляем клиента
        if client_id:
            try:
                # Отправляем сообщение клиенту
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=f"🚚 Доставщик прибыл с вашим устройством и скоро передаст его вам.\n"
                        f"Адрес доставки: {requests_data[request_id].get('location_display', 'указанный в заявке')}"
                )
                
                # Отправляем фотографии клиенту
                for photo_path in photos:
                    if os.path.exists(photo_path):
                        with open(photo_path, 'rb') as photo_file:
                            await context.bot.send_photo(
                                chat_id=int(client_id),
                                photo=photo_file,
                                caption=f"Фото вашего устройства после ремонта"
                            )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления клиенту {client_id}: {e}")
        
        # Уведомляем администраторов
        admin_message = (
            f"🚚 Доставщик {update.effective_user.first_name} прибыл к клиенту для передачи товара\n"
            f"Заявка: #{request_id}\n"
            f"Статус: {ORDER_STATUS_SC_TO_CLIENT}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=admin_message
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")
        
        # Генерируем код подтверждения
        confirmation_code = ''.join(random.choices('0123456789', k=4))
        context.user_data['client_confirmation_code'] = confirmation_code
        requests_data[request_id]['confirmation_code'] = confirmation_code
        save_requests(requests_data)
        
        # В тестовом режиме отправляем код доставщику
        if DEBUG:
            await query.edit_message_text(
                f"🔢 Тестовый режим: код подтверждения для клиента: {confirmation_code}\n\n"
                f"Попросите клиента ввести этот код в боте."
            )
            
            # Отправляем клиенту инструкцию
            if client_id:
                try:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке инструкции клиенту {client_id}: {e}")
            
            return ENTER_CONFIRMATION_CODE
        
        # В боевом режиме отправляем SMS клиенту
        else:
            if client_id and client_data.get('phone'):
                try:
                    phone = client_data['phone'].replace('+', '')
                    logger.info(f"Отправка SMS на номер: {phone}")
                    
                    # Инициализируем SMS-клиент
                    sms_client = SMSBY(SMS_TOKEN, 'by')
                    
                    # Получаем список существующих объектов пароля
                    logger.info("Получение списка существующих объектов пароля...")
                    password_objects = sms_client.get_password_objects()
                    logger.info(f"Доступные объекты пароля: {password_objects}")
                    
                    # Выбираем подходящий объект пароля
                    password_object = None
                    if password_objects and 'result' in password_objects and password_objects['result']:
                        # Сортируем объекты пароля по дате создания (новые сначала)
                        sorted_objects = sorted(
                            password_objects['result'], 
                            key=lambda x: x['d_create'], 
                            reverse=True
                        )
                        # Берем первый подходящий объект пароля типа 'numbers'
                        password_object = next(
                            (obj for obj in sorted_objects if obj['type_id'] == 'numbers'),
                            None
                        )
                        if not password_object:
                            # Если нет объектов типа 'numbers', берем первый доступный
                            password_object = sorted_objects[0]
                    
                    if not password_object:
                        logger.error("Не найдены доступные объекты пароля")
                        raise Exception("Нет доступных объектов пароля для отправки SMS")
                        
                    logger.info(f"Используем объект пароля: {password_object}")
                    
                    # Получаем доступные альфа-имена
                    alphanames = sms_client.get_alphanames()
                    logger.info(f"Доступные альфа-имена: {alphanames}")
                    
                    if alphanames:
                        alphaname_id = next(iter(alphanames.keys()))
                        sms_message = f"Код подтверждения для заявки #{request_id}: %CODE%"
                        logger.info(f"Отправка SMS с сообщением: {sms_message}")
                        
                        sms_response = sms_client.send_sms_message_with_code(
                            password_object_id=password_object['id'],  # Используем ID объекта
                            phone=phone,
                            message=sms_message,
                            alphaname_id=alphaname_id
                        )
                        logger.info(f"Ответ отправки SMS: {sms_response}")
                        
                        if 'code' in sms_response:
                            # Сохраняем код в данных заявки
                            requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                            requests_data[request_id]['confirmation_code'] = sms_response['code']
                            save_requests(requests_data)
                            
                            # Сообщаем клиенту, чтобы он ввёл код из SMS
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text=f"📲 Вам отправлен SMS с кодом подтверждения. Пожалуйста, введите его здесь:"
                            )
                            
                            # Уведомляем доставщика
                            await query.edit_message_text(
                                "📲 Клиенту отправлен SMS с кодом подтверждения.\n\n"
                                "Ожидайте, пока клиент введёт код из SMS."
                            )
                            
                            return ENTER_CONFIRMATION_CODE
                        else:
                            logger.error(f"Ошибка отправки SMS: нет кода в ответе")
                            raise Exception("Не удалось отправить SMS")
                    else:
                        logger.error(f"Ошибка: нет доступных альфа-имен")
                        raise Exception("Нет доступных альфа-имен для отправки SMS")
                        
                except Exception as e:
                    logger.error(f"Ошибка при отправке SMS: {str(e)}")
                    # Если SMS не удалось отправить, используем код из интерфейса
                    await query.edit_message_text(
                        f"❌ Не удалось отправить SMS. Используйте код: {confirmation_code}\n\n"
                        f"Попросите клиента ввести этот код в боте."
                    )
                    
                    if client_id:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                        )
                    
                    return ENTER_CONFIRMATION_CODE
            else:
                # Если у клиента нет телефона, используем код из интерфейса
                await query.edit_message_text(
                    f"🔢 Код подтверждения для клиента: {confirmation_code}\n\n"
                    f"Попросите клиента ввести этот код в боте."
                )
                
                if client_id:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=f"📱 Введите код подтверждения, который вам назвал доставщик:"
                    )
                
                return ENTER_CONFIRMATION_CODE
    except Exception as e:
        logger.error(f"Ошибка при обработке сдачи товара клиенту: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
        return ConversationHandler.END 