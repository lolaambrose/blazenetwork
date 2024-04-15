from datetime import datetime, timedelta
from inspect import getabsfile
from pyxui import XUI, xui
from pyxui.errors import BadLogin, NotFound
from aiogram.types import Message
from urllib.parse import urlparse
from pyxui.config_gen import config_generator

import asyncio
import json
import aiocron
from requests import HTTPError

from database import Subscription, User, db, ServerService, UserService
from logger import logger

LAST_UPDATE = 0


async def login_to_server(server_info):
    xui = XUI(
        full_address=server_info["full_address"],
        panel=server_info["panel"],
        https=False,
    )

    try:
        # Попытка выполнить синхронный вызов login в отдельном потоке
        await asyncio.to_thread(
            xui.login, server_info["username"], server_info["password"]
        )
        logger.info(f"{server_info['id']}: successful login")

        if server_info["new"]:
            logger.info(
                f"Detected new server ({server_info['id']}), updating clients..."
            )

            active_users = await UserService.get_subscribed_users()
            logger.info(f"found {len(active_users)} active users")

            for user in active_users:
                sub = await user.get_active_sub()

                if sub is not None:
                    await upsert_client(sub.datetime_end, user, True)
                    logger.info(f"{server_info['id']}: upserted client #{user.id}")

            server_info["new"] = False
            logger.info(f"{server_info['id']}: updated new server successfully.")

        if not server_info["uptime"]:
            server_info["uptime"] = int(0)

        if server_info["uptime"] != 0:
            server_info["uptime"] += int(
                (datetime.utcnow() - server_info["last_seen"]).total_seconds()
            )
        else:
            server_info["uptime"] = int(timedelta(seconds=1).total_seconds())

        logger.info(
            f"{server_info['id']}: uptime = {timedelta(seconds=server_info['uptime'])}"
        )
        server_info["last_seen"] = datetime.utcnow()
        await ServerService.update(server_info)

        return xui, True, server_info
    except (BadLogin, Exception) as e:
        logger.error(f"{server_info['full_address']}: failed to log in to {e}")

        server_info["uptime"] = int(0)
        await ServerService.update(server_info)

        return xui, False, server_info


async def login_all():
    logger.info(f"start...")

    global SERVERS
    global XUI_INSTANCES

    SERVERS = await ServerService.get_all()

    tasks = [login_to_server(server) for server in SERVERS]
    XUI_INSTANCES = await asyncio.gather(*tasks)

    LAST_UPDATE = datetime.utcnow()

    return XUI_INSTANCES


async def perform_action(action, *args, **kwargs):
    results = []

    for xui, is_logged_in, serverinfo in XUI_INSTANCES:
        if not is_logged_in:
            continue  # Пропускаем серверы, к которым не удалось подключиться
        try:
            result = await asyncio.to_thread(getattr(xui, action), *args, **kwargs)
            results.append(result)
        except Exception as e:
            logger.error(f"error performing {action} on {xui.full_address}: {e}")
            results.append(None)

    return results


async def upsert_client(expire_time: datetime, user: User, enable: bool, limit_ip=5):
    for xui, is_logged_in, server_info in XUI_INSTANCES:
        if not is_logged_in:
            continue
        try:
            try:
                client = await asyncio.to_thread(
                    xui.get_client, inbound_id=int(2), email=str(user.id)
                )
            except NotFound:
                client = None
            if client is not None:
                await asyncio.to_thread(
                    xui.update_client,
                    inbound_id=int(2),
                    email=str(user.id),
                    uuid=user.uuid,
                    enable=enable,
                    flow="xtls-rprx-vision",
                    limit_ip=limit_ip,
                    expire_time=int(expire_time.timestamp() * 1000),
                    total_gb=int(0),
                    telegram_id="",
                    subscription_id="",
                )

            else:
                await asyncio.to_thread(
                    xui.add_client,
                    inbound_id=int(2),
                    email=str(user.id),
                    uuid=user.uuid,
                    enable=enable,
                    flow="xtls-rprx-vision",
                    limit_ip=int(5),
                    expire_time=int(expire_time.timestamp() * 1000),
                    total_gb=int(0),
                    telegram_id="",
                    subscription_id="",
                )
        except Exception as e:
            logger.error(
                f"Error upserting client on {server_info['full_address']}: {e}"
            )


async def serverconfigs_by_user(inbound_id, email):
    results = []

    for xui, is_logged_in, server_info in XUI_INSTANCES:
        if not is_logged_in:
            continue
        try:
            conf = await get_client_config(xui, inbound_id, email, server_info)
            results.append([server_info, conf])
        except:
            continue

    return results


async def serverconfig_by_user(inbound_id, email, server_info):
    try:
        xui, is_logged_in, server_info = next(
            filter(lambda x: x[2] == server_info, XUI_INSTANCES)
        )
        if not is_logged_in:
            return None

        return await get_client_config(xui, inbound_id, email, server_info)
    except Exception as e:
        logger.error(f"error retrieving client config: {e}")


# Функция для извлечения конфигурации клиента по email
async def get_client_config(xui_instance, inbound_id, email, srv_info):
    try:
        inbounds = await asyncio.to_thread(xui_instance.get_inbounds)

        for inbound in inbounds.get("obj", []):
            if inbound["id"] == int(inbound_id):
                settings = json.loads(inbound.get("settings", "{}"))
                settings["stream"] = json.loads(inbound.get("streamSettings", "{}"))
                settings["reality"] = settings["stream"].get("realitySettings", "{}")
                settings["reality"]["connection"] = settings["reality"].get(
                    "settings", "{}"
                )

                for client in settings.get("clients", []):
                    if client["email"] == str(email):
                        config = {
                            "ps": srv_info["id"],
                            "add": urlparse(srv_info["full_address"]).hostname,
                            "port": inbound["port"],
                            "id": client.get("id", ""),
                        }

                        data = {
                            "security": settings["stream"].get("security", ""),
                            "type": settings["stream"].get("network", ""),
                            "sni": settings["reality"].get("serverNames", [])[0],
                            "spx": "/",
                            "pbk": settings["reality"]["connection"].get(
                                "publicKey", ""
                            ),
                            "sid": settings["reality"].get("shortIds", [])[0],
                            "flow": client.get("flow", ""),
                            "fp": settings["reality"]["connection"].get(
                                "fingerprint", ""
                            ),
                        }

                        return config_generator("vless", config, data)

    except Exception as e:
        logger.error(f"error retrieving client config: {e}")

    return None


async def get_updown_stats(xui, inbound: int = 1):
    data = await asyncio.to_thread(xui.get_inbounds)

    up = down = 0

    if data["success"] and len(data["obj"]) > 1:
        obj = data["obj"][1]  # Get the second inbound
        up = obj["up"] / (1024**2)  # Convert to MB
        down = obj["down"] / (1024**2)  # Convert to MB

    return up, down
