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
        firebase_uid TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # Add firebase_uid column if table already existed without it
    try:
        conn.execute("ALTER TABLE medicpoints_claims ADD COLUMN firebase_uid TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
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

def _resolve_firebase_uid(email_clean: str) -> str | None:
    """
    Resolve email → Firebase UID using Firebase Auth (primary method).
    Returns UID string or None if user not found in Firebase Auth.
    """
    try:
        from firebase_admin import auth as firebase_auth
        auth_user = firebase_auth.get_user_by_email(email_clean)
        return auth_user.uid
    except Exception:
        return None


def _get_cached_firebase_uid(conn, telegram_id: str) -> str | None:
    """Look up cached firebase_uid from a previous successful claim."""
    row = conn.execute(
        "SELECT firebase_uid FROM medicpoints_claims WHERE telegram_id = ? AND firebase_uid IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (str(telegram_id),)
    ).fetchone()
    return row["firebase_uid"] if row else None


def _sanitize_email(email: str) -> str:
    """Sanitize email: lowercase, strip, fix double-domain typos like user@gmail.com@gmail.com."""
    email_clean = email.strip().lower()
    # Fix double-domain: user@gmail.com@gmail.com -> user@gmail.com
    at_count = email_clean.count("@")
    if at_count > 1:
        parts = email_clean.split("@")
        # Take the local part (before first @) and last domain
        email_clean = parts[0] + "@" + parts[-1]
        logger.info(f"Fixed double-domain email: {email} -> {email_clean}")
    return email_clean


def preload_points_for_email(email: str, telegram_id: str, telegram_name: str, round_id: int) -> dict:
    """
    Preload MedicPoints into Firebase for an email address.

    Strategy (Auth-first — user docs are keyed by Firebase UID, not email):
    1. Try firebase_admin.auth.get_user_by_email() to resolve email → UID
    2. If found: atomically increment medicPoints on users/{uid} via Increment
    3. If not found: store in pending_medicpoints/{email} for when they sign up
    4. Store the claim in SQLite for tracking

    Returns dict with success status and details.
    """
    email_clean = _sanitize_email(email)
    if not email_clean or "@" not in email_clean:
        return {"success": False, "reason": "Invalid email address"}

    # Validate round_id is a real integer
    try:
        round_id = int(round_id)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Invalid round_id"}

    # Check if this user already claimed for this round (deduplicate)
    conn = _get_db()
    existing = conn.execute(
        "SELECT id, points, firebase_preloaded FROM medicpoints_claims WHERE telegram_id = ? AND round_id = ?",
        (str(telegram_id), round_id)
    ).fetchone()
    if existing:
        if existing["firebase_preloaded"]:
            conn.close()
            return {"success": False, "reason": "You already claimed MedicPoints for this round"}
        # Previous claim failed (firebase_preloaded=0) — delete it and retry
        conn.execute("DELETE FROM medicpoints_claims WHERE id = ?", (existing["id"],))
        conn.commit()
        logger.info(f"Deleted failed claim {existing['id']} for user {telegram_id} round {round_id}, retrying")

    db = get_firestore()
    firebase_preloaded = False
    existing_user = False
    firebase_uid = None

    if db:
        try:
            from firebase_admin import firestore as firestore_module

            # PRIMARY: resolve email → UID via Firebase Auth
            firebase_uid = _get_cached_firebase_uid(conn, telegram_id) or _resolve_firebase_uid(email_clean)

            if firebase_uid:
                # User exists in Firebase Auth — update their Firestore doc atomically
                user_ref = db.collection("users").document(firebase_uid)
                user_doc = user_ref.get()

                user_ref.set({
                    "medicPoints": firestore_module.Increment(MEDICPOINTS_REWARD),
                    "miniAppBonus": True,
                    "miniAppTelegramId": str(telegram_id),
                    "email": email_clean,
                }, merge=True)

                # Update leaderboard atomically too
                username = ""
                if user_doc.exists:
                    username = user_doc.to_dict().get("username", telegram_name)
                else:
                    username = telegram_name
                db.collection("leaderboard").document(firebase_uid).set({
                    "medicPoints": firestore_module.Increment(MEDICPOINTS_REWARD),
                    "username": username,
                }, merge=True)

                firebase_preloaded = True
                existing_user = True
                current_points = user_doc.to_dict().get("medicPoints", 0) if user_doc.exists else 0
                logger.info(f"Added {MEDICPOINTS_REWARD} points to user {firebase_uid} ({email_clean}): {current_points} -> {current_points + MEDICPOINTS_REWARD}")

            else:
                # User not in Firebase Auth yet — store as pending
                pending_ref = db.collection("pending_medicpoints").document(email_clean)
                pending_ref.set({
                    "points": firestore_module.Increment(MEDICPOINTS_REWARD),
                    "email": email_clean,
                    "telegramId": str(telegram_id),
                    "telegramName": telegram_name,
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                }, merge=True)

                firebase_preloaded = True
                logger.info(f"Preloaded {MEDICPOINTS_REWARD} pending points for new email {email_clean}")

        except Exception as e:
            logger.error(f"Firebase preload failed for {email_clean}: {e}")
    else:
        logger.error(f"Firebase unavailable for claim: user={telegram_id}, round={round_id}")

    if not firebase_preloaded:
        # Don't store a broken claim — return failure so user can retry
        conn.close()
        return {
            "success": False,
            "reason": "Could not connect to Firebase. Please try again in a moment.",
        }

    # Store claim in SQLite only on success (with cached firebase_uid)
    conn.execute(
        "INSERT INTO medicpoints_claims (telegram_id, telegram_name, email, round_id, points, firebase_preloaded, firebase_uid) VALUES (?,?,?,?,?,?,?)",
        (str(telegram_id), telegram_name, email_clean, round_id, MEDICPOINTS_REWARD, 1, firebase_uid)
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


def auto_credit_medicpoints(round_id: int, winners: list) -> dict:
    """
    Auto-credit MedicPoints to Firebase for users who already have an email on file.
    Called from send_winner_to_channel after marking capped_medic/medicpoints_eligible.

    winners: list of dicts with user_id, user_name keys.
    Returns dict with counts of credited/skipped/failed.
    """
    credited = 0
    skipped = 0
    failed = 0

    conn = _get_db()
    for w in winners:
        user_id = str(w["user_id"])
        user_name = w.get("user_name", "Anon")

        # Check if already claimed for this round
        existing = conn.execute(
            "SELECT id, firebase_preloaded FROM medicpoints_claims WHERE telegram_id = ? AND round_id = ?",
            (user_id, round_id)
        ).fetchone()
        if existing and existing["firebase_preloaded"]:
            skipped += 1
            continue

        # Look up email from previous successful claims
        row = conn.execute(
            "SELECT email FROM medicpoints_claims WHERE telegram_id = ? AND firebase_preloaded = 1 ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        if not row:
            skipped += 1  # No email on file — user will need to claim manually via popup
            continue

        email = row["email"]

        # Delete any failed prior claim for this round before retrying
        if existing and not existing["firebase_preloaded"]:
            conn.execute("DELETE FROM medicpoints_claims WHERE id = ?", (existing["id"],))
            conn.commit()

        try:
            result = preload_points_for_email(email, user_id, user_name, round_id)
            if result.get("success"):
                credited += 1
                logger.info(f"Auto-credited {MEDICPOINTS_REWARD} MedicPoints to {user_id} ({email}) for round {round_id}")
            else:
                failed += 1
                logger.warning(f"Auto-credit failed for {user_id}: {result.get('reason')}")
        except Exception as e:
            failed += 1
            logger.error(f"Auto-credit exception for {user_id}: {e}")

    conn.close()
    logger.info(f"auto_credit_medicpoints round {round_id}: credited={credited}, skipped={skipped}, failed={failed}")
    return {"credited": credited, "skipped": skipped, "failed": failed}


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

        # Apply points to user account atomically
        from firebase_admin import firestore as firestore_module

        user_ref = db.collection("users").document(firebase_uid)
        user_doc = user_ref.get()
        current_data = user_doc.to_dict() if user_doc.exists else {}

        user_ref.set({
            "medicPoints": firestore_module.Increment(points),
            "miniAppBonus": True,
            "miniAppTelegramId": pending_data.get("telegramId", ""),
        }, merge=True)

        # Update leaderboard atomically
        username = current_data.get("username", "")
        if username:
            db.collection("leaderboard").document(firebase_uid).set({
                "medicPoints": firestore_module.Increment(points),
                "username": username,
            }, merge=True)

        # Delete pending doc
        pending_ref.delete()

        logger.info(f"Applied {points} pending points to {firebase_uid} ({email_clean})")
        return points

    except Exception as e:
        logger.error(f"Error applying pending points for {email_clean}: {e}")
        return 0


def flush_pending_medicpoints() -> dict:
    """
    Apply all pending_medicpoints to users who already exist in Firebase Auth.
    Called on server startup and can be triggered manually via API.

    Uses auth.get_user_by_email() to resolve email → UID (since user docs
    are keyed by Firebase UID and often lack an email field), then uses
    firestore.Increment() for atomic point updates.

    Returns dict with counts of applied/skipped/failed.
    """
    db = get_firestore()
    if not db:
        return {"applied": 0, "skipped": 0, "error": "Firebase unavailable"}

    applied = 0
    skipped = 0
    failed = 0

    try:
        from firebase_admin import auth as firebase_auth
        from firebase_admin import firestore as firestore_module

        # Get all pending_medicpoints docs
        pending_docs = list(db.collection("pending_medicpoints").stream())
        logger.info(f"flush_pending_medicpoints: found {len(pending_docs)} pending docs")

        for pending_doc_snap in pending_docs:
            email = pending_doc_snap.id  # doc ID is the email
            pending_data = pending_doc_snap.to_dict()
            points = pending_data.get("points", 0)

            if points <= 0:
                skipped += 1
                continue

            try:
                # Resolve email → UID via Firebase Auth (primary method)
                auth_user = firebase_auth.get_user_by_email(email)
                firebase_uid = auth_user.uid

                # Atomically increment points on user doc
                user_ref = db.collection("users").document(firebase_uid)
                user_doc = user_ref.get()
                current_data = user_doc.to_dict() if user_doc.exists else {}

                user_ref.set({
                    "medicPoints": firestore_module.Increment(points),
                    "miniAppBonus": True,
                    "email": email,
                    "miniAppTelegramId": pending_data.get("telegramId", ""),
                }, merge=True)

                # Update leaderboard atomically
                username = current_data.get("username", "")
                if username:
                    db.collection("leaderboard").document(firebase_uid).set({
                        "medicPoints": firestore_module.Increment(points),
                        "username": username,
                    }, merge=True)

                # Delete pending doc — points are now on the user doc
                db.collection("pending_medicpoints").document(email).delete()

                current_points = current_data.get("medicPoints", 0)
                applied += 1
                logger.info(f"Flushed {points} pending points to {firebase_uid} ({email}): {current_points} -> {current_points + points}")

            except Exception:
                # User not in Firebase Auth yet — leave pending for when they sign up
                skipped += 1

    except Exception as e:
        logger.error(f"flush_pending_medicpoints error: {e}")
        return {"applied": applied, "skipped": skipped, "failed": failed, "error": str(e)}

    logger.info(f"flush_pending_medicpoints complete: applied={applied}, skipped={skipped}")
    return {"applied": applied, "skipped": skipped, "failed": failed}


def get_user_medicpoints(telegram_id: str) -> dict:
    """
    Get a user's total MedicPoints from Firebase.

    Looks up the user's email from medicpoints_claims table,
    then queries Firebase for their medicPoints balance.

    Returns dict with points and status info.
    """
    conn = _get_db()
    # Get the email linked to this Telegram user
    row = conn.execute(
        "SELECT email FROM medicpoints_claims WHERE telegram_id = ? ORDER BY created_at DESC LIMIT 1",
        (str(telegram_id),)
    ).fetchone()

    if not row:
        conn.close()
        return {"success": False, "points": 0, "reason": "No email linked"}

    email = row["email"]

    # Check if another user has already used this email for a withdrawal
    other = conn.execute(
        "SELECT DISTINCT telegram_id FROM medicpoints_claims WHERE email = ? AND telegram_id != ?",
        (email, str(telegram_id))
    ).fetchall()
    if other:
        # Check if any of those other users have withdrawn (withdrawal_count > 0)
        other_ids = [r["telegram_id"] for r in other]
        placeholders = ",".join("?" * len(other_ids))
        used = conn.execute(
            f"SELECT user_id FROM wallets WHERE user_id IN ({placeholders}) AND withdrawal_count > 0",
            other_ids
        ).fetchone()
        if used:
            conn.close()
            return {"success": False, "points": 0, "reason": "This email is linked to another account that already withdrew"}

    # Check for cached firebase_uid first
    cached_uid = _get_cached_firebase_uid(conn, telegram_id)
    conn.close()

    db = get_firestore()
    if not db:
        return {"success": False, "points": 0, "reason": "Firebase unavailable"}

    try:
        # PRIMARY: resolve email → UID via Firebase Auth (or use cached UID)
        firebase_uid = cached_uid or _resolve_firebase_uid(email)

        if firebase_uid:
            user_ref = db.collection("users").document(firebase_uid)
            user_doc = user_ref.get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                points = user_data.get("medicPoints", 0)
                return {"success": True, "points": points, "email": email}

        # User not in Firebase Auth — check pending points
        pending_ref = db.collection("pending_medicpoints").document(email)
        pending_doc = pending_ref.get()
        if pending_doc.exists:
            points = pending_doc.to_dict().get("points", 0)
            return {"success": True, "points": points, "email": email, "pending": True}
        return {"success": True, "points": 0, "email": email}

    except Exception as e:
        logger.error(f"Failed to get medicpoints for {telegram_id}: {e}")
        return {"success": False, "points": 0, "reason": str(e)}


def upload_to_google_drive(file_content: bytes, filename: str, mime_type: str) -> dict:
    """
    Upload a file to Google Drive using service account credentials.

    Returns dict with file_id and shareable link.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
        from google.oauth2 import service_account
        import json

        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

        if creds_path and os.path.exists(creds_path):
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/drive.file"]
            )
        elif creds_json:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive.file"]
            )
        else:
            return {"success": False, "reason": "No Google credentials configured"}

        service = build("drive", "v3", credentials=creds)

        # Upload file
        file_metadata = {"name": filename}

        # If a shared folder ID is configured, upload there
        drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if drive_folder_id:
            file_metadata["parents"] = [drive_folder_id]

        media = MediaInMemoryUpload(file_content, mimetype=mime_type)
        file = service.files().create(
            body=file_metadata, media_body=media, fields="id,webViewLink"
        ).execute()

        # Make file viewable by anyone with link
        service.permissions().create(
            fileId=file["id"],
            body={"type": "anyone", "role": "reader"}
        ).execute()

        return {
            "success": True,
            "file_id": file["id"],
            "link": file.get("webViewLink", f"https://drive.google.com/file/d/{file['id']}/view")
        }

    except Exception as e:
        logger.error(f"Google Drive upload failed: {e}")
        return {"success": False, "reason": str(e)}


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
