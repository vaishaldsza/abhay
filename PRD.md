# PRD: Setu / Abhay - AI Evacuation Coordination for India

## 1. Overview
An AI voice and messaging platform that contacts every household in a disaster warning zone, identifies who needs help, and helps dispatchers route rescuers. Built for the Gnani AI Great Indian AI Internship Challenge using Prisma (STT), Timbre (TTS) and Evon (LLM).

## 2. Problem
During floods, cyclones and landslides, elderly, disabled, bedridden and poor residents cannot self-evacuate. Helplines are overwhelmed, there is no live household-level picture of who needs help, and callers are sometimes falsely told "help is on the way." The shortage is information and coordination, not vehicles.

## 3. Goals
- Identify vulnerable residents within minutes of a warning
- Support regional languages, Hinglish and noisy phone audio
- Never give false assurance of rescue
- Keep a human dispatcher in control

## 4. Non-Goals (for the hackathon)
Real telephony at scale, route optimization, traffic simulation, real payments, integration with live government systems.

## 5. Users
- **Dispatcher** (district control room): views map, approves plans
- **Resident**: receives the call or message
- **Driver/volunteer**: accepts or declines rides
- **Field coordinator** (ASHA, panchayat worker): runs the Ready check

## 6. User Stories
- As a dispatcher, I see every home colored by status (red needs help, orange can help, green evacuated, grey unreached).
- As a resident, I speak in my own language and the system understands my needs.
- As a dispatcher, I see emergencies flagged at the top of the list.
- As a driver, I accept a ride and the resident is informed only after acceptance.
- As a coordinator, I register vulnerable households before disasters, with consent.

## 7. Functional Requirements

**FR1: Voice intake.** Audio from a call (recorded for the demo) is transcribed by Prisma. Support Kannada, Hindi, Hinglish and English at minimum.

**FR2: Understanding.** Evon converts the transcript into structured fields: address or landmark, headcount, who cannot walk, medical needs, emergency flag, can-help-others flag. The system reads the summary back and lets the resident correct it.

**FR3: Status engine.** Each household has a status: unreached, needs help, can help, evacuated, ride requested, driver accepted. Status changes only through code, never through the LLM.

**FR4: Honesty guard.** Any sentence about rescue is chosen from fixed templates based on status. Before a driver accepts, the agent says "Your request is being sent. No driver has accepted yet." The LLM's free text is checked and dropped if it sounds like a promise.

**FR5: Voice output.** Timbre speaks the replies in the resident's language.

**FR6: Dispatcher dashboard.** Live map or grid with color-coded homes, transcript view, emergency queue, and a manual match button (dispatcher assigns a vehicle to a request).

**FR7: Driver view.** Simple page showing a ride offer with Accept and Decline. Acceptance triggers a callback message to the resident with driver name and ETA.

**FR8: Retry logic.** Unanswered homes are retried, then flagged for field visit.

**FR9: Safety handling.** Questions like "should I go back for my cattle" or "which road is open" get a fixed safe answer, never an invented one.

## 8. Non-Functional Requirements
- Median agent response under 2 seconds
- Works on noisy 8 kHz audio
- Consent and minimal retention aligned with DPDP Act 2023 (auto-delete after the incident window)
- Logs for audit

## 9. Architecture (MVP)
- **Frontend:** web app (plain HTML/Tailwind/vanilla JS with Leaflet maps)
- **Backend:** Python Flask API with SQLite & Server-Sent Events (SSE)
- **AI:** Gnani Prisma (STT), Evon (extraction), Timbre (TTS)
- **Logic layer:** status engine, template responder, honesty guard
- **Inputs:** recorded audio clips simulating calls; optional WhatsApp or web call simulator

## 10. Data Model
- **Household:** id, location (lat/lng, landmark), language, members, mobility needs, status
- **Call:** id, household id, transcript, extracted fields, timestamp
- **Request:** id, household id, needs, status, assigned vehicle
- **Vehicle:** id, type (boat, bus, ambulance, car), capacity, status

## 11. Evaluation Plan
- Transcription accuracy on Kannada, Hinglish and noisy audio samples
- Field extraction accuracy on 20 to 30 scripted calls
- Honesty test: callers pressure the agent ("a van is coming, right?"), measure how many replies imply a promise (target: zero)
- Report failures openly

## 12. Demo Plan (60 seconds)
1. Show the map with grey homes (5 s)
2. Play a Kannada or Hinglish call, show Prisma transcript and extracted fields (20 s)
3. Home turns red, emergency flagged (10 s)
4. Caller asks "is help coming?" and the agent answers honestly (10 s)
5. Dispatcher assigns a vehicle, driver accepts, home updates and caller gets a callback (15 s)

## 13. Hackathon Scope and Timeline
Submission deadline: November 15, 2026 (verify the form is still open).
- **Hours 1 to 3:** Gnani API setup, STT and TTS test
- **Hours 4 to 8:** Evon extraction, status engine, templates
- **Hours 9 to 13:** Dashboard, driver page
- **Hours 14 to 16:** Test calls, record demo, write post and explanation, publish on LinkedIn and X with #GnaniAI #GreatIndianAIInternshipChallenge

## 14. Success Metrics
- Extraction accuracy above 85% on test calls
- Zero implied promises in the honesty test
- Working end-to-end demo from call to driver acceptance

## 15. Risks
- Registration may be closed: check immediately
- Timbre is beta, so keep a fallback TTS
- Regional language accuracy may vary, so test early and pick the best-supported languages
- Tight timeline: cut the map to a simple grid if needed

## 16. Future Scope
Routing optimization, flood and cyclone forecast integration, WhatsApp and IVR, integration with 112 and SDMA, UPI reimbursement for volunteers, pilot with a district authority.
