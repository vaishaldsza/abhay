"""
Core Priority Scoring Engine for Abhay
Calculates deterministic urgency scores and component breakdowns.
Used as an ordering aid for dispatchers and call floor operators.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Union
from config import Config
from db import get_db, get_standalone_db

def compute_unanswered_minutes(household: Dict[str, Any]) -> float:
    """Computes minutes since the household was queued without contact."""
    if household.get("status") != "not_reached":
        return 0.0

    ts_str = household.get("updated_at") or household.get("created_at")
    if ts_str:
        try:
            # Handle ISO string with or without Z
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = (now - dt).total_seconds() / 60.0
            return max(0.0, diff)
        except Exception:
            pass
            
    # Fallback to retry_count assumption (15 min per retry)
    retries = household.get("retry_count", 1)
    return float(retries * 15.0)

def priority_score(household: Union[Dict[str, Any], str], conn=None) -> Tuple[float, Dict[str, float]]:
    """
    Computes priority score and detailed breakdown for a household.
    Returns: (total_score, breakdown_dict)
    
    Weights are configured in Config.PRIORITY_WEIGHTS:
      - emergency
      - bedridden
      - oxygen (needs_medicine_oxygen)
      - cannot_walk
      - elderly
      - minutes unanswered (for not_reached status)
    """
    weights = getattr(Config, "PRIORITY_WEIGHTS", {
        "emergency": 50.0,
        "bedridden": 40.0,
        "oxygen": 35.0,
        "cannot_walk": 30.0,
        "elderly": 20.0,
        "unanswered_per_minute": 0.5,
        "max_unanswered_points": 30.0
    })

    # If household is passed as an ID string, fetch full details from DB
    if isinstance(household, str):
        close_after = False
        if conn is None:
            try:
                conn = get_db()
            except RuntimeError:
                conn = get_standalone_db()
                close_after = True
        try:
            row = conn.execute("""
                SELECT h.*, 
                       m.cannot_walk, m.wheelchair_type, m.bedridden, m.elderly, m.pregnant, m.needs_medicine_oxygen,
                       (SELECT emergency FROM call WHERE household_id = h.id ORDER BY created_at DESC LIMIT 1) as is_emergency
                FROM household h
                LEFT JOIN member m ON m.household_id = h.id
                WHERE h.id = ?
            """, (household,)).fetchone()
            if row:
                household = dict(row)
            else:
                return 0.0, {}
        finally:
            if close_after:
                conn.close()
    elif not isinstance(household, dict):
        household = dict(household)

    breakdown = {}

    # 1. Emergency
    is_emergency = bool(household.get("is_emergency") or household.get("emergency"))
    breakdown["emergency"] = weights.get("emergency", 50.0) if is_emergency else 0.0

    # 2. Bedridden
    is_bedridden = bool(household.get("bedridden"))
    breakdown["bedridden"] = weights.get("bedridden", 40.0) if is_bedridden else 0.0

    # 3. Oxygen / Medical
    needs_oxygen = bool(household.get("needs_medicine_oxygen") or household.get("oxygen"))
    breakdown["oxygen"] = weights.get("oxygen", 35.0) if needs_oxygen else 0.0

    # 4. Cannot Walk / Mobility
    cannot_walk = bool(household.get("cannot_walk"))
    breakdown["cannot_walk"] = weights.get("cannot_walk", 30.0) if cannot_walk else 0.0

    # 5. Elderly
    is_elderly = bool(household.get("elderly"))
    breakdown["elderly"] = weights.get("elderly", 20.0) if is_elderly else 0.0

    # 6. Unanswered wait time
    mins_unanswered = compute_unanswered_minutes(household)
    unanswered_rate = weights.get("unanswered_per_minute", 0.5)
    max_unanswered = weights.get("max_unanswered_points", 30.0)
    unanswered_pts = min(mins_unanswered * unanswered_rate, max_unanswered)
    breakdown["unanswered"] = round(unanswered_pts, 1)

    total_score = round(sum(breakdown.values()), 1)
    return total_score, breakdown
