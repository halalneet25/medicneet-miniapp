# MedicNEET Deployment Guide 🚀

This guide explains how to connect to your Oracle Cloud server and update the MedicNEET Mini App.

## 🔑 1. The "Key" (SSH Access)
To access the server, you need the **SSH Key file** (the `.key` or `.pem` file provided during setup).

1.  **Save the Key:** Keep this file somewhere safe on your computer (e.g., your Desktop).
2.  **Windows Users:** It's best to put it in a simple path like `C:\Users\YourName\Desktop\my-key.key`.
3.  **Mac/Linux Users:** You may need to run `chmod 400 path/to/key` to secure it before using.

## 🖥️ 2. How to Log In
Open your terminal (Command Prompt, PowerShell, or Terminal).

**The Command Structure:**
`ssh -i <PATH_TO_YOUR_KEY_FILE> opc@152.67.166.222`

**Real Examples:**

* **Windows Example:**
    ```powershell
    ssh -i C:\Users\Shahul\Desktop\ssh-key-2026-02-02.key opc@152.67.166.222
    ```

* **Mac/Linux Example:**
    ```bash
    ssh -i ~/Desktop/ssh-key-2026-02-02.key opc@152.67.166.222
    ```

*If it asks "Are you sure you want to continue connecting?", type `yes` and hit Enter.*

---

## 🔄 3. How to Update the App (After Pushing Code)
When you make changes to the code on GitHub, they **do not** automatically appear on the live site. You must tell the server to pull the new version.

**Run these 3 commands in order:**

1.  **Go to the app folder:**
    ```bash
    cd medicneet-miniapp
    ```

2.  **Download new code:**
    ```bash
    git pull
    ```

3.  **Restart the app (To make changes live):**
    ```bash
    sudo systemctl restart medicneet
    ```

*Note: The site will be down for about 3-5 seconds while it restarts.*

---

## 🛠️ 4. Managing Secrets (Config)
For security, passwords and API keys are **NOT** stored in this GitHub repository. They live directly on the server.

### **To Change Passwords or API Keys:**
Run this command to edit the configuration file:
```bash
sudo nano /etc/systemd/system/medicneet.service
Use arrow keys to move.

Edit SMTP_PASS, BOT_TOKEN, etc.

Press Ctrl+O then Enter to save.

Press Ctrl+X to exit.

Always run sudo systemctl restart medicneet after changing secrets.

To Update Google Credentials:
The Google Service Account file is located at: /home/opc/medicneet-miniapp/credentials.json

🚨 5. Troubleshooting
If the site is down or "Internal Server Error" appears, check the logs to see why:

Bash
sudo journalctl -u medicneet -n 50 --no-pager
Green/White text: Normal info.

Red text / Traceback: Errors (usually Python crashes).

Server IP: 152.67.166.222 App URL: https://quiz.medicneet.com