"""
Incident Management API
"""

import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify
from db import get_db, log_audit
from api.events import broadcast_event

incidents_bp = Blueprint("incidents", __name__)

@incidents_bp.route("/api/incidents", methods=["GET"])
def get_incidents():
    db = get_db()
    rows = db.execute("SELECT * FROM incident ORDER BY created_at DESC").fetchall()
    return jsonify({"success": True, "incidents": [dict(r) for r in rows]})

@incidents_bp.route("/api/incidents", methods=["POST"])
def create_incident():
    data = request.get_json() or {}
    name = data.get("name")
    hazard = data.get("hazard", "flood") # flood | cyclone | landslide
    if not name:
        return jsonify({"success": False, "error": "Incident name required"}), 400

    inc_id = f"inc-{uuid.uuid4().hex[:6]}"
    db = get_db()
    db.execute(
        "INSERT INTO incident (id, name, hazard, created_at) VALUES (?, ?, ?, ?)",
        (inc_id, name, hazard, datetime.utcnow().isoformat())
    )
    log_audit("dispatcher", "dispatcher", "INCIDENT_CREATED", None, f"Incident '{name}' ({hazard}) created", conn=db)
    db.commit()

    broadcast_event("incident_created", {"incident_id": inc_id, "name": name, "hazard": hazard})
    return jsonify({"success": True, "incident_id": inc_id, "name": name})

@incidents_bp.route("/api/incidents/<id>/close", methods=["POST"])
def close_incident(id):
    db = get_db()
    closed_at = datetime.utcnow().isoformat()
    db.execute("UPDATE incident SET closed_at = ? WHERE id = ?", (closed_at, id))
    log_audit("dispatcher", "dispatcher", "INCIDENT_CLOSED", None, f"Incident {id} closed at {closed_at}. 72h retention timer started.", conn=db)
    db.commit()
    broadcast_event("incident_closed", {"incident_id": id, "closed_at": closed_at})

    from api.audit import start_auto_purge_job
    start_auto_purge_job(id)

    return jsonify({"success": True, "incident_id": id, "closed_at": closed_at})
