1. Клиент создает заявку:
   - SCHandler.handle_repair_price (несколько раз для разных действий)

2. Админ обрабатывает заявку:
   - handle_assign_sc
   - handle_send_to_sc

3. Сервисный центр принимает заявку:
   - SCHandler.handle_request_notification
   - SCHandler.handle_repair_price (ввод цены)
   - SCHandler.confirm_repair_price

4. Создание платежа:
   - client_request_create (подготовка данных)
   - client_request_create (отправка запроса)
   - client_request_create (проверка статуса)

5. Доставка от клиента в СЦ:
   - DeliveryHandler.show_available_tasks
   - DeliveryHandler.accept_delivery
   - DeliveryHandler.update_delivery_messages
   - DeliveryHandler.handle_confirm_pickup
   - DeliveryHandler.handle_pickup_photo
   - DeliveryHandler.handle_pickup_photos_done
   - DeliveryHandler.handle_client_confirmation
   - DeliveryHandler.pickup_client_code_confirmation
   - DeliveryHandler.handle_transfer_to_sc
   - DeliveryHandler.handle_delivered_to_sc

6. СЦ принимает товар:
   - SCItemHandler.handle_item_acceptance
   - SCItemHandler.handle_photo_upload
   - SCItemHandler.handle_photos_done

7. СЦ отправляет товар клиенту:
   - SCHandler.set_sc_requests
   - SCHandler.choose_requests
   - SCHandler.assign_to_delivery
   - SCHandler.handle_sc_delivery_request

8. Доставка из СЦ клиенту:
   - DeliveryHandler.show_available_tasks
   - DeliveryHandler.accept_delivery
   - DeliverySCHandler.handle_pickup_from_sc
   - DeliverySCHandler.handle_request_sc_confirmation_code
   - DeliverySCHandler.check_sc_confirmation_code
   - DeliverySCHandler.handle_sc_photos_after_pickup
   - DeliverySCHandler.handle_sc_photos_done
   - FinalPaymentHandler.handle_deliver_to_client
   - FinalPaymentHandler._update_delivery_task_status
   - FinalPaymentHandler._notify_client_about_delivery
   - FinalPaymentHandler._notify_admins_about_delivery
   - FinalPaymentHandler._send_sms_confirmation

9. Подтверждение получения клиентом:
   - FinalPaymentHandler.handle_client_confirmation_code
   - FinalPaymentHandler._create_final_payment