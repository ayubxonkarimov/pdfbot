from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from datetime import datetime, timedelta
import fitz  # PyMuPDF
import io
import os
import asyncio

# === Faylga yozish/oqish funksiyalari ===
def load_admins(filename="admins.txt"):
    try:
        with open(filename, "r") as f:
            return [int(line.strip()) for line in f if line.strip()]
    except FileNotFoundError:
        return []

def save_admin(admin_id, filename="admins.txt"):
    with open(filename, "a") as f:
        f.write(str(admin_id) + "\n")

def remove_admin(admin_id, filename="admins.txt"):
    try:
        with open(filename, "r") as f:
            admins = [line.strip() for line in f]
        admins = [a for a in admins if a != str(admin_id)]
        with open(filename, "w") as f:
            f.write("\n".join(admins) + "\n")
    except FileNotFoundError:
        pass

def load_subscriptions(filename="subscriptions.txt"):
    try:
        with open(filename, "r") as f:
            return {
                int(line.split(",")[0]): datetime.strptime(line.split(",")[1].strip(), "%Y-%m-%d")
                for line in f if line.strip()
            }
    except FileNotFoundError:
        return {}

def save_subscription(user_id, end_date, filename="subscriptions.txt"):
    subs = load_subscriptions(filename)
    subs[user_id] = end_date
    with open(filename, "w") as f:
        for uid, date in subs.items():
            f.write(f"{uid},{date.date()}\n")

def is_subscription_valid(user_id):
    subs = load_subscriptions()
    end_date = subs.get(user_id)
    return end_date and end_date >= datetime.now()

# === Global ===
ADMINS = load_admins()
SUPER_ADMIN_ID = 1483283523

# === PDF raqam qo'shish funksiyasi ===
def add_page_numbers_to_pdf(input_bytes: bytes) -> bytes:
    reader = PdfReader(io.BytesIO(input_bytes))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=(width, height))
        can.setFont("Helvetica-Bold", 20)
        can.drawString(110, height - 100, str(i))
        can.save()
        packet.seek(0)
        overlay_pdf = PdfReader(packet)
        page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output

# === Telegram komandalar ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if (user_id in ADMINS or is_subscription_valid(user_id)):
        await update.message.reply_text("PDF faylni yuboring – sahifalarga raqam qo‘shib qaytaraman.")
    else:
        await update.message.reply_text("⛔ Sizda ruxsat yo‘q yoki obuna muddati tugagan.")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS and not is_subscription_valid(user_id):
        return
    document = update.message.document
    if document.mime_type != 'application/pdf':
        await update.message.reply_text("Iltimos, faqat PDF fayl yuboring.")
        return
    file = await document.get_file()
    file_bytes = await file.download_as_bytearray()
    result_pdf = add_page_numbers_to_pdf(file_bytes)
    await update.message.reply_document(document=InputFile(result_pdf, filename="raqamlangan.pdf"))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("Faqat bosh admin yangi admin qo‘sha oladi.")
        return
    if not context.args:
        await update.message.reply_text("Foydalanuvchi ID ni yozing: /addadmin 123456789")
        return
    try:
        new_admin = int(context.args[0])
        if new_admin in ADMINS:
            await update.message.reply_text("Bu foydalanuvchi allaqachon admin.")
        else:
            ADMINS.append(new_admin)
            save_admin(new_admin)
            await update.message.reply_text(f"✅ Yangi admin qo‘shildi: {new_admin}")
    except ValueError:
        await update.message.reply_text("ID faqat raqamlardan iborat bo‘lishi kerak.")

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("Faqat bosh admin adminni o‘chira oladi.")
        return
    if not context.args:
        await update.message.reply_text("Admin ID ni yozing: /removeadmin 123456789")
        return
    try:
        admin_id = int(context.args[0])
        if admin_id not in ADMINS:
            await update.message.reply_text("Bu foydalanuvchi admin emas.")
        else:
            ADMINS.remove(admin_id)
            remove_admin(admin_id)
            await update.message.reply_text(f"❌ Admin o‘chirildi: {admin_id}")
    except ValueError:
        await update.message.reply_text("ID noto‘g‘ri formatda.")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("Faqat bosh admin obuna bera oladi.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Foydalanuvchi ID va tugash sanasini kiriting: /subscribe 123456789 2025-08-15")
        return
    try:
        user_id = int(context.args[0])
        end_date = datetime.strptime(context.args[1], "%Y-%m-%d")
        save_subscription(user_id, end_date)
        await update.message.reply_text(f"✅ Obuna berildi: {user_id} (gacha: {end_date.date()})")
        await context.bot.send_message(chat_id=user_id, text=f"✅ Sizga obuna berildi. Tugash sanasi: {end_date.date()}")
    except ValueError:
        await update.message.reply_text("ID yoki sana noto‘g‘ri formatda. Sana: YYYY-MM-DD")

# === 1 kun qolganda ogohlantirish ===
async def notify_expiring_subscriptions(app):
    subs = load_subscriptions()
    today = datetime.now().date()
    for user_id, end_date in subs.items():
        if (end_date.date() - today).days == 1:
            try:
                await app.bot.send_message(chat_id=user_id, text="⚠️ Obunangizga 1 kun qoldi. Iltimos, admin bilan bog‘laning.")
            except:
                pass

# === Botni ishga tushirish ===
def main():
    app = ApplicationBuilder().token("7839498388:AAF6b5dI1mJYxP43P0niDYRYkfLUgBslD6E").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))

    async def daily_check():
        while True:
            await notify_expiring_subscriptions(app)
            await asyncio.sleep(86400)

    import threading
    threading.Thread(target=lambda: asyncio.run(daily_check()), daemon=True).start()

    app.run_polling()

if __name__ == "__main__":
    main()