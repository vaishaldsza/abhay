"""
Core Retry Logic for Unanswered Households
Rule: "Unanswered household retried at 2 and 5 minutes, then SMS (simulated),
then added to the field-visit list. Silence never counts as safe."
"""

import uuid
from datetime import datetime, timedelta
from db import get_db, get_standalone_db, log_audit

def process_unanswered_attempt(household_id: str, conn=None) -> dict:
    """
    Evaluates retry count for an unanswered household.
    Applies escalation ladder:
    Attempt 1 -> Schedule retry in 2 mins
    Attempt 2 -> Schedule retry in 5 mins
    Attempt 3 -> Send simulated SMS alert
    Attempt 4+ -> Escalate to physical field-visit door knock
    """
    close_after = False
    if conn is None:
        try:
            conn = get_db()
        except RuntimeError:
            conn = get_standalone_db()
            close_after = True

    try:
        cur = conn.cursor()
        # Find current attempts
        cur.execute(
            """SELECT COUNT(*) as attempts
               FROM call
               WHERE household_id = ?""",
            (household_id,)
        )
        row = cur.fetchone()
        attempts = row["attempts"] if row else 0

        # Record this failed attempt as a call
        call_id = f"call-{uuid.uuid4().hex[:8]}"
        cur.execute(
            """INSERT INTO call (id, household_id, language, transcript, emergency, retry_count, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (call_id, household_id, "kannada", "[NO_ANSWER - UNREACHABLE]", 0, attempts + 1, 0.0)
        )

        escalation_result = {
            "household_id": household_id,
            "attempt_number": attempts + 1,
            "action": None,
            "detail": None
        }

        if attempts == 0:
            action = "SCHEDULE_RETRY_2M"
            detail = "No answer. Call scheduled for retry in 2 minutes."
            log_audit("system", "system", action, household_id, detail, conn=conn)
            escalation_result.update({"action": action, "detail": detail, "next_retry_minutes": 2})

        elif attempts == 1:
            action = "SCHEDULE_RETRY_5M"
            detail = "No answer on 2nd attempt. Call scheduled for retry in 5 minutes."
            log_audit("system", "system", action, household_id, detail, conn=conn)
            escalation_result.update({"action": action, "detail": detail, "next_retry_minutes": 5})

        elif attempts == 2:
            action = "SMS_DISPATCHED_SIMULATED"
            detail = "Simulated SMS sent: 'EMERGENCY ALERT: Bantwal Control Room attempted contact. If you need rescue, call 112/1077.'"
            log_audit("system", "system", action, household_id, detail, conn=conn)
            escalation_result.update({"action": action, "detail": detail, "sms_sent": True})

        else:
            # 3 or more attempts failed: Add to field visit list
            action = "FIELD_VISIT_ESCALATION"
            detail = "Silence never counts as safe. Added to urgent Field Visit patrol list."
            
            # Check if already in field visit list
            cur.execute("SELECT id FROM field_visit WHERE household_id = ?", (household_id,))
            fv_row = cur.fetchone()
            if not fv_row:
                fv_id = f"fv-{uuid.uuid4().hex[:8]}"
                cur.execute(
                    """INSERT INTO field_visit (id, household_id, assigned_officer, status, reason, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (fv_id, household_id, "Patrol Squad 1", "pending", "Unanswered after 3 calls and SMS alerts", "Silence never counts as safe. Immediate in-person check required.")
                )

            log_audit("system", "system", action, household_id, detail, conn=conn)
            escalation_result.update({"action": action, "detail": detail, "field_visit_created": True})

        if close_after:
            conn.commit()

        return escalation_result
    finally:
        if close_after:
            conn.close()
