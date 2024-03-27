from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, inline_keyboard_button, inline_keyboard_markup
from aiogram.filters.command import Command, CommandObject
from datetime import datetime, timedelta, timezone
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import RadialGradiantColorMask

import aiogram.filters
import asyncio
import uuid
import aiocron
import qrcode
import io

from database import SubService, WalletService, User, Subscription, UserService
from logger import logger

import config
import network
import database
import payments

dp = Dispatcher()

SUBSCRIPTIONS = [
        {
        "name": "VPN на 1 месяц",
        "id": "1_month",
        "price": 15.00,
        "duration": 30
        },

        {
        "name": "VPN на 3 месяца",
        "id": "3_month",
        "price": 45.00,
        "duration": 90
        }
]

def admin_required(func):
    async def wrapped(message: types.Message, *args, **kwargs):
        user = await UserService.get(message.from_user.id)
        if not await user.is_admin:
            await message.answer("Вы не администратор!")
            return 
        return await func(message, *args, **kwargs)
    return wrapped


"""
    main()

    Главная функция, которая инициализирует бота и начинает опрос.

    Вывод:
    Начинает опрос бота.
"""
async def main():
    global bot
    bot = Bot(config.TELEGRAM_TOKEN, parse_mode=ParseMode.HTML)
    
    await dp.start_polling(bot) 
   

"""
    start(message: types.Message)

    Обрабатывает команду /start в чате.

    Аргументы:
    message -- объект сообщения Telegram

    Вывод:
    Отправляет сообщение приветствия пользователю.
"""
@dp.message(Command(commands=["start"]))
async def start(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    user = await UserService.get(message.chat.id)
    
    if not user:
        user = User(id = message.chat.id, uuid = str(uuid.uuid4()), register_time = datetime.utcnow())
        await UserService.upsert(user)

    kb = [
            [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="👤 Мой профиль"),]
         ]

    all_subs = await user.get_all_subs()

    active_sub = await user.get_active_sub()

    if active_sub:
        kb.insert(0, [KeyboardButton(text="⚙️ Моя подписка")])
    else:
        kb.insert(0, [KeyboardButton(text="💳 Купить подписку")])

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True, 
        keyboard=kb
    )

    await message.reply("Добро пожаловать в <b>bladeVPN</b>!\n\nВыберите действие", reply_markup=keyboard)


"""
    my_subscription(message: types.Message)

    Обрабатывает запрос пользователя на просмотр его подписки.

    Аргументы:
    message -- объект сообщения Telegram

    Вывод:
    Отправляет информацию о подписке пользователя.
"""
@dp.message(lambda message: message.text == "⚙️ Моя подписка")
async def my_subscription(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    user = await UserService.get(message.from_user.id)

    if not user:
        await message.answer("<b>Пользователь не найден.</b>")
        return

    active_sub = await user.get_active_sub()
    
    if not active_sub:  
        await message.answer("<b>У вас нет активных подписок.</b>")
        await network.upsert_client(datetime.now(), user, False)
        await start(message)
        return
    
    await network.upsert_client(active_sub.datetime_end, user, True)
    
    kb = []
            
    for server in network.NODES:
        # Сопоставляем сервер с экземпляром xui
        xui_instance = next((instance for instance in network.xui_instances if instance[2]["id"] == server["id"]), None)
        
        # Если экземпляр xui найден и пользователь залогинен, добавляем сервер в меню
        if xui_instance and xui_instance[1]:  # xui_instance[1] содержит значение is_logged_in
            kb += [
                [InlineKeyboardButton(text=server["name"], callback_data=f"connect_{server['id']}")]
                ]
                
    await message.answer(
                f"🔐 <b>Активная подписка</b>\n"
                f"✅ <b>{active_sub.plan}</b>\n"
                f"<b>├</b>📆 с <b>{active_sub.datetime_start.strftime('%d/%m/%y %H:%M')}</b>\n"
                f"<b>└</b>⏳ по <b>{active_sub.datetime_end.strftime('%d/%m/%y %H:%M')}</b>\n\n"
                f"<b>Выберите нужный сервер для подключения</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


"""
    connect_to_server(query: types.CallbackQuery)

    Обрабатывает запрос пользователя на подключение к серверу.

    Аргументы:
    query -- объект запроса обратного вызова Telegram

    Вывод:
    Отправляет ссылку для подключения к серверу.
"""
@dp.callback_query(lambda query: query.data.startswith("connect_"))
async def connect_to_server(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')

    server_id = query.data.split("_")[1]

    user = await UserService.get(query.from_user.id)
    user_sub = await user.get_active_sub()
    
    if not user_sub:
        query.answer("<b>У вас нет активной подписки.</b>")
        return     
    
    for xui, is_logged_in, serverinfo in network.xui_instances:
        if not is_logged_in or serverinfo["id"] != server_id:
            continue

        config = await network.serverconfig_by_user(2, user.id, serverinfo)
        
        # Генерируем QR-код
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=5,
            border=4,
        )
        qr.add_data(config)
        qr.make(fit=True)

        img = qr.make_image(fill_color=(188, 221, 228), back_color='transparent')
        
        with io.BytesIO() as output:
            img.save(output)
            output.seek(0)

            file = types.BufferedInputFile(output.getvalue(), filename="qr.png")

            # Отправляем сообщение с QR-кодом
            await bot.send_message(query.from_user.id, text=f"Ваша ссылка для подключения к <b>{serverinfo['name']}</b>\n\n"
                                                                    f"<code>{config}</code>\n\n")
            #await bot.send_photo(query.from_user.id, photo=file, caption=f"Сканируйте QR-код для подключения к <b>{serverinfo['name']}</b>")
            await bot.send_sticker(query.from_user.id, sticker=file)
            
        await bot.answer_callback_query(query.id)


"""
    buy_menu(argument)

    Обрабатывает запрос пользователя на покупку подписки.

    Аргументы:
    argument -- объект сообщения или запроса обратного вызова Telegram

    Вывод:
    Отправляет пользователю меню с доступными подписками.
"""
@dp.callback_query(lambda query: query.data == ("menu_buy_subscription"))
@dp.message(lambda message: message.text == "💳 Купить подписку")
async def buy_menu(argument):
    if isinstance(argument, types.Message):
        message = argument
    elif isinstance(argument, types.CallbackQuery):
        message = argument.message
        await bot.answer_callback_query(argument.id)
    else:
        return

    await bot.send_chat_action(message.chat.id, 'typing')
    
    kb = []

    for sub in SUBSCRIPTIONS:
        kb += [
            [InlineKeyboardButton(text=f"📅 Купить {sub['name']} – ${sub['price']}", callback_data=f"buy_{sub['id']}")]
            ]
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=kb
    )
    
    await message.answer("<b>Доступные подписки: </b>", reply_markup=keyboard)


"""
    handle_buy_callback(query: types.CallbackQuery)

    Обрабатывает запрос пользователя на покупку подписки.

    Аргументы:
    query -- объект запроса обратного вызова Telegram

    Вывод:
    Отправляет пользователю подтверждение покупки подписки.
"""
@dp.callback_query(lambda query: query.data.startswith("buy_"))
async def handle_buy_callback(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)
    
    subscription = "_".join(query.data.split("_")[1:])
    sub_data = None

    for sub in SUBSCRIPTIONS:
        if sub['id'] == subscription:
            sub_data = sub
            break

    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return
    
    user_sub = await user.get_active_sub()
    
    if user_sub:
        await query.message.answer("<b>У вас уже есть активная подписка.</b>")
        return

    if user.balance < sub_data['price']:
        kb = [
                [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="menu_deposit")]
            ]
        await query.message.answer("<b>Недостаточно средств на балансе.</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    kb = [
            InlineKeyboardButton(text="✅", callback_data=f"confirm_buy_{sub_data['id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"menu_buy_subscription")
         ]
    await query.message.answer(f"Вы собираетесь купить <b>{sub_data['name']} за ${sub_data['price']}</b>\n\n"
                               f"<b>Вы уверены, что хотите купить эту подписку?</b>", 
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))


"""
    confirm_buy(query: types.CallbackQuery)

    Обрабатывает подтверждение пользователя на покупку подписки.

    Аргументы:
    query -- объект запроса обратного вызова Telegram

    Вывод:
    Подтверждает покупку подписки и обновляет информацию о пользователе.
"""
@dp.callback_query(lambda query: query.data.startswith("confirm_buy_"))
async def confirm_buy(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)

    subscription = "_".join(query.data.split("_")[2:])
    sub_data = None

    for sub in SUBSCRIPTIONS:
        if sub['id'] == subscription:
            sub_data = sub
            break

    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return
    
    user_sub = await user.get_active_sub()
    
    if user_sub:
        await query.message.answer("<b>У вас уже есть активная подписка.</b>")
        return

    if not sub_data:
        await query.message.answer("<b>Подписка не найдена.</b>")

    user.balance -= sub_data['price']
    await UserService.upsert(user)

    result_sub = await add_subscription(user, sub_data)

    await network.upsert_client(result_sub.datetime_end, user, True)
    
    await start(query.message) 


"""
    add_subscription(user: User, sub_data: dict) -> Subscription

    Добавляет подписку пользователю.

    Аргументы:
    user -- объект пользователя
    sub_data -- данные подписки

    Вывод:
    Возвращает объект подписки.
"""
async def add_subscription(user: User, sub_data: dict) -> Subscription:
    user_sub = await user.get_active_sub()
    
    if user_sub:
        return False
    
    new_sub = Subscription(
        user_id=user.id, 
        datetime_start=datetime.utcnow(), 
        datetime_end=datetime.utcnow() + timedelta(days=sub_data["duration"]),
        plan=sub_data["name"])

    await bot.send_message(user.id, f"✅ Подписка <b>{sub_data['name']}</b> успешно куплена\n")
    
    return await SubService.upsert(new_sub)


async def remove_subscription(sub: Subscription):
    user = await sub.get_user()

    # Если пользователь найден, обновляем его статус
    if user:
        await network.upsert_client(datetime.now(), user, False)
        logger.info(f"user {user.id}'s subscription has been stopped.")
        
        await bot.send_message(user.id, f"❌ Ваша подписка <b>{sub.plan}</b> закончилась")
    else:
        logger.info(f"user {sub.user_id} not found.")



async def add_balance(user: User, amount: float):
    # проверить на наличие пользователя
    if not user:
        logger.error(f'user {user.id} not found.')
        return

    user.balance += amount

    await UserService.upsert(user)
    await bot.send_message(user.id, f"💰 Ваш баланс успешно пополнен на ${amount}.")

    logger.info(f'user {user.id} balance has been updated by ${amount}.')

"""
    menu_deposit(query: types.CallbackQuery)

    Обрабатывает запрос пользователя на пополнение баланса.

    Аргументы:
    query -- объект запроса обратного вызова Telegram

    Вывод:
    Отправляет пользователю инструкции по пополнению баланса.
"""
@dp.callback_query(lambda query: query.data == "menu_deposit")
async def menu_deposit(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)
    
    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return

    if not await user.get_wallets():
        await WalletService.upsert_many(await payments.init_user_wallets(user.id))
        
    wallets = await user.get_wallets()

    eth_address = next((wallet['address'] for wallet in wallets if wallet['currency'] == 'ETH'), None)
    usdt_address = next((wallet['address'] for wallet in wallets if wallet['currency'] == 'USDT'), None)
    btc_address = next((wallet['address'] for wallet in wallets if wallet['currency'] == 'BTC'), None)
    ltc_address = next((wallet['address'] for wallet in wallets if wallet['currency'] == 'LTC'), None)
    
    message_text = (
        "<b>Вот твои адреса для пополнения баланса</b>\n\n"
        f"<b>💠 ETH</b> <code>{eth_address}</code>\n"
        f"<b>💲 USDT</b> (TRC20) <code>{usdt_address}</code>\n"
        f"<b>⚡ BTC</b> <code>{btc_address}</code>\n"
        f"<b>🪙 LTC</b> <code>{ltc_address}</code>\n\n"
        "💸 Ты можешь пополнить эти кошельки на любую сумму, и средства зачислятся на твой баланс <b>после нескольких подтверждений сети</b>, за вычетом комиссий.\n\n"
        "🔍 Будь внимателен! Переводи только соответствующую криптовалюту на указанный адрес. Отправка других токенов может привести к потере средств."
    )

    await bot.send_message(user.id, message_text)


"""
    my_profile(message: types.Message)

    Обрабатывает запрос пользователя на просмотр его профиля.

    Аргументы:
    message -- объект сообщения Telegram

    Вывод:
    Отправляет информацию о профиле пользователя.
"""
@dp.message(lambda message: message.text == "👤 Мой профиль")
async def my_profile(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    user = await UserService.get(message.from_user.id)
    
    if user:
        kb = [
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="menu_deposit")]
        ]

        # Выводим информацию о пользователе
        await message.answer(f"👤 <b>Ваш профиль</b>\n"
                             f"<b>├ ID –</b> <code>{user.id}</code>\n"
                             f"<b>└ Баланс –</b> ${user.balance}")
        
        active_sub = await user.get_active_sub()
        
        if active_sub:
            kb += [
                [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="menu_buy_subscription")]
                ]

            # Выводим информацию о подписках
            await message.answer(    "<b>🔐 Активная подписка</b>\n\n"
                                     f"✅ <b>{active_sub.plan}</b>\n"
                                     f"<b>├ </b>📆 Начинается <b>{active_sub.datetime_start.strftime('%d/%m/%y %H:%M')}</b>\n"
                                     f"<b>└ </b>⏳ Заканчивается <b>{active_sub.datetime_end.strftime('%d/%m/%y %H:%M')}</b>", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        else:
            kb += [
                [InlineKeyboardButton(text="💳 Купить подписку", callback_data="menu_buy_subscription")]
            ]

            await message.answer("<b>У вас нет активных подписок.</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        
        all_subs = await user.get_all_subs()
            
        if all_subs:
            if len(all_subs) >= 1:
                prev_subs = []

                for sub in all_subs[:5]:
                    if sub.active:
                        continue

                    prev_subs.append(f"- <b>{sub.plan}</b>\n")
                    prev_subs.append(f"<b>├ </b>📆 с <b>{sub.datetime_start.strftime('%d/%m/%y %H:%M')}</b>\n")
                    prev_subs.append(f"<b>└ </b>⏳ до <b>{sub.datetime_end.strftime('%d/%m/%y %H:%M')}</b>\n")

                if prev_subs:
                    prev_subs.insert(0,"<b>⌛ Прошлые подписки</b> (последние 5)\n\n")
                    prev_subs = ''.join(prev_subs)

                    await message.answer(text=prev_subs)
    else:
        await message.answer("<b>Пользователь не найден.</b>")
  
        
"""
    information(message: types.Message)

    Обрабатывает запрос пользователя на получение информации о сервисе.

    Аргументы:
    message -- объект сообщения Telegram

    Вывод:
    Отправляет информацию о сервисе.
"""
@dp.message(lambda message: message.text == "ℹ️ Информация")
async def information(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    kb = [
        [InlineKeyboardButton(text="🇷🇺 Служба поддержки", url='tg://resolve?domain=blazenetworksupp')]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    await message.answer("📄 Добро пожаловать в <b>blazeVPN</b>!\n\n"
                         "blazeVPN - это безопасный VPN-сервис, использующий протокол VLess. "
                         "VLess - это протокол, который отлично маскируется и обходит многие средства цензурирования.\n"
                         "Не беспокойтесь о безопасности своих данных - blazeVPN обеспечивает шифрование трафика и защиту вашей приватности.\n"
                         "Свяжитесь с нашей поддержкой для получения дополнительной информации.", reply_markup=markup)


"""
    check_subscriptions()

    Проверяет всех пользователей с активной подпиской, и если до конца подписки осталось 5 дней или 1 день, оповещает их об этом в лс.

    Вывод:
    Отправляет уведомления пользователям, у которых подписка скоро закончится.
"""
@aiocron.crontab('0 15 * * *')
async def notify_expiring_subs():
    logger.info(f"started...")
    kb = [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="menu_buy_subscription")]

    users = await UserService.get_all()  # Получаем всех пользователей
    for user in users:
        active_sub = await user.get_active_sub()  # Получаем активную подписку пользователя
        if active_sub:
            days_left = (active_sub.datetime_end - datetime.now()).days  # Вычисляем, сколько дней осталось до конца подписки
            if days_left in [1, 5]:
                await bot.send_message(user.id, f"⏳ У вас осталось <b>{days_left} дней</b> до конца подписки.", 
                                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))


"""
    stop_expired_subs()

    This function checks all users with active subscriptions, and if the subscription has ended, it updates the user's status.

    Output:
    Updates the status of users whose subscriptions have ended.
"""
@aiocron.crontab('0 0 * * *')
async def stop_expired_subs():
    logger.info(f"started...")
    # Получаем вчерашнюю дату
    yesterday = datetime.now() - timedelta(days=1)

    # Получаем все подписки, которые закончились вчера
    expired_subs = await SubService.get_by_end_date(yesterday)

    for sub in expired_subs:
        await remove_subscription(sub)
        logger.info(f"subscription for {sub.user_id} has been stopped.")
        

@dp.message(Command(commands=["login"]))
@admin_required
async def login(message: types.Message, **kwargs):
    await network.login_all()
    

@dp.message(Command(commands=['add_client']))
@admin_required 
async def add_client(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 6:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return

    inbound_id, email, enable, flow, limit_ip, expire_time = args[:6]
    enable = enable.lower() in ['true', '1', 't', 'y', 'yes']
    results = await network.perform_action(
        "add_client",
        inbound_id=int(inbound_id),
        email=email,
        uuid=str(uuid.uuid4()),
        enable=enable,
        flow=flow,
        limit_ip=int(limit_ip),
        total_gb=int(0),
        expire_time=int(expire_time),
        telegram_id="",
        subscription_id=""
    )
    
    if any(result["success"] is not False for result in results):  # Если есть хотя бы один успешный результат
        success_count = sum(result is not None for result in results)
        await message.reply(f"Клиент успешно добавлен на {success_count} сервер(ах).")
    else:  # Если нет успешных результатов
        await message.reply("Не удалось добавить клиента на ни один из серверов.")
     
     
@dp.message(Command(commands=['update_client']))
@admin_required 
async def update_client(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 7:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return

    inbound_id, email, uuid, enable, flow, limit_ip, expire_time = args[:7]
    enable = enable.lower() in ['true', '1', 't', 'y', 'yes']
    results = await network.perform_action(
        "update_client",
        inbound_id=int(inbound_id),
        email=email,
        uuid=uuid,
        enable=enable,
        flow=flow,
        limit_ip=int(limit_ip),
        total_gb=int(0),
        expire_time=int(expire_time),
        telegram_id="",
        subscription_id=""
    )
    
    if any(result["success"] is not False for result in results):  # Если есть хотя бы один успешный результат
        success_count = sum(result is not None for result in results)
        await message.reply(f"Клиент успешно обновлен на {success_count} сервер(ах).")
    else:  # Если нет успешных результатов
        await message.reply("Не удалось обновить клиента на ни одном из серверов.")
     
@dp.message(Command(commands=['get_client']))
@admin_required 
async def get_client(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 2:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return
    
    inbound_id, email = args[:2]
    
    results = await network.perform_action(
        "get_client",
        inbound_id = int(inbound_id),
        email = email
        )
    
    if results:
        user = results[0]
        msg = await message.reply(f"Пользователь {user['email']} найден\n\n<i>{user}</i>")
    else:
        await message.reply("Пользователь не найден")
 
@dp.message(Command(commands=['delete_client']))
@admin_required 
async def delete_client(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 2:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return
    
    inbound_id, email = args[:2]
    
    results = await network.perform_action(
        "delete_client",
        inbound_id = int(inbound_id),
        email = email
        )
    
    if results[0] is not None:  # Если есть хотя бы один успешный результат
        if any(result["success"] is not False for result in results):
            success_count = sum(result is not None for result in results)
            await message.reply(f"Клиент {email} успешно удален на {success_count} сервер(ах).")
    else:  # Если нет успешных результатов
        await message.reply("Не удалось удалить клиента на ни одном из серверов.")
 
@dp.message(Command(commands=['get_client_stats']))
@admin_required 
async def get_client_stats(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 2:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return
    
    inbound_id, email = args[:2]
    
    results = await network.perform_action(
        "get_client_stats",
        inbound_id = int(inbound_id),
        email = email
        )
    
    if results[0] is not None:
        if any(result["id"] is not False for result in results):
            user = results[0]
            success_count = sum(result is not None for result in results)
            await message.reply(f"Статистика {user['email']} успешно найдена на {success_count} сервер(ах).\n\n<i>{results}</i>")
    else:
        await message.reply("Пользователь не найден")
  
@dp.message(Command(commands=['get_all_client_configs']))
@admin_required  
async def get_all_client_configs(message: types.Message, command: CommandObject, **kwargs):
    args = None
    if command.args and len(command.args.split()) == 2:
        args = command.args.split()
    else:
        await message.reply("Недостаточно аргументов.")
        return
    
    inbound_id, email = args[:2]
    
    results = await network.serverconfigs_by_user(inbound_id, email)
    
    reply = ""
    for result in results:
        reply += f"<b>{result[0]['name']}:</b>\n<code>{result[1]}</code>\n\n"
        
    await message.reply(reply)