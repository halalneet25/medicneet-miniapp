# MedicNEET Mini App — Complete Deployment Guide

## What You're Deploying

A Telegram Mini App with:
- **Quiz engine** — New NEET question every 4 hours, ₹50 for fastest correct answer
- **Email collection** — "Launching Soon" CTA collects emails (until PlayStore is live)
- **Daily email export** — CSV of all emails sent to medicneet.team@gmail.com every day at 8 AM IST
- **Winner announcements** — Auto-posted to your Telegram channel
- **Leaderboard** — All-time champions

---

## STEP 1: Prerequisites (One-Time Setup)

### 1A. Create Telegram Bot
```
1. Open Telegram → search @BotFather
2. Send: /newbot
3. Name it: MedicNEET Quiz Bot
4. Username: medicneet_quiz_bot (or similar)
5. COPY the token → this is your BOT_TOKEN
```

### 1B. Create Telegram Channel
```
1. Create a channel: "MedicNEET Quiz"
2. Add your bot as ADMIN (with "Post Messages" permission)
3. Note the channel username: @medicneet_quiz (or your choice)
```

### 1C. Gmail App Password (for daily email export)
```
1. Go to https://myaccount.google.com/security
2. Turn on 2-Step Verification (required)
3. Go to https://myaccount.google.com/apppasswords
4. App name: "MedicNEET Bot"
5. Click Generate → COPY the 16-character password
   (looks like: abcd efgh ijkl mnop)
6. This is your SMTP_PASS (remove spaces)
```

### 1D. Google Sheet for Questions (Optional)
```
Create a Google Sheet with columns:
| Question | Option A | Option B | Option C | Option D | Correct Answer | Explanation | Chapter | Difficulty |

Share it with a Google Service Account if using auto-sync.
Otherwise, you can add questions directly to SQLite.
```

---

## STEP 2: Choose Deployment Platform

### Option A: Railway.app (Recommended — Easiest)

**Why:** Free tier, auto-deploy from GitHub, HTTPS built-in, zero DevOps.

```bash
# 1. Push code to GitHub
git init
git add .
git commit -m "MedicNEET Mini App"
git remote add origin https://github.com/YOUR_USERNAME/medicneet-miniapp.git
git push -u origin main

# 2. Go to https://railway.app
#    → New Project → Deploy from GitHub → Select your repo

# 3. Add environment variables (see Step 3 below)

# 4. Railway auto-detects Python, runs uvicorn
#    Add this file to your repo:
```

Create a `Procfile`:
```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Create a `runtime.txt`:
```
python-3.11.7
```

After deploy, Railway gives you a URL like:
`https://medicneet-miniapp-production.up.railway.app`

**This is your WEBAPP_URL.**

---

### Option B: VPS (DigitalOcean / AWS Lightsail / Hetzner)

```bash
# 1. SSH into your server
ssh root@YOUR_SERVER_IP

# 2. Install dependencies
apt update && apt install python3-pip python3-venv nginx certbot python3-certbot-nginx -y

# 3. Clone your repo
git clone https://github.com/YOUR_USERNAME/medicneet-miniapp.git
cd medicneet-miniapp

# 4. Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Create .env file (see Step 3)
nano .env

# 6. Create systemd service
sudo nano /etc/systemd/system/medicneet.service
```

Paste this into `medicneet.service`:
```ini
[Unit]
Description=MedicNEET Mini App
After=network.target

[Service]
User=root
WorkingDirectory=/root/medicneet-miniapp
EnvironmentFile=/root/medicneet-miniapp/.env
ExecStart=/root/medicneet-miniapp/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# 7. Start the service
sudo systemctl daemon-reload
sudo systemctl enable medicneet
sudo systemctl start medicneet

# 8. Setup Nginx reverse proxy
sudo nano /etc/nginx/sites-available/medicneet
```

Paste this into the Nginx config:
```nginx
server {
    listen 80;
    server_name quiz.medicneet.com;  # YOUR DOMAIN

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 5M;
    }
}
```

```bash
# 9. Enable site + SSL
sudo ln -s /etc/nginx/sites-available/medicneet /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d quiz.medicneet.com  # Gets free HTTPS

# 10. Your WEBAPP_URL = https://quiz.medicneet.com
```

---

### Option C: Render.com (Also Easy)

```
1. Push to GitHub
2. Go to https://render.com → New Web Service
3. Connect your GitHub repo
4. Build command: pip install -r requirements.txt
5. Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
6. Add env vars (Step 3)
7. Deploy → get your URL
```

---

## STEP 3: Environment Variables

Set these wherever you deploy:

```bash
# === REQUIRED ===
BOT_TOKEN=7123456789:AAH_your_bot_token_from_botfather
CHANNEL_ID=@medicneet_quiz
WEBAPP_URL=https://your-deployed-url.com

# === EMAIL EXPORT (for daily CSV to your Gmail) ===
SMTP_USER=medicneet.team@gmail.com
SMTP_PASS=abcdefghijklmnop
EXPORT_TO_EMAIL=medicneet.team@gmail.com

# === APP STATUS (change when PlayStore is live) ===
APP_STATUS=launching_soon
PLAYSTORE_LINK=

# === OPTIONAL ===
QUESTION_INTERVAL_HOURS=4
CASH_PRIZE=50
GOOGLE_SHEET_ID=your_sheet_id_here
GOOGLE_CREDS_FILE=credentials.json
```

**On Railway:** Settings → Variables → Add each one
**On VPS:** Put them in `/root/medicneet-miniapp/.env` like:
```
BOT_TOKEN=7123456789:AAH_...
CHANNEL_ID=@medicneet_quiz
```

---

## STEP 4: Register Mini App with BotFather

```
1. Open @BotFather in Telegram
2. Send: /mybots → Select your bot → Bot Settings → Menu Button
3. Set Menu Button URL → paste your WEBAPP_URL
4. OR send: /setmenubutton then paste the URL

ALSO:
5. /mybots → Select bot → Bot Settings → Configure Mini App
6. Web App URL → paste your WEBAPP_URL
```

---

## STEP 5: Add Questions

### Option A: Via Google Sheets
Set `GOOGLE_SHEET_ID` in env vars. Questions auto-sync on startup.

### Option B: Direct SQLite
```bash
# SSH into server or use Railway CLI
sqlite3 medicneet.db

INSERT INTO questions (question, option_a, option_b, option_c, option_d, correct_answer, explanation, chapter)
VALUES (
    'Which of the following is not a characteristic of phylum Chordata?',
    'Dorsal hollow nerve cord',
    'Post-anal tail',
    'Ventral heart',
    'Open circulatory system',
    'D',
    'Chordates have a closed circulatory system, not open.',
    'Animal Kingdom'
);
```

### Option C: Via the CSV sample
Edit `sample_questions.csv` and import it.

---

## STEP 6: Post Quiz Button to Channel

```
1. Open your bot in Telegram DM
2. Send: /postbutton
3. The bot posts the "Play Quiz — Win ₹50!" button to your channel
```

---

## STEP 7: Test Everything

```
✅ Open the Mini App from channel button
✅ See a question with timer running
✅ Answer and see result (correct/wrong)
✅ Check leaderboard tab
✅ See "Launching Soon" CTA with email input
✅ Enter email → get "You're in!" confirmation
✅ Check your Gmail tomorrow at 8 AM IST for the CSV export
```

---

## When PlayStore Goes Live

Just change 2 environment variables:

```bash
APP_STATUS=live
PLAYSTORE_LINK=https://play.google.com/store/apps/details?id=com.medicneet.app
```

Restart the app. All "Launching Soon" CTAs automatically become "Download MedicNEET" buttons.

**The email collection stays in the database** — you still have all those emails for future campaigns.

---

## Daily Email Export — How It Works

- Runs automatically at **8:00 AM IST** (2:30 AM UTC) every day
- Sends a CSV file to `medicneet.team@gmail.com`
- CSV columns: `Email, Name, Source, Signed Up At`
- Manual trigger: visit `https://your-url.com/api/export-emails`
- Export log stored in `email_export_log` table for debugging

---

## Useful Admin Endpoints

| Endpoint | What it does |
|---|---|
| `GET /` | Main Mini App |
| `GET /api/current-round` | Current question & stats |
| `GET /api/leaderboard` | All-time winners |
| `GET /api/notify-count` | Total email signups |
| `GET /api/export-emails` | Trigger manual email export |
| `POST /api/sync-sheet` | Re-sync questions from Google Sheet |
| `GET /api/app-status` | Check if launching_soon or live |

---

## Troubleshooting

**Bot not posting to channel?**
→ Make sure bot is ADMIN in the channel with "Post Messages" permission

**Email export not arriving?**
→ Check `SMTP_PASS` is a Gmail App Password (not your regular password)
→ Check spam folder
→ Visit `/api/export-emails` to trigger manually

**Questions not loading?**
→ Add questions to the database (Step 5)
→ Check `/api/current-round` response

**Mini App not opening?**
→ WEBAPP_URL must be HTTPS (Telegram requires it)
→ Make sure BotFather has the correct URL
