"""
Evals API Endpoint
Serves benchmark results and triggers new evaluation runs.
"""

import json
from pathlib import Path
from flask import Blueprint, jsonify
from config import Config

evals_bp = Blueprint("evals", __name__)

@evals_bp.route("/api/evals", methods=["GET"])
def get_evals():
    results_path = Config.BASE_DIR / "evals" / "results.json"
    if not results_path.exists():
        from evals.run_evals import run_evaluations
        summary = run_evaluations()
        return jsonify({"success": True, "summary": summary})

    with open(results_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    return jsonify({"success": True, "summary": summary})

@evals_bp.route("/api/evals/run", methods=["POST"])
def trigger_evals():
    from evals.run_evals import run_evaluations
    summary = run_evaluations()
    return jsonify({"success": True, "summary": summary})
