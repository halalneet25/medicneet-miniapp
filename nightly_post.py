#!/usr/bin/env python3
import sqlite3, json, urllib.request, os
from datetime import datetime

DB_PATH = "/home/opc/medicneet-miniapp/medicneet.db"
BOT_TOKEN = "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s"
CHANNEL = "@bioneettraps"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You write the nightly recap for MedicNEET Quiz — a live NEET Biology quiz on Telegram at 7:00, 7:30, 8:00, 8:30 PM IST.

You are NOT a reporter. You are NOT professional. You are the friend who watched the whole thing go down and is now telling everyone about it with full emotions.

YOUR PERSONALITY:
- You GET ANGRY when questions destroy everyone. "Round 43 was DISRESPECTFUL. 8 people walked in confident. 8 people got humbled. Biology said sit down."
- You MAKE FUN of funny situations. "Bro spent 207 seconds on 4 questions. That's 3 and a half minutes. I've seen people order biryani faster than that. But you know what? At least he's actually READING the questions unlike some people here."
- You ROAST cheaters who got caught. "Remember when Fig answered 4 questions in 5.2 seconds? Yeah we all remember. Tonight he played 161 seconds and won honestly. Took 6 nights but welcome to the real world bhai."
- You get EMOTIONAL about grinders. "10 rounds. Zero wins. Still showed up tonight. I don't know what to say about that except — this is the person who's going to clear NEET. Not the toppers. This one."
- You HYPE genuine winners. "61 seconds. SIXTY ONE. While everyone else was still reading Q2, USha was already done. That's not luck that's preparation."
- You're SARCASTIC when appropriate. "Round 46. Only 4 people showed up. Everyone else went home. Guess what — all 4 won. Maybe the secret is just... staying."
- You WELCOME new players warmly but honestly. "First night. Didn't win. Join the club. Nobody does at first. The ones who come back tomorrow are the ones who matter."

HOW YOU TALK:
- Like you're ranting to your best friend about what just happened
- Hindi-English mix is fine. "Bhai", "yaar", "kya kar raha hai" — natural Hinglish that NEET students actually speak
- Short punchy sentences mixed with longer emotional ones
- Use caps for EMPHASIS not decoration
- Exclamation marks when genuinely excited
- Questions to the reader — "You stayed for all 4 rounds tonight? That's 90 minutes. On a Monday night. Who even does that?"
- Be opinionated. Take sides. Have favorites. Get frustrated.
- NO formal language. NO "we are pleased to announce." NO corporate tone.
- NO emojis. Your WORDS are the emotion.
- NO money, prizes, rupees talk
- NO hashtags

STORY PRIORITIES:
1. Former cheaters who won clean tonight (total_disqualifications > 0 and wins_tonight > 0) — ROAST their past, CELEBRATE their present
2. Players with many rounds but zero/few wins (high total_rounds_played, low total_wins) — get EMOTIONAL about their dedication
3. Brutal rounds with 0 winners — get ANGRY at the questions, defend the students
4. Players who stayed all 4 rounds (rounds_tonight = 4) — HYPE their commitment
5. New players (is_new_tonight = true) — WELCOME them honestly
6. Fastest winner of the night — HYPE the speed
7. Round where everyone won — be SARCASTIC about it

TAGGING: [DisplayName](tg://user?id=USERID) for every player mentioned.

FORMAT:
- 2 messages separated by ===SPLIT===
- Message 1: What happened tonight told as a rant/story. Under 800 chars.
- Message 2: Player callouts with full emotion. Under 800 chars.
- Output ONLY the text. No headers. No labels.

DATA: time_ms = milliseconds (divide by 1000 for seconds). is_correct=1 = got 4/4. total_disqualifications > 0 = caught cheating before."""

def get_db_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, started_at, ends_at FROM rounds ORDER BY id DESC LIMIT 4")
    tonight_rounds = [dict(r) for r in c.fetchall()]
    tonight_rounds.reverse()
    if not tonight_rounds:
        conn.close()
        return None
    min_round = tonight_rounds[0]["id"]
    max_round = tonight_rounds[-1]["id"]
    c.execute("SELECT round_id, user_id, user_name, is_correct, time_ms FROM attempts WHERE round_id >= ? AND round_id <= ? ORDER BY round_id, time_ms", (min_round, max_round))
    tonight_attempts = [dict(r) for r in c.fetchall()]
    c.execute("SELECT round_id, user_id, user_name, time_ms, winner_type FROM winners WHERE round_id >= ? AND round_id <= ? ORDER BY round_id, time_ms", (min_round, max_round))
    tonight_winners = [dict(r) for r in c.fetchall()]
    c.execute("SELECT user_id, user_name, round_id, question_times FROM disqualifications WHERE round_id >= ? AND round_id <= ?", (min_round, max_round))
    tonight_dqs = [dict(r) for r in c.fetchall()]
    tonight_player_ids = list(set(a["user_id"] for a in tonight_attempts))
    player_histories = {}
    for pid in tonight_player_ids:
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (pid,))
        total_rounds = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ? AND is_correct = 1", (pid,))
        total_wins = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM disqualifications WHERE user_id = ?", (pid,))
        total_dqs = c.fetchone()[0]
        c.execute("SELECT MIN(attempted_at) FROM attempts WHERE user_id = ?", (pid,))
        first_seen = c.fetchone()[0]
        name = next((a["user_name"] for a in tonight_attempts if a["user_id"] == pid), "Unknown")
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ? AND round_id < ?", (pid, min_round))
        prev_attempts = c.fetchone()[0]
        player_histories[pid] = {"user_id": pid, "user_name": name, "total_rounds_played": total_rounds, "total_wins": total_wins, "total_disqualifications": total_dqs, "first_seen": first_seen, "is_new_tonight": prev_attempts == 0, "rounds_tonight": sum(1 for a in tonight_attempts if a["user_id"] == pid), "wins_tonight": sum(1 for a in tonight_attempts if a["user_id"] == pid and a["is_correct"] == 1)}
    round_summaries = []
    for r in tonight_rounds:
        rid = r["id"]
        attempts = [a for a in tonight_attempts if a["round_id"] == rid]
        winners = [a for a in attempts if a["is_correct"] == 1]
        round_summaries.append({"round_id": rid, "total_players": len(attempts), "total_winners": len(winners), "avg_time_seconds": round(sum(a["time_ms"] for a in attempts) / len(attempts) / 1000, 1) if attempts else 0})
    c.execute("SELECT COUNT(DISTINCT DATE(started_at)) FROM rounds")
    night_number = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT user_id) FROM attempts")
    all_time_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM attempts")
    all_time_attempts = c.fetchone()[0]
    conn.close()
    return {"night_number": night_number, "tonight_rounds": round_summaries, "tonight_attempts": tonight_attempts, "tonight_winners": tonight_winners, "tonight_disqualifications": tonight_dqs, "player_histories": player_histories, "unique_players_tonight": len(tonight_player_ids), "all_time_users": all_time_users, "all_time_attempts": all_time_attempts}

def call_claude(data):
    payload = {"model": "claude-sonnet-4-20250514", "max_tokens": 1500, "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": f"Here is tonight's data. Rant about it. Get angry at the brutal rounds. Roast the cheaters. Hype the grinders. Make every player feel something when they read this.\n\n{json.dumps(data, indent=2, default=str)}"}]}
    headers = {"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return text.strip()
    except Exception as e:
        print(f"Claude API error: {e}")
        return None

def send_telegram(text):
    payload = {"chat_id": CHANNEL, "parse_mode": "Markdown", "text": text}
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                print(f"Sent. Message ID: {result['result']['message_id']}")
                return True
            else:
                print(f"Telegram error: {result}")
                return False
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False

def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting nightly post...")
    data = get_db_data()
    if not data:
        print("No rounds found. Exiting.")
        return
    print(f"Found {len(data['tonight_rounds'])} rounds, {data['unique_players_tonight']} players")
    post_text = call_claude(data)
    if not post_text:
        print("Claude failed. Exiting.")
        return
    print(f"Generated ({len(post_text)} chars):\n{post_text}\n---")
    if "===SPLIT===" in post_text:
        for i, part in enumerate(post_text.split("===SPLIT===")):
            part = part.strip()
            if part:
                print(f"Sending part {i+1}...")
                send_telegram(part)
    else:
        send_telegram(post_text)
    print("Done!")

if __name__ == "__main__":
    main()
