import logging
import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL")


# ─── دیتابیس ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    key TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    file_id TEXT,
                    type TEXT DEFAULT 'pdf',
                    clicks INTEGER DEFAULT 0
                )
            """)
        conn.commit()

def load_books() -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM books ORDER BY key")
            rows = cur.fetchall()
    return {row['key']: dict(row) for row in rows}

def save_book(key: str, book: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO books (key, title, description, file_id, type, clicks)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    title=EXCLUDED.title,
                    description=EXCLUDED.description,
                    file_id=EXCLUDED.file_id,
                    type=EXCLUDED.type,
                    clicks=EXCLUDED.clicks
            """, (key, book.get('title'), book.get('description'),
                  book.get('file_id'), book.get('type', 'pdf'), book.get('clicks', 0)))
        conn.commit()

def increment_clicks(key: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE books SET clicks = clicks + 1 WHERE key = %s", (key,))
        conn.commit()

def delete_book(key: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM books WHERE key = %s", (key,))
        conn.commit()

def next_key() -> str:
    books = load_books()
    n = len(books) + 1
    key = f"file_{n:04d}"
    while key in books:
        n += 1
        key = f"file_{n:04d}"
    return key


# ─── دستورات ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if args:
        book_key = args[0]
        books = load_books()
        if book_key in books:
            book = books[book_key]
            increment_clicks(book_key)
            file_type = book.get("type", "pdf")
            await update.message.reply_text(
                f"📚 *{book['title']}*\n\n"
                f"_{book.get('description', 'در حال ارسال...')}_",
                parse_mode="Markdown"
            )
            if file_type == "video":
                await update.message.reply_video(
                    video=book["file_id"],
                    caption=f"🎬 {book['title']}\n\n🔗 کانال ما را دنبال کنید!",
                )
            else:
                await update.message.reply_document(
                    document=book["file_id"],
                    caption=f"📖 {book['title']}\n\n🔗 کانال ما را دنبال کنید!",
                )
            return
        else:
            await update.message.reply_text("❌ این فایل پیدا نشد یا حذف شده.")
            return

    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 سلام ادمین!\n\n"
            "📤 PDF یا ویدیو بفرست تا اضافه بشه\n"
            "📋 /list — لیست فایل‌ها\n"
            "🗑 /delete — حذف فایل"
        )
    else:
        await update.message.reply_text(
            "👋 سلام!\n"
            "لینک فایل مورد نظر رو از کانال بزن تا برات ارسال بشه. 📚"
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط ادمین می‌تونه فایل اضافه کنه.")
        return

    doc = update.message.document
    allowed = (".pdf", ".mp4", ".mkv", ".mov", ".avi")
    if not doc.file_name.lower().endswith(allowed):
        await update.message.reply_text("⚠️ فقط PDF یا ویدیو قبول می‌شه.")
        return

    is_video = doc.file_name.lower().endswith((".mp4", ".mkv", ".mov", ".avi"))
    context.user_data["pending_file_id"] = doc.file_id
    context.user_data["pending_type"] = "video" if is_video else "pdf"
    context.user_data["state"] = "waiting_title"

    file_label = "ویدیو" if is_video else "PDF"
    await update.message.reply_text(f"✅ {file_label} دریافت شد!\n\n📝 عنوان رو بنویس:")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    video = update.message.video
    context.user_data["pending_file_id"] = video.file_id
    context.user_data["pending_type"] = "video"
    context.user_data["state"] = "waiting_title"
    await update.message.reply_text("✅ ویدیو دریافت شد!\n\n📝 عنوان رو بنویس:")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    state = context.user_data.get("state")
    if state == "waiting_title":
        context.user_data["pending_title"] = update.message.text
        context.user_data["state"] = "waiting_description"
        await update.message.reply_text("📄 توضیح کوتاه بنویس (یا /skip بزن):")
    elif state == "waiting_description":
        await _save_file(update, context, update.message.text)


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") == "waiting_description":
        await _save_file(update, context, "")


async def _save_file(update, context, description):
    file_id = context.user_data.get("pending_file_id")
    title = context.user_data.get("pending_title", "بدون عنوان")
    file_type = context.user_data.get("pending_type", "pdf")

    if not file_id:
        await update.message.reply_text("❌ خطا! دوباره فایل رو بفرست.")
        return

    key = next_key()
    save_book(key, {
        "title": title,
        "description": description,
        "file_id": file_id,
        "type": file_type,
        "clicks": 0,
    })

    bot_username = context.bot.username
    deep_link = f"https://t.me/{bot_username}?start={key}"
    emoji = "🎬" if file_type == "video" else "📖"
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ ذخیره شد!\n\n"
        f"{emoji} *{title}*\n"
        f"🔑 کلید: `{key}`\n\n"
        f"🔗 لینک برای کانال:\n`{deep_link}`",
        parse_mode="Markdown"
    )


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    if not books:
        await update.message.reply_text("📭 هنوز فایلی اضافه نشده.")
        return

    try:
        bot_username = context.bot.username
        text = "📋 *لیست فایل‌ها:*\n\n"
        for key, book in books.items():
            link = f"https://t.me/{bot_username}?start={key}"
            emoji = "🎬" if book.get("type") == "video" else "📖"
            clicks = book.get("clicks", 0)
            text += f"{emoji} `{key}` — *{book['title']}*\n👆 {clicks} کلیک\n🔗 {link}\n\n"

        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    if not books:
        await update.message.reply_text("📭 فایلی برای حذف وجود نداره.")
        return

    keyboard = []
    for key, book in books.items():
        emoji = "🎬" if book.get("type") == "video" else "📖"
        clicks = book.get("clicks", 0)
        keyboard.append([InlineKeyboardButton(
            f"🗑 {emoji} {book['title']} ({clicks} کلیک)",
            callback_data=f"delete_{key}"
        )])
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel")])

    await update.message.reply_text(
        "کدوم فایل رو می‌خوای حذف کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return

    if query.data.startswith("delete_"):
        key = query.data.replace("delete_", "")
        books = load_books()
        if key in books:
            title = books[key]["title"]
            delete_book(key)
            await query.edit_message_text(f"✅ «{title}» حذف شد.")
        else:
            await query.edit_message_text("❌ فایل پیدا نشد.")


# ─── اجرا ────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
