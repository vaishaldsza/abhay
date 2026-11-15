"""
Requests & Dispatcher Assignment API
"""

import uuid
import json
from flask import Blueprint, request, jsonify
from db import get_db, log_audit
from core.status import update_household_status
from api.events import broadcast_event

requests_bp = Blueprint("requests", __name__)

@requests_bp.route("/api/requests", methods=["POST"])
def create_request():
    """Creates an evacuation ride request from a household."""
    data = request.get_json() or {}
    household_id = data.get("household_id")
    if not household_id:
        return jsonify({"success": False, "error": "household_id is required"}), 400

    db = get_db()
    hh = db.execute("SELECT * FROM household WHERE id = ?", (household_id,)).fetchone()
    if not hh:
        return jsonify({"success": False, "error": "Household not found"}), 404

    # Check if request already exists
    existing = db.execute("SELECT * FROM request WHERE household_id = ? AND status != 'evacuated'", (household_id,)).fetchone()
    if existing:
        return jsonify({"success": True, "request_id": existing["id"], "status": existing["status"]})

    req_id = f"req-{uuid.uuid4().hex[:6]}"
    needs_json = json.dumps({
        "members": hh["members"],
        "notes": data.get("notes", "Evacuation rescue requested")
    })

    # Update household status to request_recorded
    update_household_status(
        household_id=household_id,
        new_status="request_recorded",
        actor="resident",
        actor_type="resident",
        detail="Evacuation ride request submitted by resident",
        conn=db
    )

    db.execute(
        """INSERT INTO request (id, household_id, needs_json, status, version)
           VALUES (?, ?, ?, 'request_recorded', 1)""",
        (req_id, household_id, needs_json)
    )
    db.commit()

    broadcast_event("request_created", {"request_id": req_id, "household_id": household_id, "status": "request_recorded"})

    return jsonify({"success": True, "request_id": req_id, "status": "request_recorded"})

@requests_bp.route("/api/assign", methods=["POST"])
def assign_vehicle():
    """
    Rule 7: A human dispatcher must approve every assignment before an offer reaches a driver.
    Creates a pending offer for the driver.
    """
    data = request.get_json() or {}
    request_id = data.get("request_id")
    household_id = data.get("household_id")
    vehicle_id = data.get("vehicle_id")
    dispatcher_name = data.get("dispatcher_name", "Duty Dispatcher")

    db = get_db()
    if not request_id and household_id:
        req_row = db.execute("SELECT * FROM request WHERE household_id = ? ORDER BY created_at DESC LIMIT 1", (household_id,)).fetchone()
        if req_row:
            request_id = req_row["id"]
        else:
            request_id = f"req-{uuid.uuid4().hex[:6]}"
            db.execute("INSERT INTO request (id, household_id, status, version) VALUES (?, ?, 'request_recorded', 1)", (request_id, household_id))
            db.commit()

    if not request_id or not vehicle_id:
        return jsonify({"success": False, "error": "request_id (or household_id) and vehicle_id are required"}), 400
    req_row = db.execute("SELECT * FROM request WHERE id = ?", (request_id,)).fetchone()
    if not req_row:
        return jsonify({"success": False, "error": "Request not found"}), 404

    veh_row = db.execute("SELECT * FROM vehicle WHERE id = ?", (vehicle_id,)).fetchone()
    if not veh_row:
        return jsonify({"success": False, "error": "Vehicle not found"}), 404

    # Create offer
    offer_id = f"off-{uuid.uuid4().hex[:6]}"
    db.execute(
        """INSERT INTO offer (id, request_id, vehicle_id, status, version)
           VALUES (?, ?, ?, 'pending', 1)""",
        (offer_id, request_id, vehicle_id)
    )

    log_audit(
        actor=dispatcher_name,
        actor_type="dispatcher",
        action="DISPATCHER_OFFER_DISPATCHED",
        household_id=req_row["household_id"],
        detail=f"Dispatcher approved and sent offer {offer_id} for vehicle {veh_row['designation']} (Driver: {veh_row['driver_name']})",
        conn=db
    )
    db.commit()

    broadcast_event("offer_created", {
        "offer_id": offer_id,
        "request_id": request_id,
        "vehicle_id": vehicle_id,
        "driver_name": veh_row["driver_name"],
        "designation": veh_row["designation"]
    })

    return jsonify({
        "success": True,
        "offer_id": offer_id,
        "request_id": request_id,
        "vehicle_id": vehicle_id,
        "status": "pending"
    })
