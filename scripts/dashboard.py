#!/usr/bin/env python3
"""Aipply Dashboard — serves the application tracker and artifacts."""

import os
import sys
from pathlib import Path
from flask import Flask, send_from_directory, render_template_string, jsonify
import json

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = Flask(__name__, static_folder=str(PROJECT_ROOT))

TRACKER_PATH = PROJECT_ROOT / "output" / "tracker.json"
REPORT_TEMPLATE = PROJECT_ROOT / "output" / "reports" / "applications_report.html"


@app.route("/")
def index():
    """Serve the dashboard."""
    if REPORT_TEMPLATE.exists():
        return send_from_directory(str(REPORT_TEMPLATE.parent), REPORT_TEMPLATE.name)
    return "<h1>No report generated yet. Run a scan cycle first.</h1>", 404


@app.route("/download/<path:filepath>")
def download_file(filepath):
    """Download any artifact file."""
    full_path = PROJECT_ROOT / filepath
    if full_path.exists() and full_path.is_file():
        return send_from_directory(str(full_path.parent), full_path.name, as_attachment=True)
    return "File not found", 404


@app.route("/view/<path:filepath>")
def view_file(filepath):
    """View text files inline."""
    full_path = PROJECT_ROOT / filepath
    if full_path.exists() and full_path.suffix == ".txt":
        content = full_path.read_text()
        return render_template_string("""
<!DOCTYPE html>
<html><head><title>{{ title }}</title>
<style>
body { font-family: -apple-system, system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; color: #1a1a2e; }
pre { background: #f5f5f5; padding: 1.5rem; border-radius: 8px; white-space: pre-wrap; line-height: 1.6; }
a { color: #1565c0; }
</style></head>
<body><h1>📝 {{ title }}</h1><a href="/">← Back to Dashboard</a><pre>{{ content }}</pre></body></html>
""", title=full_path.name, content=content)
    return "File not found", 404


@app.route("/api/stats")
def api_stats():
    """JSON endpoint for stats."""
    if TRACKER_PATH.exists():
        apps = json.loads(TRACKER_PATH.read_text())
        return jsonify({"total": len(apps), "applications": apps})
    return jsonify({"total": 0, "applications": []})


if __name__ == "__main__":
    print(f"🚀 Aipply Dashboard: http://localhost:{PORT}")
    print(f"   Press Ctrl+C to stop")
    app.run(host="0.0.0.0", port=PORT, debug=False)
