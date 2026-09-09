import os
import json
import base64
import tempfile
import asyncio
import subprocess

from openai import OpenAI
from pypdf import PdfReader
from faster_whisper import WhisperModel
import edge_tts

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# SETTINGS
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is missing")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY is missing")


TEXT_MODEL = "openrouter/free"
VISION_MODEL = "openrouter/free"


# =========================
# OPENROUTER
# =========================

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)


# =========================
# MEMORY
# =========================

MEMORY_FILE = "bot_memory.json"


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def get_history(user_id):
    if not os.path.exists(MEMORY_FILE):
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            memory = json.load(f)

        return memory.get(str(user_id), [])[-20:]

    except Exception:
        return []


def add_history(user_id, role, content):
    memory = {}

    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception:
            memory = {}

    user_key = str(user_id)

    if user_key not in memory:
        memory[user_key] = []

    memory[user_key].append({
        "role": role,
        "content": content
    })

    memory[user_key] = memory[user_key][-20:]

    save_memory(memory)


# =========================
# PRACTICE MODE
# =========================

practice_mode = set()


# =========================
# LANGUAGE
# =========================

def detect_language(text):
    persian_chars = "اآبپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"

    if any(char in persian_chars for char in text):
        return "fa"

    return "en"


# =========================
# SYSTEM PROMPT
# =========================

SYSTEM_PROMPT = """
You are a helpful multilingual AI assistant.

You can communicate naturally in:
- Persian / Dari
- English

Always understand the user's language and answer in the same language unless
the user asks for another language.

Be friendly, clear, helpful and accurate.

The user may send:
- text
- images
- PDFs
- voice messages

For English learning, explain mistakes clearly and give better natural English.

Do not invent information.
"""


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
سلام! 👋🤖

من ربات هوش مصنوعی تو هستم.

می‌توانی برایم:
💬 پیام متنی بفرستی
🖼️ عکس بفرستی
📄 PDF بفرستی
🎤 پیام صوتی بفرستی

برای تمرین انگلیسی:
 /practice

برای پاک کردن حافظه گفتگو:
 /clear

برای خارج شدن از حالت تمرین:
 /stop
"""

    await update.message.reply_text(text)


# =========================
# CLEAR MEMORY
# =========================

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    memory = {}

    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception:
            memory = {}

    memory[user_id] = []

    save_memory(memory)

    await update.message.reply_text(
        "🧹 حافظه گفتگوی تو پاک شد."
    )


# =========================
# PRACTICE MODE
# =========================

async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    practice_mode.add(user_id)

    await update.message.reply_text(
        "📚 حالت تمرین انگلیسی فعال شد!\n\n"
        "یک جمله انگلیسی برایم بفرست تا:\n"
        "❌ اشتباهاتت را اصلاح کنم\n"
        "📚 دلیل اشتباه را توضیح بدهم\n"
        "⭐ شکل طبیعی‌تر جمله را بگویم\n"
        "💬 و سؤال بعدی را از تو بپرسم."
    )


# =========================
# STOP PRACTICE
# =========================

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    practice_mode.discard(user_id)

    await update.message.reply_text(
        "✅ حالت تمرین انگلیسی متوقف شد."
    )


# =========================
# TEXT TO VOICE
# =========================

async def text_to_voice(text, language):

    if language == "fa":
        voice = "fa-IR-DilaraNeural"
    else:
        voice = "en-US-JennyNeural"

    temp_mp3 = tempfile.NamedTemporaryFile(
        suffix=".mp3",
        delete=False
    )

    mp3_path = temp_mp3.name
    temp_mp3.close()

    await edge_tts.Communicate(
        text,
        voice
    ).save(mp3_path)

    return mp3_path


# =========================
# SEND VOICE
# =========================

async def send_voice(update, text, language):

    mp3_path = None
    ogg_path = None

    try:

        mp3_path = await text_to_voice(text, language)

        ogg_path = mp3_path.replace(
            ".mp3",
            ".ogg"
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                mp3_path,
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                ogg_path
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        with open(ogg_path, "rb") as audio:

            await update.message.reply_voice(
                voice=audio
            )

    except Exception as e:

        print("Voice error:", e)

    finally:

        for path in [mp3_path, ogg_path]:

            if path and os.path.exists(path):

                try:
                    os.remove(path)
                except Exception:
                    pass


# =========================
# NORMAL CHAT
# =========================

async def normal_chat(user_id, user_message):

    history = get_history(user_id)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": user_message
    })

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=TEXT_MODEL,
        messages=messages
    )

    answer = response.choices[0].message.content

    add_history(
        user_id,
        "user",
        user_message
    )

    add_history(
        user_id,
        "assistant",
        answer
    )

    return answer


# =========================
# ENGLISH PRACTICE
# =========================

async def practice_text(user_id, text):

    prompt = f"""
You are an English teacher.

The student wrote:

{text}

Answer using exactly these sections:

❌ Correction:
Correct the sentence.

📚 Explanation:
Explain the mistakes simply.

⭐ Better way:
Give a more natural English version.

💬 Next question:
Ask the student one simple question in English so they can continue practicing.

Keep the explanation understandable.
"""

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a friendly English teacher."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content


# =========================
# TEXT HANDLER
# =========================

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        if not update.message or not update.message.text:
            return

        text = update.message.text

        user_id = update.effective_user.id

        language = detect_language(text)

        await update.message.chat.send_action("typing")

        if user_id in practice_mode:

            answer = await practice_text(
                user_id,
                text
            )

        else:

            answer = await normal_chat(
                user_id,
                text
            )

        await update.message.reply_text(
            answer
        )

        # Voice reply
        await send_voice(
            update,
            answer,
            language
        )

    except Exception as e:

        print("Chat error:", e)

        await update.message.reply_text(
            "❌ یک خطا رخ داد. لطفاً دوباره امتحان کن."
        )


# =========================
# IMAGE ANALYSIS
# =========================

async def analyze_image(update: Update, context: ContextTypes.DEFAULT_TYPE):

    temp_path = None

    try:

        photo = update.message.photo[-1]

        file = await context.bot.get_file(
            photo.file_id
        )

        temp_file = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        )

        temp_path = temp_file.name
        temp_file.close()

        await file.download_to_drive(
            temp_path
        )

        with open(temp_path, "rb") as f:

            image_data = base64.b64encode(
                f.read()
            ).decode("utf-8")

        caption = update.message.caption or (
            "این تصویر را بررسی و توضیح بده."
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": caption
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url":
                                f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ]
        )

        answer = response.choices[0].message.content

        await update.message.reply_text(
            answer
        )

    except Exception as e:

        print("Image error:", e)

        await update.message.reply_text(
            "❌ نتوانستم عکس را بررسی کنم."
        )

    finally:

        if temp_path and os.path.exists(temp_path):

            try:
                os.remove(temp_path)
            except Exception:
                pass


# =========================
# WHISPER
# =========================

print("Loading Whisper model...")

whisper_model = WhisperModel(
    "tiny",
    device="cpu",
    compute_type="int8"
)

print("Whisper loaded.")


# =========================
# TRANSCRIBE VOICE
# =========================

def transcribe_audio(audio_path):

    segments, info = whisper_model.transcribe(
        audio_path
    )

    text = " ".join(
        segment.text
        for segment in segments
    )

    return text.strip()


# =========================
# NORMAL VOICE
# =========================

async def normal_voice(
    update,
    text
):

    user_id = update.effective_user.id

    answer = await normal_chat(
        user_id,
        text
    )

    await update.message.reply_text(
        f"🎤 متن پیام صوتی:\n\n{text}\n\n"
        f"🤖 پاسخ:\n\n{answer}"
    )

    language = detect_language(answer)

    await send_voice(
        update,
        answer,
        language
    )


# =========================
# PRACTICE VOICE
# =========================

async def practice_voice(
    update,
    text
):

    user_id = update.effective_user.id

    answer = await practice_text(
        user_id,
        text
    )

    await update.message.reply_text(
        f"🎤 جمله تو:\n\n{text}\n\n{answer}"
    )

    await send_voice(
        update,
        answer,
        "en"
    )


# =========================
# VOICE HANDLER
# =========================

async def voice_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    temp_path = None

    try:

        voice = update.message.voice

        file = await context.bot.get_file(
            voice.file_id
        )

        temp_file = tempfile.NamedTemporaryFile(
            suffix=".ogg",
            delete=False
        )

        temp_path = temp_file.name
        temp_file.close()

        await file.download_to_drive(
            temp_path
        )

        await update.message.chat.send_action(
            "typing"
        )

        text = await asyncio.to_thread(
            transcribe_audio,
            temp_path
        )

        if not text:

            await update.message.reply_text(
                "❌ صدایی قابل تشخیص نبود."
            )

            return

        user_id = update.effective_user.id

        if user_id in practice_mode:

            await practice_voice(
                update,
                text
            )

        else:

            await normal_voice(
                update,
                text
            )

    except Exception as e:

        print("Voice error:", e)

        await update.message.reply_text(
            "❌ نتوانستم پیام صوتی را پردازش کنم."
        )

    finally:

        if temp_path and os.path.exists(temp_path):

            try:
                os.remove(temp_path)
            except Exception:
                pass


# =========================
# PDF HANDLER
# =========================

async def pdf_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    temp_path = None

    try:

        document = update.message.document

        file = await context.bot.get_file(
            document.file_id
        )

        temp_file = tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        )

        temp_path = temp_file.name
        temp_file.close()

        await file.download_to_drive(
            temp_path
        )

        await update.message.chat.send_action(
            "typing"
        )

        reader = PdfReader(temp_path)

        pages = []

        for page in reader.pages:

            page_text = page.extract_text()

            if page_text:
                pages.append(page_text)

        pdf_text = "\n".join(pages)

        pdf_text = pdf_text[:30000]

        if not pdf_text:

            await update.message.reply_text(
                "❌ نتوانستم متنی از این PDF استخراج کنم."
            )

            return

        prompt = f"""
Analyze this PDF and give a useful summary.

PDF text:

{pdf_text}
"""

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        answer = response.choices[0].message.content

        await update.message.reply_text(
            answer
        )

    except Exception as e:

        print("PDF error:", e)

        await update.message.reply_text(
            "❌ نتوانستم PDF را بررسی کنم."
        )

    finally:

        if temp_path and os.path.exists(temp_path):

            try:
                os.remove(temp_path)
            except Exception:
                pass


# =========================
# APPLICATION
# =========================

app = Application.builder().token(
    TELEGRAM_TOKEN
).build()


app.add_handler(
    CommandHandler("start", start)
)

app.add_handler(
    CommandHandler("clear", clear_memory)
)

app.add_handler(
    CommandHandler("practice", practice_command)
)

app.add_handler(
    CommandHandler("stop", stop_command)
)

app.add_handler(
    MessageHandler(
        filters.PHOTO,
        analyze_image
    )
)

app.add_handler(
    MessageHandler(
        filters.Document.PDF,
        pdf_handler
    )
)

app.add_handler(
    MessageHandler(
        filters.VOICE,
        voice_handler
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        chat_handler
    )
)


# =========================
# RUN
# =========================

print("================================")
print("🤖 AI BOT IS RUNNING")
print("================================")

app.run_polling()
