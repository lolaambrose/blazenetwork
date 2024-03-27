import os

# telegram
TELEGRAM_TOKEN = '5656984388:AAFevfzKm_qkPBAWFBmRXLl6600jJgm8n8A'
TELEGRAM_ADMINS = [6113190687]

# database 
MONGODB_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')

# merchant
MERCHANT_API_URL = "https://api.cryptomus.com/v1"
MERCHANT_UUID = "57f83d2b-0d03-4053-8d24-fd3d29e42f96"
MERCHANT_API_KEY = "5y9HhRUgIQcL1JYmtt7epbos8bflQkMSBrqjCpD7RLrLI2ZkqkxLl4ke6EUJo5wvYaTuvLeM9RaUBCTjIACTxDFJxvhdwuEdutRYEnoCpWH8zPVo7gTBEVsriweQr7bK"
MERCHANT_CALLBACK = "http://uk.drain.agency/api/v1/merchant/callback"
MERCHANT_CALLBACK_ORIGIN = '91.227.144.54'