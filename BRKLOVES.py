import os
import asyncio
import logging
import json
import re
from typing import Dict, Set, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ------------------ КОНФИГУРАЦИЯ ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", -1004386994995))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@BRKLOVES")

# ID админа для рассылки (ваш Telegram ID)
ADMIN_ID = 1302410770  # <--- ВСТАВЬТЕ СВОЙ ID

# Файлы для хранения
BLOCKED_FILE = "blocked_users.json"
USERS_FILE = "users.json"

# ------------------ РАБОТА С ФАЙЛАМИ ------------------
def load_blocked_users():
    if os.path.exists(BLOCKED_FILE):
        try:
            with open(BLOCKED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_blocked_users():
    with open(BLOCKED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(blocked_users), f, ensure_ascii=False, indent=2)

def load_users():
    """Загружает список всех пользователей бота"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except:
            return set()
    return set()

def save_users():
    """Сохраняет список всех пользователей бота"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(users), f, ensure_ascii=False, indent=2)

# Загружаем данные
blocked_users: Set[int] = load_blocked_users()
users: Set[int] = load_users()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ------------------ FSM ДЛЯ РАССЫЛКИ ------------------
class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_confirmation = State()

# ------------------ КЛАВИАТУРЫ ------------------
def get_admin_keyboard(user_id: int, username: str = None) -> InlineKeyboardMarkup:
    data = f"{user_id}"
    if username:
        data += f"|{username}"
    
    is_blocked = user_id in blocked_users
    block_button_text = "🔓 Разблокировать" if is_blocked else "🚫 Заблокировать"
    block_callback = f"unblock|{data}" if is_blocked else f"block|{data}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish|{data}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject|{data}")
        ],
        [
            InlineKeyboardButton(text="✏️ Ответить", callback_data=f"reply|{data}"),
            InlineKeyboardButton(text=block_button_text, callback_data=block_callback)
        ]
    ])
    return keyboard

# ------------------ /start ------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    
    # Сохраняем пользователя
    if user_id not in users:
        users.add(user_id)
        save_users()
    
    welcome_text = (
        "👋 Привет!\n"
        "Это предложка Telegram каналу - **\"БРАТСКУ НРАВИТСЯ\"**\n\n"
        "Отправь свое сообщение, и мы опубликуем его в канал"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

# ------------------ КОМАНДА ДЛЯ РАССЫЛКИ (ТОЛЬКО АДМИН) ------------------
@dp.message(Command("send_all"))
async def send_all_command(message: Message, state: FSMContext):
    """Админ-команда для начала рассылки"""
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    
    total_users = len(users)
    blocked_count = len(blocked_users)
    active_users = total_users - blocked_count
    
    await message.answer(
        f"📊 **Статистика пользователей:**\n"
        f"• Всего: {total_users}\n"
        f"• Заблокировано: {blocked_count}\n"
        f"• Активных: {active_users}\n\n"
        f"✏️ Напишите текст для рассылки.\n"
        f"Отправьте `cancel` чтобы отменить.",
        parse_mode="Markdown"
    )
    await state.set_state(BroadcastStates.waiting_for_text)

@dp.message(BroadcastStates.waiting_for_text)
async def broadcast_get_text(message: Message, state: FSMContext):
    """Получает текст для рассылки"""
    if message.text and message.text.lower() == "cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return
    
    # Сохраняем текст
    text = message.text or message.caption or ""
    if not text:
        await message.answer("⚠️ Отправьте текст или отмените (`cancel`)")
        return
    
    await state.update_data(text=text)
    
    # Подтверждение
    total_users = len(users)
    blocked_count = len(blocked_users)
    active_users = total_users - blocked_count
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить всем", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Только активным", callback_data="broadcast_active")
        ],
        [
            InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
        ]
    ])
    
    await message.answer(
        f"📨 **Текст для рассылки:**\n\n{text}\n\n"
        f"👥 Получат: {active_users} активных (из {total_users} всего)\n\n"
        f"Выберите действие:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await state.set_state(BroadcastStates.waiting_for_confirmation)

# ------------------ ОБРАБОТКА КНОПОК РАССЫЛКИ ------------------
@dp.callback_query(lambda c: c.data.startswith("broadcast_"))
async def broadcast_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id != ADMIN_ID:
        await callback.answer("⛔ У вас нет прав.")
        return
    
    data = await state.get_data()
    text = data.get("text", "")
    
    if not text:
        await callback.answer("⚠️ Текст не найден. Начните заново с /send_all")
        await state.clear()
        return
    
    action = callback.data.replace("broadcast_", "")
    
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.answer()
        return
    
    # Определяем, кому отправлять
    if action == "confirm":
        # Всем
        target_users = list(users)
        await callback.message.edit_text("⏳ Начинаю рассылку всем пользователям...")
    elif action == "active":
        # Только активным (не заблокированным)
        target_users = [uid for uid in users if uid not in blocked_users]
        await callback.message.edit_text("⏳ Начинаю рассылку активным пользователям...")
    else:
        await callback.answer("Неизвестное действие")
        return
    
    await callback.answer()
    
    # ----- САМА РАССЫЛКА -----
    sent = 0
    failed = 0
    skipped = 0
    
    for i, uid in enumerate(target_users):
        try:
            await bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            if "bot was blocked by the user" in str(e):
                skipped += 1
            else:
                failed += 1
        
        # Задержка, чтобы не поймать flood
        if (i + 1) % 30 == 0:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.05)  # 50 мс между сообщениями
    
    # Итог
    total = len(target_users)
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"🚫 Заблокировали бота: {skipped}\n"
        f"📊 Всего в списке: {total}",
        parse_mode="Markdown"
    )

# ------------------ ПРЕДЛОЖКИ (ТОЛЬКО В ЛИЧКУ БОТА) ------------------
@dp.message(F.chat.id != ADMIN_CHAT_ID)
async def handle_suggestion(message: Message):
    """Обрабатывает предложки ТОЛЬКО из личных сообщений"""
    user = message.from_user
    user_id = user.id
    
    content = ""
    if message.text:
        content = message.text
    elif message.caption:
        content = message.caption
    else:
        content = "[Медиафайл без текста]"
    
    username = f"@{user.username}" if user.username else None
    user_identifier = username if username else str(user_id)
    
    admin_msg = (
        f"📬 **Новая предложка**\n\n"
        f"👤 **Отправитель:** {user_identifier}\n"
        f"🆔 **ID:** `{user_id}`\n\n"
        f"📝 **Текст предложки:**\n{content}"
    )
    
    try:
        if message.photo:
            await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=message.photo[-1].file_id,
                caption=admin_msg,
                reply_markup=get_admin_keyboard(user_id, user.username),
                parse_mode="Markdown"
            )
        elif message.video:
            await bot.send_video(
                chat_id=ADMIN_CHAT_ID,
                video=message.video.file_id,
                caption=admin_msg,
                reply_markup=get_admin_keyboard(user_id, user.username),
                parse_mode="Markdown"
            )
        elif message.document:
            await bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=message.document.file_id,
                caption=admin_msg,
                reply_markup=get_admin_keyboard(user_id, user.username),
                parse_mode="Markdown"
            )
        else:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                reply_markup=get_admin_keyboard(user_id, user.username),
                parse_mode="Markdown"
            )
        
        await message.answer("✅ Ваше сообщение было отправлено модерации на проверку.")
    
    except Exception as e:
        logging.error(f"Ошибка при отправке админам: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуйте позже.")

# ------------------ ОБРАБОТКА РЕПЛАЯ НА REPLY_TO_USER ------------------
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def handle_admin_reply(message: Message):
    """Обрабатывает Reply на сообщение REPLY_TO_USER"""
    
    if not message.reply_to_message:
        return
    
    reply_to_msg = message.reply_to_message
    
    if not reply_to_msg.text or "REPLY_TO_USER:" not in reply_to_msg.text:
        return
    
    try:
        lines = reply_to_msg.text.split("\n")
        user_id_line = lines[0]
        target_user_id = int(user_id_line.replace("REPLY_TO_USER:", "").strip())
        
        moderator_display = "Модератор"
        for line in lines:
            if "Модератор:" in line:
                moderator_display = line.replace("Модератор:", "").strip()
                break
    except Exception as e:
        await message.answer(f"❌ Не удалось определить пользователя. Ошибка: {e}")
        return
    
    reply_text = message.text or "📎 Медиафайл (без текста)"
    
    try:
        await bot.send_message(
            target_user_id,
            f"✉️ **Ответ от модератора {moderator_display}**\n\n{reply_text}",
            parse_mode="Markdown"
        )
        await message.answer(f"✅ Ответ отправлен пользователю (ID: `{target_user_id}`) от {moderator_display}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение. Ошибка: {e}")

# ------------------ КНОПКИ АДМИНА ------------------
@dp.callback_query(F.data.startswith("publish|"))
async def publish_post(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    moderator = callback.from_user
    moderator_username = f"@{moderator.username}" if moderator.username else moderator.full_name or f"ID: {moderator.id}"
    
    original_msg = callback.message
    caption = original_msg.caption or original_msg.text or ""
    
    # Извлекаем ТОЛЬКО текст предложки
    suggestion_text = ""
    
    if "📝 **Текст предложки:**" in caption:
        suggestion_text = caption.split("📝 **Текст предложки:**")[1].strip()
        for stop_word in ["Пользователь", "Опубликовано", "Отклонено", "Разблокирован", "Заблокирован"]:
            if stop_word in suggestion_text:
                suggestion_text = suggestion_text.split(stop_word)[0].strip()
                break
    else:
        lines = caption.split("\n")
        suggestion_lines = []
        found = False
        
        for line in lines:
            if "Текст предложки:" in line:
                found = True
                continue
            if found:
                if any(word in line for word in ["Пользователь", "Опубликовано", "Отклонено", "Разблокирован", "Заблокирован"]):
                    break
                suggestion_lines.append(line)
        
        suggestion_text = "\n".join(suggestion_lines).strip()
    
    if not suggestion_text:
        suggestion_text = caption
    
    # Очистка текста
    suggestion_text = suggestion_text.strip()
    suggestion_text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF]', '', suggestion_text)
    suggestion_text = re.sub(r'\n\s*\n', '\n\n', suggestion_text)
    
    if not suggestion_text.strip():
        suggestion_text = "📸 Медиафайл (без текста)"
    
    # Футер
    footer = (
        f"\n\n"
        f"💬 [Общение тут](https://t.me/chat_bratsklove)\n"
        f"📩 [Предложить пост](https://t.me/BrkLovesBot)"
    )
    
    final_text = suggestion_text + footer
    
    try:
        if original_msg.photo:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=original_msg.photo[-1].file_id,
                caption=final_text,
                parse_mode="Markdown"
            )
        elif original_msg.video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=original_msg.video.file_id,
                caption=final_text,
                parse_mode="Markdown"
            )
        elif original_msg.document:
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=original_msg.document.file_id,
                caption=final_text,
                parse_mode="Markdown"
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=final_text,
                parse_mode="Markdown"
            )
        
        await callback.answer("✅ Пост опубликован в канале!")
        
        current_text = callback.message.text or callback.message.caption or ""
        
        if current_text:
            statuses = ["✅ **Опубликовано**", "❌ **Отклонено**", "🔓 **Разблокирован**", "🚫 **Заблокирован**"]
            base_text = current_text
            for status in statuses:
                if status in base_text:
                    base_text = base_text.split(status)[0].strip()
                    break
            
            new_text = f"{base_text}\n\n✅ **Опубликовано** (модератор: {moderator_username})"
            
            await callback.message.edit_text(
                new_text,
                parse_mode="Markdown"
            )
        else:
            await callback.message.answer(
                f"✅ **Опубликовано** (модератор: {moderator_username})",
                parse_mode="Markdown"
            )
    
    except Exception as e:
        logging.error(f"Ошибка публикации: {e}")
        await callback.answer("❌ Ошибка публикации", show_alert=True)

@dp.callback_query(F.data.startswith("reject|"))
async def reject_post(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    moderator = callback.from_user
    moderator_username = f"@{moderator.username}" if moderator.username else moderator.full_name or f"ID: {moderator.id}"
    
    await callback.answer("❌ Отказано")
    
    current_text = callback.message.text or callback.message.caption or ""
    
    if current_text:
        statuses = ["✅ **Опубликовано**", "❌ **Отклонено**", "🔓 **Разблокирован**", "🚫 **Заблокирован**"]
        base_text = current_text
        for status in statuses:
            if status in base_text:
                base_text = base_text.split(status)[0].strip()
                break
        
        new_text = f"{base_text}\n\n❌ **Отклонено** (модератор: {moderator_username})"
        
        await callback.message.edit_text(
            new_text,
            parse_mode="Markdown"
        )
    else:
        await callback.message.answer(
            f"❌ **Отклонено** (модератор: {moderator_username})",
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("reply|"))
async def reply_to_user(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    moderator_username = callback.from_user.username
    if moderator_username:
        moderator_display = f"@{moderator_username}"
    else:
        moderator_display = callback.from_user.full_name or f"ID: {callback.from_user.id}"
    
    await callback.message.answer(
        f"REPLY_TO_USER:{user_id}\n"
        f"Ответьте реплаем на это сообщение, и бот отправит текст пользователю.\n\n"
        f"Модератор: {moderator_display}"
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("block|"))
async def block_user(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    moderator = callback.from_user
    moderator_username = f"@{moderator.username}" if moderator.username else moderator.full_name or f"ID: {moderator.id}"
    
    full_text = callback.message.text or callback.message.caption or ""
    
    statuses = ["✅ **Опубликовано**", "❌ **Отклонено**", "🔓 **Разблокирован**", "🚫 **Заблокирован**"]
    base_text = full_text
    for status in statuses:
        if status in base_text:
            base_text = base_text.split(status)[0].strip()
            break
    
    if user_id in blocked_users:
        blocked_users.remove(user_id)
        save_blocked_users()
        await callback.answer("🔓 Пользователь разблокирован")
        
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish|{data_part}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject|{data_part}")
            ],
            [
                InlineKeyboardButton(text="✏️ Ответить", callback_data=f"reply|{data_part}"),
                InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block|{data_part}")
            ]
        ])
        
        new_text = f"{base_text}\n\n🔓 **Разблокирован** (модератор: {moderator_username})"
        
        await callback.message.edit_text(
            new_text,
            reply_markup=new_keyboard,
            parse_mode="Markdown"
        )
    else:
        blocked_users.add(user_id)
        save_blocked_users()
        await callback.answer("🚫 Пользователь заблокирован")
        
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish|{data_part}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject|{data_part}")
            ],
            [
                InlineKeyboardButton(text="✏️ Ответить", callback_data=f"reply|{data_part}"),
                InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"unblock|{data_part}")
            ]
        ])
        
        new_text = f"{base_text}\n\n🚫 **Заблокирован** (модератор: {moderator_username})"
        
        await callback.message.edit_text(
            new_text,
            reply_markup=new_keyboard,
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("unblock|"))
async def unblock_user(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    moderator = callback.from_user
    moderator_username = f"@{moderator.username}" if moderator.username else moderator.full_name or f"ID: {moderator.id}"
    
    full_text = callback.message.text or callback.message.caption or ""
    
    statuses = ["✅ **Опубликовано**", "❌ **Отклонено**", "🔓 **Разблокирован**", "🚫 **Заблокирован**"]
    base_text = full_text
    for status in statuses:
        if status in base_text:
            base_text = base_text.split(status)[0].strip()
            break
    
    if user_id in blocked_users:
        blocked_users.remove(user_id)
        save_blocked_users()
        await callback.answer("🔓 Пользователь разблокирован")
        
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish|{data_part}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject|{data_part}")
            ],
            [
                InlineKeyboardButton(text="✏️ Ответить", callback_data=f"reply|{data_part}"),
                InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block|{data_part}")
            ]
        ])
        
        new_text = f"{base_text}\n\n🔓 **Разблокирован** (модератор: {moderator_username})"
        
        await callback.message.edit_text(
            new_text,
            reply_markup=new_keyboard,
            parse_mode="Markdown"
        )
    else:
        await callback.answer("⚠️ Пользователь уже разблокирован")

# ------------------ ЗАПУСК ------------------
async def main():
    print("✅ Бот запущен и готов к работе!")
    print(f"📢 Канал: {CHANNEL_ID}")
    print(f"👥 Админ-чат: {ADMIN_CHAT_ID}")
    print(f"👤 Всего пользователей: {len(users)}")
    print(f"🔒 Загружено блокировок: {len(blocked_users)}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
