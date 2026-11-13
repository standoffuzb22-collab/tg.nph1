import json
import logging
import os
import sqlite3
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
DB_PATH = BASE_DIR / "shop.db"
PRODUCTS_PATH = BASE_DIR / "products.json"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

NAME, PHONE, ADDRESS = range(3)
MENU = ReplyKeyboardMarkup(
    [["🛍 Katalog", "🧺 Savatcha"], ["📦 Buyurtma berish", "☎️ Aloqa"]],
    resize_keyboard=True,
)


def load_products():
    with PRODUCTS_PATH.open(encoding="utf-8") as file:
        return json.load(file)


PRODUCTS = {str(product["id"]): product for product in load_products()}


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS cart (
                user_id INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, product_id)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def money(amount):
    return f"{amount:,}".replace(",", " ") + " so‘m"


def cart_items(user_id):
    with db() as connection:
        rows = connection.execute(
            "SELECT product_id, quantity FROM cart WHERE user_id = ? AND quantity > 0",
            (user_id,),
        ).fetchall()
    result = []
    for row in rows:
        product = PRODUCTS.get(row["product_id"])
        if product:
            result.append((product, row["quantity"]))
    return result


def cart_total(items):
    return sum(product["price"] * quantity for product, quantity in items)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum! 🌿\n"
        "Eco Sochiqlar do‘koniga xush kelibsiz.\n\n"
        "Tabiiy va kundalik foydalanishga qulay sochiqlarimizni katalogdan ko‘ring.",
        reply_markup=MENU,
    )


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    await message.reply_text("🛍 <b>Mahsulotlar katalogi</b>", parse_mode=ParseMode.HTML)
    for product in PRODUCTS.values():
        caption = (
            f"<b>{escape(product['name'])}</b>\n"
            f"{escape(product['description'])}\n"
            f"Narxi: <b>{money(product['price'])}</b>"
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("➕ Savatchaga qo‘shish", callback_data=f"add:{product['id']}")]]
        )
        await message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = cart_items(user_id)
    if not items:
        await update.effective_message.reply_text("Savatchangiz hozircha bo‘sh. Katalogdan mahsulot tanlang.", reply_markup=MENU)
        return

    lines = ["🧺 <b>Savatchangiz</b>"]
    buttons = []
    for product, quantity in items:
        lines.append(f"• {escape(product['name'])} × {quantity} — {money(product['price'] * quantity)}")
        buttons.append([InlineKeyboardButton(f"➖ {product['name']}", callback_data=f"remove:{product['id']}")])
    total = cart_total(items)
    lines.append(f"\nJami: <b>{money(total)}</b>")
    buttons.append([InlineKeyboardButton("📦 Buyurtma berish", callback_data="checkout")])
    buttons.append([InlineKeyboardButton("🗑 Savatchani bo‘shatish", callback_data="clear")])
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons)
    )


async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":", 1)[1]
    if product_id not in PRODUCTS:
        await query.message.reply_text("Bu mahsulot topilmadi.")
        return
    with db() as connection:
        connection.execute(
            """INSERT INTO cart(user_id, product_id, quantity) VALUES (?, ?, 1)
               ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + 1""",
            (query.from_user.id, product_id),
        )
    product = PRODUCTS[product_id]
    await query.message.reply_text(f"✅ {product['name']} savatchaga qo‘shildi. Savatchani ko‘rish uchun «🧺 Savatcha»ni bosing.")


async def remove_from_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":", 1)[1]
    with db() as connection:
        row = connection.execute(
            "SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?",
            (query.from_user.id, product_id),
        ).fetchone()
        if row:
            if row["quantity"] <= 1:
                connection.execute("DELETE FROM cart WHERE user_id = ? AND product_id = ?", (query.from_user.id, product_id))
            else:
                connection.execute("UPDATE cart SET quantity = quantity - 1 WHERE user_id = ? AND product_id = ?", (query.from_user.id, product_id))
    await query.message.reply_text("Mahsulot miqdori yangilandi.")
    await show_cart(update, context)


async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Savatcha bo‘shatildi")
    with db() as connection:
        connection.execute("DELETE FROM cart WHERE user_id = ?", (query.from_user.id,))
    await query.message.reply_text("Savatchangiz bo‘shatildi.")


async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = cart_items(update.effective_user.id)
    if not items:
        await update.effective_message.reply_text("Buyurtma berishdan oldin savatchaga mahsulot qo‘shing.", reply_markup=MENU)
        return ConversationHandler.END
    context.user_data["checkout_items"] = items
    await update.effective_message.reply_text("Buyurtma uchun ism-familiyangizni yozing:", reply_markup=ReplyKeyboardRemove())
    return NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Iltimos, ism-familiyangizni to‘liqroq kiriting:")
        return NAME
    context.user_data["customer_name"] = name
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)], ["Bekor qilish"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text("Telefon raqamingizni yuboring yoki shu yerga yozing:", reply_markup=keyboard)
    return PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    if len(phone) < 7:
        await update.message.reply_text("Telefon raqami noto‘g‘ri ko‘rinadi. Qayta yuboring:")
        return PHONE
    context.user_data["customer_phone"] = phone
    await update.message.reply_text("Yetkazib berish manzilini (shahar/tuman, ko‘cha, uy) yozing:", reply_markup=ReplyKeyboardRemove())
    return ADDRESS


async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if len(address) < 5:
        await update.message.reply_text("Iltimos, manzilni to‘liqroq yozing:")
        return ADDRESS
    user = update.effective_user
    items = context.user_data.get("checkout_items") or cart_items(user.id)
    if not items:
        await update.message.reply_text("Savatchangiz bo‘shab qolgan. Qaytadan mahsulot tanlang.", reply_markup=MENU)
        context.user_data.clear()
        return ConversationHandler.END

    name = context.user_data["customer_name"]
    phone = context.user_data["customer_phone"]
    total = cart_total(items)
    order_items = [
        {"id": product["id"], "name": product["name"], "price": product["price"], "quantity": quantity}
        for product, quantity in items
    ]
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO orders(user_id, customer_name, phone, address, items_json, total) VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, name, phone, address, json.dumps(order_items, ensure_ascii=False), total),
        )
        order_id = cursor.lastrowid
        connection.execute("DELETE FROM cart WHERE user_id = ?", (user.id,))

    lines = [f"📦 <b>Yangi buyurtma №{order_id}</b>", f"Mijoz: {escape(name)}", f"Telefon: {escape(phone)}", f"Manzil: {escape(address)}", "", "Mahsulotlar:"]
    for product, quantity in items:
        lines.append(f"• {escape(product['name'])} × {quantity} — {money(product['price'] * quantity)}")
    lines.append(f"\nJami: <b>{money(total)}</b>")
    lines.append(f"Telegram: @{escape(user.username)}" if user.username else f"Telegram ID: {user.id}")

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text="\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception("Admin chatga buyurtma yuborilmadi")
            await update.message.reply_text("Buyurtma saqlandi, lekin do‘kon bilan bog‘lanishda muammo bo‘ldi. Iltimos, telefon orqali bog‘laning.")
    await update.message.reply_text(
        f"Rahmat, {escape(name)}! Buyurtmangiz №{order_id} qabul qilindi. Tez orada siz bilan bog‘lanamiz.",
        reply_markup=MENU,
        parse_mode=ParseMode.HTML,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Buyurtma bekor qilindi.", reply_markup=MENU)
    return ConversationHandler.END


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Savollar uchun do‘kon adminiga yozing: @your_shop_username\nBu manzilni bot.py faylida o‘zingiznikiga almashtiring.", reply_markup=MENU)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning Telegram ID raqamingiz: <code>{update.effective_chat.id}</code>", parse_mode=ParseMode.HTML)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Kerakli bo‘limni pastdagi menyudan tanlang.", reply_markup=MENU)


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. .env faylini sozlang.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    checkout = ConversationHandler(
        entry_points=[CommandHandler("order", checkout_start), MessageHandler(filters.Regex(r"^📦 Buyurtma berish$"), checkout_start), CallbackQueryHandler(checkout_start, pattern=r"^checkout$")],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            PHONE: [MessageHandler((filters.CONTACT | filters.TEXT) & ~filters.COMMAND, receive_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_address)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(r"^Bekor qilish$"), cancel)],
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CommandHandler("catalog", show_catalog))
    app.add_handler(CommandHandler("cart", show_cart))
    app.add_handler(checkout)
    app.add_handler(MessageHandler(filters.Regex(r"^🛍 Katalog$"), show_catalog))
    app.add_handler(MessageHandler(filters.Regex(r"^🧺 Savatcha$"), show_cart))
    app.add_handler(MessageHandler(filters.Regex(r"^☎️ Aloqa$"), contact))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern=r"^add:"))
    app.add_handler(CallbackQueryHandler(remove_from_cart, pattern=r"^remove:"))
    app.add_handler(CallbackQueryHandler(clear_cart, pattern=r"^clear$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
