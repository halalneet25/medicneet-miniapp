"""
MedicNEET Telegram Bot
Handles the channel button and webhook for the Mini App
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import BOT_TOKEN, TELEGRAM_CHANNEL_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Your Mini App URL (replace with your actual domain)
# ---------------------------------------------------------------------------
MINI_APP_URL = "https://YOUR_DOMAIN.com"  # Replace after deployment

# ---------------------------------------------------------------------------
# Bot Commands
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show the quiz button."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🧠 Play Quiz - Win ₹50!",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )],
        [InlineKeyboardButton(
            "📲 Download MedicNEET App",
            url="https://play.google.com/store/apps/details?id=YOUR_APP_ID"
        )]
    ])

    await update.message.reply_text(
        "🏆 <b>MedicNEET Cash Prize Quiz!</b>\n\n"
        "⚡ A new NEET Biology question every 4 hours\n"
        "💰 ₹50 for the fastest correct answer\n"
        "📸 Winners get featured in the channel!\n\n"
        "Tap below to play 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quiz command - direct link to mini app."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⚡ Open Quiz Now",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])

    await update.message.reply_text(
        "🚨 <b>Quiz is LIVE!</b>\n\n"
        "💰 ₹50 for the fastest correct answer!\n"
        "Tap below 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leaderboard command."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🏆 View Leaderboard",
            web_app=WebAppInfo(url=f"{MINI_APP_URL}#leaderboard")
        )]
    ])

    await update.message.reply_text(
        "🏆 <b>Leaderboard</b>\n\n"
        "See who's the fastest NEET solver!\n"
        "Tap below 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def post_quiz_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command: /postbutton
    Posts the quiz button to the channel.
    Only works if the bot is admin in the channel.
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🧠 Play Quiz - Win ₹50! 💰",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )],
        [InlineKeyboardButton(
            "📲 Download MedicNEET App",
            url="https://play.google.com/store/apps/details?id=YOUR_APP_ID"
        )]
    ])

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=(
                "🔥 <b>MedicNEET Cash Prize Quiz</b> 🔥\n\n"
                "⚡ New NEET Biology question every 4 hours\n"
                "💰 ₹50 cash for the FASTEST correct answer\n"
                "📸 Winners get featured!\n"
                "🏆 All-time leaderboard with prizes\n\n"
                "Think you know NEET Biology? Prove it 👇"
            ),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await update.message.reply_text("✅ Quiz button posted to channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def post_new_question_alert(context: ContextTypes.DEFAULT_TYPE):
    """
    Called by scheduler when a new question goes live.
    Posts an alert to the channel.
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⚡ Play Now - Win ₹50!",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=(
                "🚨 <b>NEW QUESTION LIVE!</b>\n\n"
                "💰 ₹50 for the fastest correct answer\n"
                "⏱ 4 hours to solve it\n\n"
                "👇 Open now!"
            ),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to post question alert: {e}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Start the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("postbutton", post_quiz_button))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
