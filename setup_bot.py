"""
MedicNEET Bot Setup
Run once to configure your Telegram bot with the Mini App button.
"""

import os
import sys
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

if not BOT_TOKEN:
    BOT_TOKEN = input("Enter your Bot Token: ").strip()
if not WEBAPP_URL:
    WEBAPP_URL = input("Enter your Mini App URL (e.g. https://yourdomain.com): ").strip()

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def setup():
    client = httpx.Client()

    # 1. Get bot info
    r = client.get(f"{API}/getMe")
    bot = r.json()
    if bot["ok"]:
        print(f"✅ Bot: @{bot['result']['username']}")
    else:
        print(f"❌ Invalid token")
        sys.exit(1)

    # 2. Set bot commands
    r = client.post(f"{API}/setMyCommands", json={
        "commands": [
            {"command": "play", "description": "🎮 Play the ₹50 Quiz"},
            {"command": "leaderboard", "description": "🏆 View Leaderboard"},
            {"command": "app", "description": "📱 Download MedicNEET App"}
        ]
    })
    print(f"{'✅' if r.json()['ok'] else '❌'} Commands set")

    # 3. Set menu button (Mini App)
    r = client.post(f"{API}/setChatMenuButton", json={
        "menu_button": {
            "type": "web_app",
            "text": "🎮 Play Quiz",
            "web_app": {"url": WEBAPP_URL}
        }
    })
    print(f"{'✅' if r.json()['ok'] else '❌'} Menu button set → {WEBAPP_URL}")

    # 4. Set bot description
    r = client.post(f"{API}/setMyDescription", json={
        "description": "🏆 Win ₹50 every 4 hours!\nSolve NEET Biology questions — fastest correct answer wins cash.\n\n📱 By MedicNEET — NEET 2025 prep app"
    })
    print(f"{'✅' if r.json()['ok'] else '❌'} Bot description set")

    r = client.post(f"{API}/setMyShortDescription", json={
        "short_description": "Win ₹50 solving NEET Biology questions! 🧬"
    })
    print(f"{'✅' if r.json()['ok'] else '❌'} Short description set")

    print("\n🎉 Bot setup complete!")
    print(f"\nNext steps:")
    print(f"1. Add the bot as admin to your channel ({os.getenv('CHANNEL_ID', '@yourchannel')})")
    print(f"2. The '🎮 Play Quiz' button will appear in the bot chat")
    print(f"3. Pin a message in channel with the Mini App button:")
    print(f"   Use @BotFather → /mybots → your bot → Bot Settings → Menu Button")
    print(f"\nFor channel button, send this in your channel:")
    print(f"   Use an inline keyboard with web_app url: {WEBAPP_URL}")

    client.close()


if __name__ == "__main__":
    setup()
