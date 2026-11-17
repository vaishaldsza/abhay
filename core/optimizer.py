"""
Adaptive Large Neighborhood Search (ALNS) Evacuation Optimizer
Generates advisory assignment plans for district dispatchers.
Guarantees:
  1. Never reassigns offers already accepted.
  2. Respects seat capacity, wheelchair, and stretcher constraints.
  3. Optimizer cost is always <= greedy cost on the same input.
  4. Returns suggestions only: dispatcher must approve every assignment.
  5. Never exposes travel times or ETAs before driver acceptance.
"""

import math
import random
import copy
from typing import Dict, Any, List, Tuple, Optional
from config import Config
from db import get_db, get_standalone_db
from core.assign import haversine_km
from core.priority import priority_score

BIG_RISK_PENALTY = 1000.0
UNASSIGNED_BASE_PENALTY = 5000.0

def calculate_lateness_risk(distance_km: float, water_arrival_min: Optional[float], special_needs: bool = False) -> float:
    """
    Computes evacuation lateness risk index E in [0, 1].
    Lateness = travel_min + boarding_min - (arrival - buffer)
    E = min(1, max(0, lateness / R))
    Internal calculation only; travel times are never displayed.
    """
    if water_arrival_min is None:
        return 0.0

    nominal_speed = getattr(Config, "NOMINAL_SPEED_KMH", 25.0)
    base_boarding = getattr(Config, "BOARDING_TIME_BASE_MIN", 3.0)
    special_boarding = getattr(Config, "BOARDING_TIME_SPECIAL_MIN", 4.0)
    buffer_min = getattr(Config, "SAFETY_BUFFER_MIN", 5.0)
    r_margin = getattr(Config, "RAMP_MARGIN_R_MIN", 20.0)

    travel_min = (distance_km / max(nominal_speed, 1.0)) * 60.0
    boarding_min = base_boarding + (special_boarding if special_needs else 0.0)
    
    lateness = (travel_min + boarding_min) - (water_arrival_min - buffer_min)
    return min(1.0, max(0.0, lateness / max(r_margin, 1.0)))

def calculate_plan_cost_breakdown(
    assignments: Dict[str, str], # {request_id: vehicle_id}
    requests_data: Dict[str, Dict[str, Any]],
    vehicles_data: Dict[str, Dict[str, Any]],
    use_risk_model: bool
) -> Dict[str, float]:
    """
    Calculates cost of an assignment plan separated into:
      - assigned_cost: transit distance and lateness penalties of assigned households
      - unassigned_penalty: penalty incurred by unassigned households
      - total_cost: sum of assigned_cost and unassigned_penalty
    """
    assigned_cost = 0.0

    # Assigned requests cost
    for req_id, veh_id in assignments.items():
        req = requests_data.get(req_id)
        veh = vehicles_data.get(veh_id)
        if not req or not veh:
            continue

        dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0
        w_r = req.get("priority_weight", 10.0)

        if use_risk_model:
            e_r = calculate_lateness_risk(dist, req.get("water_arrival_minutes"), req.get("special_needs", False))
            cost_r = (BIG_RISK_PENALTY * e_r) + (w_r * dist)
        else:
            cost_r = w_r * dist

        assigned_cost += cost_r

    # Unassigned requests penalty
    unassigned_penalty = 0.0
    for req_id, req in requests_data.items():
        if req_id not in assignments:
            w_r = req.get("priority_weight", 10.0)
            unassigned_penalty += UNASSIGNED_BASE_PENALTY * (w_r / 10.0)

    total_cost = assigned_cost + unassigned_penalty
    return {
        "assigned_cost": round(assigned_cost, 2),
        "unassigned_penalty": round(unassigned_penalty, 2),
        "total_cost": round(total_cost, 2)
    }

def calculate_plan_cost(
    assignments: Dict[str, str], # {request_id: vehicle_id}
    requests_data: Dict[str, Dict[str, Any]],
    vehicles_data: Dict[str, Dict[str, Any]],
    use_risk_model: bool
) -> float:
    """
    Calculates total cost of an assignment plan.
    If RISK_MODEL is true: Cost = sum(BIG * E_r + w_r * distance_r)
    If RISK_MODEL is false: Cost = sum(w_r * distance_r)
    Unassigned requests incur a penalty proportional to priority weight.
    """
    return calculate_plan_cost_breakdown(assignments, requests_data, vehicles_data, use_risk_model)["total_cost"]

def is_assignment_feasible(
    req_id: str,
    veh_id: str,
    current_assignments: Dict[str, str],
    requests_data: Dict[str, Dict[str, Any]],
    vehicles_data: Dict[str, Dict[str, Any]]
) -> bool:
    """Checks capacity and stretcher/wheelchair feasibility for a candidate assignment."""
    req = requests_data.get(req_id)
    veh = vehicles_data.get(veh_id)
    if not req or not veh:
        return False

    # 1. Stretcher / Wheelchair constraints
    if req.get("stretcher_needed") and not veh.get("stretcher"):
        return False
    if req.get("wheelchair_needed") and not (veh.get("wheelchair") or veh.get("stretcher")):
        return False

    # 2. Cumulative seat capacity check on vehicle
    already_assigned_seats = sum(
        requests_data[r_id]["members"]
        for r_id, v_id in current_assignments.items()
        if v_id == veh_id and r_id != req_id
    )
    if already_assigned_seats + req["members"] > veh["capacity"]:
        return False

    return True

def optimize_assignments(
    requests_list: List[Dict[str, Any]],
    vehicles_list: List[Dict[str, Any]],
    iterations: int = 60,
    seed: Optional[int] = None
) -> Tuple[Dict[str, str], float, float]:
    """
    Runs simplified ALNS over unassigned requests and available vehicles.
    Returns: (best_plan, best_cost, greedy_cost)
    """
    if seed is not None:
        random.seed(seed)

    use_risk_model = getattr(Config, "RISK_MODEL", False)

    # Index by ID
    requests_data = {r["id"]: r for r in requests_list}
    vehicles_data = {v["id"]: v for v in vehicles_list}

    # ----------------------------------------------------
    # STAGE 1: Greedy Start by Priority Score
    # ----------------------------------------------------
    sorted_reqs = sorted(
        requests_list,
        key=lambda r: r.get("priority_weight", 0.0),
        reverse=True
    )

    greedy_plan: Dict[str, str] = {}
    for req in sorted_reqs:
        best_veh_id = None
        best_inc_cost = float("inf")

        for veh in vehicles_list:
            if is_assignment_feasible(req["id"], veh["id"], greedy_plan, requests_data, vehicles_data):
                dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0
                w_r = req.get("priority_weight", 10.0)
                if use_risk_model:
                    e_r = calculate_lateness_risk(dist, req.get("water_arrival_minutes"), req.get("special_needs", False))
                    inc_cost = (BIG_RISK_PENALTY * e_r) + (w_r * dist)
                else:
                    inc_cost = w_r * dist

                if inc_cost < best_inc_cost:
                    best_inc_cost = inc_cost
                    best_veh_id = veh["id"]

        if best_veh_id:
            greedy_plan[req["id"]] = best_veh_id

    greedy_cost = calculate_plan_cost(greedy_plan, requests_data, vehicles_data, use_risk_model)

    # If no assignments possible or no vehicles, return greedy
    if not greedy_plan or not vehicles_list:
        return greedy_plan, greedy_cost, greedy_cost

    # ----------------------------------------------------
    # STAGE 2: ALNS (Destroy / Repair / Simulated Annealing)
    # ----------------------------------------------------
    best_plan = copy.deepcopy(greedy_plan)
    best_cost = greedy_cost

    current_plan = copy.deepcopy(greedy_plan)
    current_cost = greedy_cost

    temp = 100.0
    cooling_rate = 0.95

    for it in range(iterations):
        repaired_plan = copy.deepcopy(current_plan)
        assigned_keys = list(repaired_plan.keys())

        # Neighborhood exploration: 2-opt vehicle swap or destroy/repair
        op = random.choice(["destroy_repair", "destroy_repair", "swap"])
        if op == "swap" and len(assigned_keys) >= 2:
            r1, r2 = random.sample(assigned_keys, 2)
            v1, v2 = repaired_plan[r1], repaired_plan[r2]
            if v1 != v2:
                temp_plan = copy.deepcopy(repaired_plan)
                del temp_plan[r1]
                del temp_plan[r2]
                if (is_assignment_feasible(r1, v2, temp_plan, requests_data, vehicles_data) and
                    is_assignment_feasible(r2, v1, {**temp_plan, r1: v2}, requests_data, vehicles_data)):
                    repaired_plan[r1] = v2
                    repaired_plan[r2] = v1
        else:
            # 1. Destroy: remove 20-30% of assignments
            if assigned_keys:
                destroy_frac = random.uniform(0.20, 0.30)
                k_destroy = max(1, int(len(assigned_keys) * destroy_frac))
                destroyed_reqs = random.sample(assigned_keys, k_destroy)
                for d_id in destroyed_reqs:
                    del repaired_plan[d_id]

            # 2. Repair: re-insert unassigned requests (shuffle half the time to break greedy bias)
            unassigned_reqs = [r for r in requests_list if r["id"] not in repaired_plan]
            if random.random() < 0.5:
                random.shuffle(unassigned_reqs)
            else:
                unassigned_reqs.sort(key=lambda r: r.get("priority_weight", 0.0), reverse=True)

            for req in unassigned_reqs:
                best_v = None
                best_c = float("inf")
                for veh in vehicles_list:
                    if is_assignment_feasible(req["id"], veh["id"], repaired_plan, requests_data, vehicles_data):
                        dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0
                        w_r = req.get("priority_weight", 10.0)
                        if use_risk_model:
                            e_r = calculate_lateness_risk(dist, req.get("water_arrival_minutes"), req.get("special_needs", False))
                            cost = (BIG_RISK_PENALTY * e_r) + (w_r * dist)
                        else:
                            cost = w_r * dist

                        if cost < best_c:
                            best_c = cost
                            best_v = veh["id"]

                if best_v:
                    repaired_plan[req["id"]] = best_v

        # 3. Cost and Simulated Annealing Acceptance
        candidate_cost = calculate_plan_cost(repaired_plan, requests_data, vehicles_data, use_risk_model)

        cost_diff = candidate_cost - current_cost
        if cost_diff < 0:
            current_plan = repaired_plan
            current_cost = candidate_cost
            if candidate_cost < best_cost:
                best_plan = copy.deepcopy(repaired_plan)
                best_cost = candidate_cost
        else:
            prob = math.exp(-cost_diff / max(temp, 0.001))
            if random.random() < prob:
                current_plan = repaired_plan
                current_cost = candidate_cost

        temp *= cooling_rate

    # Best plan cost is mathematically guaranteed to be <= greedy_cost
    if best_cost > greedy_cost:
        best_plan = copy.deepcopy(greedy_plan)
        best_cost = greedy_cost

    return best_plan, best_cost, greedy_cost

def generate_optimization_plan(conn=None, db=None) -> Dict[str, Any]:
    """
    Inspects live operational state and generates an advisory dispatch plan.
    Strict Rule: Only suggests offers for pending requests. Never alters DB state.
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
        # 1. Fetch unassigned/pending requests
        # Rule: Never touch accepted/on_run/picked_up/evacuated requests
        pending_rows = conn.execute("""
            SELECT r.id as request_id, r.household_id, r.status as request_status,
                   h.first_name, h.landmark, h.members, h.lat, h.lng, h.water_arrival_minutes,
                   m.cannot_walk, m.wheelchair_type, m.bedridden, m.elderly, m.needs_medicine_oxygen,
                   (SELECT emergency FROM call WHERE household_id = h.id ORDER BY created_at DESC LIMIT 1) as is_emergency
            FROM request r
            JOIN household h ON h.id = r.household_id
            LEFT JOIN member m ON m.household_id = h.id
            WHERE r.status IN ('request_recorded', 'needs_help')
              AND r.vehicle_id IS NULL
        """).fetchall()

        # If no requests in request table, also look for households in 'needs_help' without requests
        needs_help_hh = conn.execute("""
            SELECT h.id as household_id, h.first_name, h.landmark, h.members, h.lat, h.lng, h.water_arrival_minutes,
                   m.cannot_walk, m.wheelchair_type, m.bedridden, m.elderly, m.needs_medicine_oxygen,
                   (SELECT emergency FROM call WHERE household_id = h.id ORDER BY created_at DESC LIMIT 1) as is_emergency
            FROM household h
            LEFT JOIN member m ON m.household_id = h.id
            WHERE h.status = 'needs_help'
              AND h.id NOT IN (SELECT household_id FROM request WHERE status != 'evacuated')
        """).fetchall()

        requests_list = []
        for row in pending_rows:
            d = dict(row)
            p_score, _ = priority_score(d)
            stretcher_needed = bool(d.get("bedridden") or d.get("wheelchair_type") == "stretcher_needed")
            wheelchair_needed = bool(d.get("cannot_walk") or (d.get("wheelchair_type") and d.get("wheelchair_type") != "none"))
            requests_list.append({
                "id": d["request_id"],
                "household_id": d["household_id"],
                "household_name": d["first_name"],
                "landmark": d.get("landmark") or "Flood zone location",
                "members": int(d.get("members") or 1),
                "lat": d.get("lat") or 12.8904,
                "lng": d.get("lng") or 75.0378,
                "water_arrival_minutes": d.get("water_arrival_minutes"),
                "priority_weight": p_score,
                "stretcher_needed": stretcher_needed,
                "wheelchair_needed": wheelchair_needed,
                "special_needs": bool(stretcher_needed or wheelchair_needed)
            })

        for row in needs_help_hh:
            d = dict(row)
            p_score, _ = priority_score(d)
            stretcher_needed = bool(d.get("bedridden") or d.get("wheelchair_type") == "stretcher_needed")
            wheelchair_needed = bool(d.get("cannot_walk") or (d.get("wheelchair_type") and d.get("wheelchair_type") != "none"))
            fake_req_id = f"req-{d['household_id']}"
            requests_list.append({
                "id": fake_req_id,
                "household_id": d["household_id"],
                "household_name": d["first_name"],
                "landmark": d.get("landmark") or "Flood zone location",
                "members": int(d.get("members") or 1),
                "lat": d.get("lat") or 12.8904,
                "lng": d.get("lng") or 75.0378,
                "water_arrival_minutes": d.get("water_arrival_minutes"),
                "priority_weight": p_score,
                "stretcher_needed": stretcher_needed,
                "wheelchair_needed": wheelchair_needed,
                "special_needs": bool(stretcher_needed or wheelchair_needed)
            })

        # 2. Fetch available vehicles
        veh_rows = conn.execute("SELECT * FROM vehicle WHERE status = 'available' ORDER BY id ASC").fetchall()
        vehicles_list = [dict(v) for v in veh_rows]

        best_plan, best_cost, greedy_cost = optimize_assignments(requests_list, vehicles_list)

        # Build human-friendly plan representation
        plan_items = []
        vehicles_map = {v["id"]: v for v in vehicles_list}
        requests_map = {r["id"]: r for r in requests_list}

        for req_id, veh_id in best_plan.items():
            req = requests_map.get(req_id)
            veh = vehicles_map.get(veh_id)
            if not req or not veh:
                continue

            dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0
            
            # Formulate honest suggestion reason
            if req.get("stretcher_needed"):
                reason = f"Optimal stretcher-bay match ({dist} km distance, {veh['designation']})"
            elif req.get("wheelchair_needed"):
                reason = f"Optimal wheelchair ramp match ({dist} km distance, {veh['designation']})"
            else:
                reason = f"Capacity match ({veh['capacity']} seats for {req['members']} souls, {dist} km)"

            plan_items.append({
                "request_id": req["id"],
                "household_id": req["household_id"],
                "household_name": req["household_name"],
                "landmark": req["landmark"],
                "members": req["members"],
                "priority_score": req["priority_weight"],
                "vehicle_id": veh["id"],
                "vehicle_designation": veh["designation"],
                "vehicle_type": veh["type"],
                "driver_name": veh["driver_name"],
                "distance_km": dist,
                "reason": reason
            })

        return {
            "success": True,
            "total_pending_requests": len(requests_list),
            "assigned_count": len(plan_items),
            "unassigned_count": len(requests_list) - len(plan_items),
            "greedy_cost": greedy_cost,
            "optimizer_cost": best_cost,
            "risk_model_enabled": getattr(Config, "RISK_MODEL", False),
            "plan": plan_items
        }

    finally:
        if close_after:
            conn.close()
