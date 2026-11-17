"""
Vehicle Assignment & Ranking Engine for Abhay
Filters vehicles strictly by seat capacity, stretcher/wheelchair requirements, and haversine distance.
Rule: Never compute or return time estimates prior to driver acceptance.
"""

import math
from typing import List, Dict, Any, Optional
from db import get_db, get_standalone_db

def haversine_km(lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]) -> Optional[float]:
    """Calculates straight-line spherical distance between two coordinates in kilometers."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

def suggest_vehicles(household_id: str, conn=None, db=None) -> List[Dict[str, Any]]:
    """
    Ranks available vehicles for a given household:
      1. Filters by headcount capacity (capacity >= household.members)
      2. Filters by stretcher / wheelchair constraints
      3. Ranks remaining vehicles by straight-line haversine distance
      4. Generates a clear reason string without any travel time estimates.
    """
    if conn is None and db is not None:
        conn = db
    close_after = False
    if conn is None:
        try:
            conn = get_db()
        except RuntimeError:
            conn = get_standalone_db()
            close_after = True

    try:
        # Fetch household details
        hh = conn.execute("SELECT * FROM household WHERE id = ?", (household_id,)).fetchone()
        if not hh:
            return []

        hh_dict = dict(hh)
        members_count = int(hh_dict.get("members") or 1)
        hh_lat = hh_dict.get("lat")
        hh_lng = hh_dict.get("lng")

        # Fetch member vulnerability traits
        members = conn.execute("SELECT * FROM member WHERE household_id = ?", (household_id,)).fetchall()
        stretcher_needed = False
        wheelchair_needed = False

        for m in members:
            m_dict = dict(m)
            if m_dict.get("bedridden") or m_dict.get("wheelchair_type") == "stretcher_needed":
                stretcher_needed = True
            if m_dict.get("cannot_walk") or (m_dict.get("wheelchair_type") and m_dict.get("wheelchair_type") != "none"):
                wheelchair_needed = True

        # Fetch available vehicles
        veh_rows = conn.execute("SELECT * FROM vehicle WHERE status = 'available' ORDER BY id ASC").fetchall()
        suggestions = []

        for v in veh_rows:
            vd = dict(v)
            cap = int(vd.get("capacity") or 0)
            has_stretcher = bool(vd.get("stretcher"))
            has_wheelchair = bool(vd.get("wheelchair"))

            # 1. Seat Capacity Constraint
            if cap < members_count:
                continue

            # 2. Medical & Mobility Constraints
            if stretcher_needed and not has_stretcher:
                continue
            if wheelchair_needed and not (has_wheelchair or has_stretcher):
                continue

            # 3. Distance calculation
            dist = haversine_km(hh_lat, hh_lng, vd.get("lat"), vd.get("lng"))
            if dist is None:
                dist = 999.0

            # 4. Formulate specific operational reason without timing
            if stretcher_needed:
                reason = f"Nearest stretcher-equipped ambulance ({dist} km; capacity {cap} seats for {members_count} souls)"
            elif wheelchair_needed:
                reason = f"Nearest wheelchair-accessible vehicle ({dist} km; capacity {cap} seats for {members_count} souls)"
            elif vd.get("type") == "boat":
                reason = f"Nearest watercraft for flood terrain ({dist} km; capacity {cap} seats for {members_count} souls)"
            elif vd.get("type") == "bus":
                reason = f"High-capacity evac bus ({dist} km; capacity {cap} seats for {members_count} souls)"
            else:
                reason = f"Nearest {vd.get('type')} ({dist} km; capacity {cap} seats for {members_count} souls)"

            suggestions.append({
                "id": vd["id"],
                "type": vd["type"],
                "designation": vd["designation"],
                "capacity": cap,
                "space_flags": {
                    "has_stretcher": has_stretcher,
                    "has_wheelchair": has_wheelchair
                },
                "distance_km": dist,
                "driver_name": vd["driver_name"],
                "reason": reason
            })

        # Rank by distance ascending
        suggestions.sort(key=lambda s: s["distance_km"])
        return suggestions

    finally:
        if close_after:
            conn.close()
