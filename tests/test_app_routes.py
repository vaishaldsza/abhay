"""
Comprehensive Route & API Integration Tests for Abhay DDMA
Tests all 15 page routes and core API endpoints.
"""

import pytest
import json
from app import create_app
from db import init_db
from seed import seed_database

@pytest.fixture(scope="module")
def client():
    # Fresh database seed
    seed_database()
    app = create_app()
    app.config["TESTING"] = True
    app.config["DEMO_MODE"] = False
    with app.test_client() as client:
        yield client

def test_all_15_page_routes_return_200(client):
    routes = [
        "/",
        "/dashboard",
        "/call-floor",
        "/call/call-001",
        "/simulate",
        "/fleet",
        "/run/req-001",
        "/driver",
        "/driver?view=login",
        "/driver?view=complete",
        "/ready",
        "/confirmation",
        "/household-needs",
        "/phone",
        "/field",
        "/house-card",
        "/house/hh-001",
        "/audit",
        "/privacy",
        "/under-the-hood",
        "/evals"
    ]
    for r in routes:
        response = client.get(r)
        assert response.status_code == 200, f"Route {r} failed with status {response.status_code}"

def test_api_households(client):
    res = client.get("/api/households")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["count"] >= 40
    # Verify phone masking
    for hh in data["households"][:5]:
        assert "+91 XXXXX XXXXX" in hh["phone_masked"]
        assert "phone_enc" not in hh

def test_api_vehicles(client):
    res = client.get("/api/vehicles")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["vehicles"]) >= 6

def test_ready_registration_with_consent(client):
    payload = {
        "consent": True,
        "first_name": "Chandrashekhar",
        "phone": "9876543210",
        "landmark": "Near Bantwal Inspection Bungalow",
        "pin": "574211",
        "language": "kannada",
        "members": 3,
        "needs_evacuation": True,
        "cannot_walk": True,
        "bedridden": False,
        "elderly": True,
        "pregnant": False,
        "needs_medicine_oxygen": True,
        "sleeping_room": "Ground Floor"
    }
    res = client.post("/api/ready", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "needs_help"

def test_ready_registration_requires_consent(client):
    payload = {
        "consent": False,
        "first_name": "Anil",
        "phone": "9876543210"
    }
    res = client.post("/api/ready", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "consent is required" in data["error"].lower()

def test_api_simulate_call(client):
    payload = {
        "language": "kannada",
        "caller_question": ""
    }
    res = client.post("/api/simulate-call", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    pipeline = data["pipeline"]
    assert "stt" in pipeline
    assert "llm" in pipeline
    assert "guard_and_safety" in pipeline
    assert "tts" in pipeline
    # Verify zero false promise guarantee in reply
    final_reply = pipeline["guard_and_safety"]["final_reply_text"]
    assert "help is coming" not in final_reply.lower()

def test_api_dtmf(client):
    # Fetch first household that is not reached
    hh_res = client.get("/api/households")
    households = hh_res.get_json()["households"]
    hh = next((h for h in households if h["status"] == "not_reached"), households[0])
    hh_id = hh["id"]
    
    res = client.post("/api/dtmf", json={"household_id": hh_id, "key": "1"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "needs_help"

def test_api_evals(client):
    res = client.get("/api/evals")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "summary" in data
    # When in mock mode, numbers are labeled "-- (mock mode)"
    metrics = data["summary"]["metrics"]
    assert "mock mode" in str(metrics["forbidden_promises_detected"]) or metrics["forbidden_promises_detected"] == 0

def test_api_audit(client):
    res = client.get("/api/audit")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["logs"]) > 0

def test_api_field_visits(client):
    res = client.get("/api/field-visits")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
