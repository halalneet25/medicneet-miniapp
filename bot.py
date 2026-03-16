"""
MedicNEET Biology Doubt Bot + /start handler + Reminder callbacks
"""
import os
import logging
import sqlite3
import anthropic
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BOT_ID = 8574043659
DB_PATH = "/home/opc/medicneet-miniapp/medicneet.db"
API_BASE_URL = os.environ.get("API_BASE_URL", "https://quiz.medicneet.com")

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
    keyboard = [[InlineKeyboardButton("\U0001f9ec Play MedicNEET Quiz", web_app=WebAppInfo(url="https://quiz.medicneet.com"))],
                [InlineKeyboardButton("\U0001f4f1 Get MedicNEET App", url="https://play.google.com/store/apps/details?id=com.halalfire.medicneet")]]
    await update.message.reply_text(
        "Welcome to MedicNEET! \U0001f9ec\n\n"
        "\U0001f3ae Play live NEET Biology quiz every night at 7 PM\n"
        "\U0001f4b0 Win cash prizes for correct answers\n"
        "\U0001f4da Practice with 12,771 NEET-style questions\n\n"
        "Tap below to start!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = str(query.from_user.id)

    if data.startswith("remind_play_"):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE reminder_logs SET clicked_at = datetime('now') WHERE user_id = ? AND clicked_at IS NULL", (user_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to track click: {e}")

        keyboard = [[InlineKeyboardButton("\U0001f9ec Open Quiz", url="https://t.me/Winners_neetbot/Medicneet")]]
        await query.edit_message_text(
            text=query.message.text + "\n\n\u2705 See you at 7 PM! Tap below to open \U0001f447",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("remind_stats_"):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT COUNT(DISTINCT round_id) as rounds FROM attempts WHERE user_id = ?", (user_id,))
            rounds = c.fetchone()["rounds"]
            c.execute("SELECT COUNT(*) as wins FROM attempts WHERE user_id = ? AND is_correct = 1", (user_id,))
            wins = c.fetchone()["wins"]
            c.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            balance = row["balance"] if row else 0
            c.execute("SELECT MIN(time_ms) as best FROM attempts WHERE user_id = ? AND is_correct = 1", (user_id,))
            best_row = c.fetchone()
            best_time = f"{best_row['best']/1000:.1f}s" if best_row and best_row["best"] else "N/A"
            c.execute("SELECT COUNT(DISTINCT user_id) as total FROM attempts")
            total_players = c.fetchone()["total"]
            c.execute("SELECT COUNT(DISTINCT user_id) as behind FROM (SELECT user_id, COUNT(*) as w FROM attempts WHERE is_correct=1 GROUP BY user_id HAVING w < ?)", (wins,))
            behind = c.fetchone()["behind"]
            percentile = int((behind / total_players) * 100) if total_players > 0 else 0
            conn.close()
            win_rate = f"{(wins/rounds*100):.0f}%" if rounds > 0 else "0%"
            wins_to_50 = max(0, (50 - balance) // 5)
            stats_text = f"\U0001f4ca Your MedicNEET Stats\n\n\U0001f3af Rounds: {rounds}\n\U0001f3c6 Wins: {wins} ({win_rate})\n\u26a1 Best time: {best_time}\n\U0001f4b0 Balance: \u20b9{balance}\n\U0001f4c8 Better than {percentile}% of players\n"
            if wins_to_50 > 0:
                stats_text += f"\n\U0001f3af {wins_to_50} more wins to \u20b950 withdrawal!"
            else:
                stats_text += f"\n\u2705 You can withdraw \u20b950+ now!"
            keyboard = [[InlineKeyboardButton("\U0001f3ae Play Tonight", url="https://t.me/Winners_neetbot/Medicneet")]]
            await query.edit_message_text(text=stats_text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Failed to show stats: {e}")
            await query.edit_message_text(text="Something went wrong. Try opening the quiz directly!")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full platform stats for the past 7 days"""
    await update.message.reply_text("\u23f3 Fetching 7-day stats...")
    try:
        async with httpx.AsyncClient(timeout=15) as client_http:
            resp = await client_http.get(f"{API_BASE_URL}/api/platform-stats", params={"days": 7})
            resp.raise_for_status()
            s = resp.json()

        fastest = s.get("fastest_win")
        fastest_text = f"{fastest['name']} ({fastest['time_ms']/1000:.1f}s)" if fastest else "N/A"

        top_earners_text = ""
        for i, e in enumerate(s.get("top_earners", []), 1):
            top_earners_text += f"  {i}. {e['name']} — \u20b9{e['earned']}\n"
        if not top_earners_text:
            top_earners_text = "  No earnings yet\n"

        msg = (
            f"\U0001f4ca MedicNEET — 7 Day Stats\n"
            f"{'─' * 28}\n\n"
            f"\U0001f3ae QUIZ ACTIVITY\n"
            f"  Rounds played: {s['rounds']}\n"
            f"  Total attempts: {s['total_attempts']}\n"
            f"  Active players: {s['active_players']}\n"
            f"  Avg per round: {s['avg_attempts_per_round']}\n"
            f"  Winners (4/4): {s['total_wins']} ({s['unique_winners']} unique)\n"
            f"  Fastest win: {fastest_text}\n\n"
            f"\U0001f4b0 EARNINGS & WITHDRAWALS\n"
            f"  Cash distributed: \u20b9{s['cash_distributed']}\n"
            f"  Withdrawals: {s['withdrawals']['count']} (\u20b9{s['withdrawals']['amount']})\n\n"
            f"\u2694\ufe0f CHALLENGES\n"
            f"  Created: {s['challenges']['total']}\n"
            f"  Completed: {s['challenges']['completed']}\n\n"
            f"\U0001f4c8 GROWTH\n"
            f"  New signups: {s['new_signups']}\n"
            f"  Referrals: {s['new_referrals']}\n"
            f"  Email signups: {s['new_emails']}\n"
            f"  App clicks: {s['app_clicks']}\n\n"
            f"\U0001f4da ENGAGEMENT\n"
            f"  Study events: {s['study_events']}\n"
            f"  Disqualifications: {s['disqualifications']}\n\n"
            f"\U0001f3c6 TOP EARNERS (7 days)\n"
            f"{top_earners_text}\n"
            f"\U0001f30d ALL TIME\n"
            f"  Total users: {s['alltime_users']}\n"
            f"  Total earned: \u20b9{s['alltime_earned']}\n"
        )

        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Stats command failed: {e}")
        await update.message.reply_text(f"\u274c Failed to fetch stats: {e}")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg = update.message
    if msg.from_user and msg.from_user.id == BOT_ID:
        return
    if msg.from_user and msg.from_user.is_bot:
        return
    if getattr(msg, 'forward_origin', None) or getattr(msg, 'forward_from', None) or getattr(msg, 'forward_from_chat', None):
        return
    text = msg.text.strip()
    if len(text) < 8 or text.startswith('/'):
        return
    text_lower = text.lower()
    words = set(text_lower.split())
    if words.issubset(SKIP_WORDS) or (len(words) <= 2 and words & SKIP_WORDS):
        return
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
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(handle_reminder_callback, pattern=r"^remind_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
