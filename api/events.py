"""
Server-Sent Events (SSE) Bus for Live Dashboard Updates
"""

import json
import queue
import time
from flask import Blueprint, Response, current_app

events_bp = Blueprint("events", __name__)

# Global list of subscriber queues
_subscribers = []

def broadcast_event(event_type: str, data: dict):
    """Pushes an event to all connected SSE clients."""
    payload = json.dumps({"event": event_type, "data": data, "timestamp": time.time()})
    dead_queues = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except queue.Full:
            dead_queues.append(q)
    for dq in dead_queues:
        if dq in _subscribers:
            _subscribers.remove(dq)

@events_bp.route("/api/events")
def sse_stream():
    client_queue = queue.Queue(maxsize=50)
    _subscribers.append(client_queue)

    def gen():
        try:
            # Send initial keepalive
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"
            while True:
                try:
                    data = client_queue.get(timeout=20.0)
                    yield f"event: update\ndata: {data}\n\n"
                except queue.Empty:
                    # Keepalive heartbeat
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            if client_queue in _subscribers:
                _subscribers.remove(client_queue)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
