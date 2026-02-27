"""
MedicNEET Player Re-engagement Reminder
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

def get_inactive_players(conn, test_user_id=None):
    if test_user_id:
        return conn.execute("SELECT w.user_id, w.user_name, w.balance, (SELECT COUNT(*) FROM attempts a WHERE a.user_id = w.user_id AND a.is_correct = 1) as total_wins, (SELECT COUNT(DISTINCT round_id) FROM attempts a WHERE a.user_id = w.user_id) as total_rounds FROM wallets w WHERE w.user_id = ?", (test_user_id,)).fetchall()
    three_days_ago = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute("SELECT w.user_id, w.user_name, w.balance, (SELECT COUNT(*) FROM attempts a WHERE a.user_id = w.user_id AND a.is_correct = 1) as total_wins, (SELECT COUNT(DISTINCT round_id) FROM attempts a WHERE a.user_id = w.user_id) as total_rounds FROM wallets w WHERE w.balance >= 5 AND (SELECT MAX(attempted_at) FROM attempts a WHERE a.user_id = w.user_id) < ?", (three_days_ago,)).fetchall()

def build_message(player):
    name = player["user_name"] or "Player"
    balance = player["balance"]
    wins = player["total_wins"]
    rounds = player["total_rounds"]
    wins_needed = max(0, (50 - balance) // 5)
    if balance >= 50:
        return f"\U0001f525 {name}, you have \u20b9{balance} ready to withdraw!\n\n\U0001f4ca Stats: {wins} wins from {rounds} rounds\n\nCome claim your money - tonight\'s quiz starts at 7 PM!"
    elif balance >= 25:
        return f"\U0001f4b0 {name}, \u20b9{balance} in your wallet!\n\nJust {wins_needed} more wins to reach \u20b950 withdrawal.\n\U0001f4ca You\'ve won {wins} times in {rounds} rounds - you can do this!\n\nTonight at 7 PM \U0001f3af"
    else:
        return f"\U0001f9ec {name}, you have \u20b9{balance} waiting!\n\nWin tonight and grow it to \u20b950 for withdrawal.\n\U0001f4ca {wins} wins from {rounds} rounds so far.\n\nQuiz starts at 7 PM - every win = \u20b95!"

def send_message(user_id, text):
    keyboard = {"inline_keyboard": [[{"text": "\U0001f3ae Play Tonight", "callback_data": f"remind_play_{user_id}"}], [{"text": "\U0001f4ca My Stats", "callback_data": f"remind_stats_{user_id}"}]]}
    payload = {"chat_id": user_id, "text": text, "reply_markup": json.dumps(keyboard)}
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode()).get("ok", False)
    except Exception as e:
        logger.error(f"Failed to send to {user_id}: {e}")
        return False

def main():
    conn = get_db()
    ensure_table(conn)
    test_user_id = sys.argv[1] if len(sys.argv) > 1 else None
    players = get_inactive_players(conn, test_user_id)
    logger.info(f"Found {len(players)} players to remind")
    sent = failed = 0
    for player in players:
        msg_text = build_message(player)
        if send_message(player["user_id"], msg_text):
            conn.execute("INSERT INTO reminder_logs (user_id, user_name, balance, message_text) VALUES (?, ?, ?, ?)", (player["user_id"], player["user_name"], player["balance"], msg_text))
            sent += 1
            logger.info(f"Sent to {player['user_name']} (Rs {player['balance']})")
        else:
            failed += 1
    conn.commit()
    conn.close()
    logger.info(f"Done: {sent} sent, {failed} failed out of {len(players)} players")

if __name__ == "__main__":
    main()
