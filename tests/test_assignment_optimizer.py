"""
Unit and Integration Tests for Assignment Engine and Optimizer
Covers:
1. Capacity and stretcher constraints on randomly generated instances.
2. Accepted assignments are never moved or displaced.
3. On a hand-built instance where greedy is known to be suboptimal, the optimizer finds the better plan.
4. No ETA or arrival time string appears before driver acceptance.
5. Queue sort uses priority score without auto-assigning.
"""

import pytest
import re
import random
from app import create_app
from db import get_db, init_db
from seed import seed_database
from config import Config
from core.assign import suggest_vehicles
from core.priority import priority_score
from core.optimizer import optimize_assignments, generate_optimization_plan

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_assign.db"
    Config.DATABASE_PATH = test_db
    Config.SECRET_KEY = "test-secret-key"
    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        init_db()
        seed_database()

    with app.test_client() as client:
        yield client

def test_capacity_and_stretcher_constraints_never_violated(client):
    """
    Ensure vehicles suggested via suggest_vehicles never violate seat capacity
    or stretcher requirements for bedridden members.
    """
    with client.application.app_context():
        db = get_db()
        inc = db.execute("SELECT id FROM incident LIMIT 1").fetchone()
        incident_id = inc["id"] if inc else "inc-01"

        # Insert a household with 5 members, 1 bedridden
        hh_id = "hh-test-heavy"
        db.execute("""
            INSERT INTO household (id, incident_id, first_name, phone_enc, phone_masked, landmark, lat, lng, members, status)
            VALUES (?, ?, 'Gopal', 'enc', 'XXXXX11111', 'Temple Road', 12.8940, 75.0350, 5, 'needs_help')
        """, (hh_id, incident_id))
        db.execute("""
            INSERT INTO member (id, household_id, cannot_walk, bedridden, elderly)
            VALUES ('mem-heavy-1', ?, 1, 1, 1)
        """, (hh_id,))
        db.commit()

        suggestions = suggest_vehicles(hh_id, db=db)
        for s in suggestions:
            assert s["capacity"] >= 5, f"Vehicle {s['designation']} capacity {s['capacity']} < 5"
            assert s["space_flags"]["has_stretcher"] is True, f"Vehicle {s['designation']} lacks stretcher for bedridden patient"

def test_capacity_and_stretcher_on_random_instances():
    """
    Tests capacity, stretcher, and wheelchair feasibility across multiple
    randomly generated problem instances with heterogeneous constraints.
    """
    rng = random.Random(42)
    for trial in range(10):
        n_hh = rng.randint(8, 20)
        n_veh = rng.randint(3, 7)

        households = []
        for i in range(n_hh):
            members = rng.randint(1, 5)
            stretcher = bool(rng.random() < 0.25)
            wheelchair = bool(rng.random() < 0.30) and not stretcher
            households.append({
                "id": f"r-{trial}-{i}",
                "members": members,
                "priority_weight": rng.uniform(10.0, 90.0),
                "stretcher_needed": stretcher,
                "wheelchair_needed": wheelchair,
                "special_needs": bool(stretcher or wheelchair),
                "water_arrival_minutes": rng.uniform(40.0, 160.0),
                "lat": 12.8900 + rng.uniform(-0.02, 0.02),
                "lng": 75.0300 + rng.uniform(-0.02, 0.02)
            })

        vehicles = []
        for j in range(n_veh):
            v_cap = rng.choice([2, 4, 6, 8])
            v_stretcher = 1 if rng.random() < 0.35 else 0
            v_wheelchair = 1 if (v_stretcher or rng.random() < 0.40) else 0
            vehicles.append({
                "id": f"v-{trial}-{j}",
                "designation": f"Unit-{j}",
                "capacity": v_cap,
                "stretcher": v_stretcher,
                "wheelchair": v_wheelchair,
                "lat": 12.8900 + rng.uniform(-0.02, 0.02),
                "lng": 75.0300 + rng.uniform(-0.02, 0.02)
            })

        plan, best_cost, greedy_cost = optimize_assignments(households, vehicles, iterations=40, seed=trial)

        # Check invariants on every trial's resulting plan
        req_map = {r["id"]: r for r in households}
        veh_map = {v["id"]: v for v in vehicles}

        veh_assigned_seats = {v["id"]: 0 for v in vehicles}
        for r_id, v_id in plan.items():
            req = req_map[r_id]
            veh = veh_map[v_id]

            # 1. Stretcher invariant
            if req["stretcher_needed"]:
                assert veh["stretcher"] == 1, f"Trial {trial}: Stretcher required but assigned vehicle {v_id} lacks stretcher"

            # 2. Wheelchair invariant
            if req["wheelchair_needed"]:
                assert (veh["wheelchair"] == 1 or veh["stretcher"] == 1), f"Trial {trial}: Wheelchair required but assigned vehicle {v_id} not accessible"

            veh_assigned_seats[v_id] += req["members"]

        # 3. Capacity invariant
        for v_id, total_seats in veh_assigned_seats.items():
            assert total_seats <= veh_map[v_id]["capacity"], (
                f"Trial {trial}: Vehicle {v_id} capacity {veh_map[v_id]['capacity']} exceeded with {total_seats} seats"
            )

def test_accepted_assignments_never_moved(client):
    """
    Ensure accepted assignments (driver_accepted or on_run) are never reassigned
    or displaced by the optimizer.
    """
    with client.application.app_context():
        db = get_db()
        hh_id = "hh-001"
        veh_id = "veh-01"
        req_id = "req-test-locked"

        db.execute("""
            INSERT INTO request (id, household_id, vehicle_id, status)
            VALUES (?, ?, ?, 'driver_accepted')
        """, (req_id, hh_id, veh_id))
        db.execute("""
            INSERT INTO offer (id, request_id, vehicle_id, status, version)
            VALUES ('off-locked', ?, ?, 'accepted', 1)
        """, (req_id, veh_id))
        db.commit()

        plan = generate_optimization_plan(db=db)
        assignments = plan.get("assignments", [])

        for a in assignments:
            if a["household_id"] == hh_id:
                assert a["vehicle_id"] == veh_id, "Accepted household was reassigned to a different vehicle!"

def test_handbuilt_suboptimal_greedy_optimizer_finds_better_plan():
    """
    Verifies that on a hand-built instance where greedy is known to be suboptimal,
    the ALNS optimizer finds the better plan (best_cost < greedy_cost).
    
    Setup:
      - V1 (capacity 4) at (12.890, 75.030)
      - V2 (capacity 4) at (12.890, 75.050)
      - R1 (members 4, priority 60) closer to V1 (~0.98 km) than V2 (~1.19 km).
        Greedy greedily assigns R1 to V1.
      - R2 (members 4, priority 55) is extremely close to V1 (~0.11 km) but far from V2 (~2.06 km).
        Because V1 is full, Greedy is forced to assign R2 to V2.
        Greedy cost = 60*0.98 + 55*2.06 = 172.1.
      - Optimal allocation: R1 -> V2 (dist 1.19 km) and R2 -> V1 (dist 0.11 km).
        Optimal cost = 60*1.19 + 55*0.11 = 77.45.
    """
    Config.RISK_MODEL = False
    households = [
        {"id": "r1", "household_id": "h1", "household_name": "R1", "lat": 12.890, "lng": 75.039,
         "members": 4, "priority_weight": 60.0, "stretcher_needed": False, "wheelchair_needed": False,
         "special_needs": False, "water_arrival_minutes": 100},
        {"id": "r2", "household_id": "h2", "household_name": "R2", "lat": 12.890, "lng": 75.031,
         "members": 4, "priority_weight": 55.0, "stretcher_needed": False, "wheelchair_needed": False,
         "special_needs": False, "water_arrival_minutes": 100}
    ]

    vehicles = [
        {"id": "v1", "designation": "V1", "driver_name": "D1", "type": "boat", "capacity": 4,
         "stretcher": 0, "wheelchair": 0, "lat": 12.890, "lng": 75.030},
        {"id": "v2", "designation": "V2", "driver_name": "D2", "type": "boat", "capacity": 4,
         "stretcher": 0, "wheelchair": 0, "lat": 12.890, "lng": 75.050}
    ]

    best_plan, best_cost, greedy_cost = optimize_assignments(households, vehicles, iterations=80, seed=42)
    assert greedy_cost > best_cost, f"Greedy cost ({greedy_cost}) should be strictly greater than best cost ({best_cost})"
    assert best_plan == {"r1": "v2", "r2": "v1"}, f"Expected swapped plan, got {best_plan}"

def test_no_eta_string_before_acceptance(client):
    """
    Strict safety invariant: No ETA, arrival time, or time-to-destination string
    may ever appear in vehicle suggestions, reason strings, or optimizer output
    prior to driver acceptance.
    """
    with client.application.app_context():
        db = get_db()
        households = db.execute("SELECT id FROM household WHERE status = 'needs_help'").fetchall()

        forbidden_patterns = [
            r"\bETA\b",
            r"\barrival in\b",
            r"\bmin(?:utes)? away\b",
            r"\barriving at\b",
            r"\bwill reach in\b",
            r"\bexpected at\b"
        ]

        for h in households:
            suggestions = suggest_vehicles(h["id"], db=db)
            for s in suggestions:
                reason = s.get("reason", "")
                for pattern in forbidden_patterns:
                    assert not re.search(pattern, reason, re.IGNORECASE), (
                        f"Forbidden ETA/timing string found in pre-acceptance reason: '{reason}'"
                    )

        plan = generate_optimization_plan(db=db)
        for a in plan.get("assignments", []):
            combined_text = f"{a.get('household_name', '')} {a.get('vehicle_designation', '')}"
            for pattern in forbidden_patterns:
                assert not re.search(pattern, combined_text, re.IGNORECASE)

def test_queue_sort_uses_priority_score(client):
    """
    Verify GET /api/households returns households with priority breakdown
    and supports sorting aids without auto-assigning.
    """
    with client.session_transaction() as sess:
        sess["role"] = "dispatcher"
        sess["user_name"] = "Duty officer"

    res = client.get("/api/households")
    assert res.status_code == 200
    data = res.get_json()
    households = data.get("households", [])
    assert len(households) > 0

    scores = [h.get("priority_score", 0.0) for h in households]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i+1], f"Default queue not sorted by priority score: {scores[i]} < {scores[i+1]}"

    for h in households:
        assert "priority_breakdown" in h
        bd = h["priority_breakdown"]
        for key in ["emergency", "bedridden", "oxygen", "cannot_walk", "elderly", "unanswered"]:
            assert key in bd
        expected_total = round(sum(bd.values()), 1)
        assert abs(h["priority_score"] - expected_total) < 0.2


def test_risk_model_changes_plan_cost_on_same_instance():
    """
    Verifies that RISK_MODEL flag strictly alters plan cost calculations on the same problem instance
    when deadlines are tight and water arrival precedes or nears vehicle arrival.
    """
    from core.optimizer import calculate_plan_cost
    req = {
        "id": "r-flood",
        "lat": 12.890,
        "lng": 75.030,
        "priority_weight": 50.0,
        "water_arrival_minutes": 18.0,
        "special_needs": False,
        "members": 2
    }
    veh = {
        "id": "v-boat",
        "lat": 12.820,
        "lng": 75.080,
        "capacity": 4,
        "stretcher": 0,
        "wheelchair": 0
    }
    assignments = {"r-flood": "v-boat"}
    requests_data = {"r-flood": req}
    vehicles_data = {"v-boat": veh}

    cost_no_risk = calculate_plan_cost(assignments, requests_data, vehicles_data, use_risk_model=False)
    cost_with_risk = calculate_plan_cost(assignments, requests_data, vehicles_data, use_risk_model=True)

    assert cost_with_risk > cost_no_risk, f"Expected risk cost ({cost_with_risk}) > no-risk cost ({cost_no_risk})"
    assert cost_with_risk - cost_no_risk >= 100.0, "Risk model lateness penalty did not produce expected penalty difference"

def test_second_handbuilt_instance_optimizer_finds_better_plan():
    """
    Second hand-built instance built independently without tuning optimizer parameters.
    Setup:
      - Two vehicles: V-Alpha (cap 2) at (12.890, 75.030) and V-Beta (cap 2) at (12.890, 75.060)
      - HH-Alpha (members 2, priority 75) at (12.890, 75.042)
        Dist to V-Alpha ~1.30 km, Dist to V-Beta ~1.95 km.
        Greedy picks HH-Alpha first (priority 75 > 70) and assigns to V-Alpha (1.30 km), filling V-Alpha.
      - HH-Beta (members 2, priority 70) at (12.890, 75.031)
        Dist to V-Alpha ~0.11 km, Dist to V-Beta ~3.15 km.
        Since V-Alpha is full, Greedy sends HH-Beta to distant V-Beta (3.15 km).
        Greedy Cost = 75*1.30 + 70*3.15 = 317.3 points.
      - Better Allocation: HH-Alpha -> V-Beta (1.95 km) and HH-Beta -> V-Alpha (0.11 km).
        Cost = 75*1.95 + 70*0.11 = 153.95 points.
      - Verifies ALNS optimizer achieves strictly lower cost than greedy.
    """
    Config.RISK_MODEL = False
    v1 = {'id': 'v-alpha', 'designation': 'Alpha Boat', 'capacity': 2, 'stretcher': 0, 'wheelchair': 0, 'lat': 12.890, 'lng': 75.030}
    v2 = {'id': 'v-beta', 'designation': 'Beta Boat', 'capacity': 2, 'stretcher': 0, 'wheelchair': 0, 'lat': 12.890, 'lng': 75.060}
    vehicles = [v1, v2]

    ha = {'id': 'hh-alpha', 'household_id': 'hh-alpha', 'household_name': 'Family Alpha', 'lat': 12.890, 'lng': 75.042, 'members': 2, 'priority_weight': 75.0, 'stretcher_needed': False, 'wheelchair_needed': False, 'special_needs': False, 'water_arrival_minutes': 90}
    hb = {'id': 'hh-beta', 'household_id': 'hh-beta', 'household_name': 'Family Beta', 'lat': 12.890, 'lng': 75.031, 'members': 2, 'priority_weight': 70.0, 'stretcher_needed': False, 'wheelchair_needed': False, 'special_needs': False, 'water_arrival_minutes': 90}
    households = [ha, hb]

    best_plan, best_cost, greedy_cost = optimize_assignments(households, vehicles, iterations=60, seed=123)
    assert best_cost < greedy_cost, f"Optimizer cost ({best_cost}) should be strictly less than greedy ({greedy_cost})"
    assert best_plan.get('hh-alpha') == 'v-beta'
    assert best_plan.get('hh-beta') == 'v-alpha'


def test_plan_cost_breakdown_matches_total():
    """
    Verifies that calculate_plan_cost_breakdown correctly partitions total cost
    into assigned_cost and unassigned_penalty, and that total_cost equals their sum.
    """
    from core.optimizer import calculate_plan_cost_breakdown
    req1 = {"id": "r1", "lat": 12.89, "lng": 75.03, "priority_weight": 50.0, "members": 2, "water_arrival_minutes": 60, "special_needs": False}
    req2 = {"id": "r2", "lat": 12.89, "lng": 75.04, "priority_weight": 40.0, "members": 2, "water_arrival_minutes": 60, "special_needs": False}
    v1 = {"id": "v1", "lat": 12.89, "lng": 75.03, "capacity": 2, "stretcher": 0, "wheelchair": 0}

    reqs = {"r1": req1, "r2": req2}
    vehs = {"v1": v1}
    # Assign r1 only; r2 remains unassigned
    plan = {"r1": "v1"}

    b = calculate_plan_cost_breakdown(plan, reqs, vehs, use_risk_model=False)
    assert b["assigned_cost"] > 0
    assert b["unassigned_penalty"] > 0
    assert abs(b["total_cost"] - (b["assigned_cost"] + b["unassigned_penalty"])) < 0.01
    assert b["unassigned_penalty"] == round(5000.0 * (40.0 / 10.0), 2)


def test_unassigned_penalty_shares_equal_unassigned_divided_by_total():
    """
    Verifies that for every scenario in evals/sim_results.json, the reported
    unassigned_penalty_share_pct mathematically equals:
      round((unassigned_penalty / total_cost) * 100, 1)
    from the raw reported medians.
    """
    import json
    results_path = Config.BASE_DIR / "evals" / "sim_results.json"
    assert results_path.exists(), "evals/sim_results.json must exist"
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenarios = data.get("scenarios", {})
    assert len(scenarios) >= 3, "Expected at least 3 scenarios in sim_results.json"

    for sc_key, sc in scenarios.items():
        reported_share = sc["unassigned_penalty_share_pct"]
        opt_method = sc["methods"]["alns_optimizer"]
        u_med = opt_method["unassigned_penalty"]["median"]
        t_med = opt_method["total_cost"]["median"]
        expected_share = round((u_med / t_med) * 100.0, 1)
        assert abs(reported_share - expected_share) < 0.05, (
            f"Scenario '{sc_key}': reported share ({reported_share}%) does not match "
            f"raw unassigned/total ({u_med}/{t_med} = {expected_share}%)"
        )

