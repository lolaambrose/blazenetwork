from aiogram import types, BaseMiddleware
from aiogram.types import Message

import database

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, message: types.Message, data: dict):
        if isinstance(message, Message):
            if await database.UserService.is_user_banned(message.from_user.id):
                return  # Прерываем обработку
        return await handler(message, data)  # Продолжаем обработку