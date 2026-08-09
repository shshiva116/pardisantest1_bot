import os
import json
import io
import asyncio
import time
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
EXAM_TIMEOUT_SECONDS = 20 * 60  # ۲۰ دقیقه زمان آزمون

PERSIAN_DIGITS = {'1': '۱', '2': '۲', '3': '۳', '4': '۴', '5': '۵', '6': '۶', '7': '۷', '8': '۸', '9': '۹', '0': '۰'}
RTL_MARK = "\u200f"

def to_persian_num(num):
    return ''.join(PERSIAN_DIGITS.get(char, char) for char in str(num))

# ---------------------------------------------------------
# مدیریت داده‌ها
# ---------------------------------------------------------
def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
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
def draw_digit_vector(draw, digit, left, top, size=60, color=(0, 0, 0), stroke=8):
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
    
    padding = 20
    badge_size = 70
    grid_w = target_w * 2 + padding * 3
    grid_h = target_h * 2 + padding * 3

    canvas = Image.new("RGB", (grid_w, grid_h), (240, 240, 240))
    positions = [
        (padding, padding),
        (target_w + padding * 2, padding),
        (padding, target_h + padding * 2),
        (target_w + padding * 2, target_h + padding * 2)
    ]

    for idx, (img, pos) in enumerate(zip(resized_imgs, positions)):
        canvas.paste(img, pos)
        draw = ImageDraw.Draw(canvas)
        
        bx, by = pos[0] + 15, pos[1] + 15
        draw.rectangle([bx, by, bx + badge_size, by + badge_size], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
        draw_digit_vector(draw, str(idx + 1), bx + 10, by + 10, size=badge_size - 20)

    buf = io.BytesIO()
    canvas.save(buf, format='JPEG', quality=95)
    buf.seek(0)
    return buf

# ---------------------------------------------------------
# جستجوی هوشمند تصاویر
# ---------------------------------------------------------
async def find_question_image(exam_num, q_num):
    candidates = [
        os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}.jpg"),
        os.path.join(IMAGES_DIR, f"E{exam_num}_q{q_num}.jpg"),
        os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}.png"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

async def find_option_images(exam_num, q_num):
    paths = []
    for opt_num in range(1, 5):
        candidates = [
            os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}_opt{opt_num}.jpg"),
            os.path.join(IMAGES_DIR, f"E{exam_num}_q{q_num}_opt{opt_num}.jpg"),
            os.path.join(IMAGES_DIR, f"e{exam_num}_q{q_num}_{opt_num}.jpg"),
        ]
        found = None
        for path in candidates:
            if os.path.exists(path):
                found = path
                break
        paths.append(found)
    
    if all(p is not None for p in paths):
        return paths
    return None

def is_image_option(opt):
    text = str(opt).strip()
    return text.lower().endswith(('.jpg', '.jpeg', '.png'))

# ---------------------------------------------------------
# کیبورد اصلی و دستورات پایه
# ---------------------------------------------------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [['شروع آزمون آیین‌نامه 🚗'], ['آمار من 📊']],
    resize_keyboard=True
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"{RTL_MARK}به ربات آزمون آیین‌نامه خوش آمدید!\n{RTL_MARK}برای شروع آزمون یا مشاهده آمار کلی، از دکمه‌های زیر استفاده کنید."
    await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)

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
        f"{RTL_MARK}📊 **آمار کلی آزمون‌های شما:**\n\n"
        f"{RTL_MARK}🔹 تعداد کل آزمون‌های شرکت‌شده: {to_persian_num(stats['total'])}\n"
        f"{RTL_MARK}✅ تعداد قبول‌شده: {to_persian_num(stats['passed'])}\n"
        f"{RTL_MARK}❌ تعداد مردود‌شده: {to_persian_num(stats['failed'])}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ---------------------------------------------------------
# انتخاب آزمون و شروع
# ---------------------------------------------------------
async def show_exam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions_data = load_questions()
    if not questions_data:
        msg = f"{RTL_MARK}❌ فایل سوالات (questions.json) بارگذاری نشد."
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    keyboard = []
    row = []
    for i in range(1, 18):
        row.append(InlineKeyboardButton(f"آزمون {to_persian_num(i)}", callback_data=f"select_exam_{i}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"{RTL_MARK}لطفاً شماره آزمون مورد نظر خود را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def exam_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await asyncio.sleep(EXAM_TIMEOUT_SECONDS)
    exam = context.user_data.get('exam')
    if exam and exam.get('active'):
        await context.bot.send_message(chat_id=chat_id, text=f"{RTL_MARK}⏱ **زمان ۲۰ دقیقه‌ای آزمون به پایان رسید!**", parse_mode='Markdown')
        await finish_exam_by_chat_id(context, chat_id)

async def handle_exam_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "start_new_exam_from_btn":
        await show_exam_list(update, context)
        return

    exam_num = int(data.split('_')[2])
    persian_exam_num = to_persian_num(exam_num)
    questions_data = load_questions()

    exam_questions = (
        questions_data.get(f"آزمون {exam_num}") or 
        questions_data.get(f"آزمون {persian_exam_num}") or
        questions_data.get(str(exam_num)) or
        questions_data.get(str(persian_exam_num)) or
        []
    )

    if not exam_questions:
        await query.message.reply_text(f"{RTL_MARK}❌ سوالات مربوط به آزمون {to_persian_num(exam_num)} یافت نشد.")
        return

    if 'timer_task' in context.user_data and context.user_data['timer_task']:
        context.user_data['timer_task'].cancel()

    context.user_data['exam'] = {
        'exam_num': exam_num,
        'questions': exam_questions,
        'current_index': 0,
        'user_answers': {},
        'active': True,
        'last_review_msg_id': None
    }

    chat_id = update.effective_chat.id
    timer_task = asyncio.create_task(exam_timer(context, chat_id))
    context.user_data['timer_task'] = timer_task

    await send_exam_question(update, context)

# ---------------------------------------------------------
# نمایش سوال و ثبت پاسخ
# ---------------------------------------------------------
def build_question_keyboard(q_index, total_q, selected_opt=None):
    buttons = []
    opts_row = []
    for i in range(1, 5):
        label = f"گزینه {to_persian_num(i)}"
        if selected_opt == i:
            label = f"✅ {label}"
        opts_row.append(InlineKeyboardButton(label, callback_data=f"ans_{i}"))
    buttons.append(opts_row)

    nav_row = []
    if q_index > 0:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data="nav_prev"))
    if q_index < total_q - 1:
        nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data="nav_next"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🏁 پایان آزمون", callback_data="finish_exam_now")])
    return InlineKeyboardMarkup(buttons)

async def send_exam_question(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    exam = context.user_data.get('exam')
    if not exam or not exam.get('active'):
        return

    q_idx = exam['current_index']
    questions = exam['questions']
    q_data = questions[q_idx]
    total_q = len(questions)
    exam_num = exam['exam_num']

    selected_opt = exam['user_answers'].get(q_idx)
    reply_markup = build_question_keyboard(q_idx, total_q, selected_opt)

    caption = (
        f"{RTL_MARK}📋 **سوال {to_persian_num(q_idx + 1)} از {to_persian_num(total_q)}** (آزمون {to_persian_num(exam_num)})\n\n"
        f"{RTL_MARK}{to_persian_num(q_data.get('question', '').strip())}\n\n"
    )

    opts = q_data.get('options', [])
    opt_imgs = await find_option_images(exam_num, q_idx + 1)

    if not opt_imgs and opts and not is_image_option(opts[0]):
        for idx, opt in enumerate(opts):
            p_num = to_persian_num(idx + 1)
            clean_text = to_persian_num(str(opt).strip())
            caption += f"{RTL_MARK}گزینه {p_num} - {clean_text}\n"

    q_img = await find_question_image(exam_num, q_idx + 1)

    photo_to_send = None
    if q_img:
        photo_to_send = open(q_img, 'rb')
    elif opt_imgs:
        photo_to_send = create_2x2_grid(*opt_imgs)

    chat_id = update.effective_chat.id

    if is_callback and update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass

    if photo_to_send:
        await context.bot.send_photo(chat_id=chat_id, photo=photo_to_send, caption=caption, reply_markup=reply_markup, parse_mode='Markdown')
        if hasattr(photo_to_send, 'close'):
            photo_to_send.close()
    else:
        await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_answer_and_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam = context.user_data.get('exam')
    if not exam or not exam.get('active'):
        await query.message.reply_text(f"{RTL_MARK}آزمون در حال حاضر فعال نیست.")
        return

    data = query.data

    if data.startswith("ans_"):
        opt = int(data.split("_")[1])
        exam['user_answers'][exam['current_index']] = opt
        
        # انتقال خودکار به سوال بعدی یا اتمام آزمون در صورت رسیدن به سوال آخر
        if exam['current_index'] < len(exam['questions']) - 1:
            exam['current_index'] += 1
            await send_exam_question(update, context, is_callback=True)
        else:
            await finish_exam(update, context)

    elif data == "nav_next":
        if exam['current_index'] < len(exam['questions']) - 1:
            exam['current_index'] += 1
            await send_exam_question(update, context, is_callback=True)

    elif data == "nav_prev":
        if exam['current_index'] > 0:
            exam['current_index'] -= 1
            await send_exam_question(update, context, is_callback=True)

    elif data == "finish_exam_now":
        await finish_exam(update, context)

# ---------------------------------------------------------
# پایان آزمون و نمایش کارنامه
# ---------------------------------------------------------
async def finish_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat_id
    await finish_exam_by_chat_id(context, chat_id)

async def finish_exam_by_chat_id(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    exam = context.user_data.get('exam')
    if not exam or not exam.get('active'):
        return

    exam['active'] = False

    if 'timer_task' in context.user_data and context.user_data['timer_task']:
        context.user_data['timer_task'].cancel()

    questions = exam['questions']
    user_answers = exam['user_answers']

    correct_count = 0
    wrong_count = 0
    unanswered_count = 0

    grid_buttons = []
    row = []

    for idx, q in enumerate(questions):
        correct_opt = int(q.get('correct_option', 1))
        user_opt = user_answers.get(idx)

        if user_opt is None:
            unanswered_count += 1
            btn_text = f"⬜️ {to_persian_num(idx + 1)}"
        elif user_opt == correct_opt:
            correct_count += 1
            btn_text = f"🟩 {to_persian_num(idx + 1)}"
        else:
            wrong_count += 1
            btn_text = f"🟥 {to_persian_num(idx + 1)}"

        row.append(InlineKeyboardButton(btn_text, callback_data=f"review_q_{idx}"))
        if len(row) == 5:
            grid_buttons.append(row)
            row = []

    if row:
        grid_buttons.append(row)

    grid_buttons.append([InlineKeyboardButton("🔄 شروع آزمون جدید", callback_data="start_new_exam_from_btn")])

    passed = correct_count >= PASSING_SCORE
    update_user_stats(chat_id, passed)

    status_icon = "🎉" if passed else "❌"
    status_text = "قبول شدید" if passed else "مردود شدید"

    report_card = (
        f"{RTL_MARK}📝 **کارنامه آزمون شماره {to_persian_num(exam['exam_num'])}**\n"
        f"{RTL_MARK}━━━━━━━━━━━━━━━━━━\n"
        f"{RTL_MARK}نتیجه آزمون: **{status_text}** {status_icon}\n\n"
        f"{RTL_MARK}✅ پاسخ‌های درست: {to_persian_num(correct_count)}\n"
        f"{RTL_MARK}❌ پاسخ‌های نادرست: {to_persian_num(wrong_count)}\n"
        f"{RTL_MARK}⚪️ بدون پاسخ: {to_persian_num(unanswered_count)}\n\n"
        f"{RTL_MARK}برای مرور هر سوال، روی شماره آن در شبکه زیر کلیک کنید:"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=report_card,
        reply_markup=InlineKeyboardMarkup(grid_buttons),
        parse_mode='Markdown'
    )

# ---------------------------------------------------------
# مرور سوالات با دکمه‌های قبلی/بعدی و ارسال تصویر
# ---------------------------------------------------------
async def handle_review_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam = context.user_data.get('exam')
    if not exam:
        await query.message.reply_text(f"{RTL_MARK}اطلاعات آزمون یافت نشد.")
        return

    q_idx = int(query.data.split('_')[2])
    questions = exam['questions']
    total_q = len(questions)
    q = questions[q_idx]

    chat_id = update.effective_chat.id
    if exam.get('last_review_msg_id'):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=exam['last_review_msg_id'])
        except Exception:
            pass

    q_text_content = to_persian_num(q.get('question', f"سوال شماره {q_idx + 1}").strip())
    options = q.get('options', [])
    correct_opt = int(q.get('correct_option', 1))
    user_opt = exam['user_answers'].get(q_idx)

    msg_text = f"{RTL_MARK}🔍 **مرور سوال شماره {to_persian_num(q_idx + 1)} از {to_persian_num(total_q)}:**\n\n{RTL_MARK}{q_text_content}\n\n"

    exam_num = exam['exam_num']
    opt_imgs = await find_option_images(exam_num, q_idx + 1)

    if not opt_imgs and options and not is_image_option(options[0]):
        for i, opt in enumerate(options):
            opt_num = i + 1
            cleaned_text = to_persian_num(str(opt).strip())
            p_num = to_persian_num(opt_num)
            opt_label = f"گزینه {p_num} - {cleaned_text}"

            if opt_num == correct_opt and opt_num == user_opt:
                msg_text += f"{RTL_MARK}🟢 {opt_label} (پاسخ درست شما)\n"
            elif opt_num == correct_opt:
                msg_text += f"{RTL_MARK}🟢 {opt_label} (پاسخ صحیح)\n"
            elif opt_num == user_opt:
                msg_text += f"{RTL_MARK}🔴 {opt_label} (انتخاب اشتباه شما)\n"
            else:
                msg_text += f"{RTL_MARK}⚪️ {opt_label}\n"
    else:
        p_correct = to_persian_num(correct_opt)
        msg_text += f"{RTL_MARK}🟢 گزینه صحیح: گزینه {p_correct}\n"
        if user_opt:
            p_user = to_persian_num(user_opt)
            if user_opt == correct_opt:
                msg_text += f"{RTL_MARK}✅ پاسخ شما: گزینه {p_user} (درست)\n"
            else:
                msg_text += f"{RTL_MARK}🔴 پاسخ شما: گزینه {p_user} (نادرست)\n"
        else:
            msg_text += f"{RTL_MARK}⚪️ شما به این سوال پاسخ ندادید.\n"

    nav_keyboard = []
    nav_row = []
    if q_idx > 0:
        nav_row.append(InlineKeyboardButton("◀️ سوال قبلی", callback_data=f"review_q_{q_idx - 1}"))
    if q_idx < total_q - 1:
        nav_row.append(InlineKeyboardButton("سوال بعدی ▶️", callback_data=f"review_q_{q_idx + 1}"))
    if nav_row:
        nav_keyboard.append(nav_row)

    # چک کردن وجود تصویر سوال یا شبکه‌ای از تصاویر گزینه‌ها در مرور
    q_img = await find_question_image(exam_num, q_idx + 1)
    photo_to_send = None
    if q_img:
        photo_to_send = open(q_img, 'rb')
    elif opt_imgs:
        photo_to_send = create_2x2_grid(*opt_imgs)

    if photo_to_send:
        sent_msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_to_send,
            caption=msg_text,
            reply_markup=InlineKeyboardMarkup(nav_keyboard),
            parse_mode='Markdown'
        )
        if hasattr(photo_to_send, 'close'):
            photo_to_send.close()
    else:
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=msg_text,
            reply_markup=InlineKeyboardMarkup(nav_keyboard),
            parse_mode='Markdown'
        )

    exam['last_review_msg_id'] = sent_msg.message_id

# ---------------------------------------------------------
# اجرای برنامه
# ---------------------------------------------------------
def main():
    if not TOKEN:
        raise ValueError("متغیر TOKEN در محیط (Environment Variables) تنظیم نشده است!")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(show_exam_list, pattern="^start_new_exam_from_btn$"))
    app.add_handler(CallbackQueryHandler(handle_exam_selection, pattern="^select_exam_"))
    app.add_handler(CallbackQueryHandler(handle_review_question, pattern="^review_q_"))
    app.add_handler(CallbackQueryHandler(handle_answer_and_nav, pattern="^(ans_|nav_|finish_exam_now)"))

    print("ربات با موفقیت فعال شد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
