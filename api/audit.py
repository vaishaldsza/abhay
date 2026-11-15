"""
Audit Logs & Privacy Deletion API
Strict adherence to data minimization, 72-hour auto-purge, and manual purge.
"""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from db import get_db, log_audit
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
    Requires explicit confirmation flag.
    """
    data = request.get_json() or {}
    if not data.get("confirm", False):
        return jsonify({
            "success": False,
            "error": "Explicit confirmation {'confirm': true} is required to initiate emergency data purge."
        }), 400

    db = get_db()
    c = db.cursor()

    # Redact sensitive fields
    c.execute("""
        UPDATE household
        SET landmark = '[PURGED]', pin = '000000', phone_enc = 'PURGED'
    """)
    c.execute("""
        UPDATE call
        SET audio_path = NULL, transcript = '[VOICE RECORD PURGED POST-DISASTER]'
    """)

    log_audit("dispatcher", "dispatcher", "MANUAL_PRIVACY_PURGE", None, "Resident identifiable data purged per 72h privacy mandate", conn=db)
    db.commit()

    broadcast_event("privacy_purged", {"status": "purged", "timestamp": datetime.now(timezone.utc).isoformat()})

    return jsonify({
        "success": True,
        "message": "Resident identifiable data successfully purged from active operational tables."
    })

def purge_closed_incidents_older_than_72h(db):
    """Auto-deletes incidents closed more than 72 hours ago."""
    threshold = (datetime.utcnow() - timedelta(hours=72)).isoformat()
    c = db.cursor()
    c.execute("SELECT id FROM incident WHERE closed_at IS NOT NULL AND closed_at < ?", (threshold,))
    expired = c.fetchall()
    for inc in expired:
        inc_id = inc["id"]
        # Delete related child records
        c.execute("DELETE FROM field_visit WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
        c.execute("DELETE FROM callback WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
        c.execute("DELETE FROM offer WHERE request_id IN (SELECT id FROM request WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?))", (inc_id,))
        c.execute("DELETE FROM request WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
        c.execute("DELETE FROM call WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
        c.execute("DELETE FROM member WHERE household_id IN (SELECT id FROM household WHERE incident_id = ?)", (inc_id,))
        c.execute("DELETE FROM household WHERE incident_id = ?", (inc_id,))
        c.execute("DELETE FROM incident WHERE id = ?", (inc_id,))
        log_audit("system", "system", "AUTO_PURGE_72H", None, f"Auto-purged incident {inc_id} 72 hours after closure", conn=db)
    db.commit()
