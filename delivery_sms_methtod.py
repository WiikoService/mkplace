    async def handle_confirm_pickup(self, update: Update, context: CallbackContext):
        """
        Обработка подтверждения(отказа) передачи предмета клиентом
        Отправка смс клиенту с кодом подтверждения
        TODO: сделать смс - отдельным методом (не срочно)
        """
        query = update.callback_query
        await query.answer()
        request_id = query.data.split('_')[-1]
        requests_data = load_requests()
        delivery_tasks = load_delivery_tasks()
        users_data = load_users()
        if request_id in requests_data:
            requests_data[request_id]['status'] = 'Ожидает подтверждения клиента'
            # обновляем статус задачи
            for task in delivery_tasks:
                if isinstance(task, dict) and task.get('request_id') == request_id:
                    task['status'] = 'Ожидает подтверждения клиента'
                    break
            save_delivery_tasks(delivery_tasks)
            client_id = requests_data[request_id].get('user_id')
            client_data = users_data.get(str(client_id), {})
            if client_id:
                try:
                    keyboard = [
                        [InlineKeyboardButton("Да, забрал", callback_data=f"client_confirm_{request_id}")],
                        [InlineKeyboardButton("Нет, не забрал", callback_data=f"client_deny_{request_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=client_id,
                        text=f"Доставщик сообщает, что забрал ваш предмет по заявке №{request_id}. Подтверждаете?",
                        reply_markup=reply_markup
                    )
                    """
                    # Отправка SMS с кодом
                    if 'phone' in client_data:
                        try:
                            phone = client_data['phone'].replace('+', '')
                            logger.info(f"Отправка SMS на номер: {phone}")
                            sms_client = SMSBY(SMS_TOKEN, 'by')
                            logger.info("Создание объекта пароля...")
                            password_response = sms_client.create_password_object('numbers', 4)
                            logger.info(f"Ответ создания пароля: {password_response}")
                            if 'result' in password_response and 'password_object_id' in password_response['result']:
                                password_object_id = password_response['result']['password_object_id']
                                logger.info(f"ID объекта пароля: {password_object_id}")
                                alphanames = sms_client.get_alphanames()
                                logger.info(f"Доступные альфа-имена: {alphanames}")
                                if alphanames:
                                    alphaname_id = next(iter(alphanames.keys()))
                                    sms_message = f"Код подтверждения для заявки #{request_id}: %CODE%"
                                    logger.info(f"Отправка SMS с сообщением: {sms_message}")
                                    sms_response = sms_client.send_sms_message_with_code(
                                        password_object_id=password_object_id,
                                        phone=phone,
                                        message=sms_message,
                                        alphaname_id=alphaname_id  # альфа-имя
                                    )
                                    logger.info(f"Ответ отправки SMS: {sms_response}")
                                else:
                                    logger.error("Нет доступных альфа-имен")
                                    raise Exception("Нет доступных альфа-имен для отправки SMS")
                                if 'code' in sms_response:
                                    requests_data[request_id]['sms_id'] = sms_response.get('sms_id')
                                    requests_data[request_id]['confirmation_code'] = sms_response['code']
                                    save_requests(requests_data)
                                    await context.bot.send_message(
                                        chat_id=client_id,
                                        text=f"На ваш номер телефона отправлен код подтверждения. Пожалуйста, введите его:"
                                    )
                                    context.user_data['current_request'] = request_id
                                    return ENTER_CONFIRMATION_CODE
                                else:
                                    logger.error(f"Ошибка отправки SMS: нет кода в ответе")
                                    raise Exception("Не удалось отправить SMS")
                            else:
                                logger.error(f"Ошибка создания пароля: {password_response}")
                                raise Exception("Не удалось создать объект пароля")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке SMS: {str(e)}")
                            await context.bot.send_message(
                                chat_id=client_id,
                                text="Извините, возникла проблема с отправкой SMS. Пожалуйста, используйте кнопки подтверждения выше."
                            )
                            """
                    await query.edit_message_text(
                        f"Вы подтвердили получение предмета по заявке №{request_id}. "
                        "Ожидаем подтверждения клиента."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления: {str(e)}")
                    await query.edit_message_text("Произошла ошибка при отправке уведомления клиенту.")
                    return ConversationHandler.END
            else:
                await query.edit_message_text("ID клиента не найден для заявки.")
        else:
            await query.edit_message_text("Произошла ошибка. Заказ не найден.")
