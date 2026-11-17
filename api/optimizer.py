"""
Optimizer Blueprint
Exposes advisory ALNS optimization plan for fleet dispatch review.
Zero automated dispatching: plan suggestions must be individually approved by the human dispatcher.
"""

from flask import Blueprint, jsonify, request
from db import get_db, log_audit
from core.optimizer import generate_optimization_plan

optimizer_bp = Blueprint("optimizer", __name__)

@optimizer_bp.route("/api/optimizer/suggest-plan", methods=["GET", "POST"])
def suggest_plan():
    db = get_db()
    plan = generate_optimization_plan(db=db)
    
    # Audit log the generation of the advisory plan
    log_audit(
        actor="dispatcher",
        actor_type="dispatcher",
        action="OPTIMIZER_PLAN_SUGGESTED",
        household_id=None,
        detail=f"Generated advisory ALNS dispatch plan: {len(plan.get('assignments', []))} suggested assignments",
        conn=db
    )
    db.commit()

    return jsonify({
        "success": True,
        **plan
    })
