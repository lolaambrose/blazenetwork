import json
import hashlib
import base64
import requests

MERCHANT_API_URL = "https://api.cryptomus.com/v1"
MERCHANT_UUID = "57f83d2b-0d03-4053-8d24-fd3d29e42f96"
MERCHANT_API_KEY = "5y9HhRUgIQcL1JYmtt7epbos8bflQkMSBrqjCpD7RLrLI2ZkqkxLl4ke6EUJo5wvYaTuvLeM9RaUBCTjIACTxDFJxvhdwuEdutRYEnoCpWH8zPVo7gTBEVsriweQr7bK"
MERCHANT_CALLBACK = "http://uk.drain.agency/api/v1/merchant/callback"

def generate_signature(data):
    # Подготовка данных для подписи
    json_data = json.dumps(data, ensure_ascii=False).encode('utf-8')
    encoded_data = base64.b64encode(json_data)
    # Генерация подписи
    hash_signature = hashlib.md5(encoded_data + MERCHANT_API_KEY.encode('utf-8')).hexdigest()
    return hash_signature

def send_test_request():
    # Тестовые данные запроса
    data = {
        "currency": "ETH",
        "url_callback": MERCHANT_CALLBACK,
        "network": "eth",
        "status": "paid",
        "order_id": "6113190687"
    }

    # Генерация подписи для запроса
    signature = generate_signature(data)
    
    # Заголовки запроса
    headers = {
        'merchant': MERCHANT_UUID,
        'sign': signature,
        'Content-Type': 'application/json'
    }

    # Отправка запроса
    url = 'https://api.cryptomus.com/v1/test-webhook/wallet'
    response = requests.post(url, headers=headers, json=data)
    return response.json()

# Тестирование функции отправки запроса
print(send_test_request())
