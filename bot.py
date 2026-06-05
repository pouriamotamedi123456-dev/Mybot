import logging
import json
import os
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # آیدی عددی خودتون
DATA_FILE = "books.json"


# ─── ذخیره‌سازی کتاب‌ها ───────────────────────────────────────────────────────

def load_books() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_books(books: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)


# ─── دستورات ادمین ────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args  # پارامتر بعد از /start

    # اگه کاربر از طریق دیپ‌لینک اومده
    if args:
        book_key = args[0]
        books = load_books()
        if book_key in books:
            book = books[book_key]
            await update.message.reply_text(
                f"📚 *{book['title']}*\n\n"
                f"_{book.get('description', 'در حال ارسال کتاب...')}_",
                parse_mode="Markdown"
            )
            await update.message.reply_document(
                document=book["file_id"],
                caption=f"📖 {book['title']}\n\n"
                        f"🔗 کانال ما را دنبال کنید!",
            )
            return
        else:
            await update.message.reply_text("❌ این کتاب پیدا نشد یا حذف شده.")
            return

    # پیام خوش‌آمد برای کاربر عادی
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 سلام ادمین!\n\n"
            "📤 برای اضافه کردن کتاب جدید، PDF رو برام بفرست.\n"
            "📋 /list — لیست کتاب‌ها\n"
            "🗑 /delete — حذف کتاب"
        )
    else:
        await update.message.reply_text(
            "👋 سلام!\n"
            "این ربات برای دریافت کتاب‌های کانال ماست.\n"
            "لینک کتاب مورد نظر رو از کانال بزن تا کتاب بهت ارسال بشه. 📚"
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ فقط ادمین می‌تونه کتاب اضافه کنه.")
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("⚠️ فقط فایل PDF قبول می‌شه.")
        return

    # ذخیره موقت file_id و انتظار برای عنوان
    context.user_data["pending_file_id"] = doc.file_id
    context.user_data["pending_file_name"] = doc.file_name
    context.user_data["state"] = "waiting_title"

    await update.message.reply_text(
        "✅ PDF دریافت شد!\n\n"
        "📝 حالا عنوان کتاب رو بنویس:"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        return

    state = context.user_data.get("state")

    if state == "waiting_title":
        context.user_data["pending_title"] = update.message.text
        context.user_data["state"] = "waiting_description"
        await update.message.reply_text(
            "📄 توضیح کوتاه کتاب رو بنویس (یا /skip بزن):"
        )

    elif state == "waiting_description":
        description = update.message.text
        await _save_book(update, context, description)

    elif state == "waiting_delete_key":
        await _confirm_delete(update, context, update.message.text.strip())


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get("state") == "waiting_description":
        await _save_book(update, context, "")


async def _save_book(update, context, description):
    file_id = context.user_data.get("pending_file_id")
    title = context.user_data.get("pending_title", "بدون عنوان")

    if not file_id:
        await update.message.reply_text("❌ خطا! دوباره PDF رو بفرست.")
        return

    # ساخت کلید یکتا
    books = load_books()
    key = f"book_{len(books) + 1:04d}"
    while key in books:
        key = f"book_{int(key.split('_')[1]) + 1:04d}"

    books[key] = {
        "title": title,
        "description": description,
        "file_id": file_id,
    }
    save_books(books)

    bot_username = (await update.get_bot().get_me()).username
    deep_link = f"https://t.me/{bot_username}?start={key}"

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ کتاب ذخیره شد!\n\n"
        f"📚 *{title}*\n"
        f"🔑 کلید: `{key}`\n\n"
        f"🔗 لینک برای کانال:\n`{deep_link}`\n\n"
        f"این لینک رو تو کانالت بذار 👆",
        parse_mode="Markdown"
    )


async def list_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    if not books:
        await update.message.reply_text("📭 هنوز کتابی اضافه نشده.")
        return

    bot_username = (await update.get_bot().get_me()).username
    text = "📚 *لیست کتاب‌ها:*\n\n"
    for key, book in books.items():
        link = f"https://t.me/{bot_username}?start={key}"
        text += f"🔑 `{key}` — *{book['title']}*\n🔗 {link}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    if not books:
        await update.message.reply_text("📭 کتابی برای حذف وجود نداره.")
        return

    keyboard = []
    for key, book in books.items():
        keyboard.append([InlineKeyboardButton(
            f"🗑 {book['title']} ({key})",
            callback_data=f"delete_{key}"
        )])
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel")])

    await update.message.reply_text(
        "کدوم کتاب رو می‌خوای حذف کنی؟",
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
            del books[key]
            save_books(books)
            await query.edit_message_text(f"✅ کتاب «{title}» حذف شد.")
        else:
            await query.edit_message_text("❌ کتاب پیدا نشد.")


# ─── اجرا ────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_books))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
