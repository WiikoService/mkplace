from typing import Dict, List, Optional
from models import ServiceCenter
from storage import JsonStorage
from config import SERVICE_CENTERS_JSON


class ServiceCenterService:
    def __init__(self):
        self.storage = JsonStorage.get_instance(SERVICE_CENTERS_JSON)

    async def get_service_center(self, sc_id: str) -> Optional[ServiceCenter]:
        """Получение сервисного центра по ID"""
        data = await self.storage.get(sc_id)
        if data:
            return ServiceCenter.from_dict({'id': sc_id, **data})
        return None

    async def get_all_service_centers(self) -> Dict[str, ServiceCenter]:
        """Получение всех сервисных центров"""
        data = await self.storage.load()
        return {sc_id: ServiceCenter.from_dict({'id': sc_id, **sc_data})
                for sc_id, sc_data in data.items()}

    async def create_service_center(
            self, name: str, address: str,
            phone: Optional[str] = None,
            description: Optional[str] = None
    ) -> ServiceCenter:
        """Создание нового сервисного центра"""
        data = await self.storage.load()
        sc_id = str(len(data) + 1)
        sc = ServiceCenter(
            id=sc_id,
            name=name,
            address=address,
            phone=phone,
            description=description
        )
        await self.storage.set(sc_id, sc.to_dict())
        return sc

    async def update_service_center(
            self, sc_id: str, name: Optional[str] = None,
            address: Optional[str] = None,
            phone: Optional[str] = None,
            description: Optional[str] = None
    ) -> Optional[ServiceCenter]:
        """Обновление сервисного центра"""
        sc = await self.get_service_center(sc_id)
        if not sc:
            return None
        if name:
            sc.name = name
        if address:
            sc.address = address
        if phone:
            sc.phone = phone
        if description:
            sc.description = description
        await self.storage.set(sc_id, sc.to_dict())
        return sc

    async def delete_service_center(self, sc_id: str) -> None:
        """Удаление сервисного центра"""
        await self.storage.delete(sc_id)
