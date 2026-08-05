import os
import json
import io
from PIL import Image, ImageDraw
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------
# تنظیمات اصلی
# ---------------------------------------------------------
TOKEN = os.environ.get('TOKEN')
QUESTIONS_FILE = 'questions.json'
STATS_FILE = 'user_stats.json'
IMAGES_DIR = 'images/'
PASSING_SCORE = 26
TOTAL_QUESTIONS = 30

PERSIAN_DIGITS = {'1': '۱', '2': '۲', '3': '۳', '4': '۴', '5': '۵', '6': '۶', '7': '۷', '8': '۸', '9': '۹', '0': '۰'}

def to_persian_num(num):
    return ''.join(PERSIAN_DIGITS.get(char, char) for char in str(num))

# ---------------------------------------------------------
# مدیریت فایل‌ها و آمار
# ---------------------------------------------------------
def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {QUESTIONS_FILE}: {e}")
            return {}
    return {}

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_stats(stats):
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def update_user_stats(user_id, passed: bool):
    stats = load_stats()
    str_id = str(user_id)
    if str_id not in stats:
        stats[str_id] = {"total": 0, "passed": 0, "failed": 0}
    
    stats[str_id]["total"] += 1
    if passed:
        stats[str_id]["passed"] += 1
    else:
        stats[str_id]["failed"] += 1
    
    save_stats(stats)

# ---------------------------------------------------------
# ساخت شبکه تصویری ۲x۲
# ---------------------------------------------------------
def draw_digit_vector(draw, digit, left, top, size=30, color=(0, 0, 0), stroke=4):
    l, t, w, h = left, top, size, size
    r, b = l + w, t + h
    cx, cy = l + w / 2, t + h / 2

    if digit == '1':
        draw.line([(cx, t), (cx, b)], fill=color, width=stroke)
        draw.line([(cx - w/4, t + h/4), (cx, t)], fill=color, width=stroke)
        draw.line([(cx - w/3, b), (cx + w/3, b)], fill=color, width=stroke)
    elif digit == '2':
        draw.line([(l, t + h/4), (l + w/4, t), (r - w/4, t), (r, t + h/4), (l, b), (r, b)], fill=color, width=stroke)
    elif digit == '3':
        draw.line([(l, t), (r, t), (cx, cy), (r, cy + h/4), (r - w/4, b), (l, b)], fill=color, width=stroke)
        draw.line([(cx, cy), (r, cy)], fill=color, width=stroke)
    elif digit == '4':
        draw.line([(r - w/4, b), (r - w/4, t), (l, cy), (r, cy)], fill=color, width=stroke)

def create_2x2_grid(img1_path, img2_path, img3_path, img4_path):
    imgs = [Image.open(p).convert("RGB") for p in [img1_path, img2_path, img3_path, img4_path]]
    target_w = max(img.width for img in imgs)
    target_h = max(img.height for img in imgs)

    resized_imgs = [img.resize((target_w, target_h), Image.Resampling.LANCZOS) for img in imgs]
    
    padding = 15
    badge_size = 35
    grid_w = target_w * 2 + padding * 3
    grid_h = target_h * 2 + padding * 3

    canvas = Image.new("RGB", (grid_w, grid_h), (245, 245, 245))
    positions = [
        (padding, padding),
        (target_w + padding * 2, padding),
        (padding, target_h + padding * 2),
        (target_w + padding * 2, target_h + padding * 2)
    ]

    for idx, (img, pos) in enumerate(zip(resized_imgs, positions)):
        canvas.paste(img, pos)
        draw = ImageDraw.Draw(canvas)
        
        bx, by = pos[0] + 8, pos[1] + 8
        draw.rectangle([bx, by, bx + badge_size, by + badge_size], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
        draw_digit_vector(draw, str(idx + 1), bx + 7, by + 5, size=20, color=(0, 0, 0), stroke=3)

    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format='JPEG', quality=95)
    img_byte_arr.seek(0)
    return img_byte_arr

# ---------------------------------------------------------
# کیبورد اصلی و دستورات
# ---------------------------------------------------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [['شروع آزمون آیین‌نامه 🚗'], ['آمار من 📊']],
    resize_keyboard=True
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "به ربات آزمون آیین‌نامه خوش آمدید!\nبرای شروع آزمون یا مشاهده آمار کلی، از دکمه‌های زیر استفاده کنید.",
        reply_markup=MAIN_KEYBOARD
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == 'شروع آزمون آیین‌نامه 🚗':
        await show_exam_list(update, context)
    elif text == 'آمار من 📊':
        await show_stats(update, context)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stats = load_stats().get(user_id, {"total": 0, "passed": 0, "failed": 0})
    
    msg = (
        f"📊 **آمار کلی آزمون‌های شما:**\n\n"
        f"🔹 تعداد کل آزمون‌های شرکت‌شده: {stats['total']}\n"
        f"✅ تعداد قبول‌شده: {stats['passed']}\n"
        f"❌ تعداد مردود‌شده: {stats['failed']}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ---------------------------------------------------------
# منوی انتخاب آزمون و اجرای سوالات
# ---------------------------------------------------------
async def show_exam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions_data = load_questions()
    if not questions_data:
        await update.message.reply_text("❌ فایل سوالات (questions.json) بارگذاری نشد یا خالی است.")
        return

    keyboard = []
    row = []
    for i in range(1, 18):
        row.append(InlineKeyboardButton(f"آزمون {i}", callback_data=f"select_exam_{i}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("لطفاً شماره آزمون مورد نظر خود را انتخاب کنید:", reply_markup=reply_markup)

async def handle_exam_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam_num = int(query.data.split('_')[2])
    persian_exam_num = to_persian_num(exam_num)
    questions_data = load_questions()

    # بررسی انواع فرمت کلید در فایل JSON
    key_eng = f"آزمون {exam_num}"
    key_per = f"آزمون {persian_exam_num}"

    exam_questions = questions_data.get(key_eng) or questions_data.get(key_per) or []

    if not exam_questions:
        await query.message.reply_text(f"❌ سوالات مربوط به آزمون {exam_num} یافت نشد.")
        return

    context.user_data['exam'] = {
        'exam_num': exam_num,
        'questions': exam_questions,
        'current_index': 0,
        'correct_count': 0,
        'wrong_count': 0,
        'unanswered_count': 0
    }

    try:
        await query.delete_message()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🚗 **آزمون شماره {exam_num} شروع شد.**\nتعداد سوالات: {len(exam_questions)}\nزمان و فرصت خود را مدیریت کنید. موفق باشید!",
        parse_mode='Markdown'
    )
    await send_next_question(update, context)

async def find_image_path(exam_num, q_num, opt_num):
    candidates = [
        os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}_opt{opt_num}.jpg"),
        os.path.join(IMAGES_DIR, f"E{exam_num}_q{q_num}_opt{opt_num}.jpg"),
        os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}_{opt_num}.jpg"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.user_data.get('exam')
    if not exam:
        return

    idx = exam['current_index']
    if idx >= len(exam['questions']):
        await finish_exam(update, context)
        return

    q = exam['questions'][idx]
    q_text_content = q.get('question', f"سوال شماره {idx + 1}").strip()
    options = q.get('options', [])
    
    q_text = f"❓ **سوال {idx + 1} از {len(exam['questions'])}:**\n\n{q_text_content}"
    
    formatted_options = [f"{i+1}. {opt}" for i, opt in enumerate(options) if str(opt).strip()]
    if formatted_options:
        q_text += "\n\n" + "\n".join(formatted_options)

    keyboard = [
        [
            InlineKeyboardButton("گزینه ۱", callback_data="ans_1"),
            InlineKeyboardButton("گزینه ۲", callback_data="ans_2"),
        ],
        [
            InlineKeyboardButton("گزینه ۳", callback_data="ans_3"),
            InlineKeyboardButton("گزینه ۴", callback_data="ans_4"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id

    exam_num = exam['exam_num']
    q_num = idx + 1
    paths = [await find_image_path(exam_num, q_num, i) for i in range(1, 5)]
    paths = [p for p in paths if p is not None]

    if len(paths) == 4:
        grid_bytes = create_2x2_grid(paths[0], paths[1], paths[2], paths[3])
        await context.bot.send_photo(chat_id=chat_id, photo=grid_bytes, caption=q_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=chat_id, text=q_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam = context.user_data.get('exam')
    if not exam:
        return

    idx = exam['current_index']
    q = exam['questions'][idx]
    
    selected_option = int(query.data.split('_')[1])
    correct_option = int(q.get('correct_option', 1))

    if selected_option == correct_option:
        exam['correct_count'] += 1
    else:
        exam['wrong_count'] += 1

    exam['current_index'] += 1
    
    try:
        await query.delete_message()
    except Exception:
        pass

    await send_next_question(update, context)

# ---------------------------------------------------------
# نمایش کارنامه پایانی
# ---------------------------------------------------------
async def finish_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.user_data.get('exam')
    correct = exam['correct_count']
    wrong = exam['wrong_count']
    total_q = len(exam['questions'])
    unanswered = total_q - (correct + wrong)
    
    passed = correct >= PASSING_SCORE
    update_user_stats(update.effective_user.id, passed)

    status_icon = "🎉" if passed else "❌"
    status_text = "قبول شدید" if passed else "مردود شدید"

    report_card = (
        f"📝 **کارنامه آزمون شماره {exam['exam_num']}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"نتیجه آزمون: **{status_text}** {status_icon}\n\n"
        f"✅ پاسخ‌های درست: {correct}\n"
        f"❌ پاسخ‌های نادرست: {wrong}\n"
        f"⚪️ بدون پاسخ: {unanswered}\n"
        f"📊 کل سوالات: {total_q}\n"
        f"🎯 حد نصاب قبولی: {PASSING_SCORE} پاسخ درست\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=report_card,
        parse_mode='Markdown',
        reply_markup=MAIN_KEYBOARD
    )
    context.user_data['exam'] = None

# ---------------------------------------------------------
# نقطه شروع برنامه
# ---------------------------------------------------------
def main():
    if not TOKEN:
        raise ValueError("متغیر TOKEN در محیط سرور تنظیم نشده است!")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_exam_selection, pattern="^select_exam_"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^ans_"))

    print("Bot started successfully...")
    app.run_polling()

if __name__ == '__main__':
    main()
