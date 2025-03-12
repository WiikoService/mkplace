from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Any


@dataclass
class User:
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    role: str = "client"  # "client", "admin", "delivery"

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        return cls(
            id=data.get('id', ''),
            name=data.get('name'),
            phone=data.get('phone'),
            role=data.get('role', 'client')
        )

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'phone': self.phone,
            'role': self.role
        }


@dataclass
class Location:
    latitude: float
    longitude: float

    def to_dict(self) -> Dict[str, float]:
        return {
            'latitude': self.latitude,
            'longitude': self.longitude
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Location':
        return cls(
            latitude=float(data.get('latitude', 0)),
            longitude=float(data.get('longitude', 0))
        )


@dataclass
class Request:
    id: str
    user_id: str
    description: str
    status: str = "Новая"
    user_name: Optional[str] = None
    photos: List[str] = field(default_factory=list)
    location: Optional[Union[Location, Dict, str]] = None
    location_link: Optional[str] = None
    assigned_sc: Optional[str] = None
    assigned_delivery: Optional[str] = None

    @property
    def location_url(self) -> str:
        if isinstance(self.location, Location):
            return f"https://yandex.ru/maps?whatshere%5Bpoint%5D={self.location.longitude}%2C{self.location.latitude}&"
        elif isinstance(self.location, dict) and 'latitude' in self.location and 'longitude' in self.location:
            return f"https://yandex.ru/maps?whatshere%5Bpoint%5D={self.location['longitude']}%2C{self.location['latitude']}&"
        return "Местоположение не указано"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Request':
        location = data.get('location')
        if isinstance(location, dict) and 'latitude' in location and 'longitude' in location:
            location_obj = Location.from_dict(location)
        else:
            location_obj = location

        return cls(
            id=data.get('id', ''),
            user_id=data.get('user_id', ''),
            description=data.get('description', ''),
            status=data.get('status', 'Новая'),
            user_name=data.get('user_name'),
            photos=data.get('photos', []),
            location=location_obj,
            location_link=data.get('location_link'),
            assigned_sc=data.get('assigned_sc'),
            assigned_delivery=data.get('assigned_delivery')
        )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'user_id': self.user_id,
            'description': self.description,
            'status': self.status,
            'photos': self.photos,
            'assigned_sc': self.assigned_sc,
            'assigned_delivery': self.assigned_delivery
        }

        if self.user_name:
            result['user_name'] = self.user_name

        if self.location:
            if isinstance(self.location, Location):
                result['location'] = self.location.to_dict()
                result['location_link'] = self.location_url
            elif isinstance(self.location, dict):
                result['location'] = self.location
                result['location_link'] = self.location_url
            else:
                result['location'] = self.location

        return result


@dataclass
class ServiceCenter:
    id: str
    name: str
    address: str
    phone: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ServiceCenter':
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            address=data.get('address', ''),
            phone=data.get('phone'),
            description=data.get('description')
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'address': self.address,
            'phone': self.phone,
            'description': self.description
        }


@dataclass
class DeliveryTask:
    task_id: str
    request_id: str
    status: str
    sc_name: str
    client_address: str
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeliveryTask':
        return cls(
            task_id=data.get('task_id', ''),
            request_id=data.get('request_id', ''),
            status=data.get('status', 'Ожидает'),
            sc_name=data.get('sc_name', ''),
            client_address=data.get('client_address', ''),
            client_name=data.get('client_name'),
            client_phone=data.get('client_phone'),
            description=data.get('description'),
            assigned_to=data.get('assigned_to')
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'request_id': self.request_id,
            'status': self.status,
            'sc_name': self.sc_name,
            'client_address': self.client_address,
            'client_name': self.client_name,
            'client_phone': self.client_phone,
            'description': self.description,
            'assigned_to': self.assigned_to
        }
