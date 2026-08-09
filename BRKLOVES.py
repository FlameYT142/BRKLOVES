import os
import asyncio
import logging
from typing import Dict, Set

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

# ------------------ КОНФИГУРАЦИЯ ------------------
# Бот берет данные из переменных окружения (настраиваются в панели Bothost)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", -1004386994995))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@BRKLOVES")

# Хранилище заблокированных пользователей
blocked_users: Set[int] = set()

# Словарь для ожидания ответа админа
waiting_for_reply: Dict[int, dict] = {}

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ------------------ КЛАВИАТУРЫ АДМИНА ------------------
def get_admin_keyboard(user_id: int, username: str = None) -> InlineKeyboardMarkup:
    """Кнопки для администратора под каждой предложкой"""
    data = f"{user_id}"
    if username:
        data += f"|{username}"
    
    # Проверяем, заблокирован ли пользователь
    is_blocked = user_id in blocked_users
    
    # Выбираем текст для кнопки блокировки
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

# ------------------ ОСНОВНЫЕ КОМАНДЫ ------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    
    if user_id in blocked_users:
        await message.answer("🚫 Вы заблокированы модерацией. Вы не можете предлагать посты.")
        return
    
    welcome_text = (
        "👋 Привет!\n"
        "Это предложка Telegram каналу - **\"БРАТСКУ НРАВИТСЯ\"**\n\n"
        "Отправь свое сообщение, и мы опубликуем его в канал"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message()
async def handle_suggestion(message: Message):
    user = message.from_user
    user_id = user.id
    
    # Проверка на блокировку
    if user_id in blocked_users:
        await message.answer("🚫 Вы заблокированы модерацией. Ваши предложки не принимаются.")
        return
    
    # Получаем текст или подпись к медиа
    content = ""
    if message.text:
        content = message.text
    elif message.caption:
        content = message.caption
    else:
        content = "[Медиафайл без текста]"
    
    # Определяем юзернейм
    username = f"@{user.username}" if user.username else None
    user_identifier = username if username else str(user_id)
    
    # Формируем сообщение для админов
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

# ------------------ ОБРАБОТКА ДЕЙСТВИЙ АДМИНА ------------------
@dp.callback_query(F.data.startswith("publish|"))
async def publish_post(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    parts = data_part.split("|")
    user_id = int(parts[0])
    
    original_msg = callback.message
    caption = original_msg.caption or original_msg.text
    
    # Извлекаем ТОЛЬКО текст предложки (без служебной информации)
    if "📝 **Текст предложки:**" in caption:
        suggestion_text = caption.split("📝 **Текст предложки:**")[1].strip()
    else:
        lines = caption.split("\n")
        for i, line in enumerate(lines):
            if "Текст предложки:" in line:
                suggestion_text = "\n".join(lines[i+1:]).strip()
                break
        else:
            suggestion_text = caption
    
    # Создаём кнопку "Предложить пост" под постом
    suggest_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Предложить пост", url="https://t.me/BrkLovesBot")]
    ])
    
    try:
        if original_msg.photo:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=original_msg.photo[-1].file_id,
                caption=suggestion_text,
                reply_markup=suggest_button
            )
        elif original_msg.video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=original_msg.video.file_id,
                caption=suggestion_text,
                reply_markup=suggest_button
            )
        elif original_msg.document:
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=original_msg.document.file_id,
                caption=suggestion_text,
                reply_markup=suggest_button
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=suggestion_text,
                reply_markup=suggest_button
            )
        
        await callback.answer("✅ Пост опубликован в канале!")
        await callback.message.edit_text(
            f"{callback.message.text or callback.message.caption}\n\n✅ **Опубликовано**",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка публикации: {e}")
        await callback.answer("❌ Ошибка публикации", show_alert=True)

@dp.callback_query(F.data.startswith("reject|"))
async def reject_post(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    await callback.answer("❌ Отказано")
    await callback.message.edit_text(
        f"{callback.message.text or callback.message.caption}\n\n❌ **Отклонено**",
        parse_mode="Markdown"
    )
    
    try:
        await bot.send_message(
            user_id,
            "❌ К сожалению, ваша предложка была отклонена модерацией."
        )
    except:
        pass

@dp.callback_query(F.data.startswith("reply|"))
async def reply_to_user(callback: CallbackQuery):
    """Модератор нажимает 'Ответить' — бот запоминает, что нужно ответить этому пользователю"""
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    # Определяем юзернейм модератора
    moderator_username = callback.from_user.username
    if moderator_username:
        moderator_display = f"@{moderator_username}"
    else:
        # Если юзернейма нет, используем имя или ID
        moderator_display = callback.from_user.full_name or f"ID: {callback.from_user.id}"
    
    # Сохраняем в словарь, что этот модератор хочет ответить пользователю
    waiting_for_reply[callback.from_user.id] = {
        "user_id": user_id,
        "moderator_id": callback.from_user.id,
        "moderator_display": moderator_display
    }
    
    await callback.message.answer(
        f"✏️ Напишите текст ответа для пользователя (ID: `{user_id}`).\n"
        "Ваше сообщение будет отправлено ему от имени бота.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message()
async def handle_admin_reply(message: Message):
    """Обрабатывает ответ модератора и отправляет пользователю"""
    admin_id = message.from_user.id
    
    # Проверяем, ждёт ли этот модератор ответа
    if admin_id in waiting_for_reply:
        reply_data = waiting_for_reply.pop(admin_id)
        target_user_id = reply_data["user_id"]
        moderator_display = reply_data["moderator_display"]
        
        # Получаем текст ответа
        reply_text = message.text or "📎 Медиафайл (без текста)"
        
        try:
            await bot.send_message(
                target_user_id,
                f"✉️ **Ответ от модератора ({moderator_display}):**\n\n{reply_text}",
                parse_mode="Markdown"
            )
            await message.answer(
                f"✅ Ответ отправлен пользователю (ID: `{target_user_id}`) от {moderator_display}",
                parse_mode="Markdown"
            )
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить сообщение. Ошибка: {e}")
    else:
        # Модератор просто написал текст в чат — это не ответ пользователю
        await message.answer(
            "⚠️ Чтобы ответить пользователю, нажмите кнопку '✏️ Ответить' под его предложкой.\n"
            "А затем отправьте текст — он уйдёт пользователю.",
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("block|"))
async def block_user(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    if user_id in blocked_users:
        blocked_users.remove(user_id)
        await callback.answer("🔓 Пользователь разблокирован")
        await callback.message.edit_text(
            f"{callback.message.text or callback.message.caption}\n\n🔓 **Разблокирован**",
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                user_id,
                "🔓 Вы были разблокированы модерацией. Теперь вы снова можете предлагать посты."
            )
        except:
            pass
    else:
        blocked_users.add(user_id)
        await callback.answer("🚫 Пользователь заблокирован")
        await callback.message.edit_text(
            f"{callback.message.text or callback.message.caption}\n\n🚫 **Пользователь заблокирован**",
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                user_id,
                "🚫 Вы были заблокированы модерацией. Вы больше не можете предлагать посты.\n"
                "Причина: нарушение правил предложки."
            )
        except:
            pass

@dp.callback_query(F.data.startswith("unblock|"))
async def unblock_user(callback: CallbackQuery):
    data_part = callback.data.split("|")[1]
    user_id = int(data_part.split("|")[0])
    
    if user_id in blocked_users:
        blocked_users.remove(user_id)
        await callback.answer("🔓 Пользователь разблокирован")
        await callback.message.edit_text(
            f"{callback.message.text or callback.message.caption}\n\n🔓 **Разблокирован**",
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                user_id,
                "🔓 Вы были разблокированы модерацией. Теперь вы снова можете предлагать посты."
            )
        except:
            pass
    else:
        await callback.answer("⚠️ Пользователь уже разблокирован")

# ------------------ ЗАПУСК БОТА ------------------
async def main():
    print("✅ Бот запущен и готов к работе!")
    print(f"📢 Канал: {CHANNEL_ID}")
    print(f"👥 Админ-чат: {ADMIN_CHAT_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
