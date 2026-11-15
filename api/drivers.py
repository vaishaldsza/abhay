"""
Driver & Fleet Run Operations API
Enforces transaction version checks and idempotent callback creation.
"""

import uuid
from flask import Blueprint, request, jsonify
from db import get_db, log_audit, mask_phone
from core.status import update_request_status
from api.events import broadcast_event

drivers_bp = Blueprint("drivers", __name__)

@drivers_bp.route("/api/driver/offers", methods=["GET"])
def get_driver_offers():
    db = get_db()
    vehicle_id = request.args.get("vehicle_id")
    driver_name = request.args.get("driver_name")
    from flask import session
    if session.get("role") == "driver" and session.get("vehicle_id"):
        vehicle_id = session.get("vehicle_id")

    sql = """
        SELECT o.*, 
               r.household_id, r.needs_json, r.status as request_status,
               h.first_name as resident_name, h.landmark, h.members, h.phone_masked,
               v.designation, v.driver_name, v.type as vehicle_type
        FROM offer o
        JOIN request r ON r.id = o.request_id
        JOIN household h ON h.id = r.household_id
        JOIN vehicle v ON v.id = o.vehicle_id
        WHERE o.status = 'pending'
    """
    params = []
    if vehicle_id:
        sql += " AND o.vehicle_id = ?"
        params.append(vehicle_id)
    if driver_name:
        sql += " AND v.driver_name LIKE ?"
        params.append(f"%{driver_name}%")

    sql += " ORDER BY o.created_at DESC"
    offers = [dict(row) for row in db.execute(sql, params).fetchall()]
    for o in offers:
        o["phone_masked"] = mask_phone(o["phone_masked"])
        # Derive expires_at (120 seconds from created_at)
        created_str = o.get("created_at")
        try:
            from datetime import datetime, timezone, timedelta
            if created_str:
                if "T" in created_str:
                    cd = datetime.fromisoformat(created_str)
                else:
                    cd = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                exp = cd + timedelta(seconds=120)
                o["expires_at"] = exp.isoformat()
            else:
                o["expires_at"] = None
        except Exception:
            o["expires_at"] = None

    # Active run for this driver/vehicle
    active_run = None
    if vehicle_id or driver_name:
        run_sql = """
            SELECT r.*, h.first_name as resident_name, h.landmark, h.members, h.phone_masked,
                   v.designation, v.driver_name
            FROM request r
            JOIN household h ON h.id = r.household_id
            JOIN vehicle v ON v.id = r.vehicle_id
            WHERE r.status IN ('driver_accepted', 'on_run', 'picked_up')
        """
        run_params = []
        if vehicle_id:
            run_sql += " AND r.vehicle_id = ?"
            run_params.append(vehicle_id)
        if driver_name:
            run_sql += " AND v.driver_name LIKE ?"
            run_params.append(f"%{driver_name}%")
        
        run_row = db.execute(run_sql, run_params).fetchone()
        if run_row:
            active_run = dict(run_row)
            active_run["phone_masked"] = mask_phone(active_run["phone_masked"])

    return jsonify({"success": True, "offers": offers, "active_run": active_run})

@drivers_bp.route("/api/driver/offers/<id>/accept", methods=["POST"])
def accept_offer(id):
    """
    Rule 5: Offer acceptance is version-checked in one DB transaction:
    if two drivers accept the same request, exactly one wins.
    Rule 6: The callback to the resident (with driver first name, vehicle, ETA)
    is created only after acceptance, and idempotent.
    """
    db = get_db()
    c = db.cursor()

    try:
        db.execute("BEGIN IMMEDIATE")

        # 1. Fetch offer and request
        c.execute("""
            SELECT o.*, r.household_id, r.status as req_status, r.version as req_version,
                   v.driver_name, v.designation
            FROM offer o
            JOIN request r ON r.id = o.request_id
            JOIN vehicle v ON v.id = o.vehicle_id
            WHERE o.id = ?
        """, (id,))
        row = c.fetchone()
        if not row:
            db.rollback()
            return jsonify({"success": False, "error": "Offer not found"}), 404

        if row["status"] != "pending":
            db.rollback()
            return jsonify({"success": False, "error": f"Offer is already {row['status']}"}), 400

        req_id = row["request_id"]
        req_version = row["req_version"]
        veh_id = row["vehicle_id"]
        hh_id = row["household_id"]
        driver_name = row["driver_name"].split()[0] # First name only
        veh_desig = row["designation"]

        if row["req_status"] != "request_recorded":
            db.rollback()
            return jsonify({"success": False, "error": "Request is already assigned to another driver"}), 409

        # 2. Version-checked atomic update on request
        c.execute("""
            UPDATE request
            SET status = 'driver_accepted', vehicle_id = ?, version = version + 1
            WHERE id = ? AND version = ? AND status = 'request_recorded'
        """, (veh_id, req_id, req_version))

        if c.rowcount == 0:
            db.rollback()
            return jsonify({"success": False, "error": "Conflict: Another driver accepted this request first"}), 409

        # 3. Update accepted offer
        c.execute("UPDATE offer SET status = 'accepted', version = version + 1 WHERE id = ?", (id,))

        # Expire all other pending offers for this request
        c.execute("UPDATE offer SET status = 'expired' WHERE request_id = ? AND id != ? AND status = 'pending'", (req_id, id))

        # 4. Update household status
        c.execute("UPDATE household SET status = 'driver_accepted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (hh_id,))

        # 5. Rule 6: Idempotent callback creation
        cb_id = f"cb-{req_id}"
        c.execute("""
            INSERT OR IGNORE INTO callback (id, household_id, request_id, driver_first_name, vehicle_designation, eta_minutes, status)
            VALUES (?, ?, ?, ?, ?, 15, 'scheduled')
        """, (cb_id, hh_id, req_id, driver_name, veh_desig))

        # 6. Audit log
        c.execute("""
            INSERT INTO audit_log (actor, actor_type, action, household_id, detail)
            VALUES (?, 'driver', 'DRIVER_OFFER_ACCEPTED', ?, ?)
        """, (driver_name, hh_id, f"Driver {driver_name} accepted offer {id} for request {req_id}. Idempotent callback scheduled."))

        db.commit()

        broadcast_event("offer_accepted", {
            "offer_id": id,
            "request_id": req_id,
            "vehicle_id": veh_id,
            "driver_name": driver_name,
            "household_id": hh_id,
            "status": "driver_accepted"
        })

        return jsonify({
            "success": True,
            "offer_id": id,
            "request_id": req_id,
            "status": "driver_accepted",
            "driver_first_name": driver_name,
            "eta_minutes": 15
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@drivers_bp.route("/api/driver/offers/<id>/decline", methods=["POST"])
def decline_offer(id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT o.*, v.driver_name FROM offer o JOIN vehicle v ON v.id = o.vehicle_id WHERE o.id = ?", (id,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "error": "Offer not found"}), 404

    driver_first = row["driver_name"].split()[0]
    c.execute("UPDATE offer SET status = 'declined' WHERE id = ?", (id,))
    log_audit(driver_first, "driver", "OFFER_DECLINED", None, f"Driver {driver_first} declined offer {id}", conn=db)
    db.commit()

    broadcast_event("offer_declined", {"offer_id": id})
    return jsonify({"success": True, "offer_id": id, "status": "declined"})

@drivers_bp.route("/api/runs/<id>/start", methods=["POST"])
def start_run(id):
    """Driver starts transit to location (on_run)."""
    db = get_db()
    update_request_status(id, "on_run", "driver", "driver", detail="Driver commenced transit towards resident", conn=db)
    db.commit()
    broadcast_event("run_started", {"request_id": id, "status": "on_run"})
    return jsonify({"success": True, "request_id": id, "status": "on_run"})

@drivers_bp.route("/api/runs/<id>/picked-up", methods=["POST"])
def picked_up_run(id):
    """Driver reports household picked up."""
    db = get_db()
    update_request_status(id, "picked_up", "driver", "driver", detail="Driver picked up household members", conn=db)
    db.commit()
    broadcast_event("run_picked_up", {"request_id": id, "status": "picked_up"})
    return jsonify({"success": True, "request_id": id, "status": "picked_up"})

@drivers_bp.route("/api/runs/<id>/complete", methods=["POST"])
def complete_run(id):
    """Driver reports safe arrival at relief center (evacuated)."""
    db = get_db()
    c = db.cursor()
    c.execute("SELECT vehicle_id FROM request WHERE id = ?", (id,))
    req = c.fetchone()
    veh_id = req["vehicle_id"] if req else None

    update_request_status(id, "evacuated", "driver", "driver", detail="Household safely evacuated to relief center", conn=db)

    # Free up vehicle
    if veh_id:
        c.execute("UPDATE vehicle SET status = 'available' WHERE id = ?", (veh_id,))

    db.commit()
    broadcast_event("run_completed", {"request_id": id, "status": "evacuated"})
    return jsonify({"success": True, "request_id": id, "status": "evacuated"})
