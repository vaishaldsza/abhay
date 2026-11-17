"""
Synthetic Night Simulation & Fleet Optimization Benchmark
Evaluates scenarios under vehicle scarcity:
  1. Extreme Scarcity: 3 vehicles (12 seats total) vs 24 households (~72 souls), distant base (8-12 km), tight flood arrival deadlines (15-45 min). Dominated by seat shortage.
  2. Moderate Scarcity: 6 vehicles (54 seats total) vs 24 households (~72 souls), regional fleet, normal flood arrival deadlines (45-120 min). Loose deadlines.
  3. Bound Deadlines: 8 vehicles (96 seats total) vs 24 households (~72 souls), distant base (8-12 km), tight flood arrival deadlines (15-45 min). Sufficient seats, but deadlines bind.

Methodological Invariants:
  - On-time % denominator is ALL households needing a ride (unassigned count as NOT evacuated on time).
  - Headcount evacuated on time (people) reported per method.
  - Costs separated into assigned-plan cost, unassigned penalty, and total cost with penalty share.
  - Paired headcount differences (Optimizer vs FCFS and Optimizer vs Greedy) per seed.
  - Strictly labeled 'synthetic' with single-trip vehicles.
Outputs to evals/sim_results.json.
"""

import os
import json
import math
import random
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple

import sys
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import Config
from core.assign import haversine_km
from core.priority import priority_score
from core.optimizer import (
    optimize_assignments,
    calculate_lateness_risk,
    calculate_plan_cost,
    calculate_plan_cost_breakdown,
    is_assignment_feasible,
    BIG_RISK_PENALTY
)

def generate_extreme_scarcity_night(seed: int, n_households: int = 24) -> Dict[str, Any]:
    """
    Scenario 1: Extreme Scarcity (Dominated by Seat Shortage)
      - 3 vehicles (12 seats total) vs 24 households (~72 souls)
      - Distant depot (~8-12 km away)
      - Tight flood arrival window (15 to 45 min)
    """
    rng = random.Random(seed)
    depot_lat, depot_lng = 12.8200, 75.0800

    vehicles = [
        {"id": "v-01", "type": "boat", "designation": "NDRF Flood Boat 1", "capacity": 6, "stretcher": 0, "wheelchair": 0, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-02", "type": "ambulance", "designation": "108 Stretcher Ambulance", "capacity": 2, "stretcher": 1, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-03", "type": "car", "designation": "District 4x4 Bolero", "capacity": 4, "stretcher": 0, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)}
    ]

    cluster_centers = [(12.8950, 75.0320), (12.8820, 75.0450)]
    households = []
    for i in range(n_households):
        hh_id = f"syn-hh-{i+1:03d}"
        cluster_lat, cluster_lng = rng.choice(cluster_centers)
        members = rng.randint(2, 4)
        is_emergency = 1 if rng.random() < 0.25 else 0
        cannot_walk = 1 if rng.random() < 0.30 else 0
        bedridden = 1 if (cannot_walk and rng.random() < 0.45) else 0
        elderly = 1 if (rng.random() < 0.35 or bedridden) else 0
        needs_oxygen = 1 if (bedridden or rng.random() < 0.20) else 0
        stretcher_needed = bool(bedridden)
        wheelchair_needed = bool(cannot_walk and not bedridden)
        water_arrival = round(rng.uniform(15.0, 45.0), 1)

        hh_dict = {
            "id": hh_id, "household_id": hh_id, "household_name": f"Citizen-{i+1}",
            "members": members, "is_emergency": is_emergency, "cannot_walk": cannot_walk,
            "bedridden": bedridden, "elderly": elderly, "needs_medicine_oxygen": needs_oxygen,
            "stretcher_needed": stretcher_needed, "wheelchair_needed": wheelchair_needed,
            "special_needs": bool(stretcher_needed or wheelchair_needed),
            "water_arrival_minutes": water_arrival,
            "lat": cluster_lat + rng.gauss(0, 0.004),
            "lng": cluster_lng + rng.gauss(0, 0.004),
            "arrival_sequence": i
        }
        score, _ = priority_score(hh_dict)
        hh_dict["priority_weight"] = score
        households.append(hh_dict)

    return {"households": households, "vehicles": vehicles}

def generate_moderate_scarcity_night(seed: int, n_households: int = 24) -> Dict[str, Any]:
    """
    Scenario 2: Moderate Scarcity (Loose Deadlines)
      - 6 vehicles (54 seats total): 2 boats (6, 8), 2 ambulances (2, 2), 1 bus (32), 1 car (4)
      - Regional staging locations (in and around Bantwal zone)
      - Normal flood arrival window (45 to 120 min)
    """
    rng = random.Random(seed)
    vehicles = [
        {"id": "v-01", "type": "boat", "designation": "Rescue Boat NDRF-1", "capacity": 6, "stretcher": 0, "wheelchair": 0, "lat": 12.8904 + rng.uniform(-0.003, 0.003), "lng": 75.0378 + rng.uniform(-0.003, 0.003)},
        {"id": "v-02", "type": "boat", "designation": "Rescue Boat SDRF-2", "capacity": 8, "stretcher": 0, "wheelchair": 0, "lat": 12.8930 + rng.uniform(-0.003, 0.003), "lng": 75.0350 + rng.uniform(-0.003, 0.003)},
        {"id": "v-03", "type": "ambulance", "designation": "108 Ambulance Unit 4", "capacity": 2, "stretcher": 1, "wheelchair": 1, "lat": 12.8880 + rng.uniform(-0.003, 0.003), "lng": 75.0410 + rng.uniform(-0.003, 0.003)},
        {"id": "v-04", "type": "ambulance", "designation": "Red Cross Rapid Unit", "capacity": 2, "stretcher": 1, "wheelchair": 1, "lat": 12.8950 + rng.uniform(-0.003, 0.003), "lng": 75.0310 + rng.uniform(-0.003, 0.003)},
        {"id": "v-05", "type": "bus", "designation": "KSRTC Evac Bus B-12", "capacity": 32, "stretcher": 0, "wheelchair": 0, "lat": 12.8850 + rng.uniform(-0.003, 0.003), "lng": 75.0450 + rng.uniform(-0.003, 0.003)},
        {"id": "v-06", "type": "car", "designation": "District Jeep Bolero 7", "capacity": 4, "stretcher": 0, "wheelchair": 1, "lat": 12.8920 + rng.uniform(-0.003, 0.003), "lng": 75.0390 + rng.uniform(-0.003, 0.003)}
    ]

    cluster_centers = [(12.8950, 75.0320), (12.8820, 75.0450)]
    households = []
    for i in range(n_households):
        hh_id = f"syn-hh-{i+1:03d}"
        cluster_lat, cluster_lng = rng.choice(cluster_centers)
        members = rng.randint(2, 4)
        is_emergency = 1 if rng.random() < 0.25 else 0
        cannot_walk = 1 if rng.random() < 0.30 else 0
        bedridden = 1 if (cannot_walk and rng.random() < 0.45) else 0
        elderly = 1 if (rng.random() < 0.35 or bedridden) else 0
        needs_oxygen = 1 if (bedridden or rng.random() < 0.20) else 0
        stretcher_needed = bool(bedridden)
        wheelchair_needed = bool(cannot_walk and not bedridden)
        water_arrival = round(rng.uniform(45.0, 120.0), 1)

        hh_dict = {
            "id": hh_id, "household_id": hh_id, "household_name": f"Citizen-{i+1}",
            "members": members, "is_emergency": is_emergency, "cannot_walk": cannot_walk,
            "bedridden": bedridden, "elderly": elderly, "needs_medicine_oxygen": needs_oxygen,
            "stretcher_needed": stretcher_needed, "wheelchair_needed": wheelchair_needed,
            "special_needs": bool(stretcher_needed or wheelchair_needed),
            "water_arrival_minutes": water_arrival,
            "lat": cluster_lat + rng.gauss(0, 0.004),
            "lng": cluster_lng + rng.gauss(0, 0.004),
            "arrival_sequence": i
        }
        score, _ = priority_score(hh_dict)
        hh_dict["priority_weight"] = score
        households.append(hh_dict)

    return {"households": households, "vehicles": vehicles}

def generate_bound_deadlines_night(seed: int, n_households: int = 24) -> Dict[str, Any]:
    """
    Scenario 3: Bound Deadlines (Seats are Sufficient, but Deadlines Bind)
      - 8 vehicles (96 seats total for ~72 people):
        2 boats (12, 12), 2 buses (24, 24), 2 ambulances (4, 4), 2 cars (8, 8)
      - Distant depot (~8-12 km away)
      - Tight flood arrival window (15 to 45 min)
    """
    rng = random.Random(seed)
    depot_lat, depot_lng = 12.8200, 75.0800

    vehicles = [
        {"id": "v-01", "type": "boat", "designation": "NDRF Flood Boat 1", "capacity": 12, "stretcher": 0, "wheelchair": 0, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-02", "type": "boat", "designation": "SDRF Flood Boat 2", "capacity": 12, "stretcher": 0, "wheelchair": 0, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-03", "type": "bus", "designation": "KSRTC Evac Bus 1", "capacity": 24, "stretcher": 0, "wheelchair": 0, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-04", "type": "bus", "designation": "KSRTC Evac Bus 2", "capacity": 24, "stretcher": 0, "wheelchair": 0, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-05", "type": "ambulance", "designation": "108 Ambulance 1", "capacity": 4, "stretcher": 1, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-06", "type": "ambulance", "designation": "108 Ambulance 2", "capacity": 4, "stretcher": 1, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-07", "type": "car", "designation": "District Bolero 1", "capacity": 8, "stretcher": 0, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)},
        {"id": "v-08", "type": "car", "designation": "District Bolero 2", "capacity": 8, "stretcher": 0, "wheelchair": 1, "lat": depot_lat + rng.uniform(-0.005, 0.005), "lng": depot_lng + rng.uniform(-0.005, 0.005)}
    ]

    cluster_centers = [(12.8950, 75.0320), (12.8820, 75.0450)]
    households = []
    for i in range(n_households):
        hh_id = f"syn-hh-{i+1:03d}"
        cluster_lat, cluster_lng = rng.choice(cluster_centers)
        members = rng.randint(2, 4)
        is_emergency = 1 if rng.random() < 0.25 else 0
        cannot_walk = 1 if rng.random() < 0.30 else 0
        bedridden = 1 if (cannot_walk and rng.random() < 0.45) else 0
        elderly = 1 if (rng.random() < 0.35 or bedridden) else 0
        needs_oxygen = 1 if (bedridden or rng.random() < 0.20) else 0
        stretcher_needed = bool(bedridden)
        wheelchair_needed = bool(cannot_walk and not bedridden)
        water_arrival = round(rng.uniform(15.0, 45.0), 1)

        hh_dict = {
            "id": hh_id, "household_id": hh_id, "household_name": f"Citizen-{i+1}",
            "members": members, "is_emergency": is_emergency, "cannot_walk": cannot_walk,
            "bedridden": bedridden, "elderly": elderly, "needs_medicine_oxygen": needs_oxygen,
            "stretcher_needed": stretcher_needed, "wheelchair_needed": wheelchair_needed,
            "special_needs": bool(stretcher_needed or wheelchair_needed),
            "water_arrival_minutes": water_arrival,
            "lat": cluster_lat + rng.gauss(0, 0.004),
            "lng": cluster_lng + rng.gauss(0, 0.004),
            "arrival_sequence": i
        }
        score, _ = priority_score(hh_dict)
        hh_dict["priority_weight"] = score
        households.append(hh_dict)

    return {"households": households, "vehicles": vehicles}

def run_fcfs(households: List[Dict[str, Any]], vehicles: List[Dict[str, Any]]) -> Dict[str, str]:
    requests_data = {h["id"]: h for h in households}
    vehicles_data = {v["id"]: v for v in vehicles}
    plan: Dict[str, str] = {}
    fcfs_order = sorted(households, key=lambda h: h["arrival_sequence"])

    for req in fcfs_order:
        for veh in vehicles:
            if is_assignment_feasible(req["id"], veh["id"], plan, requests_data, vehicles_data):
                plan[req["id"]] = veh["id"]
                break
    return plan

def run_greedy(households: List[Dict[str, Any]], vehicles: List[Dict[str, Any]], use_risk_model: bool) -> Dict[str, str]:
    requests_data = {h["id"]: h for h in households}
    vehicles_data = {v["id"]: v for v in vehicles}
    plan: Dict[str, str] = {}
    priority_order = sorted(households, key=lambda h: h["priority_weight"], reverse=True)

    for req in priority_order:
        best_v = None
        best_cost = float("inf")
        for veh in vehicles:
            if is_assignment_feasible(req["id"], veh["id"], plan, requests_data, vehicles_data):
                dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0
                w_r = req["priority_weight"]
                if use_risk_model:
                    e_r = calculate_lateness_risk(dist, req.get("water_arrival_minutes"), req.get("special_needs"))
                    cost = (BIG_RISK_PENALTY * e_r) + (w_r * dist)
                else:
                    cost = w_r * dist
                if cost < best_cost:
                    best_cost = cost
                    best_v = veh["id"]
        if best_v:
            plan[req["id"]] = best_v
    return plan

def evaluate_metrics(
    plan: Dict[str, str],
    households: List[Dict[str, Any]],
    vehicles: List[Dict[str, Any]]
) -> Dict[str, float]:
    """
    Computes evacuation metrics over ALL households needing a ride.
    Strict Rule: Unassigned households count as NOT evacuated on time.
    """
    req_map = {h["id"]: h for h in households}
    veh_map = {v["id"]: v for v in vehicles}

    total_hh = len(households)
    total_headcount = sum(h["members"] for h in households)

    on_time_hh = 0
    on_time_headcount = 0
    assigned_count = len(plan)

    nominal_speed = getattr(Config, "NOMINAL_SPEED_KMH", 25.0)
    base_boarding = getattr(Config, "BOARDING_TIME_BASE_MIN", 3.0)
    special_boarding = getattr(Config, "BOARDING_TIME_SPECIAL_MIN", 4.0)
    buffer_min = getattr(Config, "SAFETY_BUFFER_MIN", 5.0)

    for req_id, veh_id in plan.items():
        req = req_map[req_id]
        veh = veh_map[veh_id]
        dist = haversine_km(req["lat"], req["lng"], veh["lat"], veh["lng"]) or 1.0

        travel_min = (dist / nominal_speed) * 60.0
        boarding_min = base_boarding + (special_boarding if req.get("special_needs") else 0.0)
        water_arr = req.get("water_arrival_minutes") or 120.0

        if (travel_min + boarding_min) <= (water_arr - buffer_min):
            on_time_hh += 1
            on_time_headcount += req["members"]

    # Recomputed over ALL households needing a ride
    on_time_hh_pct = round((on_time_hh / total_hh * 100.0) if total_hh > 0 else 0.0, 1)

    return {
        "assigned_count": assigned_count,
        "total_households": total_hh,
        "total_headcount": total_headcount,
        "on_time_hh_count": on_time_hh,
        "on_time_hh_pct": on_time_hh_pct,
        "on_time_headcount": on_time_headcount
    }

def run_scenario_benchmark(
    generator_fn,
    scenario_name: str,
    scenario_desc: str,
    num_seeds: int = 60,
    use_risk_model: bool = True
) -> Dict[str, Any]:
    Config.RISK_MODEL = use_risk_model
    formula_name = "Risk-Weighted Cost = sum_{assigned}(1000 * E_r + w_r * d_r) + sum_{unassigned}(5000 * w_r / 10)" if use_risk_model else "Priority-Weighted Cost = sum_{assigned}(w_r * d_r) + sum_{unassigned}(5000 * w_r / 10)"
    units_name = "penalty points"

    fcfs_ot_pct, fcfs_hc, fcfs_asgn, fcfs_unasgn, fcfs_tot = [], [], [], [], []
    greedy_ot_pct, greedy_hc, greedy_asgn, greedy_unasgn, greedy_tot = [], [], [], [], []
    opt_ot_pct, opt_hc, opt_asgn, opt_unasgn, opt_tot = [], [], [], [], []

    paired_cost_diffs_greedy = []      # greedy_total - opt_total
    paired_headcount_diffs_fcfs = []   # opt_hc - fcfs_hc
    paired_headcount_diffs_greedy = [] # opt_hc - greedy_hc

    cost_better, cost_tied, cost_worse = 0, 0, 0
    hc_fcfs_better, hc_fcfs_tied, hc_fcfs_worse = 0, 0, 0
    hc_greedy_better, hc_greedy_tied, hc_greedy_worse = 0, 0, 0

    for s in range(1, num_seeds + 1):
        night = generator_fn(seed=2000 + s)
        hh = night["households"]
        vv = night["vehicles"]
        req_data = {h["id"]: h for h in hh}
        veh_data = {v["id"]: v for v in vv}

        p_fcfs = run_fcfs(hh, vv)
        p_greedy = run_greedy(hh, vv, use_risk_model)
        p_opt, cost_opt, cost_greedy = optimize_assignments(hh, vv, iterations=60, seed=s)

        b_fcfs = calculate_plan_cost_breakdown(p_fcfs, req_data, veh_data, use_risk_model)
        b_greedy = calculate_plan_cost_breakdown(p_greedy, req_data, veh_data, use_risk_model)
        b_opt = calculate_plan_cost_breakdown(p_opt, req_data, veh_data, use_risk_model)

        m_fcfs = evaluate_metrics(p_fcfs, hh, vv)
        m_greedy = evaluate_metrics(p_greedy, hh, vv)
        m_opt = evaluate_metrics(p_opt, hh, vv)

        fcfs_ot_pct.append(m_fcfs["on_time_hh_pct"])
        fcfs_hc.append(m_fcfs["on_time_headcount"])
        fcfs_asgn.append(b_fcfs["assigned_cost"])
        fcfs_unasgn.append(b_fcfs["unassigned_penalty"])
        fcfs_tot.append(b_fcfs["total_cost"])

        greedy_ot_pct.append(m_greedy["on_time_hh_pct"])
        greedy_hc.append(m_greedy["on_time_headcount"])
        greedy_asgn.append(b_greedy["assigned_cost"])
        greedy_unasgn.append(b_greedy["unassigned_penalty"])
        greedy_tot.append(b_greedy["total_cost"])

        opt_ot_pct.append(m_opt["on_time_hh_pct"])
        opt_hc.append(m_opt["on_time_headcount"])
        opt_asgn.append(b_opt["assigned_cost"])
        opt_unasgn.append(b_opt["unassigned_penalty"])
        opt_tot.append(b_opt["total_cost"])

        # Cost difference vs greedy
        c_diff = round(b_greedy["total_cost"] - b_opt["total_cost"], 2)
        paired_cost_diffs_greedy.append(c_diff)
        if c_diff > 0.01:
            cost_better += 1
        elif c_diff < -0.01:
            cost_worse += 1
        else:
            cost_tied += 1

        # Headcount difference vs FCFS (people)
        hc_diff_f = m_opt["on_time_headcount"] - m_fcfs["on_time_headcount"]
        paired_headcount_diffs_fcfs.append(hc_diff_f)
        if hc_diff_f > 0:
            hc_fcfs_better += 1
        elif hc_diff_f < 0:
            hc_fcfs_worse += 1
        else:
            hc_fcfs_tied += 1

        # Headcount difference vs Greedy (people)
        hc_diff_g = m_opt["on_time_headcount"] - m_greedy["on_time_headcount"]
        paired_headcount_diffs_greedy.append(hc_diff_g)
        if hc_diff_g > 0:
            hc_greedy_better += 1
        elif hc_diff_g < 0:
            hc_greedy_worse += 1
        else:
            hc_greedy_tied += 1

    def stats(arr):
        return {
            "p5": round(float(np.percentile(arr, 5)), 1),
            "median": round(float(np.median(arr)), 1),
            "p95": round(float(np.percentile(arr, 95)), 1)
        }

    opt_tot_med = float(np.median(opt_tot))
    opt_unasgn_med = float(np.median(opt_unasgn))
    unasgn_share_pct = round((opt_unasgn_med / opt_tot_med * 100.0) if opt_tot_med > 0 else 0.0, 1)

    greedy_asgn_med = float(np.median(greedy_asgn))
    opt_asgn_med = float(np.median(opt_asgn))
    routing_gain_pct = round(((greedy_asgn_med - opt_asgn_med) / greedy_asgn_med * 100.0) if greedy_asgn_med > 0 else 0.0, 2)

    return {
        "scenario_name": scenario_name,
        "scenario_description": scenario_desc,
        "cost_formula": formula_name,
        "cost_units": units_name,
        "unassigned_penalty_share_pct": unasgn_share_pct,
        "routing_gain_assigned_cost_pct": routing_gain_pct,
        "methods": {
            "first_come_first_served": {
                "label": "First-Come-First-Served (FCFS)",
                "on_time_hh_pct": stats(fcfs_ot_pct),
                "on_time_headcount": stats(fcfs_hc),
                "assigned_cost": stats(fcfs_asgn),
                "unassigned_penalty": stats(fcfs_unasgn),
                "total_cost": stats(fcfs_tot)
            },
            "priority_greedy": {
                "label": "Priority Greedy Heuristic",
                "on_time_hh_pct": stats(greedy_ot_pct),
                "on_time_headcount": stats(greedy_hc),
                "assigned_cost": stats(greedy_asgn),
                "unassigned_penalty": stats(greedy_unasgn),
                "total_cost": stats(greedy_tot)
            },
            "alns_optimizer": {
                "label": "ALNS Metaheuristic Optimizer",
                "on_time_hh_pct": stats(opt_ot_pct),
                "on_time_headcount": stats(opt_hc),
                "assigned_cost": stats(opt_asgn),
                "unassigned_penalty": stats(opt_unasgn),
                "total_cost": stats(opt_tot)
            }
        },
        "paired_headcount_diff_optimizer_vs_fcfs": {
            "median_people": stats(paired_headcount_diffs_fcfs)["median"],
            "p5_people": stats(paired_headcount_diffs_fcfs)["p5"],
            "p95_people": stats(paired_headcount_diffs_fcfs)["p95"],
            "counts": {
                "better": hc_fcfs_better,
                "tied": hc_fcfs_tied,
                "worse": hc_fcfs_worse
            },
            "plain_statement": (
                f"Paired on-time headcount difference (Optimizer - FCFS): "
                f"Median {stats(paired_headcount_diffs_fcfs)['median']} people [p5: {stats(paired_headcount_diffs_fcfs)['p5']}, p95: {stats(paired_headcount_diffs_fcfs)['p95']}]. "
                f"Optimizer evacuated more people on time: {hc_fcfs_better} seeds. Tied: {hc_fcfs_tied} seeds. FCFS evacuated more: {hc_fcfs_worse} seeds."
            )
        },
        "paired_headcount_diff_optimizer_vs_greedy": {
            "median_people": stats(paired_headcount_diffs_greedy)["median"],
            "p5_people": stats(paired_headcount_diffs_greedy)["p5"],
            "p95_people": stats(paired_headcount_diffs_greedy)["p95"],
            "counts": {
                "better": hc_greedy_better,
                "tied": hc_greedy_tied,
                "worse": hc_greedy_worse
            },
            "plain_statement": (
                f"Paired on-time headcount difference (Optimizer - Greedy): "
                f"Median {stats(paired_headcount_diffs_greedy)['median']} people [p5: {stats(paired_headcount_diffs_greedy)['p5']}, p95: {stats(paired_headcount_diffs_greedy)['p95']}]. "
                f"Optimizer evacuated more people on time: {hc_greedy_better} seeds. Tied: {hc_greedy_tied} seeds. Greedy evacuated more: {hc_greedy_worse} seeds."
            )
        },
        "paired_cost_diff_greedy_minus_optimizer": {
            "median_pts": stats(paired_cost_diffs_greedy)["median"],
            "p5_pts": stats(paired_cost_diffs_greedy)["p5"],
            "p95_pts": stats(paired_cost_diffs_greedy)["p95"],
            "counts": {
                "better": cost_better,
                "tied": cost_tied,
                "worse": cost_worse
            },
            "plain_statement": (
                f"Paired cost difference (Greedy - Optimizer): "
                f"Median {stats(paired_cost_diffs_greedy)['median']} pts [p5: {stats(paired_cost_diffs_greedy)['p5']} pts, p95: {stats(paired_cost_diffs_greedy)['p95']} pts]. "
                f"Optimizer lower cost: {cost_better} seeds. Tied with greedy: {cost_tied} seeds. Greedy lower cost: {cost_worse} seeds."
            )
        }
    }

def run_benchmark(num_seeds: int = 60) -> Dict[str, Any]:
    print(f"[Benchmark] Scenario 1: Extreme Scarcity across {num_seeds} seeds...")
    res_extreme = run_scenario_benchmark(
        generate_extreme_scarcity_night,
        scenario_name="Extreme Scarcity",
        scenario_desc="3 vehicles (12 seats total) vs 24 households (~72 souls), distant base (8-12 km), tight flood arrival deadlines (15-45 min). Dominated by seat shortage.",
        num_seeds=num_seeds,
        use_risk_model=True
    )

    print(f"[Benchmark] Scenario 2: Seat-Limited, Loose Deadlines across {num_seeds} seeds...")
    res_moderate = run_scenario_benchmark(
        generate_moderate_scarcity_night,
        scenario_name="Seat-Limited, Loose Deadlines",
        scenario_desc="6 vehicles (54 seats total) vs 24 households (~72 souls), regional fleet, normal flood arrival deadlines (45-120 min). Seat-limited with loose deadlines.",
        num_seeds=num_seeds,
        use_risk_model=True
    )

    print(f"[Benchmark] Scenario 3: Enough General Seats, Limited Accessible Vehicles, Tight Deadlines across {num_seeds} seeds...")
    res_bound = run_scenario_benchmark(
        generate_bound_deadlines_night,
        scenario_name="Enough General Seats, Limited Accessible Vehicles, Tight Deadlines",
        scenario_desc="8 vehicles (96 seats total) vs 24 households (~72 souls), distant base (8-12 km), tight flood arrival deadlines (15-45 min). Enough general seats, limited accessible vehicles, tight deadlines.",
        num_seeds=num_seeds,
        use_risk_model=True
    )

    combined = {
        "synthetic_benchmark": True,
        "num_seeds": num_seeds,
        "methodological_notes": {
            "deadlines_disclaimer": "All water arrival deadlines and lateness buffers are demo assumptions, not hydrodynamic models.",
            "denominator_rule": "On-time % denominator is ALL households needing a ride (24 households); unassigned households count as NOT evacuated on time.",
            "headcount_metric": "On-time headcount is the total count of individual family members evacuated before water arrival.",
            "seat_shortage_dominance": "The extreme scenario is dominated by seat shortage (only 12 seats for ~72 people).",
            "loose_deadlines": "The moderate scenario has loose deadlines (45-120 min), meaning assigned pickups are virtually all on time.",
            "routing_gain": "The routing gain of the optimizer is approximately 1% of assigned-plan cost in the synthetic data.",
            "single_trip_vehicles": "All scenarios are synthetic with single-trip vehicles (no return loops).",
            "cost_advantage_scope": "The optimizer's cost advantage is strictly over the priority greedy heuristic.",
            "handbuilt_test_provenance": "Hand-built test cases were written by the same agent that changed the optimizer."
        },
        "scenarios": {
            "extreme_scarcity": res_extreme,
            "moderate_scarcity": res_moderate,
            "bound_deadlines": res_bound
        },
        # Top-level backward compatibility aliases
        "extreme_scarcity": res_extreme,
        "moderate_scarcity": res_moderate,
        "bound_deadlines": res_bound,
        "methods": res_extreme["methods"],
        "comparison_summary": {
            "plain_statement": res_extreme["paired_cost_diff_greedy_minus_optimizer"]["plain_statement"],
            "paired_difference_greedy_minus_optimizer": {
                "median": res_extreme["paired_cost_diff_greedy_minus_optimizer"]["median_pts"],
                "p5": res_extreme["paired_cost_diff_greedy_minus_optimizer"]["p5_pts"],
                "p95": res_extreme["paired_cost_diff_greedy_minus_optimizer"]["p95_pts"]
            },
            "counts": res_extreme["paired_cost_diff_greedy_minus_optimizer"]["counts"]
        }
    }

    out_dir = ROOT_DIR / "evals"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "sim_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    return combined

if __name__ == "__main__":
    res = run_benchmark(num_seeds=60)
    print("\nBenchmark completed. Results written to evals/sim_results.json")
    for s_key in ["extreme_scarcity", "moderate_scarcity", "bound_deadlines"]:
        sc = res["scenarios"][s_key]
        print(f"\n{sc['scenario_name'].upper()}:")
        print("  Cost Breakdown: Unassigned penalty share =", sc["unassigned_penalty_share_pct"], "%")
        print(" ", sc["paired_cost_diff_greedy_minus_optimizer"]["plain_statement"])
        print(" ", sc["paired_headcount_diff_optimizer_vs_fcfs"]["plain_statement"])
        print(" ", sc["paired_headcount_diff_optimizer_vs_greedy"]["plain_statement"])
