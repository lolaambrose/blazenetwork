from motor import motor_asyncio
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId

import uuid

from logger import logger

import config

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
    referral_id: int = 0
    referral_days: int = 0
    total_spent: float = 0.00

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

    async def get_referral_count(self) -> int:
        return await db.users.count_documents({"referral_id": self.id})

    async def add_subscription(self, sub: 'Subscription') -> 'Subscription':
        sub.user_id = self.id
        return await SubService.upsert(sub)

    async def remove_subscription(self, sub: 'Subscription') -> None:
        await db.subscriptions.delete_one({"_id": sub.id})

    @property
    async def is_admin(self) -> bool:
        return self.id in config.TELEGRAM_ADMINS

class Subscription(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias='_id')
    user_id: int
    datetime_start: datetime
    datetime_end: datetime
    plan: str
    cost: float

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

class ServerService():
    @staticmethod
    async def get_all() -> List[dict]:
        return await db.servers.find().to_list(None)

    @staticmethod
    async def get_by_id(id: str) -> dict:
        return await db.servers.find_one({"id": id})

    @staticmethod
    async def update(data: dict) -> dict:
        return await db.servers.update_one({"id": data["id"]}, {"$set": data})
    
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
            return await UserService.get(user.id)

    @staticmethod
    async def get_all() -> List[User]:
        users = await db.users.find().to_list(None)
        return [User(**user) for user in users]

    @staticmethod
    async def is_user_banned(id: int) -> bool:
           return await db.banned_users.find_one({"id": id}) is not None

    @staticmethod
    async def ban_user(id: int) -> None:
        await db.banned_users.insert_one({"id": id})

    @staticmethod
    async def unban_user(id: int) -> None:
        await db.banned_users.delete_one({"id": id})

    @staticmethod
    async def init_user(id: int, uuid: str, register_time: datetime, referral_id: int=0, balance: int=0) -> User:
        if referral_id != 0:
            if not await UserService.get(referral_id):
                logger.error(f"User {referral_id} is not found")
                referral_id = 0

        if referral_id == id:
            logger.error(f"User {id} tried to set himself as a referral")
            referral_id = 0

        user = await UserService.upsert(
            User(id=id, 
                 register_time=register_time, 
                 balance=balance, 
                 uuid=uuid, 
                 referral_id=referral_id))
        return user
    
    @staticmethod
    async def get_subscribed_users() -> List[User]:
        users = await db.users.find().to_list(None)
        return [User(**user) for user in users if await User(**user).get_active_sub()]

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

        if not result:
            return
    
        is_sub_active = sub.active
        user = await sub.get_user()

        from network import upsert_client
        await upsert_client(sub.datetime_end, user, is_sub_active)

        return await SubService.get(result.upserted_id)

    @staticmethod
    async def remove(sub: Subscription) -> None:
        await db.subscriptions.delete_one({"_id": sub.id})

        from network import upsert_client
        await upsert_client(sub.datetime_end, await sub.get_user(), False)

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

    @staticmethod
    async def get_expiring_subs() -> List[Subscription]:
        now = datetime.utcnow()
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=5)

        sub_data = await db.subscriptions.find({
            "datetime_end": {
                "$gte": start,
                "$lt": end
            }
        }).to_list(None)

        return [Subscription(**sub) for sub in sub_data]

class CouponService():
    @staticmethod
    async def get_valid(id: str, user_id: int) -> dict:
        coupon = await db.coupons.find_one({"id": id})

        if not coupon:
            logger.info(f"tried to activate coupon {id} that does not exist")
            return

        if coupon["limit"] == 0:
            logger.info(f"tried to activate coupon {id} with limit == 0")
            return
        
        if coupon["expire_date"] != 0:
            if coupon["expire_date"] < datetime.now():
                logger.info(f"tried to activate expired coupon {id}")
                return

        if coupon["activated_by"] and user_id in coupon["activated_by"]:
            logger.info(f"tried to activate coupon {id} that was already activated by user {user_id}")
            return

        return coupon

    @staticmethod
    async def activate(id: str, user_id: int) -> None:
        coupon = await CouponService.get_valid(id, user_id)

        if not coupon:
            return

        if coupon["limit"] > 0:
            coupon["limit"] -= 1

        # Update the coupon to include the user ID in the activated_by array
        coupon["activated_by"].append(user_id)

        await db.coupons.update_one({"id": id}, {"$set": coupon})
        
        
async def initialize_subscriptions():
    if not await db.subscriptions.find_one(): 
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime.utcnow(),
            "datetime_end": datetime.now(tz=timezone.utc) + relativedelta(years=99),
            "cost": 0.0,
            "plan": "infinite"
            })
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime(day=13, month=4, year=2018),
            "datetime_end": datetime(day=13, month=4, year=2019),
            "cost": 99.0,
            "plan": "test 1"
            })
        await db.subscriptions.insert_one({
            "user_id": int(6113190687),
            "datetime_start": datetime(day=13, month=4, year=2019),
            "datetime_end": datetime(day=13, month=4, year=2021),
            "cost": 88.0,
            "plan": "test 2"
            })

async def initialize_coupons():
    if await db.coupons.find_one():
        return

    await db.coupons.insert_one({
            "id": "TEST1000",
            "limit": 1000,
            "expire_date": datetime(day=13, month=4, year=2021),
            "value": 30.0
        })

    await db.coupons.insert_one({
        "id": "TESTINFINITE",
        "limit": -1,
        "expire_date": 0,
        "value": 30.0
    })
        