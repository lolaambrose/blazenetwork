from motor import motor_asyncio
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId

from logger import logger

import config
import uuid

db_client = motor_asyncio.AsyncIOMotorClient(config.MONGODB_URI)
db = db_client["blazevpn"]

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, values):
        if not ObjectId.is_valid(v):
            raise ValueError('Invalid objectid')
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, schema):
        schema.update(type='string', format='uuid')
        
class WalletService():
    @staticmethod
    async def get_all_by_user(id: int):
        wallets = await db.wallets.find({"order_id": str(id)}).to_list(None)
        return wallets
    
    @staticmethod
    async def upsert(wallet: dict):
        result = await db.wallets.update_one({"order_id": wallet["order_id"]}, {"$set": wallet}, upsert = True)
        if result:
            return result

    @staticmethod
    async def upsert_many(wallets: List[dict]):
        results = []
        for wallet in wallets:
            existing_wallet = await db.wallets.find_one({"order_id": wallet["order_id"], "currency": wallet["currency"]})
            if existing_wallet:
                # Если кошелек уже существует, обновляем его данные
                result = await db.wallets.update_one({"_id": existing_wallet["_id"]}, {"$set": wallet})
            else:
                # Если кошелка нет, добавляем его
                result = await db.wallets.insert_one(wallet)
            results.append(result)
        return results

class User(BaseModel):
    id: int
    register_time: datetime = datetime.utcnow()
    balance: float = 0.00
    uuid: str = str(uuid.uuid4())

    async def get_active_sub(self) -> Optional['Subscription']:
        subscriptions = await db.subscriptions.find({"user_id": self.id}).to_list(None)
        for sub_data in subscriptions:
            sub = Subscription(**sub_data)
            if sub.active:
                return sub
        return None

    async def get_all_subs(self) -> List['Subscription']:
        subscriptions = await db.subscriptions.find({"user_id": self.id}).sort('datetime_end', -1).to_list(None)
        return [Subscription(**sub) for sub in subscriptions]

    async def get_wallets(self) -> List[dict]:
        return await WalletService.get_all_by_user(self.id)
    
    async def upsert_wallet(self, wallet: dict) -> dict:
        wallet["user_id"] = self.id
        return await WalletService.upsert(wallet)

    @property
    async def is_admin(self) -> bool:
        return self.id in config.TELEGRAM_ADMINS

class Subscription(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias='_id')
    user_id: int
    datetime_start: datetime
    datetime_end: datetime
    plan: str

    @property
    def active(self) -> bool:
        return self.datetime_end > datetime.utcnow()
    
    def prolongate(self, date_to: datetime) -> None:
        datetime_end += date_to       

    async def get_user(self) -> Optional[User]:
        user_data = await db.users.find_one({"id": self.user_id})
        return User(**user_data) if user_data else None
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }
        populate_by_name = True
    
class UserService():
    @staticmethod
    async def get(id: int) -> User:
        user_data = await db.users.find_one({"id": id})
        if user_data:
            return User(**user_data)
        else:
            return None
    
    @staticmethod
    async def upsert(user: User) -> User:
        result = await db.users.update_one({"id": user.id}, {"$set": user.dict()}, upsert = True)
        if result:
            return await UserService.get(result.upserted_id)

    @staticmethod
    async def get_all() -> List[User]:
        users = await db.users.find().to_list(None)
        return [User(**user) for user in users]

class SubService():
    @staticmethod
    async def get(id: PyObjectId) -> Subscription:
        sub_data = await db.subscriptions.find_one({"_id": id})
        if sub_data:
            return Subscription(**sub_data)
        else:
            return None
    
    @staticmethod
    async def upsert(sub: Subscription) -> Subscription:
        result = await db.subscriptions.update_one({"_id": sub.id}, {"$set": sub.dict(by_alias=True)}, upsert = True)
        if result:
            return await SubService.get(result.upserted_id)

    @staticmethod
    async def get_by_end_date(end_date: datetime) -> List[Subscription]:
        # Создаем объект даты для начала и конца дня
        start_of_day = datetime(end_date.year, end_date.month, end_date.day)
        end_of_day = start_of_day + timedelta(days=1)

        # Ищем подписки, которые закончились в этот день
        sub_data = await db.subscriptions.find({
            "datetime_end": {
                "$gte": start_of_day,
                "$lt": end_of_day
            }
        }).to_list(None)

        # Преобразуем данные подписок в объекты Subscription и возвращаем их
        return [Subscription(**sub) for sub in sub_data]
        
        
async def initialize_subscriptions():
    if not await db.subscriptions.find_one(): 
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime.utcnow(),
            "datetime_end": datetime.now(tz=timezone.utc) + relativedelta(years=99),
            "plan": "infinite"
            })
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime(day=13, month=4, year=2018),
            "datetime_end": datetime(day=13, month=4, year=2019),
            "plan": "test 1"
            })
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime(day=13, month=4, year=2019),
            "datetime_end": datetime(day=13, month=4, year=2021),
            "plan": "test 2"
            })
        