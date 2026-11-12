import asyncio
import logging
import os
import sqlite3
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

# Render Dashboard -> Environment:
# BOT_TOKEN = Telegram bot token from @BotFather
# ADMIN_ID  = Your numeric Telegram user ID
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID environment variable is missing or invalid.")

# On Render, set DB_PATH=/var/data/kino.db and attach a persistent disk
DB_PATH = os.getenv("DB_PATH", "kino.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH)
db.execute("""
    CREATE TABLE IF NOT EXISTS kino (
        kod TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        nom TEXT NOT NULL
    )
""")
db.execute("""
    CREATE TABLE IF NOT EXISTS kanal (
        chat_id TEXT PRIMARY KEY,
        nom TEXT NOT NULL,
        link TEXT NOT NULL
    )
""")
db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY
    )
""")
db.commit()

bot = Bot(token=TOKEN)
dp = Dispatcher()


class AddMovie(StatesGroup):
    kod = State()
    video = State()
    nom = State()


class DelMovie(StatesGroup):
    kod = State()


class AddChannel(StatesGroup):
    ch = State()


def is_admin(message: types.Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


def admin_kb():
    b = InlineKeyboardBuilder()
    b.button(text="➕ Kino qo'shish", callback_data="a_addmovie")
    b.button(text="🗑 Kino o'chirish", callback_data="a_delmovie")
    b.button(text="📋 Kinolar ro'yxati", callback_data="a_list")
    b.button(text="📢 Kanal qo'shish", callback_data="a_addch")
    b.button(text="❌ Kanal o'chirish", callback_data="a_delch")
    b.button(text="📊 Statistika", callback_data="a_stat")
    b.adjust(2)
    return b.as_markup()


async def not_subscribed(user_id: int):
    missing = []
    rows = db.execute(
        "SELECT chat_id, nom, link FROM kanal"
    ).fetchall()

    for chat_id, nom, link in rows:
        try:
            member = await bot.get_chat_member(int(chat_id), user_id)
            if member.status in ("left", "kicked"):
                missing.append((nom, link))
        except Exception:
            # Check that the bot is an administrator in every required channel.
            logging.exception("Kanal obunasini tekshirib bo'lmadi: %s", chat_id)
            missing.append((nom, link))

    return missing


def sub_kb(channels):
    b = InlineKeyboardBuilder()
    for nom, link in channels:
        b.button(text=f"📢 {nom}", url=link)
    b.button(text="✅ Tekshirish", callback_data="check")
    b.adjust(1)
    return b.as_markup()


# ---------------- USER ----------------

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)",
               (message.from_user.id,))
    db.commit()

    channels = await not_subscribed(message.from_user.id)
    if channels:
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=sub_kb(channels)
        )
        return

    await message.answer("Salom! Kino kodini yuboring 🎬")


@dp.callback_query(F.data == "check")
async def check_subscription(callback: types.CallbackQuery):
    channels = await not_subscribed(callback.from_user.id)
    if channels:
        await callback.answer(
            "Hali hamma kanalga obuna bo'lmadingiz ❌",
            show_alert=True
        )
        return

    await callback.message.answer("✅ Rahmat! Endi kino kodini yuboring 🎬")
    await callback.answer()


# ---------------- ADMIN PANEL ----------------

@dp.message(Command("admin"), is_admin)
async def admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("👨‍💻 Admin panel", reply_markup=admin_kb())


@dp.callback_query(F.data == "a_addmovie", F.from_user.id == ADMIN_ID)
async def add_movie_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddMovie.kod)
    await callback.message.answer("Kino kodini yozing (masalan: 101):")
    await callback.answer()


@dp.message(AddMovie.kod, is_admin)
async def add_movie_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    if not code:
        await message.answer("Kino kodi bo'sh bo'lmasin. Qayta kiriting:")
        return

    await state.update_data(kod=code)
    await state.set_state(AddMovie.video)
    await message.answer("Endi kinoning videosini yuboring:")


@dp.message(AddMovie.video, F.video, is_admin)
async def add_movie_video(message: types.Message, state: FSMContext):
    await state.update_data(file_id=message.video.file_id)
    await state.set_state(AddMovie.nom)
    await message.answer("Kino nomini yozing:")


@dp.message(AddMovie.video, is_admin)
async def add_movie_video_invalid(message: types.Message):
    await message.answer("Iltimos, kino videosini Telegram video sifatida yuboring.")


@dp.message(AddMovie.nom, is_admin)
async def add_movie_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Kino nomi bo'sh bo'lmasin. Qayta kiriting:")
        return

    data = await state.get_data()
    db.execute(
        "INSERT OR REPLACE INTO kino (kod, file_id, nom) VALUES (?, ?, ?)",
        (data["kod"], data["file_id"], name)
    )
    db.commit()
    await state.clear()
    await message.answer(
        f"✅ Saqlandi: {data['kod']} — {name}",
        reply_markup=admin_kb()
    )


@dp.callback_query(F.data == "a_delmovie", F.from_user.id == ADMIN_ID)
async def delete_movie_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DelMovie.kod)
    await callback.message.answer("O'chiriladigan kino kodini yozing:")
    await callback.answer()


@dp.message(DelMovie.kod, is_admin)
async def delete_movie_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    cursor = db.execute("DELETE FROM kino WHERE kod = ?", (code,))
    db.commit()
    deleted = cursor.rowcount
    await state.clear()

    result = "🗑 Kino o'chirildi." if deleted else "Bunday kodli kino topilmadi."
    await message.answer(result, reply_markup=admin_kb())


@dp.callback_query(F.data == "a_list", F.from_user.id == ADMIN_ID)
async def list_movies(callback: types.CallbackQuery):
    rows = db.execute("SELECT kod, nom FROM kino ORDER BY kod").fetchall()
    result = "\n".join(f"{code} — {name}" for code, name in rows)
    await callback.message.answer("📋 Kinolar:\n" + (result[:4000] or "Kinolar yo'q"))
    await callback.answer()


@dp.callback_query(F.data == "a_addch", F.from_user.id == ADMIN_ID)
async def add_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddChannel.ch)
    await callback.message.answer(
        "Kanalning ochiq username'ini yuboring (masalan: @kanalim).\n"
        "Avval botni o'sha kanalga ADMIN qilib qo'shing."
    )
    await callback.answer()


@dp.message(AddChannel.ch, is_admin)
async def add_channel(message: types.Message, state: FSMContext):
    channel_name = (message.text or "").strip()
    try:
        chat = await bot.get_chat(channel_name)
        if not chat.username:
            await message.answer(
                "Bu kanal uchun ochiq username topilmadi. "
                "@username ko'rinishidagi ochiq kanal yuboring."
            )
            return

        bot_member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if bot_member.status != "administrator":
            await message.answer("Bot avval shu kanalga administrator qilinishi kerak.")
            return

        link = f"https://t.me/{chat.username}"
        db.execute(
            "INSERT OR REPLACE INTO kanal (chat_id, nom, link) VALUES (?, ?, ?)",
            (str(chat.id), chat.title, link)
        )
        db.commit()
        await message.answer(
            f"✅ Kanal qo'shildi: {chat.title}",
            reply_markup=admin_kb()
        )
        await state.clear()

    except Exception as error:
        logging.exception("Kanal qo'shishda xato")
        await message.answer(
            "❌ Kanal qo'shilmadi. Username to'g'riligini va bot admin ekanini tekshiring."
        )


@dp.callback_query(F.data == "a_delch", F.from_user.id == ADMIN_ID)
async def delete_channel_menu(callback: types.CallbackQuery):
    rows = db.execute("SELECT chat_id, nom FROM kanal").fetchall()
    if not rows:
        await callback.message.answer("Kanallar yo'q.")
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    for chat_id, name in rows:
        b.button(text=f"❌ {name}", callback_data=f"delch:{chat_id}")
    b.adjust(1)
    await callback.message.answer(
        "Qaysi kanalni o'chirasiz?",
        reply_markup=b.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delch:"), F.from_user.id == ADMIN_ID)
async def delete_channel(callback: types.CallbackQuery):
    chat_id = callback.data.split(":", 1)[1]
    db.execute("DELETE FROM kanal WHERE chat_id = ?", (chat_id,))
    db.commit()
    await callback.message.answer("✅ Kanal o'chirildi.")
    await callback.answer()


@dp.callback_query(F.data == "a_stat", F.from_user.id == ADMIN_ID)
async def statistics(callback: types.CallbackQuery):
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    movies = db.execute("SELECT COUNT(*) FROM kino").fetchone()[0]
    channels = db.execute("SELECT COUNT(*) FROM kanal").fetchone()[0]

    await callback.message.answer(
        f"📊 Foydalanuvchilar: {users}\n"
        f"🎬 Kinolar: {movies}\n"
        f"📢 Kanallar: {channels}"
    )
    await callback.answer()


# ---------------- MOVIE SEARCH ----------------
# Keep this handler after the more specific text/FSM handlers.

@dp.message(F.text)
async def get_movie(message: types.Message):
    db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)",
               (message.from_user.id,))
    db.commit()

    channels = await not_subscribed(message.from_user.id)
    if channels:
        await message.answer(
            "Avval quyidagi kanallarga obuna bo'ling:",
            reply_markup=sub_kb(channels)
        )
        return

    code = message.text.strip()
    row = db.execute(
        "SELECT file_id, nom FROM kino WHERE kod = ?",
        (code,)
    ).fetchone()

    if row:
        await message.answer_video(row[0], caption=f"🎬 {row[1]}")
    else:
        await message.answer("❌ Bunday kino kodi topilmadi.")


async def main():
    logging.info("Bot ishga tushdi.")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
