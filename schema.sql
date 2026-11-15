-- Abhay: AI Evacuation Coordination Web App Database Schema

CREATE TABLE IF NOT EXISTS incident (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hazard TEXT NOT NULL, -- flood | cyclone | landslide
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS household (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    first_name TEXT NOT NULL,
    phone_masked TEXT NOT NULL, -- e.g. +91 XXXXX XXXXX
    phone_enc TEXT NOT NULL,    -- encrypted or hashed phone
    landmark TEXT,
    pin TEXT,
    lat REAL,
    lng REAL,
    language TEXT DEFAULT 'kannada', -- kannada | hindi | english
    members INTEGER DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'not_reached', -- not_reached, needs_help, can_help, request_recorded, driver_accepted, on_run, picked_up, evacuated
    consent_given INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (incident_id) REFERENCES incident(id)
);

CREATE TABLE IF NOT EXISTS member (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    cannot_walk INTEGER DEFAULT 0,
    wheelchair_type TEXT DEFAULT 'none',
    bedridden INTEGER DEFAULT 0,
    elderly INTEGER DEFAULT 0,
    pregnant INTEGER DEFAULT 0,
    needs_medicine_oxygen INTEGER DEFAULT 0,
    sleeping_room TEXT,
    FOREIGN KEY (household_id) REFERENCES household(id)
);

CREATE TABLE IF NOT EXISTS call (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    audio_path TEXT,
    language TEXT DEFAULT 'kannada',
    transcript TEXT,
    extracted_json TEXT,
    emergency INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES household(id)
);

CREATE TABLE IF NOT EXISTS vehicle (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL, -- boat | bus | ambulance | car
    designation TEXT NOT NULL,
    capacity INTEGER DEFAULT 4,
    stretcher INTEGER DEFAULT 0,
    wheelchair INTEGER DEFAULT 0,
    driver_name TEXT NOT NULL, -- First name only
    status TEXT DEFAULT 'available', -- available | assigned | in_transit | off_duty
    lat REAL,
    lng REAL
);

CREATE TABLE IF NOT EXISTS request (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    needs_json TEXT,
    status TEXT NOT NULL DEFAULT 'request_recorded', -- request_recorded | driver_accepted | on_run | picked_up | evacuated
    vehicle_id TEXT,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES household(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicle(id)
);

CREATE TABLE IF NOT EXISTS offer (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending | accepted | declined | expired
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES request(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicle(id)
);

CREATE TABLE IF NOT EXISTS callback (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    driver_first_name TEXT NOT NULL,
    vehicle_designation TEXT NOT NULL,
    eta_minutes INTEGER DEFAULT 15,
    status TEXT DEFAULT 'scheduled', -- scheduled | placed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES household(id),
    FOREIGN KEY (request_id) REFERENCES request(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    actor_type TEXT NOT NULL, -- system | dispatcher | driver | resident
    action TEXT NOT NULL,
    household_id TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS field_visit (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    assigned_officer TEXT,
    status TEXT DEFAULT 'pending', -- pending | in_progress | resolved
    reason TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES household(id)
);

CREATE TABLE IF NOT EXISTS user (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'resident', -- dispatcher | driver | field_worker | resident
    full_name TEXT NOT NULL,
    phone TEXT,
    vehicle_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
