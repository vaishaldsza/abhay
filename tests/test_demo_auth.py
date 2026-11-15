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

def test_credential_login_with_seeded_user(auth_app):
    client = auth_app.test_client()
    res = client.post("/login", data={
        "action": "login",
        "username": "dispatcher",
        "password": "admin123"
    }, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/dashboard"

    # Access dispatcher page
    r = client.get("/dashboard")
    assert r.status_code == 200

def test_credential_login_invalid_password(auth_app):
    client = auth_app.test_client()
    res = client.post("/login", data={
        "action": "login",
        "username": "dispatcher",
        "password": "wrongpassword"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert "Invalid username or password" in res.data.decode("utf-8")

def test_user_signup_registration(auth_app):
    client = auth_app.test_client()
    # Register new field worker
    res = client.post("/register", data={
        "action": "register",
        "full_name": "Ravi Ground Officer",
        "username": "ravi_field",
        "email": "ravi@ddma.gov.in",
        "password": "securepass123",
        "role": "field_worker",
        "phone": "9876543299"
    }, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/field"

    # Check database and audit log
    with auth_app.app_context():
        db = get_db()
        u = db.execute("SELECT * FROM user WHERE username = 'ravi_field'").fetchone()
        assert u is not None
        assert u["full_name"] == "Ravi Ground Officer"
        assert u["role"] == "field_worker"

        reg_log = db.execute("SELECT * FROM audit_log WHERE action = 'USER_REGISTER'").fetchone()
        assert reg_log is not None

def test_signup_duplicate_username_rejected(auth_app):
    client = auth_app.test_client()
    res = client.post("/register", data={
        "action": "register",
        "full_name": "Another Dispatcher",
        "username": "dispatcher", # already exists in seed
        "password": "newpassword123",
        "role": "dispatcher"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert "already registered" in res.data.decode("utf-8").lower()

def test_language_dropdown_and_theme_toggle_rendered(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Language dropdown elements
    assert "lang-dropdown-wrapper" in html
    assert "lang-dropdown-menu" in html
    assert "English (EN)" in html
    assert "हिन्दी (Hindi)" in html
    assert "ಕನ್ನಡ (Kannada)" in html
    # Theme toggle elements
    assert "theme-toggle-btn" in html
    assert "toggleTheme()" in html
    assert "abhay-theme-styles" in html

def test_no_demo_warning_banner_text(auth_app):
    client = auth_app.test_client()
    # Check login screen
    res_login = client.get("/login")
    assert "sample accounts, no real data" not in res_login.data.decode("utf-8").lower()
    
    # Check dashboard
    client.post("/login", data={"role": "dispatcher"})
    res_dash = client.get("/dashboard")
    assert "sample accounts, no real data" not in res_dash.data.decode("utf-8").lower()

def test_simulate_page_close_button_and_alignment(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/simulate")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'href="/dashboard"' in html
    assert "Close" in html
    # Not trapped in fixed inset modal with blurred desktop
    assert "backdrop-blur-sm" not in html
    assert "pointer-events-none filter blur" not in html

def test_language_dropdown_z_index_above_map(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Header and dropdown menu must have high z-index (z-[9999] / z-[10000]) above Leaflet 1000
    assert "z-[9999]" in html
    assert "z-[10000]" in html

def test_dashboard_ui_translations_kannada_and_hindi(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    
    # Test Kannada
    client.post("/api/set-lang/kn")
    res_kn = client.get("/dashboard")
    html_kn = res_kn.data.decode("utf-8")
    assert "ಸಹಾಯ ಬೇಕು" in html_kn
    assert "ಸಂಪರ್ಕವಾಗಿಲ್ಲ" in html_kn
    assert "ಸ್ಥಳಾಂತರಿಸಲಾಗಿದೆ" in html_kn
    assert "ಒಟ್ಟು ಸಮೀಕ್ಷೆ ಮಾಡಿದ ಮನೆಗಳು" in html_kn

    # Test Hindi
    client.post("/api/set-lang/hi")
    res_hi = client.get("/dashboard")
    html_hi = res_hi.data.decode("utf-8")
    assert "मदद चाहिए" in html_hi
    assert "संपर्क नहीं हुआ" in html_hi
    assert "कुल सर्वेक्षण किए गए घर" in html_hi


def test_privacy_purge_modal_hidden_by_default(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/privacy")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="purge-dialog"' in html
    # Must be hidden by default
    assert 'id="purge-dialog" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-primary/70 backdrop-blur-sm transition-opacity duration-200 hidden"' in html or 'id="purge-dialog"' in html and 'hidden' in html

def test_under_the_hood_and_evals_alignment(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    
    # Under the Hood
    res_uth = client.get("/under-the-hood")
    assert res_uth.status_code == 200
    html_uth = res_uth.data.decode("utf-8")
    # Redundant Stitch sidebar removed
    assert '<aside class="fixed top-14 left-0 bottom-0 w-64' not in html_uth
    assert "max-w-7xl mx-auto" in html_uth
    
    # Evals
    res_evals = client.get("/evals")
    assert res_evals.status_code == 200
    html_evals = res_evals.data.decode("utf-8")
    assert '<aside class="fixed top-14 left-0 bottom-0 w-64' not in html_evals
    assert "max-w-7xl mx-auto" in html_evals

def test_driver_and_resident_screens_layout_and_navigation(auth_app):
    client = auth_app.test_client()
    
    # Driver page
    client.post("/login", data={"role": "driver"})
    res_driver = client.get("/driver")
    assert res_driver.status_code == 200
    html_driver = res_driver.data.decode("utf-8")
    assert 'href="/run/req-001"' in html_driver
    assert 'openDriverManifestModal()' in html_driver
    assert 'openDriverCommsModal()' in html_driver
    assert 'max-w-2xl' in html_driver
    
    # Resident page
    client.post("/login", data={"role": "resident"})
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    html_ready = res_ready.data.decode("utf-8")
    assert 'id="ready-form"' in html_ready
    assert 'href="/household-needs"' in html_ready
    assert 'href="/confirmation"' in html_ready
    assert 'max-w-2xl' in html_ready


def test_field_worker_nav_and_logout_present(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "field_worker"})
    res = client.get("/field")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'lang-dropdown-wrapper' in html
    assert 'href="/logout"' in html
    assert 'ASHA Worker' in html

def test_driver_manifest_and_comms_modals(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "driver"})
    res = client.get("/driver")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="driver-manifest-modal"' in html
    assert 'id="driver-comms-modal"' in html
    assert 'window.openDriverManifestModal = function' in html
    assert 'window.openDriverCommsModal = function' in html

def test_resident_page_language_switching(auth_app):
    client = auth_app.test_client()
    client.post("/login", data={"role": "resident"})
    
    # English
    client.post("/api/set-lang/en")
    res_en = client.get("/ready")
    assert res_en.status_code == 200
    html_en = res_en.data.decode("utf-8")
    assert "Disaster Evacuation Preparedness Form" in html_en
    assert "Step 1 of 3: Basic Details" in html_en
    assert "Head of Household First Name" in html_en
    
    # Hindi
    client.post("/api/set-lang/hi")
    res_hi = client.get("/ready")
    assert res_hi.status_code == 200
    html_hi = res_hi.data.decode("utf-8")
    assert "आपदा आपातकालीन निकासी तैयारी प्रपत्र" in html_hi
    assert "चरण 1 / 3: बुनियादी विवरण" in html_hi
    assert "परिवार के मुखिया का पहला नाम" in html_hi

    # Kannada
    client.post("/api/set-lang/kn")
    res_kn = client.get("/ready")
    assert res_kn.status_code == 200
    html_kn = res_kn.data.decode("utf-8")
    assert "ತುರ್ತು ಸನ್ನದ್ಧತಾ ನಮೂನೆ" in html_kn
    assert "ಹಂತ 1 / 3: ಪ್ರಾಥಮಿಕ ವಿವರಗಳು" in html_kn


def test_dark_mode_stylesheet_and_toggle_coverage(auth_app):
    """Verify that nav.html defines comprehensive dark and light mode stylesheet rules."""
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    
    pages = [
        "/evals",
        "/under-the-hood",
        "/privacy",
        "/audit",
        "/simulate",
        "/call-floor",
        "/dashboard",
    ]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Page {page} failed to load"
        html = res.data.decode("utf-8")
        assert 'id="abhay-theme-styles"' in html
        assert "html.dark" in html
        assert "html.light" in html
        assert "toggleTheme()" in html
        assert "theme-toggle-btn" in html

    # Also check Driver and Resident
    client.post("/login", data={"role": "driver"})
    res_driver = client.get("/driver")
    assert res_driver.status_code == 200
    html_driver = res_driver.data.decode("utf-8")
    assert 'id="abhay-theme-styles"' in html_driver
    assert "html.dark" in html_driver
    assert "html.light" in html_driver

    client.post("/login", data={"role": "resident"})
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    html_ready = res_ready.data.decode("utf-8")
    assert 'id="abhay-theme-styles"' in html_ready
    assert "html.dark" in html_ready
    assert "html.light" in html_ready

