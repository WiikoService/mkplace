from typing import List, Optional, Dict
from models import DeliveryTask
from storage import JsonStorage
from services.request import RequestService
from services.notification_service import NotificationService
from config import DELIVERY_TASKS_JSON, ORDER_STATUS_DELIVERY_TO_CLIENT


class DeliveryService:
    def __init__(self):
        self.storage = JsonStorage.get_instance(DELIVERY_TASKS_JSON)
        self.request_service = RequestService()
        self.notification_service = NotificationService()

    async def get_task(self, task_id: str) -> Optional[DeliveryTask]:
        """Получение задачи доставки по ID"""
        data = await self.storage.get(task_id)
        if data:
            return DeliveryTask.from_dict({**data, 'task_id': task_id})
        return None

    async def get_all_tasks(self) -> Dict[str, DeliveryTask]:
        """Получение всех задач доставки"""
        data = await self.storage.load()
        return {task_id: DeliveryTask.from_dict({**task_data, 'task_id': task_id})
                for task_id, task_data in data.items()}

    async def get_available_tasks(self) -> List[DeliveryTask]:
        """Получение доступных задач доставки"""
        tasks = await self.get_all_tasks()
        return [task for task in tasks.values() if task.status == "Ожидает"]

    async def get_delivery_tasks(self, delivery_id: str) -> List[DeliveryTask]:
        """Получение задач доставки для конкретного доставщика"""
        tasks = await self.get_all_tasks()
        return [task for task in tasks.values() if task.assigned_to == delivery_id]

    async def create_delivery_task(self, request_id: str, sc_name: str) -> Optional[DeliveryTask]:
        """Создание новой задачи доставки"""
        request = await self.request_service.get_request(request_id)
        if not request:
            return None
        data = await self.storage.load()
        task_id = str(len(data) + 1)
        task = DeliveryTask(
            task_id=task_id,
            request_id=request_id,
            status="Ожидает",
            sc_name=sc_name,
            client_address=request.location_link if request.location_link else "Адрес не указан",
            client_name=request.user_name,
            description=request.description
        )
        await self.storage.set(task_id, task.to_dict())
        return task

    async def accept_task(self, task_id: str, delivery_id: str) -> Optional[DeliveryTask]:
        """Принятие задачи доставки доставщиком"""
        task = await self.get_task(task_id)
        if task and task.status == "Ожидает":
            task.status = "Принято"
            task.assigned_to = delivery_id
            await self.storage.set(task_id, task.to_dict())
            # Обновляем статус заявки
            await self.request_service.update_request_status(task.request_id, ORDER_STATUS_DELIVERY_TO_CLIENT)
            await self.request_service.assign_to_delivery(task.request_id, delivery_id)
            return task
        return None

    async def update_task_status(self, task_id: str, status: str) -> Optional[DeliveryTask]:
        """Обновление статуса задачи доставки"""
        task = await self.get_task(task_id)
        if task:
            task.status = status
            await self.storage.set(task_id, task.to_dict())
            # Обновляем статус заявки
            await self.request_service.update_request_status(task.request_id, status)
            return task
        return None
