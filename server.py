import asyncio
import json
import hashlib
import base64

from aiohttp import web
from aiohttp.web import AppRunner, TCPSite

import config
import payments
import network
import telegram

from logger import logger
from telegram import Utils

app = web.Application()

def check_signature(data: dict) -> None | Exception:
    sign = data['sign']
    del data['sign']

    json_body_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    json_body_data_binary = json_body_data.encode('utf-8')
    encoded_data = base64.b64encode(json_body_data_binary)
    sign_md5_obj = hashlib.md5(encoded_data + config.MERCHANT_API_KEY.encode('utf-8'))
    generated_sign = sign_md5_obj.hexdigest()

    if generated_sign == sign:
        return True
    
    return False

async def handle_callback(request):
    logger.info(f'callback request: {request}')

    # Проверка IP адреса
    if request.headers.get('X-Real-IP') != config.MERCHANT_CALLBACK_ORIGIN:
        logger.error(f'callback not allowed from IP: {request.headers.get("X-Real-IP")}')
        return web.json_response({'error': 'Not allowed'}, status=403)

    # Получение JSON данных из запроса
    data = await request.json()

    # Проверка подписи
    if not check_signature(data):
        logger.error(f'invalid signature: {data}')
        return web.json_response({'error': 'Invalid signature'}, status=403)

    user_id = int(data['order_id'])
    amount = float(data['amount'])

    logger.info(f'callback for user {user_id} on ${amount}')
    await payments.process_payment(user_id, amount)

    return web.json_response({'status': 'success', 'message': 'Payment processed successfully'})

app.router.add_post('/v1/merchant/callback', handle_callback)

async def main():
    return app