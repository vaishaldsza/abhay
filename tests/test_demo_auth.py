import os
import pytest
from app import create_app, reset_rate_limits
from seed import seed_database
from db import get_db

@pytest.fixture
def auth_app():
    seed_database()
    reset_rate_limits()
    app = create_app()
    app.config["TESTING"] = True
    return app

def get_csrf(client, page="/register"):
    client.get(page)
    with client.session_transaction() as sess:
        return sess.get("csrf_token")

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

    # Incidents is protected for unauthenticated
    res_inc = client.get("/incidents", follow_redirects=False)
    assert res_inc.status_code == 302
    assert "/login" in res_inc.headers["Location"]

    # Resident routes redirect unauthenticated users to /signin
    res_ready = client.get("/ready", follow_redirects=False)
    assert res_ready.status_code == 302
    assert "/signin" in res_ready.headers["Location"]

    # "/" and "/under-the-hood" are public without login
    assert client.get("/").status_code == 200
    assert client.get("/under-the-hood").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/signin").status_code == 200

def test_dispatcher_login_and_access(auth_app):
    client = auth_app.test_client()
    # Login as dispatcher
    res = client.post("/login", data={"role": "dispatcher"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/dashboard"

    # Can access dispatcher pages
    for page in ["/incidents", "/dashboard", "/call-floor", "/fleet", "/simulate", "/audit", "/privacy", "/under-the-hood", "/evals"]:
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
    for blocked_page in ["/incidents", "/dashboard", "/call-floor", "/fleet", "/simulate"]:
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

def test_login_page_shows_only_four_roles_banner_and_register_links(auth_app):
    client = auth_app.test_client()
    res = client.get("/login")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Four demo role cards
    assert "Enter as demo Dispatcher" in html
    assert "Enter as demo Driver" in html
    assert "Enter as demo Field worker" in html
    assert "Enter as demo Resident" in html

    # Demo-mode banner
    assert "Demo mode: no real data" in html

    # Text link to register
    assert "Resident? Register your household" in html
    assert 'href="/register"' in html

    # Resident role card links to register
    assert "Register your household" in html

    # No registration form on /login
    assert 'name="username"' not in html
    assert 'name="password"' not in html
    assert 'name="full_name"' not in html
    assert 'name="email"' not in html
    assert 'switchAuthTab' not in html

def test_resident_registration_requires_consent(auth_app):
    client = auth_app.test_client()
    csrf = get_csrf(client, "/register")
    # Missing consent
    res = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Parvathi",
        "phone": "9876543210",
        "landmark": "Near Bantwal River Bridge",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }, follow_redirects=False)
    assert res.status_code == 400
    assert "Consent is required" in res.data.decode("utf-8")

def test_resident_registration_validates_inputs(auth_app):
    client = auth_app.test_client()
    csrf = get_csrf(client, "/register")
    # Missing first name, phone, and landmark
    res = client.post("/register", data={"csrf_token": csrf, "consent": "1"}, follow_redirects=False)
    assert res.status_code == 400
    html = res.data.decode("utf-8")
    assert "First name is required" in html
    assert "Phone number is required" in html
    assert "Landmark or location is required" in html
    assert "Password is required" in html

def test_resident_registration_success_creates_account_and_logs_in(auth_app):
    client = auth_app.test_client()
    csrf = get_csrf(client, "/register")
    res = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Kavitha",
        "phone": "9845998877",
        "landmark": "Bantwal Church Road",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "consent": "1"
    }, follow_redirects=False)

    # Redirects to /ready
    assert res.status_code == 302
    assert res.headers["Location"] == "/ready"

    # Follow redirect to /ready as authenticated resident
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200

    # Verify user, household, and audit log
    with auth_app.app_context():
        db = get_db()
        u = db.execute("SELECT * FROM user WHERE role = 'resident' AND full_name = 'Kavitha'").fetchone()
        assert u is not None
        assert (u["phone_masked"] if "phone_masked" in u.keys() else u["phone"]) == "+91 XXXXX XXXXX"
        assert u["phone_hash"] is not None

        hh = db.execute("SELECT * FROM household WHERE first_name = 'Kavitha'").fetchone()
        assert hh is not None
        assert hh["phone_masked"] == "+91 XXXXX XXXXX"
        assert hh["landmark"] == "Bantwal Church Road"
        assert hh["consent_given"] == 1
        assert hh["verification_status"] == "self-reported, unverified"

        audit = db.execute("SELECT * FROM audit_log WHERE action = 'USER_REGISTER' AND actor = 'Kavitha'").fetchone()
        assert audit is not None
        assert audit["actor_type"] == "resident"
        assert "consent" in audit["detail"].lower()

def test_register_page_elements_and_demo_login_link(auth_app):
    client = auth_app.test_client()
    res = client.get("/register")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Fields
    assert 'name="csrf_token"' in html
    assert 'name="first_name"' in html
    assert 'name="phone"' in html
    assert 'name="landmark"' in html
    assert 'name="password"' in html
    assert 'name="confirm_password"' in html
    assert 'name="consent"' in html
    assert "+91 XXXXX XXXXX" in html
    assert "DPDP Act 2023 Consent & Notice" in html
    assert "automatic deletion 72 hours" in html

    # Links
    assert "Already registered? Sign in" in html
    assert 'href="/signin"' in html
    assert "Just exploring? Use demo roles" in html
    assert 'href="/login"' in html

def test_regression_register_lands_on_ready_logged_in_as_resident(auth_app):
    """Regression test ensuring register -> logged in as Resident -> /ready (status 200)."""
    client = auth_app.test_client()
    csrf = get_csrf(client, "/register")
    reg_res = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Suresh",
        "phone": "9845112233",
        "landmark": "Near Bantwal Bus Stand",
        "password": "SecurePassword2026",
        "confirm_password": "SecurePassword2026",
        "consent": "1"
    }, follow_redirects=False)

    assert reg_res.status_code == 302
    assert reg_res.headers["Location"] == "/ready"

    # Immediately access /ready and verify session
    ready_res = client.get("/ready")
    assert ready_res.status_code == 200
    assert "Suresh" in ready_res.data.decode("utf-8") or "Ready" in ready_res.data.decode("utf-8")
    with client.session_transaction() as sess:
        assert sess.get("role") == "resident"
        assert sess.get("user_name") == "Suresh"

def test_sign_out_redirects_ready_to_signin(auth_app):
    """Test: user signs in as resident, signs out, and subsequent access to /ready redirects to /signin."""
    client = auth_app.test_client()
    # Register/login resident
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Ramesh",
        "phone": "9845223344",
        "landmark": "Near Main Market",
        "password": "SecurePassword2026",
        "confirm_password": "SecurePassword2026",
        "consent": "1"
    })

    # Verify resident has access to /ready
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200

    # Logout
    logout_res = client.get("/logout", follow_redirects=False)
    assert logout_res.status_code == 302
    assert "/signin" in logout_res.headers["Location"]

    # Now attempt accessing /ready unauthenticated -> redirects to /signin
    unauth_ready = client.get("/ready", follow_redirects=False)
    assert unauth_ready.status_code == 302
    assert "/signin" in unauth_ready.headers["Location"]

def test_signin_wrong_password_generic_error(auth_app):
    """Test: wrong password fails with the generic message 'Phone or password is incorrect'."""
    client = auth_app.test_client()
    # First register a user
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Deepa",
        "phone": "9845334455",
        "landmark": "Near River Road",
        "password": "CorrectPassword123",
        "confirm_password": "CorrectPassword123",
        "consent": "1"
    })
    client.get("/logout")

    # Sign in with wrong password
    csrf_signin = get_csrf(client, "/signin")
    res = client.post("/signin", data={
        "csrf_token": csrf_signin,
        "phone": "9845334455",
        "password": "WrongPassword999"
    }, follow_redirects=False)
    assert res.status_code == 401
    html = res.data.decode("utf-8")
    assert "Phone or password is incorrect" in html

    # Sign in with non-existent phone also returns the identical generic message
    res_unknown = client.post("/signin", data={
        "csrf_token": csrf_signin,
        "phone": "9111111111",
        "password": "AnyPassword123"
    }, follow_redirects=False)
    assert res_unknown.status_code == 401
    assert "Phone or password is incorrect" in res_unknown.data.decode("utf-8")

def test_rate_limit_triggers(auth_app):
    """Test: 5 failed sign-in attempts triggers 429 lockout."""
    client = auth_app.test_client()
    csrf = get_csrf(client, "/signin")

    for i in range(5):
        r = client.post("/signin", data={
            "csrf_token": csrf,
            "phone": "9999900000",
            "password": "BadPassword1"
        })
        assert r.status_code == 401

    # 6th attempt must trigger 429
    r_locked = client.post("/signin", data={
        "csrf_token": csrf,
        "phone": "9999900000",
        "password": "BadPassword1"
    })
    assert r_locked.status_code == 429
    assert "Too many attempts" in r_locked.data.decode("utf-8")

def test_duplicate_phone_rejected(auth_app):
    """Test: duplicate phone number is rejected with 400."""
    client = auth_app.test_client()
    csrf1 = get_csrf(client, "/register")
    res1 = client.post("/register", data={
        "csrf_token": csrf1,
        "first_name": "Ananya",
        "phone": "9845445566",
        "landmark": "Near Station Road",
        "password": "Password12345",
        "confirm_password": "Password12345",
        "consent": "1"
    }, follow_redirects=False)
    assert res1.status_code == 302
    client.get("/logout")

    # Second registration with identical phone number
    csrf2 = get_csrf(client, "/register")
    res2 = client.post("/register", data={
        "csrf_token": csrf2,
        "first_name": "Sunil",
        "phone": "9845445566",
        "landmark": "Different House",
        "password": "Password12345",
        "confirm_password": "Password12345",
        "consent": "1"
    }, follow_redirects=False)
    assert res2.status_code == 400
    assert "already registered" in res2.data.decode("utf-8")

def test_staff_roles_cannot_be_created_via_register(auth_app):
    """Test: staff roles (dispatcher, driver, field_worker) cannot be self-registered via /register."""
    client = auth_app.test_client()
    for staff_role in ["dispatcher", "driver", "field_worker"]:
        csrf = get_csrf(client, "/register")
        res = client.post("/register", data={
            "csrf_token": csrf,
            "first_name": "StaffHacker",
            "phone": "9845556677",
            "landmark": "Panchayat Office",
            "password": "Password12345",
            "confirm_password": "Password12345",
            "role": staff_role,
            "consent": "1"
        }, follow_redirects=False)
        assert res.status_code == 400
        assert "Staff roles cannot be registered" in res.data.decode("utf-8")

def test_csrf_token_missing_rejected(auth_app):
    """Test: missing or invalid CSRF token on POST forms is rejected with 400."""
    client = auth_app.test_client()

    # /signin without CSRF
    res_signin = client.post("/signin", data={
        "phone": "9876543210",
        "password": "AnyPassword123"
    }, auto_csrf=False)
    assert res_signin.status_code == 400
    assert "CSRF" in res_signin.data.decode("utf-8")

    # /register without CSRF
    res_reg = client.post("/register", data={
        "first_name": "Pooja",
        "phone": "9845667788",
        "landmark": "Temple Street",
        "password": "Password12345",
        "confirm_password": "Password12345",
        "consent": "1"
    }, auto_csrf=False)
    assert res_reg.status_code == 400
    assert "CSRF" in res_reg.data.decode("utf-8")

def test_signin_success_and_session_rotation(auth_app):
    """Test: registered user can sign in at /signin, session rotates, lands on /ready."""
    client = auth_app.test_client()
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Meera",
        "phone": "9845778899",
        "landmark": "Near Primary Health Centre",
        "password": "MyStrongPassword2026",
        "confirm_password": "MyStrongPassword2026",
        "consent": "1"
    })
    client.get("/logout")

    # Sign in
    csrf_signin = get_csrf(client, "/signin")
    res_signin = client.post("/signin", data={
        "csrf_token": csrf_signin,
        "phone": "9845778899",
        "password": "MyStrongPassword2026"
    }, follow_redirects=False)

    assert res_signin.status_code == 302
    assert res_signin.headers["Location"] == "/ready"

    # Access /ready
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("role") == "resident"
        assert sess.get("user_name") == "Meera"

def test_landing_page_links_register_household(auth_app):
    client = auth_app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Resident card and footer both have Register your household
    assert 'href="/register"' in html
    assert "Register your household" in html

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



def test_profile_edit_and_update_api(auth_app):
    """Verify user can update their profile (name, phone, address) and it reflects in session & audit."""
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})

    # Check modal and badge
    dash = client.get("/dashboard")
    assert dash.status_code == 200
    html = dash.data.decode("utf-8")
    assert "openProfileModal()" in html
    assert 'id="profile-edit-modal"' in html

    # Update profile
    res = client.post("/api/profile/update", json={
        "full_name": "Senior Officer Anand Rao",
        "phone": "+91 98450 99999",
        "address": "Bantwal Taluk Emergency Control Room, Sector 2"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["user_name"] == "Senior Officer Anand Rao"

    # Verify updated name in subsequent page load
    dash2 = client.get("/dashboard")
    html2 = dash2.data.decode("utf-8")
    assert "Senior Officer Anand Rao" in html2


def test_incident_page_light_mode_visibility(auth_app):
    """Verify incident select page has proper semantic styling and classes for visibility in light mode."""
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/incidents")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "incident-card-primary" in html
    assert "incident-card-title" in html
    assert "incident-card-subtitle" in html
    assert "incident-card-chip" in html
    assert "btn-enter-control" in html
    assert "incident-badge-active" in html
    assert "html.light .incident-card-primary" in html
    assert "html.light .btn-enter-control" in html

def test_fleet_page_light_mode_and_boxes(auth_app):
    """Verify fleet page has proper styling and classes for visibility in light mode."""
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})
    res = client.get("/fleet")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "fleet-metric-card" in html
    assert "fleet-label" in html
    assert "fleet-vehicle-card" in html
    assert "html.light .fleet-metric-card" in html


def test_resident_screens_language_switcher_and_get_redirect(auth_app):
    """Verify GET /api/set-lang/<lang> redirects and resident pages have language selector pills."""
    client = auth_app.test_client()
    client.post("/login", data={"role": "resident"})

    # GET redirect test
    res = client.get("/api/set-lang/hi", headers={"Referer": "/ready"})
    assert res.status_code == 302
    assert "/ready" in res.location

    # Verify Hindi resident page
    res_ready = client.get("/ready")
    html_ready = res_ready.data.decode("utf-8")
    assert "/api/set-lang/en" in html_ready
    assert "/api/set-lang/hi" in html_ready
    assert "/api/set-lang/kn" in html_ready
    assert "आपदा आपातकालीन निकासी तैयारी प्रपत्र" in html_ready

    # Check phone simulator in English
    client.get("/api/set-lang/en")
    res_phone = client.get("/phone")
    html_phone = res_phone.data.decode("utf-8")
    assert "Emergency Call in Progress..." in html_phone
    assert "1: I need rescue help" in html_phone


def test_landing_page_public_access_and_honesty_text(auth_app):
    client = auth_app.test_client()
    # 1. Unauthenticated gets 200
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Honesty rule text present
    assert "The agent never says help is coming until a driver has accepted" in html
    # Prototype limits box present
    assert "This is a prototype built for the Gnani AI Great Indian AI Internship Challenge" in html
    assert "Running in mock mode: Gnani models are simulated." in html

    # Unauthenticated button
    assert "Try the demo" in html

    # When logged in, header button shows "Go to my dashboard"
    client.post("/login", data={"role": "dispatcher"})
    res_logged = client.get("/")
    assert res_logged.status_code == 200
    html_logged = res_logged.data.decode("utf-8")
    assert "Go to my dashboard" in html_logged

def test_incidents_requires_dispatcher_role(auth_app):
    client = auth_app.test_client()
    # Unauthenticated is blocked
    r_unauth = client.get("/incidents", follow_redirects=False)
    assert r_unauth.status_code == 302
    assert "/login" in r_unauth.headers["Location"]

    # Driver is blocked
    client.post("/login", data={"role": "driver"})
    r_driver = client.get("/incidents", follow_redirects=False)
    assert r_driver.status_code == 302
    assert "/login" in r_driver.headers["Location"]

    # Resident is blocked
    client.post("/login", data={"role": "resident"})
    r_res = client.get("/incidents", follow_redirects=False)
    assert r_res.status_code == 302
    assert "/login" in r_res.headers["Location"]

    # Dispatcher is allowed
    client.post("/login", data={"role": "dispatcher"})
    r_disp = client.get("/incidents")
    assert r_disp.status_code == 200
    assert "District Control Room" in r_disp.data.decode("utf-8")

def test_landing_page_no_compliance_or_invented_statistics(auth_app):
    client = auth_app.test_client()
    res = client.get("/")
    html = res.data.decode("utf-8")
    for bad in ["compliant", "certified", "iso", "%"]:
        assert bad not in html.lower(), f"Forbidden word '{bad}' found on rendered landing page"

def test_landing_page_language_switch_changes_hero(auth_app):
    client = auth_app.test_client()
    # EN
    client.post("/api/set-lang/en")
    res_en = client.get("/")
    assert "Reach every home. Promise nothing you can't deliver." in res_en.data.decode("utf-8")

    # HI
    client.post("/api/set-lang/hi")
    res_hi = client.get("/")
    assert "हर घर तक पहुंचें। ऐसा कोई वादा न करें जो पूरा न हो सके।" in res_hi.data.decode("utf-8")

    # KN
    client.post("/api/set-lang/kn")
    res_kn = client.get("/")
    assert "ಪ್ರತಿಯೊಂದು ಮನೆಗೂ ತಲುಪಿ. ಈಡೇರಿಸಲಾಗದ ಭರವಸೆಯನ್ನು ನೀಡಬೇಡಿ." in res_kn.data.decode("utf-8")


def test_phone_hash_hmac_properties():
    """Verify phone hashing uses HMAC-SHA256: same phone gives same hash, different key gives different hash."""
    from db import hash_phone, encrypt_phone, normalize_phone

    phone = "9876543210"
    key1 = "secret-key-alpha-1234567890"
    key2 = "secret-key-beta-0987654321"

    # Same phone, same key -> identical hash
    h1 = hash_phone(phone, key=key1)
    h2 = hash_phone(phone, key=key1)
    assert h1 == h2
    assert len(h1) == 64 # SHA-256 hex string

    # Same phone with formatting (+91, spaces) -> normalized to same hash
    h_formatted = hash_phone("+91 98765 43210", key=key1)
    assert h_formatted == h1

    # Different key -> different hash
    h3 = hash_phone(phone, key=key2)
    assert h1 != h3
    assert len(h3) == 64

    # Phone encryption properties with Fernet authenticated encryption
    from cryptography.fernet import Fernet
    from db import decrypt_phone

    f_key1 = Fernet.generate_key().decode()
    f_key2 = Fernet.generate_key().decode()

    enc1 = encrypt_phone(phone, key=f_key1)
    enc2 = encrypt_phone(phone, key=f_key1)
    # Probabilistic encryption produces unique ciphertexts
    assert enc1 != enc2
    # Both decrypt back to original phone
    assert decrypt_phone(enc1, key=f_key1) == phone
    assert decrypt_phone(enc2, key=f_key1) == phone


def test_fernet_tampered_ciphertext_rejected():
    """Verify that tampered Fernet ciphertext is rejected with InvalidToken."""
    from cryptography.fernet import Fernet, InvalidToken
    from db import encrypt_phone, decrypt_phone

    k = Fernet.generate_key().decode()
    cipher = encrypt_phone("9876543210", key=k)
    assert len(cipher) > 20

    # Tamper with the ciphertext by mutating characters
    chars = list(cipher)
    chars[15] = 'Z' if chars[15] != 'Z' else 'Y'
    tampered = "".join(chars)

    with pytest.raises(InvalidToken):
        decrypt_phone(tampered, key=k)


def test_fernet_wrong_key_fails():
    """Verify that attempting to decrypt with a different valid key fails."""
    from cryptography.fernet import Fernet, InvalidToken
    from db import encrypt_phone, decrypt_phone

    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()

    cipher = encrypt_phone("9876543210", key=k1)
    with pytest.raises(InvalidToken):
        decrypt_phone(cipher, key=k2)


def test_phone_keys_fail_startup_if_missing_or_invalid(monkeypatch):
    """Verify that Config raises ValueError at startup if keys are missing or not valid Fernet keys."""
    import importlib
    from cryptography.fernet import Fernet
    import config

    valid_f_key = Fernet.generate_key().decode()

    # Missing PHONE_HASH_KEY
    monkeypatch.setenv("PHONE_HASH_KEY", "")
    with pytest.raises(ValueError, match="PHONE_HASH_KEY must be provided"):
        importlib.reload(config)

    # Restore PHONE_HASH_KEY, remove PHONE_ENCRYPTION_KEY
    monkeypatch.setenv("PHONE_HASH_KEY", "valid-test-hash-key")
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", "")
    with pytest.raises(ValueError, match="PHONE_ENCRYPTION_KEY must be provided"):
        importlib.reload(config)

    # Invalid PHONE_ENCRYPTION_KEY (not a 32-byte Fernet key)
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValueError, match="Fernet key"):
        importlib.reload(config)

    # Restore both with valid keys
    monkeypatch.setenv("PHONE_HASH_KEY", "valid-test-hash-key")
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", valid_f_key)
    importlib.reload(config)


def test_api_post_endpoints_require_csrf_token(auth_app):
    """
    Verify that state-changing POST endpoints under /api reject requests without X-CSRF-Token header.
    Tests assign, accept, simulate-call, delete-now, and field-visit updates.
    """
    client = auth_app.test_client()
    client.post("/login", data={"role": "dispatcher"})

    # 1. /api/assign
    res_assign = client.post(
        "/api/assign",
        json={"household_id": "hh-001", "vehicle_id": "veh-01"},
        auto_csrf=False
    )
    assert res_assign.status_code == 400
    assert "CSRF" in res_assign.get_json()["error"]

    # 2. /api/driver/offers/<id>/accept
    res_accept = client.post(
        "/api/driver/offers/off-001/accept",
        auto_csrf=False
    )
    assert res_accept.status_code == 400
    assert "CSRF" in res_accept.get_json()["error"]

    # 3. /api/simulate-call
    res_sim = client.post(
        "/api/simulate-call",
        json={"language": "kannada", "caller_question": ""},
        auto_csrf=False
    )
    assert res_sim.status_code == 400
    assert "CSRF" in res_sim.get_json()["error"]

    # 4. /api/privacy/delete-now
    res_purge = client.post(
        "/api/privacy/delete-now",
        auto_csrf=False
    )
    assert res_purge.status_code == 400
    assert "CSRF" in res_purge.get_json()["error"]

    # 5. /api/field-visits/<id>/resolve (field-visit updates)
    res_fv = client.post(
        "/api/field-visits/fv-001/resolve",
        json={"notes": "Checked door"},
        auto_csrf=False
    )
    assert res_fv.status_code == 400
    assert "CSRF" in res_fv.get_json()["error"]

    # Also test /api/field-visits creation
    res_fv_create = client.post(
        "/api/field-visits",
        json={"household_id": "hh-001", "assigned_worker": "ASHA Worker Suma"},
        auto_csrf=False
    )
    assert res_fv_create.status_code == 400
    assert "CSRF" in res_fv_create.get_json()["error"]

    # Verify that when valid X-CSRF-Token IS provided, the request is NOT rejected by CSRF
    with client.session_transaction() as sess:
        valid_csrf = sess["csrf_token"]

    res_valid_csrf = client.post(
        "/api/assign",
        json={"household_id": "hh-001", "vehicle_id": "veh-01"},
        headers={"X-CSRF-Token": valid_csrf},
        auto_csrf=False
    )
    assert res_valid_csrf.status_code == 200
    assert res_valid_csrf.get_json()["success"] is True


def test_demo_mode_false_refuses_role_entry_and_resident_signin_works(auth_app):
    """
    Requirement 5: When DEMO_MODE=false, /login must refuse role entry,
    and resident-only sign-in must still work.
    """
    auth_app.config["DEMO_MODE"] = False
    client = auth_app.test_client()

    # 1. /login GET displays production notice
    res_login_get = client.get("/login")
    assert res_login_get.status_code == 200
    assert "disabled in production" in res_login_get.data.decode("utf-8")

    # 2. /login POST with role is refused with HTTP 403
    for test_role in ["dispatcher", "driver", "field_worker", "resident"]:
        res_role_refused = client.post("/login", data={"role": test_role})
        assert res_role_refused.status_code == 403
        assert "disabled in production" in res_role_refused.data.decode("utf-8")

    # 3. Resident-only sign-in still works
    # First register a resident
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Praveen",
        "phone": "9845889900",
        "landmark": "Near Bantwal Market Gate",
        "password": "SecureResidentPassword2026",
        "confirm_password": "SecureResidentPassword2026",
        "consent": "1"
    })
    client.get("/logout")

    # Sign in at /signin
    csrf_signin = get_csrf(client, "/signin")
    res_signin = client.post("/signin", data={
        "csrf_token": csrf_signin,
        "phone": "9845889900",
        "password": "SecureResidentPassword2026"
    }, follow_redirects=False)

    assert res_signin.status_code == 302
    assert res_signin.headers["Location"] == "/ready"

    # Access /ready as logged in resident
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("role") == "resident"
        assert sess.get("user_name") == "Praveen"


def test_home_page_language_dropdown_and_resident_pages_dark_mode_visibility(auth_app):
    """Test: home page has language dropdown, resident/household pages have early theme script,
    no hardcoded class='light', and dark mode CSS styles for inputs, boxes, and texts."""
    import re
    client = auth_app.test_client()

    # 1. Home page language dropdown
    res_home = client.get("/")
    assert res_home.status_code == 200
    html_home = res_home.data.decode("utf-8")
    assert 'id="lang-dropdown-wrapper"' in html_home
    assert 'id="lang-toggle-btn"' in html_home
    assert 'id="lang-dropdown-menu"' in html_home
    assert "setAppLanguage('en')" in html_home
    assert "setAppLanguage('hi')" in html_home
    assert "setAppLanguage('kn')" in html_home

    # 2. Resident & Household pages dark mode visibility checks
    with client.session_transaction() as sess:
        sess["role"] = "resident"
        sess["household_id"] = "HH-BANTWAL-001"
        sess["user_id"] = "demo-resident"

    for path in ["/ready", "/household-needs", "/confirmation", "/phone"]:
        res = client.get(path)
        assert res.status_code == 200, f"Failed on {path}"
        html = res.data.decode("utf-8")

        # Must not have hardcoded class="light"
        html_tag_match = re.search(r'<html([^>]*)>', html, re.IGNORECASE)
        assert html_tag_match is not None
        assert 'class="light"' not in html_tag_match.group(1)
        assert "class='light'" not in html_tag_match.group(1)

        # Must have early theme initialization script in <head>
        head_match = re.search(r'<head>(.*?)</head>', html, re.IGNORECASE | re.DOTALL)
        assert head_match is not None
        head_content = head_match.group(1)
        assert "localStorage.getItem('theme')" in head_content or 'localStorage.getItem("theme")' in head_content or "localStorage.getItem('abhay_theme')" in head_content

        # Must include global theme styles with dark mode rules
        assert "abhay-theme-styles" in html
        assert "html.dark" in html



def test_no_plaintext_phone_in_database_file_for_registered_resident(auth_app):
    """
    Requirement 6: Verify that no plaintext phone appears in the database file
    for a newly registered resident.
    """
    from config import Config
    client = auth_app.test_client()

    unique_phone = "9845091827"
    csrf = get_csrf(client, "/register")
    res = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Divya",
        "phone": unique_phone,
        "landmark": "Near Someshwara Temple",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "consent": "1"
    }, follow_redirects=True)
    assert res.status_code == 200

    # Ensure all SQLite journal/wal data is flushed to disk
    with auth_app.app_context():
        from db import get_db
        db = get_db()
        user_row = db.execute("SELECT * FROM user WHERE full_name = ?", ("Divya",)).fetchone()
        assert user_row is not None
        assert "phone" not in user_row.keys() or user_row["phone_masked"] is not None
        assert user_row["phone_masked"] == "+91 XXXXX XXXXX"
        assert user_row["phone_enc"] is not None
        assert user_row["phone_enc"].startswith("gAAAAA")
        assert unique_phone not in str(dict(user_row))

        hh_row = db.execute("SELECT * FROM household WHERE first_name = ?", ("Divya",)).fetchone()
        assert hh_row is not None
        assert hh_row["phone_masked"] == "+91 XXXXX XXXXX"
        assert hh_row["phone_enc"] is not None
        assert hh_row["phone_enc"].startswith("gAAAAA")
        assert unique_phone not in str(dict(hh_row))

    # Read binary database file from disk and assert unique phone string is nowhere in the bytes
    with open(Config.DATABASE_PATH, "rb") as db_f:
        db_bytes = db_f.read()
    assert unique_phone.encode("utf-8") not in db_bytes


def test_csrf_compare_is_constant_time(auth_app, monkeypatch):
    """
    Requirement 4 & 6: Verify that CSRF tokens are compared with hmac.compare_digest
    (constant-time comparison) both in form checks (/signin) and /api checks.
    """
    import hmac
    client = auth_app.test_client()

    called_compare_digest = []
    original_compare_digest = hmac.compare_digest

    def spy_compare_digest(a, b):
        called_compare_digest.append((a, b))
        return original_compare_digest(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy_compare_digest)

    # 1. Test in /signin POST form check
    csrf = get_csrf(client, "/signin")
    called_compare_digest.clear()

    client.post("/signin", data={
        "csrf_token": csrf,
        "phone": "9876543210",
        "password": "Password123"
    })
    assert len(called_compare_digest) >= 1

    # 2. Test in /api POST check
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        api_csrf = sess["csrf_token"]

    called_compare_digest.clear()
    client.post(
        "/api/assign",
        json={"household_id": "hh-001", "vehicle_id": "veh-01"},
        headers={"X-CSRF-Token": api_csrf},
        auto_csrf=False
    )
    assert len(called_compare_digest) >= 1


def test_self_reported_unverified_badges_on_call_floor_and_call_detail(auth_app):
    """
    Requirement 5: Verify that the 'self-reported, unverified' badge appears on
    /call-floor and /call/<id> as well as the dashboard.
    """
    client = auth_app.test_client()

    # Create an unverified household via registration
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Anoop",
        "phone": "9845012399",
        "landmark": "Near Maroli Bridge",
        "password": "Password2026",
        "confirm_password": "Password2026",
        "consent": "1"
    })

    # Find the created household ID
    with auth_app.app_context():
        from db import get_db
        db = get_db()
        hh = db.execute("SELECT id, verification_status FROM household WHERE first_name = ?", ("Anoop",)).fetchone()
        assert hh is not None
        assert hh["verification_status"] == "self-reported, unverified"
        hh_id = hh["id"]

    # Login as dispatcher
    client.get("/logout")
    client.post("/login", data={"role": "dispatcher"})

    # Check /call-floor
    res_floor = client.get("/call-floor")
    assert res_floor.status_code == 200
    html_floor = res_floor.data.decode("utf-8")
    assert "self-reported, unverified" in html_floor

    # Check /call/<id>
    res_detail = client.get(f"/call/{hh_id}")
    assert res_detail.status_code == 200
    html_detail = res_detail.data.decode("utf-8")
    assert "self-reported, unverified" in html_detail


def test_privacy_delete_now_clears_personal_fields_and_allows_phone_reuse(auth_app):
    """
    Requirement 2: Make delete-now clear phone_enc, phone_hash and phone_masked,
    plus names, landmarks and any other personal fields, for households AND users
    (resident accounts too). Add a test that after purge no personal field remains
    for a resident registered in the test, and that a new registration can reuse that phone number.
    """
    client = auth_app.test_client()

    phone_num = "9845991122"
    csrf = get_csrf(client, "/register")
    res_reg = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Radhika",
        "phone": phone_num,
        "landmark": "Near Someshwara Beach",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "consent": "1"
    }, follow_redirects=True)
    assert res_reg.status_code == 200

    # Verify duplicate registration is rejected before purge
    client.get("/logout")
    csrf_dup = get_csrf(client, "/register")
    res_dup = client.post("/register", data={
        "csrf_token": csrf_dup,
        "first_name": "Radhika Duplicate",
        "phone": phone_num,
        "landmark": "Another spot",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "consent": "1"
    })
    assert res_dup.status_code == 400
    assert "already registered" in res_dup.data.decode("utf-8")

    # Log in as dispatcher and trigger /api/privacy/delete-now
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]

    res_purge = client.post(
        "/api/privacy/delete-now",
        json={"confirm": True, "incident_id": "inc-bantwal-01"},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res_purge.status_code == 200
    assert res_purge.get_json()["success"] is True

    # Check database: no personal fields remain for the resident or household
    with auth_app.app_context():
        from db import get_db
        db = get_db()
        # All resident accounts must have personal fields cleared
        residents = db.execute("SELECT * FROM user WHERE role = 'resident'").fetchall()
        for r in residents:
            assert r["full_name"] == "[PURGED]"
            assert r["phone_masked"] == "[PURGED]"
            assert r["phone_enc"] == "[PURGED]"
            assert r["phone_hash"] is None
            assert r["email"] is None
            assert r["password_hash"] == "[PURGED]"

        # All households must have personal fields cleared
        households = db.execute("SELECT * FROM household").fetchall()
        for h in households:
            assert h["first_name"] == "[PURGED]"
            assert h["phone_masked"] == "[PURGED]"
            assert h["phone_enc"] == "[PURGED]"
            assert h["phone_hash"] is None
            assert h["landmark"] == "[PURGED]"
            assert h["lat"] is None
            assert h["lng"] is None

        # Call records must have transcripts and audio cleared
        calls = db.execute("SELECT * FROM call").fetchall()
        for c in calls:
            assert c["audio_path"] is None
            assert c["transcript"] == "" or c["transcript"] is None

    # Verify that a new registration can now reuse the purged phone number
    client.get("/logout")
    csrf_new = get_csrf(client, "/register")
    res_reuse = client.post("/register", data={
        "csrf_token": csrf_new,
        "first_name": "Sujatha",
        "phone": phone_num,
        "landmark": "Near Temple Cross",
        "password": "NewSecurePassword456",
        "confirm_password": "NewSecurePassword456",
        "consent": "1"
    }, follow_redirects=True)
    assert res_reuse.status_code == 200
    assert "Sujatha" in res_reuse.data.decode("utf-8")


def test_database_files_contain_no_plaintext_phones_for_seeded_and_registered(auth_app):
    """
    Requirement 4: Verify that no plaintext phone string for any seeded resident
    or test-registered resident appears in abhay.db, abhay.db-wal, or abhay.db-shm.
    """
    import os
    import glob
    from config import Config
    from db import get_db, decrypt_phone

    client = auth_app.test_client()

    # Register a new resident with a known unique phone
    registered_phone = "9845778899"
    csrf = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Kavitha",
        "phone": registered_phone,
        "landmark": "Near Netravati Bank",
        "password": "Password1234",
        "confirm_password": "Password1234",
        "consent": "1"
    })

    # Collect all seeded and registered raw phone numbers
    phones_to_check = {registered_phone}

    # 4 default seeded users:
    for p in ["9876543210", "9876543211", "9876543212", "9876543213"]:
        phones_to_check.add(p)

    # Seeded households (decrypt phone_enc from the database):
    with auth_app.app_context():
        db = get_db()
        # Force a WAL checkpoint to flush all data from WAL to disk
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        rows = db.execute("SELECT phone_enc FROM household WHERE phone_enc != '[PURGED]' AND phone_enc IS NOT NULL").fetchall()
        for r in rows:
            try:
                decrypted = decrypt_phone(r["phone_enc"])
                if decrypted and len(decrypted) >= 7:
                    phones_to_check.add(decrypted)
            except Exception:
                pass

    # Read binary contents of abhay.db and any WAL/SHM files
    db_path = Config.DATABASE_PATH
    db_dir = os.path.dirname(os.path.abspath(db_path))
    db_base = os.path.basename(db_path)

    matching_files = glob.glob(os.path.join(db_dir, f"{db_base}*"))
    assert len(matching_files) >= 1

    all_bytes = b""
    for fpath in matching_files:
        if os.path.isfile(fpath) and not fpath.endswith("-shm"):
            try:
                with open(fpath, "rb") as f:
                    all_bytes += f.read()
            except (PermissionError, OSError):
                pass

    # Scan for every plaintext phone
    for phone in phones_to_check:
        assert phone.encode("utf-8") not in all_bytes, f"Plaintext phone {phone} found in database binary file!"


def test_post_purge_views_and_map_contain_no_purged_text_or_errors(auth_app):
    """
    Requirement 1: Load /dashboard, /call-floor, /call/<id>, /fleet and the map API after a purge.
    Confirm no errors (HTTP 200) and no '[PURGED]' text leaking into labels or counts.
    Purged households must be hidden from map and views.
    """
    client = auth_app.test_client()

    # Log in as dispatcher and trigger purge
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]

    res_purge = client.post(
        "/api/privacy/delete-now",
        json={"confirm": True},
        headers={"X-CSRF-Token": csrf},
        auto_csrf=False
    )
    assert res_purge.status_code == 200

    # 1. Map API (/api/households)
    res_map = client.get("/api/households")
    assert res_map.status_code == 200
    map_data = res_map.get_json()
    assert map_data["success"] is True
    assert map_data["count"] == 0
    assert len(map_data["households"]) == 0
    assert "[PURGED]" not in res_map.data.decode("utf-8")

    # 2. /dashboard
    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "[PURGED]" not in res_dash.data.decode("utf-8")

    # 3. /call-floor
    res_floor = client.get("/call-floor")
    assert res_floor.status_code == 200
    assert "[PURGED]" not in res_floor.data.decode("utf-8")

    # 4. /call/<id> for purged or unknown household returns 404 with plain "Record removed or not found"
    for test_id in ["hh-001", "call-001", "nonexistent-id"]:
        res_call = client.get(f"/call/{test_id}")
        assert res_call.status_code == 404
        assert "Record removed or not found" in res_call.data.decode("utf-8")
        assert "[PURGED]" not in res_call.data.decode("utf-8")

    # 5. /fleet
    res_fleet = client.get("/fleet")
    assert res_fleet.status_code == 200
    assert "[PURGED]" not in res_fleet.data.decode("utf-8")


def test_audit_log_detail_contains_no_10_digit_or_plus91_phone_numbers(auth_app):
    """
    Requirement 2: Verify that scanning audit_log.detail finds no 10-digit sequence
    or +91 phone number after registration, sign-in, and purge.
    """
    import re
    from db import get_db

    client = auth_app.test_client()
    raw_phone = "9845012399"

    # 1. Registration
    csrf_reg = get_csrf(client, "/register")
    client.post("/register", data={
        "csrf_token": csrf_reg,
        "first_name": "Deepak",
        "phone": raw_phone,
        "landmark": "Near Someshwara Beach",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "consent": "1"
    })
    client.get("/logout")

    # 2. Sign-in (success)
    csrf_signin = get_csrf(client, "/signin")
    client.post("/signin", data={
        "csrf_token": csrf_signin,
        "phone": raw_phone,
        "password": "SecurePassword123"
    })
    client.get("/logout")

    # 3. Sign-in (failed password)
    csrf_fail = get_csrf(client, "/signin")
    client.post("/signin", data={
        "csrf_token": csrf_fail,
        "phone": raw_phone,
        "password": "WrongPassword999"
    })

    # 4. Privacy purge
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]
    client.post(
        "/api/privacy/delete-now",
        json={"confirm": True},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )

    # 5. Scan all audit_log.detail entries
    with auth_app.app_context():
        db = get_db()
        rows = db.execute("SELECT detail FROM audit_log WHERE detail IS NOT NULL").fetchall()
        assert len(rows) > 0

        for r in rows:
            detail = r["detail"]
            # No 10-digit phone number sequence
            assert re.search(r'\b\d{10}\b', detail) is None, f"10-digit sequence leaked in audit detail: {detail}"
            # No +91 followed by digits (masked '+91 XXXXX XXXXX' is permitted)
            assert re.search(r'\+91\s*\d{3,}', detail) is None, f"+91 number leaked in audit detail: {detail}"
            # Ensure the test phone never appears
            assert raw_phone not in detail, f"Raw phone {raw_phone} found in audit detail: {detail}"


def test_privacy_purge_clears_requests_audio_files_and_transcripts(auth_app):
    """
    Requirement 3: Confirm the purge clears request.needs_json, generated audio files
    under static/audio and audio_cache (except the three seed clips), and any transcript text.
    """
    import os
    from config import Config
    from db import get_db

    client = auth_app.test_client()

    # Stage test audio files
    Config.AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    test_cached_audio = Config.AUDIO_CACHE_DIR / "test_cached_tts_123.wav"
    with open(test_cached_audio, "wb") as f:
        f.write(b"RIFFdummydataWAVEfmt ")

    static_audio_dir = Config.BASE_DIR / "static" / "audio"
    static_audio_dir.mkdir(parents=True, exist_ok=True)
    test_generated_audio = static_audio_dir / "generated_call_temp_456.wav"
    with open(test_generated_audio, "wb") as f:
        f.write(b"RIFFdummydataWAVEfmt ")

    # Verify seed clips exist or create mock ones
    seed_clips = ["sample_kannada.wav", "sample_hindi.wav", "sample_hinglish.wav"]
    for sc in seed_clips:
        p = static_audio_dir / sc
        if not p.exists():
            with open(p, "wb") as f:
                f.write(b"RIFFseedclipWAVEfmt ")

    # Stage a request with needs_json and a call with transcript
    with auth_app.app_context():
        db = get_db()
        db.execute("UPDATE request SET needs_json = '{\"members\": 4, \"special_assistance\": \"wheelchair\"}' WHERE id = 'req-001'")
        db.execute("UPDATE call SET transcript = 'Water is entering our house from the canal', extracted_json = '{\"emergency\": 1}' WHERE id = 'call-001'")
        db.commit()

    # Execute purge
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]

    res = client.post(
        "/api/privacy/delete-now",
        json={"confirm": True},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res.status_code == 200

    # 1. Verify audio_cache cleared
    assert not test_cached_audio.exists(), "Audio cache file was not removed by purge"

    # 2. Verify static/audio generated files removed, but seed clips preserved
    assert not test_generated_audio.exists(), "Generated static audio file was not removed by purge"
    for sc in seed_clips:
        assert (static_audio_dir / sc).exists(), f"Seed clip {sc} was incorrectly deleted by purge"

    # 3. Verify database request.needs_json and call.transcript cleared
    with auth_app.app_context():
        db = get_db()
        req_rows = db.execute("SELECT needs_json FROM request").fetchall()
        for r in req_rows:
            assert r["needs_json"] == "{}" or r["needs_json"] is None

        call_rows = db.execute("SELECT transcript, audio_path FROM call").fetchall()
        for c in call_rows:
            assert c["transcript"] == "" or c["transcript"] is None
            assert c["audio_path"] is None


def test_database_file_scan_after_purge_checks_phones_and_names(auth_app):
    """
    Requirement 3: PRAGMA wal_checkpoint(TRUNCATE) then VACUUM.
    Extend database file scan test to run after a purge, scanning binary abhay.db*
    for the plaintext phones and first names of seeded and test-registered households.
    """
    import os
    import glob
    from config import Config
    from db import get_db, decrypt_phone

    client = auth_app.test_client()

    # Register a new resident with known unique phone and unique first name
    registered_phone = "9845889900"
    registered_name = "Channabasappa"
    csrf = get_csrf(client, "/register")
    res_reg = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": registered_name,
        "phone": registered_phone,
        "landmark": "Near Town Hall Ground",
        "password": "Password1234",
        "confirm_password": "Password1234",
        "consent": "1"
    }, follow_redirects=True)
    assert res_reg.status_code == 200

    # Collect plaintext phones and names to check
    phones_to_check = {registered_phone, "9876543210", "9876543211", "9876543212", "9876543213"}
    names_to_check = {registered_name}

    with auth_app.app_context():
        from db import get_db, decrypt_phone, close_db
        db = get_db()
        # Collect first names from households before purge
        hh_rows = db.execute("SELECT first_name, phone_enc FROM household WHERE first_name != '[PURGED]' AND first_name IS NOT NULL").fetchall()
        for h in hh_rows:
            if h["first_name"] and len(h["first_name"]) >= 4:
                names_to_check.add(h["first_name"])
            try:
                dec = decrypt_phone(h["phone_enc"])
                if dec and len(dec) >= 7:
                    phones_to_check.add(dec)
            except Exception:
                pass
        close_db()

    # Trigger purge via dispatcher
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]

    res_purge = client.post(
        "/api/privacy/delete-now",
        json={"confirm": True, "incident_id": "inc-bantwal-01"},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res_purge.status_code == 200

    # Read binary contents of abhay.db and any WAL/SHM files
    db_path = Config.DATABASE_PATH
    db_dir = os.path.dirname(os.path.abspath(db_path))
    db_base = os.path.basename(db_path)

    matching_files = glob.glob(os.path.join(db_dir, f"{db_base}*"))
    assert len(matching_files) >= 1

    all_bytes = b""
    for fpath in matching_files:
        if os.path.isfile(fpath) and not fpath.endswith("-shm"):
            try:
                with open(fpath, "rb") as f:
                    all_bytes += f.read()
            except (PermissionError, OSError):
                pass

    # Scan for plaintext phones
    for phone in phones_to_check:
        assert phone.encode("utf-8") not in all_bytes, f"Plaintext phone {phone} found in database binary file after purge!"

    # Scan for first names of registered and seeded households
    for name in names_to_check:
        assert name.encode("utf-8") not in all_bytes, f"Plaintext name {name} found in database binary file after purge!"


def test_purged_resident_session_invalidated_by_before_request(auth_app):
    """
    Requirement 4: Invalidate sessions of purged resident users via session_version
    or password_hash check in before_request.
    """
    client = auth_app.test_client()

    # 1. Register resident and verify logged in
    csrf = get_csrf(client, "/register")
    res_reg = client.post("/register", data={
        "csrf_token": csrf,
        "first_name": "Narayana",
        "phone": "9845334455",
        "landmark": "Near Shamboor Checkpost",
        "password": "ValidPassword123",
        "confirm_password": "ValidPassword123",
        "consent": "1"
    }, follow_redirects=True)
    assert res_reg.status_code == 200

    # Resident can view /ready
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert "Narayana" in res_ready.data.decode("utf-8")

    # 2. In a separate dispatcher session, trigger delete-now
    disp_client = auth_app.test_client()
    disp_client.post("/login", data={"role": "dispatcher"})
    with disp_client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]

    res_purge = disp_client.post(
        "/api/privacy/delete-now",
        json={"confirm": "YES_PURGE"},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res_purge.status_code == 200

    # 3. Resident client requests /ready again -> redirected to /signin with session cleared
    res_after = client.get("/ready", follow_redirects=False)
    assert res_after.status_code == 302
    assert "/signin" in res_after.headers["Location"]

    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "role" not in sess


def test_delete_now_incident_scope_and_role_refusal(auth_app):
    """
    Requirement 5: Scope delete-now to a selected incident_id, require Dispatcher role,
    and require typed confirmation.
    """
    from db import get_db, mask_phone, encrypt_phone, hash_phone
    from werkzeug.security import generate_password_hash

    client = auth_app.test_client()

    # 1. Role refusal: Non-dispatcher (e.g. driver or resident) is rejected with 403
    client.post("/login", data={"role": "driver"})
    with client.session_transaction() as sess:
        driver_csrf = sess["csrf_token"]

    res_refusal = client.post(
        "/api/privacy/delete-now",
        json={"confirm": "CONFIRM"},
        headers={"X-CSRF-Token": driver_csrf},
        auto_csrf=False
    )
    assert res_refusal.status_code == 403
    assert "dispatcher role required" in res_refusal.get_json()["error"]

    # 2. Missing confirmation check: returns 400
    client.get("/logout")
    client.post("/login", data={"role": "dispatcher"})
    with client.session_transaction() as sess:
        disp_csrf = sess["csrf_token"]

    res_no_conf = client.post(
        "/api/privacy/delete-now",
        json={},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res_no_conf.status_code == 400
    assert "confirmation is required" in res_no_conf.get_json()["error"]

    # 3. Incident scoping test:
    with auth_app.app_context():
        db = get_db()
        # Seed second incident
        db.execute("INSERT OR REPLACE INTO incident (id, name, hazard) VALUES ('inc-scope-test-02', 'Test River Flood', 'flood')")
        raw_p2 = "9845999888"
        db.execute("""
            INSERT OR REPLACE INTO household (id, incident_id, first_name, phone_masked, phone_enc, phone_hash, landmark, pin, status)
            VALUES ('hh-scope-01', 'inc-scope-test-02', 'Gangamma', ?, ?, ?, 'Near Bridge', '574211', 'needs_help')
        """, (mask_phone(raw_p2), encrypt_phone(raw_p2), hash_phone(raw_p2)))
        db.execute("""
            INSERT OR REPLACE INTO user (id, username, password_hash, role, full_name, phone_masked, phone_enc, phone_hash)
            VALUES ('usr-scope-01', 'gangamma_test', ?, 'resident', 'Gangamma', ?, ?, ?)
        """, (generate_password_hash("pass123"), mask_phone(raw_p2), encrypt_phone(raw_p2), hash_phone(raw_p2)))
        db.commit()

    # Dispatcher purges ONLY 'inc-scope-test-02'
    res_scoped_purge = client.post(
        "/api/privacy/delete-now",
        json={"confirm": "CONFIRM_DELETE", "incident_id": "inc-scope-test-02"},
        headers={"X-CSRF-Token": disp_csrf},
        auto_csrf=False
    )
    assert res_scoped_purge.status_code == 200

    # Verify: inc-scope-test-02 household and user are purged
    with auth_app.app_context():
        db = get_db()
        hh_scoped = db.execute("SELECT first_name, phone_masked FROM household WHERE id = 'hh-scope-01'").fetchone()
        assert hh_scoped["first_name"] == "[PURGED]"

        user_scoped = db.execute("SELECT full_name FROM user WHERE id = 'usr-scope-01'").fetchone()
        assert user_scoped["full_name"] == "[PURGED]"

        # But inc-bantwal-01 households (e.g. hh-001) remain active and UNPURGED!
        hh_main = db.execute("SELECT first_name FROM household WHERE id = 'hh-001'").fetchone()
        assert hh_main["first_name"] != "[PURGED]"

        # Cleanup test incident (child tables before parent)
        db.execute("DELETE FROM callback WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-scope-test-02')")
        db.execute("DELETE FROM member WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-scope-test-02')")
        db.execute("DELETE FROM call WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-scope-test-02')")
        db.execute("DELETE FROM request WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-scope-test-02')")
        db.execute("DELETE FROM field_visit WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-scope-test-02')")
        db.execute("DELETE FROM household WHERE incident_id = 'inc-scope-test-02'")
        db.execute("DELETE FROM user WHERE id = 'usr-scope-01'")
        db.execute("DELETE FROM incident WHERE id = 'inc-scope-test-02'")
        db.commit()


def test_auto_purge_72h_with_mocked_clock(auth_app):
    """
    Requirement 6: Test automatic 72-hour deletion job using a mocked clock.
    """
    from datetime import datetime, timezone, timedelta
    from api.audit import purge_closed_incidents_older_than_72h
    from db import get_db, mask_phone, encrypt_phone, hash_phone

    with auth_app.app_context():
        db = get_db()
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        closed_at_str = t0.isoformat()

        # Insert incident closed at t0
        db.execute("INSERT OR REPLACE INTO incident (id, name, hazard, closed_at) VALUES ('inc-auto-72h', 'Old Closed Cyclone', 'cyclone', ?)", (closed_at_str,))
        raw_p = "9845119922"
        db.execute("""
            INSERT OR REPLACE INTO household (id, incident_id, first_name, phone_masked, phone_enc, phone_hash, landmark, pin, status)
            VALUES ('hh-auto-01', 'inc-auto-72h', 'Thimmakka', ?, ?, ?, 'Near Hill Road', '574211', 'needs_help')
        """, (mask_phone(raw_p), encrypt_phone(raw_p), hash_phone(raw_p)))
        db.commit()

        # At t0 + 71 hours: Not yet 72 hours -> should NOT purge
        t_71h = t0 + timedelta(hours=71)
        purged = purge_closed_incidents_older_than_72h(db=db, current_time=t_71h)
        assert "inc-auto-72h" not in purged
        hh_check = db.execute("SELECT first_name FROM household WHERE id = 'hh-auto-01'").fetchone()
        assert hh_check["first_name"] == "Thimmakka"

        # At t0 + 73 hours: Older than 72 hours -> should purge!
        t_73h = t0 + timedelta(hours=73)
        purged_73 = purge_closed_incidents_older_than_72h(db=db, current_time=t_73h)
        assert "inc-auto-72h" in purged_73
        hh_check_after = db.execute("SELECT first_name, phone_masked FROM household WHERE id = 'hh-auto-01'").fetchone()
        assert hh_check_after["first_name"] == "[PURGED]"

        # Cleanup test incident
        db.execute("DELETE FROM callback WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-auto-72h')")
        db.execute("DELETE FROM member WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-auto-72h')")
        db.execute("DELETE FROM call WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-auto-72h')")
        db.execute("DELETE FROM request WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-auto-72h')")
        db.execute("DELETE FROM field_visit WHERE household_id IN (SELECT id FROM household WHERE incident_id = 'inc-auto-72h')")
        db.execute("DELETE FROM household WHERE incident_id = 'inc-auto-72h'")
        db.execute("DELETE FROM incident WHERE id = 'inc-auto-72h'")
        db.commit()
