import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CommandHandler,
    CallbackQueryHandler, ContextTypes
)
from datetime import datetime
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import traceback

# Load .env
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# --- SHEET SETUP ---
def log_meal(timestamp, meal_description, calories):
    creds = get_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1C8ti41s9U0l9AybBAxgK_2Qa-aRqHihEBGusAt9d01M").worksheet("data_log")
    sheet.append_row([timestamp, meal_description, calories, "", ""])

def log_workout(timestamp, description, calories):
    creds = get_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1C8ti41s9U0l9AybBAxgK_2Qa-aRqHihEBGusAt9d01M").worksheet("data_log")
    sheet.append_row([timestamp, "", "", description, calories])

def get_creds():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    return ServiceAccountCredentials.from_json_keyfile_name("fitness-tracker-454904-3adade3d03e1.json", scope)

# --- GEMINI CALORIE ANALYSIS ---
def get_food_analysis_from_image(image_path):
    model = genai.GenerativeModel("gemini-1.5-flash")

    with open(image_path, "rb") as img:
        image_bytes = img.read()

    prompt = (
        "You are a calorie estimation assistant. The user has sent a photo of their meal. "
        "Look at the image and estimate the total calories and the name of each item if possible. "
        "Be specific. Reply with:\nMeal: [description]\nEstimated Calories: [number] kcal\nBreakdown:"
    )

    try:
        response = model.generate_content([
            prompt,
            {
                "mime_type": "image/jpeg",
                "data": image_bytes
            }
        ])
        return response.text
    except Exception as e:
        return f"❌ Gemini API Error: {e}"

# --- PHOTO HANDLER ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    file_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    await file.download_to_drive(file_path)
    await update.message.reply_text("📸 Got your meal photo!\nAnalyzing it now...")

    calorie_report = get_food_analysis_from_image(file_path)
    await update.message.reply_text(f"🧠 Gemini says:\n\n{calorie_report}")

    # Parse and log
    lines = calorie_report.splitlines()
    meal_line = lines[0] if lines else "Unknown meal"
    calories_line = next((line for line in lines if "Estimated Calories" in line), None)

    if calories_line:
        try:
            calories = int(''.join(filter(str.isdigit, calories_line)))
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_meal(timestamp, meal_line.replace("Meal: ", ""), calories)
            await update.message.reply_text("📊 Logged to your sheet!")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error logging:\n{traceback.format_exc()}")
    else:
        await update.message.reply_text("⚠️ Couldn't find calorie info.")

    os.remove(file_path)
    await update.message.reply_text("✅ All done!")

# --- BUTTON RESPONSE TO "hi" ---
async def handle_hi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Log Workout", callback_data="log_workout")],
        [InlineKeyboardButton("📊 How is your diet going?", callback_data="diet_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Hey! What do you want to do?", reply_markup=reply_markup)

# --- BUTTON CLICK HANDLER ---
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "log_workout":
        context.user_data["awaiting_workout"] = True
        await query.message.reply_text("🏋️ What did you do today and how many calories did it burn?\n(e.g. 60 mins gym, 420 kcal)")
    elif query.data == "diet_status":
        await query.message.reply_text("📉 Diet summary coming soon!")

# --- HANDLE TEXT REPLY AFTER "log workout" ---
async def handle_workout_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_workout"):
        text = update.message.text
        calories = 0
        try:
            calories = int(''.join(filter(str.isdigit, text)))
        except:
            pass

        description = text.replace(str(calories), "").replace("kcal", "").strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_workout(timestamp, description, calories)
        await update.message.reply_text(f"✅ Logged workout: {description} | 🔥 {calories} kcal")
        context.user_data["awaiting_workout"] = False

# --- BOT ENTRY ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^hi$"), handle_hi))
    app.add_handler(CallbackQueryHandler(handle_button_click))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_workout_entry))

    print("🤖 Bot is running... Send a photo or say hi")
    app.run_polling()
