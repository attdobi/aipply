#!/usr/bin/env python3
"""Aipply Dashboard — live job application tracker with docx preview."""

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, render_template_string, request, send_file

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8092
ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / "output" / "tracker.json"

app = Flask(__name__)

STOP_FILE = ROOT / ".stop"

# Cycle state (thread-safe)
_cycle_lock = threading.Lock()
_cycle_state = {
    "running": False,
    "cycle_id": None,
    "total": 0,
    "processed": 0,
    "last_cycle": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "materials_ready": ("#1565c0", "#e3f2fd", "Materials Ready"),
    "applied": ("#2e7d32", "#e8f5e9", "Applied"),
    "rejected": ("#c62828", "#ffebee", "Rejected"),
    "interview": ("#f9a825", "#fff8e1", "Interview"),
    "manual_needed": ("#e65100", "#fff3e0", "Manual Needed"),
    "apply_failed": ("#c62828", "#ffebee", "Apply Failed"),
}


def _load_tracker():
    """Load tracker.json, return list of application dicts."""
    if not TRACKER.exists():
        return []
    with open(TRACKER) as f:
        data = json.load(f)
    return sorted(data, key=lambda x: x.get("applied_at", ""), reverse=True)


def _make_relative(abs_path: str) -> str:
    """Convert absolute path to relative from ROOT."""
    if not abs_path:
        return ""
    try:
        return str(Path(abs_path).relative_to(ROOT))
    except ValueError:
        return abs_path


def _format_date(iso_str: str) -> str:
    """Format ISO date string to 'Mar 24, 2026'."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return iso_str


def _is_today(iso_str: str) -> bool:
    try:
        return datetime.fromisoformat(iso_str).date() == datetime.now().date()
    except (ValueError, TypeError):
        return False


def _is_this_week(iso_str: str) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str).date()
        return dt >= (datetime.now().date() - timedelta(days=7))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Aipply Dashboard</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f0f2f5;
  color: #1a1a2e;
  min-height: 100vh;
}
/* Header */
.header {
  background: #1a1a2e;
  color: #fff;
  padding: 1.5rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -.02em; }
.header .subtitle { opacity: .7; font-size: .85rem; }

/* Stats cards */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  padding: 1.5rem 2rem;
  max-width: 1400px;
  margin: 0 auto;
}
.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
}
.stat-card .label { font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: #666; margin-bottom: .35rem; }
.stat-card .value { font-size: 2rem; font-weight: 700; }
.stat-card .value.blue   { color: #1565c0; }
.stat-card .value.green  { color: #2e7d32; }
.stat-card .value.red    { color: #c62828; }
.stat-card .value.gold   { color: #f9a825; }

/* Table container */
.table-wrap {
  padding: 0 2rem 2rem;
  max-width: 1400px;
  margin: 0 auto;
}
.table-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
thead { background: #1a1a2e; color: #fff; }
th { padding: .85rem 1rem; text-align: left; font-weight: 600; font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }
td { padding: .75rem 1rem; border-bottom: 1px solid #eee; font-size: .9rem; vertical-align: middle; }
tr:hover td { background: #f8f9fa; }
tr:last-child td { border-bottom: none; }

/* Status badge */
.badge {
  display: inline-block;
  padding: .25rem .75rem;
  border-radius: 20px;
  font-size: .78rem;
  font-weight: 600;
  white-space: nowrap;
}

/* Actions */
.actions { display: flex; gap: .5rem; flex-wrap: wrap; }
.actions a, .actions button {
  display: inline-flex; align-items: center; gap: .2rem;
  padding: .3rem .55rem;
  border-radius: 6px;
  font-size: .78rem;
  text-decoration: none;
  color: #1565c0;
  background: #e3f2fd;
  border: none;
  cursor: pointer;
  transition: background .15s;
}
.actions a:hover, .actions button:hover { background: #bbdefb; }
.actions .dl { color: #2e7d32; background: #e8f5e9; }
.actions .dl:hover { background: #c8e6c9; }
.actions .ext { color: #6a1b9a; background: #f3e5f5; }
.actions .ext:hover { background: #e1bee7; }

/* Modal */
.modal-backdrop {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,.5);
  z-index: 1000;
  justify-content: center;
  align-items: center;
}
.modal-backdrop.open { display: flex; }
.modal {
  background: #fff;
  border-radius: 12px;
  max-width: 800px;
  width: 90%;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,.25);
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  background: #1a1a2e;
  color: #fff;
  border-radius: 12px 12px 0 0;
  font-weight: 600;
}
.modal-header .close-btn {
  background: none; border: none; color: #fff; font-size: 1.5rem; cursor: pointer; line-height: 1;
}
.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
  line-height: 1.7;
}
.modal-body h1, .modal-body h2, .modal-body h3 { margin: 1rem 0 .5rem; color: #1a1a2e; }
.modal-body p { margin-bottom: .75rem; }
.modal-body ul { margin: .5rem 0 .75rem 1.5rem; }
.modal-body li { margin-bottom: .25rem; }

/* Empty state */
.empty { text-align: center; padding: 3rem; color: #888; font-size: 1.1rem; }

/* Controls */
.controls { background: #fff; border-bottom: 1px solid #e0e0e0; padding: .75rem 2rem; }
.controls-inner { max-width: 1400px; margin: 0 auto; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.ctrl-btn { display: inline-flex; align-items: center; gap: .4rem; padding: .6rem 1.2rem; border: none; border-radius: 8px; font-size: .9rem; font-weight: 600; cursor: pointer; transition: all .15s; }
.ctrl-btn:disabled { opacity: .45; cursor: not-allowed; }
.ctrl-btn.green { background: #2e7d32; color: #fff; }
.ctrl-btn.green:hover:not(:disabled) { background: #1b5e20; }
.ctrl-btn.red { background: #c62828; color: #fff; }
.ctrl-btn.red:hover:not(:disabled) { background: #b71c1c; }
.ctrl-btn.resume { background: #1565c0; color: #fff; }
.ctrl-btn.resume:hover:not(:disabled) { background: #0d47a1; }
.status-indicator { margin-left: auto; font-weight: 600; font-size: .95rem; }

/* Responsive */
@media (max-width: 768px) {
  .header { padding: 1rem; }
  .stats { padding: 1rem; }
  .table-wrap { padding: 0 1rem 1rem; }
  .controls { padding: .75rem 1rem; }
  th, td { padding: .5rem; font-size: .8rem; }
}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📋 Aipply Dashboard</h1>
    <div class="subtitle">Job Application Tracker</div>
  </div>
  <div class="subtitle">Last refresh: {{ now }}</div>
</div>

<!-- Controls -->
<div class="controls" id="controlsBar">
  <div class="controls-inner">
    <button class="ctrl-btn green" id="btnStartCycle" onclick="startCycle()">🚀 Start Cycle (5 jobs)</button>
    <button class="ctrl-btn red" id="btnStop" onclick="stopCycle()">🛑 Stop</button>
    <button class="ctrl-btn resume" id="btnResume" onclick="resumeOps()" style="display:none">▶️ Resume</button>
    <span class="status-indicator" id="statusIndicator">🟢 Idle</span>
  </div>
</div>

<div class="stats">
  <div class="stat-card">
    <div class="label">Total Applications</div>
    <div class="value">{{ total }}</div>
  </div>
  {% for status_key, info in status_counts.items() %}
  <div class="stat-card">
    <div class="label">{{ info.label }}</div>
    <div class="value {{ info.css }}">{{ info.count }}</div>
  </div>
  {% endfor %}
  <div class="stat-card">
    <div class="label">Today</div>
    <div class="value">{{ today_count }}</div>
  </div>
  <div class="stat-card">
    <div class="label">This Week</div>
    <div class="value">{{ week_count }}</div>
  </div>
</div>

<div class="table-wrap">
  <div class="table-card">
  {% if apps %}
    <table>
      <thead>
        <tr>
          <th>Company</th>
          <th>Position</th>
          <th>Location</th>
          <th>Status</th>
          <th>Date Applied</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
      {% for a in apps %}
        <tr>
          <td><strong>{{ a.company }}</strong></td>
          <td>{{ a.position }}</td>
          <td>{{ a.location }}</td>
          <td><span class="badge" style="background:{{ a.badge_bg }};color:{{ a.badge_fg }}">{{ a.badge_label }}</span></td>
          <td>{{ a.date_fmt }}</td>
          <td>
            <div class="actions">
              {% if a.resume_rel %}
              <button onclick="previewDoc('{{ a.resume_rel }}')">📄 Resume</button>
              <a class="dl" href="/download/{{ a.resume_rel }}">⬇️</a>
              {% endif %}
              {% if a.cover_letter_rel %}
              <button onclick="previewDoc('{{ a.cover_letter_rel }}')">✉️ Cover Letter</button>
              <a class="dl" href="/download/{{ a.cover_letter_rel }}">⬇️</a>
              {% endif %}
              {% if a.jd_rel %}
              <a href="/view/{{ a.jd_rel }}">📝 JD</a>
              {% endif %}
              {% if a.job_url %}
              <a class="ext" href="{{ a.job_url }}" target="_blank" rel="noopener">🔗 Job Post</a>
              {% endif %}
            </div>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  {% else %}
    <div class="empty">No applications tracked yet. Run the pipeline to get started!</div>
  {% endif %}
  </div>
</div>

<!-- Preview Modal -->
<div class="modal-backdrop" id="previewModal">
  <div class="modal">
    <div class="modal-header">
      <span id="modalTitle">Document Preview</span>
      <button class="close-btn" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body" id="modalBody">
      <p>Loading…</p>
    </div>
  </div>
</div>

<script>
function previewDoc(relPath) {
  const modal = document.getElementById('previewModal');
  const body  = document.getElementById('modalBody');
  const title = document.getElementById('modalTitle');

  body.innerHTML = '<p style="text-align:center;padding:2rem;color:#888">Loading preview…</p>';
  title.textContent = relPath.split('/').pop();
  modal.classList.add('open');

  fetch('/preview/' + relPath)
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(data => {
      title.textContent = data.filename || relPath.split('/').pop();
      body.innerHTML = data.html;
    })
    .catch(err => {
      body.innerHTML = '<p style="color:#c62828;text-align:center">Failed to load preview: ' + err.message + '</p>';
    });
}

function closeModal() {
  document.getElementById('previewModal').classList.remove('open');
}

// Close on backdrop click
document.getElementById('previewModal').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

// Close on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeModal();
});

// --- Controls ---
function refreshStatus() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      const btnStart = document.getElementById('btnStartCycle');
      const btnStop  = document.getElementById('btnStop');
      const btnResume = document.getElementById('btnResume');
      const indicator = document.getElementById('statusIndicator');

      if (data.stopped) {
        btnStop.style.display = 'none';
        btnResume.style.display = '';
        btnStart.disabled = true;
        indicator.textContent = '🔴 Stopped';
      } else {
        btnStop.style.display = '';
        btnResume.style.display = 'none';
        indicator.textContent = '🟢 Idle';
      }

      if (data.cycle_running) {
        btnStart.disabled = true;
        indicator.textContent = '⏳ Cycle running (' + data.cycle_processed + '/' + data.cycle_total + ' jobs processed)';
      } else if (!data.stopped) {
        btnStart.disabled = false;
      }
    })
    .catch(() => {});
}

function startCycle() {
  if (!confirm('Start a new scan+apply cycle (5 jobs)?')) return;
  fetch('/api/start-cycle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({limit: 5})
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) { alert(data.error); return; }
      refreshStatus();
    })
    .catch(err => alert('Failed: ' + err));
}

function stopCycle() {
  fetch('/api/stop', { method: 'POST' })
    .then(() => refreshStatus())
    .catch(err => alert('Failed: ' + err));
}

function resumeOps() {
  fetch('/api/resume', { method: 'POST' })
    .then(() => refreshStatus())
    .catch(err => alert('Failed: ' + err));
}

// Poll status every 10s
refreshStatus();
setInterval(refreshStatus, 10000);
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    apps_raw = _load_tracker()
    total = len(apps_raw)

    # Status breakdown
    css_map = {
        "materials_ready": "blue",
        "applied": "green",
        "rejected": "red",
        "interview": "gold",
    }
    status_counts = {}
    for key, (fg, bg, label) in STATUS_COLORS.items():
        count = sum(1 for a in apps_raw if a.get("status") == key)
        status_counts[key] = {"count": count, "label": label, "css": css_map.get(key, "")}

    today_count = sum(1 for a in apps_raw if _is_today(a.get("applied_at", "")))
    week_count = sum(1 for a in apps_raw if _is_this_week(a.get("applied_at", "")))

    # Prepare template data
    apps = []
    for a in apps_raw:
        status = a.get("status", "unknown")
        fg, bg, label = STATUS_COLORS.get(status, ("#666", "#eee", status.replace("_", " ").title()))
        apps.append({
            "company": a.get("company", "—"),
            "position": a.get("position", "—"),
            "location": a.get("location", "—"),
            "badge_fg": fg,
            "badge_bg": bg,
            "badge_label": label,
            "date_fmt": _format_date(a.get("applied_at", "")),
            "resume_rel": _make_relative(a.get("resume_path", "")),
            "cover_letter_rel": _make_relative(a.get("cover_letter_path", "")),
            "jd_rel": _make_relative(a.get("jd_file_path", "")),
            "job_url": a.get("job_url", ""),
        })

    now_str = datetime.now().strftime("%b %d, %Y at %I:%M %p")

    return render_template_string(
        DASHBOARD_HTML,
        apps=apps,
        total=total,
        status_counts=status_counts,
        today_count=today_count,
        week_count=week_count,
        now=now_str,
    )


@app.route("/download/<path:filepath>")
def download(filepath):
    full = ROOT / filepath
    if full.exists() and full.is_file():
        return send_file(str(full), as_attachment=True)
    abort(404)


@app.route("/view/<path:filepath>")
def view(filepath):
    full = ROOT / filepath
    if full.exists() and full.suffix == ".txt":
        text = full.read_text()
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{full.name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 800px; margin: 2rem auto; padding: 0 1.5rem; color: #1a1a2e; }}
a {{ color: #1565c0; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
pre {{ background: #f5f5f5; padding: 1.5rem; border-radius: 12px;
       white-space: pre-wrap; line-height: 1.7; font-size: .9rem;
       box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
h2 {{ margin-bottom: 1rem; }}
</style></head>
<body>
<a href="/">← Back to Dashboard</a>
<h2>📝 {full.name}</h2>
<pre>{text}</pre>
</body></html>"""
    abort(404)


@app.route("/preview/<path:filepath>")
def preview(filepath):
    """Preview .docx files — extract formatted HTML via python-docx."""
    full = ROOT / filepath
    if not full.exists() or full.suffix != ".docx":
        abort(404)

    try:
        from docx import Document
    except ImportError:
        return jsonify({"error": "python-docx not installed"}), 500

    doc = Document(str(full))
    html_parts = []
    in_list = False

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""

        # Build inline HTML from runs
        run_html = ""
        for run in para.runs:
            text = run.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if not text:
                continue
            if run.bold and run.italic:
                text = f"<strong><em>{text}</em></strong>"
            elif run.bold:
                text = f"<strong>{text}</strong>"
            elif run.italic:
                text = f"<em>{text}</em>"
            run_html += text

        if not run_html.strip():
            # Close any open list before adding spacer
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        # Headings
        if style_name.startswith("Heading"):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            level = style_name.replace("Heading", "").strip()
            try:
                level = int(level)
            except ValueError:
                level = 2
            level = min(max(level, 1), 6)
            html_parts.append(f"<h{level}>{run_html}</h{level}>")

        # List items
        elif "List" in style_name or "Bullet" in style_name:
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{run_html}</li>")

        # Regular paragraph
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<p>{run_html}</p>")

    if in_list:
        html_parts.append("</ul>")

    return jsonify({"html": "\n".join(html_parts), "filename": full.name})


# ---------------------------------------------------------------------------
# API Endpoints — Controls
# ---------------------------------------------------------------------------


@app.route("/api/stop", methods=["POST"])
def api_stop():
    STOP_FILE.write_text("stopped")
    return jsonify({"stopped": True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    if STOP_FILE.exists():
        STOP_FILE.unlink()
    return jsonify({"stopped": False})


@app.route("/api/status")
def api_status():
    apps = _load_tracker()
    with _cycle_lock:
        cycle = dict(_cycle_state)
    return jsonify({
        "running": not STOP_FILE.exists(),
        "stopped": STOP_FILE.exists(),
        "total_applications": len(apps),
        "last_cycle": cycle.get("last_cycle"),
        "cycle_running": cycle["running"],
        "cycle_id": cycle["cycle_id"],
        "cycle_total": cycle["total"],
        "cycle_processed": cycle["processed"],
    })


@app.route("/api/start-cycle", methods=["POST"])
def api_start_cycle():
    """Kick off a scan+apply cycle in a background thread."""
    if STOP_FILE.exists():
        return jsonify({"error": "Emergency stop is active"}), 409

    with _cycle_lock:
        if _cycle_state["running"]:
            return jsonify({"error": "A cycle is already running", "cycle_id": _cycle_state["cycle_id"]}), 409

    data = request.get_json(silent=True) or {}
    limit = data.get("limit", 5)
    keyword = data.get("keyword", "compliance manager")
    location = data.get("location", "San Francisco Bay Area")

    cycle_id = str(uuid.uuid4())[:8]

    with _cycle_lock:
        _cycle_state.update({
            "running": True,
            "cycle_id": cycle_id,
            "total": 0,
            "processed": 0,
        })

    thread = threading.Thread(
        target=_run_cycle_background,
        args=(cycle_id, keyword, location, limit),
        daemon=True,
    )
    thread.start()

    return jsonify({"status": "started", "cycle_id": cycle_id})


@app.route("/api/cycle-status")
def api_cycle_status():
    with _cycle_lock:
        return jsonify(dict(_cycle_state))


def _run_cycle_background(cycle_id, keyword, location, limit):
    """Run a scan+apply cycle in a background thread."""
    try:
        # Import here to avoid circular issues
        sys.path.insert(0, str(ROOT))
        from scripts.quick_run import scan_jobs, save_application

        # Scan for jobs
        with _cycle_lock:
            _cycle_state["total"] = 0
            _cycle_state["processed"] = 0

        jobs = scan_jobs(keyword=keyword, location=location, limit=limit)

        with _cycle_lock:
            _cycle_state["total"] = len(jobs)

        for i, job in enumerate(jobs):
            # Check stop file before each application
            if STOP_FILE.exists():
                print(f"🛑 Cycle {cycle_id} halted by stop after {i} jobs")
                break

            try:
                save_application(
                    job=job,
                    tailored_summary=job.get("description", "")[:500],
                    competencies=[],
                    cover_letter_text="",
                    dry_run=True,
                )
            except Exception as e:
                print(f"  ⚠️ Cycle {cycle_id}: Failed on job {i + 1}: {e}")

            with _cycle_lock:
                _cycle_state["processed"] = i + 1

    except Exception as e:
        print(f"❌ Cycle {cycle_id} failed: {e}")
    finally:
        with _cycle_lock:
            _cycle_state["running"] = False
            _cycle_state["last_cycle"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"🚀 Aipply Dashboard: http://localhost:{PORT}")
    app.run(port=PORT, debug=False)
