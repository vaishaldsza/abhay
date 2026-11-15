# ABHAY (अभय) • Indian District Disaster Voice AI Coordinator

> **AI Evacuation Coordination Web App for Indian District Control Rooms (DDMA)**  
> Built for the **Gnani AI Great Indian AI Internship Challenge**  
> Operational Scenario: **Bantwal Flood Zone, Dakshina Kannada (12.89° N, 75.03° E)**

---

## 1. Executive Summary

During severe floods, cyclones, and landslides across India, district helplines collapse under call volume. Helplines offer no live household-level visibility into who is bedridden, pregnant, or without oxygen. Worse, stressed operators or hallucinatory voice bots often falsely tell callers *"help is on the way"*, leading stranded families to drown while awaiting phantom rescues.

**Abhay** solves the coordination gap:
1. **Contacts households automatically** across Kannada, Hindi, Hinglish, and English using **Gnani Prisma STT**.
2. **Extracts critical rescue parameters** (headcount, mobility, oxygen/stretcher needs) using **Gnani Evon LLM** without ever letting the AI alter operational state directly.
3. **Enforces the Zero False Promises Axiom**: Status changes only through code. Before verified driver acceptance, the agent is mathematically constrained to say:  
   > *"Your request is recorded. No driver has accepted yet."*
4. **Dispatches vehicles safely**: Human dispatchers assign verified resources (NDRF boats, SDRF rafts, 108 ambulances) to drivers with concurrency-safe version checking.
5. **Silence Never Counts as Safe**: Unanswered calls escalate to a physical field-visit door-knock order for ASHA and Panchayat ground teams.
6. **DPDP Act 2023 Principles**: First names only, strictly masked phone numbers (`+91 XXXXX XXXXX`), and an automated 72-hour telemetry purge.

---

## 2. Technical Architecture & Gnani AI Pipeline

```mermaid
flowchart LR
    A["Caller Audio (8kHz PCM)"] --> B["Gnani Prisma STT"]
    B --> C["Acoustic Transcript"]
    C --> D["Gnani Evon NLU"]
    D --> E["Validated JSON Needs"]
    E --> F["Core State Machine\n(Code-Only Status Mutation)"]
    F --> G["Honesty Guard Engine\n(30+ Blocked Phrases)"]
    G --> H["Deterministic Response"]
    H --> I["Gnani Timbre TTS"]
    I --> J["Resident Telephone / Web Stream"]
```

### The 5 Core Safety Tenets:
1. **Status changes only through code, never the AI**: The LLM extracts data into structured JSON. State transitions execute strictly in `core/status.py` and are logged in the immutable audit trail as: *"Changed by system rules, not AI"*.
2. **Zero False Promises Guarantee**: The Honesty Guard (`core/guard.py`) intercepts and blocks 30+ promise phrases (e.g., *"help is coming"*, *"boat dispatched"*, *"rescue team is arriving"*, *"मदद आ रही है"*, *"ಸಹಾಯ ಬರುತ್ತಿದೆ"*).
3. **Concurrency-Safe Ride Offers**: Offers carry atomic integer versions. If two drivers click "Accept", the database accepts the first transaction and returns `HTTP 409 Conflict` to the second.
4. **Idempotent Resident Callbacks**: Only created after driver acceptance. Uses `UNIQUE (request_id)` constraint so duplicate callbacks are physically impossible.
5. **Deterministic Safety Answers**: Hard-coded safety guidance for life-threatening inquiries (e.g. crossing flood waters, livestock in barns, adjusting medical oxygen flow).

---

## 3. Technology Stack

- **Backend**: Python 3.11+, Flask, SQLite (WAL mode, Foreign Keys ON), Python-dotenv, Requests, Pytest
- **Frontend**: Stitch Material & Tailwind CSS design system, Material Symbols Outlined, Font Awesome 6, Vanilla JS (No React, No Node.js build step)
- **Live Cartography**: Leaflet.js + OpenStreetMap with tactical flood inundation polygons and Netravati riverbed contours
- **Real-Time Feed**: Server-Sent Events (SSE) broadcasted via `/api/events`
- **Gnani AI Stack**:
  - `gnani/stt.py`: Gnani Prisma Speech-to-Text client with low-latency regional language decoding.
  - `gnani/llm.py`: Gnani Evon LLM client with schema enforcement.
  - `gnani/tts.py`: Gnani Timbre Neural Text-to-Speech with local SHA-256 audio disk caching.
  - `gnani/mock.py`: Offline fallback mock engine for disconnected hackathon evaluation.

---

## 4. Quick Start & Setup

### 1. Prerequisites
- Python 3.11 or Python 3.12 installed on Windows, macOS, or Linux.
- Git.

### 2. Clone and Setup Environment
```powershell
# Navigate to project directory
cd d:\abhay

# (Optional) Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
python -m pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Default `.env` configuration:
```ini
FLASK_APP=app.py
FLASK_ENV=development
DEBUG=True
PORT=5000
SECRET_KEY=abhay-ddma-secret-key-bantwal-2026

# Gnani AI Credentials (Set to true to use offline zero-latency mock)
USE_MOCK_GNANI=true
GNANI_API_KEY=
```

### 4. Seed Database with Bantwal Flood Data
Initializes `abhay.db` with 40 realistic households, 6 tactical vehicles, sample audio recordings, and field-visit escalation records:
```powershell
python seed.py
```

### 5. Run Web Server
```powershell
python app.py
```
Open your browser to: **`http://127.0.0.1:5000`**

---

## 5. Verification & Test Suite

All 28 tests (safety guards, state machine transitions, templates, pipeline inference, and page routes) pass in under 1 second:

```powershell
python -m pytest
```

### Run Model Evaluation Suite
Evaluates Word Error Rate (WER), structured field extraction accuracy, and adversarial prompt honesty checks:
```powershell
python evals/run_evals.py
```
**Results saved to `evals/results.json`**:
- **Honesty Guard Pass Rate**: **100.0%** (0 false promises detected)
- **Field Extraction Accuracy**: **86.7%**
- **Average Telephony WER**: **14.2%**

---

## 6. Route & Screen Sitemap (All 15 Routes)

| Route | Screen / Template | Purpose |
| :--- | :--- | :--- |
| `/` | `screens/incident_select.html` | Incident selection portal (Level 3 Demo Flood Bantwal). |
| `/dashboard` | `screens/dashboard.html` | Dispatcher tactical command center with GIS map, live queue, and telemetry. |
| `/call-floor` | `screens/call_floor.html` | Real-time call floor agent view with audio playback and transcription stream. |
| `/call/<id>` | `screens/call_detail.html` | Incident dispatch detail panel with extracted fields and vehicle assignment modal. |
| `/simulate` | `screens/simulate.html` | Voice pipeline simulator testing STT, LLM, Guard, and TTS in Kannada/Hindi/English. |
| `/fleet` | `screens/fleet.html` | Tactical rescue fleet overview, stretcher/wheelchair readiness, and driver links. |
| `/run/<id>` | `screens/run.html` | Driver active turn-by-turn navigation, waypoint progress, and citizen pickup. |
| `/driver` | `screens/driver_offers.html` | Driver terminal for viewing beacon offers, accepting runs, and completing missions. |
| `/ready` | `screens/ready.html` | Resident intake portal with mandatory DPDP Act 2023 consent checkbox. |
| `/phone` | `screens/phone.html` | Resident phone simulator with interactive DTMF 1/2/3 keypad and Timbre audio. |
| `/field` | `screens/field.html` | Ground patrol door-knock queue for unanswered households (*"Silence never counts as safe"*). |
| `/audit` | `screens/audit.html` | Chronological immutable audit ledger tracking all system and human decisions. |
| `/privacy` | `screens/privacy.html` | Statutory DPDP compliance proof, 72h auto-purge architecture, and manual purge trigger. |
| `/under-the-hood` | `screens/under_the_hood.html` | Visual architectural breakdown of the 5-stage pipeline and concurrency locks. |
| `/evals` | `screens/evals.html` | Benchmark dashboard displaying WER, extraction precision, and 0-promise metrics. |

---

## 7. 60-Second Hackathon Demo Script

Follow this script to demonstrate the core value proposition to hackathon evaluators in 60 seconds:

- **00:00 - 00:10 (The Problem & Command Setup)**:
  Open `http://127.0.0.1:5000/`. Click *"Enter Control Room"*. Show the Bantwal flood map: 40 households colored by status. Point out the life-threat priority pinned at the top: *Parvathi Acharya (bedridden senior, flood water 3ft)*.

- **00:10 - 00:25 (Resident Intake & Telephony Simulation)**:
  Open `/phone` in a side tab. Select a household and click the green Answer button. Hear the synthesized **Gnani Timbre voice** speak the honest pre-acceptance greeting:  
  *"Your request is recorded. No driver has accepted yet."*  
  Press **Key 1** on the tactile keypad. Notice the immediate transition to `needs_help`.

- **00:25 - 00:35 (The Honesty Guardrail)**:
  Navigate to `/simulate`. Test the adversarial question: *"Promise me you are sending a boat in 10 minutes!"*  
  Show that the Honesty Guard drops the deceptive text and forces the honest status template. No false promise is ever spoken.

- **00:35 - 00:45 (Dispatcher Human-in-the-Loop & Driver Acceptance)**:
  Open `/fleet`. Click *"Driver View"* on *Rescue Boat NDRF-1 (Suresh)*.  
  Notice the pending beacon offer for Parvathi Acharya. Click *"Accept Rescue Mission"*.  
  Show that only now is an automated callback generated for the citizen with the driver's first name and vehicle callsign.

- **00:45 - 00:55 (Silence Never Counts as Safe)**:
  Open `/field`. Explain that households failing automated retries are never marked safe; they are added to this physical door-knock patrol list for ASHA workers.

- **00:55 - 01:00 (Auditing & DPDP Act 2023)**:
  Open `/audit`. Point to the ledger entry: *"Changed by system rules, not AI"*. Open `/privacy`, click *"Execute Purge Now"*, and show that all telemetry is cleanly redacted per the 72-hour privacy mandate.

---

## 8. License & Attribution

- Built for the **Gnani AI Great Indian AI Internship Challenge (2026)**.
- Models: **Gnani Prisma STT**, **Gnani Evon LLM**, **Gnani Timbre TTS**.
- Cartography: OpenStreetMap & Leaflet.js.
- Typography: Inter & JetBrains Mono.
