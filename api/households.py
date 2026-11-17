"""
Household API Endpoints
"""

import uuid
from flask import Blueprint, request, jsonify
from db import get_db, mask_phone, encrypt_phone, log_audit
from api.events import broadcast_event
from core.priority import priority_score

households_bp = Blueprint("households", __name__)

@households_bp.route("/api/households", methods=["GET"])
def get_households():
    db = get_db()
    status_filter = request.args.get("status")
    lang_filter = request.args.get("language")
    search_query = request.args.get("search")
    emergency_filter = request.args.get("emergency")

    sql = """
        SELECT h.*, 
               m.cannot_walk, m.wheelchair_type, m.bedridden, m.elderly, m.pregnant, m.needs_medicine_oxygen, m.sleeping_room,
               r.id as request_id, r.status as request_status, r.vehicle_id,
               v.designation as vehicle_designation, v.driver_name as vehicle_driver,
               (SELECT emergency FROM call WHERE household_id = h.id ORDER BY created_at DESC LIMIT 1) as is_emergency
        FROM household h
        LEFT JOIN member m ON m.household_id = h.id
        LEFT JOIN request r ON r.household_id = h.id
        LEFT JOIN vehicle v ON v.id = r.vehicle_id
        WHERE 1=1
    """
    params = []

    if status_filter:
        sql += " AND h.status = ?"
        params.append(status_filter)

    if lang_filter:
        sql += " AND h.language = ?"
        params.append(lang_filter)

    if search_query:
        sql += " AND (h.first_name LIKE ? OR h.landmark LIKE ?)"
        params.append(f"%{search_query}%")
        params.append(f"%{search_query}%")

    if emergency_filter == "1":
        sql += " AND ((SELECT emergency FROM call WHERE household_id = h.id ORDER BY created_at DESC LIMIT 1) = 1 OR m.cannot_walk = 1 OR m.bedridden = 1)"

    sql += " ORDER BY h.updated_at DESC"

    rows = db.execute(sql, params).fetchall()

    households = []
    for r in rows:
        d = dict(r)
        d["phone_masked"] = mask_phone(d["phone_masked"])
        del d["phone_enc"] # Never expose hash or enc in UI API
        score, breakdown = priority_score(d)
        d["priority_score"] = score
        d["priority_breakdown"] = breakdown
        households.append(d)

    # Sort queue strictly by priority score (ordering aid) with updated_at tiebreaker
    households.sort(key=lambda h: (h.get("priority_score", 0), h.get("updated_at") or ""), reverse=True)

    return jsonify({"success": True, "count": len(households), "households": households})

@households_bp.route("/api/households/<id>", methods=["GET"])
def get_household(id):
    db = get_db()
    hh = db.execute("SELECT * FROM household WHERE id = ?", (id,)).fetchone()
    if not hh:
        return jsonify({"success": False, "error": "Household not found"}), 404

    hh_dict = dict(hh)
    hh_dict["phone_masked"] = mask_phone(hh_dict["phone_masked"])
    if "phone_enc" in hh_dict:
        del hh_dict["phone_enc"]
    score, breakdown = priority_score(hh_dict, conn=db)
    hh_dict["priority_score"] = score
    hh_dict["priority_breakdown"] = breakdown

    members = [dict(m) for m in db.execute("SELECT * FROM member WHERE household_id = ?", (id,)).fetchall()]
    calls = [dict(c) for c in db.execute("SELECT * FROM call WHERE household_id = ? ORDER BY created_at DESC", (id,)).fetchall()]
    reqs = [dict(r) for r in db.execute("SELECT * FROM request WHERE household_id = ?", (id,)).fetchall()]
    callbacks = [dict(cb) for cb in db.execute("SELECT * FROM callback WHERE household_id = ?", (id,)).fetchall()]
    field_visits = [dict(fv) for fv in db.execute("SELECT * FROM field_visit WHERE household_id = ?", (id,)).fetchall()]

    return jsonify({
        "success": True,
        "household": hh_dict,
        "members": members,
        "calls": calls,
        "requests": reqs,
        "callbacks": callbacks,
        "field_visits": field_visits
    })

@households_bp.route("/api/ready", methods=["POST"])
def register_household():
    """
    Household self sign-up with mandatory privacy consent checkbox.
    """
    data = request.get_json() or {}
    consent = data.get("consent", False)
    if not consent:
        return jsonify({"success": False, "error": "Privacy and emergency coordination consent is required."}), 400

    first_name = (data.get("first_name") or "").strip().split()[0] # Enforce first name only
    if not first_name:
        return jsonify({"success": False, "error": "First name is required."}), 400

    phone = data.get("phone", "")
    phone_masked = mask_phone(phone)
    phone_enc = encrypt_phone(phone)

    db = get_db()
    hh_id = f"hh-{uuid.uuid4().hex[:6]}"
    incident_id = data.get("incident_id", "inc-bantwal-01")
    landmark = data.get("landmark", "Bantwal")
    pin = data.get("pin", "574211")
    lat = float(data.get("lat", 12.8904))
    lng = float(data.get("lng", 75.0378))
    language = data.get("language", "kannada")
    members_count = int(data.get("members", 1))

    needs_evac = data.get("needs_evacuation", False)
    initial_status = "needs_help" if needs_evac else "can_help"

    db.execute(
        """INSERT INTO household (id, incident_id, first_name, phone_masked, phone_enc, landmark, pin, lat, lng, language, members, status, consent_given)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (hh_id, incident_id, first_name, phone_masked, phone_enc, landmark, pin, lat, lng, language, members_count, initial_status)
    )

    # Members details
    cannot_walk = 1 if data.get("cannot_walk") else 0
    bedridden = 1 if data.get("bedridden") else 0
    elderly = 1 if data.get("elderly") else 0
    pregnant = 1 if data.get("pregnant") else 0
    needs_med = 1 if data.get("needs_medicine_oxygen") else 0
    wheelchair_type = "wheelchair" if cannot_walk and not bedridden else ("stretcher" if bedridden else "none")
    sleeping_room = data.get("sleeping_room", "Ground Floor")

    db.execute(
        """INSERT INTO member (id, household_id, cannot_walk, wheelchair_type, bedridden, elderly, pregnant, needs_medicine_oxygen, sleeping_room)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"mem-{uuid.uuid4().hex[:6]}", hh_id, cannot_walk, wheelchair_type, bedridden, elderly, pregnant, needs_med, sleeping_room)
    )

    log_audit("resident", "resident", "HOUSEHOLD_REGISTERED", hh_id, f"Household registered by {first_name} with status {initial_status}", conn=db)
    db.commit()

    broadcast_event("household_registered", {"household_id": hh_id, "status": initial_status, "name": first_name})

    return jsonify({"success": True, "household_id": hh_id, "status": initial_status})

@households_bp.route("/api/field-visits", methods=["GET"])
def get_field_visits():
    db = get_db()
    rows = db.execute(
        """SELECT fv.*, h.first_name, h.phone_masked, h.landmark, h.pin, h.lat, h.lng, h.members, h.status as household_status
           FROM field_visit fv
           JOIN household h ON h.id = fv.household_id
           ORDER BY fv.created_at DESC"""
    ).fetchall()
    visits = []
    for r in rows:
        d = dict(r)
        d["phone_masked"] = mask_phone(d["phone_masked"])
        visits.append(d)
    return jsonify({"success": True, "field_visits": visits})

@households_bp.route("/api/field-visits/<id>/resolve", methods=["POST"])
def resolve_field_visit(id):
    data = request.get_json() or {}
    outcome = data.get("outcome", "safe") # safe / needs_help / evacuated
    notes = data.get("notes", "Visited in person by field patrol team")

    db = get_db()
    fv = db.execute("SELECT * FROM field_visit WHERE id = ?", (id,)).fetchone()
    if not fv:
        return jsonify({"success": False, "error": "Field visit not found"}), 404

    db.execute(
        "UPDATE field_visit SET status = 'resolved', notes = ? WHERE id = ?",
        (notes, id)
    )
    
    # Update household status
    new_status = "evacuated" if outcome == "evacuated" else ("needs_help" if outcome == "needs_help" else "can_help")
    from core.status import update_household_status
    try:
        update_household_status(
            household_id=fv["household_id"],
            new_status=new_status,
            actor="field_officer",
            actor_type="field_officer",
            detail=f"Field visit resolved: {notes} (status: {new_status})",
            conn=db
        )
    except Exception:
        pass

    log_audit("field_officer", "field_officer", "FIELD_VISIT_RESOLVED", fv["household_id"], f"Field visit {id} resolved: {notes}", conn=db)
    db.commit()

    broadcast_event("field_visit_resolved", {"field_visit_id": id, "household_id": fv["household_id"], "status": new_status})
    return jsonify({"success": True, "field_visit_id": id, "household_status": new_status})

@households_bp.route("/api/unanswered-retry", methods=["POST"])
def trigger_unanswered_retry():
    data = request.get_json() or {}
    household_id = data.get("household_id")
    from core.retry import process_unanswered_attempt
    db = get_db()

    if household_id:
        res = process_unanswered_attempt(household_id)
        broadcast_event("retry_escalated", res)
        return jsonify({"success": True, "escalation": res, "count": 1})
    else:
        # Batch retry for all not_reached households
        rows = db.execute("SELECT id FROM household WHERE status = 'not_reached'").fetchall()
        results = []
        for r in rows:
            res = process_unanswered_attempt(r["id"])
            results.append(res)
        broadcast_event("batch_retry_completed", {"count": len(results)})
        return jsonify({
            "success": True,
            "count": len(results),
            "message": f"Processed retry ladder for {len(results)} unanswered households",
            "results": results
        })


@households_bp.route("/api/field-visits", methods=["POST"])
def create_field_visit():
    data = request.get_json() or {}
    household_id = data.get("household_id")
    from flask import session
    assigned_officer = data.get("assigned_officer", "ASHA Worker Suma")
    reason = data.get("reason", "Flagged by dispatcher for in-person check")
    notes = data.get("notes", "Priority verification required.")

    if not household_id:
        return jsonify({"success": False, "error": "household_id is required"}), 400

    db = get_db()
    hh = db.execute("SELECT id FROM household WHERE id = ?", (household_id,)).fetchone()
    if not hh:
        return jsonify({"success": False, "error": "Household not found"}), 404

    fv_id = f"fv-{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO field_visit (id, household_id, assigned_officer, status, reason, notes)
           VALUES (?, ?, ?, 'pending', ?, ?)""",
        (fv_id, household_id, assigned_officer, reason, notes)
    )
    log_audit(
        actor=session.get("user_name", "Duty officer"),
        actor_type="dispatcher",
        action="FIELD_VISIT_FLAGGED",
        household_id=household_id,
        detail=f"Flagged for urgent field visit: {reason}",
        conn=db
    )
    db.commit()
    broadcast_event("field_visit_created", {"field_visit_id": fv_id, "household_id": household_id})
    return jsonify({"success": True, "field_visit_id": fv_id})

@households_bp.route("/api/households/<id>/fields", methods=["POST"])
def update_household_fields(id):
    data = request.get_json() or {}
    landmark = data.get("landmark")
    members = data.get("members")
    from flask import session
    db = get_db()
    hh = db.execute("SELECT * FROM household WHERE id = ?", (id,)).fetchone()
    if not hh:
        return jsonify({"success": False, "error": "Household not found"}), 404

    updates = []
    params = []
    if landmark:
        updates.append("landmark = ?")
        params.append(landmark)
    if members:
        updates.append("members = ?")
        params.append(int(members))

    if updates:
        params.append(id)
        db.execute(f"UPDATE household SET {', '.join(updates)} WHERE id = ?", params)
        log_audit(
            actor=session.get("user_name", "Duty officer"),
            actor_type="dispatcher",
            action="HOUSEHOLD_FIELDS_EDITED",
            household_id=id,
            detail=f"Updated operational fields: landmark='{landmark}', members={members}",
            conn=db
        )
        db.commit()
    return jsonify({"success": True, "household_id": id})

@households_bp.route("/api/ready/cancel", methods=["POST"])
def cancel_registration():
    data = request.get_json() or {}
    household_id = data.get("household_id")
    if not household_id:
        return jsonify({"success": False, "error": "household_id is required"}), 400
    db = get_db()
    db.execute("DELETE FROM request WHERE household_id = ?", (household_id,))
    db.execute("DELETE FROM household WHERE id = ?", (household_id,))
    log_audit(
        actor="Citizen",
        actor_type="resident",
        action="REGISTRATION_CANCELLED",
        household_id=household_id,
        detail="Resident cancelled their evacuation sign-up registration.",
        conn=db
    )
    db.commit()
    return jsonify({"success": True, "message": "Registration cancelled successfully."})
