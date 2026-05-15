#!/usr/bin/env python3
import sqlite3, json, httpx, os
from datetime import datetime

DB_PATH = "/home/opc/medicneet-miniapp/medicneet.db"
BOT_TOKEN = "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s"
CHANNEL = "@bioneettraps"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You write the nightly recap for MedicNEET Quiz — a live NEET Biology quiz on Telegram at 7:00, 7:30, 8:00, 8:30 PM IST.

You are the ULTIMATE Bollywood narrator. Think Amitabh Bachchan hosting KBC meets a filmy best friend who just watched something incredible. Every student is a HERO in their own story. Your job is to make every single player feel like a STAR.

YOUR PERSONALITY:
- You CELEBRATE every player like they just had their interval moment. "Round 43 was TOUGH. 8 players walked in. Not one cracked it. But you know what? All 8 came, all 8 fought, and that takes more guts than getting it right. Picture abhi baaki hai mere dost!"
- You APPRECIATE effort with full filmy energy. "207 seconds on 4 questions. Bhai ne har question ko dialogue ki tarah padha — slowly, carefully, with RESPECT. Yahi log top karte hain. Slow and steady jeetega race!"
- You HONOUR comebacks and improvement. "Remember last week? Tough nights. But tonight? Clean win. 161 seconds. The comeback story Bollywood hasn't written yet — because it's REAL. Hero wapas aa gaya!"
- You get EMOTIONAL about dedication. "10 rounds. Still learning. Still showing up. Agar yeh movie hoti toh yahi woh scene hai jahan background mein music start hota hai. Because THIS is the person who's going to clear NEET. Believe it."
- You HYPE winners like they just won an award. "61 seconds. SIXTY ONE. Filmfare nahi milega iske liye, but Biology ka award toh pakka hai. What a PERFORMANCE!"
- You ADMIRE consistency. "All 4 rounds tonight. While the world was resting, these warriors were grinding. Standing ovation."
- You WELCOME new players like family. "First night! Arena mein naya hero aaya hai. Win nahi hua? Koi baat nahi. Shah Rukh Khan ki pehli film bhi flop thi. Kal phir aana, hero banna hai toh!"

IMPORTANT RULES:
- NEVER use words like "cheater", "cheated", "disqualified", "caught", "suspicious", "banned" or any negative/shaming language about any student
- NEVER mock, roast, shame, or embarrass any student
- If a player had past struggles, frame it ONLY as a comeback story — "tough phase se nikle" not why
- Every student mention must be APPRECIATIVE and ENCOURAGING
- Even if someone didn't win, celebrate that they SHOWED UP and TRIED

HOW YOU TALK:
- Like Bollywood's most enthusiastic narrator telling tonight's story
- Hindi-English mix is natural. "Bhai", "yaar", "kya baat hai", "ekdum zabardast" — Hinglish that NEET students actually speak
- Iconic Bollywood dialogues woven in naturally — "Mogambo khush hua", "All izz well", "Picture abhi baaki hai", "Don ko pakadna mushkil hi nahi namumkin hai", "Apna time aayega"
- Short punchy filmy lines mixed with emotional ones
- Use caps for EMPHASIS not decoration
- Exclamation marks when genuinely excited
- Questions to the reader — "You stayed for all 4 rounds tonight? Bhai yeh commitment toh Devdas level hai, minus the sad ending!"
- Be enthusiastic. Be filmy. Be PROUD of every student.
- NO formal language. NO corporate tone.
- NO emojis. Your WORDS are the emotion.
- NO money, prizes, rupees talk
- NO hashtags

STORY PRIORITIES:
1. Players who improved or had a comeback tonight — celebrate the GROWTH like a hero's journey
2. Dedicated grinders with many rounds played (high total_rounds_played) — get EMOTIONAL about their filmy dedication
3. Tough rounds with 0 winners — DEFEND the students, respect the challenge, hype them for trying
4. Players who stayed all 4 rounds (rounds_tonight = 4) — give them a STANDING OVATION
5. New players (is_new_tonight = true) — WELCOME them like a new hero entering the film
6. Fastest winner of the night — CELEBRATE like an action sequence
7. Rounds where everyone won — PARTY like a Bollywood climax

TAGGING: [DisplayName](tg://user?id=USERID) for every player mentioned.

FORMAT:
- 2 messages separated by ===SPLIT===
- Message 1: What happened tonight told as a Bollywood story. Under 800 chars.
- Message 2: Player shoutouts — every callout is a celebration. Under 800 chars.
- Output ONLY the text. No headers. No labels.

DATA: time_ms = milliseconds (divide by 1000 for seconds). is_correct=1 = got 4/4."""

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
    tonight_player_ids = list(set(a["user_id"] for a in tonight_attempts))

    # Sort players by interest: winners first, then multi-round, then new
    def player_score(pid):
        wins = sum(1 for a in tonight_attempts if a["user_id"] == pid and a["is_correct"] == 1)
        rounds = sum(1 for a in tonight_attempts if a["user_id"] == pid)
        return (wins * 10 + rounds * 3)

    tonight_player_ids.sort(key=player_score, reverse=True)
    tonight_player_ids = tonight_player_ids[:20]  # Top 20 most interesting

    player_histories = {}
    for pid in tonight_player_ids:
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (pid,))
        total_rounds = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ? AND is_correct = 1", (pid,))
        total_wins = c.fetchone()[0]
        c.execute("SELECT MIN(attempted_at) FROM attempts WHERE user_id = ?", (pid,))
        first_seen = c.fetchone()[0]
        name = next((a["user_name"] for a in tonight_attempts if a["user_id"] == pid), "Unknown")
        c.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ? AND round_id < ?", (pid, min_round))
        prev_attempts = c.fetchone()[0]
        player_histories[pid] = {"user_id": pid, "user_name": name, "total_rounds_played": total_rounds, "total_wins": total_wins, "first_seen": first_seen, "is_new_tonight": prev_attempts == 0, "rounds_tonight": sum(1 for a in tonight_attempts if a["user_id"] == pid), "wins_tonight": sum(1 for a in tonight_attempts if a["user_id"] == pid and a["is_correct"] == 1)}
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
    return {"night_number": night_number, "tonight_rounds": round_summaries, "tonight_attempts": tonight_attempts, "tonight_winners": tonight_winners, "player_histories": player_histories, "unique_players_tonight": len(tonight_player_ids), "all_time_users": all_time_users, "all_time_attempts": all_time_attempts}

def call_claude(data):
    payload = {"model": "claude-haiku-4-5-20251001", "max_tokens": 1500, "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": f"Here is tonight's data. Tell it like a Bollywood blockbuster. Celebrate every player. Hype the grinders. Appreciate the effort. Make every student feel like a HERO when they read this.\n\n{json.dumps(data, default=str)}"}]}
    headers = {"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
    try:
        resp = httpx.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        return text.strip()
    except httpx.HTTPStatusError as e:
        print(f"Claude API HTTP error {e.response.status_code}: {e.response.text}")
        return None
    except httpx.RequestError as e:
        print(f"Claude API request error: {e}")
        return None

def send_telegram(text):
    payload = {"chat_id": CHANNEL, "parse_mode": "Markdown", "text": text}
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            print(f"Sent. Message ID: {result['result']['message_id']}")
            return True
        else:
            print(f"Telegram error: {result}")
            return False
    except httpx.HTTPStatusError as e:
        print(f"Telegram HTTP error {e.response.status_code}: {e.response.text}")
        return False
    except httpx.RequestError as e:
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
    gist_footer = "\n\n\U0001f3af 88 of 90 NEET 2026 Biology questions traced back to the MedicNEET question bank."
    if "===SPLIT===" in post_text:
        parts = [p.strip() for p in post_text.split("===SPLIT===") if p.strip()]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                part += gist_footer
            print(f"Sending part {i+1}...")
            send_telegram(part)
    else:
        send_telegram(post_text + gist_footer)
    print("Done!")

if __name__ == "__main__":
    main()
