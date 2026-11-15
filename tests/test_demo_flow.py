import os
import pytest
from config import Config
from app import create_app
from seed import seed_database
from db import get_db

@pytest.fixture(scope="module")
def demo_client():
    Config.USE_MOCK_GNANI = True
    os.environ["USE_MOCK_GNANI"] = "true"
    seed_database()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_six_step_demo_flow_end_to_end(demo_client):
    # Step 1: Dispatcher Login & Dashboard Context
    demo_client.post("/login", data={"role": "dispatcher"})
    res1 = demo_client.get("/dashboard")
    assert res1.status_code == 200
    html1 = res1.data.decode("utf-8")
    assert "Demo Flood, Bantwal" in html1
    assert "GPS LOCK" not in html1

    # Step 2: Intake Simulation
    target_hh_id = "hh-001"
    res2 = demo_client.post("/api/simulate-call", json={
        "household_id": target_hh_id,
        "language": "kannada"
    })
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["success"] is True
    assert data2["pipeline"]["status_engine"]["new_status"] == "needs_help"

    # Step 3: Vehicle Assignment
    res3 = demo_client.post("/api/assign", json={
        "household_id": target_hh_id,
        "vehicle_id": "veh-01",
        "dispatcher_name": "Duty officer"
    })
    assert res3.status_code == 200
    data3 = res3.get_json()
    assert data3["success"] is True
    offer_id = data3["offer_id"]
    req_id = data3["request_id"]

    # Step 4: Driver Login & Driver Offer Acceptance
    demo_client.post("/login", data={"role": "driver"})
    res4 = demo_client.post(f"/api/driver/offers/{offer_id}/accept")
    assert res4.status_code == 200
    data4 = res4.get_json()
    assert data4["success"] is True
    assert data4["status"] == "driver_accepted"

    # Step 5: In-Transit Run & Pickup
    run_page = demo_client.get(f"/run/{req_id}")
    assert run_page.status_code == 200
    assert "run-map" in run_page.data.decode("utf-8")
    assert "Turn-by-turn Navigation to Shelter" not in run_page.data.decode("utf-8")

    res5a = demo_client.post(f"/api/runs/{req_id}/start")
    assert res5a.status_code == 200
    assert res5a.get_json()["status"] == "on_run"

    res5b = demo_client.post(f"/api/runs/{req_id}/picked-up")
    assert res5b.status_code == 200
    assert res5b.get_json()["status"] == "picked_up"

    # Step 6: Shelter Delivery & Evacuation
    res6 = demo_client.post(f"/api/runs/{req_id}/complete")
    assert res6.status_code == 200
    assert res6.get_json()["status"] == "evacuated"

    db = get_db()
    hh_row = db.execute("SELECT status FROM household WHERE id = ?", (target_hh_id,)).fetchone()
    assert hh_row["status"] == "evacuated"
