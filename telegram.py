from aiogram import Bot, Dispatcher, types, Router
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, inline_keyboard_button, inline_keyboard_markup
from aiogram.filters.command import Command, CommandObject
from datetime import datetime, timedelta, timezone
from aiogram.exceptions import TelegramBadRequest

import uuid
import aiocron
import qrcode
import io

from database import ServerService, SubService, WalletService, User, Subscription, UserService, CouponService
from logger import logger

import config
import network
import database
import payments
import middlewares

dp = Dispatcher()
dp.message.middleware(middlewares.BanMiddleware())

def admin_required(func):
    async def wrapped(message: types.Message, *args, **kwargs):
        user = await UserService.get(message.from_user.id)

        if user:
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

    await SubService.fetch_prices()
    await database.initialize_coupons()
    
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
    
    if message.text.startswith("/start"):
        arg = message.text.split(" ")[1] if len(message.text.split(" ")) > 1 else None
    else:
        arg = None

    referral_id = None
    coupon = None

    if arg:
        if arg.isdigit():
            referral_id = int(arg)
            logger.info(f"referral: {referral_id}")
        else:
            coupon = arg
            logger.info(f"coupon: {coupon}")
    
    if not user:
        balance = 0
        if coupon:
            coupon_data = await CouponService.get_valid(coupon, message.chat.id)
            if coupon_data:
                balance = coupon_data["value"]
                await CouponService.activate(coupon, message.chat.id)

                logger.info(f"user {message.chat.id} activated coupon {coupon} with value ${balance}")
                bot.send_message(message.chat.id, f"<b>Купон <code>{coupon}</code> успешно активирован!\n</b>💰 Ваш баланс пополнен на <b>${balance}</b>")
            else:
                await bot.send_message(message.chat.id, f"<b>Купон <code>{coupon}</code> не найден или уже недействителен.</b>")
                logger.info(f"user {message.chat.id} tried to activate invalid coupon {coupon}.")

        user = await UserService.init_user(message.chat.id, str(uuid.uuid4()), datetime.now(), referral_id, balance=balance)
    else:
        if coupon:
            coupon_data = await CouponService.get_valid(coupon, user.id)
            if coupon_data:
                await Admin.add_balance(user, coupon_data["value"], notify=False)
                await CouponService.activate(coupon, user.id)

                logger.info(f"user {user.id} activated coupon {coupon} with value ${coupon_data['value']}")
                await bot.send_message(user.id, f"<b>Купон <code>{coupon}</code> успешно активирован!\n</b>💰 Ваш баланс пополнен на <b>${coupon_data['value']}</b>")
            else:
                await bot.send_message(message.chat.id, f"<b>Купон <code>{coupon}</code> не найден или уже недействителен.</b>")

    kb = [
            [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="👤 Мой профиль"),]
         ]

    active_sub = await user.get_active_sub()

    if active_sub:
        kb.insert(0, [KeyboardButton(text="⚙️ Моя подписка")])
    else:
        kb.insert(0, [KeyboardButton(text="💳 Купить подписку")])

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True, 
        keyboard=kb
    )

    await message.reply("Добро пожаловать в <b>🚀 blazeVPN</b>!\n\nВыберите действие", reply_markup=keyboard)

"""
    my_subscription(message: types.Message)

    Обрабатывает запрос пользователя на просмотр его подписки.

    Аргументы:
    message -- объект сообщения Telegram

    Вывод:
    Отправляет информацию о подписке пользователя.
"""
@dp.message(lambda message: message.text == "⚙️ Моя подписка")
async def menu_subscription(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    user = await UserService.get(message.from_user.id)

    if not user:
        await message.answer("<b>Пользователь не найден.</b>")
        return

    active_sub = await user.get_active_sub()
    
    if not active_sub:  
        await message.answer("<b>У вас нет активных подписок.</b>")
        #await network.upsert_client(datetime.now(), user, False)
        await start(message)
        return
    
    #await network.upsert_client(active_sub.datetime_end, user, True)
    
    kb = []
            
    for server in network.SERVERS:
        # Сопоставляем сервер с экземпляром xui
        xui_instance = next((instance for instance in network.XUI_INSTANCES if instance[2]["id"] == server["id"]), None)
        
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

@dp.callback_query(lambda query: query.data.startswith("connect_"))
async def action_connect(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')

    server_id = query.data.split("_")[1]

    user = await UserService.get(query.from_user.id)
    user_sub = await user.get_active_sub()
    
    if not user_sub:
        query.answer("<b>У вас нет активной подписки.</b>")
        return     
    
    for xui, is_logged_in, serverinfo in network.XUI_INSTANCES:
        if not is_logged_in or serverinfo["id"] != server_id:
            continue

        config = await network.serverconfig_by_user(2, user.id, serverinfo)

        if not config:
            bot.send_message(query.from_user.id, "<b>Ошибка при получении конфигурации сервера.</b>"
                            "\n\nОбратитесь к поддержке бота, чтобы решить эту проблему")
        
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

@dp.callback_query(lambda query: query.data == "menu_invite")
async def menu_invite(query: types.CallbackQuery):
    await bot.send_chat_action(query.from_user.id, 'typing')

    user = await UserService.get(query.from_user.id)

    if not user:
        await bot.send_message(query.from_user.id, "<b>Пользователь не найден.</b>")
        return

    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user.id}"

    referral_description = "🤝 Пригласите друга и получите <b>бонусные дни</b> подписки!\n\n" \
                            "🔗 Отправьте вашу реферальную ссылку друзьям:\n" \
                            f"<code>{referral_link}</code>\n\n" \

    referral_description += "Если ваш реферал купит подписку, то вы получите:\n"
    for sub in SubService.POOL:
        referral_description += f"• за <b>{sub['name_ru']}</b> – <code>{sub['referral_bonus']}</code> бонусных дней!\n"

    await bot.send_message(query.from_user.id, referral_description)
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
async def menu_buy(argument):
    if isinstance(argument, types.Message):
        message = argument
    elif isinstance(argument, types.CallbackQuery):
        message = argument.message
        await bot.answer_callback_query(argument.id)
    else:
        return

    await bot.send_chat_action(message.chat.id, 'typing')

    if not await Utils.is_user_subscribed(message.chat.id):
        channel = config.TELEGRAM_CHANNEL.lstrip('@')

        kb = [
                [InlineKeyboardButton(text="🚀 Подписаться", url=f'tg://resolve?domain={channel}')],
                [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="menu_buy_subscription")]
            ]
        await message.answer("Привет! Я заметил, что ты еще не подписался на наш новостной канал.\n\n"
                            "🔔 <b>Почему стоит подписаться?</b>\n"
                            "- 📢 Получай последние обновления и улучшения сервиса.\n"
                            "- 🚀 Узнавай о специальных акциях и скидках.\n"
                            "- 🛡️ Гарантия безопасности: будь в курсе важных новостей и предупреждений.\n\n"

                            f"Пожалуйста, <a href='{config.TELEGRAM_CHANNEL}'>подпишись на наш канал</a>, чтобы продолжить. Это займет всего мгновение!\n\n", 
                            disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    kb = []

    for sub in SubService.POOL:
        kb += [
            [InlineKeyboardButton(text=f"📅 Купить {sub['name_ru']} – ${sub['price']}", callback_data=f"buy_{sub['id']}")]
            ]
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=kb
    )
    
    await message.answer("<b>Доступные подписки: </b>", reply_markup=keyboard)


@dp.callback_query(lambda query: query.data.startswith("menu_prolongate_"))
async def action_prolongate(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)

    subscription = "_".join(query.data.split("_")[2:])

    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return

    user_sub = await user.get_active_sub()
    sub_data = None

    if not user_sub:
        await query.message.answer("<b>У вас нет активной подписки.</b>")
        return

    for sub in SubService.POOL:
        if sub['id'] == subscription:
            sub_data = sub
            break

    if not sub_data:
        query.message.answer("<b>Подписка не найдена.</b>")

    user.balance -= sub_data['price']
    user.total_spent += sub_data['price']

    user_sub.datetime_end += timedelta(days=sub_data['duration'])

    await SubService.upsert(user_sub)
    await UserService.upsert(user)

    if user.referral_id != 0:
        referrer = await UserService.get(user.referral_id)

        if not referrer:
            logger.error(f"referrer {user.referral_id} not found.")
            return

        await Admin.add_referal_days(referrer, sub_data["referral_bonus"])

    await query.message.answer(f"✅ Подписка <b>{sub_data['name_ru']}</b> успешно продлена на <code>{sub_data['duration']}</code> дней.")

"""
    handle_buy_callback(query: types.CallbackQuery)

    Обрабатывает запрос пользователя на покупку подписки.

    Аргументы:
    query -- объект запроса обратного вызова Telegram

    Вывод:
    Отправляет пользователю подтверждение покупки подписки.
"""
@dp.callback_query(lambda query: query.data.startswith("buy_"))
async def action_buy_callback(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)
    
    subscription = "_".join(query.data.split("_")[1:])
    sub_data = None

    for sub in SubService.POOL:
        if sub['id'] == subscription:
            sub_data = sub
            break

    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return
    
    user_sub = await user.get_active_sub()
    
    if user_sub:
        kb = [InlineKeyboardButton(text="✅ Да, продлить", callback_data=f"menu_prolongate_{subscription}")]
        days = sub_data["duration"]

        await query.message.answer("<b>У вас уже есть активная подписка.</b>\n\n" \
                                   f"Хотите продлить её на <code>{days}</code> дней?",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))
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
    await query.message.answer(f"Вы собираетесь купить <b>{sub_data['name_ru']} за ${sub_data['price']}</b>\n\n"
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
async def action_confirm_buy(query: types.CallbackQuery):
    await bot.send_chat_action(query.message.chat.id, 'typing')
    await bot.answer_callback_query(query.id)

    subscription = "_".join(query.data.split("_")[2:])
    sub_data = None

    for sub in SubService.POOL:
        if sub['id'] == subscription:
            sub_data = sub
            break

    user = await UserService.get(query.from_user.id)

    if not user:
        await query.message.answer("<b>Пользователь не найден.</b>")
        return
    
    user_sub = await user.get_active_sub()

    if not sub_data:
        await query.message.answer("<b>Подписка не найдена.</b>")

    user.balance -= sub_data['price']
    user.total_spent += sub_data['price']
    await UserService.upsert(user)

    result_sub = await Admin.add_subscription(user, sub_data)

    for admin in config.TELEGRAM_ADMINS:
        await bot.send_message(admin, f"<i>[ADMIN NOTIFY]</i> <b>Пользователь <code>{user.id}</code> купил подписку <code>{sub_data['name_ru']}</code> за <code>${sub_data['price']}</code>.</b>")

    if user.referral_id != 0:
        referrer = await UserService.get(user.referral_id)

        if not referrer:
            logger.error(f"referrer {user.referral_id} not found.")
            return

        await Admin.add_referal_days(referrer, sub_data["referral_bonus"])

    #await network.upsert_client(result_sub.datetime_end, user, True)
    
    await start(message=query.message) 
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
async def menu_my_profile(message: types.Message):
    await bot.send_chat_action(message.chat.id, 'typing')

    user = await UserService.get(message.from_user.id)
    
    if user:
        await Utils.render_profile(user)
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
async def menu_information(message: types.Message):
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

class Utils:
    @staticmethod
    @admin_required
    async def render_status(message: types.Message):
        status_msg =  f"<b>🔧 Статус серверов</b>\n\n"

        for xui, is_logged_in, server_info in network.XUI_INSTANCES:
            up, down = await network.get_updown_stats(xui)
            uptime = str(timedelta(seconds=server_info["uptime"]))

            status_msg += "🟢 " if is_logged_in else "🔴 "
            status_msg += "<b>" + server_info["name"] + "</b>\n"  
            status_msg += "├ 🔗 <code>" + server_info["full_address"] + "</code>\n"
            status_msg += "├ ⌛ Последний опрос <code>" + server_info["last_seen"].strftime('%H:%M %d/%m') + "</code>\n"
            status_msg += "├ 🕑 Uptime <code>" + uptime + "</code>\n"
            status_msg += f"└ ⬆️ <code>{round(up)} Mbytes</code> ⬇️ <code>{round(down)} Mbytes</code>\n\n"
            
        await message.answer(status_msg)

    @staticmethod
    async def is_user_subscribed(user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(config.TELEGRAM_CHANNEL, user_id)
            if member.status == "member" or member.status == "administrator" or member.status == "creator":
                return True
        except TelegramBadRequest:
            logger.error(f"user {user_id} is not subscribed to the channel.")
            return False

    @staticmethod
    async def render_profile(user: User, chat_id: int = None, admin: bool = False):
        if not chat_id:
            chat_id = user.id

        kb = []

        if not admin:
            kb = [
                [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="menu_deposit")],
                [InlineKeyboardButton(text="🤝 Пригласить друга", callback_data="menu_invite")]
            ]

        profile_info =  f"<b>👤 Ваш профиль</b>\n" \
                        f"<b>├ ID –</b> <code>{user.id}</code>\n" \
                        f"<b>└ Баланс –</b> <code>${user.balance}</code>\n\n" \
                        f"<b>🫂 Реферальная система</b>\n" \
                        f"<b>├</b> Привлечено рефералов – <code>{await user.get_referral_count()}</code>\n" \
                        f"<b>└</b> Получено бонусных дней – <code>{user.referral_days}</code>\n\n" \
                        f"{('🔧 Вы – <b>администратор!</b>' if await user.is_admin else '')}" 

        if admin or await user.is_admin:                    
            profile_info += f"\n\n📅 Дата регистрации – {user.register_time.strftime('%d/%m/%Y')}\n" \
                            f"🆔 UUID – {str(user.uuid)}\n" \
                            f"💸 Потраченная сумма – ${user.total_spent}"

        # Выводим информацию о пользователе
        await bot.send_message(chat_id, profile_info, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        
        active_sub = await user.get_active_sub()

        kb = []
        
        if active_sub:
            if not admin:
                kb += [
                    [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="menu_buy_subscription")]
                    ]

            # Выводим информацию о подписках
            await bot.send_message(chat_id, "<b>🔐 Активная подписка</b>\n\n"
                                            f"✅ <b>{active_sub.plan}</b>\n"
                                            f"<b>├ </b>📆 Начинается <b>{active_sub.datetime_start.strftime('%d/%m/%Y %H:%M')}</b>\n"
                                            f"<b>└ </b>⏳ Заканчивается <b>{active_sub.datetime_end.strftime('%d/%m/%Y %H:%M')}</b>\n",
                                            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        else:
            if not admin:
                kb += [
                    [InlineKeyboardButton(text="💳 Купить подписку", callback_data="menu_buy_subscription")]
                ]

            await bot.send_message(chat_id, "<b>У вас нет активных подписок.</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        
        '''
        all_subs = await user.get_all_subs()
            
        if all_subs:
            if len(all_subs) >= 1:
                prev_subs = []

                for sub in all_subs[:5]:
                    if sub.active:
                        continue

                    prev_subs.append(f"- <b>{sub.plan}</b>\n")
                    prev_subs.append(f"<b>├ </b>📆 с <b>{sub.datetime_start.strftime('%d/%m/%Y %H:%M')}</b>\n")
                    prev_subs.append(f"<b>└ </b>⏳ до <b>{sub.datetime_end.strftime('%d/%m/%Y %H:%M')}</b>\n")

                if prev_subs:
                    prev_subs.insert(0,"<b>⌛ Прошлые подписки</b> (последние 5)\n\n")
                    prev_subs = ''.join(prev_subs)

                    await bot.send_message(chat_id, text=prev_subs)
        '''        

class Admin:
    @staticmethod
    async def add_referal_days(user: User, days: int):
        user.referral_days += days

        sub = await user.get_active_sub()

        if not sub:
            custom_sub = {
                "name": "Бонусная подписка",
                "price": 0.00,
                "duration": days
            }
            await Admin.add_subscription(user, custom_sub, notify=False)
        else:
            sub.datetime_end += timedelta(days=days)
            await SubService.upsert(sub)

        await UserService.upsert(user)
        await bot.send_message(user.id, f"🎉 Вам начислено <b>{days}</b> бонусных дней за реферала.")

    @staticmethod
    async def add_subscription(user: User, sub_data: dict, notify: bool = True) -> Subscription:
        user_sub = await user.get_active_sub()
        
        if user_sub:
            return False
        
        new_sub = Subscription(
            user_id=user.id, 
            datetime_start=datetime.utcnow(), 
            datetime_end=datetime.utcnow() + timedelta(days=sub_data["duration"]),
            plan=sub_data["name_ru"],
            cost=sub_data["price"])
        
        result =  await SubService.upsert(new_sub)

        logger.info(f"user {user.id} has bought a subscription {sub_data['name_ru']} for ${sub_data['price']}.")

        if notify:
            await bot.send_message(user.id, f"✅ Подписка <b>{sub_data['name_ru']}</b> успешно куплена\n")

        return result

    @staticmethod
    async def remove_subscription(sub: Subscription):
        user = await sub.get_user()

        # Если пользователь найден, обновляем его статус
        if user:
            await SubService.remove(sub)

            logger.info(f"user {user.id}'s subscription has been stopped.")
            
            await bot.send_message(user.id, f"❌ Ваша подписка <b>{sub.plan}</b> закончилась")
        else:
            logger.info(f"user {sub.user_id} not found.")

    @staticmethod
    async def add_balance(user: User, amount: float, notify: bool = True):
        # проверить на наличие пользователя
        if not user:
            logger.error(f'user {user.id} not found.')
            return

        user.balance += amount

        await UserService.upsert(user)

        if notify:
            await bot.send_message(user.id, f"💰 Ваш баланс успешно пополнен на <b>${amount}</b>")

        logger.info(f'user {user.id} balance has been updated by +${amount}')

    @staticmethod
    async def set_balance(user: User, amount: float):
        # проверить на наличие пользователя
        if not user:
            logger.error(f'user {user.id} not found.')
            return

        user.balance = amount

        await UserService.upsert(user)
        await bot.send_message(user.id, f"💰 Ваш баланс успешно обновлен на <b>${amount}</b>")

        logger.info(f'user {user.id} balance has been set to ${amount}')

    @staticmethod
    @dp.message(Command(commands=["status"]))
    @admin_required
    async def command_status(message: types.Message, **kwargs):
        await network.login_all()
        await Utils.render_status(message)

    @staticmethod
    @dp.message(Command(commands=["login"]))
    @admin_required
    async def command_login(message: types.Message, **kwargs):
        await network.login_all()
        await Utils.render_status(message)

    @staticmethod
    @dp.message(Command(commands=["add_balance"]))
    @admin_required
    async def command_add_balance(message: types.Message, **kwargs):
        user_id = int(message.text.split(" ")[1])
        amount = float(message.text.split(" ")[2])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        await Admin.add_balance(user, amount)
        await message.answer(f"Баланс пользователя {user_id} успешно пополнен на ${amount}")

    @staticmethod
    @dp.message(Command(commands=["set_balance"]))
    @admin_required
    async def command_set_balance(message: types.Message, **kwargs):
        user_id = int(message.text.split(" ")[1])
        amount = float(message.text.split(" ")[2])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        await Admin.set_balance(user, amount)
        await message.answer(f"Баланс пользователя {user_id} успешно обновлен на ${amount}")

    @staticmethod
    @dp.message(Command(commands=["profile"]))
    @admin_required
    async def command_profile(message: types.Message, **kwargs):
        user_id = int(message.text.split(" ")[1])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        await message.answer(f"Вот профиль пользователя <code>{user_id}</code>")

        await Utils.render_profile(user, chat_id=message.chat.id, admin=True)

    @staticmethod
    @dp.message(Command(commands=["ban"]))
    @admin_required
    async def command_ban(message: types.Message, **kwargs):
        user_id = int(message.text.split(" ")[1])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        await UserService.ban_user(user_id)
        await message.answer(f"Пользователь {user_id} забанен.")

    @staticmethod
    @dp.message(Command(commands=["unban"]))
    @admin_required
    async def command_unban(message: types.Message, **kwargs):
        user_id = int(message.text.split(" ")[1])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        await UserService.unban_user(user_id)
        await message.answer(f"Пользователь {user_id} разбанен.")

    @staticmethod
    @dp.message(Command(commands=["add_sub"]))
    @admin_required
    async def command_add_sub(message: types.Message, **kwargs):
        # команда должна вызываться /add_sub <user_id> <id>
        user_id = int(message.text.split(" ")[1])
        id = message.text.split(" ")[2]

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        if not any(sub["id"] == id for sub in SubService.POOL):
            await message.answer("Подписка не найдена по ID.")
            return
        
        sub_data = {
            "name": [sub["name_ru"] for sub in SubService.POOL if sub["id"] == id][0],
            "id": id,
            "price": [sub["price"] for sub in SubService.POOL if sub["id"] == id][0],
            "duration": [sub["duration"] for sub in SubService.POOL if sub["id"] == id][0]
        }

        name = sub_data["name_ru"]

        await Admin.add_subscription(user, sub_data)
        await message.answer(f"Подписка <b>{name}</b> успешно добавлена для ID <code>{user_id}</code>.")
        logger.info(f"[ADMIN] subscription {id} added for {user.id} by {message.from_user.id}") 

    @staticmethod
    @dp.message(Command(commands=["remove_sub"]))
    @admin_required
    async def command_remove_sub(message: types.Message, **kwargs):
        # команда должна вызываться /remove_sub <user_id>
        user_id = int(message.text.split(" ")[1])

        user = await UserService.get(user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return

        sub = await user.get_active_sub()
        if not sub:
            await message.answer("У пользователя нет активной подписки.")
            return
    
        await Admin.remove_subscription(sub)
        await message.answer(f"Подписка успешно удалена для ID <code>{user_id}</code>.")
        logger.info(f"[ADMIN] subscription removed for {user.id} by {message.from_user.id}")

async def monitor_servers():
    logger.info('started...')

    xui_instances = await network.login_all()

    for xui, is_logged_in, server_info in xui_instances:
        if not is_logged_in:
            logger.error(f'server {server_info["full_address"]} is not responding!')

            for admin in config.TELEGRAM_ADMINS:
                await bot.send_message(admin, f"<i>[ADMIN NOTIFY]</i> <b>❌ server {server_info['full_address']} is not responding.</b>")

async def notify_expiring_subs():
    logger.info(f"started...")
    kb = [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="menu_buy_subscription")]

    subscriptions = await SubService.get_expiring_subs()  # Получаем все подписки, у которых дата окончания подходит

    for subscription in subscriptions:
        user = await subscription.get_user()  # Получаем пользователя для каждой подписки
        days_left = (subscription.datetime_end - datetime.now()).days  # Вычисляем, сколько дней осталось до конца подписки
        if days_left in [1, 5, 0]:
            if days_left != 0:
                await bot.send_message(user.id, f"⏳ У вас осталось <b>{days_left} дней</b> до конца подписки.", 
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))   
            else:
                await bot.send_message(user.id, f"⏳ У вас остался <b>последний день</b> подписки.\n Пожалуйста, продлите подписку, чтобы не потерять доступ к сервису.", 
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[kb]))

# Функции для старта cron задач
async def start_cron_jobs():
    aiocron.crontab('*/5 * * * *', func=monitor_servers, start=True)
    aiocron.crontab('0 15 * * *', func=notify_expiring_subs, start=True)