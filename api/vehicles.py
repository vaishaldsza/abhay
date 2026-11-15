"""
Vehicles & Fleet Management API
"""

import uuid
from flask import Blueprint, request, jsonify
from db import get_db, log_audit
from api.events import broadcast_event

vehicles_bp = Blueprint("vehicles", __name__)

@vehicles_bp.route("/api/vehicles", methods=["GET"])
def get_vehicles():
    db = get_db()
    rows = db.execute(
        """SELECT v.*,
                  (SELECT COUNT(*) FROM request WHERE vehicle_id = v.id AND status IN ('driver_accepted', 'on_run')) as active_passengers,
                  (SELECT r.id FROM request r WHERE r.vehicle_id = v.id AND r.status IN ('driver_accepted', 'on_run') LIMIT 1) as current_run_id
           FROM vehicle v
           ORDER BY v.id ASC"""
    ).fetchall()
    return jsonify({"success": True, "vehicles": [dict(r) for r in rows]})

@vehicles_bp.route("/api/vehicles", methods=["POST"])
def add_vehicle():
    data = request.get_json() or {}
    type_ = data.get("type", "boat")
    designation = data.get("designation")
    if not designation:
        return jsonify({"success": False, "error": "Vehicle designation required"}), 400

    driver_name = data.get("driver_name", "Driver").strip().split()[0] # First name only
    capacity = int(data.get("capacity", 4))
    stretcher = 1 if data.get("stretcher") else 0
    wheelchair = 1 if data.get("wheelchair") else 0
    lat = float(data.get("lat", 12.8904))
    lng = float(data.get("lng", 75.0378))

    veh_id = f"veh-{uuid.uuid4().hex[:4]}"
    db = get_db()
    db.execute(
        """INSERT INTO vehicle (id, type, designation, capacity, stretcher, wheelchair, driver_name, status, lat, lng)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?)""",
        (veh_id, type_, designation, capacity, stretcher, wheelchair, driver_name, lat, lng)
    )
    log_audit("dispatcher", "dispatcher", "VEHICLE_ADDED", None, f"Vehicle {designation} ({type_}) added to fleet", conn=db)
    db.commit()

    broadcast_event("vehicle_added", {"vehicle_id": veh_id, "designation": designation})
    return jsonify({"success": True, "vehicle_id": veh_id})
