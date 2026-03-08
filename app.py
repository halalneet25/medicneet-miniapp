from dotenv import load_dotenv
load_dotenv()
"""
MedicNEET Telegram Mini App - Cash Prize Quiz
Backend: FastAPI + SQLite + Daily Email Export
"""
import os, io, csv, json, time, hashlib, hmac, sqlite3, asyncio, logging, smtplib, string, random, html as html_lib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl
import httpx
from fastapi import FastAPI, Request, HTTPException
from medicpoints import preload_points_for_email, get_claim_status, init_medicpoints_table, get_user_medicpoints, upload_to_google_drive
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ─── CONFIG ────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel")
QUESTION_INTERVAL_HOURS = int(os.getenv("QUESTION_INTERVAL_HOURS", "4"))
PRIZE_WINDOW_MINUTES = int(os.getenv("PRIZE_WINDOW_MINUTES", "2"))  # Prize only for first X minutes
CASH_PRIZE = int(os.getenv("CASH_PRIZE", "5"))
DB_PATH = os.getenv("DB_PATH", "medicneet.db")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com")
APP_STATUS = os.getenv("APP_STATUS", "launching_soon")  # "launching_soon" or "live"
PLAYSTORE_LINK = os.getenv("PLAYSTORE_LINK", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "medicneet.team@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "YOUR_GMAIL_APP_PASSWORD")
EXPORT_TO_EMAIL = os.getenv("EXPORT_TO_EMAIL", "medicneet.team@gmail.com")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")

# ─── IST SCHEDULE CONFIG ─────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))
SCHEDULED_TIMES_IST = [(19, 0), (19, 30), (20, 0), (20, 30)]
ROUND_DURATION_MINUTES = 25

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for sql in [
        """CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL,
            option_a TEXT NOT NULL, option_b TEXT NOT NULL, option_c TEXT NOT NULL, option_d TEXT NOT NULL,
            correct_answer TEXT NOT NULL, explanation TEXT, chapter TEXT, difficulty TEXT, sheet_row INTEGER UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_1_id INTEGER NOT NULL,
            question_2_id INTEGER NOT NULL,
            question_3_id INTEGER NOT NULL,
            question_4_id INTEGER NOT NULL,
            started_at TEXT NOT NULL, ends_at TEXT NOT NULL, prize_ends_at TEXT,
            winner_user_id TEXT, winner_name TEXT, winner_time_ms INTEGER,
            winner_photo_path TEXT, winner_upi_id TEXT, announced INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER NOT NULL,
            user_id TEXT NOT NULL, user_name TEXT, selected_answers TEXT NOT NULL,
            is_correct INTEGER NOT NULL, time_ms INTEGER NOT NULL,
            attempted_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(round_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER NOT NULL,
            user_id TEXT NOT NULL, user_name TEXT, photo_path TEXT, upi_id TEXT,
            time_ms INTEGER, prize_amount INTEGER DEFAULT 5, paid INTEGER DEFAULT 0,
            winner_type TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS notify_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            user_id TEXT, user_name TEXT, source TEXT DEFAULT 'miniapp',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS email_export_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, exported_at TEXT NOT NULL,
            email_count INTEGER, status TEXT)""",
        """CREATE TABLE IF NOT EXISTS wallets (
            user_id TEXT PRIMARY KEY,
            user_name TEXT,
            balance INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            upi_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            round_id INTEGER,
            status TEXT DEFAULT 'completed',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            user_name TEXT,
            amount INTEGER NOT NULL,
            upi_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_code TEXT UNIQUE,
            challenger_id TEXT,
            challenger_name TEXT,
            challenger_time_ms INTEGER,
            challenger_round_id INTEGER,
            friend_id TEXT,
            friend_name TEXT,
            friend_time_ms INTEGER,
            friend_round_id INTEGER,
            status TEXT DEFAULT 'pending',
            chain_parent_id INTEGER,
            created_at TEXT,
            completed_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS disqualifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            user_name TEXT,
            round_id INTEGER NOT NULL,
            question_times TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS withdrawal_tasks (
            user_id TEXT NOT NULL,
            task TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            completed_at TEXT,
            PRIMARY KEY(user_id, task))""",
        """CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT NOT NULL,
            referee_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(referrer_id, referee_id))""",
        """CREATE TABLE IF NOT EXISTS blogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            excerpt TEXT NOT NULL,
            thumbnail_emoji TEXT DEFAULT '📝',
            medium_url TEXT NOT NULL,
            category TEXT DEFAULT 'strategy',
            is_featured INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            event TEXT NOT NULL,
            data TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    ]:
        c.execute(sql)
    # Migrate: add chain_parent_id to challenges if missing (for existing DBs)
    try:
        c.execute("ALTER TABLE challenges ADD COLUMN chain_parent_id INTEGER")
    except:
        pass
    # Migrate: add winner_type to winners if missing (for existing DBs)
    try:
        c.execute("ALTER TABLE winners ADD COLUMN winner_type TEXT DEFAULT NULL")
    except:
        pass
    # Migrate: add upi_id to wallets if missing (for existing DBs)
    try:
        c.execute("ALTER TABLE wallets ADD COLUMN upi_id TEXT")
    except:
        pass
    # Migrate: add withdrawal_count to wallets (V2 withdrawal system)
    try:
        c.execute("ALTER TABLE wallets ADD COLUMN withdrawal_count INTEGER DEFAULT 0")
    except:
        pass
    # Migrate: add withdrawal_cycle to referrals (V2 referral cycle tracking)
    try:
        c.execute("ALTER TABLE referrals ADD COLUMN withdrawal_cycle INTEGER DEFAULT 0")
    except:
        pass
    # V2 withdrawal proofs table
    c.execute("""CREATE TABLE IF NOT EXISTS v2_withdrawal_proofs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        task TEXT NOT NULL,
        proof_link TEXT,
        verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()
    init_medicpoints_table()
    logger.info("Database initialized")

def get_db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def seed_initial_blogs():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM blogs")
    if c.fetchone()["cnt"] == 0:
        c.execute("""INSERT INTO blogs (title, slug, excerpt, thumbnail_emoji, medium_url, category, is_featured)
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  ("The NEET Biology Strategy Nobody Talks About: How to Use PYQs the Right Way",
                   "pyq-strategy-neet-biology",
                   "Most NEET aspirants solve PYQs. Very few actually learn from them. Here's the difference — and how it can change your score by 40-80 marks.",
                   "🎯",
                   "https://medium.com/@medicneet.team/the-neet-biology-strategy-nobody-talks-about-how-to-use-previous-year-questions-the-right-way-c6cc71027584",
                   "strategy",
                   1))
        conn.commit()
    conn.close()

def sync_questions_from_sheet():
    if not GOOGLE_SHEET_ID: return 0
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly","https://www.googleapis.com/auth/drive.readonly"])
        sheet = gspread.authorize(creds).open_by_key(GOOGLE_SHEET_ID).sheet1
        rows = sheet.get_all_records(); conn = get_db(); c = conn.cursor(); count = 0
        for i, row in enumerate(rows, start=2):
            try:
                c.execute("INSERT INTO questions (question,option_a,option_b,option_c,option_d,correct_answer,explanation,chapter,difficulty,sheet_row) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sheet_row) DO UPDATE SET question=excluded.question,option_a=excluded.option_a,option_b=excluded.option_b,option_c=excluded.option_c,option_d=excluded.option_d,correct_answer=excluded.correct_answer,explanation=excluded.explanation,chapter=excluded.chapter,difficulty=excluded.difficulty",
                    (str(row.get("Question","")),str(row.get("Option A","")),str(row.get("Option B","")),str(row.get("Option C","")),str(row.get("Option D","")),
                     str(row.get("Correct Answer","")).upper().strip(),str(row.get("Explanation","")),str(row.get("Chapter","")),str(row.get("Difficulty","")),i))
                count += 1
            except Exception as e: logger.error(f"Row {i}: {e}")
        conn.commit(); conn.close(); logger.info(f"Synced {count} questions"); return count
    except Exception as e: logger.error(f"Sheet sync failed: {e}"); return 0

def validate_telegram_data(init_data):
    try:
        parsed = dict(parse_qsl(init_data)); check_hash = parsed.pop("hash","")
        dcs = "\n".join(f"{k}={v}" for k,v in sorted(parsed.items()))
        sk = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if hmac.new(sk, dcs.encode(), hashlib.sha256).hexdigest() == check_hash:
            return json.loads(parsed.get("user","{}"))
    except: pass
    return None

def get_current_round():
    """Get the currently active round without creating a new one."""
    conn = get_db(); c = conn.cursor(); now = datetime.utcnow().isoformat()
    c.execute("SELECT * FROM rounds WHERE ends_at > ? ORDER BY started_at DESC LIMIT 1", (now,))
    rnd = c.fetchone()
    conn.close()
    return dict(rnd) if rnd else None

def maybe_create_scheduled_round():
    """Create a new round only if current IST time matches a scheduled slot."""
    now_ist = datetime.now(IST)
    now_utc = datetime.utcnow()
    logger.info(f"Round checker: IST={now_ist.strftime('%H:%M')}, checking slots...")

    # Check if there's already an active round
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM rounds WHERE ends_at > ?", (now_utc.isoformat(),))
    if c.fetchone():
        conn.close()
        return None

    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    for hour, minute in SCHEDULED_TIMES_IST:
        scheduled_ist = today_ist.replace(hour=hour, minute=minute)
        diff_seconds = (now_ist - scheduled_ist).total_seconds()

        # Within 2-minute window after scheduled time
        if 0 <= diff_seconds < 120:
            # Check if round already created for this time slot today
            scheduled_utc = scheduled_ist.astimezone(timezone.utc).replace(tzinfo=None)
            window_start = (scheduled_utc - timedelta(minutes=2)).isoformat()
            window_end = (scheduled_utc + timedelta(minutes=5)).isoformat()

            c.execute("SELECT id FROM rounds WHERE started_at >= ? AND started_at <= ?", (window_start, window_end))
            if c.fetchone():
                conn.close()
                return None

            # Select 4 questions with mixed correct answers (one per A,B,C,D)
            used_ids = set()
            c.execute("SELECT question_1_id, question_2_id, question_3_id, question_4_id FROM rounds")
            for row in c.fetchall():
                used_ids.update([row['question_1_id'], row['question_2_id'], row['question_3_id'], row['question_4_id']])
            q_ids = []
            for ans in ['A', 'B', 'C', 'D']:
                if used_ids:
                    placeholders = ','.join('?' * len(used_ids))
                    c.execute(f'SELECT id FROM questions WHERE correct_answer = ? AND id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1', [ans] + list(used_ids))
                else:
                    c.execute('SELECT id FROM questions WHERE correct_answer = ? ORDER BY RANDOM() LIMIT 1', (ans,))
                row = c.fetchone()
                if not row:
                    c.execute('SELECT id FROM questions WHERE correct_answer = ? ORDER BY RANDOM() LIMIT 1', (ans,))
                    row = c.fetchone()
                if row:
                    q_ids.append(row['id'])
            if len(q_ids) < 4:
                c.execute('SELECT id FROM questions ORDER BY RANDOM() LIMIT 4')
                q_ids = [q['id'] for q in c.fetchall()]
            random.shuffle(q_ids)
            started = now_utc
            prize_ends = started + timedelta(minutes=PRIZE_WINDOW_MINUTES)
            ends = started + timedelta(minutes=ROUND_DURATION_MINUTES)
            c.execute("INSERT INTO rounds (question_1_id, question_2_id, question_3_id, question_4_id, started_at, ends_at, prize_ends_at) VALUES (?,?,?,?,?,?,?)",
                      (q_ids[0], q_ids[1], q_ids[2], q_ids[3], started.isoformat(), ends.isoformat(), prize_ends.isoformat()))
            rid = c.lastrowid; conn.commit()
            c.execute("SELECT * FROM rounds WHERE id = ?", (rid,)); r = dict(c.fetchone()); conn.close()
            # Trigger channel announcement for new round (run in background)
            import threading
            def announce():
                import asyncio
                asyncio.run(send_new_round_to_channel())
            threading.Thread(target=announce, daemon=True).start()
            logger.info(f"New scheduled round created: Round #{rid} at {hour}:{minute:02d} IST")
            return r

    conn.close()
    return None

async def send_winner_to_channel(round_id):
    conn = get_db()
    c = conn.cursor()
    now = datetime.utcnow().isoformat()

    # Step 1: Get all 4/4 correct users
    c.execute("SELECT user_id, user_name, time_ms, prize_amount FROM winners WHERE round_id = ? ORDER BY time_ms ASC", (round_id,))
    all_entries = [dict(r) for r in c.fetchall()]

    # Step 2: Separate capped (balance >= 50) vs uncapped users
    capped_users = []
    uncapped_users = []
    for entry in all_entries:
        ce = conn.cursor()
        ce.execute("SELECT balance FROM wallets WHERE user_id=?", (entry["user_id"],))
        w_row = ce.fetchone()
        bal = w_row["balance"] if w_row else 0
        if bal >= 50:
            capped_users.append(entry)
        else:
            uncapped_users.append(entry)

    # Step 3: Award 20 Medic Points to all capped users (tracked in transactions)
    for cu in capped_users:
        c.execute("UPDATE winners SET winner_type = 'capped_medic' WHERE round_id = ? AND user_id = ?", (round_id, cu["user_id"]))
        c.execute("INSERT INTO transactions (user_id, amount, type, round_id, status, created_at) VALUES (?,?,?,?,?,?)",
                 (cu["user_id"], 20, "medic_points_cap", round_id, "completed", now))

    # Step 4: Speed winners from UNCAPPED pool only (top 2)
    speed_winners = uncapped_users[:2]
    pool = uncapped_users[5:]

    for sw in speed_winners:
        c.execute("UPDATE winners SET winner_type = 'speed' WHERE round_id = ? AND user_id = ?", (round_id, sw["user_id"]))
        c.execute("INSERT INTO wallets (user_id, user_name, balance, total_earned, created_at, updated_at) VALUES (?,?,5,5,?,?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + 5, total_earned = total_earned + 5, updated_at = ?",
                 (sw["user_id"], sw["user_name"], now, now, now))
        c.execute("INSERT INTO transactions (user_id, amount, type, round_id, status, created_at) VALUES (?,?,?,?,?,?)",
                 (sw["user_id"], 5, "win", round_id, "completed", now))

    # Step 5: Weighted lucky draw from UNCAPPED pool
    lucky_count = min(8, len(pool))
    if lucky_count > 0 and pool:
        weights = []
        for p in pool:
            earned = 0
            ce = conn.cursor()
            ce.execute("SELECT total_earned FROM wallets WHERE user_id=?", (p["user_id"],))
            row = ce.fetchone()
            if row: earned = row["total_earned"] or 0
            if earned < 30: weights.append(5)
            elif earned < 100: weights.append(2)
            else: weights.append(1)
        lucky_winners = []
        temp_pool = list(pool)
        temp_weights = list(weights)
        for _ in range(lucky_count):
            if not temp_pool: break
            chosen = random.choices(range(len(temp_pool)), weights=temp_weights, k=1)[0]
            lucky_winners.append(temp_pool.pop(chosen))
            temp_weights.pop(chosen)
    else:
        lucky_winners = []

    # Step 6: Credit cash to lucky winners
    for lw in lucky_winners:
        c.execute("UPDATE winners SET winner_type = 'lucky' WHERE round_id = ? AND user_id = ?", (round_id, lw["user_id"]))
        c.execute("INSERT INTO wallets (user_id, user_name, balance, total_earned, created_at, updated_at) VALUES (?,?,5,5,?,?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + 5, total_earned = total_earned + 5, updated_at = ?",
                 (lw["user_id"], lw["user_name"], now, now, now))
        c.execute("INSERT INTO transactions (user_id, amount, type, round_id, status, created_at) VALUES (?,?,?,?,?,?)",
                 (lw["user_id"], 5, "win", round_id, "completed", now))

    # Step 7: Remove non-winners from winners table
    c.execute("DELETE FROM winners WHERE round_id = ? AND (winner_type IS NULL OR winner_type = '')", (round_id,))

    conn.commit()

    # Get total participants count
    c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM attempts WHERE round_id = ?", (round_id,))
    total_participants = c.fetchone()["cnt"]

    conn.close()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    button = {"inline_keyboard": [[{"text": "🧠 Play Next Round", "url": "https://t.me/Winners_neetbot/Medicneet"}]]}

    all_cash_winners = speed_winners + lucky_winners
    total_4of4 = len(all_cash_winners) + len(pool) + len(capped_users)

    if not all_cash_winners and not capped_users:
        text = f"""🏆 <b>ROUND #{round_id} RESULTS</b>

No winners this round! 😢
Nobody scored 4/4 correct.

👥 {total_participants} players attempted

Better luck next time!
🔥 Rounds daily at 7:00, 7:30, 8:00, 8:30 PM IST!"""
    elif not all_cash_winners and capped_users:
        # All 4/4 scorers were capped
        capped_lines = []
        for cu in capped_users:
            name = html_lib.escape(cu["user_name"] or "Anonymous")
            capped_lines.append(f"🎯 {name} — 20 Medic Points")
        capped_text = "\n".join(capped_lines)
        text = f"""🏆 <b>ROUND #{round_id} RESULTS</b>

All winners earned Medic Points this round!

🎯 <b>Medic Points Earned:</b>
{capped_text}

👥 {total_4of4}/{total_participants} scored 4/4!

🔥 Rounds daily at 7:00, 7:30, 8:00, 8:30 PM IST!"""
    else:
        sections = []

        if speed_winners:
            speed_lines = []
            for i, w in enumerate(speed_winners, start=1):
                name = html_lib.escape(w["user_name"] or "Anonymous")
                time_sec = w["time_ms"] / 1000
                speed_lines.append(f"{i}. {name} — {time_sec:.1f}s — ₹{CASH_PRIZE} ✅")
            sections.append("⚡ <b>Speed Winners (Top 2):</b>\n" + "\n".join(speed_lines))

        if lucky_winners:
            lucky_lines = []
            for w in lucky_winners:
                name = html_lib.escape(w["user_name"] or "Anonymous")
                lucky_lines.append(f"🍀 {name} — ₹{CASH_PRIZE} ✅")
            sections.append("🎲 <b>Lucky Winners:</b>\n" + "\n".join(lucky_lines))

        if capped_users:
            capped_lines = []
            for cu in capped_users:
                name = html_lib.escape(cu["user_name"] or "Anonymous")
                capped_lines.append(f"🎯 {name} — 20 Medic Points")
            sections.append("🎯 <b>Wallet Full — Medic Points:</b>\n" + "\n".join(capped_lines))

        winner_text = "\n\n".join(sections)
        total_prize = len(all_cash_winners) * CASH_PRIZE

        no_prize_4of4 = total_4of4 - len(all_cash_winners) - len(capped_users)
        medic_points_line = ""
        if no_prize_4of4 > 0:
            medic_points_line = f"\n\n🎯 {no_prize_4of4} more scored 4/4 — earn 20 Medic Points on the MedicNEET App! 🍎"

        text = f"""🏆 <b>ROUND #{round_id} RESULTS</b>

{winner_text}

💰 Total paid: ₹{total_prize}
👥 {total_4of4}/{total_participants} scored 4/4!{medic_points_line}

🔥 Rounds daily at 7:00, 7:30, 8:00, 8:30 PM IST!"""

    async with httpx.AsyncClient() as client:
        await client.post(f"{url}/sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "reply_markup": button})

async def send_new_round_to_channel():
    """Post new question alert with quiz button to channel"""
    text = f"""🚨 <b>NEET 2026 - 4 High Level Biology Questions Posted!</b>

⚡ Top 2 fastest win ₹{CASH_PRIZE} + 🎲 8 lucky winners from all 4/4 scorers!
💰 ₹50 total prize pool
⏱ Prize window: {PRIZE_WINDOW_MINUTES} minutes only!

👇 Answer now!"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    button = {"inline_keyboard": [[{"text": "🧠 Play Quiz - Win ₹5!", "url": "https://t.me/Winners_neetbot/Medicneet"}]]}
    async with httpx.AsyncClient() as client:
        await client.post(f"{url}/sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "reply_markup": button})

def export_emails_csv():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT email, user_name, source, created_at FROM notify_emails ORDER BY created_at DESC")
    rows = c.fetchall(); conn.close()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["Email","Name","Source","Signed Up At"])
    for r in rows: w.writerow([r["email"], r["user_name"] or "", r["source"] or "miniapp", r["created_at"]])
    return out.getvalue().encode("utf-8"), len(rows)

def send_daily_email_export():
    try:
        csv_bytes, count = export_emails_csv()
        if count == 0: logger.info("No emails to export"); return
        today = datetime.utcnow().strftime("%Y-%m-%d")
        msg = MIMEMultipart(); msg["From"]=SMTP_USER; msg["To"]=EXPORT_TO_EMAIL
        msg["Subject"] = f"MedicNEET Emails Export ({today}) — {count} subscribers"
        msg.attach(MIMEText(f"Daily email export from MedicNEET Mini App.\n\nTotal: {count} emails\nDate: {today}\n\nCSV attached.\n\n— MedicNEET Bot","plain"))
        att = MIMEBase("application","octet-stream"); att.set_payload(csv_bytes)
        encoders.encode_base64(att); att.add_header("Content-Disposition", f"attachment; filename=medicneet_emails_{today}.csv")
        msg.attach(att)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s: s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO email_export_log (exported_at, email_count, status) VALUES (?,?,?)", (datetime.utcnow().isoformat(), count, "success"))
        conn.commit(); conn.close(); logger.info(f"✅ Exported {count} emails to {EXPORT_TO_EMAIL}")
    except Exception as e:
        logger.error(f"❌ Email export failed: {e}")
        try:
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO email_export_log (exported_at, email_count, status) VALUES (?,?,?)", (datetime.utcnow().isoformat(), 0, f"failed: {str(e)[:200]}"))
            conn.commit(); conn.close()
        except: pass

def send_withdrawal_request_email(user_id, user_name, amount, upi_id, balance, total_earned,
                                   ugc_video_link=None, medic_points=None, required_points=None):
    """Send email when user requests withdrawal"""
    try:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        proofs = ""
        if ugc_video_link or medic_points is not None:
            proofs = (
                f"\n── Proofs ──\n"
                f"Medic Points: {medic_points}/{required_points} ✅\n"
                f"UGC Video: {ugc_video_link}\n"
            )
        msg = MIMEText(
            f"💰 New Withdrawal Request!\n\n"
            f"User: {user_name}\n"
            f"User ID: {user_id}\n"
            f"Amount: ₹{amount}\n"
            f"UPI ID: {upi_id}\n"
            f"Current Balance: ₹{balance}\n"
            f"Total Earned: ₹{total_earned}\n"
            f"{proofs}\n"
            f"Requested at: {now}\n\n"
            f"— MedicNEET Bot", "plain"
        )
        msg["From"] = SMTP_USER
        msg["To"] = "medicneet.team@gmail.com"
        msg["Subject"] = f"💰 Withdrawal Request - {user_name}"
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        logger.info(f"✅ Withdrawal email sent: {user_name} / ₹{amount}")
    except Exception as e:
        logger.error(f"❌ Withdrawal email failed: {e}")

def send_v2_withdrawal_request_email(user_id, user_name, amount, upi_id, balance, total_earned,
                                      ugc_video_link, ig_post_link, medic_points, required_points):
    """Send email when V2 user requests withdrawal - includes proof links"""
    try:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        msg = MIMEText(
            f"💰 V2 Withdrawal Request!\n\n"
            f"User: {user_name}\n"
            f"User ID: {user_id}\n"
            f"Amount: ₹{amount}\n"
            f"UPI ID: {upi_id}\n"
            f"Current Balance: ₹{balance}\n"
            f"Total Earned: ₹{total_earned}\n\n"
            f"── V2 Proofs ──\n"
            f"Medic Points: {medic_points}/{required_points} ✅\n"
            f"UGC Video: {ugc_video_link}\n"
            f"Instagram Post: {ig_post_link}\n\n"
            f"Requested at: {now}\n\n"
            f"— MedicNEET Bot", "plain"
        )
        msg["From"] = SMTP_USER
        msg["To"] = "medicneet.team@gmail.com"
        msg["Subject"] = f"💰 V2 Withdrawal - {user_name}"
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        logger.info(f"✅ V2 Withdrawal email sent: {user_name} / ₹{amount}")
    except Exception as e:
        logger.error(f"❌ V2 Withdrawal email failed: {e}")

mid_round_notified = set()

async def send_mid_round_notification(round_id, msg_type):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM attempts WHERE round_id = ?", (round_id,))
    players = c.fetchone()["cnt"]
    conn.close()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    button = {"inline_keyboard": [[{"text": "🧠 Play Now", "url": "https://t.me/Winners_neetbot/Medicneet"}]]}
    if msg_type == "mid":
        text = f"⏰ <b>Round #{round_id} is LIVE!</b>\n\n👥 {players} players joined so far\n🧬 4 NEET Biology MCQs — score 4/4 to win ₹5\n\nCan you beat them? Join now!"
    else:
        text = f"🔥 <b>Round #{round_id} closing soon!</b>\n\n👥 {players} players attempted\n⏳ Last chance to play this round!\n\nDon't miss out!"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{url}/sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "reply_markup": button})
        logger.info(f"Sent {msg_type} notification for round #{round_id}")
    except Exception as e:
        logger.error(f"Mid-round notification failed: {e}")

async def round_manager():
    last_export_date = None
    while True:
        try:
            conn = get_db(); c = conn.cursor(); now = datetime.utcnow(); now_str = now.isoformat()
            c.execute("SELECT r.id FROM rounds r WHERE r.prize_ends_at <= ? AND r.announced = 0", (now_str,))
            for rnd in c.fetchall():
                await send_winner_to_channel(rnd["id"])
                c.execute("UPDATE rounds SET announced = 1 WHERE id = ?", (rnd["id"],))
            # Mid-round notifications
            c.execute("SELECT r.id, r.started_at, r.prize_ends_at, r.ends_at FROM rounds r WHERE r.ends_at > ? AND r.announced = 0", (now_str,))
            for rnd in c.fetchall():
                rid = rnd["id"]
                started = datetime.fromisoformat(rnd["started_at"])
                prize_ends = datetime.fromisoformat(rnd["prize_ends_at"]) if rnd["prize_ends_at"] else started + timedelta(minutes=10)
                elapsed = (now - started).total_seconds()
                prize_remaining = (prize_ends - now).total_seconds()
                mid_key = f"{rid}_mid"
                last_key = f"{rid}_last"
                if elapsed >= 300 and prize_remaining > 0 and mid_key not in mid_round_notified:
                    await send_mid_round_notification(rid, "mid")
                    mid_round_notified.add(mid_key)
                if prize_remaining <= 120 and prize_remaining > 0 and last_key not in mid_round_notified:
                    await send_mid_round_notification(rid, "last")
                    mid_round_notified.add(last_key)
            if len(mid_round_notified) > 100:
                mid_round_notified.clear()
            # Expire old challenges (24 hours)
            c.execute("UPDATE challenges SET status = 'expired' WHERE status = 'pending' AND created_at < ?",
                     ((now - timedelta(hours=24)).isoformat(),))
            conn.commit(); conn.close()
            # Check if it's time to create a scheduled round
            maybe_create_scheduled_round()
            today_str = now.strftime("%Y-%m-%d")
            if now.hour == 2 and now.minute >= 30 and last_export_date != today_str:
                send_daily_email_export(); last_export_date = today_str
        except Exception as e: logger.error(f"Round manager: {e}")
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(); seed_initial_blogs(); sync_questions_from_sheet(); maybe_create_scheduled_round()
    task = asyncio.create_task(round_manager()); yield; task.cancel()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
os.makedirs("static/uploads", exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request":request,"playstore_link":PLAYSTORE_LINK,"app_status":APP_STATUS,"cash_prize":CASH_PRIZE})

@app.get("/api/schedule")
async def api_schedule():
    """Get today's round schedule with status for each time slot."""
    now_ist = datetime.now(IST)
    now_utc = datetime.utcnow()
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    conn = get_db(); c = conn.cursor()

    schedule = []
    next_round_utc = None

    for hour, minute in SCHEDULED_TIMES_IST:
        scheduled_ist = today_ist.replace(hour=hour, minute=minute)
        scheduled_utc = scheduled_ist.astimezone(timezone.utc).replace(tzinfo=None)

        # Check if a round exists for this slot
        window_start = (scheduled_utc - timedelta(minutes=2)).isoformat()
        window_end = (scheduled_utc + timedelta(minutes=ROUND_DURATION_MINUTES + 2)).isoformat()

        c.execute("SELECT id, ends_at FROM rounds WHERE started_at >= ? AND started_at <= ?", (window_start, window_end))
        existing = c.fetchone()

        if existing:
            if existing["ends_at"] > now_utc.isoformat():
                status = "active"
            else:
                status = "completed"
        elif now_ist >= scheduled_ist + timedelta(minutes=3):
            status = "completed"
        else:
            status = "upcoming"
            if next_round_utc is None:
                next_round_utc = scheduled_utc.isoformat()

        period = "AM" if hour < 12 else "PM"
        display_hour = hour % 12 or 12
        time_12h = f"{display_hour}:{minute:02d} {period}"
        schedule.append({
            "time": time_12h,
            "hour": hour,
            "minute": minute,
            "status": status,
            "scheduled_utc": scheduled_utc.isoformat(),
            "round_id": existing["id"] if existing else None
        })

    conn.close()

    all_completed = all(s["status"] in ("completed",) for s in schedule)

    if all_completed and not next_round_utc:
        # Next round is tomorrow at first scheduled time
        tomorrow_ist = today_ist + timedelta(days=1)
        first_slot = SCHEDULED_TIMES_IST[0]
        next_ist = tomorrow_ist.replace(hour=first_slot[0], minute=first_slot[1])
        next_round_utc = next_ist.astimezone(timezone.utc).replace(tzinfo=None).isoformat()

    return {
        "schedule": schedule,
        "next_round_utc": next_round_utc,
        "all_completed": all_completed,
        "now_utc": now_utc.isoformat()
    }

@app.get("/api/current-round")
async def api_current_round():
    rnd = get_current_round()
    if not rnd: return JSONResponse({"error":"No active round"}, status_code=404)
    conn = get_db(); c = conn.cursor()
    # Fetch all 4 questions
    q_ids = [rnd["question_1_id"], rnd["question_2_id"], rnd["question_3_id"], rnd["question_4_id"]]
    c.execute("SELECT * FROM questions WHERE id IN (?,?,?,?)", q_ids)
    questions_raw = c.fetchall()
    # Maintain order of questions as they were stored
    questions_dict = {q["id"]: q for q in questions_raw}
    questions = [
        {
            "text": questions_dict[q_id]["question"],
            "option_a": questions_dict[q_id]["option_a"],
            "option_b": questions_dict[q_id]["option_b"],
            "option_c": questions_dict[q_id]["option_c"],
            "option_d": questions_dict[q_id]["option_d"],
            "chapter": questions_dict[q_id]["chapter"]
        }
        for q_id in q_ids if q_id in questions_dict
    ]
    c.execute("SELECT COUNT(*) as cnt FROM attempts WHERE round_id = ?", (rnd["id"],)); ac = c.fetchone()["cnt"]
    c.execute("SELECT user_name, time_ms FROM attempts WHERE round_id = ? AND is_correct = 1 ORDER BY time_ms ASC LIMIT 1", (rnd["id"],))
    f = c.fetchone(); conn.close()
    return {"round_id":rnd["id"],"ends_at":rnd["ends_at"],"prize_ends_at":rnd.get("prize_ends_at"),"questions":questions,"stats":{"attempts":ac,"fastest_name":f["user_name"] if f else None,"fastest_time_ms":f["time_ms"] if f else None}}

@app.post("/api/submit")
async def api_submit(request: Request):
    data = await request.json()
    rid = data.get("round_id")
    uid = str(data.get("user_id", ""))
    un = data.get("user_name", "Anon")
    answers = data.get("answers", [])  # Array of 4 answers
    tms = int(data.get("time_ms", 0))
    question_times = data.get("question_times", [])  # Per-question timing array
    challenge_code = data.get("challenge_code", "")

    # Validate input
    if not all([rid, uid, tms]) or not isinstance(answers, list) or len(answers) != 4:
        raise HTTPException(400, "Missing fields or invalid answers format")

    # Validate question_times: must be a list of exactly 4 elements
    if not isinstance(question_times, list) or len(question_times) != 4:
        return JSONResponse({"error": "Invalid submission data"}, status_code=400)

    # Check if user is banned
    conn_check = get_db()
    banned = conn_check.execute("SELECT 1 FROM blocked_users WHERE user_id=?", (uid,)).fetchone()
    conn_check.close()
    if banned:
        return JSONResponse({"error": "Account suspended. Contact support."}, status_code=403)

    # Normalize answers
    answers = [str(a).upper().strip() for a in answers]

    conn = get_db(); c = conn.cursor(); now = datetime.utcnow().isoformat()

    # Link friend to challenge if challenge_code provided
    if challenge_code:
        c.execute("SELECT * FROM challenges WHERE challenge_code = ? AND status = 'pending'", (challenge_code,))
        ch = c.fetchone()
        if ch:
            if ch["challenger_id"] == uid:
                pass  # Can't challenge yourself - silently ignore
            elif not ch["friend_id"]:
                c.execute("UPDATE challenges SET friend_id = ?, friend_name = ? WHERE challenge_code = ?",
                         (uid, un, challenge_code))
            # If friend_id already set (to this user or someone else), no action needed
    c.execute("SELECT * FROM rounds WHERE id = ? AND ends_at > ?", (rid, now))
    rnd = c.fetchone()
    if not rnd:
        conn.close()
        raise HTTPException(400, "Round ended")

    c.execute("SELECT id FROM attempts WHERE round_id = ? AND user_id = ?", (rid, uid))
    if c.fetchone():
        conn.close()
        raise HTTPException(400, "Already attempted")

    # Fetch all 4 questions and their correct answers
    q_ids = [rnd["question_1_id"], rnd["question_2_id"], rnd["question_3_id"], rnd["question_4_id"]]
    c.execute("SELECT id, correct_answer, explanation FROM questions WHERE id IN (?,?,?,?)", q_ids)
    questions_raw = c.fetchall()
    questions_dict = {q["id"]: q for q in questions_raw}

    # Check each answer and collect results
    correct_answers = []
    explanations = []
    results = []
    all_correct = True

    for i, q_id in enumerate(q_ids):
        if q_id in questions_dict:
            correct_ans = questions_dict[q_id]["correct_answer"]
            user_ans = answers[i] if i < len(answers) else ""
            is_correct = user_ans == correct_ans

            correct_answers.append(correct_ans)
            explanations.append(questions_dict[q_id]["explanation"] or "")
            results.append(is_correct)

            if not is_correct:
                all_correct = False
        else:
            correct_answers.append("?")
            explanations.append("")
            results.append(False)
            all_correct = False

    # Check for suspicious answer speed (auto-disqualification)
    # Only disqualify if ALL correct (4/4) AND at least 2 positive gaps < 3 seconds
    # Negative gaps are skipped (they occur when a user revisits a previous question)
    disqualified = False
    if all_correct and isinstance(question_times, list) and len(question_times) == 4:
        try:
            qt = [int(t) if t is not None else 0 for t in question_times]
            # Calculate gaps between consecutive questions only (skip first absolute time)
            gaps = []
            for i in range(1, 4):
                gaps.append(qt[i] - qt[i - 1])
            if sum(1 for g in gaps if 0 < g < 3000) >= 2:
                disqualified = True
                logger.info(f"DISQUALIFIED user {uid} ({un}) in round {rid}: gaps={gaps}, question_times={qt}")
        except (ValueError, TypeError):
            pass

    # Store attempt with all answers as JSON
    ic = 1 if all_correct else 0
    if disqualified:
        ic = 0  # Mark as incorrect for disqualified users
    c.execute("INSERT INTO attempts (round_id,user_id,user_name,selected_answers,is_correct,time_ms) VALUES (?,?,?,?,?,?)",
              (rid, uid, un, json.dumps(answers), ic, tms))

    # Log disqualification
    if disqualified:
        c.execute("INSERT INTO disqualifications (user_id, user_name, round_id, question_times, created_at) VALUES (?,?,?,?,?)",
                  (uid, un, rid, json.dumps(question_times), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return {"disqualified": True, "reason": "Suspicious answer speed detected. Each question requires minimum reading time."}

    iw = False
    in_lucky_pool = False
    # Check if still in prize window
    prize_ends_at = rnd["prize_ends_at"]
    in_prize_window = prize_ends_at and now <= prize_ends_at

    if ic and in_prize_window:
        # Add to winners table (all 4/4 correct users during prize window)
        # Wallet crediting happens in send_winner_to_channel when prize window ends
        # so final top 5 are determined once, not on every submit
        c.execute("INSERT OR IGNORE INTO winners (round_id,user_id,user_name,time_ms,prize_amount) VALUES (?,?,?,?,?)", (rid, uid, un, tms, 5))

        # Check if user is currently in top 5 fastest (for UI feedback only, no crediting)
        c.execute("SELECT user_id FROM winners WHERE round_id = ? ORDER BY time_ms ASC LIMIT 5", (rid,))
        speed_winners = [r["user_id"] for r in c.fetchall()]

        if uid in speed_winners:
            iw = True
        else:
            in_lucky_pool = True

        # Update rounds table with fastest (1st place) winner
        c.execute("SELECT user_id, user_name, time_ms FROM winners WHERE round_id = ? ORDER BY time_ms ASC LIMIT 1", (rid,))
        fastest = c.fetchone()
        if fastest:
            c.execute("UPDATE rounds SET winner_user_id=?,winner_name=?,winner_time_ms=? WHERE id=?",
                     (fastest["user_id"], fastest["user_name"], fastest["time_ms"], rid))

    conn.commit()
    c.execute("SELECT user_name, time_ms FROM attempts WHERE round_id = ? AND is_correct = 1 ORDER BY time_ms ASC LIMIT 10", (rid,))
    lb = [dict(r) for r in c.fetchall()]

    # Get user's rank among all correct users for this round
    rank = None
    c.execute("SELECT user_id FROM winners WHERE round_id = ? ORDER BY time_ms ASC", (rid,))
    for idx, row in enumerate(c.fetchall(), start=1):
        if row["user_id"] == uid:
            rank = idx
            break

    # Challenge auto-check: check if this user has pending challenges as friend
    challenge_result = None
    c.execute("SELECT * FROM challenges WHERE friend_id = ? AND status = 'pending'", (uid,))
    pending_challenges = c.fetchall()
    for pch in pending_challenges:
        # Determine if we should evaluate this challenge based on round matching
        should_evaluate = False
        if rid == pch["challenger_round_id"]:
            # Same round - only evaluate if prize window is still active
            if in_prize_window:
                should_evaluate = True
        elif rid > pch["challenger_round_id"]:
            # Friend played a later round - always evaluate
            should_evaluate = True

        if not should_evaluate:
            continue

        if ic and tms < pch["challenger_time_ms"]:
            # Friend won - beat the challenger's time with 4/4
            c.execute("UPDATE challenges SET status = 'won', friend_time_ms = ?, friend_round_id = ?, completed_at = ? WHERE id = ?",
                     (tms, rid, now, pch["id"]))
            # Auto-create chain challenge with friend's time as new target
            chain_code = generate_challenge_code()
            c.execute("""INSERT INTO challenges (challenge_code, challenger_id, challenger_name, challenger_time_ms, challenger_round_id, status, chain_parent_id, created_at)
                         VALUES (?,?,?,?,?,?,?,?)""", (chain_code, uid, un, tms, rid, "pending", pch["id"], now))
            chain_url = f"https://t.me/Winners_neetbot/Medicneet?startapp=challenge_{chain_code}"
            challenge_result = {
                "status": "won",
                "challenger_name": pch["challenger_name"],
                "challenger_time_ms": pch["challenger_time_ms"],
                "your_time_ms": tms,
                "chain_challenge_code": chain_code,
                "chain_challenge_url": chain_url
            }
        elif ic and tms >= pch["challenger_time_ms"]:
            # Friend got 4/4 but slower - challenger retains the win
            c.execute("UPDATE challenges SET status = 'lost', friend_time_ms = ?, friend_round_id = ?, completed_at = ? WHERE id = ?",
                     (tms, rid, now, pch["id"]))
            challenge_result = {
                "status": "lost",
                "challenger_name": pch["challenger_name"],
                "challenger_time_ms": pch["challenger_time_ms"],
                "your_time_ms": tms,
                "challenge_code": pch["challenge_code"]
            }
        # If not 4/4, leave as pending (they can try next round)

    # Read wallet balance and check cap status
    wallet_balance = None
    wallet_capped = False
    c.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,))
    w = c.fetchone()
    if w:
        wallet_balance = w["balance"]
        wallet_capped = (w["balance"] or 0) >= 50

    # Track played_at for reminder funnel
    try:
        c.execute("UPDATE reminder_logs SET played_at = ? WHERE user_id = ? AND played_at IS NULL AND date(sent_at) >= date(?, '-3 days')", (now, uid, now))
    except:
        pass

    conn.commit()
    conn.close()

    score = sum(1 for r in results if r)

    # Check if user qualifies for MedicPoints offer:
    # Got 4/4 correct but NOT a speed winner and NOT in lucky pool (no cash prize)
    # OR: user is capped (balance >= 50) and got 4/4 — they earn Medic Points instead of cash
    eligible_for_medicpoints = all_correct and not disqualified and (
        (not iw and not in_lucky_pool) or wallet_capped
    )

    # Anti-cheat: hide correct answers and per-question results during prize window
    # so users can't use one account to see answers and another to submit them
    if in_prize_window:
        return {
            "all_correct": all_correct,
            "score": score,
            "results": None,
            "correct_answers": None,
            "explanations": None,
            "your_time_ms": tms,
            "is_current_winner": iw,
            "in_lucky_pool": in_lucky_pool,
            "rank": rank,
            "leaderboard": lb,
            "prize_window_active": True,
            "challenge_result": challenge_result,
            "wallet_balance": wallet_balance,
            "wallet_capped": wallet_capped,
            "eligible_for_medicpoints": eligible_for_medicpoints,
            "medicpoints_amount": 20 if eligible_for_medicpoints else 0,
            "round_id": rid
        }

    return {
        "all_correct": all_correct,
        "score": score,
        "results": results,
        "correct_answers": correct_answers,
        "explanations": None,
        "correct_answers": None,
        "your_time_ms": tms,
        "is_current_winner": iw,
        "in_lucky_pool": in_lucky_pool,
        "rank": rank,
        "leaderboard": lb,
        "prize_window_active": False,
        "challenge_result": challenge_result,
        "wallet_balance": wallet_balance,
        "wallet_capped": wallet_capped,
        "eligible_for_medicpoints": eligible_for_medicpoints,
        "medicpoints_amount": 20 if eligible_for_medicpoints else 0,
        "round_id": rid
    }

@app.get("/api/leaderboard")
async def api_leaderboard():
    conn = get_db(); c = conn.cursor()
    # Get latest round ID
    c.execute("SELECT id FROM rounds ORDER BY id DESC LIMIT 1")
    latest = c.fetchone()
    if not latest:
        conn.close()
        return {"leaderboard": []}
    rid = latest["id"]
    # Get winners for this round (speed first, then lucky, then pool)
    c.execute("SELECT user_name, time_ms, prize_amount as total_won, 1 as wins, winner_type FROM winners WHERE round_id = ? ORDER BY CASE WHEN winner_type = 'speed' THEN 0 WHEN winner_type = 'lucky' THEN 1 ELSE 2 END, time_ms ASC", (rid,))
    lb = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"leaderboard": lb}

@app.get("/api/leaderboard/alltime")
async def api_leaderboard_alltime(user_id: str = None, sort: str = "earnings"):
    """Get top 100 players by total earnings or avg speed"""
    conn = get_db(); c = conn.cursor()

    if sort == "speed":
        c.execute("""
            SELECT
                w.user_id,
                w.user_name,
                w.total_earned,
                CAST(AVG(winners.time_ms) AS INTEGER) as best_time
            FROM wallets w
            INNER JOIN winners ON winners.user_id = w.user_id
            WHERE w.total_earned > 0
            GROUP BY w.user_id
            HAVING best_time IS NOT NULL
            ORDER BY best_time ASC
            LIMIT 100
        """)
    else:
        c.execute("""
            SELECT
                w.user_id,
                w.user_name,
                w.total_earned,
                CAST(AVG(winners.time_ms) AS INTEGER) as best_time
            FROM wallets w
            LEFT JOIN winners ON winners.user_id = w.user_id
            WHERE w.total_earned > 0
            GROUP BY w.user_id
            ORDER BY w.total_earned DESC, best_time ASC
            LIMIT 100
        """)

    leaderboard = []
    user_rank = None

    for idx, row in enumerate(c.fetchall(), start=1):
        entry = {
            "rank": idx,
            "user_id": row["user_id"],
            "user_name": row["user_name"] or "Anonymous",
            "total_earned": row["total_earned"],
            "best_time": row["best_time"]
        }
        leaderboard.append(entry)

        # Track if current user is in top 100
        if user_id and row["user_id"] == user_id:
            user_rank = idx

    conn.close()

    return {
        "leaderboard": leaderboard,
        "user_rank": user_rank
    }

@app.get("/api/history")
async def api_history():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT r.id, r.started_at, r.winner_name, r.winner_time_ms, q.question, q.chapter FROM rounds r JOIN questions q ON q.id = r.question_1_id WHERE r.announced = 1 ORDER BY r.started_at DESC LIMIT 10")
    h = [dict(r) for r in c.fetchall()]; conn.close(); return {"history":h}

@app.get("/api/my-rounds")
async def api_my_rounds(request: Request):
    uid = request.query_params.get("user_id", "")
    if not uid:
        raise HTTPException(400, "user_id required")
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT a.round_id, a.is_correct, a.time_ms, a.selected_answers, a.attempted_at,
            r.question_1_id, r.question_2_id, r.question_3_id, r.question_4_id,
            r.prize_ends_at, r.started_at
        FROM attempts a
        JOIN rounds r ON r.id = a.round_id
        WHERE a.user_id = ?
        ORDER BY a.attempted_at DESC LIMIT 20
    """, (uid,))
    attempts = [dict(r) for r in c.fetchall()]
    
    now = datetime.utcnow()
    result = []
    for a in attempts:
        prize_ended = not a["prize_ends_at"] or datetime.fromisoformat(a["prize_ends_at"]) <= now
        
        entry = {
            "round_id": a["round_id"],
            "score": None,
            "time_ms": a["time_ms"],
            "is_correct": a["is_correct"],
            "attempted_at": a["attempted_at"],
            "prize_ended": prize_ended,
            "questions": None
        }
        
        if prize_ended:
            q_ids = [a["question_1_id"], a["question_2_id"], a["question_3_id"], a["question_4_id"]]
            questions = []
            selected = json.loads(a["selected_answers"]) if a["selected_answers"] else {}
            for i, qid in enumerate(q_ids):
                q = c.execute("SELECT question, option_a, option_b, option_c, option_d, correct_answer, chapter FROM questions WHERE id=?", (qid,)).fetchone()
                if q:
                    user_ans = selected[i] if isinstance(selected, list) and i < len(selected) else (selected.get(str(i), "") if isinstance(selected, dict) else "")
                    questions.append({
                        "text": q["question"],
                        "chapter": q["chapter"],
                        "option_a": q["option_a"],
                        "option_b": q["option_b"],
                        "option_c": q["option_c"],
                        "option_d": q["option_d"],
                        "correct": q["correct_answer"],
                        "your_answer": user_ans,
                        "is_correct": user_ans == q["correct_answer"]
                    })
            entry["questions"] = questions
            entry["score"] = sum(1 for q in questions if q["is_correct"])
        
        result.append(entry)
    
    conn.close()
    return {"rounds": result}

@app.get("/api/app-status")
async def api_app_status():
    return {"status":APP_STATUS,"playstore_link":PLAYSTORE_LINK}

@app.post("/api/notify-email")
async def api_notify_email(request: Request):
    data = await request.json(); email = str(data.get("email","")).strip().lower()
    uid = str(data.get("user_id","")); un = data.get("user_name","")
    if not email or "@" not in email or "." not in email: raise HTTPException(400,"Invalid email")
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO notify_emails (email,user_id,user_name,source) VALUES (?,?,?,'miniapp')", (email,uid,un))
    conn.commit()
    c.execute("SELECT COUNT(*) as cnt FROM notify_emails"); total = c.fetchone()["cnt"]; conn.close()
    return {"success":True,"total_signups":total}

@app.get("/api/notify-count")
async def api_notify_count():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM notify_emails"); t = c.fetchone()["cnt"]; conn.close()
    return {"count":t}

@app.post("/api/sync-sheet")
async def api_sync_sheet():
    return {"synced":sync_questions_from_sheet()}

@app.get("/api/export-emails")
async def api_export_emails():
    send_daily_email_export(); return {"status":"triggered"}

# ─── CHALLENGE SYSTEM ─────────────────────────────────────────

def generate_challenge_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.post("/api/challenge/create")
async def api_challenge_create(request: Request):
    data = await request.json()
    uid = str(data.get("user_id", ""))
    un = data.get("user_name", "Anon")
    rid = data.get("round_id")
    tms = int(data.get("time_ms", 0))
    chain_parent_id = data.get("chain_parent_id")

    if not all([uid, rid, tms]):
        raise HTTPException(400, "Missing fields")

    conn = get_db(); c = conn.cursor()

    # Validate user got 4/4 correct in this round
    c.execute("SELECT is_correct FROM attempts WHERE round_id = ? AND user_id = ?", (rid, uid))
    attempt = c.fetchone()
    if not attempt or attempt["is_correct"] != 1:
        conn.close()
        raise HTTPException(400, "You must score 4/4 to create a challenge")

    # Max 3 active pending challenges per user
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE challenger_id = ? AND status = 'pending'", (uid,))
    if c.fetchone()["cnt"] >= 3:
        conn.close()
        raise HTTPException(400, "Maximum 3 active challenges allowed")

    # One challenge per round per user (skip for chain challenges)
    if not chain_parent_id:
        c.execute("SELECT id FROM challenges WHERE challenger_id = ? AND challenger_round_id = ? AND chain_parent_id IS NULL", (uid, rid))
        if c.fetchone():
            conn.close()
            raise HTTPException(400, "You already created a challenge for this round")

    code = generate_challenge_code()
    now = datetime.utcnow().isoformat()
    c.execute("""INSERT INTO challenges (challenge_code, challenger_id, challenger_name, challenger_time_ms, challenger_round_id, status, chain_parent_id, created_at)
                 VALUES (?,?,?,?,?,?,?,?)""", (code, uid, un, tms, rid, "pending", chain_parent_id, now))
    conn.commit(); conn.close()

    share_url = f"https://t.me/Winners_neetbot/Medicneet?startapp=challenge_{code}"
    return {"challenge_code": code, "share_url": share_url, "challenger_time_ms": tms}

@app.get("/api/challenge/info")
async def api_challenge_info(code: str):
    if not code:
        raise HTTPException(400, "code required")

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM challenges WHERE challenge_code = ?", (code,))
    ch = c.fetchone()
    if not ch:
        conn.close()
        raise HTTPException(404, "Challenge not found")

    result = {
        "challenge_code": ch["challenge_code"],
        "challenger_name": ch["challenger_name"],
        "challenger_time_ms": ch["challenger_time_ms"],
        "challenger_round_id": ch["challenger_round_id"],
        "status": ch["status"],
        "next_round_time": None,
        "current_round_id": None,
        "prize_window_active": False
    }

    # Check current round status
    now_utc = datetime.utcnow().isoformat()
    c.execute("SELECT id, prize_ends_at, ends_at FROM rounds WHERE ends_at > ? ORDER BY started_at DESC LIMIT 1", (now_utc,))
    current_round = c.fetchone()
    if current_round:
        result["current_round_id"] = current_round["id"]
        result["prize_window_active"] = bool(current_round["prize_ends_at"] and now_utc <= current_round["prize_ends_at"])

    # Get next round time from schedule
    now_ist = datetime.now(IST)
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    for hour, minute in SCHEDULED_TIMES_IST:
        scheduled_ist = today_ist.replace(hour=hour, minute=minute)
        if scheduled_ist > now_ist:
            period = "AM" if hour < 12 else "PM"
            display_hour = hour % 12 or 12
            result["next_round_time"] = f"{display_hour}:{minute:02d} {period} IST"
            break

    if not result["next_round_time"]:
        result["next_round_time"] = "7:00 PM IST (tomorrow)"

    conn.close()
    return result

@app.get("/api/challenge/my")
async def api_challenge_my(user_id: str):
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # Sent challenges (user is challenger)
    c.execute("SELECT * FROM challenges WHERE challenger_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,))
    sent = []
    for r in c.fetchall():
        ch = dict(r)
        ch["share_url"] = f"https://t.me/Winners_neetbot/Medicneet?startapp=challenge_{ch['challenge_code']}"
        sent.append(ch)

    # Received challenges (user is friend)
    c.execute("SELECT * FROM challenges WHERE friend_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,))
    received = [dict(r) for r in c.fetchall()]

    # Recent notifications: sent challenges that were completed in last 24 hours
    now = datetime.utcnow()
    cutoff = (now - timedelta(hours=24)).isoformat()
    notifications = []
    for ch in sent:
        if ch["status"] in ("won", "lost") and ch.get("completed_at") and ch["completed_at"] >= cutoff:
            notifications.append({
                "challenge_code": ch["challenge_code"],
                "share_url": ch["share_url"],
                "friend_name": ch.get("friend_name", "Someone"),
                "friend_time_ms": ch.get("friend_time_ms"),
                "challenger_time_ms": ch["challenger_time_ms"],
                "status": ch["status"]
            })

    conn.close()
    return {"sent": sent, "received": received, "notifications": notifications}

@app.get("/api/challenge/stats")
async def api_challenge_stats(user_id: str):
    """Get challenge stats for a user"""
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # As challenger (sent challenges)
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE challenger_id = ?", (user_id,))
    total_sent = c.fetchone()["cnt"]

    # As friend (received challenges)
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE friend_id = ?", (user_id,))
    total_received = c.fetchone()["cnt"]

    # Challenges defended: sent challenges where friend couldn't beat time (status='lost' from friend perspective)
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE challenger_id = ? AND status = 'lost'", (user_id,))
    challenges_defended = c.fetchone()["cnt"]

    # Challenges lost: sent challenges where friend beat time (status='won' from friend perspective)
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE challenger_id = ? AND status = 'won'", (user_id,))
    challenges_lost = c.fetchone()["cnt"]

    # Battles won: as friend, where user beat challenger's time (status='won')
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE friend_id = ? AND status = 'won'", (user_id,))
    battles_won = c.fetchone()["cnt"]

    # Battles lost: as friend, where user couldn't beat time (status='lost')
    c.execute("SELECT COUNT(*) as cnt FROM challenges WHERE friend_id = ? AND status = 'lost'", (user_id,))
    battles_lost = c.fetchone()["cnt"]

    # Best winning time across all challenges (as friend who won or challenger who defended)
    best_time_ms = None
    # Best time when winning as friend (beat challenger)
    c.execute("SELECT MIN(friend_time_ms) as best FROM challenges WHERE friend_id = ? AND status = 'won' AND friend_time_ms IS NOT NULL", (user_id,))
    row = c.fetchone()
    if row and row["best"]:
        best_time_ms = row["best"]
    # Best time from defended challenges (challenger's original time held)
    c.execute("SELECT MIN(challenger_time_ms) as best FROM challenges WHERE challenger_id = ? AND status = 'lost' AND challenger_time_ms IS NOT NULL", (user_id,))
    row = c.fetchone()
    if row and row["best"]:
        if best_time_ms is None or row["best"] < best_time_ms:
            best_time_ms = row["best"]

    # Win streak: consecutive wins in either role, ordered by completion time
    c.execute("""
        SELECT
            CASE
                WHEN challenger_id = ? AND status = 'lost' THEN 'win'
                WHEN friend_id = ? AND status = 'won' THEN 'win'
                ELSE 'loss'
            END as result
        FROM challenges
        WHERE (challenger_id = ? OR friend_id = ?) AND status IN ('won', 'lost')
        ORDER BY completed_at DESC
    """, (user_id, user_id, user_id, user_id))
    win_streak = 0
    for row in c.fetchall():
        if row["result"] == "win":
            win_streak += 1
        else:
            break

    # Challenge score
    score = (battles_won * 3) + (challenges_defended * 2) - (challenges_lost * 1)

    # Rank on leaderboard
    c.execute("""
        SELECT user_id, score FROM (
            SELECT user_id,
                SUM(CASE WHEN role = 'friend' AND status = 'won' THEN 3 ELSE 0 END)
                + SUM(CASE WHEN role = 'challenger' AND status = 'lost' THEN 2 ELSE 0 END)
                - SUM(CASE WHEN role = 'challenger' AND status = 'won' THEN 1 ELSE 0 END)
                as score
            FROM (
                SELECT challenger_id as user_id, 'challenger' as role, status FROM challenges WHERE status IN ('won','lost')
                UNION ALL
                SELECT friend_id as user_id, 'friend' as role, status FROM challenges WHERE status IN ('won','lost') AND friend_id IS NOT NULL
            )
            GROUP BY user_id
        )
        ORDER BY score DESC
    """)
    rank = 0
    for idx, row in enumerate(c.fetchall(), 1):
        if row["user_id"] == user_id:
            rank = idx
            break

    conn.close()
    return {
        "total_challenges_sent": total_sent,
        "total_challenges_received": total_received,
        "challenges_defended": challenges_defended,
        "challenges_lost": challenges_lost,
        "battles_won": battles_won,
        "battles_lost": battles_lost,
        "win_streak": win_streak,
        "best_time_ms": best_time_ms,
        "score": score,
        "rank": rank
    }

@app.get("/api/challenge/leaderboard")
async def api_challenge_leaderboard():
    """Get top 20 users by challenge score"""
    conn = get_db(); c = conn.cursor()

    c.execute("""
        SELECT user_id, user_name,
            SUM(CASE WHEN role = 'friend' AND status = 'won' THEN 3 ELSE 0 END)
            + SUM(CASE WHEN role = 'challenger' AND status = 'lost' THEN 2 ELSE 0 END)
            - SUM(CASE WHEN role = 'challenger' AND status = 'won' THEN 1 ELSE 0 END)
            as score,
            SUM(CASE WHEN role = 'friend' AND status = 'won' THEN 1 ELSE 0 END) as battles_won,
            SUM(CASE WHEN role = 'challenger' AND status = 'lost' THEN 1 ELSE 0 END) as challenges_defended
        FROM (
            SELECT challenger_id as user_id, challenger_name as user_name, 'challenger' as role, status
            FROM challenges WHERE status IN ('won','lost')
            UNION ALL
            SELECT friend_id as user_id, friend_name as user_name, 'friend' as role, status
            FROM challenges WHERE status IN ('won','lost') AND friend_id IS NOT NULL
        )
        GROUP BY user_id
        ORDER BY score DESC
        LIMIT 20
    """)

    leaderboard = []
    for idx, row in enumerate(c.fetchall(), 1):
        leaderboard.append({
            "rank": idx,
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "score": row["score"],
            "battles_won": row["battles_won"],
            "challenges_defended": row["challenges_defended"]
        })

    conn.close()
    return {"leaderboard": leaderboard}

@app.get("/api/challenge/history")
async def api_challenge_history(user_id: str):
    """Get last 20 challenges involving this user"""
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    c.execute("""
        SELECT * FROM challenges
        WHERE challenger_id = ? OR friend_id = ?
        ORDER BY COALESCE(completed_at, created_at) DESC
        LIMIT 20
    """, (user_id, user_id))

    history = []
    for row in c.fetchall():
        ch = dict(row)
        is_challenger = ch["challenger_id"] == user_id
        user_role = "challenger" if is_challenger else "friend"

        if is_challenger:
            opponent_name = ch.get("friend_name") or "Waiting..."
            user_time_ms = ch["challenger_time_ms"]
            opponent_time_ms = ch.get("friend_time_ms")
            # For challenger: 'lost' means they defended (friend couldn't beat), 'won' means friend beat them
            if ch["status"] == "lost":
                result = "won"
            elif ch["status"] == "won":
                result = "lost"
            else:
                result = ch["status"]  # pending/expired
        else:
            opponent_name = ch.get("challenger_name") or "Unknown"
            user_time_ms = ch.get("friend_time_ms")
            opponent_time_ms = ch["challenger_time_ms"]
            # For friend: 'won' means they won, 'lost' means they lost
            result = ch["status"]

        history.append({
            "challenge_code": ch["challenge_code"],
            "opponent_name": opponent_name,
            "user_role": user_role,
            "result": result,
            "user_time_ms": user_time_ms,
            "opponent_time_ms": opponent_time_ms,
            "round_id": ch.get("challenger_round_id"),
            "created_at": ch["created_at"]
        })

    conn.close()
    return {"history": history}

@app.get("/api/wallet")
async def api_wallet(user_id: str):
    """Get wallet balance and transactions for a user"""
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # Get wallet info
    c.execute("SELECT balance, total_earned, upi_id, withdrawal_count FROM wallets WHERE user_id = ?", (user_id,))
    wallet = c.fetchone()

    if not wallet:
        conn.close()
        return {"balance": 0, "total_earned": 0, "upi_id": None, "withdrawal_count": 0, "is_capped": False, "transactions": []}

    balance = wallet["balance"] or 0

    # Get transactions (wins and medic_points_cap)
    c.execute("SELECT amount, type, round_id, created_at FROM transactions WHERE user_id = ? AND type IN ('win', 'medic_points_cap') ORDER BY created_at DESC LIMIT 50", (user_id,))
    transactions = [dict(t) for t in c.fetchall()]

    conn.close()

    return {
        "balance": balance,
        "total_earned": wallet["total_earned"],
        "upi_id": wallet["upi_id"],
        "withdrawal_count": wallet["withdrawal_count"] or 0,
        "is_capped": balance >= 50,
        "transactions": transactions
    }

@app.post("/api/withdraw")
async def api_withdraw(request: Request):
    """Submit withdrawal request"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    user_name = data.get("user_name", "Unknown")
    upi_id = str(data.get("upi_id", "")).strip()

    if not user_id or not upi_id:
        raise HTTPException(400, "user_id and upi_id required")

    if not upi_id or "@" not in upi_id:
        raise HTTPException(400, "Invalid UPI ID format")

    conn = get_db(); c = conn.cursor()

    # Get current wallet balance
    c.execute("SELECT balance, total_earned, user_name FROM wallets WHERE user_id = ?", (user_id,))
    wallet = c.fetchone()

    if not wallet or wallet["balance"] < 50:
        conn.close()
        raise HTTPException(400, "Insufficient balance. Minimum withdrawal is ₹50")

    balance = wallet["balance"]
    total_earned = wallet["total_earned"]
    actual_user_name = wallet["user_name"] or user_name

    # Deduct full balance from wallet
    c.execute("UPDATE wallets SET balance = 0, upi_id = ?, updated_at = ? WHERE user_id = ?",
             (upi_id, datetime.utcnow().isoformat(), user_id))

    # Create withdrawal request
    c.execute("INSERT INTO withdrawal_requests (user_id, user_name, amount, upi_id, status, created_at) VALUES (?,?,?,?,?,?)",
             (user_id, actual_user_name, balance, upi_id, "pending", datetime.utcnow().isoformat()))

    # Create transaction record
    c.execute("INSERT INTO transactions (user_id, amount, type, status, created_at) VALUES (?,?,?,?,?)",
             (user_id, balance, "withdraw", "pending", datetime.utcnow().isoformat()))

    conn.commit()
    conn.close()

    # Send email notification
    send_withdrawal_request_email(user_id, actual_user_name, balance, upi_id, 0, total_earned)

    return {
        "success": True,
        "message": f"Withdrawal requested! You'll receive ₹{balance} within 24 hours",
        "amount": balance
    }

# ─── WITHDRAWAL GATE SYSTEM ──────────────────────────────────────

# In-memory OTP storage: {user_id: {"otp": "123456", "expires": timestamp}}
otp_store = {}

@app.get("/api/withdraw/tasks")
async def api_withdraw_tasks(user_id: str):
    """Get checklist status for all withdrawal tasks (V1 or V2 based on withdrawal_count)"""
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # Determine V1 or V2
    c.execute("SELECT balance, withdrawal_count, upi_id FROM wallets WHERE user_id = ?", (user_id,))
    wallet = c.fetchone()
    balance = wallet["balance"] if wallet else 0
    withdrawal_count = wallet["withdrawal_count"] if wallet else 0
    is_v2 = withdrawal_count >= 1

    if is_v2:
        # ─── V2 TASKS (repeat withdrawers) ─────────────────
        tasks = {}

        # 1. min_balance >= 50
        tasks["min_balance"] = {"completed": balance >= 50, "value": balance}

        # 2. min_rounds >= 20
        c.execute("SELECT COUNT(DISTINCT round_id) as cnt FROM attempts WHERE user_id = ?", (user_id,))
        rounds_played = c.fetchone()["cnt"]
        tasks["min_rounds"] = {"completed": rounds_played >= 20, "value": rounds_played}

        # 3. medic_points: Check Firebase for total >= 2000 * withdrawal_count
        required_points = 2000 * withdrawal_count
        mp_data = get_user_medicpoints(user_id)
        current_points = mp_data.get("points", 0)
        email_linked = mp_data.get("success", False) and mp_data.get("reason") != "No email linked"
        tasks["medic_points"] = {
            "completed": current_points >= required_points,
            "value": current_points,
            "required": required_points,
            "email_linked": email_linked,
            "email": mp_data.get("email"),
            "error": mp_data.get("reason") if not mp_data.get("success") else None
        }

        # 4. ugc_video: Check v2_withdrawal_proofs for uploaded video
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'ugc_video' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ugc_row = c.fetchone()
        tasks["ugc_video"] = {
            "completed": bool(ugc_row and ugc_row["proof_link"]),
            "value": ugc_row["proof_link"] if ugc_row else None
        }

        # 5. refer_5_friends: Count NEW referrals (in current withdrawal cycle)
        c.execute("""SELECT COUNT(*) as cnt FROM referrals r
            WHERE r.referrer_id = ? AND r.withdrawal_cycle = ?
            AND (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) >= 1""",
            (user_id, withdrawal_count))
        v2_referral_count = c.fetchone()["cnt"]

        # Get detailed referral progress for current cycle
        c.execute("""SELECT r.referee_id,
            COALESCE((SELECT user_name FROM attempts WHERE user_id = r.referee_id LIMIT 1), 'Unknown') as name,
            (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) as rounds
            FROM referrals r WHERE r.referrer_id = ? AND r.withdrawal_cycle = ?""",
            (user_id, withdrawal_count))
        v2_referral_details = [{"name": row["name"], "rounds": row["rounds"], "qualified": row["rounds"] >= 1} for row in c.fetchall()]

        tasks["refer_5_friends"] = {"completed": v2_referral_count >= 5, "value": v2_referral_count, "details": v2_referral_details}

        # 6. instagram_post: Check v2_withdrawal_proofs
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'instagram_post' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ig_row = c.fetchone()
        tasks["instagram_post"] = {
            "completed": bool(ig_row and ig_row["proof_link"]),
            "value": ig_row["proof_link"] if ig_row else None
        }

        # 7. otp_verified
        c.execute("SELECT completed FROM withdrawal_tasks WHERE user_id = ? AND task = 'otp_verified'", (user_id,))
        otp_row = c.fetchone()
        tasks["otp_verified"] = {"completed": bool(otp_row and otp_row["completed"])}

        # 8. upi_id
        upi_id = wallet["upi_id"] if wallet and wallet["upi_id"] else None
        tasks["upi_id"] = {"completed": bool(upi_id), "value": upi_id}

        # Generate referral link
        referral_link = f"https://t.me/Winners_neetbot/Medicneet?startapp=ref_{user_id}"

        completed_count = sum(1 for t in tasks.values() if t["completed"])
        conn.close()

        return {
            "version": "v2",
            "withdrawal_count": withdrawal_count,
            "tasks": tasks,
            "completed_count": completed_count,
            "total_count": len(tasks),
            "all_completed": completed_count == len(tasks),
            "referral_link": referral_link
        }

    else:
        # ─── V1 TASKS (first-time withdrawers) ─────────────
        tasks = {}

        # 1. min_balance
        tasks["min_balance"] = {"completed": balance >= 50, "value": balance}

        # 2. min_rounds
        c.execute("SELECT COUNT(DISTINCT round_id) as cnt FROM attempts WHERE user_id = ?", (user_id,))
        rounds_played = c.fetchone()["cnt"]
        tasks["min_rounds"] = {"completed": rounds_played >= 20, "value": rounds_played}

        # 3. medic_points: Check Firebase for total >= 1000
        required_points = 1000
        mp_data = get_user_medicpoints(user_id)
        current_points = mp_data.get("points", 0)
        email_linked = mp_data.get("success", False) and mp_data.get("reason") != "No email linked"
        tasks["medic_points"] = {
            "completed": current_points >= required_points,
            "value": current_points,
            "required": required_points,
            "email_linked": email_linked,
            "email": mp_data.get("email"),
            "error": mp_data.get("reason") if not mp_data.get("success") else None
        }

        # 4. ugc_video: Check v2_withdrawal_proofs for uploaded video
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'ugc_video' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ugc_row = c.fetchone()
        tasks["ugc_video"] = {
            "completed": bool(ugc_row and ugc_row["proof_link"]),
            "value": ugc_row["proof_link"] if ugc_row else None
        }

        # 5-6, 9-10: Click-tracked tasks
        click_tasks = ["install_app", "rate_app", "subscribe_yt", "follow_ig"]
        for task_name in click_tasks:
            c.execute("SELECT completed FROM withdrawal_tasks WHERE user_id = ? AND task = ?", (user_id, task_name))
            row = c.fetchone()
            tasks[task_name] = {"completed": bool(row and row["completed"])}

        # 5. follow_channel
        channel_verified = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                    params={"chat_id": "@bioneettraps", "user_id": user_id}
                )
                data = resp.json()
                if data.get("ok"):
                    status = data["result"].get("status", "")
                    if status in ("member", "administrator", "creator"):
                        channel_verified = True
        except:
            pass
        tasks["follow_channel"] = {"completed": channel_verified}

        # 6. join_group
        group_verified = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                    params={"chat_id": "@neetbiotraps", "user_id": user_id}
                )
                data = resp.json()
                if data.get("ok"):
                    status = data["result"].get("status", "")
                    if status in ("member", "administrator", "creator"):
                        group_verified = True
        except:
            pass
        tasks["join_group"] = {"completed": group_verified}

        # 9. share_friends
        c.execute("SELECT COUNT(*) as cnt FROM referrals r WHERE r.referrer_id = ? AND (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) >= 3", (user_id,))
        referral_count = c.fetchone()["cnt"]

        c.execute("""SELECT r.referee_id,
            COALESCE((SELECT user_name FROM attempts WHERE user_id = r.referee_id LIMIT 1), 'Unknown') as name,
            (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) as rounds
            FROM referrals r WHERE r.referrer_id = ?""", (user_id,))
        referral_details = [{"name": row["name"], "rounds": row["rounds"], "qualified": row["rounds"] >= 3} for row in c.fetchall()]

        tasks["share_friends"] = {"completed": referral_count >= 3, "value": referral_count, "details": referral_details}

        # Generate referral link
        referral_link = f"https://t.me/Winners_neetbot/Medicneet?startapp=ref_{user_id}"

        # 10. upi_id
        w = wallet
        upi_id = w["upi_id"] if w and w["upi_id"] else None
        tasks["upi_id"] = {"completed": bool(upi_id), "value": upi_id}

        # 11. otp_verified
        c.execute("SELECT completed FROM withdrawal_tasks WHERE user_id = ? AND task = 'otp_verified'", (user_id,))
        otp_row = c.fetchone()
        tasks["otp_verified"] = {"completed": bool(otp_row and otp_row["completed"])}

        completed_count = sum(1 for t in tasks.values() if t["completed"])
        conn.close()

        return {
            "version": "v1",
            "withdrawal_count": 0,
            "tasks": tasks,
            "completed_count": completed_count,
            "total_count": len(tasks),
            "all_completed": completed_count == len(tasks),
            "referral_link": referral_link
        }

@app.post("/api/withdraw/complete-task")
async def api_withdraw_complete_task(request: Request):
    """Mark a click-tracked task as completed"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    task = str(data.get("task", ""))

    if not user_id or not task:
        raise HTTPException(400, "user_id and task required")

    # Only allow click-tracked tasks
    allowed_tasks = ["install_app", "rate_app", "subscribe_yt", "follow_ig"]
    if task not in allowed_tasks:
        raise HTTPException(400, f"Task '{task}' cannot be manually completed")

    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO withdrawal_tasks (user_id, task, completed, completed_at) VALUES (?,?,1,?) "
        "ON CONFLICT(user_id, task) DO UPDATE SET completed=1, completed_at=?",
        (user_id, task, now, now)
    )
    conn.commit(); conn.close()

    return {"success": True, "task": task}

@app.post("/api/withdraw/upi")
async def api_withdraw_upi(request: Request):
    """Save UPI ID to wallets table"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    upi_id = str(data.get("upi_id", "")).strip()

    if not user_id or not upi_id:
        raise HTTPException(400, "user_id and upi_id required")

    if "@" not in upi_id:
        raise HTTPException(400, "Invalid UPI ID format")

    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO wallets (user_id, balance, total_earned, upi_id, created_at, updated_at) VALUES (?,0,0,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET upi_id=?, updated_at=?",
        (user_id, upi_id, now, now, upi_id, now)
    )
    conn.commit(); conn.close()

    return {"success": True, "upi_id": upi_id}

@app.post("/api/withdraw/send-otp")
async def api_withdraw_send_otp(request: Request):
    """Generate and send OTP via Telegram"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))

    if not user_id:
        raise HTTPException(400, "user_id required")

    # Generate 6-digit OTP
    otp = str(random.randint(100000, 999999))
    expires = time.time() + 300  # 5 minutes

    # Store in memory
    otp_store[user_id] = {"otp": otp, "expires": expires}

    # Send via Telegram Bot API
    try:
        msg_text = f"Your MedicNEET withdrawal OTP is: {otp}. Valid for 5 minutes."
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": msg_text}
            )
    except Exception as e:
        logger.error(f"Failed to send OTP to {user_id}: {e}")
        raise HTTPException(500, "Failed to send OTP. Please try again.")

    return {"success": True, "message": "OTP sent to your Telegram"}

@app.post("/api/withdraw/verify-otp")
async def api_withdraw_verify_otp(request: Request):
    """Verify OTP and mark as completed"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    otp = str(data.get("otp", "")).strip()

    if not user_id or not otp:
        raise HTTPException(400, "user_id and otp required")

    stored = otp_store.get(user_id)
    if not stored:
        raise HTTPException(400, "No OTP found. Please request a new one.")

    if time.time() > stored["expires"]:
        del otp_store[user_id]
        raise HTTPException(400, "OTP expired. Please request a new one.")

    if stored["otp"] != otp:
        raise HTTPException(400, "Invalid OTP. Please try again.")

    # Mark otp_verified in withdrawal_tasks
    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO withdrawal_tasks (user_id, task, completed, completed_at) VALUES (?,?,1,?) "
        "ON CONFLICT(user_id, task) DO UPDATE SET completed=1, completed_at=?",
        (user_id, "otp_verified", now, now)
    )
    conn.commit(); conn.close()

    # Clean up OTP
    del otp_store[user_id]

    return {"success": True, "message": "OTP verified successfully"}

@app.post("/api/v2-link-email")
async def api_v2_link_email(request: Request):
    """Manually link email for V2 Medic Points verification"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    email = str(data.get("email", "")).strip().lower()

    if not user_id or not email or "@" not in email:
        raise HTTPException(400, "Valid user_id and email required")

    conn = get_db(); c = conn.cursor()

    # Check if this email is already used by another user who has withdrawn
    c.execute("""SELECT DISTINCT telegram_id FROM medicpoints_claims
        WHERE email = ? AND telegram_id != ?""", (email, user_id))
    others = c.fetchall()
    if others:
        other_ids = [r["telegram_id"] for r in others]
        placeholders = ",".join("?" * len(other_ids))
        used = c.execute(
            f"SELECT user_id FROM wallets WHERE user_id IN ({placeholders}) AND withdrawal_count > 0",
            other_ids
        ).fetchone()
        if used:
            conn.close()
            raise HTTPException(400, "This email is already linked to another account")

    # Insert into medicpoints_claims to link the email
    now = datetime.utcnow().isoformat()
    c.execute("""INSERT INTO medicpoints_claims (telegram_id, telegram_name, email, round_id, points, firebase_preloaded, created_at)
        VALUES (?, ?, ?, 0, 0, 0, ?)""",
        (user_id, "", email, now))
    conn.commit(); conn.close()

    # Verify the email exists in Firebase
    mp_data = get_user_medicpoints(user_id)

    return {
        "success": True,
        "email": email,
        "points": mp_data.get("points", 0),
        "found_in_firebase": mp_data.get("success", False)
    }

@app.post("/api/v2-withdrawal-proof")
async def api_v2_withdrawal_proof(request: Request):
    """Submit V2 withdrawal proof (Instagram link)"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    task = str(data.get("task", ""))
    proof_link = str(data.get("proof_link", "")).strip()

    if not user_id or not task or not proof_link:
        raise HTTPException(400, "user_id, task, and proof_link required")

    if task not in ("instagram_post",):
        raise HTTPException(400, f"Invalid task: {task}")

    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()

    # Upsert proof
    c.execute("""INSERT INTO v2_withdrawal_proofs (user_id, task, proof_link, created_at)
        VALUES (?,?,?,?)""", (user_id, task, proof_link, now))

    conn.commit(); conn.close()
    return {"success": True, "task": task, "proof_link": proof_link}

@app.post("/api/v2-upload-video")
async def api_v2_upload_video(request: Request):
    """Upload UGC video to Google Drive for V2 withdrawal"""
    from fastapi import UploadFile, File, Form

    form = await request.form()
    user_id = str(form.get("user_id", ""))
    video_file = form.get("video")

    if not user_id or not video_file:
        raise HTTPException(400, "user_id and video file required")

    # Read file content
    content = await video_file.read()
    if len(content) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(400, "File too large. Maximum 100MB.")

    # Get content type
    content_type = video_file.content_type or "video/mp4"
    filename = f"ugc_{user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{video_file.filename}"

    # Upload to Google Drive
    result = upload_to_google_drive(content, filename, content_type)

    if not result["success"]:
        raise HTTPException(500, f"Upload failed: {result.get('reason', 'Unknown error')}")

    # Save proof link in DB
    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("""INSERT INTO v2_withdrawal_proofs (user_id, task, proof_link, created_at)
        VALUES (?,?,?,?)""", (user_id, "ugc_video", result["link"], now))
    conn.commit(); conn.close()

    return {"success": True, "link": result["link"]}

@app.post("/api/withdraw/request")
async def api_withdraw_request(request: Request):
    """Submit withdrawal request - only if ALL tasks completed (V1 or V2)"""
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    amount = data.get("amount")

    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # Verify balance and get withdrawal_count
    c.execute("SELECT balance, total_earned, user_name, upi_id, withdrawal_count FROM wallets WHERE user_id = ?", (user_id,))
    wallet = c.fetchone()
    if not wallet or wallet["balance"] < 50:
        conn.close()
        raise HTTPException(400, "Insufficient balance. Minimum withdrawal is ₹50")

    if not wallet["upi_id"]:
        conn.close()
        raise HTTPException(400, "UPI ID not saved")

    balance = wallet["balance"]
    total_earned = wallet["total_earned"]
    user_name = wallet["user_name"] or "Unknown"
    upi_id = wallet["upi_id"]
    withdrawal_count = wallet["withdrawal_count"] or 0
    is_v2 = withdrawal_count >= 1

    # Verify min_rounds
    c.execute("SELECT COUNT(DISTINCT round_id) as cnt FROM attempts WHERE user_id = ?", (user_id,))
    if c.fetchone()["cnt"] < 20:
        conn.close()
        raise HTTPException(400, "Need at least 20 rounds played")

    # Verify OTP
    c.execute("SELECT completed FROM withdrawal_tasks WHERE user_id = ? AND task = 'otp_verified'", (user_id,))
    otp_row = c.fetchone()
    if not otp_row or not otp_row["completed"]:
        conn.close()
        raise HTTPException(400, "OTP not verified")

    if is_v2:
        # ─── V2 VERIFICATION ─────────────────────────────
        # Verify Medic Points
        required_points = 2000 * withdrawal_count
        mp_data = get_user_medicpoints(user_id)
        if mp_data.get("points", 0) < required_points:
            conn.close()
            raise HTTPException(400, f"Need at least {required_points} Medic Points")

        # Verify UGC video uploaded
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'ugc_video' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ugc_row = c.fetchone()
        if not ugc_row or not ugc_row["proof_link"]:
            conn.close()
            raise HTTPException(400, "UGC video not uploaded")
        ugc_video_link = ugc_row["proof_link"]

        # Verify 5 new referrals in current cycle
        c.execute("""SELECT COUNT(*) as cnt FROM referrals r
            WHERE r.referrer_id = ? AND r.withdrawal_cycle = ?
            AND (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) >= 1""",
            (user_id, withdrawal_count))
        if c.fetchone()["cnt"] < 5:
            conn.close()
            raise HTTPException(400, "Need at least 5 new referrals")

        # Verify Instagram post
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'instagram_post' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ig_row = c.fetchone()
        if not ig_row or not ig_row["proof_link"]:
            conn.close()
            raise HTTPException(400, "Instagram post not submitted")
        ig_post_link = ig_row["proof_link"]

    else:
        # ─── V1 VERIFICATION ─────────────────────────────
        # Verify Medic Points >= 1000
        required_points = 1000
        mp_data = get_user_medicpoints(user_id)
        if mp_data.get("points", 0) < required_points:
            conn.close()
            raise HTTPException(400, f"Need at least {required_points} Medic Points")

        # Verify UGC video uploaded
        c.execute("SELECT proof_link FROM v2_withdrawal_proofs WHERE user_id = ? AND task = 'ugc_video' ORDER BY created_at DESC LIMIT 1", (user_id,))
        ugc_row = c.fetchone()
        if not ugc_row or not ugc_row["proof_link"]:
            conn.close()
            raise HTTPException(400, "UGC video not uploaded")
        ugc_video_link = ugc_row["proof_link"]

        # Verify click-tracked tasks
        for task_name in ["install_app", "rate_app", "subscribe_yt", "follow_ig"]:
            c.execute("SELECT completed FROM withdrawal_tasks WHERE user_id = ? AND task = ?", (user_id, task_name))
            row = c.fetchone()
            if not row or not row["completed"]:
                conn.close()
                raise HTTPException(400, f"Task '{task_name}' not completed")

        # Verify referrals >= 3
        c.execute("SELECT COUNT(*) as cnt FROM referrals r WHERE r.referrer_id = ? AND (SELECT COUNT(DISTINCT round_id) FROM attempts WHERE user_id = r.referee_id) >= 3", (user_id,))
        if c.fetchone()["cnt"] < 3:
            conn.close()
            raise HTTPException(400, "Need at least 3 referrals")

        # Verify Telegram channel/group
        channel_ok = False
        group_ok = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                    params={"chat_id": "@bioneettraps", "user_id": user_id}
                )
                d = resp.json()
                if d.get("ok") and d["result"].get("status") in ("member", "administrator", "creator"):
                    channel_ok = True
        except:
            pass

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                    params={"chat_id": "@neetbiotraps", "user_id": user_id}
                )
                d = resp.json()
                if d.get("ok") and d["result"].get("status") in ("member", "administrator", "creator"):
                    group_ok = True
        except:
            pass

        if not channel_ok:
            conn.close()
            raise HTTPException(400, "Please follow @bioneettraps channel first")
        if not group_ok:
            conn.close()
            raise HTTPException(400, "Please join @neetbiotraps group first")

    # All checks passed - process withdrawal
    withdraw_amount = amount if amount and amount <= balance else balance
    now = datetime.utcnow().isoformat()

    c.execute("UPDATE wallets SET balance = balance - ?, withdrawal_count = withdrawal_count + 1, updated_at = ? WHERE user_id = ?",
             (withdraw_amount, now, user_id))
    c.execute("INSERT INTO withdrawal_requests (user_id, user_name, amount, upi_id, status, created_at) VALUES (?,?,?,?,?,?)",
             (user_id, user_name, withdraw_amount, upi_id, "pending", now))
    c.execute("INSERT INTO transactions (user_id, amount, type, status, created_at) VALUES (?,?,?,?,?)",
             (user_id, withdraw_amount, "withdraw", "pending", now))

    if is_v2:
        # Reset OTP for next withdrawal cycle
        c.execute("DELETE FROM withdrawal_tasks WHERE user_id = ? AND task = 'otp_verified'", (user_id,))
        # Clean up V2 proofs for next cycle
        c.execute("DELETE FROM v2_withdrawal_proofs WHERE user_id = ?", (user_id,))
        # Mark future referrals with new cycle number
        # (existing referrals keep their cycle, new ones will get the incremented count)

    else:
        # V1 -> V2 transition: reset OTP for next cycle
        c.execute("DELETE FROM withdrawal_tasks WHERE user_id = ? AND task = 'otp_verified'", (user_id,))
        # Clean up UGC proofs for next cycle
        c.execute("DELETE FROM v2_withdrawal_proofs WHERE user_id = ?", (user_id,))
        # Mark all existing referrals as cycle 0 (already used for V1)
        c.execute("UPDATE referrals SET withdrawal_cycle = 0 WHERE referrer_id = ? AND withdrawal_cycle = 0", (user_id,))

    conn.commit(); conn.close()

    # Send email notification
    if is_v2:
        send_v2_withdrawal_request_email(user_id, user_name, withdraw_amount, upi_id,
            balance - withdraw_amount, total_earned, ugc_video_link, ig_post_link,
            mp_data.get("points", 0), required_points)
    else:
        send_withdrawal_request_email(user_id, user_name, withdraw_amount, upi_id, balance - withdraw_amount, total_earned,
            ugc_video_link, mp_data.get("points", 0), required_points)

    return {
        "success": True,
        "message": f"Withdrawal of \u20b9{withdraw_amount} requested! You'll receive payment within 24 hours.",
        "amount": withdraw_amount
    }

@app.post("/api/referral")
async def api_referral(request: Request):
    """Log a referral when new user opens mini app with ref_ startapp param"""
    data = await request.json()
    referrer_id = str(data.get("referrer_id", ""))
    referee_id = str(data.get("referee_id", ""))

    if not referrer_id or not referee_id:
        raise HTTPException(400, "referrer_id and referee_id required")

    if referrer_id == referee_id:
        return {"success": False, "message": "Cannot refer yourself"}

    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()

    # Get referrer's current withdrawal_count to tag the referral with the right cycle
    c.execute("SELECT withdrawal_count FROM wallets WHERE user_id = ?", (referrer_id,))
    w = c.fetchone()
    cycle = w["withdrawal_count"] if w else 0

    try:
        c.execute("INSERT OR IGNORE INTO referrals (referrer_id, referee_id, withdrawal_cycle, created_at) VALUES (?,?,?,?)",
                 (referrer_id, referee_id, cycle, now))
        conn.commit()
    except:
        pass
    conn.close()

    return {"success": True}


@app.post("/api/track-click")
async def api_track_click(request: Request):
    data = await request.json()
    user_id = str(data.get("user_id", ""))
    source = data.get("source", "unknown")
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO app_clicks (user_id, source) VALUES (?, ?)", (user_id, source))
    conn.commit(); conn.close()
    return {"success": True}

@app.post("/api/track-study")
async def api_track_study(request: Request):
    data = await request.json()
    uid = str(data.get("user_id", ""))
    event_type = str(data.get("event_type", ""))
    item_name = str(data.get("item_name", ""))
    item_url = str(data.get("item_url", ""))
    if not uid or not event_type:
        raise HTTPException(400, "user_id and event_type required")
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO study_events (user_id, event_type, item_name, item_url) VALUES (?,?,?,?)",
              (uid, event_type, item_name, item_url))
    conn.commit(); conn.close()
    return {"success": True}

@app.post("/api/track")
async def api_track(request: Request, user_id: str = ""):
    try:
        data = await request.json()
        event = str(data.get("event", ""))
        if not event:
            raise HTTPException(400, "event required")
        evt_data = json.dumps(data.get("data", {}))
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO analytics (user_id, event, data) VALUES (?, ?, ?)",
                  (user_id, event, evt_data))
        conn.commit(); conn.close()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        return {"success": False}

@app.get("/api/stats")
async def api_stats(user_id: str):
    """Get user's personal stats including rank and performance metrics"""
    if not user_id:
        raise HTTPException(400, "user_id required")

    conn = get_db(); c = conn.cursor()

    # Get wallet info (balance and total_earned)
    c.execute("SELECT balance, total_earned FROM wallets WHERE user_id = ?", (user_id,))
    wallet = c.fetchone()

    current_balance = wallet["balance"] if wallet else 0
    total_earned = wallet["total_earned"] if wallet else 0

    # Get best time from winners table
    c.execute("SELECT MIN(time_ms) as best_time FROM winners WHERE user_id = ?", (user_id,))
    best_time_row = c.fetchone()
    best_time = best_time_row["best_time"] if best_time_row and best_time_row["best_time"] else None

    # Get rounds played (distinct rounds in attempts table)
    c.execute("SELECT COUNT(DISTINCT round_id) as rounds_played FROM attempts WHERE user_id = ?", (user_id,))
    rounds_played_row = c.fetchone()
    rounds_played = rounds_played_row["rounds_played"] if rounds_played_row else 0

    # Get rounds won (count of wins in winners table)
    c.execute("SELECT COUNT(*) as rounds_won FROM winners WHERE user_id = ?", (user_id,))
    rounds_won_row = c.fetchone()
    rounds_won = rounds_won_row["rounds_won"] if rounds_won_row else 0

    # Calculate win rate
    win_rate = round((rounds_won / rounds_played * 100) if rounds_played > 0 else 0, 1)

    # Calculate rank based on total_earned (same logic as leaderboard)
    c.execute("""
        SELECT COUNT(*) + 1 as rank
        FROM wallets w1
        WHERE w1.total_earned > (
            SELECT COALESCE(total_earned, 0)
            FROM wallets
            WHERE user_id = ?
        )
    """, (user_id,))
    rank_row = c.fetchone()
    rank = rank_row["rank"] if rank_row else None

    # Get total number of players with earnings
    c.execute("SELECT COUNT(*) as total_players FROM wallets WHERE total_earned > 0")
    total_players_row = c.fetchone()
    total_players = total_players_row["total_players"] if total_players_row else 0

    conn.close()

    if total_earned == 0:
        rank = None
    return {
        "rank": rank,
        "total_players": total_players,
        "total_earned": total_earned,
        "current_balance": current_balance,
        "best_time": best_time,
        "rounds_played": rounds_played,
        "rounds_won": rounds_won,
        "win_rate": win_rate
    }

@app.get("/api/rounds/history")
async def api_rounds_history():
    """Get list of past rounds with winner info and participant count"""
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT
            r.id as round_id,
            r.started_at as date,
            r.winner_name,
            r.winner_time_ms as winning_time,
            COUNT(DISTINCT a.user_id) as total_participants
        FROM rounds r
        LEFT JOIN attempts a ON a.round_id = r.id
        WHERE r.announced = 1
        GROUP BY r.id
        ORDER BY r.started_at DESC
        LIMIT 50
    """)
    rounds = []
    for row in c.fetchall():
        rounds.append({
            "round_id": row["round_id"],
            "date": row["date"],
            "winner_name": row["winner_name"] or "No winner",
            "winning_time": row["winning_time"],
            "total_participants": row["total_participants"]
        })
    conn.close()
    return {"rounds": rounds}

@app.get("/api/rounds/practice")
async def api_rounds_practice(round_id: int):
    """Get questions for a specific past round for practice"""
    conn = get_db(); c = conn.cursor()

    # Get round info
    c.execute("SELECT * FROM rounds WHERE id = ? AND announced = 1", (round_id,))
    rnd = c.fetchone()
    if not rnd:
        conn.close()
        raise HTTPException(404, "Round not found")

    # Fetch all 4 questions with correct answers and explanations
    q_ids = [rnd["question_1_id"], rnd["question_2_id"], rnd["question_3_id"], rnd["question_4_id"]]
    c.execute("SELECT * FROM questions WHERE id IN (?,?,?,?)", q_ids)
    questions_raw = c.fetchall()
    questions_dict = {q["id"]: q for q in questions_raw}

    questions = [
        {
            "text": questions_dict[q_id]["question"],
            "option_a": questions_dict[q_id]["option_a"],
            "option_b": questions_dict[q_id]["option_b"],
            "option_c": questions_dict[q_id]["option_c"],
            "option_d": questions_dict[q_id]["option_d"],
            "correct_answer": questions_dict[q_id]["correct_answer"],
            "explanation": questions_dict[q_id]["explanation"] or "",
            "chapter": questions_dict[q_id]["chapter"]
        }
        for q_id in q_ids if q_id in questions_dict
    ]

    # Get round winner info
    c.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM attempts WHERE round_id = ?", (round_id,))
    total_participants = c.fetchone()["cnt"]

    conn.close()

    return {
        "round_id": rnd["id"],
        "date": rnd["started_at"],
        "winner_name": rnd["winner_name"],
        "winner_time_ms": rnd["winner_time_ms"],
        "total_participants": total_participants,
        "questions": questions
    }

@app.post("/api/rounds/practice/submit")
async def api_rounds_practice_submit(request: Request):
    """Submit practice answers (no prizes, just show results)"""
    data = await request.json()
    round_id = data.get("round_id")
    answers = data.get("answers", [])  # Array of 4 answers
    time_ms = int(data.get("time_ms", 0))

    if not round_id or not isinstance(answers, list) or len(answers) != 4:
        raise HTTPException(400, "Missing fields or invalid answers format")

    # Normalize answers
    answers = [str(a).upper().strip() for a in answers]

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM rounds WHERE id = ? AND announced = 1", (round_id,))
    rnd = c.fetchone()
    if not rnd:
        conn.close()
        raise HTTPException(404, "Round not found")

    # Fetch all 4 questions and their correct answers
    q_ids = [rnd["question_1_id"], rnd["question_2_id"], rnd["question_3_id"], rnd["question_4_id"]]
    c.execute("SELECT id, correct_answer, explanation FROM questions WHERE id IN (?,?,?,?)", q_ids)
    questions_raw = c.fetchall()
    questions_dict = {q["id"]: q for q in questions_raw}

    # Check each answer
    correct_answers = []
    explanations = []
    results = []
    score = 0

    for i, q_id in enumerate(q_ids):
        if q_id in questions_dict:
            correct_ans = questions_dict[q_id]["correct_answer"]
            user_ans = answers[i] if i < len(answers) else ""
            is_correct = user_ans == correct_ans

            correct_answers.append(correct_ans)
            explanations.append(questions_dict[q_id]["explanation"] or "")
            results.append(is_correct)

            if is_correct:
                score += 1
        else:
            correct_answers.append("?")
            explanations.append("")
            results.append(False)

    conn.close()

    return {
        "score": score,
        "total": 4,
        "results": results,
        "correct_answers": correct_answers,
        "explanations": explanations,
        "your_time_ms": time_ms,
        "round_winner_name": rnd["winner_name"],
        "round_winner_time_ms": rnd["winner_time_ms"]
    }

# ─── BLOG API ───────────────────────────────────────────────────────

@app.get("/api/blogs")
async def api_blogs():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, title, slug, excerpt, thumbnail_emoji, medium_url, category, is_featured, created_at FROM blogs ORDER BY created_at DESC")
    blogs = [dict(r) for r in c.fetchall()]
    conn.close()
    for b in blogs:
        b["site_url"] = f"https://www.medicneet.com/blog/{b['slug']}"
    return {"blogs": blogs}

@app.get("/api/blogs/featured")
async def api_blogs_featured():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, title, slug, excerpt, thumbnail_emoji, medium_url, category, created_at FROM blogs WHERE is_featured = 1 LIMIT 1")
    blog = c.fetchone()
    conn.close()
    if not blog:
        return JSONResponse({"error": "No featured blog"}, status_code=404)
    result = dict(blog)
    result["site_url"] = f"https://www.medicneet.com/blog/{result['slug']}"
    return result

@app.post("/api/blogs/featured")
async def api_set_featured_blog(request: Request):
    data = await request.json()
    blog_id = data.get("blog_id")
    if not blog_id:
        raise HTTPException(400, "blog_id required")
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE blogs SET is_featured = 0")
    c.execute("UPDATE blogs SET is_featured = 1 WHERE id = ?", (blog_id,))
    conn.commit(); conn.close()
    return {"success": True}

@app.post("/api/blogs")
async def api_add_blog(request: Request):
    data = await request.json()
    title = data.get("title", "")
    slug = data.get("slug", "")
    excerpt = data.get("excerpt", "")
    thumbnail_emoji = data.get("thumbnail_emoji", "📝")
    medium_url = data.get("medium_url", "")
    category = data.get("category", "strategy")
    if not all([title, slug, excerpt, medium_url]):
        raise HTTPException(400, "title, slug, excerpt, medium_url required")
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO blogs (title, slug, excerpt, thumbnail_emoji, medium_url, category) VALUES (?,?,?,?,?,?)",
              (title, slug, excerpt, thumbnail_emoji, medium_url, category))
    blog_id = c.lastrowid
    conn.commit(); conn.close()
    return {"success": True, "blog_id": blog_id}

@app.delete("/api/blogs/{blog_id}")
async def api_delete_blog(blog_id: int):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM blogs WHERE id = ?", (blog_id,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(404, "Blog not found")
    c.execute("DELETE FROM blogs WHERE id = ?", (blog_id,))
    conn.commit(); conn.close()
    return {"success": True, "deleted_id": blog_id}

# ─── NCERT PYQ-MARKED READER ──────────────────────────────────────
NCERT_JSON_PATH = os.path.join("static", "ncert", "ncert_pyq_highlighted_v3.json")
_ncert_cache = None

FREE_CHAPTERS = [
    {"class": "Class 11", "chapter": 1},
    {"class": "Class 11", "chapter": 6},
    {"class": "Class 11", "chapter": 7},
    {"class": "Class 11", "chapter": 18},
]

def _load_ncert():
    global _ncert_cache
    if _ncert_cache is None:
        with open(NCERT_JSON_PATH, "r", encoding="utf-8") as f:
            _ncert_cache = json.load(f)
    return _ncert_cache

def _is_chapter_free(ch):
    return any(fc["class"] == ch["class"] and fc["chapter"] == ch["chapter_number"] for fc in FREE_CHAPTERS)

@app.get("/api/ncert/chapters")
async def api_ncert_chapters():
    """Return lightweight chapter list with metadata (no content)."""
    data = _load_ncert()
    chapters = []
    for ch in data["chapters"]:
        chapter_id = f"class{ch['class'].replace('Class ', '')}-ch{ch['chapter_number']}"
        chapters.append({
            "id": chapter_id,
            "chapter_number": ch["chapter_number"],
            "chapter_name": ch["chapter_name"],
            "class": ch["class"],
            "total_pyqs": ch["total_pyqs"],
            "total_paragraphs": ch["total_paragraphs"],
            "is_free": _is_chapter_free(ch),
        })
    return {
        "total_chapters": data["total_chapters"],
        "total_pyqs": data["total_pyqs"],
        "total_predicted": data["total_predicted"],
        "chapters": chapters,
    }

@app.get("/api/ncert/chapter/{chapter_id}")
async def api_ncert_chapter(chapter_id: str):
    """Return full content for a single chapter. Only free chapters served."""
    import re
    m = re.match(r"^class(\d+)-ch(\d+)$", chapter_id)
    if not m:
        raise HTTPException(400, "Invalid chapter ID format. Use class11-ch5")
    class_num, ch_num = m.group(1), int(m.group(2))
    data = _load_ncert()
    for ch in data["chapters"]:
        if ch["class"] == f"Class {class_num}" and ch["chapter_number"] == ch_num:
            if not _is_chapter_free(ch):
                return {"locked": True, "chapter_name": ch["chapter_name"], "chapter_id": chapter_id}
            paragraphs = []
            for page in ch["pages"]:
                for item in page["content"]:
                    if item["type"] == "paragraph":
                        paragraphs.append(item)
            pyq_count = sum(len(p.get("pyqs", [])) for p in paragraphs)
            predicted_count = sum(1 for p in paragraphs if p.get("predicted"))
            return {
                "locked": False,
                "chapter_id": chapter_id,
                "chapter_number": ch["chapter_number"],
                "chapter_name": ch["chapter_name"],
                "class": ch["class"],
                "total_pyqs": pyq_count,
                "total_predicted": predicted_count,
                "total_paragraphs": len(paragraphs),
                "paragraphs": paragraphs,
            }
    raise HTTPException(404, "Chapter not found")


# ─── MEDICPOINTS API ─────────────────────────────────────────────

@app.post("/api/medicpoints/claim")
async def api_medicpoints_claim(request: Request):
    """
    Claim MedicPoints by entering email.
    Called when user gets 4/4 but no cash prize.
    Preloads 20 points into their Firebase account (or pending if new user).
    """
    data = await request.json()
    email = data.get("email", "").strip()
    uid = str(data.get("user_id", ""))
    un = data.get("user_name", "Anon")
    round_id = data.get("round_id")

    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    if not uid or not round_id:
        raise HTTPException(400, "user_id and round_id required")

    result = preload_points_for_email(
        email=email,
        telegram_id=uid,
        telegram_name=un,
        round_id=round_id,
    )

    return result


@app.get("/api/medicpoints/status")
async def api_medicpoints_status(request: Request):
    """Check if user already claimed MedicPoints for a round."""
    uid = request.query_params.get("user_id", "")
    round_id = request.query_params.get("round_id")
    if not uid or not round_id:
        raise HTTPException(400, "user_id and round_id required")
    return get_claim_status(uid, int(round_id))
