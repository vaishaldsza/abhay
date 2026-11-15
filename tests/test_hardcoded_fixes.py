import os
import json
import pytest
from app import create_app
from db import get_db

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["DEMO_MODE"] = False
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_dashboard_header_incident_name_and_no_dm(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Incident name from DB
    assert "Demo Flood, Bantwal" in html
    # District Magistrate removed
    assert "District Magistrate" not in html
    # Duty officer kept
    assert "Duty officer" in html

def test_simulate_latencies_initial_dash_and_households(client):
    res = client.get("/simulate")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="household-select"' in html
    assert 'id="stt-latency-val">--</span>' in html
    assert 'id="llm-latency-val">--</span>' in html
    assert 'id="tts-latency-val">--</span>' in html
    assert 'id="pipeline-total-latency">--</span>' in html

def test_call_detail_family_roster_and_audio_conditional(client):
    # hh-001 has real audio file
    res1 = client.get("/call/hh-001")
    assert res1.status_code == 200
    html1 = res1.data.decode("utf-8")
    assert "Sudhakar" not in html1
    assert "Meenakshi" not in html1
    assert "Parvathi" in html1
    assert "Real Call Audio Player with Waveform" in html1

    # hh-002 has NO audio file -> audio player must be hidden
    res2 = client.get("/call/hh-002")
    assert res2.status_code == 200
    html2 = res2.data.decode("utf-8")
    assert "Sudhakar" not in html2
    assert "Meenakshi" not in html2
    assert "Real Call Audio Player with Waveform" not in html2

def test_call_detail_assignment_modal_attributes(client):
    res = client.get("/call/hh-001")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="assignVehicleModal"' in html
    assert "km" in html
    assert "Capacity:" in html
    assert "Stretcher:" in html
    assert "Wheelchair:" in html
    assert "Zero ETAs until driver accepts" in html

def test_run_gps_hud_labeled_demo(client):
    res = client.get("/run/run-01")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "GPS FIXED: 12.8714°N, 75.0321°E (Demo)" in html

def test_driver_offer_countdown_dynamic(client):
    res = client.get("/driver")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="countdown-timer"' in html
    assert "updateCountdownFromOffer" in html
