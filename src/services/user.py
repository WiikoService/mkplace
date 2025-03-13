from typing import List, Optional, Dict
from models import User
from storage import JsonStorage
from config import USERS_JSON, ADMIN_IDS, DELIVERY_IDS


class UserService:
    def __init__(self):
        self.storage = JsonStorage.get_instance(USERS_JSON)

    async def get_user(self, user_id: str) -> Optional[User]:
        """Получение пользователя по ID"""
        data = await self.storage.get(user_id)
        if data:
            return User.from_dict({'id': user_id, **data})
        return None

    async def get_all_users(self) -> Dict[str, User]:
        """Получение всех пользователей"""
        data = await self.storage.load()
        return {user_id: User.from_dict({'id': user_id, **user_data})
                for user_id, user_data in data.items()}

    async def create_or_update_user(
            self, user_id: str, name: Optional[str] = None,
            phone: Optional[str] = None, role: Optional[str] = None
    ) -> User:
        """Создание или обновление пользователя"""
        user = await self.get_user(user_id)

        if not user:
            # Определяем роль нового пользователя
            if int(user_id) in ADMIN_IDS:
                assigned_role = "admin"
            elif int(user_id) in DELIVERY_IDS:
                assigned_role = "delivery"
            else:
                assigned_role = "client"

            user = User(id=user_id, role=assigned_role)

        # Обновляем поля, если они предоставлены
        if name:
            user.name = name
        if phone:
            user.phone = phone
        if role:
            user.role = role
        await self.storage.set(user.id, user.to_dict())
        return user

    async def delete_user(self, user_id: str) -> None:
        """Удаление пользователя"""
        await self.storage.delete(user_id)

    async def get_users_by_role(self, role: str) -> List[User]:
        """Получение пользователей по роли"""
        users = await self.get_all_users()
        return [user for user in users.values() if user.role == role]

    async def get_admins(self) -> List[User]:
        """Получение всех администраторов"""
        return await self.get_users_by_role("admin")

    async def get_delivery_users(self) -> List[User]:
        """Получение всех доставщиков"""
        return await self.get_users_by_role("delivery")
