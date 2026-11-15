import os
import pytest
from app import create_app
from seed import seed_database
from db import get_db

@pytest.fixture
def auth_app():
    seed_database()
    app = create_app()
    app.config["TESTING"] = True
    return app

def test_no_href_hash_remains():
    import glob
    for f in glob.glob('screens/*.html') + glob.glob('templates/*.html'):
        content = open(f, encoding='utf-8', errors='ignore').read()
        assert 'href="#"' not in content, f"Found href='#' in {f}"

def test_unauthenticated_redirects_to_login(auth_app):
    client = auth_app.test_client()
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

def test_dispatcher_login_and_access(auth_app):
    client = auth_app.test_client()
    # Login as dispatcher
    res = client.post("/login", data={"role": "dispatcher"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/dashboard"

    # Can access dispatcher pages
    for page in ["/dashboard", "/call-floor", "/fleet", "/simulate", "/audit", "/privacy", "/under-the-hood", "/evals"]:
        r = client.get(page)
        assert r.status_code == 200, f"Dispatcher failed to access {page}"

    # Blocked from driver and resident pages
    for blocked_page in ["/driver", "/ready"]:
        r = client.get(blocked_page, follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

def test_driver_login_and_access(auth_app):
    client = auth_app.test_client()
    # Login as driver
    res = client.post("/login", data={"role": "driver"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/driver"

    # Can access driver pages
    r = client.get("/driver")
    assert r.status_code == 200

    # Blocked from dispatcher pages
    for blocked_page in ["/dashboard", "/call-floor", "/fleet", "/simulate"]:
        r = client.get(blocked_page, follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

def test_field_worker_login_and_access(auth_app):
    client = auth_app.test_client()
    res = client.post("/login", data={"role": "field_worker"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/field"

    r = client.get("/field")
    assert r.status_code == 200

    r_blocked = client.get("/dashboard", follow_redirects=False)
    assert r_blocked.status_code == 302

def test_resident_login_and_access(auth_app):
    client = auth_app.test_client()
    res = client.post("/login", data={"role": "resident"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/ready"

    for page in ["/ready", "/household-needs", "/confirmation", "/phone"]:
        r = client.get(page)
        assert r.status_code == 200, f"Resident failed to access {page}"

    r_blocked = client.get("/dashboard", follow_redirects=False)
    assert r_blocked.status_code == 302

def test_driver_cannot_accept_another_vehicles_offer(auth_app):
    client = auth_app.test_client()
    # Login as dispatcher first to create an offer for veh-02
    client.post("/login", data={"role": "dispatcher"})
    res_assign = client.post("/api/assign", json={
        "household_id": "hh-001",
        "vehicle_id": "veh-02", # Assigned to veh-02
        "dispatcher_name": "Duty officer"
    })
    offer_id = res_assign.get_json()["offer_id"]

    # Now login as driver (bound to veh-01)
    client.post("/login", data={"role": "driver"})
    # Attempt to accept offer that was for veh-02
    res_accept = client.post(f"/api/driver/offers/{offer_id}/accept")
    assert res_accept.status_code == 403
    assert "different vehicle" in res_accept.get_json()["error"].lower()

def test_login_and_logout_audit_logging(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    client.get("/logout")

    with auth_app.app_context():
        db = get_db()
        login_log = db.execute("SELECT * FROM audit_log WHERE action = 'USER_LOGIN'").fetchone()
        logout_log = db.execute("SELECT * FROM audit_log WHERE action = 'USER_LOGOUT'").fetchone()
        assert login_log is not None
        assert logout_log is not None
        assert login_log["actor_type"] == "dispatcher"
        assert logout_log["actor_type"] == "dispatcher"

def test_language_switcher_session(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    r_hi = client.post("/api/set-lang/hi")
    assert r_hi.status_code == 200
    assert r_hi.get_json()["lang"] == "hi"

    res = client.get("/dashboard")
    assert res.status_code == 200
    # Hindi nav label rendered
    assert "नियंत्रण केंद्र" in res.data.decode("utf-8")
