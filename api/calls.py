"""
Calls API & Simulation Pipeline
"""

import os
import uuid
import json
from flask import Blueprint, request, jsonify
from config import Config
from db import get_db, log_audit
from gnani.stt import transcribe
from gnani.llm import extract
from gnani.tts import speak
from core.status import update_household_status
from core.guard import sanitize_llm_reply
from core.templates import get_template
from core.safety_answers import get_safety_answer
from api.events import broadcast_event

calls_bp = Blueprint("calls", __name__)

@calls_bp.route("/api/calls", methods=["GET"])
def get_calls():
    db = get_db()
    rows = db.execute(
        """SELECT c.*, h.first_name, h.phone_masked, h.landmark, h.status as household_status
           FROM call c
           JOIN household h ON h.id = c.household_id
           ORDER BY c.created_at DESC"""
    ).fetchall()
    return jsonify({"success": True, "calls": [dict(r) for r in rows]})

@calls_bp.route("/api/simulate-call", methods=["POST"])
def simulate_call():
    """
    Executes the multi-stage AI pipeline:
    1. Audio (uploaded or pre-seeded sample) -> Gnani Prisma STT
    2. Transcript -> Gnani Evon LLM Information Extraction
    3. State Machine -> update household status (needs_help / can_help)
    4. Guard & Safety Engine -> determine honest reply
    5. Gnani Timbre TTS -> speech audio reply
    """
    data = request.form if request.form else (request.get_json() or {})
    household_id = data.get("household_id")
    language = data.get("language", "kannada")
    caller_question = data.get("caller_question", "") # e.g. "is help coming?" or dangerous question

    db = get_db()
    hh = db.execute("SELECT * FROM household WHERE id = ?", (household_id,)).fetchone() if household_id else None
    if not hh:
        # Default to first household in Bantwal if not specified
        hh = db.execute("SELECT * FROM household LIMIT 1").fetchone()
        household_id = hh["id"]

    # Handle audio input
    audio_file = request.files.get("audio")
    if audio_file:
        filename = f"upload_{uuid.uuid4().hex[:8]}.wav"
        save_path = os.path.join(Config.AUDIO_CACHE_DIR, filename)
        audio_file.save(save_path)
        audio_path = save_path
    else:
        # Use existing sample audio according to language
        audio_name = "sample_kannada.wav" if "kannada" in language.lower() else ("sample_hindi.wav" if "hindi" in language.lower() else "sample_hinglish.wav")
        audio_path = str(Config.BASE_DIR / "static" / "audio" / audio_name)

    # Stage 1: STT (Gnani Prisma)
    stt_res = transcribe(audio_path, lang=language)
    transcript = stt_res["text"]

    # Stage 2: Extraction (Gnani Evon)
    evon_res = extract(transcript)

    # Stage 3: Status Transition (Core State Engine)
    is_emergency = evon_res.get("emergency", 0)
    can_help = evon_res.get("can_help_others", 0)

    new_status = "can_help" if (can_help == 1 and not is_emergency) else "needs_help"
    
    current_status = hh["status"]
    # Update status if permitted by state machine
    try:
        update_household_status(
            household_id=household_id,
            new_status=new_status,
            actor="system_voice_agent",
            actor_type="system",
            detail=f"Automated call triage via Gnani AI: {new_status} (emergency={is_emergency})",
            conn=db
        )
    except Exception as e:
        # If transition is redundant or not allowed (e.g. already request_recorded), keep current
        new_status = current_status

    # Stage 4: Guard & Safety Check
    # Check if caller asked a dangerous question
    safety_answer, flagged = get_safety_answer(caller_question, language)
    
    template_reply = get_template(new_status, language)

    if safety_answer:
        final_reply = safety_answer
        reply_source = "Core Safety Answers (Vetted)"
    else:
        # Check LLM response with guard
        raw_llm_reply = f"Thank you for contacting Bantwal Control Room. {template_reply}"
        final_reply = sanitize_llm_reply(raw_llm_reply, new_status, template_reply)
        reply_source = "Guarded Template Engine"

    # Stage 5: TTS (Gnani Timbre)
    tts_res = speak(final_reply, lang=language)

    # Save call record in DB
    call_id = f"call-{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO call (id, household_id, audio_path, language, transcript, extracted_json, emergency, retry_count, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 15.2)""",
        (call_id, household_id, audio_path, language, transcript, json.dumps(evon_res), is_emergency)
    )
    db.commit()

    broadcast_event("call_processed", {
        "call_id": call_id,
        "household_id": household_id,
        "status": new_status,
        "emergency": is_emergency,
        "first_name": hh["first_name"]
    })

    return jsonify({
        "success": True,
        "call_id": call_id,
        "household_id": household_id,
        "first_name": hh["first_name"],
        "pipeline": {
            "stt": {
                "model": stt_res.get("model", "Gnani Prisma"),
                "transcript": transcript,
                "confidence": stt_res.get("confidence", 0.95),
                "latency_sec": stt_res.get("latency_sec", 0.12)
            },
            "llm": {
                "model": evon_res.get("model", "Gnani Evon"),
                "extracted": evon_res,
                "latency_sec": evon_res.get("latency_sec", 0.18)
            },
            "status_engine": {
                "previous_status": current_status,
                "new_status": new_status,
                "emergency_flag": is_emergency
            },
            "guard_and_safety": {
                "reply_source": reply_source,
                "flagged_for_human": flagged,
                "final_reply_text": final_reply
            },
            "tts": {
                "model": tts_res.get("model", "Gnani Timbre"),
                "audio_url": tts_res.get("audio_url"),
                "cached": tts_res.get("cached", False),
                "latency_sec": tts_res.get("latency_sec", 0.08)
            }
        }
    })

@calls_bp.route("/api/dtmf", methods=["POST"])
def handle_dtmf():
    """
    Fallback keypad option:
    Key 1: Needs immediate rescue -> needs_help
    Key 2: Safe / Can help others -> can_help
    Key 3: Repeat voice message
    """
    data = request.get_json() or {}
    household_id = data.get("household_id")
    key = str(data.get("key", "1"))

    db = get_db()
    hh = db.execute("SELECT * FROM household WHERE id = ?", (household_id,)).fetchone()
    if not hh:
        return jsonify({"success": False, "error": "Household not found"}), 404

    current_status = hh["status"]
    if key == "1":
        target_status = "needs_help"
        msg = "DTMF Key 1 received: Evacuation rescue requested"
    elif key == "2":
        target_status = "can_help"
        msg = "DTMF Key 2 received: Confirmed safe, can help others"
    elif key == "3":
        return jsonify({
            "success": True,
            "key": "3",
            "action": "REPEAT_PROMPT",
            "message": "Press 1 for evacuation rescue, Press 2 if you are safe, Press 3 to repeat."
        })
    else:
        return jsonify({"success": False, "error": "Invalid DTMF key. Valid keys: 1, 2, 3"}), 400

    try:
        update_household_status(household_id, target_status, "resident", "resident", msg, conn=db)
    except Exception as e:
        target_status = current_status

    broadcast_event("dtmf_received", {"household_id": household_id, "key": key, "status": target_status})

    return jsonify({
        "success": True,
        "household_id": household_id,
        "key": key,
        "status": target_status,
        "message": msg
    })

@calls_bp.route("/api/calls/apply-reviewed", methods=["POST"])
def apply_reviewed_data():
    data = request.get_json() or {}
    household_id = data.get("household_id")
    from core.status import update_household_status
    db = get_db()
    if not household_id:
        return jsonify({"success": False, "error": "household_id is required"}), 400

    update_household_status(household_id, "needs_help", "dispatcher", "dispatcher", "Dispatcher applied reviewed triage data to queue", conn=db)
    req = db.execute("SELECT id FROM request WHERE household_id = ? ORDER BY created_at DESC LIMIT 1", (household_id,)).fetchone()
    if not req:
        req_id = f"req-{uuid.uuid4().hex[:6]}"
        db.execute("INSERT INTO request (id, household_id, status, version) VALUES (?, ?, 'request_recorded', 1)", (req_id, household_id))

    db.commit()
    return jsonify({"success": True, "household_id": household_id, "status": "needs_help"})
