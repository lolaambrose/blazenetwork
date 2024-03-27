# blazeVPN telegram bot - started 12.03.24
# 
# next steps:
# - add main menu & others buttons, main bot logic (telegram.py) [ALMOST DONE, need to refactor USERS/SUBS integration code, rearrange subs]
# - add database & user-control logic (database.py, telegram.py)
# - integrate pyxui, subscription + xray configs integration, tests (network.py, database.py, telegram.py)
# - add payments 
# - bugtesting (closed alpha -> private beta -> open beta -> testing stages)

import asyncio
import logging
import elevate

from pydantic import networks

import telegram
import network
import database

from logger import logger

async def main():
    await network.login_all()
    await database.initialize_subscriptions()
    await telegram.main()
    
if __name__ == '__main__':
    elevate.elevate()
    
    logger.info("Starting bot")
    
    loop = asyncio.get_event_loop()   
    loop.create_task(main())  
    loop.run_forever()
    
    