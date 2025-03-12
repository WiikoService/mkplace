from typing import List, Optional, Dict, Any

from src.models import Request, Location
from src.storage import JsonStorage
from src.services.notification_service import NotificationService
from src.config import REQUESTS_JSON, ORDER_STATUS_NEW, ORDER_STATUS_ASSIGNED_TO_SC


class RequestService:
    def __init__(self):
        self.storage = JsonStorage.get_instance(REQUESTS_JSON)
        self.notification_service = NotificationService()

    async def get_request(self, request_id: str) -> Optional[Request]:
        """Получение заявки по ID"""
        data = await self.storage.get(request_id)
        if data:
            return Request.from_dict({**data, 'id': request_id})
        return None

    async def get_all_requests(self) -> Dict[str, Request]:
        """Получение всех заявок"""
        data = await self.storage.load()
        return {req_id: Request.from_dict({**req_data, 'id': req_id}) 
                for req_id, req_data in data.items()}

    async def get_user_requests(self, user_id: str) -> List[Request]:
        """Получение заявок пользователя"""
        requests = await self.get_all_requests()
        return [req for req in requests.values() if req.user_id == user_id]

    async def create_request(
            self, user_id: str, description: str, photos: List[str],
            location: Any, user_name: str
    ) -> Request:
        """Создание новой заявки"""
        data = await self.storage.load()
        request_id = str(len(data) + 1)
        # Обработка местоположения
        if isinstance(location, dict) and 'latitude' in location and 'longitude' in location:
            location_obj = Location(
                latitude=location['latitude'],
                longitude=location['longitude']
            )
            location_link = f"https://yandex.ru/maps?whatshere%5Bpoint%5D={location_obj.longitude}%2C{location_obj.latitude}&"
        else:
            location_obj = location
            location_link = "Адрес введен вручную"
        request = Request(
            id=request_id,
            user_id=user_id,
            description=description,
            photos=photos,
            location=location_obj,
            location_link=location_link,
            user_name=user_name,
            status=ORDER_STATUS_NEW
        )
        await self.storage.set(request_id, request.to_dict())
        return request

    async def update_request_status(self, request_id: str, status: str) -> Optional[Request]:
        """Обновление статуса заявки"""
        request = await self.get_request(request_id)
        if request:
            request.status = status
            await self.storage.set(request_id, request.to_dict())
            return request
        return None

    async def assign_to_service_center(self, request_id: str, sc_id: str, sc_name: str) -> Optional[Request]:
        """Привязка заявки к сервисному центру"""
        request = await self.get_request(request_id)
        if request:
            request.assigned_sc = sc_id
            request.status = ORDER_STATUS_ASSIGNED_TO_SC
            await self.storage.set(request_id, request.to_dict())
            return request
        return None

    async def assign_to_delivery(self, request_id: str, delivery_id: str) -> Optional[Request]:
        """Привязка заявки к доставщику"""
        request = await self.get_request(request_id)
        if request:
            request.assigned_delivery = delivery_id
            await self.storage.set(request_id, request.to_dict())
            return request
        return None
