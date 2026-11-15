import os
import wave
import struct
import math
import uuid
import random
from datetime import datetime, timedelta, timezone
from config import Config
from db import init_db, get_standalone_db, mask_phone, encrypt_phone, log_audit

def create_sample_wav(filepath: str, duration_sec: float = 2.0, freq: float = 440.0):
    """Generates a small valid WAV file for sample audio playback."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    sample_rate = 8000
    n_samples = int(sample_rate * duration_sec)
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1) # mono
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(sample_rate)
        for i in range(n_samples):
            # Gentle tone with decay
            value = int(10000.0 * math.sin(2.0 * math.pi * freq * (i / sample_rate)) * math.exp(-i / (sample_rate * 1.5)))
            data = struct.pack('<h', value)
            wav_file.writeframesraw(data)

def seed_database():
    print("Initializing database...")
    init_db()
    conn = get_standalone_db()
    cur = conn.cursor()

    # Clear existing data for fresh seed
    tables = ["field_visit", "callback", "audit_log", "offer", "request", "call", "member", "vehicle", "household", "incident"]
    for t in tables:
        cur.execute(f"DELETE FROM {t};")
    conn.commit()

    print("Creating sample audio clips...")
    static_audio_dir = Config.BASE_DIR / "static" / "audio"
    static_audio_dir.mkdir(parents=True, exist_ok=True)
    kannada_wav = str(static_audio_dir / "sample_kannada.wav")
    hindi_wav = str(static_audio_dir / "sample_hindi.wav")
    hinglish_wav = str(static_audio_dir / "sample_hinglish.wav")
    create_sample_wav(kannada_wav, 2.5, 330.0)
    create_sample_wav(hindi_wav, 2.5, 440.0)
    create_sample_wav(hinglish_wav, 2.5, 550.0)

    # 1. Incident
    incident_id = "inc-bantwal-01"
    cur.execute(
        """INSERT INTO incident (id, name, hazard, created_at)
           VALUES (?, ?, ?, ?)""",
        (incident_id, "Demo Flood, Bantwal", "flood", datetime.now(timezone.utc).isoformat())
    )

    # 2. Vehicles
    vehicles_data = [
        ("veh-01", "boat", "Rescue Boat NDRF-1", 6, 0, 0, "Suresh", "available", 12.8904, 75.0378),
        ("veh-02", "boat", "Rescue Boat SDRF-2", 8, 0, 0, "Praveen", "available", 12.8930, 75.0350),
        ("veh-03", "ambulance", "108 Ambulance Unit 4", 2, 1, 1, "Ramesh", "available", 12.8880, 75.0410),
        ("veh-04", "ambulance", "Red Cross Rapid Unit", 2, 1, 1, "Anil", "available", 12.8950, 75.0310),
        ("veh-05", "bus", "KSRTC Evac Bus B-12", 32, 0, 0, "Manjunath", "available", 12.8850, 75.0450),
        ("veh-06", "car", "District Jeep Bolero 7", 4, 0, 0, "Girish", "available", 12.8920, 75.0390),
    ]
    cur.executemany(
        """INSERT INTO vehicle (id, type, designation, capacity, stretcher, wheelchair, driver_name, status, lat, lng)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        vehicles_data
    )

    # 3. Households (~40 households around 12.89 N, 75.03 E)
    names = [
        "Devappa", "Ananya", "Fatima", "Ganapathi", "Prema", "Shridhar", "Rukmini", "Basavaraj",
        "Kamala", "Nagesh", "Sumitra", "Chetan", "Poornima", "Raghavendra", "Lakshmi", "Harish",
        "Bhavya", "Manjula", "Anand", "Yashodha", "Ravi", "Geetha", "Mohan", "Savitha",
        "Prashanth", "Deepa", "Santhosh", "Meenakshi", "Vinod", "Pushpa", "Prakash", "Roopa",
        "Jagadish", "Sunitha", "Dinesh", "Vani", "Chandrashekar", "Gowri", "Shashi", "Rekha"
    ]
    landmarks = [
        "Near Netravati Bridge Old Toll", "Behind Sri Venkataramana Temple", "Opposite Panemangalore Post Office",
        "Near Baddakatte Market Square", "Near Good Shepherd Church", "Adjacent to Government High School",
        "Beside Netravati River Ghat Road", "Near Kaikamba Cross", "Jakribettu Water Works Road",
        "Near BC Road Flyover Pillar 14", "Behind Taluk Office", "Near Shamboor Dam Viewpoint",
        "Near Melkar Junction Service Road", "Behind Anjuman Complex", "Near Modankap Chapel Cross",
        "Beside Polali Temple Arch", "Near Amtady Panchayat Road", "Near Aladka Water Tank",
        "Near Brahmarakootlu Toll Gate", "Near Thumbe Dam Pump House"
    ]

    # Predefined distribution of statuses across the 40 homes:
    # not_reached: 12
    # needs_help: 8
    # can_help: 4
    # request_recorded: 6
    # driver_accepted: 4
    # on_run: 2
    # picked_up: 2
    # evacuated: 2
    statuses_pool = (
        ["not_reached"] * 12 +
        ["needs_help"] * 8 +
        ["can_help"] * 4 +
        ["request_recorded"] * 6 +
        ["driver_accepted"] * 4 +
        ["on_run"] * 2 +
        ["picked_up"] * 2 +
        ["evacuated"] * 2
    )
    random.seed(42) # Deterministic seed for reproducible testing
    random.shuffle(statuses_pool)

    languages = ["kannada", "kannada", "kannada", "hindi", "english"]

    household_records = []
    member_records = []
    request_records = []
    offer_records = []
    callback_records = []
    call_records = []
    field_visit_records = []

    for i, name in enumerate(names):
        hh_id = f"hh-{i+1:03d}"
        status = statuses_pool[i]
        lang = random.choice(languages)
        # Lat/Lng perturbed around 12.890, 75.038 (+- 0.02)
        lat = round(12.8904 + random.uniform(-0.022, 0.022), 5)
        lng = round(75.0378 + random.uniform(-0.022, 0.022), 5)
        landmark = landmarks[i % len(landmarks)]
        pin = f"57421{random.randint(1, 9)}"
        members_count = random.randint(1, 6)
        phone_raw = f"988{random.randint(1000000, 9999999)}"
        phone_masked = mask_phone(phone_raw)
        phone_enc = encrypt_phone(phone_raw)

        household_records.append((
            hh_id, incident_id, name, phone_masked, phone_enc, landmark, pin,
            lat, lng, lang, members_count, status, 1, datetime.now(timezone.utc).isoformat()
        ))

        # Member details
        cannot_walk = 1 if (status in ["needs_help", "request_recorded", "driver_accepted"] and i % 3 == 0) else 0
        bedridden = 1 if (cannot_walk and i % 2 == 0) else 0
        wheelchair_type = "manual" if (cannot_walk and not bedridden) else ("none" if not bedridden else "stretcher_needed")
        elderly = 1 if (i % 4 == 0 or bedridden) else 0
        pregnant = 1 if (i % 7 == 0 and not elderly) else 0
        needs_medicine = 1 if (elderly or bedridden or i % 5 == 0) else 0
        sleeping_room = random.choice(["Ground floor front", "Ground floor rear", "First floor south", "First floor north"])

        member_records.append((
            f"mem-{i+1:03d}", hh_id, cannot_walk, wheelchair_type, bedridden, elderly,
            pregnant, needs_medicine, sleeping_room
        ))

        # If status is not not_reached, simulate a recorded call
        if status != "not_reached":
            sample_audio = kannada_wav if lang == "kannada" else (hindi_wav if lang == "hindi" else hinglish_wav)
            is_emergency = 1 if (cannot_walk or bedridden or status in ["driver_accepted", "on_run"]) else 0
            transcript_text = f"Hello control room, this is {name} near {landmark}. Water level is rising fast."
            extracted = f'{{"address_or_landmark": "{landmark}", "headcount": {members_count}, "cannot_walk": {cannot_walk}, "medical_needs": {needs_medicine}, "emergency": {is_emergency}, "can_help_others": 0, "language": "{lang}"}}'
            call_records.append((
                f"call-{i+1:03d}", hh_id, sample_audio, lang, transcript_text, extracted,
                is_emergency, 0, 18.5, datetime.now(timezone.utc).isoformat()
            ))

        # If status is one of the request statuses, create request / offer / callback
        if status in ["request_recorded", "driver_accepted", "on_run", "picked_up", "evacuated"]:
            req_id = f"req-{i+1:03d}"
            assigned_veh = None
            if status in ["driver_accepted", "on_run", "picked_up", "evacuated"]:
                assigned_veh = f"veh-0{((i % 6) + 1)}"

            needs_json = f'{{"members": {members_count}, "cannot_walk": {cannot_walk}, "bedridden": {bedridden}, "special_requirements": "Requires ground assistance"}}'
            request_records.append((
                req_id, hh_id, needs_json, status, assigned_veh, 1, datetime.now(timezone.utc).isoformat()
            ))

            if assigned_veh:
                offer_status = "accepted" if status in ["driver_accepted", "on_run", "picked_up", "evacuated"] else "pending"
                offer_records.append((
                    f"off-{i+1:03d}", req_id, assigned_veh, offer_status, 1, datetime.now(timezone.utc).isoformat()
                ))

                # Create idempotent callback
                driver_name = [v[6] for v in vehicles_data if v[0] == assigned_veh][0]
                veh_desig = [v[2] for v in vehicles_data if v[0] == assigned_veh][0]
                callback_records.append((
                    f"cb-{i+1:03d}", hh_id, req_id, driver_name, veh_desig, 12, "placed" if status in ["picked_up", "evacuated"] else "scheduled", datetime.now(timezone.utc).isoformat()
                ))

        # If unanswered and retry_count >= 3, add to field visit
        if status == "not_reached" and i < 4:
            field_visit_records.append((
                f"fv-{i+1:03d}", hh_id, "Officer Patil", "pending", "Unanswered after 3 calls and SMS alerts",
                "High water zone near river bank. In-person door knock required.", datetime.now(timezone.utc).isoformat()
            ))

    cur.executemany(
        """INSERT INTO household (id, incident_id, first_name, phone_masked, phone_enc, landmark, pin, lat, lng, language, members, status, consent_given, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        household_records
    )

    cur.executemany(
        """INSERT INTO member (id, household_id, cannot_walk, wheelchair_type, bedridden, elderly, pregnant, needs_medicine_oxygen, sleeping_room)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        member_records
    )

    cur.executemany(
        """INSERT INTO call (id, household_id, audio_path, language, transcript, extracted_json, emergency, retry_count, duration_seconds, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        call_records
    )

    cur.executemany(
        """INSERT INTO request (id, household_id, needs_json, status, vehicle_id, version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        request_records
    )

    cur.executemany(
        """INSERT INTO offer (id, request_id, vehicle_id, status, version, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        offer_records
    )

    cur.executemany(
        """INSERT INTO callback (id, household_id, request_id, driver_first_name, vehicle_designation, eta_minutes, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        callback_records
    )

    cur.executemany(
        """INSERT INTO field_visit (id, household_id, assigned_officer, status, reason, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        field_visit_records
    )

    conn.commit()

    # Initial audit logs
    log_audit("system", "system", "SYSTEM_INITIALIZED", None, "Database schema and seed initialized for Demo Flood, Bantwal", conn=conn)
    log_audit("dispatcher", "dispatcher", "INCIDENT_ACTIVATED", None, "Incident inc-bantwal-01 activated by District Control Room", conn=conn)

    conn.commit()
    conn.close()
    print("Database successfully seeded with 40 households, 6 vehicles, calls, requests, and offers.")

if __name__ == "__main__":
    seed_database()
