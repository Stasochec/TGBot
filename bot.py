import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.session.aiohttp import AiohttpSession
import shutil

from config import BOT_TOKEN, HOMEWORK_FILE, HOMEWORK_TIMESTAMP, get_admins

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')

# --- Инициализация бота ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- FSM ---
class AdminStates(StatesGroup):
    waiting_for_file = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class SupportState(StatesGroup):
    waiting_for_request = State()

class UrgentState(StatesGroup):  # ✅ Добавлено: состояние для срочной рассылки
    waiting = State()

# --- Хранилища ---
waiting_support_requests = {}  # {user_id: time}
active_support_chats = {}      # {user_id: admin_id}

# --- Динамическое главное меню ---
def get_main_menu(user_id: int):
    buttons = [
        [KeyboardButton(text="📚 Получить домашнее задание")],
        [KeyboardButton(text="🛠 Связаться с поддержкой")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    if user_id in get_admins():
        buttons.append([KeyboardButton(text="🔐 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Клавиатура во время поддержки
support_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔚 Завершить диалог")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# --- Функции ---
def add_user(user_id: int):
    user_id = str(user_id)
    if os.path.exists('users.txt'):
        with open('users.txt', 'r') as f:
            if user_id in f.read():
                return
    with open('users.txt', 'a') as f:
        f.write(user_id + '\n')

def get_all_users():
    if not os.path.exists('users.txt'):
        return []
    with open('users.txt', 'r') as f:
        return [line.strip() for line in f if line.strip().isdigit()]

async def broadcast_message(bot: Bot, message: str):
    users = get_all_users()
    new_users = []
    removed = 0
    for user_id in users:
        try:
            await bot.send_message(int(user_id), message)
            new_users.append(user_id)
        except Exception as e:
            if "blocked" in str(e).lower() or "kicked" in str(e).lower():
                removed += 1
                logging.warning(f"Удалён {user_id}: {e}")
            else:
                new_users.append(user_id)
    with open('users.txt', 'w') as f:
        for uid in new_users:
            f.write(uid + '\n')
    logging.info(f"Чистка: удалено {removed} неактивных")

# --- КОМАНДЫ И КНОПКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Я бот для домашних заданий.\n"
        "Выбери нужное действие в меню ниже 👇",
        reply_markup=get_main_menu(message.from_user.id)
    )

@dp.message(F.text == "📚 Получить домашнее задание")
async def cmd_homework(message: types.Message):
    add_user(message.from_user.id)
    if not os.path.exists(HOMEWORK_FILE):
        await message.answer("Пока нет загруженного домашнего задания.")
        return
    try:
        timestamp = "неизвестно"
        if os.path.exists(HOMEWORK_TIMESTAMP):
            with open(HOMEWORK_TIMESTAMP, 'r', encoding='utf-8') as f:
                timestamp = f.read().strip()

        caption = f"📬 Актуальное домашнее задание\nОбновлено: {timestamp}"

        await message.answer_document(
            document=types.FSInputFile(HOMEWORK_FILE),
            caption=caption
        )
        logging.info(f"Пользователь {message.from_user.id} получил домашку")
    except Exception as e:
        await message.answer(f"Ошибка при отправке: {e}")

@dp.message(F.text == "🛠 Связаться с поддержкой")
async def cmd_support(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    admins = get_admins()

    if not admins:
        await message.answer("К сожалению, администраторы недоступны.")
        return

    if user_id in waiting_support_requests:
        await message.answer("Вы уже в очереди на поддержку. Ожидайте ответа.")
        return

    waiting_support_requests[user_id] = datetime.now().strftime("%H:%M")
    await state.set_state(SupportState.waiting_for_request)
    await message.answer("📩 Вы запросили поддержку. Ожидайте, когда администратор подключится...")

    for admin_id in admins:
        try:
            await bot.send_message(
                admin_id,
                f"🆘 Запрос в поддержку от {user_id}\n"
                f"Имя: {message.from_user.full_name}\n"
                f"Юзернейм: @{message.from_user.username or 'нет'}\n"
                f"Время: {waiting_support_requests[user_id]}\n\n"
                f"👉 Нажмите /connect {user_id} для подключения\n"
                f"📌 Или /requests для просмотра всех заявок",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.warning(f"Не удалось уведомить админа {admin_id}: {e}")

@dp.message(F.text == "ℹ️ О боте")
async def btn_about(message: types.Message):
    await message.answer(
        "🤖 <b>О боте</b>\n\n"
        "Этот бот помогает получать домашние задания.\n\n"
        "Все действия — через кнопки.\n"
        "Нет команд — только удобство.\n\n",
        parse_mode="HTML"
    )

@dp.message(F.text == "🔐 Админ-панель")
async def btn_admin_panel(message: types.Message):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Загрузить новое задание")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📢 Сделать рассылку")],
            [KeyboardButton(text="❗ Срочное уведомление")],
            [KeyboardButton(text="📋 Просмотреть заявки в поддержку")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("🔐 Вы в админ-панели. Выберите действие:", reply_markup=keyboard)

@dp.message(F.text == "📤 Загрузить новое задание")
async def btn_upload(message: types.Message, state: FSMContext):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    await message.answer("Отправьте новый файл с домашним заданием (.xlsx или .zip).")
    await state.set_state(AdminStates.waiting_for_file)

@dp.message(AdminStates.waiting_for_file, F.document)
async def receive_homework_file(message: types.Message, state: FSMContext):
    document = message.document
    file_name = document.file_name

    if not file_name.endswith((".xlsx", ".zip")):
        await message.answer("Файл должен быть .xlsx или .zip")
        return

    # Резервная копия
    if os.path.exists(HOMEWORK_FILE):
        backup_name = f"data/backup/Домашка_{datetime.now().strftime('%d%m_%H%M')}.xlsx"
        shutil.copy(HOMEWORK_FILE, backup_name)

    # Скачивание
    file = await bot.get_file(document.file_id)
    await bot.download_file(file.file_path, HOMEWORK_FILE)

    # Время обновления по МСК
    moscow_time = datetime.now(ZoneInfo("Europe/Moscow"))
    timestamp = moscow_time.strftime("%d.%m.%Y в %H:%M")

    with open(HOMEWORK_TIMESTAMP, 'w', encoding='utf-8') as f:
        f.write(timestamp)

    await message.answer(f"✅ Файл '{file_name}' успешно обновлён и доступен всем!")
    await message.answer("Выберите действие:", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

    # Рассылка
    await broadcast_message(bot, f"📚 Новое домашнее задание загружено!\n"
                                f"📄 {file_name}\n"
                                f"🕒 {timestamp}\n"
                                f"👉 Нажмите 'Получить домашнее задание'")

@dp.message(F.text == "📊 Статистика")
async def cmd_stats(message: types.Message):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    users = get_all_users()
    await message.answer(f"📊 Всего пользователей: <b>{len(users)}</b>", parse_mode="HTML")

@dp.message(F.text == "📢 Сделать рассылку")
async def btn_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    await message.answer("✉️ Введите сообщение для рассылки всем пользователям.")
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    await broadcast_message(bot, text)
    await message.answer("✅ Рассылка завершена.", reply_markup=get_main_menu(message.from_user.id))

@dp.message(F.text == "❗ Срочное уведомление")
async def btn_urgent(message: types.Message, state: FSMContext):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    await message.answer("⚠️ Введите срочное сообщение (всем пользователям):")
    await state.set_state(UrgentState.waiting)

@dp.message(UrgentState.waiting)
async def send_urgent(message: types.Message, state: FSMContext):
    text = f"❗ СРОЧНО: {message.text}"
    await broadcast_message(bot, text)
    await message.answer("✅ Срочное уведомление отправлено!")
    await state.clear()

@dp.message(F.text == "📋 Просмотреть заявки в поддержку")
async def cmd_requests(message: types.Message):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return

    if not waiting_support_requests:
        await message.answer("📭 Нет активных заявок в поддержку.")
        return

    text = "📋 <b>Активные заявки в поддержку:</b>\n\n"
    for user_id, time in waiting_support_requests.items():
        text += (
            f"👤 Пользователь: <code>{user_id}</code>\n"
            f"⏰ Время запроса: {time}\n"
            f"📌 Чтобы подключиться — отправьте: <code>/connect {user_id}</code>\n"
            f"──────────────────\n"
        )

    await message.answer(text, parse_mode="HTML")

@dp.message(Command("requests"))
async def cmd_requests_by_command(message: types.Message):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return

    if not waiting_support_requests:
        await message.answer("📭 Нет активных заявок в поддержку.")
        return

    text = "📋 <b>Активные заявки в поддержку:</b>\n\n"
    for user_id, time in waiting_support_requests.items():
        text += (
            f"👤 Пользователь: <code>{user_id}</code>\n"
            f"⏰ Время запроса: {time}\n"
            f"📌 Чтобы подключиться — отправьте: <code>/connect {user_id}</code>\n"
            f"──────────────────\n"
        )

    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🔙 Назад")
async def btn_back(message: types.Message):
    await message.answer(
        "Вы вернулись в главное меню.",
        reply_markup=get_main_menu(message.from_user.id)
    )

# --- Поддержка: подключение и чат ---
@dp.message(Command("connect"))
async def cmd_connect(message: types.Message):
    if message.from_user.id not in get_admins():
        await message.answer("У вас нет доступа.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /connect <user_id>")
        return
    user_id = int(parts[1])
    if user_id in active_support_chats:
        await message.answer("Пользователь уже в чате с другим админом.")
        return
    if user_id in waiting_support_requests:
        del waiting_support_requests[user_id]

    active_support_chats[user_id] = message.from_user.id

    await bot.send_message(
        user_id,
        "✅ Администратор подключился. Вы можете отправлять сообщения.",
        reply_markup=support_keyboard
    )
    await message.answer(
        f"✅ Вы подключены к пользователю {user_id}. Все сообщения будут пересылаться.",
        reply_markup=support_keyboard
    )

@dp.message(Command("end"))
async def cmd_end(message: types.Message):
    admin_id = message.from_user.id
    user_id = None
    for uid, aid in active_support_chats.items():
        if aid == admin_id:
            user_id = uid
            break
    if not user_id:
        await message.answer("Вы не в чате поддержки.")
        return
    await message.answer("✅ Диалог завершён.", reply_markup=get_main_menu(message.from_user.id))
    try:
        await bot.send_message(user_id, "✅ Администратор завершил диалог.")
    except Exception as e:
        logging.warning(e)
    del active_support_chats[user_id]

@dp.message(F.text == "🔚 Завершить диалог")
async def btn_end_support(message: types.Message):
    user_id = message.from_user.id

    # Проверка: завершает ли админ
    if user_id in active_support_chats.values():
        for uid, aid in active_support_chats.items():
            if aid == user_id:
                del active_support_chats[uid]
                try:
                    await bot.send_message(uid, "🔚 Администратор завершил диалог поддержки.", reply_markup=get_main_menu(uid))
                except Exception as e:
                    logging.warning(f"Не удалось уведомить пользователя {uid}: {e}")
                await message.answer("🔚 Диалог завершён.", reply_markup=get_main_menu(user_id))
                logging.info(f"Админ {user_id} завершил диалог с {uid}")
                return

    # Проверка: завершает ли пользователь
    if user_id in active_support_chats:
        admin_id = active_support_chats[user_id]
        del active_support_chats[user_id]
        try:
            await bot.send_message(admin_id, f"🔚 Пользователь {user_id} завершил диалог.")
        except Exception as e:
            logging.warning(f"Не удалось уведомить админа {admin_id}: {e}")
        await message.answer("🔚 Вы завершили диалог с поддержкой.", reply_markup=get_main_menu(user_id))
        logging.info(f"Пользователь {user_id} завершил диалог")
        return

    await message.answer(
        "Вы не находитесь в диалоге поддержки.",
        reply_markup=get_main_menu(user_id)
    )

# --- Пересылка сообщений ---
@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    admin_id = message.from_user.id

    # 1. Админ отвечает пользователю
    if admin_id in active_support_chats.values():
        for uid, aid in active_support_chats.items():
            if aid == admin_id:
                target = uid
                if message.text == "/end":
                    await cmd_end(message)
                    return
                try:
                    if message.sticker:
                        await bot.send_sticker(target, sticker=message.sticker.file_id)
                    elif message.photo:
                        await bot.send_photo(target, photo=message.photo[-1].file_id, caption=message.caption)
                    elif message.document:
                        await bot.send_document(target, document=message.document.file_id, caption=message.caption)
                    elif message.video:
                        await bot.send_video(target, video=message.video.file_id, caption=message.caption)
                    elif message.voice:
                        await bot.send_voice(target, voice=message.voice.file_id, caption=message.caption)
                    elif message.video_note:
                        await bot.send_video_note(target, video_note=message.video_note.file_id)
                    elif message.location:
                        await bot.send_location(target, latitude=message.location.latitude, longitude=message.location.longitude)
                    elif message.contact:
                        await bot.send_contact(target, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
                    elif message.text:
                        await bot.send_message(target, message.text)
                    else:
                        await bot.send_message(target, "📨 Неизвестный тип сообщения")
                except Exception as e:
                    await message.answer(f"❌ Ошибка при отправке: {e}")
                return

    # 2. Пользователь пишет админу
    if user_id in active_support_chats:
        admin_id = active_support_chats[user_id]
        try:
            if message.sticker:
                await bot.send_message(admin_id, f"📌 Стикер от пользователя {user_id}:")
                await bot.send_sticker(admin_id, sticker=message.sticker.file_id)
            elif message.photo:
                caption = f"🖼 Фото от пользователя {user_id}"
                if message.caption:
                    caption += f"\n📝 Подпись: {message.caption}"
                await bot.send_photo(admin_id, photo=message.photo[-1].file_id, caption=caption)
            elif message.document:
                caption = f"📎 Файл от пользователя {user_id}"
                if message.caption:
                    caption += f"\n📝 Подпись: {message.caption}"
                await bot.send_document(admin_id, document=message.document.file_id, caption=caption)
            elif message.video:
                caption = f"🎬 Видео от пользователя {user_id}"
                if message.caption:
                    caption += f"\n📝 Подпись: {message.caption}"
                await bot.send_video(admin_id, video=message.video.file_id, caption=caption)
            elif message.voice:
                await bot.send_message(admin_id, f"🎧 Голосовое от пользователя {user_id}")
                await bot.send_voice(admin_id, voice=message.voice.file_id)
            elif message.video_note:
                await bot.send_message(admin_id, f"⭕ Круговое видео от пользователя {user_id}")
                await bot.send_video_note(admin_id, video_note=message.video_note.file_id)
            elif message.location:
                await bot.send_message(admin_id, f"📍 Локация от пользователя {user_id}")
                await bot.send_location(admin_id, latitude=message.location.latitude, longitude=message.location.longitude)
            elif message.contact:
                await bot.send_message(admin_id, f"📞 Контакт от пользователя {user_id}")
                await bot.send_contact(admin_id, phone_number=message.contact.phone_number, first_name=message.contact.first_name)
            elif message.text:
                await bot.send_message(admin_id, f"💬 От пользователя {user_id}:\n{message.text}")
            else:
                await bot.send_message(admin_id, f"📨 Неизвестное сообщение от {user_id}")
        except Exception as e:
            await message.answer("❌ Не удалось отправить сообщение админу.")
        return

    # Если не поддержка — игнор (остальные обработчики через F.text сработают)

# --- Запуск ---
async def main():
    admins = get_admins()
    if admins:
        try:
            await bot.send_message(chat_id=admins[0], text="✅ Бот запущен и готов к работе!")
        except Exception as e:
            logging.error(f"Не удалось отправить админу при старте: {e}")
    logging.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
