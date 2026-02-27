"""
MedicNEET Player Re-engagement Reminder
Runs daily at 6:30 PM IST via cron
Group A: wallet >= 5, inactive 3+ days (wallet reminder)
Group B: wallet < 5 or no wallet, but has played, inactive 2+ days (come back)
Tracks sent -> clicked -> played funnel
"""
import os, sys, json, sqlite3, urllib.request, logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s")
DB_PATH = "/home/opc/medicneet-miniapp/medicneet.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS reminder_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, user_name TEXT,
        balance INTEGER, message_text TEXT, sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
        clicked_at TEXT, played_at TEXT)""")
    conn.commit()

def get_wallet_players(conn, test_user_id=None):
    if test_user_id:
        return conn.execute("SELECT w.user_id, w.user_name, w.balance, (SELECT COUNT(*) FROM attempts a WHERE a.user_id = w.user_id AND a.is_correct = 1) as total_wins, (SELECT COUNT(DISTINCT round_id) FROM attempts a WHERE a.user_id = w.user_id) as total_rounds FROM wallets w WHERE w.user_id = ?", (test_user_id,)).fetchall()
    three_days_ago = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute("SELECT w.user_id, w.user_name, w.balance, (SELECT COUNT(*) FROM attempts a WHERE a.user_id = w.user_id AND a.is_correct = 1) as total_wins, (SELECT COUNT(DISTINCT round_id) FROM attempts a WHERE a.user_id = w.user_id) as total_rounds FROM wallets w WHERE w.balance >= 5 AND (SELECT MAX(attempted_at) FROM attempts a WHERE a.user_id = w.user_id) < ?", (three_days_ago,)).fetchall()

def get_inactive_players(conn):
    two_days_ago = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute("""SELECT a.user_id, a.user_name, COALESCE(w.balance, 0) as balance,
        (SELECT COUNT(*) FROM attempts a2 WHERE a2.user_id = a.user_id AND a2.is_correct = 1) as total_wins,
        (SELECT COUNT(DISTINCT round_id) FROM attempts a2 WHERE a2.user_id = a.user_id) as total_rounds
        FROM (SELECT user_id, user_name, MAX(attempted_at) as last_played FROM attempts GROUP BY user_id HAVING last_played < ?) a
        LEFT JOIN wallets w ON a.user_id = w.user_id
        WHERE COALESCE(w.balance, 0) < 5""", (two_days_ago,)).fetchall()

def build_wallet_message(player):
    name = player["user_name"] or "Player"
    balance = player["balance"]
    wins = player["total_wins"]
    rounds = player["total_rounds"]
    wins_needed = max(0, (50 - balance) // 5)
    if balance >= 50:
        return "\U0001f525 " + name + ", you have \u20b9" + str(balance) + " ready to withdraw!\n\n\U0001f4ca Stats: " + str(wins) + " wins from " + str(rounds) + " rounds\n\nCome claim your money - tonight's quiz starts at 7 PM!"
    elif balance >= 25:
        return "\U0001f4b0 " + name + ", \u20b9" + str(balance) + " in your wallet!\n\nJust " + str(wins_needed) + " more wins to reach \u20b950 withdrawal.\n\U0001f4ca You've won " + str(wins) + " times in " + str(rounds) + " rounds - you can do this!\n\nTonight at 7 PM \U0001f3af"
    else:
        return "\U0001f9ec " + name + ", you have \u20b9" + str(balance) + " waiting!\n\nWin tonight and grow it to \u20b950 for withdrawal.\n\U0001f4ca " + str(wins) + " wins from " + str(rounds) + " rounds so far.\n\nQuiz starts at 7 PM - every win = \u20b95!"

def build_comeback_message(player):
    name = player["user_name"] or "Player"
    wins = player["total_wins"]
    rounds = player["total_rounds"]
    if wins > 0:
        return "\U0001f3ae " + name + ", we miss you!\n\nYou won " + str(wins) + " times in " + str(rounds) + " rounds - that's solid!\n\nTonight's quiz starts at 7 PM. Every correct round = \u20b95 cash prize.\n\nCome back and stack those wins! \U0001f525"
    else:
        return "\U0001f3ae " + name + ", tonight could be your night!\n\nYou played " + str(rounds) + " rounds - a win is coming.\n\n4 NEET Biology MCQs, answer all correct = \u20b95 instant.\n\nQuiz starts 7 PM \U0001f9ec"

def send_message(user_id, text):
    keyboard = {"inline_keyboard": [[{"text": "\U0001f3ae Play Tonight", "callback_data": "remind_play_" + str(user_id)}], [{"text": "\U0001f4ca My Stats", "callback_data": "remind_stats_" + str(user_id)}]]}
    payload = {"chat_id": user_id, "text": text, "reply_markup": json.dumps(keyboard)}
    try:
        req = urllib.request.Request("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode()).get("ok", False)
    except Exception as e:
        logger.error("Failed to send to " + str(user_id) + ": " + str(e))
        return False

def main():
    conn = get_db()
    ensure_table(conn)
    test_user_id = sys.argv[1] if len(sys.argv) > 1 else None
    sent = failed = 0

    # Group A: wallet players (>=5 balance, 3+ days inactive)
    wallet_players = get_wallet_players(conn, test_user_id)
    logger.info("Group A (wallet): " + str(len(wallet_players)) + " players")
    for player in wallet_players:
        msg = build_wallet_message(player)
        if send_message(player["user_id"], msg):
            conn.execute("INSERT INTO reminder_logs (user_id, user_name, balance, message_text) VALUES (?, ?, ?, ?)", (player["user_id"], player["user_name"], player["balance"], msg))
            sent += 1
            logger.info("Sent wallet reminder to " + str(player["user_name"]) + " (Rs " + str(player["balance"]) + ")")
        else:
            failed += 1

    # Group B: inactive players (<5 balance, 2+ days inactive)
    if not test_user_id:
        inactive_players = get_inactive_players(conn)
        logger.info("Group B (comeback): " + str(len(inactive_players)) + " players")
        wallet_ids = set(p["user_id"] for p in wallet_players)
        for player in inactive_players:
            if player["user_id"] in wallet_ids:
                continue
            msg = build_comeback_message(player)
            if send_message(player["user_id"], msg):
                conn.execute("INSERT INTO reminder_logs (user_id, user_name, balance, message_text) VALUES (?, ?, ?, ?)", (player["user_id"], player["user_name"], player["balance"], msg))
                sent += 1
                logger.info("Sent comeback to " + str(player["user_name"]))
            else:
                failed += 1

    conn.commit()
    conn.close()
    logger.info("Done: " + str(sent) + " sent, " + str(failed) + " failed")

if __name__ == "__main__":
    main()
