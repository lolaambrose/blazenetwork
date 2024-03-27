import json
import aiohttp
import hashlib
import base64

import config
import database
import telegram

from logger import logger

async def create_wallet(currency, network, order_id, url_callback=None, from_referral_code=None):
    data = {
        "currency": currency,
        "network": network,
        "order_id": str(order_id)
    }

    if url_callback:
        data["url_callback"] = url_callback
    else:
        data["url_callback"] = config.MERCHANT_CALLBACK
    if from_referral_code:
        data["from_referral_code"] = from_referral_code

    encoded_data = json.dumps(data)

    # Генерация подписи
    sign = hashlib.md5((base64.b64encode(encoded_data.encode()) + config.MERCHANT_API_KEY.encode())).hexdigest()

    # Заголовки запроса
    headers = {
        "merchant": config.MERCHANT_UUID,
        "sign": sign,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(config.MERCHANT_API_URL + "/wallet", headers=headers, data=encoded_data) as response:
            if response.status == 200:
                resp = await response.json()  # Возвращаем JSON-ответ в случае успеха
                resp['result'] = resp.get('result', {})
                return resp['result']
            else:
                response_text = await response.text()
                raise Exception(f"Ошибка создания статичного кошелька: {response.status}, Тело ответа: {response_text}")
                return None

async def init_user_wallets(user_id: str):
    new_wallets = []
    new_wallets.append(await create_wallet("LTC", "LTC", user_id))
    new_wallets.append(await create_wallet("BTC", "BTC", user_id))
    new_wallets.append(await create_wallet("ETH", "ETH", user_id))
    new_wallets.append(await create_wallet("USDT", "tron", user_id))

    return new_wallets

async def process_payment(user_id: int, amount: float):
    user = await database.UserService.get(user_id)
    
    if not user:
        logger.error(f"user not found: {user_id}")
        return
    
    await telegram.add_balance(user, amount)