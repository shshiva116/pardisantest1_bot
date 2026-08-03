code = '''import logging
import json
import time
import os
from io import BytesIO
from PIL import Image, ImageDraw
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = '8869494146:AAHkajzHX-cjX_hLvtRaNRD91XeuAm7KaNg'
JSON_PATH = '/content/drive/MyDrive/DrivingBot/questions.json'
STATS_PATH = '/content/drive/MyDrive/DrivingBot/user_stats.json'
IMAGES_DIR = '/content/drive/MyDrive/DrivingBot/images/'

logging.basicConfig(level=logging.INFO)

USER_EXAMS = {}
RTL_MARK = "\\u200f"

def load_all_stats():
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_user_stat(user_id, is_passed):
    stats = load_all_stats()
    str_uid = str(user_id)
    
    if str_uid not in stats:
        stats[str_uid] = {'total': 0, 'passed': 0, 'failed': 0}
        
    stats[str_uid]['total'] += 1
    if is_passed:
        stats[str_uid]['passed'] += 1
    else:
        stats[str_uid]['failed'] += 1
        
    try:
        with open(STATS_PATH, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error saving stats: {e}")

def get_user_stat(user_id):
    stats = load_all_stats()
    return stats.get(str(user_id), {'total': 0, 'passed': 0, 'failed': 0})

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 شروع آزمون آیین‌نامه")],
        [KeyboardButton("📊 مشاهده کارنامه و پیشرفت")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def load_questions():
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_question_image(exam_id, q_idx_1based, custom_img_name=None):
    if custom_img_name and isinstance(custom_img_name, str):
        c_name = custom_img_name.strip()
        if c_name:
            if not c_name.lower().endswith('.jpg'):
                c_name += '.jpg'
            full_path = os.path.join(IMAGES_DIR, c_name)
            if os.path.exists(full_path):
                return full_path

    standard_name = f"e{exam_id}_q{q_idx_1based}.jpg"
    standard_path = os.path.join(IMAGES_DIR, standard_name)
    if os.path.exists(standard_path):
        return standard_path

    return None

def draw_huge_digit(draw, digit, cx, cy):
    """رسم اعداد ۱ تا ۴ با ضخامت و ابعاد بسیار بزرگ بدون نیاز به فایل فونت"""
    w, h = 40, 60
    left, top = cx - w//2, cy - h//2
    right, bottom = cx + w//2, cy + h//2
    color = (0, 0, 0)
    thick = 12

    if digit == "1":
        draw.line([(cx, top), (cx, bottom)], fill=color, width=thick)
        draw.line([(cx - 15, top + 15), (cx, top)], fill=color, width=thick)
        draw.line([(cx - 20, bottom), (cx + 20, bottom)], fill=color, width=thick)
    elif digit == "2":
        draw.line([(left, top), (right, top)], fill=color, width=thick)
        draw.line([(right, top), (right, top + 25)], fill=color, width=thick)
        draw.line([(right, top + 25), (left, bottom)], fill=color, width=thick)
        draw.line([(left, bottom), (right, bottom)], fill=color, width=thick)
    elif digit == "3":
        draw.line([(left, top), (right, top)], fill=color, width=thick)
        draw.line([(right, top), (right, cy)], fill=color, width=thick)
        draw.line([(left + 5, cy), (right, cy)], fill=color, width=thick)
        draw.line([(right, cy), (right, bottom)], fill=color, width=thick)
        draw.line([(left, bottom), (right, bottom)], fill=color, width=thick)
    elif digit == "4":
        draw.line([(left, top), (left, cy)], fill=color, width=thick)
        draw.line([(left, cy), (right, cy)], fill=color, width=thick)
        draw.line([(right - 5, top), (right - 5, bottom)], fill=color, width=thick)

def create_options_grid(exam_id, q_idx_1based):
    opt_paths = []
    for opt_num in range(1, 5):
        opt_path = os.path.join(IMAGES_DIR, f"e{exam_id}_q{q_idx_1based}_opt{opt_num}.jpg")
        if os.path.exists(opt_path):
            opt_paths.append(opt_path)
        else:
            return None

    try:
        images = [Image.open(p) for p in opt_paths]
        img_w, img_h = 320, 320
        resized_imgs = [img.resize((img_w, img_h)) for img in images]

        label_area_height = 100
        grid_width = (img_w * 2) + 60
        grid_height = (img_h * 2) + (label_area_height * 2) + 60
        
        grid_img = Image.new('RGB', (grid_width, grid_height), color=(255, 255, 255))
        draw = ImageDraw.Draw(grid_img)

        positions = [
            (20, 20),
            (img_w + 40, 20),
            (20, img_h + label_area_height + 40),
            (img_w + 40, img_h + label_area_height + 40)
        ]

        labels = ["1", "2", "3", "4"]

        for idx, r_img in enumerate(resized_imgs):
            x, y = positions[idx]
            grid_img.paste(r_img, (x, y))

            cx = x + (img_w // 2)
            cy = y + img_h + (label_area_height // 2)

            # رسم عدد فوق‌العاده بزرگ و پررنگ
            draw_huge_digit(draw, labels[idx], cx, cy)

        bio = BytesIO()
        bio.name = f"e{exam_id}_q{q_idx_1based}_opts.jpg"
        grid_img.save(bio, 'JPEG', quality=95)
        bio.seek(0)
        return bio
    except Exception as e:
        logging.error(f"Error creating options grid: {e}")
        return None

async def send_or_edit_with_photo(update_or_query, text, reply_markup, photo_obj=None):
    formatted_text = RTL_MARK + text
    
    if isinstance(update_or_query, Update):
        msg = update_or_query.message
        if photo_obj:
            if isinstance(photo_obj, str) and os.path.exists(photo_obj):
                with open(photo_obj, 'rb') as f:
                    await msg.reply_photo(photo=f, caption=formatted_text, parse_mode='Markdown', reply_markup=reply_markup)
                return
            elif isinstance(photo_obj, BytesIO):
                await msg.reply_photo(photo=photo_obj, caption=formatted_text, parse_mode='Markdown', reply_markup=reply_markup)
                return
        await msg.reply_text(formatted_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        query = update_or_query
        msg = query.message
        try:
            await msg.delete()
        except Exception:
            pass

        if photo_obj:
            try:
                if isinstance(photo_obj, str) and os.path.exists(photo_obj):
                    with open(photo_obj, 'rb') as f:
                        await msg.reply_photo(photo=f, caption=formatted_text, parse_mode='Markdown', reply_markup=reply_markup)
                    return
                elif isinstance(photo_obj, BytesIO):
                    await msg.reply_photo(photo=photo_obj, caption=formatted_text, parse_mode='Markdown', reply_markup=reply_markup)
                    return
            except Exception as e:
                logging.error(f"Error sending photo: {e}")

        await msg.reply_text(formatted_text, parse_mode='Markdown', reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = load_questions()
    keyboard = []
    test_ids = sorted(questions.keys(), key=lambda x: int(x))
    row = []
    for t_id in test_ids:
        row.append(InlineKeyboardButton(f"📝 آزمون {t_id}", callback_data=f"start_exam_{t_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("📊 کارنامه و آمار کلی من", callback_data="stats")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = f"{RTL_MARK}👋 **به ربات آزمون آیین‌نامه خوش آمدید!**\\n\\n⏱ زمان هر آزمون: **۲۰ دقیقه**\\n❌ حد مجاز خطا: **حداکثر ۴ خطا**\\n\\nلطفاً یک آزمون را انتخاب کنید:"
    
    if update.message:
        await update.message.reply_text("منوی اصلی آماده است 👇", reply_markup=get_main_keyboard())
        await update.message.reply_text(msg_text, parse_mode='Markdown', reply_markup=reply_markup)
    elif update.callback_query:
        await send_or_edit_with_photo(update.callback_query, msg_text, reply_markup)

async def show_stats(update_or_query):
    if isinstance(update_or_query, Update):
        user_id = update_or_query.message.from_user.id
    else:
        user_id = update_or_query.from_user.id

    st = get_user_stat(user_id)
    
    text = (
        f"📊 **کارنامه و آمار کلی شما**\\n\\n"
        f"🔹 تعداد کل آزمون‌های انجام شده: **{st['total']}**\\n"
        f"✅ تعداد آزمون‌های قبول شده: **{st['passed']}**\\n"
        f"❌ تعداد آزمون‌های مردود شده: **{st['failed']}**\\n"
    )
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu")]]
    await send_or_edit_with_photo(update_or_query, text, InlineKeyboardMarkup(keyboard))

async def start_new_exam(query, exam_id):
    user_id = query.from_user.id
    questions = load_questions().get(str(exam_id), [])
    
    USER_EXAMS[user_id] = {
        'exam_id': exam_id,
        'start_time': time.time(),
        'duration': 20 * 60,
        'answers': {},
        'questions': questions
    }
    await render_question(query, user_id, 0)

async def render_question(query, user_id, q_idx):
    exam_data = USER_EXAMS.get(user_id)
    if not exam_data:
        await query.message.reply_text("❌ آزمون فعال یافت نشد.")
        return

    elapsed = time.time() - exam_data['start_time']
    remaining = exam_data['duration'] - elapsed
    
    if remaining <= 0:
        await finish_exam(query, user_id, reason="time_out")
        return

    mins, secs = divmod(int(remaining), 60)
    time_str = f"{mins:02d}:{secs:02d}"
    
    questions = exam_data['questions']
    q = questions[q_idx]
    user_ans = exam_data['answers'].get(q_idx)
    exam_id = exam_data['exam_id']
    q_num = q_idx + 1
    
    photo_obj = get_question_image(exam_id, q_num, q.get('image'))
    has_opt_grid = False
    if not photo_obj:
        photo_obj = create_options_grid(exam_id, q_num)
        if photo_obj:
            has_opt_grid = True

    text = f"⏱ **زمان باقی‌مانده:** `{time_str}`\\n"
    text += f"❓ **سوال {q_num} از {len(questions)} (آزمون {exam_id}):**\\n\\n{q['question']}\\n\\n"
    
    if not has_opt_grid:
        for idx, opt in enumerate(q['options']):
            opt_num = idx + 1
            icon = "🔹" if user_ans == opt_num else "⚪"
            text += f"{RTL_MARK}{icon} **گزینه {opt_num}:** {opt}\\n"

    keyboard = []
    opt_btns = []
    for idx in range(len(q['options'])):
        opt_num = idx + 1
        label = f"[{opt_num}] ✅" if user_ans == opt_num else f"گزینه {opt_num}"
        opt_btns.append(InlineKeyboardButton(label, callback_data=f"ans_{q_idx}_{opt_num}"))
    keyboard.append(opt_btns)

    nav_row = []
    if q_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"goto_{q_idx - 1}"))
    if q_idx < len(questions) - 1:
        nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"goto_{q_idx + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🏁 پایان / لغو آزمون و مشاهده نتیجه", callback_data="finish_exam")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_or_edit_with_photo(query, text, reply_markup, photo_obj)

async def finish_exam(query, user_id, reason="user_finish"):
    exam_data = USER_EXAMS.get(user_id)
    if not exam_data:
        return

    questions = exam_data['questions']
    answers = exam_data['answers']
    
    correct_cnt = 0
    wrong_cnt = 0
    unanswered_cnt = 0
    
    for i, q in enumerate(questions):
        corr = q.get('correct_option')
        user_ans = answers.get(i)
        
        if user_ans is None:
            unanswered_cnt += 1
        elif corr and int(user_ans) == int(corr):
            correct_cnt += 1
        else:
            wrong_cnt += 1

    is_passed = wrong_cnt <= 4
    
    save_user_stat(user_id, is_passed)

    status_text = "🎉 **قبول شدید!**" if is_passed else "❌ **مردود شدید!** (بیشتر از ۴ خطا)"
    
    if reason == "time_out":
        status_text = "⏰ **زمان آزمون تمام شد!**\\n" + status_text

    text = (
        f"📋 **کارنامه آزمون {exam_data['exam_id']}**\\n\\n"
        f"نتیجه: {status_text}\\n\\n"
        f"🟩 پاسخ‌های درست: **{correct_cnt}**\\n"
        f"🟥 پاسخ‌های اشتباه: **{wrong_cnt}**\\n"
        f"⬜ بدون پاسخ: **{unanswered_cnt}**\\n\\n"
        f"👇 جهت مرور هر سوال روی شماره آن در جدول کلیک کنید:"
    )

    keyboard = []
    current_row = []
    for i in range(len(questions)):
        status_icon = "⬜"
        if i in answers:
            corr = questions[i].get('correct_option')
            if corr and int(answers[i]) == int(corr):
                status_icon = "🟩"
            else:
                status_icon = "🟥"
                
        current_row.append(InlineKeyboardButton(f"{status_icon}{i+1}", callback_data=f"review_{i}"))
        if len(current_row) == 5:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)

    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu")])
    await send_or_edit_with_photo(query, text, InlineKeyboardMarkup(keyboard))

async def review_question(query, user_id, q_idx):
    exam_data = USER_EXAMS.get(user_id)
    if not exam_data:
        await query.message.reply_text("اطلاعات آزمون یافت نشد.")
        return

    questions = exam_data['questions']
    q = questions[q_idx]
    user_ans = exam_data['answers'].get(q_idx)
    corr_ans = q.get('correct_option')
    exam_id = exam_data['exam_id']
    q_num = q_idx + 1

    photo_obj = get_question_image(exam_id, q_num, q.get('image'))
    has_opt_grid = False
    if not photo_obj:
        photo_obj = create_options_grid(exam_id, q_num)
        if photo_obj:
            has_opt_grid = True

    text = f"🔍 **مرور سوال {q_num} از {len(questions)}:**\\n\\n{q['question']}\\n\\n"
    
    if not has_opt_grid:
        for idx, opt in enumerate(q['options']):
            opt_num = idx + 1
            if corr_ans and opt_num == int(corr_ans):
                text += f"{RTL_MARK}🟩 **گزینه {opt_num}: {opt}** ✅ (پاسخ درست)\\n"
            elif user_ans and opt_num == int(user_ans) and opt_num != int(corr_ans if corr_ans else 0):
                text += f"{RTL_MARK}🟥 **گزینه {opt_num}: {opt}** ❌ (انتخاب اشتباه شما)\\n"
            else:
                text += f"{RTL_MARK}⚪ گزینه {opt_num}: {opt}\\n"
    else:
        text += f"{RTL_MARK}✅ **پاسخ درست:** گزینه {corr_ans}\\n"
        if user_ans:
            text += f"{RTL_MARK}👈 **پاسخ شما:** گزینه {user_ans}\\n"
        else:
            text += f"{RTL_MARK}⚪ **پاسخ شما:** بدون پاسخ\\n"

    keyboard = [[InlineKeyboardButton("📋 بازگشت به کارنامه", callback_data="finish_exam")]]
    await send_or_edit_with_photo(query, text, InlineKeyboardMarkup(keyboard), photo_obj)

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "شروع آزمون" in text:
        await start(update, context)
    elif "مشاهده کارنامه" in text:
        await show_stats(update)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    data = query.data
    
    if data == "menu":
        await start(update, context)
    elif data == "stats":
        await show_stats(query)
    elif data.startswith("start_exam_"):
        await start_new_exam(query, data.split("_")[2])
    elif data.startswith("ans_"):
        _, q_idx, opt_num = data.split("_")
        q_idx = int(q_idx)
        if user_id in USER_EXAMS:
            USER_EXAMS[user_id]['answers'][q_idx] = int(opt_num)
            next_q = q_idx + 1 if q_idx + 1 < len(USER_EXAMS[user_id]['questions']) else q_idx
            await render_question(query, user_id, next_q)
    elif data.startswith("goto_"):
        await render_question(query, user_id, int(data.split("_")[1]))
    elif data == "finish_exam":
        await finish_exam(query, user_id, reason="user_finish")
    elif data.startswith("review_"):
        await review_question(query, user_id, int(data.split("_")[1]))

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("🤖 Bot is running...")
    app.run_polling()
'''

import os
os.makedirs('/content/drive/MyDrive/DrivingBot', exist_ok=True)
with open('/content/drive/MyDrive/DrivingBot/bot.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("✅ فایل bot.py آپدیت شد. اکنون اعداد به صورت ضخیم و بسیار درشت نمایش داده می‌شوند.")
