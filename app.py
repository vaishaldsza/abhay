"""
Abhay DDMA Command Web Application
Indian District Disaster AI Evacuation Coordinator
Built for the Gnani AI Great Indian AI Internship Challenge.
"""

import os
from pathlib import Path
from flask import Flask, render_template, send_from_directory, request, jsonify, session, redirect, url_for, flash
import jinja2

from config import Config
from db import close_db, get_db, log_audit
import urllib.parse

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
        # Allow static files, audio cache, login and logout
        if path.startswith("/static/") or path.startswith("/audio-cache/") or path in ("/", "/login", "/logout", "/register", "/under-the-hood") or path.startswith("/api/set-lang/"):
            return None

        # If DEMO_MODE is disabled, allow access without demo role enforcement
        demo_mode = app.config.get("DEMO_MODE", Config.DEMO_MODE)
        if not demo_mode:
            return None

        role = session.get("role")
        if not role:
            if path.startswith("/api/"):
                return jsonify({"success": False, "error": "Unauthorized: please login at /login"}), 401
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
            "demo_mode": Config.DEMO_MODE,
            "current_lang": cur_lang,
            "t": lambda k: t(k, cur_lang),
            "t_status": lambda k: translate_status(k, cur_lang),
            "t_nav": lambda k: translate_nav(k, cur_lang),
            "i18n_dict": dict_i18n,
            "i18n_json": json.dumps(dict_i18n),
            "use_mock_gnani": Config.USE_MOCK_GNANI
        }

    @app.route("/login", methods=["GET", "POST"])
    def page_login():
        tab = request.args.get("tab", "login")
        if request.method == "POST":
            action = request.form.get("action")
            role_home = {
                "dispatcher": "/dashboard",
                "driver": "/driver",
                "field_worker": "/field",
                "resident": "/ready"
            }

            # --- CASE 1: Sign Up / Register New Account ---
            if action == "register":
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                full_name = (request.form.get("full_name") or "").strip()
                email = (request.form.get("email") or "").strip()
                role = (request.form.get("role") or "resident").strip()
                phone = (request.form.get("phone") or "").strip()
                vehicle_id = (request.form.get("vehicle_id") or "").strip() or ("veh-01" if role == "driver" else None)

                if not username or not password or not full_name:
                    return render_template("login.html", demo_mode=Config.DEMO_MODE, error="Please provide Full Name, Username, and Password.", tab="register")
                if role not in ("dispatcher", "driver", "field_worker", "resident"):
                    return render_template("login.html", demo_mode=Config.DEMO_MODE, error="Invalid role selected.", tab="register")

                db = get_db()
                existing = db.execute("SELECT id FROM user WHERE username = ? OR (email IS NOT NULL AND email != '' AND email = ?)", (username, email)).fetchone()
                if existing:
                    return render_template("login.html", demo_mode=Config.DEMO_MODE, error="Username or email is already registered.", tab="register")

                import uuid
                from werkzeug.security import generate_password_hash
                user_id = f"usr-{uuid.uuid4().hex[:8]}"
                pwd_hash = generate_password_hash(password)
                db.execute(
                    "INSERT INTO user (id, username, email, password_hash, role, full_name, phone, vehicle_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, email or None, pwd_hash, role, full_name, phone or None, vehicle_id)
                )
                log_audit(
                    actor=full_name,
                    actor_type=role,
                    action="USER_REGISTER",
                    detail=f"User registered with username {username} as {role}",
                    conn=db
                )
                db.commit()

                # Automatically establish session upon registration
                session["user_id"] = user_id
                session["role"] = role
                session["user_name"] = full_name
                if role == "driver":
                    session["vehicle_id"] = vehicle_id or "veh-01"
                else:
                    session.pop("vehicle_id", None)

                log_audit(
                    actor=full_name,
                    actor_type=role,
                    action="USER_LOGIN",
                    detail=f"User {username} auto-logged in as {role} after registration",
                    conn=db
                )
                db.commit()
                return redirect(role_home.get(role, "/dashboard"))

            # --- CASE 2: Account Login with Username & Password ---
            if action == "login" or (request.form.get("username") and request.form.get("password")):
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                db = get_db()
                user = db.execute(
                    "SELECT * FROM user WHERE username = ? OR (email IS NOT NULL AND email != '' AND email = ?)",
                    (username, username)
                ).fetchone()
                from werkzeug.security import check_password_hash
                if not user or not check_password_hash(user["password_hash"], password):
                    return render_template("login.html", demo_mode=Config.DEMO_MODE, error="Invalid username or password.", tab="login")

                role = user["role"]
                full_name = user["full_name"]
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

            # --- CASE 3: Quick Demo Role 1-Click Login ---
            role = request.form.get("role", "dispatcher")
            user_names = {
                "dispatcher": "Duty officer",
                "driver": "Driver Suresh (Rescue Boat NDRF-1)",
                "field_worker": "ASHA Worker Suma",
                "resident": "Citizen Parvathi"
            }
            user_name = user_names.get(role, "Demo User")
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

        error = request.args.get("error")
        return render_template("login.html", demo_mode=Config.DEMO_MODE, error=error, tab=tab)

    @app.route("/register", methods=["GET", "POST"])
    def page_register():
        if request.method == "POST":
            return page_login()
        error = request.args.get("error")
        return render_template("login.html", demo_mode=Config.DEMO_MODE, error=error, tab="register")

    @app.route("/logout")
    def page_logout():
        role = session.get("role", "demo_user")
        user_name = session.get("user_name", "Demo User")
        db = get_db()
        log_audit(
            actor=user_name,
            actor_type=role,
            action="USER_LOGOUT",
            detail=f"User logged out from {role}",
            conn=db
        )
        db.commit()
        session.clear()
        return redirect("/login")

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
        if phone:
            session["phone"] = phone
        if address:
            session["address"] = address

        db = get_db()
        user_id = session.get("user_id")
        if user_id:
            db.execute(
                "UPDATE user SET full_name = ?, phone = ? WHERE id = ?",
                (full_name, phone or None, user_id)
            )
        log_audit(
            actor=full_name,
            actor_type=session.get("role", "user"),
            action="USER_PROFILE_UPDATE",
            detail=f"User updated profile: name={full_name}, phone={phone}, address={address}",
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
            call = db.execute("SELECT * FROM call WHERE id = ?", (id,)).fetchone()
            if call:
                hh = db.execute("SELECT * FROM household WHERE id = ?", (call["household_id"],)).fetchone()
        else:
            hh = db.execute("SELECT * FROM household WHERE id = ?", (id,)).fetchone()
            if hh:
                call = db.execute("SELECT * FROM call WHERE household_id = ? ORDER BY created_at DESC LIMIT 1", (hh["id"],)).fetchone()

        if not hh:
            hh = db.execute("SELECT * FROM household LIMIT 1").fetchone()
        if not call and hh:
            call = db.execute("SELECT * FROM call WHERE household_id = ? ORDER BY created_at DESC LIMIT 1", (hh["id"],)).fetchone()

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
