# utils.py
import fitz  # PyMuPDF
from PIL import Image
import os
import random
import hashlib
from collections import defaultdict

def generate_pdf_thumbnail(pdf_path: str, output_thumb_path: str) -> str:
    """
    استخراج صفحه اول PDF و تبدیل به تامبنیل تلگرام.
    """
    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        doc.close()
        raise ValueError("فایل PDF خالی است.")
    
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=150)
    
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    
    img.thumbnail((320, 320), Image.Resampling.LANCZOS)
    img.save(output_thumb_path, format="JPEG", quality=90)
    return output_thumb_path


def optimize_custom_thumbnail(input_image_path: str, output_thumb_path: str) -> str:
    """
    بهینه‌سازی ابعاد تصویر تامبنیل ارسالی کاربر.
    """
    with Image.open(input_image_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((320, 320), Image.Resampling.LANCZOS)
        img.save(output_thumb_path, format="JPEG", quality=90)
    return output_thumb_path


def _is_safe_rect(candidate_rect: fitz.Rect, text_rects: list, padding: float = 6.0) -> bool:
    expanded = fitz.Rect(
        candidate_rect.x0 - padding,
        candidate_rect.y0 - padding,
        candidate_rect.x1 + padding,
        candidate_rect.y1 + padding
    )
    for tr in text_rects:
        if expanded.intersects(tr):
            return False
    return True


def _get_candidate_rects(page_rect: fitz.Rect, w: float, h: float, margin: float = 18.0) -> dict:
    pw, ph = page_rect.width, page_rect.height
    return {
        "bottom-right": fitz.Rect(pw - w - margin, ph - h - margin, pw - margin, ph - margin),
        "bottom-left": fitz.Rect(margin, ph - h - margin, margin + w, ph - margin),
        "top-right": fitz.Rect(pw - w - margin, margin, pw - margin, margin + h),
        "top-left": fitz.Rect(margin, margin, margin + w, margin + h),
        "bottom-center": fitz.Rect((pw - w) / 2, ph - h - margin, (pw + w) / 2, ph - margin),
        "top-center": fitz.Rect((pw - w) / 2, margin, (pw + w) / 2, margin + h)
    }


def apply_watermark_to_pdf(
    input_pdf_path: str,
    output_pdf_path: str,
    logo_path: str,
    position: str = "bottom-right",
    target_pages: str = "all",
    max_logo_w: float = 65.0,
    max_logo_h: float = 35.0
) -> str:
    """
    درج لوگو/واترمارک در گوشه‌های امن بدون هیچ تداخل با متن.
    """
    if not os.path.exists(logo_path):
        raise FileNotFoundError("لوگوی واترمارک یافت نشد.")

    doc = fitz.open(input_pdf_path)
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        return input_pdf_path

    with Image.open(logo_path) as img:
        orig_w, orig_h = img.size
    aspect = orig_h / orig_w if orig_w > 0 else 1.0

    target_w = max_logo_w
    target_h = target_w * aspect
    if target_h > max_logo_h:
        target_h = max_logo_h
        target_w = target_h / aspect

    if target_pages == "first":
        pages_to_watermark = [0]
    elif target_pages == "random":
        sample_count = max(1, total_pages // 2)
        pages_to_watermark = sorted(random.sample(range(total_pages), sample_count))
    else:
        pages_to_watermark = list(range(total_pages))

    for page_num in pages_to_watermark:
        page = doc.load_page(page_num)
        page_rect = page.rect

        text_blocks = page.get_text("blocks")
        text_rects = [
            fitz.Rect(b[:4]) for b in text_blocks
            if len(b) >= 5 and isinstance(b[4], str) and b[4].strip()
        ]

        candidates = _get_candidate_rects(page_rect, target_w, target_h, margin=15.0)

        safe_candidates = {}
        for pos_name, rect in candidates.items():
            if _is_safe_rect(rect, text_rects, padding=8.0):
                safe_candidates[pos_name] = rect

        chosen_rect = None
        if position == "random":
            if safe_candidates:
                chosen_pos = random.choice(list(safe_candidates.keys()))
                chosen_rect = safe_candidates[chosen_pos]
            else:
                chosen_rect = candidates["bottom-right"]
        else:
            if position in safe_candidates:
                chosen_rect = safe_candidates[position]
            elif safe_candidates:
                chosen_rect = list(safe_candidates.values())[0]
            else:
                chosen_rect = candidates.get(position, candidates["bottom-right"])

        if chosen_rect:
            page.insert_image(
                chosen_rect,
                filename=logo_path,
                keep_proportion=True,
                overlay=True
            )

    doc.save(output_pdf_path)
    doc.close()
    return output_pdf_path


# ==================== الگوریتم‌های اصولی حذف واترمارک ====================

def remove_watermark_clean(
    input_pdf_path: str,
    output_pdf_path: str,
    remove_repeated_logos: bool = True,
    text_to_remove: str = None,
    corner_only: bool = True
) -> dict:
    """
    الگوریتم اصولی و مهندسی‌شده برای حذف تمیز واترمارک:
    ۱. شناسایی واترمارک‌های تصویری بر اساس تکرار در صفحات یا قرارگیری در حاشیه‌ها (Corner/Margin).
    ۲. حذف بدون آسیب زدن به تصاویر واقعی یا متن‌های اصلی کتاب/سند.
    ۳. حذف متن‌های مزاحم (مثل آیدی کانال، لینک، نام سایت) در صورت درخواست.
    """
    doc = fitz.open(input_pdf_path)
    total_pages = len(doc)
    stats = {"removed_images": 0, "removed_text_occurrences": 0}

    if total_pages == 0:
        doc.close()
        return stats

    # ۱. شناسایی تصاویر مشکوک به واترمارک
    # واترمارک‌ها یا دارای xref مشترک در صفحات هستند، یا در حاشیه‌ها تکرار شده‌اند
    image_occurrences = defaultdict(list)  # xref: [(page_index, rect)]
    image_hashes = defaultdict(list)       # md5_hash: [xref, ...]

    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        p_rect = page.rect
        images = page.get_images(full=True)
        
        # حاشیه‌های امن برای تشخیص گوشه‌ها (15% از هر طرف صفحه)
        margin_w = p_rect.width * 0.22
        margin_h = p_rect.height * 0.18

        for img in images:
            xref = img[0]
            rects = page.get_image_rects(xref)
            for r in rects:
                # بررسی اینکه آیا این عکس در حاشیه یا گوشه صفحه است
                is_corner = (
                    (r.x1 <= margin_w or r.x0 >= p_rect.width - margin_w) or
                    (r.y1 <= margin_h or r.y0 >= p_rect.height - margin_h)
                )
                image_occurrences[xref].append({
                    "page": page_num,
                    "rect": r,
                    "is_corner": is_corner,
                    "area": r.width * r.height
                })

    # شناسایی قطعی xrefهایی که واترمارک هستند:
    # شرایط واترمارک اصولی:
    # الف) در ۲ صفحه یا بیشتر تکرار شده باشد (بیشتر اسناد واقعی تصاویرشان فقط ۱ بار می‌آید)
    # ب) یا اندازه آن کوچک باشد و در حاشیه/گوشه قرار گرفته باشد
    xrefs_to_remove = set()

    for xref, occ_list in image_occurrences.items():
        pages_count = len(set(o["page"] for o in occ_list))
        
        # اگر در چند صفحه تکرار شده باشد، قطعا واترمارک یا هدر/فوتر تبلیغاتی است
        if pages_count >= 2 and remove_repeated_logos:
            xrefs_to_remove.add(xref)
        elif corner_only:
            # اگر فقط در یک صفحه بود، اما دقیقا در گوشه با اندازه کوچک بود
            all_in_corners = all(o["is_corner"] for o in occ_list)
            small_size = all(o["area"] < 15000 for o in occ_list)  # کمتر از ابعاد تصاویر مقالات
            if all_in_corners and small_size:
                xrefs_to_remove.add(xref)

    # ۲. حذف اصولی تصاویر مشخص‌شده از صفحات
    for page_num in range(total_pages):
        page = doc.load_page(page_num)

        # حذف تصاویر واترمارک
        for xref in xrefs_to_remove:
            try:
                if hasattr(page, "delete_image"):
                    page.delete_image(xref)
                    stats["removed_images"] += 1
                else:
                    for r in page.get_image_rects(xref):
                        page.add_redact_annot(r)
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
                        stats["removed_images"] += 1
            except Exception:
                pass

        # ۳. حذف متن واترمارک (در صورت مشخص بودن آیدی یا نام)
        if text_to_remove and text_to_remove.strip():
            text_rects = page.search_for(text_to_remove.strip())
            for tr in text_rects:
                page.add_redact_annot(tr)
                stats["removed_text_occurrences"] += 1
            if text_rects:
                page.apply_redactions()

    # ذخیره فایل بهینه‌سازی‌شده و پاکسازی اشیاء حذف‌شده
    doc.save(
        output_pdf_path,
        garbage=4,       # حذف داده‌های بدون استفاده و بدون مرجع
        deflate=True     # فشرده‌سازی جهت کاهش حجم
    )
    doc.close()
    return stats
