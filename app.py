"""
Abhay DDMA Command Web Application
Indian District Disaster AI Evacuation Coordinator
Built for the Gnani AI Great Indian AI Internship Challenge.
"""

import hmac
import os
import secrets
import time
import uuid
from collections import defaultdict
from pathlib import Path
from flask import Flask, render_template, send_from_directory, request, jsonify, session, redirect, url_for, flash
import jinja2

from config import Config
from db import close_db, get_db, log_audit, mask_phone, encrypt_phone, hash_phone, normalize_phone
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.parse

# Rate limiting storage (in-memory per process)
RATE_LIMIT_STORE = defaultdict(list)

def check_rate_limit(key: str, max_attempts: int = 5, window_sec: int = 900) -> bool:
    """Returns True if within rate limit, False if exceeded limit."""
    now = time.time()
    attempts = RATE_LIMIT_STORE[key]
    # Filter attempts within current sliding window
    RATE_LIMIT_STORE[key] = [t for t in attempts if now - t < window_sec]
    return len(RATE_LIMIT_STORE[key]) < max_attempts

def record_rate_limit_attempt(key: str):
    RATE_LIMIT_STORE[key].append(time.time())

def reset_rate_limits():
    RATE_LIMIT_STORE.clear()

# Constant-time dummy hash for generic timing on failed lookups
DUMMY_PASSWORD_HASH = generate_password_hash("constant_timing_dummy_password_2026")

from flask.testing import FlaskClient

class AbhayTestClient(FlaskClient):
    """
    Test client that automatically attaches the session's X-CSRF-Token for authenticated
    state-changing calls, exactly mimicking the browser's shared JS fetch wrapper, unless
    explicitly overridden or auto_csrf=False.
    """
    def open(self, *args, **kwargs):
        auto_csrf = kwargs.pop("auto_csrf", True)
        if auto_csrf:
            headers = kwargs.get("headers")
            if headers is None:
                headers = {}
                kwargs["headers"] = headers
            has_csrf = False
            if isinstance(headers, dict):
                has_csrf = any(k.lower() == "x-csrf-token" for k in headers)
            elif isinstance(headers, (list, tuple)):
                has_csrf = any(k.lower() == "x-csrf-token" for k, _ in headers)
            if not has_csrf:
                try:
                    with self.session_transaction() as sess:
                        token = sess.get("csrf_token")
                        if token and isinstance(headers, dict):
                            headers["X-CSRF-Token"] = token
                except Exception:
                    pass
        return super().open(*args, **kwargs)

# Import Blueprints
from api.events import events_bp
from api.households import households_bp
from api.calls import calls_bp
from api.requests import requests_bp
from api.vehicles import vehicles_bp
from api.drivers import drivers_bp
from api.audit import audit_bp
from api.incidents import incidents_bp
from api.evals import evals_bp
from api.optimizer import optimizer_bp

def create_app():
    app = Flask(
        __name__,
        static_folder=str(Config.BASE_DIR / "static"),
        static_url_path="/static"
    )
    app.secret_key = Config.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.test_client_class = AbhayTestClient

    def rotate_session():
        """Rotate session to prevent session fixation attacks."""
        lang = session.get("lang", "en")
        session.clear()
        session["session_id"] = secrets.token_hex(16)
        session["csrf_token"] = secrets.token_hex(32)
        session["lang"] = lang

    # Configure dual Jinja loader so templates from screens/ and templates/ can be loaded seamlessly
    screens_dir = str(Config.BASE_DIR / "screens")
    templates_dir = str(Config.BASE_DIR / "templates")
    app.jinja_loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(screens_dir),
        jinja2.FileSystemLoader(templates_dir)
    ])

    # Register Blueprints
    app.register_blueprint(events_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(evals_bp)
    app.register_blueprint(optimizer_bp)

    # Database connection teardown
    @app.teardown_appcontext
    def teardown_db(exception):
        close_db(exception)

    # Serve generated audio cache
    @app.route("/audio-cache/<path:filename>")
    def serve_audio_cache(filename):
        return send_from_directory(str(Config.AUDIO_CACHE_DIR), filename)


    # --- Role-Based Access Control Middleware ---
    @app.before_request
    def check_role_access():
        path = request.path

        # Ensure CSRF token is initialized in session
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)

        # Enforce CSRF token on all state-changing API requests under /api
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if path.startswith("/api/") and not path.startswith("/api/set-lang/"):
                token = request.headers.get("X-CSRF-Token")
                if not token and request.is_json:
                    token = (request.get_json(silent=True) or {}).get("csrf_token")
                if not token:
                    token = request.form.get("csrf_token")

                session_token = session.get("csrf_token")
                if not token or not session_token or not hmac.compare_digest(str(token), str(session_token)):
                    return jsonify({
                        "success": False,
                        "error": "Invalid or missing CSRF token. X-CSRF-Token header is required."
                    }), 400

        # Allow static files, audio cache, public auth screens and info
        if path.startswith("/static/") or path.startswith("/audio-cache/") or path in ("/", "/login", "/logout", "/register", "/signin", "/under-the-hood") or path.startswith("/api/set-lang/"):
            return None

        # Invalidate sessions of purged resident users
        role = session.get("role")
        if role == "resident":
            user_id = session.get("user_id")
            hh_id = session.get("household_id")
            sess_ver = session.get("session_version", 1)
            db = get_db()
            invalid = False
            if user_id:
                u_cols = [r[1] for r in db.execute("PRAGMA table_info(user)").fetchall()]
                if "session_version" in u_cols:
                    u = db.execute("SELECT session_version, password_hash FROM user WHERE id = ?", (user_id,)).fetchone()
                    if u and (u["password_hash"] == "[PURGED]" or u["session_version"] != sess_ver):
                        invalid = True
                else:
                    u = db.execute("SELECT password_hash FROM user WHERE id = ?", (user_id,)).fetchone()
                    if u and u["password_hash"] == "[PURGED]":
                        invalid = True
            elif hh_id:
                hh = db.execute("SELECT first_name FROM household WHERE id = ?", (hh_id,)).fetchone()
                if hh and hh["first_name"] == "[PURGED]":
                    invalid = True

            if invalid:
                session.clear()
                if path.startswith("/api/"):
                    return jsonify({"success": False, "error": "Session invalidated or record purged", "redirect": "/signin"}), 401
                return redirect("/signin?error=" + urllib.parse.quote("Your session has ended as personal data was purged."))

        # If DEMO_MODE is disabled, allow access without demo role enforcement
        demo_mode = app.config.get("DEMO_MODE", Config.DEMO_MODE)
        if not demo_mode:
            return None

        role = session.get("role")
        if not role:
            if path.startswith("/api/"):
                return jsonify({"success": False, "error": "Unauthorized"}), 401
            # Route residents to /signin, staff/demo to /login
            if path in ("/ready", "/household-needs", "/confirmation", "/phone"):
                return redirect("/signin?error=" + urllib.parse.quote("Please sign in to continue."))
            return redirect("/login?error=" + urllib.parse.quote("Please choose a demo role to continue."))

        # Page-level role whitelist
        ROLE_PAGE_WHITELIST = {
            "dispatcher": ["/incidents", "/dashboard", "/call-floor", "/call/", "/simulate", "/fleet", "/audit", "/privacy", "/under-the-hood", "/evals"],
            "driver": ["/driver", "/run/"],
            "field_worker": ["/field", "/house/", "/house-card"],
            "resident": ["/ready", "/household-needs", "/confirmation", "/phone"]
        }

        # Check page routes
        if not path.startswith("/api/"):
            allowed_prefixes = ROLE_PAGE_WHITELIST.get(role, [])
            allowed = False
            for p in allowed_prefixes:
                if p == "/" and path == "/":
                    allowed = True
                    break
                elif p != "/" and (path == p or path.startswith(p)):
                    allowed = True
                    break
            if not allowed:
                return redirect("/login?error=" + urllib.parse.quote(f"Access denied: {role} cannot access {path}"))

        # API-level role permissions
        if path.startswith("/api/"):
            # Driver-only endpoints
            if path.startswith("/api/driver/offers/") or path.startswith("/api/runs/"):
                if role != "driver":
                    return jsonify({"success": False, "error": "Forbidden: driver role required"}), 403
                
                # Check offer addressed to their own vehicle
                if "/accept" in path or "/decline" in path:
                    parts = path.split("/")
                    if len(parts) >= 5:
                        offer_id = parts[4]
                        db = get_db()
                        off = db.execute("SELECT vehicle_id FROM offer WHERE id = ?", (offer_id,)).fetchone()
                        if off and session.get("vehicle_id") and off["vehicle_id"] != session.get("vehicle_id"):
                            return jsonify({"success": False, "error": "Forbidden: offer is for a different vehicle"}), 403

            # Dispatcher-only endpoints
            DISPATCHER_ONLY_APIS = ["/api/assign", "/api/simulate-call", "/api/privacy/delete-now", "/api/evals/run", "/api/unanswered-retry", "/api/optimizer/suggest-plan"]
            for d_api in DISPATCHER_ONLY_APIS:
                if path.startswith(d_api) and role != "dispatcher":
                    return jsonify({"success": False, "error": "Forbidden: dispatcher role required"}), 403
            
            # Request creation: only dispatcher
            if path == "/api/requests" and request.method == "POST" and role != "dispatcher":
                return jsonify({"success": False, "error": "Forbidden: dispatcher role required"}), 403

            # Field worker endpoints
            if path.startswith("/api/field-visits/") and request.method == "POST":
                if role != "field_worker":
                    return jsonify({"success": False, "error": "Forbidden: field_worker role required"}), 403

        return None

    # --- HTML Page Routes (15 Core Navigation Pages) ---

    @app.context_processor
    def inject_global_vars():
        import json
        from core.i18n import t, translate_status, translate_nav, get_i18n_dict
        db = get_db()
        inc = db.execute("SELECT name FROM incident WHERE closed_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        incident_name = inc["name"] if inc else "Demo Flood, Bantwal"
        cur_lang = session.get("lang", "en")
        dict_i18n = get_i18n_dict(cur_lang)
        return {
            "officer_name": session.get("user_name", "Duty officer"),
            "incident_name": incident_name,
            "demo_mode": app.config.get("DEMO_MODE", Config.DEMO_MODE),
            "current_lang": cur_lang,
            "t": lambda k: t(k, cur_lang),
            "t_status": lambda k: translate_status(k, cur_lang),
            "t_nav": lambda k: translate_nav(k, cur_lang),
            "i18n_dict": dict_i18n,
            "i18n_json": json.dumps(dict_i18n),
            "use_mock_gnani": Config.USE_MOCK_GNANI,
            "csrf_token": session.get("csrf_token", "")
        }

    @app.route("/login", methods=["GET", "POST"])
    def page_login():
        if request.method == "POST":
            role_home = {
                "dispatcher": "/dashboard",
                "driver": "/driver",
                "field_worker": "/field",
                "resident": "/ready"
            }

            # Optional credential login support
            action = request.form.get("action")
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            if action == "login" or (username and password):
                db = get_db()
                user = db.execute(
                    "SELECT * FROM user WHERE username = ? OR (email IS NOT NULL AND email != '' AND email = ?)",
                    (username, username)
                ).fetchone()
                from werkzeug.security import check_password_hash
                if not user or not check_password_hash(user["password_hash"], password):
                    demo_mode = app.config.get("DEMO_MODE", Config.DEMO_MODE)
                    return render_template("login.html", demo_mode=demo_mode, error="Invalid username or password."), 200

                role = user["role"]
                full_name = user["full_name"]
                rotate_session()
                session["user_id"] = user["id"]
                session["role"] = role
                session["user_name"] = full_name
                if role == "driver":
                    session["vehicle_id"] = user["vehicle_id"] or "veh-01"
                else:
                    session.pop("vehicle_id", None)

                log_audit(
                    actor=full_name,
                    actor_type=role,
                    action="USER_LOGIN",
                    detail=f"User {user['username']} logged in with credentials as {role}",
                    conn=db
                )
                db.commit()
                return redirect(role_home.get(role, "/dashboard"))

            # Quick Demo Role 1-Click Login
            demo_mode = app.config.get("DEMO_MODE", Config.DEMO_MODE)
            if not demo_mode:
                return render_template(
                    "login.html",
                    demo_mode=False,
                    error="Demo role entry is disabled in production mode. Please use resident sign-in."
                ), 403

            role = request.form.get("role", "dispatcher")
            user_names = {
                "dispatcher": "Duty officer",
                "driver": "Driver Suresh (Rescue Boat NDRF-1)",
                "field_worker": "ASHA Worker Suma",
                "resident": "Citizen Parvathi"
            }
            user_name = user_names.get(role, "Demo User")
            rotate_session()
            session["role"] = role
            session["user_name"] = user_name
            if role == "driver":
                session["vehicle_id"] = "veh-01"
            else:
                session.pop("vehicle_id", None)

            # Log to audit_log
            db = get_db()
            log_audit(
                actor=user_name,
                actor_type=role,
                action="USER_LOGIN",
                detail=f"User logged in as {role}",
                conn=db
            )
            db.commit()

            return redirect(role_home.get(role, "/dashboard"))

        demo_mode = app.config.get("DEMO_MODE", Config.DEMO_MODE)
        error = request.args.get("error")
        return render_template("login.html", demo_mode=demo_mode, error=error)

    @app.route("/signin", methods=["GET", "POST"])
    def page_signin():
        if request.method == "POST":
            # CSRF protection on POST forms
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            session_token = session.get("csrf_token")
            if not token or not session_token or not hmac.compare_digest(str(token), str(session_token)):
                return render_template("signin.html", error="Invalid or missing CSRF token."), 400

            phone = (request.form.get("phone") or "").strip()
            password = request.form.get("password") or ""
            client_ip = request.remote_addr or "127.0.0.1"
            phone_h = hash_phone(phone) if phone else "none"

            # Rate limit check per IP and per phone (5 attempts per 15 min)
            ip_key = f"ip:{client_ip}:signin"
            phone_key = f"phone:{phone_h}:signin"

            if not check_rate_limit(ip_key) or (phone and not check_rate_limit(phone_key)):
                db = get_db()
                log_audit(
                    actor="anonymous",
                    actor_type="resident",
                    action="RATE_LIMIT_EXCEEDED",
                    household_id=None,
                    detail="Rate limit exceeded on /signin endpoint",
                    conn=db
                )
                db.commit()
                return render_template("signin.html", error="Too many attempts. Please try again after 15 minutes.", phone=phone), 429

            record_rate_limit_attempt(ip_key)
            if phone:
                record_rate_limit_attempt(phone_key)

            if not phone or not password:
                return render_template("signin.html", error="Phone or password is incorrect", phone=phone), 400

            db = get_db()
            user = db.execute("SELECT * FROM user WHERE role = 'resident' AND phone_hash = ?", (phone_h,)).fetchone()

            # Generic error timing: always perform a password hash comparison
            if not user:
                check_password_hash(DUMMY_PASSWORD_HASH, password)
                log_audit(
                    actor="anonymous",
                    actor_type="resident",
                    action="AUTH_FAILED",
                    household_id=None,
                    detail="Failed sign-in attempt (invalid credentials)",
                    conn=db
                )
                db.commit()
                return render_template("signin.html", error="Phone or password is incorrect", phone=phone), 401

            if not check_password_hash(user["password_hash"], password):
                log_audit(
                    actor="anonymous",
                    actor_type="resident",
                    action="AUTH_FAILED",
                    household_id=None,
                    detail="Failed sign-in attempt (invalid credentials)",
                    conn=db
                )
                db.commit()
                return render_template("signin.html", error="Phone or password is incorrect", phone=phone), 401

            # Sign-in verified. Find associated household
            hh = db.execute("SELECT id FROM household WHERE phone_hash = ?", (phone_h,)).fetchone()
            hh_id = hh["id"] if hh else None

            rotate_session()
            session["user_id"] = user["id"]
            session["role"] = "resident"
            session["user_name"] = user["full_name"]
            session["household_id"] = hh_id
            session["session_version"] = user["session_version"] if "session_version" in user.keys() else 1
            session.pop("vehicle_id", None)

            log_audit(
                actor=user["full_name"],
                actor_type="resident",
                action="USER_LOGIN",
                household_id=hh_id,
                detail="Resident signed in with phone credentials",
                conn=db
            )
            db.commit()

            if request.is_json:
                return jsonify({"success": True, "redirect": "/ready"}), 200
            return redirect("/ready")

        error = request.args.get("error")
        return render_template("signin.html", error=error)

    @app.route("/register", methods=["GET", "POST"])
    def page_register():
        if request.method == "POST":
            # CSRF protection on POST forms
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            session_token = session.get("csrf_token")
            if not token or not session_token or not hmac.compare_digest(str(token), str(session_token)):
                return render_template("register.html", error="Invalid or missing CSRF token."), 400

            data = request.form
            first_name_input = (data.get("first_name") or data.get("full_name") or "").strip()
            phone = (data.get("phone") or "").strip()
            landmark = (data.get("landmark") or "").strip()
            password = data.get("password") or ""
            confirm_password = data.get("confirm_password") or ""
            consent = data.get("consent")
            attempted_role = (data.get("role") or "").strip().lower()

            # Prevent staff registration
            if attempted_role in ("dispatcher", "driver", "field_worker"):
                return render_template(
                    "register.html",
                    error="Staff roles cannot be registered. Please use demo login.",
                    errors=["Staff roles cannot be registered. Please use demo login."],
                    first_name=first_name_input,
                    phone=phone,
                    landmark=landmark,
                    consent=bool(consent)
                ), 400

            client_ip = request.remote_addr or "127.0.0.1"
            phone_h = hash_phone(phone) if phone else "none"

            # Rate limiting check
            ip_key = f"ip:{client_ip}:register"
            phone_key = f"phone:{phone_h}:register"

            if not check_rate_limit(ip_key) or (phone and not check_rate_limit(phone_key)):
                db = get_db()
                log_audit(
                    actor="anonymous",
                    actor_type="resident",
                    action="RATE_LIMIT_EXCEEDED",
                    household_id=None,
                    detail="Rate limit exceeded on /register endpoint",
                    conn=db
                )
                db.commit()
                return render_template(
                    "register.html",
                    error="Too many attempts. Please try again after 15 minutes.",
                    errors=["Too many attempts. Please try again after 15 minutes."],
                    first_name=first_name_input,
                    phone=phone,
                    landmark=landmark,
                    consent=bool(consent)
                ), 429

            record_rate_limit_attempt(ip_key)
            if phone:
                record_rate_limit_attempt(phone_key)

            errors = []
            if not first_name_input:
                errors.append("First name is required.")
            first_name = first_name_input.split()[0] if first_name_input else ""

            if not phone:
                errors.append("Phone number is required.")
            else:
                digits = "".join(c for c in phone if c.isdigit())
                if len(digits) < 7:
                    errors.append("Please provide a valid telephone number.")

            if not landmark:
                errors.append("Landmark or location is required.")

            if not password:
                errors.append("Password is required.")
            elif len(password) < 8:
                errors.append("Password must be at least 8 characters long.")

            if password and confirm_password and password != confirm_password:
                errors.append("Passwords do not match.")
            elif not confirm_password:
                errors.append("Please confirm your password.")

            if not consent:
                errors.append("Consent is required under DPDP Act 2023 principles for disaster coordination.")

            if errors:
                err_msg = " ".join(errors)
                return render_template(
                    "register.html",
                    error=err_msg,
                    errors=errors,
                    first_name=first_name,
                    phone=phone,
                    landmark=landmark,
                    consent=bool(consent)
                ), 400

            db = get_db()
            # Enforce limit: one household per phone number
            existing_hh = db.execute("SELECT id FROM household WHERE phone_hash = ?", (phone_h,)).fetchone()
            existing_usr = db.execute("SELECT id FROM user WHERE phone_hash = ?", (phone_h,)).fetchone()
            if existing_hh or existing_usr:
                return render_template(
                    "register.html",
                    error="A household with this phone number is already registered.",
                    errors=["A household with this phone number is already registered."],
                    first_name=first_name,
                    phone=phone,
                    landmark=landmark,
                    consent=bool(consent)
                ), 400

            user_id = f"usr-{uuid.uuid4().hex[:8]}"
            username = f"res_{uuid.uuid4().hex[:8]}"
            pwd_hash = generate_password_hash(password)
            phone_masked = mask_phone(phone)
            phone_enc = encrypt_phone(phone)

            # Insert resident user (never store plaintext phone)
            db.execute(
                "INSERT INTO user (id, username, email, password_hash, role, full_name, phone_masked, phone_enc, phone_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, None, pwd_hash, "resident", first_name, phone_masked, phone_enc, phone_h)
            )

            # Insert household with verification_status = 'self-reported, unverified'
            hh_id = f"hh-{uuid.uuid4().hex[:6]}"
            inc = db.execute("SELECT id FROM incident WHERE closed_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
            incident_id = inc["id"] if inc else "inc-bantwal-01"

            db.execute(
                """INSERT INTO household (id, incident_id, first_name, phone_masked, phone_enc, phone_hash, landmark, pin, lat, lng, language, members, status, consent_given, verification_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'self-reported, unverified')""",
                (hh_id, incident_id, first_name, phone_masked, phone_enc, phone_h, landmark, "574211", 12.8904, 75.0378, session.get("lang", "en"), 1, "needs_help")
            )

            # Insert initial household member
            db.execute(
                """INSERT INTO member (id, household_id, cannot_walk, wheelchair_type, bedridden, elderly, pregnant, needs_medicine_oxygen, sleeping_room)
                   VALUES (?, ?, 0, 'none', 0, 0, 0, 0, 'Ground Floor')""",
                (f"mem-{uuid.uuid4().hex[:6]}", hh_id)
            )

            # Log registration to audit_log (never log password or raw phone)
            log_audit(
                actor=first_name,
                actor_type="resident",
                action="USER_REGISTER",
                household_id=hh_id,
                detail=f"Resident {first_name} registered household at {landmark} with DPDP consent and auto-deletion notice",
                conn=db
            )
            db.commit()

            # Rotate session to prevent session fixation and establish resident session
            rotate_session()
            session["user_id"] = user_id
            session["role"] = "resident"
            session["user_name"] = first_name
            session["household_id"] = hh_id
            session["session_version"] = 1
            session.pop("vehicle_id", None)

            if request.is_json:
                return jsonify({"success": True, "redirect": "/ready", "household_id": hh_id}), 200

            return redirect("/ready")

        error = request.args.get("error")
        return render_template("register.html", error=error)

    @app.route("/logout")
    def page_logout():
        role = session.get("role", "demo_user")
        user_name = session.get("user_name", "Demo User")
        db = get_db()
        log_audit(
            actor=user_name,
            actor_type=role if role in ("dispatcher", "driver", "resident", "field_worker") else "resident",
            action="USER_LOGOUT",
            detail=f"User signed out from {role}",
            conn=db
        )
        db.commit()
        rotate_session()
        session.clear()
        return redirect("/signin")

    @app.route("/api/set-lang/<lang>", methods=["POST", "GET"])
    def set_language(lang):
        if lang in ("en", "hi", "kn"):
            session["lang"] = lang
            if request.method == "GET":
                referer = request.headers.get("Referer")
                if referer:
                    return redirect(referer)
                return redirect(request.args.get("next") or "/")
            return jsonify({"success": True, "lang": lang})
        return jsonify({"success": False, "error": "Invalid language"}), 400

    @app.route("/api/profile/update", methods=["POST"])
    def update_profile():
        if not session.get("role"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        data = request.get_json() or {}
        full_name = (data.get("full_name") or "").strip()
        phone = (data.get("phone") or "").strip()
        address = (data.get("address") or "").strip()
        if not full_name:
            return jsonify({"success": False, "error": "Full name cannot be empty"}), 400

        session["user_name"] = full_name
        p_masked = mask_phone(phone) if phone else None
        if phone:
            session["phone"] = p_masked
        if address:
            session["address"] = address

        db = get_db()
        user_id = session.get("user_id")
        if user_id:
            u_cols = [r[1] for r in db.execute("PRAGMA table_info(user)").fetchall()]
            if "phone_masked" in u_cols and "phone" in u_cols:
                db.execute(
                    "UPDATE user SET full_name = ?, phone = ?, phone_masked = ? WHERE id = ?",
                    (full_name, p_masked, p_masked, user_id)
                )
            elif "phone_masked" in u_cols:
                db.execute(
                    "UPDATE user SET full_name = ?, phone_masked = ? WHERE id = ?",
                    (full_name, p_masked, user_id)
                )
            else:
                db.execute(
                    "UPDATE user SET full_name = ?, phone = ? WHERE id = ?",
                    (full_name, p_masked, user_id)
                )
        log_audit(
            actor=full_name,
            actor_type=session.get("role", "user"),
            action="USER_PROFILE_UPDATE",
            detail=f"User updated profile: name={full_name}, phone={p_masked or '[NONE]'}, address={address}",
            conn=db
        )
        db.commit()
        return jsonify({"success": True, "user_name": full_name, "role": session.get("role")})

    @app.route("/")
    def page_landing():
        return render_template("landing.html")

    @app.route("/incidents")
    def page_incident_select():
        return render_template("incident_select.html", active_page="incidents")

    @app.route("/dashboard")
    def page_dashboard():
        return render_template("dashboard.html")

    @app.route("/call-floor")
    def page_call_floor():
        return render_template("call_floor.html")

    @app.route("/call/<id>")
    def page_call_detail(id):
        import math, os
        db = get_db()
        call = None
        hh = None
        if str(id).startswith("call-"):
            call = db.execute("SELECT * FROM call WHERE id = ? AND transcript != ''", (id,)).fetchone()
            if call:
                hh = db.execute("SELECT * FROM household WHERE id = ? AND first_name != '[PURGED]' AND phone_masked != '[PURGED]'", (call["household_id"],)).fetchone()
        else:
            hh = db.execute("SELECT * FROM household WHERE id = ? AND first_name != '[PURGED]' AND phone_masked != '[PURGED]'", (id,)).fetchone()
            if hh:
                call = db.execute("SELECT * FROM call WHERE household_id = ? AND transcript != '' ORDER BY created_at DESC LIMIT 1", (hh["id"],)).fetchone()

        # If household is not found or has been purged, return 404 with plain "Record removed or not found" page
        if not hh:
            return render_template("404.html", message="Record removed or not found"), 404

        has_real_audio = False
        if call and call["audio_path"]:
            has_real_audio = os.path.exists(call["audio_path"])

        def haversine_km(lat1, lon1, lat2, lon2):
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                return None
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return round(R * c, 2)

        from core.assign import suggest_vehicles
        vehicles = suggest_vehicles(hh["id"], db=db) if hh else []

        req = None
        if hh:
            req = db.execute("SELECT * FROM request WHERE household_id = ? ORDER BY created_at DESC LIMIT 1", (hh["id"],)).fetchone()

        return render_template(
            "call_detail.html",
            call_id=id,
            household=hh,
            call=call,
            has_real_audio=has_real_audio,
            vehicles=vehicles,
            request=req,
            suggested_veh=request.args.get("suggested_veh", "")
        )

    @app.route("/simulate")
    def page_simulate():
        return render_template("simulate.html")

    @app.route("/fleet")
    def page_fleet():
        return render_template("fleet.html")

    @app.route("/run/<id>")
    def page_run(id):
        db = get_db()
        req = db.execute("SELECT * FROM request WHERE id = ?", (id,)).fetchone()
        hh = None
        veh = None
        if req:
            hh = db.execute("SELECT * FROM household WHERE id = ?", (req["household_id"],)).fetchone()
            if req["vehicle_id"]:
                veh = db.execute("SELECT * FROM vehicle WHERE id = ?", (req["vehicle_id"],)).fetchone()
        else:
            hh = db.execute("SELECT * FROM household WHERE status = 'needs_help' LIMIT 1").fetchone()
            if not hh:
                hh = db.execute("SELECT * FROM household LIMIT 1").fetchone()

        pickup_lat = hh["lat"] if hh else 12.8942
        pickup_lng = hh["lng"] if hh else 75.0351
        pickup_name = hh["first_name"] if hh else "Parvathi"
        pickup_landmark = hh["landmark"] if hh else "Someshwara Temple Lane, Ward 4"

        return render_template(
            "run.html",
            run_id=id,
            request=req,
            household=hh,
            vehicle=veh,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            pickup_name=pickup_name,
            pickup_landmark=pickup_landmark
        )

    @app.route("/driver")
    def page_driver():
        view = request.args.get("view", "offers")
        if view == "login":
            return render_template("driver_login.html")
        elif view == "complete":
            return render_template("run_complete.html")
        return render_template("driver_offers.html")

    @app.route("/ready")
    def page_ready():
        return render_template("ready.html")

    @app.route("/confirmation")
    def page_confirmation():
        return render_template("confirmation.html")

    @app.route("/household-needs")
    def page_household_needs():
        return render_template("household_needs.html")

    @app.route("/phone")
    def page_phone():
        return render_template("phone.html")

    @app.route("/field")
    def page_field():
        return render_template("field.html")

    @app.route("/house/<id>")
    @app.route("/house-card")
    def page_house_card(id=None):
        return render_template("house_card.html", house_id=id)

    @app.route("/audit")
    def page_audit():
        return render_template("audit.html")

    @app.route("/privacy")
    def page_privacy():
        return render_template("privacy.html")

    @app.route("/under-the-hood")
    def page_under_the_hood():
        return render_template("under_the_hood.html")

    @app.route("/evals")
    def page_evals():
        import json
        sim_path = Config.BASE_DIR / "evals" / "sim_results.json"
        sim_data = None
        if sim_path.exists():
            try:
                with open(sim_path, "r", encoding="utf-8") as f:
                    sim_data = json.load(f)
            except Exception:
                sim_data = None
        return render_template("evals.html", sim_results=sim_data)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
