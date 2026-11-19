"""
Audit Logs & Privacy Deletion API
Strict adherence to data minimization, 72-hour auto-purge, and manual purge.
"""

import threading
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, session
from config import Config
from db import get_db, log_audit, get_standalone_db
from api.events import broadcast_event

audit_bp = Blueprint("audit", __name__)

@audit_bp.route("/api/audit", methods=["GET"])
def get_audit_logs():
    db = get_db()
    limit = int(request.args.get("limit", 100))
    rows = db.execute(
        """SELECT * FROM audit_log ORDER BY id DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    return jsonify({"success": True, "count": len(rows), "logs": [dict(r) for r in rows]})

@audit_bp.route("/api/privacy/delete-now", methods=["POST"])
def manual_privacy_delete():
    """
    Purges resident identifiers upon incident closure or authorized emergency manual purge.
    Scopes purge to selected incident_id (defaults to active incident).
    Requires Dispatcher role and typed confirmation.
    Clears phone_enc, phone_hash, phone_masked, names, landmarks, coordinates, and other
    personal fields for households AND resident user accounts in the scoped incident so no
    personal identifiers remain and phone numbers can be cleanly reused in future incidents.
    Invalidates active resident user sessions by bumping session_version.
    Runs PRAGMA wal_checkpoint(TRUNCATE) and VACUUM at completion.
    """
    # 1. Require Dispatcher role
    if session.get("role") != "dispatcher":
        return jsonify({"success": False, "error": "Forbidden: dispatcher role required"}), 403

    data = request.get_json(silent=True) or {}

    # 2. Require typed confirmation
    confirmation = data.get("confirmation") or data.get("confirm")
    if not confirmation or (isinstance(confirmation, str) and not confirmation.strip()):
        return jsonify({
            "success": False,
            "error": "Typed confirmation is required to initiate emergency data purge."
        }), 400

    db = get_db()
    c = db.cursor()

    # 3. Scope to selected incident_id
    incident_id = data.get("incident_id")
    if not incident_id:
        active_inc = db.execute("SELECT id FROM incident WHERE closed_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        incident_id = active_inc["id"] if active_inc else "inc-bantwal-01"

    inc = db.execute("SELECT id FROM incident WHERE id = ?", (incident_id,)).fetchone()
    if not inc:
        return jsonify({"success": False, "error": f"Incident '{incident_id}' not found"}), 404

    # 4. Invalidate and purge resident user accounts associated with this incident
    c.execute("""
        UPDATE user
        SET full_name = '[PURGED]',
            phone_masked = '[PURGED]',
            phone_enc = '[PURGED]',
            phone_hash = NULL,
            email = NULL,
            password_hash = '[PURGED]',
            session_version = session_version + 1
        WHERE role = 'resident' AND (
            phone_hash IN (
                SELECT phone_hash FROM household WHERE incident_id = ? AND phone_hash IS NOT NULL
            )
            OR (? = 'inc-bantwal-01' OR ? = 'all')
        )
    """, (incident_id, incident_id, incident_id))

    # 5. Purge related operational and telemetry records for this incident
    c.execute("UPDATE call SET audio_path = NULL, transcript = '', extracted_json = '{}' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (incident_id,))
    c.execute("UPDATE request SET needs_json = '{}' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (incident_id,))
    c.execute("UPDATE member SET sleeping_room = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (incident_id,))
    c.execute("UPDATE callback SET driver_first_name = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (incident_id,))
    c.execute("UPDATE field_visit SET notes = '[PURGED]', reason = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (incident_id,))
    c.execute("UPDATE audit_log SET actor = '[PURGED]', detail = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?) OR actor_type = 'resident'", (incident_id,))

    # 6. Purge all personal and identifiable fields on households in scoped incident
    c.execute("""
        UPDATE household
        SET first_name = '[PURGED]',
            phone_masked = '[PURGED]',
            phone_enc = '[PURGED]',
            phone_hash = NULL,
            landmark = '[PURGED]',
            pin = '000000',
            lat = NULL,
            lng = NULL
        WHERE incident_id = ?
    """, (incident_id,))

    # 7. Purge generated audio files in audio_cache and static/audio (except the 3 seed clips and .gitkeep)
    if Config.AUDIO_CACHE_DIR.exists():
        for f in Config.AUDIO_CACHE_DIR.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                try:
                    f.unlink()
                except Exception:
                    pass

    static_audio_dir = Config.BASE_DIR / "static" / "audio"
    seed_clips = {"sample_kannada.wav", "sample_hindi.wav", "sample_hinglish.wav"}
    if static_audio_dir.exists():
        for f in static_audio_dir.iterdir():
            if f.is_file() and f.name.lower() not in seed_clips:
                try:
                    f.unlink()
                except Exception:
                    pass

    # 8. Log the purge without personal data
    log_audit("dispatcher", "dispatcher", "MANUAL_PRIVACY_PURGE", None, f"Resident identifiable data purged for incident {incident_id} per privacy mandate", conn=db)
    db.commit()

    # 9. At the end of delete-now: PRAGMA wal_checkpoint(TRUNCATE) then VACUUM then TRUNCATE checkpoint
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    db.execute("VACUUM;")
    db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    db.commit()

    broadcast_event("privacy_purged", {"status": "purged", "incident_id": incident_id, "timestamp": datetime.now(timezone.utc).isoformat()})

    return jsonify({
        "success": True,
        "incident_id": incident_id,
        "message": f"Resident identifiable data successfully purged for incident {incident_id}."
    })

def purge_closed_incidents_older_than_72h(db=None, current_time=None) -> list:
    """
    Auto-purges incidents and resident identifiers closed more than 72 hours ago.
    Accepts optional current_time (for clock mocking in tests).
    Returns list of purged incident IDs.
    """
    close_conn = False
    if db is None:
        db = get_standalone_db()
        close_conn = True

    now = current_time or datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    c = db.cursor()
    c.execute("SELECT id, closed_at FROM incident WHERE closed_at IS NOT NULL")
    incidents = c.fetchall()
    purged_ids = []

    for inc in incidents:
        closed_at_str = inc["closed_at"]
        try:
            closed_dt = datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
            if closed_dt.tzinfo is None:
                closed_dt = closed_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if (now - closed_dt).total_seconds() >= 72 * 3600:
            inc_id = inc["id"]
            # Purge resident users for this incident
            c.execute("""
                UPDATE user
                SET full_name = '[PURGED]',
                    phone_masked = '[PURGED]',
                    phone_enc = '[PURGED]',
                    phone_hash = NULL,
                    email = NULL,
                    password_hash = '[PURGED]',
                    session_version = session_version + 1
                WHERE role = 'resident' AND phone_hash IN (
                    SELECT phone_hash FROM household WHERE incident_id = ? AND phone_hash IS NOT NULL
                )
            """, (inc_id,))

            # Purge household telemetry
            c.execute("""
                UPDATE household
                SET first_name = '[PURGED]',
                    phone_masked = '[PURGED]',
                    phone_enc = '[PURGED]',
                    phone_hash = NULL,
                    landmark = '[PURGED]',
                    pin = '000000',
                    lat = NULL,
                    lng = NULL
                WHERE incident_id = ?
            """, (inc_id,))

            c.execute("UPDATE call SET audio_path = NULL, transcript = '', extracted_json = '{}' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
            c.execute("UPDATE request SET needs_json = '{}' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
            c.execute("UPDATE member SET sleeping_room = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
            c.execute("UPDATE callback SET driver_first_name = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
            c.execute("UPDATE field_visit SET notes = '[PURGED]', reason = '[PURGED]' WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))

            log_audit("system", "system", "AUTO_PURGE_72H", None, f"Auto-purged incident {inc_id} 72 hours after closure", conn=db)
            purged_ids.append(inc_id)

    if purged_ids:
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        db.commit()
        db.execute("VACUUM;")
        db.commit()

    if close_conn:
        db.close()
    return purged_ids

def start_auto_purge_job(incident_id: str, delay_seconds: float = 72 * 3600):
    """Starts a background timer to trigger automatic purge after 72 hours."""
    def job():
        purge_closed_incidents_older_than_72h()

    t = threading.Timer(delay_seconds, job)
    t.daemon = True
    t.start()
    return t

