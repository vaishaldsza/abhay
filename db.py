import sqlite3
import hashlib
import base64
from datetime import datetime, timezone
from pathlib import Path
from flask import g
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
    conn.commit()
    conn.close()

def mask_phone(phone_str: str) -> str:
    """Mask phone strictly as +91 XXXXX XXXXX for UI display."""
    return "+91 XXXXX XXXXX"

def encrypt_phone(phone_str: str) -> str:
    """Hash and securely obscure phone so plaintext is never exposed or logged."""
    if not phone_str:
        return ""
    # Salted hash with SECRET_KEY
    salted = f"{Config.SECRET_KEY}:{phone_str}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()

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
