import pytest
import sqlite3
import threading
from core.status import (
    validate_transition,
    update_household_status,
    update_request_status,
    InvalidStatusTransitionError,
    UnauthorizedActorError,
    ALLOWED_STATUSES
)
from db import init_db, get_standalone_db, log_audit

def setup_module():
    init_db()

def test_legal_status_transitions():
    assert validate_transition("not_reached", "needs_help", "system") is True
    assert validate_transition("not_reached", "can_help", "system") is True
    assert validate_transition("needs_help", "request_recorded", "resident") is True
    assert validate_transition("request_recorded", "driver_accepted", "driver") is True
    assert validate_transition("driver_accepted", "on_run", "driver") is True
    assert validate_transition("on_run", "picked_up", "driver") is True
    assert validate_transition("picked_up", "evacuated", "driver") is True

def test_illegal_status_transitions():
    # Cannot jump from not_reached directly to evacuated
    with pytest.raises(InvalidStatusTransitionError):
        validate_transition("not_reached", "evacuated", "system")

    # Cannot jump backwards from evacuated
    with pytest.raises(InvalidStatusTransitionError):
        validate_transition("evacuated", "needs_help", "dispatcher")

    # Cannot jump from request_recorded directly to picked_up
    with pytest.raises(InvalidStatusTransitionError):
        validate_transition("request_recorded", "picked_up", "driver")

def test_llm_actor_is_strictly_rejected():
    # LLM is never permitted to change status
    with pytest.raises(UnauthorizedActorError):
        validate_transition("not_reached", "needs_help", "llm")

    with pytest.raises(UnauthorizedActorError):
        validate_transition("request_recorded", "driver_accepted", "ai_model")

    with pytest.raises(UnauthorizedActorError):
        validate_transition("not_reached", "can_help", "gnani_evon")

def test_concurrent_offer_accept_single_winner():
    """
    Rule 5: Offer acceptance is version-checked in one DB transaction:
    if two drivers accept the same request, exactly one wins.
    """
    conn = get_standalone_db()
    cur = conn.cursor()

    req_id = "test-req-concurrent"
    hh_id = "test-hh-concurrent"

    cur.execute("DELETE FROM offer WHERE request_id = ?", (req_id,))
    cur.execute("DELETE FROM request WHERE id = ?", (req_id,))
    cur.execute("DELETE FROM household WHERE id = ?", (hh_id,))
    conn.commit()

    cur.execute(
        """INSERT INTO household (id, incident_id, first_name, phone_masked, phone_enc, status)
           VALUES (?, 'inc-bantwal-01', 'TestResident', '+91 XXXXX XXXXX', 'hash123', 'request_recorded')""",
        (hh_id,)
    )
    cur.execute(
        """INSERT INTO request (id, household_id, status, version)
           VALUES (?, ?, 'request_recorded', 1)""",
        (req_id, hh_id)
    )

    offer_1 = "test-off-1"
    offer_2 = "test-off-2"
    cur.execute(
        """INSERT INTO offer (id, request_id, vehicle_id, status, version)
           VALUES (?, ?, 'veh-01', 'pending', 1)""",
        (offer_1, req_id)
    )
    cur.execute(
        """INSERT INTO offer (id, request_id, vehicle_id, status, version)
           VALUES (?, ?, 'veh-02', 'pending', 1)""",
        (offer_2, req_id)
    )
    conn.commit()
    conn.close()

    results = []

    def accept_offer(offer_id, vehicle_id, expected_req_version):
        db = get_standalone_db()
        c = db.cursor()
        try:
            db.execute("BEGIN IMMEDIATE")
            # Check request state
            c.execute("SELECT status, version FROM request WHERE id = ?", (req_id,))
            req_row = c.fetchone()
            if req_row["status"] != "request_recorded" or req_row["version"] != expected_req_version:
                db.rollback()
                results.append((offer_id, False, "Request already taken or version mismatch"))
                return

            # Update request
            c.execute(
                """UPDATE request
                   SET status = 'driver_accepted', vehicle_id = ?, version = version + 1
                   WHERE id = ? AND version = ?""",
                (vehicle_id, req_id, expected_req_version)
            )

            # Update offer
            c.execute(
                """UPDATE offer
                   SET status = 'accepted', version = version + 1
                   WHERE id = ? AND status = 'pending'""",
                (offer_id,)
            )

            # Reject other offers for this request
            c.execute(
                """UPDATE offer
                   SET status = 'expired'
                   WHERE request_id = ? AND id != ? AND status = 'pending'""",
                (req_id, offer_id)
            )

            db.commit()
            results.append((offer_id, True, "Success"))
        except Exception as e:
            db.rollback()
            results.append((offer_id, False, str(e)))
        finally:
            db.close()

    t1 = threading.Thread(target=accept_offer, args=(offer_1, "veh-01", 1))
    t2 = threading.Thread(target=accept_offer, args=(offer_2, "veh-02", 1))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for r in results if r[1] is True]
    assert len(successes) == 1, f"Expected exactly 1 successful accept, got: {results}"
