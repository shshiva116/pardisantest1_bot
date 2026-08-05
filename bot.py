async def handle_exam_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    exam_num = int(query.data.split('_')[2])
    persian_exam_num = to_persian_num(exam_num)
    questions_data = load_questions()

    if not questions_data:
        await query.message.reply_text("❌ فایل questions.json خوانده نشد یا خالی است.")
        return

    # بررسی تمامی حالت‌های ممکن برای نام کلید در فایل JSON
    possible_keys = [
        f"آزمون {exam_num}",
        f"آزمون {persian_exam_num}",
        f"آزمون شماره {exam_num}",
        f"آزمون شماره {persian_exam_num}",
        str(exam_num),
        str(persian_exam_num),
        f"exam_{exam_num}",
        f"exam{exam_num}"
    ]

    exam_questions = None
    for key in possible_keys:
        if key in questions_data:
            exam_questions = questions_data[key]
            break

    # اگر با هیچ کلیدی پیدا نشد، ۵ کلید اول فایل JSON را برای عیب‌یابی نمایش بده
    if not exam_questions:
        sample_keys = list(questions_data.keys())[:5]
        await query.message.reply_text(
            f"❌ آزمون شماره {exam_num} در فایل پیدا نشد!\n\n"
            f"🔍 **نمونه کلیدهای موجود در فایل JSON شما:**\n`{sample_keys}`\n\n"
            f"لطفاً ساختار نام‌گذاری فایل JSON را بررسی کنید.",
            parse_mode='Markdown'
        )
        return

    context.user_data['exam'] = {
        'exam_num': exam_num,
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
        text=f"🚗 **آزمون شماره {exam_num} شروع شد.**\nتعداد سوالات: {len(exam_questions)}\nموفق باشید!",
        parse_mode='Markdown'
    )
    await send_next_question(update, context)
