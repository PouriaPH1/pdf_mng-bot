# bot.py
import os
import shutil
import asyncio
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename

import config
from utils import (
    generate_pdf_thumbnail,
    optimize_custom_thumbnail,
    apply_watermark_to_pdf,
    remove_watermark_clean
)
from FastTelethon import upload_file as fast_upload_file, download_file as fast_download_file


async def download_pdf_fast(client_instance, message, target_path: str):
    """دانلود موازی و بسیار سریع با FastTelethon با پشتیبانی از فال‌بک امن"""
    try:
        with open(target_path, "wb") as out:
            await fast_download_file(client_instance, message.document, out)
    except Exception as e:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass
        await message.download_media(target_path)


async def upload_pdf_fast(client_instance, file_path: str):
    """آپلود موازی چندبخشی و فوق‌سریع با FastTelethon"""
    try:
        with open(file_path, "rb") as f:
            return await fast_upload_file(client_instance, f)
    except Exception as e:
        return file_path


# ساخت پوشه فایل‌های موقت
os.makedirs(config.TEMP_DIR, exist_ok=True)

client = TelegramClient("pdf_bot_session", config.API_ID, config.API_HASH)

# مسیرهای فایل‌های تنظیمات شخصی
CUSTOM_THUMB_PATH = os.path.join(config.TEMP_DIR, "custom_thumb.jpg")
WATERMARK_LOGO_PATH = os.path.join(config.TEMP_DIR, "watermark_logo.png")

# وضعیت سراسری ربات شخصی
state = {
    # ۱. تنظیمات تامبنیل
    "thumb_mode": "auto",       # "auto" یا "custom"
    "has_custom_thumb": os.path.exists(CUSTOM_THUMB_PATH),
    
    # ۲. تنظیمات درج واترمارک (افزودن لوگو)
    "watermark_enabled": False,
    "watermark_pos": "bottom-right",  # "bottom-right", "bottom-left", "top-right", "top-left", "random"
    "watermark_pages": "all",         # "all", "first", "random"
    "has_watermark_logo": os.path.exists(WATERMARK_LOGO_PATH),

    # ۳. تنظیمات حذف اصولی واترمارک‌های قبلی
    "remove_wm_enabled": False,       # حذف لوگوها و واترمارک‌های تکراری موجود در فایل
    "remove_wm_text": None,           # متن یا آیدی خاص برای حذف از صفحات (مثل @channel)

    # ۴. تنظیمات تغییر نام فایل‌های PDF
    "rename_mode": "original",        # "original", "custom", "prefix", "suffix", "remove"
    "rename_value": None,            # مقدار متنی (مثلاً نام جدید، پیشوند، پسوند، یا عبارت حذفی)

    # وضعیت موقت ثبت مدیا و ورودی‌ها
    "waiting_for": None               # "custom_thumb", "watermark_logo", "remove_text", "rename_value"
}

RENAME_LABELS = {
    "original": "حفظ نام اصلی ➖",
    "custom": "نام دلخواه ✍️",
    "prefix": "افزودن پیشوند ◀️",
    "suffix": "افزودن پسوند ▶️",
    "remove": "حذف عبارت از نام ✂️"
}

POS_LABELS = {
    "bottom-right": "گوشه پایین-راست ↘️",
    "bottom-left": "گوشه پایین-چپ ↙️",
    "top-right": "گوشه بالا-راست ↗️",
    "top-left": "گوشه بالا-چپ ↖️",
    "random": "🎲 گوشه تصادفی (بدون متن)"
}

PAGE_LABELS = {
    "all": "تمام صفحات 📄",
    "first": "فقط صفحه اول 1️⃣",
    "random": "🎲 صفحات رندوم"
}


# ==================== کیبوردها (Keyboards) ====================

# دکمه‌های ثابت در پایین صفحه (Reply Markup)
MAIN_REPLY_KEYBOARD = [
    [Button.text("🖼 تنظیمات تامبنیل", resize=True), Button.text("🏷 درج واترمارک", resize=True)],
    [Button.text("🧹 حذف واترمارک قبلی", resize=True), Button.text("✏️ تغییر نام فایل", resize=True)],
    [Button.text("⚡ وضعیت کلی و راهنما", resize=True), Button.text("🗑 پاکسازی فایل‌های موقت", resize=True)]
]

# تابع محاسبه و تولید نام جدید فایل
def calculate_target_filename(original_file_name: str) -> str:
    raw_name = original_file_name or "document.pdf"
    base, ext = os.path.splitext(raw_name)
    if not ext:
        ext = ".pdf"

    mode = state.get("rename_mode", "original")
    val = state.get("rename_value")

    if not val or mode == "original":
        return f"{base}{ext}"

    if mode == "custom":
        clean_val = val[:-4] if val.lower().endswith(".pdf") else val
        return f"{clean_val}{ext}"
    elif mode == "prefix":
        return f"{val}{base}{ext}"
    elif mode == "suffix":
        return f"{base}{val}{ext}"
    elif mode == "remove":
        cleaned_base = base.replace(val, "").strip()
        if not cleaned_base:
            cleaned_base = "document"
        return f"{cleaned_base}{ext}"

    return f"{base}{ext}"

# ۱. دکمه‌های شیشه‌ای تنظیمات تامبنیل
def get_thumb_inline_keyboard():
    mode_text = "🟢 خودکار (صفحه اول PDF)" if state["thumb_mode"] == "auto" else "🔵 عکس دلخواه"
    buttons = [
        [Button.inline(f"⚙️ حالت تامبنیل: {mode_text}", b"toggle_thumb_mode")],
        [Button.inline("📤 ارسال عکس تامبنیل جدید", b"req_custom_thumb")]
    ]
    sub_row = []
    if state["has_custom_thumb"]:
        sub_row.append(Button.inline("👁 مشاهده عکس", b"view_thumb"))
        sub_row.append(Button.inline("❌ حذف عکس", b"clear_thumb"))
    if sub_row:
        buttons.append(sub_row)
    return buttons

# ۲. دکمه‌های شیشه‌ای درج واترمارک
def get_watermark_inline_keyboard():
    wm_status = "فعال ✅" if state["watermark_enabled"] else "غیرفعال ❌"
    pos_text = POS_LABELS.get(state["watermark_pos"], state["watermark_pos"])
    page_text = PAGE_LABELS.get(state["watermark_pages"], state["watermark_pages"])
    
    buttons = [
        [Button.inline(f"🏷 درج لوگو: {wm_status}", b"toggle_wm_enable")],
        [Button.inline(f"📍 موقعیت: {pos_text}", b"cycle_wm_pos")],
        [Button.inline(f"📑 صفحات: {page_text}", b"cycle_wm_pages")],
        [Button.inline("📤 ارسال فایل لوگو جدید", b"req_wm_logo")]
    ]
    sub_row = []
    if state["has_watermark_logo"]:
        sub_row.append(Button.inline("👁 مشاهده لوگو", b"view_logo"))
        sub_row.append(Button.inline("❌ حذف لوگو", b"clear_logo"))
    if sub_row:
        buttons.append(sub_row)
    return buttons

# ۳. دکمه‌های شیشه‌ای حذف واترمارک
def get_remove_wm_inline_keyboard():
    rm_status = "فعال ✅" if state["remove_wm_enabled"] else "غیرفعال ❌"
    text_val = state["remove_wm_text"] or "تعیین نشده ➖"
    
    buttons = [
        [Button.inline(f"🧹 حذف لوگوهای تکراری: {rm_status}", b"toggle_remove_wm")],
        [Button.inline(f"✍️ متن/آیدی حذفی: {text_val}", b"req_remove_text")]
    ]
    if state["remove_wm_text"]:
        buttons.append([Button.inline("❌ پاک کردن متن حذفی", b"clear_remove_text")])
    return buttons

# ۴. دکمه‌های شیشه‌ای تغییر نام فایل
def get_rename_inline_keyboard():
    mode_text = RENAME_LABELS.get(state["rename_mode"], "حفظ نام اصلی")
    val_text = state["rename_value"] or "تعیین نشده ➖"

    buttons = [
        [Button.inline(f"⚙️ حالت تغییر نام: {mode_text}", b"cycle_rename_mode")],
    ]
    if state["rename_mode"] != "original":
        buttons.append([Button.inline(f"📝 مقدار/عبارت: {val_text}", b"req_rename_val")])
        buttons.append([Button.inline("🔄 بازگشت به نام اصلی", b"reset_rename")])
    return buttons


# ==================== هندلر دستور /start ====================

@client.on(events.NewMessage(pattern=r"^/start"))
async def start_handler(event):
    state["waiting_for"] = None
    welcome_text = (
        "👋 **به ربات حرفه‌ای و چندمنظوره PDF خوش آمدید.**\n\n"
        "🛠 **امکانات کلیدی:**\n"
        "1️⃣ **تنظیم تامبنیل (کاور):** خودکار از صفحه اول یا تصویر دلخواه (تکی و گروهی).\n"
        "2️⃣ **درج لوگو / واترمارک:** در گوشه‌ها و حاشیه‌های امن (با تضمین عدم تداخل با متن).\n"
        "3️⃣ **حذف اصولی واترمارک:** پاکسازی لوگوهای تکراری و متن‌های مزاحم (آیدی، نام سایت و...) بدون افت کیفیت.\n"
        "4️⃣ **تغییر نام فایل:** تنظیم نام دلخواه، افزودن پیشوند/پسوند (مثل آیدی کانال) یا پاکسازی نام فایل.\n\n"
        "👇 از دکمه‌های زیر جهت تنظیم هر بخش استفاده کنید:"
    )
    await event.respond(welcome_text, buttons=MAIN_REPLY_KEYBOARD)
    await event.respond("🎛 **تنظیمات تامبنیل:**", buttons=get_thumb_inline_keyboard())


# ==================== پردازش دکمه‌های ثابت پایین ====================

@client.on(events.NewMessage(func=lambda e: e.is_private and e.text in [
    "🖼 تنظیمات تامبنیل", "🏷 درج واترمارک", "🧹 حذف واترمارک قبلی", "✏️ تغییر نام فایل", "⚡ وضعیت کلی و راهنما", "🗑 پاکسازی فایل‌های موقت"
]))
async def reply_markup_handler(event):
    state["waiting_for"] = None
    text = event.text.strip()

    if text == "🖼 تنظیمات تامبنیل":
        await event.respond("🖼 **تنظیمات کاور / تامبنیل PDF:**", buttons=get_thumb_inline_keyboard())

    elif text == "🏷 درج واترمارک":
        await event.respond("🏷 **تنظیمات درج لوگو روی PDF:**", buttons=get_watermark_inline_keyboard())

    elif text == "🧹 حذف واترمارک قبلی":
        await event.respond(
            "🧹 **تنظیمات حذف تمیز و اصولی واترمارک:**\n\n"
            "• **حذف لوگوهای تکراری:** واترمارک‌ها و لوگوهایی که در گوشه‌ها و صفحات تکرار شده‌اند را به صورت کاملاً لایه‌ای و تمیز حذف می‌کند.\n"
            "• **حذف متن/آیدی:** اگر در فایل آیدی کانال یا لینکی درج شده باشد، دقیقاً همان متن را از کل صفحات برمی‌دارد.",
            buttons=get_remove_wm_inline_keyboard()
        )

    elif text == "✏️ تغییر نام فایل":
        await event.respond(
            "✏️ **تنظیمات تغییر نام فایل‌های PDF:**\n\n"
            "• **نام دلخواه:** قرار دادن یک نام ثابت روی فایل‌های ارسالی.\n"
            "• **افزودن پیشوند / پسوند:** درج خودکار آیدی کانال یا متن در اول یا آخر نام فایل‌ها.\n"
            "• **حذف عبارت:** پاکسازی خودکار آیدی یا کلمات تبلیغاتی از نام اصلی فایل.",
            buttons=get_rename_inline_keyboard()
        )

    elif text == "⚡ وضعیت کلی و راهنما":
        thumb_mode_fa = "🟢 خودکار (صفحه اول)" if state["thumb_mode"] == "auto" else "🔵 عکس دلخواه"
        wm_status_fa = "روشن ✅" if state["watermark_enabled"] else "خاموش ❌"
        rm_status_fa = "روشن ✅" if state["remove_wm_enabled"] else "خاموش ❌"
        pos_fa = POS_LABELS.get(state["watermark_pos"], state["watermark_pos"])
        rename_fa = RENAME_LABELS.get(state["rename_mode"], "حفظ نام اصلی")
        rename_val_fa = f" (`{state['rename_value']}`)" if state["rename_value"] and state["rename_mode"] != "original" else ""
        
        info_text = (
            "⚙️ **وضعیت فعلی بخش‌های ربات:**\n\n"
            f"1️⃣ **تامبنیل:** {thumb_mode_fa}\n"
            f"2️⃣ **درج لوگو:** {wm_status_fa} (موقعیت: {pos_fa})\n"
            f"3️⃣ **حذف واترمارک قبلی:** {rm_status_fa}\n"
            f"   • متن حذفی: `{state['remove_wm_text'] or 'ندارد'}`\n"
            f"4️⃣ **تغییر نام فایل:** {rename_fa}{rename_val_fa}\n\n"
            "📥 **ارسال فایل:** هر تعداد فایل PDF بفرستید، طبق این تنظیمات پردازش و بازگردانده می‌شوند."
        )
        await event.respond(info_text)

    elif text == "🗑 پاکسازی فایل‌های موقت":
        deleted = 0
        for f in os.listdir(config.TEMP_DIR):
            if f not in ["custom_thumb.jpg", "watermark_logo.png"]:
                f_path = os.path.join(config.TEMP_DIR, f)
                if os.path.isfile(f_path):
                    try:
                        os.remove(f_path)
                        deleted += 1
                    except Exception:
                        pass
        await event.respond(f"🧹 کش موقت پاک شد! (`{deleted}` فایل پاکسازی شدند)")


# ==================== پردازش دکمه‌های شیشه‌ای ====================

@client.on(events.CallbackQuery)
async def inline_callback_handler(event):
    data = event.data.decode("utf-8")

    # --- تامبنیل ---
    if data == "toggle_thumb_mode":
        if state["thumb_mode"] == "auto":
            if not state["has_custom_thumb"]:
                await event.answer("⚠️ ابتدا عکس تامبنیل را ارسال کنید.", alert=True)
                return
            state["thumb_mode"] = "custom"
        else:
            state["thumb_mode"] = "auto"
        await event.edit(buttons=get_thumb_inline_keyboard())
        await event.answer(f"حالت به {'خودکار' if state['thumb_mode'] == 'auto' else 'عکس دلخواه'} تغییر کرد.")

    elif data == "req_custom_thumb":
        state["waiting_for"] = "custom_thumb"
        await event.respond("📷 لطفاً اکنون عکس مورد نظرتان برای **تامبنیل** را بفرستید:")
        await event.answer()

    elif data == "clear_thumb":
        if os.path.exists(CUSTOM_THUMB_PATH):
            os.remove(CUSTOM_THUMB_PATH)
        state["has_custom_thumb"] = False
        state["thumb_mode"] = "auto"
        await event.edit(buttons=get_thumb_inline_keyboard())
        await event.answer("عکس تامبنیل حذف شد.")

    elif data == "view_thumb":
        if state["has_custom_thumb"] and os.path.exists(CUSTOM_THUMB_PATH):
            await client.send_file(event.chat_id, CUSTOM_THUMB_PATH, caption="🖼 عکس تامبنیل فعلی")
            await event.answer()
        else:
            await event.answer("عکسی تنظیم نشده است!", alert=True)

    # --- درج واترمارک ---
    elif data == "toggle_wm_enable":
        if not state["watermark_enabled"]:
            if not state["has_watermark_logo"]:
                await event.answer("⚠️ ابتدا فایل لوگوی واترمارک را ارسال کنید.", alert=True)
                return
            state["watermark_enabled"] = True
        else:
            state["watermark_enabled"] = False
        await event.edit(buttons=get_watermark_inline_keyboard())
        await event.answer(f"درج واترمارک {'فعال شد ✅' if state['watermark_enabled'] else 'غیرفعال شد ❌'}")

    elif data == "cycle_wm_pos":
        positions = ["bottom-right", "bottom-left", "top-right", "top-left", "random"]
        curr_idx = positions.index(state["watermark_pos"]) if state["watermark_pos"] in positions else 0
        state["watermark_pos"] = positions[(curr_idx + 1) % len(positions)]
        await event.edit(buttons=get_watermark_inline_keyboard())
        await event.answer(f"موقعیت: {POS_LABELS.get(state['watermark_pos'])}")

    elif data == "cycle_wm_pages":
        pages_options = ["all", "first", "random"]
        curr_idx = pages_options.index(state["watermark_pages"]) if state["watermark_pages"] in pages_options else 0
        state["watermark_pages"] = pages_options[(curr_idx + 1) % len(pages_options)]
        await event.edit(buttons=get_watermark_inline_keyboard())
        await event.answer(f"صفحات: {PAGE_LABELS.get(state['watermark_pages'])}")

    elif data == "req_wm_logo":
        state["waiting_for"] = "watermark_logo"
        await event.respond("🎨 لطفاً اکنون فایل عکس یا PNG لوگوی خود را جهت **واترمارک** بفرستید:")
        await event.answer()

    elif data == "clear_logo":
        if os.path.exists(WATERMARK_LOGO_PATH):
            os.remove(WATERMARK_LOGO_PATH)
        state["has_watermark_logo"] = False
        state["watermark_enabled"] = False
        await event.edit(buttons=get_watermark_inline_keyboard())
        await event.answer("لوگوی واترمارک حذف شد.")

    elif data == "view_logo":
        if state["has_watermark_logo"] and os.path.exists(WATERMARK_LOGO_PATH):
            await client.send_file(event.chat_id, WATERMARK_LOGO_PATH, caption="🎨 لوگوی واترمارک فعلی")
            await event.answer()
        else:
            await event.answer("لوگویی ذخیره نشده است!", alert=True)

    # --- حذف واترمارک ---
    elif data == "toggle_remove_wm":
        state["remove_wm_enabled"] = not state["remove_wm_enabled"]
        await event.edit(buttons=get_remove_wm_inline_keyboard())
        await event.answer(f"حذف هوشمند واترمارک {'فعال شد ✅' if state['remove_wm_enabled'] else 'غیرفعال شد ❌'}")

    elif data == "req_remove_text":
        state["waiting_for"] = "remove_text"
        await event.respond("✍️ لطفاً متن یا آیدی کانالی که می‌خواهید از صفحات PDF حذف شود را بنویسید (مثلاً: `@channel_name`):")
        await event.answer()

    elif data == "clear_remove_text":
        state["remove_wm_text"] = None
        await event.edit(buttons=get_remove_wm_inline_keyboard())
        await event.answer("متن حذفی پاک شد.")

    # --- تغییر نام فایل ---
    elif data == "cycle_rename_mode":
        modes = ["original", "custom", "prefix", "suffix", "remove"]
        curr_idx = modes.index(state["rename_mode"]) if state["rename_mode"] in modes else 0
        state["rename_mode"] = modes[(curr_idx + 1) % len(modes)]

        if state["rename_mode"] != "original" and not state["rename_value"]:
            state["waiting_for"] = "rename_value"
            await event.edit(buttons=get_rename_inline_keyboard())
            mode_desc = RENAME_LABELS.get(state["rename_mode"])
            await event.respond(f"✍️ لطفاً مقدار مورد نظر برای **{mode_desc}** را بفرستید (مثلاً: `@MyChannel`):")
            return

        await event.edit(buttons=get_rename_inline_keyboard())
        await event.answer(f"حالت: {RENAME_LABELS.get(state['rename_mode'])}")

    elif data == "req_rename_val":
        state["waiting_for"] = "rename_value"
        mode_desc = RENAME_LABELS.get(state["rename_mode"])
        await event.respond(f"✍️ لطفاً مقدار جدید برای **{mode_desc}** را بفرستید:")
        await event.answer()

    elif data == "reset_rename":
        state["rename_mode"] = "original"
        state["rename_value"] = None
        await event.edit(buttons=get_rename_inline_keyboard())
        await event.answer("تنظیمات تغییر نام ریست شد و نام اصلی حفظ می‌شود.")


# ==================== دریافت متن، عکس و PDF ====================

@client.on(events.NewMessage)
async def incoming_messages_handler(event):
    if event.raw_text.startswith("/") or event.text in [
        "🖼 تنظیمات تامبنیل", "🏷 درج واترمارک", "🧹 حذف واترمارک قبلی", "✏️ تغییر نام فایل", "⚡ وضعیت کلی و راهنما", "🗑 پاکسازی فایل‌های موقت"
    ]:
        return

    # ۱. اگر در انتظار دریافت متن حذفی باشیم
    if state["waiting_for"] == "remove_text" and event.raw_text:
        state["remove_wm_text"] = event.raw_text.strip()
        state["remove_wm_enabled"] = True
        state["waiting_for"] = None
        await event.reply(
            f"✅ متن حذفی ذخیره شد: `{state['remove_wm_text']}`\n"
            "قابلیت حذف واترمارک فعال شد. از این پس این متن از تمام صفحات PDFهای ارسالی حذف می‌شود.",
            buttons=get_remove_wm_inline_keyboard()
        )
        return

    # ۲. اگر در انتظار دریافت مقدار تغییر نام فایل باشیم
    if state["waiting_for"] == "rename_value" and event.raw_text:
        state["rename_value"] = event.raw_text.strip()
        state["waiting_for"] = None
        mode_desc = RENAME_LABELS.get(state["rename_mode"])
        await event.reply(
            f"✅ مقدار تغییر نام ذخیره شد: `{state['rename_value']}`\n"
            f"حالت فعال: **{mode_desc}**",
            buttons=get_rename_inline_keyboard()
        )
        return

    # ۲. اگر عکس ارسال شده باشد (جهت تامبنیل یا لوگو)
    is_image = event.photo or (event.file and event.file.ext in [".png", ".jpg", ".jpeg"])
    if is_image and not (event.file and event.file.ext == ".pdf"):
        if state["waiting_for"] == "watermark_logo":
            status_msg = await event.reply("⏳ در حال ثبت لوگوی واترمارک...")
            await event.download_media(WATERMARK_LOGO_PATH)
            state["has_watermark_logo"] = True
            state["watermark_enabled"] = True
            state["waiting_for"] = None
            await status_msg.edit("✅ **لوگوی واترمارک با موفقیت ذخیره و فعال شد!**", buttons=get_watermark_inline_keyboard())
            return

        # در غیر این صورت به عنوان تامبنیل ذخیره می‌شود
        status_msg = await event.reply("⏳ در حال پردازش و ثبت عکس به عنوان تامبنیل...")
        temp_photo = os.path.join(config.TEMP_DIR, "temp_incoming_photo.jpg")
        await event.download_media(temp_photo)
        try:
            optimize_custom_thumbnail(temp_photo, CUSTOM_THUMB_PATH)
            state["has_custom_thumb"] = True
            state["thumb_mode"] = "custom"
            state["waiting_for"] = None
            if os.path.exists(temp_photo):
                os.remove(temp_photo)
            await status_msg.edit("✅ **عکس به عنوان تامبنیل دلخواه تنظیم شد!**", buttons=get_thumb_inline_keyboard())
        except Exception as e:
            await status_msg.edit(f"❌ خطا در پردازش تصویر: {e}")
        return

    # ۳. دریافت و پردازش فایل PDF
    if event.document:
        file_name = None
        for attr in event.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
                break

        is_pdf = (event.file.ext == ".pdf") or (file_name and file_name.lower().endswith(".pdf"))
        if not is_pdf:
            return

        task_id = event.message.id
        raw_pdf_path = os.path.join(config.TEMP_DIR, f"raw_{task_id}.pdf")
        cleaned_pdf_path = os.path.join(config.TEMP_DIR, f"cleaned_{task_id}.pdf")
        watermarked_pdf_path = os.path.join(config.TEMP_DIR, f"wm_{task_id}.pdf")
        auto_thumb_path = os.path.join(config.TEMP_DIR, f"thumb_{task_id}.jpg")

        status_msg = await event.reply("📥 در حال دریافت فایل PDF...")

        try:
            # دانلود چندکاناله و فوق‌سریع با FastTelethon
            await download_pdf_fast(client, event.message, raw_pdf_path)
            current_pdf = raw_pdf_path

            # گام ۱: حذف واترمارک‌های قبلی (در صورت فعال بودن)
            if state["remove_wm_enabled"] or state["remove_wm_text"]:
                await status_msg.edit("🧹 در حال پاکسازی اصولی واترمارک‌ها و متن‌های مزاحم...")
                stats = remove_watermark_clean(
                    input_pdf_path=current_pdf,
                    output_pdf_path=cleaned_pdf_path,
                    remove_repeated_logos=state["remove_wm_enabled"],
                    text_to_remove=state["remove_wm_text"]
                )
                current_pdf = cleaned_pdf_path

            # گام ۲: درج واترمارک جدید (در صورت فعال بودن)
            if state["watermark_enabled"] and state["has_watermark_logo"] and os.path.exists(WATERMARK_LOGO_PATH):
                await status_msg.edit("🏷 در حال درج لوگوی اختصاصی شما در نقاط امن...")
                apply_watermark_to_pdf(
                    input_pdf_path=current_pdf,
                    output_pdf_path=watermarked_pdf_path,
                    logo_path=WATERMARK_LOGO_PATH,
                    position=state["watermark_pos"],
                    target_pages=state["watermark_pages"]
                )
                current_pdf = watermarked_pdf_path

            # گام ۳: تولید تامبنیل
            actual_thumb = None
            if state["thumb_mode"] == "custom" and state["has_custom_thumb"] and os.path.exists(CUSTOM_THUMB_PATH):
                actual_thumb = CUSTOM_THUMB_PATH
            else:
                generate_pdf_thumbnail(current_pdf, auto_thumb_path)
                actual_thumb = auto_thumb_path

            # گام ۴: آپلود چندکاناله و فوق‌سریع با FastTelethon و ارسال فایل نهایی
            caption = event.text or ""
            await status_msg.edit("🚀 در حال آپلود فوق‌سریع و ارسال نسخه نهایی...")
            
            uploaded_file = await upload_pdf_fast(client, current_pdf)
            final_filename = calculate_target_filename(file_name)
            await client.send_file(
                event.chat_id,
                file=uploaded_file,
                thumb=actual_thumb,
                caption=caption,
                force_document=True,
                attributes=[DocumentAttributeFilename(final_filename)]
            )

            await status_msg.delete()

        except Exception as e:
            await status_msg.edit(f"❌ خطا در پردازش فایل: {str(e)}")

        finally:
            for p in [raw_pdf_path, cleaned_pdf_path, watermarked_pdf_path, auto_thumb_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass


if __name__ == "__main__":
    print("🤖 ربات همه‌منظوره PDF آماده فعالیت است...")
    client.start(bot_token=config.BOT_TOKEN)
    client.run_until_disconnected()
