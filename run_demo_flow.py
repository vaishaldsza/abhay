import os
import sys
import json
from config import Config

Config.USE_MOCK_GNANI = True
os.environ["USE_MOCK_GNANI"] = "true"

from app import create_app
from seed import seed_database
from db import get_db

def run_end_to_end_demo():
    print("======================================================================")
    print("STARTING ABHAY DDMA 6-STEP DEMO FLOW (USE_MOCK_GNANI=True)")
    print("======================================================================")

    # Re-seed to a known pristine operational state
    seed_database()
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    results = {}

    with app.app_context():
        # ------------------------------------------------------------------
        # STEP 1: Incident & Command Dashboard Context
        # ------------------------------------------------------------------
        print("\n--- STEP 1: Command Dashboard & Incident Context ---")
        try:
            # Login as Dispatcher
            login_res = client.post("/login", data={"role": "dispatcher"})
            assert login_res.status_code == 302
            res = client.get("/dashboard")
            assert res.status_code == 200, f"Status code {res.status_code}"
            html = res.data.decode("utf-8")
            assert "Demo Flood, Bantwal" in html
            assert "Duty officer" in html
            assert "District Magistrate" not in html
            assert "GPS LOCK" not in html
            
            hh_res = client.get("/api/households")
            assert hh_res.status_code == 200
            hh_data = hh_res.get_json()
            assert hh_data["success"] is True
            print(f"  [SUCCESS] Dashboard online. Loaded {hh_data['count']} households in active incident.")
            results["step1"] = {"success": True, "details": f"{hh_data['count']} households tracked"}
        except Exception as e:
            print(f"  [FAILED] Step 1: {e}")
            results["step1"] = {"success": False, "error": str(e)}

        # ------------------------------------------------------------------
        # STEP 2: Citizen Distress Intake Simulation (STT -> NLU -> State -> TTS)
        # ------------------------------------------------------------------
        print("\n--- STEP 2: Voice Intake Call Simulation (Gnani Prisma/Evon/Timbre) ---")
        sim_call_id = None
        target_hh_id = "hh-001"
        try:
            payload = {
                "household_id": target_hh_id,
                "language": "kannada",
                "caller_question": ""
            }
            res = client.post("/api/simulate-call", json=payload)
            assert res.status_code == 200, f"Status code {res.status_code}"
            data = res.get_json()
            assert data["success"] is True
            sim_call_id = data["call_id"]
            pipe = data["pipeline"]
            
            stt_lat = pipe["stt"]["latency_sec"]
            llm_lat = pipe["llm"]["latency_sec"]
            tts_lat = pipe["tts"]["latency_sec"]
            reply_text = pipe["guard_and_safety"]["final_reply_text"]
            new_status = pipe["status_engine"]["new_status"]
            
            assert "help is coming" not in reply_text.lower()
            assert "dispatched" not in reply_text.lower()
            assert new_status == "needs_help"

            safe_reply = reply_text.encode('ascii', 'replace').decode('ascii')
            print(f"  [SUCCESS] Call {sim_call_id} processed.")
            print(f"    - STT Model: {pipe['stt']['model']} (Latency: {stt_lat}s)")
            print(f"    - NLU Model: {pipe['llm']['model']} (Latency: {llm_lat}s)")
            print(f"    - State Mutation: {new_status}")
            print(f"    - Honesty Guard Reply: \"{safe_reply}\"")
            print(f"    - TTS Model: {pipe['tts']['model']} (Latency: {tts_lat}s)")
            results["step2"] = {"success": True, "call_id": sim_call_id, "status": new_status}
        except Exception as e:
            print(f"  [FAILED] Step 2: {e}")
            results["step2"] = {"success": False, "error": str(e)}

        # ------------------------------------------------------------------
        # STEP 3: Dispatcher Review & Asset Assignment Modal
        # ------------------------------------------------------------------
        print("\n--- STEP 3: Dispatcher Review & Asset Assignment ---")
        dispatched_offer_id = None
        target_veh_id = "veh-01" # Rescue Boat NDRF-1
        try:
            # 3a. Verify call detail page
            call_res = client.get(f"/call/{target_hh_id}")
            assert call_res.status_code == 200
            call_html = call_res.data.decode("utf-8")
            assert "assignVehicleModal" in call_html
            assert "Sudhakar" not in call_html # no invented roster
            assert "+91 XXXXX XXXXX" in call_html # phone masked

            # 3b. Dispatch vehicle assignment
            assign_res = client.post("/api/assign", json={
                "household_id": target_hh_id,
                "vehicle_id": target_veh_id,
                "dispatcher_name": "Duty officer"
            })
            assert assign_res.status_code == 200, f"Status code {assign_res.status_code}: {assign_res.data.decode()}"
            assign_data = assign_res.get_json()
            assert assign_data["success"] is True
            dispatched_offer_id = assign_data["offer_id"]
            dispatched_req_id = assign_data["request_id"]
            print(f"  [SUCCESS] Offer {dispatched_offer_id} created for request {dispatched_req_id} (Vehicle: {target_veh_id})")
            results["step3"] = {"success": True, "offer_id": dispatched_offer_id, "request_id": dispatched_req_id}
        except Exception as e:
            print(f"  [FAILED] Step 3: {e}")
            results["step3"] = {"success": False, "error": str(e)}

        # ------------------------------------------------------------------
        # STEP 4: Driver Feed & Offer Acceptance (Version-checked Transaction)
        # ------------------------------------------------------------------
        print("\n--- STEP 4: Driver Feed & Offer Acceptance ---")
        try:
            # Login as Driver (bound to veh-01)
            drv_login = client.post("/login", data={"role": "driver"})
            assert drv_login.status_code == 302

            # 4a. Check driver offers feed
            driver_res = client.get(f"/api/driver/offers?vehicle_id={target_veh_id}")
            assert driver_res.status_code == 200
            driver_data = driver_res.get_json()
            assert driver_data["success"] is True
            offers = driver_data["offers"]
            assert any(o["id"] == dispatched_offer_id for o in offers), f"Offer {dispatched_offer_id} not in driver offers"
            matching_offer = next(o for o in offers if o["id"] == dispatched_offer_id)
            assert matching_offer["expires_at"] is not None

            # 4b. Driver accepts offer
            accept_res = client.post(f"/api/driver/offers/{dispatched_offer_id}/accept")
            assert accept_res.status_code == 200, f"Status code {accept_res.status_code}: {accept_res.data.decode()}"
            accept_data = accept_res.get_json()
            assert accept_data["success"] is True
            assert accept_data["status"] == "driver_accepted"
            print(f"  [SUCCESS] Driver accepted offer {dispatched_offer_id}. Request mutated to 'driver_accepted'.")
            results["step4"] = {"success": True, "offer_id": dispatched_offer_id, "status": "driver_accepted"}
        except Exception as e:
            print(f"  [FAILED] Step 4: {e}")
            results["step4"] = {"success": False, "error": str(e)}

        # ------------------------------------------------------------------
        # STEP 5: Driver In-Transit & Citizen Pickup
        # ------------------------------------------------------------------
        print("\n--- STEP 5: Driver In-Transit & Citizen Pickup ---")
        try:
            req_id = results.get("step3", {}).get("request_id", "req-001")
            
            # 5a. Verify run page UI with Leaflet pickup map
            run_res = client.get(f"/run/{req_id}")
            assert run_res.status_code == 200
            run_html = run_res.data.decode("utf-8")
            assert "run-map" in run_html
            assert "Turn-by-turn Navigation to Shelter" not in run_html
            assert "GPS FIXED: 12.8714°N, 75.0321°E (Demo)" in run_html

            # 5b. Driver starts transit (on_run)
            status_res1 = client.post(f"/api/runs/{req_id}/start")
            assert status_res1.status_code == 200, f"Status code {status_res1.status_code}: {status_res1.data.decode()}"
            assert status_res1.get_json()["status"] == "on_run"

            # 5c. Driver confirms pickup (picked_up)
            status_res2 = client.post(f"/api/runs/{req_id}/picked-up")
            assert status_res2.status_code == 200, f"Status code {status_res2.status_code}: {status_res2.data.decode()}"
            assert status_res2.get_json()["status"] == "picked_up"
            print(f"  [SUCCESS] Request {req_id} progressed: driver_accepted -> on_run -> picked_up")
            results["step5"] = {"success": True, "request_id": req_id, "status": "picked_up"}
        except Exception as e:
            print(f"  [FAILED] Step 5: {e}")
            results["step5"] = {"success": False, "error": str(e)}

        # ------------------------------------------------------------------
        # STEP 6: Shelter Delivery & Evacuation Verification
        # ------------------------------------------------------------------
        print("\n--- STEP 6: Shelter Delivery & Evacuation Verification ---")
        try:
            req_id = results.get("step3", {}).get("request_id", "req-001")
            
            # 6a. Complete run upon arrival at relief shelter
            evac_res = client.post(f"/api/runs/{req_id}/complete")
            assert evac_res.status_code == 200, f"Status code {evac_res.status_code}: {evac_res.data.decode()}"
            evac_data = evac_res.get_json()
            assert evac_data["status"] == "evacuated"

            # 6b. Verify household status in database
            db = get_db()
            hh_row = db.execute("SELECT status FROM household WHERE id = ?", (target_hh_id,)).fetchone()
            assert hh_row["status"] == "evacuated"

            # 6c. Verify vehicle freed up
            veh_row = db.execute("SELECT status FROM vehicle WHERE id = ?", (target_veh_id,)).fetchone()
            assert veh_row["status"] == "available"

            # 6d. Verify immutable audit log
            audit_res = client.get("/api/audit")
            assert audit_res.status_code == 200
            logs = audit_res.get_json()["logs"]
            assert any(l.get("household_id") == target_hh_id for l in logs)

            print(f"  [SUCCESS] Household {target_hh_id} verified as 'evacuated' at shelter relief camp.")
            print(f"  [SUCCESS] Vehicle {target_veh_id} returned to 'available' pool.")
            print(f"  [SUCCESS] Audit trail logged state change.")
            results["step6"] = {"success": True, "household_id": target_hh_id, "status": "evacuated"}
        except Exception as e:
            print(f"  [FAILED] Step 6: {e}")
            results["step6"] = {"success": False, "error": str(e)}

    print("\n======================================================================")
    print("DEMO FLOW EXECUTION SUMMARY:")
    all_passed = True
    for step_num in range(1, 7):
        key = f"step{step_num}"
        res = results.get(key, {"success": False, "error": "Not executed"})
        if res["success"]:
            print(f"  Step {step_num}: PASSED")
        else:
            all_passed = False
            print(f"  Step {step_num}: FAILED ({res.get('error')})")
    print(f"OVERALL STATUS: {'ALL 6 STEPS PASSED WITHOUT ERRORS' if all_passed else 'SOME STEPS FAILED'}")
    print("======================================================================\n")
    return all_passed, results

if __name__ == "__main__":
    success, res = run_end_to_end_demo()
    if not success:
        sys.exit(1)
