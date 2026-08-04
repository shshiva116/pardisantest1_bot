import os
import json
import random
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
# Configurations
# ---------------------------------------------------------
TOKEN = os.environ.get('TOKEN')
QUESTIONS_FILE = 'questions.json'
STATS_FILE = 'user_stats.json'
IMAGES_DIR = 'images/'

EXAM_QUESTION_COUNT = 30
PASSING_SCORE = 26

# ---------------------------------------------------------
# Data Helpers
# ---------------------------------------------------------
def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
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

questions_data = load_questions()

# ---------------------------------------------------------
# Vector-Based Number Drawing
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
# Bot UI & Commands
# ---------------------------------------------------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [['شروع آزمون آیین‌نامه 🚗'], ['آمار من 📊']],
    resize_keyboard=True
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "به ربات آزمون آیین‌نامه خوش آمدید!\nبرای شروع آزمون یا مشاهده آمار از دکمه‌های زیر استفاده کنید.",
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
        f"📊 **آمار کارنامه شما:**\n\n"
        f"تعداد کل آزمون‌ها: {stats['total']}\n"
        f"تعداد قبول شده: {stats['passed']} ✅\n"
        f"تعداد مردود شده: {stats['failed']} ❌"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ---------------------------------------------------------
# Exam Selection & Execution
# ---------------------------------------------------------
async def show_exam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global questions_data
    questions_data = load_questions()  # بارگذاری مجدد فایل جهت اطمینان
    
    if not questions_data:
        await update.message.reply_text("خطا: هیچ سوالی در فایل questions.json یافت نشد!")
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
    
    # فیلتر بر اساس exam_number (مطمئن شویم نوع داده یکسان بررسی می‌شود)
    exam_questions = [q for q in questions_data if int(q.get('exam_number', 0)) == exam_num]

    if not exam_questions:
        await query.answer(f"سوالاتی برای آزمون {exam_num} یافت نشد!", show_alert=True)
        return

    context.user_data['exam'] = {
        'questions': exam_questions,
        'current_index': 0,
        'correct_count': 0,
        'wrong_count': 0,
    }

    try:
        await query.delete_message()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🚗 **آزمون شماره {exam_num} شروع شد.**\nموفق باشید!",
        parse_mode='Markdown'
    )
    await send_next_question(update, context)

async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.user_data.get('exam')
    if not exam:
        return

    idx = exam['current_index']
    if idx >= len(exam['questions']):
        await finish_exam(update, context)
        return

    q = exam['questions'][idx]
    q_text = f"سوال {idx + 1} از {len(exam['questions'])}:\n\n{q['question']}"
    
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

    exam_num = q.get('exam_number')
    q_num = q.get('question_number')
    
    grid_img_paths = [os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}_{i}.jpg") for i in range(1, 5)]
    has_grid = all(os.path.exists(p) for p in grid_img_paths)

    chat_id = update.effective_chat.id

    if has_grid:
        grid_bytes = create_2x2_grid(*grid_img_paths)
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=grid_bytes,
            caption=q_text,
            reply_markup=reply_markup
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=q_text,
            reply_markup=reply_markup
        )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam = context.user_data.get('exam')
    if not exam:
        await query.edit_message_text("آزمون فعال یافت نشد. لطفا آزمون جدیدی شروع کنید.")
        return

    idx = exam['current_index']
    q = exam['questions'][idx]
    
    selected_option = int(query.data.split('_')[1])
    correct_option = int(q['correct_option'])

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

async def finish_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.user_data.get('exam')
    correct = exam['correct_count']
    wrong = exam['wrong_count']
    passed = correct >= PASSING_SCORE

    update_user_stats(update.effective_user.id, passed)

    status_str = "قبول شدید! 🎉" if passed else "مردود شدید. ❌"
    result_text = (
        f"🏁 **پایان آزمون**\n\n"
        f"نتیجه: **{status_str}**\n"
        f"تعداد پاسخ‌های درست: {correct}\n"
        f"تعداد پاسخ‌های نادرست: {wrong}\n"
        f"حداقل نمره قبولی: {PASSING_SCORE}"
    )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=result_text,
        parse_mode='Markdown',
        reply_markup=MAIN_KEYBOARD
    )
    context.user_data['exam'] = None

# ---------------------------------------------------------
# Main Execution
# ---------------------------------------------------------
def main():
    if not TOKEN:
        raise ValueError("TOKEN environment variable is missing!")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_exam_selection, pattern="^select_exam_"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^ans_"))

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
