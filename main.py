import asyncio

from threading import Thread
from aiohttp.web import AppRunner, TCPSite

import telegram
import server
import network

from logger import logger

async def start_aiohttp_server(app):
    runner = AppRunner(app)

    await runner.setup()
    site = TCPSite(runner, '127.0.0.1', 10000)

    logger.info('started aiohttp server!')

    await telegram.start_cron_jobs()

    await site.start()
    await asyncio.Event().wait()

async def main():
    app = await server.main()  # Запуск aiohttp сервера

    await network.login_all()

    bot_task = asyncio.create_task(telegram.main())  # Запуск телеграм бота
    server_task = asyncio.create_task(start_aiohttp_server(app))  # Запуск aiohttp сервера

    await asyncio.gather(bot_task, server_task)  # Запускаем и управляем обеими задачами одновременно

if __name__ == '__main__':
    asyncio.run(main())