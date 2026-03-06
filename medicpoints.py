"""
MedicPoints Service - Mini App to Flutter App Funnel

Flow:
1. User gets 4/4 correct in Mini App but doesn't win cash prize
2. Show: "You earned 20 MedicPoints! Top MedicPoints winner gets iPad + Apple Pencil"
3. User enters email -> we preload 20 points into Firebase under that email
4. Send install link to download MedicNEET app
5. User installs app, signs in with same email -> 20 points already there

Points awarded:
- 4/4 correct but no cash: 20 MedicPoints (preloaded via email)
- Regular play in Flutter app: +4 correct, -1 wrong (existing system)
"""

import os
import logging
import sqlite3
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

MEDICPOINTS_REWARD = 20  # Points awarded for 4/4 no-cash in Mini App

# Firebase state
_firebase_initialized = False
_firestore_client = None

DB_PATH = os.getenv("DB_PATH", "medicneet.db")


def init_medicpoints_table():
    """Create medicpoints_claims table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS medicpoints_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT NOT NULL,
        telegram_name TEXT,
        email TEXT NOT NULL,
        round_id INTEGER,
        points INTEGER DEFAULT 20,
        firebase_preloaded INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Firebase ────────────────────────────────────────────────────

def _init_firebase():
    """Initialize Firebase Admin SDK (lazy, once)."""
    global _firebase_initialized, _firestore_client

    if _firebase_initialized:
        return _firestore_client

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        try:
            app = firebase_admin.get_app()
        except ValueError:
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

            if creds_path and os.path.exists(creds_path):
                cred = credentials.Certificate(creds_path)
                app = firebase_admin.initialize_app(cred)
                logger.info(f"Firebase initialized with credentials file: {creds_path}")
            elif creds_json:
                import json
                cred = credentials.Certificate(json.loads(creds_json))
                app = firebase_admin.initialize_app(cred)
                logger.info("Firebase initialized with JSON credentials from env")
            else:
                app = firebase_admin.initialize_app()
                logger.info("Firebase initialized with default credentials")

        _firestore_client = firestore.client()
        _firebase_initialized = True
        logger.info("Firestore client ready")
        return _firestore_client

    except Exception as e:
        logger.error(f"Firebase init failed: {e}")
        _firebase_initialized = False
        _firestore_client = None
        return None


def get_firestore():
    """Get Firestore client, initializing if needed."""
    return _init_firebase()


# ─── Core Logic ──────────────────────────────────────────────────

def preload_points_for_email(email: str, telegram_id: str, telegram_name: str, round_id: int) -> dict:
    """
    Preload MedicPoints into Firebase for an email address.

    1. Check if a Flutter app user with this email already exists
       - YES: Add points directly to their existing account
       - NO: Create a "pending" doc so points are ready when they sign up
    2. Store the claim in SQLite for tracking

    Returns dict with success status and details.
    """
    email_clean = email.strip().lower()
    if not email_clean or "@" not in email_clean:
        return {"success": False, "reason": "Invalid email address"}

    # Check if this user already claimed for this round
    conn = _get_db()
    existing = conn.execute(
        "SELECT id FROM medicpoints_claims WHERE telegram_id = ? AND round_id = ?",
        (str(telegram_id), round_id)
    ).fetchone()
    if existing:
        conn.close()
        return {"success": False, "reason": "You already claimed MedicPoints for this round"}

    db = get_firestore()
    firebase_preloaded = False
    existing_user = False
    firebase_uid = None

    if db:
        try:
            # Search for existing Flutter app user with this email
            query = db.collection("users").where("email", "==", email_clean).limit(1)
            results = list(query.stream())

            if not results:
                # Try original case
                query2 = db.collection("users").where("email", "==", email.strip()).limit(1)
                results = list(query2.stream())

            if results:
                # Existing user found - add points to their account
                user_doc = results[0]
                firebase_uid = user_doc.id
                user_data = user_doc.to_dict()
                current_points = user_data.get("medicPoints", 0)
                new_total = current_points + MEDICPOINTS_REWARD

                db.collection("users").document(firebase_uid).set({
                    "medicPoints": new_total,
                    "miniAppBonus": True,
                    "miniAppTelegramId": str(telegram_id),
                }, merge=True)

                # Update leaderboard too
                username = user_data.get("username", telegram_name)
                db.collection("leaderboard").document(firebase_uid).set({
                    "medicPoints": new_total,
                    "username": username,
                }, merge=True)

                firebase_preloaded = True
                existing_user = True
                logger.info(f"Added {MEDICPOINTS_REWARD} points to existing user {firebase_uid} ({email_clean}): {current_points} -> {new_total}")

            else:
                # No existing user - create a pending points doc
                # When they sign up in Flutter app with this email, points will be there
                pending_ref = db.collection("pending_medicpoints").document(email_clean)
                pending_doc = pending_ref.get()

                if pending_doc.exists:
                    # Already has pending points - add more
                    existing_pending = pending_doc.to_dict().get("points", 0)
                    pending_ref.set({
                        "points": existing_pending + MEDICPOINTS_REWARD,
                        "email": email_clean,
                        "telegramId": str(telegram_id),
                        "telegramName": telegram_name,
                        "updatedAt": datetime.now(timezone.utc).isoformat(),
                    }, merge=True)
                else:
                    pending_ref.set({
                        "points": MEDICPOINTS_REWARD,
                        "email": email_clean,
                        "telegramId": str(telegram_id),
                        "telegramName": telegram_name,
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    })

                firebase_preloaded = True
                logger.info(f"Preloaded {MEDICPOINTS_REWARD} pending points for new email {email_clean}")

        except Exception as e:
            logger.error(f"Firebase preload failed for {email_clean}: {e}")

    # Store claim in SQLite
    conn.execute(
        "INSERT INTO medicpoints_claims (telegram_id, telegram_name, email, round_id, points, firebase_preloaded) VALUES (?,?,?,?,?,?)",
        (str(telegram_id), telegram_name, email_clean, round_id, MEDICPOINTS_REWARD, 1 if firebase_preloaded else 0)
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "points": MEDICPOINTS_REWARD,
        "email": email_clean,
        "preloaded": firebase_preloaded,
        "existing_user": existing_user,
    }


def check_and_apply_pending_points(firebase_uid: str, email: str) -> int:
    """
    Called from Flutter app (via Cloud Function or on signup).
    Checks if there are pending MedicPoints for this email and applies them.

    Returns number of points applied (0 if none).
    """
    db = get_firestore()
    if not db:
        return 0

    email_clean = email.strip().lower()

    try:
        pending_ref = db.collection("pending_medicpoints").document(email_clean)
        pending_doc = pending_ref.get()

        if not pending_doc.exists:
            return 0

        pending_data = pending_doc.to_dict()
        points = pending_data.get("points", 0)

        if points <= 0:
            return 0

        # Apply points to user account
        user_ref = db.collection("users").document(firebase_uid)
        user_doc = user_ref.get()
        current_data = user_doc.to_dict() if user_doc.exists else {}
        current_points = current_data.get("medicPoints", 0)
        new_total = current_points + points

        user_ref.set({
            "medicPoints": new_total,
            "miniAppBonus": True,
            "miniAppTelegramId": pending_data.get("telegramId", ""),
        }, merge=True)

        # Update leaderboard
        username = current_data.get("username", "")
        if username:
            db.collection("leaderboard").document(firebase_uid).set({
                "medicPoints": new_total,
                "username": username,
            }, merge=True)

        # Delete pending doc
        pending_ref.delete()

        logger.info(f"Applied {points} pending points to {firebase_uid} ({email_clean})")
        return points

    except Exception as e:
        logger.error(f"Error applying pending points for {email_clean}: {e}")
        return 0


def get_claim_status(telegram_id: str, round_id: int) -> dict:
    """Check if user already claimed MedicPoints for a round."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM medicpoints_claims WHERE telegram_id = ? AND round_id = ?",
            (str(telegram_id), round_id)
        ).fetchone()
        conn.close()
        if row:
            return {"claimed": True, "email": row["email"], "points": row["points"]}
        return {"claimed": False}
    except Exception:
        return {"claimed": False}
