"""
MedicNEET Biology Doubt Bot + /start handler + Reminder callbacks
"""
import os
import logging
import sqlite3
import anthropic
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BOT_ID = 8574043659
DB_PATH = "/home/opc/medicneet-miniapp/medicneet.db"
IST = timezone(timedelta(hours=5, minutes=30))

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SYSTEM_PROMPT = """You are MedicNEET Biology Expert Bot. Answer ONLY Biology/NEET related questions based strictly on NCERT textbooks (Class 11 and 12 Biology).

Rules:
- Keep answers concise (under 200 words)
- Always reference specific NCERT chapter and topic
- If the message is NOT a Biology question, return exactly: __SKIP__
- Use Hinglish naturally where appropriate
- Be accurate and exam-focused
- End every answer with:

12,771 NEET questions with NCERT references on MedicNEET App: https://play.google.com/store/apps/details?id=com.halalfire.medicneet
(88 of 90 Biology questions in the NEET 2026 paper traced back to this question bank.)"""

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
        "\U0001f4da Practice with 12,771 NEET-style questions\n"
        "\U0001f3af 88 of 90 NEET 2026 Biology questions trace back to our question bank\n\n"
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
    """Show full platform stats for the past 7 days — queries DB directly"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        cutoff = (datetime.now(IST) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        # Quiz activity
        c.execute("SELECT COUNT(*) as cnt FROM rounds WHERE started_at >= ?", (cutoff,))
        total_rounds = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as players FROM attempts WHERE attempted_at >= ?", (cutoff,))
        row = c.fetchone()
        total_attempts, active_players = row["cnt"], row["players"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as uniq FROM winners WHERE created_at >= ?", (cutoff,))
        row = c.fetchone()
        total_wins, unique_winners = row["cnt"], row["uniq"]

        avg_per_round = round(total_attempts / total_rounds, 1) if total_rounds > 0 else 0

        c.execute("SELECT user_name, time_ms FROM winners WHERE created_at >= ? AND time_ms IS NOT NULL ORDER BY time_ms ASC LIMIT 1", (cutoff,))
        fastest = c.fetchone()
        fastest_text = f"{fastest['user_name']} ({fastest['time_ms']/1000:.1f}s)" if fastest else "N/A"

        # Earnings & withdrawals
        c.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = 'win' AND created_at >= ?", (cutoff,))
        cash_distributed = c.fetchone()["total"]

        c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM withdrawal_requests WHERE created_at >= ?", (cutoff,))
        row = c.fetchone()
        wd_count, wd_amount = row["cnt"], row["total"]

        # Challenges
        c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE created_at >= ?", (cutoff,))
        challenges_total = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE status IN ('won', 'lost') AND completed_at >= ?", (cutoff,))
        challenges_done = c.fetchone()["cnt"]

        # Growth
        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE created_at >= ?", (cutoff,))
        new_signups = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM referrals WHERE created_at >= ?", (cutoff,))
        new_referrals = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM notify_emails WHERE created_at >= ?", (cutoff,))
        new_emails = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM app_clicks WHERE created_at >= ?", (cutoff,))
        app_clicks = c.fetchone()["cnt"]

        # Engagement
        c.execute("SELECT COUNT(*) as cnt FROM study_events WHERE created_at >= ?", (cutoff,))
        study_events = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM disqualifications WHERE created_at >= ?", (cutoff,))
        disqualifications = c.fetchone()["cnt"]

        # Top 5 earners in period
        c.execute("""
            SELECT t.user_id, w.user_name, SUM(t.amount) as earned
            FROM transactions t LEFT JOIN wallets w ON w.user_id = t.user_id
            WHERE t.type = 'win' AND t.created_at >= ?
            GROUP BY t.user_id ORDER BY earned DESC LIMIT 5
        """, (cutoff,))
        top_earners_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_earners_text += f"  {i}. {r['user_name'] or 'Unknown'} — \u20b9{r['earned']}\n"
        if not top_earners_text:
            top_earners_text = "  No earnings yet\n"

        # All time
        c.execute("SELECT COUNT(*) as cnt FROM wallets")
        alltime_users = c.fetchone()["cnt"]
        c.execute("SELECT COALESCE(SUM(total_earned), 0) as total FROM wallets")
        alltime_earned = c.fetchone()["total"]

        conn.close()

        msg = (
            f"\U0001f4ca MedicNEET — 7 Day Stats\n"
            f"{'─' * 28}\n\n"
            f"\U0001f3ae QUIZ ACTIVITY\n"
            f"  Rounds played: {total_rounds}\n"
            f"  Total attempts: {total_attempts}\n"
            f"  Active players: {active_players}\n"
            f"  Avg per round: {avg_per_round}\n"
            f"  Winners (4/4): {total_wins} ({unique_winners} unique)\n"
            f"  Fastest win: {fastest_text}\n\n"
            f"\U0001f4b0 EARNINGS & WITHDRAWALS\n"
            f"  Cash distributed: \u20b9{cash_distributed}\n"
            f"  Withdrawals: {wd_count} (\u20b9{wd_amount})\n\n"
            f"\u2694\ufe0f CHALLENGES\n"
            f"  Created: {challenges_total}\n"
            f"  Completed: {challenges_done}\n\n"
            f"\U0001f4c8 GROWTH\n"
            f"  New signups: {new_signups}\n"
            f"  Referrals: {new_referrals}\n"
            f"  Email signups: {new_emails}\n"
            f"  App clicks: {app_clicks}\n\n"
            f"\U0001f4da ENGAGEMENT\n"
            f"  Study events: {study_events}\n"
            f"  Disqualifications: {disqualifications}\n\n"
            f"\U0001f3c6 TOP EARNERS (7 days)\n"
            f"{top_earners_text}\n"
            f"\U0001f30d ALL TIME\n"
            f"  Total users: {alltime_users}\n"
            f"  Total earned: \u20b9{alltime_earned}\n"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Stats command failed: {e}")
        await update.message.reply_text(f"\u274c Failed to fetch stats: {e}")

async def statsmonth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show platform stats for the current month"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        now = datetime.now(IST)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        month_name = now.strftime("%B %Y")

        # Quiz activity
        c.execute("SELECT COUNT(*) as cnt FROM rounds WHERE started_at >= ?", (month_start,))
        total_rounds = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as players FROM attempts WHERE attempted_at >= ?", (month_start,))
        row = c.fetchone()
        total_attempts, active_players = row["cnt"], row["players"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as uniq FROM winners WHERE created_at >= ?", (month_start,))
        row = c.fetchone()
        total_wins, unique_winners = row["cnt"], row["uniq"]

        avg_per_round = round(total_attempts / total_rounds, 1) if total_rounds > 0 else 0

        c.execute("SELECT user_name, time_ms FROM winners WHERE created_at >= ? AND time_ms IS NOT NULL ORDER BY time_ms ASC LIMIT 1", (month_start,))
        fastest = c.fetchone()
        fastest_text = f"{fastest['user_name']} ({fastest['time_ms']/1000:.1f}s)" if fastest else "N/A"

        # Earnings & withdrawals
        c.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = 'win' AND created_at >= ?", (month_start,))
        cash_distributed = c.fetchone()["total"]

        c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM withdrawal_requests WHERE created_at >= ?", (month_start,))
        row = c.fetchone()
        wd_count, wd_amount = row["cnt"], row["total"]

        # Challenges
        c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE created_at >= ?", (month_start,))
        challenges_total = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE status IN ('won', 'lost') AND completed_at >= ?", (month_start,))
        challenges_done = c.fetchone()["cnt"]

        # Growth
        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE created_at >= ?", (month_start,))
        new_signups = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM referrals WHERE created_at >= ?", (month_start,))
        new_referrals = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM notify_emails WHERE created_at >= ?", (month_start,))
        new_emails = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM app_clicks WHERE created_at >= ?", (month_start,))
        app_clicks = c.fetchone()["cnt"]

        # MedicPoints this month
        c.execute("SELECT COUNT(*) as cnt FROM winners WHERE created_at >= ? AND winner_type IN ('capped_medic', 'medicpoints_eligible')", (month_start,))
        mp_rounds = c.fetchone()["cnt"]
        mp_points = mp_rounds * 20

        c.execute("SELECT COUNT(*) as cnt FROM medicpoints_claims WHERE created_at >= ? AND firebase_preloaded = 1 AND round_id != 0", (month_start,))
        mp_claimed = c.fetchone()["cnt"]

        # Top 5 earners this month
        c.execute("""
            SELECT t.user_id, w.user_name, SUM(t.amount) as earned
            FROM transactions t LEFT JOIN wallets w ON w.user_id = t.user_id
            WHERE t.type = 'win' AND t.created_at >= ?
            GROUP BY t.user_id ORDER BY earned DESC LIMIT 5
        """, (month_start,))
        top_earners_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_earners_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 \u20b9{r['earned']}\n"
        if not top_earners_text:
            top_earners_text = "  No earnings yet\n"

        # Top 5 MedicPoints earners this month
        c.execute("""
            SELECT w.user_name, COUNT(*) as wins
            FROM winners w
            WHERE w.created_at >= ? AND w.winner_type IN ('capped_medic', 'medicpoints_eligible')
            GROUP BY w.user_id ORDER BY wins DESC LIMIT 5
        """, (month_start,))
        top_mp_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_mp_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 {r['wins'] * 20} pts\n"
        if not top_mp_text:
            top_mp_text = "  No MedicPoints yet\n"

        conn.close()

        msg = (
            f"\U0001f4c5 MedicNEET \u2014 {month_name} Stats\n"
            f"{'─' * 28}\n\n"
            f"\U0001f3ae QUIZ ACTIVITY\n"
            f"  Rounds played: {total_rounds}\n"
            f"  Total attempts: {total_attempts}\n"
            f"  Active players: {active_players}\n"
            f"  Avg per round: {avg_per_round}\n"
            f"  Winners (4/4): {total_wins} ({unique_winners} unique)\n"
            f"  Fastest win: {fastest_text}\n\n"
            f"\U0001f4b0 EARNINGS & WITHDRAWALS\n"
            f"  Cash distributed: \u20b9{cash_distributed}\n"
            f"  Withdrawals: {wd_count} (\u20b9{wd_amount})\n\n"
            f"\U0001f3c5 MEDICPOINTS\n"
            f"  Points earned: {mp_points} ({mp_rounds} rounds)\n"
            f"  Synced to app: {mp_claimed * 20} ({mp_claimed} rounds)\n\n"
            f"\u2694\ufe0f CHALLENGES\n"
            f"  Created: {challenges_total}\n"
            f"  Completed: {challenges_done}\n\n"
            f"\U0001f4c8 GROWTH\n"
            f"  New signups: {new_signups}\n"
            f"  Referrals: {new_referrals}\n"
            f"  Email signups: {new_emails}\n"
            f"  App clicks: {app_clicks}\n\n"
            f"\U0001f3c6 TOP EARNERS ({month_name})\n"
            f"{top_earners_text}\n"
            f"\U0001f3c5 TOP MEDICPOINTS ({month_name})\n"
            f"{top_mp_text}"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Statsmonth command failed: {e}")
        await update.message.reply_text(f"\u274c Failed to fetch monthly stats: {e}")

async def statsoverall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all-time platform stats"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Quiz activity
        c.execute("SELECT COUNT(*) as cnt FROM rounds")
        total_rounds = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as players FROM attempts")
        row = c.fetchone()
        total_attempts, total_players = row["cnt"], row["players"]

        c.execute("SELECT COUNT(*) as cnt, COUNT(DISTINCT user_id) as uniq FROM winners")
        row = c.fetchone()
        total_wins, unique_winners = row["cnt"], row["uniq"]

        avg_per_round = round(total_attempts / total_rounds, 1) if total_rounds > 0 else 0
        win_rate = round(total_wins / total_attempts * 100, 1) if total_attempts > 0 else 0

        c.execute("SELECT user_name, time_ms FROM winners WHERE time_ms IS NOT NULL ORDER BY time_ms ASC LIMIT 1")
        fastest = c.fetchone()
        fastest_text = f"{fastest['user_name']} ({fastest['time_ms']/1000:.1f}s)" if fastest else "N/A"

        # Earnings
        c.execute("SELECT COALESCE(SUM(total_earned), 0) as total FROM wallets")
        total_earned = c.fetchone()["total"]

        c.execute("SELECT COALESCE(SUM(balance), 0) as total FROM wallets")
        total_pending = c.fetchone()["total"]

        c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM withdrawal_requests")
        row = c.fetchone()
        wd_count, wd_amount = row["cnt"], row["total"]

        # Users
        c.execute("SELECT COUNT(*) as cnt FROM wallets")
        total_users = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE balance >= 50")
        users_with_50 = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE withdrawal_count > 0")
        users_withdrawn = c.fetchone()["cnt"]

        # MedicPoints
        c.execute("SELECT COUNT(*) as cnt FROM winners WHERE winner_type IN ('capped_medic', 'medicpoints_eligible')")
        mp_rounds = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM medicpoints_claims WHERE firebase_preloaded = 1 AND round_id != 0")
        mp_claimed = c.fetchone()["cnt"]

        # Challenges
        c.execute("SELECT COUNT(*) as cnt FROM challenges")
        challenges_total = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE status IN ('won', 'lost')")
        challenges_done = c.fetchone()["cnt"]

        # Growth
        c.execute("SELECT COUNT(*) as cnt FROM referrals")
        total_referrals = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM notify_emails")
        total_emails = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM app_clicks")
        total_app_clicks = c.fetchone()["cnt"]

        # Top 10 all-time earners
        c.execute("""
            SELECT user_name, total_earned, balance, withdrawal_count
            FROM wallets ORDER BY total_earned DESC LIMIT 10
        """)
        top_earners_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            wd_tag = f" [{r['withdrawal_count']}x wd]" if r['withdrawal_count'] > 0 else ""
            top_earners_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 \u20b9{r['total_earned']} (bal: \u20b9{r['balance']}){wd_tag}\n"
        if not top_earners_text:
            top_earners_text = "  No earnings yet\n"

        # Top 5 MedicPoints all-time
        c.execute("""
            SELECT w.user_name, COUNT(*) as wins
            FROM winners w
            WHERE w.winner_type IN ('capped_medic', 'medicpoints_eligible')
            GROUP BY w.user_id ORDER BY wins DESC LIMIT 5
        """)
        top_mp_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_mp_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 {r['wins'] * 20} pts\n"
        if not top_mp_text:
            top_mp_text = "  No MedicPoints yet\n"

        # First and last round dates
        c.execute("SELECT MIN(started_at) as first, MAX(started_at) as last FROM rounds")
        dates = c.fetchone()
        first_round = dates["first"][:10] if dates["first"] else "N/A"
        last_round = dates["last"][:10] if dates["last"] else "N/A"

        conn.close()

        msg = (
            f"\U0001f30d MedicNEET \u2014 All-Time Stats\n"
            f"{'─' * 28}\n"
            f"  {first_round} \u2192 {last_round}\n\n"
            f"\U0001f3ae QUIZ ACTIVITY\n"
            f"  Rounds played: {total_rounds}\n"
            f"  Total attempts: {total_attempts}\n"
            f"  Total players: {total_players}\n"
            f"  Avg per round: {avg_per_round}\n"
            f"  Winners (4/4): {total_wins} ({unique_winners} unique)\n"
            f"  Win rate: {win_rate}%\n"
            f"  Fastest ever: {fastest_text}\n\n"
            f"\U0001f4b0 EARNINGS\n"
            f"  Total earned: \u20b9{total_earned}\n"
            f"  Pending balance: \u20b9{total_pending}\n"
            f"  Withdrawals: {wd_count} (\u20b9{wd_amount})\n\n"
            f"\U0001f465 USERS\n"
            f"  Total users: {total_users}\n"
            f"  Balance \u2265\u20b950: {users_with_50}\n"
            f"  Withdrawn at least once: {users_withdrawn}\n\n"
            f"\U0001f3c5 MEDICPOINTS\n"
            f"  Total earned: {mp_rounds * 20} ({mp_rounds} rounds)\n"
            f"  Synced to app: {mp_claimed * 20} ({mp_claimed} rounds)\n\n"
            f"\u2694\ufe0f CHALLENGES\n"
            f"  Created: {challenges_total}\n"
            f"  Completed: {challenges_done}\n\n"
            f"\U0001f4c8 GROWTH\n"
            f"  Referrals: {total_referrals}\n"
            f"  Email signups: {total_emails}\n"
            f"  App clicks: {total_app_clicks}\n\n"
            f"\U0001f3c6 TOP 10 EARNERS (All-Time)\n"
            f"{top_earners_text}\n"
            f"\U0001f3c5 TOP MEDICPOINTS (All-Time)\n"
            f"{top_mp_text}"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Statsoverall command failed: {e}")
        await update.message.reply_text(f"\u274c Failed to fetch overall stats: {e}")

async def statswithdrawal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed withdrawal task tracker — who did what, how many, how much"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Overall withdrawal summary
        c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM withdrawal_requests")
        row = c.fetchone()
        total_wd, total_wd_amount = row["cnt"], row["total"]

        c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM withdrawal_requests WHERE status = 'pending'")
        row = c.fetchone()
        pending_wd, pending_amount = row["cnt"], row["total"]

        c.execute("SELECT COUNT(*) as cnt FROM withdrawal_requests WHERE status = 'completed'")
        completed_wd = c.fetchone()["cnt"]

        # Users who have withdrawn
        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE withdrawal_count > 0")
        users_withdrawn = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE balance >= 50")
        users_eligible = c.fetchone()["cnt"]

        # V1 vs V2 breakdown
        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE withdrawal_count = 0 AND balance >= 50")
        v1_eligible = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM wallets WHERE withdrawal_count >= 1 AND balance >= 50")
        v2_eligible = c.fetchone()["cnt"]

        # Task completion stats (V1 click tasks)
        v1_tasks = ["install_app", "rate_app", "subscribe_yt", "follow_ig"]
        task_stats_text = ""
        for task_name in v1_tasks:
            c.execute("SELECT COUNT(*) as cnt FROM withdrawal_tasks WHERE task = ? AND completed = 1", (task_name,))
            cnt = c.fetchone()["cnt"]
            task_stats_text += f"  {task_name}: {cnt} users\n"

        # OTP verified
        c.execute("SELECT COUNT(*) as cnt FROM withdrawal_tasks WHERE task = 'otp_verified' AND completed = 1")
        otp_verified = c.fetchone()["cnt"]
        task_stats_text += f"  otp_verified: {otp_verified} users\n"

        # UGC video submissions
        c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM v2_withdrawal_proofs WHERE task = 'ugc_video'")
        ugc_users = c.fetchone()["cnt"]

        # Instagram post submissions
        c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM v2_withdrawal_proofs WHERE task = 'instagram_post'")
        ig_users = c.fetchone()["cnt"]

        # Referral stats
        c.execute("SELECT COUNT(DISTINCT referrer_id) as cnt FROM referrals")
        referrers = c.fetchone()["cnt"]

        c.execute("""SELECT r.referrer_id, w.user_name, COUNT(*) as refs, w.withdrawal_count
            FROM referrals r LEFT JOIN wallets w ON w.user_id = r.referrer_id
            GROUP BY r.referrer_id ORDER BY refs DESC LIMIT 5""")
        top_referrers_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_referrers_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 {r['refs']} referrals (wd: {r['withdrawal_count'] or 0}x)\n"
        if not top_referrers_text:
            top_referrers_text = "  No referrals yet\n"

        # Recent withdrawals (last 10)
        c.execute("""SELECT wr.user_name, wr.amount, wr.status, wr.created_at, w.withdrawal_count
            FROM withdrawal_requests wr LEFT JOIN wallets w ON w.user_id = wr.user_id
            ORDER BY wr.created_at DESC LIMIT 10""")
        recent_text = ""
        for r in c.fetchall():
            status_icon = "\u2705" if r["status"] == "completed" else "\u23f3" if r["status"] == "pending" else "\u274c"
            date = r["created_at"][:10] if r["created_at"] else "?"
            recent_text += f"  {status_icon} {r['user_name'] or 'Unknown'} \u2014 \u20b9{r['amount']} ({date}) [wd #{r['withdrawal_count'] or 1}]\n"
        if not recent_text:
            recent_text = "  No withdrawals yet\n"

        # Users with most withdrawals
        c.execute("""SELECT user_name, withdrawal_count, total_earned, balance
            FROM wallets WHERE withdrawal_count > 0
            ORDER BY withdrawal_count DESC LIMIT 5""")
        top_withdrawers_text = ""
        for i, r in enumerate(c.fetchall(), 1):
            top_withdrawers_text += f"  {i}. {r['user_name'] or 'Unknown'} \u2014 {r['withdrawal_count']}x withdrawn, earned \u20b9{r['total_earned']} (bal: \u20b9{r['balance']})\n"
        if not top_withdrawers_text:
            top_withdrawers_text = "  No one has withdrawn yet\n"

        # Email linked stats
        c.execute("SELECT COUNT(DISTINCT telegram_id) as cnt FROM medicpoints_claims WHERE email IS NOT NULL AND email != ''")
        emails_linked = c.fetchone()["cnt"]

        conn.close()

        msg = (
            f"\U0001f4b8 MedicNEET \u2014 Withdrawal Tracker\n"
            f"{'─' * 28}\n\n"
            f"\U0001f4ca OVERVIEW\n"
            f"  Total withdrawals: {total_wd} (\u20b9{total_wd_amount})\n"
            f"  Completed: {completed_wd}\n"
            f"  Pending: {pending_wd} (\u20b9{pending_amount})\n"
            f"  Users withdrawn: {users_withdrawn}\n"
            f"  Users eligible (\u2265\u20b950): {users_eligible}\n"
            f"    V1 (first-time): {v1_eligible}\n"
            f"    V2 (repeat): {v2_eligible}\n\n"
            f"\u2705 TASK COMPLETION (all users)\n"
            f"{task_stats_text}"
            f"  ugc_video: {ugc_users} users\n"
            f"  instagram_post: {ig_users} users\n"
            f"  emails_linked: {emails_linked} users\n\n"
            f"\U0001f517 TOP REFERRERS\n"
            f"{top_referrers_text}\n"
            f"\U0001f451 TOP WITHDRAWERS\n"
            f"{top_withdrawers_text}\n"
            f"\U0001f4dd RECENT WITHDRAWALS\n"
            f"{recent_text}"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Statswithdrawal command failed: {e}")
        await update.message.reply_text(f"\u274c Failed to fetch withdrawal stats: {e}")

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
    app.add_handler(CommandHandler("statsmonth", statsmonth_command))
    app.add_handler(CommandHandler("statsoverall", statsoverall_command))
    app.add_handler(CommandHandler("statswithdrawal", statswithdrawal_command))
    app.add_handler(CallbackQueryHandler(handle_reminder_callback, pattern=r"^remind_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
