import sqlite3
import hashlib
import hmac
import base64
from datetime import datetime, timezone
from pathlib import Path
from flask import g
from cryptography.fernet import Fernet, InvalidToken
from config import Config

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            Config.DATABASE_PATH,
            timeout=10.0
        )
        g.db.row_factory = sqlite3.Row
        # Enable foreign keys and WAL mode for concurrent access
        g.db.execute("PRAGMA foreign_keys = ON;")
        g.db.execute("PRAGMA journal_mode = WAL;")
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def get_standalone_db():
    conn = sqlite3.connect(
        Config.DATABASE_PATH,
        timeout=10.0
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()
    conn = get_standalone_db()
    conn.executescript(schema)
    
    # Check if water_arrival_minutes column exists on household table
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(household)")
    cols = [r["name"] for r in cur.fetchall()]
    if "phone" in cols:
        cur.execute("ALTER TABLE household DROP COLUMN phone")
    if "water_arrival_minutes" not in cols:
        cur.execute("ALTER TABLE household ADD COLUMN water_arrival_minutes REAL")
    if "phone_hash" not in cols:
        cur.execute("ALTER TABLE household ADD COLUMN phone_hash TEXT")
    if "verification_status" not in cols:
        cur.execute("ALTER TABLE household ADD COLUMN verification_status TEXT DEFAULT 'verified'")

    cur.execute("PRAGMA table_info(user)")
    u_cols = [r["name"] for r in cur.fetchall()]
    if "phone" in u_cols:
        cur.execute("ALTER TABLE user DROP COLUMN phone")
    if "phone_hash" not in u_cols:
        cur.execute("ALTER TABLE user ADD COLUMN phone_hash TEXT")
    if "phone_masked" not in u_cols:
        cur.execute("ALTER TABLE user ADD COLUMN phone_masked TEXT DEFAULT '+91 XXXXX XXXXX'")
    if "phone_enc" not in u_cols:
        cur.execute("ALTER TABLE user ADD COLUMN phone_enc TEXT")
    if "session_version" not in u_cols:
        cur.execute("ALTER TABLE user ADD COLUMN session_version INTEGER DEFAULT 1")
    
    conn.commit()
    migrate_phone_hashes(conn)
    conn.close()

def migrate_phone_hashes(conn=None) -> dict:
    """
    Re-hash existing rows in household and user using HMAC-SHA256 with PHONE_HASH_KEY.
    Only re-hashes what can be truthfully recovered via decrypt_phone() or valid raw input;
    never fabricates numbers. Drops legacy plaintext phone columns if present.
    Returns a summary dict of migrated vs unmigrated rows. Strictly idempotent.
    """
    close_after = False
    if conn is None:
        conn = get_standalone_db()
        close_after = True
    
    report = {
        "migrated_households": [],
        "unmigrated_households": [],
        "migrated_users": [],
        "unmigrated_users": []
    }
    try:
        # 1. Drop legacy plaintext phone columns if still present
        h_cols = [r["name"] for r in conn.execute("PRAGMA table_info(household)").fetchall()]
        if "phone" in h_cols:
            conn.execute("ALTER TABLE household DROP COLUMN phone")
        u_cols = [r["name"] for r in conn.execute("PRAGMA table_info(user)").fetchall()]
        if "phone" in u_cols:
            conn.execute("ALTER TABLE user DROP COLUMN phone")

        # 2. Re-hash household rows where phone_enc is a valid decryptable Fernet ciphertext
        hh_rows = conn.execute("SELECT id, phone_enc, phone_hash FROM household ORDER BY id").fetchall()
        for row in hh_rows:
            enc = row["phone_enc"]
            recovered = None
            if enc and enc != "PURGED":
                try:
                    recovered = decrypt_phone(enc)
                except Exception:
                    recovered = None
            if recovered:
                new_h = hash_phone(recovered)
                conn.execute("UPDATE household SET phone_hash = ? WHERE id = ?", (new_h, row["id"]))
                report["migrated_households"].append(row["id"])
            elif enc == "PURGED" or (enc is None and row["phone_hash"] is None):
                # Purged or empty, no phone to migrate, not an unmigrated failure
                pass
            else:
                report["unmigrated_households"].append(row["id"])

        # 3. Re-hash user rows
        users = conn.execute("SELECT id, phone_enc, phone_hash FROM user ORDER BY id").fetchall()
        for u in users:
            recovered = None
            enc = u["phone_enc"]
            if enc and enc != "PURGED":
                try:
                    recovered = decrypt_phone(enc)
                except Exception:
                    recovered = None
            if recovered:
                new_h = hash_phone(recovered)
                conn.execute("UPDATE user SET phone_hash = ? WHERE id = ?", (new_h, u["id"]))
                report["migrated_users"].append(u["id"])
            elif enc == "PURGED" or (enc is None and u["phone_hash"] is None):
                # Purged or empty, not an unmigrated failure
                pass
            else:
                report["unmigrated_users"].append(u["id"])

        conn.commit()
        return report
    finally:
        if close_after:
            conn.close()

def normalize_phone(phone_str: str) -> str:
    """Normalize phone to the last 10 digits for consistent comparison and hashing."""
    if not phone_str:
        return ""
    digits = "".join(c for c in phone_str if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits

def hash_phone(phone_str: str, key: str = None) -> str:
    """HMAC-SHA256 hash of normalized phone number keyed by PHONE_HASH_KEY from .env."""
    norm = normalize_phone(phone_str)
    if not norm:
        return ""
    k = (key or Config.PHONE_HASH_KEY).encode("utf-8")
    return hmac.new(k, norm.encode("utf-8"), hashlib.sha256).hexdigest()

def mask_phone(phone_str: str) -> str:
    """Mask phone strictly as +91 XXXXX XXXXX for UI display."""
    return "+91 XXXXX XXXXX"

def encrypt_phone(phone_str: str, key: str = None) -> str:
    """Encrypt phone number using Fernet authenticated symmetric encryption keyed by PHONE_ENCRYPTION_KEY."""
    if not phone_str:
        return ""
    k = (key or Config.PHONE_ENCRYPTION_KEY).encode("utf-8")
    f = Fernet(k)
    return f.encrypt(phone_str.encode("utf-8")).decode("utf-8")

def decrypt_phone(cipher_str: str, key: str = None) -> str:
    """Decrypt Fernet-encrypted ciphertext back to phone number string. Raises InvalidToken if tampered or invalid."""
    if not cipher_str or cipher_str == "PURGED":
        return ""
    k = (key or Config.PHONE_ENCRYPTION_KEY).encode("utf-8")
    f = Fernet(k)
    return f.decrypt(cipher_str.encode("utf-8")).decode("utf-8")

def log_audit(actor: str, actor_type: str, action: str, household_id: str = None, detail: str = None, conn=None):
    """
    Log an event to audit_log.
    actor_type must be one of: 'system', 'dispatcher', 'driver', 'resident', 'field_worker'
    """
    allowed_actor_types = {"system", "dispatcher", "driver", "resident", "field_worker"}
    if actor_type not in allowed_actor_types:
        raise ValueError(f"Invalid actor_type '{actor_type}'. Allowed: {allowed_actor_types}")
    
    close_after = False
    if conn is None:
        try:
            conn = get_db()
        except RuntimeError:
            conn = get_standalone_db()
            close_after = True

    try:
        conn.execute(
            """INSERT INTO audit_log (actor, actor_type, action, household_id, detail, ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (actor, actor_type, action, household_id, detail, datetime.now(timezone.utc).isoformat())
        )
        if close_after:
            conn.commit()
    finally:
        if close_after:
            conn.close()
