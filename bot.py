import os
import json
import io
import asyncio
import threading
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
# سرور سبک Flask جهت پایداری در بسترهای ابری (مانند Railway)
# ---------------------------------------------------------
try:
    from flask import Flask
    app_web = Flask(__name__)

    @app_web.route('/')
    def home():
        return "Bot is running online!"

    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        app_web.run(host="0.0.0.0", port=port)
    
    flask_available = True
except ImportError:
    flask_available = False

# ---------------------------------------------------------
# تنظیمات اصلی ربات، کانال و کاراکترهای فارسی
# ---------------------------------------------------------
TOKEN = os.environ.get('TOKEN')
QUESTIONS_FILE = 'questions.json'
STATS_FILE = 'user_stats.json'
IMAGES_DIR = 'images/'
PASSING_SCORE = 26
EXAM_TIMEOUT_SECONDS = 20 * 60  # ۲۰ دقیقه

CHANNEL_USERNAME = "@ds_pardisan"
CHANNEL_LINK = "https://t.me/ds_pardisan"

PERSIAN_DIGITS = {'1': '۱', '2': '۲', '3': '۳', '4': '۴', '5': '۵', '6': '۶', '7': '۷', '8': '۸', '9': '۹', '0': '۰'}
RLM = "\u200f"  # کاراکتر راست‌چینی متون

def to_persian_num(text):
    """تبدیل تمام اعداد انگلیسی به فارسی"""
    if text is None:
        return ""
    str_text = str(text)
    return ''.join(PERSIAN_DIGITS.get(char, char) for char in str_text)

def clean_text(text):
    """پاک‌سازی فاصله‌های اضافه و تبدیل اعداد به فارسی"""
    if text is None:
        return ""
    cleaned = str(text).strip()
    return to_persian_num(cleaned)

# ---------------------------------------------------------
# بررسی عضویت در کانال
# ---------------------------------------------------------
async def is_user_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Error checking membership: {e}")
        return True

async def check_membership_and_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if await is_user_member(context, user_id):
        return True

    keyboard = [
        [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ عضو شدم / بررسی مجدد", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = (
        f"{RLM}⚠️ **جهت استفاده از ربات، ابتدا باید در کانال زیر عضو شوید:**\n\n"
        f"{RLM}کانال: {CHANNEL_USERNAME}\n\n"
        f"{RLM}پس از عضویت، روی دکمه «عضو شدم / بررسی مجدد» کلیک کنید."
    )

    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')

    return False

# ---------------------------------------------------------
# مدیریت فایل‌ها و آمار
# ---------------------------------------------------------
def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading questions: {e}")
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
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving stats: {e}")

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
# ساخت شبکه تصویری ۲x۲ برای گزینه‌ها
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
        draw.rectangle([bx, by, bx + badge_size, by + badge_size], fill=(255, 255, 255), outline=(0, 0, 0), width=4)
        draw_digit_vector(draw, str(idx + 1), bx + 12, by + 10, size=45, color=(0, 0, 0), stroke=7)

    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format='JPEG', quality=95)
    img_byte_arr.seek(0)
    return img_byte_arr

# ---------------------------------------------------------
# جستجوی تصاویر
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

def clean_option_text(opt):
    text = clean_text(opt)
    if text.lower().endswith(('.jpg', '.jpeg', '.png')):
        return ""
    return text

# ---------------------------------------------------------
# کیبورد اصلی و دستورات اولیه
# ---------------------------------------------------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [['شروع آزمون آیین‌نامه 🚗'], ['آمار من 📊']],
    resize_keyboard=True
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_and_prompt(update, context):
        return

    await update.message.reply_text(
        f"{RLM}به ربات آزمون آیین‌نامه خوش آمدید!\n{RLM}برای شروع آزمون یا مشاهده آمار کلی، از دکمه‌های زیر استفاده کنید.",
        reply_markup=MAIN_KEYBOARD
    )

async def handle_check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_user_member(context, update.effective_user.id):
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{RLM}✅ عضویت شما تایید شد!\n{RLM}به ربات آزمون آیین‌نامه خوش آمدید.",
            reply_markup=MAIN_KEYBOARD
        )
    else:
        await query.answer("❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_and_prompt(update, context):
        return

    text = clean_text(update.message.text)
    if 'شروع آزمون' in text:
        await show_exam_list(update, context)
    elif 'آمار من' in text:
        await show_stats(update, context)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stats = load_stats().get(user_id, {"total": 0, "passed": 0, "failed": 0})
    
    msg = (
        f"{RLM}📊 **آمار کلی آزمون‌های شما:**\n\n"
        f"{RLM}🔹 تعداد کل آزمون‌های شرکت‌شده: {to_persian_num(stats['total'])}\n"
        f"{RLM}✅ تعداد قبول‌شده: {to_persian_num(stats['passed'])}\n"
        f"{RLM}❌ تعداد مردود‌شده: {to_persian_num(stats['failed'])}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ---------------------------------------------------------
# نمایش لیست آزمون‌ها و شروع
# ---------------------------------------------------------
async def show_exam_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions_data = load_questions()
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat_id

    if not questions_data:
        msg = f"{RLM}❌ فایل سوالات (questions.json) بارگذاری نشد."
        await context.bot.send_message(chat_id=chat_id, text=msg)
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
    text = f"{RLM}لطفاً شماره آزمون مورد نظر خود را انتخاب کنید:"
    
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

async def handle_start_new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.delete_message()
    except Exception:
        pass

    await show_exam_list(update, context)

async def handle_exam_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_membership_and_prompt(update, context):
        return

    exam_num = int(query.data.split('_')[2])
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
        await query.message.reply_text(f"{RLM}❌ سوالات مربوط به آزمون {persian_exam_num} یافت نشد.")
        return

    if 'timer_task' in context.user_data and context.user_data['timer_task']:
        try:
            context.user_data['timer_task'].cancel()
        except Exception:
            pass

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

    try:
        await query.delete_message()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{RLM}🚗 **آزمون شماره {persian_exam_num} شروع شد.**\n{RLM}⏱ زمان آزمون: **{to_persian_num(20)} دقیقه**\n{RLM}تعداد سوالات: {to_persian_num(len(exam_questions))}\n{RLM}موفق باشید!",
        parse_mode='Markdown'
    )
    await send_next_question(update, context)

async def exam_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await asyncio.sleep(EXAM_TIMEOUT_SECONDS)
    exam = context.user_data.get('exam')
    if exam and exam.get('active'):
        await context.bot.send_message(chat_id=chat_id, text=f"{RLM}⏰ **زمان {to_persian_num(20)} دقیقه‌ای آزمون به پایان رسید!**", parse_mode='Markdown')
        await finish_exam_by_chat_id(context, chat_id)

# ---------------------------------------------------------
# ارسال سوالات
# ---------------------------------------------------------
async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam = context.user_data.get('exam')
    if not exam or not exam.get('active'):
        return

    idx = exam['current_index']
    total_q = len(exam['questions'])

    if idx >= total_q:
        await finish_exam(update, context)
        return

    q = exam['questions'][idx]
    q_text_content = clean_text(q.get('question', f"سوال شماره {to_persian_num(idx + 1)}"))
    options = q.get('options', [])
    
    exam_num = exam['exam_num']
    q_num = idx + 1

    q_img_path = await find_question_image(exam_num, q_num)
    opt_img_paths = await find_option_images(exam_num, q_num)

    selected_opt = exam['user_answers'].get(idx)
    selected_str = f"\n\n{RLM}📌 **پاسخ انتخابی شما:** گزینه {to_persian_num(selected_opt)}" if selected_opt else ""

    q_text = f"{RLM}❓ **سوال {to_persian_num(idx + 1)} از {to_persian_num(total_q)}:**\n\n{RLM}{q_text_content}"

    if not opt_img_paths:
        formatted_options = []
        for i, opt in enumerate(options):
            cleaned_opt = clean_option_text(opt)
            if cleaned_opt:
                formatted_options.append(f"{RLM}{to_persian_num(i+1)}. {cleaned_opt}")
        if formatted_options:
            q_text += "\n\n" + "\n".join(formatted_options)
    
    q_text += selected_str

    keyboard = [
        [
            InlineKeyboardButton(f"گزینه {to_persian_num(1)}", callback_data="ans_1"),
            InlineKeyboardButton(f"گزینه {to_persian_num(2)}", callback_data="ans_2"),
        ],
        [
            InlineKeyboardButton(f"گزینه {to_persian_num(3)}", callback_data="ans_3"),
            InlineKeyboardButton(f"گزینه {to_persian_num(4)}", callback_data="ans_4"),
        ]
    ]

    nav_row = []
    if idx > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data="nav_prev"))
    if idx < total_q - 1:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data="nav_next"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🏁 پایان آزمون و مشاهده نتیجه", callback_data="finish_exam_now")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat_id

    if opt_img_paths:
        grid_bytes = create_2x2_grid(*opt_img_paths)
        await context.bot.send_photo(chat_id=chat_id, photo=grid_bytes, caption=q_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif q_img_path:
        with open(q_img_path, 'rb') as photo_file:
            await context.bot.send_photo(chat_id=chat_id, photo=photo_file, caption=q_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=chat_id, text=q_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_answer_and_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_membership_and_prompt(update, context):
        return

    data = query.data
    exam = context.user_data.get('exam')
    if not exam or not exam.get('active'):
        return

    if data == "finish_exam_now":
        await finish_exam(update, context)
        return

    if data == "nav_prev":
        if exam['current_index'] > 0:
            exam['current_index'] -= 1
    elif data == "nav_next":
        if exam['current_index'] < len(exam['questions']) - 1:
            exam['current_index'] += 1
    elif data.startswith("ans_"):
        selected_option = int(data.split('_')[1])
        idx = exam['current_index']
        exam['user_answers'][idx] = selected_option
        exam['current_index'] += 1

    try:
        await query.delete_message()
    except Exception:
        pass

    await send_next_question(update, context)

# ---------------------------------------------------------
# کارنامه
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
        try:
            context.user_data['timer_task'].cancel()
        except Exception:
            pass

    questions = exam['questions']
    user_answers = exam['user_answers']

    correct_count = 0
    wrong_count = 0
    unanswered_count = 0

    grid_buttons = []
    row = []

    for idx, q in enumerate(questions):
        try:
            correct_opt = int(q.get('correct_option', 1))
        except Exception:
            correct_opt = 1
            
        user_opt = user_answers.get(idx)
        persian_q_num = to_persian_num(idx + 1)

        if user_opt is None:
            unanswered_count += 1
            btn_text = f"⬜️ {persian_q_num}"
        elif user_opt == correct_opt:
            correct_count += 1
            btn_text = f"🟩 {persian_q_num}"
        else:
            wrong_count += 1
            btn_text = f"🟥 {persian_q_num}"

        row.append(InlineKeyboardButton(btn_text, callback_data=f"review_q_{idx}"))
        if len(row) == 5:
            grid_buttons.append(row)
            row = []

    if row:
        grid_buttons.append(row)

    # دکمه شروع آزمون جدید
    grid_buttons.append([InlineKeyboardButton("🔄 شروع آزمون جدید", callback_data="start_new_exam_action")])

    total_q = len(questions)
    passed = correct_count >= PASSING_SCORE
    
    update_user_stats(chat_id, passed)

    status_icon = "🎉" if passed else "❌"
    status_text = "قبول شدید" if passed else "مردود شدید"

    report_card = (
        f"{RLM}📝 **کارنامه آزمون شماره {to_persian_num(exam['exam_num'])}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{RLM}نتیجه آزمون: **{status_text}** {status_icon}\n\n"
        f"{RLM}✅ پاسخ‌های درست: {to_persian_num(correct_count)}\n"
        f"{RLM}❌ پاسخ‌های نادرست: {to_persian_num(wrong_count)}\n"
        f"{RLM}⚪️ بدون پاسخ: {to_persian_num(unanswered_count)}\n"
        f"{RLM}📊 کل سوالات: {to_persian_num(total_q)}\n"
        f"{RLM}🎯 حد نصاب قبولی: {to_persian_num(PASSING_SCORE)} پاسخ درست\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{RLM}👇 **بررسی سوالات:** برای مشاهده جزئیات هر سوال کلیک کنید:"
    )

    reply_markup = InlineKeyboardMarkup(grid_buttons)
    await context.bot.send_message(
        chat_id=chat_id,
        text=report_card,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# ---------------------------------------------------------
# مرور سوالات
# ---------------------------------------------------------
async def handle_review_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_membership_and_prompt(update, context):
        return

    exam = context.user_data.get('exam')
    if not exam:
        await query.message.reply_text(f"{RLM}اطلاعات آزمون یافت نشد.")
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

    q_text_content = clean_text(q.get('question', f"سوال شماره {to_persian_num(q_idx + 1)}"))
    options = q.get('options', [])
    
    try:
        correct_opt = int(q.get('correct_option', 1))
    except Exception:
        correct_opt = 1
        
    user_opt = exam['user_answers'].get(q_idx)

    msg_text = f"{RLM}🔍 **مرور سوال شماره {to_persian_num(q_idx + 1)} از {to_persian_num(total_q)}:**\n\n{RLM}{q_text_content}\n\n"

    exam_num = exam['exam_num']
    q_num = q_idx + 1

    opt_img_paths = await find_option_images(exam_num, q_num)

    if not opt_img_paths:
        for i, opt in enumerate(options):
            opt_num = i + 1
            opt_str = clean_option_text(opt)
            persian_opt_num = to_persian_num(opt_num)
            
            if opt_num == correct_opt and opt_num == user_opt:
                msg_text += f"{RLM}🟢 {persian_opt_num}. {opt_str} (پاسخ درست شما)\n"
            elif opt_num == correct_opt:
                msg_text += f"{RLM}🟢 {persian_opt_num}. {opt_str} (پاسخ صحیح)\n"
            elif opt_num == user_opt:
                msg_text += f"{RLM}🔴 {persian_opt_num}. {opt_str} (انتخاب اشتباه شما)\n"
            else:
                msg_text += f"{RLM}⚪️ {persian_opt_num}. {opt_str}\n"
    else:
        if user_opt is None:
            msg_text += f"{RLM}⚪️ شما به این سوال پاسخ نداده‌اید.\n{RLM}🟢 پاسخ صحیح: گزینه {to_persian_num(correct_opt)}"
        elif user_opt == correct_opt:
            msg_text += f"{RLM}🟢 پاسخ شما (گزینه {to_persian_num(user_opt)}) درست بود."
        else:
            msg_text += f"{RLM}🔴 پاسخ شما: گزینه {to_persian_num(user_opt)} (نادرست)\n{RLM}🟢 پاسخ صحیح: گزینه {to_persian_num(correct_opt)}"

    nav_keyboard = []
    nav_row = []
    if q_idx > 0:
        nav_row.append(InlineKeyboardButton("◀️ سوال قبلی", callback_data=f"review_q_{q_idx - 1}"))
    if q_idx < total_q - 1:
        nav_row.append(InlineKeyboardButton("سوال بعدی ▶️", callback_data=f"review_q_{q_idx + 1}"))
    if nav_row:
        nav_keyboard.append(nav_row)

    reply_markup = InlineKeyboardMarkup(nav_keyboard) if nav_keyboard else None

    q_img_path = await find_question_image(exam_num, q_num)

    sent_msg = None
    if opt_img_paths:
        grid_bytes = create_2x2_grid(*opt_img_paths)
        sent_msg = await context.bot.send_photo(chat_id=chat_id, photo=grid_bytes, caption=msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif q_img_path:
        with open(q_img_path, 'rb') as photo_file:
            sent_msg = await context.bot.send_photo(chat_id=chat_id, photo=photo_file, caption=msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        sent_msg = await context.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=reply_markup, parse_mode='Markdown')

    if sent_msg:
        exam['last_review_msg_id'] = sent_msg.message_id

# ---------------------------------------------------------
# اجرای اصلی برنامه و لایه‌بندی درست هندلرها
# ---------------------------------------------------------
def main():
    if not TOKEN:
        raise ValueError("متغیر TOKEN در Environment Variables تعریف نشده است!")

    if flask_available:
        try:
            threading.Thread(target=run_flask, daemon=True).start()
        except Exception as e:
            print(f"Flask start warning: {e}")

    app = ApplicationBuilder().token(TOKEN).build()

    # ۱. دستور start
    app.add_handler(CommandHandler("start", start_command))

    # ۲. هندلرهای عمومی Callback
    app.add_handler(CallbackQueryHandler(handle_check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(handle_start_new_exam, pattern="^start_new_exam_action$"))

    # ۳. هندلر دکمه‌های شیشه‌ای مربوط به آزمون و سوالات
    app.add_handler(CallbackQueryHandler(handle_exam_selection, pattern="^select_exam_"))
    app.add_handler(CallbackQueryHandler(handle_review_question, pattern="^review_q_"))
    app.add_handler(CallbackQueryHandler(handle_answer_and_nav, pattern="^(ans_|nav_|finish_exam_now)"))

    # ۴. هندلر پیام‌های متنی کیبورد اصلی
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is up and running successfully...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
