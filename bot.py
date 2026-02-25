"""
MedicNEET Biology Doubt Bot + /start handler
"""

import os
import logging
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BOT_ID = 8574043659

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SYSTEM_PROMPT = """You are MedicNEET Biology Expert Bot. Answer ONLY Biology/NEET related questions based strictly on NCERT textbooks (Class 11 and 12 Biology).

Rules:
- Keep answers concise (under 200 words)
- Always reference specific NCERT chapter and topic
- If the message is NOT a Biology question, return exactly: __SKIP__
- Use Hinglish naturally where appropriate
- Be accurate and exam-focused
- End every answer with:

12,771 NEET questions with NCERT references on MedicNEET App: https://play.google.com/store/apps/details?id=com.halalfire.medicneet"""

SKIP_WORDS = {'lol', 'haha', 'ok', 'okay', 'hi', 'hello', 'hey', 'bhai', 'yaar', 'scam', 
              'wallet', 'money', 'paisa', 'withdraw', 'payment', 'paid', 'free', 'prize',
              'nice', 'good', 'bad', 'thanks', 'thank', 'gm', 'gn', 'hmm', 'ohh', 'acha',
              'haan', 'nahi', 'ha', 'na', 'ji', 'wow', 'bruh', 'bro', 'sis', 'dude',
              'lmao', 'rofl', 'xd', 'gg', 'rip', 'f', 'w', 'l'}

QUESTION_WORDS = {'?', 'what', 'why', 'how', 'explain', 'define', 'difference', 'between',
                  'kya', 'kyun', 'kaise', 'batao', 'bata', 'samjhao', 'meaning', 'function',
                  'structure', 'which', 'where', 'when', 'describe', 'name', 'list', 'role',
                  'process', 'mechanism', 'diagram', 'example', 'type', 'types', 'classify',
                  'classification', 'compare', 'distinguish'}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🧬 Play MedicNEET Quiz", web_app=WebAppInfo(url="https://quiz.medicneet.com"))],
                [InlineKeyboardButton("📱 Get MedicNEET App", url="https://play.google.com/store/apps/details?id=com.halalfire.medicneet")]]
    await update.message.reply_text(
        "Welcome to MedicNEET! 🧬\n\n"
        "🎮 Play live NEET Biology quiz every night at 7 PM\n"
        "💰 Win cash prizes for correct answers\n"
        "📚 Practice with 12,771 NEET-style questions\n\n"
        "Tap below to start!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    msg = update.message
    
    # Skip bot's own messages
    if msg.from_user and msg.from_user.id == BOT_ID:
        return
    
    # Skip other bots
    if msg.from_user and msg.from_user.is_bot:
        return
    
    # Skip forwarded messages (prevents replying to nightly recap)
    if getattr(msg, 'forward_origin', None) or getattr(msg, 'forward_from', None) or getattr(msg, 'forward_from_chat', None):
        return
    
    text = msg.text.strip()
    
    # Skip short messages and commands
    if len(text) < 8 or text.startswith('/'):
        return
    
    # Skip casual chat
    text_lower = text.lower()
    words = set(text_lower.split())
    if words.issubset(SKIP_WORDS) or (len(words) <= 2 and words & SKIP_WORDS):
        return
    
    # Only trigger on question-like messages
    has_question_indicator = False
    if '?' in text:
        has_question_indicator = True
    else:
        for w in QUESTION_WORDS:
            if w in text_lower:
                has_question_indicator = True
                break
    
    if not has_question_indicator:
        return
    
    if not client:
        logger.warning("No Anthropic API key set")
        return
    
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        
        reply = response.content[0].text.strip()
        
        if '__SKIP__' in reply:
            return
        
        await msg.reply_text(reply, disable_web_page_preview=True)
        logger.info(f"Answered doubt from {msg.from_user.first_name}: {text[:50]}")
        
    except Exception as e:
        logger.error(f"Error answering doubt: {e}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
