#!/usr/bin/env python3
"""
NEET Flash News Bot — Fetches latest NEET UG exam news via Claude web_search,
saves structured JSON for the website, posts SHORT teaser to Telegram
directing users to medicneet.com/neet-news for full details.

STRICT RULES:
- NEET UG ONLY. No NEET PG, no NEET SS, no NEET MDS.
- Only official/verified sources: nta.ac.in, neet.nta.nic.in, Supreme Court,
  PIB, Education Ministry, verified major news outlets.
- Current date awareness — only news from last 48 hours.
- No speculation, no rumors, no coaching institute predictions.
"""
import json, urllib.request, os, ssl
from datetime import datetime, timezone, timedelta

BOT_TOKEN = "8574043659:AAEQHtEmevdGoQFcpLmWl8vsc6GSv74Pn0s"
CHANNEL = "@bioneettraps"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NEWS_JSON_PATH = "/home/opc/medicneet-miniapp/static/neet_news_data.json"
WEBSITE_URL = "https://www.medicneet.com/neet-news"

IST = timezone(timedelta(hours=5, minutes=30))

SYSTEM_PROMPT = """You are MedicNEET News Research Bot. Your ONLY job is to find VERIFIED, FACTUAL news about NEET UG (undergraduate medical entrance exam in India) from the last 48 hours.

STRICT RULES:
1. NEET UG ONLY — absolutely NO NEET PG, NEET SS, NEET MDS, or any postgraduate medical exam news. If a news item is about NEET PG, skip it completely.
2. ONLY trust these sources:
   - nta.ac.in / neet.nta.nic.in (NTA official)
   - Supreme Court of India official orders
   - PIB (Press Information Bureau)
   - Ministry of Education official statements
   - Major verified news: NDTV, Times of India, Indian Express, Hindustan Times, The Hindu, LiveLaw (for court orders only)
3. VERIFY before including — if you cannot confirm a news item from an official or major source, DO NOT include it.
4. NO coaching institute opinions, NO cutoff predictions, NO "expected" dates unless from NTA.
5. NO speculation. Only confirmed facts.
6. Be aware of the CURRENT DATE provided. Only include genuinely recent news (last 48 hours). Don't include old news repackaged as new.

OUTPUT FORMAT — You MUST respond with valid JSON only, no other text:
{
  "date": "YYYY-MM-DD",
  "has_news": true/false,
  "items": [
    {
      "headline": "Short factual headline in English",
      "headline_hi": "Same headline in Hinglish",
      "summary": "2-3 sentence factual summary in English with specific details (dates, numbers, etc.)",
      "summary_hi": "Same summary in Hinglish (Hindi-English mix)",
      "source": "Source name",
      "source_url": "URL of the source article",
      "category": "one of: registration, exam_date, admit_card, result, syllabus, court_order, nta_announcement, policy_change",
      "verified": true,
      "importance": "high/medium/low"
    }
  ],
  "tip": "If has_news is false, provide one useful NEET Biology preparation tip in Hinglish here, otherwise null"
}

If NO genuine NEET UG news exists from the last 48 hours, set has_news to false and items to empty array. Do NOT make up news. Honesty > content."""


def call_claude_with_search():
    """Call Claude API with web_search to find latest NEET UG news."""
    now = datetime.now(IST)
    today = now.strftime("%d %B %Y")
    day_of_week = now.strftime("%A")
    yesterday = (now - timedelta(days=1)).strftime("%d %B %Y")

    user_msg = f"""Today is {day_of_week}, {today} (IST). Yesterday was {yesterday}.

Search for the latest NEET UG 2026 news from the last 48 hours ONLY. Remember:
- NEET UG only. NOT NEET PG.
- Check nta.ac.in, neet.nta.nic.in, Supreme Court orders, PIB, Education Ministry.
- Also check NDTV Education, Times of India Education, Indian Express Education for NEET UG news.
- Search queries should include "NEET UG 2026", "NTA NEET 2026", "NEET exam 2026".
- VERIFY each item. If you're not sure, don't include it.
- Look for: registration updates, exam date changes, admit card release, result dates, syllabus notifications, Supreme Court NEET UG orders, NTA official circulars.

Respond with JSON only. No other text."""

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 10
            }
        ],
        "messages": [
            {"role": "user", "content": user_msg}
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return text.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Claude API HTTP error {e.code}: {body}")
        return None
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


def parse_news_json(raw_text):
    """Parse Claude's JSON response, handling markdown code blocks and preamble text."""
    import re
    text = raw_text.strip()

    # Try to extract JSON from markdown code blocks first
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()
    else:
        # Try to find the first { ... } JSON object in the text
        brace_start = text.find('{')
        if brace_start != -1:
            # Find the matching closing brace
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        text = text[brace_start:i+1]
                        break

    try:
        data = json.loads(text)
        # Validate structure
        if "items" not in data:
            data["items"] = []
        if "has_news" not in data:
            data["has_news"] = len(data["items"]) > 0
        if "date" not in data:
            data["date"] = datetime.now(IST).strftime("%Y-%m-%d")

        # Filter: remove any NEET PG items that slipped through
        filtered = []
        for item in data["items"]:
            headline = (item.get("headline", "") + " " + item.get("summary", "")).lower()
            if any(pg_term in headline for pg_term in ["neet pg", "neet-pg", "neet ss", "neet mds", "postgraduate", "pg counselling", "pg cutoff", "pg cut-off"]):
                print(f"FILTERED OUT (NEET PG): {item.get('headline', '')}")
                continue
            filtered.append(item)

        data["items"] = filtered
        data["has_news"] = len(filtered) > 0

        # Add metadata
        data["generated_at"] = datetime.now(IST).isoformat()
        data["source_bot"] = "MedicNEET News Bot v2"

        return data
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Raw text: {text[:500]}")
        return None


def save_news_json(data):
    """Save news data as JSON file for the website to consume."""
    # Load existing archive if present
    archive_path = NEWS_JSON_PATH.replace(".json", "_archive.json")
    try:
        with open(archive_path, "r") as f:
            archive = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        archive = []

    # Add today's data to archive (keep last 30 days)
    archive.append(data)
    archive = archive[-30:]

    # Save current
    with open(NEWS_JSON_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved news JSON to {NEWS_JSON_PATH}")

    # Save archive
    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2, ensure_ascii=False)
    print(f"Updated archive ({len(archive)} days)")


def build_telegram_teaser(data):
    """Build a SHORT teaser for Telegram that directs users to the website."""
    now = datetime.now(IST)
    today = now.strftime("%d %B %Y")

    if not data.get("has_news") or not data.get("items"):
        print("No NEET UG news found. Skipping Telegram post.")
        return None

    items = data["items"]
    # Sort by importance
    importance_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: importance_order.get(x.get("importance", "low"), 2))

    category_emoji = {
        "registration": "📝",
        "exam_date": "📅",
        "admit_card": "🎫",
        "result": "📊",
        "syllabus": "📚",
        "court_order": "⚖️",
        "nta_announcement": "📢",
        "policy_change": "🏛️",
    }

    msg = f"📰 *NEET FLASH NEWS* — {today}\n\n"

    for item in items[:5]:
        emoji = category_emoji.get(item.get("category", ""), "🔹")
        headline = item.get("headline_hi", item.get("headline", ""))
        msg += f"{emoji} *{headline}*\n"

    msg += f"\n👉 *Full details padhne ke liye visit karo:*\n{WEBSITE_URL}\n\n"
    msg += f"Stay updated. Stay focused. 🧬\n"
    msg += f"📱 MedicNEET App: https://play.google.com/store/apps/details?id=com.halalfire.medicneet"

    return msg


def send_telegram(text):
    """Send message to Telegram channel with fallback."""
    payload = {
        "chat_id": CHANNEL,
        "parse_mode": "Markdown",
        "text": text,
        "disable_web_page_preview": False
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                print(f"Sent to Telegram. Message ID: {result['result']['message_id']}")
                return True
            else:
                print(f"Telegram error: {result}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Telegram HTTP error {e.code}: {body}")
        # Fallback: strip markdown and send plain
        plain = text.replace("*", "").replace("_", "")
        payload["parse_mode"] = ""
        payload["text"] = plain
        req2 = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                result2 = json.loads(resp2.read().decode("utf-8"))
                if result2.get("ok"):
                    print(f"Sent plain text fallback. Message ID: {result2['result']['message_id']}")
                    return True
        except Exception as e2:
            print(f"Plain text fallback also failed: {e2}")
        return False
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def main():
    now = datetime.now(IST)
    print(f"[{now.isoformat()}] Starting NEET Flash News v2...")
    print(f"Current date: {now.strftime('%A, %d %B %Y %I:%M %p IST')}")

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set. Exiting.")
        return

    # Step 1: Call Claude with web search
    print("\n--- Step 1: Searching for NEET UG news via Claude ---")
    raw_response = call_claude_with_search()

    if not raw_response:
        print("Claude returned no response. Exiting.")
        return

    print(f"Raw response ({len(raw_response)} chars)")

    # Step 2: Parse structured JSON
    print("\n--- Step 2: Parsing news data ---")
    news_data = parse_news_json(raw_response)

    if not news_data:
        print("Failed to parse news JSON. Exiting.")
        return

    item_count = len(news_data.get("items", []))
    print(f"Parsed: {item_count} news items, has_news={news_data.get('has_news')}")

    for i, item in enumerate(news_data.get("items", [])):
        print(f"  [{i+1}] [{item.get('importance','?')}] {item.get('headline','?')} — {item.get('source','?')}")

    # Step 3: Save JSON for website
    print("\n--- Step 3: Saving news data ---")
    save_news_json(news_data)

    # Step 4: Build and send Telegram teaser
    print("\n--- Step 4: Sending Telegram teaser ---")
    teaser = build_telegram_teaser(news_data)
    if teaser is None:
        print("No news — skipping Telegram post.")
        print("\nDone! No post today.")
        return
    print(f"Teaser ({len(teaser)} chars):\n{teaser}\n---")

    success = send_telegram(teaser)
    if success:
        print("\nDone! Teaser posted, full news on website.")
    else:
        print("\nWARNING: Failed to send Telegram teaser.")


if __name__ == "__main__":
    main()
