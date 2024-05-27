import os

# telegram
TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", "5656984388:"
)
TELEGRAM_ADMINS = [6113190687, 6405543408]
TELEGRAM_CHANNEL = "@blazesecurity"

# database
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

# merchant
MERCHANT_API_URL = "https://api.cryptomus.com/v1"
MERCHANT_UUID = "57f83d2b"
MERCHANT_API_KEY = "oCpWH8zPVo7gTBEVsriweQr7bK"
MERCHANT_CALLBACK = "https://"
MERCHANT_CALLBACK_ORIGIN = ""
