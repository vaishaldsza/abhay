"""
Core Status Transition Engine for Abhay
Enforces strict state machine rules and mandatory audit logging.
The LLM is NEVER permitted to write status.
"""

from db import get_db, get_standalone_db, log_audit

ALLOWED_STATUSES = {
    "not_reached",
    "needs_help",
    "can_help",
    "request_recorded",
    "driver_accepted",
    "on_run",
    "picked_up",
    "evacuated"
}

STATUS_LABELS = {
    "not_reached": "Not reached",
    "needs_help": "Needs help",
    "can_help": "Can help",
    "request_recorded": "Request recorded, no driver accepted yet",
    "driver_accepted": "Driver accepted",
    "on_run": "On run",
    "picked_up": "Picked up",
    "evacuated": "Evacuated"
}

# Legal transition graph: key -> set of valid next states
ALLOWED_TRANSITIONS = {
    "not_reached": {"needs_help", "can_help", "not_reached"},
    "needs_help": {"request_recorded", "can_help"},
    "can_help": {"needs_help", "can_help"},
    "request_recorded": {"driver_accepted", "needs_help"},
    "driver_accepted": {"on_run", "request_recorded"}, # request_recorded if driver drops
    "on_run": {"picked_up", "driver_accepted"},
    "picked_up": {"evacuated"},
    "evacuated": set() # Terminal state
}

ALLOWED_ACTOR_TYPES = {"system", "dispatcher", "driver", "resident"}

class InvalidStatusTransitionError(ValueError):
    """Raised when an illegal status change is attempted."""
    pass

class UnauthorizedActorError(ValueError):
    """Raised when an unauthorized actor (such as an LLM) tries to mutate status."""
    pass

def validate_transition(current_status: str, new_status: str, actor_type: str) -> bool:
    """Validates whether a transition from current_status to new_status is permitted for actor_type."""
    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise UnauthorizedActorError(
            f"Actor type '{actor_type}' is unauthorized. Only {ALLOWED_ACTOR_TYPES} may change status. LLM is never permitted."
        )

    if new_status not in ALLOWED_STATUSES:
        raise InvalidStatusTransitionError(f"Unknown target status: '{new_status}'")

    if current_status not in ALLOWED_STATUSES:
        raise InvalidStatusTransitionError(f"Unknown current status: '{current_status}'")

    # If staying in the same status, allowed only for 'not_reached' (e.g. retry) or 'can_help'
    if current_status == new_status:
        if current_status in {"not_reached", "can_help"}:
            return True
        return False

    valid_targets = ALLOWED_TRANSITIONS.get(current_status, set())
    if new_status not in valid_targets:
        raise InvalidStatusTransitionError(
            f"Illegal transition: '{current_status}' -> '{new_status}'. Allowed from '{current_status}': {valid_targets}"
        )

    return True

def update_household_status(household_id: str, new_status: str, actor: str, actor_type: str, detail: str = None, conn=None):
    """
    Updates household status in the database with strict validation and audit logging.
    """
    validate_transition_allowed = False
    close_after = False
    if conn is None:
        try:
            conn = get_db()
        except RuntimeError:
            conn = get_standalone_db()
            close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM household WHERE id = ?", (household_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Household '{household_id}' not found.")
        
        current_status = row["status"]
        validate_transition(current_status, new_status, actor_type)

        cur.execute(
            """UPDATE household
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_status, household_id)
        )

        audit_msg = detail or f"Household status transitioned from '{current_status}' to '{new_status}'"
        log_audit(
            actor=actor,
            actor_type=actor_type,
            action="STATUS_CHANGED",
            household_id=household_id,
            detail=audit_msg,
            conn=conn
        )
        if close_after:
            conn.commit()
    finally:
        if close_after:
            conn.close()

def update_request_status(request_id: str, new_status: str, actor: str, actor_type: str, vehicle_id: str = None, detail: str = None, conn=None):
    """
    Updates request status and synchronized household status in the database.
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
        cur.execute("SELECT household_id, status FROM request WHERE id = ?", (request_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Request '{request_id}' not found.")

        current_status = row["status"]
        household_id = row["household_id"]

        validate_transition(current_status, new_status, actor_type)

        if vehicle_id:
            cur.execute(
                """UPDATE request
                   SET status = ?, vehicle_id = ?, version = version + 1
                   WHERE id = ?""",
                (new_status, vehicle_id, request_id)
            )
        else:
            cur.execute(
                """UPDATE request
                   SET status = ?, version = version + 1
                   WHERE id = ?""",
                (new_status, request_id)
            )

        # Synchronize household status
        cur.execute(
            """UPDATE household
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_status, household_id)
        )

        audit_msg = detail or f"Request '{request_id}' transitioned from '{current_status}' to '{new_status}' (vehicle: {vehicle_id or 'none'})"
        log_audit(
            actor=actor,
            actor_type=actor_type,
            action="REQUEST_STATUS_CHANGED",
            household_id=household_id,
            detail=audit_msg,
            conn=conn
        )

        if close_after:
            conn.commit()
    finally:
        if close_after:
            conn.close()
